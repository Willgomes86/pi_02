import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from compras.models import Fornecedor, ItemCompra, PedidoCompra
from comercial.models import Corretor, Empreendimento, Venda
from carteira.models import Recebivel
from planejamento.models import CategoriaPlanejamento, TarefaPlanejada

PT_NUM = re.compile(r"[.\s]")
DEFAULT_CITY = "Não informado"
DEFAULT_FORNECEDOR = "Fornecedor Desconhecido"
DEFAULT_CORRETOR = "Corretor Desconhecido"


def to_decimal_pt(value):
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    s = PT_NUM.sub("", s).replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return None


def clean_str(s):
    return (str(s).strip() if s is not None else "").strip()


def parse_date(value, default: Optional[date] = None) -> Optional[date]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default

    try:
        parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    except Exception:
        return default

    if parsed is None or (isinstance(parsed, float) and pd.isna(parsed)):
        return default

    if isinstance(parsed, pd.Series):
        parsed = parsed.iloc[0]

    if hasattr(parsed, "to_pydatetime"):
        parsed = parsed.to_pydatetime()

    if isinstance(parsed, datetime):
        return parsed.date()
    if isinstance(parsed, date):
        return parsed

    return default


def parse_int(value, default: int = 1) -> int:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default

    try:
        s = str(value).strip()
        if not s or s.lower() == "nan":
            return default
        s = re.sub(r"[^0-9-]", "", s.split(",")[0])
        if not s:
            return default
        return int(s)
    except Exception:
        return default


def _contains_any(text: str, keywords: list[str]) -> bool:
    t = (text or "").casefold()
    return any(k.casefold() in t for k in keywords)


def sniff_header_row(
    df: pd.DataFrame, keywords_groups: list[list[str]], max_scan: int = 15
):
    """
    Procura a 'linha de cabeçalho' nas primeiras N linhas que contenha
    um conjunto suficiente de palavras-chave de algum grupo.
    Retorna (df_reheader, header_index) ou (df, None) se não achou.
    """

    limit = min(max_scan, len(df.index))
    for i in range(limit):
        candidate = [clean_str(c) for c in df.iloc[i].astype(str).tolist()]
        if candidate.count("") >= len(candidate) * 0.5:
            continue
        hits = 0
        for group in keywords_groups:
            if (
                sum(1 for c in candidate if _contains_any(c, group))
                >= max(2, len(group) // 2)
            ):
                hits += 1
        if hits > 0:
            df2 = df.copy()
            df2.columns = candidate
            df2 = df2.iloc[i + 1 :].reset_index(drop=True)
            return normalize_columns(df2), i
    return normalize_columns(df.copy()), None


def best_column_match(columns: list[str], synonyms: list[str]):
    """
    Dada uma lista de nomes de colunas e uma lista de sinônimos,
    retorna o primeiro nome de coluna que contemple algum sinônimo.
    """

    for syn in synonyms:
        for c in columns:
            if syn.casefold() in c.casefold():
                return c
    return None


def looks_like_compras(df: pd.DataFrame) -> bool:
    txt = " ".join(map(str, df.columns))
    if _contains_any(txt, ["Fornecedor", "Insumo", "Descrição", "Produto", "Pedido", "Qtde"]):
        return True
    sample = " ".join(map(lambda x: " ".join(map(str, x)), df.head(5).values.tolist()))
    return _contains_any(sample, ["Fornecedor", "Pedido", "Insumo", "Produto", "Valor"])


def looks_like_comercial(df: pd.DataFrame) -> bool:
    txt = " ".join(map(str, df.columns))
    if _contains_any(txt, ["Vendas", "Empreendimento", "Cliente", "Corretor", "Contrato", "Valor"]):
        return True
    sample = " ".join(map(lambda x: " ".join(map(str, x)), df.head(5).values.tolist()))
    return _contains_any(sample, ["Empreendimento", "Cliente", "Corretor", "Venda"])


def looks_like_carteira(df: pd.DataFrame) -> bool:
    txt = " ".join(map(str, df.columns))
    if _contains_any(txt, ["Carteira", "Parcela", "Vencimento", "Pago", "Status"]):
        return True
    sample = " ".join(map(lambda x: " ".join(map(str, x)), df.head(5).values.tolist()))
    return _contains_any(sample, ["Parcela", "Vencimento", "Recebível"])


def looks_like_planejamento(df: pd.DataFrame) -> bool:
    txt = " ".join(map(str, df.columns))
    if _contains_any(txt, ["Planejamento", "Categoria", "Custo", "Início", "Fim"]):
        return True
    sample = " ".join(map(lambda x: " ".join(map(str, x)), df.head(5).values.tolist()))
    return _contains_any(sample, ["Categoria", "Custo", "Tarefa", "Planejamento"])


def first_non_empty_header(df: pd.DataFrame) -> pd.DataFrame:
    for i in range(min(10, len(df.index))):
        row = list(df.iloc[i].astype(str))
        non_empty = [x for x in row if x and x != "nan"]
        if len(non_empty) >= 3:
            df2 = df.copy()
            df2.columns = [clean_str(col) for col in row]
            df2 = df2.iloc[i + 1 :].reset_index(drop=True)
            return df2
    return df


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [re.sub(r"\s+", " ", clean_str(col)) for col in df.columns]
    return df


def parse_emp_name(df: pd.DataFrame) -> str:
    for i in range(min(5, len(df))):
        row = df.iloc[i].tolist()
        for value in row:
            name = clean_str(value)
            if name and name.lower() not in {"empresa", "fornecedor"} and len(name) > 2:
                return name
    return ""


def get_or_create_empreendimento(nome: str) -> Empreendimento:
    nome = nome or "Empreendimento Desconhecido"
    empreendimento, _ = Empreendimento.objects.get_or_create(
        nome=nome, defaults={"cidade": DEFAULT_CITY}
    )
    return empreendimento


def get_or_create_corretor(nome: str) -> Corretor:
    nome = nome or DEFAULT_CORRETOR
    corretor, _ = Corretor.objects.get_or_create(
        nome=nome,
        defaults={"email": "", "telefone": ""},
    )
    return corretor


def get_or_create_fornecedor(nome: str) -> Fornecedor:
    nome = nome or DEFAULT_FORNECEDOR
    fornecedor, _ = Fornecedor.objects.get_or_create(nome=nome)
    return fornecedor


def normalize_recebivel_status(value: str) -> str:
    status = clean_str(value).lower()
    if "pago" in status:
        return Recebivel.Status.PAGO
    if "atras" in status:
        return Recebivel.Status.ATRASADO
    if "reneg" in status:
        return Recebivel.Status.RENEGOCIADO
    return Recebivel.Status.ABERTO


@transaction.atomic
def import_compras(df: pd.DataFrame, filename: str, debug=False):
    df, hdr = sniff_header_row(
        df,
        keywords_groups=[
            ["Fornecedor", "Pedido", "Insumo", "Descrição", "Produto"],
            ["Qtde", "Quantidade", "Valor Unit", "Valor Unitário", "Preço"],
        ],
    )
    columns = list(df.columns)

    col_fornecedor = best_column_match(columns, ["Fornecedor", "Fornecedor Nome"])
    col_insumo = best_column_match(columns, ["Insumo", "Descrição", "Produto", "Item"])
    col_qtde = best_column_match(columns, ["Qtde", "Quantidade"])
    col_val_unit = best_column_match(
        columns, ["Valor Unitário", "Valor Unit", "Preço Unit", "Preço"]
    )
    col_total = best_column_match(columns, ["Total", "Valor Total"])

    if debug:
        print(f"[DEBUG compras] header_at={hdr} cols={columns}")
        print(
            "[DEBUG compras] fornecedor={} insumo={} qtde={} unit={} total={}".format(
                col_fornecedor, col_insumo, col_qtde, col_val_unit, col_total
            )
        )

    if not col_insumo:
        return

    emp_nome = parse_emp_name(df)
    emp, _ = Empreendimento.objects.get_or_create(
        nome=emp_nome or "Empreendimento Desconhecido", defaults={"cidade": ""}
    )

    pedido = PedidoCompra.objects.create(
        fornecedor=None,
        empreendimento=emp,
        numero_pedido=clean_str(filename),
        observacoes="Importado automaticamente de relatório Vinit (compras).",
    )

    for _, row in df.iterrows():
        desc = clean_str(row.get(col_insumo))
        if not desc or desc.lower() in {
            "nan",
            "descricao",
            "descrição",
            "produto",
            "insumo",
        }:
            continue

        fornecedor = None
        fornecedor_nome = clean_str(row.get(col_fornecedor)) if col_fornecedor else ""
        if fornecedor_nome and fornecedor_nome.lower() not in {"fornecedor"}:
            fornecedor, _ = Fornecedor.objects.get_or_create(nome=fornecedor_nome)

        qtde_raw = row.get(col_qtde) if col_qtde else 1
        try:
            qtde = (
                int(str(qtde_raw).split(",")[0])
                if qtde_raw not in (None, "", "nan")
                else 1
            )
        except Exception:
            qtde = 1

        custo_unit = to_decimal_pt(row.get(col_val_unit)) if col_val_unit else None

        ItemCompra.objects.create(
            pedido=pedido,
            descricao=desc,
            quantidade=qtde,
            custo_unitario=custo_unit or Decimal("0"),
        )

        if fornecedor and pedido.fornecedor is None:
            pedido.fornecedor = fornecedor
            pedido.save(update_fields=["fornecedor"])


@transaction.atomic
def import_comercial(df: pd.DataFrame, filename: str, debug=False):
    df, hdr = sniff_header_row(
        df,
        keywords_groups=[
            ["Empreendimento", "Cliente", "Corretor"],
            ["Data", "Venda", "Contrato", "Valor", "Unidades", "Qtde"],
        ],
    )
    columns = list(df.columns)

    col_emp = best_column_match(columns, ["Empreendimento", "Obra", "Projeto"])
    col_cliente = best_column_match(columns, ["Cliente", "Comprador", "Proponente"])
    col_corretor = best_column_match(columns, ["Corretor", "Vendedor"])
    col_valor = best_column_match(columns, ["Valor Contrato", "Valor", "Total"])
    col_data = best_column_match(columns, ["Data Venda", "Data", "Emissão"])
    col_unid = best_column_match(columns, ["Unidades", "Qtde", "Quantidade"])

    if debug:
        print(
            f"[DEBUG comercial] header_at={hdr} cols={columns}"
        )
        print(
            "[DEBUG comercial] emp={} cliente={} corretor={} valor={} data={} unidades={}".format(
                col_emp, col_cliente, col_corretor, col_valor, col_data, col_unid
            )
        )

    if not (col_emp or col_cliente):
        return

    for _, row in df.iterrows():
        emp_nome = clean_str(row.get(col_emp)) if col_emp else parse_emp_name(df)
        if not emp_nome or emp_nome.lower() in {"empreendimento"}:
            continue

        emp, _ = Empreendimento.objects.get_or_create(
            nome=emp_nome, defaults={"cidade": ""}
        )

        cliente = clean_str(row.get(col_cliente)) if col_cliente else "Cliente"
        corretor_nome = clean_str(row.get(col_corretor)) if col_corretor else ""
        valor = to_decimal_pt(row.get(col_valor)) if col_valor else None
        data = row.get(col_data) if col_data else None

        unidades_raw = row.get(col_unid) if col_unid else 1
        try:
            unidades = (
                int(str(unidades_raw).split(",")[0])
                if unidades_raw not in (None, "", "nan")
                else 1
            )
        except Exception:
            unidades = 1

        corretor = None
        if corretor_nome and corretor_nome.lower() not in {"corretor", "vendedor"}:
            corretor, _ = Corretor.objects.get_or_create(nome=corretor_nome)

        Venda.objects.create(
            empreendimento=emp,
            cliente_nome=cliente or "Cliente",
            corretor=corretor,
            data_venda=data,
            unidades_vendidas=unidades,
            valor_contrato=valor or Decimal("0"),
        )


@transaction.atomic
def import_carteira(df: pd.DataFrame, filename: str) -> None:
    df = first_non_empty_header(df)
    df = normalize_columns(df)

    col_emp = next((c for c in df.columns if "Empreendimento" in c), None)
    col_venc = next((c for c in df.columns if "Vencimento" in c), None)
    col_valor = next(
        (
            c
            for c in df.columns
            if "Valor" in c and ("Parcela" in c or c.strip() == "Valor")
        ),
        None,
    )
    col_pago = next((c for c in df.columns if "Pago" in c), None)
    col_status = next((c for c in df.columns if "Status" in c), None)
    col_corretor = next((c for c in df.columns if "Corretor" in c), None)
    col_cliente = next((c for c in df.columns if "Cliente" in c or "Comprador" in c), None)

    for _, row in df.iterrows():
        emp_nome = clean_str(row.get(col_emp)) if col_emp else parse_emp_name(df)
        if not emp_nome:
            continue
        empreendimento = get_or_create_empreendimento(emp_nome)

        cliente_nome = clean_str(row.get(col_cliente)) if col_cliente else "Cliente"
        corretor_nome = clean_str(row.get(col_corretor)) if col_corretor else DEFAULT_CORRETOR
        corretor = get_or_create_corretor(corretor_nome)

        valor_parcela = to_decimal_pt(row.get(col_valor)) if col_valor else None
        data_vencimento = (
            parse_date(row.get(col_venc), default=timezone.localdate())
            if col_venc
            else timezone.localdate()
        )

        venda, _ = Venda.objects.get_or_create(
            corretor=corretor,
            empreendimento=empreendimento,
            cliente_nome=cliente_nome or "Cliente",
            data_venda=timezone.localdate(),
            defaults={
                "unidades_vendidas": 1,
                "valor_contrato": valor_parcela or Decimal("0"),
            },
        )

        valor_pago = to_decimal_pt(row.get(col_pago)) if col_pago else None
        status = normalize_recebivel_status(row.get(col_status) if col_status else "")

        recebivel, created = Recebivel.objects.get_or_create(
            venda=venda,
            data_vencimento=data_vencimento,
            defaults={
                "valor": valor_parcela or Decimal("0"),
                "valor_pago": valor_pago or Decimal("0"),
                "status": status,
            },
        )

        if not created:
            updates = []
            if valor_parcela is not None and recebivel.valor != valor_parcela:
                recebivel.valor = valor_parcela
                updates.append("valor")
            if valor_pago is not None and recebivel.valor_pago != valor_pago:
                recebivel.valor_pago = valor_pago
                updates.append("valor_pago")
            if status and recebivel.status != status:
                recebivel.status = status
                updates.append("status")
            if updates:
                recebivel.save(update_fields=updates)


@transaction.atomic
def import_planejamento(df: pd.DataFrame, filename: str) -> None:
    df = first_non_empty_header(df)
    df = normalize_columns(df)

    col_emp = next((c for c in df.columns if "Empreendimento" in c), None)
    col_cat = next((c for c in df.columns if "Categoria" in c), None)
    col_nome = next((c for c in df.columns if "Descrição" in c or "Nome" in c), None)
    col_inicio = next((c for c in df.columns if "Início" in c or "Inicio" in c), None)
    col_fim_prev = next((c for c in df.columns if "Fim" in c and "prev" in c.lower()), None)
    col_fim_real = next((c for c in df.columns if "Fim" in c and "real" in c.lower()), None)
    col_custo = next((c for c in df.columns if "Custo" in c and "Real" not in c), None)
    col_custo_real = next((c for c in df.columns if "Custo" in c and "Real" in c), None)

    for _, row in df.iterrows():
        emp_nome = clean_str(row.get(col_emp)) if col_emp else parse_emp_name(df)
        if not emp_nome:
            continue
        empreendimento = get_or_create_empreendimento(emp_nome)

        cat_nome = clean_str(row.get(col_cat)) if col_cat else "Geral"
        categoria, _ = CategoriaPlanejamento.objects.get_or_create(
            nome=cat_nome or "Geral"
        )

        nome = clean_str(row.get(col_nome)) if col_nome else "Tarefa"
        data_inicio = (
            parse_date(row.get(col_inicio), default=timezone.localdate())
            if col_inicio
            else timezone.localdate()
        )
        data_fim_prevista = (
            parse_date(row.get(col_fim_prev), default=data_inicio)
            if col_fim_prev
            else data_inicio
        )
        data_fim_real = (
            parse_date(row.get(col_fim_real)) if col_fim_real else None
        )
        custo_planejado = to_decimal_pt(row.get(col_custo)) if col_custo else None
        custo_real = to_decimal_pt(row.get(col_custo_real)) if col_custo_real else None

        tarefa, created = TarefaPlanejada.objects.get_or_create(
            empreendimento=empreendimento,
            nome=nome or "Tarefa",
            data_inicio_prevista=data_inicio,
            defaults={
                "categoria": categoria,
                "data_fim_prevista": data_fim_prevista,
                "data_fim_real": data_fim_real,
                "custo_planejado": custo_planejado or Decimal("0"),
                "custo_real": custo_real or Decimal("0"),
            },
        )

        if not created:
            updates = []
            if tarefa.categoria_id != categoria.id:
                tarefa.categoria = categoria
                updates.append("categoria")
            if data_fim_prevista and tarefa.data_fim_prevista != data_fim_prevista:
                tarefa.data_fim_prevista = data_fim_prevista
                updates.append("data_fim_prevista")
            if data_fim_real and tarefa.data_fim_real != data_fim_real:
                tarefa.data_fim_real = data_fim_real
                updates.append("data_fim_real")
            if custo_planejado is not None and tarefa.custo_planejado != custo_planejado:
                tarefa.custo_planejado = custo_planejado
                updates.append("custo_planejado")
            if custo_real is not None and tarefa.custo_real != custo_real:
                tarefa.custo_real = custo_real
                updates.append("custo_real")
            if updates:
                tarefa.save(update_fields=updates)


class Command(BaseCommand):
    help = "Importa relatórios Vinit (.xlsx) para os modelos do sistema."

    def add_arguments(self, parser):
        parser.add_argument("--path", required=True, help="Pasta contendo os .xlsx")
        parser.add_argument(
            "--force",
            choices=["compras", "comercial", "carteira", "planejamento"],
            help="Força o tipo de importação",
        )
        parser.add_argument(
            "--debug",
            action="store_true",
            help="Mostra colunas detectadas e salva amostras",
        )

    def handle(self, *args, **opts):
        path = Path(opts["path"]).expanduser().resolve()
        force = opts.get("force")
        debug = bool(opts.get("debug"))

        if not path.exists() or not path.is_dir():
            raise CommandError(f"Pasta inválida: {path}")

        files = list(path.glob("*.xlsx"))
        if not files:
            self.stdout.write(self.style.WARNING("Nenhum .xlsx encontrado."))
            return

        out_debug = path / "_debug_import"
        if debug:
            out_debug.mkdir(exist_ok=True)

        imported = 0
        for f in files:
            try:
                xls = pd.ExcelFile(f)
            except Exception as e:
                self.stderr.write(f"[ERRO] Abrindo {f.name}: {e}")
                continue

            for sheet in xls.sheet_names:
                try:
                    df = xls.parse(sheet)
                except Exception as e:
                    self.stderr.write(f"[ERRO] Lendo aba {sheet} em {f.name}: {e}")
                    continue

                if df.empty or df.shape[1] < 2:
                    continue

                if debug:
                    try:
                        df.head(10).to_csv(
                            out_debug
                            / f"{f.stem}__{sheet}__preview.csv",
                            index=False,
                            encoding="utf-8-sig",
                        )
                    except Exception:
                        pass

                try:
                    if force == "compras" or (not force and looks_like_compras(df)):
                        import_compras(df, f.name, debug=debug)
                        self.stdout.write(
                            self.style.SUCCESS(f"[OK] Compras <- {f.name}:{sheet}")
                        )
                        imported += 1
                    elif force == "carteira" or (not force and looks_like_carteira(df)):
                        import_carteira(df, f.name)
                        self.stdout.write(
                            self.style.SUCCESS(f"[OK] Carteira <- {f.name}:{sheet}")
                        )
                        imported += 1
                    elif force == "comercial" or (not force and looks_like_comercial(df)):
                        import_comercial(df, f.name, debug=debug)
                        self.stdout.write(
                            self.style.SUCCESS(f"[OK] Comercial <- {f.name}:{sheet}")
                        )
                        imported += 1
                    elif force == "planejamento" or (
                        not force and looks_like_planejamento(df)
                    ):
                        import_planejamento(df, f.name)
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"[OK] Planejamento <- {f.name}:{sheet}"
                            )
                        )
                        imported += 1
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"[?] Ignorado (não reconhecido): {f.name}:{sheet}"
                            )
                        )
                except Exception as e:
                    self.stderr.write(f"[ERRO] Processando {f.name}:{sheet}: {e}")

        self.stdout.write(
            self.style.SUCCESS(f"Finalizado. Abas importadas: {imported}")
        )

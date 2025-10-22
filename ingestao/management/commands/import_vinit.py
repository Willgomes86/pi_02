import math
import re
from datetime import datetime, date
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


def safe_decimal(value, default="0"):
    """
    Converte qualquer coisa (incluindo NaN/None/'') para Decimal seguro.
    """
    if value is None:
        return Decimal(default)
    # pandas NaN (float) ou string 'NaN'
    try:
        if isinstance(value, float) and math.isnan(value):
            return Decimal(default)
    except Exception:
        pass
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return Decimal(default)
    d = to_decimal_pt(s)
    return d if d is not None else Decimal(default)


def normalize_date(value):
    """
    Aceita pandas.Timestamp, datetime, date, string variada, NaT/NaN/None.
    Retorna date ou None.
    """
    if value is None:
        return None
    # pandas Timestamp
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime().date()
        except Exception:
            try:
                return value.date()
            except Exception:
                return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # strings
    s = str(value).strip()
    if not s or s.lower() in {"nan", "nat", "none", "null"}:
        return None
    # tenta vários formatos
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    # último recurso: pandas.to_datetime
    try:
        import pandas as pd

        dt = pd.to_datetime(s, errors="coerce")
        if pd.isna(dt):
            return None
        return dt.to_pydatetime().date()
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
            ["Qtde", "Quantidade", "Valor Unit", "Valor Unitário", "Preço", "Total"],
        ],
    )
    df = normalize_columns(df)
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
            f"[DEBUG compras] fornecedor={col_fornecedor} insumo={col_insumo} qtde={col_qtde} "
            f"unit={col_val_unit} total={col_total}"
        )

    if not col_insumo:
        return

    emp_nome = parse_emp_name(df)
    emp, _ = Empreendimento.objects.get_or_create(
        nome=emp_nome or "Empreendimento Desconhecido", defaults={"cidade": ""}
    )

    # cria/obtém fornecedor default (caso o model exija)
    fornecedor_default, _ = Fornecedor.objects.get_or_create(nome="Fornecedor Desconhecido")

    # cria um PedidoCompra "sintético" com campos que EXISTEM no model
    # descobre campos do model dinamicamente
    pedido_fields = {f.name for f in PedidoCompra._meta.get_fields() if hasattr(f, "attname")}
    pedido_kwargs = {}

    # setamos apenas se o campo existir:
    if "empreendimento" in pedido_fields:
        pedido_kwargs["empreendimento"] = emp
    if "fornecedor" in pedido_fields:
        pedido_kwargs["fornecedor"] = fornecedor_default
    # se tiver "data" no model, podemos pôr hoje (opcional):
    if "data" in pedido_fields:
        pedido_kwargs["data"] = date.today()

    pedido = PedidoCompra.objects.create(**pedido_kwargs)

    for _, row in df.iterrows():
        desc = clean_str(row.get(col_insumo))
        if not desc or desc.lower() in {"nan", "descricao", "descrição", "produto", "insumo"}:
            continue

        fornecedor = None
        fornecedor_nome = clean_str(row.get(col_fornecedor)) if col_fornecedor else ""
        if fornecedor_nome and fornecedor_nome.lower() not in {"fornecedor"}:
            fornecedor, _ = Fornecedor.objects.get_or_create(nome=fornecedor_nome)

        qtde_raw = row.get(col_qtde) if col_qtde else 1
        try:
            qtde = int(str(qtde_raw).split(",")[0]) if qtde_raw not in (None, "", "nan") else 1
        except Exception:
            qtde = 1

        custo_unit = safe_decimal(row.get(col_val_unit))

        item_kwargs = {
            "pedido": pedido,
            "descricao": desc,
            "quantidade": qtde,
            "custo_unitario": custo_unit,
        }

        # só manda campos que existem no model ItemCompra
        item_fields = {f.name for f in ItemCompra._meta.get_fields() if hasattr(f, "attname")}
        item_kwargs = {k: v for k, v in item_kwargs.items() if k in item_fields}

        ItemCompra.objects.create(**item_kwargs)

        # se o model do PedidoCompra tiver fornecedor e ele ainda for "desconhecido", atualiza com fornecedor real
        if fornecedor and "fornecedor" in pedido_fields and pedido.fornecedor_id == fornecedor_default.id:
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
    df = normalize_columns(df)
    columns = list(df.columns)

    col_emp = best_column_match(columns, ["Empreendimento", "Obra", "Projeto"])
    col_cliente = best_column_match(columns, ["Cliente", "Comprador", "Proponente"])
    col_corretor = best_column_match(columns, ["Corretor", "Vendedor"])
    col_valor = best_column_match(columns, ["Valor Contrato", "Valor", "Total"])
    col_data = best_column_match(columns, ["Data Venda", "Data", "Emissão"])
    col_unid = best_column_match(columns, ["Unidades", "Qtde", "Quantidade"])

    if debug:
        print(f"[DEBUG comercial] header_at={hdr} cols={columns}")
        print(
            f"[DEBUG comercial] emp={col_emp} cliente={col_cliente} corretor={col_corretor} "
            f"valor={col_valor} data={col_data} unidades={col_unid}"
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
        valor = safe_decimal(row.get(col_valor))
        data = normalize_date(row.get(col_data))

        unidades_raw = row.get(col_unid) if col_unid else 1
        try:
            unidades = int(str(unidades_raw).split(",")[0]) if unidades_raw not in (None, "", "nan") else 1
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
            valor_contrato=valor,
        )


@transaction.atomic
def import_carteira(df: pd.DataFrame, filename: str):
    df, _ = sniff_header_row(
        df,
        keywords_groups=[
            ["Empreendimento", "Cliente", "Contrato"],
            ["Parcela", "Nº", "Numero", "Vencimento", "Valor", "Pago", "Status"],
        ],
    )
    df = normalize_columns(df)

    col_emp = best_column_match(list(df.columns), ["Empreendimento", "Obra", "Projeto"])
    col_parcela = best_column_match(list(df.columns), ["Parcela", "Nº", "Numero"])
    col_venc = best_column_match(list(df.columns), ["Vencimento", "Dt Venc", "Data Vencimento"])
    col_valor = best_column_match(list(df.columns), ["Valor Parcela", "Valor", "Total"])
    col_pago = best_column_match(list(df.columns), ["Pago", "Valor Pago"])
    col_status = best_column_match(list(df.columns), ["Status", "Situação"])

    for _, row in df.iterrows():
        emp_nome = clean_str(row.get(col_emp)) if col_emp else parse_emp_name(df)
        if not emp_nome:
            continue
        emp, _ = Empreendimento.objects.get_or_create(nome=emp_nome, defaults={"cidade": ""})

        valor_raw = row.get(col_valor) if col_valor else None

        # cria venda "sintética" apenas para vincular parcela (se não houver ID real)
        venda = Venda.objects.create(
            empreendimento=emp,
            cliente_nome="Cliente",
            unidades_vendidas=1,
            valor_contrato=safe_decimal(valor_raw)
        )

        Recebivel.objects.create(
            venda=venda,
            numero_parcela=clean_str(row.get(col_parcela)) if col_parcela else "",
            data_vencimento=normalize_date(row.get(col_venc)),
            valor=safe_decimal(valor_raw),
            valor_pago=safe_decimal(row.get(col_pago)) if col_pago else Decimal("0"),
            status=(clean_str(row.get(col_status)) or "aberto").lower() if col_status else "aberto",
        )


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
                    df = xls.parse(sheet, header=None)
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
                    fname = f.name.casefold()

                    # heurística de tipo usando o NOME do arquivo:
                    forced_by_name = None
                    if "comercial" in fname:
                        forced_by_name = "comercial"
                    elif "compras" in fname:
                        forced_by_name = "compras"
                    elif "carteira" in fname:
                        forced_by_name = "carteira"
                    elif "planejamento" in fname:
                        forced_by_name = "planejamento"

                    tipo = force or forced_by_name
                    if not tipo:
                        # fallback pelas heurísticas de conteúdo, se o nome não ajudou
                        if looks_like_compras(df):
                            tipo = "compras"
                        elif looks_like_carteira(df):
                            tipo = "carteira"
                        elif looks_like_comercial(df):
                            tipo = "comercial"
                        elif looks_like_planejamento(df):
                            tipo = "planejamento"

                    if tipo == "compras":
                        import_compras(df, f.name, debug=debug)
                        self.stdout.write(
                            self.style.SUCCESS(f"[OK] Compras <- {f.name}:{sheet}")
                        )
                        imported += 1

                    elif tipo == "carteira":
                        import_carteira(df, f.name)
                        self.stdout.write(
                            self.style.SUCCESS(f"[OK] Carteira <- {f.name}:{sheet}")
                        )
                        imported += 1

                    elif tipo == "comercial":
                        import_comercial(df, f.name, debug=debug)
                        self.stdout.write(
                            self.style.SUCCESS(f"[OK] Comercial <- {f.name}:{sheet}")
                        )
                        imported += 1

                    elif tipo == "planejamento":
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

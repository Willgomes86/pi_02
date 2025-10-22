import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional, Set

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
    """
    Converte números pt-BR: "1.234.567,89" -> Decimal("1234567.89")
    Aceita vazios/NaN.
    """

    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except Exception:
            return None

    s = str(value).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    s = PT_NUM.sub("", s).replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return None


def clean_str(value) -> str:
    return (str(value).strip() if value is not None else "").strip()


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


def looks_like_compras(df: pd.DataFrame) -> bool:
    cols = " ".join(map(str, df.columns))
    return ("Fornecedor" in cols and "Insumo" in cols) or ("Pedidos" in cols and "Compras" in cols)


def looks_like_comercial(df: pd.DataFrame) -> bool:
    cols = " ".join(map(str, df.columns))
    return "Vendas" in cols or "Empreendimento" in cols or "Cliente" in cols


def looks_like_carteira(df: pd.DataFrame) -> bool:
    cols = " ".join(map(str, df.columns))
    return ("Carteira" in cols) or ("Vencimento" in cols and "Parcela" in cols)


def looks_like_planejamento(df: pd.DataFrame) -> bool:
    cols = " ".join(map(str, df.columns))
    return ("Planejamento" in cols) or ("Categoria" in cols and "Custo" in cols)


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
def import_compras(df: pd.DataFrame, filename: str) -> None:
    df = first_non_empty_header(df)
    df = normalize_columns(df)

    col_fornecedor = next((c for c in df.columns if "Fornecedor" in c), None)
    col_insumo = next((c for c in df.columns if "Insumo" in c or "Descrição" in c), None)
    col_qtde = next((c for c in df.columns if "Qtde" in c or "Quantidade" in c), None)
    col_valor_unit = next(
        (
            c
            for c in df.columns
            if "Valor Unit" in c or "Valor Unitário" in c or "Preço" in c
        ),
        None,
    )
    col_total = next(
        (
            c
            for c in df.columns
            if c.strip().lower() in {"total", "valor total"} or "Total" in c
        ),
        None,
    )
    col_data = next(
        (
            c
            for c in df.columns
            if "Data" in c and ("Pedido" in c or c.strip().lower() == "data")
        ),
        None,
    )

    if col_insumo is None:
        return

    emp_nome = parse_emp_name(df)
    empreendimento = get_or_create_empreendimento(emp_nome)

    pedidos_atualizados: Set[int] = set()

    for _, row in df.iterrows():
        descricao = clean_str(row.get(col_insumo))
        if not descricao:
            continue

        fornecedor_nome = clean_str(row.get(col_fornecedor)) if col_fornecedor else ""
        fornecedor = get_or_create_fornecedor(fornecedor_nome)

        quantidade = parse_int(row.get(col_qtde)) if col_qtde else 1
        valor_unitario = to_decimal_pt(row.get(col_valor_unit)) if col_valor_unit else None
        valor_total = to_decimal_pt(row.get(col_total)) if col_total else None

        if valor_total is None and valor_unitario is not None:
            valor_total = (valor_unitario or Decimal("0")) * Decimal(max(quantidade, 1))
        elif valor_total is not None and valor_unitario is None and quantidade:
            try:
                valor_unitario = (valor_total or Decimal("0")) / Decimal(max(quantidade, 1))
            except Exception:
                valor_unitario = None

        data_pedido = parse_date(row.get(col_data), default=timezone.localdate()) if col_data else timezone.localdate()

        pedido, _ = PedidoCompra.objects.get_or_create(
            empreendimento=empreendimento,
            fornecedor=fornecedor,
            data_pedido=data_pedido,
            categoria="outros",
            defaults={"valor_total": Decimal("0")},
        )

        item, created = ItemCompra.objects.get_or_create(
            pedido=pedido,
            descricao=descricao,
            defaults={
                "quantidade": max(quantidade, 1),
                "custo_unitario": valor_unitario or Decimal("0"),
            },
        )

        if not created:
            updated = False
            if quantidade and item.quantidade != max(quantidade, 1):
                item.quantidade = max(quantidade, 1)
                updated = True
            if valor_unitario is not None and item.custo_unitario != valor_unitario:
                item.custo_unitario = valor_unitario
                updated = True
            if updated:
                item.save(update_fields=["quantidade", "custo_unitario"])

        pedidos_atualizados.add(pedido.pk)

    for pedido_id in pedidos_atualizados:
        pedido = PedidoCompra.objects.get(pk=pedido_id)
        total = sum(
            (item.custo_unitario or Decimal("0")) * Decimal(item.quantidade or 0)
            for item in pedido.itens.all()
        )
        pedido.valor_total = total
        pedido.save(update_fields=["valor_total"])


@transaction.atomic
def import_comercial(df: pd.DataFrame, filename: str) -> None:
    df = first_non_empty_header(df)
    df = normalize_columns(df)

    col_emp = next((c for c in df.columns if "Empreendimento" in c), None)
    col_cliente = next((c for c in df.columns if "Cliente" in c), None)
    col_corretor = next((c for c in df.columns if "Corretor" in c), None)
    col_valor = next(
        (
            c
            for c in df.columns
            if ("Valor" in c and "Contrato" in c) or c.strip() == "Valor"
        ),
        None,
    )
    col_data = next((c for c in df.columns if "Data" in c), None)
    col_unidades = next(
        (c for c in df.columns if "Unidades" in c or "Qtde" in c),
        None,
    )

    for _, row in df.iterrows():
        emp_nome = clean_str(row.get(col_emp)) if col_emp else parse_emp_name(df)
        if not emp_nome:
            continue
        empreendimento = get_or_create_empreendimento(emp_nome)

        cliente_nome = clean_str(row.get(col_cliente)) if col_cliente else "Cliente"
        corretor_nome = clean_str(row.get(col_corretor)) if col_corretor else DEFAULT_CORRETOR
        corretor = get_or_create_corretor(corretor_nome)

        valor_contrato = to_decimal_pt(row.get(col_valor)) if col_valor else None
        data_venda = parse_date(row.get(col_data), default=timezone.localdate()) if col_data else timezone.localdate()
        unidades = parse_int(row.get(col_unidades)) if col_unidades else 1

        venda, created = Venda.objects.get_or_create(
            corretor=corretor,
            empreendimento=empreendimento,
            cliente_nome=cliente_nome or "Cliente",
            data_venda=data_venda,
            defaults={
                "unidades_vendidas": max(unidades, 1),
                "valor_contrato": valor_contrato or Decimal("0"),
            },
        )

        if not created:
            updated_fields = []
            unidades_normalizadas = max(unidades, 1)
            if venda.unidades_vendidas != unidades_normalizadas:
                venda.unidades_vendidas = unidades_normalizadas
                updated_fields.append("unidades_vendidas")
            if valor_contrato is not None and venda.valor_contrato != valor_contrato:
                venda.valor_contrato = valor_contrato
                updated_fields.append("valor_contrato")
            if updated_fields:
                venda.save(update_fields=updated_fields)


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

    def handle(self, *args, **opts):
        path = Path(opts["path"]).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise CommandError(f"Pasta inválida: {path}")

        files = list(path.glob("*.xlsx"))
        if not files:
            self.stdout.write(self.style.WARNING("Nenhum .xlsx encontrado."))
            return

        imported = 0
        for f in files:
            try:
                xls = pd.ExcelFile(f)
            except Exception as exc:
                self.stderr.write(f"[ERRO] Abrindo {f.name}: {exc}")
                continue

            for sheet in xls.sheet_names:
                try:
                    df = xls.parse(sheet)
                except Exception as exc:
                    self.stderr.write(f"[ERRO] Lendo aba {sheet} em {f.name}: {exc}")
                    continue

                if df.empty or df.shape[1] < 2:
                    continue

                try:
                    if looks_like_compras(df):
                        import_compras(df, f.name)
                        self.stdout.write(
                            self.style.SUCCESS(f"[OK] Compras <- {f.name}:{sheet}")
                        )
                        imported += 1
                    elif looks_like_carteira(df):
                        import_carteira(df, f.name)
                        self.stdout.write(
                            self.style.SUCCESS(f"[OK] Carteira <- {f.name}:{sheet}")
                        )
                        imported += 1
                    elif looks_like_comercial(df):
                        import_comercial(df, f.name)
                        self.stdout.write(
                            self.style.SUCCESS(f"[OK] Comercial <- {f.name}:{sheet}")
                        )
                        imported += 1
                    elif looks_like_planejamento(df):
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
                except Exception as exc:
                    self.stderr.write(f"[ERRO] Processando {f.name}:{sheet}: {exc}")

        self.stdout.write(
            self.style.SUCCESS(f"Finalizado. Abas importadas: {imported}")
        )

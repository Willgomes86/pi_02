from collections import OrderedDict
from decimal import Decimal
import json

from django.contrib.auth.decorators import login_required
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Avg, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.shortcuts import render
from django.utils import timezone

from carteira.models import Recebivel
from comercial.models import Empreendimento, Venda
from compras.models import PedidoCompra
from planejamento.models import TarefaPlanejada


def _format_month_label(date_obj):
    month_names = [
        "Jan",
        "Fev",
        "Mar",
        "Abr",
        "Mai",
        "Jun",
        "Jul",
        "Ago",
        "Set",
        "Out",
        "Nov",
        "Dez",
    ]
    return f"{month_names[date_obj.month - 1]}/{date_obj.year}"


def _group_periods(data, key_func, label_func):
    grouped = OrderedDict()
    for item in data:
        period = item["period"]
        if period is None:
            continue
        if hasattr(period, "date"):
            period = period.date()
        key = key_func(period)
        group = grouped.setdefault(
            key,
            {"label": label_func(period), "valor": Decimal("0"), "unidades": 0},
        )
        group["valor"] += item["valor"]
        group["unidades"] += item["unidades"]
    return list(grouped.values())


@login_required
def dashboard_overview(request):
    # Comercial KPIs
    vendas_stats = Venda.objects.aggregate(
        total_valor=Coalesce(Sum("valor_contrato"), Decimal("0")),
        total_unidades=Coalesce(Sum("unidades_vendidas"), 0),
        ticket_medio=Coalesce(Avg("valor_contrato"), Decimal("0")),
    )

    total_vendas = vendas_stats["total_valor"]
    total_unidades = vendas_stats["total_unidades"]
    ticket_medio_por_unidade = (
        (total_vendas / total_unidades) if total_unidades else Decimal("0")
    )

    vendas_por_corretor = (
        Venda.objects.values("corretor__nome", "empreendimento__nome")
        .annotate(
            total_valor=Coalesce(Sum("valor_contrato"), Decimal("0")),
            total_unidades=Coalesce(Sum("unidades_vendidas"), 0),
        )
        .order_by("-total_valor")
    )

    vendas_por_periodo = list(
        Venda.objects.annotate(period=TruncMonth("data_venda"))
        .values("period")
        .order_by("period")
        .annotate(
            valor=Coalesce(Sum("valor_contrato"), Decimal("0")),
            unidades=Coalesce(Sum("unidades_vendidas"), 0),
        )
    )

    vendas_mensal = [
        {
            "label": _format_month_label(period["period"].date() if hasattr(period["period"], "date") else period["period"]),
            "valor": period["valor"],
            "unidades": period["unidades"],
        }
        for period in vendas_por_periodo
        if period["period"]
    ]

    vendas_bimestral = _group_periods(
        vendas_por_periodo,
        key_func=lambda dt: (dt.year, (dt.month - 1) // 2 + 1),
        label_func=lambda dt: f"{((dt.month - 1) // 2 + 1)}º Bim/{dt.year}",
    )
    vendas_semestral = _group_periods(
        vendas_por_periodo,
        key_func=lambda dt: (dt.year, 1 if dt.month <= 6 else 2),
        label_func=lambda dt: f"{1 if dt.month <= 6 else 2}º Sem/{dt.year}",
    )

    # Carteira KPIs
    recebiveis_stats = Recebivel.objects.aggregate(
        total=Coalesce(Sum("valor"), Decimal("0")),
        total_pago=Coalesce(Sum("valor_pago"), Decimal("0")),
    )
    total_recebiveis = recebiveis_stats["total"]
    valor_pago = recebiveis_stats["total_pago"]
    saldo_devedor = total_recebiveis - valor_pago

    inadimplentes = Recebivel.objects.exclude(status=Recebivel.Status.PAGO)
    valor_inadimplente = inadimplentes.aggregate(
        total=Coalesce(Sum(F("valor") - F("valor_pago")), Decimal("0"))
    )["total"]
    taxa_inadimplencia = (
        (valor_inadimplente / total_recebiveis) if total_recebiveis else Decimal("0")
    )
    taxa_inadimplencia_percentual = taxa_inadimplencia * 100

    hoje = timezone.localdate()
    faixas = {
        "0-30": Decimal("0"),
        "31-60": Decimal("0"),
        "61-120": Decimal("0"),
        "120+": Decimal("0"),
    }
    for recebivel in inadimplentes.select_related("venda"):
        dias_atraso = 0
        if recebivel.data_vencimento:
            dias_atraso = (hoje - recebivel.data_vencimento).days
        saldo = recebivel.saldo_devedor
        if dias_atraso <= 30:
            faixa = "0-30"
        elif dias_atraso <= 60:
            faixa = "31-60"
        elif dias_atraso <= 120:
            faixa = "61-120"
        else:
            faixa = "120+"
        faixas[faixa] += saldo

    inadimplencia_por_faixa = {chave: valor for chave, valor in faixas.items() if valor}

    saldo_expression = ExpressionWrapper(
        F("valor") - F("valor_pago"), output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    carteira_por_corretor = (
        Recebivel.objects.values("venda__corretor__nome")
        .annotate(
            total=Coalesce(Sum("valor"), Decimal("0")),
            recebido=Coalesce(Sum("valor_pago"), Decimal("0")),
        )
        .order_by("venda__corretor__nome")
    )

    inadimplencia_lookup = {
        item["venda__corretor__nome"] or "Não informado": item["total_inadimplente"]
        for item in inadimplentes.values("venda__corretor__nome")
        .annotate(total_inadimplente=Coalesce(Sum(saldo_expression), Decimal("0")))
    }

    inadimplencia_por_corretor = []
    for corretor in carteira_por_corretor:
        nome = corretor["venda__corretor__nome"] or "Não informado"
        total_carteira = corretor["total"]
        valor_inadimplente_corretor = inadimplencia_lookup.get(nome, Decimal("0"))
        taxa_corretor = (
            (valor_inadimplente_corretor / total_carteira * 100)
            if total_carteira
            else Decimal("0")
        )
        inadimplencia_por_corretor.append(
            {
                "corretor": nome,
                "total_carteira": total_carteira,
                "valor_inadimplente": valor_inadimplente_corretor,
                "taxa": taxa_corretor,
            }
        )

    # Compras KPIs
    compras_stats = PedidoCompra.objects.aggregate(
        total=Coalesce(Sum("valor_total"), Decimal("0"))
    )
    custo_total_compras = compras_stats["total"]

    custo_por_empreendimento = (
        PedidoCompra.objects.values("empreendimento__nome")
        .annotate(total=Coalesce(Sum("valor_total"), Decimal("0")))
        .order_by("empreendimento__nome")
    )

    total_por_fornecedor = list(
        PedidoCompra.objects.values("fornecedor__nome")
        .annotate(total=Coalesce(Sum("valor_total"), Decimal("0")))
        .order_by("-total")
    )
    supplier_total = sum((item["total"] for item in total_por_fornecedor), Decimal("0"))
    supplier_share = [
        {
            "fornecedor": item["fornecedor__nome"],
            "valor": item["total"],
            "percentual": (item["total"] / supplier_total * 100)
            if supplier_total
            else Decimal("0"),
        }
        for item in total_por_fornecedor
    ]

    # Planejamento x Realizado
    planejamento_resumo = (
        TarefaPlanejada.objects.values("empreendimento__nome")
        .annotate(
            custo_planejado=Coalesce(Sum("custo_planejado"), Decimal("0")),
            custo_real=Coalesce(Sum("custo_real"), Decimal("0")),
        )
        .order_by("empreendimento__nome")
    )
    planejamento_vs_realizado = [
        {
            **item,
            "variacao": item["custo_real"] - item["custo_planejado"],
        }
        for item in planejamento_resumo
    ]

    # Margem de Lucro por Empreendimento
    margem_por_empreendimento = []
    for empreendimento in Empreendimento.objects.all().order_by("nome"):
        vendas_total = empreendimento.vendas.aggregate(
            total=Coalesce(Sum("valor_contrato"), Decimal("0"))
        )["total"]
        custo_total = empreendimento.pedidos_compra.aggregate(
            total=Coalesce(Sum("valor_total"), Decimal("0"))
        )["total"]
        margem_por_empreendimento.append(
            {
                "empreendimento": empreendimento.nome,
                "vendas": vendas_total,
                "custos": custo_total,
            "margem": vendas_total - custo_total,
        }
    )

    comparativos_series = {
        "mensal": [
            {
                "label": item["label"],
                "valor": float(item["valor"]),
                "unidades": item["unidades"],
            }
            for item in vendas_mensal
        ],
        "bimestral": [
            {
                "label": item["label"],
                "valor": float(item["valor"]),
                "unidades": item["unidades"],
            }
            for item in vendas_bimestral
        ],
        "semestral": [
            {
                "label": item["label"],
                "valor": float(item["valor"]),
                "unidades": item["unidades"],
            }
            for item in vendas_semestral
        ],
    }

    inadimplencia_corretor_chart = {
        "labels": [item["corretor"] for item in inadimplencia_por_corretor],
        "values": [float(item["valor_inadimplente"]) for item in inadimplencia_por_corretor],
        "taxas": [float(item["taxa"]) for item in inadimplencia_por_corretor],
    }

    supplier_share_chart = {
        "labels": [item["fornecedor"] for item in supplier_share],
        "values": [float(item["valor"]) for item in supplier_share],
    }

    charts_payload = json.dumps(
        {
            "comparativos_vendas": comparativos_series,
            "inadimplencia_corretor": inadimplencia_corretor_chart,
            "supplier_share": supplier_share_chart,
        },
        cls=DjangoJSONEncoder,
    )

    context = {
        "comercial": {
            "valor_total_vendas": total_vendas,
            "total_unidades": total_unidades,
            "ticket_medio_venda": vendas_stats["ticket_medio"],
            "ticket_medio_por_unidade": ticket_medio_por_unidade,
            "vendas_por_corretor": vendas_por_corretor,
            "comparativos": {
                "mensal": vendas_mensal,
                "bimestral": vendas_bimestral,
                "semestral": vendas_semestral,
            },
        },
        "carteira": {
            "taxa_inadimplencia": taxa_inadimplencia_percentual,
            "inadimplencia_por_faixa": inadimplencia_por_faixa,
            "valor_recebido": valor_pago,
            "saldo_devedor": saldo_devedor,
            "inadimplencia_por_corretor": inadimplencia_por_corretor,
        },
        "compras": {
            "custo_total": custo_total_compras,
            "custo_por_empreendimento": custo_por_empreendimento,
            "supplier_share": supplier_share,
        },
        "estrategicos": {
            "planejado_vs_realizado": planejamento_vs_realizado,
            "margem_por_empreendimento": margem_por_empreendimento,
        },
        "charts_payload": charts_payload,
    }
    return render(request, "dashboards/dashboard.html", context)

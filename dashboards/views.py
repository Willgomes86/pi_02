from decimal import Decimal

from django.db.models import Avg, F, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.utils import timezone

from carteira.models import Recebivel
from comercial.models import Empreendimento, Venda
from compras.models import PedidoCompra
from planejamento.models import TarefaPlanejada


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

    context = {
        "comercial": {
            "valor_total_vendas": total_vendas,
            "total_unidades": total_unidades,
            "ticket_medio_venda": vendas_stats["ticket_medio"],
            "ticket_medio_por_unidade": ticket_medio_por_unidade,
            "vendas_por_corretor": vendas_por_corretor,
        },
        "carteira": {
            "taxa_inadimplencia": taxa_inadimplencia_percentual,
            "inadimplencia_por_faixa": inadimplencia_por_faixa,
            "valor_recebido": valor_pago,
            "saldo_devedor": saldo_devedor,
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
    }
    return render(request, "dashboards/dashboard.html", context)

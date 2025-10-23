from datetime import datetime
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.utils.dateparse import parse_date

from carteira.models import Recebivel
from comercial.models import Empreendimento, Venda
from compras.models import Fornecedor, PedidoCompra


def kpis(request):
    total_vendas = Venda.objects.aggregate(v=Sum("valor_contrato"))["v"] or Decimal("0")
    qtd_vendas = Venda.objects.count()
    ticket_medio = (total_vendas / qtd_vendas) if qtd_vendas else Decimal("0")

    em_atraso = (
        Recebivel.objects.filter(
            status__in=["atrasado", "renegociado", "em atraso", "inadimplente"]
        ).aggregate(v=Sum("valor"))["v"]
        or Decimal("0")
    )

    return JsonResponse(
        {
            "total_vendas": float(total_vendas),
            "qtd_vendas": qtd_vendas,
            "ticket_medio": float(ticket_medio),
            "carteira_em_atraso": float(em_atraso),
        }
    )


def _parse_periodo(request):
    de = parse_date(request.GET.get("de") or "") or None
    ate = parse_date(request.GET.get("ate") or "") or None
    return de, ate


def vendas(request):
    qs = Venda.objects.select_related("empreendimento", "corretor")
    emp = request.GET.get("empreendimento")
    de, ate = _parse_periodo(request)
    if emp:
        qs = qs.filter(empreendimento__nome__icontains=emp)
    if de:
        qs = qs.filter(data_venda__gte=de)
    if ate:
        qs = qs.filter(data_venda__lte=ate)
    data = [
        {
            "empreendimento": v.empreendimento.nome if v.empreendimento_id else None,
            "cliente": v.cliente_nome,
            "corretor": v.corretor.nome if v.corretor_id else None,
            "data_venda": v.data_venda.isoformat() if v.data_venda else None,
            "unidades": v.unidades_vendidas,
            "valor": float(v.valor_contrato or 0),
        }
        for v in qs.order_by("-data_venda")[:1000]
    ]
    return JsonResponse({"results": data})


def carteira_status(request):
    qs = Recebivel.objects.values("status").annotate(total=Sum("valor")).order_by("status")
    data = [{"status": r["status"], "total": float(r["total"] or 0)} for r in qs]
    return JsonResponse({"results": data})


def top_fornecedores(request):
    qs = (
        PedidoCompra.objects.values("fornecedor__nome")
        .annotate(total=Sum("valor_total"))
        .order_by("-total")[:10]
    )
    data = [
        {"fornecedor": r["fornecedor__nome"], "total": float(r["total"] or 0)}
        for r in qs
    ]
    return JsonResponse({"results": data})

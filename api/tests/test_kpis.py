import pytest
from django.urls import reverse
from decimal import Decimal
from comercial.models import Venda, Empreendimento, Corretor
from datetime import date


@pytest.mark.django_db
def test_kpis_ok(client):
    emp = Empreendimento.objects.create(nome="Alpha")
    corr = Corretor.objects.create(nome="João")
    Venda.objects.create(
        empreendimento=emp,
        corretor=corr,
        cliente_nome="A",
        data_venda=date.today(),
        unidades_vendidas=1,
        valor_contrato=Decimal("1000"),
    )
    r = client.get("/api/kpis/")
    assert r.status_code == 200
    j = r.json()
    assert j["total_vendas"] >= 1000

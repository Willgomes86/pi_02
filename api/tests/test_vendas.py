import pytest
from django.utils.timezone import now
from decimal import Decimal
from comercial.models import Venda, Empreendimento, Corretor


@pytest.mark.django_db
def test_vendas_filtro_empreendimento(client):
    e1 = Empreendimento.objects.create(nome="Alpha")
    e2 = Empreendimento.objects.create(nome="Beta")
    c = Corretor.objects.create(nome="C1")
    Venda.objects.create(
        empreendimento=e1,
        corretor=c,
        cliente_nome="X",
        data_venda=now().date(),
        unidades_vendidas=1,
        valor_contrato=Decimal("10"),
    )
    Venda.objects.create(
        empreendimento=e2,
        corretor=c,
        cliente_nome="Y",
        data_venda=now().date(),
        unidades_vendidas=1,
        valor_contrato=Decimal("20"),
    )
    r = client.get("/api/vendas/?empreendimento=Alpha")
    assert r.status_code == 200
    assert len(r.json()["results"]) == 1

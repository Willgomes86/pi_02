from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from carteira.models import Recebivel
from comercial.models import Corretor, Empreendimento, Venda
from compras.models import Fornecedor, PedidoCompra
from planejamento.models import CategoriaPlanejamento, TarefaPlanejada


class DashboardViewTests(TestCase):
    def setUp(self) -> None:
        self.corretor = Corretor.objects.create(nome="João Silva")
        self.empreendimento = Empreendimento.objects.create(
            nome="Residencial Aurora", cidade="São Paulo"
        )
        self.venda = Venda.objects.create(
            corretor=self.corretor,
            empreendimento=self.empreendimento,
            cliente_nome="Maria Souza",
            data_venda=date.today(),
            unidades_vendidas=2,
            valor_contrato=Decimal("500000.00"),
        )

        Recebivel.objects.create(
            venda=self.venda,
            data_vencimento=date.today() - timedelta(days=45),
            valor=Decimal("100000.00"),
            valor_pago=Decimal("20000.00"),
            status=Recebivel.Status.ATRASADO,
        )
        Recebivel.objects.create(
            venda=self.venda,
            data_vencimento=date.today(),
            valor=Decimal("150000.00"),
            valor_pago=Decimal("150000.00"),
            status=Recebivel.Status.PAGO,
        )

        fornecedor = Fornecedor.objects.create(nome="Construsupply")
        PedidoCompra.objects.create(
            empreendimento=self.empreendimento,
            fornecedor=fornecedor,
            data_pedido=date.today(),
            categoria="materiais",
            valor_total=Decimal("120000.00"),
        )

        categoria = CategoriaPlanejamento.objects.create(nome="Infraestrutura")
        TarefaPlanejada.objects.create(
            empreendimento=self.empreendimento,
            categoria=categoria,
            nome="Fundação",
            data_inicio_prevista=date.today(),
            data_fim_prevista=date.today() + timedelta(days=30),
            data_fim_real=date.today() + timedelta(days=32),
            custo_planejado=Decimal("80000.00"),
            custo_real=Decimal("85000.00"),
        )

    def test_dashboard_overview_returns_expected_context(self) -> None:
        response = self.client.get(reverse("dashboards:overview"))
        self.assertEqual(response.status_code, 200)

        contexto = response.context
        self.assertIn("comercial", contexto)
        self.assertIn("carteira", contexto)
        self.assertIn("compras", contexto)
        self.assertIn("estrategicos", contexto)

        comercial = contexto["comercial"]
        self.assertEqual(comercial["total_unidades"], 2)
        self.assertEqual(comercial["valor_total_vendas"], Decimal("500000.00"))

        carteira = contexto["carteira"]
        self.assertGreater(carteira["taxa_inadimplencia"], 0)
        self.assertGreater(carteira["saldo_devedor"], 0)

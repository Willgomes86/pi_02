from decimal import Decimal

from django.db import models

from core.models import TimeStampedModel


class Fornecedor(TimeStampedModel):
    nome = models.CharField(max_length=120)
    documento = models.CharField("CNPJ/CPF", max_length=20, blank=True)
    contato = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        verbose_name = "Fornecedor"
        verbose_name_plural = "Fornecedores"
        ordering = ("nome",)

    def __str__(self) -> str:
        return self.nome


class PedidoCompra(TimeStampedModel):
    CATEGORIAS = (
        ("materiais", "Materiais"),
        ("servicos", "Serviços"),
        ("equipamentos", "Equipamentos"),
        ("outros", "Outros"),
    )

    empreendimento = models.ForeignKey(
        "comercial.Empreendimento",
        on_delete=models.PROTECT,
        related_name="pedidos_compra",
    )
    fornecedor = models.ForeignKey(
        Fornecedor, on_delete=models.PROTECT, related_name="pedidos"
    )
    data_pedido = models.DateField()
    categoria = models.CharField(max_length=20, choices=CATEGORIAS)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Pedido de Compra"
        verbose_name_plural = "Pedidos de Compra"
        ordering = ("-data_pedido",)

    def __str__(self) -> str:
        return f"{self.fornecedor} - {self.empreendimento}"


class ItemCompra(TimeStampedModel):
    pedido = models.ForeignKey(
        PedidoCompra, on_delete=models.CASCADE, related_name="itens"
    )
    descricao = models.CharField(max_length=200)
    quantidade = models.PositiveIntegerField(default=1)
    custo_unitario = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Item de Compra"
        verbose_name_plural = "Itens de Compra"

    def __str__(self) -> str:
        return self.descricao

    @property
    def custo_total(self) -> Decimal:
        return (self.custo_unitario or Decimal("0")) * Decimal(self.quantidade)

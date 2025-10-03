from decimal import Decimal

from django.db import models

from core.models import TimeStampedModel


class Corretor(TimeStampedModel):
    nome = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Corretor"
        verbose_name_plural = "Corretores"
        ordering = ("nome",)

    def __str__(self) -> str:
        return self.nome


class Empreendimento(TimeStampedModel):
    nome = models.CharField(max_length=150)
    cidade = models.CharField(max_length=80)
    data_lancamento = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Empreendimento"
        verbose_name_plural = "Empreendimentos"
        ordering = ("nome",)

    def __str__(self) -> str:
        return self.nome


class Venda(TimeStampedModel):
    class Status(models.TextChoices):
        ATIVA = "ativa", "Ativa"
        CANCELADA = "cancelada", "Cancelada"
        CONCLUIDA = "concluida", "Concluída"

    corretor = models.ForeignKey(Corretor, on_delete=models.PROTECT, related_name="vendas")
    empreendimento = models.ForeignKey(
        Empreendimento, on_delete=models.PROTECT, related_name="vendas"
    )
    cliente_nome = models.CharField(max_length=120)
    data_venda = models.DateField()
    unidades_vendidas = models.PositiveIntegerField(default=1)
    valor_contrato = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.ATIVA)

    class Meta:
        verbose_name = "Venda"
        verbose_name_plural = "Vendas"
        ordering = ("-data_venda",)

    def __str__(self) -> str:
        return f"{self.cliente_nome} - {self.empreendimento}"

    @property
    def ticket_medio(self) -> Decimal:
        if not self.unidades_vendidas:
            return Decimal("0")
        return (self.valor_contrato or Decimal("0")) / Decimal(
            self.unidades_vendidas
        )

from decimal import Decimal

from django.db import models

from core.models import TimeStampedModel


class Recebivel(TimeStampedModel):
    class Status(models.TextChoices):
        ABERTO = "aberto", "Em aberto"
        PAGO = "pago", "Pago"
        ATRASADO = "atrasado", "Atrasado"
        RENEGOCIADO = "renegociado", "Renegociado"

    venda = models.ForeignKey(
        "comercial.Venda", on_delete=models.CASCADE, related_name="parcelas"
    )
    data_vencimento = models.DateField()
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    data_pagamento = models.DateField(null=True, blank=True)
    valor_pago = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.ABERTO)

    class Meta:
        verbose_name = "Recebível"
        verbose_name_plural = "Recebíveis"
        ordering = ("data_vencimento",)

    def __str__(self) -> str:
        return f"Parcela {self.id} - {self.venda}"

    @property
    def esta_em_atraso(self) -> bool:
        return self.status in {self.Status.ATRASADO, self.Status.RENEGOCIADO}

    @property
    def saldo_devedor(self) -> Decimal:
        valor = self.valor or Decimal("0")
        pago = self.valor_pago or Decimal("0")
        if not isinstance(pago, Decimal):
            pago = Decimal(pago)
        return valor - pago

    @property
    def dias_em_atraso(self) -> int:
        if not self.data_vencimento or not self.esta_em_atraso:
            return 0
        from django.utils import timezone

        hoje = timezone.localdate()
        delta = hoje - self.data_vencimento
        return max(delta.days, 0)

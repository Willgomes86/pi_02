from decimal import Decimal

from django.db import models

from core.models import TimeStampedModel


class CategoriaPlanejamento(TimeStampedModel):
    nome = models.CharField(max_length=120, unique=True)

    class Meta:
        verbose_name = "Categoria de Planejamento"
        verbose_name_plural = "Categorias de Planejamento"
        ordering = ("nome",)

    def __str__(self) -> str:
        return self.nome


class TarefaPlanejada(TimeStampedModel):
    empreendimento = models.ForeignKey(
        "comercial.Empreendimento",
        on_delete=models.CASCADE,
        related_name="tarefas_planejamento",
    )
    categoria = models.ForeignKey(
        CategoriaPlanejamento, on_delete=models.SET_NULL, null=True, blank=True
    )
    nome = models.CharField(max_length=150)
    data_inicio_prevista = models.DateField()
    data_fim_prevista = models.DateField()
    data_fim_real = models.DateField(null=True, blank=True)
    custo_planejado = models.DecimalField(max_digits=12, decimal_places=2)
    custo_real = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Tarefa Planejada"
        verbose_name_plural = "Tarefas Planejadas"
        ordering = ("data_inicio_prevista",)

    def __str__(self) -> str:
        return self.nome

    @property
    def variacao_custo(self) -> Decimal:
        return (self.custo_real or Decimal("0")) - (
            self.custo_planejado or Decimal("0")
        )

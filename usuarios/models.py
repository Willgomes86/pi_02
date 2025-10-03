from __future__ import annotations
from django.contrib.auth.models import AbstractUser
from django.db import models
from apps.utils.encryption import OptionalEncryptedFieldsMixin


class Usuario(OptionalEncryptedFieldsMixin, AbstractUser):
    """Usuário principal do sistema com preferências extras."""

    class Papel(models.TextChoices):
        GERENTE = "GERENTE", "Gerente"
        CLINICO = "CLINICO", "Clínico"
        RECEPCAO_CAIXA = "RECEPCAO_CAIXA", "Recepção / Caixa"
        LEITURA = "LEITURA", "Somente leitura"

    ENCRYPTED_FIELDS = ("telefone", "cpf", "endereco")

    GENERO_OPCOES = [
        ("masculino", "Masculino"),
        ("feminino", "Feminino"),
        ("nao_informado", "Prefere não dizer"),
    ]

    genero = models.CharField(
        max_length=20,
        choices=GENERO_OPCOES,
        blank=True,
        default="nao_informado",
    )

    telefone = models.CharField(max_length=20, blank=True)
    cpf = models.CharField("CPF", max_length=14, blank=True, unique=True, null=True)
    endereco = models.CharField(max_length=255, blank=True)
    empresa = models.CharField(max_length=120, blank=True)
    papel = models.CharField(
        max_length=20,
        choices=Papel.choices,
        default=Papel.LEITURA,
        help_text="Determina os acessos principais deste usuário.",
    )

    class Meta:
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"

    def __str__(self) -> str:  # pragma: no cover - representação simples
        nome = self.get_full_name().strip()
        return nome or self.username
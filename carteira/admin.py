from django.contrib import admin

from .models import Recebivel


@admin.register(Recebivel)
class RecebivelAdmin(admin.ModelAdmin):
    list_display = (
        "venda",
        "data_vencimento",
        "valor",
        "status",
        "data_pagamento",
        "valor_pago",
    )
    list_filter = ("status", "data_vencimento")
    search_fields = (
        "venda__cliente_nome",
        "venda__empreendimento__nome",
        "venda__corretor__nome",
    )
    autocomplete_fields = ("venda",)

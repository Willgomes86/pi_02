from django.contrib import admin

from .models import Corretor, Empreendimento, Venda


@admin.register(Corretor)
class CorretorAdmin(admin.ModelAdmin):
    list_display = ("nome", "email", "telefone", "ativo")
    list_filter = ("ativo",)
    search_fields = ("nome", "email")


@admin.register(Empreendimento)
class EmpreendimentoAdmin(admin.ModelAdmin):
    list_display = ("nome", "cidade", "data_lancamento")
    search_fields = ("nome", "cidade")


@admin.register(Venda)
class VendaAdmin(admin.ModelAdmin):
    list_display = (
        "cliente_nome",
        "empreendimento",
        "corretor",
        "data_venda",
        "unidades_vendidas",
        "valor_contrato",
        "status",
    )
    list_filter = ("status", "data_venda")
    search_fields = ("cliente_nome", "empreendimento__nome", "corretor__nome")
    autocomplete_fields = ("corretor", "empreendimento")

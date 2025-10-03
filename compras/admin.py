from django.contrib import admin

from .models import Fornecedor, ItemCompra, PedidoCompra


class ItemCompraInline(admin.TabularInline):
    model = ItemCompra
    extra = 0


@admin.register(Fornecedor)
class FornecedorAdmin(admin.ModelAdmin):
    list_display = ("nome", "documento", "email", "contato")
    search_fields = ("nome", "documento")


@admin.register(PedidoCompra)
class PedidoCompraAdmin(admin.ModelAdmin):
    list_display = (
        "empreendimento",
        "fornecedor",
        "data_pedido",
        "categoria",
        "valor_total",
    )
    list_filter = ("categoria", "data_pedido")
    search_fields = (
        "empreendimento__nome",
        "fornecedor__nome",
    )
    autocomplete_fields = ("empreendimento", "fornecedor")
    inlines = [ItemCompraInline]

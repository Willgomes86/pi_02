from django.contrib import admin

from .models import CategoriaPlanejamento, TarefaPlanejada


@admin.register(CategoriaPlanejamento)
class CategoriaPlanejamentoAdmin(admin.ModelAdmin):
    list_display = ("nome",)
    search_fields = ("nome",)


@admin.register(TarefaPlanejada)
class TarefaPlanejadaAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "empreendimento",
        "categoria",
        "data_inicio_prevista",
        "data_fim_prevista",
        "data_fim_real",
        "custo_planejado",
        "custo_real",
    )
    list_filter = ("categoria", "data_inicio_prevista", "data_fim_prevista")
    search_fields = ("nome", "empreendimento__nome")
    autocomplete_fields = ("empreendimento", "categoria")

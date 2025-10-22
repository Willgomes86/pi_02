from django.urls import path

from .views import (
    dashboard_overview,
    kpis_resumo,
    series_carteira,
    series_vendas,
)


app_name = "dashboards"

urlpatterns = [
    path("", dashboard_overview, name="overview"),
    path("api/kpis/", kpis_resumo, name="kpis_resumo"),
    path("api/series/vendas/", series_vendas, name="series_vendas"),
    path("api/series/carteira/", series_carteira, name="series_carteira"),
]

from django.urls import path

from .views import carteira_status, kpis, top_fornecedores, vendas

urlpatterns = [
    path("kpis/", kpis, name="kpis"),
    path("vendas/", vendas, name="vendas"),
    path("carteira/status/", carteira_status, name="carteira_status"),
    path("compras/top-fornecedores/", top_fornecedores, name="top_fornecedores"),
]

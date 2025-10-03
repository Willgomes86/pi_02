from django.urls import path

from .views import dashboard_overview

app_name = "dashboards"

urlpatterns = [
    path("", dashboard_overview, name="overview"),
]

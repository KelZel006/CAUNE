from django.urls import path

from . import views

app_name = "reportes"

urlpatterns = [
    path("", views.IndiceView.as_view(), name="indice"),
    path("afiliados/", views.ReporteAfiliadosView.as_view(), name="afiliados"),
    path("aportaciones-depositos/", views.ReporteMovimientosView.as_view(), name="movimientos"),
    path("estado-de-cuenta/", views.ir_a_estado_cuenta, name="estado_cuenta"),
]

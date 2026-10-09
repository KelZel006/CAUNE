from django.urls import path

from . import views

app_name = "reportes"

urlpatterns = [
    path("", views.IndiceView.as_view(), name="indice"),
    path("afiliados/", views.ReporteAfiliadosView.as_view(), name="afiliados"),
    path("aportaciones-depositos/", views.ReporteMovimientosView.as_view(), name="movimientos"),
    path("estado-de-cuenta/", views.ir_a_estado_cuenta, name="estado_cuenta"),
    path("prestamos/", views.ReportePrestamosView.as_view(), name="prestamos"),
    path("cuadro-amortizacion/", views.ir_a_cuadro, name="cuadro"),
    path("pagos-prestamos/", views.ReportePagosView.as_view(), name="pagos"),
    path("saldos-prestamos/", views.ReporteSaldosPrestamosView.as_view(), name="saldos"),
    path("actividades/", views.ReporteMovimientosActividadView.as_view(), name="actividades"),
    path("resultados-actividades/", views.ReporteResultadosActividadView.as_view(), name="resultados_actividades"),
]

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
    path("ganancias-afiliado/", views.ir_a_ganancias, name="ganancias"),
    path("distribuciones/", views.ReporteDistribucionesView.as_view(), name="distribuciones"),
    path("libro-caja/", views.ReporteLibroCajaView.as_view(), name="libro_caja"),
    path("flujo-efectivo/", views.ReporteFlujoView.as_view(), name="flujo"),
    path("resumen-financiero/", views.ReporteResumenFinancieroView.as_view(), name="resumen_financiero"),
    path("balance-general/", views.ReporteBalanceView.as_view(), name="balance"),
    path("estado-resultados/", views.ReporteEstadoResultadosView.as_view(), name="estado_resultados"),
    path("cambios-patrimonio/", views.ReportePatrimonioView.as_view(), name="patrimonio"),
    path("estado-flujo-efectivo/", views.ReporteFlujoClasificadoView.as_view(), name="flujo_clasificado"),
    path("indicadores/", views.ReporteIndicadoresView.as_view(), name="indicadores"),
    path("estados-financieros/", views.EstadosFinancierosView.as_view(), name="estados_financieros"),
    path("saldos-caja/", views.ReporteCajaCuentasView.as_view(), name="caja_cuentas"),
    path("caja-diaria/", views.ReporteCajaDiariaView.as_view(), name="caja_diaria"),
    path("antiguedad-cartera/", views.ReporteCarteraView.as_view(), name="cartera"),
]

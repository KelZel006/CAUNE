from django.urls import path

from . import views

app_name = "prestamos"

urlpatterns = [
    path("", views.PrestamoListView.as_view(), name="lista"),
    path("nuevo/", views.PrestamoCreateView.as_view(), name="crear"),
    path("<int:pk>/", views.PrestamoDetailView.as_view(), name="detalle"),
    path("<int:pk>/desembolso/", views.DesembolsoView.as_view(), name="desembolsar"),
    path("<int:pk>/anular/", views.AnularPrestamoView.as_view(), name="anular"),
    path("<int:pk>/pagar/", views.PagoCreateView.as_view(), name="pagar"),
    path("pagos/<int:pk>/", views.PagoDetailView.as_view(), name="pago_detalle"),
    path("pagos/<int:pk>/anular/", views.AnularPagoView.as_view(), name="anular_pago"),
    path("<int:pk>/responsable/", views.ResponsableView.as_view(), name="responsable"),
]

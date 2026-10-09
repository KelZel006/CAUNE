from django.urls import path

from . import views

app_name = "aportaciones"

urlpatterns = [
    path("", views.MovimientoListView.as_view(), name="lista"),
    path("nuevo/", views.MovimientoCreateView.as_view(), name="crear"),
    path("<int:pk>/", views.MovimientoDetailView.as_view(), name="detalle"),
    path("<int:pk>/recibo/", views.ReciboView.as_view(), name="recibo"),
    path("<int:pk>/anular/", views.AnularMovimientoView.as_view(), name="anular"),
    path("tipos/", views.TipoListView.as_view(), name="tipos"),
    path("tipos/nuevo/", views.TipoCreateView.as_view(), name="tipo_crear"),
    path("tipos/<int:pk>/", views.TipoUpdateView.as_view(), name="tipo_editar"),
]

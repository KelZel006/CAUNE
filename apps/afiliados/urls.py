from django.urls import path

from . import views

app_name = "afiliados"

urlpatterns = [
    path("", views.AfiliadoListView.as_view(), name="lista"),
    path("nuevo/", views.AfiliadoCreateView.as_view(), name="crear"),
    path("<int:pk>/", views.AfiliadoDetailView.as_view(), name="detalle"),
    path("<int:pk>/editar/", views.AfiliadoUpdateView.as_view(), name="editar"),
    path("<int:pk>/estado/", views.CambiarEstadoView.as_view(), name="cambiar_estado"),
    path("<int:pk>/estado-de-cuenta/", views.EstadoCuentaView.as_view(), name="estado_cuenta"),
]

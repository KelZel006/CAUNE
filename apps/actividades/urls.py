from django.urls import path

from . import views

app_name = "actividades"

urlpatterns = [
    path("", views.ActividadListView.as_view(), name="lista"),
    path("nueva/", views.ActividadCreateView.as_view(), name="crear"),
    path("<int:pk>/", views.ActividadDetailView.as_view(), name="detalle"),
    path("<int:pk>/editar/", views.ActividadUpdateView.as_view(), name="editar"),
    path("<int:pk>/estado/", views.CambiarEstadoView.as_view(), name="cambiar_estado"),
    path("<int:pk>/subactividades/nueva/", views.SubactividadCreateView.as_view(), name="subactividad_crear"),
    path("<int:pk>/registrar/", views.MovimientoCreateView.as_view(), name="registrar"),
    path("movimientos/<int:pk>/anular/", views.AnularMovimientoView.as_view(), name="anular"),
    path("<int:pk>/participacion/excluir/", views.ExcluirAfiliadoView.as_view(), name="excluir"),
    path("participacion/<int:pk>/incluir/", views.IncluirAfiliadoView.as_view(), name="incluir"),
]

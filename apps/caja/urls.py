from django.urls import path

from . import views

app_name = "caja"

urlpatterns = [
    path("", views.CajaView.as_view(), name="indice"),
    path("registrar/", views.MovimientoCreateView.as_view(), name="registrar"),
    path("<int:pk>/", views.MovimientoDetailView.as_view(), name="detalle"),
    path("<int:pk>/anular/", views.AnularView.as_view(), name="anular"),
    path("categorias/", views.CategoriaListView.as_view(), name="categorias"),
    path("categorias/nueva/", views.CategoriaCreateView.as_view(), name="categoria_crear"),
    path("categorias/<int:pk>/", views.CategoriaUpdateView.as_view(), name="categoria_editar"),
]

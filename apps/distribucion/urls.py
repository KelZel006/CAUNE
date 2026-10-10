from django.urls import path

from . import views

app_name = "distribucion"

urlpatterns = [
    path("", views.DistribucionListView.as_view(), name="lista"),
    path("nueva/", views.DistribucionCreateView.as_view(), name="crear"),
    path("<int:pk>/", views.DistribucionDetailView.as_view(), name="detalle"),
    path("<int:pk>/recalcular/", views.RecalcularView.as_view(), name="recalcular"),
    path("<int:pk>/aprobar/", views.AprobarView.as_view(), name="aprobar"),
    path("<int:pk>/anular/", views.AnularView.as_view(), name="anular"),
    path("<int:pk>/entregar/", views.EntregarView.as_view(), name="entregar"),
    path("pagos/<int:pk>/anular/", views.AnularPagoView.as_view(), name="anular_pago"),
]

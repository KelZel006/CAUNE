from django.urls import path

from . import views

app_name = "liquidaciones"

urlpatterns = [
    path("", views.LiquidacionListView.as_view(), name="lista"),
    path("afiliado/<int:pk>/", views.LiquidacionCreateView.as_view(), name="crear"),
    path("<int:pk>/", views.LiquidacionDetailView.as_view(), name="detalle"),
    path("<int:pk>/recalcular/", views.RecalcularView.as_view(), name="recalcular"),
    path("<int:pk>/ejecutar/", views.EjecutarView.as_view(), name="ejecutar"),
    path("<int:pk>/anular/", views.AnularView.as_view(), name="anular"),
]

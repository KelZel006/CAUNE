from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy

admin.site.site_header = "CAUNE · Administración técnica"
admin.site.site_title = "CAUNE"

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "cuenta/ingresar/",
        auth_views.LoginView.as_view(redirect_authenticated_user=True),
        name="login",
    ),
    path("cuenta/salir/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "cuenta/contrasena/",
        auth_views.PasswordChangeView.as_view(success_url=reverse_lazy("password_change_done")),
        name="password_change",
    ),
    path(
        "cuenta/contrasena/listo/",
        auth_views.PasswordChangeDoneView.as_view(),
        name="password_change_done",
    ),
    path("", include("apps.core.urls")),
    path("afiliados/", include("apps.afiliados.urls")),
    path("movimientos/", include("apps.aportaciones.urls")),
    path("prestamos/", include("apps.prestamos.urls")),
    path("actividades/", include("apps.actividades.urls")),
    path("caja/", include("apps.caja.urls")),
    path("ganancias/", include("apps.distribucion.urls")),
    path("reportes/", include("apps.reportes.urls")),
]

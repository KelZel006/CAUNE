from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("configuracion/", views.ConfiguracionView.as_view(), name="configuracion"),
    path("configuracion/parametros/", views.ParametroListView.as_view(), name="parametros"),
    path("configuracion/parametros/<int:pk>/", views.ParametroUpdateView.as_view(), name="parametro_editar"),
    path("configuracion/cuentas/", views.CuentaFondoListView.as_view(), name="cuentas"),
    path("configuracion/cuentas/nueva/", views.CuentaFondoCreateView.as_view(), name="cuenta_crear"),
    path("configuracion/cuentas/<int:pk>/", views.CuentaFondoUpdateView.as_view(), name="cuenta_editar"),
    path("configuracion/numeracion/", views.SecuenciaListView.as_view(), name="secuencias"),
    path("configuracion/numeracion/<int:pk>/", views.SecuenciaUpdateView.as_view(), name="secuencia_editar"),
    path("configuracion/usuarios/", views.UsuarioListView.as_view(), name="usuarios"),
    path("configuracion/usuarios/nuevo/", views.UsuarioCreateView.as_view(), name="usuario_crear"),
    path("configuracion/usuarios/<int:pk>/", views.UsuarioUpdateView.as_view(), name="usuario_editar"),
    path("configuracion/usuarios/<int:pk>/contrasena/", views.UsuarioPasswordView.as_view(), name="usuario_password"),
    path("configuracion/roles/", views.RolListView.as_view(), name="roles"),
    path("configuracion/roles/nuevo/", views.RolCreateView.as_view(), name="rol_crear"),
    path("configuracion/roles/<int:pk>/", views.RolUpdateView.as_view(), name="rol_editar"),
    path("auditoria/", views.AuditoriaListView.as_view(), name="auditoria"),
]

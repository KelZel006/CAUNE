"""Roles iniciales (mínimo privilegio). Son configurables desde Configuración → Roles."""
from django.contrib.auth.models import Group, Permission

APPS_CAUNE = ("core", "afiliados", "aportaciones", "auth")

ROLES = {
    "Administrador": "__todos__",
    # Decisión de CAUNE (08/10/2026): el tesorero tiene acceso total al sistema.
    "Tesorero": "__todos__",
    # El presidente consulta los reportes de importancia; no registra ni modifica nada.
    "Presidente": [
        "core.ver_dashboard_financiero", "core.ver_reportes",
        "afiliados.view_afiliado", "afiliados.ver_estado_cuenta",
        "aportaciones.view_movimientoafiliado", "aportaciones.view_tipomovimiento",
    ],
    "Encargado de préstamos": [
        "afiliados.view_afiliado", "afiliados.ver_estado_cuenta",
    ],
    "Encargado de actividades": [],
    "Contador o supervisor": [
        "core.ver_dashboard_financiero", "core.ver_reportes", "core.ver_auditoria",
        "core.view_cuentafondo", "core.view_parametro", "core.view_secuencia",
        "afiliados.view_afiliado", "afiliados.ver_estado_cuenta",
        "aportaciones.view_tipomovimiento", "aportaciones.view_movimientoafiliado",
        "aportaciones.anular_movimientoafiliado",
    ],
}


def permisos_asignables():
    return (Permission.objects.filter(content_type__app_label__in=APPS_CAUNE)
            .exclude(content_type__app_label="auth", content_type__model="permission")
            .select_related("content_type").order_by("content_type__app_label", "content_type__model", "codename"))


def _resolver(codigos):
    permisos = []
    for codigo in codigos:
        app, codename = codigo.split(".")
        permisos.append(Permission.objects.get(content_type__app_label=app, codename=codename))
    return permisos


def configurar_roles(restablecer=False):
    """Crea los roles que falten. Con restablecer=True devuelve sus permisos a los iniciales."""
    resultado = {}
    for nombre, codigos in ROLES.items():
        grupo, creado = Group.objects.get_or_create(name=nombre)
        if creado or restablecer:
            permisos = list(permisos_asignables()) if codigos == "__todos__" else _resolver(codigos)
            grupo.permissions.set(permisos)
        resultado[nombre] = creado
    return resultado

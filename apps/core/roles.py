"""Roles iniciales (mínimo privilegio). Son configurables desde Configuración → Roles."""
from django.contrib.auth.models import Group, Permission

APPS_CAUNE = ("core", "afiliados", "aportaciones", "prestamos", "actividades", "caja", "distribucion", "liquidaciones",
              "auth")

ROLES = {
    "Administrador": "__todos__",
    # Decisión de CAUNE (08/10/2026): el tesorero tiene acceso total al sistema.
    "Tesorero": "__todos__",
    # El presidente consulta los reportes de importancia; no registra ni modifica nada.
    "Presidente": [
        "core.ver_dashboard_financiero", "core.ver_reportes",
        "afiliados.view_afiliado", "afiliados.ver_estado_cuenta",
        "aportaciones.view_movimientoafiliado", "aportaciones.view_tipomovimiento",
        "prestamos.view_prestamo", "prestamos.view_pagoprestamo",
        "actividades.view_actividad", "actividades.view_movimientoactividad",
        "caja.view_movimientocaja", "caja.view_conciliacionbancaria", "distribucion.view_distribucion",
        "liquidaciones.view_liquidacion",
    ],
    "Encargado de préstamos": [
        "core.ver_reportes", "afiliados.view_afiliado", "afiliados.ver_estado_cuenta",
        "prestamos.view_prestamo", "prestamos.add_prestamo", "prestamos.desembolsar_prestamo",
        "prestamos.view_pagoprestamo", "prestamos.add_pagoprestamo",
    ],
    "Encargado de actividades": [
        "core.ver_reportes",
        "actividades.view_actividad", "actividades.add_actividad", "actividades.change_actividad",
        "actividades.add_subactividad", "actividades.view_movimientoactividad",
        "actividades.add_movimientoactividad",
    ],
    "Contador o supervisor": [
        "core.ver_dashboard_financiero", "core.ver_reportes", "core.ver_auditoria",
        "core.view_cuentafondo", "core.view_parametro", "core.view_secuencia",
        "afiliados.view_afiliado", "afiliados.ver_estado_cuenta",
        "aportaciones.view_tipomovimiento", "aportaciones.view_movimientoafiliado",
        "aportaciones.anular_movimientoafiliado",
        "prestamos.view_prestamo", "prestamos.view_pagoprestamo", "prestamos.anular_pagoprestamo",
        "prestamos.anular_prestamo",
        "actividades.view_actividad", "actividades.view_movimientoactividad",
        "actividades.anular_movimientoactividad",
        "caja.view_movimientocaja", "caja.view_categoriacaja", "caja.anular_movimientocaja",
        "caja.view_conciliacionbancaria", "caja.anular_conciliacionbancaria",
        "liquidaciones.view_liquidacion", "liquidaciones.anular_liquidacion",
        "distribucion.view_distribucion", "distribucion.anular_distribucion", "distribucion.anular_pagoganancia",
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
    """Crea los roles que falten y les agrega permisos nuevos. restablecer=True los deja exactamente como el inicial."""
    resultado = {}
    for nombre, codigos in ROLES.items():
        grupo, creado = Group.objects.get_or_create(name=nombre)
        permisos = list(permisos_asignables()) if codigos == "__todos__" else _resolver(codigos)
        if creado or restablecer:
            grupo.permissions.set(permisos)
        else:
            # Agrega los permisos de módulos nuevos sin quitar los que CAUNE haya ajustado a mano.
            grupo.permissions.add(*permisos)
        resultado[nombre] = creado
    return resultado

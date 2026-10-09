"""Registro de auditoría: quién hizo qué, cuándo y con qué datos."""
import json

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder

from .middleware import obtener_request
from .models import HistorialAuditoria

Accion = HistorialAuditoria.Accion


def instantanea(obj, excluir=()):
    """Copia serializable de los campos concretos de un modelo."""
    datos = {f.attname: getattr(obj, f.attname) for f in obj._meta.concrete_fields if f.name not in excluir}
    return json.loads(json.dumps(datos, cls=DjangoJSONEncoder))


def diferencias(antes, despues):
    """Devuelve solo los campos que cambiaron entre dos instantáneas."""
    claves = [k for k in despues if antes.get(k) != despues.get(k)]
    return {k: antes.get(k) for k in claves}, {k: despues.get(k) for k in claves}


def _ip(request):
    if request is None:
        return None
    if settings.CAUNE_CONFIAR_PROXY:
        reenviada = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if reenviada:
            return reenviada.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def registrar(accion, *, usuario=None, objeto=None, entidad="", entidad_id="", descripcion="",
              antes=None, despues=None):
    request = obtener_request()
    if usuario is None and request is not None and getattr(request, "user", None) is not None:
        if request.user.is_authenticated:
            usuario = request.user
    if objeto is not None:
        entidad = entidad or objeto._meta.label
        entidad_id = entidad_id or str(objeto.pk)
    return HistorialAuditoria.objects.create(
        usuario=usuario if (usuario is not None and usuario.pk) else None,
        usuario_nombre=(usuario.get_username() if usuario is not None else ""),
        accion=accion,
        entidad=entidad,
        entidad_id=str(entidad_id),
        descripcion=descripcion,
        datos_antes=antes,
        datos_despues=despues,
        ip=_ip(request),
    )

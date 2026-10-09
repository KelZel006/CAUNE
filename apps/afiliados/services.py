from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import auditoria
from apps.core.secuencias import siguiente_numero

from .models import Afiliado, CambioEstadoAfiliado

CAMPOS_EDITABLES = ("nombres", "apellidos", "identidad", "telefono", "direccion", "fecha_ingreso")


def _validar_fecha_ingreso(afiliado, fecha_ingreso):
    if fecha_ingreso is None:
        raise ValidationError({"fecha_ingreso": "Indique la fecha de ingreso."})
    if fecha_ingreso > timezone.localdate():
        raise ValidationError({"fecha_ingreso": "La fecha de ingreso no puede ser futura."})
    if afiliado.pk:
        primero = afiliado.movimientos.order_by("fecha").values_list("fecha", flat=True).first()
        if primero is not None and fecha_ingreso > primero:
            raise ValidationError({"fecha_ingreso": f"El afiliado tiene movimientos desde el {primero:%d/%m/%Y}; "
                                                    "la fecha de ingreso no puede ser posterior."})


@transaction.atomic
def crear_afiliado(datos, usuario):
    if not usuario.has_perm("afiliados.add_afiliado"):
        raise ValidationError("No tiene permiso para crear afiliados.")
    afiliado = Afiliado(**{c: datos.get(c, "") for c in CAMPOS_EDITABLES}, creado_por=usuario)
    _validar_fecha_ingreso(afiliado, afiliado.fecha_ingreso)
    afiliado.codigo = siguiente_numero("AF")
    afiliado.full_clean()
    afiliado.save()
    auditoria.registrar(auditoria.Accion.CREAR, usuario=usuario, objeto=afiliado,
                        descripcion=f"Alta del afiliado {afiliado.codigo}", despues=auditoria.instantanea(afiliado))
    return afiliado


@transaction.atomic
def actualizar_afiliado(afiliado, datos, usuario):
    if not usuario.has_perm("afiliados.change_afiliado"):
        raise ValidationError("No tiene permiso para modificar afiliados.")
    afiliado = Afiliado.objects.select_for_update().get(pk=afiliado.pk)
    antes = auditoria.instantanea(afiliado)
    for campo in CAMPOS_EDITABLES:
        if campo in datos:
            setattr(afiliado, campo, datos[campo])
    _validar_fecha_ingreso(afiliado, afiliado.fecha_ingreso)
    afiliado.full_clean()
    afiliado.save()
    cambios_antes, cambios_despues = auditoria.diferencias(antes, auditoria.instantanea(afiliado))
    cambios_antes.pop("actualizado_en", None)
    cambios_despues.pop("actualizado_en", None)
    if cambios_despues:
        auditoria.registrar(auditoria.Accion.MODIFICAR, usuario=usuario, objeto=afiliado,
                            descripcion=f"Modificación de datos de {afiliado.codigo}",
                            antes=cambios_antes, despues=cambios_despues)
    return afiliado


@transaction.atomic
def cambiar_estado(afiliado, *, estado_nuevo, fecha_efectiva, motivo, usuario):
    if not usuario.has_perm("afiliados.cambiar_estado_afiliado"):
        raise ValidationError("No tiene permiso para activar o inactivar afiliados.")
    afiliado = Afiliado.objects.select_for_update().get(pk=afiliado.pk)
    motivo = (motivo or "").strip()
    if estado_nuevo not in Afiliado.Estado.values:
        raise ValidationError({"estado_nuevo": "Estado inválido."})
    if estado_nuevo == afiliado.estado:
        raise ValidationError(f"El afiliado ya está {afiliado.get_estado_display().lower()}.")
    if len(motivo) < 10:
        raise ValidationError({"motivo": "Explique el motivo (mínimo 10 caracteres)."})
    if fecha_efectiva is None or fecha_efectiva > timezone.localdate():
        raise ValidationError({"fecha_efectiva": "La fecha efectiva es obligatoria y no puede ser futura."})
    if fecha_efectiva < afiliado.fecha_ingreso:
        raise ValidationError({"fecha_efectiva": "La fecha efectiva es anterior al ingreso del afiliado."})
    ultimo = afiliado.cambios_estado.order_by("-fecha_efectiva", "-id").first()
    if ultimo is not None and fecha_efectiva < ultimo.fecha_efectiva:
        raise ValidationError({"fecha_efectiva": "La fecha efectiva es anterior al último cambio de estado."})
    anterior = afiliado.estado
    afiliado.estado = estado_nuevo
    afiliado.save(update_fields=["estado", "actualizado_en"])
    cambio = CambioEstadoAfiliado.objects.create(afiliado=afiliado, estado_anterior=anterior, estado_nuevo=estado_nuevo,
                                                 fecha_efectiva=fecha_efectiva, motivo=motivo, registrado_por=usuario)
    auditoria.registrar(auditoria.Accion.CAMBIO_ESTADO, usuario=usuario, objeto=afiliado,
                        descripcion=f"{afiliado.codigo}: {anterior} → {estado_nuevo} desde {fecha_efectiva:%d/%m/%Y}. "
                                    f"Motivo: {motivo}",
                        antes={"estado": anterior}, despues={"estado": estado_nuevo})
    return cambio

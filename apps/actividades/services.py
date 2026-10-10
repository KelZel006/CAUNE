"""Actividades económicas: registro de ingresos y gastos y cálculo de resultados.

Total de ingresos = suma de ingresos confirmados; total de gastos = suma de gastos confirmados;
resultado neto = ingresos − gastos. Los anulados no suman.
"""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.aportaciones.services import _validar_monto
from apps.core import auditoria, parametros
from apps.core.dinero import CERO, redondear
from apps.core.secuencias import siguiente_numero
from apps.prestamos.services import _validar_cuenta_metodo

from .models import Actividad, ExclusionActividad, MovimientoActividad, Subactividad

_DEC = DecimalField(max_digits=16, decimal_places=2)
_CONF = Q(movimientos__estado=MovimientoActividad.Estado.CONFIRMADO)


def _sumas(prefijo="movimientos__", filtro=Q()):
    return {
        "ingresos": Coalesce(Sum(f"{prefijo}monto", filter=Q(**{f"{prefijo}tipo": "INGRESO"}) & filtro), Value(CERO),
                             output_field=_DEC),
        "gastos": Coalesce(Sum(f"{prefijo}monto", filter=Q(**{f"{prefijo}tipo": "GASTO"}) & filtro), Value(CERO),
                           output_field=_DEC),
    }


def _filtro_periodo(desde, hasta, prefijo="movimientos__"):
    f = Q(**{f"{prefijo}estado": MovimientoActividad.Estado.CONFIRMADO})
    if desde:
        f &= Q(**{f"{prefijo}fecha__gte": desde})
    if hasta:
        f &= Q(**{f"{prefijo}fecha__lte": hasta})
    return f


def anotar_resultados(queryset, desde=None, hasta=None):
    """Agrega ingresos, gastos y resultado a un queryset de Actividad o Subactividad."""
    return queryset.annotate(**_sumas(filtro=_filtro_periodo(desde, hasta)))


def resultado_actividad(actividad, desde=None, hasta=None):
    qs = MovimientoActividad.objects.filter(actividad=actividad)
    datos = qs.aggregate(**_sumas(prefijo="", filtro=_filtro_periodo(desde, hasta, prefijo="")))
    ingresos, gastos = redondear(datos["ingresos"]), redondear(datos["gastos"])
    return {"ingresos": ingresos, "gastos": gastos, "neto": ingresos - gastos}


def resultado_general(desde=None, hasta=None):
    datos = MovimientoActividad.objects.aggregate(**_sumas(prefijo="", filtro=_filtro_periodo(desde, hasta, prefijo="")))
    ingresos, gastos = redondear(datos["ingresos"]), redondear(datos["gastos"])
    return {"ingresos": ingresos, "gastos": gastos, "neto": ingresos - gastos}


def resultados_por_subactividad(actividad, desde=None, hasta=None):
    filas = []
    for sub in anotar_resultados(actividad.subactividades.all(), desde, hasta):
        filas.append({"subactividad": sub, "ingresos": redondear(sub.ingresos), "gastos": redondear(sub.gastos),
                      "neto": redondear(sub.ingresos - sub.gastos)})
    sin_sub = MovimientoActividad.objects.filter(actividad=actividad, subactividad__isnull=True).aggregate(
        **_sumas(prefijo="", filtro=_filtro_periodo(desde, hasta, prefijo="")))
    if sin_sub["ingresos"] or sin_sub["gastos"]:
        filas.append({"subactividad": None, "ingresos": redondear(sin_sub["ingresos"]),
                      "gastos": redondear(sin_sub["gastos"]), "neto": redondear(sin_sub["ingresos"] - sin_sub["gastos"])})
    return filas


# --------------------------------------------------------------------------- actividades

@transaction.atomic
def crear_actividad(datos, usuario):
    if not usuario.has_perm("actividades.add_actividad"):
        raise ValidationError("No tiene permiso para crear actividades.")
    actividad = Actividad(nombre=" ".join(datos["nombre"].split()), descripcion=datos.get("descripcion", "").strip(),
                          fecha_inicio=datos["fecha_inicio"], creado_por=usuario)
    if actividad.fecha_inicio and actividad.fecha_inicio > timezone.localdate():
        raise ValidationError({"fecha_inicio": "La fecha de inicio no puede ser futura."})
    actividad.codigo = siguiente_numero("ACT")
    actividad.full_clean()
    actividad.save()
    auditoria.registrar(auditoria.Accion.CREAR, usuario=usuario, objeto=actividad, despues=auditoria.instantanea(actividad))
    return actividad


@transaction.atomic
def actualizar_actividad(actividad, datos, usuario):
    if not usuario.has_perm("actividades.change_actividad"):
        raise ValidationError("No tiene permiso para modificar actividades.")
    actividad = Actividad.objects.select_for_update().get(pk=actividad.pk)
    antes = auditoria.instantanea(actividad)
    actividad.nombre = " ".join(datos["nombre"].split())
    actividad.descripcion = datos.get("descripcion", "").strip()
    nueva_fecha = datos["fecha_inicio"]
    primero = actividad.movimientos.order_by("fecha").values_list("fecha", flat=True).first()
    if nueva_fecha > timezone.localdate() or (primero and nueva_fecha > primero):
        raise ValidationError({"fecha_inicio": "La fecha de inicio no puede ser futura ni posterior a sus movimientos."})
    actividad.fecha_inicio = nueva_fecha
    actividad.full_clean()
    actividad.save()
    a, d = auditoria.diferencias(antes, auditoria.instantanea(actividad))
    if d:
        auditoria.registrar(auditoria.Accion.MODIFICAR, usuario=usuario, objeto=actividad, antes=a, despues=d)
    return actividad


@transaction.atomic
def cambiar_estado_actividad(actividad, usuario, motivo):
    if not usuario.has_perm("actividades.cambiar_estado_actividad"):
        raise ValidationError("No tiene permiso para cerrar o reabrir actividades.")
    if len((motivo or "").strip()) < 10:
        raise ValidationError({"motivo": "Explique el motivo (mínimo 10 caracteres)."})
    actividad = Actividad.objects.select_for_update().get(pk=actividad.pk)
    anterior = actividad.estado
    actividad.estado = Actividad.Estado.CERRADA if actividad.activa else Actividad.Estado.ACTIVA
    actividad.save(update_fields=["estado"])
    auditoria.registrar(auditoria.Accion.CAMBIO_ESTADO, usuario=usuario, objeto=actividad,
                        descripcion=f"{actividad.codigo}: {anterior} → {actividad.estado}. Motivo: {motivo.strip()}",
                        antes={"estado": anterior}, despues={"estado": actividad.estado})
    return actividad


@transaction.atomic
def crear_subactividad(actividad, datos, usuario):
    if not usuario.has_perm("actividades.add_subactividad"):
        raise ValidationError("No tiene permiso para crear subactividades.")
    sub = Subactividad(actividad=actividad, nombre=" ".join(datos["nombre"].split()),
                       descripcion=datos.get("descripcion", "").strip())
    sub.full_clean()
    sub.save()
    auditoria.registrar(auditoria.Accion.CREAR, usuario=usuario, objeto=sub, despues=auditoria.instantanea(sub))
    return sub


# --------------------------------------------------------------------------- ingresos y gastos

def registrar_movimiento(*, actividad, tipo, fecha, concepto, monto, metodo_pago, cuenta_fondo, usuario,
                         subactividad=None, referencia="", observacion="", clave_idempotencia=None):
    if not usuario.has_perm("actividades.add_movimientoactividad"):
        raise ValidationError("No tiene permiso para registrar ingresos o gastos.")
    if clave_idempotencia is not None:
        existente = MovimientoActividad.objects.filter(clave_idempotencia=clave_idempotencia).first()
        if existente is not None:
            return existente, False
    monto = _validar_monto(monto)
    concepto = " ".join((concepto or "").split())
    errores = {}
    if tipo not in MovimientoActividad.Tipo.values:
        errores["tipo"] = "Indique si es ingreso o gasto."
    if len(concepto) < 3:
        errores["concepto"] = "Describa el concepto."
    if fecha is None or fecha > timezone.localdate():
        errores["fecha"] = "La fecha es obligatoria y no puede ser futura."
    _validar_cuenta_metodo(metodo_pago, cuenta_fondo, referencia, errores)
    if errores:
        raise ValidationError(errores)
    with transaction.atomic():
        try:
            actividad = Actividad.objects.select_for_update().get(pk=getattr(actividad, "pk", actividad))
        except Actividad.DoesNotExist:
            raise ValidationError({"actividad": "La actividad no existe."}) from None
        if not actividad.activa:
            raise ValidationError({"actividad": "La actividad está cerrada; no admite nuevos registros."})
        if fecha < actividad.fecha_inicio:
            raise ValidationError({"fecha": "La fecha es anterior al inicio de la actividad."})
        if subactividad is not None:
            if subactividad.actividad_id != actividad.pk:
                raise ValidationError({"subactividad": "La subactividad no pertenece a esta actividad."})
            if not subactividad.activa:
                raise ValidationError({"subactividad": "La subactividad está inactiva."})
        try:
            with transaction.atomic():
                mov = MovimientoActividad.objects.create(
                    numero=siguiente_numero("MA"), actividad=actividad, subactividad=subactividad, tipo=tipo,
                    fecha=fecha, concepto=concepto, monto=monto, metodo_pago=metodo_pago, cuenta_fondo=cuenta_fondo,
                    referencia=(referencia or "").strip(), observacion=(observacion or "").strip(),
                    registrado_por=usuario,
                    **({"clave_idempotencia": clave_idempotencia} if clave_idempotencia else {}),
                )
        except IntegrityError:
            existente = MovimientoActividad.objects.filter(clave_idempotencia=clave_idempotencia).first()
            if existente is not None:
                return existente, False
            raise
        auditoria.registrar(auditoria.Accion.CREAR, usuario=usuario, objeto=mov,
                            descripcion=f"{mov.get_tipo_display()} {mov.numero} en {actividad.codigo}",
                            despues=auditoria.instantanea(mov))
    return mov, True


@transaction.atomic
def anular_movimiento(mov, *, usuario, motivo):
    if not usuario.has_perm("actividades.anular_movimientoactividad"):
        raise ValidationError("No tiene permiso para anular ingresos o gastos.")
    motivo = (motivo or "").strip()
    if len(motivo) < 10:
        raise ValidationError({"motivo": "Explique el motivo de la anulación (mínimo 10 caracteres)."})
    mov = MovimientoActividad.objects.select_for_update().get(pk=mov.pk)
    if not mov.confirmado:
        raise ValidationError("El registro ya está anulado.")
    if parametros.obtener("movimientos.anulacion_requiere_otro_usuario") and mov.registrado_por_id == usuario.pk:
        raise ValidationError("La anulación debe autorizarla un usuario distinto al que registró la operación.")
    antes = auditoria.instantanea(mov)
    mov.estado = MovimientoActividad.Estado.ANULADO
    mov.anulado_por = usuario
    mov.anulado_en = timezone.now()
    mov.motivo_anulacion = motivo
    mov.save(update_fields=["estado", "anulado_por", "anulado_en", "motivo_anulacion"])
    auditoria.registrar(auditoria.Accion.ANULAR, usuario=usuario, objeto=mov,
                        descripcion=f"Anulación de {mov.numero}. Motivo: {motivo}", antes=antes,
                        despues=auditoria.instantanea(mov))
    return mov


# --------------------------------------------------------------------------- participación en ganancias

@transaction.atomic
def excluir_afiliado(actividad, afiliado, *, usuario, motivo):
    """Marca a un afiliado para que no participe en las ganancias de esta actividad."""
    if not usuario.has_perm("actividades.gestionar_participacion"):
        raise ValidationError("No tiene permiso para cambiar quién participa en las ganancias.")
    motivo = " ".join((motivo or "").split())
    if len(motivo) < 10:
        raise ValidationError({"motivo": "Explique el motivo (mínimo 10 caracteres)."})
    if ExclusionActividad.objects.filter(actividad=actividad, afiliado=afiliado).exists():
        raise ValidationError({"afiliado": "Este afiliado ya está marcado como no participante."})
    exclusion = ExclusionActividad.objects.create(actividad=actividad, afiliado=afiliado, motivo=motivo,
                                                  registrado_por=usuario)
    auditoria.registrar(auditoria.Accion.CREAR, usuario=usuario, objeto=exclusion,
                        descripcion=f"{afiliado.codigo} no participa en las ganancias de {actividad.codigo}. "
                                    f"Motivo: {motivo}",
                        despues=auditoria.instantanea(exclusion))
    return exclusion


@transaction.atomic
def incluir_afiliado(exclusion, *, usuario, motivo):
    """Quita la marca: el afiliado vuelve a participar en las ganancias de la actividad."""
    if not usuario.has_perm("actividades.gestionar_participacion"):
        raise ValidationError("No tiene permiso para cambiar quién participa en las ganancias.")
    motivo = " ".join((motivo or "").split())
    if len(motivo) < 10:
        raise ValidationError({"motivo": "Explique el motivo (mínimo 10 caracteres)."})
    exclusion = ExclusionActividad.objects.select_related("actividad", "afiliado").get(pk=exclusion.pk)
    antes = auditoria.instantanea(exclusion)
    auditoria.registrar(auditoria.Accion.MODIFICAR, usuario=usuario, objeto=exclusion,
                        descripcion=f"{exclusion.afiliado.codigo} vuelve a participar en las ganancias de "
                                    f"{exclusion.actividad.codigo}. Motivo: {motivo}",
                        antes=antes, despues=None)
    exclusion.delete()


def excluidos_ids(actividad):
    return set(ExclusionActividad.objects.filter(actividad=actividad).values_list("afiliado_id", flat=True))

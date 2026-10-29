"""Conciliación bancaria: el libro de una cuenta bancaria frente al estado de cuenta del banco.

saldo según libros = saldo según el banco + entradas en tránsito − salidas en tránsito

Las partidas en tránsito son las operaciones del libro que el banco todavía no refleja (por ejemplo, un depósito
hecho el último día o un cheque que no se ha cobrado). Lo que el banco registró y CAUNE no (comisiones, intereses)
se registra primero en Caja como egreso o ingreso; así la conciliación cuadra y los libros quedan completos.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import auditoria
from apps.core.dinero import CERO
from apps.core.models import CuentaFondo
from apps.core.secuencias import siguiente_numero

from . import services
from .models import ConciliacionBancaria

E = ConciliacionBancaria.Estado
CENTAVO = Decimal("0.01")


def conciliadas_antes(cuenta, excluir=None):
    """Números ya conciliados en las conciliaciones cerradas de la cuenta."""
    numeros = set()
    qs = ConciliacionBancaria.objects.filter(cuenta=cuenta, estado=E.CERRADA)
    if excluir is not None:
        qs = qs.exclude(pk=excluir.pk)
    for c in qs:
        numeros.update(c.conciliadas)
    return numeros


@dataclass
class Resultado:
    partidas: list = field(default_factory=list)  # (LineaCaja, marcada)
    saldo_libros: object = CERO
    entradas_transito: object = CERO
    salidas_transito: object = CERO
    saldo_banco_ajustado: object = CERO
    diferencia: object = CERO


def calcular(conc):
    """Partidas pendientes de la cuenta hasta la fecha de corte y el cuadre con el saldo del banco."""
    previas = conciliadas_antes(conc.cuenta, excluir=conc)
    marcadas = set(conc.conciliadas)
    r = Resultado(saldo_libros=services.saldo(conc.cuenta, hasta=conc.fecha_corte))
    for linea in services.lineas(conc.cuenta, hasta=conc.fecha_corte):
        if linea.numero in previas:
            continue
        marcada = linea.numero in marcadas
        r.partidas.append((linea, marcada))
        if not marcada:
            r.entradas_transito += linea.entrada
            r.salidas_transito += linea.salida
    r.saldo_banco_ajustado = conc.saldo_banco + r.entradas_transito - r.salidas_transito
    r.diferencia = r.saldo_libros - r.saldo_banco_ajustado
    return r


def _ultima_cerrada(cuenta):
    return ConciliacionBancaria.objects.filter(cuenta=cuenta, estado=E.CERRADA).order_by("-fecha_corte", "-id").first()


@transaction.atomic
def crear(*, cuenta, fecha_corte, saldo_banco, usuario, observaciones=""):
    if not usuario.has_perm("caja.add_conciliacionbancaria"):
        raise ValidationError("No tiene permiso para registrar conciliaciones bancarias.")
    errores = {}
    if not isinstance(cuenta, CuentaFondo) or cuenta.tipo != CuentaFondo.Tipo.BANCO:
        errores["cuenta"] = "Seleccione una cuenta bancaria."
    if fecha_corte is None or fecha_corte > timezone.localdate():
        errores["fecha_corte"] = "La fecha de corte es obligatoria y no puede ser futura."
    if saldo_banco is None or saldo_banco != saldo_banco.quantize(CENTAVO):
        errores["saldo_banco"] = "Indique el saldo del estado del banco, con un máximo de 2 decimales."
    if errores:
        raise ValidationError(errores)
    CuentaFondo.objects.select_for_update().get(pk=cuenta.pk)
    if ConciliacionBancaria.objects.filter(cuenta=cuenta, estado=E.BORRADOR).exists():
        raise ValidationError({"cuenta": "Ya hay una conciliación en proceso para esta cuenta. Ciérrela o anúlela."})
    ultima = _ultima_cerrada(cuenta)
    if ultima is not None and fecha_corte <= ultima.fecha_corte:
        raise ValidationError({"fecha_corte": f"Debe ser posterior al último corte conciliado "
                                              f"({ultima.fecha_corte:%d/%m/%Y})."})
    conc = ConciliacionBancaria.objects.create(
        numero=siguiente_numero("CB"), cuenta=cuenta, fecha_corte=fecha_corte, saldo_banco=saldo_banco,
        observaciones=(observaciones or "").strip(), registrado_por=usuario)
    auditoria.registrar(auditoria.Accion.CREAR, usuario=usuario, objeto=conc,
                        descripcion=f"Conciliación {conc.numero} de {cuenta.nombre} al {fecha_corte:%d/%m/%Y}",
                        despues=auditoria.instantanea(conc))
    return conc


@transaction.atomic
def guardar_marcas(conc, *, numeros, saldo_banco, usuario):
    """Guarda qué partidas refleja el banco y, si cambió, el saldo del banco."""
    if not usuario.has_perm("caja.change_conciliacionbancaria"):
        raise ValidationError("No tiene permiso para modificar conciliaciones bancarias.")
    conc = ConciliacionBancaria.objects.select_for_update().get(pk=conc.pk)
    if not conc.editable:
        raise ValidationError("La conciliación ya no está en proceso.")
    disponibles = {linea.numero for linea, _ in calcular(conc).partidas}
    numeros = set(numeros)
    if not numeros <= disponibles:
        raise ValidationError("Hay partidas que no pertenecen a esta conciliación. Recargue la página.")
    antes = {"conciliadas": len(conc.conciliadas), "saldo_banco": str(conc.saldo_banco)}
    conc.conciliadas = sorted(numeros)
    if saldo_banco is not None:
        conc.saldo_banco = saldo_banco
    conc.save(update_fields=["conciliadas", "saldo_banco"])
    auditoria.registrar(auditoria.Accion.MODIFICAR, usuario=usuario, objeto=conc,
                        descripcion=f"Partidas marcadas en {conc.numero}", antes=antes,
                        despues={"conciliadas": len(conc.conciliadas), "saldo_banco": str(conc.saldo_banco)})
    return conc


@transaction.atomic
def cerrar(conc, *, usuario):
    if not usuario.has_perm("caja.cerrar_conciliacionbancaria"):
        raise ValidationError("No tiene permiso para cerrar conciliaciones bancarias.")
    conc = ConciliacionBancaria.objects.select_for_update().get(pk=conc.pk)
    if not conc.editable:
        raise ValidationError("La conciliación ya no está en proceso.")
    r = calcular(conc)
    if r.diferencia != 0:
        raise ValidationError(f"No cuadra: diferencia de L {r.diferencia:,.2f}. Revise las partidas marcadas y "
                              "registre en Caja lo que el banco cobró o pagó y aún no está en los libros.")
    # Solo las partidas vigentes: si una se anuló después de marcarla, ya no cuenta.
    conc.conciliadas = sorted(linea.numero for linea, marcada in r.partidas if marcada)
    conc.estado = E.CERRADA
    conc.saldo_libros = r.saldo_libros
    conc.cerrado_por = usuario
    conc.cerrado_en = timezone.now()
    conc.save(update_fields=["conciliadas", "estado", "saldo_libros", "cerrado_por", "cerrado_en"])
    auditoria.registrar(auditoria.Accion.CAMBIO_ESTADO, usuario=usuario, objeto=conc,
                        descripcion=f"Cierre de la conciliación {conc.numero}: saldo L {r.saldo_libros:,.2f}",
                        despues=auditoria.instantanea(conc))
    return conc


@transaction.atomic
def anular(conc, *, usuario, motivo):
    if not usuario.has_perm("caja.anular_conciliacionbancaria"):
        raise ValidationError("No tiene permiso para anular conciliaciones bancarias.")
    motivo = (motivo or "").strip()
    if len(motivo) < 10:
        raise ValidationError({"motivo": "Explique el motivo de la anulación (mínimo 10 caracteres)."})
    conc = ConciliacionBancaria.objects.select_for_update().get(pk=conc.pk)
    if conc.estado == E.ANULADA:
        raise ValidationError("La conciliación ya está anulada.")
    if conc.estado == E.CERRADA and _ultima_cerrada(conc.cuenta).pk != conc.pk:
        raise ValidationError("Solo se puede anular la última conciliación cerrada de la cuenta.")
    antes = auditoria.instantanea(conc)
    conc.estado = E.ANULADA
    conc.anulado_por = usuario
    conc.anulado_en = timezone.now()
    conc.motivo_anulacion = motivo
    conc.save(update_fields=["estado", "anulado_por", "anulado_en", "motivo_anulacion"])
    auditoria.registrar(auditoria.Accion.ANULAR, usuario=usuario, objeto=conc,
                        descripcion=f"Anulación de la conciliación {conc.numero}. Motivo: {motivo}", antes=antes,
                        despues=auditoria.instantanea(conc))
    return conc

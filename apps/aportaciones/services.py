"""Reglas de negocio de aportaciones, depósitos y retiros.

Los saldos NUNCA se guardan: siempre se calculan a partir de los movimientos confirmados.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Case, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.afiliados.models import Afiliado
from apps.core import auditoria, parametros
from apps.core.dinero import CERO, redondear
from apps.core.models import CuentaFondo
from apps.core.secuencias import siguiente_numero

from .models import MetodoPago, MovimientoAfiliado, TipoMovimiento

Clase = TipoMovimiento.Clase
Naturaleza = TipoMovimiento.Naturaleza
_DECIMAL = DecimalField(max_digits=16, decimal_places=2)


def _monto_con_signo(prefijo=""):
    return Case(
        When(**{f"{prefijo}tipo__naturaleza": Naturaleza.SALIDA}, then=F(f"{prefijo}monto") * Value(-1)),
        default=F(f"{prefijo}monto"),
        output_field=_DECIMAL,
    )


def _suma(filtro, prefijo=""):
    return Coalesce(Sum(_monto_con_signo(prefijo), filter=filtro), Value(CERO), output_field=_DECIMAL)


# --------------------------------------------------------------------------- saldos

def saldos_afiliado(afiliado, hasta=None):
    qs = MovimientoAfiliado.objects.confirmados().filter(afiliado=afiliado)
    if hasta is not None:
        qs = qs.filter(fecha__lte=hasta)
    datos = qs.aggregate(
        aportaciones=_suma(Q(tipo__clase=Clase.APORTACION)),
        depositos=_suma(Q(tipo__clase=Clase.DEPOSITO)),
    )
    aportaciones, depositos = redondear(datos["aportaciones"]), redondear(datos["depositos"])
    return {"aportaciones": aportaciones, "depositos": depositos, "total": aportaciones + depositos}


def anotar_saldos(queryset_afiliados):
    """Agrega saldo_aportaciones y saldo_depositos a cada afiliado del queryset."""
    confirmado = Q(movimientos__estado=MovimientoAfiliado.Estado.CONFIRMADO)
    return queryset_afiliados.annotate(
        saldo_aportaciones=_suma(confirmado & Q(movimientos__tipo__clase=Clase.APORTACION), "movimientos__"),
        saldo_depositos=_suma(confirmado & Q(movimientos__tipo__clase=Clase.DEPOSITO), "movimientos__"),
    )


def totales_generales(hasta=None):
    qs = MovimientoAfiliado.objects.confirmados()
    if hasta is not None:
        qs = qs.filter(fecha__lte=hasta)
    datos = qs.aggregate(
        aportaciones=_suma(Q(tipo__clase=Clase.APORTACION)),
        depositos=_suma(Q(tipo__clase=Clase.DEPOSITO)),
    )
    return {k: redondear(v) for k, v in datos.items()}


def _saldo_minimo_diario(afiliado, clase, excluir_pk=None, adicional=None):
    """Saldo más bajo al cierre de cualquier día, considerando un cambio hipotético.

    Garantiza que ningún retiro (incluso con fecha anterior) ni anulación deje un saldo
    negativo en algún momento del historial.
    """
    qs = MovimientoAfiliado.objects.confirmados().filter(afiliado=afiliado, tipo__clase=clase)
    if excluir_pk is not None:
        qs = qs.exclude(pk=excluir_pk)
    netos = defaultdict(lambda: CERO)
    for fila in qs.values("fecha").annotate(neto=Sum(_monto_con_signo())).order_by("fecha"):
        netos[fila["fecha"]] += redondear(fila["neto"])
    if adicional is not None:
        netos[adicional[0]] += adicional[1]
    acumulado, minimo = CERO, CERO
    for dia in sorted(netos):
        acumulado += netos[dia]
        minimo = min(minimo, acumulado)
    return minimo


# --------------------------------------------------------------------------- registro

METODOS_CAJA = {MetodoPago.EFECTIVO}
METODOS_BANCO = {MetodoPago.TRANSFERENCIA, MetodoPago.DEPOSITO_BANCARIO}
METODOS_CON_REFERENCIA = {MetodoPago.TRANSFERENCIA, MetodoPago.DEPOSITO_BANCARIO, MetodoPago.CHEQUE}


def _validar_monto(monto):
    if monto is None:
        raise ValidationError({"monto": "Indique el monto."})
    monto = Decimal(str(monto))
    if not monto.is_finite() or monto <= 0:
        raise ValidationError({"monto": "El monto debe ser mayor que cero."})
    if monto.as_tuple().exponent < -2:
        raise ValidationError({"monto": "El monto admite como máximo dos decimales."})
    if monto >= Decimal("1000000000000"):
        raise ValidationError({"monto": "El monto excede el máximo permitido."})
    return monto.quantize(Decimal("0.01"))


def registrar_movimiento(*, afiliado, tipo, fecha, monto, metodo_pago, cuenta_fondo, usuario,
                         clave_idempotencia=None, referencia="", observacion=""):
    """Registra un movimiento confirmado. Devuelve (movimiento, creado).

    Si la misma clave de idempotencia ya fue usada (doble clic, reenvío del formulario),
    devuelve el movimiento existente sin crear otro.
    """
    if not usuario.has_perm("aportaciones.add_movimientoafiliado"):
        raise ValidationError("No tiene permiso para registrar movimientos.")
    if clave_idempotencia is not None:
        existente = MovimientoAfiliado.objects.filter(clave_idempotencia=clave_idempotencia).first()
        if existente is not None:
            return existente, False

    monto = _validar_monto(monto)
    referencia = (referencia or "").strip()
    observacion = (observacion or "").strip()
    errores = {}
    if fecha is None:
        errores["fecha"] = "Indique la fecha."
    elif fecha > timezone.localdate():
        errores["fecha"] = "La fecha no puede ser futura."
    if not isinstance(tipo, TipoMovimiento) or not tipo.activo:
        errores["tipo"] = "Seleccione un tipo de movimiento activo."
    if not isinstance(cuenta_fondo, CuentaFondo) or not cuenta_fondo.activa:
        errores["cuenta_fondo"] = "Seleccione una caja o cuenta activa."
    if metodo_pago not in MetodoPago.values:
        errores["metodo_pago"] = "Método de pago inválido."
    elif isinstance(cuenta_fondo, CuentaFondo):
        if metodo_pago in METODOS_CAJA and cuenta_fondo.tipo != CuentaFondo.Tipo.CAJA:
            errores["cuenta_fondo"] = "Un pago en efectivo debe registrarse en una caja."
        if metodo_pago in METODOS_BANCO and cuenta_fondo.tipo != CuentaFondo.Tipo.BANCO:
            errores["cuenta_fondo"] = "Una transferencia o depósito bancario debe registrarse en una cuenta bancaria."
    if metodo_pago in METODOS_CON_REFERENCIA and not referencia:
        errores["referencia"] = "Indique la referencia del documento bancario o cheque."
    if errores:
        raise ValidationError(errores)

    with transaction.atomic():
        # Bloquea al afiliado: serializa operaciones simultáneas sobre su saldo.
        try:
            afiliado = Afiliado.objects.select_for_update().get(pk=getattr(afiliado, "pk", afiliado))
        except Afiliado.DoesNotExist:
            raise ValidationError({"afiliado": "El afiliado no existe."}) from None
        if not afiliado.activo and not parametros.obtener("afiliados.permitir_movimientos_inactivos"):
            raise ValidationError({"afiliado": "El afiliado está inactivo; no admite nuevos movimientos."})
        if fecha < afiliado.fecha_ingreso:
            raise ValidationError({"fecha": "La fecha es anterior a la fecha de ingreso del afiliado."})
        if tipo.es_retiro:
            if tipo.clase == Clase.APORTACION and not parametros.obtener("movimientos.permitir_retiro_aportaciones"):
                raise ValidationError({"tipo": "Las aportaciones no son retirables según la configuración vigente."})
            if _saldo_minimo_diario(afiliado, tipo.clase, adicional=(fecha, -monto)) < 0:
                disponible = saldos_afiliado(afiliado)[
                    "aportaciones" if tipo.clase == Clase.APORTACION else "depositos"]
                raise ValidationError({"monto": f"Saldo insuficiente para el retiro (saldo actual: L {disponible:,.2f}, "
                                                f"sin quedar negativo en ninguna fecha)."})
        try:
            with transaction.atomic():
                movimiento = MovimientoAfiliado.objects.create(
                    numero_operacion=siguiente_numero("OP"),
                    afiliado=afiliado, tipo=tipo, fecha=fecha, monto=monto, metodo_pago=metodo_pago,
                    cuenta_fondo=cuenta_fondo, referencia=referencia, observacion=observacion,
                    registrado_por=usuario,
                    **({"clave_idempotencia": clave_idempotencia} if clave_idempotencia else {}),
                )
        except IntegrityError:
            existente = MovimientoAfiliado.objects.filter(clave_idempotencia=clave_idempotencia).first()
            if existente is not None:
                return existente, False
            raise
        auditoria.registrar(auditoria.Accion.CREAR, usuario=usuario, objeto=movimiento,
                            descripcion=f"{tipo.nombre} {movimiento.numero_operacion} a {afiliado.codigo}",
                            despues=auditoria.instantanea(movimiento))
    return movimiento, True


@transaction.atomic
def anular_movimiento(movimiento, *, motivo, usuario):
    if not usuario.has_perm("aportaciones.anular_movimientoafiliado"):
        raise ValidationError("No tiene permiso para anular movimientos.")
    motivo = (motivo or "").strip()
    if len(motivo) < 10:
        raise ValidationError({"motivo": "Explique el motivo de la anulación (mínimo 10 caracteres)."})
    Afiliado.objects.select_for_update().get(pk=movimiento.afiliado_id)
    movimiento = MovimientoAfiliado.objects.select_for_update().select_related("tipo").get(pk=movimiento.pk)
    if not movimiento.confirmado:
        raise ValidationError("El movimiento ya está anulado.")
    if (parametros.obtener("movimientos.anulacion_requiere_otro_usuario")
            and movimiento.registrado_por_id == usuario.pk):
        raise ValidationError("La anulación debe autorizarla un usuario distinto al que registró la operación.")
    if not movimiento.tipo.es_retiro:
        if _saldo_minimo_diario(movimiento.afiliado, movimiento.tipo.clase, excluir_pk=movimiento.pk) < 0:
            raise ValidationError("No se puede anular: hay retiros posteriores que dependen de este movimiento. "
                                  "Anule primero esos retiros.")
    antes = auditoria.instantanea(movimiento)
    movimiento.estado = MovimientoAfiliado.Estado.ANULADO
    movimiento.anulado_por = usuario
    movimiento.anulado_en = timezone.now()
    movimiento.motivo_anulacion = motivo
    movimiento.save(update_fields=["estado", "anulado_por", "anulado_en", "motivo_anulacion"])
    auditoria.registrar(auditoria.Accion.ANULAR, usuario=usuario, objeto=movimiento,
                        descripcion=f"Anulación de {movimiento.numero_operacion}. Motivo: {motivo}",
                        antes=antes, despues=auditoria.instantanea(movimiento))
    return movimiento


# --------------------------------------------------------------------------- estado de cuenta

@dataclass
class EstadoCuenta:
    afiliado: Afiliado
    desde: object
    hasta: object
    saldo_inicial: dict
    lineas: list = field(default_factory=list)
    totales: dict = field(default_factory=dict)
    saldo_final: dict = field(default_factory=dict)


def estado_cuenta(afiliado, desde=None, hasta=None):
    hasta = hasta or timezone.localdate()
    if desde is not None and desde > hasta:
        raise ValidationError("La fecha inicial no puede ser posterior a la final.")
    if desde is not None:
        saldo_inicial = saldos_afiliado(afiliado, hasta=desde - timedelta(days=1))
    else:
        saldo_inicial = {"aportaciones": CERO, "depositos": CERO, "total": CERO}
    qs = (MovimientoAfiliado.objects.confirmados().filter(afiliado=afiliado, fecha__lte=hasta)
          .select_related("tipo", "cuenta_fondo").order_by("fecha", "id"))
    if desde is not None:
        qs = qs.filter(fecha__gte=desde)

    saldo_ap, saldo_dep = saldo_inicial["aportaciones"], saldo_inicial["depositos"]
    totales = {"entradas_aportaciones": CERO, "retiros_aportaciones": CERO,
               "entradas_depositos": CERO, "retiros_depositos": CERO}
    lineas = []
    for mov in qs:
        es_aportacion = mov.tipo.clase == Clase.APORTACION
        clave = ("retiros_" if mov.tipo.es_retiro else "entradas_") + ("aportaciones" if es_aportacion else "depositos")
        totales[clave] += mov.monto
        if es_aportacion:
            saldo_ap += mov.monto_con_signo
        else:
            saldo_dep += mov.monto_con_signo
        lineas.append({"movimiento": mov, "es_aportacion": es_aportacion, "entrada": None if mov.tipo.es_retiro else mov.monto,
                       "salida": mov.monto if mov.tipo.es_retiro else None,
                       "saldo_aportaciones": saldo_ap, "saldo_depositos": saldo_dep, "saldo_total": saldo_ap + saldo_dep})
    return EstadoCuenta(afiliado=afiliado, desde=desde, hasta=hasta, saldo_inicial=saldo_inicial, lineas=lineas,
                        totales=totales,
                        saldo_final={"aportaciones": saldo_ap, "depositos": saldo_dep, "total": saldo_ap + saldo_dep})


# --------------------------------------------------------------------------- tipos

TIPOS_INICIALES = [
    dict(codigo="APO", nombre="Aportación", clase=Clase.APORTACION, naturaleza=Naturaleza.ENTRADA,
         participa_distribucion=True, descripcion="Aportación de capital del afiliado (no retirable)."),
    dict(codigo="DEP", nombre="Depósito reembolsable", clase=Clase.DEPOSITO, naturaleza=Naturaleza.ENTRADA,
         participa_distribucion=False, descripcion="Ahorro del afiliado que puede retirar."),
    dict(codigo="RDEP", nombre="Retiro de depósito", clase=Clase.DEPOSITO, naturaleza=Naturaleza.SALIDA,
         participa_distribucion=False, descripcion="Devolución de depósitos reembolsables al afiliado."),
]


def asegurar_tipos_iniciales():
    for datos in TIPOS_INICIALES:
        TipoMovimiento.objects.get_or_create(codigo=datos["codigo"], defaults=datos)


def tipo_tiene_movimientos(tipo):
    return tipo.pk is not None and MovimientoAfiliado.objects.filter(tipo=tipo).exists()

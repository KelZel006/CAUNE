"""Reglas de negocio de préstamos.

Decisiones de CAUNE aplicadas (08/10/2026):
- P1: las tasas son mensuales (interno 1 %, externo 5 %, editables con historial).
- P2: interés de cada cuota = saldo de capital × tasa mensual.
- P4: se aceptan pagos parciales; cada pago cubre primero el interés y luego el capital, cuota por cuota.
- P5: un abono extraordinario NO modifica el cuadro aprobado: se aplica al capital pendiente de las cuotas
  siguientes, en orden de vencimiento. Los intereses de esas cuotas siguen siendo exigibles en su fecha.

Los saldos no se guardan: se calculan desde el cuadro aprobado y las aplicaciones de pagos confirmados.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import DecimalField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.afiliados.models import Afiliado
from apps.aportaciones.models import MetodoPago
from apps.aportaciones.services import METODOS_BANCO, METODOS_CAJA, METODOS_CON_REFERENCIA, _validar_monto
from apps.core import auditoria, parametros
from apps.core.dinero import CERO, redondear
from apps.core.models import CuentaFondo
from apps.core.secuencias import siguiente_numero

from . import amortizacion
from .models import AplicacionPago, CuotaAmortizacion, PagoPrestamo, Prestamo, PrestatarioExterno

_DEC = DecimalField(max_digits=16, decimal_places=2)
CONFIRMADO = PagoPrestamo.Estado.CONFIRMADO


# --------------------------------------------------------------------------- configuración vigente

def tasa_configurada(tipo_prestatario):
    clave = "prestamos.tasa_interna" if tipo_prestatario == Prestamo.Tipo.INTERNO else "prestamos.tasa_externa"
    return parametros.obtener(clave)


def metodos_permitidos():
    return [m.strip() for m in parametros.obtener("prestamos.metodos_permitidos").split(",") if m.strip()]


def simular(monto, tasa, plazo, metodo, primer_vencimiento):
    filas = amortizacion.generar_cuadro(monto, tasa, plazo, metodo, primer_vencimiento)
    return filas, amortizacion.totales_cuadro(filas)


# --------------------------------------------------------------------------- validaciones comunes

def _validar_cuenta_metodo(metodo_pago, cuenta, referencia, errores, campo_cuenta="cuenta_fondo"):
    if not isinstance(cuenta, CuentaFondo) or not cuenta.activa:
        errores[campo_cuenta] = "Seleccione una caja o cuenta activa."
        return
    if metodo_pago not in MetodoPago.values:
        errores["metodo_pago"] = "Método de pago inválido."
    elif metodo_pago in METODOS_CAJA and cuenta.tipo != CuentaFondo.Tipo.CAJA:
        errores[campo_cuenta] = "El efectivo debe registrarse en una caja."
    elif metodo_pago in METODOS_BANCO and cuenta.tipo != CuentaFondo.Tipo.BANCO:
        errores[campo_cuenta] = "Una transferencia o depósito bancario debe registrarse en una cuenta bancaria."
    if metodo_pago in METODOS_CON_REFERENCIA and not (referencia or "").strip():
        errores["referencia"] = "Indique la referencia del documento bancario o cheque."


# --------------------------------------------------------------------------- aprobación

@transaction.atomic
def aprobar_prestamo(*, usuario, tipo_prestatario, monto_solicitado, monto_aprobado, plazo, metodo_amortizacion,
                     fecha_aprobacion, fecha_primer_vencimiento, afiliado=None, externo=None, tasa=None,
                     motivo_excepcion="", observaciones=""):
    """Registra un préstamo aprobado con sus condiciones congeladas y su cuadro de amortización.

    `externo` es un dict (nombre_completo, identidad, telefono, direccion) para prestatarios externos;
    si la identidad ya existe se reutiliza el registro.
    """
    if not usuario.has_perm("prestamos.add_prestamo"):
        raise ValidationError("No tiene permiso para registrar préstamos.")
    errores = {}
    hoy = timezone.localdate()
    if tipo_prestatario not in Prestamo.Tipo.values:
        raise ValidationError({"tipo_prestatario": "Tipo de prestatario inválido."})
    try:
        monto_solicitado = _validar_monto(monto_solicitado)
    except ValidationError:
        errores["monto_solicitado"] = "Indique un monto solicitado válido (mayor que cero, máximo 2 decimales)."
    try:
        monto_aprobado = _validar_monto(monto_aprobado)
    except ValidationError:
        errores["monto_aprobado"] = "Indique un monto aprobado válido (mayor que cero, máximo 2 decimales)."
    if "monto_solicitado" not in errores and "monto_aprobado" not in errores and monto_aprobado > monto_solicitado:
        errores["monto_aprobado"] = "El monto aprobado no puede ser mayor que el solicitado."
    plazo_maximo = parametros.obtener("prestamos.plazo_maximo")
    if not plazo or plazo < 1 or plazo > plazo_maximo:
        errores["plazo"] = f"El plazo debe estar entre 1 y {plazo_maximo} cuotas."
    if metodo_amortizacion not in metodos_permitidos():
        errores["metodo_amortizacion"] = "Ese método de amortización no está permitido en la configuración."
    if parametros.obtener("prestamos.periodicidad_tasa") != Prestamo.Periodicidad.MENSUAL:
        errores["__all__"] = "La periodicidad configurada no es soportada por el cálculo."
    if fecha_aprobacion is None or fecha_aprobacion > hoy:
        errores["fecha_aprobacion"] = "La fecha de aprobación es obligatoria y no puede ser futura."
    if fecha_primer_vencimiento is None or (fecha_aprobacion and fecha_primer_vencimiento <= fecha_aprobacion):
        errores["fecha_primer_vencimiento"] = "El primer vencimiento debe ser posterior a la aprobación."

    configurada = tasa_configurada(tipo_prestatario)
    tasa = configurada if tasa is None or tasa == "" else Decimal(str(tasa))
    es_excepcion = tasa != configurada
    motivo_excepcion = (motivo_excepcion or "").strip()
    if tasa < 0 or tasa > 100:
        errores["tasa"] = "La tasa debe estar entre 0 y 100 % mensual."
    elif es_excepcion:
        if not parametros.obtener("prestamos.permitir_excepcion_tasa"):
            errores["tasa"] = f"La configuración no permite excepciones: la tasa vigente es {configurada} % mensual."
        elif not usuario.has_perm("prestamos.autorizar_excepcion_tasa"):
            errores["tasa"] = "No tiene permiso para autorizar una tasa distinta a la configurada."
        elif len(motivo_excepcion) < 10:
            errores["motivo_excepcion"] = "Explique la excepción de tasa (mínimo 10 caracteres)."

    prestatario = {}
    if tipo_prestatario == Prestamo.Tipo.INTERNO:
        if afiliado is None:
            errores["afiliado"] = "Seleccione el afiliado."
        else:
            afiliado = Afiliado.objects.select_for_update().get(pk=getattr(afiliado, "pk", afiliado))
            if not afiliado.activo:
                errores["afiliado"] = "El afiliado está inactivo; no puede recibir préstamos."
            prestatario["afiliado"] = afiliado
    else:
        externo = externo or {}
        identidad = (externo.get("identidad") or "").replace("-", "").strip()
        nombre = " ".join((externo.get("nombre_completo") or "").split())
        if len(identidad) != 13 or not identidad.isdigit():
            errores["externo_identidad"] = "La identidad del prestatario externo debe tener 13 dígitos."
        if len(nombre) < 5:
            errores["externo_nombre"] = "Indique el nombre completo del prestatario externo."
        if not errores.get("externo_identidad") and Afiliado.objects.filter(identidad=identidad).exists():
            errores["externo_identidad"] = "Esa identidad pertenece a un afiliado: registre un préstamo interno."
    if errores:
        raise ValidationError(errores)

    if tipo_prestatario == Prestamo.Tipo.EXTERNO:
        registro, _ = PrestatarioExterno.objects.get_or_create(
            identidad=identidad,
            defaults={"nombre_completo": nombre, "telefono": (externo.get("telefono") or "").strip(),
                      "direccion": (externo.get("direccion") or "").strip(), "creado_por": usuario})
        prestatario["prestatario_externo"] = registro

    filas = amortizacion.generar_cuadro(monto_aprobado, tasa, plazo, metodo_amortizacion, fecha_primer_vencimiento)
    prestamo = Prestamo.objects.create(
        numero=siguiente_numero("PREST"), tipo_prestatario=tipo_prestatario, monto_solicitado=monto_solicitado,
        monto_aprobado=monto_aprobado, tasa=tasa, tasa_configurada=configurada,
        periodicidad_tasa=Prestamo.Periodicidad.MENSUAL, tasa_es_excepcion=es_excepcion,
        motivo_excepcion=motivo_excepcion if es_excepcion else "",
        excepcion_autorizada_por=usuario if es_excepcion else None, metodo_amortizacion=metodo_amortizacion,
        plazo=plazo, frecuencia_pago=Prestamo.Frecuencia.MENSUAL, fecha_aprobacion=fecha_aprobacion,
        fecha_primer_vencimiento=fecha_primer_vencimiento, observaciones=(observaciones or "").strip(),
        registrado_por=usuario, **prestatario,
    )
    CuotaAmortizacion.objects.bulk_create([
        CuotaAmortizacion(prestamo=prestamo, numero=f.numero, fecha_vencimiento=f.fecha_vencimiento,
                          saldo_inicial=f.saldo_inicial, capital=f.capital, interes=f.interes, cuota=f.cuota,
                          saldo_final=f.saldo_final)
        for f in filas
    ])
    auditoria.registrar(auditoria.Accion.CREAR, usuario=usuario, objeto=prestamo,
                        descripcion=f"Aprobación de {prestamo.numero} a {prestamo.prestatario_nombre}"
                                    + (f" con tasa de excepción {tasa} %. Motivo: {motivo_excepcion}" if es_excepcion else ""),
                        despues=auditoria.instantanea(prestamo))
    return prestamo


@transaction.atomic
def desembolsar(prestamo, *, usuario, fecha, cuenta, metodo_pago, referencia=""):
    if not usuario.has_perm("prestamos.desembolsar_prestamo"):
        raise ValidationError("No tiene permiso para registrar desembolsos.")
    prestamo = Prestamo.objects.select_for_update().get(pk=prestamo.pk)
    if prestamo.estado != Prestamo.Estado.APROBADO:
        raise ValidationError("Solo se desembolsan préstamos aprobados que aún no se han desembolsado.")
    errores = {}
    if fecha is None or fecha > timezone.localdate():
        errores["fecha"] = "La fecha de desembolso es obligatoria y no puede ser futura."
    elif fecha < prestamo.fecha_aprobacion:
        errores["fecha"] = "El desembolso no puede ser anterior a la aprobación."
    elif fecha >= prestamo.fecha_primer_vencimiento:
        errores["fecha"] = "El desembolso debe ser anterior al primer vencimiento del cuadro aprobado."
    _validar_cuenta_metodo(metodo_pago, cuenta, referencia, errores, campo_cuenta="cuenta")
    if errores:
        raise ValidationError(errores)
    antes = auditoria.instantanea(prestamo)
    prestamo.fecha_desembolso = fecha
    prestamo.cuenta_desembolso = cuenta
    prestamo.referencia_desembolso = (referencia or "").strip()
    prestamo.desembolsado_por = usuario
    prestamo.estado = Prestamo.Estado.VIGENTE
    prestamo.save(update_fields=["fecha_desembolso", "cuenta_desembolso", "referencia_desembolso", "desembolsado_por",
                                 "estado"])
    auditoria.registrar(auditoria.Accion.CAMBIO_ESTADO, usuario=usuario, objeto=prestamo,
                        descripcion=f"Desembolso de {prestamo.numero} por L {prestamo.monto_aprobado:,.2f}",
                        antes=antes, despues=auditoria.instantanea(prestamo))
    return prestamo


@transaction.atomic
def anular_prestamo(prestamo, *, usuario, motivo):
    if not usuario.has_perm("prestamos.anular_prestamo"):
        raise ValidationError("No tiene permiso para anular préstamos.")
    motivo = (motivo or "").strip()
    if len(motivo) < 10:
        raise ValidationError({"motivo": "Explique el motivo de la anulación (mínimo 10 caracteres)."})
    prestamo = Prestamo.objects.select_for_update().get(pk=prestamo.pk)
    if prestamo.estado != Prestamo.Estado.APROBADO:
        raise ValidationError("Solo se anulan préstamos que aún no se han desembolsado.")
    antes = auditoria.instantanea(prestamo)
    prestamo.estado = Prestamo.Estado.ANULADO
    prestamo.anulado_por = usuario
    prestamo.anulado_en = timezone.now()
    prestamo.motivo_anulacion = motivo
    prestamo.save(update_fields=["estado", "anulado_por", "anulado_en", "motivo_anulacion"])
    auditoria.registrar(auditoria.Accion.ANULAR, usuario=usuario, objeto=prestamo,
                        descripcion=f"Anulación de {prestamo.numero}. Motivo: {motivo}", antes=antes,
                        despues=auditoria.instantanea(prestamo))
    return prestamo


# --------------------------------------------------------------------------- estado de cuenta del préstamo

@dataclass
class EstadoCuota:
    cuota: CuotaAmortizacion
    interes_pagado: Decimal
    capital_pagado: Decimal

    @property
    def interes_pendiente(self):
        return self.cuota.interes - self.interes_pagado

    @property
    def capital_pendiente(self):
        return self.cuota.capital - self.capital_pagado

    @property
    def pendiente(self):
        return self.interes_pendiente + self.capital_pendiente

    @property
    def estado(self):
        if self.pendiente == 0:
            return "PAGADA"
        if self.interes_pagado or self.capital_pagado:
            return "PARCIAL"
        return "PENDIENTE"


@dataclass
class ResumenPrestamo:
    cuotas: list = field(default_factory=list)
    capital_pagado: Decimal = CERO
    saldo_capital: Decimal = CERO
    intereses_cobrados: Decimal = CERO
    intereses_pendientes: Decimal = CERO
    total_pendiente: Decimal = CERO
    cuotas_pagadas: int = 0
    proxima: EstadoCuota | None = None


def estado_cuotas(prestamo):
    pagado = {
        f["cuota_id"]: (f["i"], f["c"])
        for f in AplicacionPago.objects.filter(cuota__prestamo=prestamo, pago__estado=CONFIRMADO)
        .values("cuota_id").annotate(i=Sum("interes"), c=Sum("capital"))
    }
    return [EstadoCuota(c, redondear(pagado.get(c.pk, (CERO, CERO))[0]), redondear(pagado.get(c.pk, (CERO, CERO))[1]))
            for c in prestamo.cuotas.order_by("numero")]


def resumen(prestamo):
    cuotas = estado_cuotas(prestamo)
    r = ResumenPrestamo(cuotas=cuotas)
    r.capital_pagado = sum((c.capital_pagado for c in cuotas), CERO)
    r.saldo_capital = prestamo.monto_aprobado - r.capital_pagado
    r.intereses_cobrados = sum((c.interes_pagado for c in cuotas), CERO)
    r.intereses_pendientes = sum((c.interes_pendiente for c in cuotas), CERO)
    r.total_pendiente = r.saldo_capital + r.intereses_pendientes
    r.cuotas_pagadas = sum(1 for c in cuotas if c.estado == "PAGADA")
    r.proxima = next((c for c in cuotas if c.pendiente > 0), None)
    return r


def anotar_saldos(queryset):
    """Agrega capital_pagado, intereses_cobrados y saldo_capital a cada préstamo (sin multiplicar filas)."""
    base = AplicacionPago.objects.filter(cuota__prestamo=OuterRef("pk"), pago__estado=CONFIRMADO).values("cuota__prestamo")
    capital = base.annotate(t=Sum("capital")).values("t")
    interes = base.annotate(t=Sum("interes")).values("t")
    interes_total = (CuotaAmortizacion.objects.filter(prestamo=OuterRef("pk")).values("prestamo")
                     .annotate(t=Sum("interes")).values("t"))
    return queryset.annotate(
        capital_pagado=Coalesce(Subquery(capital, output_field=_DEC), Value(CERO), output_field=_DEC),
        intereses_cobrados=Coalesce(Subquery(interes, output_field=_DEC), Value(CERO), output_field=_DEC),
        intereses_cuadro=Coalesce(Subquery(interes_total, output_field=_DEC), Value(CERO), output_field=_DEC),
    )


def cartera_vigente():
    qs = anotar_saldos(Prestamo.objects.filter(estado=Prestamo.Estado.VIGENTE))
    total = CERO
    for p in qs:
        total += p.monto_aprobado - p.capital_pagado
    return redondear(total)


def intereses_cobrados(desde=None, hasta=None):
    qs = AplicacionPago.objects.filter(pago__estado=CONFIRMADO)
    if desde:
        qs = qs.filter(pago__fecha__gte=desde)
    if hasta:
        qs = qs.filter(pago__fecha__lte=hasta)
    return redondear(qs.aggregate(t=Coalesce(Sum("interes"), Value(CERO), output_field=_DEC))["t"])


# --------------------------------------------------------------------------- pagos

def _distribuir(cuotas, monto, tipo):
    """Reparte el monto entre las cuotas pendientes en orden. Devuelve [(cuota, interes, capital), ...]."""
    restante = monto
    aplicaciones = []
    for ec in cuotas:
        if restante <= 0:
            break
        interes = capital = CERO
        if tipo == PagoPrestamo.Tipo.PAGO and ec.interes_pendiente > 0:
            interes = min(restante, ec.interes_pendiente)
            restante -= interes
        if restante > 0 and ec.capital_pendiente > 0:
            capital = min(restante, ec.capital_pendiente)
            restante -= capital
        if interes or capital:
            aplicaciones.append((ec, interes, capital))
    return aplicaciones, restante


def registrar_pago(prestamo, *, usuario, tipo, fecha, monto, metodo_pago, cuenta_fondo, referencia="", observacion="",
                   clave_idempotencia=None):
    """Registra un pago de cuota o un abono a capital. Devuelve (pago, creado)."""
    if not usuario.has_perm("prestamos.add_pagoprestamo"):
        raise ValidationError("No tiene permiso para registrar pagos.")
    if clave_idempotencia is not None:
        existente = PagoPrestamo.objects.filter(clave_idempotencia=clave_idempotencia).first()
        if existente is not None:
            return existente, False
    monto = _validar_monto(monto)
    errores = {}
    if tipo not in PagoPrestamo.Tipo.values:
        errores["tipo"] = "Tipo de pago inválido."
    if fecha is None or fecha > timezone.localdate():
        errores["fecha"] = "La fecha del pago es obligatoria y no puede ser futura."
    _validar_cuenta_metodo(metodo_pago, cuenta_fondo, referencia, errores)
    if errores:
        raise ValidationError(errores)

    with transaction.atomic():
        prestamo = Prestamo.objects.select_for_update().get(pk=prestamo.pk)
        if prestamo.estado != Prestamo.Estado.VIGENTE:
            raise ValidationError("Solo se registran pagos en préstamos vigentes (desembolsados y no cancelados).")
        if fecha < prestamo.fecha_desembolso:
            raise ValidationError({"fecha": "El pago no puede ser anterior al desembolso."})
        ultimo = prestamo.pagos.filter(estado=CONFIRMADO).order_by("-fecha", "-id").first()
        if ultimo is not None and fecha < ultimo.fecha:
            raise ValidationError({"fecha": f"Ya existe un pago posterior ({ultimo.fecha:%d/%m/%Y}); "
                                            "registre los pagos en orden de fecha."})
        cuotas = [c for c in estado_cuotas(prestamo) if c.pendiente > 0]
        r = resumen(prestamo)
        if tipo == PagoPrestamo.Tipo.ABONO_CAPITAL:
            if monto > r.saldo_capital:
                raise ValidationError({"monto": f"El abono excede el saldo de capital (L {r.saldo_capital:,.2f})."})
        elif monto > r.total_pendiente:
            raise ValidationError({"monto": f"El pago excede el total pendiente del préstamo (L {r.total_pendiente:,.2f})."})
        aplicaciones, restante = _distribuir(cuotas, monto, tipo)
        assert restante == 0
        if tipo == PagoPrestamo.Tipo.PAGO and not parametros.obtener("prestamos.permitir_pagos_parciales"):
            ultima_ec, i, c = aplicaciones[-1]
            if i + c != ultima_ec.pendiente:
                raise ValidationError({"monto": "La configuración no permite pagos parciales: el monto debe cubrir "
                                                "cuotas completas."})
        try:
            with transaction.atomic():
                pago = PagoPrestamo.objects.create(
                    numero_recibo=siguiente_numero("PAG"), prestamo=prestamo, tipo=tipo, fecha=fecha, monto=monto,
                    metodo_pago=metodo_pago, cuenta_fondo=cuenta_fondo, referencia=(referencia or "").strip(),
                    observacion=(observacion or "").strip(), registrado_por=usuario,
                    **({"clave_idempotencia": clave_idempotencia} if clave_idempotencia else {}),
                )
        except IntegrityError:
            existente = PagoPrestamo.objects.filter(clave_idempotencia=clave_idempotencia).first()
            if existente is not None:
                return existente, False
            raise
        AplicacionPago.objects.bulk_create([AplicacionPago(pago=pago, cuota=ec.cuota, interes=i, capital=c)
                                            for ec, i, c in aplicaciones])
        if resumen(prestamo).total_pendiente == 0:
            prestamo.estado = Prestamo.Estado.PAGADO
            prestamo.save(update_fields=["estado"])
        auditoria.registrar(auditoria.Accion.CREAR, usuario=usuario, objeto=pago,
                            descripcion=f"{pago.get_tipo_display()} {pago.numero_recibo} al préstamo {prestamo.numero}",
                            despues={**auditoria.instantanea(pago),
                                     "aplicaciones": [{"cuota": ec.cuota.numero, "interes": str(i), "capital": str(c)}
                                                      for ec, i, c in aplicaciones]})
    return pago, True


@transaction.atomic
def anular_pago(pago, *, usuario, motivo):
    """Anula un pago. Solo el último pago confirmado del préstamo, para no desordenar la aplicación de los demás."""
    if not usuario.has_perm("prestamos.anular_pagoprestamo"):
        raise ValidationError("No tiene permiso para anular pagos.")
    motivo = (motivo or "").strip()
    if len(motivo) < 10:
        raise ValidationError({"motivo": "Explique el motivo de la anulación (mínimo 10 caracteres)."})
    prestamo = Prestamo.objects.select_for_update().get(pk=pago.prestamo_id)
    pago = PagoPrestamo.objects.select_for_update().get(pk=pago.pk)
    if not pago.confirmado:
        raise ValidationError("El pago ya está anulado.")
    if (parametros.obtener("movimientos.anulacion_requiere_otro_usuario") and pago.registrado_por_id == usuario.pk):
        raise ValidationError("La anulación debe autorizarla un usuario distinto al que registró el pago.")
    ultimo = prestamo.pagos.filter(estado=CONFIRMADO).order_by("-fecha", "-id").first()
    if ultimo.pk != pago.pk:
        raise ValidationError(f"Solo puede anularse el último pago del préstamo ({ultimo.numero_recibo}). "
                              "Anule primero los pagos posteriores.")
    antes = auditoria.instantanea(pago)
    pago.estado = PagoPrestamo.Estado.ANULADO
    pago.anulado_por = usuario
    pago.anulado_en = timezone.now()
    pago.motivo_anulacion = motivo
    pago.save(update_fields=["estado", "anulado_por", "anulado_en", "motivo_anulacion"])
    if prestamo.estado == Prestamo.Estado.PAGADO:
        prestamo.estado = Prestamo.Estado.VIGENTE
        prestamo.save(update_fields=["estado"])
    auditoria.registrar(auditoria.Accion.ANULAR, usuario=usuario, objeto=pago,
                        descripcion=f"Anulación de {pago.numero_recibo} ({prestamo.numero}). Motivo: {motivo}",
                        antes=antes, despues=auditoria.instantanea(pago))
    return pago

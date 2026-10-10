"""Caja y bancos: libro de caja, saldos, ingresos y egresos varios y transferencias.

El libro de caja NO se captura: se arma con las operaciones que ya registra cada módulo
(aportaciones y depósitos, desembolsos y pagos de préstamos, actividades, pagos de ganancias)
más los movimientos propios de caja. Cada operación aparece una sola vez, en su caja o cuenta.
No hay cierre de caja: el saldo de cualquier fecha se calcula siempre desde las operaciones confirmadas.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.aportaciones.models import MovimientoAfiliado, TipoMovimiento
from apps.aportaciones.services import METODOS_CON_REFERENCIA, _validar_monto
from apps.core import auditoria, parametros
from apps.core.dinero import CERO, redondear
from apps.core.models import CuentaFondo
from apps.core.secuencias import siguiente_numero

from .models import CategoriaCaja, MovimientoCaja

# Orígenes del libro de caja (también son las filas del flujo de efectivo)
APORTACIONES = "Aportaciones y depósitos de afiliados"
RETIROS = "Retiros de afiliados"
DESEMBOLSOS = "Desembolsos de préstamos"
COBROS_CAPITAL = "Cobros de préstamos: capital"
COBROS_INTERES = "Cobros de préstamos: intereses"
COBROS_MORA = "Cobros de préstamos: mora"
ACT_INGRESOS = "Ingresos de actividades"
ACT_GASTOS = "Gastos de actividades"
CAJA_INGRESOS = "Otros ingresos de caja"
CAJA_EGRESOS = "Otros egresos de caja"
TRANSFERENCIAS = "Transferencias entre cajas y cuentas"
GANANCIAS = "Ganancias pagadas a afiliados"


@dataclass
class LineaCaja:
    fecha: object
    orden: tuple
    origen: str
    numero: str
    descripcion: str
    cuenta: CuentaFondo
    entrada: object = CERO
    salida: object = CERO
    url: str = ""
    saldo: object = None

    @property
    def neto(self):
        return self.entrada - self.salida


def _filtrar(qs, campo_fecha, campo_cuenta, cuenta, desde, hasta):
    if cuenta is not None:
        qs = qs.filter(**{campo_cuenta: cuenta})
    if desde is not None:
        qs = qs.filter(**{f"{campo_fecha}__gte": desde})
    if hasta is not None:
        qs = qs.filter(**{f"{campo_fecha}__lte": hasta})
    return qs


def lineas(cuenta=None, desde=None, hasta=None, separar_intereses=False):
    """Todas las entradas y salidas de dinero confirmadas, en orden de fecha.

    Con `separar_intereses`, cada pago de préstamo se divide en capital e intereses (para el flujo de efectivo).
    """
    from apps.actividades.models import MovimientoActividad
    from apps.distribucion.models import PagoGanancia
    from apps.prestamos.models import PagoPrestamo, Prestamo

    filas = []
    # Aportaciones, depósitos y retiros. Las ganancias capitalizadas no mueven dinero: se excluyen.
    qs = _filtrar(MovimientoAfiliado.objects.confirmados().filter(pago_ganancia__isnull=True)
                  .select_related("afiliado", "tipo", "cuenta_fondo"), "fecha", "cuenta_fondo", cuenta, desde, hasta)
    for m in qs:
        retiro = m.tipo.naturaleza == TipoMovimiento.Naturaleza.SALIDA
        filas.append(LineaCaja(m.fecha, (m.registrado_en, 1, m.pk), RETIROS if retiro else APORTACIONES,
                               m.numero_operacion, f"{m.tipo.nombre} · {m.afiliado.codigo} {m.afiliado.nombre_completo}",
                               m.cuenta_fondo, entrada=CERO if retiro else m.monto, salida=m.monto if retiro else CERO,
                               url=reverse("aportaciones:detalle", args=[m.pk])))
    # Desembolsos de préstamos (un préstamo desembolsado no se anula).
    qs = _filtrar(Prestamo.objects.filter(fecha_desembolso__isnull=False)
                  .exclude(estado=Prestamo.Estado.ANULADO)
                  .select_related("afiliado", "prestatario_externo", "cuenta_desembolso"),
                  "fecha_desembolso", "cuenta_desembolso", cuenta, desde, hasta)
    for p in qs:
        filas.append(LineaCaja(p.fecha_desembolso, (p.registrado_en, 2, p.pk), DESEMBOLSOS, p.numero,
                               f"Desembolso a {p.prestatario_nombre}", p.cuenta_desembolso, salida=p.monto_aprobado,
                               url=reverse("prestamos:detalle", args=[p.pk])))
    # Pagos y abonos de préstamos.
    qs = _filtrar(PagoPrestamo.objects.filter(estado=PagoPrestamo.Estado.CONFIRMADO)
                  .select_related("prestamo__afiliado", "prestamo__prestatario_externo", "cuenta_fondo")
                  .prefetch_related("aplicaciones"), "fecha", "cuenta_fondo", cuenta, desde, hasta)
    for pago in qs:
        url = reverse("prestamos:pago_detalle", args=[pago.pk])
        texto = f"{pago.get_tipo_display()} · {pago.prestamo.numero} {pago.prestamo.prestatario_nombre}"
        if separar_intereses:
            interes = sum((a.interes for a in pago.aplicaciones.all()), CERO)
            capital = pago.monto - interes - pago.mora
            for origen, valor in ((COBROS_CAPITAL, capital), (COBROS_INTERES, interes), (COBROS_MORA, pago.mora)):
                if valor:
                    filas.append(LineaCaja(pago.fecha, (pago.registrado_en, 3, pago.pk), origen, pago.numero_recibo,
                                           texto, pago.cuenta_fondo, entrada=valor, url=url))
        else:
            filas.append(LineaCaja(pago.fecha, (pago.registrado_en, 3, pago.pk), COBROS_CAPITAL, pago.numero_recibo,
                                   texto, pago.cuenta_fondo, entrada=pago.monto, url=url))
    # Ingresos y gastos de actividades.
    qs = _filtrar(MovimientoActividad.objects.confirmados().select_related("actividad", "cuenta_fondo"),
                  "fecha", "cuenta_fondo", cuenta, desde, hasta)
    for m in qs:
        gasto = m.tipo == MovimientoActividad.Tipo.GASTO
        filas.append(LineaCaja(m.fecha, (m.registrado_en, 4, m.pk), ACT_GASTOS if gasto else ACT_INGRESOS, m.numero,
                               f"{m.actividad.nombre} · {m.concepto}", m.cuenta_fondo,
                               entrada=CERO if gasto else m.monto, salida=m.monto if gasto else CERO,
                               url=reverse("actividades:detalle", args=[m.actividad_id])))
    # Movimientos propios de caja. Una transferencia sale de una cuenta y entra en otra.
    base = MovimientoCaja.objects.confirmados().select_related("categoria", "cuenta_fondo", "cuenta_destino")
    for m in _filtrar(base, "fecha", "cuenta_fondo", cuenta, desde, hasta):
        url = reverse("caja:detalle", args=[m.pk])
        if m.es_transferencia:
            filas.append(LineaCaja(m.fecha, (m.registrado_en, 5, m.pk), TRANSFERENCIAS, m.numero,
                                   f"Transferencia a {m.cuenta_destino.nombre} · {m.concepto}", m.cuenta_fondo,
                                   salida=m.monto, url=url))
        else:
            egreso = m.tipo == MovimientoCaja.Tipo.EGRESO
            filas.append(LineaCaja(m.fecha, (m.registrado_en, 5, m.pk), CAJA_EGRESOS if egreso else CAJA_INGRESOS,
                                   m.numero, f"{m.categoria.nombre} · {m.concepto}", m.cuenta_fondo,
                                   entrada=CERO if egreso else m.monto, salida=m.monto if egreso else CERO, url=url))
    for m in _filtrar(base.filter(tipo=MovimientoCaja.Tipo.TRANSFERENCIA), "fecha", "cuenta_destino", cuenta, desde,
                      hasta):
        filas.append(LineaCaja(m.fecha, (m.registrado_en, 5, m.pk), TRANSFERENCIAS, m.numero,
                               f"Transferencia desde {m.cuenta_fondo.nombre} · {m.concepto}", m.cuenta_destino,
                               entrada=m.monto, url=reverse("caja:detalle", args=[m.pk])))
    # Ganancias pagadas en dinero (las capitalizadas no salen de caja).
    qs = _filtrar(PagoGanancia.objects.confirmados().filter(forma=PagoGanancia.Forma.PAGO)
                  .select_related("afiliado", "distribucion", "cuenta_fondo"), "fecha", "cuenta_fondo", cuenta, desde,
                  hasta)
    for pg in qs:
        filas.append(LineaCaja(pg.fecha, (pg.registrado_en, 6, pg.pk), GANANCIAS, pg.numero,
                               f"Ganancias {pg.distribucion.codigo} · {pg.afiliado.codigo} {pg.afiliado.nombre_completo}",
                               pg.cuenta_fondo, salida=pg.monto,
                               url=reverse("distribucion:detalle", args=[pg.distribucion_id])))
    filas.sort(key=lambda f: (f.fecha, f.orden))
    return filas


def saldo(cuenta=None, hasta=None):
    """Saldo de una caja o cuenta (o de todas) al final del día `hasta`."""
    return redondear(sum((f.neto for f in lineas(cuenta, hasta=hasta)), CERO))


def saldos_por_cuenta(hasta=None, solo_activas=False):
    totales = defaultdict(lambda: CERO)
    for f in lineas(hasta=hasta):
        totales[f.cuenta.pk] += f.neto
    cuentas = CuentaFondo.objects.all()
    if solo_activas:
        cuentas = cuentas.filter(activa=True)
    return [{"cuenta": c, "saldo": redondear(totales[c.pk])} for c in cuentas]


@dataclass
class Libro:
    cuenta: object
    desde: object
    hasta: object
    saldo_inicial: object
    lineas: list
    entradas: object
    salidas: object
    saldo_final: object


def libro(cuenta=None, desde=None, hasta=None):
    """Libro de caja con saldo inicial, cada operación con su saldo acumulado y saldo final."""
    hasta = hasta or timezone.localdate()
    if desde is not None and desde > hasta:
        raise ValidationError("La fecha inicial no puede ser posterior a la final.")
    inicial = saldo(cuenta, hasta=desde - timedelta(days=1)) if desde else CERO
    filas = lineas(cuenta, desde, hasta)
    acumulado, entradas, salidas = inicial, CERO, CERO
    for f in filas:
        acumulado += f.neto
        entradas += f.entrada
        salidas += f.salida
        f.saldo = acumulado
    return Libro(cuenta, desde, hasta, inicial, filas, entradas, salidas, acumulado)


def flujo_efectivo(desde=None, hasta=None):
    """Entradas y salidas agrupadas por origen. Las transferencias internas no cambian el total y se omiten."""
    entradas, salidas = defaultdict(lambda: CERO), defaultdict(lambda: CERO)
    for f in lineas(desde=desde, hasta=hasta, separar_intereses=True):
        if f.origen == TRANSFERENCIAS:
            continue
        entradas[f.origen] += f.entrada
        salidas[f.origen] += f.salida
    orden = [APORTACIONES, RETIROS, DESEMBOLSOS, COBROS_CAPITAL, COBROS_INTERES, COBROS_MORA, ACT_INGRESOS, ACT_GASTOS,
             CAJA_INGRESOS, CAJA_EGRESOS, GANANCIAS]
    filas = [{"origen": o, "entradas": entradas[o], "salidas": salidas[o], "neto": entradas[o] - salidas[o]}
             for o in orden if entradas[o] or salidas[o]]
    total_e, total_s = sum(entradas.values(), CERO), sum(salidas.values(), CERO)
    return {"filas": filas, "entradas": total_e, "salidas": total_s, "neto": total_e - total_s,
            "saldo_inicial": saldo(hasta=desde - timedelta(days=1)) if desde else CERO}


def otros_resultados(desde=None, hasta=None):
    """Ingresos y egresos de caja que cuentan como utilidad (categorías con «afecta utilidades»)."""
    qs = _filtrar(MovimientoCaja.objects.confirmados().filter(categoria__afecta_utilidades=True)
                  .select_related("categoria"), "fecha", "cuenta_fondo", None, desde, hasta)
    ingresos, egresos = CERO, CERO
    por_categoria = defaultdict(lambda: CERO)
    for m in qs:
        if m.tipo == MovimientoCaja.Tipo.INGRESO:
            ingresos += m.monto
            por_categoria[m.categoria.nombre] += m.monto
        else:
            egresos += m.monto
            por_categoria[m.categoria.nombre] -= m.monto
    return {"ingresos": redondear(ingresos), "egresos": redondear(egresos), "neto": redondear(ingresos - egresos),
            "por_categoria": dict(por_categoria)}


# --------------------------------------------------------------------------- control de saldo

def validar_saldo_disponible(cuenta, fecha, monto, excluir_caja=None):
    """Impide que una salida de `monto` en `fecha` deje la cuenta en negativo ese día o cualquier día posterior.

    `excluir_caja` es un MovimientoCaja que se va a anular (deja de contar).
    """
    if parametros.obtener("caja.permitir_saldo_negativo"):
        return
    netos = defaultdict(lambda: CERO)
    for f in lineas(cuenta):
        if excluir_caja is not None and f.numero == excluir_caja.numero:
            continue
        netos[f.fecha] += f.neto
    netos[fecha] -= monto
    acumulado = CERO
    for dia in sorted(netos):
        acumulado += netos[dia]
        if dia >= fecha and acumulado < 0:
            disponible = saldo(cuenta, hasta=fecha)
            if excluir_caja is not None:
                raise ValidationError(
                    f"No se puede: {cuenta.nombre} quedaría con saldo negativo el {dia:%d/%m/%Y} "
                    f"(L {acumulado:,.2f}).")
            raise ValidationError(
                {"monto": f"Saldo insuficiente en {cuenta.nombre}: disponible L {disponible:,.2f} al "
                          f"{fecha:%d/%m/%Y}" + ("" if dia == fecha else
                                                 f"; además quedaría en negativo el {dia:%d/%m/%Y}") + "."})


# --------------------------------------------------------------------------- registro

def registrar_movimiento(*, tipo, fecha, concepto, monto, metodo_pago, cuenta_fondo, usuario, categoria=None,
                         cuenta_destino=None, referencia="", observacion="", clave_idempotencia=None):
    """Registra un ingreso, egreso o transferencia. Devuelve (movimiento, creado)."""
    from apps.prestamos.services import _validar_cuenta_metodo

    if not usuario.has_perm("caja.add_movimientocaja"):
        raise ValidationError("No tiene permiso para registrar movimientos de caja.")
    if clave_idempotencia is not None:
        existente = MovimientoCaja.objects.filter(clave_idempotencia=clave_idempotencia).first()
        if existente is not None:
            return existente, False
    monto = _validar_monto(monto)
    concepto = " ".join((concepto or "").split())
    errores = {}
    if tipo not in MovimientoCaja.Tipo.values:
        errores["tipo"] = "Tipo de movimiento inválido."
    if len(concepto) < 3:
        errores["concepto"] = "Describa el concepto."
    if fecha is None or fecha > timezone.localdate():
        errores["fecha"] = "La fecha es obligatoria y no puede ser futura."
    if tipo == MovimientoCaja.Tipo.TRANSFERENCIA:
        categoria = None
        if not isinstance(cuenta_fondo, CuentaFondo) or not cuenta_fondo.activa:
            errores["cuenta_fondo"] = "Seleccione la caja o cuenta de origen (activa)."
        if not isinstance(cuenta_destino, CuentaFondo) or not cuenta_destino.activa:
            errores["cuenta_destino"] = "Seleccione la caja o cuenta de destino (activa)."
        elif cuenta_destino == cuenta_fondo:
            errores["cuenta_destino"] = "El destino debe ser distinto del origen."
        hay_banco = any(getattr(c, "tipo", None) == CuentaFondo.Tipo.BANCO for c in (cuenta_fondo, cuenta_destino))
        if (hay_banco or metodo_pago in METODOS_CON_REFERENCIA) and not (referencia or "").strip():
            errores["referencia"] = "Indique la referencia del depósito, retiro, transferencia o cheque."
    elif tipo in (MovimientoCaja.Tipo.INGRESO, MovimientoCaja.Tipo.EGRESO):
        cuenta_destino = None
        if not isinstance(categoria, CategoriaCaja) or not categoria.activa:
            errores["categoria"] = "Seleccione una categoría activa."
        elif categoria.tipo != tipo:
            errores["categoria"] = f"La categoría no corresponde a un {tipo.lower()}."
        _validar_cuenta_metodo(metodo_pago, cuenta_fondo, referencia, errores)
    if errores:
        raise ValidationError(errores)
    with transaction.atomic():
        # Bloquea la cuenta de origen para que dos salidas simultáneas no usen el mismo saldo.
        CuentaFondo.objects.select_for_update().get(pk=cuenta_fondo.pk)
        if tipo != MovimientoCaja.Tipo.INGRESO:
            validar_saldo_disponible(cuenta_fondo, fecha, monto)
        try:
            with transaction.atomic():
                mov = MovimientoCaja.objects.create(
                    numero=siguiente_numero("CJ"), tipo=tipo, categoria=categoria, fecha=fecha, concepto=concepto,
                    monto=monto, metodo_pago=metodo_pago, cuenta_fondo=cuenta_fondo, cuenta_destino=cuenta_destino,
                    referencia=(referencia or "").strip(), observacion=(observacion or "").strip(),
                    registrado_por=usuario,
                    **({"clave_idempotencia": clave_idempotencia} if clave_idempotencia else {}),
                )
        except IntegrityError:
            existente = MovimientoCaja.objects.filter(clave_idempotencia=clave_idempotencia).first()
            if existente is not None:
                return existente, False
            raise
        auditoria.registrar(auditoria.Accion.CREAR, usuario=usuario, objeto=mov,
                            descripcion=f"{mov.get_tipo_display()} {mov.numero} por L {mov.monto:,.2f}",
                            despues=auditoria.instantanea(mov))
    return mov, True


@transaction.atomic
def anular_movimiento(mov, *, usuario, motivo):
    if not usuario.has_perm("caja.anular_movimientocaja"):
        raise ValidationError("No tiene permiso para anular movimientos de caja.")
    motivo = (motivo or "").strip()
    if len(motivo) < 10:
        raise ValidationError({"motivo": "Explique el motivo de la anulación (mínimo 10 caracteres)."})
    mov = MovimientoCaja.objects.select_for_update().select_related("cuenta_fondo", "cuenta_destino").get(pk=mov.pk)
    if not mov.confirmado:
        raise ValidationError("El movimiento ya está anulado.")
    if parametros.obtener("movimientos.anulacion_requiere_otro_usuario") and mov.registrado_por_id == usuario.pk:
        raise ValidationError("La anulación debe autorizarla un usuario distinto al que registró la operación.")
    # Anular un ingreso (o la entrada de una transferencia) quita dinero de esa cuenta: no puede dejarla en negativo.
    if mov.tipo == MovimientoCaja.Tipo.INGRESO:
        validar_saldo_disponible(mov.cuenta_fondo, mov.fecha, CERO, excluir_caja=mov)
    elif mov.es_transferencia:
        validar_saldo_disponible(mov.cuenta_destino, mov.fecha, CERO, excluir_caja=mov)
    antes = auditoria.instantanea(mov)
    mov.estado = MovimientoCaja.Estado.ANULADO
    mov.anulado_por = usuario
    mov.anulado_en = timezone.now()
    mov.motivo_anulacion = motivo
    mov.save(update_fields=["estado", "anulado_por", "anulado_en", "motivo_anulacion"])
    auditoria.registrar(auditoria.Accion.ANULAR, usuario=usuario, objeto=mov,
                        descripcion=f"Anulación de {mov.numero}. Motivo: {motivo}", antes=antes,
                        despues=auditoria.instantanea(mov))
    return mov


# --------------------------------------------------------------------------- categorías

CATEGORIAS_INICIALES = [
    dict(nombre="Saldo inicial", tipo="INGRESO", afecta_utilidades=False,
         descripcion="Dinero con el que la caja o cuenta empieza a usarse en el sistema. No es utilidad."),
    dict(nombre="Intereses bancarios", tipo="INGRESO", afecta_utilidades=True,
         descripcion="Intereses que paga el banco por los ahorros de CAUNE."),
    dict(nombre="Otros ingresos", tipo="INGRESO", afecta_utilidades=True, descripcion=""),
    dict(nombre="Gastos administrativos", tipo="EGRESO", afecta_utilidades=True,
         descripcion="Papelería, impresiones, reuniones y otros gastos de operación."),
    dict(nombre="Comisiones bancarias", tipo="EGRESO", afecta_utilidades=True, descripcion=""),
    dict(nombre="Otros egresos", tipo="EGRESO", afecta_utilidades=True, descripcion=""),
]


def asegurar_categorias():
    for datos in CATEGORIAS_INICIALES:
        CategoriaCaja.objects.get_or_create(nombre=datos["nombre"], defaults=datos)


def categoria_tiene_movimientos(categoria):
    return categoria.pk is not None and MovimientoCaja.objects.filter(categoria=categoria).exists()

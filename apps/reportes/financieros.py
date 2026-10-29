"""Estados financieros de CAUNE (reportes 15 a 22).

Todo se calcula desde las operaciones confirmadas, con los mismos servicios que usan caja, préstamos, actividades y
distribución: no hay asientos contables aparte que puedan desviarse. La base es de efectivo: los intereses y la mora
son ingreso cuando se cobran (igual que en la distribución de ganancias).

Ecuación del balance (es la misma del resumen financiero, reporte 14):

    efectivo + cartera = depósitos + ganancias por pagar + aportaciones + fondos que no son utilidad
                         + reserva + resultados acumulados

Las distribuciones aprobadas trasladan utilidad de «resultados acumulados» a «ganancias por pagar» (lo repartido) y
a «reserva» (lo retenido). Al pagar o capitalizar, baja la cuenta por pagar; lo capitalizado sube las aportaciones.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from apps.actividades import services as act_services
from apps.actividades.models import Actividad
from apps.aportaciones.models import MovimientoAfiliado, TipoMovimiento
from apps.aportaciones.services import totales_generales
from apps.caja import services as caja_services
from apps.caja.models import MovimientoCaja
from apps.core.dinero import CERO, redondear
from apps.core.models import CuentaFondo
from apps.distribucion import services as dist_services
from apps.distribucion.models import Distribucion
from apps.prestamos import services as pre_services
from apps.prestamos.models import AplicacionPago, PagoPrestamo, Prestamo

INTERNO, EXTERNO = Prestamo.Tipo.INTERNO, Prestamo.Tipo.EXTERNO
CIEN = Decimal(100)


# --------------------------------------------------------------------------- estructura de un estado

@dataclass
class Fila:
    """Una línea de un estado financiero. `tipo`: seccion, linea, subtotal o total."""
    tipo: str
    concepto: str
    valores: list = field(default_factory=list)
    nivel: int = 0
    url: str = ""


@dataclass
class Estado:
    titulo: str
    subtitulo: str
    columnas: list
    filas: list
    nota: str = ""
    resumen: list = field(default_factory=list)
    diferencia: object = None  # cuadre: debe ser cero
    firmas: bool = True


def _seccion(concepto):
    return Fila("seccion", concepto)


def _linea(concepto, valores, nivel=1, url=""):
    return Fila("linea", concepto, list(valores), nivel, url)


def _subtotal(concepto, valores, nivel=0):
    return Fila("subtotal", concepto, list(valores), nivel)


def _total(concepto, valores):
    return Fila("total", concepto, list(valores))


def _lineas_no_vacias(filas):
    """Quita las líneas de detalle que están en cero en todas las columnas."""
    return [f for f in filas if f.tipo != "linea" or any(v for v in f.valores if isinstance(v, Decimal))]


def con_variacion(estado):
    """Agrega la columna de variación (primera columna menos la segunda) a un estado comparativo."""
    if len(estado.columnas) != 2:
        return estado
    estado.columnas = estado.columnas + ["Variación"]
    for f in estado.filas:
        if len(f.valores) == 2 and all(isinstance(v, Decimal) for v in f.valores):
            f.valores.append(f.valores[0] - f.valores[1])
        elif f.valores:
            f.valores.append("")
    return estado


def porcentaje(parte, total):
    return redondear(parte * CIEN / total) if total else CERO


def inicio_ejercicio(fecha):
    """El ejercicio es el año calendario (1 de enero al 31 de diciembre)."""
    return date(fecha.year, 1, 1)


def mismo_dia_anio_anterior(fecha):
    try:
        return fecha.replace(year=fecha.year - 1)
    except ValueError:  # 29 de febrero
        return fecha.replace(year=fecha.year - 1, day=28)


# --------------------------------------------------------------------------- utilidad del período

def utilidad(desde=None, hasta=None):
    """Componentes de la utilidad (base de efectivo) entre dos fechas.

    Es la misma utilidad que reparte la distribución: intereses y mora cobrados, resultado de actividades y los
    ingresos y egresos de caja cuyas categorías «afectan utilidades».
    """
    aplicaciones = AplicacionPago.objects.filter(pago__estado=PagoPrestamo.Estado.CONFIRMADO)
    pagos = PagoPrestamo.objects.filter(estado=PagoPrestamo.Estado.CONFIRMADO)
    if desde:
        aplicaciones, pagos = aplicaciones.filter(pago__fecha__gte=desde), pagos.filter(fecha__gte=desde)
    if hasta:
        aplicaciones, pagos = aplicaciones.filter(pago__fecha__lte=hasta), pagos.filter(fecha__lte=hasta)
    intereses = defaultdict(lambda: CERO)
    for f in aplicaciones.values("pago__prestamo__tipo_prestatario").annotate(t=Sum("interes")):
        intereses[f["pago__prestamo__tipo_prestatario"]] += redondear(f["t"] or CERO)
    mora = defaultdict(lambda: CERO)
    for f in pagos.values("prestamo__tipo_prestatario").annotate(t=Sum("mora")):
        mora[f["prestamo__tipo_prestatario"]] += redondear(f["t"] or CERO)

    actividades = []
    for a in act_services.anotar_resultados(Actividad.objects.order_by("codigo"), desde, hasta):
        if a.ingresos or a.gastos:
            actividades.append({"actividad": a, "ingresos": redondear(a.ingresos), "gastos": redondear(a.gastos),
                                "neto": redondear(a.ingresos - a.gastos)})

    otros_ingresos, otros_egresos = defaultdict(lambda: CERO), defaultdict(lambda: CERO)
    qs = MovimientoCaja.objects.confirmados().filter(categoria__afecta_utilidades=True).select_related("categoria")
    if desde:
        qs = qs.filter(fecha__gte=desde)
    if hasta:
        qs = qs.filter(fecha__lte=hasta)
    for m in qs:
        destino = otros_ingresos if m.tipo == MovimientoCaja.Tipo.INGRESO else otros_egresos
        destino[m.categoria.nombre] += m.monto

    financieros = intereses[INTERNO] + intereses[EXTERNO] + mora[INTERNO] + mora[EXTERNO]
    neto_actividades = sum((a["neto"] for a in actividades), CERO)
    total_otros_ingresos = sum(otros_ingresos.values(), CERO)
    total_otros_egresos = sum(otros_egresos.values(), CERO)
    return {
        "intereses_internos": intereses[INTERNO], "intereses_externos": intereses[EXTERNO],
        "mora_internos": mora[INTERNO], "mora_externos": mora[EXTERNO], "financieros": financieros,
        "actividades": actividades, "neto_actividades": neto_actividades,
        "ingresos_actividades": sum((a["ingresos"] for a in actividades), CERO),
        "gastos_actividades": sum((a["gastos"] for a in actividades), CERO),
        "otros_ingresos": dict(otros_ingresos), "otros_egresos": dict(otros_egresos),
        "total_otros_ingresos": total_otros_ingresos, "total_otros_egresos": total_otros_egresos,
        "ingresos_totales": financieros + sum((a["ingresos"] for a in actividades), CERO) + total_otros_ingresos,
        "neto": redondear(financieros + neto_actividades + total_otros_ingresos - total_otros_egresos),
    }


# --------------------------------------------------------------------------- distribuciones a una fecha

def asignaciones(hasta, corte_ejercicio=None):
    """Cuánto de la utilidad ya se asignó por distribuciones aprobadas al final del día `hasta`.

    Una distribución aprobada a esa fecha asigna lo repartido (por pagar o ya entregado) y su reserva. Si aún no
    estaba aprobada, solo cuentan las entregas hechas hasta ese día. Con `corte_ejercicio`, separa lo asignado por
    distribuciones cuyo período termina antes de esa fecha (ejercicios anteriores) del resto (ejercicio actual).
    """
    res = {"reserva": CERO, "por_pagar": CERO, "entregado": CERO, "anteriores": CERO, "ejercicio": CERO}
    for d in Distribucion.objects.filter(estado__in=[Distribucion.Estado.APROBADA, Distribucion.Estado.APLICADA]):
        entregado = redondear(d.pagos.confirmados().filter(fecha__lte=hasta).aggregate(t=Sum("monto"))["t"] or CERO)
        aprobada = d.aprobado_en is not None and timezone.localtime(d.aprobado_en).date() <= hasta
        if aprobada:
            r = dist_services.resumen(d)
            reserva, por_pagar = r["reserva"], max(r["total"] - entregado, CERO)
        else:
            reserva = por_pagar = CERO
        asignado = entregado + por_pagar + reserva
        res["reserva"] += reserva
        res["por_pagar"] += por_pagar
        res["entregado"] += entregado
        res["anteriores" if corte_ejercicio and d.fecha_fin < corte_ejercicio else "ejercicio"] += asignado
    return res


# --------------------------------------------------------------------------- 15. balance general

def cartera(hasta):
    """Capital de préstamos desembolsados y no recuperado, por tipo de prestatario."""
    saldo = {INTERNO: CERO, EXTERNO: CERO}
    for p in (Prestamo.objects.filter(fecha_desembolso__lte=hasta).exclude(estado=Prestamo.Estado.ANULADO)
              .values("tipo_prestatario").annotate(t=Sum("monto_aprobado"))):
        saldo[p["tipo_prestatario"]] += p["t"] or CERO
    for a in (AplicacionPago.objects.filter(pago__estado=PagoPrestamo.Estado.CONFIRMADO, pago__fecha__lte=hasta)
              .values("pago__prestamo__tipo_prestatario").annotate(t=Sum("capital"))):
        saldo[a["pago__prestamo__tipo_prestatario"]] -= a["t"] or CERO
    return {k: redondear(v) for k, v in saldo.items()}


def fondos_no_utilidad(hasta):
    """Ingresos menos egresos de caja con categorías que no son utilidad (saldo inicial y similares)."""
    total = CERO
    for m in MovimientoCaja.objects.confirmados().filter(fecha__lte=hasta, categoria__afecta_utilidades=False):
        total += m.monto if m.tipo == MovimientoCaja.Tipo.INGRESO else -m.monto
    return redondear(total)


def situacion(hasta):
    """Cifras del balance general al final del día `hasta`."""
    corte = inicio_ejercicio(hasta)
    cuentas = caja_services.saldos_por_cuenta(hasta=hasta)
    efectivo = sum((c["saldo"] for c in cuentas), CERO)
    cart = cartera(hasta)
    saldos = totales_generales(hasta=hasta)
    asig = asignaciones(hasta, corte_ejercicio=corte)
    util_anteriores = utilidad(hasta=corte - timedelta(days=1))["neto"]
    util_ejercicio = utilidad(desde=corte, hasta=hasta)["neto"]
    no_utilidad = fondos_no_utilidad(hasta)
    resultados_anteriores = util_anteriores - asig["anteriores"]
    resultado_ejercicio = util_ejercicio - asig["ejercicio"]
    activo = efectivo + cart[INTERNO] + cart[EXTERNO]
    pasivo = saldos["depositos"] + asig["por_pagar"]
    patrimonio = saldos["aportaciones"] + no_utilidad + asig["reserva"] + resultados_anteriores + resultado_ejercicio
    return {
        "hasta": hasta, "ejercicio": hasta.year, "cuentas": cuentas, "efectivo": efectivo,
        "cartera_internos": cart[INTERNO], "cartera_externos": cart[EXTERNO],
        "cartera": cart[INTERNO] + cart[EXTERNO], "activo": activo,
        "depositos": saldos["depositos"], "por_pagar": asig["por_pagar"], "pasivo": pasivo,
        "aportaciones": saldos["aportaciones"], "no_utilidad": no_utilidad, "reserva": asig["reserva"],
        "resultados_anteriores": resultados_anteriores, "resultado_ejercicio": resultado_ejercicio,
        "utilidad_ejercicio": util_ejercicio,
        "patrimonio": patrimonio, "pasivo_patrimonio": pasivo + patrimonio, "diferencia": activo - pasivo - patrimonio,
    }


def pendientes_de_cobro():
    """Intereses y mora vencidos y no cobrados hoy. No son ingreso hasta cobrarlos (cuentas de orden)."""
    intereses = mora = CERO
    hoy = timezone.localdate()
    for p in Prestamo.objects.filter(estado=Prestamo.Estado.VIGENTE, fecha_desembolso__isnull=False):
        r = pre_services.resumen(p)
        intereses += sum((c.interes_pendiente for c in r.cuotas if c.cuota.fecha_vencimiento < hoy), CERO)
        mora += r.mora_pendiente
    return {"intereses": redondear(intereses), "mora": redondear(mora)}


def balance_general(hasta, comparar=None):
    fechas = [hasta] + ([comparar] if comparar else [])
    datos = [situacion(f) for f in fechas]

    def v(clave):
        return [d[clave] for d in datos]

    filas = [_seccion("ACTIVO"), _subtotal("Efectivo y equivalentes", v("efectivo"))]
    cuentas = {}
    for i, d in enumerate(datos):
        for c in d["cuentas"]:
            cuentas.setdefault(c["cuenta"].pk, (c["cuenta"], [CERO] * len(datos)))[1][i] = c["saldo"]
    for cuenta, saldos in cuentas.values():
        banco = " ".join(x for x in (cuenta.banco, cuenta.numero_cuenta) if x)
        etiqueta = f"{cuenta.nombre} ({banco})" if banco else cuenta.nombre
        filas.append(_linea(etiqueta, saldos, nivel=2))
    filas += [
        _subtotal("Cartera de préstamos (capital por cobrar)", v("cartera")),
        _linea("Préstamos a afiliados", v("cartera_internos"), nivel=2),
        _linea("Préstamos a externos", v("cartera_externos"), nivel=2),
        _total("TOTAL ACTIVO", v("activo")),
        _seccion("PASIVO"),
        _linea("Depósitos de ahorro de afiliados (reembolsables)", v("depositos")),
        _linea("Ganancias distribuidas por pagar", v("por_pagar")),
        _total("TOTAL PASIVO", v("pasivo")),
        _seccion("PATRIMONIO"),
        _linea("Aportaciones de afiliados", v("aportaciones")),
        _linea("Fondos que no son utilidad (saldo inicial y similares)", v("no_utilidad")),
        _linea("Reserva", v("reserva")),
        _linea("Resultados acumulados de ejercicios anteriores", v("resultados_anteriores")),
        _linea("Resultado del ejercicio en curso, no distribuido", v("resultado_ejercicio")),
        _total("TOTAL PATRIMONIO", v("patrimonio")),
        _total("TOTAL PASIVO Y PATRIMONIO", v("pasivo_patrimonio")),
    ]
    nota = ("Base de efectivo: los intereses y la mora son ingreso cuando se cobran. Las ganancias capitalizadas "
            "forman parte de las aportaciones. El ejercicio es el año calendario.")
    principal = datos[0]
    if hasta == timezone.localdate():
        pend = pendientes_de_cobro()
        if pend["intereses"] or pend["mora"]:
            filas += [_seccion("CUENTAS DE ORDEN (no forman parte del balance)"),
                      _linea("Intereses vencidos por cobrar", [pend["intereses"]] + [""] * (len(datos) - 1)),
                      _linea("Mora por cobrar", [pend["mora"]] + [""] * (len(datos) - 1))]
    estado = Estado(
        titulo="Balance general", subtitulo=f"Al {hasta:%d/%m/%Y}" + (f", comparado con el {comparar:%d/%m/%Y}"
                                                                    if comparar else ""),
        columnas=[f"{f:%d/%m/%Y}" for f in fechas], filas=_lineas_no_vacias(filas), nota=nota,
        resumen=[("Total activo", principal["activo"]), ("Total pasivo", principal["pasivo"]),
                 ("Total patrimonio", principal["patrimonio"]),
                 ("Cuadre", "Cuadra" if principal["diferencia"] == 0
                  else f"Diferencia L {principal['diferencia']:,.2f}")],
        diferencia=principal["diferencia"])
    return con_variacion(estado)


# --------------------------------------------------------------------------- 16. estado de resultados

def estado_resultados(desde, hasta, comparar=False):
    periodos = [(desde, hasta)]
    if comparar:
        periodos.append((mismo_dia_anio_anterior(desde), mismo_dia_anio_anterior(hasta)))
    datos = [utilidad(d, h) for d, h in periodos]
    n = len(datos)

    def v(clave):
        return [d[clave] for d in datos]

    filas = [
        _seccion("INGRESOS FINANCIEROS"),
        _linea("Intereses de préstamos a afiliados", v("intereses_internos")),
        _linea("Intereses de préstamos a externos", v("intereses_externos")),
        _linea("Mora cobrada a afiliados", v("mora_internos")),
        _linea("Mora cobrada a externos", v("mora_externos")),
        _subtotal("Total ingresos financieros", v("financieros")),
        _seccion("RESULTADO DE ACTIVIDADES ECONÓMICAS"),
    ]
    actividades = {}
    for i, d in enumerate(datos):
        for a in d["actividades"]:
            fila = actividades.setdefault(a["actividad"].pk, {"actividad": a["actividad"],
                                                              "neto": [CERO] * n, "ingresos": [CERO] * n,
                                                              "gastos": [CERO] * n})
            for k in ("neto", "ingresos", "gastos"):
                fila[k][i] = a[k]
    for fila in actividades.values():
        act = fila["actividad"]
        filas.append(_linea(f"{act.codigo} · {act.nombre}", fila["neto"],
                            url=reverse("actividades:detalle", args=[act.pk])))
    filas += [
        _linea("Ingresos brutos de actividades", v("ingresos_actividades"), nivel=2),
        _linea("Gastos de actividades", v("gastos_actividades"), nivel=2),
        _subtotal("Resultado neto de actividades", v("neto_actividades")),
        _seccion("OTROS INGRESOS"),
    ]
    for nombre in sorted({k for d in datos for k in d["otros_ingresos"]}):
        filas.append(_linea(nombre, [d["otros_ingresos"].get(nombre, CERO) for d in datos]))
    filas += [_subtotal("Total otros ingresos", v("total_otros_ingresos")), _seccion("GASTOS DE OPERACIÓN")]
    for nombre in sorted({k for d in datos for k in d["otros_egresos"]}):
        filas.append(_linea(nombre, [d["otros_egresos"].get(nombre, CERO) for d in datos]))
    filas += [_subtotal("Total gastos de operación", v("total_otros_egresos")),
              _total("UTILIDAD (PÉRDIDA) NETA DEL PERÍODO", v("neto"))]
    principal = datos[0]
    margen = porcentaje(principal["neto"], principal["ingresos_totales"])
    estado = Estado(
        titulo="Estado de resultados",
        subtitulo=f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}" + (
            f", comparado con el mismo período de {periodos[1][1].year}" if comparar else ""),
        columnas=[f"{d:%d/%m/%Y} – {h:%d/%m/%Y}" if comparar else "Monto" for d, h in periodos],
        filas=_lineas_no_vacias(filas),
        nota="Base de efectivo. El capital recuperado de préstamos y los fondos de caja que no son utilidad (como el "
             "saldo inicial) no son ingreso. Esta utilidad es la misma que reparte la distribución de ganancias.",
        resumen=[("Utilidad neta", principal["neto"]), ("Ingresos totales", principal["ingresos_totales"]),
                 ("Margen neto", f"{margen:.2f} %")])
    return con_variacion(estado)


# --------------------------------------------------------------------------- 17. cambios en el patrimonio

def cambios_patrimonio(desde, hasta):
    """Movimiento de cada componente del patrimonio entre `desde` y `hasta`."""
    antes = desde - timedelta(days=1)
    ini, fin = situacion(antes), situacion(hasta)
    columnas = ["Aportaciones", "Fondos no utilidad", "Reserva", "Resultados acumulados", "Total"]

    def fila_saldo(concepto, s):
        resultados = s["resultados_anteriores"] + s["resultado_ejercicio"]
        return _total(concepto, [s["aportaciones"], s["no_utilidad"], s["reserva"], resultados, s["patrimonio"]])

    def valores(apo=CERO, otros=CERO, reserva=CERO, resultados=CERO):
        return [apo, otros, reserva, resultados, apo + otros + reserva + resultados]

    filas = [fila_saldo(f"Saldo al {antes:%d/%m/%Y}", ini)]
    movs = (MovimientoAfiliado.objects.confirmados()
            .filter(fecha__gte=desde, fecha__lte=hasta, tipo__clase=TipoMovimiento.Clase.APORTACION)
            .values("tipo__nombre", "tipo__naturaleza").annotate(t=Sum("monto")).order_by("tipo__nombre"))
    for m in movs:
        signo = 1 if m["tipo__naturaleza"] == TipoMovimiento.Naturaleza.ENTRADA else -1
        filas.append(_linea(m["tipo__nombre"], valores(apo=signo * redondear(m["t"]))))
    otros = fin["no_utilidad"] - ini["no_utilidad"]
    filas.append(_linea("Fondos que no son utilidad recibidos (saldo inicial y similares)", valores(otros=otros)))
    util = utilidad(desde, hasta)["neto"]
    filas.append(_linea("Utilidad (pérdida) neta del período", valores(resultados=util)))
    resultados_ini = ini["resultados_anteriores"] + ini["resultado_ejercicio"]
    resultados_fin = fin["resultados_anteriores"] + fin["resultado_ejercicio"]
    d_reserva = fin["reserva"] - ini["reserva"]
    asignado = resultados_ini + util - resultados_fin  # lo que las distribuciones sacaron de resultados
    filas.append(_linea("Reserva constituida en distribuciones", valores(reserva=d_reserva, resultados=-d_reserva)))
    filas.append(_linea("Ganancias distribuidas a afiliados (pasan a pagar o a capitalizar)",
                        valores(resultados=-(asignado - d_reserva))))
    filas.append(fila_saldo(f"Saldo al {hasta:%d/%m/%Y}", fin))
    # Comprobación: saldo inicial + movimientos = saldo final, columna por columna.
    suma = [sum((f.valores[i] for f in filas[:-1]), CERO) for i in range(len(columnas))]
    diferencia = suma[-1] - fin["patrimonio"]
    return Estado(
        titulo="Estado de cambios en el patrimonio", subtitulo=f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}",
        columnas=columnas, filas=_lineas_no_vacias(filas),
        nota="Las ganancias capitalizadas aparecen como aportaciones porque se acreditan a la cuenta de aportaciones "
             "del afiliado. Lo distribuido sale de resultados acumulados cuando la distribución se aprueba.",
        resumen=[("Patrimonio final", fin["patrimonio"]), ("Patrimonio inicial", ini["patrimonio"]),
                 ("Variación", fin["patrimonio"] - ini["patrimonio"])],
        diferencia=diferencia)


# --------------------------------------------------------------------------- 18. flujo de efectivo clasificado

def flujo_clasificado(desde, hasta):
    """Estado de flujo de efectivo (método directo) por operación, cartera de préstamos y financiamiento."""
    c = caja_services
    t = defaultdict(lambda: CERO)
    for f in c.lineas(desde=desde, hasta=hasta, separar_intereses=True):
        if f.origen == c.TRANSFERENCIAS:
            continue
        if f.origen in (c.APORTACIONES, c.RETIROS):
            clave = ("aportaciones" if f.clase == TipoMovimiento.Clase.APORTACION else "depositos")
            t[clave + ("_salida" if f.salida else "_entrada")] += f.entrada or f.salida
        elif f.origen in (c.CAJA_INGRESOS, c.CAJA_EGRESOS):
            clave = "otros" if f.clase == "UTILIDAD" else "no_utilidad"
            t[clave + ("_salida" if f.salida else "_entrada")] += f.entrada or f.salida
        else:
            t[f.origen] += f.entrada - f.salida
    operacion = [
        ("Intereses cobrados", t[c.COBROS_INTERES]),
        ("Mora cobrada", t[c.COBROS_MORA]),
        ("Ingresos de actividades económicas", t[c.ACT_INGRESOS]),
        ("Gastos de actividades económicas", t[c.ACT_GASTOS]),
        ("Otros ingresos", t["otros_entrada"]),
        ("Gastos de operación", -t["otros_salida"]),
    ]
    cartera_ = [
        ("Préstamos desembolsados", t[c.DESEMBOLSOS]),
        ("Capital recuperado de préstamos", t[c.COBROS_CAPITAL]),
    ]
    financiamiento = [
        ("Aportaciones recibidas", t["aportaciones_entrada"]),
        ("Retiros de aportaciones", -t["aportaciones_salida"]),
        ("Depósitos de ahorro recibidos", t["depositos_entrada"]),
        ("Retiros de depósitos", -t["depositos_salida"]),
        ("Fondos que no son utilidad recibidos (saldo inicial y similares)", t["no_utilidad_entrada"]),
        ("Fondos que no son utilidad devueltos", -t["no_utilidad_salida"]),
        ("Ganancias pagadas a afiliados", t[c.GANANCIAS]),
    ]
    filas, netos = [], []
    for titulo, lineas_, cierre in (("ACTIVIDADES DE OPERACIÓN", operacion, "Efectivo neto de la operación"),
                                    ("CARTERA DE PRÉSTAMOS (INVERSIÓN)", cartera_, "Efectivo neto de la cartera"),
                                    ("ACTIVIDADES DE FINANCIAMIENTO", financiamiento,
                                     "Efectivo neto del financiamiento")):
        filas.append(_seccion(titulo))
        filas += [_linea(concepto, [redondear(valor)]) for concepto, valor in lineas_]
        neto = redondear(sum((valor for _, valor in lineas_), CERO))
        netos.append(neto)
        filas.append(_subtotal(cierre, [neto]))
    aumento = sum(netos, CERO)
    inicial = c.saldo(hasta=desde - timedelta(days=1))
    final = c.saldo(hasta=hasta)
    filas += [_total("AUMENTO (DISMINUCIÓN) NETO DEL EFECTIVO", [aumento]),
              _linea("Efectivo al inicio del período", [inicial], nivel=0),
              _total("EFECTIVO AL FINAL DEL PERÍODO", [inicial + aumento])]
    return Estado(
        titulo="Estado de flujo de efectivo", subtitulo=f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y} · método directo",
        columnas=["Monto"], filas=_lineas_no_vacias(filas),
        nota="Las transferencias entre cajas y cuentas de CAUNE no cambian el efectivo total y no se muestran. Lo "
             "pagado de más en un préstamo aparece como aportación o depósito, según a dónde se acreditó.",
        resumen=[("Efectivo final", final), ("Efectivo inicial", inicial), ("Aumento neto", aumento)],
        diferencia=inicial + aumento - final)


# --------------------------------------------------------------------------- 19. indicadores

def indicadores(hasta):
    """Indicadores financieros básicos al corte, con la utilidad del ejercicio en curso."""
    s = situacion(hasta)
    util = utilidad(inicio_ejercicio(hasta), hasta)
    filas = []

    def agregar(nombre, calculo, valor, lectura, sufijo=" %"):
        filas.append({"url": "", "valores": [nombre, calculo, f"{valor:,.2f}{sufijo}", lectura]})

    agregar("Liquidez", "Efectivo ÷ depósitos y ganancias por pagar",
            (s["efectivo"] / s["pasivo"]) if s["pasivo"] else CERO,
            "Veces que el efectivo cubre lo que se debe devolver a la vista.", sufijo=" veces")
    agregar("Colocación", "Cartera ÷ activo total", porcentaje(s["cartera"], s["activo"]),
            "Parte de los recursos prestada.")
    morosidad = morosidad_actual() if hasta == timezone.localdate() else None
    if morosidad is not None:
        agregar("Morosidad", "Capital de préstamos con atraso ÷ cartera", morosidad["indice"],
                "Parte de la cartera con al menos una cuota vencida (a hoy).")
    agregar("Capitalización", "Patrimonio ÷ activo total", porcentaje(s["patrimonio"], s["activo"]),
            "Parte de los recursos que pertenece a CAUNE y sus afiliados como capital.")
    agregar("Endeudamiento", "Pasivo ÷ activo total", porcentaje(s["pasivo"], s["activo"]),
            "Parte de los recursos que se debe devolver.")
    agregar("Rentabilidad sobre aportaciones", f"Utilidad {hasta.year} ÷ aportaciones",
            porcentaje(util["neto"], s["aportaciones"]), "Rendimiento del año para el capital de los afiliados.")
    agregar("Rentabilidad sobre activos", f"Utilidad {hasta.year} ÷ activo total",
            porcentaje(util["neto"], s["activo"]), "Rendimiento del año sobre todos los recursos.")
    agregar("Margen neto", f"Utilidad {hasta.year} ÷ ingresos {hasta.year}",
            porcentaje(util["neto"], util["ingresos_totales"]), "Parte de los ingresos que queda como utilidad.")
    agregar("Peso de los intereses", "Ingresos financieros ÷ ingresos totales",
            porcentaje(util["financieros"], util["ingresos_totales"]),
            "Cuánto dependen los ingresos de los préstamos.")
    return {"filas": filas, "situacion": s, "utilidad": util, "morosidad": morosidad}


# --------------------------------------------------------------------------- 20 y 21. caja y bancos

def movimiento_por_cuenta(desde, hasta):
    """Saldo inicial, entradas, salidas y saldo final de cada caja y cuenta en el período."""
    inicial, entradas, salidas = defaultdict(lambda: CERO), defaultdict(lambda: CERO), defaultdict(lambda: CERO)
    for f in caja_services.lineas(hasta=hasta):
        if f.fecha < desde:
            inicial[f.cuenta.pk] += f.neto
        else:
            entradas[f.cuenta.pk] += f.entrada
            salidas[f.cuenta.pk] += f.salida
    filas = []
    for cuenta in CuentaFondo.objects.order_by("tipo", "nombre"):
        i, e, s = redondear(inicial[cuenta.pk]), redondear(entradas[cuenta.pk]), redondear(salidas[cuenta.pk])
        if not cuenta.activa and not (i or e or s):
            continue
        filas.append({"cuenta": cuenta, "inicial": i, "entradas": e, "salidas": s, "final": i + e - s})
    return filas


def caja_diaria(cuenta, desde, hasta):
    """Entradas, salidas y saldo al cierre de cada día con operaciones."""
    inicial = caja_services.saldo(cuenta, hasta=desde - timedelta(days=1))
    dias = {}
    for f in caja_services.lineas(cuenta, desde, hasta):
        if cuenta is None and f.origen == caja_services.TRANSFERENCIAS:
            continue  # en el consolidado una transferencia entra y sale el mismo día
        d = dias.setdefault(f.fecha, {"fecha": f.fecha, "operaciones": 0, "entradas": CERO, "salidas": CERO})
        d["operaciones"] += 1
        d["entradas"] += f.entrada
        d["salidas"] += f.salida
    acumulado, filas = inicial, []
    for d in sorted(dias.values(), key=lambda x: x["fecha"]):
        d["neto"] = d["entradas"] - d["salidas"]
        acumulado += d["neto"]
        d["saldo"] = acumulado
        filas.append(d)
    return {"inicial": inicial, "filas": filas, "final": acumulado,
            "entradas": sum((d["entradas"] for d in filas), CERO), "salidas": sum((d["salidas"] for d in filas), CERO)}


# --------------------------------------------------------------------------- 22. antigüedad de la cartera

RANGOS = [(0, 0, "Al día"), (1, 30, "1 a 30 días"), (31, 60, "31 a 60 días"), (61, 90, "61 a 90 días"),
          (91, None, "Más de 90 días")]


def rango_atraso(dias):
    for minimo, maximo, nombre in RANGOS:
        if dias >= minimo and (maximo is None or dias <= maximo):
            return nombre
    return RANGOS[0][2]


def antiguedad_cartera(tipo=None):
    """Préstamos vigentes clasificados por los días de atraso de su cuota más antigua, a hoy."""
    qs = (Prestamo.objects.filter(estado=Prestamo.Estado.VIGENTE, fecha_desembolso__isnull=False)
          .select_related("afiliado", "prestatario_externo").order_by("numero"))
    if tipo:
        qs = qs.filter(tipo_prestatario=tipo)
    prestamos = []
    for p in qs:
        r = pre_services.resumen(p)
        dias = max((c.dias_atraso for c in r.cuotas), default=0)
        vencido = sum((c.capital_pendiente for c in r.cuotas if c.dias_atraso > 0), CERO)
        intereses = sum((c.interes_pendiente for c in r.cuotas if c.dias_atraso > 0), CERO)
        prestamos.append({"prestamo": p, "dias": dias, "rango": rango_atraso(dias), "saldo": r.saldo_capital,
                          "vencido": vencido, "intereses": intereses, "mora": r.mora_pendiente})
    total = sum((x["saldo"] for x in prestamos), CERO)
    en_mora = sum((x["saldo"] for x in prestamos if x["dias"] > 0), CERO)
    return {"prestamos": prestamos, "total": total, "en_mora": en_mora, "indice": porcentaje(en_mora, total),
            "mora": sum((x["mora"] for x in prestamos), CERO)}


def morosidad_actual():
    a = antiguedad_cartera()
    return {"indice": a["indice"], "en_mora": a["en_mora"], "total": a["total"]}


def estado_antiguedad(tipo=None):
    a = antiguedad_cartera(tipo)
    filas = []
    for _, _, nombre in RANGOS:
        grupo = [x for x in a["prestamos"] if x["rango"] == nombre]
        if not grupo:
            continue
        filas.append(_seccion(nombre.upper()))
        for x in sorted(grupo, key=lambda y: -y["dias"]):
            p = x["prestamo"]
            filas.append(_linea(f"{p.numero} · {p.prestatario_nombre}" + (f" ({x['dias']} días)" if x["dias"] else ""),
                                [x["saldo"], x["vencido"], x["intereses"], x["mora"],
                                 f"{porcentaje(x['saldo'], a['total']):.2f} %"],
                                url=reverse("prestamos:detalle", args=[p.pk])))
        saldo = sum((x["saldo"] for x in grupo), CERO)
        filas.append(_subtotal(f"Subtotal {nombre.lower()} ({len(grupo)})",
                               [saldo, sum((x["vencido"] for x in grupo), CERO),
                                sum((x["intereses"] for x in grupo), CERO), sum((x["mora"] for x in grupo), CERO),
                                f"{porcentaje(saldo, a['total']):.2f} %"]))
    filas.append(_total("TOTAL CARTERA VIGENTE", [a["total"], sum((x["vencido"] for x in a["prestamos"]), CERO),
                                                  sum((x["intereses"] for x in a["prestamos"]), CERO), a["mora"],
                                                  "100.00 %" if a["total"] else ""]))
    return Estado(
        titulo="Antigüedad de la cartera de préstamos", subtitulo=f"Al {timezone.localdate():%d/%m/%Y}",
        columnas=["Saldo capital", "Capital vencido", "Intereses vencidos", "Mora pendiente", "% de la cartera"],
        filas=filas, firmas=False,
        nota="Cada préstamo se clasifica por los días de atraso de su cuota vencida más antigua. Índice de morosidad "
             "= saldo de los préstamos con atraso ÷ cartera vigente.",
        resumen=[("Cartera vigente", a["total"]), ("Cartera con atraso", a["en_mora"]),
                 ("Índice de morosidad", f"{a['indice']:.2f} %"), ("Mora pendiente", a["mora"])])

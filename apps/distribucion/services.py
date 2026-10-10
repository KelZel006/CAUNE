"""Distribución de ganancias entre los afiliados (socios internos).

Reglas (Fase 3):
- Solo participan los afiliados. Los prestatarios externos nunca reciben ganancias.
- Quien más aporta, más recibe: cada fondo se reparte en proporción a la base de cada afiliado, que es su saldo
  de aportaciones (tipos marcados «cuenta para la distribución»). Según la configuración, la base es el saldo
  promedio de cada día del período o el saldo al último día.
- Hay un fondo de «utilidad general» (intereses y mora cobrados de préstamos + otros ingresos de caja − otros egresos
  de caja que afectan utilidades) y un fondo por cada actividad económica con resultado en el período.
- En cada actividad pueden marcarse afiliados que NO participan: no reciben nada de ese fondo, pero sí su parte
  del resto de utilidades. El fondo de esa actividad se reparte solo entre los demás.
- Una actividad con pérdida reparte su pérdida entre quienes participan en ella. Si a algún afiliado le resulta
  un total negativo, la distribución no puede aprobarse hasta que la directiva lo resuelva.
- Los centavos se reparten por el método del mayor residuo: la suma de las partes es exactamente el fondo.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal, localcontext

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.actividades import services as act_services
from apps.actividades.models import Actividad, MovimientoActividad
from apps.afiliados.models import Afiliado, CambioEstadoAfiliado
from apps.aportaciones import services as mov_services
from apps.aportaciones.models import MovimientoAfiliado, TipoMovimiento
from apps.caja import services as caja_services
from apps.core import auditoria, parametros
from apps.core.dinero import CENTAVO, CERO, redondear
from apps.core.models import CuentaFondo
from apps.core.secuencias import siguiente_numero
from apps.prestamos import services as pre_services

from .models import Distribucion, FondoDistribucion, LineaDistribucion, PagoGanancia


# --------------------------------------------------------------------------- base de cada afiliado

def estado_en(afiliado, fecha, cambios=None):
    """Estado (ACTIVO/INACTIVO) del afiliado al final del día `fecha`, según su historial de cambios."""
    if cambios is None:
        cambios = list(afiliado.cambios_estado.order_by("fecha_efectiva", "id"))
    anteriores = [c for c in cambios if c.fecha_efectiva <= fecha]
    if anteriores:
        return anteriores[-1].estado_nuevo
    if cambios:
        return cambios[0].estado_anterior
    return afiliado.estado


def _movimientos_base(hasta):
    """Netos diarios de los tipos que cuentan para la distribución, por afiliado."""
    qs = (MovimientoAfiliado.objects.confirmados()
          .filter(tipo__participa_distribucion=True, fecha__lte=hasta)
          .values_list("afiliado_id", "fecha", "monto", "tipo__naturaleza"))
    netos = defaultdict(lambda: defaultdict(lambda: CERO))
    for afiliado_id, fecha, monto, naturaleza in qs:
        netos[afiliado_id][fecha] += -monto if naturaleza == TipoMovimiento.Naturaleza.SALIDA else monto
    return netos


def peso_afiliado(netos_por_fecha, desde, hasta, base):
    """Devuelve (peso, base_mostrada).

    SALDO_CIERRE: peso = saldo al último día.
    PROMEDIO_DIARIO: peso = suma del saldo al final de cada día del período (saldo × días);
    base mostrada = peso / días del período.
    """
    if base == Distribucion.Base.SALDO_CIERRE:
        saldo_final = sum((m for f, m in netos_por_fecha.items() if f <= hasta), CERO)
        return saldo_final, redondear(saldo_final)
    dias = (hasta - desde).days + 1
    saldo = sum((m for f, m in netos_por_fecha.items() if f < desde), CERO)
    peso, anterior = CERO, desde
    for f in sorted(x for x in netos_por_fecha if desde <= x <= hasta):
        peso += saldo * (f - anterior).days
        saldo += netos_por_fecha[f]
        anterior = f
    peso += saldo * ((hasta - anterior).days + 1)
    return peso, redondear(peso / dias)


def repartir(total, pesos):
    """Reparte `total` en proporción a `pesos` {clave: peso>0}. La suma de las partes es exactamente `total`.

    Cada parte se trunca al centavo y los centavos sobrantes se asignan a los mayores residuos
    (empate: orden de la clave, que es el código del afiliado).
    """
    suma = sum(pesos.values(), CERO)
    if not pesos or suma <= 0:
        return {}
    signo = -1 if total < 0 else 1
    absoluto = abs(total)
    with localcontext() as ctx:
        ctx.prec = 50
        exactos = {k: absoluto * p / suma for k, p in pesos.items()}
    partes = {k: v.quantize(CENTAVO, rounding=ROUND_DOWN) for k, v in exactos.items()}
    sobrante = int((absoluto - sum(partes.values(), CERO)) / CENTAVO)
    for k in sorted(pesos, key=lambda k: (-(exactos[k] - partes[k]), k))[:sobrante]:
        partes[k] += CENTAVO
    return {k: v * signo for k, v in partes.items()}


# --------------------------------------------------------------------------- cálculo

@dataclass
class Participante:
    afiliado: Afiliado
    peso: Decimal
    base: Decimal


@dataclass
class Fondo:
    tipo: str
    actividad: object
    ingresos: Decimal
    gastos: Decimal
    reserva: Decimal
    detalle: dict
    excluidos: set = field(default_factory=set)
    partes: dict = field(default_factory=dict)
    participantes: int = 0

    @property
    def resultado(self):
        return self.ingresos - self.gastos

    @property
    def a_distribuir(self):
        return self.resultado - self.reserva


@dataclass
class Calculo:
    desde: object
    hasta: object
    base: str
    porcentaje_reserva: Decimal
    incluye_inactivos: bool
    participantes: list
    fondos: list
    no_elegibles: list

    def huella(self):
        """Representación comparable del resultado (para saber si los datos cambiaron desde el cálculo)."""
        return sorted((f.tipo, f.actividad.pk if f.actividad else 0, str(f.resultado), str(f.reserva),
                       tuple(sorted((k, str(v)) for k, v in f.partes.items()))) for f in self.fondos)


def _reserva(resultado, porcentaje):
    return redondear(resultado * porcentaje / 100) if resultado > 0 else CERO


def calcular(desde, hasta, *, base=None, porcentaje_reserva=None, incluir_inactivos=None):
    """Calcula (sin guardar) cómo se repartirían las ganancias del período."""
    if desde is None or hasta is None or desde > hasta:
        raise ValidationError("Indique un período válido: la fecha inicial no puede ser posterior a la final.")
    if hasta > timezone.localdate():
        raise ValidationError({"fecha_fin": "El período no puede terminar en una fecha futura."})
    base = base or parametros.obtener("distribucion.base_calculo")
    porcentaje = (parametros.obtener("distribucion.porcentaje_reserva") if porcentaje_reserva is None
                  else Decimal(porcentaje_reserva)) or CERO
    inactivos = (parametros.obtener("distribucion.incluir_inactivos") if incluir_inactivos is None
                 else incluir_inactivos)

    # 1. Participantes: afiliados que ingresaron antes del cierre, activos al cierre (salvo configuración) y con base.
    netos = _movimientos_base(hasta)
    cambios = defaultdict(list)
    for c in CambioEstadoAfiliado.objects.order_by("fecha_efectiva", "id"):
        cambios[c.afiliado_id].append(c)
    participantes, no_elegibles = [], []
    for a in Afiliado.objects.filter(fecha_ingreso__lte=hasta).order_by("codigo"):
        if not inactivos and estado_en(a, hasta, cambios[a.pk]) != Afiliado.Estado.ACTIVO:
            no_elegibles.append((a, "Inactivo al cierre del período"))
            continue
        peso, base_mostrada = peso_afiliado(netos.get(a.pk, {}), desde, hasta, base)
        if peso <= 0:
            no_elegibles.append((a, "Sin saldo de aportaciones en el período"))
            continue
        participantes.append(Participante(a, peso, base_mostrada))

    # 2. Fondos: utilidad general y una por actividad con movimientos en el período.
    intereses = pre_services.intereses_cobrados(desde, hasta)
    mora = pre_services.mora_cobrada(desde, hasta)
    otros = caja_services.otros_resultados(desde, hasta)
    general = Fondo(FondoDistribucion.Tipo.GENERAL, None,
                    ingresos=intereses + mora + otros["ingresos"], gastos=otros["egresos"], reserva=CERO,
                    detalle={"intereses_prestamos": str(intereses), "mora_prestamos": str(mora),
                             "otros_ingresos": str(otros["ingresos"]),
                             "otros_egresos": str(otros["egresos"]),
                             "por_categoria": {k: str(v) for k, v in otros["por_categoria"].items()}})
    fondos = [general]
    con_movimientos = (MovimientoActividad.objects.confirmados().filter(fecha__gte=desde, fecha__lte=hasta)
                       .values_list("actividad_id", flat=True).distinct())
    for actividad in Actividad.objects.filter(pk__in=con_movimientos).order_by("codigo"):
        r = act_services.resultado_actividad(actividad, desde, hasta)
        if r["ingresos"] == 0 and r["gastos"] == 0:
            continue
        fondos.append(Fondo(FondoDistribucion.Tipo.ACTIVIDAD, actividad, ingresos=r["ingresos"], gastos=r["gastos"],
                            reserva=CERO, detalle={}, excluidos=act_services.excluidos_ids(actividad)))

    # 3. Reparto de cada fondo entre sus participantes.
    for f in fondos:
        f.reserva = _reserva(f.resultado, porcentaje)
        pesos = {p.afiliado.codigo: p.peso for p in participantes if p.afiliado.pk not in f.excluidos}
        f.participantes = len(pesos)
        f.partes = repartir(f.a_distribuir, pesos) if f.a_distribuir else {}
    return Calculo(desde, hasta, base, porcentaje, inactivos, participantes, fondos, no_elegibles)


def totales_por_afiliado(calculo):
    """{codigo: total} sumando todos los fondos."""
    totales = defaultdict(lambda: CERO)
    for f in calculo.fondos:
        for codigo, monto in f.partes.items():
            totales[codigo] += monto
    return dict(totales)


# --------------------------------------------------------------------------- guardar la fotografía

def _guardar_calculo(dist, calculo):
    por_codigo = {p.afiliado.codigo: p for p in calculo.participantes}
    suma_pesos = {}
    for orden, f in enumerate(calculo.fondos):
        fondo = FondoDistribucion.objects.create(
            distribucion=dist, tipo=f.tipo, actividad=f.actividad, orden=orden, ingresos=f.ingresos, gastos=f.gastos,
            resultado=f.resultado, reserva=f.reserva, a_distribuir=f.a_distribuir, participantes=f.participantes,
            excluidos=len([p for p in calculo.participantes if p.afiliado.pk in f.excluidos]), detalle=f.detalle)
        pesos = {c: por_codigo[c].peso for c in por_codigo if por_codigo[c].afiliado.pk not in f.excluidos}
        suma_pesos[orden] = sum(pesos.values(), CERO)
        lineas = []
        for codigo, monto in f.partes.items():
            p = por_codigo[codigo]
            with localcontext() as ctx:
                ctx.prec = 40
                porcentaje = (p.peso * 100 / suma_pesos[orden]).quantize(Decimal("0.000001"))
            lineas.append(LineaDistribucion(fondo=fondo, afiliado=p.afiliado, base=p.base, porcentaje=porcentaje,
                                            monto=monto))
        LineaDistribucion.objects.bulk_create(lineas)


def _validar_periodo_libre(desde, hasta, excluir_pk=None):
    choque = (Distribucion.objects.exclude(estado=Distribucion.Estado.ANULADA)
              .filter(fecha_inicio__lte=hasta, fecha_fin__gte=desde))
    if excluir_pk:
        choque = choque.exclude(pk=excluir_pk)
    otra = choque.first()
    if otra is not None:
        raise ValidationError(f"El período se cruza con la distribución {otra.codigo} "
                              f"({otra.fecha_inicio:%d/%m/%Y} al {otra.fecha_fin:%d/%m/%Y}). "
                              "Una utilidad no puede repartirse dos veces.")


@transaction.atomic
def crear_distribucion(*, desde, hasta, usuario, observaciones=""):
    if not usuario.has_perm("distribucion.add_distribucion"):
        raise ValidationError("No tiene permiso para calcular distribuciones de ganancias.")
    _validar_periodo_libre(desde, hasta)
    calculo = calcular(desde, hasta)
    dist = Distribucion.objects.create(
        codigo=siguiente_numero("DIST"), fecha_inicio=desde, fecha_fin=hasta, base_calculo=calculo.base,
        porcentaje_reserva=calculo.porcentaje_reserva, incluye_inactivos=calculo.incluye_inactivos,
        observaciones=(observaciones or "").strip(), calculado_por=usuario, calculado_en=timezone.now())
    _guardar_calculo(dist, calculo)
    auditoria.registrar(auditoria.Accion.CREAR, usuario=usuario, objeto=dist,
                        descripcion=f"Cálculo de la distribución {dist.codigo} "
                                    f"({desde:%d/%m/%Y} al {hasta:%d/%m/%Y})",
                        despues={**auditoria.instantanea(dist), "resumen": resumen_texto(dist)})
    return dist


@transaction.atomic
def recalcular(dist, *, usuario):
    """Vuelve a calcular un borrador con los datos y la configuración actuales."""
    if not usuario.has_perm("distribucion.add_distribucion"):
        raise ValidationError("No tiene permiso para calcular distribuciones de ganancias.")
    dist = Distribucion.objects.select_for_update().get(pk=dist.pk)
    if not dist.editable:
        raise ValidationError("Solo se recalcula una distribución en borrador (calculada y no aprobada).")
    antes = resumen_texto(dist)
    calculo = calcular(dist.fecha_inicio, dist.fecha_fin)
    dist.fondos.all().delete()
    dist.base_calculo = calculo.base
    dist.porcentaje_reserva = calculo.porcentaje_reserva
    dist.incluye_inactivos = calculo.incluye_inactivos
    dist.calculado_por = usuario
    dist.calculado_en = timezone.now()
    dist.save(update_fields=["base_calculo", "porcentaje_reserva", "incluye_inactivos", "calculado_por",
                             "calculado_en"])
    _guardar_calculo(dist, calculo)
    auditoria.registrar(auditoria.Accion.MODIFICAR, usuario=usuario, objeto=dist,
                        descripcion=f"Recálculo de la distribución {dist.codigo}", antes={"resumen": antes},
                        despues={"resumen": resumen_texto(dist)})
    return dist


def _huella_guardada(dist):
    filas = []
    for f in dist.fondos.prefetch_related("lineas__afiliado"):
        filas.append((f.tipo, f.actividad_id or 0, str(f.resultado), str(f.reserva),
                      tuple(sorted((l.afiliado.codigo, str(l.monto)) for l in f.lineas.all()))))
    return sorted(filas)


@transaction.atomic
def aprobar(dist, *, usuario):
    if not usuario.has_perm("distribucion.aprobar_distribucion"):
        raise ValidationError("No tiene permiso para aprobar distribuciones de ganancias.")
    dist = Distribucion.objects.select_for_update().get(pk=dist.pk)
    if not dist.editable:
        raise ValidationError("Solo se aprueba una distribución calculada que aún no se ha aprobado.")
    if (parametros.obtener("distribucion.aprobacion_requiere_otro_usuario")
            and dist.calculado_por_id == usuario.pk):
        raise ValidationError("La distribución debe aprobarla un usuario distinto al que la calculó.")
    _validar_periodo_libre(dist.fecha_inicio, dist.fecha_fin, excluir_pk=dist.pk)
    actual = calcular(dist.fecha_inicio, dist.fecha_fin, base=dist.base_calculo,
                      porcentaje_reserva=dist.porcentaje_reserva, incluir_inactivos=dist.incluye_inactivos)
    if actual.huella() != _huella_guardada(dist):
        raise ValidationError("Los datos del período cambiaron después del cálculo (movimientos nuevos, anulados o "
                              "cambios en quién participa). Recalcule la distribución y revísela antes de aprobarla.")
    negativos = [(c, t) for c, t in totales_por_afiliado(actual).items() if t < 0]
    if negativos:
        lista = ", ".join(f"{c} (L {t:,.2f})" for c, t in sorted(negativos))
        raise ValidationError(f"Hay afiliados con resultado negativo: {lista}. La pérdida de alguna actividad supera "
                              "su parte de las ganancias. Revise qué afiliados participan en esa actividad.")
    if not any(t > 0 for t in totales_por_afiliado(actual).values()):
        raise ValidationError("No hay ganancias que repartir en este período.")
    dist.estado = Distribucion.Estado.APROBADA
    dist.aprobado_por = usuario
    dist.aprobado_en = timezone.now()
    dist.save(update_fields=["estado", "aprobado_por", "aprobado_en"])
    auditoria.registrar(auditoria.Accion.CAMBIO_ESTADO, usuario=usuario, objeto=dist,
                        descripcion=f"Aprobación de la distribución {dist.codigo}",
                        antes={"estado": Distribucion.Estado.CALCULADA}, despues={"estado": dist.estado})
    return dist


@transaction.atomic
def anular(dist, *, usuario, motivo):
    if not usuario.has_perm("distribucion.anular_distribucion"):
        raise ValidationError("No tiene permiso para anular distribuciones.")
    motivo = (motivo or "").strip()
    if len(motivo) < 10:
        raise ValidationError({"motivo": "Explique el motivo de la anulación (mínimo 10 caracteres)."})
    dist = Distribucion.objects.select_for_update().get(pk=dist.pk)
    if dist.estado == Distribucion.Estado.ANULADA:
        raise ValidationError("La distribución ya está anulada.")
    if dist.pagos.confirmados().exists():
        raise ValidationError("La distribución ya tiene ganancias pagadas o capitalizadas. Anule primero esos pagos.")
    anterior = dist.estado
    dist.estado = Distribucion.Estado.ANULADA
    dist.anulado_por = usuario
    dist.anulado_en = timezone.now()
    dist.motivo_anulacion = motivo
    dist.save(update_fields=["estado", "anulado_por", "anulado_en", "motivo_anulacion"])
    auditoria.registrar(auditoria.Accion.ANULAR, usuario=usuario, objeto=dist,
                        descripcion=f"Anulación de la distribución {dist.codigo}. Motivo: {motivo}",
                        antes={"estado": anterior}, despues={"estado": dist.estado})
    return dist


# --------------------------------------------------------------------------- consulta

def resumen(dist):
    """Totales de la distribución y una fila por afiliado con su parte en cada fondo."""
    fondos = list(dist.fondos.select_related("actividad").prefetch_related("lineas__afiliado"))
    pagos = {p.afiliado_id: p for p in dist.pagos.confirmados()}
    filas = {}
    for f in fondos:
        for l in f.lineas.all():
            fila = filas.setdefault(l.afiliado_id, {"afiliado": l.afiliado, "base": l.base, "porcentaje": None,
                                                    "partes": {}, "total": CERO})
            fila["partes"][f.pk] = l.monto
            fila["total"] += l.monto
            if f.tipo == FondoDistribucion.Tipo.GENERAL:
                fila["porcentaje"] = l.porcentaje
    for fila in filas.values():
        fila["por_fondo"] = [fila["partes"].get(f.pk) for f in fondos]
        fila["pago"] = pagos.get(fila["afiliado"].pk)
    lista = sorted(filas.values(), key=lambda x: x["afiliado"].codigo)
    total = sum((x["total"] for x in lista), CERO)
    entregado = sum((p.monto for p in pagos.values()), CERO)
    return {
        "fondos": fondos, "filas": lista,
        "resultado": sum((f.resultado for f in fondos), CERO),
        "reserva": sum((f.reserva for f in fondos), CERO),
        "sin_asignar": sum((f.sin_asignar for f in fondos), CERO),
        "total": total, "entregado": entregado,
        "pendiente": sum((x["total"] for x in lista if x["pago"] is None and x["total"] > 0), CERO),
        "negativos": [x for x in lista if x["total"] < 0],
    }


def resumen_texto(dist):
    r = resumen(dist)
    return {"resultado": str(r["resultado"]), "reserva": str(r["reserva"]), "total": str(r["total"]),
            "afiliados": len(r["filas"])}


def ganancias_afiliado(afiliado):
    """Lo que le tocó al afiliado en cada distribución aprobada o aplicada."""
    filas = []
    dists = (Distribucion.objects.filter(estado__in=[Distribucion.Estado.APROBADA, Distribucion.Estado.APLICADA],
                                         fondos__lineas__afiliado=afiliado).distinct().order_by("-fecha_fin"))
    for d in dists:
        total = sum((l.monto for l in LineaDistribucion.objects.filter(fondo__distribucion=d, afiliado=afiliado)), CERO)
        filas.append({"distribucion": d, "total": total,
                      "pago": d.pagos.confirmados().filter(afiliado=afiliado).first()})
    return filas


# --------------------------------------------------------------------------- pago o capitalización

METODO_CAPITALIZACION = {CuentaFondo.Tipo.CAJA: "EFECTIVO", CuentaFondo.Tipo.BANCO: "DEPOSITO_BANCARIO"}


def registrar_pagos(dist, *, afiliados, forma, fecha, cuenta_fondo, metodo_pago, usuario, referencia=""):
    """Entrega la ganancia de cada afiliado indicado: en dinero (sale de caja) o capitalizada en su cuenta.

    Todo o nada: si a uno no se le puede entregar, no se registra ninguno.
    """
    from apps.prestamos.services import _validar_cuenta_metodo

    if not usuario.has_perm("distribucion.aplicar_distribucion"):
        raise ValidationError("No tiene permiso para pagar o capitalizar ganancias.")
    errores = {}
    if forma not in PagoGanancia.Forma.values:
        errores["forma"] = "Indique si se paga o se capitaliza."
    if fecha is None or fecha > timezone.localdate():
        errores["fecha"] = "La fecha es obligatoria y no puede ser futura."
    elif fecha < dist.fecha_fin:
        errores["fecha"] = "La entrega no puede ser anterior al cierre del período distribuido."
    if forma == PagoGanancia.Forma.CAPITALIZACION and isinstance(cuenta_fondo, CuentaFondo):
        metodo_pago = METODO_CAPITALIZACION[cuenta_fondo.tipo]
        referencia = referencia or dist.codigo
    _validar_cuenta_metodo(metodo_pago, cuenta_fondo, referencia, errores)
    if not afiliados:
        errores["afiliados"] = "Seleccione al menos un afiliado."
    if errores:
        raise ValidationError(errores)
    creados = []
    with transaction.atomic():
        dist = Distribucion.objects.select_for_update().get(pk=dist.pk)
        if dist.estado != Distribucion.Estado.APROBADA:
            raise ValidationError("Solo se pagan o capitalizan ganancias de una distribución aprobada.")
        totales = {fila["afiliado"].pk: fila for fila in resumen(dist)["filas"]}
        if forma == PagoGanancia.Forma.PAGO:
            CuentaFondo.objects.select_for_update().get(pk=cuenta_fondo.pk)
        for afiliado in afiliados:
            fila = totales.get(afiliado.pk)
            if fila is None or fila["total"] <= 0:
                raise ValidationError({"afiliados": f"{afiliado.codigo} no tiene ganancias por recibir en "
                                                    f"{dist.codigo}."})
            if fila["pago"] is not None or dist.pagos.confirmados().filter(afiliado=afiliado).exists():
                raise ValidationError({"afiliados": f"La ganancia de {afiliado.codigo} ya se entregó."})
            monto = fila["total"]
            movimiento = None
            if forma == PagoGanancia.Forma.PAGO:
                caja_services.validar_saldo_disponible(cuenta_fondo, fecha, monto)
            else:
                tipo = TipoMovimiento.objects.filter(
                    codigo=parametros.obtener("distribucion.tipo_capitalizacion")).first()
                if tipo is None:
                    raise ValidationError("Configure el tipo de movimiento para capitalizar ganancias.")
                try:
                    movimiento, _ = mov_services.registrar_movimiento(
                        afiliado=afiliado, tipo=tipo, fecha=fecha, monto=monto, metodo_pago=metodo_pago,
                        cuenta_fondo=cuenta_fondo, usuario=usuario, referencia=referencia,
                        observacion=f"Ganancias capitalizadas de la distribución {dist.codigo}")
                except ValidationError as error:
                    detalle = " ".join(error.messages)
                    raise ValidationError({"afiliados": f"{afiliado.codigo}: {detalle}"}) from None
            pago = PagoGanancia.objects.create(
                numero=siguiente_numero("PG"), distribucion=dist, afiliado=afiliado, forma=forma, fecha=fecha,
                monto=monto, metodo_pago=metodo_pago, cuenta_fondo=cuenta_fondo, referencia=(referencia or "").strip(),
                movimiento_afiliado=movimiento, registrado_por=usuario)
            auditoria.registrar(auditoria.Accion.CREAR, usuario=usuario, objeto=pago,
                                descripcion=f"{pago.get_forma_display()} {pago.numero}: L {monto:,.2f} a "
                                            f"{afiliado.codigo} ({dist.codigo})",
                                despues=auditoria.instantanea(pago))
            creados.append(pago)
        _actualizar_estado(dist)
    return creados


def _actualizar_estado(dist):
    """APLICADA cuando todos los que tienen ganancia ya la recibieron; si se anula un pago, vuelve a APROBADA."""
    r = resumen(dist)
    completa = all(x["pago"] is not None for x in r["filas"] if x["total"] > 0)
    nuevo = Distribucion.Estado.APLICADA if completa else Distribucion.Estado.APROBADA
    if dist.estado != nuevo:
        anterior = dist.estado
        dist.estado = nuevo
        dist.save(update_fields=["estado"])
        auditoria.registrar(auditoria.Accion.CAMBIO_ESTADO, objeto=dist,
                            descripcion=f"Distribución {dist.codigo}: {anterior} → {nuevo}",
                            antes={"estado": anterior}, despues={"estado": nuevo})


@transaction.atomic
def anular_pago(pago, *, usuario, motivo):
    if not usuario.has_perm("distribucion.anular_pagoganancia"):
        raise ValidationError("No tiene permiso para anular pagos de ganancias.")
    motivo = (motivo or "").strip()
    if len(motivo) < 10:
        raise ValidationError({"motivo": "Explique el motivo de la anulación (mínimo 10 caracteres)."})
    dist = Distribucion.objects.select_for_update().get(pk=pago.distribucion_id)
    pago = PagoGanancia.objects.select_for_update().get(pk=pago.pk)
    if not pago.confirmado:
        raise ValidationError("El pago ya está anulado.")
    if parametros.obtener("movimientos.anulacion_requiere_otro_usuario") and pago.registrado_por_id == usuario.pk:
        raise ValidationError("La anulación debe autorizarla un usuario distinto al que registró el pago.")
    if pago.movimiento_afiliado_id:
        mov_services.anular_movimiento(pago.movimiento_afiliado, usuario=usuario,
                                       motivo=f"Anulación de {pago.numero}: {motivo}", automatico=True)
    antes = auditoria.instantanea(pago)
    pago.estado = PagoGanancia.Estado.ANULADO
    pago.anulado_por = usuario
    pago.anulado_en = timezone.now()
    pago.motivo_anulacion = motivo
    pago.save(update_fields=["estado", "anulado_por", "anulado_en", "motivo_anulacion"])
    auditoria.registrar(auditoria.Accion.ANULAR, usuario=usuario, objeto=pago,
                        descripcion=f"Anulación de {pago.numero} ({dist.codigo}). Motivo: {motivo}",
                        antes=antes, despues=auditoria.instantanea(pago))
    _actualizar_estado(dist)
    return pago


def ganancias_por_pagar():
    """Total aprobado que aún no se ha pagado ni capitalizado."""
    total = CERO
    for d in Distribucion.objects.filter(estado=Distribucion.Estado.APROBADA):
        total += resumen(d)["pendiente"]
    return total

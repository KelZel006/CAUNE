"""Liquidación de un afiliado que se retira de CAUNE.

Haberes = saldo de aportaciones + saldo de depósitos + ganancias de distribuciones aprobadas que aún no se le entregan.
Deudas  = lo que debe de sus préstamos vigentes (capital, intereses del cuadro aprobado y mora a la fecha) y, si se
          decide descontarlos, lo que deben los préstamos de terceros que avala.
Neto a entregar = haberes − deudas.

Al ejecutarla se registran las operaciones en sus propios módulos, en este orden, todas con la fecha del día:
1. Un pago por el total de cada préstamo vigente (se compensa con sus haberes; el préstamo queda cancelado), también
   los de terceros que avala si se decidió descontarlos.
2. La entrega en dinero de cada ganancia pendiente.
3. La devolución de sus depósitos (RDEP) y de sus aportaciones (RAPO).
4. La baja: el afiliado pasa a inactivo.
Así el libro de caja, los estados financieros y la auditoría reflejan la liquidación sin asientos aparte.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.afiliados.models import Afiliado, CambioEstadoAfiliado
from apps.afiliados.services import cambiar_estado
from apps.aportaciones import services as mov_services
from apps.aportaciones.models import TipoMovimiento
from apps.core import auditoria, parametros
from apps.core.dinero import CERO
from apps.core.secuencias import siguiente_numero
from apps.distribucion import services as dist_services
from apps.distribucion.models import Distribucion, PagoGanancia
from apps.prestamos import services as pre_services
from apps.prestamos.models import PagoPrestamo, Prestamo

from .models import Liquidacion

E = Liquidacion.Estado


def _deuda(p, avalado=False):
    r = pre_services.resumen(p)
    return {"prestamo": p.pk, "numero": p.numero, "capital": str(r.saldo_capital),
            "intereses": str(r.intereses_pendientes), "mora": str(r.mora_pendiente), "total": str(r.total_pendiente),
            "avalado": avalado, "prestatario": p.prestatario_nombre}


def calcular(afiliado, descontar_avalados=False):
    """Haberes, deudas, bloqueos y avisos del afiliado hoy (sin guardar nada).

    Los bloqueos impiden liquidar; los avisos solo informan. `descontar_avalados`: la deuda de los préstamos externos
    de los que es responsable se le resta y esos préstamos se cancelan; si no, siguen vigentes.
    """
    saldos = mov_services.saldos_afiliado(afiliado)
    ganancias = []
    for d in Distribucion.objects.filter(estado=Distribucion.Estado.APROBADA).order_by("fecha_fin"):
        fila = next((x for x in dist_services.resumen(d)["filas"] if x["afiliado"].pk == afiliado.pk), None)
        if fila is not None and fila["pago"] is None and fila["total"] > 0:
            ganancias.append({"distribucion": d.pk, "codigo": d.codigo, "monto": str(fila["total"])})
    prestamos = [_deuda(p) for p in afiliado.prestamos.filter(estado=Prestamo.Estado.VIGENTE).order_by("numero")]
    avalados = [_deuda(p, avalado=True) for p in afiliado.prestamos_respaldados
                .filter(estado=Prestamo.Estado.VIGENTE).select_related("prestatario_externo").order_by("numero")]
    if descontar_avalados:
        prestamos += avalados
    bloqueos, avisos = [], []
    por_desembolsar = afiliado.prestamos.filter(estado=Prestamo.Estado.APROBADO)
    if por_desembolsar.exists():
        bloqueos.append("Tiene préstamos aprobados sin desembolsar (" + ", ".join(p.numero for p in por_desembolsar)
                        + "): desembólselos o anúlelos antes.")
    if avalados and not descontar_avalados:
        avisos.append("Avala préstamos de terceros que no se le descuentan ("
                      + ", ".join(f"{p['numero']} · {p['prestatario']}" for p in avalados)
                      + "): seguirán vigentes; asígneles otro afiliado responsable.")
    por_desembolsar_avalados = afiliado.prestamos_respaldados.filter(estado=Prestamo.Estado.APROBADO)
    if por_desembolsar_avalados.exists():
        avisos.append("Es responsable de préstamos externos aprobados sin desembolsar ("
                      + ", ".join(p.numero for p in por_desembolsar_avalados) + "): asígneles otro responsable.")
    if Distribucion.objects.filter(estado=Distribucion.Estado.CALCULADA).exists():
        avisos.append("Hay una distribución de ganancias calculada sin aprobar: no se incluye; solo cuentan las "
                      "distribuciones aprobadas.")
    total_ganancias = sum((Decimal(g["monto"]) for g in ganancias), CERO)
    deuda = sum((Decimal(p["total"]) for p in prestamos), CERO)
    haberes = saldos["aportaciones"] + saldos["depositos"] + total_ganancias
    neto = haberes - deuda
    if neto < 0:
        bloqueos.append(f"Sus deudas superan lo que tiene en {_siglas()} por L {-neto:,.2f}: debe pagar esa "
                        "diferencia en sus préstamos antes de liquidarlo.")
    return {"aportaciones": saldos["aportaciones"], "depositos": saldos["depositos"], "ganancias": total_ganancias,
            "deuda_prestamos": deuda, "neto": neto, "haberes": haberes, "bloqueos": bloqueos, "avisos": avisos,
            "avalados": avalados, "detalle": {"ganancias": ganancias, "prestamos": prestamos}}


def _siglas():
    return parametros.obtener("coop.siglas")


def _huella(c):
    return (str(c["aportaciones"]), str(c["depositos"]), str(c["ganancias"]), str(c["deuda_prestamos"]),
            c["detalle"])


def _huella_guardada(liq):
    return (str(liq.aportaciones), str(liq.depositos), str(liq.ganancias), str(liq.deuda_prestamos), liq.detalle)


def _guardar(liq, c):
    liq.fecha_calculo = timezone.localdate()
    for campo in ("aportaciones", "depositos", "ganancias", "deuda_prestamos", "neto", "detalle"):
        setattr(liq, campo, c[campo])


@transaction.atomic
def crear(afiliado, *, motivo, usuario, descontar_avalados=False):
    if not usuario.has_perm("liquidaciones.add_liquidacion"):
        raise ValidationError("No tiene permiso para liquidar afiliados.")
    motivo = " ".join((motivo or "").split())
    if len(motivo) < 10:
        raise ValidationError({"motivo": "Explique el motivo del retiro (mínimo 10 caracteres)."})
    afiliado = Afiliado.objects.select_for_update().get(pk=afiliado.pk)
    if not afiliado.activo:
        raise ValidationError("Solo se liquida a un afiliado activo.")
    if Liquidacion.objects.filter(afiliado=afiliado, estado=E.CALCULADA).exists():
        raise ValidationError("El afiliado ya tiene una liquidación por aprobar.")
    liq = Liquidacion(numero=siguiente_numero("LQ"), afiliado=afiliado, motivo=motivo, calculado_por=usuario,
                      descontar_avalados=descontar_avalados)
    _guardar(liq, calcular(afiliado, descontar_avalados))
    liq.save()
    auditoria.registrar(auditoria.Accion.CREAR, usuario=usuario, objeto=liq,
                        descripcion=f"Liquidación {liq.numero} de {afiliado.codigo}: neto L {liq.neto:,.2f}. "
                                    f"Motivo: {motivo}", despues=auditoria.instantanea(liq))
    return liq


@transaction.atomic
def recalcular(liq, *, usuario, descontar_avalados=None):
    """Vuelve a calcular a hoy. Con `descontar_avalados` se puede cambiar esa decisión."""
    if not usuario.has_perm("liquidaciones.add_liquidacion"):
        raise ValidationError("No tiene permiso para liquidar afiliados.")
    liq = Liquidacion.objects.select_for_update().get(pk=liq.pk)
    if liq.estado != E.CALCULADA:
        raise ValidationError("Solo se recalcula una liquidación por aprobar.")
    antes = {"neto": str(liq.neto), "descontar_avalados": liq.descontar_avalados}
    if descontar_avalados is not None:
        liq.descontar_avalados = descontar_avalados
    _guardar(liq, calcular(liq.afiliado, liq.descontar_avalados))
    liq.calculado_por = usuario
    liq.save()
    auditoria.registrar(auditoria.Accion.MODIFICAR, usuario=usuario, objeto=liq,
                        descripcion=f"Recálculo de la liquidación {liq.numero}", antes=antes,
                        despues={"neto": str(liq.neto), "descontar_avalados": liq.descontar_avalados})
    return liq


@transaction.atomic
def ejecutar(liq, *, usuario, cuenta_fondo, metodo_pago, referencia=""):
    """Aprueba la liquidación y registra todas sus operaciones. Todo o nada."""
    if not usuario.has_perm("liquidaciones.ejecutar_liquidacion"):
        raise ValidationError("No tiene permiso para aprobar y ejecutar liquidaciones.")
    liq = Liquidacion.objects.select_for_update().get(pk=liq.pk)
    if liq.estado != E.CALCULADA:
        raise ValidationError("La liquidación ya no está por aprobar.")
    if parametros.obtener("afiliados.liquidacion_requiere_otro_usuario") and liq.calculado_por_id == usuario.pk:
        raise ValidationError("La liquidación debe aprobarla un usuario distinto al que la calculó.")
    errores = {}
    pre_services._validar_cuenta_metodo(metodo_pago, cuenta_fondo, referencia, errores)
    if errores:
        raise ValidationError(errores)
    afiliado = Afiliado.objects.select_for_update().get(pk=liq.afiliado_id)
    if not afiliado.activo:
        raise ValidationError("El afiliado ya está inactivo.")
    c = calcular(afiliado, liq.descontar_avalados)
    if c["bloqueos"]:
        raise ValidationError(c["bloqueos"])
    if _huella(c) != _huella_guardada(liq) or liq.fecha_calculo != timezone.localdate():
        raise ValidationError("Los saldos o las deudas del afiliado cambiaron desde el cálculo (o se calculó otro "
                              "día y la mora cambió). Recalcule la liquidación antes de aprobarla.")
    fecha = timezone.localdate()
    nota = f"Liquidación {liq.numero} de {afiliado.codigo}"
    comunes = dict(usuario=usuario, fecha=fecha, metodo_pago=metodo_pago, referencia=referencia)
    # 1. Sus préstamos (y los de terceros que avala, si se decidió descontarlos) se cancelan con sus haberes.
    for p in c["detalle"]["prestamos"]:
        pago, _ = pre_services.registrar_pago(Prestamo.objects.get(pk=p["prestamo"]), tipo=PagoPrestamo.Tipo.PAGO,
                                              monto=Decimal(p["total"]), cuenta_fondo=cuenta_fondo,
                                              observacion=f"Compensación por la {nota.lower()}", **comunes)
        liq.pagos_prestamo.add(pago)
    # 2. Ganancias aprobadas que aún no se le entregaban.
    for g in c["detalle"]["ganancias"]:
        for pago in dist_services.registrar_pagos(Distribucion.objects.get(pk=g["distribucion"]), afiliados=[afiliado],
                                                  forma=PagoGanancia.Forma.PAGO, cuenta_fondo=cuenta_fondo, **comunes):
            liq.pagos_ganancia.add(pago)
    # 3. Devolución de depósitos y aportaciones.
    tipos = {t.codigo: t for t in TipoMovimiento.objects.filter(codigo__in=["RDEP", mov_services.TIPO_LIQUIDACION])}
    for codigo, monto in (("RDEP", c["depositos"]), (mov_services.TIPO_LIQUIDACION, c["aportaciones"])):
        if monto > 0:
            if codigo not in tipos:
                raise ValidationError(f"Falta el tipo de movimiento {codigo}. Ejecute la configuración inicial.")
            mov, _ = mov_services.registrar_movimiento(
                afiliado=afiliado, tipo=tipos[codigo], monto=monto, cuenta_fondo=cuenta_fondo, observacion=nota,
                por_liquidacion=codigo == mov_services.TIPO_LIQUIDACION, **comunes)
            liq.movimientos.add(mov)
    # 4. Baja.
    liq.cambio_estado = cambiar_estado(afiliado, estado_nuevo=Afiliado.Estado.INACTIVO, fecha_efectiva=fecha,
                                       motivo=f"{nota}: {liq.motivo}", usuario=usuario)
    liq.estado = E.EJECUTADA
    liq.fecha = fecha
    liq.cuenta_fondo = cuenta_fondo
    liq.metodo_pago = metodo_pago
    liq.referencia = (referencia or "").strip()
    liq.ejecutado_por = usuario
    liq.ejecutado_en = timezone.now()
    liq.save()
    auditoria.registrar(auditoria.Accion.CAMBIO_ESTADO, usuario=usuario, objeto=liq,
                        descripcion=f"Ejecución de la liquidación {liq.numero}: neto entregado L {liq.neto:,.2f}; "
                                    f"{afiliado.codigo} dado de baja.", despues=auditoria.instantanea(liq))
    return liq


@transaction.atomic
def anular(liq, *, usuario, motivo):
    """Anula una liquidación. Si ya se ejecutó, anula sus operaciones y reactiva al afiliado. Todo o nada."""
    if not usuario.has_perm("liquidaciones.anular_liquidacion"):
        raise ValidationError("No tiene permiso para anular liquidaciones.")
    motivo = (motivo or "").strip()
    if len(motivo) < 10:
        raise ValidationError({"motivo": "Explique el motivo de la anulación (mínimo 10 caracteres)."})
    liq = Liquidacion.objects.select_for_update().get(pk=liq.pk)
    if liq.estado == E.ANULADA:
        raise ValidationError("La liquidación ya está anulada.")
    texto = f"Anulación de la liquidación {liq.numero}: {motivo}"
    if liq.estado == E.EJECUTADA:
        if parametros.obtener("movimientos.anulacion_requiere_otro_usuario") and liq.ejecutado_por_id == usuario.pk:
            raise ValidationError("La anulación debe autorizarla un usuario distinto al que ejecutó la liquidación.")
        afiliado = Afiliado.objects.select_for_update().get(pk=liq.afiliado_id)
        # Primero vuelve el dinero devuelto (retiros y ganancias), después se quitan los pagos de préstamos.
        for mov in liq.movimientos.filter(estado="CONFIRMADO"):
            mov_services.anular_movimiento(mov, usuario=usuario, motivo=texto, automatico=True)
        for pago in liq.pagos_ganancia.filter(estado="CONFIRMADO"):
            dist_services.anular_pago(pago, usuario=usuario, motivo=texto)
        for pago in liq.pagos_prestamo.filter(estado="CONFIRMADO").order_by("-fecha", "-id"):
            pre_services.anular_pago(pago, usuario=usuario, motivo=texto)
        if not afiliado.activo:  # reactivación automática: es consecuencia de anular la baja
            afiliado.estado = Afiliado.Estado.ACTIVO
            afiliado.save(update_fields=["estado", "actualizado_en"])
            CambioEstadoAfiliado.objects.create(afiliado=afiliado, estado_anterior=Afiliado.Estado.INACTIVO,
                                                estado_nuevo=Afiliado.Estado.ACTIVO,
                                                fecha_efectiva=timezone.localdate(), motivo=texto,
                                                registrado_por=usuario)
    antes = auditoria.instantanea(liq)
    liq.estado = E.ANULADA
    liq.anulado_por = usuario
    liq.anulado_en = timezone.now()
    liq.motivo_anulacion = motivo
    liq.save(update_fields=["estado", "anulado_por", "anulado_en", "motivo_anulacion"])
    auditoria.registrar(auditoria.Accion.ANULAR, usuario=usuario, objeto=liq, descripcion=texto, antes=antes,
                        despues=auditoria.instantanea(liq))
    return liq

"""Mora, pagos de más (a aportaciones) y afiliado responsable de préstamos externos. Cálculos hechos a mano."""
from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.aportaciones import services as ms
from apps.caja import services as cs
from apps.core.models import Parametro
from apps.distribucion import services as ds
from apps.prestamos import services as ps
from apps.prestamos.models import PagoPrestamo
from apps.reportes.views import resumen_financiero


@pytest.fixture
def prestamo_vencido(tesorero, caja, hoy, mov):
    """L 1,000 a una sola cuota (interés 10.00) que venció hace 30 días. Mora interna: 1 % mensual."""
    def crear(afiliado, tipo="INTERNO", **extra):
        datos = dict(usuario=tesorero, tipo_prestatario=tipo, monto_solicitado="1000", monto_aprobado="1000",
                     plazo=1, metodo_amortizacion="CUOTA_FIJA", fecha_aprobacion=hoy - timedelta(days=60),
                     fecha_primer_vencimiento=hoy - timedelta(days=30))
        if tipo == "INTERNO":
            datos["afiliado"] = afiliado
        else:
            datos.update(externo={"nombre_completo": "Tercero Ficticio", "identidad": "8888199000009"},
                         afiliado_responsable=afiliado)
        datos.update(extra)
        p = ps.aprobar_prestamo(**datos)
        return ps.desembolsar(p, usuario=tesorero, fecha=hoy - timedelta(days=59), cuenta=caja, metodo_pago="EFECTIVO")
    return crear


def pagar(p, monto, usuario, caja, fecha, tipo="PAGO"):
    pago, _ = ps.registrar_pago(p, usuario=usuario, tipo=tipo, fecha=fecha, monto=D(str(monto)),
                                metodo_pago="EFECTIVO", cuenta_fondo=caja)
    return pago


# --------------------------------------------------------------------------- cálculo

def test_mora_por_dias_de_atraso(afiliado, prestamo_vencido):
    p = prestamo_vencido(afiliado)
    assert (p.tasa_mora, p.dias_gracia_mora) == (D("1.0000"), 0)
    r = ps.resumen(p)
    # 1,000 de capital vencido × 1 % mensual × 30 días ÷ 30 = 10.00
    assert r.mora_pendiente == D("10.00") and r.cuotas[0].dias_atraso == 30
    assert r.cuotas[0].estado == "VENCIDA" and r.cuotas_vencidas == 1
    assert r.total_pendiente == D("1000.00") + D("10.00") + D("10.00")


def test_sin_atraso_no_hay_mora(afiliado, tesorero, caja, hoy):
    p = ps.aprobar_prestamo(usuario=tesorero, tipo_prestatario="INTERNO", afiliado=afiliado, monto_solicitado="1000",
                            monto_aprobado="1000", plazo=2, metodo_amortizacion="CUOTA_FIJA", fecha_aprobacion=hoy,
                            fecha_primer_vencimiento=hoy + timedelta(days=30))
    p = ps.desembolsar(p, usuario=tesorero, fecha=hoy, cuenta=caja, metodo_pago="EFECTIVO")
    assert ps.resumen(p).mora_pendiente == 0
    assert ps.resumen(p, hoy + timedelta(days=30)).mora_pendiente == 0  # el día del vencimiento aún no hay mora
    assert ps.resumen(p, hoy + timedelta(days=33)).mora_pendiente == D("0.50")  # 497.51 × 1 % × 3 ÷ 30


def test_pago_cubre_mora_luego_interes_luego_capital(afiliado, prestamo_vencido, tesorero, caja, hoy):
    p = prestamo_vencido(afiliado)
    # A los 15 días de atraso la mora es 1,000 × 1 % × 15 ÷ 30 = 5.00
    pago = pagar(p, "515", tesorero, caja, hoy - timedelta(days=15))
    aps = list(pago.aplicaciones.values_list("interes", "capital"))
    assert pago.mora == D("5.00") and aps == [(D("10.00"), D("500.00"))]
    # Después la mora corre sobre los 500 que quedan: 5.00 + 500 × 1 % × 15 ÷ 30 = 7.50 generada; 2.50 pendiente
    r = ps.resumen(p)
    assert (r.mora_generada, r.mora_cobrada, r.mora_pendiente) == (D("7.50"), D("5.00"), D("2.50"))
    assert r.total_pendiente == D("502.50")
    pagar(p, "502.50", tesorero, caja, hoy)
    p.refresh_from_db()
    assert p.estado == "PAGADO" and ps.resumen(p).total_pendiente == 0


def test_pago_menor_que_la_mora_solo_cubre_mora(afiliado, prestamo_vencido, tesorero, caja, hoy):
    p = prestamo_vencido(afiliado)
    pago = pagar(p, "4", tesorero, caja, hoy)
    assert pago.mora == D("4.00") and not pago.aplicaciones.exists()
    assert ps.resumen(p).mora_pendiente == D("6.00")


def test_dias_de_gracia(afiliado, prestamo_vencido):
    Parametro.objects.filter(clave="prestamos.dias_gracia_mora").update(valor="5")
    p = prestamo_vencido(afiliado)
    assert ps.resumen(p).mora_pendiente == D("8.33")  # 1,000 × 1 % × 25 ÷ 30


def test_tasa_de_mora_congelada_y_externa(afiliado, prestamo_vencido):
    interno = prestamo_vencido(afiliado)
    Parametro.objects.filter(clave="prestamos.tasa_mora_interna").update(valor="3")
    assert ps.resumen(interno).mora_pendiente == D("10.00")  # no cambia el préstamo ya aprobado
    externo = prestamo_vencido(afiliado, tipo="EXTERNO")
    assert externo.tasa_mora == D("5.0000")
    assert ps.resumen(externo).mora_pendiente == D("50.00")  # 1,000 × 5 % × 30 ÷ 30


def test_abono_no_paga_mora(afiliado, prestamo_vencido, tesorero, caja, hoy):
    p = prestamo_vencido(afiliado)
    abono = pagar(p, "500", tesorero, caja, hoy, tipo="ABONO")
    assert abono.mora == 0 and ps.resumen(p).mora_pendiente == D("10.00")


def test_mora_cobrada_es_utilidad_y_aparece_en_el_flujo(afiliado, mov, prestamo_vencido, tesorero, caja, hoy):
    mov(afiliado, "APO", 2000, fecha=hoy - timedelta(days=90))
    p = prestamo_vencido(afiliado)
    pagar(p, "1020", tesorero, caja, hoy)
    assert ps.mora_cobrada() == D("10.00")
    general = ds.calcular(hoy - timedelta(days=5), hoy).fondos[0]
    assert general.ingresos == D("20.00") and general.detalle["mora_prestamos"] == "10.00"
    filas = {f["origen"]: f for f in cs.flujo_efectivo()["filas"]}
    assert filas[cs.COBROS_MORA]["entradas"] == D("10.00")
    assert filas[cs.COBROS_INTERES]["entradas"] == D("10.00")
    assert filas[cs.COBROS_CAPITAL]["entradas"] == D("1000.00")
    assert resumen_financiero(hoy)["diferencia"] == 0


# --------------------------------------------------------------------------- pagos de más

def test_lo_pagado_de_mas_va_a_aportaciones(afiliado, prestamo_vencido, tesorero, caja, hoy):
    p = prestamo_vencido(afiliado)
    antes = cs.saldo(caja)
    pago = pagar(p, "1100", tesorero, caja, hoy)  # debe 1,020.00
    assert (pago.monto, pago.mora, pago.excedente) == (D("1020.00"), D("10.00"), D("80.00"))
    assert ms.saldos_afiliado(afiliado)["aportaciones"] == D("80.00")
    assert cs.saldo(caja) == antes + D("1100.00")  # entra todo el dinero, una sola vez
    p.refresh_from_db()
    assert p.estado == "PAGADO"
    # El excedente no se anula por separado: se anula con su pago.
    with pytest.raises(ValidationError) as e:
        ms.anular_movimiento(pago.movimiento_excedente, motivo="Intento de anular solo el excedente",
                             usuario=tesorero)
    assert "lo generó" in str(e.value)


def test_anular_pago_anula_el_excedente(afiliado, prestamo_vencido, tesorero, supervisor, caja, hoy):
    p = prestamo_vencido(afiliado)
    pago = pagar(p, "1100", tesorero, caja, hoy)
    ps.anular_pago(pago, usuario=supervisor, motivo="Monto digitado incorrecto")
    pago.movimiento_excedente.refresh_from_db()
    assert pago.movimiento_excedente.estado == "ANULADO"
    assert ms.saldos_afiliado(afiliado)["aportaciones"] == 0
    p.refresh_from_db()
    assert p.estado == "VIGENTE"


def test_externo_que_paga_de_mas_deja_deposito_al_aval(afiliado, prestamo_vencido, tesorero, caja, hoy):
    p = prestamo_vencido(afiliado, tipo="EXTERNO")  # debe 1,000 + 50 interés + 50 mora; lo avala `afiliado`
    pago = pagar(p, "1150", tesorero, caja, hoy)
    assert (pago.monto, pago.excedente) == (D("1100.00"), D("50.00"))
    mov = pago.movimiento_excedente
    assert (mov.afiliado, mov.tipo.codigo, mov.tipo.clase) == (afiliado, "EXA", "DEPOSITO")
    assert ms.saldos_afiliado(afiliado) == {"aportaciones": D("0.00"), "depositos": D("50.00"), "total": D("50.00")}
    p.refresh_from_db()
    assert p.estado == "PAGADO"


def test_externo_sin_responsable_no_puede_pagar_de_mas(afiliado, prestamo_vencido, tesorero, caja, hoy):
    p = prestamo_vencido(afiliado, tipo="EXTERNO")
    from django.db import connection
    # Se quita el responsable con SQL directo, como en un préstamo registrado antes de exigirlo.
    with connection.cursor() as c:
        c.execute("UPDATE prestamos_prestamo SET afiliado_responsable_id = NULL WHERE id = %s", [p.pk])
    with pytest.raises(ValidationError) as e:
        pagar(p, "1100.01", tesorero, caja, hoy)
    assert "responsable" in str(e.value)
    pagar(p, "1100", tesorero, caja, hoy)
    assert PagoPrestamo.objects.get().excedente == 0


def test_mora_se_congela_a_los_90_dias(afiliado, prestamo_vencido, hoy):
    p = prestamo_vencido(afiliado)
    assert p.dias_maximos_mora == 90
    cuota = p.cuotas.get()
    # A los 90 días: 1,000 × 1 % × 90 ÷ 30 = 30.00. Después ya no aumenta.
    assert ps.resumen(p, cuota.fecha_vencimiento + timedelta(days=90)).mora_pendiente == D("30.00")
    assert ps.resumen(p, cuota.fecha_vencimiento + timedelta(days=200)).mora_pendiente == D("30.00")
    assert ps.resumen(p, cuota.fecha_vencimiento + timedelta(days=200)).cuotas[0].dias_atraso == 200


def test_sin_limite_si_el_parametro_es_cero(afiliado, prestamo_vencido):
    Parametro.objects.filter(clave="prestamos.dias_maximos_mora").update(valor="0")
    p = prestamo_vencido(afiliado)
    cuota = p.cuotas.get()
    assert ps.resumen(p, cuota.fecha_vencimiento + timedelta(days=120)).mora_pendiente == D("40.00")


def test_numero_de_prestamo_por_anio(tesorero, caja, afiliado, prestamo_vencido, hoy):
    from django.db import transaction
    from apps.core.secuencias import numero_prestamo
    interno = prestamo_vencido(afiliado)
    externo = prestamo_vencido(afiliado, tipo="EXTERNO")
    assert interno.numero == f"1{hoy.year}001" and externo.numero == f"2{hoy.year}002"
    with transaction.atomic():
        # Al cambiar de año el correlativo vuelve a empezar.
        assert numero_prestamo("INTERNO", hoy.year + 1) == f"1{hoy.year + 1}001"
        assert numero_prestamo("EXTERNO", hoy.year + 1) == f"2{hoy.year + 1}002"
        assert numero_prestamo("INTERNO", hoy.year) == f"1{hoy.year}003"


def test_excedente_lo_registra_el_encargado_de_prestamos(afiliado, prestamo_vencido, prestamos, caja, hoy):
    """El encargado no puede registrar aportaciones, pero sí el excedente de un pago que él cobra."""
    p = prestamo_vencido(afiliado)
    pago = pagar(p, "1030", prestamos, caja, hoy)
    assert pago.excedente == D("10.00")


# --------------------------------------------------------------------------- afiliado responsable

def test_externo_exige_afiliado_responsable_activo(afiliado, tesorero, hoy):
    base = dict(usuario=tesorero, tipo_prestatario="EXTERNO", monto_solicitado="500", monto_aprobado="500", plazo=2,
                metodo_amortizacion="CUOTA_FIJA", fecha_aprobacion=hoy, fecha_primer_vencimiento=hoy + timedelta(days=30),
                externo={"nombre_completo": "Tercero Ficticio", "identidad": "8888199000010"})
    with pytest.raises(ValidationError) as e:
        ps.aprobar_prestamo(**base)
    assert "afiliado_responsable" in e.value.message_dict
    p = ps.aprobar_prestamo(**base, afiliado_responsable=afiliado)
    assert p.afiliado_responsable == afiliado


def test_cambiar_responsable_y_ficha_del_afiliado(client, nuevo_afiliado, prestamo_vencido, tesorero, hoy):
    a, b = nuevo_afiliado(nombres="Ana"), nuevo_afiliado(nombres="Beto")
    p = prestamo_vencido(a, tipo="EXTERNO")
    client.force_login(tesorero)
    r = client.post(reverse("prestamos:responsable", args=[p.pk]), {"afiliado": b.pk, "motivo": "Ana pidió retirarse"})
    assert r.status_code == 302
    p.refresh_from_db()
    assert p.afiliado_responsable == b
    html = client.get(reverse("afiliados:detalle", args=[b.pk])).content.decode()
    assert "Préstamos externos que respalda" in html and p.numero in html
    detalle = client.get(reverse("prestamos:detalle", args=[p.pk])).content.decode()
    assert "Afiliado responsable" in detalle and "En mora" in detalle


def test_formulario_oculta_campos_de_externos(client, tesorero):
    client.force_login(tesorero)
    html = client.get(reverse("prestamos:crear")).content.decode()
    assert "'afiliado_responsable'" in html  # el script lo muestra solo para externos


def test_reporte_de_saldos_muestra_mora(client, tesorero, afiliado, prestamo_vencido):
    prestamo_vencido(afiliado)
    client.force_login(tesorero)
    r = client.get(reverse("reportes:saldos"))
    assert r.context["totales"][5] == D("10.00")
    assert ("Préstamos en mora", 1) in r.context["resumen"]

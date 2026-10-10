import uuid
from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core import parametros
from apps.core.models import Parametro
from apps.prestamos import services as ps
from apps.prestamos.models import AplicacionPago, CuotaAmortizacion, PagoPrestamo, Prestamo


# Estas pruebas verifican intereses y capital; la mora tiene sus propias pruebas en test_mora.py.
pytestmark = pytest.mark.usefixtures("sin_mora")


@pytest.fixture(autouse=True)
def _caja_por_defecto(caja):
    return caja


def pagar(prestamo, monto, usuario, caja, tipo="PAGO", fecha=None, **extra):
    pago, _ = ps.registrar_pago(prestamo, usuario=usuario, tipo=tipo, fecha=fecha or timezone.localdate(),
                                monto=D(str(monto)), metodo_pago="EFECTIVO", cuenta_fondo=caja, **extra)
    return pago


# ------------------------------------------------------------------ tasas y aprobación

def test_interno_usa_1_por_ciento_y_externo_5(afiliado, nuevo_prestamo, tesorero, hoy, caja):
    interno = nuevo_prestamo(afiliado, desembolsar=False)
    assert (interno.tasa, interno.tasa_configurada, interno.tasa_es_excepcion) == (D("1.00"), D("1.00"), False)
    externo = ps.aprobar_prestamo(
        usuario=tesorero, tipo_prestatario="EXTERNO",
        externo={"nombre_completo": "Prestatario Externo Ficticio", "identidad": "8888-1990-00001"},
        afiliado_responsable=afiliado, monto_solicitado="2000", monto_aprobado="2000", plazo=4, metodo_amortizacion="CAPITAL_FIJO",
        fecha_aprobacion=hoy, fecha_primer_vencimiento=hoy + timedelta(days=30))
    assert externo.tasa == D("5.00") and externo.prestatario_externo.identidad == "8888199000001"
    assert externo.cuotas.first().interes == D("100.00")
    anio = hoy.year
    assert interno.numero == f"1{anio}001" and externo.numero == f"2{anio}002"


def test_cambio_de_tasa_no_afecta_prestamos_existentes(afiliado, nuevo_prestamo, admin_caune):
    antes = nuevo_prestamo(afiliado)
    cuadro_antes = list(antes.cuotas.values_list("interes", "capital", "cuota"))
    parametros.actualizar(Parametro.objects.get(clave="prestamos.tasa_interna"), "2.00", admin_caune,
                          "Acta de directiva: nueva tasa interna")
    antes.refresh_from_db()
    assert antes.tasa == D("1.00")
    assert list(antes.cuotas.values_list("interes", "capital", "cuota")) == cuadro_antes
    despues = nuevo_prestamo(afiliado, desembolsar=False)
    assert despues.tasa == D("2.00") and despues.cuotas.first().interes == D("20.00")
    # El historial de la tasa queda registrado
    assert Parametro.objects.get(clave="prestamos.tasa_interna").historial.get().valor_anterior == "1.00"


def test_excepcion_de_tasa_requiere_permiso_y_motivo(afiliado, nuevo_prestamo, tesorero, hoy):
    p = nuevo_prestamo(afiliado, desembolsar=False, tasa="0.75", motivo_excepcion="Aprobado por asamblea, acta 7")
    assert p.tasa_es_excepcion and p.tasa == D("0.75") and p.excepcion_autorizada_por == tesorero
    with pytest.raises(ValidationError) as e:
        nuevo_prestamo(afiliado, desembolsar=False, tasa="0.5", motivo_excepcion="")
    assert "motivo_excepcion" in e.value.message_dict


def test_encargado_de_prestamos_no_autoriza_excepciones(afiliado, prestamos, hoy):
    from django.contrib.auth.models import Group
    with pytest.raises(ValidationError) as e:
        ps.aprobar_prestamo(usuario=prestamos, tipo_prestatario="INTERNO", afiliado=afiliado, monto_solicitado="500",
                            monto_aprobado="500", plazo=2, metodo_amortizacion="CUOTA_FIJA", fecha_aprobacion=hoy,
                            fecha_primer_vencimiento=hoy + timedelta(days=30), tasa="0.5",
                            motivo_excepcion="Intento sin permiso de autorización")
    assert "tasa" in e.value.message_dict


@pytest.mark.parametrize("cambios, campo", [
    ({"monto_aprobado": "1500"}, "monto_aprobado"),
    ({"plazo": 61}, "plazo"),
    ({"plazo": 0}, "plazo"),
    ({"monto_solicitado": "0", "monto_aprobado": "0"}, "monto_solicitado"),
    ({"metodo_amortizacion": "ALEMAN"}, "metodo_amortizacion"),
])
def test_validaciones_de_aprobacion(afiliado, nuevo_prestamo, cambios, campo):
    with pytest.raises(ValidationError) as e:
        nuevo_prestamo(afiliado, desembolsar=False, **cambios)
    assert campo in e.value.message_dict


def test_afiliado_inactivo_no_recibe_prestamo(afiliado, nuevo_prestamo, admin_caune, hoy):
    from apps.afiliados.services import cambiar_estado
    cambiar_estado(afiliado, estado_nuevo="INACTIVO", fecha_efectiva=hoy, motivo="Retiro del afiliado de prueba",
                   usuario=admin_caune)
    with pytest.raises(ValidationError):
        nuevo_prestamo(afiliado, desembolsar=False)


def test_cuadro_queda_inmutable(afiliado, nuevo_prestamo):
    cuota = nuevo_prestamo(afiliado).cuotas.first()
    cuota.interes = D("1")
    with pytest.raises(ValidationError):
        cuota.save()
    with pytest.raises(ValidationError):
        CuotaAmortizacion.objects.all().delete()


# ------------------------------------------------------------------ desembolso y anulación

def test_flujo_de_estados(afiliado, nuevo_prestamo, tesorero, supervisor, caja, hoy):
    p = nuevo_prestamo(afiliado, desembolsar=False)
    with pytest.raises(ValidationError):  # no se paga lo que no se ha desembolsado
        pagar(p, 100, tesorero, caja)
    p = ps.desembolsar(p, usuario=tesorero, fecha=p.fecha_aprobacion, cuenta=caja, metodo_pago="EFECTIVO")
    assert p.estado == "VIGENTE" and p.desembolsado_por == tesorero
    with pytest.raises(ValidationError):  # ya desembolsado
        ps.anular_prestamo(p, usuario=supervisor, motivo="Ya no se puede anular")
    otro = nuevo_prestamo(afiliado, desembolsar=False)
    ps.anular_prestamo(otro, usuario=supervisor, motivo="Solicitud retirada por el afiliado")
    otro.refresh_from_db()
    assert otro.estado == "ANULADO"


def test_desembolso_debe_ser_antes_del_primer_vencimiento(afiliado, nuevo_prestamo, tesorero, caja):
    p = nuevo_prestamo(afiliado, desembolsar=False)
    with pytest.raises(ValidationError):
        ps.desembolsar(p, usuario=tesorero, fecha=p.fecha_primer_vencimiento, cuenta=caja, metodo_pago="EFECTIVO")


# ------------------------------------------------------------------ pagos

def test_pago_de_cuota_completa(afiliado, nuevo_prestamo, tesorero, caja):
    p = nuevo_prestamo(afiliado)  # 1000 al 1 %, cuotas de 507.51
    pago = pagar(p, "507.51", tesorero, caja)
    ap = pago.aplicaciones.get()
    assert (ap.cuota.numero, ap.interes, ap.capital) == (1, D("10.00"), D("497.51"))
    r = ps.resumen(p)
    assert r.saldo_capital == D("502.49") and r.intereses_cobrados == D("10.00")
    assert r.intereses_pendientes == D("5.02") and r.cuotas_pagadas == 1 and r.proxima.cuota.numero == 2


def test_pago_parcial_cubre_interes_primero(afiliado, nuevo_prestamo, tesorero, caja):
    p = nuevo_prestamo(afiliado)
    pagar(p, "5", tesorero, caja)
    r = ps.resumen(p)
    assert r.cuotas[0].interes_pagado == D("5.00") and r.cuotas[0].capital_pagado == 0
    # Parcial y ya vencida: se muestra como vencida.
    assert r.cuotas[0].estado == "VENCIDA" and r.saldo_capital == D("1000.00")
    pagar(p, "300", tesorero, caja)
    r = ps.resumen(p)
    assert r.cuotas[0].interes_pagado == D("10.00") and r.cuotas[0].capital_pagado == D("295.00")
    assert r.saldo_capital == D("705.00")
    pagar(p, "202.51", tesorero, caja)  # completa la cuota 1
    assert ps.resumen(p).cuotas[0].estado == "PAGADA"


def test_pago_que_cubre_varias_cuotas_y_cancela(afiliado, nuevo_prestamo, tesorero, supervisor, caja):
    p = nuevo_prestamo(afiliado)
    pago = pagar(p, "1015.02", tesorero, caja)
    assert pago.aplicaciones.count() == 2
    p.refresh_from_db()
    assert p.estado == "PAGADO" and ps.resumen(p).total_pendiente == 0
    with pytest.raises(ValidationError):  # cancelado: no admite más pagos
        pagar(p, 1, tesorero, caja)
    ps.anular_pago(pago, usuario=supervisor, motivo="Pago registrado por error")
    p.refresh_from_db()
    assert p.estado == "VIGENTE" and ps.resumen(p).saldo_capital == D("1000.00")


def test_sobrepago_de_afiliado_va_a_aportaciones(afiliado, nuevo_prestamo, tesorero, caja):
    from apps.aportaciones.services import saldos_afiliado
    p = nuevo_prestamo(afiliado)
    pago = pagar(p, "1015.03", tesorero, caja)  # debe 1,015.02
    assert (pago.monto, pago.excedente) == (D("1015.02"), D("0.01"))
    assert pago.movimiento_excedente.tipo.codigo == "EXP"
    assert saldos_afiliado(afiliado)["aportaciones"] == D("0.01")
    p.refresh_from_db()
    assert p.estado == "PAGADO"


def test_abono_extraordinario_no_cambia_el_cuadro(afiliado, nuevo_prestamo, tesorero, caja):
    p = nuevo_prestamo(afiliado, monto="3000", plazo=3)
    cuadro = list(p.cuotas.values_list("numero", "capital", "interes", "cuota"))
    abono = pagar(p, "1500", tesorero, caja, tipo="ABONO")
    assert list(p.cuotas.values_list("numero", "capital", "interes", "cuota")) == cuadro
    # El abono va solo a capital, en orden de vencimiento
    aps = list(abono.aplicaciones.values_list("cuota__numero", "interes", "capital"))
    assert all(i == 0 for _, i, _ in aps)
    assert sum(c for _, _, c in aps) == D("1500")
    assert aps[0][0] == 1
    r = ps.resumen(p)
    assert r.saldo_capital == D("1500.00")
    # Los intereses del cuadro siguen exigibles (decisión P5: las cuotas se mantienen)
    assert r.intereses_pendientes == sum(c[2] for c in cuadro)
    # Lo que el afiliado abona de más va a sus aportaciones.
    ultimo = pagar(p, "1500.01", tesorero, caja, tipo="ABONO")
    assert (ultimo.monto, ultimo.excedente) == (D("1500.00"), D("0.01"))


def test_saldo_despues_de_cada_pago(afiliado, nuevo_prestamo, tesorero, caja):
    p = nuevo_prestamo(afiliado, monto="5000", plazo=6, metodo="CAPITAL_FIJO")
    esperado = D("5000.00")
    for cuota in p.cuotas.order_by("numero"):
        pagar(p, cuota.cuota, tesorero, caja)
        esperado -= cuota.capital
        assert ps.resumen(p).saldo_capital == esperado == cuota.saldo_final
    p.refresh_from_db()
    assert p.estado == "PAGADO"
    assert ps.resumen(p).intereses_cobrados == sum(c.interes for c in p.cuotas.all())


def test_pago_no_se_duplica(afiliado, nuevo_prestamo, tesorero, caja):
    p = nuevo_prestamo(afiliado)
    clave = uuid.uuid4()
    a = pagar(p, 100, tesorero, caja, clave_idempotencia=clave)
    b = pagar(p, 100, tesorero, caja, clave_idempotencia=clave)
    assert a.pk == b.pk and PagoPrestamo.objects.count() == 1


def test_anulacion_solo_del_ultimo_pago_y_por_otro_usuario(afiliado, nuevo_prestamo, tesorero, supervisor, caja):
    p = nuevo_prestamo(afiliado)
    primero = pagar(p, 100, tesorero, caja)
    segundo = pagar(p, 100, tesorero, caja)
    with pytest.raises(ValidationError):
        ps.anular_pago(primero, usuario=supervisor, motivo="Intento fuera de orden")
    with pytest.raises(ValidationError):
        ps.anular_pago(segundo, usuario=tesorero, motivo="Autoanulación no permitida")
    ps.anular_pago(segundo, usuario=supervisor, motivo="Pago duplicado por error")
    ps.anular_pago(primero, usuario=supervisor, motivo="Pago con monto equivocado")
    assert ps.resumen(p).total_pendiente == D("1015.02")


def test_pagos_parciales_deshabilitados(afiliado, nuevo_prestamo, tesorero, admin_caune, caja):
    parametros.actualizar(Parametro.objects.get(clave="prestamos.permitir_pagos_parciales"), "false", admin_caune,
                          "Prueba: solo cuotas completas")
    p = nuevo_prestamo(afiliado)
    with pytest.raises(ValidationError):
        pagar(p, "300", tesorero, caja)
    assert pagar(p, "507.51", tesorero, caja).pk


def test_pago_con_fecha_anterior_al_ultimo(afiliado, nuevo_prestamo, tesorero, caja, hoy):
    p = nuevo_prestamo(afiliado)
    pagar(p, 100, tesorero, caja, fecha=hoy)
    with pytest.raises(ValidationError):
        pagar(p, 100, tesorero, caja, fecha=hoy - timedelta(days=3))


def test_saldos_anotados_coinciden(afiliado, nuevo_prestamo, tesorero, caja):
    p1, p2 = nuevo_prestamo(afiliado), nuevo_prestamo(afiliado, monto="3000", plazo=3)
    pagar(p1, "507.51", tesorero, caja)
    pagar(p2, "800", tesorero, caja, tipo="ABONO")
    for p in ps.anotar_saldos(Prestamo.objects.all()):
        r = ps.resumen(p)
        assert p.monto_aprobado - p.capital_pagado == r.saldo_capital
        assert p.intereses_cobrados == r.intereses_cobrados
    assert ps.cartera_vigente() == D("502.49") + D("2200.00")
    assert ps.intereses_cobrados() == D("10.00")


def test_aplicaciones_inmutables(afiliado, nuevo_prestamo, tesorero, caja):
    p = nuevo_prestamo(afiliado)
    pago = pagar(p, 100, tesorero, caja)
    with pytest.raises(ValidationError):
        pago.delete()
    with pytest.raises(ValidationError):
        AplicacionPago.objects.all().delete()

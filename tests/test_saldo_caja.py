"""Ninguna salida de dinero de ningún módulo deja una caja o cuenta en negativo, ni la anulación de una entrada."""
from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError

from apps.actividades import services as acs
from apps.aportaciones import services as ms
from apps.caja import services as cs
from apps.core.models import Parametro
from apps.prestamos import services as ps


def _transferir(caja, banco, monto, usuario, fecha):
    cs.registrar_movimiento(tipo="TRANSFERENCIA", fecha=fecha, concepto="Al banco", monto=D(monto),
                            metodo_pago="DEPOSITO_BANCARIO", cuenta_fondo=caja, cuenta_destino=banco,
                            referencia="T-1", usuario=usuario)


def test_retiro_de_deposito_sin_efectivo_en_caja(afiliado, mov, tipos, tesorero, caja, banco, hoy):
    mov(afiliado, "DEP", 1000, fecha=hoy - timedelta(days=5))
    _transferir(caja, banco, "800", tesorero, hoy - timedelta(days=4))
    # El afiliado tiene L 1,000 de saldo, pero en la caja solo quedan L 200.
    with pytest.raises(ValidationError) as e:
        mov(afiliado, "RDEP", 500)
    assert "Caja de prueba" in str(e.value)
    assert mov(afiliado, "RDEP", 200).monto == D("200.00")


def test_desembolso_sin_fondos(afiliado, nuevo_prestamo, tesorero, caja, mov, hoy):
    p = nuevo_prestamo(afiliado, desembolsar=False)
    mov(afiliado, "APO", 600, fecha=p.fecha_aprobacion)
    with pytest.raises(ValidationError) as e:
        ps.desembolsar(p, usuario=tesorero, fecha=p.fecha_aprobacion, cuenta=caja, metodo_pago="EFECTIVO")
    assert "cuenta" in e.value.message_dict
    mov(afiliado, "APO", 400, fecha=p.fecha_aprobacion)
    assert ps.desembolsar(p, usuario=tesorero, fecha=p.fecha_aprobacion, cuenta=caja,
                          metodo_pago="EFECTIVO").estado == "VIGENTE"


def test_gasto_de_actividad_sin_fondos(tesorero, caja, hoy):
    act = acs.crear_actividad({"nombre": "Rifa", "fecha_inicio": hoy - timedelta(days=5)}, tesorero)

    def registrar(tipo, monto):
        return acs.registrar_movimiento(actividad=act, tipo=tipo, fecha=hoy, concepto="Prueba", monto=D(monto),
                                        metodo_pago="EFECTIVO", cuenta_fondo=caja, usuario=tesorero)
    with pytest.raises(ValidationError):
        registrar("GASTO", "100")
    registrar("INGRESO", "150")
    registrar("GASTO", "100")
    assert cs.saldo(caja) == D("50.00")


def test_no_se_anula_una_aportacion_que_ya_se_gasto(afiliado, mov, tesorero, supervisor, caja, banco, hoy):
    apo = mov(afiliado, "APO", 1000, fecha=hoy - timedelta(days=3))
    _transferir(caja, banco, "900", tesorero, hoy - timedelta(days=2))
    with pytest.raises(ValidationError) as e:
        ms.anular_movimiento(apo, usuario=supervisor, motivo="Registrada por error en esta caja")
    assert "negativo" in str(e.value)


def test_no_se_anula_un_pago_de_prestamo_que_ya_se_gasto(sin_mora, afiliado, nuevo_prestamo, tesorero, supervisor,
                                                         caja, banco, hoy):
    p = nuevo_prestamo(afiliado)  # la caja queda en cero tras el desembolso
    pago, _ = ps.registrar_pago(p, usuario=tesorero, tipo="PAGO", fecha=hoy - timedelta(days=2), monto=D("507.51"),
                                metodo_pago="EFECTIVO", cuenta_fondo=caja)
    _transferir(caja, banco, "500", tesorero, hoy - timedelta(days=1))
    with pytest.raises(ValidationError):
        ps.anular_pago(pago, usuario=supervisor, motivo="Pago registrado dos veces")
    pago.refresh_from_db()
    assert pago.estado == "CONFIRMADO"


def test_no_se_anula_un_ingreso_de_actividad_que_ya_se_gasto(tesorero, supervisor, caja, hoy):
    act = acs.crear_actividad({"nombre": "Venta", "fecha_inicio": hoy - timedelta(days=5)}, tesorero)
    ingreso, _ = acs.registrar_movimiento(actividad=act, tipo="INGRESO", fecha=hoy - timedelta(days=2),
                                          concepto="Ventas", monto=D("300"), metodo_pago="EFECTIVO",
                                          cuenta_fondo=caja, usuario=tesorero)
    acs.registrar_movimiento(actividad=act, tipo="GASTO", fecha=hoy, concepto="Insumos", monto=D("250"),
                             metodo_pago="EFECTIVO", cuenta_fondo=caja, usuario=tesorero)
    with pytest.raises(ValidationError):
        acs.anular_movimiento(ingreso, usuario=supervisor, motivo="Ingreso duplicado por error")


def test_parametro_permite_saldo_negativo(afiliado, nuevo_prestamo, tesorero, caja):
    Parametro.objects.filter(clave="caja.permitir_saldo_negativo").update(valor="true")
    p = nuevo_prestamo(afiliado, desembolsar=False)
    ps.desembolsar(p, usuario=tesorero, fecha=p.fecha_aprobacion, cuenta=caja, metodo_pago="EFECTIVO")
    assert cs.saldo(caja) == D("-1000.00")

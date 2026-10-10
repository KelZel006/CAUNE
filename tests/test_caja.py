"""Caja y bancos: libro de caja calculado, saldos, transferencias y controles de saldo. Datos sintéticos."""
import uuid
from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError

from apps.actividades import services as acs
from apps.caja import services as cs
from apps.caja.models import CategoriaCaja, MovimientoCaja
from apps.core.models import Parametro
from apps.prestamos import services as ps


@pytest.fixture
def cat():
    return {c.nombre: c for c in CategoriaCaja.objects.all()}


@pytest.fixture
def caja_mov(tesorero, caja, hoy, cat):
    def registrar(tipo, monto, categoria=None, cuenta=None, fecha=None, usuario=None, **extra):
        if categoria is None and tipo != "TRANSFERENCIA":
            categoria = "Otros ingresos" if tipo == "INGRESO" else "Otros egresos"
        m, _ = cs.registrar_movimiento(tipo=tipo, fecha=fecha or hoy, concepto=extra.pop("concepto", "Prueba"),
                                       monto=D(str(monto)), metodo_pago=extra.pop("metodo_pago", "EFECTIVO"),
                                       cuenta_fondo=cuenta or caja, categoria=cat.get(categoria),
                                       usuario=usuario or tesorero, **extra)
        return m
    return registrar


def test_saldo_reune_todas_las_fuentes_sin_duplicar(afiliado, mov, caja_mov, nuevo_prestamo, tesorero, caja, hoy):
    mov(afiliado, "APO", 5000, fecha=hoy - timedelta(days=70))
    mov(afiliado, "DEP", 1000)
    mov(afiliado, "RDEP", 200)
    caja_mov("INGRESO", 300, "Saldo inicial", fecha=hoy - timedelta(days=80))
    caja_mov("EGRESO", 50, "Gastos administrativos")
    p = nuevo_prestamo(afiliado, monto="1000", plazo=2)  # desembolso de 1000 desde la caja
    ps.registrar_pago(p, usuario=tesorero, tipo="PAGO", fecha=hoy, monto=D("507.51"), metodo_pago="EFECTIVO",
                      cuenta_fondo=caja)
    act = acs.crear_actividad({"nombre": "Rifa", "fecha_inicio": hoy - timedelta(days=5)}, tesorero)
    acs.registrar_movimiento(actividad=act, tipo="INGRESO", fecha=hoy, concepto="Boletos", monto=D("400"),
                             metodo_pago="EFECTIVO", cuenta_fondo=caja, usuario=tesorero)
    acs.registrar_movimiento(actividad=act, tipo="GASTO", fecha=hoy, concepto="Premio", monto=D("150"),
                             metodo_pago="EFECTIVO", cuenta_fondo=caja, usuario=tesorero)
    esperado = D("5000") + 1000 - 200 + 300 - 50 - 1000 + D("507.51") + 400 - 150
    assert cs.saldo(caja) == esperado == D("5807.51")
    # Cada operación aparece exactamente una vez en el libro.
    numeros = [f.numero for f in cs.lineas(caja)]
    assert len(numeros) == len(set(numeros)) == 9


def test_anulados_no_suman(afiliado, mov, caja_mov, supervisor, caja):
    mov(afiliado, "APO", 1000)
    m = caja_mov("INGRESO", 500)
    cs.anular_movimiento(m, usuario=supervisor, motivo="Ingreso registrado por error")
    assert cs.saldo(caja) == D("1000.00")
    m.refresh_from_db()
    with pytest.raises(ValidationError):
        m.delete()


def test_transferencia_mueve_entre_cuentas_sin_cambiar_el_total(afiliado, mov, caja_mov, caja, banco):
    mov(afiliado, "APO", 2000)
    caja_mov("TRANSFERENCIA", 1500, cuenta_destino=banco, metodo_pago="DEPOSITO_BANCARIO", referencia="DEP-1")
    assert cs.saldo(caja) == D("500.00")
    assert cs.saldo(banco) == D("1500.00")
    assert cs.saldo() == D("2000.00")
    flujo = cs.flujo_efectivo()
    assert flujo["neto"] == D("2000.00")
    assert all(f["origen"] != cs.TRANSFERENCIAS for f in flujo["filas"])


def test_transferencia_con_banco_exige_referencia_y_destino_distinto(caja_mov, caja, banco, afiliado, mov):
    mov(afiliado, "APO", 2000)
    with pytest.raises(ValidationError) as e:
        caja_mov("TRANSFERENCIA", 100, cuenta_destino=banco)
    assert "referencia" in e.value.message_dict
    with pytest.raises(ValidationError) as e:
        caja_mov("TRANSFERENCIA", 100, cuenta_destino=caja)
    assert "cuenta_destino" in e.value.message_dict


def test_egreso_sin_saldo_rechazado(afiliado, mov, caja_mov, caja):
    mov(afiliado, "APO", 100)
    with pytest.raises(ValidationError) as e:
        caja_mov("EGRESO", D("100.01"))
    assert "Saldo insuficiente" in str(e.value)
    caja_mov("EGRESO", 100)
    assert cs.saldo(caja) == D("0.00")


def test_egreso_con_fecha_anterior_no_puede_dejar_negativo_un_dia_posterior(afiliado, mov, caja_mov, hoy):
    mov(afiliado, "APO", 1000, fecha=hoy - timedelta(days=10))
    caja_mov("EGRESO", 800, fecha=hoy - timedelta(days=2))
    # Hace 5 días había 1000, pero después salieron 800: solo quedan 200 para cualquier salida anterior.
    with pytest.raises(ValidationError):
        caja_mov("EGRESO", 300, fecha=hoy - timedelta(days=5))
    caja_mov("EGRESO", 200, fecha=hoy - timedelta(days=5))


def test_anular_ingreso_que_ya_se_gasto_rechazado(caja_mov, supervisor):
    ingreso = caja_mov("INGRESO", 500, "Saldo inicial")
    caja_mov("EGRESO", 400)
    with pytest.raises(ValidationError) as e:
        cs.anular_movimiento(ingreso, usuario=supervisor, motivo="Saldo inicial duplicado")
    assert "negativo" in str(e.value)


def test_parametro_permite_saldo_negativo(caja_mov, caja):
    Parametro.objects.filter(clave="caja.permitir_saldo_negativo").update(valor="true")
    caja_mov("EGRESO", 75)
    assert cs.saldo(caja) == D("-75.00")


def test_categoria_debe_coincidir_con_el_tipo(caja_mov):
    with pytest.raises(ValidationError) as e:
        caja_mov("INGRESO", 10, "Gastos administrativos")
    assert "categoria" in e.value.message_dict


def test_efectivo_solo_en_caja(caja_mov, banco):
    with pytest.raises(ValidationError) as e:
        caja_mov("INGRESO", 10, cuenta=banco)
    assert "cuenta_fondo" in e.value.message_dict


def test_misma_clave_no_registra_dos_veces(caja_mov):
    clave = uuid.uuid4()
    a = caja_mov("INGRESO", 10, clave_idempotencia=clave)
    b = caja_mov("INGRESO", 10, clave_idempotencia=clave)
    assert a.pk == b.pk and MovimientoCaja.objects.count() == 1


def test_anulacion_requiere_otro_usuario(caja_mov, tesorero):
    m = caja_mov("INGRESO", 10)
    with pytest.raises(ValidationError):
        cs.anular_movimiento(m, usuario=tesorero, motivo="Lo anulo yo mismo")


def test_libro_con_saldo_inicial_y_acumulado(afiliado, mov, caja_mov, caja, hoy):
    mov(afiliado, "APO", 1000, fecha=hoy - timedelta(days=30))
    caja_mov("EGRESO", 100, "Gastos administrativos", fecha=hoy - timedelta(days=3))
    mov(afiliado, "DEP", 250, fecha=hoy - timedelta(days=1))
    libro = cs.libro(caja, desde=hoy - timedelta(days=5), hasta=hoy)
    assert libro.saldo_inicial == D("1000.00")
    assert [f.saldo for f in libro.lineas] == [D("900.00"), D("1150.00")]
    assert libro.entradas == D("250.00") and libro.salidas == D("100.00")
    assert libro.saldo_final == cs.saldo(caja) == D("1150.00")


def test_otros_resultados_solo_categorias_que_afectan_utilidades(caja_mov):
    caja_mov("INGRESO", 5000, "Saldo inicial")
    caja_mov("INGRESO", 120, "Intereses bancarios")
    caja_mov("EGRESO", 20, "Comisiones bancarias")
    r = cs.otros_resultados()
    assert (r["ingresos"], r["egresos"], r["neto"]) == (D("120.00"), D("20.00"), D("100.00"))


def test_flujo_separa_capital_e_intereses(sin_mora, afiliado, mov, nuevo_prestamo, tesorero, caja, hoy):
    mov(afiliado, "APO", 2000, fecha=hoy - timedelta(days=90))
    p = nuevo_prestamo(afiliado, monto="1000", plazo=2)
    ps.registrar_pago(p, usuario=tesorero, tipo="PAGO", fecha=hoy, monto=D("507.51"), metodo_pago="EFECTIVO",
                      cuenta_fondo=caja)
    filas = {f["origen"]: f for f in cs.flujo_efectivo()["filas"]}
    assert filas[cs.COBROS_INTERES]["entradas"] == D("10.00")
    assert filas[cs.COBROS_CAPITAL]["entradas"] == D("497.51")
    assert filas[cs.DESEMBOLSOS]["salidas"] == D("1000.00")


def test_permisos_caja(caja, presidente, encargado_actividades, cat, hoy):
    for usuario in (presidente, encargado_actividades):
        with pytest.raises(ValidationError):
            cs.registrar_movimiento(tipo="INGRESO", fecha=hoy, concepto="X", monto=D("1"), metodo_pago="EFECTIVO",
                                    cuenta_fondo=caja, categoria=cat["Otros ingresos"], usuario=usuario)

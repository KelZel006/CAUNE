"""Distribución de ganancias: cálculos verificados a mano con datos sintéticos."""
from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError

from apps.actividades import services as acs
from apps.afiliados.services import cambiar_estado
from apps.aportaciones import services as ms
from apps.caja import services as cs
from apps.caja.models import CategoriaCaja
from apps.core.models import Parametro
from apps.distribucion import services as ds
from apps.distribucion.models import Distribucion, PagoGanancia
from apps.prestamos import services as ps


def _param(clave, valor):
    Parametro.objects.filter(clave=clave).update(valor=valor)


@pytest.fixture
def periodo(hoy):
    return hoy - timedelta(days=9), hoy


@pytest.fixture
def socios(nuevo_afiliado, mov, hoy):
    """A, B y C con 1,000 / 3,000 / 6,000 de aportaciones antes del período. A además tiene depósitos."""
    a, b, c = (nuevo_afiliado(nombres=n) for n in ("Ana", "Beto", "Carla"))
    for afiliado, monto in ((a, 1000), (b, 3000), (c, 6000)):
        mov(afiliado, "APO", monto, fecha=hoy - timedelta(days=60))
    mov(a, "DEP", 5000, fecha=hoy - timedelta(days=60))  # los depósitos no cuentan para la base
    return a, b, c


@pytest.fixture
def utilidad_caja(tesorero, caja, hoy):
    def registrar(monto, categoria="Intereses bancarios", fecha=None, tipo="INGRESO"):
        m, _ = cs.registrar_movimiento(tipo=tipo, fecha=fecha or hoy - timedelta(days=1), concepto="Utilidad de prueba",
                                       monto=D(str(monto)), metodo_pago="EFECTIVO", cuenta_fondo=caja,
                                       categoria=CategoriaCaja.objects.get(nombre=categoria), usuario=tesorero)
        return m
    return registrar


@pytest.fixture
def actividad(tesorero, caja, hoy):
    def crear(nombre, ingresos=0, gastos=0):
        act = acs.crear_actividad({"nombre": nombre, "fecha_inicio": hoy - timedelta(days=20)}, tesorero)
        for tipo, monto in (("INGRESO", ingresos), ("GASTO", gastos)):
            if monto:
                acs.registrar_movimiento(actividad=act, tipo=tipo, fecha=hoy - timedelta(days=2), concepto="Prueba",
                                         monto=D(str(monto)), metodo_pago="EFECTIVO", cuenta_fondo=caja,
                                         usuario=tesorero)
        return act
    return crear


def _por_afiliado(calculo):
    return {c: t for c, t in ds.totales_por_afiliado(calculo).items()}


# --------------------------------------------------------------------------- reparto proporcional

def test_quien_mas_aporta_mas_recibe(socios, utilidad_caja, periodo):
    a, b, c = socios
    _param("distribucion.base_calculo", "SALDO_CIERRE")
    utilidad_caja(1000)
    calc = ds.calcular(*periodo)
    general = calc.fondos[0]
    assert general.resultado == D("1000.00")
    assert general.partes == {a.codigo: D("100.00"), b.codigo: D("300.00"), c.codigo: D("600.00")}


def test_excluido_de_actividad_recibe_solo_el_resto(socios, utilidad_caja, actividad, tesorero, periodo):
    """C no participa en la Rifa: su parte sale solo de la utilidad general; A y B se reparten la rifa."""
    a, b, c = socios
    _param("distribucion.base_calculo", "SALDO_CIERRE")
    utilidad_caja(1000)
    rifa = actividad("Rifa", ingresos=600, gastos=100)
    acs.excluir_afiliado(rifa, c, usuario=tesorero, motivo="No trabajó en la rifa de este año")
    calc = ds.calcular(*periodo)
    fondo_rifa = calc.fondos[1]
    assert fondo_rifa.resultado == D("500.00") and fondo_rifa.participantes == 2
    assert fondo_rifa.partes == {a.codigo: D("125.00"), b.codigo: D("375.00")}  # 1,000 : 3,000
    assert _por_afiliado(calc) == {a.codigo: D("225.00"), b.codigo: D("675.00"), c.codigo: D("600.00")}
    assert sum(_por_afiliado(calc).values()) == D("1500.00")


def test_promedio_diario_premia_el_tiempo(nuevo_afiliado, mov, utilidad_caja, periodo, hoy):
    """A tiene 1,000 los 10 días; B deposita 1,000 el día 6 (solo 5 días). Pesos 10,000 : 5,000."""
    a, b = nuevo_afiliado(nombres="Ana"), nuevo_afiliado(nombres="Beto")
    mov(a, "APO", 1000, fecha=hoy - timedelta(days=30))
    mov(b, "APO", 1000, fecha=hoy - timedelta(days=4))
    utilidad_caja(300)
    calc = ds.calcular(*periodo, base="PROMEDIO_DIARIO")
    assert calc.fondos[0].partes == {a.codigo: D("200.00"), b.codigo: D("100.00")}
    bases = {p.afiliado.codigo: p.base for p in calc.participantes}
    assert bases == {a.codigo: D("1000.00"), b.codigo: D("500.00")}
    # Con saldo al cierre ambos pesan igual.
    calc = ds.calcular(*periodo, base="SALDO_CIERRE")
    assert calc.fondos[0].partes == {a.codigo: D("150.00"), b.codigo: D("150.00")}


def test_centavos_por_mayor_residuo_suman_exacto(nuevo_afiliado, mov, utilidad_caja, periodo, hoy):
    socios = [nuevo_afiliado(nombres=n) for n in ("Uno", "Dos", "Tres")]
    for s in socios:
        mov(s, "APO", 500, fecha=hoy - timedelta(days=30))
    utilidad_caja(100)
    partes = ds.calcular(*periodo).fondos[0].partes
    assert sorted(partes.values()) == [D("33.33"), D("33.33"), D("33.34")]
    assert partes[socios[0].codigo] == D("33.34")  # empate: el primer código recibe el centavo
    assert sum(partes.values()) == D("100.00")


def test_repartir_invariantes():
    for total in (D("0.01"), D("999.99"), D("-250.00"), D("12345.67")):
        pesos = {"AF-1": D("3"), "AF-2": D("7.5"), "AF-3": D("0.25"), "AF-4": D("1000")}
        partes = ds.repartir(total, pesos)
        assert sum(partes.values()) == total
        assert max(partes.values()) == partes["AF-4"] if total > 0 else True


def test_intereses_de_prestamos_internos_y_externos_son_utilidad(sin_mora, socios, nuevo_prestamo, tesorero, caja, periodo, hoy):
    a, b, c = socios
    p = nuevo_prestamo(a, monto="1000", plazo=2)
    ps.registrar_pago(p, usuario=tesorero, tipo="PAGO", fecha=hoy - timedelta(days=1), monto=D("507.51"),
                      metodo_pago="EFECTIVO", cuenta_fondo=caja)
    calc = ds.calcular(*periodo)
    general = calc.fondos[0]
    assert general.ingresos == D("10.00")  # solo el interés; el capital recuperado no es ganancia
    assert general.detalle["intereses_prestamos"] == "10.00"


def test_gastos_de_caja_restan_y_saldo_inicial_no_es_utilidad(socios, utilidad_caja, periodo):
    utilidad_caja(1000)
    utilidad_caja(250, "Gastos administrativos", tipo="EGRESO")
    utilidad_caja(50000, "Saldo inicial")
    assert ds.calcular(*periodo).fondos[0].resultado == D("750.00")


def test_solo_cuenta_lo_del_periodo(socios, utilidad_caja, periodo, hoy):
    utilidad_caja(1000, fecha=hoy - timedelta(days=30))  # antes del período
    utilidad_caja(200)
    assert ds.calcular(*periodo).fondos[0].resultado == D("200.00")


def test_reserva_se_descuenta_antes_de_repartir(socios, utilidad_caja, periodo):
    utilidad_caja(1000)
    calc = ds.calcular(*periodo, porcentaje_reserva=D("10"))
    assert calc.fondos[0].reserva == D("100.00") and calc.fondos[0].a_distribuir == D("900.00")
    assert sum(_por_afiliado(calc).values()) == D("900.00")


def test_inactivo_al_cierre_no_participa(socios, utilidad_caja, tesorero, periodo, hoy):
    a, b, c = socios
    cambiar_estado(c, estado_nuevo="INACTIVO", fecha_efectiva=hoy - timedelta(days=3),
                   motivo="Se retiró de la caja", usuario=tesorero)
    utilidad_caja(400)
    _param("distribucion.base_calculo", "SALDO_CIERRE")
    calc = ds.calcular(*periodo)
    assert set(calc.fondos[0].partes) == {a.codigo, b.codigo}
    assert calc.fondos[0].partes[b.codigo] == D("300.00")
    # Para un período que cerró antes de su inactivación, sí participa.
    calc = ds.calcular(periodo[0] - timedelta(days=20), hoy - timedelta(days=5))
    assert c in [p.afiliado for p in calc.participantes]


def test_afiliado_sin_aportaciones_ni_externos_participan(socios, nuevo_afiliado, mov, utilidad_caja, periodo):
    solo_depositos = nuevo_afiliado(nombres="Sin aportes")
    mov(solo_depositos, "DEP", 9000)
    utilidad_caja(100)
    calc = ds.calcular(*periodo)
    assert solo_depositos.codigo not in calc.fondos[0].partes
    assert any(a == solo_depositos for a, _ in calc.no_elegibles)


def test_actividad_con_perdida_la_absorben_sus_participantes(socios, utilidad_caja, actividad, tesorero, periodo):
    a, b, c = socios
    _param("distribucion.base_calculo", "SALDO_CIERRE")
    utilidad_caja(1000)
    feria = actividad("Feria", ingresos=100, gastos=300)  # pérdida de 200
    acs.excluir_afiliado(feria, a, usuario=tesorero, motivo="No participó en la feria")
    calc = ds.calcular(*periodo)
    assert calc.fondos[1].partes == {b.codigo: D("-66.67"), c.codigo: D("-133.33")}
    assert _por_afiliado(calc)[a.codigo] == D("100.00")


# --------------------------------------------------------------------------- flujo: calcular, aprobar, pagar

@pytest.fixture
def dist_aprobada(socios, utilidad_caja, tesorero, admin_caune, periodo):
    _param("distribucion.base_calculo", "SALDO_CIERRE")
    utilidad_caja(1000)
    d = ds.crear_distribucion(desde=periodo[0], hasta=periodo[1], usuario=tesorero)
    return ds.aprobar(d, usuario=admin_caune)


def test_fotografia_guardada_coincide_con_el_calculo(socios, utilidad_caja, actividad, tesorero, periodo):
    utilidad_caja(1000)
    actividad("Rifa", ingresos=500)
    d = ds.crear_distribucion(desde=periodo[0], hasta=periodo[1], usuario=tesorero)
    assert d.codigo == "DIST-001" and d.estado == Distribucion.Estado.CALCULADA
    r = ds.resumen(d)
    assert r["total"] == r["resultado"] == D("1500.00")
    assert len(r["fondos"]) == 2 and len(r["filas"]) == 3
    for f in r["fondos"]:
        assert sum(l.monto for l in f.lineas.all()) == f.a_distribuir
    assert all(sum(x for x in fila["por_fondo"] if x) == fila["total"] for fila in r["filas"])


def test_aprobacion_por_otro_usuario(socios, utilidad_caja, tesorero, admin_caune, periodo):
    utilidad_caja(100)
    d = ds.crear_distribucion(desde=periodo[0], hasta=periodo[1], usuario=tesorero)
    with pytest.raises(ValidationError):
        ds.aprobar(d, usuario=tesorero)
    assert ds.aprobar(d, usuario=admin_caune).estado == Distribucion.Estado.APROBADA


def test_no_se_aprueba_si_los_datos_cambiaron(socios, utilidad_caja, actividad, tesorero, admin_caune, periodo):
    a, b, c = socios
    utilidad_caja(100)
    rifa = actividad("Rifa", ingresos=300)
    d = ds.crear_distribucion(desde=periodo[0], hasta=periodo[1], usuario=tesorero)
    acs.excluir_afiliado(rifa, b, usuario=tesorero, motivo="Se decidió después del cálculo")
    with pytest.raises(ValidationError) as e:
        ds.aprobar(d, usuario=admin_caune)
    assert "Recalcule" in str(e.value)
    d = ds.recalcular(d, usuario=tesorero)
    assert ds.aprobar(d, usuario=admin_caune).estado == Distribucion.Estado.APROBADA


def test_no_se_aprueba_con_afiliados_en_negativo(socios, actividad, tesorero, admin_caune, periodo):
    a, b, c = socios
    actividad("Feria", gastos=300)
    d = ds.crear_distribucion(desde=periodo[0], hasta=periodo[1], usuario=tesorero)
    with pytest.raises(ValidationError) as e:
        ds.aprobar(d, usuario=admin_caune)
    assert "negativo" in str(e.value)


def test_periodos_no_se_cruzan(dist_aprobada, tesorero, hoy):
    with pytest.raises(ValidationError) as e:
        ds.crear_distribucion(desde=hoy - timedelta(days=3), hasta=hoy, usuario=tesorero)
    assert "DIST-001" in str(e.value)


def test_pagar_en_efectivo_sale_de_caja(dist_aprobada, socios, tesorero, caja, hoy):
    a, b, c = socios
    antes = cs.saldo(caja)
    ds.registrar_pagos(dist_aprobada, afiliados=[a, b], forma="PAGO", fecha=hoy, cuenta_fondo=caja,
                       metodo_pago="EFECTIVO", usuario=tesorero)
    assert cs.saldo(caja) == antes - D("400.00")
    dist_aprobada.refresh_from_db()
    assert dist_aprobada.estado == Distribucion.Estado.APROBADA  # falta C
    with pytest.raises(ValidationError):  # una ganancia no se entrega dos veces
        ds.registrar_pagos(dist_aprobada, afiliados=[a], forma="PAGO", fecha=hoy, cuenta_fondo=caja,
                           metodo_pago="EFECTIVO", usuario=tesorero)
    ds.registrar_pagos(dist_aprobada, afiliados=[c], forma="PAGO", fecha=hoy, cuenta_fondo=caja,
                       metodo_pago="EFECTIVO", usuario=tesorero)
    dist_aprobada.refresh_from_db()
    assert dist_aprobada.estado == Distribucion.Estado.APLICADA


def test_capitalizar_acredita_deposito_sin_mover_caja(dist_aprobada, socios, tesorero, caja, hoy):
    a, b, c = socios
    antes = cs.saldo(caja)
    pagos = ds.registrar_pagos(dist_aprobada, afiliados=[c], forma="CAPITALIZACION", fecha=hoy, cuenta_fondo=caja,
                               metodo_pago="", usuario=tesorero)
    # Decisión de CAUNE: la ganancia capitalizada se suma a las aportaciones.
    assert ms.saldos_afiliado(c)["aportaciones"] == D("6600.00")
    assert ms.saldos_afiliado(c)["depositos"] == D("0.00")
    assert pagos[0].movimiento_afiliado.tipo.codigo == "GAN"
    assert cs.saldo(caja) == antes  # el dinero no sale: queda en CAUNE a nombre del afiliado


def test_pago_sin_efectivo_suficiente_no_registra_ninguno(socios, utilidad_caja, tesorero, admin_caune, caja, periodo,
                                                           hoy):
    a, b, c = socios
    # En caja hay 16,000 (aportaciones, depósitos y la utilidad); tras una compra de 15,500 quedan 500,
    # que no alcanzan para entregar los 1,000 de ganancias.
    utilidad_caja(1000)
    cs.registrar_movimiento(tipo="EGRESO", fecha=hoy, concepto="Compra", monto=D("15500"), metodo_pago="EFECTIVO",
                            cuenta_fondo=caja, categoria=CategoriaCaja.objects.get(nombre="Otros egresos"),
                            usuario=tesorero)
    _param("distribucion.base_calculo", "SALDO_CIERRE")
    d = ds.crear_distribucion(desde=periodo[0], hasta=periodo[1] - timedelta(days=1), usuario=tesorero)
    d = ds.aprobar(d, usuario=admin_caune)
    with pytest.raises(ValidationError):
        ds.registrar_pagos(d, afiliados=[a, b, c], forma="PAGO", fecha=hoy, cuenta_fondo=caja,
                           metodo_pago="EFECTIVO", usuario=tesorero)
    assert not PagoGanancia.objects.exists()


def test_anular_pago_devuelve_a_aprobada(dist_aprobada, socios, tesorero, supervisor, caja, hoy):
    a, b, c = socios
    pagos = ds.registrar_pagos(dist_aprobada, afiliados=[a, b, c], forma="CAPITALIZACION", fecha=hoy,
                               cuenta_fondo=caja, metodo_pago="", usuario=tesorero)
    dist_aprobada.refresh_from_db()
    assert dist_aprobada.estado == Distribucion.Estado.APLICADA
    ds.anular_pago(pagos[0], usuario=supervisor, motivo="Prefiere recibirla en efectivo")
    dist_aprobada.refresh_from_db()
    assert dist_aprobada.estado == Distribucion.Estado.APROBADA
    assert ms.saldos_afiliado(a)["aportaciones"] == D("1000.00")  # la capitalización se anuló
    ds.registrar_pagos(dist_aprobada, afiliados=[a], forma="PAGO", fecha=hoy, cuenta_fondo=caja,
                       metodo_pago="EFECTIVO", usuario=tesorero)


def test_anular_distribucion_solo_sin_pagos(dist_aprobada, socios, tesorero, supervisor, caja, hoy):
    ds.registrar_pagos(dist_aprobada, afiliados=[socios[0]], forma="PAGO", fecha=hoy, cuenta_fondo=caja,
                       metodo_pago="EFECTIVO", usuario=tesorero)
    with pytest.raises(ValidationError):
        ds.anular(dist_aprobada, usuario=supervisor, motivo="Se calculó con datos incompletos")


def test_anulada_libera_el_periodo(dist_aprobada, supervisor, tesorero, periodo):
    ds.anular(dist_aprobada, usuario=supervisor, motivo="Se calculó con datos incompletos")
    nueva = ds.crear_distribucion(desde=periodo[0], hasta=periodo[1], usuario=tesorero)
    assert nueva.codigo == "DIST-002"


def test_permisos_distribucion(socios, presidente, encargado_actividades, periodo):
    for usuario in (presidente, encargado_actividades):
        with pytest.raises(ValidationError):
            ds.crear_distribucion(desde=periodo[0], hasta=periodo[1], usuario=usuario)


def test_exclusion_exige_permiso_y_motivo(socios, actividad, encargado_actividades, tesorero):
    rifa = actividad("Rifa", ingresos=10)
    with pytest.raises(ValidationError):
        acs.excluir_afiliado(rifa, socios[0], usuario=encargado_actividades, motivo="Motivo suficiente")
    with pytest.raises(ValidationError):
        acs.excluir_afiliado(rifa, socios[0], usuario=tesorero, motivo="corto")
    ex = acs.excluir_afiliado(rifa, socios[0], usuario=tesorero, motivo="No participó en la rifa")
    with pytest.raises(ValidationError):
        acs.excluir_afiliado(rifa, socios[0], usuario=tesorero, motivo="No participó en la rifa")
    acs.incluir_afiliado(ex, usuario=tesorero, motivo="Sí participó, error de registro")
    assert acs.excluidos_ids(rifa) == set()

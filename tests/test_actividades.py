from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError

from apps.actividades import services as acs
from apps.actividades.models import Actividad, MovimientoActividad


@pytest.fixture
def actividad(tesorero, hoy):
    return acs.crear_actividad({"nombre": "Venta de tamales", "descripcion": "Ficticia", "fecha_inicio": hoy - timedelta(days=30)},
                               tesorero)


@pytest.fixture
def mov_act(tesorero, caja, hoy, fondear):
    def registrar(actividad, tipo, monto, subactividad=None, concepto="Concepto de prueba", usuario=None, **extra):
        fecha = extra.pop("fecha", hoy)
        if tipo == "GASTO":
            fondear(caja, monto, fecha)
        m, _ = acs.registrar_movimiento(actividad=actividad, tipo=tipo, fecha=fecha, concepto=concepto,
                                        monto=D(str(monto)), metodo_pago="EFECTIVO", cuenta_fondo=caja,
                                        usuario=usuario or tesorero, subactividad=subactividad, **extra)
        return m
    return registrar


def test_codigo_y_resultado_con_varios_ingresos_y_gastos(actividad, mov_act):
    assert actividad.codigo == "ACT-001"
    for monto in ("1500", "750.50", "249.50"):
        mov_act(actividad, "INGRESO", monto)
    for monto in ("800", "200.25"):
        mov_act(actividad, "GASTO", monto)
    assert acs.resultado_actividad(actividad) == {"ingresos": D("2500.00"), "gastos": D("1000.25"), "neto": D("1499.75")}


def test_perdida(actividad, mov_act):
    mov_act(actividad, "INGRESO", 100)
    mov_act(actividad, "GASTO", 350)
    assert acs.resultado_actividad(actividad)["neto"] == D("-250.00")


def test_subactividades_suman_al_total(actividad, mov_act, tesorero):
    comida = acs.crear_subactividad(actividad, {"nombre": "Comida"}, tesorero)
    bebida = acs.crear_subactividad(actividad, {"nombre": "Bebidas"}, tesorero)
    mov_act(actividad, "INGRESO", 1000, comida)
    mov_act(actividad, "GASTO", 400, comida)
    mov_act(actividad, "INGRESO", 300, bebida)
    mov_act(actividad, "GASTO", 50)  # gasto general sin subactividad
    filas = acs.resultados_por_subactividad(actividad)
    por_nombre = {(f["subactividad"].nombre if f["subactividad"] else None): f["neto"] for f in filas}
    assert por_nombre == {"Comida": D("600.00"), "Bebidas": D("300.00"), None: D("-50.00")}
    assert sum(f["neto"] for f in filas) == acs.resultado_actividad(actividad)["neto"] == D("850.00")


def test_resultado_por_periodo(actividad, mov_act, hoy):
    mov_act(actividad, "INGRESO", 100, fecha=hoy - timedelta(days=20))
    mov_act(actividad, "INGRESO", 200, fecha=hoy - timedelta(days=2))
    assert acs.resultado_actividad(actividad, desde=hoy - timedelta(days=5))["ingresos"] == D("200.00")
    assert acs.resultado_general(hasta=hoy - timedelta(days=10))["ingresos"] == D("100.00")


def test_anulado_no_suma(actividad, mov_act, supervisor):
    m = mov_act(actividad, "INGRESO", 500)
    mov_act(actividad, "INGRESO", 100)
    acs.anular_movimiento(m, usuario=supervisor, motivo="Ingreso digitado dos veces")
    assert acs.resultado_actividad(actividad)["ingresos"] == D("100.00")
    with pytest.raises(ValidationError):
        m.refresh_from_db(); m.delete()


def test_subactividad_de_otra_actividad_rechazada(actividad, mov_act, tesorero, hoy):
    otra = acs.crear_actividad({"nombre": "Rifa", "fecha_inicio": hoy}, tesorero)
    ajena = acs.crear_subactividad(otra, {"nombre": "Boletos"}, tesorero)
    with pytest.raises(ValidationError) as e:
        mov_act(actividad, "INGRESO", 10, ajena)
    assert "subactividad" in e.value.message_dict


def test_actividad_cerrada_no_admite_registros(actividad, mov_act, admin_caune):
    acs.cambiar_estado_actividad(actividad, admin_caune, "Actividad finalizada en junio")
    actividad.refresh_from_db()
    assert actividad.estado == Actividad.Estado.CERRADA
    with pytest.raises(ValidationError):
        mov_act(actividad, "INGRESO", 10)


@pytest.mark.parametrize("monto", ["0", "-5", "1.001"])
def test_montos_invalidos(actividad, mov_act, monto):
    with pytest.raises(ValidationError):
        mov_act(actividad, "GASTO", monto)
    assert MovimientoActividad.objects.count() == 0


def test_permisos_de_actividades(actividad, mov_act, encargado_actividades, presidente, prestamos):
    assert mov_act(actividad, "INGRESO", 10, usuario=encargado_actividades).pk
    for usuario in (presidente, prestamos):
        with pytest.raises(ValidationError):
            mov_act(actividad, "INGRESO", 10, usuario=usuario)

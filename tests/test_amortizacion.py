"""Cuadros de amortización comparados contra cálculos hechos a mano."""
from datetime import date
from decimal import Decimal as D

import pytest

from apps.prestamos.amortizacion import (CAPITAL_FIJO, CUOTA_FIJA, cuota_fija, generar_cuadro, sumar_meses,
                                         totales_cuadro)


def test_cuota_fija_dos_cuotas_a_mano():
    # 1000 al 1 % mensual, 2 cuotas: cuota = 10 / (1 - 1.01^-2) = 507.51
    filas = generar_cuadro(D("1000"), D("1"), 2, CUOTA_FIJA, date(2026, 1, 15))
    assert [(f.saldo_inicial, f.interes, f.capital, f.cuota, f.saldo_final) for f in filas] == [
        (D("1000.00"), D("10.00"), D("497.51"), D("507.51"), D("502.49")),
        (D("502.49"), D("5.02"), D("502.49"), D("507.51"), D("0.00")),
    ]
    assert [f.fecha_vencimiento for f in filas] == [date(2026, 1, 15), date(2026, 2, 15)]


def test_cuota_fija_caso_airtable_prest_001():
    # PREST-001 de Airtable: 15,000 a 18 % anual (1.5 % mensual), 12 cuotas. Airtable registraba L 1,375.50 a mano.
    assert cuota_fija(D("15000"), D("1.5"), 12) == D("1375.20")
    filas = generar_cuadro(D("15000"), D("1.5"), 12, CUOTA_FIJA, date(2026, 2, 8))
    assert filas[0].interes == D("225.00") and filas[0].capital == D("1150.20")
    assert all(f.cuota == D("1375.20") for f in filas[:-1])
    t = totales_cuadro(filas)
    assert t["capital"] == D("15000.00") and filas[-1].saldo_final == 0
    assert abs(filas[-1].cuota - D("1375.20")) <= D("0.05")  # el ajuste final es de centavos


def test_capital_fijo_a_mano():
    # 5000 al 1 %, 6 cuotas: capital 833.33; la última ajusta a 833.35
    filas = generar_cuadro(D("5000"), D("1"), 6, CAPITAL_FIJO, date(2026, 3, 1))
    assert [f.capital for f in filas] == [D("833.33")] * 5 + [D("833.35")]
    assert [f.interes for f in filas] == [D("50.00"), D("41.67"), D("33.33"), D("25.00"), D("16.67"), D("8.33")]
    assert sum(f.capital for f in filas) == D("5000.00")


@pytest.mark.parametrize("metodo", [CUOTA_FIJA, CAPITAL_FIJO])
@pytest.mark.parametrize("monto, tasa, plazo", [("8000", "1.25", 8), ("12000", "5", 10), ("999.99", "1", 7),
                                                ("250000", "1", 60), ("100", "0", 3)])
def test_invariantes(metodo, monto, tasa, plazo):
    filas = generar_cuadro(D(monto), D(tasa), plazo, metodo, date(2026, 1, 31))
    assert len(filas) == plazo
    assert sum(f.capital for f in filas) == D(monto)
    assert filas[-1].saldo_final == 0
    for anterior, f in zip(filas, filas[1:]):
        assert f.saldo_inicial == anterior.saldo_final
    for f in filas:
        assert f.cuota == f.capital + f.interes
        assert f.interes == (f.saldo_inicial * D(tasa) / 100).quantize(D("0.01"), rounding="ROUND_HALF_UP")
        assert f.capital >= 0


def test_tasa_cero():
    filas = generar_cuadro(D("100"), D("0"), 3, CUOTA_FIJA, date(2026, 1, 1))
    assert [f.cuota for f in filas] == [D("33.33"), D("33.33"), D("33.34")]


def test_fechas_fin_de_mes():
    assert sumar_meses(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert sumar_meses(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert sumar_meses(date(2026, 1, 31), 2) == date(2026, 3, 31)
    assert sumar_meses(date(2026, 11, 15), 3) == date(2027, 2, 15)


@pytest.mark.parametrize("args", [("0", "1", 2), ("100", "-1", 2), ("100", "1", 0)])
def test_entradas_invalidas(args):
    with pytest.raises(ValueError):
        generar_cuadro(D(args[0]), D(args[1]), args[2], CUOTA_FIJA, date(2026, 1, 1))

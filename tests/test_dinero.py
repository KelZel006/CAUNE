from decimal import Decimal

import pytest

from apps.core.dinero import formato_lempiras, monto_en_letras, redondear


@pytest.mark.parametrize("valor, esperado", [
    (Decimal("1250"), "L 1,250.00"),
    (Decimal("0"), "L 0.00"),
    (None, "L 0.00"),
    (Decimal("1234567.891"), "L 1,234,567.89"),
    (Decimal("-50.5"), "L -50.50"),
    (Decimal("0.005"), "L 0.01"),  # HALF_UP
])
def test_formato_lempiras(valor, esperado):
    assert formato_lempiras(valor) == esperado


def test_redondeo_half_up():
    assert redondear(Decimal("2.675")) == Decimal("2.68")
    assert redondear(Decimal("2.665")) == Decimal("2.67")


@pytest.mark.parametrize("valor, esperado", [
    (Decimal("1"), "UN LEMPIRA CON 00/100"),
    (Decimal("21"), "VEINTIÚN LEMPIRAS CON 00/100"),
    (Decimal("100"), "CIEN LEMPIRAS CON 00/100"),
    (Decimal("101.5"), "CIENTO UN LEMPIRAS CON 50/100"),
    (Decimal("1250.75"), "MIL DOSCIENTOS CINCUENTA LEMPIRAS CON 75/100"),
    (Decimal("15000"), "QUINCE MIL LEMPIRAS CON 00/100"),
    (Decimal("1000000"), "UN MILLÓN DE LEMPIRAS CON 00/100"),
    (Decimal("2500300.10"), "DOS MILLONES QUINIENTOS MIL TRESCIENTOS LEMPIRAS CON 10/100"),
    (Decimal("999.99"), "NOVECIENTOS NOVENTA Y NUEVE LEMPIRAS CON 99/100"),
])
def test_monto_en_letras(valor, esperado):
    assert monto_en_letras(valor) == esperado

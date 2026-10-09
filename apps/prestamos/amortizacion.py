"""Cálculo del cuadro de amortización (funciones puras, sin base de datos).

Reglas aprobadas por CAUNE (08/10/2026):
- La tasa es MENSUAL y el interés de cada cuota = saldo de capital × tasa mensual (sin contar días).
- Todos los importes se redondean HALF_UP a 2 decimales en cada cuota.
- La última cuota se ajusta para cancelar exactamente el saldo.
"""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.core.dinero import CERO, redondear

CUOTA_FIJA = "CUOTA_FIJA"
CAPITAL_FIJO = "CAPITAL_FIJO"


@dataclass(frozen=True)
class FilaCuadro:
    numero: int
    fecha_vencimiento: date
    saldo_inicial: Decimal
    capital: Decimal
    interes: Decimal
    cuota: Decimal
    saldo_final: Decimal


def sumar_meses(fecha, meses):
    """Misma fecha N meses después; si el día no existe (31 de abril), usa el último día del mes."""
    anio, mes = divmod(fecha.month - 1 + meses, 12)
    anio += fecha.year
    mes += 1
    return date(anio, mes, min(fecha.day, monthrange(anio, mes)[1]))


def cuota_fija(monto, tasa_mensual, plazo):
    """Cuota del sistema francés. `tasa_mensual` en porcentaje (1 = 1 %)."""
    r = Decimal(tasa_mensual) / Decimal(100)
    if r == 0:
        return redondear(Decimal(monto) / plazo)
    return redondear(Decimal(monto) * r / (1 - (1 + r) ** -plazo))


def generar_cuadro(monto, tasa_mensual, plazo, metodo, primer_vencimiento):
    monto = redondear(monto)
    if monto <= 0:
        raise ValueError("El monto debe ser mayor que cero.")
    if plazo < 1:
        raise ValueError("El plazo debe ser de al menos una cuota.")
    if Decimal(tasa_mensual) < 0:
        raise ValueError("La tasa no puede ser negativa.")
    if metodo not in (CUOTA_FIJA, CAPITAL_FIJO):
        raise ValueError("Método de amortización no reconocido.")

    r = Decimal(tasa_mensual) / Decimal(100)
    cuota_base = cuota_fija(monto, tasa_mensual, plazo) if metodo == CUOTA_FIJA else None
    capital_base = redondear(monto / plazo) if metodo == CAPITAL_FIJO else None
    saldo = monto
    filas = []
    for n in range(1, plazo + 1):
        interes = redondear(saldo * r)
        if n == plazo:
            capital = saldo  # la última cuota cancela exactamente el saldo
        elif metodo == CUOTA_FIJA:
            capital = min(cuota_base - interes, saldo)
        else:
            capital = min(capital_base, saldo)
        cuota = capital + interes
        filas.append(FilaCuadro(n, sumar_meses(primer_vencimiento, n - 1), saldo, capital, interes, cuota,
                                saldo - capital))
        saldo -= capital
    assert saldo == CERO
    return filas


def totales_cuadro(filas):
    return {
        "capital": sum((f.capital for f in filas), CERO),
        "interes": sum((f.interes for f in filas), CERO),
        "total": sum((f.cuota for f in filas), CERO),
    }

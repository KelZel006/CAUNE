"""Utilidades monetarias. Todo importe se maneja con Decimal y redondeo HALF_UP a 2 decimales."""
from decimal import ROUND_HALF_UP, Decimal

CENTAVO = Decimal("0.01")
CERO = Decimal("0.00")


def redondear(valor):
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def formato_lempiras(valor):
    """Decimal('1250') -> 'L 1,250.00'; negativos -> 'L -1,250.00'."""
    if valor is None or valor == "":
        valor = CERO
    valor = redondear(valor)
    signo = "-" if valor < 0 else ""
    return f"L {signo}{abs(valor):,.2f}"


_UNIDADES = [
    "", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE", "DIEZ", "ONCE", "DOCE",
    "TRECE", "CATORCE", "QUINCE", "DIECISÉIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE", "VEINTE",
    "VEINTIÚN", "VEINTIDÓS", "VEINTITRÉS", "VEINTICUATRO", "VEINTICINCO", "VEINTISÉIS", "VEINTISIETE",
    "VEINTIOCHO", "VEINTINUEVE",
]
_DECENAS = ["", "", "", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
_CENTENAS = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS", "SEISCIENTOS",
             "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]


def _menor_mil(n):
    if n == 100:
        return "CIEN"
    centenas, resto = divmod(n, 100)
    partes = [_CENTENAS[centenas]] if centenas else []
    if resto:
        if resto < 30:
            partes.append(_UNIDADES[resto])
        else:
            decenas, unidades = divmod(resto, 10)
            partes.append(_DECENAS[decenas] + (f" Y {_UNIDADES[unidades]}" if unidades else ""))
    return " ".join(partes)


def entero_a_letras(n):
    if n == 0:
        return "CERO"
    millones, resto = divmod(n, 1_000_000)
    miles, unidades = divmod(resto, 1000)
    partes = []
    if millones:
        partes.append("UN MILLÓN" if millones == 1 else f"{entero_a_letras(millones)} MILLONES")
    if miles:
        partes.append("MIL" if miles == 1 else f"{_menor_mil(miles)} MIL")
    if unidades:
        partes.append(_menor_mil(unidades))
    return " ".join(partes)


def monto_en_letras(valor):
    """Decimal('1250.50') -> 'MIL DOSCIENTOS CINCUENTA LEMPIRAS CON 50/100'."""
    valor = redondear(valor)
    entero = int(valor)
    centavos = int((valor - entero) * 100)
    letras = entero_a_letras(entero)
    if entero and entero % 1_000_000 == 0:
        letras += " DE"
    moneda = "LEMPIRA" if entero == 1 else "LEMPIRAS"
    return f"{letras} {moneda} CON {centavos:02d}/100"

from django.db import transaction

from .models import Secuencia

SECUENCIAS_INICIALES = {
    "AF": ("Código de afiliado", 4),
    "OP": ("Operaciones de aportaciones y depósitos", 6),
    "PAG": ("Recibos de pago de préstamos", 6),
    "ACT": ("Actividades económicas", 3),
    "MA": ("Movimientos de actividades", 6),
    "CJ": ("Movimientos de caja y transferencias", 6),
    "DIST": ("Distribuciones de ganancias", 3),
    "PG": ("Pagos y capitalizaciones de ganancias", 6),
}


def siguiente_numero(prefijo):
    """Reserva y devuelve el siguiente número de la secuencia.

    Debe llamarse dentro de una transacción: la fila se bloquea hasta el final de
    la transacción, así dos operaciones simultáneas nunca obtienen el mismo número.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("siguiente_numero() debe ejecutarse dentro de transaction.atomic().")
    try:
        secuencia = Secuencia.objects.select_for_update().get(prefijo=prefijo)
    except Secuencia.DoesNotExist:
        descripcion, relleno = SECUENCIAS_INICIALES.get(prefijo, (prefijo, 6))
        secuencia = Secuencia.objects.create(prefijo=prefijo, descripcion=descripcion, relleno=relleno)
    numero = secuencia.siguiente
    secuencia.siguiente = numero + 1
    secuencia.save(update_fields=["siguiente"])
    return secuencia.formatear(numero)


def siguiente_correlativo(prefijo, descripcion, relleno):
    """Reserva el siguiente número entero de una secuencia (se crea la primera vez que se usa)."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("siguiente_correlativo() debe ejecutarse dentro de transaction.atomic().")
    Secuencia.objects.get_or_create(prefijo=prefijo, defaults={"descripcion": descripcion, "relleno": relleno})
    secuencia = Secuencia.objects.select_for_update().get(prefijo=prefijo)
    numero = secuencia.siguiente
    secuencia.siguiente = numero + 1
    secuencia.save(update_fields=["siguiente"])
    return numero, secuencia.relleno


def numero_prestamo(tipo_prestatario, anio):
    """1 (interno) o 2 (externo) + año + correlativo de 3 dígitos que se reinicia cada año. Ej.: 12026001, 22027001.

    Internos y externos comparten el correlativo del año: el préstamo n.º 5 del año es 12026005 o 22026005.
    """
    numero, relleno = siguiente_correlativo(f"PR{anio}", f"Préstamos {anio}", 3)
    return f"{1 if tipo_prestatario == 'INTERNO' else 2}{anio}{numero:0{relleno}d}"


def asegurar_secuencias():
    for prefijo, (descripcion, relleno) in SECUENCIAS_INICIALES.items():
        Secuencia.objects.get_or_create(prefijo=prefijo, defaults={"descripcion": descripcion, "relleno": relleno})

from django.db import transaction

from .models import Secuencia

SECUENCIAS_INICIALES = {
    "AF": ("Código de afiliado", 4),
    "OP": ("Operaciones de aportaciones y depósitos", 6),
    "PREST": ("Préstamos", 4),
    "PAG": ("Recibos de pago de préstamos", 6),
    "ACT": ("Actividades económicas", 3),
    "MA": ("Movimientos de actividades", 6),
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


def asegurar_secuencias():
    for prefijo, (descripcion, relleno) in SECUENCIAS_INICIALES.items():
        Secuencia.objects.get_or_create(prefijo=prefijo, defaults={"descripcion": descripcion, "relleno": relleno})

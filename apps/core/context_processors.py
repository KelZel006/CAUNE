from . import parametros


def cooperativa(request):
    """Datos generales de CAUNE disponibles en todas las plantillas."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"coop": {"nombre": "Caja de Ahorro Unión y Esfuerzo", "siglas": "CAUNE"}}
    return {"coop": datos_cooperativa()}


def datos_cooperativa():
    return {campo: parametros.obtener(f"coop.{campo}")
            for campo in ("nombre", "siglas", "fundacion", "rtn", "direccion", "telefono", "correo")}

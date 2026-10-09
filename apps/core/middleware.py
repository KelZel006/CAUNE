import contextvars

_request_actual = contextvars.ContextVar("caune_request", default=None)


def obtener_request():
    """Devuelve la petición HTTP en curso (o None fuera de una petición)."""
    return _request_actual.get()


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _request_actual.set(request)
        try:
            return self.get_response(request)
        finally:
            _request_actual.reset(token)

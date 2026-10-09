from django import template
from django.utils.html import format_html

from apps.core.dinero import formato_lempiras, monto_en_letras

register = template.Library()


@register.filter
def lempiras(valor):
    return formato_lempiras(valor)


@register.filter
def restar(valor, otro):
    """Resta exacta de Decimal (el filtro `add` de Django convierte a entero y trunca centavos)."""
    return (valor or 0) - (otro or 0)


@register.filter
def add_dec(valor, otro):
    """Suma exacta de Decimal."""
    return (valor or 0) + (otro or 0)


@register.filter
def letras(valor):
    return monto_en_letras(valor)


@register.filter
def celda(valor):
    """Formato de celda para reportes genéricos: dinero en lempiras, fechas DD/MM/AAAA."""
    from datetime import date
    from decimal import Decimal

    if isinstance(valor, Decimal):
        return formato_lempiras(valor)
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return "" if valor is None else valor


@register.filter
def es_numero(valor):
    from decimal import Decimal

    return isinstance(valor, (Decimal, int, float)) and not isinstance(valor, bool)


@register.filter
def fecha(valor):
    return valor.strftime("%d/%m/%Y") if valor else ""


@register.filter
def identidad(valor):
    if valor and len(valor) == 13:
        return f"{valor[:4]}-{valor[4:8]}-{valor[8:]}"
    return valor or ""


@register.simple_tag
def icono(nombre):
    return format_html('<svg class="icon" aria-hidden="true" focusable="false"><use href="#i-{}"></use></svg>', nombre)


@register.filter
def iniciales(usuario):
    palabras = [p for p in (usuario.get_full_name() or usuario.get_username()).replace(".", " ").split() if p[0].isalpha()]
    return "".join(p[0] for p in palabras[:2]).upper() or "?"


@register.simple_tag(takes_context=True)
def orden(context, campo, etiqueta):
    """Encabezado de columna ordenable: alterna entre ascendente y descendente."""
    request = context["request"]
    actual = request.GET.get("orden", context.get("orden_actual", ""))
    nuevo = f"-{campo}" if actual == campo else campo
    params = request.GET.copy()
    params["orden"] = nuevo
    params.pop("page", None)
    indicador = " ▲" if actual == campo else (" ▼" if actual == f"-{campo}" else "")
    return format_html('<a class="th-orden" href="?{}">{}{}</a>', params.urlencode(), etiqueta, indicador)


@register.simple_tag(takes_context=True)
def url_exportar(context, formato):
    params = context["request"].GET.copy()
    params["formato"] = formato
    params.pop("page", None)
    return f"?{params.urlencode()}"

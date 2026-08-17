"""
Filtros de formato con separadores chilenos (miles con punto, decimales con coma).
"""
from django import template

register = template.Library()


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@register.filter
def formato_clp(value):
    """Monto en pesos, sin decimales."""
    v = _to_float(value)
    if v is None:
        return value
    return '$' + f'{v:,.0f}'.replace(',', '.')


@register.filter
def formato_numero(value, decimals=2):
    v = _to_float(value)
    if v is None:
        return value
    try:
        decimals = int(decimals)
    except (TypeError, ValueError):
        decimals = 2
    txt = f'{v:,.{decimals}f}'
    return txt.replace(',', 'X').replace('.', ',').replace('X', '.')


@register.filter
def formato_tasa(value, decimals=4):
    v = _to_float(value)
    if v is None:
        return value
    return formato_numero(v, decimals) + '%'


@register.filter
def formato_factor(value):
    v = _to_float(value)
    if v is None:
        return value
    return f'{v:.8f}'.replace('.', ',')


@register.filter
def formato_precio(value):
    v = _to_float(value)
    if v is None:
        return value
    return formato_numero(v, 4)


@register.filter
def color_mtm(value):
    v = _to_float(value)
    if v is None:
        return ''
    return 'neg' if v < 0 else 'pos'


@register.filter
def abs_val(value):
    v = _to_float(value)
    return abs(v) if v is not None else value


@register.filter
def get_item(d, key):
    """Acceso a diccionarios desde el template."""
    try:
        return d.get(key)
    except AttributeError:
        return None

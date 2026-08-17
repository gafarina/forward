"""
Convenciones de conteo de días.

En el repositorio original el parámetro `day_count` sólo cambiaba la base del
año (360 vs 365) y dejaba los días como días corridos. En particular la opción
"30/360" era idéntica a ACT/360, con un comentario reconociéndolo:

    elif day_count == '30/360':
        # Simplify 30/360 to 360 year base for factor, days already calendar
        year_days = 360.0

Acá cada convención calcula su propia fracción de año, que es lo que
efectivamente entra en el factor de descuento.
"""

from __future__ import annotations

from datetime import date

__all__ = ["DAY_COUNT_CONVENTIONS", "day_count_fraction", "day_count_days", "year_basis"]

DAY_COUNT_CONVENTIONS = (
    "ACT/360",
    "ACT/365",
    "30/360",        # 30/360 US (Bond Basis)
    "30E/360",       # 30/360 Europea (ISDA/Eurobond)
    "ACT/ACT",       # ACT/ACT ISDA
)


def year_basis(convention: str) -> float:
    """Base anual nominal de la convención (para reportes)."""
    conv = convention.upper()
    if conv == "ACT/365":
        return 365.0
    if conv == "ACT/ACT":
        return 365.25
    return 360.0


def _days_30_360_us(d1: date, d2: date) -> int:
    """30/360 US (Bond Basis), regla NASD."""
    dd1, dd2 = d1.day, d2.day
    # Fin de febrero
    if _is_last_day_of_february(d1) and _is_last_day_of_february(d2):
        dd2 = 30
    if _is_last_day_of_february(d1):
        dd1 = 30
    if dd2 == 31 and dd1 >= 30:
        dd2 = 30
    if dd1 == 31:
        dd1 = 30
    return 360 * (d2.year - d1.year) + 30 * (d2.month - d1.month) + (dd2 - dd1)


def _days_30e_360(d1: date, d2: date) -> int:
    """30E/360 (Eurobond): ambos días 31 se llevan a 30, sin regla de febrero."""
    dd1 = 30 if d1.day == 31 else d1.day
    dd2 = 30 if d2.day == 31 else d2.day
    return 360 * (d2.year - d1.year) + 30 * (d2.month - d1.month) + (dd2 - dd1)


def _is_last_day_of_february(d: date) -> bool:
    if d.month != 2:
        return False
    if d.day == 29:
        return True
    is_leap = (d.year % 4 == 0 and d.year % 100 != 0) or d.year % 400 == 0
    return d.day == 28 and not is_leap


def day_count_days(d1: date, d2: date, convention: str = "ACT/360") -> int:
    """Días que la convención reconoce entre d1 y d2 (numerador)."""
    conv = convention.upper()
    if conv == "30/360":
        return _days_30_360_us(d1, d2)
    if conv == "30E/360":
        return _days_30e_360(d1, d2)
    return (d2 - d1).days


def day_count_fraction(d1: date, d2: date, convention: str = "ACT/360") -> float:
    """
    Fracción de año entre d1 y d2 según la convención.

    ACT/ACT ISDA reparte los días entre años bisiestos y no bisiestos, que es
    la única convención acá cuyo denominador no es constante.
    """
    conv = convention.upper()

    if conv == "ACT/360":
        return (d2 - d1).days / 360.0
    if conv == "ACT/365":
        return (d2 - d1).days / 365.0
    if conv == "30/360":
        return _days_30_360_us(d1, d2) / 360.0
    if conv == "30E/360":
        return _days_30e_360(d1, d2) / 360.0
    if conv == "ACT/ACT":
        return _act_act_isda(d1, d2)
    raise ValueError(
        f"Convención '{convention}' desconocida. Disponibles: {DAY_COUNT_CONVENTIONS}"
    )


def _act_act_isda(d1: date, d2: date) -> float:
    if d2 < d1:
        return -_act_act_isda(d2, d1)
    if d1 == d2:
        return 0.0

    total = 0.0
    for year in range(d1.year, d2.year + 1):
        y_start = max(d1, date(year, 1, 1))
        y_end = min(d2, date(year + 1, 1, 1))
        if y_end <= y_start:
            continue
        is_leap = (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
        total += (y_end - y_start).days / (366.0 if is_leap else 365.0)
    return total

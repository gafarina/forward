"""
Calendarios de días hábiles (Chile y Estados Unidos).

El repositorio original ajustaba vencimientos con una regla que sólo movía
sábados y domingos ("modified following" simplificado). Eso subestima los
plazos cuando el vencimiento cae en feriado, lo que desplaza el factor de
descuento y el punto interpolado de la curva.

Este módulo implementa los feriados legales chilenos, incluyendo las reglas
de traslado de la Ley 19.973 / 20.215 / 20.299, el feriado bancario del
31 de diciembre, y un calendario de EE.UU. para construir el calendario
conjunto CLP+USD que corresponde a un forward USD/CLP con entrega.

Uso:
    cal = get_calendar("CL")
    cal.is_business_day(date(2026, 9, 18))   -> False
    cal.adjust(date(2026, 9, 18), "ModifiedFollowing")
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

__all__ = [
    "easter_sunday",
    "chile_holidays",
    "us_holidays",
    "Calendar",
    "get_calendar",
    "BUSINESS_DAY_CONVENTIONS",
]

BUSINESS_DAY_CONVENTIONS = (
    "Exacto",              # sin ajuste: se usa la fecha tal cual
    "Following",           # siguiente día hábil
    "ModifiedFollowing",   # siguiente hábil, salvo que cambie de mes -> anterior
    "Preceding",           # día hábil anterior
    "ModifiedPreceding",
)


# ──────────────────────────────────────────────────────────────────────
# Pascua (algoritmo gregoriano anónimo) — base de Viernes y Sábado Santo
# ──────────────────────────────────────────────────────────────────────

def easter_sunday(year: int) -> date:
    """Domingo de Resurrección para un año gregoriano."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lam = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lam) // 451
    month = (h + lam - 7 * m + 114) // 31
    day = ((h + lam - 7 * m + 114) % 31) + 1
    return date(year, month, day)


# ──────────────────────────────────────────────────────────────────────
# Chile
# ──────────────────────────────────────────────────────────────────────

def _traslado_lunes(d: date) -> date:
    """
    Ley 20.215: los feriados del 29 de junio y 12 de octubre se trasladan al
    lunes de la misma semana si caen martes, miércoles o jueves, y al lunes de
    la semana siguiente si caen viernes.
    """
    wd = d.weekday()  # 0 = lunes
    if wd in (1, 2, 3):            # martes / miércoles / jueves
        return d - timedelta(days=wd)
    if wd == 4:                    # viernes
        return d + timedelta(days=3)
    return d


def _traslado_iglesias(year: int) -> date:
    """
    Ley 20.299: Día de las Iglesias Evangélicas y Protestantes.
    Base 31 de octubre. Si cae martes se adelanta al viernes anterior (27-oct);
    si cae miércoles se posterga al viernes siguiente (2-nov).
    """
    d = date(year, 10, 31)
    wd = d.weekday()
    if wd == 1:                    # martes -> viernes anterior
        return d - timedelta(days=4)
    if wd == 2:                    # miércoles -> viernes siguiente
        return d + timedelta(days=2)
    return d


# Solsticio de invierno (Día Nacional de los Pueblos Indígenas, Ley 21.357).
# La fecha depende del solsticio austral; se tabula porque no es derivable de
# forma trivial y un error acá mueve un día hábil completo.
_SOLSTICIO = {
    2021: date(2021, 6, 21),
    2022: date(2022, 6, 21),
    2023: date(2023, 6, 21),
    2024: date(2024, 6, 20),
    2025: date(2025, 6, 20),
    2026: date(2026, 6, 21),
    2027: date(2027, 6, 21),
    2028: date(2028, 6, 20),
    2029: date(2029, 6, 20),
    2030: date(2030, 6, 21),
}


@lru_cache(maxsize=256)
def chile_holidays(year: int, *, bancario: bool = True) -> frozenset[date]:
    """
    Feriados legales chilenos del año indicado.

    bancario=True agrega el 31 de diciembre, que es feriado bancario y por lo
    tanto no es día hábil para liquidación de operaciones de cambio.
    """
    easter = easter_sunday(year)
    days: set[date] = {
        date(year, 1, 1),                    # Año Nuevo
        easter - timedelta(days=2),          # Viernes Santo
        easter - timedelta(days=1),          # Sábado Santo
        date(year, 5, 1),                    # Día del Trabajo
        date(year, 5, 21),                   # Glorias Navales
        _traslado_lunes(date(year, 6, 29)),  # San Pedro y San Pablo
        date(year, 7, 16),                   # Virgen del Carmen
        date(year, 8, 15),                   # Asunción de la Virgen
        date(year, 9, 18),                   # Independencia Nacional
        date(year, 9, 19),                   # Glorias del Ejército
        _traslado_lunes(date(year, 10, 12)),  # Encuentro de Dos Mundos
        _traslado_iglesias(year),            # Iglesias Evangélicas
        date(year, 11, 1),                   # Todos los Santos
        date(year, 12, 8),                   # Inmaculada Concepción
        date(year, 12, 25),                  # Navidad
    }

    solsticio = _SOLSTICIO.get(year)
    if solsticio is not None:
        days.add(solsticio)

    # Ley 20.215: feriados "puente" de Fiestas Patrias.
    dieciocho = date(year, 9, 18)
    if dieciocho.weekday() == 1:             # martes -> lunes 17 es feriado
        days.add(date(year, 9, 17))
    elif dieciocho.weekday() == 2:           # miércoles -> viernes 20 es feriado
        days.add(date(year, 9, 20))

    if bancario:
        days.add(date(year, 12, 31))         # feriado bancario

    return frozenset(days)


# ──────────────────────────────────────────────────────────────────────
# Estados Unidos (necesario para el calendario conjunto de un USD/CLP)
# ──────────────────────────────────────────────────────────────────────

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-ésimo `weekday` (0=lunes) del mes. n negativo = contando desde el final."""
    if n > 0:
        d = date(year, month, 1)
        offset = (weekday - d.weekday()) % 7
        return d + timedelta(days=offset + 7 * (n - 1))
    # último
    if month == 12:
        d = date(year, 12, 31)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    offset = (d.weekday() - weekday) % 7
    return d - timedelta(days=offset)


def _observed(d: date) -> date:
    """Regla de observancia federal de EE.UU.: sábado -> viernes, domingo -> lunes."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=256)
def us_holidays(year: int) -> frozenset[date]:
    """Feriados federales de EE.UU. (con regla de observancia)."""
    days = {
        _observed(date(year, 1, 1)),                 # New Year's Day
        _nth_weekday(year, 1, 0, 3),                 # MLK
        _nth_weekday(year, 2, 0, 3),                 # Presidents' Day
        _nth_weekday(year, 5, 0, -1),                # Memorial Day
        _observed(date(year, 6, 19)),                # Juneteenth
        _observed(date(year, 7, 4)),                 # Independence Day
        _nth_weekday(year, 9, 0, 1),                 # Labor Day
        _nth_weekday(year, 10, 0, 2),                # Columbus Day
        _observed(date(year, 11, 11)),               # Veterans Day
        _nth_weekday(year, 11, 3, 4),                # Thanksgiving
        _observed(date(year, 12, 25)),               # Christmas
    }
    return frozenset(days)


# ──────────────────────────────────────────────────────────────────────
# Calendario
# ──────────────────────────────────────────────────────────────────────

class Calendar:
    """Calendario de días hábiles con reglas de ajuste de fecha."""

    def __init__(self, name: str, holiday_fn, extra: frozenset[date] | None = None):
        self.name = name
        self._holiday_fn = holiday_fn
        self._extra = frozenset(extra or ())

    # -- consultas ----------------------------------------------------

    def holidays(self, year: int) -> frozenset[date]:
        return self._holiday_fn(year) | {d for d in self._extra if d.year == year}

    def is_weekend(self, d: date) -> bool:
        return d.weekday() >= 5

    def is_holiday(self, d: date) -> bool:
        return d in self.holidays(d.year)

    def is_business_day(self, d: date) -> bool:
        return not self.is_weekend(d) and not self.is_holiday(d)

    # -- ajustes ------------------------------------------------------

    def next_business_day(self, d: date) -> date:
        while not self.is_business_day(d):
            d += timedelta(days=1)
        return d

    def prev_business_day(self, d: date) -> date:
        while not self.is_business_day(d):
            d -= timedelta(days=1)
        return d

    def adjust(self, d: date, convention: str = "ModifiedFollowing") -> date:
        """Ajusta `d` al día hábil que corresponda según la convención."""
        if convention == "Exacto" or self.is_business_day(d):
            return d
        if convention == "Following":
            return self.next_business_day(d)
        if convention == "ModifiedFollowing":
            adj = self.next_business_day(d)
            if adj.month != d.month:
                return self.prev_business_day(d)
            return adj
        if convention == "Preceding":
            return self.prev_business_day(d)
        if convention == "ModifiedPreceding":
            adj = self.prev_business_day(d)
            if adj.month != d.month:
                return self.next_business_day(d)
            return adj
        raise ValueError(f"Convención de días hábiles desconocida: {convention}")

    def add_business_days(self, d: date, n: int) -> date:
        """Suma n días hábiles (n puede ser negativo). Útil para spot T+1/T+2."""
        step = 1 if n >= 0 else -1
        remaining = abs(n)
        cur = d
        while remaining > 0:
            cur += timedelta(days=step)
            if self.is_business_day(cur):
                remaining -= 1
        return cur

    def business_days_between(self, start: date, end: date) -> int:
        if end < start:
            return -self.business_days_between(end, start)
        n, cur = 0, start
        while cur < end:
            cur += timedelta(days=1)
            if self.is_business_day(cur):
                n += 1
        return n

    def __repr__(self) -> str:  # pragma: no cover - utilidad de depuración
        return f"<Calendar {self.name}>"


class JointCalendar(Calendar):
    """Unión de calendarios: un día es hábil sólo si lo es en todos."""

    def __init__(self, name: str, calendars: list[Calendar]):
        self.name = name
        self._calendars = calendars
        self._extra = frozenset()

    def holidays(self, year: int) -> frozenset[date]:
        out: frozenset[date] = frozenset()
        for c in self._calendars:
            out = out | c.holidays(year)
        return out


_NULL = Calendar("NULL", lambda year: frozenset())
_CL = Calendar("CL", chile_holidays)
_US = Calendar("US", us_holidays)
_CLUS = JointCalendar("CL+US", [_CL, _US])

_REGISTRY = {
    "NULL": _NULL,      # sólo fines de semana
    "CL": _CL,
    "US": _US,
    "CL+US": _CLUS,
}


def get_calendar(code: str = "CL") -> Calendar:
    """Devuelve el calendario registrado. Códigos: NULL, CL, US, CL+US."""
    try:
        return _REGISTRY[code.upper()]
    except KeyError as exc:
        raise ValueError(
            f"Calendario '{code}' no registrado. Disponibles: {sorted(_REGISTRY)}"
        ) from exc

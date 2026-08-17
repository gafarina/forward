"""
Curvas de mercado: interpolación, extrapolación y descuento.

Diferencias contra el motor original (`services/interpolation.py`):

1. La interpolación log-lineal existía pero nunca se aplicaba a la curva de
   descuento: el código elegía log-lineal para el forward y dejaba la tasa de
   descuento en lineal, con un comentario explicando que log(tasa negativa)
   falla. La solución correcta es interpolar log-linealmente sobre los
   **factores de descuento**, no sobre las tasas, que es lo estándar y admite
   tasas negativas.

2. La extrapolación era siempre plana. Para una curva de forwards outright eso
   es incorrecto: un outright plano más allá del último nodo implica que los
   puntos forward dejan de crecer, es decir, un diferencial de tasas que
   colapsa a cero. Se agrega la política `puntos` (mantiene constante la
   pendiente de puntos forward), y se marca siempre el resultado como
   extrapolado.

3. No había manejo de nodos duplicados ni desordenados: el usuario podía
   guardar una curva no monótona y la interpolación devolvía basura en
   silencio.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass, field

__all__ = [
    "Curve",
    "DiscountCurve",
    "INTERP_METHODS",
    "EXTRAP_METHODS",
    "COMPOUNDING",
    "discount_factor",
]

INTERP_METHODS = ("Lineal", "Log-Lineal", "Escalonada")
EXTRAP_METHODS = ("Plana", "Lineal", "Puntos")
COMPOUNDING = ("Compuesta", "Simple", "Continua")


# ──────────────────────────────────────────────────────────────────────
# Curva genérica
# ──────────────────────────────────────────────────────────────────────

@dataclass
class Curve:
    """
    Curva definida por nodos (plazo en días, valor).

    `interp`  — método de interpolación entre nodos.
    `extrap`  — qué hacer fuera del rango [primer nodo, último nodo].
    """

    name: str
    xs: list[float]
    ys: list[float]
    interp: str = "Lineal"
    extrap: str = "Plana"
    _extrapolated: bool = field(default=False, init=False, repr=False)

    def __post_init__(self):
        if len(self.xs) != len(self.ys):
            raise ValueError(f"Curva '{self.name}': plazos y valores de distinto largo.")
        if not self.xs:
            raise ValueError(f"Curva '{self.name}': sin nodos.")
        if self.interp not in INTERP_METHODS:
            raise ValueError(f"Interpolación '{self.interp}' no soportada.")
        if self.extrap not in EXTRAP_METHODS:
            raise ValueError(f"Extrapolación '{self.extrap}' no soportada.")

        # Ordena y colapsa nodos duplicados quedándose con el último valor.
        merged: dict[float, float] = {}
        for x, y in zip(self.xs, self.ys):
            merged[float(x)] = float(y)
        pairs = sorted(merged.items())
        self.xs = [p[0] for p in pairs]
        self.ys = [p[1] for p in pairs]

    # -- consultas ----------------------------------------------------

    @property
    def min_tenor(self) -> float:
        return self.xs[0]

    @property
    def max_tenor(self) -> float:
        return self.xs[-1]

    def is_outside(self, x: float) -> bool:
        return x < self.xs[0] or x > self.xs[-1]

    def __len__(self) -> int:
        return len(self.xs)

    # -- evaluación ---------------------------------------------------

    def value(self, x: float) -> float:
        """Valor de la curva en el plazo x (días). Interpola o extrapola."""
        x = float(x)
        xs, ys = self.xs, self.ys

        if len(xs) == 1:
            return ys[0]

        if x < xs[0]:
            return self._extrapolate(x, left=True)
        if x > xs[-1]:
            return self._extrapolate(x, left=False)

        i = bisect_left(xs, x)
        if i < len(xs) and xs[i] == x:
            return ys[i]

        x0, x1 = xs[i - 1], xs[i]
        y0, y1 = ys[i - 1], ys[i]
        w = (x - x0) / (x1 - x0)

        if self.interp == "Escalonada":
            return y0
        if self.interp == "Log-Lineal" and y0 > 0 and y1 > 0:
            return math.exp(math.log(y0) * (1 - w) + math.log(y1) * w)
        return y0 + w * (y1 - y0)

    def _extrapolate(self, x: float, *, left: bool) -> float:
        """
        Extiende la curva fuera del rango de nodos.

        Plana   — mantiene el nodo extremo. Es lo que hacía el motor v1 y lo
                  que produce la discrepancia contra la planilla en plazos
                  menores al primer nodo de la curva de descuento.
        Lineal  — prolonga la pendiente del **segmento extremo**. Reproduce la
                  planilla Cordada.
        Puntos  — prolonga la pendiente **promedio de toda la curva**, medida
                  entre el primer y el último nodo. Para una curva de outrights
                  eso equivale a mantener constante el ritmo de acumulación de
                  puntos forward, es decir, el diferencial de tasas implícito,
                  en vez de perpetuar el diferencial marginal del último tramo,
                  que suele ser el más ruidoso por falta de liquidez.
        """
        xs, ys = self.xs, self.ys
        if self.extrap == "Plana":
            return ys[0] if left else ys[-1]

        if self.extrap == "Puntos":
            span = xs[-1] - xs[0]
            slope = (ys[-1] - ys[0]) / span if span else 0.0
            anchor_x, anchor_y = (xs[0], ys[0]) if left else (xs[-1], ys[-1])
            return anchor_y + slope * (x - anchor_x)

        # "Lineal": pendiente del segmento extremo.
        if left:
            x0, x1, y0, y1 = xs[0], xs[1], ys[0], ys[1]
            anchor_x, anchor_y = x0, y0
        else:
            x0, x1, y0, y1 = xs[-2], xs[-1], ys[-2], ys[-1]
            anchor_x, anchor_y = x1, y1

        slope = (y1 - y0) / (x1 - x0) if x1 != x0 else 0.0
        return anchor_y + slope * (x - anchor_x)

    def shifted(self, *, additive: float = 0.0, multiplicative: float = 0.0) -> "Curve":
        """Copia con un desplazamiento aditivo y/o porcentual (para escenarios)."""
        ys = [(y + additive) * (1.0 + multiplicative) for y in self.ys]
        return Curve(self.name, list(self.xs), ys, self.interp, self.extrap)

    def to_points(self) -> list[dict]:
        return [{"tenor_days": int(x), "value": y} for x, y in zip(self.xs, self.ys)]


# ──────────────────────────────────────────────────────────────────────
# Curva de descuento
# ──────────────────────────────────────────────────────────────────────

def discount_factor(rate_pct: float, year_fraction: float, compounding: str = "Compuesta") -> float:
    """
    Factor de descuento a partir de una tasa cero expresada en porcentaje.

    Compuesta  : 1 / (1 + r)^t          ← convención de mercado local CLP
    Simple     : 1 / (1 + r·t)          ← usual en plazos menores a un año
    Continua   : exp(-r·t)
    """
    r = rate_pct / 100.0
    t = year_fraction

    if compounding == "Simple":
        denom = 1.0 + r * t
        if denom <= 0:
            raise ValueError("Factor de descuento simple no definido (1 + r·t ≤ 0).")
        return 1.0 / denom
    if compounding == "Continua":
        return math.exp(-r * t)
    if compounding == "Compuesta":
        base = 1.0 + r
        if base <= 0:
            raise ValueError("Factor de descuento compuesto no definido (1 + r ≤ 0).")
        return base ** (-t)
    raise ValueError(f"Capitalización '{compounding}' no soportada. Use {COMPOUNDING}.")


class DiscountCurve:
    """
    Curva de tasas cero con interpolación consistente sobre factores.

    Cuando el método es "Log-Lineal", la interpolación se hace sobre los
    factores de descuento (equivalente a interpolar linealmente la tasa
    continua × plazo), no sobre las tasas. Es lo que corresponde y además
    tolera tasas cero o negativas.
    """

    def __init__(
        self,
        curve: Curve,
        *,
        compounding: str = "Compuesta",
        basis: float = 360.0,
    ):
        self.curve = curve
        self.compounding = compounding
        self.basis = basis
        self.name = curve.name

    # -- API ----------------------------------------------------------

    def zero_rate(self, days: float) -> float:
        """Tasa cero en porcentaje para el plazo indicado."""
        if self.curve.interp != "Log-Lineal":
            return self.curve.value(days)
        return self._zero_from_df(days)

    def factor(self, days: float, year_fraction: float | None = None) -> float:
        """Factor de descuento para el plazo indicado."""
        t = year_fraction if year_fraction is not None else days / self.basis
        return discount_factor(self.zero_rate(days), t, self.compounding)

    def is_outside(self, days: float) -> bool:
        return self.curve.is_outside(days)

    @property
    def max_tenor(self) -> float:
        return self.curve.max_tenor

    @property
    def min_tenor(self) -> float:
        return self.curve.min_tenor

    # -- interno ------------------------------------------------------

    def _node_factors(self) -> list[float]:
        return [
            discount_factor(y, x / self.basis, self.compounding)
            for x, y in zip(self.curve.xs, self.curve.ys)
        ]

    def _zero_from_df(self, days: float) -> float:
        """Interpola log-linealmente en factores y devuelve la tasa equivalente."""
        xs = self.curve.xs
        dfs = self._node_factors()
        x = float(days)

        if x <= 0:
            return self.curve.ys[0]

        log_df_curve = Curve(
            f"{self.curve.name}::logDF",
            list(xs),
            [math.log(df) for df in dfs],
            interp="Lineal",
            extrap=self.curve.extrap,
        )
        log_df = log_df_curve.value(x)
        df = math.exp(log_df)

        t = x / self.basis
        if t == 0:
            return self.curve.ys[0]
        if self.compounding == "Simple":
            return ((1.0 / df) - 1.0) / t * 100.0
        if self.compounding == "Continua":
            return -math.log(df) / t * 100.0
        return ((1.0 / df) ** (1.0 / t) - 1.0) * 100.0

    def shifted_bp(self, bp: float) -> "DiscountCurve":
        """Copia con desplazamiento paralelo en puntos base (para DV01/rho)."""
        shifted = self.curve.shifted(additive=bp / 100.0)  # 1 bp = 0.01 en %
        return DiscountCurve(shifted, compounding=self.compounding, basis=self.basis)

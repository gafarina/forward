"""
Ajustes por riesgo de crédito: CVA y DVA.

El motor original calculaba:

    credit_spread = 0.005                       # 50 bps fijos para todos
    risk_proxy = credit_spread * (días / base)
    cva = mtm * risk_proxy   si mtm > 0
    dva = |mtm| * risk_proxy si mtm < 0

Eso tiene tres problemas de fondo:

1. Usa el MtM de hoy como si fuera la exposición esperada de toda la vida del
   contrato. Un forward con MtM cero hoy tiene exposición futura esperada
   estrictamente positiva; ese CVA da cero.
2. Aproxima la probabilidad de default por `spread × t`, sin la severidad
   (LGD) ni la supervivencia acumulada. Sobrestima en plazos largos.
3. Aplica el spread a nivel de operación, no de contraparte, e ignora el
   neteo. Con un ISDA con neteo, el CVA de la cartera es menor que la suma
   de los CVA individuales.

Acá se implementa el estándar de mercado en su forma reducida:

    h  = s / (1 - R)                     intensidad de default (hazard rate)
    S(t) = exp(-h·t)                     probabilidad de supervivencia
    CVA = (1-R) · Σ_i EPE(t_i) · [S(t_{i-1}) - S(t_i)]
    DVA = (1-R_own) · Σ_i ENE(t_i) · [S_own(t_{i-1}) - S_own(t_i)]

con la exposición esperada de un forward FX calculada en forma cerrada bajo un
modelo normal (Bachelier) sobre el precio forward, que es la aproximación
habitual para un producto lineal:

    V(t) = ε·(K − F_t)·N·DF(t),   F_t ~ N(F_0, σ_F²·t)

    EPE(t) = N·DF(t)·[ m·Φ(m/v) + v·φ(m/v) ]      con m = ε·(K − F_0), v = σ_F·√t
    ENE(t) = N·DF(t)·[ −m·Φ(−m/v) + v·φ(−m/v) ]

El neteo se aplica agregando las exposiciones de todas las operaciones de la
contraparte antes de aplicar la probabilidad de default, y luego se asigna el
CVA de la cartera a cada operación por su contribución marginal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = ["CreditProfile", "expected_exposure", "cva_dva_netting_set", "DEFAULT_CREDIT"]

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _phi(x: float) -> float:
    """Densidad normal estándar."""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _Phi(x: float) -> float:
    """Distribución normal estándar acumulada."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class CreditProfile:
    """
    Parámetros de crédito de una contraparte.

    spread_bp   : spread de crédito (CDS o proxy por rating), en puntos base.
    recovery    : tasa de recuperación esperada (R). LGD = 1 − R.
    own_spread_bp / own_recovery : lo mismo para la propia entidad (DVA).
    fx_vol      : volatilidad anualizada del tipo de cambio, en términos
                  absolutos de CLP por USD si `vol_is_relative` es False, o
                  como fracción (ej. 0.12 = 12%) si es True.
    """

    spread_bp: float = 100.0
    recovery: float = 0.40
    own_spread_bp: float = 60.0
    own_recovery: float = 0.40
    fx_vol: float = 0.12
    vol_is_relative: bool = True
    steps_per_year: int = 12

    @property
    def lgd(self) -> float:
        return 1.0 - self.recovery

    @property
    def own_lgd(self) -> float:
        return 1.0 - self.own_recovery

    @property
    def hazard(self) -> float:
        """Intensidad de default implícita en el spread."""
        lgd = max(self.lgd, 1e-6)
        return (self.spread_bp / 10_000.0) / lgd

    @property
    def own_hazard(self) -> float:
        lgd = max(self.own_lgd, 1e-6)
        return (self.own_spread_bp / 10_000.0) / lgd

    def survival(self, t_years: float) -> float:
        return math.exp(-self.hazard * max(t_years, 0.0))

    def own_survival(self, t_years: float) -> float:
        return math.exp(-self.own_hazard * max(t_years, 0.0))

    def absolute_vol(self, forward_level: float) -> float:
        """Volatilidad en CLP por USD (Bachelier) a partir del nivel forward."""
        if self.vol_is_relative:
            return self.fx_vol * abs(forward_level)
        return self.fx_vol


DEFAULT_CREDIT = CreditProfile()


# ──────────────────────────────────────────────────────────────────────
# Exposición esperada
# ──────────────────────────────────────────────────────────────────────

def expected_exposure(
    *,
    sign: int,
    strike: float,
    forward: float,
    notional: float,
    vol_abs: float,
    t_years: float,
    discount: float,
) -> tuple[float, float]:
    """
    Exposición esperada positiva (EPE) y negativa (ENE) de un forward FX en t.

    Devuelve (EPE, ENE), ambas en moneda de cotización y ya descontadas.
    """
    m = sign * (strike - forward) * notional * discount
    v = vol_abs * math.sqrt(max(t_years, 0.0)) * notional * discount

    if v <= 0:
        return max(m, 0.0), max(-m, 0.0)

    z = m / v
    epe = m * _Phi(z) + v * _phi(z)
    ene = -m * _Phi(-z) + v * _phi(-z)
    return epe, ene


# ──────────────────────────────────────────────────────────────────────
# CVA / DVA sobre un conjunto de neteo
# ──────────────────────────────────────────────────────────────────────

@dataclass
class _TradeSpec:
    sign: int
    strike: float
    notional: float
    t_years: float
    forward_fn: object          # callable(t_years) -> forward outright
    discount_fn: object         # callable(t_years) -> factor de descuento
    key: object = None


def cva_dva_netting_set(
    trades: list[dict],
    credit: CreditProfile,
    *,
    netting: bool = True,
) -> dict:
    """
    Calcula CVA y DVA de un conjunto de operaciones con la misma contraparte.

    Cada operación en `trades` es un dict con:
        sign, strike, notional, t_years, forward_fn, discount_fn, key

    Con `netting=True` las exposiciones se agregan antes de aplicar la
    probabilidad de default (comportamiento correcto bajo un ISDA con neteo).
    Con `netting=False` se calcula operación por operación, que es la cota
    superior y el criterio conservador cuando no hay contrato marco.

    Devuelve {'cva', 'dva', 'por_operacion': {key: {'cva','dva'}}, 'perfil': [...]}.
    """
    specs = [_TradeSpec(**t) for t in trades]
    if not specs:
        return {"cva": 0.0, "dva": 0.0, "por_operacion": {}, "perfil": []}

    horizon = max(s.t_years for s in specs)
    if horizon <= 0:
        return {
            "cva": 0.0,
            "dva": 0.0,
            "por_operacion": {s.key: {"cva": 0.0, "dva": 0.0} for s in specs},
            "perfil": [],
        }

    n_steps = max(1, int(math.ceil(horizon * credit.steps_per_year)))
    grid = [horizon * (i + 1) / n_steps for i in range(n_steps)]

    perfil: list[dict] = []
    cva_total = 0.0
    dva_total = 0.0
    contrib_epe: dict[object, float] = {s.key: 0.0 for s in specs}
    contrib_ene: dict[object, float] = {s.key: 0.0 for s in specs}

    prev_t = 0.0
    prev_s = 1.0
    prev_s_own = 1.0

    for t in grid:
        epe_sum = 0.0
        ene_sum = 0.0
        netted_value = 0.0
        netted_vol = 0.0
        per_trade_epe: dict[object, float] = {}
        per_trade_ene: dict[object, float] = {}

        for s in specs:
            if s.t_years <= prev_t:
                continue  # ya venció antes de este paso
            t_eff = min(t, s.t_years)
            fwd = s.forward_fn(t_eff)
            df = s.discount_fn(t_eff)
            vol_abs = credit.absolute_vol(fwd)

            epe, ene = expected_exposure(
                sign=s.sign,
                strike=s.strike,
                forward=fwd,
                notional=s.notional,
                vol_abs=vol_abs,
                t_years=t_eff,
                discount=df,
            )
            per_trade_epe[s.key] = per_trade_epe.get(s.key, 0.0) + epe
            per_trade_ene[s.key] = per_trade_ene.get(s.key, 0.0) + ene
            epe_sum += epe
            ene_sum += ene

            # Para el conjunto neteado: media y desviación del valor agregado.
            #
            # Todas las operaciones del conjunto miran el **mismo** tipo de
            # cambio, así que sus exposiciones están perfectamente
            # correlacionadas: la sensibilidad del conjunto es la suma con
            # signo de las sensibilidades individuales (dV_i/dF = -ε_i·N_i·DF_i)
            # y la desviación del valor neto es su valor absoluto por σ·√t.
            # Sumar varianzas (como si fueran factores independientes) le da
            # beneficio de neteo incluso a operaciones del mismo lado, que es
            # justamente lo que no debe ocurrir.
            netted_value += s.sign * (s.strike - fwd) * s.notional * df
            netted_vol += s.sign * vol_abs * math.sqrt(t_eff) * s.notional * df

        if netting:
            v = abs(netted_vol)
            if v > 0:
                z = netted_value / v
                epe_set = netted_value * _Phi(z) + v * _phi(z)
                ene_set = -netted_value * _Phi(-z) + v * _phi(-z)
            else:
                epe_set = max(netted_value, 0.0)
                ene_set = max(-netted_value, 0.0)
        else:
            epe_set, ene_set = epe_sum, ene_sum

        surv = credit.survival(t)
        surv_own = credit.own_survival(t)
        pd_marginal = max(prev_s - surv, 0.0)
        pd_own_marginal = max(prev_s_own - surv_own, 0.0)

        cva_step = credit.lgd * epe_set * pd_marginal
        dva_step = credit.own_lgd * ene_set * pd_own_marginal
        cva_total += cva_step
        dva_total += dva_step

        # Asignación por contribución a la exposición del conjunto.
        if epe_sum > 0:
            for k, v_epe in per_trade_epe.items():
                contrib_epe[k] += cva_step * (v_epe / epe_sum)
        if ene_sum > 0:
            for k, v_ene in per_trade_ene.items():
                contrib_ene[k] += dva_step * (v_ene / ene_sum)

        perfil.append(
            {
                "t": round(t, 4),
                "epe": round(epe_set, 2),
                "ene": round(ene_set, 2),
                "supervivencia": round(surv, 6),
                "cva_paso": round(cva_step, 2),
                "dva_paso": round(dva_step, 2),
            }
        )

        prev_t, prev_s, prev_s_own = t, surv, surv_own

    return {
        "cva": round(cva_total, 2),
        "dva": round(dva_total, 2),
        "por_operacion": {
            k: {"cva": round(contrib_epe[k], 2), "dva": round(contrib_ene[k], 2)}
            for k in contrib_epe
        },
        "perfil": perfil,
    }

"""
Motor de valorización de forwards FX (USD/CLP y otros pares contra CLP).

Este módulo no depende de Django: recibe estructuras planas y devuelve
resultados planos. Eso permite que exactamente el mismo código alimente la
aplicación web, la generación del libro Excel y la suite de tests de
reconciliación entre ambos.

Convención de signos
--------------------
    ε = +1  si la operación es una **Venta** de la moneda base
    ε = −1  si es una **Compra**

    MtM = ε · (K − F_t) · N · DF

donde K es el precio forward pactado, F_t el forward de mercado al plazo
residual, N el nocional en moneda base y DF el factor de descuento en moneda
de cotización. Un vendedor gana cuando el mercado cae por debajo del precio
pactado, de ahí el signo.

Descomposición
--------------
    Componente spot   = ε · (S₀ − S_t) · N · DF
    Puntos forward    = MtM − Componente spot

S₀ es el tipo de cambio spot vigente **el día en que se pactó** la operación.
Esto separa el resultado atribuible al movimiento del spot del atribuible al
movimiento del diferencial de tasas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta

from .calendars import get_calendar, BUSINESS_DAY_CONVENTIONS
from .credit import CreditProfile, cva_dva_netting_set
from .curves import Curve, DiscountCurve, COMPOUNDING, EXTRAP_METHODS, INTERP_METHODS
from .daycount import DAY_COUNT_CONVENTIONS, day_count_fraction, year_basis

__all__ = [
    "Contract",
    "MarketData",
    "PricingConfig",
    "price_contract",
    "price_portfolio",
    "sensitivity_matrix",
]


# ──────────────────────────────────────────────────────────────────────
# Entradas
# ──────────────────────────────────────────────────────────────────────

@dataclass
class Contract:
    """Un forward FX. Independiente de cualquier valorización."""

    notional: float
    fwd_price: float                 # K, precio pactado
    maturity_date: date
    side: str = "Venta"              # "Venta" | "Compra"
    spot_inicio: float = 0.0         # S₀, spot al momento de pactar
    counterparty: str = ""
    folio: str = ""
    base_ccy: str = "USD"
    quote_ccy: str = "CLP"
    modality: str = "Compensacion"
    start_date: date | None = None
    fwd_curve: str = "FWDUSDCLP"
    disc_curve: str = "CLP423"
    cartera: str = ""
    id: object = None

    @property
    def sign(self) -> int:
        return 1 if str(self.side).strip().lower().startswith("v") else -1


@dataclass
class MarketData:
    """Fotografía de mercado a una fecha de valorización."""

    valuation_date: date
    spot: float
    curves: dict[str, Curve]
    label: str = ""

    def curve(self, name: str) -> Curve | None:
        return self.curves.get(name)


@dataclass
class PricingConfig:
    """Parámetros metodológicos de la valorización."""

    day_count: str = "ACT/360"
    interp_method: str = "Lineal"
    extrap_method: str = "Plana"
    business_days: str = "Exacto"
    calendar: str = "CL"
    compounding: str = "Compuesta"
    calc_greeks: bool = True
    calc_cva: bool = False
    netting: bool = True
    credit: CreditProfile = field(default_factory=CreditProfile)

    def validate(self) -> None:
        if self.day_count not in DAY_COUNT_CONVENTIONS:
            raise ValueError(f"day_count '{self.day_count}' no soportado.")
        if self.interp_method not in INTERP_METHODS:
            raise ValueError(f"interp_method '{self.interp_method}' no soportado.")
        if self.extrap_method not in EXTRAP_METHODS:
            raise ValueError(f"extrap_method '{self.extrap_method}' no soportado.")
        if self.business_days not in BUSINESS_DAY_CONVENTIONS:
            raise ValueError(f"business_days '{self.business_days}' no soportado.")
        if self.compounding not in COMPOUNDING:
            raise ValueError(f"compounding '{self.compounding}' no soportado.")


# ──────────────────────────────────────────────────────────────────────
# Valorización de un contrato
# ──────────────────────────────────────────────────────────────────────

def _prepare_curves(market: MarketData, contract: Contract, config: PricingConfig):
    fwd_raw = market.curve(contract.fwd_curve)
    disc_raw = market.curve(contract.disc_curve)
    if fwd_raw is None or len(fwd_raw) == 0:
        raise LookupError(f"Falta la curva forward '{contract.fwd_curve}'.")
    if disc_raw is None or len(disc_raw) == 0:
        raise LookupError(f"Falta la curva de descuento '{contract.disc_curve}'.")

    fwd = Curve(fwd_raw.name, list(fwd_raw.xs), list(fwd_raw.ys),
                interp=config.interp_method, extrap=config.extrap_method)
    disc_c = Curve(disc_raw.name, list(disc_raw.xs), list(disc_raw.ys),
                   interp=config.interp_method, extrap=config.extrap_method)
    disc = DiscountCurve(disc_c, compounding=config.compounding,
                         basis=year_basis(config.day_count))
    return fwd, disc


def price_contract(
    contract: Contract,
    market: MarketData,
    config: PricingConfig | None = None,
) -> dict:
    """Valoriza un contrato y devuelve un diccionario con el detalle completo."""
    config = config or PricingConfig()
    config.validate()

    cal = get_calendar(config.calendar)
    val_date = market.valuation_date
    mat_raw = contract.maturity_date
    mat_date = cal.adjust(mat_raw, config.business_days)

    days_to_mat = (mat_date - val_date).days
    year_fraction = day_count_fraction(val_date, mat_date, config.day_count)

    K = float(contract.fwd_price)
    N = float(contract.notional)
    S0 = float(contract.spot_inicio or 0.0)
    St = float(market.spot)
    eps = contract.sign

    result: dict = {
        "contract_id": contract.id,
        "folio": contract.folio,
        "counterparty": contract.counterparty,
        "cartera": contract.cartera or "-",
        "side": contract.side,
        "notional": N,
        "currency": contract.base_ccy,
        "quote_currency": contract.quote_ccy,
        "maturity_date": mat_date.isoformat(),
        "maturity_date_raw": mat_raw.isoformat(),
        "maturity_adjusted": mat_date != mat_raw,
        "days_to_mat": days_to_mat,
        "year_fraction": round(year_fraction, 8),
        "spot_inicio": S0,
        "spot_val": St,
        "fwd_contract": K,
        "fwd_mkt": None,
        "disc_rate": None,
        "disc_factor": None,
        "mtm": None,
        "spot_component": None,
        "fwd_points": None,
        "delta": 0.0,
        "delta_pct": 0.0,
        "gamma": 0.0,
        "dv01": 0.0,
        "rho": 0.0,
        "theta_1d": 0.0,
        "cva": 0.0,
        "dva": 0.0,
        "mtm_ajustado": None,
        "flags": [],
        "error": None,
    }

    # ── validaciones de entrada ──────────────────────────────────────
    flags: list[str] = []
    fatal = False

    if N <= 0:
        flags.append("Nocional no positivo")
        fatal = True
    if K <= 0:
        flags.append("Precio forward pactado inválido")
        fatal = True
    if St <= 0:
        flags.append("Spot de valorización inválido")
        fatal = True
    if S0 <= 0:
        flags.append("Falta el tipo de cambio al inicio: la descomposición spot/puntos no es confiable")
    if days_to_mat < 0:
        flags.append("Contrato vencido a la fecha de valorización")
        fatal = True
    elif days_to_mat == 0:
        flags.append("Vence hoy")

    if fatal:
        result["flags"] = flags
        result["error"] = "Excluido de los totales: " + ", ".join(flags)
        return result

    try:
        fwd_curve, disc_curve = _prepare_curves(market, contract, config)
    except LookupError as exc:
        result["flags"] = flags
        result["error"] = str(exc)
        return result

    if fwd_curve.is_outside(days_to_mat):
        flags.append(
            f"Forward extrapolado ({config.extrap_method.lower()}): plazo {days_to_mat}d "
            f"fuera de [{int(fwd_curve.min_tenor)}, {int(fwd_curve.max_tenor)}]"
        )
    if disc_curve.is_outside(days_to_mat):
        flags.append(
            f"Descuento extrapolado: plazo {days_to_mat}d "
            f"fuera de [{int(disc_curve.min_tenor)}, {int(disc_curve.max_tenor)}]"
        )

    F = fwd_curve.value(days_to_mat)
    r = disc_curve.zero_rate(days_to_mat)
    df = disc_curve.factor(days_to_mat, year_fraction)

    if F <= 0:
        result["flags"] = flags
        result["error"] = "Forward de mercado no positivo: revisa la curva."
        return result
    if 0 < abs(r) < 0.5:
        flags.append("Tasa de descuento muy baja: verifica si está en % o en fracción")
    if r > 60 or r < -10:
        flags.append("Tasa de descuento fuera de rango razonable")

    mtm = eps * (K - F) * N * df
    spot_component = eps * (S0 - St) * N * df if S0 > 0 else 0.0

    # Los puntos forward se reportan como el residuo de los valores **ya
    # redondeados**: si se redondeara la diferencia sin redondear, la
    # descomposición del reporte podía no sumar el total por un peso.
    mtm_r = round(mtm, 2)
    spot_component_r = round(spot_component, 2)
    fwd_points_r = round(mtm_r - spot_component_r, 2)

    result.update(
        {
            "fwd_mkt": round(F, 6),
            "disc_rate": round(r, 6),
            "disc_factor": round(df, 10),
            "mtm": mtm_r,
            "spot_component": spot_component_r,
            "fwd_points": fwd_points_r,
            "mtm_ajustado": mtm_r,
        }
    )

    # ── griegas ──────────────────────────────────────────────────────
    if config.calc_greeks:
        # Delta: la curva de outrights se desplaza 1:1 con el spot manteniendo
        # constantes los puntos forward. Se calcula por bump y revaluación para
        # que sea consistente con el resto del motor.
        f_up = fwd_curve.shifted(additive=1.0).value(days_to_mat)
        mtm_spot_up = eps * (K - f_up) * N * df
        delta = mtm_spot_up - mtm

        bump_pct = St * 0.01
        f_up_pct = fwd_curve.shifted(additive=bump_pct).value(days_to_mat)
        delta_pct = eps * (K - f_up_pct) * N * df - mtm

        disc_up = disc_curve.shifted_bp(1.0)
        df_up = disc_up.factor(days_to_mat, year_fraction)
        dv01 = eps * (K - F) * N * df_up - mtm

        # Theta: un día de paso del tiempo con curvas congeladas.
        theta = _theta_one_day(contract, market, config, fwd_curve, disc_curve, mtm)

        result.update(
            {
                "delta": round(delta, 2),
                "delta_pct": round(delta_pct, 2),
                "gamma": 0.0,  # el payoff es lineal en el forward: gamma exacta = 0
                "dv01": round(dv01, 2),
                "rho": round(dv01, 2),  # alias retrocompatible
                "theta_1d": round(theta, 2),
            }
        )

    result["flags"] = flags

    checks = [F, r, df, mtm, spot_component, fwd_points_r]
    if any((not isinstance(v, (int, float))) or math.isnan(v) or math.isinf(v) for v in checks):
        result["error"] = "Resultado no numérico: revisa curvas y parámetros."

    return result


def _theta_one_day(contract, market, config, fwd_curve, disc_curve, mtm_base) -> float:
    """Variación del MtM por un día de paso del tiempo, curvas constantes."""
    cal = get_calendar(config.calendar)
    next_day = market.valuation_date + timedelta(days=1)
    mat_date = cal.adjust(contract.maturity_date, config.business_days)
    d = (mat_date - next_day).days
    if d < 0:
        return 0.0
    yf = day_count_fraction(next_day, mat_date, config.day_count)
    F = fwd_curve.value(d)
    df = disc_curve.factor(d, yf)
    eps = contract.sign
    mtm_next = eps * (float(contract.fwd_price) - F) * float(contract.notional) * df
    return mtm_next - mtm_base


# ──────────────────────────────────────────────────────────────────────
# Cartera
# ──────────────────────────────────────────────────────────────────────

def price_portfolio(
    contracts: list[Contract],
    market: MarketData,
    config: PricingConfig | None = None,
) -> dict:
    """
    Valoriza una cartera completa.

    El CVA/DVA se calcula por contraparte (conjunto de neteo) y luego se asigna
    a cada operación por su contribución a la exposición esperada del conjunto.
    """
    config = config or PricingConfig()
    config.validate()

    lines = [price_contract(c, market, config) for c in contracts]
    valid_idx = [i for i, l in enumerate(lines) if not l["error"]]

    if config.calc_cva and valid_idx:
        _apply_cva(contracts, lines, valid_idx, market, config)

    valid = [lines[i] for i in valid_idx]

    totals = {
        "total_mtm": round(sum(l["mtm"] for l in valid), 2),
        "total_mtm_ajustado": round(sum(l["mtm_ajustado"] for l in valid), 2),
        "total_spot": round(sum(l["spot_component"] for l in valid), 2),
        "total_fwdpoints": round(sum(l["fwd_points"] for l in valid), 2),
        "total_notional": round(sum(l["notional"] for l in valid), 2),
        "total_delta": round(sum(l["delta"] for l in valid), 2),
        "total_dv01": round(sum(l["dv01"] for l in valid), 2),
        "total_theta": round(sum(l["theta_1d"] for l in valid), 2),
        "total_cva": round(sum(l["cva"] for l in valid), 2),
        "total_dva": round(sum(l["dva"] for l in valid), 2),
    }

    by_cp: dict[str, dict] = {}
    for l in valid:
        cp = by_cp.setdefault(
            l["counterparty"] or "(sin contraparte)",
            {"mtm": 0.0, "notional": 0.0, "cva": 0.0, "dva": 0.0, "n": 0},
        )
        cp["mtm"] += l["mtm"]
        cp["notional"] += l["notional"]
        cp["cva"] += l["cva"]
        cp["dva"] += l["dva"]
        cp["n"] += 1
    for cp in by_cp.values():
        for k in ("mtm", "notional", "cva", "dva"):
            cp[k] = round(cp[k], 2)

    diagnostics = {
        "valued": len(valid),
        "failed": len(lines) - len(valid),
        "with_warnings": len([l for l in valid if l["flags"]]),
        "extrapolated": len([l for l in valid if any("xtrapol" in f for f in l["flags"])]),
    }

    return {
        "valuation_date": market.valuation_date.isoformat(),
        "label": market.label,
        "spot": market.spot,
        "config": _config_to_dict(config),
        "lines": lines,
        "totals": totals,
        "por_contraparte": by_cp,
        "diagnostics": diagnostics,
    }


def _apply_cva(contracts, lines, valid_idx, market, config) -> None:
    """Calcula CVA/DVA por contraparte y lo escribe en las líneas."""
    cal = get_calendar(config.calendar)
    groups: dict[str, list] = {}
    for i in valid_idx:
        c = contracts[i]
        groups.setdefault(c.counterparty or "(sin contraparte)", []).append((i, c))

    for cp_name, items in groups.items():
        trades = []
        for i, c in items:
            line = lines[i]
            mat_date = cal.adjust(c.maturity_date, config.business_days)
            days = (mat_date - market.valuation_date).days
            t_years = max(days / 365.0, 0.0)
            fwd_mkt = line["fwd_mkt"]
            df = line["disc_factor"]
            trades.append(
                {
                    "sign": c.sign,
                    "strike": float(c.fwd_price),
                    "notional": float(c.notional),
                    "t_years": t_years,
                    "forward_fn": (lambda f: (lambda _t: f))(fwd_mkt),
                    "discount_fn": (lambda d: (lambda _t: d))(df),
                    "key": i,
                }
            )

        res = cva_dva_netting_set(trades, config.credit, netting=config.netting)
        for i, _c in items:
            alloc = res["por_operacion"].get(i, {"cva": 0.0, "dva": 0.0})
            lines[i]["cva"] = alloc["cva"]
            lines[i]["dva"] = alloc["dva"]
            lines[i]["mtm_ajustado"] = round(
                lines[i]["mtm"] - alloc["cva"] + alloc["dva"], 2
            )
            lines[i]["netting_set"] = cp_name


def _config_to_dict(config: PricingConfig) -> dict:
    d = {
        "day_count": config.day_count,
        "interp_method": config.interp_method,
        "extrap_method": config.extrap_method,
        "business_days": config.business_days,
        "calendar": config.calendar,
        "compounding": config.compounding,
        "calc_greeks": config.calc_greeks,
        "calc_cva": config.calc_cva,
        "netting": config.netting,
    }
    if config.calc_cva:
        d["credit"] = {
            "spread_bp": config.credit.spread_bp,
            "recovery": config.credit.recovery,
            "own_spread_bp": config.credit.own_spread_bp,
            "fx_vol": config.credit.fx_vol,
        }
    return d


# ──────────────────────────────────────────────────────────────────────
# Escenarios
# ──────────────────────────────────────────────────────────────────────

def sensitivity_matrix(
    contracts: list[Contract],
    market: MarketData,
    config: PricingConfig | None = None,
    *,
    shock_max: float = 5.0,
    n_points: int = 5,
    full_revaluation: bool = True,
) -> dict:
    """
    Matriz de MtM ante desplazamientos del spot y de la curva forward.

    Ambos ejes están en porcentaje. El desplazamiento de spot arrastra a la
    curva de outrights en la misma magnitud absoluta (los puntos forward no
    cambian con el nivel del spot); el desplazamiento de curva se aplica
    después, en forma multiplicativa, y representa un cambio en el diferencial
    de tasas.

    Con `full_revaluation=True` cada celda es una revalorización completa de la
    cartera. Con False se usa la aproximación de primer orden por delta, que es
    exacta para un producto lineal salvo por el efecto del descuento.
    """
    config = config or PricingConfig()
    if n_points < 3 or n_points % 2 == 0:
        n_points = 5

    half = (n_points - 1) // 2
    step = shock_max / half
    shifts = [round(-shock_max + i * step, 4) for i in range(n_points)]
    shifts = [int(s) if float(s).is_integer() else s for s in shifts]

    base_spot = float(market.spot)
    base = price_portfolio(contracts, market, config)
    base_mtm = base["totals"]["total_mtm"]
    base_delta = base["totals"]["total_delta"]

    matrix = []
    for s_pct in shifts:
        spot_val = base_spot * (1.0 + s_pct / 100.0)
        delta_spot = spot_val - base_spot
        row = {"spot_pct": s_pct, "spot_value": round(spot_val, 4), "cells": []}

        for c_pct in shifts:
            if full_revaluation:
                curves = {}
                for name, curve in market.curves.items():
                    if name.upper().startswith("FWD"):
                        curves[name] = curve.shifted(
                            additive=delta_spot, multiplicative=c_pct / 100.0
                        )
                    else:
                        curves[name] = curve
                sim = MarketData(
                    valuation_date=market.valuation_date,
                    spot=spot_val,
                    curves=curves,
                    label=market.label,
                )
                res = price_portfolio(contracts, sim, config)
                t = res["totals"]
                cell = {
                    "curve_pct": c_pct,
                    "mtm": t["total_mtm"],
                    "spot_component": t["total_spot"],
                    "fwd_points": t["total_fwdpoints"],
                }
            else:
                approx = base_mtm + base_delta * delta_spot
                cell = {
                    "curve_pct": c_pct,
                    "mtm": round(approx, 2),
                    "spot_component": None,
                    "fwd_points": None,
                }
            row["cells"].append(cell)
        matrix.append(row)

    all_mtm = [c["mtm"] for r in matrix for c in r["cells"]]
    matrix.reverse()  # spot más alto arriba

    return {
        "base_mtm": base_mtm,
        "spot_shifts": list(reversed(shifts)),
        "curve_shifts": shifts,
        "matrix": matrix,
        "min_mtm": min(all_mtm) if all_mtm else 0.0,
        "max_mtm": max(all_mtm) if all_mtm else 0.0,
        "full_revaluation": full_revaluation,
    }

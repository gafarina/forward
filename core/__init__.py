"""
Motor cuantitativo de valorización de forwards FX.

Deliberadamente independiente de Django: el mismo código alimenta la
aplicación web, el generador del libro Excel y los tests de reconciliación.
"""

from .calendars import Calendar, get_calendar, chile_holidays, easter_sunday
from .credit import CreditProfile, cva_dva_netting_set, expected_exposure
from .curves import Curve, DiscountCurve, discount_factor
from .daycount import day_count_fraction, day_count_days, DAY_COUNT_CONVENTIONS
from .valuation import (
    Contract,
    MarketData,
    PricingConfig,
    price_contract,
    price_portfolio,
    sensitivity_matrix,
)

__all__ = [
    "Calendar", "get_calendar", "chile_holidays", "easter_sunday",
    "CreditProfile", "cva_dva_netting_set", "expected_exposure",
    "Curve", "DiscountCurve", "discount_factor",
    "day_count_fraction", "day_count_days", "DAY_COUNT_CONVENTIONS",
    "Contract", "MarketData", "PricingConfig",
    "price_contract", "price_portfolio", "sensitivity_matrix",
]

__version__ = "2.0.0"

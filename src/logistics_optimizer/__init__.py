"""Группировка заказов в общие рейсы и расчёт стоимости доставки."""

from .config import Settings, SettingsError
from .excel import DataError, OrdersTable, load_orders, load_tariffs
from .geo import CityIndex, load_cities
from .grouping import AnalysisCancelled, optimize
from .models import AnalysisResult, Group, Method, Order, OrderResult, Summary
from .pricing import DirectRate, Tariffs

__version__ = "2.0.0"

__all__ = [
    "AnalysisCancelled",
    "AnalysisResult",
    "CityIndex",
    "DataError",
    "DirectRate",
    "Group",
    "Method",
    "Order",
    "OrderResult",
    "OrdersTable",
    "Settings",
    "SettingsError",
    "Summary",
    "Tariffs",
    "load_cities",
    "load_orders",
    "load_tariffs",
    "optimize",
]

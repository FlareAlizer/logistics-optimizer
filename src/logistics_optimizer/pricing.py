"""Тарифы и стоимость доставки: паллетная, прямая машина, Москва, общий рейс с наценкой."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .config import Settings
from .models import NO_TRUCKS, Order, TruckCombo
from .trucks import cheapest_combo


@dataclass(frozen=True, slots=True)
class DirectRate:
    """Цена рейса до города. inf значит, что машина этого типа туда не ездит."""

    price_10t: float = math.inf
    price_20t: float = math.inf


@dataclass(frozen=True, slots=True)
class Tariffs:
    """Тарифы по ключу города (см. models.city_key)."""

    direct: Mapping[str, DirectRate] = field(default_factory=dict)
    pallet: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GroupCost:
    cost: float
    trucks: TruckCombo
    base_cost: float = math.inf
    markup: float = 1.0
    markup_reason: str = ""


class CostCalculator:
    """Считает стоимости для одного запуска. Кэш живёт вместе с объектом."""

    def __init__(self, tariffs: Tariffs, settings: Settings) -> None:
        self.tariffs = tariffs
        self.settings = settings
        self._combos: dict[tuple[str, float, float], tuple[float, TruckCombo]] = {}

    def pallet_cost(self, city: str, pallets: float) -> float:
        """Паллетная доставка: тариф города плюс базовая ставка за каждую паллету."""
        if pallets <= 0:
            return 0.0
        rate = self.tariffs.pallet.get(city)
        if rate is None or math.isnan(rate):
            return math.inf
        return (rate + self.settings.costs.pallet_base_rate) * pallets

    def moscow_cost(self, pallets: float) -> float:
        return self.settings.costs.moscow_rate_per_pallet * pallets

    def direct_cost(self, city: str, pallets: float, weight: float) -> tuple[float, TruckCombo]:
        """Отдельные машины до города под весь груз."""
        key = (city, pallets, weight)
        cached = self._combos.get(key)
        if cached is None:
            rate = self.tariffs.direct.get(city)
            if rate is None:
                cached = (math.inf, NO_TRUCKS)
            else:
                cached = cheapest_combo(
                    rate.price_10t, rate.price_20t, pallets, weight, self.settings
                )
            self._combos[key] = cached
        return cached

    def group_cost(self, orders: Sequence[Order]) -> GroupCost:
        """Стоимость общего рейса для набора заказов."""
        return self.trip_cost(
            list(dict.fromkeys(order.city_key for order in orders)),
            sum(order.pallets for order in orders),
            sum(order.weight for order in orders),
            recipients=len({order.recipient for order in orders if order.recipient is not None}),
            dates=len({order.date for order in orders if order.date is not None}),
        )

    def trip_cost(
        self, cities: Sequence[str], pallets: float, weight: float, *, recipients: int, dates: int
    ) -> GroupCost:
        """Рейс стоит как машина до самого дорогого города, плюс наценка за сложность."""
        base, trucks = 0.0, NO_TRUCKS
        for city in cities:
            cost, combo = self.direct_cost(city, pallets, weight)
            if cost != math.inf and cost > base:
                base, trucks = cost, combo
        if base <= 0:
            return GroupCost(math.inf, trucks)

        costs = self.settings.costs
        if len(cities) == 3 or recipients == 3 or dates == 3:
            markup, reason = costs.markup_three_entities, "три города, получателя или даты"
        elif len(cities) > 1:
            markup, reason = costs.markup_diff_cities, "разные города"
        elif dates > 1:
            markup, reason = costs.markup_same_city_diff_dates, "один город, разные даты"
        else:
            markup, reason = 1.0, ""
        return GroupCost(base * markup, trucks, base, markup, reason)

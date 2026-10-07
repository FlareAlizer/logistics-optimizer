"""Подбор машин под груз: самый дешёвый набор и набор с наименьшим числом машин."""

from __future__ import annotations

import math

from .config import Settings, Truck
from .models import NO_TRUCKS, TruckCombo


def trucks_needed(pallets: float, weight: float, truck: Truck) -> int:
    """Сколько машин одного типа закрывают груз и по паллетам, и по весу."""
    return max(_units(pallets, truck.pallets), _units(weight, truck.kg))


def _units(amount: float, capacity: float) -> int:
    # Округление гасит шум суммирования: 9750.000000001 кг не должны требовать второй машины.
    return math.ceil(round(amount / capacity, 9)) if amount > 0 else 0


def _price(count: int, price: float) -> float:
    # Ноль машин ничего не стоит, даже если тарифа на этот тип нет (0 * inf дало бы nan).
    return count * price if count else 0.0


def cheapest_combo(
    price_10t: float, price_20t: float, pallets: float, weight: float, settings: Settings
) -> tuple[float, TruckCombo]:
    """Самый дешёвый набор машин. Цена inf значит, что тарифа на этот тип нет."""
    if pallets <= 0 and weight <= 0:
        return 0.0, NO_TRUCKS
    small, big = settings.truck_10t, settings.truck_20t
    best_cost, best = math.inf, NO_TRUCKS
    for n_20t in range(trucks_needed(pallets, weight, big) + 2):
        rest_pallets = max(0.0, pallets - n_20t * big.pallets)
        rest_weight = max(0.0, weight - n_20t * big.kg)
        n_10t = trucks_needed(rest_pallets, rest_weight, small)
        cost = _price(n_20t, price_20t) + _price(n_10t, price_10t)
        if cost < best_cost:
            best_cost, best = cost, TruckCombo(n_10t, n_20t)
    return best_cost, best


def fewest_trucks(pallets: float, weight: float, settings: Settings) -> TruckCombo:
    """Набор с наименьшим числом машин, без оглядки на цену."""
    pallets = max(0.0, _number(pallets))
    weight = max(0.0, _number(weight))
    if pallets <= 0 and weight <= 0:
        return NO_TRUCKS
    small, big = settings.truck_10t, settings.truck_20t
    combo = _search_fewest(
        pallets,
        weight,
        settings,
        _units(pallets, big.pallets) + 1,
        _units(pallets, small.pallets) + 1,
    )
    if combo is None:
        # Груз тяжёлый при малом числе паллет: границы поиска считаем по весу.
        combo = _search_fewest(
            pallets,
            weight,
            settings,
            trucks_needed(pallets, weight, big) + 1,
            trucks_needed(pallets, weight, small) + 1,
        )
    return combo or TruckCombo(n_10t=1)


def _search_fewest(
    pallets: float, weight: float, settings: Settings, max_20t: int, max_10t: int
) -> TruckCombo | None:
    small, big = settings.truck_10t, settings.truck_20t
    best: TruckCombo | None = None
    for n_20t in range(max_20t + 1):
        for n_10t in range(max_10t + 1):
            if n_10t == 0 and n_20t == 0:
                continue
            fits_pallets = n_10t * small.pallets + n_20t * big.pallets >= pallets
            fits_weight = n_10t * small.kg + n_20t * big.kg >= weight
            if fits_pallets and fits_weight and (best is None or n_10t + n_20t < best.total):
                best = TruckCombo(n_10t, n_20t)
    return best


def _number(value: float) -> float:
    return 0.0 if value is None or math.isnan(value) else float(value)

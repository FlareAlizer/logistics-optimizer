"""Контрольные числа. Сняты со старой версии программы на этих же синтетических наборах:
новый расчёт должен давать те же группы и ту же стоимость."""

import pytest

from logistics_optimizer import Method, Settings, optimize
from logistics_optimizer.config import Costs, GroupingRules, Truck
from logistics_optimizer.excel import orders_from_frame, tariffs_from_frames
from logistics_optimizer.sample import generate_sample

ALTERNATIVE = Settings(
    truck_10t=Truck(10, 8000),
    truck_20t=Truck(30, 18000),
    rules=GroupingRules(
        max_cities=2,
        max_day_diff=1,
        radius_km=520,
        max_recipients=2,
        simple_group_savings_threshold=0.2,
    ),
    costs=Costs(
        markup_three_entities=1.4,
        markup_same_city_diff_dates=1.05,
        markup_diff_cities=1.2,
        moscow_rate_per_pallet=1750,
        pallet_base_rate=900,
    ),
)


def solve(seed: int, n_orders: int, days: int, n_cities: int, settings: Settings, cities):
    data = generate_sample(seed=seed, n_orders=n_orders, days=days, n_cities=n_cities)
    orders = orders_from_frame(data.orders).orders
    return optimize(orders, tariffs_from_frames(data.direct, data.pallet), settings, cities)


def test_default_rules_match_reference(cities):
    result = solve(3, 260, 9, 18, Settings(), cities)
    summary = result.summary()
    assert summary.plan_cost == pytest.approx(4_523_850.00)
    assert summary.groups == 55
    assert {method: count for method, (count, _) in summary.by_method.items()} == {
        Method.PALLET: 96,
        Method.DIRECT: 2,
        Method.DIRECT_GROUP: 147,
        Method.MOSCOW: 10,
        Method.MOSCOW_GROUP: 5,
    }


def test_alternative_rules_match_reference(cities):
    summary = solve(17, 260, 9, 18, ALTERNATIVE, cities).summary()
    assert summary.plan_cost == pytest.approx(4_822_650.00)
    assert summary.groups == 56


def test_many_cities_and_long_window_match_reference(cities):
    wide = Settings(
        rules=GroupingRules(max_cities=4, max_day_diff=3, radius_km=800, max_recipients=4)
    )
    summary = solve(18, 220, 9, 14, wide, cities).summary()
    assert summary.plan_cost == pytest.approx(3_438_225.00)
    assert summary.groups == 42

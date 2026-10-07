import pytest

from helpers import TARIFFS, make_orders
from logistics_optimizer import AnalysisCancelled, Method, Settings, optimize
from logistics_optimizer.config import GroupingRules, Truck

PALLET = 3800  # Казань: 2500 по тарифу + 1300 базовая ставка


def methods(result):
    return [res.method for res in result.results]


def costs(result):
    return [res.cost for res in result.results]


def test_small_order_goes_by_pallets(run):
    result = run(("А", "Казань", 0, 2))
    res = result.results[0]
    assert res.method is Method.PALLET
    assert res.cost == 2 * PALLET
    assert res.group == 0
    assert result.groups == []


def test_big_order_takes_a_truck(run):
    res = run(("А", "Казань", 0, 12)).results[0]
    assert res.method is Method.DIRECT
    assert res.cost == 40000
    assert res.transport == "1 x 10т"
    assert res.pallet_cost == 12 * PALLET


def test_same_recipient_same_day_shares_a_truck(run):
    result = run(("А", "Казань", 0, 11), ("А", "Казань", 0, 11))
    assert methods(result) == [Method.DIRECT_GROUP] * 2
    assert costs(result) == [25000, 25000]  # одна 20т за 50 000 пополам
    group = result.groups[0]
    assert group.indices == (0, 1)
    assert group.markup == 1.0
    assert group.pallet_cost == 22 * PALLET
    assert group.savings == 80000 - 50000  # по отдельности это две машины 10т


def test_cost_is_split_by_pallets(run):
    result = run(("А", "Казань", 0, 4), ("А", "Казань", 0, 8))
    assert costs(result) == pytest.approx([40000 / 3, 80000 / 3])


def test_same_city_next_day_is_grouped_with_markup(run):
    result = run(("А", "Казань", 0, 8), ("Б", "Казань", 1, 8))
    assert methods(result) == [Method.DIRECT_GROUP] * 2
    group = result.groups[0]
    assert group.cost == pytest.approx(50000 * 1.15)
    assert group.markup_reason == "один город, разные даты"
    assert group.separate_cost == 2 * 8 * PALLET


def test_markup_can_make_a_group_pointless(run):
    # 12 паллет: машина 40 000 * 1.15 = 46 000 против 45 600 паллетами.
    result = run(("А", "Казань", 0, 6), ("Б", "Казань", 1, 6))
    assert methods(result) == [Method.PALLET] * 2


def test_neighbouring_cities_are_grouped(run):
    result = run(("А", "Казань", 0, 8), ("Б", "Зеленодольск", 1, 8))
    assert methods(result) == [Method.DIRECT_GROUP] * 2
    assert result.groups[0].base_cost == 50000  # дороже из двух городов
    assert result.groups[0].markup_reason == "разные города"


def test_far_cities_are_not_grouped(run):
    result = run(("А", "Казань", 0, 8), ("Б", "Екатеринбург", 1, 8))
    assert result.groups == []
    assert methods(result) == [Method.PALLET] * 2


def test_radius_setting_is_applied(run):
    rows = (("А", "Казань", 0, 10), ("Б", "Екатеринбург", 1, 12))
    assert run(*rows).groups == []
    wide = Settings(rules=GroupingRules(radius_km=1000))
    group = run(*rows, settings=wide).groups[0]
    assert group.cost == pytest.approx(85000 * 1.15)  # 20т до Екатеринбурга плюс наценка


def test_one_unloading_point_per_day(run):
    # Разные получатели в один день в общий рейс не идут.
    result = run(("А", "Казань", 0, 8), ("Б", "Казань", 0, 8))
    assert result.groups == []


def test_dates_must_be_consecutive(run):
    result = run(("А", "Казань", 0, 8), ("Б", "Казань", 2, 8))
    assert result.groups == []


def test_three_days_in_a_row_get_the_bigger_markup(run):
    result = run(("А", "Казань", 0, 8), ("Б", "Казань", 1, 8), ("В", "Казань", 2, 8))
    assert len(result.groups) == 1
    assert result.groups[0].cost == pytest.approx(50000 * 1.25)
    assert result.groups[0].indices == (0, 1, 2)


def test_day_window_setting_is_applied(run):
    narrow = Settings(rules=GroupingRules(max_day_diff=1))
    result = run(
        ("А", "Казань", 0, 8), ("Б", "Казань", 1, 8), ("В", "Казань", 2, 8), settings=narrow
    )
    assert [len(group.indices) for group in result.groups] == [2]


def test_moscow_uses_fixed_rate(run):
    result = run(("М", "Москва", 0, 3), ("М", "Москва", 0, 5), ("Н", "Москва", 0, 4))
    assert methods(result) == [Method.MOSCOW_GROUP, Method.MOSCOW_GROUP, Method.MOSCOW]
    assert costs(result) == [3900, 6500, 5200]
    assert result.results[0].transport == "1 x 10т"
    assert result.results[0].group == result.results[1].group == 1


def test_moscow_never_joins_other_cities(run):
    result = run(("М", "Москва", 0, 8), ("А", "Казань", 1, 8))
    assert methods(result) == [Method.MOSCOW, Method.PALLET]


def test_missing_tariffs_are_reported(run):
    result = run(("А", "Безпрямого", 0, 2), ("Б", "Нигде", 0, 2), ("В", "Казань", 0, 2))
    assert methods(result) == [Method.ERROR_NO_DIRECT, Method.ERROR_NO_TARIFF, Method.PALLET]
    assert costs(result)[:2] == [0.0, 0.0]
    assert result.summary().errors == 2
    assert any("Безпрямого" in warning for warning in result.warnings)
    assert any("Нигде" in warning for warning in result.warnings)


def test_order_without_date_is_still_priced(run):
    # Раньше такой заказ оставался с нулевой стоимостью и пустым методом.
    result = run((None, "Казань", 0, 12), ("А", "Казань", None, 2), ("А", "Москва", None, 2))
    assert methods(result) == [Method.DIRECT, Method.PALLET, Method.MOSCOW]
    assert costs(result) == [40000, 2 * PALLET, 2600]
    assert any("без получателя или даты: 3" in warning for warning in result.warnings)


def test_city_without_coordinates_is_not_consolidated(run):
    result = run(("А", "Верхнереченск", 0, 8), ("Б", "Верхнереченск", 1, 8))
    assert result.groups == []
    assert any("Верхнереченск" in warning for warning in result.warnings)


def test_city_with_only_20t_price(run):
    res = run(("А", "Только20", 0, 20)).results[0]
    assert (res.method, res.cost, res.transport) == (Method.DIRECT, 50000, "1 x 20т")


def test_pallet_orders_with_same_depot_are_shown_together(run):
    result = run(
        ("А", "Казань", 0, 2, 400.0, 5, "Склад 1"),
        ("Б", "Казань", 3, 3, 600.0, 5, "Склад 1"),
        ("В", "Казань", 6, 2, 400.0, 5, "Склад 2"),
    )
    assert methods(result) == [Method.PALLET] * 3
    assert [res.group for res in result.results] == [1, 1, 0]
    assert costs(result) == [2 * PALLET, 3 * PALLET, 2 * PALLET]
    assert result.groups[0].method is Method.PALLET


def test_settings_do_not_leak_between_runs(run):
    rows = (("А", "Казань", 0, 11), ("А", "Казань", 0, 11))
    assert run(*rows).results[0].transport == "1 x 20т"
    small = Settings(truck_20t=Truck(pallets=20, kg=19500))
    assert run(*rows, settings=small).results[0].transport == "2 x 10т"
    assert run(*rows).results[0].transport == "1 x 20т"


def test_summary(run):
    result = run(
        ("А", "Казань", 0, 11),
        ("А", "Казань", 0, 11),
        ("Б", "Казань", 5, 12),
        ("В", "Казань", 9, 2),
        ("М", "Москва", 0, 3),
    )
    summary = result.summary()
    assert summary.orders == 5
    assert summary.groups == 1
    assert summary.trips == 2
    assert (summary.trucks_10t, summary.trucks_20t) == (1, 1)
    assert summary.plan_cost == 50000 + 40000 + 2 * PALLET + 3900
    assert summary.separate_cost == 80000 + 40000 + 2 * PALLET + 3900
    assert summary.savings == 30000
    assert summary.by_method[Method.DIRECT_GROUP] == (2, 50000)


def test_progress_and_cancel(cities):
    orders = make_orders(*[(f"П{i}", "Казань", i % 3, 8) for i in range(12)])
    seen = []
    optimize(orders, TARIFFS, cities=cities, progress=lambda p, m: seen.append(p))
    assert seen[0] == 5
    assert seen[-1] == 100
    assert seen == sorted(seen)
    with pytest.raises(AnalysisCancelled):
        optimize(orders, TARIFFS, cities=cities, should_cancel=lambda: True)


def test_result_is_repeatable(cities):
    orders = make_orders(*[(f"П{i % 7}", "Казань", i % 5, 3 + i % 9) for i in range(60)])
    first = optimize(orders, TARIFFS, cities=cities)
    second = optimize(orders, TARIFFS, cities=cities)
    assert [(r.method, r.group, r.cost) for r in first.results] == [
        (r.method, r.group, r.cost) for r in second.results
    ]
    assert sum(len(group.indices) for group in first.groups) == sum(
        1 for res in first.results if res.group
    )

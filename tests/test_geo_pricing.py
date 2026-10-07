import math

import pytest

from helpers import TARIFFS, make_orders
from logistics_optimizer import Settings
from logistics_optimizer.config import Costs
from logistics_optimizer.geo import CityIndex, geodesic_km
from logistics_optimizer.models import TruckCombo, city_key
from logistics_optimizer.pricing import CostCalculator


def test_known_distance(cities):
    # Между точками из справочника по геодезической около 637 км.
    assert cities.distance_km("Москва", "Санкт-Петербург") == pytest.approx(637.0, abs=0.5)
    assert cities.distance_km("Казань", "Зеленодольск") == pytest.approx(38, abs=2)


def test_distance_is_symmetric_and_zero_for_same_city(cities):
    assert cities.distance_km("Казань", "Самара") == cities.distance_km("самара", "КАЗАНЬ")
    assert cities.distance_km("Казань", "Казань") == 0.0


def test_unknown_city_is_unreachable(cities):
    assert cities.get("Верхнереченск") is None
    assert cities.distance_km("Казань", "Верхнереченск") == math.inf
    assert cities.missing(["Казань", "Верхнереченск"]) == ["Верхнереченск"]


def test_geodesic_on_equator_matches_ellipsoid():
    assert geodesic_km((0.0, 0.0), (0.0, 1.0)) == pytest.approx(111.3195, abs=1e-3)


def test_extra_cities_override_builtin(tmp_path, cities):
    extra = tmp_path / "cities.csv"
    extra.write_text("city,lat,lon\nВерхнереченск,55.0,50.0\nбитая строка\n", encoding="utf-8")
    from logistics_optimizer.geo import load_cities

    index = load_cities(extra)
    assert index.get("ВЕРХНЕРЕЧЕНСК") == (55.0, 50.0)
    assert len(index) == len(cities) + 1


def test_city_key_normalisation():
    assert city_key("  орёл ") == "ОРЕЛ"
    assert city_key("Нижний   Новгород") == "НИЖНИЙ НОВГОРОД"
    assert "орел" in CityIndex({"Орёл": (52.97, 36.08)})


def test_pallet_cost():
    calc = CostCalculator(TARIFFS, Settings())
    assert calc.pallet_cost("КАЗАНЬ", 2) == 2 * (2500 + 1300)
    assert calc.pallet_cost("КАЗАНЬ", 0) == 0.0
    assert calc.pallet_cost("НЕТ ТАКОГО", 2) == math.inf


def test_direct_and_moscow_cost():
    calc = CostCalculator(TARIFFS, Settings())
    assert calc.direct_cost("КАЗАНЬ", 12, 2000) == (40000, TruckCombo(1, 0))
    assert calc.direct_cost("НЕТ ТАКОГО", 12, 2000) == (math.inf, TruckCombo())
    assert calc.moscow_cost(7) == 9100


def test_group_cost_markups():
    calc = CostCalculator(TARIFFS, Settings())
    same = calc.group_cost(make_orders(("А", "Казань", 0, 8), ("А", "Казань", 0, 8)))
    assert (same.cost, same.markup) == (50000, 1.0)

    two_dates = calc.group_cost(make_orders(("А", "Казань", 0, 8), ("Б", "Казань", 1, 8)))
    assert two_dates.cost == pytest.approx(50000 * 1.15)
    assert two_dates.markup_reason == "один город, разные даты"

    two_cities = calc.group_cost(make_orders(("А", "Казань", 0, 8), ("Б", "Зеленодольск", 1, 8)))
    assert two_cities.base_cost == 50000  # берётся самый дорогой город
    assert two_cities.markup_reason == "разные города"

    three = calc.group_cost(
        make_orders(("А", "Казань", 0, 8), ("Б", "Казань", 1, 8), ("В", "Казань", 2, 8))
    )
    assert three.cost == pytest.approx(50000 * 1.25)


def test_group_cost_respects_settings():
    calc = CostCalculator(TARIFFS, Settings(costs=Costs(markup_diff_cities=1.5)))
    trip = calc.group_cost(make_orders(("А", "Казань", 0, 8), ("Б", "Зеленодольск", 1, 8)))
    assert trip.cost == 75000


def test_group_without_any_tariff_is_impossible():
    calc = CostCalculator(TARIFFS, Settings())
    assert calc.group_cost(make_orders(("А", "Нигде", 0, 8))).cost == math.inf

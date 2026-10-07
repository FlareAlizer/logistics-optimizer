import math

import pytest

from logistics_optimizer import Settings
from logistics_optimizer.config import Truck
from logistics_optimizer.models import TruckCombo
from logistics_optimizer.trucks import cheapest_combo, fewest_trucks, trucks_needed

SETTINGS = Settings()


@pytest.mark.parametrize(
    ("pallets", "weight", "expected_cost", "expected"),
    [
        (5, 1000, 40000, TruckCombo(1, 0)),
        (12, 9750, 40000, TruckCombo(1, 0)),  # ровно в край по паллетам и весу
        (13, 2000, 50000, TruckCombo(0, 1)),
        (33, 19500, 50000, TruckCombo(0, 1)),
        (34, 5000, 90000, TruckCombo(1, 1)),
        (46, 5000, 100000, TruckCombo(0, 2)),
        (5, 12000, 50000, TruckCombo(0, 1)),  # паллет мало, но вес не входит в 10т
        (70, 5000, 140000, TruckCombo(1, 2)),
    ],
)
def test_cheapest_combo(pallets, weight, expected_cost, expected):
    cost, combo = cheapest_combo(40000, 50000, pallets, weight, SETTINGS)
    assert cost == expected_cost
    assert combo == expected


def test_cheapest_combo_prefers_small_trucks_when_they_are_cheap():
    cost, combo = cheapest_combo(10000, 50000, 30, 3000, SETTINGS)
    assert (cost, combo) == (30000, TruckCombo(3, 0))


def test_empty_load_costs_nothing():
    assert cheapest_combo(40000, 50000, 0, 0, SETTINGS) == (0.0, TruckCombo())


def test_only_20t_price_is_usable():
    # В старой версии 0 * inf давало nan, и город с одной ценой считался городом без тарифа.
    cost, combo = cheapest_combo(math.inf, 50000, 20, 4000, SETTINGS)
    assert (cost, combo) == (50000, TruckCombo(0, 1))


def test_only_10t_price_is_usable():
    cost, combo = cheapest_combo(40000, math.inf, 20, 4000, SETTINGS)
    assert (cost, combo) == (80000, TruckCombo(2, 0))


def test_no_prices_means_no_trip():
    cost, combo = cheapest_combo(math.inf, math.inf, 20, 4000, SETTINGS)
    assert cost == math.inf
    assert combo == TruckCombo()


def test_float_noise_does_not_add_a_truck():
    weight = sum([3250.1, 3249.9, 3250.0])  # 9750 с точностью до ошибки округления
    assert trucks_needed(1, weight + 1e-9, Truck(12, 9750.0)) == 1


@pytest.mark.parametrize(
    ("pallets", "weight", "expected"),
    [
        (0, 0, TruckCombo()),
        (10, 1000, TruckCombo(1, 0)),
        (20, 1000, TruckCombo(0, 1)),
        (40, 1000, TruckCombo(1, 1)),
        (66, 1000, TruckCombo(0, 2)),
        (5, 15000, TruckCombo(0, 1)),
    ],
)
def test_fewest_trucks(pallets, weight, expected):
    assert fewest_trucks(pallets, weight, SETTINGS) == expected


def test_fewest_trucks_for_heavy_load_with_few_pallets():
    # Старый поиск ограничивал число машин паллетами и для такого груза сдавался на «1 x 10т».
    combo = fewest_trucks(2, 120000, SETTINGS)
    assert combo.n_10t * 9750 + combo.n_20t * 19500 >= 120000
    assert combo.total == 7


def test_combo_text():
    assert str(TruckCombo(1, 2)) == "1 x 10т + 2 x 20т"
    assert str(TruckCombo(0, 1)) == "1 x 20т"
    assert str(TruckCombo()) == "НЕТ ПРЯМОГО ТАРИФА"

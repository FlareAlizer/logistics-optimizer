import json

import pandas as pd
import pytest

from helpers import TARIFFS, make_orders
from logistics_optimizer import Settings, SettingsError, optimize
from logistics_optimizer.cli import main
from logistics_optimizer.config import Costs, GroupingRules, Truck
from logistics_optimizer.report import export_xlsx, groups_frame, orders_frame
from logistics_optimizer.sample import generate_sample


def test_defaults_match_the_business_rules():
    settings = Settings()
    assert (settings.truck_10t, settings.truck_20t) == (Truck(12, 9750.0), Truck(33, 19500.0))
    assert settings.rules == GroupingRules(3, 2, 350.0, 3, 0.35)
    assert settings.costs == Costs(1.25, 1.15, 1.15, 1300.0, 1300.0)


def test_settings_round_trip(tmp_path):
    settings = Settings(
        truck_10t=Truck(10, 8000.0),
        rules=GroupingRules(max_cities=2, radius_km=500.0),
        costs=Costs(moscow_rate_per_pallet=1500.0),
    )
    path = tmp_path / "nested" / "settings.json"
    settings.save(path)
    assert Settings.load(path) == settings


def test_partial_file_keeps_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"rules": {"radius_km": "420"}}), encoding="utf-8")
    settings = Settings.load(path)
    assert settings.rules.radius_km == 420.0
    assert settings.rules.max_cities == 3
    assert settings.truck_20t.pallets == 33


@pytest.mark.parametrize(
    "bad",
    [
        {"truck_10t": {"pallets": 0}},
        {"rules": {"max_day_diff": -1}},
        {"rules": {"simple_group_savings_threshold": 35}},
        {"costs": {"markup_diff_cities": 0}},
        {"costs": {"pallet_base_rate": "дорого"}},
        {"rules": [1, 2]},
    ],
)
def test_bad_settings_are_rejected(bad):
    with pytest.raises(SettingsError):
        Settings.from_dict(bad)


def test_broken_settings_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{не json", encoding="utf-8")
    with pytest.raises(SettingsError, match="JSON"):
        Settings.load(path)
    with pytest.raises(SettingsError, match="прочитать"):
        Settings.load(tmp_path / "missing.json")


@pytest.fixture
def result(cities):
    orders = make_orders(
        ("А", "Казань", 0, 11),
        ("А", "Казань", 0, 11),
        ("Б", "Казань", 5, 2),
        ("М", "Москва", 0, 3),
        ("Н", "Нигде", 0, 3),
    )
    return optimize(orders, TARIFFS, cities=cities)


def test_orders_frame_keeps_legacy_columns(result):
    frame = orders_frame(result)
    assert list(frame.columns[:14]) == [
        "Грузополучатель",
        "Дата П.П.С.",
        "Дата отгрузки",
        "Паллеты",
        "Вес, кг",
        "Город",
        "Группа",
        "Стоимость",
        "Паллетная стоимость",
        "Метод доставки",
        "Транспорт",
        "Адрес доставки",
        "Адрес тр. отдела",
        "Номер заказа",
    ]
    assert frame["Метод доставки"].tolist() == [
        "ПРЯМАЯ ГРУППА",
        "ПРЯМАЯ ГРУППА",
        "ПАЛЛЕТНАЯ",
        "ПРЯМАЯ МСК",
        "ОШИБКА: Нет одного из тарифов",
    ]
    assert frame["Стоимость"].tolist()[:4] == [25000, 25000, 7600, 3900]
    assert pd.isna(frame["Стоимость"].iloc[4])
    assert pd.isna(frame["Паллетная стоимость"].iloc[3])  # для Москвы паллетной доставки нет
    assert frame["Паллетная стоимость"].iloc[0] == 11 * 3800  # своя, а не сумма по группе


def test_groups_frame(result):
    frame = groups_frame(result)
    assert len(frame) == 1
    row = frame.iloc[0]
    assert (row["Группа"], row["Заказов"], row["Транспорт"]) == (1, 2, "1 x 20т")
    assert (row["Стоимость"], row["Экономия"]) == (50000, 30000)


def test_export_writes_three_sheets(result, tmp_path):
    path = export_xlsx(result, tmp_path / "out")
    assert path.name == "out.xlsx"
    book = pd.read_excel(path, sheet_name=None)
    assert list(book) == ["Заказы", "Группы", "Сводка"]
    assert len(book["Заказы"]) == 5
    summary = dict(zip(book["Сводка"]["Показатель"], book["Сводка"]["Значение"], strict=True))
    assert summary["Заказов без расчёта"] == 1
    assert summary["Стоимость по плану"] == 50000 + 7600 + 3900


def test_cli_end_to_end(tmp_path, capsys):
    orders_path, tariffs_path = generate_sample(seed=3, n_orders=80, days=6).save(tmp_path)
    output = tmp_path / "result.xlsx"
    code = main([str(orders_path), "--tariffs", str(tariffs_path), "-o", str(output), "--quiet"])
    printed = capsys.readouterr().out
    assert code == 0
    assert output.exists()
    assert "Заказов: 80" in printed
    assert "Экономия" in printed
    assert len(pd.read_excel(output, sheet_name="Заказы")) == 80


def test_cli_reports_problems_without_traceback(tmp_path, capsys):
    code = main([str(tmp_path / "нет.xlsx")])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.err.startswith("Ошибка:")
    assert "Traceback" not in captured.err

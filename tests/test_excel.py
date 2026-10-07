import math
from datetime import date, datetime

import pandas as pd
import pytest

from logistics_optimizer import DataError, load_orders, load_tariffs
from logistics_optimizer.columns import ColumnMappingError, guess_columns, resolve_columns
from logistics_optimizer.excel import orders_from_frame, parse_date, tariffs_from_frames

COLUMNS = [
    "ГРУЗОПОЛУЧАТЕЛЬ",
    "ДАТА ДОСТАВКИ",
    "ЗАКАЗАНО ПАЛЛЕТ",
    "ЗАКАЗАНО КГ",
    "ЗАКАЗ ДАТА",
    "ГОРОД",
]


def frame(**overrides) -> pd.DataFrame:
    data = {
        "Грузополучатель": ["ООО Ромашка", "ТД Кедр", None],
        "Дата доставки": ["05.09.2025", "06.09.2025", "07.09.2025"],
        "Заказано ПАЛЛЕТ": [4, "2,5", 1],
        "Заказано КГ": [800.5, "1 200", None],
        "Заказ НОМЕР": [500001, 500002.0, "A-3"],
        "Заказ ДАТА": [datetime(2025, 9, 1), "Заказ от 02.09.2025 10:15:00", 45000],
        "ГОРОД": [" Казань ", "Самара", "Тула"],
    }
    data.update(overrides)
    return pd.DataFrame(data)


def test_guess_columns_follows_alias_priority():
    found = guess_columns(COLUMNS)
    assert found["city"] == "ГОРОД"
    assert found["ownership_date"] == "ЗАКАЗ ДАТА"
    assert found["shipment_date"] == "ДАТА ДОСТАВКИ"
    assert found["order_num"] is None


def test_shipment_date_replaces_missing_ownership_date():
    mapping = resolve_columns(["ГОРОД", "ЗАКАЗАНО ПАЛЛЕТ", "ЗАКАЗАНО КГ", "ДАТА ОТГРУЗКИ"])
    assert mapping.ownership_date == mapping.shipment_date == "ДАТА ОТГРУЗКИ"


def test_missing_columns_are_listed():
    with pytest.raises(ColumnMappingError) as error:
        resolve_columns(["НАСЕЛЁННЫЙ ПУНКТ", "МЕСТ", "ЗАКАЗАНО КГ", "ДАТА"])
    assert error.value.missing == ["city", "pallets", "ownership_date"]
    assert "город" in str(error.value)


def test_manual_override_wins():
    columns = ["НАСЕЛЁННЫЙ ПУНКТ", "МЕСТ", "ЗАКАЗАНО КГ", "ДАТА", "ГОРОД"]
    mapping = resolve_columns(
        columns, {"city": "НАСЕЛЁННЫЙ ПУНКТ", "pallets": "МЕСТ", "ownership_date": "ДАТА"}
    )
    assert (mapping.city, mapping.pallets, mapping.ownership_date) == (
        "НАСЕЛЁННЫЙ ПУНКТ",
        "МЕСТ",
        "ДАТА",
    )


def test_orders_are_cleaned():
    table = orders_from_frame(frame())
    first, second, third = table.orders
    assert (first.city, first.city_key) == ("Казань", "КАЗАНЬ")
    assert first.date == date(2025, 9, 1)
    assert first.shipment_date == date(2025, 9, 5)
    assert first.order_num == "500001"
    assert second.pallets == 2.5  # запятая вместо точки
    assert second.weight == 1200.0  # пробел между разрядами
    assert second.date == date(2025, 9, 2)  # дата вытащена из текста
    assert second.order_num == "500002"
    assert third.recipient is None
    assert third.weight == 0.0
    assert third.date is None  # число в колонке даты датой не считается
    assert [order.index for order in table.orders] == [0, 1, 2]


def test_rows_without_city_or_with_negative_pallets_are_skipped():
    table = orders_from_frame(
        frame(**{"ГОРОД": ["Казань", None, "Тула"], "Заказано ПАЛЛЕТ": [4, 2, -1]})
    )
    assert [order.city for order in table.orders] == ["Казань"]
    assert table.skipped_rows == 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("31.12.2025", date(2025, 12, 31)),
        ("1.2.2025", date(2025, 2, 1)),
        ("2025-03-04", date(2025, 3, 4)),
        ("Заказ клиента 00012 от 07.08.2025 9:15:00", date(2025, 8, 7)),
        (pd.Timestamp("2025-05-06 13:00"), date(2025, 5, 6)),
        (date(2025, 1, 2), date(2025, 1, 2)),
        ("32.13.2025", None),
        ("нет", None),
        (float("nan"), None),
        (pd.NaT, None),
        (12345, None),
    ],
)
def test_parse_date(value, expected):
    assert parse_date(value) == expected


def test_header_row_is_found_below_a_title(tmp_path):
    path = tmp_path / "orders.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([["Отчёт за сентябрь"], [None]]).to_excel(
            writer, sheet_name="Заказы", index=False, header=False
        )
        frame().to_excel(writer, sheet_name="Заказы", index=False, startrow=3)
    table = load_orders(path)
    assert len(table.orders) == 3
    assert table.sheet == "Заказы"


def test_orders_sheet_is_found_among_others(tmp_path):
    path = tmp_path / "book.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"Город": ["Казань"], "10Т": [1], "20Т": [2]}).to_excel(
            writer, sheet_name="Прямая", index=False
        )
        frame().to_excel(writer, sheet_name="Данные", index=False)
    assert load_orders(path).sheet == "Данные"


def test_unknown_columns_raise_mapping_error(tmp_path):
    path = tmp_path / "odd.xlsx"
    pd.DataFrame({"Куда": ["Казань"], "Мест": [1]}).to_excel(path, index=False)
    with pytest.raises(ColumnMappingError) as error:
        load_orders(path)
    assert error.value.available == ["КУДА", "МЕСТ"]
    table = load_orders(
        path,
        overrides={
            "city": "КУДА",
            "pallets": "МЕСТ",
            "weight_kg": "МЕСТ",
            "ownership_date": "МЕСТ",
        },
    )
    assert table.orders[0].city == "Казань"


def test_file_errors_are_readable(tmp_path):
    with pytest.raises(DataError, match="не найден"):
        load_orders(tmp_path / "missing.xlsx")
    with pytest.raises(DataError, match=r"\.xls"):
        load_orders(tmp_path / "old.xls")
    broken = tmp_path / "broken.xlsx"
    broken.write_text("это не эксель", encoding="utf-8")
    with pytest.raises(DataError, match="не открывается"):
        load_orders(broken)


def test_tariffs_first_row_wins_and_empty_price_means_no_tariff():
    direct = pd.DataFrame(
        {
            "Сеть РЦ": ["а", "б", "в"],
            "Город": ["Казань ", "КАЗАНЬ", "Орёл"],
            "10Т": [40000, 1, None],
            "20T": [50000, 2, "60000"],  # латинская T в заголовке тоже подходит
        }
    )
    pallet = pd.DataFrame(
        {
            "Город грузополучателя": ["Казань", "Орел", "Тула"],
            "Цена доставки за 1 паллету": [2500, None, 3000.5],
        }
    )
    tariffs = tariffs_from_frames(direct, pallet)
    assert tariffs.direct["КАЗАНЬ"].price_10t == 40000
    assert tariffs.direct["ОРЕЛ"].price_10t == math.inf
    assert tariffs.direct["ОРЕЛ"].price_20t == 60000
    assert tariffs.pallet == {"КАЗАНЬ": 2500, "ТУЛА": 3000.5}


def test_tariff_sheets_are_detected(tmp_path):
    path = tmp_path / "tariffs.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"Заметки": ["черновик"]}).to_excel(writer, sheet_name="Лист1", index=False)
        pd.DataFrame(
            {"Город грузополучателя": ["Казань"], "Цена доставки за 1 паллету": [2500]}
        ).to_excel(writer, sheet_name="П", index=False)
        pd.DataFrame({"Город": ["Казань"], "10Т": [40000], "20Т": [50000]}).to_excel(
            writer, sheet_name="Д", index=False
        )
    tariffs = load_tariffs(path)
    assert list(tariffs.direct) == ["КАЗАНЬ"]
    assert tariffs.pallet == {"КАЗАНЬ": 2500}


def test_missing_tariff_sheet_is_explained(tmp_path):
    path = tmp_path / "orders_only.xlsx"
    frame().to_excel(path, index=False)
    with pytest.raises(DataError, match="прямыми тарифами"):
        load_tariffs(path)

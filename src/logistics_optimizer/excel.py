"""Чтение заказов и тарифов из Excel."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .columns import (
    ColumnMapping,
    ColumnMappingError,
    known_headers,
    normalize_header,
    resolve_columns,
)
from .models import Order, city_key
from .pricing import DirectRate, Tariffs

HEADER_SEARCH_ROWS = 20
PALLET_PRICE = "ЦЕНА ДОСТАВКИ ЗА 1 ПАЛЛЕТУ"
_PALLET_CITY = ("ГОРОД ГРУЗОПОЛУЧАТЕЛЯ", "ГОРОД")
_DIRECT_CITY = ("ГОРОД", "ГОРОД ГРУЗОПОЛУЧАТЕЛЯ")
_PRICE_10T = ("10Т", "10T")  # кириллическая и латинская буква
_PRICE_20T = ("20Т", "20T")

_DATE_DMY = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)")
_DATE_YMD = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")


class DataError(Exception):
    """Файл не удалось прочитать или в нём нет нужных данных. Текст можно показывать как есть."""


@dataclass(frozen=True, slots=True)
class OrdersTable:
    orders: list[Order]
    mapping: ColumnMapping
    columns: list[str]
    sheet: str
    skipped_rows: int = 0


def open_workbook(path: Path | str) -> pd.ExcelFile:
    path = Path(path)
    if path.suffix.lower() == ".xls":
        raise DataError(f"{path.name}: старый формат .xls. Пересохраните файл как .xlsx.")
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        raise DataError(f"{path.name}: нужен файл Excel (.xlsx).")
    try:
        return pd.ExcelFile(path, engine="openpyxl")
    except FileNotFoundError as exc:
        raise DataError(f"Файл {path.name} не найден.") from exc
    except PermissionError as exc:
        raise DataError(f"Нет доступа к {path.name}. Возможно, файл открыт в Excel.") from exc
    except Exception as exc:
        raise DataError(f"{path.name} не открывается как книга Excel.") from exc


def read_sheet(book: pd.ExcelFile, sheet: str) -> pd.DataFrame:
    """Лист с найденной строкой заголовков: колонки в верхнем регистре, пустое убрано."""
    raw = book.parse(sheet, header=None)
    if raw.empty:
        return pd.DataFrame()
    known = known_headers() | {PALLET_PRICE, *_PALLET_CITY, *_PRICE_10T, *_PRICE_20T}
    header_row, best_hits = 0, 0
    for row in range(min(HEADER_SEARCH_ROWS, len(raw))):
        hits = sum(1 for value in raw.iloc[row] if normalize_header(value) in known)
        if hits > best_hits:
            header_row, best_hits = row, hits
    frame = raw.iloc[header_row + 1 :].copy()
    frame.columns = _unique([normalize_header(value) for value in raw.iloc[header_row]])
    frame = frame.dropna(how="all")
    return frame.loc[:, frame.notna().any()].reset_index(drop=True)


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for name in names:
        count = seen.get(name, 0)
        seen[name] = count + 1
        result.append(name if count == 0 else f"{name}.{count}")
    return result


def load_orders(
    path: Path | str,
    *,
    sheet: str | None = None,
    overrides: Mapping[str, str | None] | None = None,
) -> OrdersTable:
    """Читает заказы. Без указания листа берёт первый, где находятся обязательные колонки."""
    with open_workbook(path) as book:
        sheets = [sheet] if sheet else list(book.sheet_names)
        if not sheets:
            raise DataError("В книге нет листов.")
        first_error: ColumnMappingError | None = None
        first_sheet = sheets[0]
        for name in sheets:
            if name not in book.sheet_names:
                raise DataError(f"В книге нет листа «{name}».")
            frame = read_sheet(book, name)
            try:
                return orders_from_frame(frame, overrides=overrides, sheet=name)
            except ColumnMappingError as exc:
                if first_error is None:
                    first_error, first_sheet = exc, name
        assert first_error is not None
        first_error.sheet = first_sheet
        raise first_error


def orders_from_frame(
    frame: pd.DataFrame,
    *,
    overrides: Mapping[str, str | None] | None = None,
    sheet: str = "",
) -> OrdersTable:
    """Превращает таблицу в список заказов: чистит города, числа и даты."""
    frame = frame.copy()
    frame.columns = _unique([normalize_header(name) for name in frame.columns])
    columns = list(frame.columns)
    mapping = resolve_columns(columns, overrides)

    def column(name: str | None) -> list[object]:
        return frame[name].tolist() if name else [None] * len(frame)

    cities = [_text(value) for value in column(mapping.city)]
    pallets = _numbers(frame[mapping.pallets])
    weights = _numbers(frame[mapping.weight_kg])
    dates = [parse_date(value) for value in column(mapping.ownership_date)]
    shipments = [parse_date(value) for value in column(mapping.shipment_date)]
    recipients = column(mapping.recipient)
    numbers = column(mapping.order_num)
    addresses = column(mapping.delivery_address)
    depots = column(mapping.transport_address)

    orders: list[Order] = []
    for row, city in enumerate(cities):
        if not city or pallets[row] < 0:
            continue
        orders.append(
            Order(
                index=len(orders),
                city=city,
                pallets=pallets[row],
                weight=weights[row],
                recipient=_text(recipients[row]) or None,
                date=dates[row],
                shipment_date=shipments[row],
                order_num=_text(numbers[row]),
                delivery_address=_text(addresses[row]),
                transport_address=_text(depots[row]) or None,
            )
        )
    return OrdersTable(orders, mapping, columns, sheet, skipped_rows=len(frame) - len(orders))


def load_tariffs(
    path: Path | str, *, direct_sheet: str | None = None, pallet_sheet: str | None = None
) -> Tariffs:
    """Читает прямые и паллетные тарифы. Листы ищет по набору колонок."""
    with open_workbook(path) as book:
        frames = {name: read_sheet(book, name) for name in book.sheet_names}
    for name in (direct_sheet, pallet_sheet):
        if name and name not in frames:
            raise DataError(f"В книге нет листа «{name}».")

    direct_name = direct_sheet or next((n for n, f in frames.items() if _is_direct(f)), None)
    pallet_name = pallet_sheet or next((n for n, f in frames.items() if _is_pallet(f)), None)
    if direct_name is None:
        raise DataError("Не нашёлся лист с прямыми тарифами: нужны колонки «Город», «10Т» и «20Т».")
    if pallet_name is None:
        raise DataError(
            "Не нашёлся лист с паллетными тарифами: нужны колонки "
            "«Город грузополучателя» и «Цена доставки за 1 паллету»."
        )
    return tariffs_from_frames(frames[direct_name], frames[pallet_name])


def tariffs_from_frames(direct: pd.DataFrame, pallet: pd.DataFrame) -> Tariffs:
    direct = direct.rename(columns=normalize_header)
    pallet = pallet.rename(columns=normalize_header)
    if not _is_direct(direct):
        raise DataError("В прямых тарифах нужны колонки «Город», «10Т» и «20Т».")
    if not _is_pallet(pallet):
        raise DataError(
            "В паллетных тарифах нужны колонки «Город грузополучателя» "
            "и «Цена доставки за 1 паллету»."
        )

    direct_rates: dict[str, DirectRate] = {}
    prices_10t = _prices(direct[_first(direct, _PRICE_10T)])
    prices_20t = _prices(direct[_first(direct, _PRICE_20T)])
    for row, city in enumerate(direct[_first(direct, _DIRECT_CITY)].tolist()):
        key = city_key(_text(city))
        if key and key not in direct_rates:  # при повторах действует первая строка
            direct_rates[key] = DirectRate(prices_10t[row], prices_20t[row])

    pallet_rates: dict[str, float] = {}
    prices = _prices(pallet[PALLET_PRICE])
    for row, city in enumerate(pallet[_first(pallet, _PALLET_CITY)].tolist()):
        key = city_key(_text(city))
        if key and key not in pallet_rates:
            pallet_rates[key] = prices[row]
    # Пустая цена за паллету значит «тарифа нет», а не «бесплатно».
    pallet_rates = {key: price for key, price in pallet_rates.items() if price != math.inf}
    return Tariffs(direct_rates, pallet_rates)


def _first(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def _is_direct(frame: pd.DataFrame) -> bool:
    return all(_first(frame, names) for names in (_DIRECT_CITY, _PRICE_10T, _PRICE_20T))


def _is_pallet(frame: pd.DataFrame) -> bool:
    return PALLET_PRICE in frame.columns and _first(frame, _PALLET_CITY) is not None


def _text(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NaT:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _numbers(series: pd.Series) -> list[float]:
    """Числа с запятой и пробелами тоже читаются. Нечисловое становится нулём."""
    cleaned = series.map(
        lambda v: v.replace(" ", "").replace(" ", "").replace(",", ".") if isinstance(v, str) else v
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0).astype(float).tolist()


def _prices(series: pd.Series) -> list[float]:
    """Цены из тарифа. Пустая или нечисловая ячейка значит, что тарифа нет."""
    numbers = pd.to_numeric(series, errors="coerce").astype(float)
    return [math.inf if math.isnan(value) else value for value in numbers.tolist()]


def parse_date(value: object) -> date | None:
    """Дата из ячейки: настоящая дата Excel или текст с датой вида 31.12.2025 внутри."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        if match := _DATE_DMY.search(value):
            day, month, year = map(int, match.groups())
            return date(year, month, day)
        if match := _DATE_YMD.search(value):
            return date(*map(int, match.groups()))
    except ValueError:
        return None
    return None

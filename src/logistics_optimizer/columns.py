"""Сопоставление колонок файла заказов с полями, которые нужны расчёту."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields

# Варианты заголовков в порядке предпочтения. Сравнение без учёта регистра и пробелов по краям.
ALIASES: Mapping[str, tuple[str, ...]] = {
    "order_num": ("ЗАКАЗ НОМЕР", "ЗАКАЗ ПОКУПАТЕЛЯ", "ЗАКАЗ КЛИЕНТА", "НОМЕР ЗАКАЗА"),
    "recipient": ("ГРУЗОПОЛУЧАТЕЛЬ", "ПОЛУЧАТЕЛЬ", "КЛИЕНТ"),
    "city": ("ГОРОД", "CITY", "ПУНКТ НАЗНАЧЕНИЯ"),
    "shipment_date": (
        "ДАТА ОТГРУЗКИ",
        "ДАТА ОТПРАВКИ",
        "ОТГРУЗКА",
        "ДАТА ДОСТАВКИ",
        "DELIVERY DATE",
    ),
    "ownership_date": (
        "ДАТА ПЕРЕХОДА ПРАВА СОБСТВЕННОСТИ",
        "ДАТА ППС",
        "ППС",
        "ЗАКАЗ ДАТА",
        "ДАТА ЗАКАЗА",
    ),
    "pallets": ("ЗАКАЗАНО ПАЛЛЕТ", "ЗАКАЗАНО", "ЗАКАЗ ПАЛЛЕТ", "КОЛ-ВО ПАЛЛЕТ", "PLT"),
    "weight_kg": ("ЗАКАЗАНО КГ", "ЗАКАЗАНО ПРИХОД ВЕС МЕСТ", "ВЕС", "ВЕС КГ", "KG"),
    "transport_address": ("АДРЕС ДОСТАВКИ ТРАНСПОРТНЫЙ ОТДЕЛ", "АДРЕС СКЛАДА"),
    "delivery_address": ("АДРЕС ДОСТАВКИ", "АДРЕС"),
}

TITLES: Mapping[str, str] = {
    "city": "Город назначения",
    "pallets": "Количество паллет",
    "weight_kg": "Вес, кг",
    "ownership_date": "Дата для группировки (ППС или дата заказа)",
    "shipment_date": "Дата отгрузки или доставки",
    "recipient": "Грузополучатель",
    "order_num": "Номер заказа",
    "delivery_address": "Адрес доставки",
    "transport_address": "Адрес транспортного отдела",
}

REQUIRED = ("city", "pallets", "weight_kg", "ownership_date")


def normalize_header(name: object) -> str:
    return str(name).strip().upper()


def known_headers() -> frozenset[str]:
    return frozenset(alias for names in ALIASES.values() for alias in names)


@dataclass(frozen=True, slots=True)
class ColumnMapping:
    """Какая колонка файла отвечает за какое поле. None значит, что колонки нет."""

    city: str
    pallets: str
    weight_kg: str
    ownership_date: str
    shipment_date: str | None = None
    recipient: str | None = None
    order_num: str | None = None
    delivery_address: str | None = None
    transport_address: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {item.name: getattr(self, item.name) for item in fields(self)}


class ColumnMappingError(ValueError):
    """Не хватает обязательных колонок. Интерфейс по этой ошибке спрашивает их у пользователя."""

    def __init__(self, missing: Sequence[str], available: Sequence[str], sheet: str = "") -> None:
        self.missing = list(missing)
        self.available = list(available)
        self.sheet = sheet
        names = ", ".join(TITLES[key].lower() for key in self.missing)
        super().__init__(f"Не удалось найти колонки: {names}.")


def guess_columns(columns: Sequence[str]) -> dict[str, str | None]:
    """Автоматический подбор по списку известных заголовков."""
    present = set(columns)
    return {
        key: next((alias for alias in aliases if alias in present), None)
        for key, aliases in ALIASES.items()
    }


def resolve_columns(
    columns: Sequence[str], overrides: Mapping[str, str | None] | None = None
) -> ColumnMapping:
    """Подбирает колонки, поверх накладывает ручной выбор.

    Если отдельной даты ППС нет, группировка идёт по дате отгрузки.
    """
    found = guess_columns(columns)
    for key, column in (overrides or {}).items():
        if key in found and (column is None or column in columns):
            found[key] = column
    if found["ownership_date"] is None:
        found["ownership_date"] = found["shipment_date"]
    missing = [key for key in REQUIRED if found[key] is None]
    if missing:
        raise ColumnMappingError(missing, columns)
    return ColumnMapping(**found)  # type: ignore[arg-type]

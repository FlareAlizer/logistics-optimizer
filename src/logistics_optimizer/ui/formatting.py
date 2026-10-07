"""Как числа и даты выглядят на экране."""

from __future__ import annotations

import math
from datetime import date

NBSP = " "
DASH = "—"
MONTHS = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


def number(value: float, digits: int = 0) -> str:
    if value is None or not math.isfinite(value):
        return DASH
    return f"{value:,.{digits}f}".replace(",", NBSP).replace(".", ",")


def money(value: float, digits: int = 0) -> str:
    text = number(value, digits)
    return text if text == DASH else f"{text}{NBSP}₽"


def quantity(value: float) -> str:
    """Паллеты: целые без дробной части, дробные с одной цифрой."""
    return number(value, 0 if float(value).is_integer() else 1)


def percent(share: float) -> str:
    return f"{share * 100:.1f}".replace(".", ",") + f"{NBSP}%"


def day(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else DASH


def day_range(days: list[date]) -> str:
    if not days:
        return DASH
    first, last = min(days), max(days)
    if first == last:
        return day(first)
    return f"{first.strftime('%d.%m')}–{last.strftime('%d.%m.%Y')}"


def month_label(value: date) -> str:
    return f"{MONTHS[value.month - 1]} {value.year}"


def plural(count: int, one: str, few: str, many: str) -> str:
    """1 заказ, 2 заказа, 5 заказов."""
    tail = count % 100
    if 11 <= tail <= 14:
        word = many
    elif tail % 10 == 1:
        word = one
    elif 2 <= tail % 10 <= 4:
        word = few
    else:
        word = many
    return f"{number(count)}{NBSP}{word}"

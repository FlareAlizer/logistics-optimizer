"""Данные, которыми обмениваются части программы: заказ, результат по заказу, группа, итог."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

MOSCOW = "МОСКВА"


def city_key(name: object) -> str:
    """Ключ города для сравнения: без лишних пробелов, в верхнем регистре, Ё как Е."""
    return " ".join(str(name).split()).upper().replace("Ё", "Е")


class Method(StrEnum):
    """Способ доставки. Значения совпадают с тем, что пишется в выгрузку."""

    NONE = ""
    DIRECT = "ПРЯМАЯ"
    DIRECT_GROUP = "ПРЯМАЯ ГРУППА"
    MOSCOW = "ПРЯМАЯ МСК"
    MOSCOW_GROUP = "ПРЯМАЯ МСК ГРУППА"
    PALLET = "ПАЛЛЕТНАЯ"
    ERROR_NO_DIRECT = "ОШИБКА: Нет города в прямом тарифе"
    ERROR_NO_TARIFF = "ОШИБКА: Нет одного из тарифов"
    ERROR_NO_COST = "ОШИБКА: РАСЧЕТ НЕВОЗМОЖЕН"

    @property
    def is_error(self) -> bool:
        return self.value.startswith("ОШИБКА")

    @property
    def is_truck_trip(self) -> bool:
        """Отдельная машина по тарифу за рейс."""
        return self in (Method.DIRECT, Method.DIRECT_GROUP)

    @property
    def label(self) -> str:
        return _METHOD_LABELS[self]


_METHOD_LABELS = {
    Method.NONE: "",
    Method.DIRECT: "Прямая",
    Method.DIRECT_GROUP: "Прямая, группа",
    Method.MOSCOW: "Москва",
    Method.MOSCOW_GROUP: "Москва, группа",
    Method.PALLET: "Паллетная",
    Method.ERROR_NO_DIRECT: "Нет прямого тарифа",
    Method.ERROR_NO_TARIFF: "Нет тарифов",
    Method.ERROR_NO_COST: "Расчёт невозможен",
}


@dataclass(frozen=True, slots=True)
class TruckCombo:
    """Сколько машин каждого типа нужно на рейс."""

    n_10t: int = 0
    n_20t: int = 0

    @property
    def total(self) -> int:
        return self.n_10t + self.n_20t

    def __str__(self) -> str:
        parts = []
        if self.n_10t > 0:
            parts.append(f"{self.n_10t} x 10т")
        if self.n_20t > 0:
            parts.append(f"{self.n_20t} x 20т")
        return " + ".join(parts) if parts else "НЕТ ПРЯМОГО ТАРИФА"


NO_TRUCKS = TruckCombo()


@dataclass(frozen=True, slots=True)
class Order:
    """Одна строка файла заказов после чистки."""

    index: int
    city: str
    pallets: float
    weight: float
    recipient: str | None = None
    date: date | None = None  # дата ППС, по ней идёт группировка
    shipment_date: date | None = None
    order_num: str = ""
    delivery_address: str = ""
    transport_address: str | None = None
    city_key: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not self.city_key:
            object.__setattr__(self, "city_key", city_key(self.city))

    @property
    def is_moscow(self) -> bool:
        return self.city_key == MOSCOW


@dataclass(slots=True)
class OrderResult:
    """Что решено по заказу."""

    order: Order
    method: Method = Method.NONE
    group: int = 0
    cost: float = 0.0
    pallet_cost: float = math.inf  # сколько стоила бы паллетная доставка этого заказа
    direct_cost: float = math.inf  # отдельная машина под этот заказ
    separate_cost: float = 0.0  # самый дешёвый способ, если везти заказ отдельно
    trucks: TruckCombo = NO_TRUCKS
    transport: str = ""

    @property
    def is_error(self) -> bool:
        return self.method.is_error


@dataclass(frozen=True, slots=True)
class Group:
    """Несколько заказов, которые едут вместе."""

    id: int
    method: Method
    indices: tuple[int, ...]
    trucks: TruckCombo
    cost: float
    pallet_cost: float
    separate_cost: float
    base_cost: float = 0.0  # стоимость рейса до наценки
    markup: float = 1.0
    markup_reason: str = ""

    @property
    def savings(self) -> float:
        return self.separate_cost - self.cost


@dataclass(frozen=True, slots=True)
class Summary:
    orders: int
    errors: int
    separate_cost: float
    plan_cost: float
    groups: int
    trips: int
    trucks_10t: int
    trucks_20t: int
    by_method: dict[Method, tuple[int, float]]

    @property
    def savings(self) -> float:
        return self.separate_cost - self.plan_cost

    @property
    def savings_share(self) -> float:
        return self.savings / self.separate_cost if self.separate_cost > 0 else 0.0


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    results: list[OrderResult]
    groups: list[Group]
    warnings: list[str]

    def group_by_id(self) -> dict[int, Group]:
        return {group.id: group for group in self.groups}

    def summary(self) -> Summary:
        by_method: dict[Method, tuple[int, float]] = {}
        trucks_10t = trucks_20t = trips = 0
        for res in self.results:
            count, cost = by_method.get(res.method, (0, 0.0))
            by_method[res.method] = (count + 1, cost + res.cost)
            if res.group == 0 and res.method is Method.DIRECT:
                trips += 1
                trucks_10t += res.trucks.n_10t
                trucks_20t += res.trucks.n_20t
        for group in self.groups:
            if group.method is Method.DIRECT_GROUP:
                trips += 1
                trucks_10t += group.trucks.n_10t
                trucks_20t += group.trucks.n_20t
        return Summary(
            orders=len(self.results),
            errors=sum(1 for res in self.results if res.is_error),
            separate_cost=sum(res.separate_cost for res in self.results),
            plan_cost=sum(res.cost for res in self.results),
            groups=len(self.groups),
            trips=trips,
            trucks_10t=trucks_10t,
            trucks_20t=trucks_20t,
            by_method=by_method,
        )

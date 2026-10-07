"""Расчёт целиком: стоимость каждого заказа, группы, назначение способа доставки."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from .config import Settings
from .consolidation import (
    AnalysisCancelled,
    CancelCheck,
    Progress,
    build_pre_groups,
    find_consolidated_groups,
)
from .geo import CityIndex, load_cities
from .models import AnalysisResult, Group, Method, Order, OrderResult, TruckCombo
from .pricing import CostCalculator, GroupCost, Tariffs
from .trucks import fewest_trucks

__all__ = ["AnalysisCancelled", "optimize"]


@dataclass(slots=True)
class _Plan:
    orders: Sequence[Order]
    results: list[OrderResult]
    calc: CostCalculator
    cities: CityIndex
    warnings: list[str] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)

    @property
    def settings(self) -> Settings:
        return self.calc.settings

    def pick(self, indices: Sequence[int]) -> list[Order]:
        return [self.orders[i] for i in indices]


def optimize(
    orders: Sequence[Order],
    tariffs: Tariffs,
    settings: Settings | None = None,
    cities: CityIndex | None = None,
    *,
    progress: Progress | None = None,
    should_cancel: CancelCheck | None = None,
) -> AnalysisResult:
    """Раскладывает заказы по способам доставки и собирает общие рейсы.

    Заказы должны идти по порядку: orders[i].index == i.
    """
    settings = settings or Settings()
    report = progress or (lambda percent, message: None)
    plan = _Plan(
        orders=orders,
        results=[OrderResult(order) for order in orders],
        calc=CostCalculator(tariffs, settings),
        cities=cities or load_cities(),
    )

    report(5, "Считаю стоимость каждого заказа")
    _price_orders(plan)
    ungrouped = set(range(len(orders)))

    report(10, "Собираю московские заказы")
    moscow_groups = _group_moscow(plan, ungrouped)
    for members in moscow_groups:
        ungrouped.difference_update(members)

    report(15, "Объединяю заказы одного получателя")
    simple_groups = _group_same_recipient(plan, ungrouped)
    for members in simple_groups:
        ungrouped.difference_update(members)

    report(25, "Ищу общие рейсы между городами")
    trips = find_consolidated_groups(
        ungrouped,
        orders,
        plan.results,
        plan.calc,
        plan.cities,
        progress=progress,
        should_cancel=should_cancel,
    )
    for members in trips:
        ungrouped.difference_update(members)
        for i in members:
            plan.results[i].method = Method.DIRECT_GROUP

    report(85, "Распределяю стоимость по заказам")
    for members in (*moscow_groups, *simple_groups, *trips):
        _finalize_group(plan, members)
    _assign_remaining(plan, ungrouped)

    report(95, "Проверяю паллетные заказы")
    _group_pallets_by_address(plan, ungrouped)
    _warn_about_coordinates(plan)

    report(100, "Готово")
    return AnalysisResult(plan.results, plan.groups, plan.warnings)


def _price_orders(plan: _Plan) -> None:
    """Считает паллетную и прямую стоимость каждого заказа и отмечает заказы без тарифа."""
    no_direct: dict[str, int] = {}
    no_tariff: dict[str, int] = {}
    for res in plan.results:
        order = res.order
        pallet = plan.calc.pallet_cost(order.city_key, order.pallets)
        direct, _ = plan.calc.direct_cost(order.city_key, order.pallets, order.weight)
        if order.is_moscow:
            res.direct_cost = res.separate_cost = plan.calc.moscow_cost(order.pallets)
        elif direct == math.inf and pallet != math.inf:
            res.method = Method.ERROR_NO_DIRECT
            res.pallet_cost = pallet
            no_direct[order.city] = no_direct.get(order.city, 0) + 1
        elif direct == math.inf:
            res.method = Method.ERROR_NO_TARIFF
            no_tariff[order.city] = no_tariff.get(order.city, 0) + 1
        else:
            res.pallet_cost, res.direct_cost = pallet, direct
            res.separate_cost = min(pallet, direct)
    for city, count in sorted(no_direct.items()):
        plan.warnings.append(f"{city}: нет прямого тарифа, заказов без расчёта: {count}.")
    for city, count in sorted(no_tariff.items()):
        plan.warnings.append(f"{city}: города нет в тарифах, заказов без расчёта: {count}.")


def _group_moscow(plan: _Plan, available: set[int]) -> list[list[int]]:
    """Москва: несколько заказов одного получателя на одну дату едут вместе."""
    buckets: dict[tuple[str, date], list[int]] = {}
    for i in sorted(available):
        order = plan.orders[i]
        if order.is_moscow and order.recipient is not None and order.date is not None:
            buckets.setdefault((order.recipient, order.date), []).append(i)
    groups = [members for _, members in sorted(buckets.items()) if len(members) > 1]
    for members in groups:
        for i in members:
            plan.results[i].method = Method.MOSCOW_GROUP
    return groups


def _group_same_recipient(plan: _Plan, available: set[int]) -> list[list[int]]:
    """Заказы одного получателя на одну дату, где машина заметно дешевле паллет."""
    threshold = plan.settings.rules.simple_group_savings_threshold
    groups = []
    for pre_group in build_pre_groups(available, plan.orders, plan.results, plan.calc):
        if len(pre_group.indices) <= 1 or pre_group.has_error:
            continue
        pallet_sum = pre_group.pallet_sum
        direct, _ = plan.calc.direct_cost(pre_group.city, pre_group.pallets, pre_group.weight)
        if not (direct < pallet_sum and 0 < pallet_sum < math.inf):
            continue
        if (pallet_sum - direct) / pallet_sum >= threshold:
            groups.append(list(pre_group.indices))
            for i in pre_group.indices:
                plan.results[i].method = Method.DIRECT_GROUP
    return groups


def _finalize_group(plan: _Plan, members: Sequence[int]) -> None:
    """Назначает группе номер, машины и делит стоимость рейса между заказами."""
    orders = plan.pick(members)
    method = plan.results[members[0]].method
    if method is Method.MOSCOW_GROUP:
        for i in members:
            plan.results[i].cost = plan.calc.moscow_cost(plan.orders[i].pallets)
        trucks = fewest_trucks(
            sum(order.pallets for order in orders),
            sum(order.weight for order in orders),
            plan.settings,
        )
        _register_group(plan, members, method, trucks)
    else:
        trip = plan.calc.group_cost(orders)
        _split_cost(plan, members, trip.cost)
        _register_group(plan, members, method, trip.trucks, trip)


def _split_cost(plan: _Plan, members: Sequence[int], cost: float) -> None:
    """Делит стоимость пропорционально паллетам, а если их нет, то поровну."""
    total_pallets = sum(plan.orders[i].pallets for i in members)
    for i in members:
        if total_pallets > 0:
            plan.results[i].cost = (cost * plan.orders[i].pallets) / total_pallets
        else:
            plan.results[i].cost = cost / len(members)


def _register_group(
    plan: _Plan,
    members: Sequence[int],
    method: Method,
    trucks: TruckCombo,
    trip: GroupCost | None = None,
) -> None:
    group_id = len(plan.groups) + 1
    for i in members:
        res = plan.results[i]
        res.method = method
        res.group = group_id
        res.trucks = trucks
        res.transport = str(trucks)
    plan.groups.append(
        Group(
            id=group_id,
            method=method,
            indices=tuple(members),
            trucks=trucks,
            cost=sum(plan.results[i].cost for i in members),
            pallet_cost=sum(plan.results[i].pallet_cost for i in members),
            separate_cost=sum(plan.results[i].separate_cost for i in members),
            base_cost=trip.base_cost if trip else 0.0,
            markup=trip.markup if trip else 1.0,
            markup_reason=trip.markup_reason if trip else "",
        )
    )


def _assign_remaining(plan: _Plan, remaining: set[int]) -> None:
    """Решает судьбу заказов, которые не попали в общие рейсы."""
    for pre_group in build_pre_groups(remaining, plan.orders, plan.results, plan.calc):
        members = pre_group.indices
        if any(plan.results[i].method is not Method.NONE for i in members):
            continue
        orders = plan.pick(members)
        if orders[0].is_moscow:
            _assign_moscow(plan, members)
            continue
        pallet_sum = sum(plan.results[i].pallet_cost for i in members)
        trip = plan.calc.group_cost(orders)
        if trip.cost < pallet_sum and trip.cost != math.inf:
            if len(members) == 1:
                _set_single(plan, members[0], Method.DIRECT, trip.cost, trip.trucks)
            else:
                _split_cost(plan, members, trip.cost)
                _register_group(plan, members, Method.DIRECT_GROUP, trip.trucks, trip)
        else:
            for i in members:
                _assign_single(plan, i)

    # Заказ без получателя или даты объединить не с чем, но посчитать его можно.
    loose = [i for i in sorted(remaining) if plan.results[i].method is Method.NONE]
    for i in loose:
        if plan.orders[i].is_moscow:
            _assign_moscow(plan, (i,))
        else:
            _assign_single(plan, i)
    if loose:
        plan.warnings.append(
            f"Заказов без получателя или даты: {len(loose)}. Они посчитаны по отдельности."
        )


def _assign_moscow(plan: _Plan, members: Sequence[int]) -> None:
    orders = plan.pick(members)
    total_pallets = sum(order.pallets for order in orders)
    cost = plan.calc.moscow_cost(total_pallets)
    trucks = fewest_trucks(total_pallets, sum(order.weight for order in orders), plan.settings)
    if len(members) == 1:
        _set_single(plan, members[0], Method.MOSCOW, cost, trucks)
    else:
        _split_cost(plan, members, cost)
        _register_group(plan, members, Method.MOSCOW_GROUP, trucks)


def _assign_single(plan: _Plan, index: int) -> None:
    """Одиночный заказ едет тем способом, который дешевле."""
    res = plan.results[index]
    order = res.order
    _, trucks = plan.calc.direct_cost(order.city_key, order.pallets, order.weight)
    if res.direct_cost < res.pallet_cost and res.direct_cost != math.inf:
        _set_single(plan, index, Method.DIRECT, res.direct_cost, trucks)
    elif res.pallet_cost != math.inf:
        cost = res.pallet_cost if order.pallets > 0 else 0.0
        _set_single(plan, index, Method.PALLET, cost, trucks)
    else:
        res.method = Method.ERROR_NO_COST


def _set_single(plan: _Plan, index: int, method: Method, cost: float, trucks: TruckCombo) -> None:
    res = plan.results[index]
    res.method = method
    res.group = 0
    res.cost = cost
    res.trucks = trucks
    res.transport = str(trucks)


def _group_pallets_by_address(plan: _Plan, remaining: set[int]) -> None:
    """Паллетные заказы с одной датой отгрузки и одним адресом транспортного отдела.

    На стоимость это не влияет: группа нужна, чтобы отгружать их одной машиной.
    """
    buckets: dict[tuple[date, str], list[int]] = {}
    for i in sorted(remaining):
        order = plan.orders[i]
        if plan.results[i].method is not Method.PALLET:
            continue
        if order.shipment_date is None or order.transport_address is None:
            continue
        buckets.setdefault((order.shipment_date, order.transport_address), []).append(i)
    for _, members in sorted(buckets.items()):
        if len(members) > 1:
            orders = plan.pick(members)
            trucks = fewest_trucks(
                sum(order.pallets for order in orders),
                sum(order.weight for order in orders),
                plan.settings,
            )
            _register_group(plan, members, Method.PALLET, trucks)


def _warn_about_coordinates(plan: _Plan) -> None:
    unknown = plan.cities.missing(
        res.order.city for res in plan.results if not res.is_error and not res.order.is_moscow
    )
    if unknown:
        plan.warnings.append(
            "Нет координат, заказы не объединяются с другими городами и датами: "
            + ", ".join(unknown)
            + "."
        )

"""Поиск общих рейсов: заказы разных получателей и дат, которые выгодно везти одной машиной.

Единица объединения здесь не заказ, а «пакет»: все заказы одного получателя на одну дату.
Пакет либо целиком попадает в рейс, либо целиком остаётся.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import combinations, pairwise

from .config import GroupingRules
from .geo import CityIndex
from .models import MOSCOW, Order, OrderResult
from .pricing import CostCalculator

Progress = Callable[[int, str], None]
CancelCheck = Callable[[], bool]


class AnalysisCancelled(Exception):
    """Пользователь остановил расчёт."""


@dataclass(frozen=True, slots=True, eq=False)
class PreGroup:
    """Заказы одного получателя на одну дату."""

    indices: tuple[int, ...]
    recipient: str
    date: date
    city: str  # город первого заказа, по нему считаются расстояния
    cities: tuple[tuple[int, str], ...]  # (номер первой строки, город) без повторов
    pallets: float
    weight: float
    pallet_sum: float
    standalone_cost: float
    has_error: bool


def build_pre_groups(
    indices: Iterable[int],
    orders: Sequence[Order],
    results: Sequence[OrderResult],
    calc: CostCalculator,
) -> list[PreGroup]:
    """Собирает пакеты. Заказы без получателя или даты в пакеты не попадают."""
    buckets: dict[tuple[str, date], list[int]] = {}
    for index in sorted(indices):
        order = orders[index]
        if order.recipient is None or order.date is None:
            continue
        buckets.setdefault((order.recipient, order.date), []).append(index)

    pre_groups = []
    for (recipient, day), members in sorted(buckets.items()):
        first = orders[members[0]]
        pallets = sum(orders[i].pallets for i in members)
        weight = sum(orders[i].weight for i in members)
        pallet_sum = sum(results[i].pallet_cost for i in members)
        direct, _ = calc.direct_cost(first.city_key, pallets, weight)
        standalone = min(pallet_sum, direct) if direct != math.inf else pallet_sum
        cities: dict[str, int] = {}
        for i in members:
            cities.setdefault(orders[i].city_key, i)
        pre_groups.append(
            PreGroup(
                indices=tuple(members),
                recipient=recipient,
                date=day,
                city=first.city_key,
                cities=tuple((i, city) for city, i in cities.items()),
                pallets=pallets,
                weight=weight,
                pallet_sum=pallet_sum,
                standalone_cost=standalone,
                has_error=any(results[i].is_error for i in members),
            )
        )
    return pre_groups


@dataclass(frozen=True, slots=True)
class _Candidate:
    savings: float
    size: int


def find_consolidated_groups(
    available: set[int],
    orders: Sequence[Order],
    results: Sequence[OrderResult],
    calc: CostCalculator,
    cities: CityIndex,
    *,
    progress: Progress | None = None,
    should_cancel: CancelCheck | None = None,
) -> list[list[int]]:
    """Жадно набирает рейсы, пока находятся выгодные и допустимые.

    На каждом круге каждый пакет по очереди становится «зерном» и обрастает соседями.
    Из найденных вариантов берутся самые выгодные непересекающиеся, остальное идёт на новый круг.
    """
    if len(available) < 2:
        return []
    rules = calc.settings.rules
    candidates = {
        i
        for i in available
        if not results[i].is_error
        and orders[i].recipient is not None
        and orders[i].date is not None
        and not orders[i].is_moscow
    }
    total = len(available)
    found: list[list[int]] = []
    iteration = 0
    while len(candidates) >= 2:
        iteration += 1
        if progress:
            done = 25 + int(60 * (1 - len(candidates) / total))
            progress(done, f"Круг {iteration}: ищу рейсы среди {len(candidates)} заказов")
        pre_groups = build_pre_groups(candidates, orders, results, calc)
        if not pre_groups:
            break

        by_date: dict[date, list[tuple[int, PreGroup]]] = {}
        for position, pre_group in enumerate(pre_groups):
            by_date.setdefault(pre_group.date, []).append((position, pre_group))

        profitable: dict[frozenset[int], _Candidate] = {}
        for seed in pre_groups:
            if should_cancel and should_cancel():
                raise AnalysisCancelled
            profitable.update(_grow_from_seed(seed, by_date, calc, cities, rules))
        for pre_group in pre_groups:
            cost = calc.group_cost([orders[i] for i in pre_group.indices]).cost
            if cost < pre_group.standalone_cost:
                profitable[frozenset(pre_group.indices)] = _Candidate(
                    pre_group.standalone_cost - cost, len(pre_group.indices)
                )
        if not profitable:
            break

        owner = {i: pre_group for pre_group in pre_groups for i in pre_group.indices}
        ranked = sorted(
            profitable.items(), key=lambda item: (item[1].savings, item[1].size), reverse=True
        )
        used: set[int] = set()
        for members, _ in ranked:
            if members & used:
                continue
            if is_valid_group(members, orders, results, rules, cities, owner):
                found.append(sorted(members))
                used |= members
        if not used:
            break
        candidates -= used
    return found


def _grow_from_seed(
    seed: PreGroup,
    by_date: dict[date, list[tuple[int, PreGroup]]],
    calc: CostCalculator,
    cities: CityIndex,
    rules: GroupingRules,
) -> dict[frozenset[int], _Candidate]:
    """Добавляет к зерну по одному пакету, каждый раз самый выгодный."""
    if cities.get(seed.city) is None:
        return {}
    nearby: list[tuple[float, int, PreGroup]] = []
    for shift in range(-rules.max_day_diff, rules.max_day_diff + 1):
        for position, pre_group in by_date.get(seed.date + timedelta(days=shift), ()):
            if pre_group is seed:
                continue
            if cities.distance_km(seed.city, pre_group.city) <= rules.radius_km:
                nearby.append((pre_group.standalone_cost, position, pre_group))
    if not nearby:
        return {}
    nearby.sort(key=lambda item: item[:2])
    compatible = [item[2] for item in nearby]

    current = [seed]
    found: dict[frozenset[int], _Candidate] = {}
    while True:
        best_savings, best = -1.0, None
        for pre_group in compatible:
            if pre_group in current:
                continue
            trial = [*current, pre_group]
            days = [item.date for item in trial]
            if (max(days) - min(days)).days > rules.max_day_diff:
                continue
            if len({item.recipient for item in trial}) > rules.max_recipients:
                continue
            ordered = sorted(pair for item in trial for pair in item.cities)
            trial_cities = list(dict.fromkeys(city for _, city in ordered))
            if len(trial_cities) > rules.max_cities:
                continue
            cost = calc.trip_cost(
                trial_cities,
                sum(item.pallets for item in trial),
                sum(item.weight for item in trial),
                recipients=len({item.recipient for item in trial}),
                dates=len(set(days)),
            ).cost
            if cost == math.inf:
                continue
            savings = sum(item.standalone_cost for item in trial) - cost
            if savings > best_savings:
                best_savings, best = savings, pre_group
        if best is None or best_savings <= 0:
            return found
        current.append(best)
        members = frozenset(i for item in current for i in item.indices)
        found[members] = _Candidate(best_savings, len(current))


def is_valid_group(
    members: Iterable[int],
    orders: Sequence[Order],
    results: Sequence[OrderResult],
    rules: GroupingRules,
    cities: CityIndex,
    owner: dict[int, PreGroup] | None = None,
) -> bool:
    """Проверяет рейс по всем правилам сразу."""
    indices = sorted(members)
    if len(indices) <= 1:
        return True
    group = [orders[i] for i in indices]
    if any(results[i].is_error for i in indices):
        return False
    if any(order.date is None for order in group):
        return False

    days = sorted({order.date for order in group})
    if (days[-1] - days[0]).days > rules.max_day_diff:
        return False
    group_cities = list(dict.fromkeys(order.city_key for order in group))
    if MOSCOW in group_cities and len(group_cities) > 1:
        return False
    if len(group_cities) > rules.max_cities:
        return False
    if (
        len({order.recipient for order in group if order.recipient is not None})
        > rules.max_recipients
    ):
        return False

    if len(group_cities) > 1:
        if any(cities.get(city) is None for city in group_cities):
            return False
        distances = [cities.distance_km(a, b) for a, b in combinations(group_cities, 2)]
        # Два города должны быть рядом. Для трёх достаточно одной близкой пары:
        # остальные расстояния уже ограничены радиусом от города-зерна.
        within = [distance <= rules.radius_km for distance in distances]
        if not (all(within) if len(group_cities) == 2 else any(within)):
            return False

    # В один день машина разгружается у одного получателя в одном городе.
    for day in days:
        same_day = [order for order in group if order.date == day]
        if len({order.recipient for order in same_day if order.recipient is not None}) > 1:
            return False
        if len({order.city_key for order in same_day}) > 1:
            return False
    # Даты идут подряд, без пропусков.
    if any((later - earlier).days != 1 for earlier, later in pairwise(days)):
        return False

    if owner:
        chosen = set(indices)
        for i in indices:
            pre_group = owner.get(i)
            if pre_group is not None and not chosen.issuperset(pre_group.indices):
                return False
    return True

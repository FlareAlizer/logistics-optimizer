"""Настройки расчёта: вместимость машин, правила группировки, наценки. Хранятся в JSON."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Self


class SettingsError(ValueError):
    """Настройки заданы так, что считать по ним нельзя."""


@dataclass(frozen=True, slots=True)
class Truck:
    pallets: int
    kg: float


@dataclass(frozen=True, slots=True)
class GroupingRules:
    max_cities: int = 3
    max_day_diff: int = 2
    radius_km: float = 350.0
    max_recipients: int = 3
    # Заказы одного получателя на одну дату объединяются сразу,
    # если прямая машина дешевле паллетной доставки хотя бы на эту долю.
    simple_group_savings_threshold: float = 0.35


@dataclass(frozen=True, slots=True)
class Costs:
    markup_three_entities: float = 1.25
    markup_same_city_diff_dates: float = 1.15
    markup_diff_cities: float = 1.15
    moscow_rate_per_pallet: float = 1300.0
    pallet_base_rate: float = 1300.0


@dataclass(frozen=True, slots=True)
class Settings:
    truck_10t: Truck = field(default_factory=lambda: Truck(pallets=12, kg=9750.0))
    truck_20t: Truck = field(default_factory=lambda: Truck(pallets=33, kg=19500.0))
    rules: GroupingRules = field(default_factory=GroupingRules)
    costs: Costs = field(default_factory=Costs)

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        for name, truck in (("10т", self.truck_10t), ("20т", self.truck_20t)):
            if truck.pallets < 1 or truck.kg <= 0:
                raise SettingsError(f"Вместимость машины {name} должна быть больше нуля.")
        rules = self.rules
        if rules.max_cities < 1 or rules.max_recipients < 1:
            raise SettingsError("В группе должен быть хотя бы один город и один получатель.")
        if rules.max_day_diff < 0 or rules.radius_km < 0:
            raise SettingsError("Разница в днях и радиус не могут быть отрицательными.")
        if not 0 <= rules.simple_group_savings_threshold <= 1:
            raise SettingsError("Порог экономии задаётся долей от 0 до 1.")
        costs = self.costs
        markups = (
            costs.markup_three_entities,
            costs.markup_same_city_diff_dates,
            costs.markup_diff_cities,
        )
        if any(markup <= 0 for markup in markups):
            raise SettingsError("Наценка задаётся множителем больше нуля, например 1.15.")
        if costs.moscow_rate_per_pallet < 0 or costs.pallet_base_rate < 0:
            raise SettingsError("Ставки за паллету не могут быть отрицательными.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Собирает настройки из словаря. Пропущенные поля берутся по умолчанию."""
        default = cls()
        try:
            return cls(
                truck_10t=_merge(default.truck_10t, data.get("truck_10t")),
                truck_20t=_merge(default.truck_20t, data.get("truck_20t")),
                rules=_merge(default.rules, data.get("rules")),
                costs=_merge(default.costs, data.get("costs")),
            )
        except (TypeError, ValueError, AttributeError) as exc:
            if isinstance(exc, SettingsError):
                raise
            raise SettingsError(f"Файл настроек повреждён: {exc}") from exc

    @classmethod
    def load(cls, path: Path | str) -> Self:
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise SettingsError(f"Не удалось прочитать файл настроек {path.name}.") from exc
        except json.JSONDecodeError as exc:
            raise SettingsError(f"Файл настроек {path.name} не похож на JSON.") from exc
        if not isinstance(data, dict):
            raise SettingsError(f"В файле настроек {path.name} ожидается объект JSON.")
        return cls.from_dict(data)

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        path.write_text(text + "\n", encoding="utf-8")


def _merge[T](default: T, patch: object) -> T:
    """Накладывает словарь из файла на значения по умолчанию, приводя типы."""
    if patch is None:
        return default
    if not isinstance(patch, dict):
        raise TypeError("ожидался объект")
    values = {}
    for item in fields(default):  # type: ignore[arg-type]
        current = getattr(default, item.name)
        raw = patch.get(item.name, current)
        values[item.name] = type(current)(raw)
    return type(default)(**values)

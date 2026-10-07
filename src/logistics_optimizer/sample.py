"""Выдуманные заказы и тарифы той же структуры, что рабочие файлы. Для примеров и тестов."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from importlib import resources
from pathlib import Path

import pandas as pd

from .geo import geodesic_km, read_cities

ORDERS_SHEET = "Заказы"
DIRECT_SHEET = "Прямая"
PALLET_SHEET = "Паллетная"

_WAREHOUSE = (55.60, 37.20)  # условный склад, от него считаются выдуманные ставки
_FORMS = ("ООО", "ТД", "АО")
_NAMES = (
    "Ромашка",
    "Берёзка",
    "Лукошко",
    "Самовар",
    "Колосок",
    "Янтарь",
    "Меридиан",
    "Причал",
    "Жаворонок",
    "Кедр",
    "Орбита",
    "Родник",
    "Клевер",
    "Тополь",
    "Гранит",
    "Рябина",
    "Снегирь",
    "Подсолнух",
)
_STREETS = ("Складская", "Промышленная", "Заводская", "Товарная", "Индустриальная", "Тупиковая")
_PALLET_CHOICES = ((1, 2), (2, 4), (4, 8), (8, 12), (12, 24), (24, 33))
_PALLET_WEIGHTS = (30, 26, 22, 12, 8, 2)


@dataclass(frozen=True, slots=True)
class SampleData:
    orders: pd.DataFrame
    direct: pd.DataFrame
    pallet: pd.DataFrame

    def save(self, folder: Path | str) -> tuple[Path, Path]:
        """Пишет orders.xlsx и tariffs.xlsx, возвращает пути."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        orders_path, tariffs_path = folder / "orders.xlsx", folder / "tariffs.xlsx"
        self.orders.to_excel(orders_path, sheet_name=ORDERS_SHEET, index=False)
        with pd.ExcelWriter(tariffs_path) as writer:
            self.direct.to_excel(writer, sheet_name=DIRECT_SHEET, index=False)
            self.pallet.to_excel(writer, sheet_name=PALLET_SHEET, index=False)
        return orders_path, tariffs_path


def generate_sample(
    seed: int = 7,
    n_orders: int = 600,
    days: int = 28,
    n_cities: int = 36,
    start: date = date(2025, 9, 1),
) -> SampleData:
    """Собирает набор данных. Один и тот же seed всегда даёт одни и те же таблицы."""
    rng = random.Random(seed)
    builtin = resources.files("logistics_optimizer") / "data" / "cities.csv"
    with resources.as_file(builtin) as path:
        coords = read_cities(path)
    others = sorted(name for name in coords if name != "Москва")
    cities = ["Москва", *rng.sample(others, min(n_cities, len(others)) - 1)]

    direct_rows, pallet_rows, recipients = [], [], []
    for city in cities:
        km = geodesic_km(_WAREHOUSE, coords[city])
        price_10t = _round_to(12000 + 42 * km, 500)
        price_20t = _round_to(price_10t * rng.uniform(1.15, 1.35), 500)
        pallet_rate = _round_to(price_10t / 12 * rng.uniform(0.55, 0.85), 50)
        if city != "Москва":  # в Москву возят своим транспортом по фиксированной ставке
            direct_rows.append((f"РЦ {city}", city, price_10t, price_20t))
        depots = [f"{city}, ул. {rng.choice(_STREETS)}, {rng.randint(1, 40)}" for _ in range(2)]
        for name in rng.sample(_NAMES, rng.randint(2, 4)):
            recipient = f"{rng.choice(_FORMS)} {name} {city}"
            address = f"г. {city}, ул. {rng.choice(_STREETS)}, д. {rng.randint(1, 120)}"
            recipients.append((recipient, city, address, rng.choice(depots)))
        pallet_rows.append((city, recipients[-1][0], pallet_rate))

    order_rows = []
    number = 500001
    while len(order_rows) < n_orders:
        recipient, city, address, depot = rng.choice(recipients)
        ordered = start + timedelta(days=rng.randrange(days))
        # У части получателей в один день несколько заказов.
        for _ in range(rng.choice((1, 1, 1, 1, 2, 2, 3))):
            low, high = rng.choices(_PALLET_CHOICES, weights=_PALLET_WEIGHTS)[0]
            pallets = rng.randint(low, high)
            per_pallet = rng.uniform(520, 780) if rng.random() < 0.06 else rng.uniform(40, 480)
            delivery = ordered + timedelta(days=rng.randint(3, 10))
            order_rows.append(
                (
                    recipient,
                    delivery.strftime("%d.%m.%Y"),
                    address,
                    pallets,
                    round(pallets * per_pallet, 1),
                    number,
                    pd.Timestamp(ordered),
                    city,
                    depot,
                )
            )
            number += 1
    orders = pd.DataFrame(
        order_rows[:n_orders],
        columns=[
            "Грузополучатель",
            "Дата доставки",
            "Адрес доставки",
            "Заказано ПАЛЛЕТ",
            "Заказано КГ",
            "Заказ НОМЕР",
            "Заказ ДАТА",
            "ГОРОД",
            "Адрес доставки транспортный отдел",
        ],
    )
    direct = pd.DataFrame(direct_rows, columns=["Сеть РЦ", "Город", "10Т", "20Т"])
    pallet = pd.DataFrame(
        pallet_rows,
        columns=["Город грузополучателя", "Грузополучатель", "Цена доставки за 1 паллету"],
    )
    return SampleData(orders, direct, pallet)


def _round_to(value: float, step: int) -> int:
    return int(round(value / step) * step)

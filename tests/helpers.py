"""Общие данные для тестов: выдуманные тарифы и короткая запись заказов."""

from __future__ import annotations

from datetime import date, timedelta

from logistics_optimizer import DirectRate, Order, Tariffs

DAY = date(2025, 9, 1)

# Ставки выдуманы так, чтобы результат легко считался в уме.
TARIFFS = Tariffs(
    direct={
        "КАЗАНЬ": DirectRate(40000, 50000),
        "ЗЕЛЕНОДОЛЬСК": DirectRate(38000, 48000),
        "ЕКАТЕРИНБУРГ": DirectRate(70000, 85000),
        "ВЕРХНЕРЕЧЕНСК": DirectRate(40000, 50000),  # города нет в справочнике координат
        "ТОЛЬКО20": DirectRate(price_20t=50000),
    },
    pallet={
        "КАЗАНЬ": 2500,  # с базовой ставкой 1300 выходит 3800 за паллету
        "ЗЕЛЕНОДОЛЬСК": 2600,
        "ЕКАТЕРИНБУРГ": 4000,
        "ВЕРХНЕРЕЧЕНСК": 2500,
        "ТОЛЬКО20": 2500,
        "МОСКВА": 900,
        "БЕЗПРЯМОГО": 2000,
    },
)


def make_orders(*rows: tuple) -> list[Order]:
    """Строка: (получатель, город, день от начала, паллеты[, вес[, отгрузка, адрес отдела]])."""
    orders = []
    for index, row in enumerate(rows):
        recipient, city, day, pallets, *rest = row
        weight = rest[0] if rest else pallets * 200.0
        shipment = DAY + timedelta(days=rest[1]) if len(rest) > 1 else None
        orders.append(
            Order(
                index=index,
                city=city,
                pallets=pallets,
                weight=weight,
                recipient=recipient,
                date=None if day is None else DAY + timedelta(days=day),
                shipment_date=shipment,
                order_num=str(1000 + index),
                transport_address=rest[2] if len(rest) > 2 else None,
            )
        )
    return orders

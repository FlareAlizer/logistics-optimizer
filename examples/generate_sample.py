"""Пересобирает примеры: orders.xlsx и tariffs.xlsx рядом с этим файлом.

Все получатели, адреса и ставки выдуманы. Названия и координаты городов настоящие.

    python examples/generate_sample.py --orders 600 --seed 7
"""

from __future__ import annotations

import argparse
from pathlib import Path

from logistics_optimizer.sample import generate_sample


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--orders", type=int, default=600, help="сколько заказов")
    parser.add_argument("--days", type=int, default=28, help="на сколько дней их растянуть")
    parser.add_argument("--cities", type=int, default=36, help="сколько городов")
    parser.add_argument("--seed", type=int, default=7, help="зерно генератора")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent, help="папка")
    args = parser.parse_args()

    data = generate_sample(args.seed, args.orders, args.days, args.cities)
    orders_path, tariffs_path = data.save(args.out)
    print(f"{orders_path}: заказов {len(data.orders)}")
    print(f"{tariffs_path}: городов в прямом тарифе {len(data.direct)}")


if __name__ == "__main__":
    main()

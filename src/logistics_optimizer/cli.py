"""Запуск без окна: заказы и тарифы на входе, файл с результатом на выходе."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import Settings, SettingsError
from .excel import DataError, load_orders, load_tariffs
from .geo import load_cities
from .grouping import optimize
from .models import AnalysisResult
from .report import export_xlsx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="logistics-optimizer",
        description="Группирует заказы в общие рейсы и считает стоимость доставки.",
    )
    parser.add_argument("orders", type=Path, help="файл Excel с заказами")
    parser.add_argument(
        "-t",
        "--tariffs",
        type=Path,
        help="файл Excel с тарифами; если не указан, тарифы ищутся в файле заказов",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("result.xlsx"), help="куда сохранить результат"
    )
    parser.add_argument("--sheet", help="лист с заказами, если их несколько")
    parser.add_argument("--settings", type=Path, help="JSON с настройками расчёта")
    parser.add_argument(
        "--cities", type=Path, help="CSV с координатами городов в дополнение к встроенным"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="не печатать ход расчёта")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.load(args.settings) if args.settings else Settings()
        table = load_orders(args.orders, sheet=args.sheet)
        tariffs = load_tariffs(args.tariffs or args.orders)
        if not table.orders:
            raise DataError("В файле заказов нет ни одной строки с городом.")

        def progress(percent: int, message: str) -> None:
            if not args.quiet:
                print(f"[{percent:3d}%] {message}", file=sys.stderr)

        result = optimize(
            table.orders, tariffs, settings, load_cities(args.cities), progress=progress
        )
        output = export_xlsx(result, args.output)
    except (DataError, SettingsError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    print(format_summary(result))
    print(f"\nРезультат: {output}")
    return 0


def format_summary(result: AnalysisResult) -> str:
    summary = result.summary()
    lines = [
        f"Заказов: {summary.orders}, без расчёта: {summary.errors}",
        f"Групп: {summary.groups}, прямых рейсов: {summary.trips} "
        f"(10т: {summary.trucks_10t}, 20т: {summary.trucks_20t})",
        f"По отдельности: {_money(summary.separate_cost)}",
        f"По плану:       {_money(summary.plan_cost)}",
        f"Экономия:       {_money(summary.savings)} ({summary.savings_share:.1%})",
        "",
        "Способ доставки                заказов       стоимость",
    ]
    for method, (count, cost) in sorted(summary.by_method.items(), key=lambda item: -item[1][1]):
        lines.append(f"{method.value or 'без метода':<30} {count:>7} {_money(cost):>15}")
    if result.warnings:
        lines.append("")
        lines.append("Предупреждения:")
        lines.extend(f"  - {warning}" for warning in result.warnings)
    return "\n".join(lines)


def _money(value: float) -> str:
    return f"{value:,.0f} руб.".replace(",", " ")


if __name__ == "__main__":
    raise SystemExit(main())

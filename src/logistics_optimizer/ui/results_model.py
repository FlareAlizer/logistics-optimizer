"""Дерево результатов: группы с заказами внутри и одиночные заказы, плюс отбор строк."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PyQt6.QtCore import QModelIndex, QSortFilterProxyModel, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QStandardItem, QStandardItemModel

from ..models import AnalysisResult, Group, Method, Order, OrderResult
from . import formatting as fmt
from .theme import Palette
from .widgets import METHOD_ROLE

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
GROUP_ROLE = Qt.ItemDataRole.UserRole + 3
ERRORS = "errors"


@dataclass(frozen=True, slots=True)
class Column:
    title: str
    numeric: bool = False
    width: int = 110
    hidden: bool = False
    tip: str = ""


COLUMNS = (
    Column("Группа / получатель", width=270),
    Column("Город", width=170),
    Column("Дата ППС", width=110, tip="Дата, по которой заказы объединяются в рейсы"),
    Column("Отгрузка", width=110),
    Column("Паллет", numeric=True, width=70),
    Column("Вес, кг", numeric=True, width=85),
    Column("Способ", width=140),
    Column("Транспорт", width=130),
    Column("Стоимость", numeric=True, width=110),
    Column("Паллетами", numeric=True, width=110, tip="Сколько стоила бы паллетная доставка"),
    Column("Экономия", numeric=True, width=100, tip="Против доставки каждого заказа отдельно"),
    Column("Заказ №", width=90),
    Column("Адрес доставки", width=260),
    Column("Адрес тр. отдела", width=220, hidden=True),
)
METHOD_COLUMN = 6


@dataclass(frozen=True, slots=True)
class RowFacts:
    """По чему отбирается строка верхнего уровня (группа отбирается целиком)."""

    text: str
    cities: frozenset[str]
    methods: frozenset[Method]
    months: frozenset[str]
    is_group: bool


def month_key(order: Order) -> str | None:
    day = order.date or order.shipment_date
    return f"{day.year:04d}-{day.month:02d}" if day else None


def _facts(orders: Sequence[Order], results: Sequence[OrderResult | None], is_group: bool):
    parts: list[str] = []
    for order in orders:
        parts += [
            order.recipient or "",
            order.city,
            order.order_num,
            fmt.day(order.date),
            fmt.day(order.shipment_date),
            order.delivery_address,
            order.transport_address or "",
        ]
    return RowFacts(
        text=" ".join(parts).lower(),
        cities=frozenset(order.city for order in orders),
        methods=frozenset(res.method for res in results if res is not None),
        months=frozenset(key for order in orders if (key := month_key(order))),
        is_group=is_group,
    )


def _cell(text: str, sort: object = None, numeric: bool = False) -> QStandardItem:
    item = QStandardItem(text)
    item.setEditable(False)
    item.setData(text.lower() if sort is None else sort, SORT_ROLE)
    if numeric:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


def _money_cell(value: float | None) -> QStandardItem:
    if value is None:
        return _cell("", -1.0, numeric=True)
    item = _cell(fmt.money(value), value, numeric=True)
    item.setToolTip(fmt.money(value, 2))
    return item


def _transport(res: OrderResult) -> str:
    return res.transport.replace(" x ", " × ") if res.trucks.total else fmt.DASH


def _order_row(order: Order, res: OrderResult | None, in_group: bool) -> list[QStandardItem]:
    name = _cell(order.recipient or "Без получателя")
    name.setToolTip(order.recipient or "")
    address = _cell(order.delivery_address)
    address.setToolTip(order.delivery_address)
    row = [
        name,
        _cell(order.city),
        _cell(fmt.day(order.date), order.date.toordinal() if order.date else 0),
        _cell(
            fmt.day(order.shipment_date),
            order.shipment_date.toordinal() if order.shipment_date else 0,
        ),
        _cell(fmt.quantity(order.pallets), order.pallets, numeric=True),
        _cell(fmt.number(order.weight), order.weight, numeric=True),
    ]
    if res is None:
        row += [_cell(""), _cell(""), _money_cell(None), _money_cell(None)]
    else:
        method = _cell("" if in_group else res.method.label)
        method.setData(res.method.value, METHOD_ROLE)
        if res.is_error:
            method.setToolTip(res.method.value)
        row += [
            method,
            _cell("" if in_group else _transport(res)),
            _money_cell(None if res.is_error else res.cost),
            _money_cell(res.pallet_cost),
        ]
    row += [
        _money_cell(None),
        _cell(order.order_num),
        address,
        _cell(order.transport_address or ""),
    ]
    return row


def _group_row(group: Group, orders: Sequence[Order], colors: Palette) -> list[QStandardItem]:
    dates = [order.date for order in orders if order.date]
    shipments = [order.shipment_date for order in orders if order.shipment_date]
    cities = list(dict.fromkeys(order.city for order in sorted(orders, key=_by_date)))
    count = fmt.plural(len(orders), "заказ", "заказа", "заказов")
    title = _cell(f"Группа {group.id} · {count}", f" {group.id:06d}")  # группы идут первыми
    title.setData(group.id, GROUP_ROLE)
    method = _cell(group.method.label)
    method.setData(group.method.value, METHOD_ROLE)
    savings = group.savings if group.savings > 0.005 else None
    savings_cell = _money_cell(savings)
    savings_cell.setForeground(QBrush(QColor(colors.good)))
    row = [
        title,
        _cell(" → ".join(cities)),
        _cell(fmt.day_range(dates), min(dates).toordinal() if dates else 0),
        _cell(fmt.day_range(shipments), min(shipments).toordinal() if shipments else 0),
        _cell(fmt.quantity(sum(o.pallets for o in orders)), sum(o.pallets for o in orders), True),
        _cell(fmt.number(sum(o.weight for o in orders)), sum(o.weight for o in orders), True),
        method,
        _cell(str(group.trucks).replace(" x ", " × ")),
        _money_cell(group.cost),
        _money_cell(group.pallet_cost),
        savings_cell,
        _cell(""),
        _cell(""),
        _cell(""),
    ]
    bold = QFont()
    bold.setWeight(QFont.Weight.DemiBold)
    for item in row:
        item.setBackground(QBrush(QColor(colors.group_bg)))
        item.setFont(bold)
    return row


def _by_date(order: Order) -> tuple[int, int]:
    return (order.date.toordinal() if order.date else 0, order.index)


def build_model(
    orders: Sequence[Order], result: AnalysisResult | None, colors: Palette
) -> tuple[QStandardItemModel, list[RowFacts]]:
    """Сначала группы по номерам, затем одиночные заказы в порядке файла."""
    model = QStandardItemModel()
    model.setHorizontalHeaderLabels([column.title for column in COLUMNS])
    for position, column in enumerate(COLUMNS):
        header = model.horizontalHeaderItem(position)
        if column.tip:
            header.setToolTip(column.tip)
        if column.numeric:
            header.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    facts: list[RowFacts] = []
    if result is None:
        for order in orders:
            model.appendRow(_order_row(order, None, in_group=False))
            facts.append(_facts([order], [None], is_group=False))
        return model, facts

    for group in result.groups:
        members = sorted((result.results[i] for i in group.indices), key=lambda r: _by_date(r.order))
        group_orders = [res.order for res in members]
        row = _group_row(group, group_orders, colors)
        for res in members:
            row[0].appendRow(_order_row(res.order, res, in_group=True))
        model.appendRow(row)
        facts.append(_facts(group_orders, members, is_group=True))
    for res in result.results:
        if res.group == 0:
            model.appendRow(_order_row(res.order, res, in_group=False))
            facts.append(_facts([res.order], [res], is_group=False))
    return model, facts


class ResultsFilter(QSortFilterProxyModel):
    """Отбор по строке поиска, городу, способу и месяцу. Группа показывается целиком."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._facts: list[RowFacts] = []
        self._text = ""
        self._city: str | None = None
        self._method: Method | str | None = None
        self._month: str | None = None
        self._groups_only = False

    def set_facts(self, facts: list[RowFacts]) -> None:
        self._facts = facts
        self.invalidateFilter()

    def set_filters(
        self,
        text: str = "",
        city: str | None = None,
        method: Method | str | None = None,
        month: str | None = None,
        groups_only: bool = False,
    ) -> None:
        self._text = text.strip().lower()
        self._city, self._method, self._month = city, method, month
        self._groups_only = groups_only
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        top = source_parent.row() if source_parent.isValid() else source_row
        if top >= len(self._facts):
            return True
        facts = self._facts[top]
        if self._groups_only and not facts.is_group:
            return False
        if self._city and self._city not in facts.cities:
            return False
        if self._month and self._month not in facts.months:
            return False
        if self._method == ERRORS:
            if not any(method.is_error for method in facts.methods):
                return False
        elif self._method is not None and self._method not in facts.methods:
            return False
        return all(word in facts.text for word in self._text.split())

    def visible_orders(self) -> int:
        total = 0
        for row in range(self.rowCount()):
            children = self.rowCount(self.index(row, 0))
            total += children or 1
        return total

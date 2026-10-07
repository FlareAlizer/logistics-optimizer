"""Правая часть окна: сводка, отбор, дерево результатов."""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QPainter
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QStackedWidget,
    QStyleOptionViewItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..models import AnalysisResult, Method, Order
from . import formatting as fmt
from .results_model import (
    COLUMNS,
    ERRORS,
    GROUP_ROLE,
    METHOD_COLUMN,
    ResultsFilter,
    build_model,
    month_key,
)
from .theme import Palette
from .widgets import MethodDelegate, StatCard, link_button


class ResultsTree(QTreeView):
    """Дерево, в котором строка группы подкрашена целиком, вместе с отступом слева."""

    def __init__(self, colors: Palette) -> None:
        super().__init__()
        self.colors = colors

    def drawRow(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        if index.siblingAtColumn(0).data(GROUP_ROLE):
            painter.fillRect(option.rect, QColor(self.colors.group_bg))
        super().drawRow(painter, option, index)


class ResultsPanel(QWidget):
    groupOpened = pyqtSignal(int)
    warningsRequested = pyqtSignal()

    def __init__(self, colors: Palette) -> None:
        super().__init__()
        self.colors = colors
        self.status = ""
        self._orders: Sequence[Order] = ()
        self._result: AnalysisResult | None = None
        self._hidden: dict[int, bool] = {}  # колонки, которые пользователь скрыл или вернул
        self.proxy = ResultsFilter(self)

        self.stat_separate = StatCard("Каждый заказ отдельно")
        self.stat_plan = StatCard("По плану")
        self.stat_savings = StatCard("Экономия")
        self.stat_trips = StatCard("Прямые рейсы")
        self.stats = (self.stat_separate, self.stat_plan, self.stat_savings, self.stat_trips)
        stats = QHBoxLayout()
        stats.setSpacing(12)
        for card in self.stats:
            stats.addWidget(card, 1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск: получатель, город, номер заказа, дата")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filters)
        self.city_filter = QComboBox()
        self.method_filter = QComboBox()
        self.month_filter = QComboBox()
        for combo in (self.city_filter, self.method_filter, self.month_filter):
            combo.setMinimumWidth(150)
            combo.currentIndexChanged.connect(self.apply_filters)
        self.groups_only = QCheckBox("Только группы")
        self.groups_only.toggled.connect(self.apply_filters)
        collapse = link_button("Свернуть")
        expand = link_button("Развернуть")
        filters = QHBoxLayout()
        filters.setSpacing(10)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.city_filter)
        filters.addWidget(self.method_filter)
        filters.addWidget(self.month_filter)
        filters.addWidget(self.groups_only)
        filters.addSpacing(6)
        filters.addWidget(collapse)
        filters.addWidget(expand)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        self.banner_text = QLabel()
        banner_more = link_button("Показать")
        banner_more.clicked.connect(self.warningsRequested)
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(12, 6, 12, 6)
        banner_layout.addWidget(self.banner_text, 1)
        banner_layout.addWidget(banner_more)
        self.banner.setVisible(False)

        self.tree = ResultsTree(colors)
        self.tree.setModel(self.proxy)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.setIndentation(18)
        self.tree.doubleClicked.connect(self._open_row)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._row_menu)
        self.method_delegate = MethodDelegate(colors, self.tree)
        self.tree.setItemDelegateForColumn(METHOD_COLUMN, self.method_delegate)
        collapse.clicked.connect(self.tree.collapseAll)
        expand.clicked.connect(self.tree.expandAll)
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._columns_menu)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._empty_state())
        self.stack.addWidget(self.tree)
        self.status_line = QLabel()
        self.status_line.setObjectName("statusLine")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 12)
        layout.setSpacing(12)
        layout.addLayout(stats)
        layout.addLayout(filters)
        layout.addWidget(self.banner)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.status_line)
        self.show_rows((), None)

    @staticmethod
    def _empty_state() -> QWidget:
        title = QLabel("Перетащите сюда файл с заказами")
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note = QLabel(
            "Подойдёт книга Excel с листом заказов. Если тарифы лежат в ней же, "
            "программа найдёт их сама.\nЧтобы сначала посмотреть, как всё работает, "
            "откройте пример слева внизу."
        )
        note.setObjectName("muted")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addSpacing(6)
        layout.addWidget(note)
        layout.addStretch(1)
        return panel

    # ---------- данные ----------

    def set_colors(self, colors: Palette) -> None:
        self.colors = self.tree.colors = self.method_delegate.colors = colors
        self.show_rows(self._orders, self._result)

    def show_rows(self, orders: Sequence[Order], result: AnalysisResult | None) -> None:
        """Перестраивает дерево: до расчёта это плоский список заказов, после него группы."""
        self._orders, self._result = orders, result
        model, facts = build_model(orders, result, self.colors)
        old = self.proxy.sourceModel()
        self.proxy.setSourceModel(model)
        self.proxy.set_facts(facts)
        model.setParent(self.proxy)
        if old is not None:
            old.deleteLater()
        self.proxy.sort(-1)
        self.tree.header().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        for position, column in enumerate(COLUMNS):
            self.tree.setColumnWidth(position, column.width)
            self.tree.setColumnHidden(position, self._hidden.get(position, column.hidden))
        self._fill_filters()
        self.tree.expandAll()
        self.stack.setCurrentIndex(1 if orders else 0)
        for widget in (self.search, self.city_filter, self.method_filter, self.month_filter):
            widget.setEnabled(bool(orders))
        self.groups_only.setEnabled(result is not None)
        self._show_stats()
        self.update_status()

    def _fill_filters(self) -> None:
        cities = sorted({order.city for order in self._orders})
        months = sorted({key for order in self._orders if (key := month_key(order))})
        methods: list[Method | str] = []
        if self._result:
            present = {res.method for res in self._result.results}
            methods = [m for m in Method if m in present and not m.is_error and m.value]
            if any(method.is_error for method in present):
                methods.append(ERRORS)
        self._fill(self.city_filter, "Все города", [(city, city) for city in cities])
        self._fill(
            self.method_filter,
            "Все способы",
            [(m, "Без расчёта" if m == ERRORS else Method(m).label) for m in methods],
        )
        self._fill(
            self.month_filter,
            "Все месяцы",
            [(key, f"{fmt.MONTHS[int(key[5:]) - 1]} {key[:4]}") for key in months],
        )

    @staticmethod
    def _fill(combo: QComboBox, everything: str, items: list[tuple[object, str]]) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(everything, None)
        for data, text in items:
            combo.addItem(text, data)
        combo.setCurrentIndex(max(combo.findData(current), 0))
        combo.blockSignals(False)

    def apply_filters(self) -> None:
        self.proxy.set_filters(
            self.search.text(),
            self.city_filter.currentData(),
            self.method_filter.currentData(),
            self.month_filter.currentData(),
            self.groups_only.isChecked(),
        )
        self.tree.expandAll()
        self.update_status()

    # ---------- сводка и строка состояния ----------

    def _show_stats(self) -> None:
        if self._result is None:
            for card in self.stats:
                card.show_value(fmt.DASH)
            self.banner.setVisible(False)
            return
        summary = self._result.summary()
        self.stat_separate.show_value(
            fmt.money(summary.separate_cost), "самым дешёвым способом для каждого"
        )
        self.stat_plan.show_value(
            fmt.money(summary.plan_cost),
            f"{fmt.plural(summary.groups, 'группа', 'группы', 'групп')} из "
            f"{fmt.plural(summary.orders, 'заказа', 'заказов', 'заказов')}",
        )
        self.stat_savings.show_value(
            fmt.money(summary.savings),
            f"{fmt.percent(summary.savings_share)} от стоимости по отдельности",
            tone="good" if summary.savings > 0 else "",
        )
        self.stat_trips.show_value(
            fmt.number(summary.trips),
            f"машин 10т: {summary.trucks_10t} · 20т: {summary.trucks_20t}",
        )
        count = len(self._result.warnings)
        self.banner.setVisible(count > 0)
        if count:
            text = fmt.plural(count, "предупреждение", "предупреждения", "предупреждений")
            if summary.errors:
                errors = fmt.plural(summary.errors, "заказ", "заказа", "заказов")
                text += f". Без расчёта: {errors}"
            self.banner_text.setText(text + ".")

    def update_status(self) -> None:
        parts = [self.status] if self.status else []
        if self._orders:
            total = fmt.plural(len(self._orders), "заказа", "заказов", "заказов")
            parts.append(f"Показано {fmt.number(self.proxy.visible_orders())} из {total}")
            if self._result is not None:
                parts.append("двойной щелчок по группе открывает её состав")
        self.status_line.setText(" · ".join(parts))

    # ---------- действия в дереве ----------

    def _group_id(self, index: QModelIndex) -> int | None:
        top = index if not index.parent().isValid() else index.parent()
        return top.siblingAtColumn(0).data(GROUP_ROLE)

    def _open_row(self, index: QModelIndex) -> None:
        group_id = self._group_id(index)
        if group_id:
            self.groupOpened.emit(group_id)

    def _row_menu(self, position) -> None:
        index = self.tree.indexAt(position)
        if not index.isValid() or not self._group_id(index):
            return
        menu = QMenu(self)
        menu.addAction("Состав группы…", lambda: self._open_row(index))
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _columns_menu(self, position) -> None:
        menu = QMenu(self)
        for number, column in enumerate(COLUMNS[1:], start=1):
            action = QAction(column.title, menu)
            action.setCheckable(True)
            action.setChecked(not self.tree.isColumnHidden(number))
            action.toggled.connect(lambda shown, n=number: self._show_column(n, shown))
            menu.addAction(action)
        menu.exec(self.tree.header().mapToGlobal(position))

    def _show_column(self, number: int, shown: bool) -> None:
        self._hidden[number] = not shown
        self.tree.setColumnHidden(number, not shown)

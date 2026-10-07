"""Главное окно: слева шаги (заказы, тарифы, правила, запуск), справа сводка и дерево."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtGui import QAction, QDragEnterEvent, QDropEvent, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..columns import ColumnMappingError
from ..config import Settings, SettingsError
from ..excel import (
    DataError,
    OrdersTable,
    load_orders,
    load_tariffs,
    orders_from_frame,
    tariffs_from_frames,
)
from ..geo import load_cities
from ..models import AnalysisResult, Method
from ..pricing import Tariffs
from ..report import export_xlsx
from ..sample import generate_sample
from . import formatting as fmt
from .dialogs import ColumnsDialog, GroupDialog, SettingsDialog, WarningsDialog
from .results_model import (
    COLUMNS,
    ERRORS,
    GROUP_ROLE,
    METHOD_COLUMN,
    ResultsFilter,
    build_model,
    month_key,
)
from .theme import Palette, apply_theme, system_theme
from .widgets import MethodDelegate, StatCard, StepCard, dropped_excel_files, link_button
from .worker import AnalysisWorker

EXCEL_FILTER = "Книги Excel (*.xlsx *.xlsm)"


class MainWindow(QMainWindow):
    def __init__(self, config_dir: Path | None = None, theme: str | None = None) -> None:
        """config_dir хранит settings.json и свой cities.csv. Без него окно ничего не пишет."""
        super().__init__()
        self.setWindowTitle("Оптимизатор доставки")
        self.resize(1440, 880)
        self.setMinimumSize(1100, 640)
        self.setAcceptDrops(True)

        self.config_dir = config_dir
        self.settings = self._load_settings()
        self.cities = load_cities(config_dir / "cities.csv" if config_dir else None)
        self.theme = theme or system_theme()
        self.colors: Palette = apply_theme(QApplication.instance(), self.theme)

        self.table: OrdersTable | None = None
        self.orders_path: Path | None = None
        self.overrides: dict[str, str | None] = {}
        self.tariffs: Tariffs | None = None
        self.tariffs_name = ""
        self.result: AnalysisResult | None = None
        self.worker: AnalysisWorker | None = None
        self._status = ""
        self._hidden: dict[int, bool] = {}  # колонки, которые пользователь скрыл или вернул

        self.proxy = ResultsFilter(self)
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())
        layout.addWidget(self._build_content(), 1)
        self.setCentralWidget(root)
        self._refresh()

    # ---------- сборка окна ----------

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(340)

        title = QLabel("Оптимизатор доставки")
        title.setObjectName("appTitle")
        subtitle = QLabel("Собирает заказы в общие рейсы и считает стоимость")
        subtitle.setObjectName("appSubtitle")
        subtitle.setWordWrap(True)

        self.orders_card = StepCard(1, "Заказы", accepts_files=True)
        self.orders_card.fileDropped.connect(self.open_orders)
        self.orders_card.add_action("Выбрать файл…").clicked.connect(self.choose_orders)
        self.columns_link = self.orders_card.add_action("Колонки…")
        self.columns_link.clicked.connect(self.edit_columns)

        self.tariffs_card = StepCard(2, "Тарифы", accepts_files=True)
        self.tariffs_card.fileDropped.connect(self.open_tariffs)
        self.tariffs_card.add_action("Выбрать файл…").clicked.connect(self.choose_tariffs)

        self.rules_card = StepCard(3, "Правила")
        self.rules_card.add_action("Изменить…").clicked.connect(self.edit_settings)

        self.run_button = QPushButton("Рассчитать")
        self.run_button.setObjectName("primary")
        self.run_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_button.clicked.connect(self.start_analysis)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("stepHint")
        self.progress_label.setWordWrap(True)
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.clicked.connect(self.cancel_analysis)
        self.running_box = QWidget()
        running = QVBoxLayout(self.running_box)
        running.setContentsMargins(0, 0, 0, 0)
        running.setSpacing(8)
        running.addWidget(self.progress)
        running.addWidget(self.progress_label)
        running.addWidget(self.cancel_button)
        self.running_box.setVisible(False)

        self.export_button = QPushButton("Сохранить в Excel…")
        self.export_button.clicked.connect(self.export)

        self.sample_link = link_button("Открыть пример")
        self.sample_link.clicked.connect(self.load_sample)
        self.theme_link = link_button("")
        self.theme_link.clicked.connect(self.toggle_theme)
        footer = QHBoxLayout()
        footer.addWidget(self.sample_link)
        footer.addStretch(1)
        footer.addWidget(self.theme_link)

        layout = QVBoxLayout(side)
        layout.setContentsMargins(18, 20, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(6)
        layout.addWidget(self.orders_card)
        layout.addWidget(self.tariffs_card)
        layout.addWidget(self.rules_card)
        layout.addStretch(1)
        layout.addWidget(self.run_button)
        layout.addWidget(self.running_box)
        layout.addWidget(self.export_button)
        layout.addSpacing(4)
        layout.addLayout(footer)
        return side

    def _build_content(self) -> QWidget:
        self.stat_separate = StatCard("Каждый заказ отдельно")
        self.stat_plan = StatCard("По плану")
        self.stat_savings = StatCard("Экономия")
        self.stat_trips = StatCard("Прямые рейсы")
        stats = QHBoxLayout()
        stats.setSpacing(12)
        for card in (self.stat_separate, self.stat_plan, self.stat_savings, self.stat_trips):
            stats.addWidget(card, 1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск: получатель, город, номер заказа, дата")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filters)
        self.city_filter = QComboBox()
        self.method_filter = QComboBox()
        self.month_filter = QComboBox()
        for combo in (self.city_filter, self.method_filter, self.month_filter):
            combo.setMinimumWidth(150)
            combo.currentIndexChanged.connect(self._apply_filters)
        self.groups_only = QCheckBox("Только группы")
        self.groups_only.toggled.connect(self._apply_filters)
        collapse = link_button("Свернуть")
        collapse.clicked.connect(lambda: self.tree.collapseAll())
        expand = link_button("Развернуть")
        expand.clicked.connect(lambda: self.tree.expandAll())
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
        banner_more.clicked.connect(self.show_warnings)
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(12, 6, 12, 6)
        banner_layout.addWidget(self.banner_text, 1)
        banner_layout.addWidget(banner_more)
        self.banner.setVisible(False)

        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.setIndentation(18)
        self.tree.setAnimated(False)
        self.tree.doubleClicked.connect(self._open_row)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._row_menu)
        self.method_delegate = MethodDelegate(self.colors, self.tree)
        self.tree.setItemDelegateForColumn(METHOD_COLUMN, self.method_delegate)
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._columns_menu)

        empty = QWidget()
        empty_title = QLabel("Перетащите сюда файл с заказами")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_note = QLabel(
            "Подойдёт книга Excel с листом заказов. Если тарифы лежат в ней же, "
            "программа найдёт их сама.\nХотите сначала посмотреть, как всё работает — "
            "откройте пример слева внизу."
        )
        empty_note.setObjectName("muted")
        empty_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch(1)
        empty_layout.addWidget(empty_title)
        empty_layout.addSpacing(6)
        empty_layout.addWidget(empty_note)
        empty_layout.addStretch(1)
        empty_panel = QFrame()
        empty_panel.setObjectName("panel")
        panel_layout = QVBoxLayout(empty_panel)
        panel_layout.addWidget(empty)

        self.stack = QStackedWidget()
        self.stack.addWidget(empty_panel)
        self.stack.addWidget(self.tree)

        self.status_line = QLabel()
        self.status_line.setObjectName("statusLine")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 12)
        layout.setSpacing(12)
        layout.addLayout(stats)
        layout.addLayout(filters)
        layout.addWidget(self.banner)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.status_line)
        return content

    # ---------- настройки ----------

    def _settings_path(self) -> Path | None:
        return self.config_dir / "settings.json" if self.config_dir else None

    def _load_settings(self) -> Settings:
        path = self._settings_path()
        if path and path.is_file():
            try:
                return Settings.load(path)
            except SettingsError:
                return Settings()
        return Settings()

    def edit_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if not dialog.exec() or dialog.result_settings is None:
            return
        if dialog.result_settings == self.settings:
            return
        self.settings = dialog.result_settings
        path = self._settings_path()
        if path:
            try:
                self.settings.save(path)
            except OSError:
                self._say("Настройки применены, но сохранить их в файл не удалось.")
        self._drop_result("Правила изменены. Запустите расчёт заново.")

    def toggle_theme(self) -> None:
        self.theme = "light" if self.theme == "dark" else "dark"
        self.colors = apply_theme(QApplication.instance(), self.theme)
        self.method_delegate.colors = self.colors
        self._rebuild_tree()
        self._refresh()

    # ---------- загрузка файлов ----------

    def choose_orders(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Файл с заказами", "", EXCEL_FILTER)
        if path:
            self.open_orders(path)

    def choose_tariffs(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Файл с тарифами", "", EXCEL_FILTER)
        if path:
            self.open_tariffs(path)

    def open_orders(self, path: str | Path, overrides: Mapping[str, str | None] | None = None):
        """Читает заказы. Если колонки не определились, спрашивает их и пробует ещё раз."""
        path = Path(path)
        overrides = dict(overrides or {})
        sheet = None
        while True:
            try:
                with _busy():
                    table = load_orders(path, sheet=sheet, overrides=overrides)
                break
            except ColumnMappingError as exc:
                dialog = ColumnsDialog(exc.available, overrides, exc.missing, self)
                if not dialog.exec():
                    return False
                overrides, sheet = dialog.mapping(), exc.sheet or None
            except DataError as exc:
                self._say(str(exc))
                return False
        if not table.orders:
            self._say(f"В файле {path.name} не нашлось ни одной строки с городом.")
            return False
        self.table, self.orders_path, self.overrides = table, path, overrides
        self._drop_result()
        # Тарифы часто лежат в той же книге на соседних листах.
        if self.tariffs is None:
            self.open_tariffs(path, quiet=True)
        return True

    def open_tariffs(self, path: str | Path, quiet: bool = False) -> bool:
        path = Path(path)
        try:
            with _busy():
                tariffs = load_tariffs(path)
        except DataError as exc:
            if not quiet:
                self._say(str(exc))
            return False
        self.tariffs, self.tariffs_name = tariffs, path.name
        self._drop_result()
        return True

    def edit_columns(self) -> None:
        if self.table is None or self.orders_path is None:
            return
        dialog = ColumnsDialog(self.table.columns, self.table.mapping.as_dict(), parent=self)
        if dialog.exec():
            self.open_orders(self.orders_path, dialog.mapping())

    def load_sample(self) -> None:
        data = generate_sample()
        self.table = orders_from_frame(data.orders, sheet="Заказы")
        self.orders_path, self.overrides = None, {}
        self.tariffs = tariffs_from_frames(data.direct, data.pallet)
        self.tariffs_name = "пример"
        self._drop_result("Открыт пример с выдуманными заказами. Нажмите «Рассчитать».")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if dropped_excel_files(event):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for path in dropped_excel_files(event)[:2]:
            event.acceptProposedAction()
            if self.table is not None and self.tariffs is None:
                self.open_tariffs(path)
            else:
                self.open_orders(path)

    # ---------- расчёт ----------

    def start_analysis(self) -> None:
        if self.table is None or self.tariffs is None or self.worker is not None:
            return
        self.worker = AnalysisWorker(
            self.table.orders, self.tariffs, self.settings, self.cities, self
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.finished.connect(self._on_thread_finished)
        self.progress.setValue(0)
        self.progress_label.setText("Начинаю расчёт")
        self.cancel_button.setEnabled(True)
        self.worker.start()
        self._refresh()

    def cancel_analysis(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.progress_label.setText("Останавливаю…")

    def _on_progress(self, percent: int, message: str) -> None:
        self.progress.setValue(percent)
        self.progress_label.setText(message)

    def _on_done(self, result: AnalysisResult) -> None:
        self.result = result
        self._rebuild_tree()
        summary = result.summary()
        self._status = (
            f"Готово: {fmt.plural(summary.groups, 'группа', 'группы', 'групп')}, "
            f"экономия {fmt.money(summary.savings)}."
        )

    def _on_failed(self, message: str) -> None:
        self._status = "Расчёт не выполнен."
        self._say(message)

    def _on_cancelled(self) -> None:
        self._status = "Расчёт остановлен."

    def _on_thread_finished(self) -> None:
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.deleteLater()
        self._refresh()

    def _drop_result(self, status: str = "") -> None:
        """Данные или правила изменились: старый результат больше не действителен."""
        self.result = None
        self._status = status
        self._rebuild_tree()
        self._refresh()

    # ---------- дерево и отбор ----------

    def _rebuild_tree(self) -> None:
        orders = self.table.orders if self.table else []
        model, facts = build_model(orders, self.result, self.colors)
        old = self.proxy.sourceModel()
        self.proxy.setSourceModel(model)
        self.proxy.set_facts(facts)
        if old is not None:
            old.deleteLater()
        model.setParent(self.proxy)
        self.proxy.sort(-1)
        self.tree.header().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        for position, column in enumerate(COLUMNS):
            self.tree.setColumnWidth(position, column.width)
            self.tree.setColumnHidden(position, self._hidden.get(position, column.hidden))
        self._fill_filters()
        self.tree.expandAll()
        self.stack.setCurrentIndex(1 if orders else 0)

    def _fill_filters(self) -> None:
        orders = self.table.orders if self.table else []
        cities = sorted({order.city for order in orders})
        months = sorted({key for order in orders if (key := month_key(order))})
        methods = []
        if self.result:
            present = {res.method for res in self.result.results}
            methods = [m for m in Method if m in present and not m.is_error and m is not Method.NONE]
            if any(method.is_error for method in present):
                methods.append(ERRORS)
        self._fill(self.city_filter, "Все города", [(city, city) for city in cities])
        self._fill(
            self.method_filter,
            "Все способы",
            [(m, "Без расчёта" if m == ERRORS else m.label) for m in methods],
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

    def _apply_filters(self) -> None:
        self.proxy.set_filters(
            self.search.text(),
            self.city_filter.currentData(),
            self.method_filter.currentData(),
            self.month_filter.currentData(),
            self.groups_only.isChecked(),
        )
        self.tree.expandAll()
        self._update_status_line()

    def _open_row(self, index: QModelIndex) -> None:
        top = index if not index.parent().isValid() else index.parent()
        group_id = top.siblingAtColumn(0).data(GROUP_ROLE)
        if group_id and self.result:
            GroupDialog(self.result.group_by_id()[group_id], self.result, self).exec()

    def _row_menu(self, position) -> None:
        index = self.tree.indexAt(position)
        if not index.isValid():
            return
        top = index if not index.parent().isValid() else index.parent()
        if not top.siblingAtColumn(0).data(GROUP_ROLE):
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

    def show_warnings(self) -> None:
        if self.result and self.result.warnings:
            WarningsDialog(self.result.warnings, self).exec()

    # ---------- выгрузка ----------

    def export(self) -> None:
        if self.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить результат", "result.xlsx", EXCEL_FILTER)
        if path:
            self.export_to(path)

    def export_to(self, path: str | Path) -> bool:
        if self.result is None:
            return False
        try:
            with _busy():
                saved = export_xlsx(self.result, path)
        except DataError as exc:
            self._say(str(exc))
            return False
        self._status = f"Результат сохранён: {saved.name}"
        self._update_status_line()
        return True

    # ---------- состояние ----------

    def _refresh(self) -> None:
        """Приводит подписи и доступность кнопок к текущим данным."""
        running = self.worker is not None
        ready = self.table is not None and self.tariffs is not None

        if self.table is None:
            self.orders_card.show_state("Перетащите сюда книгу Excel или выберите файл.")
        else:
            orders = self.table.orders
            days = [order.date for order in orders if order.date]
            cities = len({order.city_key for order in orders})
            hint = (
                f"{fmt.plural(len(orders), 'заказ', 'заказа', 'заказов')} · "
                f"{fmt.plural(cities, 'город', 'города', 'городов')}\n{fmt.day_range(days)}"
            )
            if self.table.skipped_rows:
                hint += f"\nПропущено строк без города: {self.table.skipped_rows}"
            name = self.orders_path.name if self.orders_path else "Пример"
            self.orders_card.show_state(hint, name, done=True)
        self.columns_link.setVisible(self.orders_path is not None)

        if self.tariffs is None:
            self.tariffs_card.show_state(
                "Нужны листы с прямыми (10Т, 20Т) и паллетными ценами по городам."
            )
        else:
            hint = (
                f"Прямые: {fmt.plural(len(self.tariffs.direct), 'город', 'города', 'городов')}"
                f" · паллетные: {len(self.tariffs.pallet)}"
            )
            self.tariffs_card.show_state(hint, self.tariffs_name.capitalize(), done=True)

        self.rules_card.show_state(self._rules_text(), done=True)

        self.run_button.setVisible(not running)
        self.run_button.setEnabled(ready)
        self.run_button.setText("Пересчитать" if self.result else "Рассчитать")
        self.running_box.setVisible(running)
        self.export_button.setEnabled(self.result is not None and not running)
        for widget in (self.orders_card, self.tariffs_card, self.rules_card, self.sample_link):
            widget.setEnabled(not running)
        self.theme_link.setText("Светлая тема" if self.theme == "dark" else "Тёмная тема")
        has_rows = self.table is not None
        for widget in (self.search, self.city_filter, self.method_filter, self.month_filter):
            widget.setEnabled(has_rows)
        self.groups_only.setEnabled(self.result is not None)
        self._update_stats()
        self._update_status_line()

    def _rules_text(self) -> str:
        small, big = self.settings.truck_10t, self.settings.truck_20t
        rules, costs = self.settings.rules, self.settings.costs
        return (
            f"10т: {small.pallets} паллет, {fmt.number(small.kg)} кг\n"
            f"20т: {big.pallets} паллеты, {fmt.number(big.kg)} кг\n"
            f"В рейсе до {rules.max_cities} городов и {rules.max_recipients} получателей, "
            f"даты в пределах {rules.max_day_diff} дн., города не дальше "
            f"{fmt.number(rules.radius_km)} км\n"
            f"Москва: {fmt.money(costs.moscow_rate_per_pallet)} за паллету"
        )

    def _update_stats(self) -> None:
        if self.result is None:
            for card in (self.stat_separate, self.stat_plan, self.stat_savings, self.stat_trips):
                card.show_value(fmt.DASH)
            self.banner.setVisible(False)
            return
        summary = self.result.summary()
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
        count = len(self.result.warnings)
        self.banner.setVisible(count > 0)
        if count:
            errors = (
                f" Без расчёта: {fmt.plural(summary.errors, 'заказ', 'заказа', 'заказов')}."
                if summary.errors
                else ""
            )
            self.banner_text.setText(
                f"{fmt.plural(count, 'предупреждение', 'предупреждения', 'предупреждений')}."
                f"{errors}"
            )

    def _update_status_line(self) -> None:
        parts = []
        if self.table is not None:
            total = len(self.table.orders)
            shown = self.proxy.visible_orders()
            parts.append(
                f"Показано {fmt.number(shown)} из {fmt.plural(total, 'заказа', 'заказов', 'заказов')}"
            )
            if self.result is not None:
                parts.append("двойной щелчок по группе открывает её состав")
        if self._status:
            parts.insert(0, self._status)
        self.status_line.setText(" · ".join(parts))

    def _say(self, text: str) -> None:
        QMessageBox.warning(self, "Оптимизатор доставки", text)

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(5000)
        super().closeEvent(event)


class _busy:
    """Курсор ожидания на время чтения или записи файла."""

    def __enter__(self) -> None:
        if QGuiApplication.instance() is not None:
            QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def __exit__(self, *exc) -> None:
        if QGuiApplication.instance() is not None:
            QGuiApplication.restoreOverrideCursor()

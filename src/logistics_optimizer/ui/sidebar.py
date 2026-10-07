"""Левая колонка окна: три шага, запуск расчёта, сохранение."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings
from ..excel import OrdersTable
from ..pricing import Tariffs
from . import formatting as fmt
from .widgets import StepCard, link_button


class Sidebar(QFrame):
    ordersDropped = pyqtSignal(str)
    tariffsDropped = pyqtSignal(str)
    chooseOrders = pyqtSignal()
    chooseTariffs = pyqtSignal()
    editColumns = pyqtSignal()
    editSettings = pyqtSignal()
    runRequested = pyqtSignal()
    cancelRequested = pyqtSignal()
    exportRequested = pyqtSignal()
    sampleRequested = pyqtSignal()
    themeToggled = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(320)

        title = QLabel("Оптимизатор доставки")
        title.setObjectName("appTitle")
        subtitle = QLabel("Собирает заказы в общие рейсы и считает стоимость")
        subtitle.setObjectName("appSubtitle")
        subtitle.setWordWrap(True)

        self.orders_card = StepCard(1, "Заказы", accepts_files=True)
        self.orders_card.fileDropped.connect(self.ordersDropped)
        self.orders_card.add_action("Выбрать файл…").clicked.connect(self.chooseOrders)
        self.columns_link = self.orders_card.add_action("Колонки…")
        self.columns_link.clicked.connect(self.editColumns)

        self.tariffs_card = StepCard(2, "Тарифы", accepts_files=True)
        self.tariffs_card.fileDropped.connect(self.tariffsDropped)
        self.tariffs_card.add_action("Выбрать файл…").clicked.connect(self.chooseTariffs)

        self.rules_card = StepCard(3, "Правила")
        self.rules_card.add_action("Изменить…").clicked.connect(self.editSettings)

        self.run_button = QPushButton("Рассчитать")
        self.run_button.setObjectName("primary")
        self.run_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_button.clicked.connect(self.runRequested)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("stepHint")
        self.progress_label.setWordWrap(True)
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.clicked.connect(self._cancel)
        self.running_box = QWidget()
        running = QVBoxLayout(self.running_box)
        running.setContentsMargins(0, 0, 0, 0)
        running.setSpacing(8)
        running.addWidget(self.progress)
        running.addWidget(self.progress_label)
        running.addWidget(self.cancel_button)
        self.running_box.setVisible(False)

        self.export_button = QPushButton("Сохранить в Excel…")
        self.export_button.clicked.connect(self.exportRequested)

        self.sample_link = link_button("Открыть пример")
        self.sample_link.clicked.connect(self.sampleRequested)
        self.theme_link = link_button("")
        self.theme_link.clicked.connect(self.themeToggled)
        footer = QHBoxLayout()
        footer.addWidget(self.sample_link)
        footer.addStretch(1)
        footer.addWidget(self.theme_link)

        layout = QVBoxLayout(self)
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

    # ---------- что показывать ----------

    def show_orders(self, table: OrdersTable | None, file_name: str) -> None:
        if table is None:
            self.orders_card.show_state("Перетащите сюда книгу Excel или выберите файл.")
            self.columns_link.setVisible(False)
            return
        orders = table.orders
        days = [order.date for order in orders if order.date]
        cities = len({order.city_key for order in orders})
        hint = (
            f"{fmt.plural(len(orders), 'заказ', 'заказа', 'заказов')} · "
            f"{fmt.plural(cities, 'город', 'города', 'городов')}\n{fmt.day_range(days)}"
        )
        if table.skipped_rows:
            hint += f"\nПропущено строк без города: {table.skipped_rows}"
        self.orders_card.show_state(hint, file_name or "Пример", done=True)
        self.columns_link.setVisible(bool(file_name))

    def show_tariffs(self, tariffs: Tariffs | None, file_name: str) -> None:
        if tariffs is None:
            self.tariffs_card.show_state(
                "Нужны листы с прямыми (10Т, 20Т) и паллетными ценами по городам."
            )
            return
        hint = (
            f"Прямые: {fmt.plural(len(tariffs.direct), 'город', 'города', 'городов')}"
            f" · паллетные: {len(tariffs.pallet)}"
        )
        self.tariffs_card.show_state(hint, file_name, done=True)

    def show_rules(self, settings: Settings) -> None:
        small, big = settings.truck_10t, settings.truck_20t
        rules, costs = settings.rules, settings.costs
        self.rules_card.show_state(
            f"10т: {small.pallets} паллет, {fmt.number(small.kg)} кг\n"
            f"20т: {big.pallets} паллет, {fmt.number(big.kg)} кг\n"
            f"В рейсе до {rules.max_cities} городов и {rules.max_recipients} получателей, "
            f"даты в пределах {rules.max_day_diff} дн., города не дальше "
            f"{fmt.number(rules.radius_km)} км\n"
            f"Москва: {fmt.money(costs.moscow_rate_per_pallet)} за паллету",
            done=True,
        )

    def show_run_state(self, ready: bool, running: bool, has_result: bool, dark: bool) -> None:
        self.run_button.setVisible(not running)
        self.run_button.setEnabled(ready)
        self.run_button.setText("Пересчитать" if has_result else "Рассчитать")
        self.running_box.setVisible(running)
        self.export_button.setEnabled(has_result and not running)
        for widget in (self.orders_card, self.tariffs_card, self.rules_card, self.sample_link):
            widget.setEnabled(not running)
        self.theme_link.setText("Светлая тема" if dark else "Тёмная тема")

    def start_progress(self) -> None:
        self.progress.setValue(0)
        self.progress_label.setText("Начинаю расчёт")
        self.cancel_button.setEnabled(True)

    def show_progress(self, percent: int, message: str) -> None:
        self.progress.setValue(percent)
        self.progress_label.setText(message)

    def _cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.progress_label.setText("Останавливаю…")
        self.cancelRequested.emit()

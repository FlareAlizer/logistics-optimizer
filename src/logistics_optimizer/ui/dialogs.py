"""Диалоги: настройки расчёта, выбор колонок, состав группы, предупреждения."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..columns import ALIASES, REQUIRED, TITLES, guess_columns
from ..config import Costs, GroupingRules, Settings, SettingsError, Truck
from ..models import AnalysisResult, Group
from . import formatting as fmt

NO_COLUMN = "— нет —"


def _spin(value: int, low: int, high: int, suffix: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    box.setSuffix(suffix)
    box.setGroupSeparatorShown(True)
    box.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    return box


def _real(value: float, low: float, high: float, step: float, digits: int, suffix: str = ""):
    box = QDoubleSpinBox()
    box.setDecimals(digits)
    box.setRange(low, high)
    box.setSingleStep(step)
    box.setValue(value)
    box.setSuffix(suffix)
    box.setGroupSeparatorShown(True)
    box.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    return box


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("dialogTitle")
    return label


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


class SettingsDialog(QDialog):
    """Правила расчёта. Возвращает новый объект настроек, старый не трогает."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Правила расчёта")
        self.setMinimumWidth(520)
        self.result_settings: Settings | None = None

        self.pallets_10t = _spin(1, 1, 200)
        self.kg_10t = _real(1, 1, 100000, 250, 0, " кг")
        self.pallets_20t = _spin(1, 1, 200)
        self.kg_20t = _real(1, 1, 100000, 250, 0, " кг")
        trucks = QGroupBox("Машины")
        grid = QGridLayout(trucks)
        grid.setHorizontalSpacing(12)
        grid.addWidget(QLabel("Паллет"), 0, 1)
        grid.addWidget(QLabel("Вес"), 0, 2)
        grid.addWidget(QLabel("10 тонн"), 1, 0)
        grid.addWidget(self.pallets_10t, 1, 1)
        grid.addWidget(self.kg_10t, 1, 2)
        grid.addWidget(QLabel("20 тонн"), 2, 0)
        grid.addWidget(self.pallets_20t, 2, 1)
        grid.addWidget(self.kg_20t, 2, 2)

        self.max_cities = _spin(1, 1, 10)
        self.max_recipients = _spin(1, 1, 10)
        self.max_day_diff = _spin(0, 0, 14, " дн.")
        self.radius = _real(0, 0, 5000, 10, 0, " км")
        self.threshold = _real(0, 0, 100, 1, 1, " %")
        self.threshold.setToolTip(
            "Заказы одного получателя на одну дату объединяются сразу, если машина "
            "дешевле паллетной доставки хотя бы на столько процентов."
        )
        rules = QGroupBox("Общий рейс")
        form = QFormLayout(rules)
        form.addRow("Городов, не больше", self.max_cities)
        form.addRow("Получателей, не больше", self.max_recipients)
        form.addRow("Разброс дат, не больше", self.max_day_diff)
        form.addRow("Города не дальше друг от друга", self.radius)
        form.addRow("Порог выгоды для одного получателя", self.threshold)

        self.markup_three = _real(1, 0.01, 10, 0.05, 2)
        self.markup_dates = _real(1, 0.01, 10, 0.05, 2)
        self.markup_cities = _real(1, 0.01, 10, 0.05, 2)
        self.moscow_rate = _real(0, 0, 1000000, 50, 0, " ₽")
        self.pallet_base = _real(0, 0, 1000000, 50, 0, " ₽")
        costs = QGroupBox("Наценки и ставки")
        form = QFormLayout(costs)
        form.addRow("Множитель: три города, получателя или даты", self.markup_three)
        form.addRow("Множитель: один город, разные даты", self.markup_dates)
        form.addRow("Множитель: разные города", self.markup_cities)
        form.addRow("Свой транспорт по Москве, за паллету", self.moscow_rate)
        form.addRow("Свой транспорт до РЦ, за паллету", self.pallet_base)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        reset = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        reset.setText("По умолчанию")
        reset.clicked.connect(lambda: self._fill(Settings()))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        self.error = QLabel()
        self.error.setObjectName("muted")
        self.error.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(_title("Правила расчёта"))
        layout.addWidget(trucks)
        layout.addWidget(rules)
        layout.addWidget(costs)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self._fill(settings)

    def _fill(self, settings: Settings) -> None:
        self.pallets_10t.setValue(settings.truck_10t.pallets)
        self.kg_10t.setValue(settings.truck_10t.kg)
        self.pallets_20t.setValue(settings.truck_20t.pallets)
        self.kg_20t.setValue(settings.truck_20t.kg)
        rules, costs = settings.rules, settings.costs
        self.max_cities.setValue(rules.max_cities)
        self.max_recipients.setValue(rules.max_recipients)
        self.max_day_diff.setValue(rules.max_day_diff)
        self.radius.setValue(rules.radius_km)
        self.threshold.setValue(rules.simple_group_savings_threshold * 100)
        self.markup_three.setValue(costs.markup_three_entities)
        self.markup_dates.setValue(costs.markup_same_city_diff_dates)
        self.markup_cities.setValue(costs.markup_diff_cities)
        self.moscow_rate.setValue(costs.moscow_rate_per_pallet)
        self.pallet_base.setValue(costs.pallet_base_rate)

    def _save(self) -> None:
        try:
            self.result_settings = Settings(
                truck_10t=Truck(self.pallets_10t.value(), self.kg_10t.value()),
                truck_20t=Truck(self.pallets_20t.value(), self.kg_20t.value()),
                rules=GroupingRules(
                    max_cities=self.max_cities.value(),
                    max_day_diff=self.max_day_diff.value(),
                    radius_km=self.radius.value(),
                    max_recipients=self.max_recipients.value(),
                    simple_group_savings_threshold=round(self.threshold.value() / 100, 4),
                ),
                costs=Costs(
                    markup_three_entities=self.markup_three.value(),
                    markup_same_city_diff_dates=self.markup_dates.value(),
                    markup_diff_cities=self.markup_cities.value(),
                    moscow_rate_per_pallet=self.moscow_rate.value(),
                    pallet_base_rate=self.pallet_base.value(),
                ),
            )
        except SettingsError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class ColumnsDialog(QDialog):
    """Какая колонка файла за что отвечает. Обязательные поля идут первыми."""

    def __init__(
        self,
        available: Sequence[str],
        current: Mapping[str, str | None] | None = None,
        missing: Sequence[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Колонки файла заказов")
        self.setMinimumWidth(520)
        chosen = dict(guess_columns(list(available)))
        chosen.update(current or {})
        self.combos: dict[str, QComboBox] = {}

        form = QFormLayout()
        form.setVerticalSpacing(8)
        keys = [*REQUIRED, *(key for key in ALIASES if key not in REQUIRED)]
        for key in keys:
            combo = QComboBox()
            combo.addItem(NO_COLUMN, None)
            for name in available:
                combo.addItem(name, name)
            position = combo.findData(chosen.get(key))
            combo.setCurrentIndex(max(position, 0))
            self.combos[key] = combo
            label = TITLES[key] + (" *" if key in REQUIRED else "")
            form.addRow(label, combo)

        if missing:
            names = ", ".join(TITLES[key].lower() for key in missing)
            intro = f"Не получилось определить сами: {names}. Выберите колонки вручную."
        else:
            intro = "Колонки подобраны по заголовкам. Поправьте, если что-то определилось неверно."
        self.error = QLabel()
        self.error.setObjectName("muted")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Применить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(_title("Колонки файла заказов"))
        layout.addWidget(_note(intro))
        layout.addLayout(form)
        layout.addWidget(
            _note(
                "* без этих колонок расчёт невозможен. Если отдельной даты ППС "
                "нет, достаточно выбрать дату отгрузки."
            )
        )
        layout.addWidget(self.error)
        layout.addWidget(buttons)

    def mapping(self) -> dict[str, str | None]:
        return {key: combo.currentData() for key, combo in self.combos.items()}

    def _apply(self) -> None:
        chosen = self.mapping()
        if chosen["ownership_date"] is None:
            chosen["ownership_date"] = chosen["shipment_date"]
        empty = [TITLES[key].lower() for key in REQUIRED if chosen[key] is None]
        if empty:
            self.error.setText("Не выбрано: " + ", ".join(empty) + ".")
            return
        self.accept()


class GroupDialog(QDialog):
    """Состав группы и откуда взялась её стоимость."""

    def __init__(self, group: Group, result: AnalysisResult, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Группа {group.id}")
        self.resize(1120, 540)
        members = sorted(
            (result.results[i] for i in group.indices),
            key=lambda res: (res.order.date is None, res.order.date, res.order.index),
        )
        orders = [res.order for res in members]
        cities = " → ".join(dict.fromkeys(order.city for order in orders))
        pallets = sum(order.pallets for order in orders)
        weight = sum(order.weight for order in orders)

        facts = QGridLayout()
        facts.setHorizontalSpacing(28)
        facts.setVerticalSpacing(6)
        rows = [
            ("Маршрут", cities),
            ("Даты ППС", fmt.day_range([order.date for order in orders if order.date])),
            ("Транспорт", str(group.trucks).replace(" x ", " × ")),
            ("Груз", f"{fmt.quantity(pallets)} паллет, {fmt.number(weight)} кг"),
            ("Стоимость", self._cost_text(group)),
            ("По отдельности", fmt.money(group.separate_cost)),
            ("Паллетами", fmt.money(group.pallet_cost)),
        ]
        if group.savings > 0.005:
            rows.insert(6, ("Экономия", fmt.money(group.savings)))
        for position, (caption, value) in enumerate(rows):
            name = QLabel(caption)
            name.setObjectName("muted")
            text = QLabel(value)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            facts.addWidget(name, position // 2, (position % 2) * 2)
            facts.addWidget(text, position // 2, (position % 2) * 2 + 1)
        facts.setColumnStretch(1, 1)
        facts.setColumnStretch(3, 1)

        headers = [
            "Заказ №",
            "Получатель",
            "Город",
            "Дата ППС",
            "Отгрузка",
            "Паллет",
            "Вес, кг",
            "Стоимость",
            "Паллетами",
            "Адрес доставки",
        ]
        numeric = {5, 6, 7, 8}
        table = QTableWidget(len(members), len(headers))
        table.setHorizontalHeaderLabels(headers)
        for column in range(len(headers)):
            side = Qt.AlignmentFlag.AlignRight if column in numeric else Qt.AlignmentFlag.AlignLeft
            table.horizontalHeaderItem(column).setTextAlignment(
                side | Qt.AlignmentFlag.AlignVCenter
            )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        for row, res in enumerate(members):
            order = res.order
            values = [
                order.order_num,
                order.recipient or fmt.DASH,
                order.city,
                fmt.day(order.date),
                fmt.day(order.shipment_date),
                fmt.quantity(order.pallets),
                fmt.number(order.weight),
                fmt.money(res.cost, 2),
                fmt.money(res.pallet_cost, 2),
                order.delivery_address,
            ]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column in numeric:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                table.setItem(row, column, item)
        table.resizeColumnsToContents()
        table.horizontalHeader().setSectionResizeMode(
            len(headers) - 1, QHeaderView.ResizeMode.Stretch
        )
        self.table = table

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Закрыть")
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(_title(f"Группа {group.id} · {group.method.label}"))
        layout.addLayout(facts)
        layout.addWidget(table, 1)
        layout.addWidget(buttons)

    @staticmethod
    def _cost_text(group: Group) -> str:
        if group.markup != 1.0 and group.base_cost:
            markup = f"{group.markup:.2f}".replace(".", ",")
            return (
                f"{fmt.money(group.cost)} = {fmt.money(group.base_cost)} × {markup} "
                f"({group.markup_reason})"
            )
        return fmt.money(group.cost)


class WarningsDialog(QDialog):
    def __init__(self, warnings: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Предупреждения")
        self.resize(640, 360)
        text = QPlainTextEdit("\n\n".join(warnings))
        text.setReadOnly(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Закрыть")
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(_title("На что обратить внимание"))
        layout.addWidget(text, 1)
        layout.addWidget(buttons)

"""Главное окно: держит данные и связывает левую колонку, расчёт и дерево результатов."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
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
from ..models import AnalysisResult
from ..pricing import Tariffs
from ..report import export_xlsx
from ..sample import generate_sample
from . import formatting as fmt
from .dialogs import ColumnsDialog, GroupDialog, SettingsDialog, WarningsDialog
from .results_panel import ResultsPanel
from .sidebar import Sidebar
from .theme import apply_theme, system_theme
from .widgets import dropped_excel_files
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
        colors = apply_theme(QApplication.instance(), self.theme)

        self.table: OrdersTable | None = None
        self.orders_path: Path | None = None
        self.tariffs: Tariffs | None = None
        self.tariffs_name = ""
        self.result: AnalysisResult | None = None
        self.worker: AnalysisWorker | None = None

        self.sidebar = Sidebar()
        self.panel = ResultsPanel(colors)
        self._connect()
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.panel, 1)
        self.setCentralWidget(root)
        self._refresh()

    def _connect(self) -> None:
        side = self.sidebar
        side.ordersDropped.connect(self.open_orders)
        side.tariffsDropped.connect(self.open_tariffs)
        side.chooseOrders.connect(self.choose_orders)
        side.chooseTariffs.connect(self.choose_tariffs)
        side.editColumns.connect(self.edit_columns)
        side.editSettings.connect(self.edit_settings)
        side.runRequested.connect(self.start_analysis)
        side.cancelRequested.connect(self.cancel_analysis)
        side.exportRequested.connect(self.export)
        side.sampleRequested.connect(self.load_sample)
        side.themeToggled.connect(self.toggle_theme)
        self.panel.groupOpened.connect(self.show_group)
        self.panel.warningsRequested.connect(self.show_warnings)

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
        self._drop_result("Правила изменены. Запустите расчёт заново." if self.table else "")

    def toggle_theme(self) -> None:
        self.theme = "light" if self.theme == "dark" else "dark"
        self.panel.set_colors(apply_theme(QApplication.instance(), self.theme))
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

    def open_orders(
        self, path: str | Path, overrides: Mapping[str, str | None] | None = None
    ) -> bool:
        """Читает заказы. Если колонки не определились, спрашивает их и пробует ещё раз."""
        path = Path(path)
        overrides = dict(overrides or {})
        sheet = None
        while True:
            try:
                with _Busy():
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
        self.table, self.orders_path = table, path
        # Тарифы часто лежат в той же книге на соседних листах.
        if self.tariffs is None:
            self.open_tariffs(path, quiet=True)
        self._drop_result()
        return True

    def open_tariffs(self, path: str | Path, quiet: bool = False) -> bool:
        path = Path(path)
        try:
            with _Busy():
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
        self.orders_path = None
        self.tariffs = tariffs_from_frames(data.direct, data.pallet)
        self.tariffs_name = "Пример"
        self._drop_result("Открыт пример с выдуманными заказами. Нажмите «Рассчитать».")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.worker is None and dropped_excel_files(event):
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
        self.worker.progress.connect(self.sidebar.show_progress)
        self.worker.succeeded.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.finished.connect(self._on_thread_finished)
        self.sidebar.start_progress()
        self.worker.start()
        self._refresh()

    def cancel_analysis(self) -> None:
        if self.worker is not None:
            self.worker.cancel()

    def _on_done(self, result: AnalysisResult) -> None:
        self.result = result
        summary = result.summary()
        self.panel.status = (
            f"Готово: {fmt.plural(summary.groups, 'группа', 'группы', 'групп')}, "
            f"экономия {fmt.money(summary.savings)}"
        )
        self.panel.show_rows(self.table.orders if self.table else (), result)

    def _on_failed(self, message: str) -> None:
        self.panel.status = "Расчёт не выполнен"
        self._say(message)

    def _on_cancelled(self) -> None:
        self.panel.status = "Расчёт остановлен"

    def _on_thread_finished(self) -> None:
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.deleteLater()
        self._refresh()

    def _drop_result(self, status: str = "") -> None:
        """Данные или правила изменились: старый результат больше не действителен."""
        self.result = None
        self.panel.status = status
        self.panel.show_rows(self.table.orders if self.table else (), None)
        self._refresh()

    # ---------- результат ----------

    def show_group(self, group_id: int) -> None:
        if self.result is not None:
            GroupDialog(self.result.group_by_id()[group_id], self.result, self).exec()

    def show_warnings(self) -> None:
        if self.result and self.result.warnings:
            WarningsDialog(self.result.warnings, self).exec()

    def export(self) -> None:
        if self.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить результат", "result.xlsx", EXCEL_FILTER
        )
        if path:
            self.export_to(path)

    def export_to(self, path: str | Path) -> bool:
        if self.result is None:
            return False
        try:
            with _Busy():
                saved = export_xlsx(self.result, path)
        except DataError as exc:
            self._say(str(exc))
            return False
        self.panel.status = f"Результат сохранён: {saved.name}"
        self.panel.update_status()
        return True

    # ---------- состояние ----------

    def _refresh(self) -> None:
        """Приводит подписи и доступность кнопок к текущим данным."""
        side = self.sidebar
        side.show_orders(self.table, self.orders_path.name if self.orders_path else "")
        side.show_tariffs(self.tariffs, self.tariffs_name)
        side.show_rules(self.settings)
        side.show_run_state(
            ready=self.table is not None and self.tariffs is not None,
            running=self.worker is not None,
            has_result=self.result is not None,
            dark=self.theme == "dark",
        )
        self.panel.update_status()

    def _say(self, text: str) -> None:
        QMessageBox.warning(self, "Оптимизатор доставки", text)

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(5000)
        super().closeEvent(event)


class _Busy:
    """Курсор ожидания на время чтения или записи файла."""

    def __enter__(self) -> None:
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def __exit__(self, *exc) -> None:
        QGuiApplication.restoreOverrideCursor()

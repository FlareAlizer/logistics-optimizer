"""Окно целиком, без экрана: загрузка, расчёт в потоке, отбор, выгрузка."""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QEventLoop, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from logistics_optimizer import Method, Settings
from logistics_optimizer.config import GroupingRules
from logistics_optimizer.sample import generate_sample
from logistics_optimizer.ui.dialogs import ColumnsDialog, GroupDialog, SettingsDialog
from logistics_optimizer.ui.main_window import MainWindow
from logistics_optimizer.ui.results_model import COLUMNS, ERRORS, SORT_ROLE


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def messages(monkeypatch):
    shown = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda parent, title, text, *a: shown.append(text))
    )
    return shown


@pytest.fixture
def window(app, messages):
    window = MainWindow(config_dir=None, theme="light")
    yield window
    window.close()


def run_analysis(window: MainWindow) -> None:
    loop = QEventLoop()
    window.start_analysis()
    window.worker.finished.connect(loop.quit)
    QTimer.singleShot(60_000, loop.quit)
    loop.exec()


def test_empty_window_waits_for_files(window):
    assert not window.sidebar.run_button.isEnabled()
    assert not window.sidebar.export_button.isEnabled()
    assert window.panel.stack.currentIndex() == 0
    assert window.panel.city_filter.itemText(0) == "Все города"


def test_files_analysis_filters_and_export(window, messages, tmp_path):
    orders_path, tariffs_path = generate_sample(seed=3, n_orders=120, days=8).save(tmp_path)
    assert window.open_orders(orders_path)
    assert not window.sidebar.run_button.isEnabled()  # тарифов ещё нет
    assert window.open_tariffs(tariffs_path)
    assert window.sidebar.run_button.isEnabled()
    panel = window.panel
    assert panel.proxy.rowCount() == 120  # до расчёта заказы идут плоским списком

    run_analysis(window)
    assert messages == []
    result = window.result
    assert result is not None and result.groups
    singles = sum(1 for res in result.results if res.group == 0)
    assert panel.proxy.rowCount() == len(result.groups) + singles
    assert panel.proxy.visible_orders() == 120
    assert panel.stat_savings.value.text().endswith("₽")
    assert window.sidebar.run_button.text() == "Пересчитать"

    panel.groups_only.setChecked(True)
    assert panel.proxy.rowCount() == len(result.groups)
    panel.groups_only.setChecked(False)
    panel.method_filter.setCurrentIndex(panel.method_filter.findData(Method.PALLET))
    pallet_rows = panel.proxy.rowCount()
    assert 0 < pallet_rows < len(result.groups) + singles
    panel.method_filter.setCurrentIndex(0)
    first = result.results[0].order
    panel.search.setText(first.order_num)
    assert panel.proxy.rowCount() == 1
    panel.search.clear()

    cost_column = next(i for i, column in enumerate(COLUMNS) if column.key == "cost")
    panel.tree.sortByColumn(cost_column, Qt.SortOrder.DescendingOrder)
    shown = [panel.proxy.index(row, cost_column).data(SORT_ROLE) for row in range(5)]
    assert shown == sorted(shown, reverse=True)
    assert shown[0] == max(group.cost for group in result.groups)

    assert window.export_to(tmp_path / "result.xlsx")
    assert (tmp_path / "result.xlsx").stat().st_size > 5000
    dialog = GroupDialog(result.groups[0], result, window)
    assert dialog.table.rowCount() == len(result.groups[0].indices)


def test_sample_button_and_stale_result(window, monkeypatch):
    window.load_sample()
    assert window.table is not None and window.tariffs is not None
    run_analysis(window)
    assert window.result is not None

    new_settings = Settings(rules=GroupingRules(radius_km=100))

    def accept(dialog: SettingsDialog) -> bool:
        dialog.result_settings = new_settings
        return True

    monkeypatch.setattr(SettingsDialog, "exec", accept)
    window.edit_settings()
    assert window.settings == new_settings
    assert window.result is None  # правила поменялись, старый расчёт сброшен
    assert not window.sidebar.export_button.isEnabled()
    assert "100" in window.sidebar.rules_card.hint.text()


def test_errors_are_shown_as_plain_messages(window, messages, tmp_path):
    broken = tmp_path / "broken.xlsx"
    broken.write_text("не эксель", encoding="utf-8")
    assert not window.open_orders(broken)
    assert not window.open_tariffs(tmp_path / "missing.xlsx")
    assert len(messages) == 2
    assert all("Traceback" not in text for text in messages)


def test_errors_filter_appears_only_with_errors(window, tmp_path):
    data = generate_sample(seed=5, n_orders=60, days=5, n_cities=8)
    data.direct.drop(index=data.direct.index[0], inplace=True)
    orders_path, tariffs_path = data.save(tmp_path)
    window.open_orders(orders_path)
    window.open_tariffs(tariffs_path)
    run_analysis(window)
    panel = window.panel
    assert window.result.summary().errors > 0
    assert panel.banner.isVisibleTo(window)
    position = panel.method_filter.findData(ERRORS)
    assert position > 0
    panel.method_filter.setCurrentIndex(position)
    assert panel.proxy.visible_orders() == window.result.summary().errors


def test_settings_dialog_round_trip(app):
    settings = Settings(rules=GroupingRules(max_cities=2, simple_group_savings_threshold=0.2))
    dialog = SettingsDialog(settings)
    dialog._save()
    assert dialog.result_settings == settings


def test_columns_dialog_requires_mandatory_fields(app):
    dialog = ColumnsDialog(["КУДА", "МЕСТ", "ЗАКАЗАНО КГ"], missing=["city", "pallets"])
    dialog._apply()
    assert "город" in dialog.error.text()
    assert dialog.mapping()["weight_kg"] == "ЗАКАЗАНО КГ"

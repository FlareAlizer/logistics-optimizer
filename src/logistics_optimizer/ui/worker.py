"""Расчёт в отдельном потоке, чтобы окно не замирало."""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence

from PyQt6.QtCore import QThread, pyqtSignal

from ..config import Settings
from ..geo import CityIndex
from ..grouping import AnalysisCancelled, optimize
from ..models import Order
from ..pricing import Tariffs

log = logging.getLogger(__name__)


class AnalysisWorker(QThread):
    progress = pyqtSignal(int, str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(
        self,
        orders: Sequence[Order],
        tariffs: Tariffs,
        settings: Settings,
        cities: CityIndex,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._orders = orders
        self._tariffs = tariffs
        self._settings = settings
        self._cities = cities
        self._stop = threading.Event()

    def cancel(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            result = optimize(
                self._orders,
                self._tariffs,
                self._settings,
                self._cities,
                progress=self.progress.emit,
                should_cancel=self._stop.is_set,
            )
        except AnalysisCancelled:
            self.cancelled.emit()
        except Exception as exc:
            log.exception("Расчёт упал")
            self.failed.emit(
                "Расчёт не удалось довести до конца. Проверьте, что в колонках паллет, веса "
                f"и дат нет посторонних значений.\n\nТехническая причина: {exc}"
            )
        else:
            self.succeeded.emit(result)

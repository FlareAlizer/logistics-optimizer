"""Запуск окна."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWidgets import QApplication

from .main_window import MainWindow

APP_NAME = "logistics-optimizer"


def config_dir() -> Path:
    """Папка с настройками пользователя: settings.json и, если нужен, свой cities.csv."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(base)


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    window = MainWindow(config_dir())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from helpers import TARIFFS, make_orders
from logistics_optimizer import Settings, load_cities, optimize
from logistics_optimizer.models import AnalysisResult


@pytest.fixture(scope="session")
def cities():
    return load_cities()


@pytest.fixture
def run(cities):
    def _run(*rows: tuple, settings: Settings | None = None, **kwargs) -> AnalysisResult:
        return optimize(make_orders(*rows), TARIFFS, settings or Settings(), cities, **kwargs)

    return _run

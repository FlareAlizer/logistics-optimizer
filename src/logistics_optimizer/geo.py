"""Координаты городов и расстояние между ними по эллипсоиду WGS-84."""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping
from importlib import resources
from pathlib import Path

from .models import city_key

Coords = tuple[float, float]

_WGS84_A = 6378137.0
_WGS84_F = 1 / 298.257223563
_WGS84_B = _WGS84_A * (1 - _WGS84_F)


def geodesic_km(first: Coords, second: Coords) -> float:
    """Расстояние по формуле Винсенти. Для антиподов откатывается к сфере."""
    lat1, lon1 = first
    lat2, lon2 = second
    if first == second:
        return 0.0
    u1 = math.atan((1 - _WGS84_F) * math.tan(math.radians(lat1)))
    u2 = math.atan((1 - _WGS84_F) * math.tan(math.radians(lat2)))
    lon_diff = math.radians(lon2 - lon1)
    sin_u1, cos_u1 = math.sin(u1), math.cos(u1)
    sin_u2, cos_u2 = math.sin(u2), math.cos(u2)

    lam = lon_diff
    for _ in range(200):
        sin_lam, cos_lam = math.sin(lam), math.cos(lam)
        sin_sigma = math.hypot(cos_u2 * sin_lam, cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lam)
        if sin_sigma == 0:
            return 0.0
        cos_sigma = sin_u1 * sin_u2 + cos_u1 * cos_u2 * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cos_u1 * cos_u2 * sin_lam / sin_sigma
        cos_sq_alpha = 1 - sin_alpha**2
        cos_2sigma_m = cos_sigma - 2 * sin_u1 * sin_u2 / cos_sq_alpha if cos_sq_alpha else 0.0
        c = _WGS84_F / 16 * cos_sq_alpha * (4 + _WGS84_F * (4 - 3 * cos_sq_alpha))
        previous = lam
        lam = lon_diff + (1 - c) * _WGS84_F * sin_alpha * (
            sigma + c * sin_sigma * (cos_2sigma_m + c * cos_sigma * (-1 + 2 * cos_2sigma_m**2))
        )
        if abs(lam - previous) < 1e-12:
            break
    else:
        return _haversine_km(first, second)

    u_sq = cos_sq_alpha * (_WGS84_A**2 - _WGS84_B**2) / _WGS84_B**2
    big_a = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq)))
    big_b = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))
    delta_sigma = (
        big_b
        * sin_sigma
        * (
            cos_2sigma_m
            + big_b
            / 4
            * (
                cos_sigma * (-1 + 2 * cos_2sigma_m**2)
                - big_b / 6 * cos_2sigma_m * (-3 + 4 * sin_sigma**2) * (-3 + 4 * cos_2sigma_m**2)
            )
        )
    )
    return _WGS84_B * big_a * (sigma - delta_sigma) / 1000


def _haversine_km(first: Coords, second: Coords) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*first, *second))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


class CityIndex:
    """Справочник координат. Расстояния между парами городов запоминает."""

    def __init__(self, coords: Mapping[str, Coords]) -> None:
        self._coords = {city_key(name): value for name, value in coords.items()}
        self._distances: dict[tuple[str, str], float] = {}

    def __len__(self) -> int:
        return len(self._coords)

    def __contains__(self, city: str) -> bool:
        return city_key(city) in self._coords

    def get(self, city: str) -> Coords | None:
        return self._coords.get(city_key(city))

    def distance_km(self, first: str, second: str) -> float:
        """Расстояние между городами. Если координат нет, считаем город недостижимым."""
        a, b = city_key(first), city_key(second)
        pair = (a, b) if a <= b else (b, a)
        cached = self._distances.get(pair)
        if cached is not None:
            return cached
        start, end = self._coords.get(a), self._coords.get(b)
        distance = math.inf if start is None or end is None else geodesic_km(start, end)
        self._distances[pair] = distance
        return distance

    def missing(self, cities: Iterable[str]) -> list[str]:
        return sorted({city for city in cities if city_key(city) not in self._coords})

    def merged(self, extra: Mapping[str, Coords]) -> CityIndex:
        return CityIndex({**self._coords, **extra})


def read_cities(path: Path | str) -> dict[str, Coords]:
    """Читает CSV с колонками city, lat, lon."""
    coords: dict[str, Coords] = {}
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                coords[row["city"].strip()] = (float(row["lat"]), float(row["lon"]))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
    return coords


def load_cities(extra: Path | str | None = None) -> CityIndex:
    """Встроенный справочник. Файл extra дополняет его и перекрывает совпадения."""
    builtin = resources.files("logistics_optimizer") / "data" / "cities.csv"
    with resources.as_file(builtin) as path:
        index = CityIndex(read_cities(path))
    if extra is not None and Path(extra).is_file():
        index = index.merged(read_cities(extra))
    return index

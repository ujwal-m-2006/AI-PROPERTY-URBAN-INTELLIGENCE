"""City registry — multi-city support.

Added for the Chennai expansion. Every city-aware call defaults to
``bengaluru``, so all existing endpoints and services behave exactly as before.

Hard rule enforced by this module: Bengaluru and Chennai never share a dataset,
a preprocessing pipeline or a model directory. Property prices between the two
cities are not comparable at the row level and must never be pooled for
training.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "processed"
MODELS = ROOT / "models"

CityId = Literal["bengaluru", "chennai"]
DEFAULT_CITY: CityId = "bengaluru"


@dataclass(frozen=True, slots=True)
class City:
    id: str
    name: str
    name_local: str
    authority: str
    authority_short: str

    # GIS
    wards_file: str
    zones_file: str | None
    ward_count: int
    subdivision_label: str          # what the corporation calls its tier-2 unit
    bbox: tuple[float, float, float, float]  # W, S, E, N
    centre: tuple[float, float]     # lng, lat

    # ML
    dataset_file: str
    amenities_file: str
    model_dir: str

    # Honest description of what the price target actually is
    price_target: str
    price_target_note: str

    supports_temporal: bool = False
    notes: list[str] = field(default_factory=list)


BENGALURU = City(
    id="bengaluru",
    name="Greater Bengaluru",
    name_local="ಬೃಹತ್ ಬೆಂಗಳೂರು",
    authority="Greater Bengaluru Authority",
    authority_short="GBA",
    wards_file="gba_wards.geojson",
    zones_file="gba_corporations.geojson",
    ward_count=369,
    subdivision_label="City Corporation",
    bbox=(77.30, 12.70, 77.90, 13.25),
    centre=(77.5946, 12.9716),
    dataset_file="bengaluru_house_data.csv",
    amenities_file="osm_amenities.json",
    model_dir="bengaluru",
    price_target="asking price per sq.ft",
    price_target_note=(
        "Listing/asking prices. Karnataka does not publish transaction prices, "
        "so this target carries a systematic upward bias of unknown size."
    ),
    supports_temporal=False,
    notes=[
        "5 city corporations, 369 wards, final delimitation notified 19 Nov 2025",
        "Listing dataset has no sale dates — future-price modelling is not "
        "supportable from this data",
    ],
)

CHENNAI = City(
    id="chennai",
    name="Chennai",
    name_local="சென்னை",
    authority="Greater Chennai Corporation",
    authority_short="GCC",
    wards_file="chennai_wards.geojson",
    zones_file="chennai_zones.geojson",
    ward_count=200,
    subdivision_label="Zone",
    bbox=(80.10, 12.83, 80.35, 13.25),
    centre=(80.2707, 13.0827),
    dataset_file="chennai_house_price.csv",
    amenities_file="osm_amenities_chennai.json",
    model_dir="chennai",
    price_target="recorded sale price",
    price_target_note=(
        "Recorded sale prices with registration fee and commission — closer to "
        "transaction value than the Bengaluru asking-price data. Sale dates span "
        "roughly 2004-2015, so absolute levels are historical."
    ),
    supports_temporal=True,
    notes=[
        "200 wards across 15 zones, GCC ward map 2022",
        "Dataset carries DATE_SALE and DATE_BUILD — supports property age and "
        "time-aware modelling",
    ],
)

REGISTRY: dict[str, City] = {c.id: c for c in (BENGALURU, CHENNAI)}


def get(city_id: str | None = None) -> City:
    """Resolve a city, defaulting to Bengaluru (the primary city)."""
    key = (city_id or DEFAULT_CITY).strip().lower()
    if key not in REGISTRY:
        raise KeyError(
            f"unknown city {city_id!r}; available: {', '.join(sorted(REGISTRY))}"
        )
    return REGISTRY[key]


def all_cities() -> list[City]:
    # Bengaluru first — it is the primary city.
    return [BENGALURU, CHENNAI]


def wards_path(city: City) -> Path:
    return DATA / city.wards_file


def zones_path(city: City) -> Path | None:
    return DATA / city.zones_file if city.zones_file else None


def dataset_path(city: City) -> Path:
    return ROOT / "data" / "raw" / city.dataset_file


def amenities_path(city: City) -> Path:
    return DATA / city.amenities_file


def model_path(city: City, filename: str) -> Path:
    return MODELS / city.model_dir / filename


def in_bbox(city: City, lng: float, lat: float) -> bool:
    w, s, e, n = city.bbox
    return w <= lng <= e and s <= lat <= n


def city_for_point(lng: float, lat: float) -> City | None:
    """Which city's coverage contains this point, if any."""
    for c in all_cities():
        if in_bbox(c, lng, lat):
            return c
    return None

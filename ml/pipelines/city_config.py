"""Per-city dataset configuration and cleaning.

Bengaluru and Chennai have completely different schemas, different targets and
different failure modes, so each gets its own cleaning function. They are never
concatenated: prices in the two cities are not comparable at row level, and a
model trained on pooled data would be meaningless for both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"


@dataclass(frozen=True)
class CityConfig:
    id: str
    display: str
    dataset_file: str
    locality_column: str
    amenities_file: str
    wards_file: str
    target: str
    target_label: str
    target_note: str
    source_url: str
    tier: str
    clean: Callable[[pd.DataFrame], tuple[pd.DataFrame, list[str]]]
    numeric_features: list[str] = field(default_factory=list)
    categorical_features: list[str] = field(default_factory=list)
    supports_temporal: bool = False
    date_column: str | None = None

    # Columns that are the target, a component of it, or otherwise unavailable
    # at prediction time. Excluded from EDA correlations and hard-blocked from
    # the feature matrix — a correlation of 0.72 between `price` and
    # `price_per_sqft` is arithmetic, not a finding, and an examiner will ask.
    leakage_columns: list[str] = field(default_factory=list)

    # What kind of time signal the data actually has:
    #   "sale_year"       real transaction dates -> a market index is possible
    #   "possession_year" completion timing only -> NO market index is possible
    #   None              no time signal at all
    temporal_basis: str | None = None


# ---------------------------------------------------------------- Bengaluru

MIN_PSF_BLR, MAX_PSF_BLR = 1_500, 40_000
MIN_SQFT_PER_ROOM = 300


def _parse_sqft(value: object) -> float | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip()
    if "-" in text:
        parts = [p.strip() for p in text.split("-")]
        try:
            return (float(parts[0]) + float(parts[1])) / 2
        except (ValueError, IndexError):
            return None
    m = re.match(r"^([\d.]+)\s*(.*)$", text)
    if not m:
        return None
    try:
        n = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2).lower().replace(" ", "").replace(".", "")
    factors = {"sqmeter": 10.7639, "perch": 272.25, "sqyards": 9.0, "acres": 43560.0,
               "cents": 435.6, "guntha": 1089.0, "grounds": 2400.0}
    return n * factors.get(unit, 1.0)


def _parse_rooms(value: object) -> int | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    m = re.search(r"(\d+)", str(value))
    return int(m.group(1)) if m else None


def clean_bengaluru(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    log: list[str] = [f"loaded {len(df):,} raw listing rows"]

    df["sqft"] = df["total_sqft"].map(_parse_sqft)
    df["rooms"] = df["size"].map(_parse_rooms)
    df["price_inr"] = pd.to_numeric(df["price"], errors="coerce") * 100_000  # lakhs

    before = len(df)
    df = df.dropna(subset=["sqft", "rooms", "price_inr", "location"])
    log.append(f"dropped {before - len(df):,} rows missing sqft / rooms / price / location")

    before = len(df)
    df = df[df["sqft"] / df["rooms"] >= MIN_SQFT_PER_ROOM]
    log.append(f"dropped {before - len(df):,} rows under {MIN_SQFT_PER_ROOM} sq.ft per room")

    df["price_per_sqft"] = df["price_inr"] / df["sqft"]

    before = len(df)
    df = df[(df["price_per_sqft"] >= MIN_PSF_BLR) & (df["price_per_sqft"] <= MAX_PSF_BLR)]
    log.append(f"dropped {before - len(df):,} rows outside Rs {MIN_PSF_BLR:,}-{MAX_PSF_BLR:,}/sq.ft")

    before = len(df)
    stats = df.groupby("location")["price_per_sqft"].agg(["mean", "std", "count"])
    df = df.join(stats, on="location")
    keep = (df["count"] < 5) | (
        (df["price_per_sqft"] >= df["mean"] - 2 * df["std"].fillna(0))
        & (df["price_per_sqft"] <= df["mean"] + 2 * df["std"].fillna(0))
    )
    df = df[keep].drop(columns=["mean", "std", "count"])
    log.append(f"dropped {before - len(df):,} rows beyond 2 SD of their locality mean")

    df["location"] = df["location"].astype(str).str.strip()
    df["bath"] = pd.to_numeric(df["bath"], errors="coerce")
    df["balcony"] = pd.to_numeric(df["balcony"], errors="coerce")
    df["area_type"] = df["area_type"].astype(str).str.strip()
    df["ready_to_move"] = (
        df["availability"].astype(str).str.strip().str.lower() == "ready to move"
    ).astype(int)

    # `availability` holds either "Ready To Move" or a possession month-year
    # such as "19-Dec". That is a POSSESSION date, not a sale date: every price
    # in this dataset was observed at one scrape, so variation across possession
    # years reflects the under-construction discount, not market appreciation.
    poss = df["availability"].astype(str).str.strip().str.extract(
        r"^(\d{2})-([A-Za-z]{3})$")
    df["possession_year"] = pd.to_numeric(poss[0], errors="coerce") + 2000
    n_poss = int(df["possession_year"].notna().sum())
    log.append(
        f"parsed possession year for {n_poss:,} rows (possession timing, NOT sale date)"
    )

    # Engineered ratios (no target leakage — derived from inputs only).
    df["area_per_room"] = df["sqft"] / df["rooms"]
    df["bath_per_room"] = df["bath"] / df["rooms"]

    log.append(f"final: {len(df):,} rows")
    return df.reset_index(drop=True), log


BENGALURU = CityConfig(
    id="bengaluru",
    display="Greater Bengaluru",
    dataset_file="bengaluru_house_data.csv",
    locality_column="location",
    amenities_file="osm_amenities.json",
    wards_file="gba_wards.geojson",
    target="price_per_sqft",
    target_label="asking price per sq.ft (INR)",
    target_note=(
        "ASKING price from listings. Karnataka does not publish transaction "
        "prices, so this carries a systematic upward bias of unknown size."
    ),
    source_url=(
        "https://raw.githubusercontent.com/dphi-official/Datasets/master/"
        "Bengaluru_House_Data.csv"
    ),
    tier="T4",
    clean=clean_bengaluru,
    numeric_features=[
        "sqft", "rooms", "bath", "balcony", "ready_to_move",
        "area_per_room", "bath_per_room",
    ],
    categorical_features=["area_type"],
    supports_temporal=False,
    leakage_columns=["price", "price_inr", "price_per_sqft", "total_sqft", "size"],
    temporal_basis="possession_year",
)


# ------------------------------------------------------------------ Chennai

MIN_PSF_CHN, MAX_PSF_CHN = 500, 30_000


def clean_chennai(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    log: list[str] = [f"loaded {len(df):,} raw sale records"]

    df.columns = [c.strip().upper() for c in df.columns]

    # This dataset is known for typo'd categoricals; normalise rather than drop.
    fixes = {
        "AREA": {"Karapakam": "Karapakkam", "Ana Nagar": "Anna Nagar",
                 "Ann Nagar": "Anna Nagar", "Adyr": "Adyar", "Velchery": "Velachery",
                 "KKNagar": "KK Nagar", "TNagar": "T Nagar", "Chrompt": "Chrompet",
                 "Chrmpet": "Chrompet", "Chormpet": "Chrompet"},
        "SALE_COND": {"Ab Normal": "AbNormal", "Adj Land": "AdjLand",
                      "PartiaLl": "Partial", "Partiall": "Partial"},
        "PARK_FACIL": {"Noo": "No"},
        "BUILDTYPE": {"Comercial": "Commercial", "Other": "Others"},
        "UTILITY_AVAIL": {"All Pub": "AllPub", "NoSewr ": "NoSeWa"},
        "STREET": {"Pavd": "Paved", "NoAccess": "No Access"},
    }
    for col, mapping in fixes.items():
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().replace(mapping)
    log.append("normalised known category typos (AREA, SALE_COND, BUILDTYPE, ...)")

    for c in ("INT_SQFT", "N_BEDROOM", "N_BATHROOM", "N_ROOM", "SALES_PRICE",
              "DIST_MAINROAD", "REG_FEE", "COMMIS", "QS_OVERALL"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    for c in ("DATE_SALE", "DATE_BUILD"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], format="%d-%m-%Y", errors="coerce")

    before = len(df)
    df = df.dropna(subset=["INT_SQFT", "SALES_PRICE", "AREA"])
    log.append(f"dropped {before - len(df):,} rows missing sqft / price / area")

    # Target: price per sq.ft, consistent with the Bengaluru model.
    df["price_per_sqft"] = df["SALES_PRICE"] / df["INT_SQFT"]

    before = len(df)
    df = df[(df["price_per_sqft"] >= MIN_PSF_CHN) & (df["price_per_sqft"] <= MAX_PSF_CHN)]
    log.append(f"dropped {before - len(df):,} rows outside Rs {MIN_PSF_CHN:,}-{MAX_PSF_CHN:,}/sq.ft")

    before = len(df)
    df = df.drop_duplicates(subset=["PRT_ID"]) if "PRT_ID" in df.columns else df
    log.append(f"dropped {before - len(df):,} duplicate property ids")

    # Real temporal features — this dataset supports them, Bengaluru's does not.
    if "DATE_SALE" in df.columns and "DATE_BUILD" in df.columns:
        age = (df["DATE_SALE"] - df["DATE_BUILD"]).dt.days / 365.25
        df["property_age_years"] = age.where((age >= 0) & (age < 120))
        df["sale_year"] = df["DATE_SALE"].dt.year
        df["sale_month"] = df["DATE_SALE"].dt.month
        log.append(
            f"derived property_age_years (median "
            f"{df['property_age_years'].median():.1f} yr) and sale_year "
            f"({int(df['sale_year'].min())}-{int(df['sale_year'].max())})"
        )

    df["N_BEDROOM"] = df["N_BEDROOM"].fillna(df["N_BEDROOM"].median())
    df["N_BATHROOM"] = df["N_BATHROOM"].fillna(df["N_BATHROOM"].median())
    df["area_per_room"] = df["INT_SQFT"] / df["N_ROOM"].replace(0, np.nan)
    df["bath_per_bedroom"] = df["N_BATHROOM"] / df["N_BEDROOM"].replace(0, np.nan)
    df["AREA"] = df["AREA"].astype(str).str.strip()

    log.append(f"final: {len(df):,} rows")
    return df.reset_index(drop=True), log


CHENNAI = CityConfig(
    id="chennai",
    display="Chennai",
    dataset_file="chennai_house_price.csv",
    locality_column="AREA",
    amenities_file="osm_amenities_chennai.json",
    wards_file="chennai_wards.geojson",
    target="price_per_sqft",
    target_label="recorded sale price per sq.ft (INR)",
    target_note=(
        "RECORDED SALE price with registration fee and commission — closer to "
        "transaction value than the Bengaluru asking-price data. Sales span "
        "roughly 2004-2015, so absolute levels are historical."
    ),
    source_url=(
        "https://raw.githubusercontent.com/Ravi8149/"
        "Chennai-House-Price-Prediction/HEAD/chennai-house-price.csv"
    ),
    tier="T4",
    clean=clean_chennai,
    numeric_features=[
        "INT_SQFT", "N_BEDROOM", "N_BATHROOM", "N_ROOM", "DIST_MAINROAD",
        "QS_OVERALL", "property_age_years", "sale_year",
        "area_per_room", "bath_per_bedroom",
    ],
    categorical_features=["BUILDTYPE", "SALE_COND", "PARK_FACIL",
                          "UTILITY_AVAIL", "STREET", "MZZONE"],
    supports_temporal=True,
    date_column="DATE_SALE",
    leakage_columns=[
        "SALES_PRICE", "price_per_sqft", "REG_FEE", "COMMIS", "INT_SQFT_TOTAL",
    ],
    temporal_basis="sale_year",
)


REGISTRY: dict[str, CityConfig] = {"bengaluru": BENGALURU, "chennai": CHENNAI}


def get(city: str) -> CityConfig:
    key = city.strip().lower()
    if key not in REGISTRY:
        raise KeyError(f"unknown city {city!r}; available: {list(REGISTRY)}")
    return REGISTRY[key]


def load_raw(cfg: CityConfig) -> pd.DataFrame:
    return pd.read_csv(RAW / cfg.dataset_file)

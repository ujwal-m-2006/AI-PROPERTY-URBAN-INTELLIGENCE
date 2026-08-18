"""A shared feature vocabulary for Bengaluru and Chennai.

Cross-city transfer was impossible not for any deep reason but because the two
datasets name the same quantities differently. `sqft` and `INT_SQFT` are the
same measurement; `rooms` and `N_BEDROOM` are the same count. Exactly one column
name — `area_per_room` — happened to match, so a model trained on one city saw
almost nothing it recognised in the other.

WHAT IS AND IS NOT CLAIMED HERE
-------------------------------
Each mapping below is a claim that two columns measure the same thing. Those
claims are stated one by one so they can be disputed individually rather than
hidden inside a rename. Where a mapping would be a stretch it is NOT made:

  * **Categoricals are excluded entirely.** Bengaluru's `area_type`
    (Super built-up / Plot / Carpet) and Chennai's `BUILDTYPE`
    (Commercial / House / Others) are not the same variable, and forcing them
    together would inject a false equivalence into every transfer result.
  * **City-specific columns are dropped, not imputed.** Chennai's
    `property_age_years` has no Bengaluru counterpart. Filling it with a
    constant would let the model learn "constant age means Bengaluru", which is
    city identity leaking in through a feature that claims to be about age.

THE TARGETS STILL DO NOT MATCH
------------------------------
Bengaluru's target is ASKING price per sq.ft; Chennai's is RECORDED SALE price
per sq.ft, over a period ending around 2015. Harmonising the *features* does not
make the *targets* comparable, and no renaming can. That is why the transfer
experiment reports both a raw and a rank-based result — see
`train_cross_city.py`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# --- property features: one row per equivalence claim ----------------------
# shared_name: (bengaluru_column, chennai_column, what the claim is)
PROPERTY_MAP: dict[str, tuple[str, str, str]] = {
    "built_up_sqft": (
        "sqft", "INT_SQFT",
        "Interior/built-up floor area in square feet. Bengaluru's parses from "
        "the messy `total_sqft` string; Chennai's is already numeric.",
    ),
    "bedrooms": (
        "rooms", "N_BEDROOM",
        "Bedroom count. Bengaluru's derives from the '2 BHK' size string, which "
        "is a bedroom count by construction.",
    ),
    "bathrooms": (
        "bath", "N_BATHROOM",
        "Bathroom count. Directly equivalent.",
    ),
    "area_per_room": (
        "area_per_room", "area_per_room",
        "Built-up area divided by bedroom count. The only column that already "
        "shared a name.",
    ),
    "bath_per_bedroom": (
        "bath_per_room", "bath_per_bedroom",
        "Bathrooms per bedroom. Same derivation, different name.",
    ),
}

# --- GIS features: already identical in both cities ------------------------
# These are computed by ml/features/gis_features.py from each city's own OSM
# layer, so the columns match without any mapping. They are the reason a shared
# feature space is worth having at all: 11 of the 16 shared features are urban
# context, which is precisely what the ablation says carries the signal.
GIS_SHARED: list[str] = [
    "metro_distance_m", "railway_distance_m", "bus_distance_m",
    "hospital_distance_m", "school_distance_m", "college_distance_m",
    "govt_office_distance_m", "bank_distance_m", "park_distance_m",
    "supermarket_distance_m", "amenity_count_1km",
]

# Deliberately NOT mapped. Recorded so the exclusions are reviewable.
NOT_MAPPED: dict[str, str] = {
    "area_type / BUILDTYPE": (
        "Bengaluru's area_type is a measurement convention (Super built-up, "
        "Plot, Carpet); Chennai's BUILDTYPE is a use class (Commercial, House). "
        "Different variables that happen to both be categorical."
    ),
    "balcony, ready_to_move": "Bengaluru only; no Chennai counterpart.",
    "N_ROOM, DIST_MAINROAD, QS_OVERALL, property_age_years, sale_year": (
        "Chennai only. property_age_years and sale_year would be especially "
        "damaging to impute — a constant would encode city identity."
    ),
    "SALE_COND, PARK_FACIL, UTILITY_AVAIL, STREET, MZZONE": "Chennai only.",
}

SHARED_FEATURES: list[str] = list(PROPERTY_MAP) + GIS_SHARED


def to_shared(df: pd.DataFrame, city: str) -> pd.DataFrame:
    """Project one city's dataframe onto the shared vocabulary.

    Returns only the shared columns plus the target and grouping key, so a
    caller cannot accidentally train on a city-specific feature.
    """
    if city not in ("bengaluru", "chennai"):
        raise ValueError(f"unknown city: {city}")
    idx = 0 if city == "bengaluru" else 1

    out = pd.DataFrame(index=df.index)
    missing: list[str] = []

    for shared, mapping in PROPERTY_MAP.items():
        source = mapping[idx]
        if source in df.columns:
            out[shared] = pd.to_numeric(df[source], errors="coerce")
        else:
            missing.append(f"{shared} <- {source}")

    for col in GIS_SHARED:
        out[col] = (pd.to_numeric(df[col], errors="coerce")
                    if col in df.columns else pd.NA)

    if missing:
        raise KeyError(
            f"{city}: shared features could not be built from the source "
            f"columns: {missing}. The mapping in PROPERTY_MAP is stale."
        )
    return out


def describe() -> dict[str, Any]:
    """The mapping as data, so the UI and the report can show it."""
    return {
        "shared_feature_count": len(SHARED_FEATURES),
        "property_features": [
            {"shared": k, "bengaluru": v[0], "chennai": v[1], "claim": v[2]}
            for k, v in PROPERTY_MAP.items()
        ],
        "gis_features": GIS_SHARED,
        "gis_note": (
            "Already identical in both cities — computed by the same code from "
            "each city's own OpenStreetMap layer, so no mapping is needed. "
            "11 of the 16 shared features are urban context."
        ),
        "not_mapped": NOT_MAPPED,
        "target_warning": (
            "Harmonising features does NOT make the targets comparable. "
            "Bengaluru's is ASKING price per sq.ft; Chennai's is RECORDED SALE "
            "price per sq.ft over a period ending around 2015. A model "
            "transferred between them is predicting a different quantity, and "
            "the transfer experiment reports that separately from model skill."
        ),
    }

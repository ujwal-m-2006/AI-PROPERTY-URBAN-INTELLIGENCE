"""Content-based property recommendation (Module 16).

A fitted k-nearest-neighbours index over the real cleaned listings for a city,
in a standardised feature space. This IS machine learning — an unsupervised
model fitted to data — as distinct from the weighted indices in analytics.py.

Recommendations never cross cities: a Chennai property is never suggested to a
Bengaluru user. The two markets and the two price definitions are different.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "ml"))

FEATURES = ["sqft", "rooms", "bath", "price_per_sqft"]


def _index(city_id: str) -> dict[str, Any] | None:
    """KNN index for a city, rebuilt if the source dataset changes."""
    from app.services import cities as _c

    try:
        raw = _c.dataset_path(_c.get(city_id))
        stamp = raw.stat().st_mtime if raw.exists() else 0.0
    except Exception:
        stamp = 0.0
    return _build_index(city_id, stamp)


@lru_cache(maxsize=4)
def _build_index(city_id: str, mtime: float) -> dict[str, Any] | None:
    """Build the KNN index once per (city, dataset version), lazily."""
    try:
        import numpy as np
        import pandas as pd
        from sklearn.neighbors import NearestNeighbors
        from sklearn.preprocessing import StandardScaler

        from pipelines import city_config
    except Exception:
        return None

    try:
        cfg = city_config.get(city_id)
        df, _ = cfg.clean(city_config.load_raw(cfg))
    except Exception:
        return None

    # Normalise the two schemas onto one comparable feature space.
    if city_id == "chennai":
        frame = pd.DataFrame({
            "sqft": df["INT_SQFT"],
            "rooms": df["N_ROOM"],
            "bath": df["N_BATHROOM"],
            "price_per_sqft": df["price_per_sqft"],
            "locality": df["AREA"].astype(str),
            "property_type": df.get("BUILDTYPE", pd.Series(["-"] * len(df))).astype(str),
        })
    else:
        frame = pd.DataFrame({
            "sqft": df["sqft"],
            "rooms": df["rooms"],
            "bath": df["bath"],
            "price_per_sqft": df["price_per_sqft"],
            "locality": df["location"].astype(str),
            "property_type": df["area_type"].astype(str),
        })

    frame = frame.dropna(subset=FEATURES).reset_index(drop=True)
    if len(frame) < 20:
        return None

    scaler = StandardScaler()
    matrix = scaler.fit_transform(frame[FEATURES].to_numpy(dtype=float))
    knn = NearestNeighbors(n_neighbors=min(25, len(frame)), metric="euclidean")
    knn.fit(matrix)

    return {"frame": frame, "scaler": scaler, "knn": knn, "np": np}


def is_available(city_id: str) -> bool:
    return _index(city_id) is not None


def recommend(
    city_id: str,
    *,
    sqft: float,
    rooms: int,
    bath: float | None,
    price_per_sqft: float,
    same_locality_only: bool = False,
    locality: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    idx = _index(city_id)
    if idx is None:
        return {
            "available": False,
            "reason": (
                "Recommendation index unavailable — the city dataset could not "
                "be loaded."
            ),
            "results": [],
        }

    np = idx["np"]
    frame, scaler, knn = idx["frame"], idx["scaler"], idx["knn"]

    query = np.array([[sqft, rooms, bath if bath is not None else rooms, price_per_sqft]],
                     dtype=float)
    distances, indices = knn.kneighbors(scaler.transform(query))

    results = []
    for dist, i in zip(distances[0], indices[0]):
        row = frame.iloc[int(i)]
        if same_locality_only and locality and row["locality"].lower() != locality.lower():
            continue
        # Euclidean distance in standardised space -> a bounded similarity.
        results.append({
            "locality": row["locality"],
            "property_type": row["property_type"],
            "sqft": round(float(row["sqft"])),
            "rooms": int(row["rooms"]),
            "bath": None if row["bath"] != row["bath"] else int(row["bath"]),
            "price_per_sqft": round(float(row["price_per_sqft"])),
            "estimated_total": round(float(row["price_per_sqft"] * row["sqft"])),
            "similarity": round(float(1.0 / (1.0 + dist)), 3),
        })
        if len(results) >= limit:
            break

    return {
        "available": True,
        "method": "ML — unsupervised k-nearest neighbours in standardised feature space",
        "features_used": FEATURES,
        "index_size": int(len(frame)),
        "results": results,
        "caveat": (
            "Similar records from the same city's dataset. These are real rows "
            "from the source data, not generated listings, and they are not "
            "currently-available properties."
        ),
    }

"""Guidance value and transaction-price reference.

Two things the platform has always reported as UNAVAILABLE. Handled here as
honestly as the data allows, which is differently for each city.

GUIDANCE VALUE
    Karnataka publishes it on Kaveri and Tamil Nadu on TNREGINET, both
    portal-only with no public API and terms that do not permit scraping. So it
    is NOT fetched. Instead this module keeps a small reference table that a
    user or administrator fills in by looking the value up themselves. Every
    entry records who entered it, when, and from which portal — and is labelled
    MANUAL ENTRY, never VERIFIED.

TRANSACTION PRICE
    Karnataka does not publish transactions, so Bengaluru stays UNAVAILABLE.
    Chennai is different: its dataset IS recorded sale prices, so a locality
    median from it is a genuine transaction reference — historical, but real.
    That asymmetry is reported rather than smoothed over.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services import cities

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data" / "processed" / "guidance_values.json"

METHOD_MANUAL = "MANUAL ENTRY"
METHOD_DATASET = "DATASET AGGREGATE"

PORTALS = {
    "bengaluru": {
        "name": "Kaveri Online Services (Department of Stamps and Registration, Karnataka)",
        "url": "https://kaveri.karnataka.gov.in",
        "how": ("Log in, choose 'Know Your Property Valuation', then select "
                "district, taluk, hobli, village and the property type."),
        "note": ("Guidance value is a government-notified minimum for stamp duty. "
                 "It is a floor, not a market price, and is revised periodically."),
    },
    "chennai": {
        "name": "TNREGINET (Registration Department, Tamil Nadu)",
        "url": "https://tnreginet.gov.in",
        "how": ("Choose 'Guideline Value Search', then select zone, sub-registrar "
                "office, village and street."),
        "note": ("Guideline value is the notified minimum for stamp duty, not a "
                 "market price."),
    },
}


# ------------------------------------------------------------ guidance value

def _empty_store() -> dict[str, Any]:
    return {"entries": [], "updated_at": None}


def _read() -> dict[str, Any]:
    if not STORE.exists():
        return _empty_store()
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except ValueError:
        return _empty_store()


def _write(data: dict[str, Any]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def guidance_lookup(city: str, locality: str | None) -> dict[str, Any]:
    """Return a manually-recorded guidance value, or explain how to obtain one."""
    portal = PORTALS[cities.get(city).id]
    data = _read()

    match = None
    if locality:
        key = locality.strip().lower()
        for e in data["entries"]:
            if e.get("city") == city and e.get("locality", "").strip().lower() == key:
                match = e
                break

    if match:
        return {
            "available": True,
            "method": METHOD_MANUAL,
            "value_per_sqft": match.get("value_per_sqft"),
            "locality": match.get("locality"),
            "recorded_by": match.get("recorded_by"),
            "recorded_at": match.get("recorded_at"),
            "source_portal": match.get("source_portal", portal["name"]),
            "notified_on": match.get("notified_on"),
            "caveat": (
                "Recorded by hand from the official portal. It is a stamp-duty "
                "floor, not a market price, and may have been revised since it "
                "was entered. Re-check before relying on it."
            ),
            "portal": portal,
        }

    return {
        "available": False,
        "method": METHOD_MANUAL,
        "reason": (
            f"No guidance value has been recorded for this locality. "
            f"{portal['name']} is portal-only with no public API, and its terms "
            "do not permit automated retrieval, so the platform does not fetch "
            "it."
        ),
        "how_to_obtain": portal["how"],
        "portal": portal,
        "entries_held": len([e for e in data["entries"] if e.get("city") == city]),
    }


def record_guidance(
    *, city: str, locality: str, value_per_sqft: float,
    recorded_by: str, notified_on: str | None = None,
) -> dict[str, Any]:
    """Store a value a person looked up themselves, with attribution."""
    data = _read()
    entry = {
        "city": city,
        "locality": locality.strip(),
        "value_per_sqft": round(float(value_per_sqft), 2),
        "recorded_by": recorded_by.strip()[:80],
        "recorded_at": datetime.now(UTC).isoformat(),
        "notified_on": notified_on,
        "source_portal": PORTALS[cities.get(city).id]["name"],
        "method": METHOD_MANUAL,
    }
    data["entries"] = [
        e for e in data["entries"]
        if not (e.get("city") == city
                and e.get("locality", "").strip().lower() == locality.strip().lower())
    ]
    data["entries"].append(entry)
    data["updated_at"] = entry["recorded_at"]
    _write(data)
    return entry


# -------------------------------------------------------- transaction price

@lru_cache(maxsize=4)
def transaction_reference(city: str) -> dict[str, Any]:
    """Locality-level recorded sale prices, where the city's data is transactions."""
    if city != "chennai":
        return {
            "available": False,
            "reason": (
                "Karnataka does not publish registered transaction prices. The "
                "Bengaluru dataset holds ASKING prices from listings, which are "
                "systematically higher than what properties sell for."
            ),
            "alternative": (
                "An Encumbrance Certificate from Kaveri shows transactions for a "
                "specific property, but only to a party with a legitimate "
                "interest, and only one property at a time."
            ),
        }

    try:
        sys.path.insert(0, str(ROOT / "ml"))
        from pipelines import city_config
    except ImportError:
        return {"available": False, "reason": "Chennai pipeline unavailable"}

    try:
        cfg = city_config.get("chennai")
        df, _ = cfg.clean(city_config.load_raw(cfg))
    except Exception as exc:
        return {"available": False,
                "reason": f"Chennai dataset could not be read: {type(exc).__name__}"}

    grouped = (df.groupby("AREA")
                 .agg(median_psf=("price_per_sqft", "median"),
                      median_total=("SALES_PRICE", "median"),
                      sales=("SALES_PRICE", "size"),
                      first_year=("sale_year", "min"),
                      last_year=("sale_year", "max"))
                 .sort_values("sales", ascending=False))

    return {
        "available": True,
        "method": METHOD_DATASET,
        "basis": "RECORDED SALE PRICES",
        "localities": [
            {
                "locality": str(i),
                "median_price_per_sqft": round(float(r.median_psf)),
                "median_sale_price": round(float(r.median_total)),
                "recorded_sales": int(r.sales),
                "period": f"{int(r.first_year)}-{int(r.last_year)}",
            }
            for i, r in grouped.iterrows()
        ],
        "total_sales": int(len(df)),
        "caveat": (
            "These are recorded sale prices, not asking prices — genuinely "
            "transactions. But the period ends in 2015, so they describe a "
            "historical market and must not be read as current values."
        ),
        "note": (
            "This is the one place the platform holds real transaction prices. "
            "Bengaluru has no equivalent, because Karnataka does not publish them."
        ),
    }

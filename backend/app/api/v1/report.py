"""Module 28 — report generation endpoint.

Assembles the 360° report from the services that already exist, then renders it.
Sections with no data are kept in the document and marked UNAVAILABLE, so the
reader sees the shape of what could not be established.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.services import advisory, analytics, cities, jurisdiction, proximity, report
from app.services import rules_engine as rules
from app.services import valuation as val

router = APIRouter()

UNAVAILABLE = "UNAVAILABLE"


class ReportRequest(BaseModel):
    city: str = "bengaluru"
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    sqft: float = Field(1200, gt=100, le=100_000)
    rooms: int = Field(2, ge=1, le=20)
    bath: float | None = Field(2, ge=0, le=20)
    asking_price_per_sqft: float | None = Field(None, gt=0, le=200_000)
    plot_area_sqm: float | None = Field(None, gt=0)
    road_width_m: float | None = Field(None, gt=0)


def _fmt_inr(v: Any) -> str:
    try:
        return "Rs " + format(round(float(v)), ",")
    except (TypeError, ValueError):
        return ""


def _assemble(req: ReportRequest) -> dict[str, Any]:
    city = cities.get(req.city)
    sections: list[tuple[str, list[tuple[str, str, str]]]] = []
    caveats: list[str] = []
    sources: list[dict[str, str]] = []

    # --- jurisdiction -------------------------------------------------
    jur_rows: list[tuple[str, str, str]] = []
    ward_name = None
    if req.lat is not None and req.lng is not None and \
            jurisdiction.in_coverage(req.lng, req.lat, city.id):
        result = jurisdiction.jurisdiction(req.lng, req.lat, city.id)
        for key in ("corporation", "ward_no", "ward_name", "zone", "division",
                    "sub_division", "assembly"):
            f = result.facts.get(key)
            if f is None:
                continue
            label = key.replace("_", " ").title()
            if f.is_known:
                jur_rows.append((label, str(f.value), "VERIFIED"))
                if key == "ward_name":
                    ward_name = str(f.value)
            else:
                jur_rows.append((label, "", UNAVAILABLE))
        for key in ("planning_authority", "district", "taluk"):
            f = result.facts.get(key)
            if f is not None and not f.is_known:
                jur_rows.append((key.replace("_", " ").title(),
                                 f.reason or "", UNAVAILABLE))
        if result.found:
            sources.append({
                "name": f"{city.authority} ward boundaries",
                "tier": "T2",
                "licence": "Official delimitation via OpenCity urban data portal",
            })
    else:
        jur_rows.append(("Location", "No location supplied", UNAVAILABLE))
        caveats.append(
            "No coordinates were supplied, so jurisdiction, nearby facilities "
            "and all proximity-derived scores could not be established.")
    sections.append(("Administrative jurisdiction", jur_rows))

    # --- records (never machine-readable) ------------------------------
    sections.append(("Property records and approvals", [
        ("Khata / e-Khata", "No public API; owner-consent portal only", UNAVAILABLE),
        ("Property tax status", "Per-property portal, OTP gated", UNAVAILABLE),
        ("Building approval", "No public searchable register", UNAVAILABLE),
        ("Occupancy certificate", "No public searchable register", UNAVAILABLE),
        ("Encumbrance certificate", "Per-property, consent required", UNAVAILABLE),
    ]))
    caveats.append(
        "No government property record was retrieved. None of Khata, property "
        "tax, building approval, occupancy or encumbrance status is available "
        "through a public API, and none has been checked.")

    # --- nearby --------------------------------------------------------
    near_rows: list[tuple[str, str, str]] = []
    scores: dict[str, Any] = {}
    prox: dict[str, Any] = {}
    if req.lat is not None and req.lng is not None:
        pr = proximity.facts(req.lat, req.lng, city_id=city.id)
        if pr["available"]:
            prox = pr["found"]
            scores = {k: f.value for k, f in pr["scores"].items()}
            for cat, label in (("metro_station", "Nearest metro"),
                               ("railway_station", "Nearest railway station"),
                               ("bus_stop", "Nearest bus stop"),
                               ("hospital", "Nearest hospital"),
                               ("school", "Nearest school"),
                               ("government_office", "Nearest government office")):
                places = prox.get(cat) or []
                if places:
                    p = places[0]
                    near_rows.append((label, f"{p.name or cat} — {p.distance_m:,} m",
                                      "GIS"))
                else:
                    near_rows.append((label, "None found within 5 km", UNAVAILABLE))
            for k, v in scores.items():
                near_rows.append((k.replace("_", " ").title(),
                                  f"{v}/100" if v is not None else "",
                                  "DATA-DRIVEN SCORE" if v is not None else UNAVAILABLE))
            sources.append({"name": "OpenStreetMap amenities (Overpass)",
                            "tier": "T3",
                            "licence": "ODbL 1.0 — © OpenStreetMap contributors"})
    if not near_rows:
        near_rows.append(("Nearby facilities", "No location supplied", UNAVAILABLE))
    sections.append(("Transport, government offices and nearby services", near_rows))

    # --- market --------------------------------------------------------
    est = val.estimate(
        val.ValuationInput(sqft=req.sqft, rooms=req.rooms, bath=req.bath),
        city=city.id)
    predicted = est["price_per_sqft"].value
    half = None
    if est["price_range_high"].value is not None and predicted is not None:
        half = float(est["price_range_high"].value) - float(predicted)

    market_rows: list[tuple[str, str, str]] = []
    if predicted is not None:
        market_rows += [
            ("Estimated rate", f"{_fmt_inr(predicted)} per sq.ft", "ML PREDICTION"),
            ("90% prediction interval",
             f"{_fmt_inr(est['price_range_low'].value)} – "
             f"{_fmt_inr(est['price_range_high'].value)}", "ML PREDICTION"),
            ("Estimated value", _fmt_inr(predicted * req.sqft), "ML PREDICTION"),
            ("Target measured",
             analytics.city_target_label(city.id), "ML PREDICTION"),
        ]
        caveats.append(est["price_per_sqft"].caveats[0])
        sources.append({
            "name": f"{city.name} property dataset",
            "tier": "T4",
            "licence": "Public mirror; licence unconfirmed — see model card",
        })
    else:
        market_rows.append(("Estimated rate", est["price_per_sqft"].reason or "",
                            UNAVAILABLE))
    market_rows += [
        ("Government guidance value",
         est["guidance_value"].reason or "", UNAVAILABLE),
        ("Registered transaction price",
         est["transaction_price"].reason or "", UNAVAILABLE),
    ]
    if req.asking_price_per_sqft:
        market_rows.insert(0, ("Asking price",
                               f"{_fmt_inr(req.asking_price_per_sqft)} per sq.ft",
                               "RULE"))
    sections.append(("Market value", market_rows))

    # --- demand, risk, verdict -----------------------------------------
    def nearest(cat: str) -> float | None:
        places = prox.get(cat) or []
        return float(places[0].distance_m) if places else None

    amenity_1km = sum(1 for pl in prox.values() for x in pl if x.distance_m <= 1000) \
        if prox else None
    demand = analytics.demand_score(
        connectivity_score=scores.get("connectivity_score"),
        healthcare_score=scores.get("healthcare_score"),
        education_score=scores.get("education_score"),
        amenity_count_1km=amenity_1km,
        locality_listing_count=None, max_listing_count=None)
    risk = analytics.risk_score(
        lake_distance_m=nearest("lake"), park_distance_m=nearest("park"),
        hospital_distance_m=nearest("hospital"),
        fire_station_distance_m=nearest("fire_station"),
        connectivity_score=scores.get("connectivity_score"))

    sections.append(("Demand and risk", [
        ("Demand",
         f"{demand['band']}" + (f" ({demand['score']}/100)" if demand.get("score") is not None else ""),
         "DATA-DRIVEN SCORE" if demand.get("score") is not None else UNAVAILABLE),
        ("Risk",
         f"{risk['band']}" + (f" ({risk['score']}/100)" if risk.get("score") is not None else ""),
         "DATA-DRIVEN SCORE" if risk.get("score") is not None else UNAVAILABLE),
        ("Flood risk", "No authoritative flood or drain geometry is public",
         UNAVAILABLE),
    ]))

    verdict = None
    if req.asking_price_per_sqft and predicted:
        verdict = advisory.buyer_verdict(
            observed_psf=req.asking_price_per_sqft, predicted_psf=float(predicted),
            interval_half=half, demand=demand, risk=risk,
            connectivity=scores.get("connectivity_score"), records_verified=False)
        sections.append(("Buyer assessment", [
            ("Verdict", verdict["verdict"], "COMPOSITE"),
            ("Price vs model", f"{verdict['price_gap_pct']:+.1f}%", "ML PREDICTION"),
        ] + [("In its favour", p, "COMPOSITE") for p in verdict["positives"]]
          + [("Against it", n, "COMPOSITE") for n in verdict["negatives"]]))

    # --- feasibility ----------------------------------------------------
    feas = rules.evaluate(rules.FeasibilityInput(
        plot_area_sqm=req.plot_area_sqm, road_width_m=req.road_width_m,
        land_use="residential"))
    feas_rows = []
    for key in ("far", "max_height", "max_built_up", "potential_floors", "setbacks"):
        f = feas.facts.get(key)
        if f is None:
            continue
        label = key.replace("_", " ").title()
        if f.is_known:
            feas_rows.append((label, f"{f.value} {f.unit or ''}".strip(), "RULE"))
        else:
            feas_rows.append((label, f.reason or "", UNAVAILABLE))
    sections.append(("Development feasibility", feas_rows))
    caveats.append(
        "Development-control rules are not yet verified against the Karnataka "
        "Gazette, so the feasibility engine returns no FAR or height figure. "
        "This is deliberate: publishing an unverified FAR would be a guess with "
        "financial consequences.")
    sources.append({"name": "Zoning Regulations, RMP-2015 (India Code)",
                    "tier": "T1", "licence": "Government publication"})

    # --- summary --------------------------------------------------------
    bits = [f"This report covers a {req.sqft:,.0f} sq.ft, {req.rooms}-bedroom "
            f"property in {city.name}."]
    if ward_name:
        bits.append(f"It falls in {ward_name}.")
    if predicted:
        bits.append(f"The model estimates {_fmt_inr(predicted)} per sq.ft "
                    f"({analytics.city_target_label(city.id)}).")
    if verdict:
        bits.append(f"The buyer assessment is <b>{verdict['verdict']}</b>.")
    bits.append("No government property record could be retrieved, so all "
                "record-dependent conclusions require manual verification.")

    return {
        "city": {"id": city.id, "name": city.name},
        "summary": {"text": " ".join(bits)},
        "sections": sections,
        "caveats": caveats,
        "sources": sources,
    }


@router.post("/generate", summary="Generate the 360 Property Intelligence Report (PDF)")
async def generate(req: ReportRequest) -> Response:
    payload = _assemble(req)
    pdf = report.build(payload)
    city = payload["city"]["id"]
    stamp = __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'attachment; filename="property-report-{city}-{stamp}.pdf"'
        },
    )


@router.post("/preview", summary="Report contents as JSON (same assembly, no PDF)")
async def preview(req: ReportRequest) -> dict[str, Any]:
    payload = _assemble(req)
    return {
        "city": payload["city"],
        "summary": payload["summary"]["text"],
        "sections": [
            {"title": t,
             "rows": [{"item": a, "value": b, "method": c} for a, b, c in rows],
             "unavailable_count": sum(1 for _, _, c in rows if c == UNAVAILABLE)}
            for t, rows in payload["sections"]
        ],
        "caveats": payload["caveats"],
        "sources": payload["sources"],
    }

"""End-to-end check: every endpoint, both cities, one run.

Catches the failure mode of rapid feature work — an endpoint that silently
regressed while something else was being added. Exercises the real app through
TestClient, so no server needs to be running.

    cd backend && PYTHONPATH=. python scripts/e2e_check.py
"""

from __future__ import annotations

import sys
from typing import Any

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

BLR = {"lat": 12.9794, "lng": 77.5912}
CHN = {"lat": 13.0418, "lng": 80.2341}
POINTS = {"bengaluru": BLR, "chennai": CHN}

results: list[tuple[str, str, bool, str]] = []


def check(city: str, name: str, ok: bool, detail: str = "") -> None:
    results.append((city, name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name:<34} {detail}")


def get(path: str, **params) -> tuple[int, Any]:
    r = client.get(path, params=params)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.content


def _purge_test_guidance() -> None:
    """Guidance values persist to a real store — don't leave test rows behind."""
    from app.services import market_reference as mr

    if not mr.STORE.exists():
        return
    data = mr._read()
    keep = [e for e in data["entries"] if e.get("recorded_by") != "e2e_check"]
    if len(keep) != len(data["entries"]):
        data["entries"] = keep
        mr._write(data)


def post(path: str, body: dict) -> tuple[int, Any]:
    r = client.post(path, json=body)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.content


def run_city(city: str) -> None:
    pt = POINTS[city]
    print(f"\n{'=' * 72}\n  {city.upper()}\n{'=' * 72}")

    # --- jurisdiction ------------------------------------------------
    code, d = get("/api/v1/jurisdiction", city=city, **pt)
    check(city, "jurisdiction", code == 200 and d.get("found"),
          f"ward={d.get('data', {}).get('ward_name', {}).get('value')}"
          if code == 200 else f"HTTP {code}")

    code, d = get("/api/v1/jurisdiction/wards", city=city)
    expected = 369 if city == "bengaluru" else 200
    check(city, "ward list", code == 200 and d.get("count") == expected,
          f"{d.get('count')} wards (expected {expected})")

    # --- map layers ---------------------------------------------------
    layer = "wards" if city == "bengaluru" else "chennai_wards"
    code, d = get(f"/api/v1/map/layers/{layer}")
    n = len(d.get("features", [])) if isinstance(d, dict) else 0
    check(city, "map ward layer", code == 200 and n == expected, f"{n} features")

    # --- nearby -------------------------------------------------------
    code, d = get("/api/v1/nearby", city=city, **pt)
    groups = sum(len(v) for v in d.get("groups", {}).values()) if code == 200 else 0
    check(city, "nearby", code == 200 and d.get("available") and groups > 0,
          f"{groups} facilities")

    # --- valuation ----------------------------------------------------
    code, d = post("/api/v1/valuation/estimate",
                   {"city": city, "sqft": 1200, "rooms": 2, "bath": 2})
    psf = d.get("data", {}).get("price_per_sqft", {}).get("value") if code == 200 else None
    check(city, "valuation", code == 200 and psf, f"Rs {psf}/sq.ft")

    # --- prediction strategies ----------------------------------------
    for mode in ("single", "dual", "multi"):
        code, d = post("/api/v1/predict",
                       {"city": city, "mode": mode, "sqft": 1200, "rooms": 2, "bath": 2})
        res = d.get("result", {}) if code == 200 else {}
        check(city, f"predict ({mode})",
              code == 200 and res.get("available") and res.get("prediction"),
              f"Rs {res.get('prediction')} from {res.get('model_count')} model(s)")

    code, d = get("/api/v1/predict/models", city=city)
    check(city, "model catalogue", code == 200 and d.get("count", 0) >= 4,
          f"{d.get('count')} models")

    # --- ML dashboard -------------------------------------------------
    code, d = get("/api/v1/ml/summary", city=city)
    check(city, "ml summary", code == 200 and d.get("selected_model"),
          f"{d.get('selected_model')}")

    code, d = get("/api/v1/ml/eda", city=city)
    check(city, "ml eda", code == 200 and d.get("rows"), f"{d.get('rows')} rows")

    code, d = get("/api/v1/ml/explain", city=city)
    check(city, "ml explain", code == 200 and d.get("permutation_importance"),
          f"{len(d.get('permutation_importance', []))} features")

    code, d = get("/api/v1/ml/future-price", city=city)
    supported = d.get("available") if code == 200 else None
    check(city, "future price", code == 200,
          "forecast supported" if supported else "forecast correctly refused")

    # --- planning -----------------------------------------------------
    code, d = get("/api/v1/planning/summary", city=city)
    reliable = d.get("coverage", {}).get("scores_reliable") if code == 200 else None
    check(city, "planning summary", code == 200 and d.get("ward_count") == expected,
          f"{d.get('ward_count')} wards, coverage reliable={reliable}")

    code, d = get("/api/v1/planning/choropleth", city=city, metric="infrastructure_score")
    check(city, "planning choropleth", code == 200 and d.get("count", 0) > 0,
          f"{d.get('count')} shaded, key={d.get('key_format')}")

    # --- advisory -----------------------------------------------------
    body = {"label": "E2E", "city": city, **pt, "sqft": 1200, "rooms": 2,
            "bath": 2, "asking_price_per_sqft": 6500}
    code, d = post("/api/v1/advisory/buyer", body)
    v = d.get("verdict", {}) if code == 200 else {}
    check(city, "buyer mode", code == 200 and v.get("verdict"),
          f"{v.get('verdict')}")
    check(city, "buyer records cap", bool(v.get("blocking")),
          "records caveat present" if v.get("blocking") else "MISSING CAVEAT")

    code, d = post("/api/v1/advisory/investor", {"options": [
        {**body, "label": "A"},
        {**body, "label": "B", "sqft": 1500, "asking_price_per_sqft": 5800},
    ]})
    ranked = d.get("ranking", {}).get("ranked", []) if code == 200 else []
    check(city, "investor mode", code == 200 and len(ranked) == 2,
          f"ranked {len(ranked)}")

    # --- builder / feasibility ---------------------------------------
    code, d = post("/api/v1/builder/analyze", {
        "city": city, "land_area_sqft": 10000, "land_cost_total": 18000000,
        "expected_builtup_sqft": 18000, "num_units": 16, "avg_unit_size_sqft": 1150})
    dg = d.get("diagnosis", {}) if code == 200 else {}
    check(city, "builder mode", code == 200 and "returns" in d,
          f"ROI {d.get('returns', {}).get('roi_pct')}%, viable={dg.get('viable')}")

    code, d = post("/api/v1/feasibility/evaluate",
                   {"plot_area_sqm": 929, "road_width_m": 12.2, "land_use": "residential"})
    far = d.get("data", {}).get("far", {}) if code == 200 else {}
    check(city, "feasibility refuses FAR", code == 200 and far.get("status") == "UNAVAILABLE",
          "FAR correctly UNAVAILABLE")

    # Phase 0.5 closed R2/R3/R4: the instruments are now cited. Citing them must
    # not have caused any value to appear.
    gi = d.get("ruleset", {}).get("governing_instruments", {}) if code == 200 else {}
    check(city, "governing instruments cited",
          gi.get("zoning_amendment", {}).get("reference") == "UDD 235 MNJ 2025"
          and gi.get("corporation_byelaws", {}).get("instrument_count") == 5,
          f"{gi.get('zoning_amendment', {}).get('reference')} "
          f"+ {gi.get('corporation_byelaws', {}).get('instrument_count')} per-corporation bye-laws")
    check(city, "citation did not unlock a value",
          gi.get("transcription_status") == "NOT TRANSCRIBED"
          and far.get("value") is None
          and "UDD 235 MNJ 2025" in (far.get("reason") or ""),
          "sources named, FAR still withheld")

    # --- insights -----------------------------------------------------
    code, d = post("/api/v1/insights/analyze", body)
    check(city, "insights", code == 200 and d.get("investment_score"),
          f"investment {d.get('investment_score', {}).get('band')}")

    # --- report -------------------------------------------------------
    rbody = {"city": city, **pt, "sqft": 1200, "rooms": 2, "bath": 2,
             "asking_price_per_sqft": 6500, "plot_area_sqm": 929, "road_width_m": 12.2}
    code, d = post("/api/v1/report/preview", rbody)
    secs = len(d.get("sections", [])) if code == 200 else 0
    check(city, "report preview", code == 200 and secs >= 6, f"{secs} sections")

    r = client.post("/api/v1/report/generate", json=rbody)
    ok = r.status_code == 200 and r.content[:5] == b"%PDF-"
    check(city, "report PDF", ok, f"{len(r.content):,} bytes")

    # --- additional models --------------------------------------------
    code, d = get("/api/v1/extra/models", city=city)
    cl = d.get("classification", {}) if code == 200 else {}
    cu = d.get("clustering", {}) if code == 200 else {}
    an = d.get("anomaly", {}) if code == 200 else {}
    check(city, "extra models", code == 200 and cl.get("accuracy") is not None,
          f"accuracy {cl.get('accuracy')}, macro F1 {cl.get('macro_f1')}")

    # A degenerate classifier must SAY so, not be reported as a working model.
    never = cl.get("classes_never_predicted") or []
    check(city, "degenerate guard honest",
          bool(cl.get("warning")) == bool(never),
          f"warning={bool(cl.get('warning'))}, never predicted={never or 'none'}")

    # Clustering must refuse rather than cluster a handful of localities.
    if cu.get("available"):
        check(city, "clustering", cu.get("silhouette") is not None and cu.get("k", 0) >= 2,
              f"k={cu.get('k')}, silhouette {cu.get('silhouette')}, "
              f"{cu.get('localities_clustered')} localities")
    else:
        check(city, "clustering refuses", bool(cu.get("reason")),
              (cu.get("reason") or "")[:52])

    check(city, "anomaly detection",
          an.get("flagged") is not None and an.get("total", 0) > an.get("flagged", 0),
          f"{an.get('flagged')} of {an.get('total')} flagged")

    # --- guidance value -----------------------------------------------
    code, d = get("/api/v1/extra/guidance-value", city=city)
    # Nothing recorded yet must read as "not recorded", never as a value.
    ok = code == 200 and (d.get("available") is False and d.get("how_to_obtain")
                          or d.get("method") == "MANUAL ENTRY")
    check(city, "guidance value honest", bool(ok),
          f"available={d.get('available')}, portal linked="
          f"{bool(d.get('portal', {}).get('url'))}")

    code, d = post("/api/v1/extra/guidance-value",
                   {"city": city, "locality": "E2E Test Locality",
                    "value_per_sqft": 5000, "recorded_by": "e2e_check"})
    check(city, "guidance value entry",
          code == 200 and d.get("method") == "MANUAL ENTRY",
          f"stored as {d.get('method')} — never VERIFIED")

    code, d = get("/api/v1/extra/guidance-value", city=city,
                  locality="E2E Test Locality")
    check(city, "guidance value readback",
          code == 200 and d.get("available") is True
          and d.get("value_per_sqft") == 5000 and bool(d.get("recorded_by")),
          f"{d.get('value_per_sqft')} by {d.get('recorded_by')}")
    _purge_test_guidance()

    # --- transaction price --------------------------------------------
    code, d = get("/api/v1/extra/transaction-price", city=city)
    if city == "chennai":
        locs = d.get("localities", []) if code == 200 else []
        check(city, "transaction prices",
              code == 200 and d.get("available") is True
              and d.get("basis") == "RECORDED SALE PRICES" and len(locs) >= 5,
              f"{len(locs)} localities, {d.get('total_sales')} recorded sales")
        check(city, "transaction vintage stated",
              "2015" in (d.get("caveat") or ""),
              "historical period declared in the caveat")
    else:
        check(city, "transaction prices unavailable",
              code == 200 and d.get("available") is False
              and "asking" in (d.get("reason") or "").lower(),
              "asking prices are not transactions — correctly refused")

    # --- document intelligence (Module 27) -----------------------------
    sample = ("KHATA CERTIFICATE\nKhata No: 123/456/78\nOwner: Test Person\n"
              "Ward No: 111\nTaluk: Bangalore East\nHobli: Varthur\n"
              "Village: Marathhalli\nSurvey No: 36\nMobile: 9876543210\n")
    doc_point = {"lat": 12.9591, "lng": 77.6974} if city == "bengaluru" else pt
    code, d = post("/api/v1/documents/analyze",
                   {"text": sample, "city": city, **doc_point})
    blob = str(d)
    check(city, "document analysis",
          code == 200 and d.get("fields_found", 0) >= 5,
          f"{d.get('fields_found')} fields extracted from pasted text")

    # The three properties that make this module safe to ship.
    check(city, "document not stored",
          d.get("retention", {}).get("stored") is False,
          "parsed in memory and discarded")
    check(city, "personal data withheld",
          d.get("personal_data", {}).get("present") is True
          and "Test Person" not in blob and "9876543210" not in blob,
          "detected as present, never echoed back")
    check(city, "consistent is never verified",
          d.get("summary", {}).get("verified") is False
          and "Khata is not title" in d.get("summary", {}).get("why_never_verified", ""),
          "a consistent document is not a verified one")

    # No OCR engine: an image must be refused, not guessed at.
    r = client.post("/api/v1/documents/upload",
                    files={"file": ("scan.jpg", b"\xff\xd8\xffnotreallyanimage",
                                    "image/jpeg")})
    dd = r.json() if r.status_code == 200 else {}
    check(city, "image upload refused",
          dd.get("analysed") is False and dd.get("ocr_status") == "NOT INSTALLED",
          "no OCR engine — refuses rather than fabricating fields")

    # --- road intelligence (Module 8) ----------------------------------
    code, d = get("/api/v1/roads/coverage", city=city)
    if city == "bengaluru":
        m = d.get("measured", {}) if code == 200 else {}
        check(city, "road coverage",
              code == 200 and d.get("segments", 0) > 10_000 and m.get("measured"),
              f"{d.get('segments'):,} segments, {d.get('network_length_km'):,.0f} km, "
              f"{m.get('within_pct', {}).get('150')}% of localities within 150 m")

        # On a mapped arterial: both widths present, and different.
        code, d = get("/api/v1/roads", lat=12.9750, lng=77.6100, city=city)
        ex, pr = d.get("width_existing_m"), d.get("width_proposed_m")
        check(city, "nearest road",
              code == 200 and d.get("available") is True and ex and pr,
              f"{d.get('distance_to_centreline_m')} m away, {d.get('hierarchy_code')}, "
              f"existing {ex} m vs proposed {pr} m")
        check(city, "proposed width carries refusal",
              "DO NOT USE FOR FEASIBILITY" in (d.get("proposed_width_caveat") or ""),
              "the wider figure is excluded from feasibility")
        check(city, "no field named road_width",
              "road_width" not in d,
              "the two widths are never collapsed into one number")

        # The feasibility offer must be the smaller figure, and must be an offer.
        code, d = get("/api/v1/roads/feasibility-input",
                      lat=12.9750, lng=77.6100, city=city)
        check(city, "feasibility offer is the existing width",
              code == 200 and d.get("available") is True
              and d.get("suggested_road_width_m") == ex
              and d.get("source_flag") == "dataset"
              and d.get("excluded", {}).get("width_proposed_m") == pr,
              f"offers {d.get('suggested_road_width_m')} m as 'dataset', "
              f"excludes {pr} m")

        # Off the mapped network: refuse, and don't call it "no road access".
        code, d = get("/api/v1/roads", lat=12.9250, lng=77.5833, city=city)
        check(city, "off-network refuses honestly",
              code == 200 and d.get("available") is False
              and "not a finding" in " ".join(str(v) for v in d.values()).lower(),
              "gap in the layer, not an absence of road")
    else:
        check(city, "road layer unavailable",
              code == 200 and d.get("available") is False and bool(d.get("reason")),
              "no road width layer for Chennai — stated, not implied")

    # --- revenue layer -------------------------------------------------
    code, d = get("/api/v1/extra/revenue-coverage", city=city)
    if city == "bengaluru":
        check(city, "revenue coverage",
              code == 200 and d.get("available") is True
              and len(d.get("taluks", [])) >= 1 and d.get("parcel_count", 0) > 100,
              f"{len(d.get('taluks', []))} taluks, {len(d.get('hoblis', []))} hoblis, "
              f"{d.get('parcel_count'):,} parcels")
        check(city, "revenue partial declared",
              d.get("partial") is True and bool(d.get("survey_number_caveat")),
              "partial coverage and survey caveat both stated")

        # A point inside coverage resolves taluk/hobli/village.
        code, d = get("/api/v1/jurisdiction", lat=12.9591, lng=77.6974, city=city)
        f = d.get("data", {}) if code == 200 else {}
        got = {k: f.get(k, {}).get("value") for k in ("taluk", "hobli", "village")}
        check(city, "revenue fields resolve",
              all(got.values()),
              ", ".join(f"{k}={v}" for k, v in got.items()))
        check(city, "survey number indicative",
              f.get("survey_number", {}).get("status") in ("INDICATIVE", "UNAVAILABLE"),
              f"survey_number status {f.get('survey_number', {}).get('status')} "
              "— never VERIFIED")

        # Inside GBA but outside the revenue sheets. Since the administrative
        # boundary layer landed, taluk resolves here from a T3 areal source —
        # but the cadastral fields must still refuse. Widening areal coverage
        # must never widen what is claimed about a parcel.
        code, d = get("/api/v1/jurisdiction", lat=13.0500, lng=77.6200, city=city)
        f = d.get("data", {}) if code == 200 else {}
        tal = f.get("taluk", {})
        check(city, "taluk resolves outside the sheets",
              d.get("found") is True and tal.get("value")
              and tal.get("status") == "INDICATIVE",
              f"taluk {tal.get('value')} (INDICATIVE, boundary layer)")
        check(city, "cadastral fields still refuse",
              all(f.get(k, {}).get("value") is None
                  and "cannot produce" in (f.get(k, {}).get("reason") or "")
                  for k in ("hobli", "village", "survey_number")),
              "hobli/village/survey UNAVAILABLE — a polygon cannot produce them")
    else:
        check(city, "revenue unavailable",
              code == 200 and d.get("available") is False and bool(d.get("reason")),
              "no revenue layer for Chennai — stated, not implied")


def main() -> int:
    print("END-TO-END CHECK — every endpoint, both cities")

    code, d = get("/health")
    check("-", "health", code == 200, d.get("status", ""))

    code, d = get("/api/v1/cities")
    check("-", "city registry", code == 200 and len(d.get("data", [])) == 2,
          f"{len(d.get('data', []))} cities")

    code, d = get("/api/v1/predict/glossary")
    check("-", "glossary", code == 200 and d.get("term_count", 0) > 20,
          f"{d.get('term_count')} terms, {d.get('ml_feature_count')} ML features")

    code, d = get("/api/v1/sources")
    srcs = d.get("data", []) if code == 200 else []
    linked = [s for s in srcs if s.get("source_url")]
    check("-", "source registry", code == 200 and len(srcs) >= 7,
          f"{len(srcs)} datasets, {len(linked)} with a source link")
    # A registry that lost its provenance is worse than no registry.
    check("-", "registry keeps provenance",
          all(s.get("tier") and s.get("verification_status") for s in srcs),
          "every dataset carries a tier and verification status")

    code, d = get("/api/v1/ml/compare")
    avail = sum(1 for c in d.get("data", []) if c.get("available")) if code == 200 else 0
    check("-", "city comparison", code == 200 and avail == 2,
          f"{avail}/2 cities available")

    for city in ("bengaluru", "chennai"):
        run_city(city)

    failed = [r for r in results if not r[2]]
    print(f"\n{'=' * 72}")
    print(f"  {len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("\n  FAILURES:")
        for city, name, _, detail in failed:
            print(f"    {city:<11} {name:<34} {detail}")
    print("=" * 72)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

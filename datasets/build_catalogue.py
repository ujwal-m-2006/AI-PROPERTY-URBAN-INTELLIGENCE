"""Generate the dataset catalogue from the provenance sidecars.

Generated rather than hand-written for one reason: a hand-maintained dataset
list drifts. Every ingest flow writes a `source_*.json` beside its output
recording what it actually downloaded, and this reads those. If a layer is
re-ingested from a different URL, the catalogue changes on the next run without
anyone remembering to edit it.

What the sidecars cannot know is *what each dataset is for* — which module it
powers, and which project claim rests on it. That mapping lives in USES below
and is the only hand-maintained part.

    python datasets/build_catalogue.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
ARTIFACTS = ROOT / "ml" / "artifacts"
OUT = Path(__file__).resolve().parent

# What each layer powers. Keyed by the sidecar stem.
USES: dict[str, dict[str, str]] = {
    "gba_wards": {
        "category": "Administrative boundaries",
        "powers": "Module 1 jurisdiction, Module 21 ward analytics, Module 22 map; "
                  "spatial-block CV groups for every Bengaluru model",
        "why_it_matters": "The whole platform keys off which of the 369 wards a "
                          "point falls in. Without it nothing else resolves.",
    },
    "chennai_wards": {
        "category": "Administrative boundaries",
        "powers": "Module 1 jurisdiction for Chennai, ward analytics, map, "
                  "Tamil ward names",
        "why_it_matters": "GCC publishes ward numbers only. Place names here are "
                          "DERIVED from OpenStreetMap, not official.",
    },
    "admin_subdistricts_bengaluru": {
        "category": "Administrative boundaries",
        "powers": "District and taluk for any point in Bengaluru",
        "why_it_matters": "Took taluk coverage from 3 taluks (revenue sheets "
                          "only) to 100% of localities.",
    },
    "admin_subdistricts_chennai": {
        "category": "Administrative boundaries",
        "powers": "District and taluk for any point in Chennai",
        "why_it_matters": "Chennai had no taluk data at all before this.",
    },
    "revenue_parcels": {
        "category": "Cadastral records",
        "powers": "Hobli, village and survey number (Module 1, Module 2)",
        "why_it_matters": "The only source of a survey number in the project, "
                          "and it covers 7% of localities. Everything outside it "
                          "returns UNAVAILABLE.",
    },
    "road_network_bengaluru": {
        "category": "Infrastructure",
        "powers": "Module 8 road intelligence; offers a road width to Module 6 "
                  "feasibility",
        "why_it_matters": "Contains TWO width columns. The proposed one would "
                          "double reported buildable area city-wide if used.",
    },
    "flood_locations_bengaluru": {
        "category": "Environmental",
        "powers": "Module 12 proximity to reported flooding",
        "why_it_matters": "Reported locations only. Explicitly NOT folded into "
                          "the risk score, which still lists flood as excluded.",
    },
    "osm_amenities": {
        "category": "Points of interest",
        "powers": "Modules 9, 10, 11 proximity; 11 GIS features in every model",
        "why_it_matters": "Adding these raised Bengaluru's honest spatial-CV R² "
                          "from 0.3078 to 0.4231.",
    },
    "osm_amenities_chennai": {
        "category": "Points of interest",
        "powers": "Modules 9, 10, 11 for Chennai; GIS features",
        "why_it_matters": "Same features, separate file — the two cities' layers "
                          "are never pooled.",
    },
    "locality_gazetteer_bengaluru": {
        "category": "Points of interest",
        "powers": "Locality search, geocoding the property dataset to wards",
        "why_it_matters": "Joins the T4 property dataset to real geography, "
                          "which is what makes spatial-block CV possible.",
    },
    "locality_gazetteer_chennai": {
        "category": "Points of interest",
        "powers": "Locality search, Chennai ward place names and Tamil names",
        "why_it_matters": "Supplies the Tamil ward names — 129 of 200; the rest "
                          "are left blank rather than transliterated.",
    },
    "property_dataset_bengaluru": {
        "category": "Property market (ML training data)",
        "powers": "Module 14 price prediction, 16 demand, 17-18 builder ROI, "
                  "19 buyer, 20 investor, quantile negotiation band",
        "why_it_matters": "ASKING prices, not transactions. Every price the "
                          "platform predicts inherits that upward bias.",
    },
    "property_dataset_chennai": {
        "category": "Property market (ML training data)",
        "powers": "Same modules for Chennai, plus Module 15 future price",
        "why_it_matters": "RECORDED SALE prices — the only real transaction data "
                          "in the project. Period ends ~2015, and only 7 "
                          "localities, so spatial CV has 7 blocks.",
    },
}

# Sources the audit examined and could NOT use. Documented because "we looked and
# it is not obtainable" is a finding, and a catalogue of only what worked hides it.
UNAVAILABLE: list[dict[str, str]] = [
    {"feature": "e-Khata / e-Aasthi records", "authority": "Revenue Dept / ULB",
     "url": "https://landrecords.karnataka.gov.in", "classification": "PORTAL + UPLOAD",
     "why": "Per-property lookup behind SAS ID + mobile OTP with owner consent. "
            "No bulk feed, no query API. Automated retrieval would be both "
            "technically hostile and legally questionable."},
    {"feature": "Property tax / SAS status", "authority": "GBA property tax portal",
     "url": "https://bbmptax.karnataka.gov.in", "classification": "PORTAL",
     "why": "Per-property lookup. Personal data."},
    {"feature": "Encumbrance Certificate", "authority": "Kaveri 2.0",
     "url": "https://kaveri.karnataka.gov.in", "classification": "PORTAL",
     "why": "Account required, one property at a time, and only to a party with "
            "a legitimate interest."},
    {"feature": "Guidance value", "authority": "Dept of Stamps & Registration",
     "url": "https://kaveri.karnataka.gov.in", "classification": "PORTAL",
     "why": "No public API and terms do not permit automated retrieval. The "
            "platform links to it and stores what a person records by hand."},
    {"feature": "Registered transaction prices (Karnataka)", "authority": "—",
     "url": "", "classification": "NONE",
     "why": "Karnataka does not publish transaction-level registration data at "
            "all. This is why the Bengaluru model trains on asking prices."},
    {"feature": "Survey number boundaries", "authority": "Dishaank (KSRSAC)",
     "url": "", "classification": "PORTAL",
     "why": "Mobile/web GIS app, no public API. Its boundaries are notional "
            "with 3-10 m GPS error and are not legally valid for disputes."},
    {"feature": "Land use / zoning polygons", "authority": "BDA master plan",
     "url": "", "classification": "DOWNLOAD (PDF only)",
     "why": "Published as planning-district PDF map sheets. No machine-readable "
            "polygon layer exists, so Module 5 cannot be geographic."},
    {"feature": "Planning authority boundaries", "authority": "BMRDA / BDA",
     "url": "https://bmrda.karnataka.gov.in", "classification": "NONE (PDF maps only)",
     "why": "Audit task R5, closed as a negative: PDF jurisdiction maps for 12 "
            "local planning authorities, no shapefile or KML anywhere."},
    {"feature": "BBMP GIS viewer service endpoints", "authority": "BBMP",
     "url": "https://bbmp.gov.in/gisviewer", "classification": "UNKNOWN",
     "why": "Audit task R1, still open. The host presents an incomplete TLS "
            "certificate chain and could not be reached by two independent "
            "clients. Not worked around."},
    {"feature": "Ward population", "authority": "GBA ward KML",
     "url": "", "classification": "PARTIAL — withheld",
     "why": "The published field sums to ~6x the real total and 125 of 369 rows "
            "fail male+female=total. No figure is published."},
]


def sidecars() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for p in sorted(PROCESSED.glob("source_*.json")):
        try:
            out.append((p.stem.replace("source_", ""),
                        json.loads(p.read_text(encoding="utf-8"))))
        except ValueError:
            continue
    return out


def rows_for(stem: str, d: dict[str, Any]) -> str:
    cov = d.get("coverage") or {}
    for key in ("parcel_count", "segments", "points", "polygons"):
        if cov.get(key):
            return f"{cov[key]:,}"
    if stem.startswith("property_dataset"):
        city = stem.rsplit("_", 1)[-1]
        p = ARTIFACTS / city / "metrics.json"
        if p.exists():
            m = json.loads(p.read_text(encoding="utf-8"))
            return f"{m.get('dataset', {}).get('rows_clean', 0):,} (cleaned)"
    notes = d.get("access_notes") or ""
    return notes.split(",")[0][:24] if notes else "—"


def main() -> int:
    entries = sidecars()
    print(f"Building catalogue from {len(entries)} provenance sidecars\n")

    records = []
    for stem, d in entries:
        use = USES.get(stem, {})
        records.append({
            "layer": stem,
            "category": use.get("category", "Other"),
            "name": d.get("name", stem),
            "publisher": d.get("organisation"),
            "tier": d.get("tier"),
            "availability": d.get("availability"),
            "rows": rows_for(stem, d),
            "licence": d.get("licence") or f"[{d.get('licence_status', 'not stated')}]",
            "source_url": d.get("source_url") or "",
            "download_url": d.get("download_url") or "",
            "retrieved_at": (d.get("retrieved_at") or "")[:10],
            "powers": use.get("powers", ""),
            "why_it_matters": use.get("why_it_matters", ""),
            "caveats": " | ".join(d.get("caveats", [])),
        })

    records.sort(key=lambda r: (r["category"], r["tier"] or "", r["name"]))

    # --- machine-readable ------------------------------------------------
    (OUT / "catalogue.json").write_text(
        json.dumps({"datasets": records, "not_available": UNAVAILABLE},
                   indent=2), encoding="utf-8")
    with (OUT / "catalogue.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)

    # --- human-readable --------------------------------------------------
    lines: list[str] = [
        "# Dataset catalogue",
        "",
        "**Generated by `datasets/build_catalogue.py` — do not edit by hand.**",
        "It is built from the provenance sidecar each ingest writes beside its",
        "output, so it cannot drift from what was actually downloaded.",
        "",
        f"{len(records)} datasets in use. Every one is public; none required a",
        "credential, and none was scraped from a source whose terms forbid it.",
        "",
        "## Provenance tiers",
        "",
        "| Tier | Meaning | Max confidence |",
        "|---|---|---|",
        "| T1 | Official primary, retrieved directly from the authority | 0.95 |",
        "| T2 | Official data republished through a portal | 0.85 |",
        "| T3 | Community / open data (OpenStreetMap, civic tech) | 0.70 |",
        "| T4 | Public dataset, not a government register | 0.55 |",
        "",
        "**No dataset here is T1.** Every government layer reached this project",
        "through a portal or a community mirror, and confidence is capped",
        "accordingly. That is a finding about Indian property data availability,",
        "not a shortcut.",
        "",
    ]

    current = None
    for r in records:
        if r["category"] != current:
            current = r["category"]
            lines += ["---", "", f"## {current}", ""]
        lines += [
            f"### {r['name']}",
            "",
            f"- **Publisher** {r['publisher']}",
            f"- **Tier** {r['tier']} · **Availability** {r['availability']}"
            f" · **Records** {r['rows']}",
            f"- **Licence** {r['licence']}",
        ]
        if r["source_url"]:
            lines.append(f"- **Source** <{r['source_url']}>")
        if r["download_url"] and r["download_url"] != r["source_url"]:
            lines.append(f"- **Downloaded from** <{r['download_url']}>")
        if r["retrieved_at"]:
            lines.append(f"- **Retrieved** {r['retrieved_at']}")
        if r["powers"]:
            lines.append(f"- **Powers** {r['powers']}")
        if r["why_it_matters"]:
            lines += ["", f"**Why it matters.** {r['why_it_matters']}"]
        if r["caveats"]:
            lines += ["", "**Caveats**", ""]
            lines += [f"- {c.strip()}" for c in r["caveats"].split("|") if c.strip()]
        lines.append("")

    lines += [
        "---",
        "",
        "## Datasets that exist but could not be used",
        "",
        f"{len(UNAVAILABLE)} sources were examined and are not obtainable. This",
        "list is the more important half of the catalogue: it is why several",
        "modules return UNAVAILABLE rather than a number, and it is the project's",
        "central finding.",
        "",
        "| Feature | Authority | Classification | Why not |",
        "|---|---|---|---|",
    ]
    for u in UNAVAILABLE:
        link = f"[{u['authority']}]({u['url']})" if u["url"] else u["authority"]
        lines.append(f"| {u['feature']} | {link} | `{u['classification']}` | "
                     f"{u['why']} |")

    lines += [
        "",
        "---",
        "",
        "## Collection policy",
        "",
        "Enforced in code by `etl/http/client.py`, the only sanctioned way this",
        "project makes an outbound request:",
        "",
        "- `robots.txt` is respected. No exceptions.",
        "- Seven OTP-gated government portals are hard-blocked at the client, so",
        "  no future code path can accidentally hit them.",
        "- A descriptive User-Agent identifies the project on every request.",
        "- Rate limits are respected; Nominatim is capped at 1 request/second.",
        "- No personal data is collected, and no source whose terms forbid",
        "  automated access is fetched.",
        "",
    ]

    (OUT / "CATALOGUE.md").write_text("\n".join(lines), encoding="utf-8")

    by_cat: dict[str, int] = {}
    for r in records:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat:<38} {n}")
    print(f"\n  {len(records)} datasets in use, {len(UNAVAILABLE)} documented as "
          "unobtainable")
    print(f"  wrote CATALOGUE.md, catalogue.csv, catalogue.json to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

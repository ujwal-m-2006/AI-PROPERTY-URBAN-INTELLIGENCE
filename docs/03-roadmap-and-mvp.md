# Roadmap, MVP Definition & Limitations
**Bengaluru AI Property & Urban Intelligence Platform**
Version 0.1 — 2026-08-09

---

## 1. The scope problem, stated plainly

The specification contains 40 modules. A realistic delivery capacity for one final-year student over ~9 months, alongside coursework, is roughly **12–15 modules built properly**.

"Built properly" means: real data ingested, provenance tracked, tested, and demonstrable to an examiner who asks *"where did this number come from?"* — a question that will be asked, and that kills projects whose answer is "the model".

Forty shallow modules is a worse project than twelve deep ones, and the difference is visible within thirty seconds of a demo. The phasing below front-loads everything that is both **buildable with real data** and **visibly impressive**, and defers everything gated on data that does not exist.

---

## 2. MVP definition — exact scope

### MVP name
**"Greater Bengaluru Location & Development Intelligence"**

### MVP thesis
> Click anywhere in Greater Bengaluru. Get the correct current jurisdiction, what the regulations indicate can be built there under stated assumptions, what infrastructure surrounds it, an estimated market range, and a completely explicit account of which of those facts is verified and which you must go and confirm — including which office to confirm it at.

Note what is **not** in that sentence: any claim to hold government property records. That restraint is the strategy, not a compromise.

### MVP — in scope (8 modules, complete and deep)

| Module | Delivered as | Data foundation |
|---|---|---|
| **M1 Jurisdiction** | Corporation / zone / ward / ward no. / division / sub-division from any point | GBA 369-ward KML (T2, high confidence) |
| **M22 GIS map** | MapLibre, tiered layers, search, click, layer catalogue with licences | PostGIS + Martin MVT |
| **M6 Feasibility rules engine** | YAML rules with citations; FAR/setback/height/coverage; `blocking_unknowns`; assumptions surfaced | RMP-2015 zoning regulations |
| **M9 Transport** | Nearest metro/rail/bus/airport + connectivity score | OSM + community GTFS (T3) |
| **M11 Amenities** | Health, education, daily-life, emergency + accessibility scores | OSM (T3) |
| **M10 Government offices** | Locations **plus jurisdiction mapping**, "which office for which issue" | OSM + official notifications |
| **M23 Confidence system** | `Fact[T]` everywhere, category scores, min-not-mean overall | Core framework |
| **M24 Provenance** | Source drawer with full derivation chains | `meta.data_sources` + `fact_provenance` |

### MVP — explicitly out of scope
ML price prediction · future price · demand · document OCR · builder ROI · government dashboard · PDF reports · investor comparison · flood risk.

These are Phase 2+. Several appear in the MVP demo as visible, labelled "coming in Phase N" placeholders — which is honest and, in a viva, reads as planning rather than as a gap.

### MVP acceptance criteria
1. Any click within GBA limits returns the correct corporation and ward, validated against ≥ 50 known addresses spanning all five corporations.
2. Every displayed value opens a source drawer showing tier, source, retrieval date, and — if computed — its derivation chain.
3. The feasibility calculator returns `UNAVAILABLE` with a stated reason wherever inputs or verified rules are missing, and **never** substitutes a default.
4. Zero fabricated government records. Enforced by test: no code path writes to a records table from any non-upload source.
5. Full stack runs from `docker compose up` on a clean machine.
6. Derived layers are visually distinguishable (hatched) from authoritative layers at every zoom level.

---

## 3. Phased plan

Durations assume roughly 15–20 hours/week.

### Phase 0.5 — Close the research gaps · 1–2 weeks · **NOW**
Answer R1–R8 from the audit. Deliverable: audit v1.0 with no `UNKNOWN` rows in the P0 set.
**Gate: R1, R5, R8 answered before Phase 2.**

### Phase 1 — Foundation · 2 weeks
Repo, Docker Compose (Postgres+PostGIS, Redis, MinIO, API, web), Alembic, CI, the `Fact[T]` framework and confidence engine **with tests**, `data_sources` + `fact_provenance` tables, the ethical HTTP client.

> Build `Fact[T]` first. Retrofitting provenance onto a system that already returns bare floats is a rewrite, and it is the single most common way this kind of project ends up unable to answer the examiner's question.

### Phase 2 — GBA boundaries · 2 weeks
Ingest the 369-ward KML; validate and repair geometry; dissolve to corporations and GBA outline; load divisions/sub-divisions CSV; temporal boundary tables; historical BBMP wards as reference only. **Validate against ≥ 50 known addresses.**

### Phase 3 — Jurisdiction service + map shell · 2 weeks
`/jurisdiction`, Martin tiles, MapLibre shell, layer catalogue, first working source drawer. *First demo-able milestone.*

### Phase 4 — Search & geocoding · 2 weeks
Self-hosted Nominatim, locality gazetteer, fuzzy search, map click, reverse geocode, match-confidence propagation.

### Phase 5 — Proximity intelligence · 2 weeks
OSM ingest, amenity/transport/office tables, KNN queries, connectivity & accessibility scores, community GTFS stop locations, government-office jurisdiction mapping.

### Phase 6 — Land use layer · 3 weeks *(gated on R4/R5)*
Georeference RMP map sheets, digitise zones for a **pilot area first** (do not attempt all of Greater Bengaluru), `is_derived` enforcement, hatched rendering, land-use compatibility score.

> Scope control: digitise 2–3 planning districts thoroughly rather than the whole city badly. Coverage gaps render as GREY, which is correct behaviour, not a bug.

### Phase 7 — Rules engine · 4 weeks *(gated on R2/R3)*
Encode RMP-2015 zoning with clause citations; YAML loader with citation enforcement; evaluator; golden + property-based tests; `blocking_unknowns`; feasibility UI. **The technical centrepiece — do not rush it.**

### ▶ MVP COMPLETE — approximately month 5

### Phase 8 — Market dataset · 3 weeks *(gated on R6)*
Licensed/ethical listing acquisition, cleaning, outlier detection, ward join, guidance-value reference table, three-way price separation enforced in schema.

### Phase 9 — Price model · 3 weeks
Feature store, baselines, RF/XGB/LGBM, **spatial-block CV**, Optuna, conformal intervals, SHAP, MLflow, model card.

### Phase 10 — Buyer & builder modes · 3 weeks
Fair-value band vs asking price, builder ROI with best/base/worst scenarios and sensitivity analysis, development-potential scoring.

### Phase 11 — Document intelligence · 3 weeks
Consent flow, encrypted upload, OCR extraction, field matching → MATCH/MISMATCH/MISSING/UNVERIFIED, official deep-links, audit logging.

### Phase 12 — Reports · 2 weeks
25-section PDF with provenance appendix and disclaimers.

### Phase 13 — Government dashboard · 3 weeks
Ward-level metrics, underserved-area analysis, development-pressure indicators.

### Phase 14 — Future price, demand index, risk · 3 weeks *(gated on data sufficiency)*
Only what the data supports. **Cut without hesitation if it does not.**

### Phase 15 — Hardening & deployment · 3 weeks
Security review, load testing, accessibility audit, documentation, deployment.

**Total ≈ 40 weeks with gates.** Phases 13–14 are the designated cut line if time compresses.

---

## 4. Limitations to state in the project report and the UI

These belong in the dissertation as a *Limitations* chapter. Stating them proactively is a mark of rigour; having an examiner find them is not.

1. **No government property records are accessible programmatically.** Khata, tax, sanctioned plan, OC and CC status cannot be auto-verified. The platform links and checks user-supplied documents; it does not hold official records.
2. **Khata is not title.** Stated in the UI, the PDF, and the report.
3. **Land use is derived** from georeferenced raster plans and is indicative only.
4. **The operative zoning instrument is RMP-2015 as amended**; RMP-2031 is draft/withdrawn. Amendments after the encoding date may not be reflected. Every assessment prints its ruleset version.
5. **Road width is usually user-supplied**, and feasibility output is only as good as that input.
6. **Price models train on asking prices**, not registered transactions, and therefore carry a systematic upward bias.
7. **Bus timing data is community-sourced and unreliable**; only stop locations are used.
8. **Survey-number geometry (Dishaank) is notional**, with GPS error of 3–10 m or worse, and is not valid for boundary determination.
9. **Flood/drain proximity is computed**, not an official flood declaration, wherever authoritative geometry is unavailable.
10. **The government dashboard is a research prototype** and is not an official decision system.
11. **Coverage is uneven** — OSM completeness and land-use digitisation vary across Greater Bengaluru. Gaps render GREY rather than being interpolated.
12. **The platform does not replace** government approval, legal title verification, advocate due diligence, plan sanction, surveyor verification, planning-authority confirmation, registration verification, or professional valuation.

---

## 5. Post-MVP / startup-track features

Deliberately excluded from the academic scope, listed because the specification asks and because they shape what not to foreclose:

- **Road-network isochrones** (OSRM) replacing straight-line distance — a large realism gain for connectivity scores.
- **Change detection** from satellite imagery for construction-activity metrics — genuinely novel, publishable, and unblocked by any of the record-access problems above.
- **Automated gazette watch** — scheduled diffing of Karnataka Gazette publications against the encoded ruleset. Solves the amendment-staleness risk permanently and is a strong differentiator.
- **Comparable-sales engine** if licensed transaction data ever becomes obtainable.
- **Portfolio mode** for investors; **project pipeline mode** for builders.
- **Official partnership track** — a GBA or BDA MoU converts most `PORTAL` rows in the audit into `API` rows and is the only route to a genuinely record-integrated product.
- **Multilingual UI** (Kannada first) — materially widens real-world usefulness.
- **Public API** with tiered keys.

---

## 6. What makes this project distinctive

Worth being explicit, because it determines where effort should go:

The novelty is **not** the price model — Bengaluru house-price prediction is the most over-done project in Indian AIML departments, and an examiner has seen forty of them.

The novelty is:
1. A **cited, versioned, testable regulatory rules engine** for Bengaluru development control — genuinely uncommon, and defensible as engineering.
2. A **calibrated confidence and provenance system** where every value is traceable to its source and no derived value outranks its inputs.
3. **Correct current GBA jurisdiction** at a time when most tools and datasets still assume BBMP — a real, current, verifiable advantage.
4. **Structural refusal to fabricate**, in a domain where fabrication is the norm and the consequences are financial.

Effort should be weighted accordingly. A viva panel remembers the system that said *"I cannot verify this, here is exactly why, and here is the office that can"* far longer than one that reported R² = 0.94 on a random split of scraped listings.

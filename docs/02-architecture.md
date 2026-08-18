# System Architecture
**Bengaluru AI Property & Urban Intelligence Platform**
Version 0.1 — 2026-08-09 — pre-implementation

> Read [01-data-source-audit.md](01-data-source-audit.md) first. Every design decision below follows from it.

---

## 1. Architectural principle

One idea governs the whole system:

> **Every fact the platform emits carries its provenance and its confidence, and no derived value can be more confident than its weakest input.**

This is not a feature bolted on at the end (Module 23/24). It is the **type system**. A bare `float` for FAR does not exist anywhere in this codebase. Everything user-facing is a `Fact<T>`:

```python
class Fact(BaseModel, Generic[T]):
    value: T | None
    unit: str | None
    status: Literal["VERIFIED","INDICATIVE","COMPUTED","ESTIMATED","UNAVAILABLE","CONFLICT"]
    tier: Literal["T1","T2","T3","T4","T5"]
    confidence: float            # 0..1
    source_id: UUID | None       # → data_sources
    retrieved_at: datetime | None
    valid_as_of: date | None
    assumptions: list[str]       # non-empty whenever status == COMPUTED
    caveats: list[str]
    provenance_chain: list[UUID] # inputs, for derived facts
```

Rules enforced in code, tested, not left to discipline:
- `status == UNAVAILABLE` → `value is None`. The UI renders GREY. There is no fallback default, ever.
- `status == COMPUTED` → `assumptions` must be non-empty.
- `confidence(derived) ≤ min(confidence(inputs)) × method_factor`.
- `tier(derived) = T5` always.
- Serialising a `Fact` without its provenance is a lint error.

This single decision is what makes Module 38 ("never silently invent") structurally true rather than aspirational.

---

## 2. Context & container view

```
┌──────────────────────────────────────── USERS ────────────────────────────────────────┐
│   Buyer (mobile)   Investor   Builder (desktop)   Planner/Gov   Admin/Data steward     │
└───────────────────────────────────────┬───────────────────────────────────────────────┘
                                        │ HTTPS
┌───────────────────────────────────────▼───────────────────────────────────────────────┐
│  WEB — Next.js 15 (App Router) + TypeScript + Tailwind + MapLibre GL JS               │
│  Map shell · role dashboards · report viewer · document upload · source drawer        │
└───────────────────────────────────────┬───────────────────────────────────────────────┘
                                        │ REST/JSON  (+ /tiles for MVT)
┌───────────────────────────────────────▼───────────────────────────────────────────────┐
│  API — FastAPI (Python 3.12), Pydantic v2, JWT auth, rate limiting                     │
│  ┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬───────────────┐  │
│  │Jurisdict.│ Planning │  Rules   │ Nearby/  │  Risk    │ Market/  │  Document     │  │
│  │ service  │ service  │ engine   │ proximity│ service  │ ML svc   │  service      │  │
│  └──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴───────────────┘  │
│  ┌──────────────────────────── Fact assembler / confidence engine ────────────────┐   │
│  │        composes module outputs → 360° report DTO with provenance graph         │   │
│  └───────────────────────────────────────────────────────────────────────────────┘   │
└────────┬───────────────────────┬────────────────────┬───────────────────┬─────────────┘
         │                       │                    │                   │
┌────────▼────────┐   ┌──────────▼─────────┐  ┌───────▼────────┐  ┌───────▼──────────┐
│ PostgreSQL 16   │   │ Redis              │  │ Object storage │  │ MLflow           │
│ + PostGIS 3.4   │   │ cache + rate limit │  │ (MinIO/S3)     │  │ model registry   │
│ + pg_trgm       │   │ + job queue        │  │ docs, tiles,   │  │ + metrics        │
│ (facts + geom + │   │                    │  │ report PDFs    │  │                  │
│  provenance)    │   └────────────────────┘  └────────────────┘  └──────────────────┘
└────────▲────────┘
         │ writes only via ETL
┌────────┴──────────────────────────────────────────────────────────────────────────────┐
│  ETL — Prefect (or Dagster) orchestrated, Python + GeoPandas + Shapely                 │
│  ingest → validate → clean → normalise → geocode → dedupe → load → provenance stamp    │
└────────▲──────────────────────────────────────────────────────────────────────────────┘
         │
┌────────┴──────────────────────────────────────────────────────────────────────────────┐
│ EXTERNAL: OpenCity CKAN (GBA KML) · OSM/Overpass · SRTM/Bhuvan DEM · community GTFS ·  │
│ India Code & Gazette PDFs · K-RERA · [deep-links only: e-Aasthi, Kaveri, rh.bbmpgov]   │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

**Deliberately a modular monolith, not microservices.** One FastAPI app, hard module boundaries, one database. A solo final-year developer who splits this into services will spend the year on infrastructure instead of the product. The module boundaries below are clean enough to extract later if it ever becomes a company.

---

## 3. GIS architecture

### 3.1 Coordinate systems
- **Storage & API:** EPSG:4326 (WGS84).
- **All measurement** (area, distance, buffer, setback): EPSG:32643 (UTM 43N). Metres, minimal distortion over Bengaluru.
- Never compute area or distance in 4326. A helper `to_metric(geom)` is the only sanctioned path; direct `ST_Area` on a 4326 geometry fails CI.

### 3.2 Layer model
Three classes of layer, visually and structurally distinct:

| Class | Examples | Rendering |
|---|---|---|
| **Authoritative** (T1/T2) | GBA wards, corporations | Solid, saturated |
| **Community** (T3) | OSM roads, amenities, metro | Solid, muted |
| **Derived** (T5) | Digitised land use, DEM low-lying, price/demand heatmaps | **Hatched fill + dashed outline**, always |

The hatch pattern is the visual grammar of "we computed this". A user must never confuse a digitised land-use polygon with a notified one, and this is a rendering-level guarantee.

### 3.3 Tiles
- Boundary/infra layers → **Martin** or `pg_tileserv` serving MVT direct from PostGIS. No pre-generation, no rebuild step.
- Static reference layers → pre-baked PMTiles on object storage, cheap and CDN-friendly.
- Heatmaps → ward/H3-aggregated MVT, never raw points (avoids exposing point-level derived prices as if precise).

### 3.4 Core spatial operations
| Operation | Implementation | Index |
|---|---|---|
| Point → ward/corporation | `ST_Contains` on `wards` | GiST |
| Nearest-k amenities | `<->` KNN operator | GiST |
| Isochrone/radius | Buffer in UTM; road-network isochrones deferred to v2 | GiST |
| Boundary sanity | `ST_IsValid` + `ST_MakeValid` at ingest, non-negotiable | — |
| Ward aggregation | Materialised views, refreshed nightly | — |

### 3.5 Geocoding
Self-hosted **Nominatim** on the Bengaluru OSM extract, plus a locality gazetteer built from ward/division names with `pg_trgm` fuzzy match. Self-hosting avoids per-call cost, rate limits and third-party ToS problems, and keeps addresses off external services — which matters given the privacy posture. Every geocode result stores its match confidence and match type; a low-confidence geocode degrades every downstream fact.

---

## 4. Database architecture

PostgreSQL 16 + PostGIS 3.4. Schemas separate concerns and make the provenance rule enforceable:

```
raw        -- landing zone, immutable, as-fetched, one table per source+version
ref        -- reference/authoritative: boundaries, regulations, gazetteers
osm        -- OSM-derived features
market     -- listings, guidance values, price history
user_data  -- accounts, saved properties, uploaded documents  (encrypted, restricted)
analytics  -- materialised aggregates, ward metrics, heatmap sources
ml         -- feature store, predictions, model registry mirror
meta       -- data_sources, data_quality, audit_logs, rule_versions
```

### 4.1 The two tables everything hangs off

```sql
CREATE TABLE meta.data_sources (
    id              uuid PRIMARY KEY,
    name            text NOT NULL,
    organisation    text,
    source_url      text,                 -- never invented; NULL if none
    dataset_name    text,
    tier            text NOT NULL CHECK (tier IN ('T1','T2','T3','T4','T5')),
    availability    text NOT NULL CHECK (availability IN
                      ('API','DOWNLOAD','PORTAL','PARTIAL','UPLOAD','NONE','UNKNOWN')),
    licence         text,
    licence_url     text,
    retrieved_at    timestamptz,
    source_updated  date,
    method          text,                 -- 'http_download' | 'manual' | 'derived' | ...
    transformation  text,                 -- what we did to it
    access_notes    text,                 -- TLS exceptions, robots, rate limits
    max_confidence  numeric NOT NULL CHECK (max_confidence BETWEEN 0 AND 1),
    is_active       boolean DEFAULT true
);

CREATE TABLE meta.fact_provenance (
    id            uuid PRIMARY KEY,
    entity_type   text NOT NULL,      -- 'property' | 'ward' | 'assessment'
    entity_id     uuid NOT NULL,
    field_path    text NOT NULL,      -- 'feasibility.far.value'
    source_id     uuid REFERENCES meta.data_sources(id),
    status        text NOT NULL,
    tier          text NOT NULL,
    confidence    numeric NOT NULL,
    assumptions   jsonb DEFAULT '[]',
    derived_from  uuid[] DEFAULT '{}', -- other fact_provenance ids
    computed_at   timestamptz DEFAULT now()
);
```

`derived_from` makes the provenance graph traversable — "View Source" (Module 24) walks it and renders the actual chain: *max built-up area ← FAR ← zoning regulation clause 4.2 ← RMP-2015 PDF p.34 ← India Code URL, retrieved 2026-08-09*. That traversal is the most convincing thing in the entire demo.

### 4.2 Entity groups

**Administrative (`ref`)** — `corporations`, `zones`, `wards` (369, `MULTIPOLYGON`, with `population`, `division`, `subdivision`, `notification_ref`, `valid_from`, `valid_to`), `historical_boundaries` (old BBMP 198/243 — historical only), `revenue_units` (district/taluk/hobli/village), `planning_authorities`.

> Boundaries are **temporal**. `valid_from`/`valid_to` on every boundary row, because Bengaluru just redrew them and will again. Every jurisdiction query is `WHERE valid_to IS NULL`. Historical price data joined to old wards stays correct.

**Property (`user_data` + `ref`)** — `properties` (a *user-created study subject*, not a government record), `property_identifiers` (typed key–value: PID/ePID/survey no./khata no., each with `source`, `entered_by`, `verified`), `documents`, `document_extractions`, `document_field_matches`.

> `properties` is deliberately **not** a mirror of a government register. It is "a location a user asked about". This naming keeps the team honest.

**Planning (`ref`)** — `regulations` (versioned rule sets), `regulation_clauses` (clause text + citation + effective dates), `land_use_zones` (digitised, `is_derived=true` NOT NULL DEFAULT true), `zoning_categories`.

**Infrastructure (`osm`)** — `roads`, `road_widths`, `road_history`, `metro_stations`, `metro_lines`, `railway_stations`, `bus_stops`, `government_offices`, `office_jurisdictions`, `hospitals`, `schools`, `colleges`, `police_stations`, `fire_stations`, `parks`, `lakes`.

**Risk (`ref`/`analytics`)** — `storm_water_drains`, `drain_buffers`, `flood_observations`, `terrain_low_lying` (derived), `environmental_risk_scores`.

**Market (`market`)** — `listings` (with `is_asking_price=true` NOT NULL), `transactions` (expected to stay sparse — kept so the schema tells the truth), `guidance_values`, `market_history`, `projects`, `builders`.

**ML (`ml`)** — `feature_snapshots`, `models`, `predictions` (with interval + confidence + model version + feature vector hash), `explanations` (SHAP payloads).

**Assessments (`analytics`)** — `feasibility_assessments`, `investment_analyses`, `reports`, `ward_metrics`.

**Meta** — `data_sources`, `fact_provenance`, `data_quality_checks`, `audit_logs`, `users`, `api_keys`.

### 4.3 Constraints that encode policy
```sql
-- A listing can never masquerade as a transaction
ALTER TABLE market.listings ADD CONSTRAINT listing_is_asking
  CHECK (is_asking_price = true);

-- Derived land use can never be marked authoritative
ALTER TABLE ref.land_use_zones ADD CONSTRAINT land_use_derived
  CHECK (is_derived = true);

-- Every prediction must record its interval
ALTER TABLE ml.predictions ADD CONSTRAINT prediction_has_interval
  CHECK (lower_bound IS NOT NULL AND upper_bound IS NOT NULL
         AND upper_bound >= lower_bound);
```
Policy in the schema survives refactors and new contributors. Policy in a code review does not.

---

## 5. The rules engine (Module 6/18) — the technical centrepiece

This is what makes the project a serious piece of engineering rather than a dashboard over a scikit-learn model. **It is not ML.** It is a versioned, cited, deterministic regulatory interpreter.

### 5.1 Design
Rules live in **YAML, not Python** — reviewable by a non-programmer, diffable, versioned, and every rule carries its legal citation:

```yaml
ruleset:
  id: rmp2015-zoning
  authority: BDA / Greater Bengaluru corporations
  source_document: "Zoning Regulations, Revised Master Plan 2015"
  source_url: "https://www.indiacode.nic.in/..."
  effective_from: 2007-06-25
  amendments:
    - id: premium-far-2025
      status: UNVERIFIED          # gazette copy not yet obtained
      effective_from: null
      note: "Premium FAR chapter reported added after Chapter 10, Feb 2025"
    - id: setback-parking-2026
      status: UNVERIFIED          # blocks encoding — see audit R2
      effective_from: null

  rules:
    - id: height-cap-narrow-road
      clause: "<clause ref pending verification>"
      when:
        road_width_m: { lt: 9 }
      then:
        max_height_m:
          value: 15
          includes_stilt: true
        overrides: [far_derived_height]
      note: "Height cap applies regardless of otherwise-applicable FAR"
      confidence: 0.9
      status: UNVERIFIED
```

### 5.2 Evaluation contract
Input: `plot_area`, `plot_dimensions`, `road_width` **+ its source flag**, `land_use`, `building_type`, `corner_plot`, `authority`.

Output — a `FeasibilityAssessment`, never a bare number:
```json
{
  "far":            { "value": null, "status": "UNAVAILABLE",
                      "reason": "Applicable FAR clause not yet verified (audit R2)" },
  "max_built_up":   { "value": null, "status": "UNAVAILABLE" },
  "max_height_m":   { "value": 15, "status": "COMPUTED", "confidence": 0.62,
                      "assumptions": [
                        "Road width 7.5 m as declared by user (source: ESTIMATED)",
                        "Residential main use assumed",
                        "Rule not yet verified against gazette"],
                      "rule_ids": ["height-cap-narrow-road"] },
  "potential_floors": { "status": "UNAVAILABLE",
                        "reason": "Depends on unverified FAR" },
  "overall_confidence": 0.62,
  "blocking_unknowns": ["verified FAR clause", "surveyed road width",
                        "notified land use for this parcel"]
}
```

### 5.3 Rules the engine obeys
1. **No rule without a citation.** A rule whose `clause` is empty cannot be loaded — startup fails.
2. **`UNVERIFIED` rules do not fire in production.** They are visible in a "pending verification" panel, so the work is transparent rather than silently missing.
3. **Missing input ⇒ `UNAVAILABLE` output.** Never a default, never an average, never a guess.
4. **Every output carries the rule IDs that produced it**, so the report can print exactly which clauses drove the answer.
5. **`blocking_unknowns` is a first-class output** — it tells the user precisely what to go and find out. In practice this is the most useful field in the whole platform.
6. **Rulesets are date-versioned.** An assessment records which ruleset version produced it and remains reproducible after amendments.

Test strategy: golden-file tests per rule, plus property-based tests asserting monotonicity (more road width never reduces permitted height; larger plot never reduces permitted built-up area) — these catch encoding errors that eyeballing never will.

---

## 6. ML architecture

### 6.1 Honest problem framing

| Model | Target | Label source | Verdict |
|---|---|---|---|
| **M1 — Price/sq.ft** | Listing ₹/sq.ft | Listings (T4) | Buildable. **Predicts asking price, not market value.** Name it that everywhere |
| **M2 — Fair-value band** | Range | M1 + guidance value + comparables | Buildable as a **band**, never a point |
| **M3 — Future price** | 1/3/5 yr change | Locality time series | **Only if ≥ 5 yrs × ≥ 8 quarters of locality history exists.** Otherwise ship city/ward-level trend with explicit "not a locality forecast" |
| **M4 — Demand** | HIGH/MED/LOW | **No ground truth exists** | Ship as a **transparent weighted composite index**, not a classifier. Calling an unlabelled heuristic a "model" is the most common way student projects lose credibility in a viva |
| **M5 — Development potential** | LOW/MED/HIGH | Rules + economics | Deterministic scoring, not ML |

**M4 deserves emphasis.** Predicting a label you have no ground truth for is not machine learning. An honest, documented, weighted index — with the weights exposed and adjustable in the UI — is defensible, explainable and more useful. If a supply/absorption proxy from K-RERA project data becomes available later, M4 can be upgraded to a real supervised model.

### 6.2 Pipeline
```
feature store (ml.feature_snapshots, point-in-time correct)
   → sklearn Pipeline (imputation, encoding, transforms — all inside the pipeline)
   → spatial-block CV  ←── critical
   → baseline: Linear Regression / locality median
   → candidates: RandomForest, XGBoost, LightGBM
   → Optuna tuning on the CV objective
   → conformal prediction for calibrated intervals
   → SHAP explanations, persisted
   → MLflow registry + model card
```

**Spatial-block cross-validation is mandatory.** Random k-fold on geographic data leaks neighbouring properties across folds and produces R² values that look brilliant and mean nothing. Split by ward, or by H3 cell. Report both random-CV and spatial-CV scores — the gap between them is itself a finding worth putting in the report, and it demonstrates methodological maturity.

**Conformal prediction** for intervals, not a Gaussian assumption. It gives distribution-free coverage guarantees and directly satisfies "do not provide fake precision".

Temporal split for M3 — train past, test future. Never random.

### 6.3 Guardrails
- A prediction outside the training distribution (novel locality, extreme area) returns `status: LOW_CONFIDENCE` with the reason, not a number.
- Every prediction persists: model version, feature vector hash, interval, SHAP values. Reproducible after retraining.
- Drift monitoring on feature distributions; alert on the admin dashboard.
- **No accuracy claim in any UI or document without the validation run that produced it**, including the CV scheme used.

### 6.4 Explainability (Module 34)
SHAP `TreeExplainer` on the tree models. Rendered as a waterfall against the locality median baseline, in plain language: *"₹2.1 L above the Hebbal median — metro proximity +₹0.9 L, plot size +₹0.5 L, building age −₹0.3 L."* Global importance on the ML dashboard; local explanation attached to every prediction.

---

## 7. API architecture

FastAPI, versioned under `/api/v1`. Every response envelope carries `data`, `provenance`, `confidence`, `disclaimers`.

```
# Location & jurisdiction
GET  /api/v1/jurisdiction?lat=&lng=          → corporation, zone, ward, division, revenue units
GET  /api/v1/geocode?q=                      → candidates with match confidence
GET  /api/v1/reverse-geocode?lat=&lng=

# Reference
GET  /api/v1/corporations
GET  /api/v1/corporations/{id}/wards
GET  /api/v1/wards/{id}
GET  /api/v1/planning-authority?lat=&lng=

# Property (user-scoped study subjects)
POST /api/v1/properties                      → create study subject
GET  /api/v1/properties/{id}
GET  /api/v1/properties/{id}/jurisdiction
GET  /api/v1/properties/{id}/planning
GET  /api/v1/properties/{id}/nearby?categories=&radius=
GET  /api/v1/properties/{id}/risks
GET  /api/v1/properties/{id}/market
GET  /api/v1/properties/{id}/records          → upload status + official deep-links (never fetched)

# Analysis
POST /api/v1/feasibility/evaluate            → rules engine (stateless, no property needed)
POST /api/v1/valuation/predict               → M1/M2 + interval + SHAP
POST /api/v1/investment/analyze              → builder ROI + scenarios
POST /api/v1/compare                         → investor mode, ranked
POST /api/v1/reports/generate                → async job → PDF

# Documents
POST /api/v1/documents                       → upload (consent required)
GET  /api/v1/documents/{id}/extraction
GET  /api/v1/documents/{id}/consistency      → MATCH/MISMATCH/MISSING/UNVERIFIED

# Map & planning
GET  /api/v1/map/layers                      → catalogue w/ tier + licence + attribution
GET  /tiles/{layer}/{z}/{x}/{y}.mvt
GET  /api/v1/analytics/wards?metric=

# Meta
GET  /api/v1/sources                         → the audit, live
GET  /api/v1/sources/{id}
GET  /api/v1/health
```

Design notes:
- `POST /feasibility/evaluate` is **stateless** — a builder can test hypothetical plots without creating records. This is the single most demo-able endpoint in the project.
- `/records` returns *link + status*, never fetched government content. The endpoint name and its docstring both say so.
- Errors use RFC 7807 `application/problem+json`, with `data_unavailable` / `source_conflict` / `low_confidence` as first-class problem types rather than 500s.

---

## 8. Frontend architecture

Next.js 15 App Router · TypeScript strict · Tailwind · shadcn/ui · MapLibre GL JS · TanStack Query · Zustand (map state) · Recharts.

```
Map shell (persistent, never unmounts)
  ├── Left rail    — layer catalogue, grouped by tier, each with licence + attribution
  ├── Map canvas   — MapLibre; authoritative solid / community muted / derived hatched
  └── Right panel  — context-driven, role-aware
        ├── Search & select
        ├── 360° report (accordion of module cards)
        ├── Feasibility calculator (live rules-engine calls)
        ├── Comparison tray
        └── Source drawer  ← slides over anything, shows the provenance chain
```

**The Source Drawer is the signature UI element.** Every single value in the app has a small ⓘ affordance; clicking it opens the drawer showing tier, source name, URL, retrieval date, assumptions, and — for computed values — the full derivation tree. Nothing else communicates the project's thesis as fast.

Colour semantics, applied strictly and *only* to data status (never decoration):
`GREEN` verified T1/T2 · `AMBER` computed/indicative, needs verification · `RED` conflict or identified risk · `GREY` unavailable.

Accessibility: status is never colour alone — icon + label always. Roughly 1 in 12 men has a colour-vision deficiency, and a due-diligence tool that hides risk in hue is a broken tool. Contrast targets WCAG AA.

Role routing: `/` public map · `/property/[id]` intelligence report · `/buyer` · `/investor` · `/builder` · `/planning` · `/admin` (data quality) · `/models` (ML dashboard).

Mobile: buyer flow is fully responsive with a bottom-sheet panel. Builder and planning dashboards are desktop-first and say so on small screens rather than degrading into unusable tables.

---

## 9. Security & privacy architecture

Given that this system touches property documents, privacy is not a checklist item — it is a design constraint.

| Layer | Measure |
|---|---|
| AuthN | JWT access (15 min) + refresh (7 d, rotating, revocable); Argon2id password hashing |
| AuthZ | RBAC: `anonymous`, `user`, `builder`, `planner`, `admin`. Row-level ownership on all `user_data` |
| Transport | TLS everywhere; HSTS |
| Documents | Encrypted at rest (per-object key, envelope encryption); pre-signed short-TTL URLs; **never public** |
| PII minimisation | Owner names extracted from documents are stored **encrypted, owner-scoped, never indexed, never in analytics, never in tiles**. Excluded from ML features by schema, not by convention |
| Input validation | Pydantic on every endpoint; explicit bounds on lat/lng, area, coordinates |
| Injection | SQLAlchemy parameterised throughout; **no string-built SQL, including PostGIS predicates** |
| File upload | MIME sniffing, size caps, ClamAV scan, render-to-image before OCR (defuses malicious PDFs) |
| Rate limiting | Redis token bucket, per-IP and per-key; stricter on ML and report endpoints |
| Audit | Append-only `meta.audit_logs` on every document, report and record access |
| Retention | User documents auto-purged on a stated schedule; explicit consent captured before upload with the purpose recorded |
| Secrets | Environment/secret manager; no credentials in the repo; pre-commit secret scanning |
| Scraping ethics | Enforced in code — a shared HTTP client that checks `robots.txt`, applies per-host rate limits, refuses OTP/captcha/login-gated hosts by allowlist, and writes a provenance row before any payload is used |

The scraping-ethics client deserves note: making the polite behaviour the *only available* code path is far more reliable than documenting a policy and hoping.

**Threat to name explicitly:** the greatest harm this system can do is not a breach — it is a confidently wrong statement causing someone to buy an unbuildable or encumbered plot. Confidence calibration is therefore a *safety* control, not a UX nicety, and belongs in the same review process as the security controls above.

---

## 10. Repository structure

```
gba-property-intelligence/
├── README.md
├── docker-compose.yml
├── Makefile
├── docs/
│   ├── 01-data-source-audit.md
│   ├── 02-architecture.md
│   ├── 03-roadmap-and-mvp.md
│   ├── adr/                          # architecture decision records
│   ├── regulations/                  # source PDFs + extraction notes
│   └── model-cards/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/                     # config, security, deps, problem+json
│   │   ├── facts/                    # Fact[T], confidence engine  ← read this first
│   │   ├── db/                       # models, session, migrations (Alembic)
│   │   ├── api/v1/                   # routers
│   │   ├── services/
│   │   │   ├── jurisdiction/
│   │   │   ├── planning/
│   │   │   ├── rules_engine/         # evaluator + loader + tests
│   │   │   ├── proximity/
│   │   │   ├── risk/
│   │   │   ├── market/
│   │   │   ├── documents/
│   │   │   └── reports/
│   │   └── ml/                       # inference, explainers, registry client
│   ├── rules/                        # ★ YAML rulesets, versioned, cited
│   │   └── rmp2015/
│   └── tests/
├── etl/
│   ├── flows/                        # Prefect flows per source
│   ├── connectors/                   # opencity, osm, dem, gtfs, rera
│   ├── transforms/
│   ├── validators/                   # Great Expectations suites
│   └── http/                         # the ethical HTTP client
├── ml/
│   ├── notebooks/                    # exploration only — never the pipeline
│   ├── pipelines/                    # training entry points
│   ├── features/
│   ├── evaluation/                   # spatial CV, error analysis
│   └── conf/
├── frontend/
│   ├── app/                          # Next.js routes
│   ├── components/{map,report,charts,ui}/
│   ├── lib/{api,types,fact-rendering}/
│   └── styles/
└── infra/
    ├── docker/
    ├── tiles/                        # martin config
    └── ci/
```

`backend/rules/` sitting at the top level, outside `app/`, is intentional: the regulatory encoding is a **deliverable in its own right**, reviewable by someone who does not read Python.

---

## 11. Technology choices & justification

| Choice | Why | Rejected alternative |
|---|---|---|
| PostgreSQL + PostGIS | The only realistic option — spatial predicates, indexing, tile serving from one store | MongoDB (weak spatial); SQLite/SpatiaLite (no concurrency, no MVT) |
| FastAPI | Pydantic v2 gives runtime-validated `Fact[T]`; async; auto OpenAPI | Django (ORM fights PostGIS raw queries); Flask (build everything yourself) |
| MapLibre GL JS | Vector tiles, GPU rendering, data-driven styling for the hatched-derived rule; no licence key | Leaflet (raster-oriented, weaker at 369 polygons + heatmaps); Mapbox GL (licence/cost) |
| Next.js App Router | SSR for reports, streaming, one deployable frontend | CRA/Vite SPA (worse SEO, worse report rendering) |
| Martin / pg_tileserv | MVT straight from PostGIS, no tile build step | GeoServer (heavy, Java, painful ops for one dev) |
| Prefect | Python-native, readable retries, local-first | Airflow (operationally heavy for a solo project) |
| MLflow | Free, local, gives model versions + metrics + artefacts | Ad-hoc pickles (unreproducible, unviva-able) |
| Optuna | Efficient search, integrates with spatial-CV objective | GridSearchCV (wasteful) |
| Conformal prediction | Distribution-free calibrated intervals | Quantile regression (fine, but weaker coverage guarantees) |
| YAML rules | Reviewable by non-programmers; diffable; citable | Rules in Python (unauditable, untestable as regulation) |
| Self-hosted Nominatim | No cost, no rate limit, addresses stay in-house | Google Geocoding (cost, ToS on storage, privacy) |
| Docker Compose | One-command reproducible env for demo and marking | Kubernetes (absurd at this scale) |

---

## 12. Cross-cutting: the confidence engine

```
confidence(fact) = tier_ceiling(source)
                 × completeness(inputs)
                 × recency_decay(source_updated, half_life_by_layer)
                 × method_factor(exact_match | spatial_join | interpolation | ml)
                 × (1 − conflict_penalty)
```

Category scores (jurisdiction / planning / records / infrastructure / risk / market) are reported separately, and the **overall score is the minimum, not the mean**. A report with perfect jurisdiction data and zero record data is not "75% confident" — it is *unverified on records*, and averaging hides exactly the thing the user needs to see.

Conflict detection is explicit: when two sources disagree beyond tolerance (e.g. document says 2,400 sq ft, GIS parcel says 2,050 sq ft), the fact becomes `CONFLICT`, both values are shown with their sources, and no resolution is invented.

---

## 13. Known architectural risks

| Risk | Impact | Mitigation |
|---|---|---|
| Zoning amendments unverified (audit R2/R3) | Rules engine legally wrong | `UNVERIFIED` rules do not fire; gazette watch; version every ruleset |
| Land-use georeferencing error | Wrong zone → wrong feasibility | Always AMBER; show source map sheet; never state permitted use as fact |
| Road width unavailable | Feasibility unusable | User-declared + source flag; confidence bounded; `blocking_unknowns` |
| Listing-price bias | Systematic over-valuation | Label as asking price; band not point; disclose bias in every output |
| Thin time series | M3 not credible | Ship ward/city trend, not locality forecast, until data supports it |
| GBA boundaries change again | Stale jurisdiction | Temporal boundary tables; quarterly re-check |
| Scope (40 modules, one student, one year) | Nothing finished | Phased plan; MVP is 8 modules — see [03-roadmap-and-mvp.md](03-roadmap-and-mvp.md) |
| Liability from a wrong risk call | Real-world harm | Three-tier risk badges; disclaimers in UI *and* PDF; never assert drain/flood status without authoritative geometry |

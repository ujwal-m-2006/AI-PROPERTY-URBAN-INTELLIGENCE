# Existing Project Audit & Final Implementation Plan
**Date:** 2026-08-09 · **Purpose:** SRM University BTech AIML 100-mark ML project
**Rule:** continue the existing project. Nothing is renamed, removed or rebuilt.

---

## 1. What is already implemented

| Layer | Implemented |
|---|---|
| Backend | FastAPI (`backend/app`), 9 endpoints, RFC-7807 problem responses |
| Provenance core | `Fact[T]` generic type + confidence engine (`app/facts/`) |
| GIS ingest | GBA 369-ward KML → validated GeoJSON (`etl/flows/ingest_gba_wards.py`) |
| Jurisdiction | Point-in-polygon ray casting over 369 wards (`app/services/jurisdiction.py`) |
| Proximity | OSM Overpass ingest + nearest-facility service (`app/services/proximity.py`) |
| Rules engine | YAML-driven, citation-enforced (`backend/rules/rmp2015/zoning.yaml`) |
| ML | Price model, spatial-block CV, conformal intervals (`ml/pipelines/train_price_model.py`) |
| Frontend | Single-page GIGW-style portal (`frontend/index.html`), MapLibre, 5 tabs |
| Tests | 49 passing |
| Infra | Docker Compose (Postgres+PostGIS, Redis, MinIO), Alembic-ready schema, CI |

## 2. What is currently working (verified this session)

- Jurisdiction lookup — correct across all 5 corporations, validated on 6 known locations
- Ward search — 369 wards, works with **no map click** (fallback if WebGL fails)
- Market estimate — auto-runs, returns band + conformal interval
- Development feasibility — auto-runs, returns UNAVAILABLE with reasons (correct)
- Data sources tab — layer catalogue with tier/licence
- Price model — 12,038 rows, HistGradientBoosting, spatial CV R² 0.3078
- Map — 369 ward polygons, corporation labels, hover tooltips *(rendering unverified in my sandbox — no WebGL)*

**In flight:** OSM amenity ingest, 18/21 categories done. `clinic` failed on all mirrors and needs a re-run.

## 3. Existing names — EXACT, to be preserved

**Application title:** `Greater Bengaluru Property & Urban Intelligence Platform`

**Existing tabs (exact strings in `frontend/index.html`):**

| `data-tab` | Visible label |
|---|---|
| `jurisdiction` | Jurisdiction |
| `nearby` | Nearby & connectivity |
| `market` | Market estimate |
| `feasibility` | Development feasibility |
| `sources` | Data sources |

**Existing panel headings:** Administrative Jurisdiction · Nearby & Connectivity · Market Estimate · Development Feasibility · Data Sources

**Existing internal group names** (in `proximity.py`): `transport`, `government`, `healthcare`, `education`, `daily_life`

### ⚠ Names in your instruction that DO NOT currently exist

Your brief says "KEEP the existing X — do not rename". These have never been built, so there is nothing to preserve. They will be **created new**:

`BUYER MODE` · `BUILDER MODE` · `INVESTOR MODE` · `GOVERNMENT / URBAN PLANNING MODE` ·
`ROAD INTELLIGENCE` · `TRANSPORTATION INTELLIGENCE` · `GOVERNMENT OFFICE INTELLIGENCE` ·
`NEARBY ESSENTIAL SERVICES` · `ENVIRONMENTAL / PHYSICAL RISK` · `Investment Score`

Closest existing equivalents: the **Nearby & connectivity** tab already contains transport, government-office and essential-services groupings — but not under those names. Your instruction 2 says "if the current project uses different names, preserve the current names instead", so **I will keep `Nearby & connectivity` as the tab and use your names as section headings inside it.** Nothing is renamed; names are added.

## 4. Existing Bengaluru functionality

- 369 GBA wards, 5 corporations (North 72, South 72, East 50, West 112, Central 63)
- Per-ward: ward no., name, Kannada name, zone, RO division, ARO sub-division, assembly constituency
- Corporation layer derived by grouping wards (`is_derived=true`, dashed rendering)
- Coverage check distinguishes "outside GBA" from "inside region, no ward" (e.g. ELCITA/Electronic City)
- Temporal boundary design — old BBMP 198/243 wards treated as historical only

## 5. Existing datasets

| Dataset | Rows/size | Tier | Location |
|---|---|---|---|
| GBA 369-ward final delimitation (KML) | 369 wards, 4.0 MB | T2 | `data/raw/gba-369-wards-december-2025.kml` |
| GBA ward→division mapping (CSV) | 369 | T2 | `data/raw/gba-wards-divisions-mapping.csv` |
| Bengaluru house listings (CSV) | 13,320 → 12,038 clean | **T4** | `data/raw/bengaluru_house_data.csv` |
| OSM amenities (Overpass) | ~12k features, in progress | T3 | `data/processed/osm_amenities.json` |

## 6. Existing ML functionality

**Present:** cleaning pipeline w/ logged filters · locality→ward fuzzy match (40.1%) · 4 algorithms
(median baseline, LinearRegression, RandomForest, HistGradientBoosting) · **random vs spatial-block CV
comparison** · split conformal intervals (90.0% measured coverage) · permutation importance ·
model card · `ml/artifacts/metrics.json` · 10 ML tests pinning the honesty properties

**Headline result:** with locality features, random k-fold R² **0.4729**, spatial-block CV R² **0.2477**
— **48% of the reported accuracy was geographic leakage.**

## 7. Existing APIs / data sources

`GET /health` · `GET /api/v1/jurisdiction` · `GET /api/v1/jurisdiction/wards` ·
`GET /api/v1/map/layers` · `GET /api/v1/map/layers/{name}` · `GET /api/v1/nearby` ·
`POST /api/v1/feasibility/evaluate` · `POST /api/v1/valuation/estimate` · `GET /api/v1/sources`

Sources: OpenCity CKAN (GBA wards) · OSM Overpass via community mirrors · India Code (RMP-2015 PDF) ·
GitHub-mirrored listing CSV. Full classification in `docs/01-data-source-audit.md`.

## 8. Missing ML components (measured against a 100-mark ML rubric)

| # | Missing | Severity for grading |
|---|---|---|
| 1 | **GIS features not used by the model** — OSM distances computed but never fed to ML | **critical** — this is the project's whole thesis |
| 2 | No EDA artefacts (distributions, correlations, target analysis, plots) | **critical** — explicitly required |
| 3 | No hyperparameter tuning (defaults only) | **critical** |
| 4 | No XGBoost / GradientBoosting (used sklearn HistGB) | high |
| 5 | No SHAP (permutation importance only) | high |
| 6 | No ML performance dashboard page | high |
| 7 | No demand model / score | high |
| 8 | No future-price model | high |
| 9 | No overpricing / anomaly detection | medium |
| 10 | No recommendation system | medium |
| 11 | No explicit train/val/test split reporting | medium |
| 12 | No classification metrics anywhere (confusion matrix, ROC-AUC) | medium |
| 13 | No actual-vs-predicted / residual plots | medium |

## 9. Missing data

- **Bengaluru listings have no coordinates** — only locality strings. GIS features therefore need a
  locality gazetteer before they can be computed. This is the key blocker for gap #1.
- No Bengaluru historical price series → future-price model not supportable from this dataset
- No labelled demand target → must be a transparent score, not a classifier
- No labelled risk target → same
- Government records (Khata, tax, approvals, land use, planning authority) — unavailable by API,
  unchanged from the Phase 0 audit

## 10. What can realistically be completed in one day

### Two findings that change the plan

**Finding A — the Chennai dataset is materially better than the Bengaluru one.**
`Ravi8149/Chennai-House-Price-Prediction/chennai-house-price.csv`, 7,109 rows:

```
PRT_ID, AREA, INT_SQFT, DATE_SALE, DIST_MAINROAD, N_BEDROOM, N_BATHROOM, N_ROOM,
SALE_COND, PARK_FACIL, DATE_BUILD, BUILDTYPE, UTILITY_AVAIL, STREET, MZZONE,
QS_ROOMS, QS_BATHROOM, QS_BEDROOM, QS_OVERALL, REG_FEE, COMMIS, SALES_PRICE
```

It carries **`DATE_SALE` and `DATE_BUILD`** and the target is a **recorded sale price with registration
fee**, not an asking price. So Chennai — not Bengaluru — is what makes **property age** and a genuine
**time-aware future-price model** possible. Chennai becomes the stronger ML story, and the Bengaluru
vs Chennai contrast (asking price vs sale price) is a real methodological talking point.

**Finding B — Chennai GIS is feasible.** OpenCity carries *GCC Ward Information* in **CSV + KML** for
Greater Chennai Corporation, so the existing `ingest_gba_wards.py` pattern transfers directly.

### Achievable in one day (in priority order)

✅ Locality gazetteer from OSM → geocode listing localities → **GIS distance features into the model**
✅ EDA notebook/script producing real plots
✅ XGBoost + GradientBoosting added; hyperparameter tuning (RandomizedSearchCV) on top-2
✅ SHAP explanations
✅ ML Performance dashboard tab
✅ Overpricing / anomaly detection
✅ Data-driven demand score + data-driven risk score (correctly labelled, not called ML)
✅ Recommendation system (KNN / cosine)
✅ Chennai tab: dataset, ward GIS, separate models under `models/chennai/`
✅ Chennai future-price model (dataset supports it)
✅ BUILDER MODE with ROI
✅ Bengaluru vs Chennai comparison

⚠ Deferred: PDF report · document OCR · road-widening · flood/rajakaluve (no authoritative geometry) ·
government record integration (no API) · LSTM (dataset does not justify it)

## 11. Exact files to MODIFY (nothing removed)

| File | Change |
|---|---|
| `frontend/index.html` | Add city switcher (Greater Bengaluru / Chennai); add tabs: ML Performance, Investment, BUILDER MODE, Compare Cities. **Existing 5 tabs untouched.** |
| `backend/app/api/v1/router.py` | Register new routers only |
| `backend/app/services/valuation.py` | Add `city` parameter; default `bengaluru` so existing calls are unchanged |
| `backend/app/api/v1/valuation.py` | Optional `city` field, defaults to bengaluru |
| `backend/app/services/proximity.py` | Parameterise data file by city |
| `ml/pipelines/train_price_model.py` | Add XGBoost/GBR, tuning, SHAP, GIS features, `--city` flag |
| `README.md`, `DEMO.md`, `docs/01-data-source-audit.md` | Register new sources and phases |

**Explicitly NOT touched:** `app/facts/*` · `app/services/jurisdiction.py` · `app/services/rules_engine.py` ·
`etl/flows/ingest_gba_wards.py` · `backend/rules/**` · all existing tests

## 12. Exact NEW files to add

```
etl/flows/ingest_locality_gazetteer.py     OSM place nodes -> locality coordinates
etl/flows/ingest_chennai_wards.py          GCC ward KML -> GeoJSON
etl/flows/fetch_chennai_dataset.py         Chennai sale dataset

ml/features/gis_features.py                distance features from OSM layers
ml/pipelines/eda.py                        EDA -> plots + eda_report.json
ml/pipelines/train_demand_model.py         demand score + risk score
ml/pipelines/train_future_price.py         Chennai temporal model
ml/pipelines/train_chennai_model.py        Chennai price model
ml/explain/shap_explainer.py               SHAP wrapper

models/bengaluru/                          (per your instruction 32)
models/chennai/

backend/app/services/cities.py             city registry + per-city paths
backend/app/services/anomaly.py            overpricing detection
backend/app/services/recommender.py        similar-property recommendation
backend/app/services/investment.py         Investment Score
backend/app/services/builder.py            BUILDER MODE ROI
backend/app/api/v1/ml.py                   ML performance dashboard API
backend/app/api/v1/cities.py               city list/switch
backend/app/api/v1/investment.py
backend/app/api/v1/builder.py

backend/tests/test_cities.py
backend/tests/test_anomaly.py
backend/tests/test_gis_features.py
```

---

# FINAL IMPLEMENTATION PLAN

| Phase | Work | Est. |
|---|---|---|
| **1 — Preserve & verify** | Finish OSM ingest, re-run failed `clinic`, run 49 tests, snapshot working endpoints as a regression baseline | 30 m |
| **2 — ML dataset** | Fetch Chennai dataset; register both in `data_sources` with tier/licence; build locality gazetteer from OSM | 45 m |
| **3 — Preprocessing** | Chennai cleaning pipeline (dates, typo-ridden categoricals, `SALES_PRICE` target); keep Bengaluru pipeline unchanged | 45 m |
| **4 — EDA** | `ml/pipelines/eda.py` → distributions, missingness, duplicates, outliers, correlation heatmap, price-by-locality, target skew. Real PNGs + JSON | 60 m |
| **5 — Feature engineering** | `price_per_sqft`, `property_age`, `area_per_bhk`, `bathroom_per_bhk`, `locality_median_price` (fold-safe), **+ GIS distances: metro, railway, bus, hospital, school, government office, main road** | 75 m |
| **6 — Model training** | LinearRegression, RandomForest, GradientBoosting, **XGBoost**; RandomizedSearchCV on top-2; spatial-block CV retained | 60 m |
| **7 — Model comparison** | MAE/RMSE/R²/MAPE table, random vs spatial CV, actual-vs-predicted, residual plots, feature importance | 45 m |
| **8 — Explainable AI** | SHAP TreeExplainer; global summary + per-prediction waterfall in plain language | 45 m |
| **9 — ML integration** | ML Performance dashboard tab; anomaly detection; demand score; risk score; recommender; Investment Score; BUILDER MODE | 90 m |
| **10 — Chennai tab** | City switcher; GCC ward ingest; Chennai jurisdiction + nearby | 60 m |
| **11 — Chennai ML** | Chennai price model → `models/chennai/`; **future-price model (1/3/5 yr)** using `DATE_SALE` | 60 m |
| **12 — Testing** | Full suite; assert no Bengaluru regression; assert city data never mixes | 30 m |
| **13 — Demo prep** | Update `DEMO.md` with the 13-step flow and evaluator Q&A | 30 m |

**Total ≈ 11 hours.** If time compresses, cut in this order: Compare Cities → recommender →
future-price → Chennai nearby. **Phases 4–8 are the graded core and are not cut.**

---

## Guarantees

1. No existing file is deleted; no existing name is changed.
2. `city` parameters default to `bengaluru`, so every current API call behaves identically.
3. Bengaluru and Chennai never share a dataset, a pipeline or a model directory.
4. Every metric shown comes from an actual run written to `ml/artifacts/`.
5. Anything computed by formula is labelled **DATA-DRIVEN SCORE**, never "ML".
6. The 49 existing tests must still pass at every phase boundary.

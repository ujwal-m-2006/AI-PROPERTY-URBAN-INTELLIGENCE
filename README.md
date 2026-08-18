# Bengaluru AI Property & Urban Intelligence Platform

A GIS + ML decision-support platform for property due diligence, development
feasibility and urban analysis across the **Greater Bengaluru Authority** area
(5 city corporations, 369 wards).

> **This is a research prototype.** It is not an official government system. It
> does not replace government approval, legal title verification, plan sanction,
> surveyor verification or professional valuation.

---

## The one thing to understand first

**Every user-facing value is a `Fact[T]`, never a bare number.** A fact carries
its source, provenance tier, status, confidence, and — if it was calculated —
the assumptions behind it. A derived value can never be more confident than its
weakest input, and that rule is enforced by validators, not by convention.

```python
from app.facts import Fact, Method

# Data we don't have is reported as missing. There is deliberately no way
# to supply a fallback value here.
far = Fact.unavailable("Applicable FAR clause not yet verified against gazette")

# Calculated values must declare what they assumed.
height = Fact.derive(
    15.0,
    inputs=[plot_area, road_width],
    method=Method.RULE_EVALUATION,
    assumptions=["Road width 7.5 m as declared by user (source: ESTIMATED)"],
    unit="m",
)
assert height.confidence <= min(plot_area.confidence, road_width.confidence)
```

Read `backend/app/facts/types.py` before anything else. The rest of the system
is built on top of it.

---

## Why the scope looks the way it does

A Phase 0 audit established that **no public API exists for any property-level
Bengaluru government record** — e-Khata/e-Aasthi, property tax, building
permission, occupancy and encumbrance certificates are all OTP- or
consent-gated per-property portals, and Karnataka does not publish transaction
prices.

So those modules are built as **upload → consistency-check → official
deep-link**, never as data integration. The platform tells you what it can
verify, what it cannot, and which office to go to. See
[docs/01-data-source-audit.md](docs/01-data-source-audit.md).

---

## Documentation

| Document | Contents |
|---|---|
| [01-data-source-audit.md](docs/01-data-source-audit.md) | Data-source audit, availability matrix, open research tasks |
| [02-architecture.md](docs/02-architecture.md) | System, GIS, database, rules engine, ML, API, UI, security |
| [03-roadmap-and-mvp.md](docs/03-roadmap-and-mvp.md) | Phases, MVP scope, limitations, future features |

---

## Quick start

```bash
docker compose up -d db redis minio
```

```bash
cd backend && pip install -e ".[dev]" && pytest
```

API docs at http://localhost:8000/docs once the `api` service is running.

---

## Cities

**Greater Bengaluru is the primary city.** Chennai is a second, fully separate
city: separate dataset, separate preprocessing, separate model directory
(`models/bengaluru/`, `models/chennai/`). Prices are never pooled — Bengaluru's
target is **asking price**, Chennai's is **recorded sale price**, and the two are
not comparable at row level. Enforced by tests in `backend/tests/test_cities.py`.

| | Greater Bengaluru | Chennai |
|---|---|---|
| Authority | GBA (5 corporations) | GCC |
| Wards | 369 | 200 (15 zones) |
| Records | 12,038 | 7,109 |
| Target | asking ₹/sq.ft | recorded sale ₹/sq.ft |
| Spatial blocks | 858 | **7** |
| Spatial-CV R² | **0.4231** | **0.3809** |
| Random-CV R² | 0.5473 | 0.9962 |
| Temporal features | no sale dates | `DATE_SALE`, `DATE_BUILD` |

## Status

**300 tests passing.** `cd backend && pytest`

**138/138 end-to-end checks passing**, every endpoint in both cities:
```bash
cd backend && PYTHONPATH=. python scripts/e2e_check.py
```

**All 40 specified modules verified against the live app** — 0 missing:
```bash
cd backend && PYTHONPATH=. python scripts/module_check.py
```

| Verdict | Count | Meaning |
|---|---|---|
| BUILT | 28 | evidence found in the running system |
| PARTIAL | 10 | some of the capability exists; the rest is stated as unavailable, not faked |
| NOT BUILDABLE | 2 | no lawful public source exists — the app says so |
| **NOT BUILT** | **0** | specified, buildable, and genuinely absent |

The two NOT BUILDABLE modules are Khata/tax status (3) and sanctioned plan/OC (7). Each is a per-property OTP-gated record or an
unpublished GIS layer; each returns UNAVAILABLE with a specific reason and a
deep-link to the office that can answer it. `module_check.py` derives every
verdict from a live probe, so it cannot drift from the code.

| Phase | State |
|---|---|
| 0 — audit & architecture | done |
| 1 — foundation (`Fact[T]`, provenance, ethical HTTP client) | done |
| 2 — GBA 369-ward ingest | done, validated |
| 3 — jurisdiction service + map | done |
| 4 — ward/locality search | done (works without the map) |
| 5 — proximity intelligence (Modules 9, 10, 11) | done; OSM via Overpass |
| 7 — rules engine | **4 clauses encoded** from the notification, each citing its page; FAR still not encoded |
| 9 — price model | done, both cities; 6 algorithms, tuning, SHAP |
| 10–11 — Chennai tab + ML | done |
| 15 — future price (temporal) | done, both cities |
| 21 — Government / Urban Planning | done, both cities |
| 19 — BUYER MODE | done |
| 20 — INVESTOR MODE | done |
| 28 — 360° PDF report | done, both cities |
| district + taluk (administrative boundaries) | done, **both cities, 100% of localities** |
| hobli / village / survey no. (revenue sheets) | done, Bengaluru only, **7% of localities** |
| market references — guidance value, transaction price | done; neither is fetched — see below |
| extra models — classification, clustering, anomaly | done, both cities |
| 8 — road intelligence | done, Bengaluru only, **partial coverage** |
| 27 — document intelligence | done; text-first, nothing stored |

### Two jurisdiction layers, and why the coverage numbers differ so much

| Field | Source | Bengaluru | Chennai |
|---|---|---|---|
| district, taluk | administrative boundary layer (T3, areal) | **100%** of localities | **100%** |
| hobli, village, survey number | revenue sheets (T2, cadastral) | **7%** | **0%** |

These answer different questions. *"Which taluk is this point in?"* is a boundary
question and a polygon layer answers it everywhere — 24 taluks for Bengaluru,
29 for Chennai. *"What is the survey number of this parcel?"* is a cadastral
question, answerable only where a revenue sheet is published.

**A boundary polygon cannot produce a survey number.** Widening areal coverage
from 3 taluks to the whole of both cities deliberately did not widen what the
platform claims to know about a parcel — a test asserts hobli, village and
survey number still refuse outside the sheets, with the reason.

Where a revenue sheet *does* cover the point it also supplies taluk at higher
confidence, and that T2 value wins over the T3 boundary value. Boundary-derived
values are `INDICATIVE`, never `VERIFIED`: the layer is republished from LGD and
Survey of India rather than fetched from them, and carries no per-boundary
vintage while both states have reorganised taluks in recent years.

### The revenue layer, and what it does not settle

Five fields the Phase 0 audit listed as `UNKNOWN` now resolve for part of
Bengaluru Urban, from 92 digitised revenue map sheets (3 taluks, 7 hoblis,
35 villages, 4,151 survey parcels):

* **Coverage is partial and says so.** Outside the published sheets the answer
  is `UNAVAILABLE`, naming the taluks actually held. The nearest parcel is
  never substituted — a neighbouring survey number is a different property.
* **A survey number here is `INDICATIVE`, never `VERIFIED`.** It is read from a
  digitised sheet, not a survey. Boundary, extent and title are settled by the
  Sub-Registrar and a licensed surveyor.

**Guidance value is not fetched.** Kaveri and TNREGINET are portal-only with no
public API and terms that do not permit automated retrieval. The platform links
to them and stores what a person looks up by hand, labelled `MANUAL ENTRY` with
attribution — never `VERIFIED`, because the platform did not retrieve it.

**Transaction prices stay `UNAVAILABLE` for Bengaluru,** because Karnataka does
not publish them and the Bengaluru dataset holds *asking* prices. Chennai is the
one place the project holds real recorded sale prices; its period ends in 2015
and is labelled historical everywhere it appears.

### Road intelligence, and the two-width problem

The BBMP road width map (23,324 segments, 2,240 km) publishes **two** widths per
segment, and they are not the same number:

| Source field | median | read as |
|---|---|---|
| `RR_width_B` | 9 m | existing carriageway width |
| `RR_WIDTH_P` | 18 m | proposed / planned width |

`RR_WIDTH_P` is larger on **100% of segments**. FAR, height and setback are
functions of road width, so quietly deriving one `road_width` from this file
would roughly double the floor area reported as permissible, city-wide, with no
visible symptom. The layer therefore keeps both fields under their source names,
derives no field called `road_width`, and excludes the proposed figure from
feasibility. It may only *offer* the existing width, flagged `dataset` — the
second-weakest of the four provenance flags feasibility accepts.

It is also **not the complete street network**: only 37% of localities have a
mapped segment within 150 m. Beyond that the answer is UNAVAILABLE, stated as a
gap in the layer rather than as an absence of road access.

### Module 12 — reported flooding, and the score it deliberately does not feed

391 reported flooding locations from three BBMP layers (locations vulnerable to
flooding, flood-prone locations, low-lying areas), public domain.

```bash
curl "localhost:8000/api/v1/flood?lat=12.9750&lng=77.6100&city=bengaluru"
```

**It is served as proximity only.** The environmental risk score still lists
flood as **excluded**, and a test fails if that ever changes. The source has no
return period, depth, drainage capacity or terrain — turning a list of reported
addresses into "flood risk 62/100" would manufacture a hazard model nobody
built, and it is the most tempting thing to do with this layer because it looks
exactly like the number the spec asks for.

Two asymmetries travel with every response:

* A nearby point is weak evidence flooding **has** occurred nearby.
* No nearby point is **not** evidence it hasn't — the dataset is a report, not
  a survey.

A test also asserts no response key is named like a score, so a future
`flood_risk_score` field cannot appear without failing the suite.

### Local-language ward names — both cities

Bengaluru showed a Kannada name on all 369 wards. Chennai showed one on **none**
of its 200 — not because the data was missing, but because the ward ingest
matched each ward to an OpenStreetMap locality, took `name`, and discarded the
rest of the record. `name_local` (the Tamil name) was there the whole time.

| | Local name | Coverage |
|---|---|---|
| Bengaluru | Kannada | 369 / 369 |
| Chennai | Tamil | **129 / 200 (64%)** |

Where several localities fall inside a ward, the join now prefers one that
carries a Tamil name — so the English and Tamil labels always describe the
**same** place, never two different ones.

**The other 71 wards are left blank on purpose.** OpenStreetMap has no `name:ta`
for those localities, and a machine-made Tamil spelling of an English name is
not a Tamil name. A test asserts some wards remain null, so if a transliteration
step is ever added the suite fails.

Both are labelled `DERIVED — not an official GCC ward name in Tamil`. The one
exception is the corporation itself: `பெருநகர சென்னை மாநகராட்சி` is GCC's own
published Tamil name, not derived.

Ward search indexes the local name too, so typing `எண்ணூர்` finds Ward 1.

### Model 1 — total price, and whether to model it directly

The project predicted price *per sq.ft* and never modelled what a buyer asks:
what does this cost. Adding it raised a question worth answering — model total
price directly, or model price per sq.ft and multiply by area?

Seven algorithms plus a median baseline, spatial-block CV, Bengaluru:

| Algorithm | R² | MAE | MAPE |
|---|---|---|---|
| baseline (median) | −0.076 | ₹5,509,009 | 48.0% |
| linear / ridge / lasso | 0.596 | ₹3,545,650 | 38.3% |
| decision_tree | 0.526 | ₹3,289,873 | 29.4% |
| random_forest | 0.645 | ₹3,096,470 | 29.0% |
| extra_trees | 0.657 | ₹3,078,378 | 28.9% |
| gradient_boosting | **0.674** | ₹3,030,257 | 29.1% |
| **indirect** (price/sq.ft × area) | **0.700** | **₹2,937,233** | **27.9%** |

**Indirect wins in both cities** — by 0.026 R² on Bengaluru and 0.087 on
Chennai. Total price spans two orders of magnitude and is dominated by area;
price per sq.ft is closer to stationary, leaving the model free to learn
location and quality rather than size. That retroactively justifies the target
this project already used.

**The instructive row is on Chennai.** Ridge scores **−2.36** and Lasso **+0.47**
— two linear models differing only in penalty, 2.8 R² apart. With 7 spatial
blocks the unpenalised fit extrapolates catastrophically onto held-out
localities; L1 shrinkage drops the features that cause it. Reporting only the
best model would have hidden that entirely.

**The number to quote is not R².** The best Bengaluru model is out by **27.9%**
on a median property of ₹68 lakh — roughly ₹19 lakh. That is what a buyer would
feel.

A leakage guard **raises rather than warns**: `price_per_sqft = price / area`, so
handing it to a model predicting price gives it the answer divided by a column it
already has. A leaked run still produces a number — a spectacular one — which is
why the guard is a hard failure and a test asserts no algorithm scores above 0.97.

### Cross-city transfer — the experiment, and why it fails

Transfer between the two cities was impossible until the schemas were
harmonised: of every column in the two datasets, **exactly one name matched**
(`area_per_room`). `sqft`/`INT_SQFT` and `rooms`/`N_BEDROOM` are the same
quantities under different names. That is a naming problem, not a research
finding, and fixing it unblocked the experiment.

Four experiments on a shared 16-feature vocabulary — 11 of them GIS features
that already matched — with one algorithm throughout:

| Experiment | Result |
|---|---|
| A · Bengaluru → Bengaluru | R² 0.328, Spearman **0.502** |
| B · Chennai → Chennai | R² 0.216, Spearman **0.496** |
| C · Bengaluru → Chennai | raw R² −0.923 · rank Spearman **0.105** |
| D · Chennai → Bengaluru | raw R² −1.617 · rank Spearman **−0.060** |

Every transfer is scored twice. **Raw** predicts rupees directly and is dominated
by the fact that Bengaluru's target is *asking* price and Chennai's is *recorded
sale* price — reporting that as model failure would be a misattribution.
**Rank** predicts within-city percentile, so price level cancels.

**The finding is negative and it survives the correction.** Within each city the
same model reaches Spearman ≈0.50; across cities it falls to roughly zero. What
identifies an expensive property in Bengaluru does not identify one in Chennai,
on the features the two datasets share.

**And a trap worth showing an examiner.** The combined model looks better:

| | R² | MAE |
|---|---|---|
| Separate (size-weighted) | 0.2863 | ₹1,723 |
| Combined + city flag | 0.3812 | ₹1,713 |

**R² +0.0949, MAE −10.** Pooling two different targets widens the variance R² is
scored against; MAE is in rupees and immune to that, and it barely moves. The
apparent gain is arithmetic, not skill — and a test fails if that verdict is
ever softened.

```bash
curl "localhost:8000/api/v1/cross-city"
```

### Planning ML — does every dataset earn its place?

The shipped price model used 20 features from two layers. Four more had been
ingested and no model had ever seen them: the road width map, reported flooding,
district/taluk boundaries, and the revenue sheets.

"Use all the datasets" is easy to satisfy dishonestly — bolt every column on and
report a number. So each layer was added in turn and scored under the **same
spatial-block CV** as the headline model, making the R² values directly
comparable:

| Feature set | Bengaluru R² | delta | verdict |
|---|---|---|---|
| property only | 0.3427 | — | baseline |
| + OSM amenities / wards *(shipped)* | 0.4109 | +0.0682 | **HELPS** |
| + road width & distance | 0.4217 | +0.0108 | **HELPS** |
| + reported flooding distance | 0.4151 | −0.0065 | **HURTS** |
| + taluk | 0.4216 | +0.0064 | **HELPS** |

**Reported-flooding distance makes the model worse.** It is reported as HURTS
rather than quietly kept — a feature that does not improve out-of-locality
generalisation is noise with a plausible name, and keeping it is how a model
degrades while its feature list grows. On Chennai, taluk hurts (−0.0120).

`width_proposed_m` is **excluded by name**, with a pipeline assertion that fails
if it reappears: it encodes a road-widening intention, not a present condition,
and feeding it to a price model would leak a planning decision into a market
prediction.

**Ward typologies** are unsupervised (KMeans, k by silhouette) because no dataset
carries an observed "development pressure" or "underserved" label — training
against a formula the project itself computed would be circular. Bengaluru scores
silhouette **0.2653**, below the 0.35 threshold, so it is flagged
`usable_for_classification: false`: the groups describe a gradient, not distinct
ward types. Chennai reaches 0.4445 and is usable.

```bash
curl "localhost:8000/api/v1/planning-ml/ablation?city=bengaluru"
```

### The trained-model registry — `Trained Models` tab

Eleven trained artefacts for Bengaluru, ten for Chennai, ~112 MB on disk. The
tab enumerates them from the **files themselves** — size and training time read
live — so a model that was never trained cannot appear, and the page cannot
drift from what is actually shipped.

```bash
curl "localhost:8000/api/v1/ml/registry?city=bengaluru"
```

Every entry carries a verdict, and the verdict is earned:

| Verdict | Bengaluru | Chennai |
|---|---|---|
| WORKS | 3 | 1 |
| WORKS WITH LIMITS | 6 | 6 |
| **TRAINED BUT NOT USABLE** | **2** | **3** |

The negatives are the point. Listed as unusable: Chennai's degenerate price-band
classifier, both cities' negotiation bands (coverage off target), Bengaluru's
refused forecast, and Chennai's forecast that loses to a naive baseline.

**Building the registry found two reporting bugs.** Bengaluru's future-price run
was being shown as *"not trained"* when it had in fact run, inspected the data,
found possession dates rather than sale dates, and **refused** — a decision
being flattened into an apparent gap. And Chennai's forecast was labelled WORKS
while `beats_naive_baseline` was `false`; a CAGR that cannot beat carrying the
last value forward has no predictive value, and now reads TRAINED BUT NOT
USABLE. Both are pinned by tests.

### Advisory ML — the negotiation band (buyer / seller / investor)

Quantile regression (P10/P50/P90) under pinball loss, conformalized (CQR), on
the same spatial-block split as everything else. It answers what a point
estimate cannot: a defensible offer, a realistic ask, and how wide the
uncertainty really is.

Three measured results, all reported rather than tuned away:

| | Bengaluru | Chennai |
|---|---|---|
| Raw band coverage (nominal 80%) | 67.1% | 63.7% |
| After conformal adjustment | **74.3%** (UNDER-covers) | **100%** (OVER-covers) |
| Same method, random split | 80.8% | 77.1% |
| Usable as an "80% band"? | **No** | **No** |

The random-split figure is the point. Conformal prediction guarantees coverage
only when calibration and test rows are **exchangeable**, and holding out whole
localities breaks that deliberately. The method reaches 80.8% where
exchangeability holds, so the shortfall is the honest cost of spatial
validation, not a broken implementation. Chennai's 100% is not "better" — on 7
spatial blocks the band is so wide it says nothing, and the app labels it
over-conservative.

**Partial dependence is filtered before it becomes advice.** An early run gave
`bath` a falling curve and the next gave it a rising one, on the same data with
a different fold. So each curve is refit on **three independent spatial splits**
and only reported directionally if all three agree. On Bengaluru **3 of 5 flip**
— `bath`, `rooms`, `balcony` — and the seller view excludes them by name, saying
why. Only `sqft` and `area_per_room` survive. Varying the estimator seed alone
would not have caught this, because the flip came from the fold.

Partial dependence is also declared **not causal** wherever it appears: it shows
how the model responds to a feature, never what changing that feature would earn.

### Headline ML findings (all from actual runs)

1. **GIS features earn their place.** Adding distance-to-metro/hospital/school/
   government-office and amenity density raised Bengaluru's honest spatial-CV R²
   from **0.3078 → 0.4231**, and `amenity_count_1km` is the strongest single
   correlate with price (r = 0.43).
2. **Random k-fold leaks.** Every model scores higher under random CV than under
   spatial-block CV. Model selection uses the lower number.
3. **Chennai is the cautionary tale.** Test R² reads 0.9969 on a random split,
   but the dataset covers only 7 localities — hold out a whole locality and
   random forest scores **−0.247**. The app displays a warning refusing to let
   the 0.997 be quoted as accuracy.
4. **The same failure repeats in classification.** A price-band classifier
   reaches macro F1 **0.5159** on Bengaluru against a 0.333 chance line, but on
   Chennai it collapses to predicting one class — recall 1.000 for Budget,
   0.000 for Mid-market. Its 0.366 accuracy is reported as a **degenerate
   model**, not as a result.
5. **Unsupervised ML agrees with the regression.** KMeans on locality features
   picks k = 3 by silhouette (0.5543) and separates 77 premium Bengaluru
   localities — Jayanagar, Koramangala, Indiranagar among them — at roughly
   ₹10,000/sq.ft. Nothing labelled them; the features did.

See [docs/model-cards/price-model.md](docs/model-cards/price-model.md) and
[docs/04-existing-project-audit.md](docs/04-existing-project-audit.md).

### Phase 0.5 — the research tasks were actually worked (2026-08-12)

The audit shipped with eleven open research tasks. Six are now closed against
primary sources, and the two that could not be answered say so:

| Task | Outcome |
|---|---|
| R2 zoning amendment | **Closed** — UDD 235 MNJ 2025, notified 05.01.2026 |
| R3 GBA bye-laws | **Closed — yes, and there are five, one per corporation**, effective 14.05.2026 |
| R4 RMP-2031 | **Closed** — still not notified; RMP-2015 remains operative |
| R5 planning-authority GIS | **Closed — no such layer exists.** PDF maps only |
| R8 OpenCity licence | **Closed** — public domain, redistribution permitted |
| R9 ward population | **Partly closed** — ~6x inflation characterised; field stays suppressed |
| R1 BBMP GIS viewer | **Not answered** — host still unreachable, same TLS fault |

Three of these are worth reading in full in
[docs/01-data-source-audit.md §7](docs/01-data-source-audit.md):

**R3 changed a design.** Building bye-laws are issued *per city corporation* —
five separate instruments, not one Bengaluru rule set. The rules engine must key
on corporation, which Module 1 already resolves as a `VERIFIED` fact.

**R9 is the one worth defending in a viva.** Dividing the suppressed `TOT_P`
field by 6 reproduces the published per-corporation ward averages almost exactly
— including East's distinctly lower ~26,000, which nothing was fitted to — and
the total lands on 14.0M against a real ~14M. It was still **not implemented**:
the mechanism is unexplained, and 125 of 369 rows fail `TOT_M + TOT_F = TOT_P`.
A constant chosen because it makes a total look right is curve-fitting, not
provenance.

**Citing a source did not unlock a value.** Feasibility now names and links its
governing instruments — and still returns FAR as `UNAVAILABLE`, because their
clauses have not been transcribed. A test and an e2e check both assert that
naming the instrument did not cause a number to appear.

Open: R1, R6, R10, R11.

Endpoints for unbuilt phases are **absent, not stubbed**. An endpoint returning
plausible placeholder values is the exact failure this project is designed
against.

---

## Data collection policy

Enforced in code by `etl/http/client.py`, which is the only sanctioned way this
project makes an outbound request:

1. `robots.txt` is obeyed. There is no override flag.
2. OTP-, captcha- and login-gated government portals are refused outright.
3. Rate limits apply per host (2 s for `.gov.in` / `.nic.in`), with an
   identifying User-Agent carrying a real contact address.
4. TLS chain exceptions are per-host, logged, and recorded in the provenance
   row. A global `verify=False` does not exist.
5. No personal data is collected from any portal. Owner details enter the system
   only from documents a user uploads about their own property.

---

## Licence and attribution

Third-party data carries its own terms — OpenStreetMap under ODbL requires
attribution and share-alike. Attribution strings live in
`meta.data_sources.attribution` and are rendered in the map layer catalogue.

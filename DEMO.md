# Demo & presentation guide
**SRM University — BTech AIML project demonstration**

## Start it (three terminals, ~20 seconds)

Terminal 1 — API:
```bash
cd backend && PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

Terminal 2 — web:
```bash
cd frontend && python -m http.server 3000
```

Open **http://localhost:3000**. No database, no Docker, no internet needed.

> **Check the map once before you present.** Everything was verified through the
> API and the DOM, but the sandbox used to build this had no WebGL, so the
> polygons drawing on screen is unconfirmed. If the map is blank the right-hand
> panel still works — and the panel is the substance. Text fallback:
> `cd backend && PYTHONPATH=. .venv/Scripts/python.exe scripts/smoke_demo.py`

---

## What is real

| Claim | Evidence |
|---|---|
| 369 GBA wards, 5 corporations | Official GBA delimitation KML; ingest **fails** if count ≠ 369 |
| 200 GCC wards, 15 zones | Official GCC 2022 ward + zone KML; ward→zone by spatial join |
| 13,921 Bengaluru OSM features | Overpass, 22 categories |
| 12,038 + 7,109 property records | Two separate public datasets, never pooled |
| 219 passing tests | `cd backend && pytest` |
| 4,151 survey parcels, 3 taluks, 7 hoblis | Digitised Bengaluru Urban revenue map sheets |
| Every metric on screen | Read from `ml/artifacts/<city>/metrics.json`, written by an actual run |

Nothing is mock data.

---

## The 10-minute demo

### 1. Open the app — **GREATER BENGALURU** is selected by default
Point at the city switcher: two cities, separate data, separate models.

### 2. Search "Jayanagar" (no map click needed)
Jurisdiction tab: corporation, ward number, ward name in **English and Kannada**,
zone, revenue division, ARO sub-division, assembly constituency — each GREEN with
a **View source** link showing dataset, tier, licence, retrieval date.

Then search **"Marathahalli"** — inside the digitised revenue sheets — and four
more rows fill in: district **Bengaluru Urban**, taluk **Bangalore East**, hobli
**Varthur**, village **Marathhalli**, all GREEN. Survey number **36** appears
AMBER, marked `INDICATIVE`.

> "The survey number is amber on purpose. It is read from a digitised revenue
> sheet, not from a survey — it is not a determination of boundary or title."

Now search **Jayanagar**, which sits outside the published sheets. District and
taluk still resolve — **Bengaluru Urban / Bengaluru South** — but in AMBER, from
the administrative boundary layer. Hobli, village and survey number go grey.

> **The line to say:** "Two layers, two different questions. Taluk is a boundary
> question, so a polygon answers it for 100% of localities in both cities — 24
> taluks here, 29 in Chennai. Survey number is a cadastral question, and revenue
> sheets cover 7% of Bengaluru and none of Chennai. A polygon cannot produce a
> survey number, so when I widened taluk coverage to the whole city I made sure
> it didn't widen what I claim about a parcel. There's a test that fails if it
> ever does."

Switch to **Chennai** and search any locality: district **Chennai**, taluk
**Guindy** / **Mylapore** / **Ambattur** — real taluks, where before there was
nothing at all.

Scroll to **"Requested — no data source"**: planning authority and ward
population remain grey with a specific reason.

> "The system could guess planning authority from the locality name, or hand
> back the nearest survey number. It refuses to do either."

Scroll to **Road access (Module 8)**: nearest mapped road 38.3 m away,
hierarchy `MA`, **existing width 12 m**, **proposed width 24 m**.

> **The line to say:** "This one file nearly cost me the whole feasibility
> engine. It's called a road width map, and it has two width columns. The
> proposed width is bigger on every single one of 23,324 segments — median 18 m
> against 9 m. FAR is a function of road width, so if I'd just taken 'the' width
> I'd have doubled the buildable area for the entire city and nothing on screen
> would have looked wrong. So neither field is called `road_width`, and the
> proposed one is excluded from feasibility by name."

### 2b. **Documents tab** — the answer to "you can't fetch Khata, so what do you do?"

Click **Load a sample**, then **Check document**. It's a Khata certificate whose
ward number (111) deliberately disagrees with this location (ward 44).

The result: taluk, hobli, village and survey number all **CONSISTENT** against
the revenue layer — and ward number **INCONSISTENT**, flagged in red.

> **The three lines to say:** "Nothing I paste here is stored — it's parsed in
> memory and discarded. The document has an owner name and a mobile number; the
> app detects that personal data is present and never echoes it back — search
> the response, they aren't in it. And four fields matching does *not* make this
> verified. Khata is not title. The app says so on screen and links to the
> Sub-Registrar, because that's who can actually answer it."

Then upload a `.jpg`: it **refuses**, saying no OCR engine is installed.

> "It would have been easy to return plausible fields for an image nobody read.
> Refusing is the same rule the whole project runs on."

### 2c. Market estimate — guidance value & transaction price

Type **Chrompet** into the Locality box (Chennai) and press Estimate.

**Transaction price: ₹9,771/sq.ft** — *"Chrompet: median of 1,702 recorded
sales, 2006–2015"*, with the historical caveat attached. Switch to Bengaluru and
it refuses: Karnataka doesn't publish transactions, and the dataset holds
*asking* prices.

**Guidance value** starts as "Data unavailable" — and explains why, and how to
get it. Fill in the form below it (locality, value, your name) and press Record;
the row fills in as **MANUAL ENTRY**, attributed, INDICATIVE, 55% confidence.

> **The line to say:** "Kaveri and TNREGINET have no public API and their terms
> don't permit scraping, so the platform never fetches guidance value. It links
> to the portal and stores what a person looked up, with their name on it — and
> it is never labelled VERIFIED, because the platform didn't retrieve it. That's
> the difference between a system that has a value and a system that can defend
> where the value came from."

### 2d. Chennai in Tamil

Switch to **Chennai** and open the ward search. Options now read
`Ward 1 - Ennore — வார்டு 1 - எண்ணூர் — Greater Chennai Corporation`. Type
**எண்ணூர்** and it finds the ward.

Select it: **Ward (local) வார்டு 1 - எண்ணூர்**, corporation
**பெருநகர சென்னை மாநகராட்சி**.

Then scroll to **Ward 4 — CMWSSB Division 4**, which shows no Tamil name.

> **The line to say:** "129 of 200 wards have a Tamil name. The other 71 are
> blank because OpenStreetMap has no Tamil name for those localities — and a
> transliteration would be a machine-invented spelling, not a Tamil name.
> There's a test that fails if anyone ever fills those in automatically. The
> corporation's own Tamil name is the one exception, because GCC publishes it."

### 3. Nearby & connectivity
Nearest metro, government offices, hospitals, schools, banks — with connectivity,
healthcare, education and daily-life scores.

> "Government offices carry a warning that **nearest is not jurisdictional** —
> the closest sub-registrar office is often not the one with jurisdiction."

### 4. **ML Performance — spend the most time here**

**Dataset & split:** 12,038 records · train 8,426 / calibration 1,806 / test 1,806 ·
**22 features, 11 of them GIS-derived** · 858 spatial blocks.

**Model comparison** — 6 algorithms, two CV schemes side by side:

| Algorithm | spatial R² | random R² | leakage |
|---|---|---|---|
| gradient_boosting | **0.4231** | 0.5116 | +0.0885 |
| hist_gradient_boosting ★ | 0.4132 | 0.5473 | +0.1341 |
| xgboost | 0.4121 | 0.5381 | +0.1260 |
| random_forest | 0.4022 | 0.5346 | +0.1324 |
| linear_regression | 0.2959 | 0.3406 | +0.0447 |
| baseline (median) | −0.0653 | −0.0623 | — |

> **The line to say:** "Random k-fold puts a property and its neighbour on
> opposite sides of the split, so the model memorises a locality's price level.
> I grouped folds by the real GBA wards instead. Every model drops. The gap is
> the part of the accuracy that was leakage — and I selected the model on the
> lower, honest number."

**Then the GIS point:** "Before GIS features, spatial-CV R² was **0.3078**. After
adding distance-to-metro, hospital, school, government office and amenity density,
it's **0.4231**. And `amenity_count_1km` is now the strongest single correlate
with price at r = 0.43. That's the map work earning its place in the model."

**Tuning:** RandomizedSearchCV, 12 candidates, GroupKFold by spatial block.

**Final test:** MAE ₹1,357 · RMSE ₹2,169 · R² 0.5247 · MAPE 23.5% ·
90% conformal interval ±₹2,643 with **89.0% measured coverage**.

**SHAP:** area_type, bath, amenity_count_1km, sqft, area_per_room, metro_distance_m.

**EDA:** distribution, correlation heatmap, price-by-locality, duplicates,
outliers, skew — all generated plots, not screenshots.

### 5. Investment Score
Predicted price (ML) · overpricing verdict (ML) · demand (**DATA-DRIVEN SCORE**) ·
risk (**DATA-DRIVEN SCORE**) · Investment Score (**COMPOSITE**) · 5 similar
properties (**ML — k-nearest neighbours**).

> "Demand and risk are labelled DATA-DRIVEN SCORE, not ML, because neither
> dataset has an observed demand or risk label. Training a classifier on a label
> you cannot observe isn't machine learning. The weights are shown on screen so
> you can argue with them."

### 6. BUILDER MODE
Land cost, construction, other costs, marketing, finance → total cost, revenue,
net profit, ROI, break-even, best/base/worst scenarios.
**Selling price comes from the trained ML model.**

### 7. Development feasibility
FAR, height, floors, setbacks — all **UNAVAILABLE** with reasons.

> "The operative instrument is RMP-2015, because RMP-2031's provisional approval
> was withdrawn in 2020. The 2025/2026 amendments I found are in secondary
> sources, not the gazette, so those rules are marked UNVERIFIED and the engine
> refuses to fire them. A wrong FAR is somebody's money."

### 8. Switch to **CHENNAI**
Title becomes Chennai / சென்னை, mark becomes GCC, 200 wards load.
Search a ward → GCC ward, zone (Kodambakkam, Adyar, …).

### 9. Chennai ML Performance — **the best teaching moment in the project**

7,109 recorded **sale** prices (not asking prices), with `DATE_SALE` and
`DATE_BUILD` → real `property_age_years` (median 23 years).

| | random R² | spatial R² | gap |
|---|---|---|---|
| hist_gradient_boosting | 0.9962 | 0.3809 | **+0.6153** |
| random_forest | 0.9715 | **−0.2470** | +1.2185 |

Test R² reads **0.9969**, MAPE **1.19%** — and the app shows a red warning
telling you not to quote it.

> **Say this:** "This is where I'd have fooled myself. Test R² is 0.997. But the
> Chennai dataset covers only **7 localities**, so there are only 7 spatial
> blocks. Hold out a whole locality and random forest scores **minus 0.25** —
> worse than predicting the mean. The honest number is 0.38, and the app refuses
> to let me quote the 0.997."

### 10. Compare Cities
Bengaluru median ₹5,226/sq.ft vs Chennai ₹7,924/sq.ft — with a red caveat that
the two targets measure **different things** (asking vs recorded sale, different
periods) and are not directly comparable.

### 11. **More ML** — three model families beyond regression

This tab is the answer to "is this just one regression model?"

**Classification** — price band from the same features. Bengaluru: accuracy
**0.5175**, macro F1 **0.5159**, ROC-AUC **0.7045**, against a stated chance
line of 0.333. The confusion matrix is on screen, so the errors are visible:
Budget↔Mid-market confusion is where it loses most.

Switch to **Chennai** and the same pipeline prints a red block:

> "DEGENERATE MODEL — the classifier never predicts Mid-market. It has
> collapsed toward a single class, so its accuracy of 0.366 is not evidence
> that it works. With only 7 spatial groups… This result should be reported as
> a failure to generalise, not as a model."

> **The line to say:** "Its accuracy is 0.366, above the 0.333 chance line. A
> project trying to look good would print that number. The guard catches that
> recall for Mid-market is exactly zero and refuses to call it a model."

**Clustering** — KMeans on locality features, k chosen by silhouette (0.5543 at
k = 3), 413 Bengaluru localities. Cluster 1 is 77 localities at ~₹10,000/sq.ft
— Jayanagar, Koramangala, Indiranagar. Nothing labelled them as premium; the
features did. On Chennai it **refuses to run**: 7 localities is too few.

**Anomaly** — Isolation Forest, 602 of 12,038 records flagged. The caveat is
part of the result: contamination is set at 5% by assumption, so ~5% will be
flagged whatever the data looks like, and an anomaly is not evidence of
anything wrong.

**Guidance value** — not fetched, and the tab explains why: Kaveri is
portal-only, no public API, terms don't permit automated retrieval. It links to
the portal and stores what you look up by hand, labelled **MANUAL ENTRY**.

**Transaction prices** — "Not available" for Bengaluru (Karnataka doesn't
publish them; the dataset holds *asking* prices). Switch to Chennai and there
are real ones: Chrompet ₹9,771/sq.ft from **1,702 recorded sales**, 2006–2015,
with the historical caveat attached.

**Revenue coverage** — 3 taluks, 7 hoblis, 35 villages, 4,151 parcels, marked
partial.

---

---

## Where the machine learning is — answer this in one click

Open the **Glossary** tab. It lists all 14 features and marks each one:

| Badge | Meaning | Count |
|---|---|---|
| **ML** | Trained model | 5 |
| **GIS** | Geometric computation | 3 |
| **SCORE** | Weighted formula, *not* ML | 3 |
| **COMPOSITE** | ML + formula | 1 |
| **RULE** | Deterministic arithmetic | 2 |

Green dots on the nav bar mark the four tabs whose output comes from a trained
model: Market estimate, ML Models, ML Performance, Investment Score.

> "Five features use a trained model. The rest are geometry, formulas or rules,
> and the app labels them that way rather than calling everything AI."

The Glossary also explains **31 terms** — MAE, RMSE, R², MAPE, spatial-block CV,
leakage, conformal intervals, SHAP, one-hot encoding, imputation, lakh/crore,
sq.ft↔sq.m — each with what it means, how to read it, and a caution.

---

## Models trained, and the three prediction strategies

**ML Models tab.** Five algorithms are trained and saved *per city*:
linear regression, random forest, gradient boosting, HistGradientBoosting,
XGBoost. They are ranked by spatial-block CV, and the tab shows which strategy
uses which model.

| Strategy | Models | What it adds |
|---|---|---|
| **Single** | 1 — best on spatial CV | Fastest; SHAP maps to one model |
| **Dual** | 2 best, averaged | Reports model disagreement |
| **Multi** | all 5, averaged | Variance reduction |

All three run on the same input and are shown side by side.

**Bengaluru** — single ₹5,034 · dual ₹4,906 · multi ₹5,117 · disagreement **42.0%**
**Chennai** — single ₹9,911 · dual ₹8,393 · multi ₹7,317 · disagreement **51.9%**

> **The line to say:** "Chennai's models disagree by 52%. Linear regression says
> ₹9,911, random forest says ₹6,114 — on the same property. And linear
> regression ranks *first* on spatial CV there, because with only 7 localities
> the tree models overfit. Disagreement is a second uncertainty signal that a
> single model cannot give you."

---

## Languages

Bengaluru shows **Kannada**, Chennai shows **Tamil** — the toggle follows the
city, because Kannada in Chennai would be meaningless. Chennai's 200 wards are
numbered in the official source, so each is given a place name derived from the
nearest OpenStreetMap locality and labelled as derived.

---

## If BUILDER MODE shows a loss

That is a real result, not a bug, and the tab now explains it. It names the
cause — usually the land price being too high relative to the achievable selling
price — and states exactly what would be needed to break even: the required
selling price, or the land cost that would work. Defaults were also corrected;
the earlier land figure was inconsistent with the model's own price level.


---

## Urban Planning tab (Module 21) — ward-level analytics

369 Bengaluru wards scored on infrastructure access, with the map shadeable by
five metrics (choropleth). Everything here is labelled **DATA-DRIVEN SCORE**.

**Highest development pressure — market activity running ahead of provision:**

| Ward | Listings | Infra |
|---|---|---|
| Whitefield (East 38) | 515 | 85 |
| Kasavanahalli (South 31) | 202 | 78 |
| Thanisandra (North 19) | 239 | 82 |
| Uttarahalli (South 49) | 191 | — |
| RR Nagara (West 23) | 226 | — |

> "Those are Bengaluru's actual growth corridors, and the platform found them
> from listing volume against infrastructure — not from a list I typed in."

**Least-served wards:** Hagaduru, Anjanapura, Gunjur, Andrahalli, Abbigere —
the outer, newer areas. Average infrastructure across the city is 90.6/100.

**A bug worth mentioning if asked about data quality.** The first run showed ward
38 three times with identical figures. Bengaluru's ward numbers restart inside
each corporation, so keying on the number alone silently merged five different
wards. Fixed by keying on `corporation|ward_no` throughout — analytics, API and
map expression. Market coverage went from 86 wards to 206 once the collision was
removed.

The tab also carries a **coverage guard**: if fewer than 75% of facility
categories were retrieved for a city, every score is flagged as understated
rather than published as evidence of poor provision.


---

## The question you will definitely be asked

> *"You listed 40 modules. How many did you actually build?"*

Run this in front of them:

```bash
cd backend && PYTHONPATH=. python scripts/module_check.py
```

It probes the live app for all 40 and prints: **27 BUILT, 10 PARTIAL,
3 NOT BUILDABLE, 0 NOT BUILT.**

> **Say this:** "Nothing specified and buildable is missing. Sixteen are partial
> and three aren't buildable at all — and that's the finding, not the excuse.
> The spec assumed I could fetch Khata records, tax status and planning-authority
> boundaries. No public API exists for any of them, for anyone. So those modules
> return UNAVAILABLE with a specific reason and a link to the office that can
> answer it. Every verdict on that screen comes from a live probe, so it can't
> drift from the code."

---

## Verify everything before you present

```bash
cd backend && PYTHONPATH=. python scripts/e2e_check.py
```

Exercises all 39 endpoints (40 operations) in both cities — jurisdiction, map layers, nearby,
valuation, all three prediction strategies, ML dashboard, future price,
planning, buyer, investor, builder, feasibility, insights, PDF generation, the
extra models, guidance value, transaction price and revenue coverage.
Expect **97/97**. It needs no running server.

It also asserts the behaviours that matter, not just HTTP 200:

- the buyer verdict still carries its records caveat
- the feasibility engine still refuses to publish a FAR
- the planning choropleth still keys on `corporation|ward_no`
- Chennai's future-price forecast is supported and Bengaluru's is refused
- a degenerate classifier carries a warning, and a non-degenerate one does not
- a guidance value written back reads as `MANUAL ENTRY`, never `VERIFIED`
- Bengaluru still refuses transaction prices, and Chennai still declares its vintage
- a point outside the revenue sheets returns `UNAVAILABLE`, not a nearest match
- no road endpoint returns a field called `road_width`, and the feasibility
  offer is the *existing* width with the proposed one explicitly excluded


## Questions you will get

**"Why is Bengaluru's R² only 0.42?"**
Because it's the spatial-block score. The same model reports 0.55 under random
k-fold and I can show you exactly how much of that is leakage. The model also has
no per-property coordinates — location resolves only to locality level, so two
flats on the same street get identical GIS features. A higher number would mean I
was fooling myself.

**"Chennai's R² is 0.997 — is that real?"**
No, and the app says so. It's a random split over a dataset covering 7 localities.
The spatial-block figure of 0.38 is the honest one. That contrast is the most
useful result in the project.

**"Where's the data from? Is the licence clear?"**
Ward boundaries: official GBA and GCC data via OpenCity — clear. Amenities:
OpenStreetMap under ODbL — clear, attributed. Property datasets: public GitHub
mirrors, licence **unconfirmed** — flagged as the weakest link, capped at 0.45
confidence in code, and used for methodology, not valuation.

**"Why no flood risk?"**
No authoritative stormwater-drain or rajakaluve geometry is public. Proximity to
water is not a flood determination. Telling someone their plot floods without
that data is the highest-liability error this platform could make, so the risk
module lists flood under `excluded`.

**"Is demand a model?"**
No — and that's deliberate. It's a weighted index with the weights on screen.
Neither dataset has an observed demand label, so nothing can be trained or
validated. Calling it ML would be the easiest thing for you to catch.

---

## Don't claim

- ❌ "99.7% accurate" — that's Chennai's leaked random-split score
- ❌ that demand or risk are ML models
- ❌ that it verifies Khata, title or building approvals
- ❌ ward populations (the source field is ~6× the known total; unresolved)
- ✅ "Two cities, two separately-trained models, six algorithms compared under
  spatial-block cross-validation, with GIS-derived features and SHAP" — all true
  and all on screen

---

## Reproduce everything

```bash
python etl/flows/ingest_gba_wards.py
python etl/flows/ingest_chennai_wards.py
python etl/flows/ingest_osm_amenities.py bengaluru
python etl/flows/ingest_locality_gazetteer.py bengaluru
python ml/pipelines/train_city_model.py bengaluru
python ml/pipelines/train_city_model.py chennai
```

Deterministic at `random_state=42`.

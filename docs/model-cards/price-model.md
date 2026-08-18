# Model card — Bengaluru asking-price model

**Model id:** `price-psf-hgb-v0.1`
**Trained:** 2026-08-09 · **Status:** research prototype, not for decisions

---

## 1. What it predicts

**Asking price per square foot, in rupees.** Not a valuation. Not a transaction
price. Not a guidance value.

Karnataka does not publish registered transaction prices (data-source audit,
finding 6), so no model trained on public data can predict one. Asking prices sit
systematically above transaction prices by an amount this project has not been
able to quantify.

## 2. Data

| | |
|---|---|
| Source | Public "Bengaluru House Data" CSV, mirrored on GitHub |
| URL | https://raw.githubusercontent.com/dphi-official/Datasets/master/Bengaluru_House_Data.csv |
| Tier | **T4** — commercial/listing, provenance unconfirmed |
| Rows | 13,320 raw → 12,038 after cleaning |
| Vintage | **Estimated 2016–2018.** Not stated in the file. Treat as historical |
| Licence | **Unconfirmed.** Used here for methodological demonstration only |

> **This is the weakest link in the project and should be replaced.** Audit task
> R6 (find a licensed or clearly-licensed listing source) remains open. Until it
> closes, no output from this model should inform a real decision.

### Cleaning (every filter logged in `ml/artifacts/metrics.json`)

| Filter | Rows removed |
|---|---|
| Missing sqft / rooms / price / location | 17 |
| Under 300 sq.ft per room (implausible) | 748 |
| Outside ₹1,500–40,000 / sq.ft | 48 |
| Beyond 2 SD of the locality mean | 469 |

Ranges in `total_sqft` ("1195 - 1440") are averaged; non-sq.ft units (Sq. Meter,
Perch, Acres, Cents, Guntha, Grounds) are converted.

### GBA integration

**40.1%** of listing localities were fuzzy-matched to one of the 369 official GBA
ward names. This is **derived (T5)** — a locality name matching a ward name is
evidence of location, not proof. It is used to form cross-validation blocks and
as a coarse corporation-level feature. It is never shown to a user as the ward a
property sits in.

## 3. Features

`sqft`, `rooms`, `bath`, `balcony`, `ready_to_move`, `area_type`,
`gba_corporation`.

**Not included and materially missing:** coordinates, metro/rail distance, road
width, floor, building age, amenities, plot frontage. Location is represented
only at corporation level — five categories for a city of 14 million. This is the
main reason performance is modest, and it is honest to say so.

## 4. Validation — the point of the exercise

Random k-fold cross-validation on geographic data leaks neighbouring properties
between folds. Spatial-block CV (`GroupKFold` over 1,146 ward/locality blocks)
does not.

### Shipped model — locality excluded, must generalise to unseen areas

| Model | Random-CV R² | **Spatial-CV R²** | Leakage gap | Spatial MAE |
|---|---|---|---|---|
| Median baseline | −0.062 | −0.062 | +0.000 | ₹1,893 |
| Linear regression | 0.248 | 0.199 | +0.048 | ₹1,827 |
| Random forest | 0.398 | 0.287 | +0.111 | ₹1,704 |
| **HistGradientBoosting** | 0.403 | **0.308** | +0.095 | **₹1,675** |

### Locality one-hot included — the usual setup in published projects

| Model | Random-CV R² | Spatial-CV R² | **Leakage gap** |
|---|---|---|---|
| Linear regression | 0.359 | 0.222 | +0.137 |
| Random forest | 0.456 | 0.223 | **+0.233** |
| HistGradientBoosting | **0.473** | 0.248 | **+0.225** |

> **48% of the headline R² was leakage.** A project reporting 0.47 from random
> k-fold with locality features is reporting 0.25 of real generalisation and 0.22
> of neighbours appearing on both sides of the split.

**Model selection was done on the spatial-block score.** Selecting on random CV
would have picked a different, worse model.

## 5. Prediction intervals

Split conformal prediction, α = 0.10. Distribution-free — no Gaussian error
assumption.

- Half-width: **±₹3,364 / sq.ft**
- Empirical coverage on the held-out test split: **90.0%** (target 90%)

The interval is wide — often ±60% of the point estimate. That is the correct
representation of this model's uncertainty, and it is why the API returns a band
and the UI never shows a bare number.

## 6. Explainability

Permutation importance on the spatially-honest test split (not impurity
importance, which is biased toward high-cardinality features):

| Feature | Importance |
|---|---|
| sqft | 0.331 |
| bath | 0.238 |
| area_type | 0.177 |
| gba_corporation | 0.116 |
| rooms | 0.097 |
| balcony | 0.037 |
| ready_to_move | 0.029 |

Per-prediction SHAP attribution is Phase 9b.

## 7. Confidence ceiling

Model confidence in the API is capped at **0.45** regardless of validation score,
and scaled down further by interval width. Typical output lands near **0.08**.

That is deliberate. A T4 source of uncertain vintage cannot support a confident
number, however well the model validates against itself.

## 8. Known failure modes

- Overestimates for properties in low-price areas; corporation-level location is
  too coarse.
- No extrapolation guard yet for inputs outside the training distribution.
- 2016–2018 vintage means absolute levels are stale; Bengaluru guidance values
  alone rose 6–15% in February 2026.
- Sparse localities survive cleaning (the 2-SD filter is skipped below 5 rows).
- Asking-price bias is acknowledged but unquantified.

## 9. Do not

- Present any output as a valuation, a fair price, or a negotiating position.
- Report the random-CV R² as the model's accuracy.
- Use it without showing the interval.
- Compare its output to guidance value — guidance value is not in the system,
  because Kaveri has no public API.

## 10. Reproduce

```bash
cd "GBA development project" && backend/.venv/Scripts/python.exe ml/pipelines/train_price_model.py
```

Deterministic at `random_state=42`. Writes `ml/artifacts/price_model.joblib` and
`ml/artifacts/metrics.json`.

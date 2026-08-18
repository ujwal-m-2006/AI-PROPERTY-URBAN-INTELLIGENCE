# Google Colab

Everything needed to run the project's data and ML in a notebook, without
cloning the repo or installing anything.

## Open it

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ujwal-m-2006/AI-PROPERTY-URBAN-INTELLIGENCE/blob/main/colab/GBA_Property_Intelligence.ipynb)

Or: Colab → *File → Open notebook → GitHub* → paste
`ujwal-m-2006/AI-PROPERTY-URBAN-INTELLIGENCE`.

Then *Runtime → Run all*. A few minutes on a free CPU instance. No GPU, no Drive
mount, nothing to install — the notebook reads its CSVs from this repository over
HTTPS and the two property datasets from their original public sources.

## What is here

| File | What it is |
|---|---|
| `GBA_Property_Intelligence.ipynb` | The notebook — 27 cells |
| `data/` | 17 CSVs, 49,676 rows |
| `build_notebook.py` | Generates the notebook |
| `verify_notebook.py` | Executes every cell locally |
| `verified_output.txt` | Transcript of that local run |

The notebook is **generated, not hand-written**, so the code inside it can be
syntax-checked and executed before anyone opens Colab. `verified_output.txt` is
the proof it ran — a notebook nobody has executed will fail in front of an
examiner on a cell nobody checked.

To regenerate after changing a cell:

```bash
python colab/build_notebook.py && python colab/verify_notebook.py
```

## The CSVs

Produced by `scripts/export_csv.py` from `data/processed/`.

| File | Rows | Notes |
|---|---|---|
| `gba_wards.csv` | 369 | `_raw_tot_p` is **not** usable as population — see below |
| `gba_corporations.csv` | 5 | Derived by dissolving wards |
| `chennai_wards.csv` | 200 | Place names DERIVED from OSM, 129 with Tamil |
| `chennai_zones.csv` | 16 | |
| `admin_taluks_bengaluru.csv` | 24 | T3, INDICATIVE, no per-boundary vintage |
| `admin_taluks_chennai.csv` | 30 | As above |
| `revenue_parcels.csv` | 4,151 | Partial coverage: 3 taluks, 7 hoblis |
| `road_network_bengaluru.csv` | 23,324 | **Two** width columns — see below |
| `flood_locations_bengaluru.csv` | 391 | Reported locations, **not** a hazard model |
| `localities_bengaluru.csv` | 1,885 | OSM, ODbL |
| `localities_chennai.csv` | 781 | OSM, ODbL |
| `amenities_bengaluru.csv` | 13,921 | OSM, ODbL |
| `amenities_chennai.csv` | 3,987 | OSM, ODbL |
| `ward_analytics_bengaluru.csv` | 369 | Weighted formulas, **not** ML |
| `ward_analytics_chennai.csv` | 200 | As above |
| `model_comparison.csv` | 12 | Every algorithm under both CV schemes |
| `_sources.csv` | 11 | Tier, licence, retrieval date, caveats |

### Two things that will mislead you if you skip the header

Every CSV's first line is a `#` comment carrying its caveat. The loader in the
notebook keeps that line rather than discarding it, because two of these tables
are actively dangerous read at face value:

**`road_network_bengaluru.csv` has two width columns.** `width_proposed_m`
exceeds `width_existing_m` on **100%** of 23,324 segments, median 18 m against
9 m. It is a road-*widening* proposal inside a file called a road width map.
FAR, height and setback are functions of road width — use the proposed figure
and you double the buildable area for the whole city with nothing looking wrong.

**`gba_wards._raw_tot_p` is not a population.** It sums to ~84 million against a
real Greater Bengaluru figure of ~14 million. Dividing by 6 reproduces the
officially reported per-corporation averages almost exactly, including East's
distinctly lower value — but the mechanism is unexplained and 125 of 369 rows
fail `male + female = total`. The platform publishes no ward population, and
neither should a notebook.

### Geometry

Polygons and lines do not fit in a CSV cell, so each row carries
`centroid_lng`, `centroid_lat` and `vertex_count` instead. **A centroid is not a
boundary.** Join on it and you have a point inside or near the shape, not the
shape. Use the GeoJSON in `data/processed/` for real spatial work.

### Not exported

* `guidance_values.json` — local runtime state, and it holds a person's name.
* The `source_*.json` sidecars — folded into `_sources.csv` instead.
* The two property datasets — fetched by the notebook from their original public
  sources. This project does not redistribute them.

## What the notebook shows

Sections 1–6 load and describe the layers. Then:

* **§7 — random k-fold leaks.** Every model scores higher under random CV than
  when folds are grouped by locality. The gap is leakage, and model selection
  uses the lower number.
* **§8 — Chennai, where this would fool anyone.** 7 localities means 7 spatial
  blocks. Random split reports near-perfect accuracy; hold out a locality and
  R² goes negative — worse than predicting the mean.
* **§9 — the results reported as failures.** Kept in the comparison table rather
  than dropped, because a comparison that hides its failures is not one.
* **§11 — what the notebook deliberately does not do**, and why each omission is
  a data-availability fact rather than a gap in the work.

Two of the numbers in there are bad. They are the interesting ones.

# Datasets

Every dataset this project uses, where it came from, what it powers, and what it
cannot be trusted to say.

## Start here

| File | What it is |
|---|---|
| **[CATALOGUE.md](CATALOGUE.md)** | The full catalogue — 13 datasets in use, plus 10 that exist and could not be used |
| `catalogue.csv` | Same, one row per dataset, for a spreadsheet |
| `catalogue.json` | Same, for code |
| `build_catalogue.py` | Regenerates all three |

The catalogue is **generated, not hand-maintained**. Every ingest flow writes a
`source_*.json` sidecar beside its output recording what it actually downloaded,
and the generator reads those. Re-ingest a layer from a different URL and the
catalogue changes on the next run without anyone remembering to edit it.

```bash
python datasets/build_catalogue.py
```

## Where the actual data lives

Nothing is duplicated into this folder — one copy, one source of truth.

| Location | Contents | In git? |
|---|---|---|
| `data/raw/` | Original downloads exactly as fetched (212 MB) | No — reproducible |
| `data/processed/` | Cleaned GeoJSON/JSON the app reads | **Yes** |
| `data/processed/source_*.json` | Provenance sidecar per layer | **Yes** |
| `colab/data/` | The same layers flattened to 17 CSVs | **Yes** |

To rebuild `data/raw/` from scratch:

```bash
python scripts/bootstrap.py
```

## The 13 datasets, by category

**Administrative boundaries (4)** — GBA 369 wards, GCC 200 wards, and district/
taluk polygons for both cities. Everything else keys off these.

**Cadastral records (1)** — 4,151 digitised revenue parcels giving hobli, village
and survey number. Covers 7% of Bengaluru localities; the rest returns
UNAVAILABLE.

**Infrastructure (1)** — 23,324 BBMP road segments with width. Read the caveat
before using it.

**Environmental (1)** — 391 reported flooding locations. Proximity only, never a
risk score.

**Points of interest (4)** — OpenStreetMap amenities and locality gazetteers for
both cities. These supply 11 of the model's GIS features.

**Property market (2)** — the ML training data, from Kaggle via GitHub mirrors.
T4: public datasets, not government registers.

## Three caveats that will mislead you if skipped

These are in the catalogue against their datasets, repeated here because each one
is a mistake waiting to happen.

**The road width file has two width columns.** `width_proposed_m` exceeds
`width_existing_m` on **100%** of 23,324 segments — median 18 m against 9 m. It
is a road-*widening* proposal inside a file called a road width map. FAR, height
and setback are all functions of road width, so using the proposed figure doubles
the buildable area for the entire city with nothing on screen looking wrong.

**The ward population field is not a population.** `_raw_tot_p` sums to ~84
million against a real Greater Bengaluru figure of ~14 million. Dividing by 6
reproduces the officially reported per-corporation averages almost exactly,
including East's distinctly lower value — but the mechanism is unexplained and
125 of 369 rows fail `male + female = total`. No ward population is published
anywhere in this project.

**Bengaluru prices are asking prices; Chennai's are recorded sales.** Different
things, different periods, never pooled, and not comparable at row level. Every
price the Bengaluru model predicts inherits a systematic upward bias of unknown
size.

## Licence status

Eleven layers carry a stated licence — public domain, CC0 or ODbL. Two do not:
both Kaggle property datasets are recorded `licence_status: UNVERIFIED`, because
Kaggle's dataset pages are JavaScript-rendered and could not be read
programmatically. **No licence was guessed.** Confirm on the dataset page before
any redistribution or commercial use.

Related: the Kaggle upstream is recorded alongside the GitHub mirror that was
actually fetched. Chennai's upstream is marked **INFERRED** — the mirror's
columns match the named dataset but the mirror cites no source, so it is the
likely origin rather than an established one.

## Why the mirrors instead of the Kaggle API

The Kaggle API needs a `kaggle.json` token. This project will not handle a user's
credentials, and requiring one would break *Run all* in the Colab notebook. The
trade is weaker provenance for zero credential handling, and it is recorded in
each sidecar under `why_not_kaggle_api` rather than left unexplained.

## The more important half

[CATALOGUE.md](CATALOGUE.md) ends with **10 datasets that exist and could not be
used** — e-Khata, property tax, encumbrance certificates, guidance value, survey
number boundaries, zoning polygons, planning-authority boundaries, transaction
prices, ward population, and the BBMP GIS viewer.

That table is the project's central finding. It is why several modules return
UNAVAILABLE with a reason instead of a number, and why the answer to "why didn't
you just integrate the government data" is that no one can.

Full reasoning: [docs/01-data-source-audit.md](../docs/01-data-source-audit.md).

## Collection policy

Enforced in code by `etl/http/client.py`, the only sanctioned outbound request
path in the project:

- `robots.txt` respected, no exceptions
- seven OTP-gated government portals hard-blocked at the client, so no future
  code path can hit them by accident
- descriptive User-Agent on every request
- rate limits respected; Nominatim capped at 1 request/second
- no personal data collected, and nothing fetched from a source whose terms
  forbid automated access

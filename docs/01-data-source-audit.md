# Phase 0 — Greater Bengaluru Data-Source Audit
**Bengaluru AI Property & Urban Intelligence Platform**

Audit date: **2026-08-09**
Auditor: architecture pass, desk research against public web sources
Audit revisited: **2026-08-12** — the Phase 0.5 research tasks were worked through against primary sources. See §7.
Status: **DRAFT — every row marked `UNVERIFIED` must be confirmed against the primary source before any code depends on it.** Six of eleven research tasks are now closed; the rest are recorded with what was actually found, including the two that could not be answered and why.

---

## 0. How to read this document

### 0.1 Availability classification (fixed vocabulary — used everywhere in the codebase)

| Code | Meaning |
|---|---|
| `API` | Available through an official, documented, public API |
| `DOWNLOAD` | Available as official downloadable bulk data (shapefile/KML/CSV/PDF) |
| `PORTAL` | Available through an official web portal, but **no public API**; typically per-record lookup, often OTP/captcha gated |
| `PARTIAL` | Available for some of Greater Bengaluru, some attributes, or some time periods only |
| `UPLOAD` | Only obtainable if the *user* supplies the document |
| `NONE` | Not publicly available |
| `UNKNOWN` | Requires verification — **do not build on this row yet** |

### 0.2 Provenance tier (drives the confidence score in Module 23)

| Tier | Definition | Max confidence allowed |
|---|---|---|
| **T1 — Official primary** | Government portal / gazette / official dataset, retrieved directly | 0.95 |
| **T2 — Official secondary** | Government document republished by a third party (e.g. OpenCity mirror of a GBA notification) | 0.85 |
| **T3 — Community/open** | OpenStreetMap, community GTFS, civic-tech datasets | 0.70 |
| **T4 — Commercial/listing** | Property portals, aggregators, listing scrapes | 0.55 |
| **T5 — Derived** | Anything this platform computes (georeferencing, geocoding, interpolation, ML) | Bounded by weakest input |

**Hard rule:** a derived value can never carry higher confidence than its weakest input. This is enforced in code, not by convention.

### 0.3 Verification status of this audit itself

Two Karnataka government domains (`gba.karnataka.gov.in`, `bbmp.gov.in/gisviewer`) could **not** be fetched during this audit — TLS chain error (`unable to verify the first certificate`). This is itself a finding (see §6.1). Rows depending on those hosts are marked `UNVERIFIED` and carry a research task in Phase 0.5.

---

## 1. Executive findings — read this before anything else

### Finding 1 — The administrative layer is solved. Build on it immediately.
The Greater Bengaluru Authority came into existence **15 May 2025** under the Greater Bengaluru Governance Act, 2024, replacing BBMP as a single corporation. Five city corporations (North, South, East, West, Central) subdivided into **369 wards**, final delimitation notified **19 November 2025**.

Critically: the **final 369-ward boundaries are downloadable as KML**, with population and a ward → division → sub-division mapping CSV, via the OpenCity urban data portal, sourced from GBA, licensed public domain.
→ *Modules 1, 3 (jurisdiction part), 21 and 22 are unblocked today.*

### Finding 2 — There is no public API for any property-level government record. None.
e-Aasthi/e-Khata, property tax (SAS), building permission, occupancy certificates, encumbrance certificates and RTCs are all **per-property, OTP or consent gated portal lookups**. There is no bulk feed, no query API, and automated retrieval would be both technically hostile and legally questionable.

**Architectural consequence — this is the single most important decision in the project:**
> Modules 2, 3, 7 and 27 must be built as **document-upload + verification + official-deep-link** modules, *not* as data-integration modules.

The platform's honest posture is: *"we cannot fetch your Khata; upload it and we will check it for internal consistency and against everything we do know, and here is the exact official link and the exact office to go to."* That is genuinely valuable and it is achievable. Pretending otherwise produces a demo that fabricates government records.

### Finding 3 — The statutory zoning baseline is RMP-2015, not RMP-2031.
The Revised Master Plan 2031's provisional approval was **withdrawn** (2020) and it has not, as far as this audit could establish, been notified since. The operative zoning instrument therefore remains the **Zoning Regulations of RMP-2015**, as amended — including a Premium FAR chapter added (reported Feb 2025) and setback/parking amendments (reported Feb 2026).

`UNVERIFIED` — the Feb 2026 amendment was found only via a law-firm commentary, not the Karnataka Gazette. **The rules engine must not encode it until the gazette notification is obtained.**

Also `UNKNOWN`: whether GBA has issued or will issue new building bye-laws superseding the BBMP-era position. This is a live risk to Module 6 and must be re-checked at implementation time.

### Finding 4 — Zoning *geometry* is raster/PDF, not GIS.
The master plan land-use maps exist as planning-district PDF map sheets. There is no published machine-readable land-use polygon layer. Georeferencing and digitising them yields **T5 derived data** — useful, never authoritative.
→ Module 5 must display land use as *indicative*, always AMBER, always with "verify with the planning authority" and a link to the source map sheet. It must never be fed into a statement of what may legally be built without that caveat travelling with it.

### Finding 5 — Road width is the accuracy bottleneck of the entire feasibility engine.
FAR, height and setbacks in the Bengaluru zoning regulations are functions of road width. But:
- `rh.bbmpgov.in` (Road History v2.0) is a **portal**, not an API, and reporting indicates key fields have been withheld from publication.
- The available road-width dataset covers **major roads only**.
- OSM road width tagging in Bengaluru is sparse.

→ Design decision: road width is a **user-declared input with a mandatory source flag** (`measured` / `official_document` / `dataset` / `estimated`), and feasibility output confidence is bounded by that flag. A feasibility result derived from an estimated road width must be visibly weaker than one derived from a sanctioned plan.

**Update after ingest (Module 8 built).** The BBMP road width map has now been ingested: 23,324 centreline segments, 2,240 km. It confirmed this finding and added a sharper hazard than the one anticipated above.

Every segment carries **two** width fields:

| Source field | min | median | max | Read as |
|---|---|---|---|---|
| `RR_width_B` | 6 m | **9 m** | 50 m | existing carriageway width |
| `RR_WIDTH_P` | 12 m | **18 m** | 100 m | proposed / planned width |

`RR_WIDTH_P` exceeds `RR_width_B` on **100% of segments** and its median is double. That is the "road widening / proposed roads" row of §2.4 arriving inside a file whose title is simply *road width*. Feeding it into the rules engine would roughly double the floor area reported as permissible, city-wide, with no visible symptom.

So the ingest keeps both fields under their **source names**, derives no field called `road_width`, and marks `RR_WIDTH_P` as excluded from feasibility. The road layer may only *offer* `RR_width_B` as a candidate carrying the `dataset` flag — the second-weakest of the four. The design decision above is unchanged; the layer feeds it, it does not bypass it.

Two further limits, both measured rather than asserted:

* **It is not the complete street network.** Only **37%** of gazetteer localities have a mapped segment within 150 m (11% within 50 m). It is a width map for the roads BBMP tracks. A residential lane having no segment nearby is the dataset, not a lookup failure — and is never reported as "no road access".
* **No road names are published**, so a segment cannot be identified as a named road.

### Finding 6 — Transaction prices are not public. Your ML trains on asking prices.
Karnataka does not publish transaction-level registration data. Encumbrance certificates are per-property via Kaveri. The only broad price signals available are (a) **guidance values** — government-notified, portal-only, a legal floor rather than a market price, and (b) **listing prices** — commercial, T4, and systematically above transaction price.

→ Module 13's three-way separation (listing / transaction / estimated fair value) is correct and must be enforced at the schema level. The transaction column will be largely empty. Say so, in the UI and in the report. A price model trained on asking prices has a known upward bias — quantify it if you can, disclose it always.

### Finding 7 — Transport, amenity and government-office data comes from OSM, and that's fine.
No official BMTC GTFS exists; the widely used feed is community-built from the Namma BMTC app and is unreliable for timings. OSM + Overpass covers bus stops, metro, rail, hospitals, schools, banks, police, offices with good Bengaluru coverage.
→ Modules 9, 10, 11 are buildable now at T3 confidence. ODbL attribution and share-alike obligations apply.

---

## 2. Master data-source audit

Difficulty: **E**asy / **M**edium / **H**ard / **X** = blocked or legally constrained.

### 2.1 Administrative & jurisdiction

| Feature | Source | Official? | Class | Access method | Update freq | Coverage | License / restrictions | Diff |
|---|---|---|---|---|---|---|---|---|
| GBA 369 final ward boundaries | OpenCity CKAN, sourced from GBA | T2 (GBA original) | `DOWNLOAD` | KML download | On delimitation | Full GBA | Public domain (as stated by portal) | E |
| Ward population (final, Dec 2025) | OpenCity CKAN | T2 | `DOWNLOAD` | KML w/ attributes | Per delimitation | Full GBA | Public domain | E |
| Ward → division → sub-division map | OpenCity CKAN | T2 | `DOWNLOAD` | CSV + PDF | Per delimitation | Full GBA | Public domain | E |
| Per-corporation final ward notifications | OpenCity CKAN | T2 | `DOWNLOAD` | 5 × PDF | Per delimitation | Full GBA | Public domain | E |
| Ward renaming notifications (Dec 2025) | OpenCity CKAN | T2 | `DOWNLOAD` | 5 × PDF | Ad hoc | Full GBA | Public domain | M (parse) |
| 5 corporation boundaries | Derived: dissolve wards by corporation | T5 | `DOWNLOAD`→derived | GIS dissolve | — | Full GBA | — | E |
| GBA outer boundary | Derived: dissolve corporations | T5 | derived | GIS dissolve | — | Full GBA | — | E |
| GBA GIS Viewer layers | `bbmp.gov.in/gisviewer` | T1 | `UNKNOWN` | Viewer; underlying service endpoints unconfirmed | ? | ? | ? | `UNVERIFIED` |
| "Know Your Ward" lookup | GBA portal | T1 | `PORTAL` | Address/geo lookup, UI only | — | Full GBA | Cross-check only | — |
| District / taluk / hobli / village | Karnataka revenue GIS (KSRSAC) | T1 | `UNKNOWN` | Not confirmed public | — | State | — | `UNVERIFIED` |
| District / taluk / hobli / village / survey no. **(resolved — see R10)** | Bengaluru Urban revenue maps, OpenCity CKAN | T2 (digitised revenue sheets) | `DOWNLOAD` | 92 × KML, one per hobli sheet | Not stated | **Partial** — 3 taluks, 7 hoblis, 35 villages, 4,151 parcels | As published by portal | E |
| Assembly/parliamentary constituency | ECI / KSRSAC | T1 | `PARTIAL` | Some layers in GIS viewer | Per delimitation | State | — | M |

> **Note on BBMP→GBA transition:** the old 198/243-ward BBMP layers are still widely circulated and are now **historical**. Keep them in the DB only as a `historical_boundaries` table for time-series continuity of old datasets. Never use them for present-day jurisdiction answers.

### 2.2 Property records — the constrained zone

| Feature | Source | Official? | Class | Access method | Coverage | Legal/access concern | Diff |
|---|---|---|---|---|---|---|---|
| e-Khata / e-Aasthi record | e-Aasthi (Revenue Dept / ULB) | T1 | `PORTAL` + `UPLOAD` | SAS ID + mobile OTP; owner-consent | ~13 lakh Bengaluru properties (reported) | Personal data; OTP-gated. **Do not automate.** | X |
| ePID ↔ PID ↔ SAS ID linkage | e-Aasthi | T1 | `UPLOAD` | Read from user's own e-Khata | — | Same | X |
| A-Khata / B-Khata classification | e-Aasthi | T1 | `UPLOAD` | From document | — | Same | X |
| Property tax / SAS status | GBA property tax portal | T1 | `PORTAL` | Per-property lookup | GBA | Personal data | X |
| Property GPS coords in e-Khata | e-Aasthi | T1 | `UPLOAD` | From document | Partial | Same | M |
| Survey number boundaries | Dishaank (KSRSAC) | T1 | `PORTAL` | Mobile/web GIS app; no public API | State | **Boundaries are notional**, GPS error 3–10 m (worse under canopy); not legally valid for disputes | X |
| RTC / Pahani | Bhoomi | T1 | `PORTAL` | Per-record | State (rural/agri) | Personal data | X |
| Encumbrance Certificate | Kaveri 2.0 | T1 | `PORTAL` | Per-property, account required | State | Personal data | X |
| Guidance value | Kaveri / Dept of Stamps & Registration | T1 | `PORTAL` | Location lookup, no API | State | Scraping likely against ToS | H |
| Registered transaction prices | — | — | `NONE` | Not published | — | — | X |

**Design rule for this whole block:** the platform stores what the *user* uploads, tied to the user's own session, encrypted, with an audit log — and otherwise emits a deep link to the official portal plus the jurisdictionally correct office to visit. Nothing here is ever auto-populated.

### 2.3 Planning, zoning & development control

| Feature | Source | Official? | Class | Notes | Diff |
|---|---|---|---|---|---|
| Zoning Regulations RMP-2015 (text) | India Code / BDA | T1 | `DOWNLOAD` | PDF. **This is the operative rule set.** Hand-encode into the rules engine with clause citations | H |
| Premium FAR chapter (added after Ch.10) | Karnataka Gazette | T1 | `UNVERIFIED` | Reported Feb 2025. Obtain gazette copy before encoding | H |
| Setback & parking amendment | Karnataka Gazette | T1 | `UNVERIFIED` | Reported Feb 2026 via law-firm commentary only. **Do not encode yet** | H |
| RMP-2031 volumes (incl. Vol-6 Zoning) | BDA / OpenCity mirror | T2 | `DOWNLOAD` | **Draft/withdrawn — reference only.** Never use as the operative rule | M |
| RMP land-use map sheets | BDA planning districts | T1/T2 | `DOWNLOAD` (raster/PDF) | Requires georeferencing → T5 derived | X |
| Machine-readable land-use polygons | — | — | `NONE` | Must be digitised in-house; label derived | X |
| Planning authority jurisdiction boundaries (GBA / BDA / BMRDA) | Respective authorities | T1 | `UNKNOWN` | No confirmed public GIS layer. Until confirmed, Module 4 answers **"requires verification"** for anything outside corporation limits | `UNVERIFIED` |
| Building plan approval (Nambike Nakshe) | GBA/BBMP | T1 | `PORTAL` | Applicant-side workflow; ≤4,000 sq ft trust-based auto-approval reported. No public register API | X |
| Sanctioned plan / CC / OC register | GBA/BBMP | T1 | `NONE` / `UPLOAD` | No public searchable register found | X |
| RERA project register | K-RERA | T1 | `PORTAL` | Searchable by project/promoter/district; certificate download. **Project-level, not parcel-level** | M |

### 2.4 Infrastructure, transport & amenities

| Feature | Source | Official? | Class | Notes | Diff |
|---|---|---|---|---|---|
| **Amenities/transport/offices (ingested)** | OSM Overpass | T3 | `API` | **In use.** ~20 categories over the GBA bbox. Note: `overpass-api.de` returns **406** for this client; community mirrors (`kumi.systems`, `private.coffee`) accept it | E |
| Road network + geometry | OpenStreetMap | T3 | `API` | Overpass API / Geofabrik extracts | E |
| Road width (major roads) **(ingested — Module 8)** | OpenCity road width map, from BBMP | T2 | `DOWNLOAD` | 23,324 segments, 2,240 km. **Two width fields — existing and proposed. See Finding 5.** 37% of localities within 150 m | E |
| Road History (per-road register) | `rh.bbmpgov.in` | T1 | `PORTAL` | v2.0; ~13,000 km mapped (reported). Key fields reportedly withheld | H |
| Road widening / proposed roads | RMP map sheets | T1 | `PARTIAL` | Raster only → derived. **Never assert widening impact without the source sheet** | X |
| Metro stations & alignments | OSM (+ BMRCL published maps) | T3 | `API` | Under-construction phases need manual curation | E |
| Metro proposed/under-construction | BMRCL | T1 | `PARTIAL` | Published as maps/PDF, not GIS | M |
| Bus stops & routes | Community GTFS (`Vonter/bmtc-gtfs`) + OSM | T3 | `DOWNLOAD` | **No official BMTC GTFS exists.** Timetables unreliable — use stop *locations*, not timings | M |
| Railway / suburban stations | OSM | T3 | `API` | — | E |
| Airport | OSM | T3 | `API` | — | E |
| Hospitals, PHCs, clinics, pharmacies | OSM | T3 | `API` | Completeness varies; government/private split needs tag cleaning | M |
| Schools, colleges | OSM | T3 | `API` | Same | M |
| Police, fire stations | OSM | T3 | `API` | — | E |
| Government offices (SRO, RTO, tahsildar, ward office…) | OSM + official directory pages | T3/T1 | `PARTIAL` | Locations from OSM; **jurisdiction mapping must come from official notifications**, not proximity | H |
| BESCOM / BWSSB service divisions | BESCOM / BWSSB | T1 | `UNKNOWN` | Division boundaries not confirmed public | `UNVERIFIED` |
| Parks, lakes | OSM + BBMP lake lists | T3/T2 | `DOWNLOAD` | — | E |

> **Critical distinction for Module 10:** *nearest* office ≠ *jurisdictionally correct* office. The platform must answer with the office that has jurisdiction (derived from ward/sub-division/SRO mapping) and may show the nearest as a separate, clearly-labelled fact. Conflating the two produces confidently wrong advice.

### 2.5 Environment & risk

| Feature | Source | Official? | Class | Notes | Diff |
|---|---|---|---|---|---|
| Stormwater drains + buffer lines | GBA GIS portal | T1 | `UNKNOWN` | Reported visible in the viewer; extractability unconfirmed | `UNVERIFIED` |
| Rajakaluve classification (primary/secondary/tertiary) & buffers | RMP-2015 + NGT directions | T1 | `PARTIAL` | Rule text obtainable; **authoritative geometry is the constraint** | H |
| Flood-prone / vulnerable locations | KSNDMC / GBA | T1 | `UNKNOWN` | Early-warning system operational since 2021; public dataset access unconfirmed | `UNVERIFIED` |
| Terrain / elevation | SRTM 30 m, or Bhuvan CartoDEM | T1/T3 | `DOWNLOAD` | Derive low-lying/sink analysis. **Derived flood proxy ≠ official flood risk** | M |
| Lakes & catchments | OSM + BBMP lake list | T3/T2 | `PARTIAL` | — | M |
| Air quality | CPCB / KSPCB stations | T1 | `PARTIAL` | Sparse station network; interpolation is derived | M |
| Groundwater | CGWB | T1 | `DOWNLOAD` | Coarse (taluk-level) | M |

**Non-negotiable UI rule for Module 12:** three visually distinct badges — `OFFICIAL RISK DATA`, `GIS PROXIMITY (COMPUTED)`, `ML ESTIMATE`. A terrain-derived low-lying flag is *not* a flood-risk declaration, and must never be rendered as one. Telling a user a specific plot floods, or is on a rajakaluve, without authoritative geometry is the highest-liability failure mode in this entire platform.

### 2.6 Market data

| Feature | Source | Class | Notes |
|---|---|---|---|
| **Listing dataset (in use)** | Public "Bengaluru House Data" CSV, GitHub mirror | `DOWNLOAD` / T4 | **Currently used to train the price model.** ~13.3k rows, est. 2016–2018 vintage, **licence unconfirmed**. Adequate for methodology, not for valuation. Replacing it is task **R6** |
| Guidance value | Kaveri | `PORTAL` | Best official price anchor. Location-keyed. Portal-only → periodic manual reference table with recorded retrieval date, or user input |
| Listing prices | Commercial portals | `PARTIAL` / T4 | **Check robots.txt and ToS before any collection.** Prefer licensed/API/academic datasets. Asking price ≠ transaction price |
| Historical price index | Public research / RBI HPI (Bengaluru) | T1/T3 | `DOWNLOAD` | City-level only — too coarse for locality prediction, useful for trend anchoring |
| Rental data | Commercial portals | T4 | `PARTIAL` | Same ToS constraints |
| Project/builder data | K-RERA | T1 | `PORTAL` | Project-level supply signal |

---

## 3. Complete feature availability matrix (Modules 1–40)

| # | Module / feature | Avail? | Official src | Public API | Download | Portal only | Manual/upload | Alt source | Coverage | Accuracy concern | Legal concern | Priority |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Corporation / zone / ward / division | ✅ | ✅ GBA | ✗ | ✅ KML | — | — | — | Full | Low | None | **P0** |
| 1 | District/taluk/hobli/village | ⚠ | ✅ | ✗ | ? | ✅ | — | KSRSAC | State | Med | None | P2 |
| 2 | PID / ePID / Khata no. | ⚠ | ✅ | ✗ | ✗ | ✅ | ✅ | — | Per-property | — | **Personal data** | P1 |
| 2 | Survey number geometry | ⚠ | ✅ Dishaank | ✗ | ✗ | ✅ | — | — | State | **High — notional** | Terms | P2 |
| 3 | e-Khata / tax status | ⚠ | ✅ | ✗ | ✗ | ✅ | ✅ | — | Per-property | — | **OTP/consent** | P1 |
| 4 | Planning authority | ⚠ | ✅ | ✗ | ? | ? | — | — | Unconfirmed | Med | None | **P0** |
| 5 | Land use / zoning polygons | ⚠ | ✅ raster | ✗ | ✅ PDF | — | — | — | Full (raster) | **High — derived** | None | P1 |
| 6 | FAR / setback / height rules | ✅ | ✅ RMP-2015 | ✗ | ✅ PDF | — | — | — | Full | Med — amendments | None | **P0** |
| 6 | Road width input | ⚠ | ✅ partial | ✗ | ✅ partial | ✅ | ✅ | OSM | Major roads | **High** | None | **P0** |
| 7 | Sanctioned plan / OC / CC | ✗ | ✅ | ✗ | ✗ | ✗ | ✅ | — | — | — | Personal data | P2 |
| 8 | Road network / classification | ✅ | ✗ | ✅ OSM | ✅ | — | — | OSM | Full | Med | ODbL | P1 |
| 8 | Road widening risk | ⚠ | ✅ raster | ✗ | ✅ PDF | — | — | — | Partial | **High** | None | P3 |
| 9 | Metro / rail / bus / airport | ✅ | ✗ | ✅ OSM | ✅ GTFS* | — | — | OSM | Full | Med | ODbL | P1 |
| 10 | Government office locations | ✅ | ⚠ | ✅ OSM | ✅ | — | — | OSM | Good | Med | ODbL | P1 |
| 10 | Office **jurisdiction** mapping | ⚠ | ✅ | ✗ | ⚠ | ✅ | — | — | Partial | **High** | None | P2 |
| 11 | Amenities (health/edu/daily) | ✅ | ✗ | ✅ OSM | ✅ | — | — | OSM | Good | Med | ODbL | P1 |
| 12 | Flood / SWD / rajakaluve | ⚠ | ✅ | ✗ | ? | ✅ | — | DEM (derived) | Unconfirmed | **Very high** | **Liability** | P2 |
| 13 | Listing prices | ⚠ | ✗ | ⚠ | ⚠ | — | — | Licensed data | Partial | **High bias** | **ToS** | P1 |
| 13 | Guidance value | ⚠ | ✅ | ✗ | ✗ | ✅ | ✅ | — | Full | Low (is a floor) | ToS | P1 |
| 13 | Transaction prices | ✗ | — | ✗ | ✗ | ✗ | ✅ (EC) | — | None | — | Personal data | P3 |
| 14 | Price prediction | ✅ derived | — | — | — | — | — | — | — | Bounded by input | Disclose | P1 |
| 15 | Future price | ⚠ derived | — | — | — | — | — | — | — | **Low — thin history** | Disclose | P2 |
| 16 | Demand | ⚠ derived | — | — | — | — | — | — | — | **No ground truth label** | Disclose | P3 |
| 17–18 | Builder ROI / what-can-I-build | ✅ computed | — | — | — | — | ✅ inputs | — | — | Assumption-driven | Disclaimer | P1 |
| 19–20 | Buyer / investor modes | ✅ computed | — | — | — | — | — | — | — | Composite | Disclaimer | P2 |
| 21 | Government dashboard | ✅ aggregate | — | — | — | — | — | — | Ward-level | Aggregation bias | "Not official" | P2 |
| 27 | Document OCR | ✅ | — | — | — | — | ✅ | — | — | OCR error | **Consent + storage** | P2 |

\* GTFS is community-built, not official.

---

## 4. What this means for scope — the honest version

Scoring the 40 modules against actual data availability:

| Bucket | Modules | Verdict |
|---|---|---|
| **Fully buildable, high confidence** | 1, 8 (partial), 9, 10 (location), 11, 22, 23, 24, 25, 26, 29–35, 38, 39 | Green light |
| **Buildable as *calculators* with declared assumptions** | 6, 17, 18, 19, 20, 21 | Green light *if* assumptions are surfaced |
| **Buildable only as upload + verify + deep-link** | 2, 3, 7, 27 | Redefine before building |
| **Buildable but heavily caveated / derived** | 4, 5, 12, 13, 14, 15, 16 | Ship with prominent uncertainty |
| **Not buildable as specified** | Auto-fetch of any government property record; transaction-price history; authoritative parcel geometry | Say so in the report |

This is not a reduction in ambition. A platform that correctly answers *"here is your jurisdiction, here is what the regulations permit on this plot under these stated assumptions, here is what's around you, here is what the market suggests, here is exactly which of these facts is verified and which you must go and confirm — and here is the office to confirm it at"* is a stronger and more defensible project than one that pretends to hold government records it cannot legally obtain.

The differentiator is **calibrated honesty**. Modules 23, 24 and 38 are the actual product.

---

## 5. Open research tasks (Phase 0.5 — before Phase 2 coding)

| # | Question | Why it blocks | Owner |
|---|---|---|---|
| R1 | **STILL OPEN (§7).** Does `bbmp.gov.in/gisviewer` sit on ArcGIS REST / GeoServer with reachable endpoints? | Would unlock SWD, buffers, land use as vectors — would change several rows above from `UNKNOWN` to `API` | You |
| R2 | **CLOSED (§7)** — UDD 235 MNJ 2025 dated 05.01.2026 obtained. Karnataka Gazette notification for the zoning amendment | Rules engine correctness | You |
| R3 | **CLOSED (§7) — yes, five, one per corporation, effective 14.05.2026.** Whether GBA has issued building bye-laws superseding BBMP's | Rules engine validity | You |
| R4 | **CLOSED (§7)** — still not notified; RMP-2015 as amended 05.01.2026 is operative. RMP-2031 legal status | Determines operative zoning | You |
| R5 | **CLOSED (§7) — no. PDF maps only.** Planning-authority boundary layer (GBA / BDA / BMRDA) | Module 4 cannot be geographic without it | You |
| R6 | Licensed/ethical source for listing prices (academic dataset, licensed API, or partnership) | Modules 13–15 | You |
| R7 | **CLOSED (§7) — ingested 2026-08-15.** 391 reported locations from 3 BBMP layers, served as proximity only; flood stays excluded from the risk score. KSNDMC / GBA flood-vulnerability dataset access | Module 12 official tier | You |
| R8 | **CLOSED (§7)** — Other (Public Domain), Open Definition. OpenCity licence terms for the GBA KML | Redistribution rights | You |
| R9 | **PARTLY CLOSED (§7)** — ~6x inflation characterised, mechanism unexplained, field stays suppressed. What does `TOT_P` measure? | It sums to ~84 M across 369 wards against a Greater Bengaluru figure of ~14 M. No population is published until this is resolved | You |
| R11 | Is there a published data dictionary for the BBMP road width map — confirming `RR_width_B` as existing and `RR_WIDTH_P` as proposed, and expanding the hierarchy codes MA/MI/PU/OR/IR/CR/PR? | The proposed/existing reading is an inference from field naming and from `RR_WIDTH_P` exceeding `RR_width_B` on 100% of segments. It is strong, but it is not a fact, and feasibility depends on it | You |
| R10 | **Partly answered.** What is the vintage of the Bengaluru Urban revenue map sheets, and which taluks are absent from the published set? | The sheets carry no per-file date, and coverage is 3 of the district's taluks. Taluk/hobli/village/survey number now resolve *inside* that footprint and return `UNAVAILABLE` outside it — but the layer cannot be described as current until the vintage is confirmed | You |

**Do not begin Phase 2 until R1, R5 and R8 are answered.** R2–R4 block Phase 7.

> **Status as of 2026-08-12.** R5 and R8 are closed; R8 clears cleanly and R5 closes as a negative finding that confirms the platform's existing refusal. R1 could not be answered — the host is still unreachable — so the rows that depend on it stay `UNKNOWN`. R2, R3 and R4 are closed, which means Phase 7 is unblocked *as to its sources*; the clauses themselves remain unencoded and the rules engine still does not fire. See §7.

### 5.1 What R10 changed

Five fields that this audit originally listed as `UNKNOWN` — district, taluk,
hobli, village and survey number — are now answered from a `DOWNLOAD` source
for part of Bengaluru Urban. Two limits travel with every one of them:

* **Coverage is partial and is reported as partial.** A point outside the
  published sheets returns `UNAVAILABLE` naming the taluks actually held. The
  nearest parcel is never substituted, because a neighbouring survey number is
  a different property.
* **A survey number here is `INDICATIVE`, never `VERIFIED`.** These are
  digitised revenue sheets, not a survey. Section 2.2 still applies: boundary,
  extent and title are settled by the Sub-Registrar and a licensed surveyor,
  and Dishaank's own boundaries remain notional.

Guidance value (row 2.2) and transaction price stay where the audit put them.
Neither is fetched. Guidance value is stored only when a person looks it up on
Kaveri or TNREGINET themselves, and is labelled `MANUAL ENTRY` with attribution
— never `VERIFIED`, because the platform did not retrieve it. Transaction
prices remain `NONE` for Bengaluru; the one place the project holds real
recorded sale prices is the Chennai dataset, whose period ends in 2015 and is
labelled historical wherever it appears.

---

## 6. Practical ingestion notes

### 6.1 TLS
Multiple Karnataka government hosts presented incomplete certificate chains during this audit. Any ingestion client must handle this explicitly — with a **pinned, logged, per-host exception**, never a global `verify=False`. Log every such request in `data_sources.access_notes`.

### 6.2 Ethical collection policy (binding on this project)
1. `robots.txt` is respected. No exceptions.
2. No automated interaction with any OTP-, captcha- or login-gated government portal. Ever.
3. No personal data collected from any portal. Owner names entering the system come only from documents the user uploads about their own property.
4. Rate limits: ≥ 1 req/sec to any government host, off-peak, identifying User-Agent with contact address.
5. Every fetch writes a provenance row before the payload is used.
6. Commercial listing sources require ToS review and are quarantined until cleared.

### 6.3 Data freshness
| Layer | Re-check |
|---|---|
| Ward/corporation boundaries | Quarterly + on any delimitation news |
| Zoning regulations & amendments | Quarterly (gazette watch) |
| Guidance value | On notification (was revised Feb 2026; further revision reported proposed — `UNVERIFIED`) |
| OSM extract | Weekly |
| Listings | Per licence terms |

---

## 7. Sources consulted

- Greater Bengaluru Authority — https://www.gba.karnataka.gov.in/ *(fetch blocked: TLS)*
- GBA GIS Viewer — https://bbmp.gov.in/gisviewer/ *(fetch blocked: TLS)*
- OpenCity — GBA Wards Delimitation 2025 — https://data.opencity.in/dataset/gba-wards-delimitation-2025
- OpenCity — BBMP Road History — https://data.opencity.in/dataset/bbmp-road-history
- OpenCity — Bengaluru Road Width Map — https://data.opencity.in/dataset/bengaluru-road-width-map
- OpenCity — Bengaluru Revised Master Plan 2031 — https://data.opencity.in/dataset/bengaluru-revised-master-plan-2031
- India Code — Zoning Regulations RMP-2015 — https://www.indiacode.nic.in/ViewFileUploaded?path=AC_KA_71_402_00001_11_1552283484255%2Frulesindividualfile%2F&file=zoning_regulations_rmp2015f.pdf
- BBMP Road History portal — https://rh.bbmpgov.in/
- Karnataka RERA — https://rera.karnataka.gov.in
- Kaveri 2.0 — https://kaveri.karnataka.gov.in
- Dishaank (KSRSAC) — https://play.google.com/store/apps/details?id=com.ksrsac.sslr
- Community BMTC GTFS — https://github.com/Vonter/bmtc-gtfs
- Wikipedia — Greater Bengaluru Authority — https://en.wikipedia.org/wiki/Greater_Bengaluru_Authority
- Deccan Herald — five corporations / 369 wards reporting — https://www.deccanherald.com/india/karnataka/bengaluru/greater-bengaluru-areas-five-corporations-to-have-369-wards-3803924
- The South First — 369 wards approval — https://thesouthfirst.com/karnataka/karnataka-approves-369-wards-under-gba-raising-hopes-for-long-delayed-civic-polls/

*Secondary/commentary sources were used only to locate primary documents and are not cited as authority.*

---

## 7. Phase 0.5 — resolution of the research tasks

Worked through on **2026-08-12**. Each task below records what was found, from
where, and what it changes. Two could not be answered; they say so.

### Summary

| # | Question | Outcome |
|---|---|---|
| R1 | BBMP GIS viewer — ArcGIS REST / GeoServer? | **NOT ANSWERED** — host unreachable, same TLS fault as the original audit |
| R2 | Gazette notification for the zoning amendment | **CLOSED** — obtained |
| R3 | Has GBA issued building bye-laws? | **CLOSED — yes, and they are per-corporation** |
| R4 | RMP-2031 legal status | **CLOSED** — still not notified; RMP-2015 remains operative |
| R5 | Planning-authority boundary GIS layer | **CLOSED — no such layer is published** |
| R6 | Licensed source for listing prices | **OPEN** — not researched in this pass |
| R7 | Flood-vulnerability dataset | **PARTLY CLOSED** — a BBMP dataset exists, but it is points |
| R8 | OpenCity licence terms for the GBA KML | **CLOSED** — public domain, redistribution permitted |
| R9 | What does `TOT_P` measure? | **PARTLY CLOSED** — inflation characterised, mechanism still unexplained |
| R10 | Revenue sheet vintage | **OPEN** — unchanged |
| R11 | Road width data dictionary | **OPEN** — unchanged |

### R1 — BBMP GIS viewer: NOT ANSWERED

`bbmp.gov.in` could not be reached, by two independent clients, with the **same
fault the original audit recorded on 2026-08-09**: `unable to verify the first
certificate`. Probed `/robots.txt`, `/gisviewer`, `/arcgis/rest/services`,
`/geoserver/web/` and `gba.karnataka.gov.in` — all failed at TLS, before any
HTTP request was made.

This was **not** worked around. The project's own collection policy (§6.1)
permits a pinned, logged, per-host exception, but disabling certificate
verification in order to probe a government host for undocumented service
endpoints is not something an academic prototype should do unprompted.

→ R1 stays open and now requires **manual verification in a browser**. Its
status is unchanged since Phase 0, and the rows depending on it remain
`UNKNOWN`. The TLS finding in §6.1 is confirmed as persistent, not transient.

### R2 — Zoning amendment notification: CLOSED

The final notification exists and has been located:

* **Zonal Regulations to RMP-2015**, notification reference **UDD 235 MNJ 2025**,
  dated **05.01.2026** (draft published November 2025).
* Published by the Greater Bengaluru Authority, republished by the OpenCity
  portal as `udd-235-mnj-2025e-05.01.2026.pdf`, licence Other (Public Domain).

The audit previously said: *"the Feb 2026 amendment was found only via a
law-firm commentary, not the Karnataka Gazette. The rules engine must not encode
it until the gazette notification is obtained."* The document is now obtained.

**This does not by itself unblock the rules engine.** It is a T2 republication,
and the numbers inside it still have to be read, encoded and tested clause by
clause. What changes is that Module 6 can now *cite and link* its governing
instrument instead of reporting that none was available.

### R3 — GBA building bye-laws: CLOSED, and the answer changes a design

**Yes.** GBA has issued building bye-laws, and they are **not city-wide**. There
are five separate instruments — one per city corporation:

> Bengaluru Central / East / North / South / West City Corporation Building
> (Amendment) Bye-laws 2026, effective **14 May 2026**, alongside five 2026
> drafts.

This is a structural finding, not a detail. The rules engine was scoped for one
Bengaluru rule set. It needs to key on **corporation** — which Module 1 already
resolves as a `VERIFIED` fact, so the input exists. Any FAR, height or setback
answer must state which corporation's bye-laws it applied.

### R4 — RMP-2031: CLOSED, Finding 3 confirmed

RMP-2031 remains **not notified**. Provisional approval was granted in 2017 and
withdrawn by the Urban Development Department around 2020, and the Karnataka
High Court has directed the State not to approve it without the court's
permission. Reporting in 2026 describes Bengaluru as still operating on
RMP-2015, itself based on 2003-era surveys, against a statutory ten-year
revision cycle.

→ The operative zoning instrument is the **Zoning Regulations of RMP-2015 as
amended 05.01.2026** (R2). Finding 3 stands unchanged.

### R5 — Planning-authority boundaries: CLOSED, and the answer is no

BMRDA publishes its jurisdiction as **PDF maps and notifications only**. No
shapefile, KML or GeoJSON of local planning area boundaries is offered. Twelve
local planning authorities are listed (BDA, Anekal, BIAAPA, Hoskote, Kanakapura,
Magadi, Nelamangala, Ramanagara UDA, Channapatna, Doddabalapura, STRR Planning
Authority, and a Greater Bengaluru Development Authority).

→ **Module 4 cannot be made geographic for the region.** No machine-readable
geometry is published, so this row moves from `UNKNOWN` to a settled finding.

**Refinement (2026-08-12).** Reviewing this answer showed the refusal had been
applied more widely than the finding justifies. Two questions were being
declined together:

| Question | Answerable? |
|---|---|
| Which of the 12 regional planning authorities covers this point? | **No** — needs the boundary layer nobody publishes |
| Who grants planning permission *inside* GBA / GCC limits? | **Yes** — fixed by statute |

Inside a corporation the authority is not inferred from geography at all. The
Greater Bengaluru Governance Act, 2024 gives GBA the powers of the local
planning authority for its area; in Chennai, CMDA regulates the metropolitan
area under s. 49 of the Tamil Nadu Town and Country Planning Act, 1971, and has
delegated ordinary-building permission to the local body while retaining Special
Buildings, Group Developments and High Rise directly.

The platform already resolves corporation as a `VERIFIED` fact, so a point
either falls inside a corporation whose statutory position is cited or it does
not. `planning_authority` and a new `building_permission_authority` are now
answered inside limits, with the instrument cited, and **still refused outside
them** with the R5 reason. Naming an authority is explicitly not a permission.

### R7 — Flood vulnerability: PARTLY CLOSED

A BBMP dataset exists on the OpenCity portal — *Flooding Locations in Bengaluru
Urban*, licence Other (Public Domain), three KML resources: locations vulnerable
to flooding, flood-prone locations, and BBMP low-lying areas. Reporting
elsewhere describes KSNDMC having identified 174 flood-prone areas and running
100 automatic rain gauges across the city.

**But it is point data, not inundation geometry**, and no return period, depth
or methodology is attached. That is enough to say *"a known flooding location is
recorded N metres away"*. It is not enough to compute a flood risk score.

→ Module 12's existing exclusion — the risk score names flood as excluded in its
own response — stays. If this layer is ingested it must enter as a separate
`INDICATIVE` proximity fact, never as a component of a risk score, or the score
would imply a hazard model that does not exist.

### R8 — Licence: CLOSED

The GBA ward delimitation dataset is licensed **Other (Public Domain)**, licence
URL `http://opendefinition.org/okd/`, carrying the portal's *"This dataset
satisfies the Open Definition"* badge, source attributed to GBA.

→ Redistribution rights are confirmed. The attribution string the ingest already
writes is appropriate. **R8 was one of the three tasks flagged as blocking Phase
2, and it clears cleanly.**

### R9 — `TOT_P`: PARTLY CLOSED, and the field stays suppressed

The published field sums to **84,028,870** across 369 wards (median 225,690,
range 139,690–299,050) against a Greater Bengaluru population of roughly 14
million — the ~6× discrepancy that caused it to be withheld.

Reporting on the 2025 delimitation gives an average ward population of about
**40,000** for Central, West, North and South, and about **26,000** for East,
which covers only two assembly constituencies. Dividing the observed means by 6:

| Corporation | wards | mean `TOT_P` | ÷ 6 | published expectation |
|---|---|---|---|---|
| Central | 63 | 231,296 | **38,549** | ~40,000 |
| East | 50 | 171,089 | **28,515** | **~26,000** |
| North | 72 | 249,014 | **41,502** | ~40,000 |
| South | 72 | 226,084 | **37,681** | ~40,000 |
| West | 112 | 238,355 | **39,726** | ~40,000 |

Sum ÷ 6 = **14,004,812**. The relative structure survives as well: East comes
out distinctly lower than the other four, exactly as reported, and nothing here
was fitted to that figure.

Two hypotheses were tested and rejected. The field is **not** an
assembly-constituency population repeated across its wards — only 1 of 28
assemblies has a single shared value, with up to 27 distinct values inside one
assembly. And the field is **not internally consistent**: 125 of 369 rows have
`TOT_M + TOT_F ≠ TOT_P`.

→ **No population is published, and dividing by 6 was not implemented.** A
constant chosen because it makes a total match a figure from a news report is
curve-fitting, not provenance — and a third of the rows fail an internal
consistency check that has nothing to do with scale. R9 stays open with far
better evidence than it had: the *shape* of the error is now characterised, the
mechanism is not.

**Incidental validation.** The ingested ward counts per corporation — West 112,
North 72, South 72, Central 63, East 50 — match the officially reported final
distribution exactly, independently confirming the 369-ward ingest against a
figure it was never checked against.

### What this section changes in the code

Nothing in the same pass, deliberately. Six tasks closing does not license
encoding zoning numbers read from a PDF in the pass that located the PDF. The
changes these findings justify are:

1. Module 6 should cite and link **UDD 235 MNJ 2025 (05.01.2026)** as its
   governing instrument rather than reporting that no source was available (R2).
2. The rules engine must be scoped **per corporation**, not per city (R3).
3. `planning_authority` stays `UNAVAILABLE` — now on evidence, not caution (R5).
4. Flood locations may be ingested as an `INDICATIVE` proximity fact only, never
   as a risk-score component (R7).
5. Ward population stays suppressed (R9).

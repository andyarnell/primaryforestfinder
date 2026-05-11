# Datasets Used by Primary Forest Finder

Primary Forest Finder combines 14 global datasets to delineate candidate primary forest areas. This page summarises what's actively wired into the analysis (current code: `pff_4.js` v4.15.7-beta.1, QGIS plugin v0.16.0-beta.1).

For full citations + DOIs see [`datasets_global.md`](datasets_global.md). For the code-level audit see [`datasets_usage_table.md`](datasets_usage_table.md).

---

## Datasets driving outputs

### 🌳 Forest cover (the baseline)

| Dataset | Role | Resolution |
|---|---|---|
| **GLAD GLCLU v2** (default) | Tree-height ≥ 5 m → forest baseline | 30 m, 6 time steps 1990–2020 |
| **Hansen Global Forest Change v1.12** | Tree-cover-2000 + annual loss; alternative forest source | 30 m, annual updates |

You can pick either as the forest source. GLAD gives consistent multi-date height; Hansen gives precise annual loss detection.

### 🚜 Anthropogenic exclusions (what we subtract)

| Layer | Driven by |
|---|---|
| **Cropland** | GLAD Cropland (Potapov) 2000–2019 |
| **Cultivated grassland** | Global Pasture Watch v1 (class 1) |
| **Oil palm** | Descals Global Oil Palm YoP 1990–2021 |
| **Planted forest + tree crops** | SDPT v2 (class 1 + class 2) |
| **Built-up areas (small + large)** | JRC GHSL SMOD + POP P2023A, plus DLR WSF Evolution OR'd in |
| **Roads** | OSM Roads (PFF 33-region merge, May 2025) |

### 🏔️ Rescue exceptions (forest survives despite proximity)

| Tier | Dataset |
|---|---|
| Tier 1.2 — Steep slope rescue | **JAXA ALOS World 3D-30m v3.2** (DEM → slope) |
| Tier 1.3 — Long-protected areas | **WDPA** (IUCN Ia/Ib/II, ≥30 yr designation) |

### 🗺️ Admin + reference

| Dataset | Role |
|---|---|
| **FAO GAUL 2024 L0** | Country boundaries + clipping |
| **FLII 2019** (Forest Landscape Integrity Index) | Optional reference overlay |
| **FDaP Forest Persistence 2020** | Optional reference overlay |

---

## What's loaded but not driving outputs

12 datasets are loaded by the code but their results are currently not consumed (line commented out, function never called, or flag set to `false`). These are documented for transparency and as candidates for future workshop swaps.

| Dataset | Reason it's off |
|---|---|
| **GRIP4 Roads + AADT** | Computed but split-by-traffic lines commented (speed pass) — only OSM feeds road buffering |
| **GLC_FCS30D landcover** | Cropland extracted but `.or()` into cropland composite commented (speed pass) |
| **JRC TMF Deforestation Year** | `forest_disturbances()` defined but never called |
| **GISD30**, **GISA** | Impervious-surface dynamics — disabled by `includeGISD/A=false` (rock false positives) |
| **LandScan Global** | No caller in `pff_4.js` |
| **FDAP Palm / Rubber / Cocoa** (2024a) | Disabled — model commits primary forest as agriculture |
| **OSM Water Layer (canals)** | Computed; `addLayer` line commented |
| **WDB Navigable Rivers** | Painted to raster; never buffered |
| **Navigable Waterways USA** | Loaded; never buffered |

---

## What's only in commented references

10 datasets appear in the code as commented-out alternatives — zero runtime cost. Kept for workshop discussion + future swap-in:

- **Alternative built-up:** WSF 2015, WSF 2019 (single-year, superseded by WSF Evolution)
- **Alternative roads:** USA TIGER, WUR Congo Logging Roads, Microsoft Global Roads, Ghost Roads Asia/NG, MapBiomas Brazil Roads
- **Alternative reference layers:** WRI SBTN Natural Lands v1.1, European Primary Forests Database v2, Tsinghua China Terrace Map v1

---

## Summary

| Category | Count |
|---|---:|
| ✅ Actively used | 14 |
| 🟠 Loaded but unused | 12 |
| 🔵 Commented-out alternatives | 10 |
| **Total tracked** | **36** |

Canonical source: [`datasets_global.json`](datasets_global.json). Last verified against code: 2026-05-11.

---

## How to add a dataset

See [`.github/agents/add-dataset.agent.md`](../.github/agents/add-dataset.agent.md) for the standard pattern: add the loader, OR it into the right composite, register in `datasets_global.json`, and refresh this page.

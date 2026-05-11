# PFF Datasets — Usage Summary Table

Forensic audit of `pff_4.js` + `modules/timeSeriesAnthro.js` (covers v4.15.7-beta.1, verified 2026-05-11). This version traces every dataset's data flow end-to-end to determine if its result actually drives an output, rather than just checking whether the asset is loaded.

The audit caught several traps:
- Result computed but the `.or(...)` line that would consume it is **commented**
- Asset loaded inside a function that's never called
- Variable assigned but downstream consumer is in a commented block
- Conditional use behind a hard-coded `false` flag

## Status legend

| Flag | Meaning |
|:---:|---|
| ✅ **ACTIVE** | Result feeds an output layer or export via a non-commented line |
| 🟠 **LOADED_UNUSED** | Loaded at runtime but result is never consumed (line commented, flag false, or function never called) |
| 🔵 **COMMENTED_ONLY** | Only appears in commented-out code; zero runtime cost |
| ❌ **NOT_PRESENT** | Listed in JSON but no reference of any kind in code |

## Summary counts

| Status | Count |
|---|---:|
| ✅ ACTIVE | 14 |
| 🟠 LOADED_UNUSED | 12 |
| 🔵 COMMENTED_ONLY | 10 |
| ❌ NOT_PRESENT | 0 |
| **Total** | **36** |

---

## Full table

| # | Role | Dataset | Status | JSON flag | Evidence (file:line) |
|--:|------|---------|:------:|:---:|------|
| 1 | Forest cover | Hansen GFC v1.12 | ✅ | true ✓ | `gfcHansenTreecoverPrep()`, exported 02a |
| 2 | Forest cover | GLAD GLCLU v2 | ✅ | true ✓ | `gladLulcForestPrep()`, default forest source |
| 3 | Reference | FLII 2019 | ✅ | true ✓ | pff_4.js:6357 (UI-toggled reference layer) |
| 4 | Reference | FDaP Forest Persistence 2020 | ✅ | true ✓ | pff_4.js:6366 (UI-toggled reference layer) |
| 5 | Admin | FAO GAUL 2024 L0 | ✅ | true ✓ | Country clipping (used everywhere) |
| 6 | Protected areas | WDPA | ✅ | true ✓ | Tier 3 PA rescue + 03b export |
| 7 | Terrain | JAXA ALOS AW3D30 v3.2 | ✅ | true ✓ | Slope rescue + DEM/slope exports |
| 8 | Built-up | JRC GHSL SMOD + POP P2023A | ✅ | true ✓ | Built-up small + large composite |
| 9 | Built-up | DLR WSF Evolution | ✅ | true ✓ | OR'd into built-up small |
| 10 | Built-up | GISD30 1985–2020 | 🟠 | false ✓ | `includeGISD = false` at pff_4.js:89 — block never runs |
| 11 | Built-up | GISA 1972–2019 | 🟠 | false ✓ | `includeGISA = false` at pff_4.js:90 — block never runs |
| 12 | Built-up | WSF 2015 | 🔵 | false ✓ | timeSeriesAnthro.js:332 — commented `// var wsf2015 = …(unused)` |
| 13 | Built-up | WSF 2019 | 🔵 | false ✓ | timeSeriesAnthro.js:333 — commented `// var wsf2019 = …(unused)` |
| 14 | Population | LandScan Global | 🟠 | false ✓ | `processLandscanPop()` exported but **never called** from pff_4.js |
| 15 | Landcover | **GLC_FCS30D** | 🟠 | **true ← WRONG** | `landcover` → `croplandSel` computed (pff_4.js:5918), but `croplandComb = croplandGladSel //.or(croplandSelLessNoise)` at 5929 — OR is commented. Result discarded. |
| 16 | Landcover | GLAD Cropland (Potapov) | ✅ | true ✓ | pff_4.js:5929+5944 → `agriculture.or(croplandComb)` |
| 17 | Landcover | Global Pasture Watch v1 | ✅ | true ✓ | pff_4.js:5940 → `agriculture = pastureDatasetSel.or(...)` |
| 18 | Plantations | Descals Oil Palm YoP | ✅ | true ✓ | pff_4.js:5943 → `.or(oilPalmDescalsSel.unmask())` |
| 19 | Plantations | SDPT v2 | ✅ | true ✓ | pff_4.js:5941-5942 → both class 1 + class 2 used |
| 20 | Plantations | FDAP Palm 2024a | 🟠 | false ✓ | Loaded + thresholded at timeSeriesAnthro.js:708-712; aggregated into `fdapCommoditiesLargePatches` but the `.or(fdapCommoditiesLargePatches)` line at ~752 is **commented** |
| 21 | Plantations | FDAP Rubber 2024a | 🟠 | false ✓ | Same — disabled at line 752 |
| 22 | Plantations | FDAP Cocoa 2024a | 🟠 | false ✓ | Same — disabled at line 752 |
| 23 | Roads | **GRIP4 + AADT** | 🟠 | **true ← WRONG** | pff_4.js:5978-5985 → `roadsCollection` loaded, `roadsSel = …filter(year)`, but `// var roadsSmall = roadsSel.lte(...).or(roadsMosaicStatic)` is **commented**. Line 5985: `var roadsSmall = roadsMosaicStatic;` (OSM only). GRIP4 result discarded. |
| 24 | Roads | OSM Roads (PFF custom) | ✅ | true ✓ | pff_4.js:5985 → only roads source consumed |
| 25 | Roads | USA TIGER | 🔵 | false ✓ | timeSeriesAnthro.js:1089 — commented in legacy multi-source `roadsMosaicStatic` |
| 26 | Roads | WUR Congo Logging | 🔵 | false ✓ | timeSeriesAnthro.js:1088 — commented |
| 27 | Roads | Microsoft Global Roads | 🔵 | false ✓ | pff_4.js:5974-5976 — entire block commented |
| 28 | Roads | Ghost Roads Asia/NG | 🔵 | false ✓ | timeSeriesAnthro.js:1115 — commented |
| 29 | Roads | MapBiomas Brazil | 🔵 | false ✓ | timeSeriesAnthro.js:2-4 — commented at top of module |
| 30 | Disturbance | **JRC TMF v1_2025 — Deforestation Year** | 🟠 | **true ← WRONG** | timeSeriesAnthro.js:1130-1150 defines + exports `forest_disturbances()` (which loads TMF and ORs with Hansen loss). **But no caller in pff_4.js** — `forest_disturbances` is never invoked. |
| 31 | Water | OSM Water Layer | 🟠 | false ✓ | pff_4.js:6005-6008 → `osmCanals` computed, `// Map.addLayer(osmCanals,…)` commented |
| 32 | Water | PFF Navigable Rivers (WDB) | 🟠 | false ✓ | pff_4.js:6001-6002 → `nav_rivers` painted; never consumed downstream |
| 33 | Water | PFF Navigable Waterways USA | 🟠 | false ✓ | pff_4.js:6004 + 6010 → loaded; only commented `// Map.addLayer` |
| 34 | Ancillary | WRI SBTN Natural Lands v1.1 | 🔵 | false ✓ | timeSeriesAnthro.js:1239 — `// var dataset = ee.Image('WRI/SBTN/naturalLands/...')` |
| 35 | Ancillary | EPFD v2 | 🔵 | false ✓ | pff_4.js:6390-6392 — entire block commented |
| 36 | Ancillary | Tsinghua China Terrace v1 | 🔵 | false ✓ | timeSeriesAnthro.js:1 — single commented line |

---

## ⚠️ Three JSON flag corrections needed

`docs/datasets_global.json` currently claims these three are `active_in_default_run: true`, but the code does not consume them:

| Dataset | JSON says | Reality | Fix |
|---|---|---|---|
| **GLC_FCS30D** | `active` / true | LOADED_UNUSED — `.or()` commented at pff_4.js:5929 | Set `active_in_default_run: false`, status `optional_default_off` |
| **GRIP4 + AADT** | `active` / true | LOADED_UNUSED — split lines commented at pff_4.js:5982-5985 | Set `active_in_default_run: false`, status `optional_default_off` |
| **JRC TMF Deforestation Year** | `active` / true | LOADED_UNUSED — `forest_disturbances()` never called | Set `active_in_default_run: false`, status `optional_default_off` |

These three are biggest surprises — the docs (and intent) suggest they should be combined with Hansen/OSM, but the actual consume-lines were left commented (likely during a speed-optimisation pass that swapped GRIP4-based roads for the OSM raster and disabled the TMF disturbance composite).

---

## 12 datasets loaded but unused (candidates for cleanup)

These cost load-time but produce no output. Decide: wire them in or drop the load.

| Dataset | Why it's off | Suggested action |
|---|---|---|
| **GRIP4 + AADT** | Split lines commented (speed) | Decide: re-enable for AADT-weighted roads or remove |
| **GLC_FCS30D** | `.or(croplandSelLessNoise)` commented (slow) | Decide: re-enable or remove |
| **JRC TMF** | `forest_disturbances()` never called | Decide: wire into disturbance composite or remove |
| GISD30 | `includeGISD=false` (rock false positives) | Workshop swap option — keep or drop |
| GISA | `includeGISA=false` | Workshop swap option — keep or drop |
| LandScan | No caller | Wire up or drop |
| FDAP Palm | Commits primary forest as agri | **Do not enable** (auto-memory note) |
| FDAP Rubber | Same as Palm | **Do not enable** |
| FDAP Cocoa | Same as Palm | **Do not enable** |
| OSM Water (canals) | `Map.addLayer` commented | Decide if canals should buffer |
| WDB Navigable Rivers | Painted but unused | Decide if rivers should buffer |
| Navigable Waterways USA | Loaded but unused | Decide if waterways should buffer |

---

## What changed from the previous version of this table

- **GLC_FCS30D**: flipped flag was incorrect in last iteration. Confirmed LOADED_UNUSED by tracing `croplandSel → croplandComb`.
- **GRIP4 + AADT**: changed from ACTIVE to LOADED_UNUSED. Confirmed line 5985 sets `roadsSmall = roadsMosaicStatic` (OSM only).
- **JRC TMF Deforestation Year**: NEW finding — changed from ACTIVE to LOADED_UNUSED. `forest_disturbances()` is exported but never called from pff_4.js.
- **WRI SBTN Natural Lands**: changed from NOT_PRESENT to COMMENTED_ONLY. Found at timeSeriesAnthro.js:1239.
- **WSF 2015 / WSF 2019**: confirmed COMMENTED_ONLY (a previous audit briefly conflated them with WSF Evolution — they are separate, single-year products and their loader lines are explicitly commented as `(unused)`).
- **All 7 alternative roads datasets**: confirmed COMMENTED_ONLY (legacy vector-paint version replaced by OSM raster for speed).

**Net effect:** 14 ACTIVE (was 13–17 in earlier passes), 12 LOADED_UNUSED, 10 COMMENTED_ONLY, 0 NOT_PRESENT.

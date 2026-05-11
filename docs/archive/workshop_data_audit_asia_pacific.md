# PFF Asia-Pacific Workshop Data — Audit

Audit of the GEE exports staged on Google Drive at `G:/My Drive/PFF_Asia_Pacific_data/` against the inputs the QGIS plugin expects (`pff_qgis_tools/algorithms/full_workflow.py` parameter list, plugin v0.8.40 in the same Drive folder).

Generated 2026-05-08, re-verified after audit feedback. Repeated 30 m tile chunks (suffix `-XXXXXXXXXX-YYYYYYYYYY.tif`) are NOT counted as duplicates — they are GEE's automatic tile splitting for large exports and represent the same single layer.

## Headline finding

**Vietnam is missing 2 datasets at 90 m**: `02b_other_land_with_tree_cover_2020` and `02d_planted_forest_2020`. Both exist for VNM only at 30 m (`VNM_gee_02b_other_land_with_tree_cover_2020_30m_16h35m.tif`, `VNM_gee_02d_planted_forest_2020_30m_16h35m.tif`). Re-export at 90 m to match the rest of VNM's package, OR document that VNM users should run mixed-resolution.

---

## 1. Country coverage summary

| Country | ISO3 | Years exported | 30 m present | 90 m present | AOI vector | Plugin-ready? |
|---|---|---|---|---|---|---|
| Bhutan | BTN | **2010 + 2020** | — | ✅ | ✅ | ✅ both years runnable |
| Indonesia | IDN | 2020 | **✅ (multi-tile, in `30m/` subfolder)** | ✅ | ✅ | ✅ choose 30 m or 90 m |
| Lao PDR | LAO | 2020 | — | ✅ | ✅ | ✅ |
| Papua New Guinea | PNG | 2020 | — | ✅ | ✅ | ✅ |
| Thailand | THA | 2020 | — | ✅ | ✅ (duplicate AOI) | ✅ |
| Viet Nam | VNM | 2020 | partial (only 02b + 02d) | ✅ | ✅ | ⚠ see anomalies §4 |

Bhutan is the only country with **two analysis years**; all others are 2020-only. Indonesia is the only country with a **30 m** core export (multi-tile). VNM has a 30 m export for the OLTC + planted-forest layers only, while everything else is 90 m.

---

## 2. Layer × country matrix

Legend
- `90` = 90 m raster present
- `30` = 30 m raster present (Indonesia: 3-tile chunks for most layers; 8 tiles for DEM)
- `30·` = 30 m only (no 90 m available for that layer / country)
- `vec` = vector (shapefile) present
- `2010+2020` = both analysis years
- `—` = layer absent
- `(no year)` = static / non-annual layer

| Layer (file pattern) | Plugin slot | BTN | IDN | LAO | PNG | THA | VNM |
|---|---|---|---|---|---|---|---|
| `00a_aoi_<country>_vector` | `AOI` | vec | vec | vec | vec | vec | vec |
| `02a_forest_raw_<year>` | `FOREST_RASTER` (REQUIRED) | 90 (2010+2020) | 30 + 90 (2020) | 90 (2020) | 90 (2020) | 90 (2020) | 90 (2020) |
| `02a_glad_tree_height_m_<year>` | (no plugin slot — re-threshold helper) | 90 (2010+2020) | 30 + 90 (2020) | 90 (2020) | 90 (2020) | 90 (2020) | 90 (2020) |
| `02a_hansen_lossyear_raw` | (no plugin slot — debug) | 90 (no year) | 30 + 90 (no year) | 90 | 90 | 90 | 90 |
| `02a_hansen_treecover2000_raw` | (no plugin slot — re-threshold helper) | 90 | 30 + 90 | 90 | 90 | 90 | 90 |
| `02b_other_land_with_tree_cover_2020` | `FRA_AGRICULTURE_RASTER` | 90 (2020 only) | 90 | 90 | 90 | 90 | **30· (no 90 m) ⚠** |
| `02d_planted_forest_2020` | `PLANTATIONS_RASTER` | 90 (2020 only) | 90 | 90 | 90 | 90 | **30· (no 90 m) ⚠** |
| `03a_agriculture_<year>` | `AGRICULTURE_RASTER` | 90 (2010+2020) | 30 + 90 (2020) | 90 | 90 | 90 | 90 |
| `03a_builtup_large_<year>` | `BUILTUP_LARGE_RASTER` | 90 (2010+2020) | 30 + 90 (2020) | 90 | 90 | 90 | 90 |
| `03a_builtup_small_<year>` | `BUILTUP_SMALL_RASTER` | 90 (2010+2020) | 30 + 90 (2020) | 90 | 90 | 90 | 90 |
| `03a_roads_<year>` | `ROADS_RASTER` | 90 (2010+2020) | 30 + 90 (2020) | 90 | 90 | 90 | 90 |
| `03a_roads_osm_vector` | `ROADS` | vec | vec | vec | vec | vec | vec |
| `03b_protection_legal` | `PROTECTED_RASTER` | 90 (no year) | 30 + 90 (no year) | 90 | 90 | 90 | 90 |
| `03b_protection_legal_unfiltered_vector` | `PROTECTED_AREAS` | vec | vec | vec | vec | vec | vec |
| `03b_protection_natural_dem` | `DEM` | 90 (no year) | 30 (8 tiles) + 90 (2 tiles) | 90 | 90 | 90 | 90 |
| `03b_protection_natural_slope` | `SLOPE_RASTER` | 90 (no year) | 30 + 90 | 90 | 90 | 90 | 90 |
| `03c_pre_refinement_primary_forest_<year>` | (output reference, not input) | 90 (2010+2020) | 30 + 90 (2020) | 90 | 90 | 90 | 90 |
| `04a_primary_forest_<year>` | (output reference, not input) | 90 (2010+2020) | 30 + 90 (2020) | 90 | 90 | 90 | 90 |

`⚠` markers point to genuine anomalies (not GEE tile chunks) — see §4.

---

## 3. GEE export → QGIS plugin input mapping

Plugin parameter list confirmed from `pff_qgis_tools/algorithms/full_workflow.py:945-1163`. Slot name = constant in code; input prompt = the label the user sees.

| GEE export | Plugin input slot | Required? | Input prompt (plugin UI) |
|---|---|---|---|
| `00a_aoi_<country>_vector.shp` | `AOI` | optional | "00 Country: AOI boundary (vector, optional)" |
| `02a_forest_raw_<year>.tif` | `FOREST_RASTER` | **REQUIRED** | "02 Tree Cover: Forest raster (REQUIRED; binary 1/0; defines reference grid)" |
| `02b_other_land_with_tree_cover_2020.tif` | `FRA_AGRICULTURE_RASTER` | optional | "02 Tree Cover: Other land with tree cover raster" |
| `02d_planted_forest_2020.tif` | `PLANTATIONS_RASTER` | optional | "02 Tree Cover: Planted forest raster" |
| `03a_roads_osm_vector.shp` | `ROADS` | optional | "03a Disturbance Inputs: Roads (vector, optional)" |
| `03a_roads_<year>.tif` | `ROADS_RASTER` | optional, overrides vector | "03a Disturbance Inputs: Roads raster" |
| `03a_builtup_small_<year>.tif` | `BUILTUP_SMALL_RASTER` | optional | "03a Disturbance Inputs: Built-up small raster" |
| `03a_builtup_large_<year>.tif` | `BUILTUP_LARGE_RASTER` | optional | "03a Disturbance Inputs: Built-up large raster" |
| `03a_agriculture_<year>.tif` | `AGRICULTURE_RASTER` | optional | "03a Disturbance Inputs: Agriculture raster" |
| `03b_protection_natural_dem.tif` | `DEM` | optional | "03c Buffer Exceptions: DEM (slope computed from this)" |
| `03b_protection_natural_slope.tif` | `SLOPE_RASTER` | optional, overrides DEM | "03c Buffer Exceptions: OR Slope raster" |
| `03b_protection_legal_unfiltered_vector.shp` | `PROTECTED_AREAS` | optional | "03c Buffer Exceptions: Protected areas (vector)" |
| `03b_protection_legal.tif` | `PROTECTED_RASTER` | optional, overrides vector | "03c Buffer Exceptions: OR protected areas raster" |

The plugin's filename heuristic check (`_SLOT_FILENAME_HINTS` at `full_workflow.py:445-508`) recognises every one of these GEE patterns — i.e. the pluck-and-load workflow should produce no false-positive slot warnings on this Drive.

### GEE exports with NO plugin input slot

- `02a_glad_tree_height_m_<year>.tif` — raw GLAD height in metres; QGIS user can re-threshold to a custom binary forest before feeding to `FOREST_RASTER`. Not loaded directly.
- `02a_hansen_treecover2000_raw.tif` — same idea for Hansen canopy %.
- `02a_hansen_lossyear_raw.tif` — debug / time-series re-thresholding helper.
- `03c_pre_refinement_primary_forest_<year>.tif` — GEE output for comparison; the plugin produces its own equivalent.
- `04a_primary_forest_<year>.tif` — GEE final output for comparison; the plugin produces its own.

These are reference / comparison artefacts, not plugin inputs. Workshop note: it's worth being clear with users that these `.tif`s are NOT consumed by the plugin — they're either thresholded sources or GEE-side reference outputs.

### Plugin slots with NO matching GEE export

- `CUSTOM_<1|2|3>_RASTER` — three optional advanced custom-disturbance slots. By design unrelated to GEE export, used for national / bespoke layers.
- (no other gaps)

---

## 4. Anomalies / things to look at

| # | Country | Issue | What it is | Action |
|---|---|---|---|---|
| 1 | **VNM** | **`02b_other_land_with_tree_cover_2020` and `02d_planted_forest_2020` exist at 30 m only — no 90 m** | The two missing 90 m datasets — only `*_30m_16h35m.tif` exists for both. All of VNM's other layers are 90 m. | Re-export both at 90 m to match the rest of VNM's package. Until then VNM runs will be mixed-resolution (plugin reprojects, but file sizes inflate and the workshop UX is inconsistent). |
| 2 | BTN | **02b OLTC + 02d planted forest only for 2020**, despite forest / agriculture / roads / built-up / 04a all having 2010+2020 | These layers are derived from datasets that only have a 2020 baseline (SDPT v2 = 2020 snapshot, Descals oil palm to 2021). Re-running for 2010 with the same 2020 OLTC layer is the GEE app's intentional behaviour. | Document in the workshop guide: "OLTC and Planted Forest are 2020 baselines; reused for any analysisYear when running 2010". Confirms expected. No re-export needed. |
| 3 | LAO | `.aux.xml` sidecars present (QGIS-generated stats cache) | Not a problem, just worth knowing — appear once a user opens the file in QGIS | No action; ignored by plugin. |
| 4 | IDN | **DEM exported as 8 tiles at 30 m + 2 tiles at 90 m** while everything else is 3-tile / single | DEM is a much heavier layer (Float32 vs Byte for the binary masks), so GEE auto-split it more. Not duplicates, expected. | Workshop note: when loading IDN DEM, use a virtual raster (`gdalbuildvrt`) over the 8 tiles (now in `30m/`), or QGIS Layer → Build VRT, before feeding to plugin. The 90 m DEM (2 tiles in the parent folder) is the simpler workshop default. |
| 4b | IDN | All 30 m exports (44 TIFs) reorganised into `PFF_export_Indonesia/30m/` subfolder on 2026-05-08 | Was: 44 × 30 m + 13 × 90 m + multi-tile chunks all jumbled in one folder, hard to point participants at the 90 m package. Now: parent folder = workshop-ready 90 m package; `30m/` = high-res tiles for advanced use. | Done. |
| 5 | All countries except BTN, IDN | Only one analysis year (2020) | Workshop scope decision. | If 2010 runs are desired for the other five countries, queue equivalent BTN-style exports. Same disclaimer as #2 applies (OLTC, planted forest, protection legal/DEM/slope are non-yearly). |

> **Note on previous audit pass:** an earlier version of this file flagged duplicate timestamped exports for BTN (`03a_roads_osm_vector` ×2), THA (`00a_aoi` ×2), and VNM (`03b_protection_natural_slope` ×2). A fresh re-listing of the Drive shows only one of each — either Drive sync was mid-update during the first scan or the duplicates have already been cleaned. Current state is clean on those three.

---

## 5. Layers per country — what's missing vs the BTN reference

Bhutan has the most complete layer set (and is the self-test target — see auto-memory `feedback_pff_self_test_before_zip`). Checking each other country against BTN:

| Layer | LAO | PNG | THA | VNM | IDN |
|---|---|---|---|---|---|
| All 18 BTN layer families present? | ✅ | ✅ | ✅ | ✅ (with VNM 30 m note) | ✅ (with multi-tile DEM note) |
| 2010 also exported? | ❌ | ❌ | ❌ | ❌ | ❌ |
| 30 m exports? | ❌ | ❌ | ❌ | partial | ✅ full |

Conclusion: **no country is missing a layer family** other than the second analysis year, which is by-design (only BTN was run for 2010+2020). Five countries are 90 m / 2020 single-shot; IDN has the dual-resolution package; BTN has the dual-year package.

---

## 6. Recommendations

### Quick cleanup (low effort, high payoff)
1. **Re-export VNM `02b_other_land_with_tree_cover_2020` and `02d_planted_forest_2020` at 90 m** to match the rest of VNM's resolution. This is the only genuine missing-data finding in the audit (see anomaly #1). The 30 m versions already on the Drive can stay (or move to a `30m/` subfolder) — the plugin will still reproject correctly either way, but a consistent 90 m package is cleaner for workshop participants.

### Workshop documentation
3. Add a section to `docs/PFF_QGIS_Workshop_Guide_DRAFT.md` titled **"What's in the workshop data folder"** that summarises §1–2 of this audit so participants know:
   - BTN has two years; everyone else has 2020 only
   - IDN has both 30 m and 90 m; pick the resolution to match your laptop's RAM
   - The three `02a_*_raw_*.tif` and the `04a_primary_forest_*.tif` are reference / re-thresholding helpers, NOT plugin inputs
4. Add a callout box: **"OLTC and Planted Forest are 2020-only by design"** explaining that running BTN at 2010 reuses the 2020 OLTC + planted forest layers. Workshop participants will otherwise wonder why those files have no `_2010_` variant.

### Re-run candidates (only if needed for the workshop scope)
5. **2010 exports for LAO / PNG / THA / VNM / IDN** — only if the workshop asks for change-over-time comparisons. Same files as BTN's 2010 set; ~1 h GEE export queue per country.
6. **30 m exports for non-IDN countries** — only if a participant's laptop is fast enough to handle 30 m and they want pixel-precise outputs. IDN is already 30 m as the demo. The plugin will reproject any combination, so mixed-resolution workflows are fine but noisy in the log.

### Plugin alignment (no change needed today)
The plugin's slot-vs-filename heuristic (`_SLOT_FILENAME_HINTS`, `full_workflow.py:445-508`) already covers every GEE pattern in this Drive. No plugin code changes are required to load this data.

---

## 7. Plugin version on Drive — ⚠ STALE

`G:/My Drive/PFF_Asia_Pacific_data/QGIS_plugin/v0_8_40/pff_qgis_tools.zip` is **v0.8.40**.
Repo `pff_qgis_tools/metadata.txt` is **v0.15.0** — the Drive copy is several major batches behind (see recent commits: 0.13.1 → 0.13.2 → 0.15.0).

**Action before workshop:** rebuild the plugin zip from the current repo (`pff_qgis_tools/`) and replace the Drive copy. Otherwise participants installing from the Drive get the old version, won't have the latest input slots / batch-28 fixes / batch-29 UX, and any references to GEE export filenames the older plugin doesn't understand will trigger slot-warning false positives.

Suggested replacement path: `G:/My Drive/PFF_Asia_Pacific_data/QGIS_plugin/v0_15_0/pff_qgis_tools.zip` (and remove `v0_8_40` after confirming workshop participants are installing the new one).

# PFF Output Naming Convention (Option D)

*Decided 2026-04-26, refined with FRA-aligned schema 2026-04-27. See [planning/tasks_260425_merged.md → P1.13, P1.16, P1.19, P1.20](../../planning/tasks_260425_merged.md) for the backlog. Helper utility implemented in `pff_qgis_tools/utils.py` (Python) and `pff_4.js` (JavaScript) — see those modules for the canonical reference implementation.*

## Schema

```
[ISO3]_[platform]_[step][substep]_[layer_name].[ext]
```

| Component | Required | Notes |
|---|---|---|
| `[ISO3]_` | optional | ISO3 country code (e.g. `KEN`). Omit when no country selected. Always uppercase when present. Trailing underscore included. |
| `[platform]` | required | `gee` or `qgis`. **Use these exact strings — not `app` / `plugin`.** |
| `[step][substep]` | required | Two-digit step (`00`-`06`) optionally followed by a substep letter (`a`-`z`). Always leading-zero on the step. |
| `[layer_name]` | required | Snake-case layer descriptor. Drop `results_` / `refined_` / `validation_` qualifiers — the step number already encodes the production stage. |
| `.[ext]` | required | Standard file extension. `tif` for rasters, `gpkg` for vectors, `csv` for tables, `shp` for shapefile-zone outputs, `json` for metadata sidecars. |

## Step numbers

Step prefix encodes the **production stage** (where in the pipeline the file was made), not the action that saves it. Sortable alphabetically = workflow order. Numbers are policy-stable (changing them later is a breaking change).

| Step | Stage | Example file | UI section in plugin |
|---|---|---|---|
| `00` | Context (supplies ISO3) | — (no files of its own) | Country / Context |
| `01` | Time Period (supplies year) | — (no files of its own) | Time Period |
| `02` | **Forest Definition** | `02b_forest.tif`, `02c_natural_forest.tif`, `02d_plantations.tif` (when produced) | Forest Inputs / Forest Definition |
| `03` | Human Influence Inputs | `03a_roads.tif`, `03b_protection_legal.tif` (when user opts to save) | Human Influence Layers |
| `04` | **Refine — ecological viability** | `04a_primary_forest.tif`, `04b_pre_connectivity_primary_forest.tif`, `04c_combined_coded_raster.tif` | Refine Output |
| `05` | Statistics | `05a_area_statistics.csv`, `05b_area_statistics_by_admin1.shp` | (right-panel in GEE; standard form section in QGIS) |
| `06` | Validation / Export | `06a_primary_forest_vector.gpkg`, `06b_primary_forest_dissolved.gpkg` | (right-panel in GEE; standard form section in QGIS) |

Step 02 is a **reframe** — formerly "Forest Inputs", now "Forest Definition" — because it covers both raw source layers (`02a_*`) and the FRA-aligned forest-type derivations (`02b`, `02c`, `02d`). See [Forest Definition (Step 02)](#forest-definition-step-02) below.

Step 04 means **ecological viability filtering only** — patch/thin-section removal via neighbourhood density + raster sieve. Anything that isn't viability-related does NOT belong at step 04, regardless of whether the word "refine" sounds general. Forest-type derivations (e.g. naturally regenerating forest = Natural − Primary) are stats numbers, not new step-04 outputs.

## Substep policy (DECIDED 2026-04-27)

**Input steps (`02`, `03`) — substep letter encodes semantic category.** Multiple files share a letter; the `layer_name` field disambiguates. This scales to user custom slots and dataset additions (e.g. splitting roads into small/large) without enumerating letters.

**Output steps (`04`, `05`, `06`) — substep letter is a unique, position-stable file ID.** `04a` always means "the headline result", etc. Adding a new substep is allowed; reusing or shifting existing letters is a breaking change.

| Step | Substep meaning | Why |
|---|---|---|
| `02` (input) | category-letter | Open set; `02b_forest`, `02c_natural_forest`, `02d_plantations` etc. — name disambiguates within categories |
| `03` (input) | category-letter | `03a_*` = disturbance inputs; `03b_*` = protection exceptions. New layers don't push toward `03j`/`03k`/... |
| `04` (output) | unique-letter | Small fixed set with meaningful production order |
| `05` (output) | unique-letter | Small fixed set |
| `06` (output) | unique-letter | Small fixed set |

## Forest Definition (Step 02)

Step 02 produces three forest-type layers that map onto the FRA hierarchy. Whichever ones get produced depends on user inputs (see [Variable output set](#variable-output-set-by-input-declaration) below).

```
02a_*                       Source components (Hansen treecover2000_raw, Hansen lossyear_raw,
                            GLAD tree_height_m) — when GEE produces them and user opts to save
02b_forest                  ≈ FRA Forest baseline (thresholded tree cover)
02c_natural_forest          ≈ FRA Natural Forest (Forest minus planted forest)
02d_plantations             ≈ FRA Planted Forest (SDPT class 1 only — see P1.20)
```

### FRA framework + caveats

The tool's forest layers are **operational proxies** — they lean on the best globally-consistent datasets and apply the FRA framework as faithfully as those datasets allow. They are NOT an FRA classification. Official FRA numbers come from country submissions with local context the tool cannot replicate. Compare in spirit, not as ground truth.

```
Tree cover (Hansen + GLAD, thresholded)     ← physical canopy + height
   │
   ├─ 02b_forest               ≈ FRA Forest         (caveat: agriculture filter is partial — see P1.18)
   │     │
   │     ├─ 02d_plantations    ≈ FRA Planted forest  (caveat: SDPT incompleteness, smallholders missing)
   │     │
   │     └─ 02c_natural_forest ≈ FRA Natural forest  (caveat: SDPT incompleteness can wrongly exclude
   │                                                   real natural forest; missed planted areas remain)
   │            │
   │            ├─ 04a_primary_forest    ← Natural forest minus disturbance buffers + viability filter
   │            │                           (the headline PFF output)
   │            │
   │            └─ "Naturally regenerating forest" = 02c − 04a — **stats only**, not a saved file
   │                                                              (trivial raster math; users can derive)
   │
   └─ Agricultural tree cover (oil palm, tree crops, agroforestry)
                                            ← routed via agriculture buffering toward primary forest;
                                              NOT in 02d_plantations (per P1.20 — FRA-correct mapping)
```

**Why 02b is "≈ FRA Forest" not "FRA Forest":** Hansen tree cover above thresholds doesn't exclude agricultural land use the way FRA does. Oil palm, agroforestry, and orchards meeting the canopy/height thresholds remain in `02b_forest` until removed downstream via the agriculture disturbance buffer. P1.18 may add an option to exclude agriculture from the Forest baseline directly.

**Why 02c is "≈ FRA Natural Forest" not "FRA Natural Forest":** The plantations layer used for subtraction (`02d`) is SDPT class 1 + national overrides; it misses smallholder plantations and may include some misclassified natural forest pixels. The result is "tree-covered areas not identified as planted" — a reasonable global-scale proxy, not a strict classification.

**Why "naturally regenerating forest" is only a stats number:** FRA defines naturally regenerating forest = Natural forest − Primary forest. With `02c` and `04a` both produced, this is a one-step raster subtraction users can do themselves. Producing it as a saved file would bloat outputs without adding analytical value. Stats panel reports the area inline.

### Variable output set (by input declaration)

User declares what their forest input represents via the Step 02 dropdown (P1.19 — multi-level input declaration). What gets produced depends on declaration + which auxiliary layers are provided:

| Forest input declared as | Plantations layer | Files produced (Step 02) |
|---|---|---|
| Tree cover | yes (+ agriculture) | `02b_forest`, `02c_natural_forest`, `02d_plantations` |
| Tree cover | yes (only) | `02c_natural_forest` (loose — agriculture not filtered), `02d_plantations` |
| Tree cover | no | None at step 02 (input passes through to 04 directly) |
| Forest (FRA) | yes | `02b_forest` (= input), `02c_natural_forest`, `02d_plantations` |
| Forest (FRA) | no | `02b_forest` (= input) |
| Natural forest | n/a | `02c_natural_forest` (= input) |
| Naturally regenerating | n/a | None at step 02 — primary forest computation should yield ≈ 0 area; warn |

Files only exist when actually computed. `run_metadata.json` records which layers were produced, which were skipped, and why.

## Step 03 — Human Influence Inputs

Two semantic categories under Step 03; substep letter encodes the category.

```
03a_roads                                    ← disturbance inputs (get buffered)
03a_builtup_small
03a_builtup_large
03a_agriculture                              ← cropland + pasture + oil palm + SDPT class 2 (per P1.20)
03a_custom_<userlabel>                       ← unbounded — N user custom slots
03b_protection_legal                         ← protection exceptions (preserve forest from buffers)
03b_protection_legal_unfiltered_vector
03b_protection_natural_dem
03b_protection_natural_slope
```

Splitting an existing layer (e.g. `03a_roads_small` and `03a_roads_large`) requires no schema change — the category letter accommodates open-ended additions.

**Plantations does NOT have its own Step 03 entry.** The raw plantations layer lives at `02d_plantations` (Forest Definition), where its primary semantic role (forest-type discriminator) sits. If the user opts to also use plantations as a buffered disturbance, that's a checkbox toggle that consumes the `02d` layer into the agriculture buffer — no separate `03_plantations` file is produced.

## Step 04 — Refine Output (ecological viability)

```
04a_primary_forest                          ← headline PFF result
04b_pre_connectivity_primary_forest         ← state before viability filtering
04c_combined_coded_raster                   ← optional debug raster
```

`04a` always = headline result. `04b` always = pre-connectivity. `04c` always = optional debug. **Nothing else lives at step 04** — forest-type derivations (Forest, Natural, Naturally regenerating) belong at step 02; stats CSV belongs at step 05; vectorisations belong at step 06.

Substeps are stable: adding a new substep is allowed (`04d`, `04e`); reusing or shifting existing letters is a breaking change.

## Stats panel (Step 05) — FRA-faithful four-row breakdown

Stats reports areas matching FRA reportable categories. Hidden rows when input/data isn't available — don't surface things that didn't happen.

```
─────────────────────────────────────────────────────────────────
Forest (≈FRA def):                 2,705 km²    [FRA 2025: 2,725 ✓ within 1%]
   ├─ Natural forest:              2,612 km²    [FRA 2025: not separately reported]
   │     ├─ Primary forest:        1,418 km²    [FRA 2025: 1,400 ✓ within 1.4%]
   │     └─ Naturally regenerating:  1,194 km²  [FRA 2025: 1,180 ✓ within 1.2%]
   └─ Planted forest:                 93 km²    [no FRA comparator in tool]
─────────────────────────────────────────────────────────────────
```

- "Naturally regenerating" row computed inline as `02c − 04a` area; no separate file
- FRA comparators come from `modules/fraStats.js`: forest area (235 countries), primary forest (56), naturally regenerating (86)
- Plantations has no FRA comparator in the tool's lookup (FRA reports it; not currently in `fraStats.js`)
- Rows are hidden (not shown as "—") when the corresponding layer wasn't produced this run

## Intermediates

Files that aren't headline outputs (working files, prepared inputs, distance surfaces) live under `intermediates/` with **no top-level step prefix**. The folder location + platform tag (`qgis_` — only QGIS produces intermediates) carries the "this is a working file" semantic.

```
intermediates/
  prepared/                ← reprojected + aligned inputs (reusable across runs)
    forest.tif
    natural_forest.tif     ← when computed
    plantations.tif
    roads.tif, builtup_small.tif, builtup_large.tif, agriculture.tif
    protected.tif, dem.tif, slope.tif
    custom_1.tif, custom_2.tif, custom_3.tif

  distances/               ← cached distance surfaces
    dist_roads.tif, dist_builtup.tif, dist_builtup_large.tif,
    dist_agriculture.tif
    dist_custom_1.tif, ...

  tier1_undisturbed.tif    ← tier-logic byproducts
  tier2_steep.tif
  tier3_protected.tif
  forest_inside_buffers.tif
  steep_slope.tif, gentle_slope.tif

  anthropogenic_mask.tif   ← combined buffered disturbance mask

  refine_step_a_neighbourhood.tif    ← (only when both refine steps run)
  refine_step_b_sieve_unmasked.tif   ← (only when refine step b runs)

  _vectorize/              ← Stage 7 vectorise scratch
  _zonal_work/             ← Stage 6 zonal stats temporary workspace
```

## Rules

1. **Always leading zero** on step (`01`, not `1`).
2. **No colons in filenames.** Use underscores or dashes if you need separators within a layer name.
3. **Numbering is stable.** Once published, step numbers + substep letters don't change without a documented breaking-change migration.
4. **Platform tag is `gee` or `qgis`.** Never `app`, `plugin`, `module`, or anything else.
5. **Filename step encodes production stage**, not the user-facing UI section it's controlled from. (UI sections may rearrange; file numbers don't.)
6. **Layer names drop the production-category prefix.** `04a_primary_forest.tif`, not `04a_results_primary_forest.tif` — the `04` already says "this came from Refine".
7. **ISO3 prefix is optional.** Include when a country was selected in the run; omit otherwise.
8. **Input substeps are category-letters; output substeps are unique-letters.** See [Substep policy](#substep-policy-decided-2026-04-27).
9. **Step 02 file slots are fixed** (`02a_*` source / `02b_forest` / `02c_natural_forest` / `02d_plantations`). New forest-type derivations don't get new Step 02 letters — they live in stats or as intermediates.
10. **Step 04 = ecological viability only.** Anything that isn't patch/sieve viability filtering does not belong at step 04.

## Helper utility

Both tools ship a `generate_layer_name()` / `generateLayerName()` helper that constructs filenames per this schema. Use it instead of manual string concatenation so all call sites are consistent.

**Python** (`pff_qgis_tools/utils.py`):
```python
from pff_qgis_tools.utils import generate_layer_name, PLATFORM_QGIS

generate_layer_name('KEN', PLATFORM_QGIS, '04a', 'primary_forest')
# -> 'KEN_qgis_04a_primary_forest.tif'

generate_layer_name(None, PLATFORM_QGIS, '06b',
                    'primary_forest_dissolved', ext='gpkg')
# -> 'qgis_06b_primary_forest_dissolved.gpkg'
```

**JavaScript** (`pff_4.js`):
```javascript
generateLayerName('KEN', PLATFORM_GEE, '05a', 'area_statistics', 'csv')
// -> 'KEN_gee_05a_area_statistics.csv'

generateLayerName(null, PLATFORM_GEE, '04a', 'primary_forest')
// -> 'gee_04a_primary_forest.tif'
```

Both helpers raise / throw on `platform ∉ {'gee', 'qgis'}`, missing `step`, or missing `name` — typos at call sites fail fast.

## Folder examples

### Plugin run, no country selected (single export)

```
my-output-folder/
  qgis_02b_forest.tif                        ← when input declared as Forest or derived from tree cover
  qgis_02c_natural_forest.tif                ← when plantations subtraction ran
  qgis_04a_primary_forest.tif
  qgis_04b_pre_connectivity_primary_forest.tif
  qgis_04c_combined_coded_raster.tif         ← (when ticked)
  qgis_05a_area_statistics.csv
  qgis_06a_primary_forest_vector.gpkg        ← (when Stage 7 ticked)
  qgis_06b_primary_forest_dissolved.gpkg     ← (when Stage 7 ticked)
  run_metadata.json
  intermediates/
    ... (see Intermediates section above)
```

### Plugin run, ISO3 = KEN, Forest input + plantations

```
my-output-folder/
  KEN_qgis_02b_forest.tif
  KEN_qgis_02c_natural_forest.tif
  KEN_qgis_04a_primary_forest.tif
  KEN_qgis_04b_pre_connectivity_primary_forest.tif
  KEN_qgis_05a_area_statistics.csv
  KEN_qgis_05b_area_statistics_by_admin1.shp ← (when zonal stats ticked)
  KEN_qgis_06a_primary_forest_vector.gpkg
  KEN_qgis_06b_primary_forest_dissolved.gpkg
  KEN_run_metadata.json
  intermediates/...
```

### GEE run, ISO3 = KEN, two years (2010 + 2020)

```
GEE Drive folder/
  KEN_gee_02a_hansen_treecover2000_raw_30m.tif
  KEN_gee_02a_hansen_lossyear_raw_30m.tif
  KEN_gee_02a_glad_tree_height_m_2010_30m.tif
  KEN_gee_02a_glad_tree_height_m_2020_30m.tif
  KEN_gee_02b_forest_2010_30m.tif
  KEN_gee_02b_forest_2020_30m.tif
  KEN_gee_02c_natural_forest_2010_30m.tif    ← (P1.16 — new export)
  KEN_gee_02c_natural_forest_2020_30m.tif
  KEN_gee_02d_plantations_2010_30m.tif       ← SDPT class 1 only (per P1.20)
  KEN_gee_02d_plantations_2020_30m.tif
  KEN_gee_03a_roads_2010_30m.tif
  KEN_gee_03a_roads_2020_30m.tif
  ... (per-year for each step)
  KEN_gee_04a_primary_forest_2010_30m.tif
  KEN_gee_04a_primary_forest_2020_30m.tif
  KEN_gee_05a_area_statistics_2010.csv
  KEN_gee_05a_area_statistics_2020.csv
  KEN_gee_run_metadata_2010_30m.geojson
  KEN_gee_run_metadata_2020_30m.geojson
```

(Year suffixes — `_YYYY` — on per-year files. Stable substep letters across years so e.g. `04a_primary_forest_2010.tif` and `04a_primary_forest_2020.tif` pair up cleanly.)

### Mixed GEE + QGIS folder (the auto-pairing motivation)

```
country-bundle/
  KEN_gee_02b_forest_2020_30m.tif             ← raw input from GEE
  KEN_qgis_04a_primary_forest.tif             ← QGIS-derived result
  KEN_gee_04a_primary_forest_2020_30m.tif     ← GEE-derived result for compare
  KEN_qgis_05a_area_statistics.csv
  KEN_gee_05a_area_statistics_2020.csv
```

Sorted alphabetically the file groups naturally by country + step, with the platform tag making the source obvious. A future auto-collection tool (P2.21) can scan this folder, pair `gee_` and `qgis_` outputs at matching steps, and drive automated comparison workflows.

## What NOT to use

- `app`, `plugin`, `tool`, `module` as platform tags. Use `gee` / `qgis`.
- `1`, `2`, `3` (no leading zero) for step numbers. Use `01`, `02`, `03`.
- Colons (`:`) anywhere in filenames.
- `results_`, `refined_`, `validation_` prefixes on layer names. Step number encodes that.
- Spaces. Use underscores.
- Capital letters in layer names (snake_case only). ISO3 is the only uppercase part.
- `04d_*` for forest-type derivations. Step 04 is ecological viability only.
- Unique substep letters on input steps (no `03e_plantations`, `03f_protection_*`). Use category letters (`03a` / `03b`).
- "Naturally regenerating forest" as a saved file. Stats only.
- "Plantations" as the bucket name for oil palm + tree crops + planted forest. Per FRA, plantations = planted forest only; oil palm + tree crops = agriculture (per P1.20).

## Migration status

- **P1.13 plugin side:** ✅ shipped 2026-04-27 (commit `8bf5960`). All plugin output paths migrated to Option D via `generate_layer_name()`. Filename `04d_forest_naturally_regenerating.tif` slated for rename to `02c_natural_forest.tif` per the FRA-aligned schema (P1.16).
- **P1.13 GEE side:** WIP on branch `feat/v1-release-batch10` (uncommitted). All `Export.image.toDrive` / `Export.table.toDrive` description / fileNamePrefix calls migrated via new `mkExportName()` helper. Pending paste-into-Code-Editor verify cycle.
- **P1.16-P1.20:** captured in `planning/tasks_260425_merged.md`. Code changes not yet started.

## See also

- [`planning/tasks_260425_merged.md`](../../planning/tasks_260425_merged.md) — backlog entries P1.13, P1.16, P1.17, P1.18, P1.19, P1.20, P2.20, P2.21
- [`pff_qgis_tools/utils.py`](../../pff_qgis_tools/utils.py) — Python helper + constants
- [`pff_4.js`](../../pff_4.js) — JavaScript helper + constants
- [`modules/fraStats.js`](../../modules/fraStats.js) — FRA 2025 lookup tables (forest area, primary forest, naturally regenerating)
- [`modules/timeseriesAnthro.js`](../../modules/timeseriesAnthro.js) — `processingPlantationsMosaic()` (slated for FRA-correct refactor per P1.20)

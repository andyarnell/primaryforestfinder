# PFF Output Naming Convention (Option D)

*Decided 2026-04-26. See [planning/tasks_260425_merged.md → P1.13](../../planning/tasks_260425_merged.md) for the full backlog entry. Helper utility implemented in `pff_qgis_tools/utils.py` (Python) and `pff_4.js` (JavaScript) — see those modules for the canonical reference implementation.*

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
| `02` | Forest Inputs | `02a_forest_input_hansen.tif` (when user opts to save raw) | Forest Inputs |
| `03` | Human Influence Inputs | `03a_human_influence_roads.tif` (when user opts to save raw) | Human Influence Layers |
| `04` | Refine | `04a_primary_forest.tif`, `04b_pre_connectivity_primary_forest.tif`, `04c_combined_coded_raster.tif`, `04d_forest_naturally_regenerating.tif` | Refine Output |
| `05` | Statistics | `05a_area_statistics.csv`, `05b_area_statistics_by_admin1.shp` | (right-panel in GEE; standard form section in QGIS) |
| `06` | Validation / Export | `06a_primary_forest.gpkg`, `06b_primary_forest_dissolved.gpkg` | (right-panel in GEE; standard form section in QGIS) |

## Substeps

Use letters (`a`, `b`, `c`, …) when multiple files belong to the same step:

```
04a_primary_forest.tif                 ← headline result
04b_pre_connectivity_primary_forest.tif
04c_combined_coded_raster.tif          ← optional debug raster
04d_forest_naturally_regenerating.tif  ← when plantations refined
```

Substeps are stable: `04a` always means "the primary headline result", `04b` always means "pre-connectivity", etc. Adding a new substep is allowed (`04e`, `04f`); reusing or shifting existing letters is a breaking change.

## Intermediates

Files that aren't headline outputs (working files, prepared inputs, distance surfaces) live under `intermediates/` with **no top-level step prefix**. The folder location + platform tag (`qgis_` — only QGIS produces intermediates) carries the "this is a working file" semantic.

```
intermediates/
  prepared/                ← reprojected + aligned inputs (reusable across runs)
    forest.tif
    roads.tif, builtup_small.tif, builtup_large.tif, agriculture.tif
    plantations.tif, protected.tif, dem.tif, slope.tif
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
  qgis_04a_primary_forest.tif
  qgis_04b_pre_connectivity_primary_forest.tif
  qgis_04c_combined_coded_raster.tif         ← (when ticked)
  qgis_04d_forest_naturally_regenerating.tif ← (when plantations refined)
  qgis_05a_area_statistics.csv
  qgis_06a_primary_forest.gpkg        ← (when Stage 7 ticked)
  qgis_06b_primary_forest_dissolved.gpkg     ← (when Stage 7 ticked)
  run_metadata.json
  intermediates/
    ... (see Intermediates section above)
```

### Plugin run, ISO3 = KEN

```
my-output-folder/
  KEN_qgis_02a_forest_input_glad.tif         ← (when "Save inputs" ticked)
  KEN_qgis_03a_human_influence_roads.tif     ← (when "Save inputs" ticked)
  KEN_qgis_04a_primary_forest.tif
  KEN_qgis_04b_pre_connectivity_primary_forest.tif
  KEN_qgis_05a_area_statistics.csv
  KEN_qgis_05b_area_statistics_by_admin1.shp ← (when zonal stats ticked)
  KEN_qgis_06a_primary_forest.gpkg
  KEN_qgis_06b_primary_forest_dissolved.gpkg
  KEN_run_metadata.json
  intermediates/...
```

### GEE run, ISO3 = KEN, two years (2010 + 2020)

```
GEE Drive folder/
  KEN_gee_02a_forest_input_glad_2010.tif
  KEN_gee_02a_forest_input_glad_2020.tif
  KEN_gee_03a_human_influence_roads_2010.tif
  KEN_gee_03a_human_influence_roads_2020.tif
  ... (per-year for each step)
  KEN_gee_04a_primary_forest_2010.tif
  KEN_gee_04a_primary_forest_2020.tif
  KEN_gee_05a_area_statistics_2010.csv
  KEN_gee_05a_area_statistics_2020.csv
  KEN_gee_pff_run_metadata_2010_30m.geojson
  KEN_gee_pff_run_metadata_2020_30m.geojson
```

(Year suffixes — `_YYYY` — on per-year files. Stable substep letters across years so e.g. `04a_primary_forest_2010.tif` and `04a_primary_forest_2020.tif` pair up cleanly.)

### Mixed GEE + QGIS folder (the auto-pairing motivation)

```
country-bundle/
  KEN_gee_02a_forest_input_glad_2020.tif      ← raw input from GEE
  KEN_qgis_04a_primary_forest.tif             ← QGIS-derived result
  KEN_gee_04a_primary_forest_2020.tif         ← GEE-derived result for compare
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

## Migration status (P1.13)

As of 2026-04-26, neither tool has migrated to this schema yet. The helper utilities exist; the consumer call sites still use ad-hoc filenames. Migration is the substance of P1.13.

## See also

- [`planning/tasks_260425_merged.md`](../../planning/tasks_260425_merged.md) — backlog entries P1.13, P2.20, P2.21
- [`pff_qgis_tools/utils.py`](../../pff_qgis_tools/utils.py) — Python helper + constants
- [`pff_4.js`](../../pff_4.js) — JavaScript helper + constants

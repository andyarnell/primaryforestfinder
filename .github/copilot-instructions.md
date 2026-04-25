# Copilot Instructions for Primary Forest Finder

This repository supports countries with primary forest reporting through three components:
1. A **Google Earth Engine (GEE) JavaScript app** for global-scale analysis
2. A **QGIS Processing plugin** for national/subnational desktop workflows
3. **Preprocessing notebooks** for extracting and formatting input data (OSM, Microsoft Roads, etc.)

---

## 1. GEE JavaScript App (`pff_4.js`, `pff_connectivity*.js`, `pff_cepi.js`, `modules/`)

The current production script is `pff_4.js`. Older versions (`pff.js`, `pff_3.js`, `old_pff.js`, `old_pff2/`) are kept for reference but should not be modified.

- This is a Google Earth Engine (GEE) JavaScript app.
- Code must be compatible with the GEE Code Editor environment.

### General principles

- Prefer minimal, incremental edits over major refactors.
- Preserve existing UI patterns and naming conventions.
- Use snake_case for new identifiers where practical.
- Prefer config-driven patterns over repetitive hardcoding.
- Avoid introducing abstractions unless they clearly reduce duplication.
- Do not rewrite unrelated parts of the app.
- When suggesting code, explain assumptions briefly.

### GEE-specific rules

- Always use Earth Engine objects (`ee.Image`, `ee.FeatureCollection`, etc.) correctly.
- Do not mix client-side and server-side logic incorrectly.
- Avoid unnecessary use of `.getInfo()` or client-side evaluation.
- Prefer server-side operations (`map`, `reduce`, etc.) where appropriate.
- Ensure all code runs in the GEE Code Editor without modification.

### Code Editor compatibility

- Write code that can be easily copied and pasted into the GEE Code Editor.
- Avoid dependencies on external modules, build tools, or modern JS features not supported in GEE.
- Prefer simple, self-contained functions over complex module structures.
- Avoid async/await, promises, or browser-specific APIs.

### Style for GEE code

- Keep functions small, explicit, and readable.
- Clearly separate data loading, processing, and visualization.
- Follow the existing module pattern: `exports.functionName = function(params) {...}`.
- Use JSDoc comments with parameter types and return values for public functions.
- When adding new functionality, follow existing patterns in the codebase.

### GEE dataset handling

- Prefer configuration-driven dataset definitions where possible.
- Avoid hardcoding dataset logic in multiple places.
- Keep dataset loading and processing modular and reusable.
- The `modules/timeSeriesAnthro.js` module centralises most anthropogenic input datasets. Key datasets include:
  - **Forest / boundaries**: Hansen Global Forest Change, JRC TMF (deforestation year), WDPA (protected areas), USDOS/LSIB (boundaries), GEDI canopy height.
  - **Land cover**: GLC-FCS30D (30 m, five-yearly + annual), Copernicus Land Cover.
  - **Built-up / settlement (time series)**: WSF Evolution (DLR), GHSL SMOD + POP (JRC), GISD30, GISA.
  - **Cropland**: GLAD Croplands (Potapov), with forward-fill to ensure persistent presence.
  - **Plantations**: SDPT v2 (planted trees / tree crops), FDAP modelled commodities (palm, rubber, cocoa), Descals oil palm year-of-planting.
  - **Roads**: GRIP4 modelled roads (time series, interpolated), OSM roads raster, Congo Basin forest logging roads, TIGER US roads.
  - **Population**: LandScan Global (ORNL).
- Target years for time-series collections: `[1990, 2000, 2010, 2015, 2020]`.
- Use `forwardFillBinaryTimeSeries()` for layers where presence is cumulative (e.g., cropland, built-up).

### GEE distance and masking patterns

- Distance computation: prefer `fastDistanceTransform()` with fallback to `cumulativeCost()`.
- Binary masks: 1=presence, 0=absence. Use `.selfMask()`, `.updateMask()`, `.unmask(0)`.
- Use `.reproject({crs: proj, scale: scale})` for zoom-invariant results where needed.
- Key parameters: `neighborhoodSize = 170` (~5km at 30m), `maxForAllDistances = 5100` m, `slope_threshold = 45` degrees.

### Output expectations (GEE)

- Provide code that is ready to run with minimal modification.
- Highlight exactly where new code should be inserted if not inserting it directly.
- Avoid overengineering solutions.

---

## 2. QGIS Processing Plugin (`pff_qgis_tools/`)

- This is a **QGIS Processing provider plugin** (minimum QGIS 3.38).
- Only use `native:` and `gdal:` processing providers — avoid SAGA and GRASS (instability).
- Python code runs inside the QGIS bundled Python environment (includes `osgeo`, `numpy`).

### Plugin architecture

- `pff_plugin.py` — thin registration wrapper.
- `pff_provider.py` — registers all algorithms under the "Primary Forest Finder" toolbox group.
- `utils.py` — shared GDAL/QGIS helpers (reproject, rasterize, proximity, `ensure_dir()`, etc.).
- `algorithms/` — individual processing algorithms, each in its own file.

### Algorithm conventions

All algorithms follow the `QgsProcessingAlgorithm` pattern:
- `name()` → snake_case unique ID.
- `displayName()` → human-readable name.
- `group()` → always `"Primary Forest Finder"`.
- `initAlgorithm()` → define parameters (raster layers, vector layers, numbers, CRS, folders).
- `processAlgorithm()` → main logic using `feedback.pushInfo()`, `feedback.setProgress()`, `feedback.reportError()`.
- Return `{OUTPUT_KEY: output_path}`.

### The 7-step workflow

The algorithms run in sequence (or via `full_workflow.py`):
1. **validate_inputs** — check CRS consistency, projected CRS, resolution, binary values of the inputs only (do not validate outputs).
2. **prepare_inputs** — reproject, rasterize vectors, align to forest raster reference grid.
3. **distance_surfaces** — compute proximity rasters for anthropogenic layers (cached for reuse).
4. **anthropogenic_mask** — apply distance thresholds and combine masks.
5. **primary_forest** — three-tier decision tree (undisturbed, steep-slope, protected).
6. **refine_output** (internal file: `connectivity_filter.py`, display name "5 — Refine Output") — neighbourhood density filter matching the GEE tool's "Refine Output" step.
7. **full_workflow** — one-click orchestration of steps 1–6.

### QGIS coding rules

- **CRS**: All layers must be in a projected CRS with metre units. Use a CRS appropriate to the country of interest (e.g., a national CRS or UTM zone), or a global equal-area projection if the analysis spans multiple countries. Validate and auto-reproject early.
- **Reference grid**: The forest raster defines the reference extent, resolution, and pixel origin. All other rasters must align to it.
- **Binary convention**: Strictly 0/1 for presence/absence. NoData should be None or 255, never 0.
- **Raster output**: GeoTIFF with LZW compression and tiling (`["COMPRESS=LZW", "TILED=YES"]`).
- **File organisation**: Use automatic subdirectories (`prepared/`, `distances/`) via `ensure_dir()`.
- **Caching**: Distance surfaces are cached to disk. Skip recomputation if the output file already exists. This allows fast re-runs with different thresholds.
- Use direct GDAL (`gdal.Open()`, `GetRasterBand(1).ReadAsArray()`) and numpy for array operations.
- Run processing algorithms via `processing.run("native:algorithm", params, context=context, feedback=feedback)`.

### Key thresholds (aligned with pff_4.js defaults)

```
buffer_aoi          = 2000 m
roads               = 1000 m   # single layer (no major/minor split)
builtup_small       = 1000 m
builtup_large       = 2000 m
agriculture         = 1000 m
slope_threshold     = 45 degrees
max_distance        = 5100 m
refine_smooth_radius= 2000 m
refine_density      = 0.5      # 0–1, matches GEE smallPixelThreshold
```

Note: never use `-tap` in gdalwarp / `gdal:cliprasterbymasklayer` — it shifts the pixel grid origin. Use `gdal:warpreproject` with `CUTLINE` + `CROP_TO_CUTLINE` + explicit `TARGET_RESOLUTION` instead. See `utils.clip_raster_by_mask()`.

### Known documentation issues

See `docs/specs/PFF_QGIS_WORKFLOW_DOC_UPDATES.md` for 10 known ambiguities including:
- NoData vs init value handling
- Validation failure behaviour (warn vs. block)
- Slope threshold placement in the tier logic
- Distance cache invalidation rules

When modifying the plugin, check these documents for context:
- `planning/tasks_260417_organised.md` — current task backlog and open questions (check first)
- `docs/QGIS_Workflow_Ann_Rotich_V0.md` — Ann Rotich's canonical technical workflow (fallback when plugin has bugs, or for users who prefer manual QGIS steps)
- `docs/PFF_QGIS_Workshop_Guide_DRAFT.md` — end-user workshop guide
- `docs/specs/PFF_QGIS_PROCESSING_TOOL_SPEC.md` — input/output definitions
- `docs/specs/PFF_QGIS_WORKFLOW_AI_REFERENCE.md` — conceptual workflow description
- `docs/specs/PFF_QGIS_PYTHON_PSEUDOCODE.md` — pseudocode for code generation
- `docs/specs/PFF_QGIS_AUTOMATION_RECOMMENDATIONS.md` — architecture recommendations
- `docs/specs/PFF_QGIS_WORKFLOW_DOC_UPDATES.md` — known ambiguities from earlier specs

---

## 3. Data Preprocessing (`preprocessing/`)

Jupyter notebooks for extracting and formatting input data that feeds into the GEE app or QGIS plugin:
- `preprocessing/osm_local/` — pyosmium-based local PBF extraction (see its own README for Conda setup)
- `preprocessing/osm_online/` — online OSM queries
- `preprocessing/microsoft/` — Microsoft Road Detections (TSV → CSV with WKT)
- `preprocessing/wdb/` — World Database of navigable rivers/waterways
- `preprocessing/archive/` — superseded/experimental notebooks

### OSM data extraction

- Use `osmium` (`osmium.SimpleHandler`) to extract geometries from Geofabrik PBF files.
- Filter ways by OSM tags (highway, railway, waterway, etc.).
- Output: GeoPackages per feature type.
- Large GeoPackages are split into chunked CSVs with WKT geometry columns (for GEE upload).
- Naming convention: `{prefix}_{start_idx}_to_{end_idx}_of_{total_rows}.csv`.
- Chunk size default: 10,000 rows.

### Microsoft Roads

- Source: Microsoft Road Detections (TSV format with embedded GeoJSON).
- Parse GeoJSON column → extract coordinates and properties → CSV with WKT geometry.
- Use CSV format for GEE uploads (10 GB limit vs 2 GB for shapefiles).

### Preprocessing conventions

- **Libraries**: `osmium`, `geopandas`, `pandas`, `shapely`.
- **Geometry format**: WKT for GEE compatibility.
- **Binary classification**: 1=presence, 0=absence.
- **Large datasets**: Always chunk for manageability and upload limits.
- **Progress tracking**: Use `time.time()` for timing.
- Keep notebooks focused on a single extraction/transformation step.
- Prefer `geopandas` for vector operations; `pandas` for tabular splits.

---

## Cross-cutting conventions

- **Naming**: snake_case for variables and file names; PascalCase for classes; camelCase for GEE JS functions; UPPERCASE for constants.
- **Distance units**: Always metres (projected CRS required).
- **Area units**: Hectares (with pixel-size conversion formula where needed).
- **Validate early**: Check CRS, resolution, and binary values before any processing step.
- **Modular design**: Each tool/algorithm should work independently or as part of a sequence.
- **No overengineering**: Keep solutions minimal and targeted.

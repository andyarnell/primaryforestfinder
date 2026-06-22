# Primary Forest Finder — QGIS Processing Tools

QGIS Processing tools that run the Primary Forest Finder workflow on **local data** — the desktop counterpart of the [GEE app](https://github.com/andyarnell/primaryforestfinder). Uses only native QGIS + GDAL algorithms (no SAGA/GRASS). **Beta** — actively being tested and updated.

## Install & open

1. Download the latest zip from [`../dist/`](../dist/) and install via QGIS **Plugins → Manage and Install Plugins → Install from ZIP**; enable **Primary Forest Finder** (the *Installed* tab).
2. **Open the panel** from the menu bar at the top of the QGIS window: **Plugins → Primary Forest Finder → Show PFF Panel** (or the plugin's toolbar button). The panel docks on the right.

The individual tools also appear under **Processing Toolbox → Primary Forest Finder**.

## How to run

In the panel, set your inputs and parameters and click **Run Full Workflow** — one guided run through the whole pipeline: tree cover → forest → naturally regenerating → primary forest, with human-influence buffers, protected-area and steep-slope rescues, and a connectivity refinement (plus optional area statistics and vector outputs, e.g. for [Collect Earth Online](https://collect.earth/) sampling).

The individual stages are also exposed as separate Processing algorithms, but **Run Full Workflow** in the panel is the recommended way to use the plugin.

## Inputs

Only the **forest raster** (binary 1 = forest / 0 = non-forest) is required — it sets the reference grid. All others are optional (roads, built-up, agriculture, DEM, protected areas, AOI boundary, custom disturbance layers); missing layers are skipped.

The dock's **"Treat input as"** selector aligns your tree-cover input with FRA categories (Tree cover / Forest / Naturally regenerating forest). A GEE-exported `02a_tree_cover_binary` (formerly `forest_raw`) auto-matches the forest slot.

## Outputs

Headline files land in your chosen output folder (with an ISO3 prefix when set); intermediate and cached layers nest under `intermediates/`:

- `…02c_forest.tif` — forest baseline (≈ FRA Forest)
- `…02e_naturally_regenerating_forest.tif` — when a plantations layer is supplied
- `…03c_pre_refinement_primary_forest.tif`
- `…04a_primary_forest.tif` — final result
- `…04e_anthropogenic_mask.tif` — combined buffered disturbance
- `…05a_area_statistics.csv` — when zonal stats is on
- `…06*_*.gpkg` — vector outputs, when vectorise is on
- `…run_metadata.json` — run parameters + stage timings

Main outputs auto-load into the QGIS Layers panel after a run (toggle: "Add main outputs to map").

## Datasets

The global datasets behind the workflow, with sources and citations: [`../docs/datasets_global.md`](../docs/datasets_global.md).

## Compatibility

Recommended: QGIS **3.44** (the current long-term release). Known to run on QGIS 3.28–4.0; releases after 4.0 are not yet tested. Python ≥ 3.9 · native + GDAL Processing providers only (no SAGA/GRASS). Version history: the `changelog=` field in [`metadata.txt`](metadata.txt).

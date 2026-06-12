# Primary Forest Finder — QGIS Processing Tools

A set of QGIS Processing algorithms (QGIS ≥ 3.38) that replicate the
[PFF Google Earth Engine app](https://github.com/andyarnell/primaryforestfinder)
workflow using **local data** with GDAL and native QGIS algorithms only
(no SAGA/GRASS dependency).

---

## Tools

All tools appear under **Processing Toolbox → Primary Forest Finder**.

| # | Tool | Purpose |
|---|------|---------|
| 1 | **Validate Inputs** | Check CRS, resolution & binary values before processing |
| 2 | **Prepare Datasets** | Reproject, buffer AOI, clip, rasterise vectors, align grids |
| 3a | **Distance Surfaces** | Compute proximity rasters (cached — run once) |
| 3b | **Build Anthropogenic Mask** | Apply distance thresholds → combined mask (re‑run with different thresholds instantly) |
| 4 | **Run Primary Forest Finder** | Three‑tier logic (undisturbed / steep / protected) → candidate layer |
| 5 | **Refine Output** | Two optional steps: (a) neighbourhood density filter (matches GEE tool); (b) minimum patch size filter via `gdal:sieve`. Either or both. |
| 6 | **Zonal Statistics** | Per-zone area totals (kha) for primary / pre-connectivity / forest input rasters. Optional integer YEAR column for time-series stitching. |
| 7 | **Vectorize PFF output** | Polygonise binary/coded raster + optional Douglas-Peucker simplify + dissolved multipart. Pixel-value selector accepts comma-separated list (e.g. `1,2,3` for combined coded raster). Dissolved-multipart output is suitable as a sampling-area boundary for validation tools such as [Collect Earth Online](https://collect.earth/). |
| — | **Run Full Workflow** | Chains all steps in one click with all parameters exposed. Also includes optional vectorise stage (Stage 7) under Advanced parameters with primary / forest selection + nesting (cut primary out of forest, ideal CEO stratification format). |

### Typical workflow

```
1. Validate Inputs
2. Prepare Datasets
3a. Distance Surfaces            ← expensive, cached
3b. Build Anthropogenic Mask     ← fast, re‑run with new thresholds
4. Run Primary Forest Finder
5. Refine Output                  ← (a) neighbourhood density, (b) min patch size
6. Zonal Statistics               ← optional area totals (kha) per zone
7. Vectorize PFF output           ← optional polygonise / dissolve for CEO sampling
```

Or use **Run Full Workflow** to execute everything (Stages 1-7) in one click.

For repeated runs while tuning thresholds, leave **Reuse preprocessing/*.tif cache**
ticked (default) — anthro reprojection is skipped when an aligned cache from
a prior run exists, saving minutes per re-run on national-scale data.

---

## Parameters (defaults from the spec)

| Parameter | Default |
|-----------|---------|
| AOI buffer distance | 2 000 m |
| Roads buffer | 1 000 m |
| Built-up (small) buffer | 1 000 m |
| Built-up (large) buffer | 2 000 m |
| Agriculture buffer | 1 000 m |
| Slope threshold | 45° |
| Max distance compute | 5 100 m |
| Refine Step (a): neighbourhood radius | 2 000 m (0 = skip step) |
| Refine Step (a): density threshold | 0.5 |
| Refine Step (b): minimum patch area | 0 ha (set > 0 to enable raster sieve) |
| Vectorize: simplify tolerance | 0 m (0 = no simplify) |

All buffer thresholds are adjustable via sliders. Distance surfaces are
cached so that changing thresholds does **not** recompute them.

---

## Required inputs

| Dataset | Type | Notes |
|---------|------|-------|
| Forest extent | Raster | Binary (1=forest, 0=non‑forest) — used as **reference grid** |
| Roads | Vector | Single layer (or raster override) |
| Built‑up areas (small) | Vector / Raster | Small settlements |
| Built‑up areas (large) | Raster | Dense urban (optional) |
| Agriculture | Vector | Cropland extent |
| DEM | Raster | Used to derive slope |
| Protected areas | Vector | WDPA or national equivalent |
| AOI boundary | Vector | Defines area of interest |
| Custom disturbance 1/2/3 | Raster (binary) | Optional, FlagAdvanced. User-labelled human-use layers (e.g. pipelines, mines, lights at night). Each slot has its own buffer distance. |

All inputs are optional except the forest raster. The tool will skip
layers that are not provided.

---

## Installation

1. Copy the `pff_qgis_tools` folder into your QGIS plugins directory:
   - **Windows:** `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
   - **macOS:** `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
   - **Linux:** `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`

2. Restart QGIS.

3. Enable **Primary Forest Finder** in *Plugins → Manage and Install Plugins → Installed*.

4. The tools appear under **Processing Toolbox → Primary Forest Finder**.

---

## Development (editing the plugin)

The repo and the QGIS **installed** plugin are **separate copies** — editing
files here does **not** change what QGIS runs. After any edit:

1. **Sync** the repo into the installed plugin folder:
   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\sync_plugin_to_qgis.ps1
   ```
   The script first **fast-forward pulls** the local repo if it's behind GitHub
   (so a remotely-merged change isn't missed — skipped if the tree is dirty or
   diverged, and with `-NoPull`), mirrors `pff_qgis_tools/` into the install
   folder, and refreshes the `pff_qgis_tools.zip` timestamp companion next to it
   (`-NoZip` to skip; build the zip first with `build_plugin_zip.ps1`). Defaults
   to the `default` profile under `%APPDATA%`; use `-Profile <name>` or
   `-Dest <path>` to target another. macOS/Linux: copy `pff_qgis_tools/` into the
   plugins path above by hand.
2. **Reload** in QGIS: *Plugins → Plugin Reloader → Reload "Primary Forest
   Finder"* — no restart needed. The dock header version (read from
   `FullWorkflowAlgorithm.PFF_VERSION`) should then match `metadata.txt`.

If the dock still shows the old version, the sync didn't reach the folder QGIS
loads from — check the profile/path.

To build the distributable zip, see [`../dist/README.md`](../dist/README.md)
(`tools\build_plugin_zip.ps1` — do **not** use `Compress-Archive`).

---

## Outputs

The Full Workflow produces this folder layout (headlines at top, everything else nested in `intermediates/`):

```
OUT/                                     (OUT = your chosen output folder; ISO3 prefix when set)
  [ISO3_]qgis_02c_forest.tif             ← HEADLINE (≈ FRA Forest baseline -- the
                                            harmonised forest layer used downstream;
                                            FRA-strict when "Refine to forest" is
                                            on with OLTC raster supplied, else
                                            thresholded tree cover)
  [ISO3_]qgis_02e_naturally_regenerating_forest.tif
                                         ← HEADLINE (≈ FRA Naturally Regenerating
                                            Forest, if plantations input supplied)
  [ISO3_]qgis_03c_pre_refinement_primary_forest.tif
                                         ← HEADLINE (forest after disturbance buffers
                                            + protection rescues; output of Step 03
                                            tier logic, input to Step 04 viability)
  [ISO3_]qgis_03d_combined_coded_raster.tif
                                         ← HEADLINE (only if ticked; tier-logic debug)
  [ISO3_]qgis_04a_primary_forest.tif     ← HEADLINE (final result -- after Step 04
                                            ecological viability filter)
  [ISO3_]qgis_04e_anthropogenic_mask.tif ← HEADLINE (combined buffered disturbance)
  [ISO3_]qgis_05a_area_statistics.csv    ← HEADLINE (if zonal stats ticked)
  [ISO3_]qgis_05b_area_statistics_by_zone.shp (+sidecars)
  [ISO3_]qgis_run_metadata.json          ← HEADLINE (run parameters + stage timings)

  [ISO3_]qgis_06a_primary_forest_vector.gpkg
                                         ← HEADLINE (Stage 7 vectorise, if ticked)
  [ISO3_]qgis_06b_primary_forest_dissolved.gpkg
                                         ← HEADLINE (Stage 7, sampling boundary)
  [ISO3_]qgis_06c_<forest>_vector.gpkg   ← HEADLINE (Stage 7, if forest also ticked;
                                            <forest> = naturally_regenerating_forest
                                            if refined, else forest)
  [ISO3_]qgis_06d_<forest>_dissolved.gpkg

  intermediates/
    tier1_undisturbed.tif                ← tier logic byproducts
    tier2_steep.tif
    tier3_protected.tif
    forest_inside_buffers.tif
    steep_slope.tif, gentle_slope.tif
    refine_step_a_neighbourhood.tif      ← (only when both refine steps run)
    refine_step_b_sieve_unmasked.tif     ← (only when refine step b runs)

    preprocessing/                       ← reprojected + aligned inputs (reusable)
      forest.tif
      roads.tif, builtup_small.tif, builtup_large.tif, agriculture.tif
      plantations.tif, protected.tif
      dem.tif, slope.tif
      custom_1.tif, custom_2.tif, custom_3.tif  ← (if custom slots provided)

    distances/                           ← cached distance surfaces
      dist_roads.tif, dist_builtup.tif, dist_builtup_large.tif,
      dist_agriculture.tif
      dist_custom_1.tif, ...             ← (if custom slots provided)

    _vectorize/                          ← vectorise stage scratch
    zonal_work/                          ← zonal stats temporary workspace
```

Top-level filenames follow the Option D schema (see
[`docs/specs/PFF_NAMING_CONVENTION.md`](../docs/specs/PFF_NAMING_CONVENTION.md)).
Tier raster names match the canonical `pff_4.js` naming: `tier1_undisturbed`,
`tier2_steep`, `tier3_protected`. Vector outputs use `_vector` / `_dissolved`
suffixes. Forest vector naming carries the plantation-refinement state
(`naturally_regenerating_forest_*` if refined, `forest_*` otherwise).

When the **Add main outputs to map** option is ticked (default ON), Primary
forest, Pre-connectivity forest, Forest, and Naturally regenerating forest
(when produced) are auto-loaded into the QGIS Layers panel after the run
completes — so the user can compare the FRA hierarchy visually.

---

## Compatibility

- QGIS ≥ 3.38
- Uses only `native:` and `gdal:` Processing providers (no SAGA/GRASS)
- Python ≥ 3.9 (ships with QGIS 3.38)

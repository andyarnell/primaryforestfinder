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
| 5 | **Refine Output** | Neighbourhood density filter (matches GEE tool) |
| — | **Run Full Workflow** | Chains all steps in one click with all parameters exposed |

### Typical workflow

```
1. Validate Inputs
2. Prepare Datasets
3a. Distance Surfaces            ← expensive, cached
3b. Build Anthropogenic Mask     ← fast, re‑run with new thresholds
4. Run Primary Forest Finder
5. Refine Output
```

Or use **Run Full Workflow** to execute everything at once.

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
| Refine: neighbourhood radius | 2 000 m |
| Refine: density threshold | 0.5 |

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

## Outputs

The Full Workflow produces this folder layout (headlines at top, everything else nested in `intermediates/`):

```
<out>/
  primary_forest.tif           ← HEADLINE (final result)
  pre_connectivity_forest.tif  ← HEADLINE (combined tiers, before refine)
  forest_natreg.tif            ← HEADLINE (FRA naturally regenerating forest,
                                  if plantations input supplied)
  anthropogenic_mask.tif       ← HEADLINE (combined buffered disturbance)
  combined_coded_raster.tif    ← HEADLINE (only if ticked)
  zonal_statistics.csv         ← HEADLINE (if zonal stats ticked)
  zonal_statistics.shp (+sidecars)
  run_metadata.json            ← HEADLINE (run parameters record)

  intermediates/
    tier1_undisturbed.tif         ← tier logic byproducts
    tier2_steep.tif
    tier3_protected.tif
    forest_inside_buffers.tif
    steep_slope.tif, gentle_slope.tif

    prepared/                     ← reprojected + aligned inputs (reusable)
      forest.tif
      roads.tif, builtup_small.tif, builtup_large.tif, agriculture.tif
      plantations.tif, protected.tif
      dem.tif, slope.tif

    distances/                    ← cached distance surfaces
      dist_roads.tif, dist_builtup.tif, dist_builtup_large.tif, dist_agriculture.tif

    zonal_work/                   ← zonal stats temporary workspace
```

Tier raster names match the canonical pff_4.js naming: `tier1_undisturbed`, `tier2_steep`, `tier3_protected`.

---

## Compatibility

- QGIS ≥ 3.38
- Uses only `native:` and `gdal:` Processing providers (no SAGA/GRASS)
- Python ≥ 3.9 (ships with QGIS 3.38)

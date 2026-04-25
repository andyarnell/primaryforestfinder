# pFF_4 vs QGIS Plugin — Workflow Comparison

## 1. Processing Flow

| Stage | pFF_4 (GEE) | QGIS Plugin |
|-------|-------------|-------------|
| Input selection | Country + year dropdown; forest dataset choice (Hansen/GLAD/Agreement/Union/Custom) | User provides raster/vector layers directly |
| Data prep | Internal GEE datasets; raster-based country mask (GAUL 2024) | Reproject + rasterise + align to reference grid |
| Distance surfaces | `fastDistanceTransform` or `cumulativeCost`; cached in-memory per year | `gdal:proximity`; cached on disk, validated by grid dimensions |
| Anthropogenic mask | `ee.ImageCollection.reduce(anyNonZero)` | `np.maximum()` over thresholded arrays |
| Primary forest tiers | Tier 1 (outside buffers), Tier 2 (steep slope), Tier 3 (protected gentle slope) | Same three-tier logic |
| Connectivity filter | `reduceNeighborhood()` with circular kernel | Custom `_circular_focal_mean_fast()` via integral image |
| Zonal statistics | `reduceRegions()` on 50 km hex grid; CSV export with full parameter metadata | **Not implemented** |

## 2. Exports

### pFF_4 exports (per year)

| Export name pattern | Content |
|---|---|
| `0_aoi_<country>_vector` | Country boundary shapefile |
| `1_forest_<year>_<scale>` | Forest extent |
| `1_hansen_treecover2000_raw_<scale>` | Raw Hansen 2000 treecover |
| `1_hansen_lossyear_raw_<scale>` | Raw Hansen loss year |
| `1_glad_tree_height_m_<year>_<scale>` | GLAD tree height |
| `2_roads_<year>_<scale>` | Roads binary |
| `2_builtup_small_<year>_<scale>` | Built-up small binary |
| `2_builtup_large_<year>_<scale>` | Built-up large binary |
| `2_agriculture_<year>_<scale>` | Agriculture binary |
| `3_protection_legal_<scale>` | WDPA raster |
| `3_protection_legal_unfilt_vector` | WDPA unfiltered shapefile |
| `3_protection_natural_dem_<scale>` | ALOS DEM (Int16) |
| `4_pre_connectivity_forest_<year>_<scale>` | Combined tiers before filtering |
| `5_primary_forest_<year>_<scale>` | Final primary forest |

### QGIS plugin exports

| File | Content |
|---|---|
| `prepared/forest_aligned.tif` | Reference grid forest |
| `prepared/roads.tif` | Rasterised roads |
| `prepared/builtup_small.tif` | Rasterised built-up small |
| `prepared/builtup_large.tif` | Rasterised built-up large |
| `prepared/agriculture.tif` | Rasterised agriculture |
| `prepared/protected.tif` | Rasterised protected areas |
| `prepared/dem_aligned.tif` | Aligned DEM |
| `distances/dist_roads.tif` | Distance to roads |
| `distances/dist_builtup.tif` | Distance to built-up |
| `distances/dist_builtup_large.tif` | Distance to large built-up |
| `distances/dist_agriculture.tif` | Distance to agriculture |
| `anthropogenic_mask.tif` | Combined binary mask |
| `primary_candidate.tif` | Pre-refinement primary forest |
| `primary_forest_final.tif` | Final primary forest |
| (intermediates if enabled) `forest_undisturbed.tif`, `forest_anthropogenic.tif`, `steep_slope.tif`, `gentle_slope.tif`, `forest_anthro_steep.tif`, `forest_anthro_protected.tif`, `slope.tif` | Tier intermediates |

### Mismatches

- **Roads vector export**: pFF_4 exports roads as binary raster; plugin does not export the original vector
- **DEM**: pFF_4 exports DEM; plugin saves `dem_aligned.tif` in prepared dir but not as a named output
- **Slope**: pFF_4 does not export slope; plugin saves `slope.tif` only as intermediate
- **Protected areas vector**: pFF_4 exports WDPA as shapefile; plugin does not export vectors
- **Zonal stats CSV**: pFF_4 exports area statistics with parameter metadata; plugin has nothing equivalent
- **Combined coded raster**: neither workflow produces one
- **No selective export control** in either workflow

## 3. Naming Conventions

| Concept | pFF_4 | QGIS plugin |
|---------|-------|-------------|
| Input forest | `1_forest_<year>_<scale>` | `forest_aligned.tif` |
| Pre-connectivity | `4_pre_connectivity_forest_<year>_<scale>` | `primary_candidate.tif` |
| Final primary forest | `5_primary_forest_<year>_<scale>` | `primary_forest_final.tif` |
| Roads | `2_roads_<year>_<scale>` | `roads.tif` |
| Built-up small | `2_builtup_small_<year>_<scale>` | `builtup_small.tif` |
| Built-up large | `2_builtup_large_<year>_<scale>` | `builtup_large.tif` |
| Agriculture | `2_agriculture_<year>_<scale>` | `agriculture.tif` |
| Protected areas | `3_protection_legal_<scale>` | `protected.tif` |
| DEM | `3_protection_natural_dem_<scale>` | `dem_aligned.tif` |
| Slope | (not exported) | `slope.tif` (intermediate only) |
| Anthropogenic mask | (not exported separately) | `anthropogenic_mask.tif` |

Plugin naming is simpler (no year/scale suffixes) but diverges from pFF_4 conventions.

## 4. DEM / Slope Handling

| Aspect | pFF_4 | QGIS plugin |
|--------|-------|-------------|
| DEM source | ALOS AW3D30 v3.2 (built-in) | User-provided |
| Slope computation | `ee.Terrain.slope()` | `gdal:slope` |
| Custom slope | Optional textbox for national slope raster | Optional pre-computed slope raster input |
| Default threshold | 45 degrees | 45 degrees |
| DEM export | Yes (Int16) | Only in prepared dir |
| Slope export | No | Only as intermediate |

## 5. Projection / CRS

| Aspect | pFF_4 | QGIS plugin |
|--------|-------|-------------|
| Working CRS | EPSG:4326 (WGS84) | User-specified projected CRS |
| Export CRS | EPSG:4326 | Target projected CRS |
| Auto UTM detection | No | No |
| Distance units | Metres (via pixelArea) | Metres (projected CRS) |

Neither workflow auto-detects an appropriate UTM zone.

## 6. Validation

| Aspect | pFF_4 | QGIS plugin |
|--------|-------|-------------|
| Dedicated tool | No (implicit checks only) | Yes — Tool 1 with report |
| CRS check | No | Yes — projected CRS required |
| Resolution check | No | Yes — DEM vs forest |
| Binary check | No | Yes — forest raster 0/1 |
| Vector check | No | No |
| Raster output check | No | No |
| Combined raster check | N/A | N/A |
| Zonal stats check | N/A | N/A |

## 7. Zonal Statistics

pFF_4 provides:
- `reduceRegions()` on a 50 km hex grid
- On-the-fly display in kha
- CSV export with full parameter metadata (country, year, thresholds, IUCN categories, etc.)
- FRA 2025 comparison values inline

QGIS plugin: **no zonal statistics functionality**.

## 8. Priority Mismatches

1. **Zonal statistics missing from plugin** — high priority, core analytical output
2. **No selective export controls** — causes clutter in Tasks tab
3. **Naming divergence** — confuses cross-workflow comparison
4. **No auto UTM projection** — users must manually select CRS
5. **DEM/slope not consistently exportable** — minor but should be aligned
6. **No combined coded raster** — useful for validation and communication
7. **Validation does not cover new output types** — needs updating after other changes
8. **Vector inputs not exportable** — roads, protected areas cannot be re-exported

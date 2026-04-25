# Additional Alignment Recommendations

## Changes implemented in v0.8.0

1. **Selective export controls** -- 11 tick boxes for granular control over which layers are exported. Reduces Tasks tab clutter and processing time.

2. **Missing vector exports** -- Roads, buffered roads, protected areas, built-up, and agriculture vectors can now be exported as reprojected GeoPackages.

3. **DEM and slope exports** -- Both are now independently exportable via tick boxes. Slope is computed from DEM when needed and saved regardless of intermediate-save setting.

4. **Auto UTM projection** -- New "Auto UTM" tick box detects the appropriate UTM zone from the AOI or forest raster centroid. Manual CRS selection is still available.

5. **Naming conventions aligned** -- Plugin output names now match pFF_4:
   - `primary_candidate.tif` -> `pre_connectivity_forest.tif`
   - `primary_forest_final.tif` -> `primary_forest_candidate.tif`
   - Exported vectors use `roads_vector.gpkg`, `protected_areas_vector.gpkg` etc.

6. **Combined coded raster** -- Optional single-band raster with class values:
   - 0 = no forest
   - 1 = input forest
   - 2 = pre-connectivity forest
   - 3 = primary forest candidate

7. **Zonal statistics** -- New Tool 6 computes per-zone area statistics (ha, sq km, percent) for all raster outputs. CSV and vector-attribute output. Field names match pFF_4.

8. **Validation updated** -- Tool 1 now validates output rasters (binary check, combined raster 0-3 range), exported vectors (folder check), and zonal statistics CSV.

## Further recommendations

### Buffering methods
- pFF_4 offers two distance methods: `fastDistanceTransform` (kernel-based, fast, approximate) and `cumulativeCost` (Dijkstra, exact). The plugin uses only `gdal:proximity` (exact). Consider adding a fast mode using `gdal_proximity` with lower max_distance for quick previews.

### Export defaults
- pFF_4 exports everything by default. The plugin now defaults to exporting only the final and pre-connectivity layers. Consider whether defaults should match pFF_4 more closely for users who expect the same outputs.

### CRS assumptions
- pFF_4 works entirely in EPSG:4326 and uses `ee.Image.pixelArea()` to handle area calculations in geographic coordinates. The plugin requires a projected CRS. This is a fundamental difference that cannot be fully aligned without significant rearchitecture on either side. Document this clearly for users who switch between workflows.

### Intermediate layer generation
- pFF_4 does not save intermediates — they exist only as GEE computation graph nodes. The plugin writes intermediates to disk. Consider making the intermediate directory a `tempfile.mkdtemp()` when `SAVE_INTERMEDIATES` is off, so files are cleaned up automatically.

### Validation logic
- pFF_4 has no dedicated validation. The plugin's validation is more rigorous. Consider adding a quick validation pass at the start of the Full Workflow (before any processing) that fails fast on obvious problems like missing required inputs or geographic CRS.

### Naming patterns
- pFF_4 uses numbered prefixes (`1_`, `2_`, `3_`, `4_`, `5_`) to indicate processing stage. The plugin does not use numbered prefixes. Consider adding optional numbered prefixes to exports for users who want to match pFF_4 exactly.

### Zonal statistics structure
- pFF_4 uses a 50 km hex grid generated from the country boundary. The plugin accepts any user-provided zone layer. For closer alignment, consider adding a "Generate hex grid" option that creates a hex grid from the AOI, matching pFF_4's approach.
- pFF_4 exports include full parameter metadata in the CSV (thresholds, IUCN categories, etc.). Consider adding a metadata section or companion file to the zonal statistics output.

### Distance surface caching
- pFF_4 caches distance images in memory per year. The plugin caches on disk. The disk cache is more robust but can accumulate stale files. Consider adding a "Clear cache" button or automatic cache cleanup when input layers change.

### Custom national assets
- pFF_4 supports loading custom national road/built-up/agriculture/protected area assets via textbox URLs pointing to GEE assets. The plugin accepts these as standard QGIS layers. No alignment needed, but document the equivalence for users.

# OSM roads dataset — preparation and provenance

How the global OSM roads GEE assets (vector FeatureCollections + rasterized image) were produced for the Primary Forest Finder work. Compiled from the preprocessing notebooks in [preprocessing/osm_local/](../preprocessing/osm_local/), the GEE asset descriptions, and the module code in [modules/timeSeriesAnthro.js](../modules/timeSeriesAnthro.js). Consolidates and supersedes the raw upload notes previously kept in `docs/osm_roads_prep` (no extension).

## Outputs

| Output | GEE location | Notes |
|---|---|---|
| Vector roads (34 FeatureCollections; the 34th, an Asia chunk, ingested 2026-09-15) | `projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/{region}_{start}_to_{end}_of_{total}` | Regional CSV chunks ingested as tables; merged at query time by `getOsmRoadsAll()` |
| Rasterized roads | `projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/roadsAllImageOSM` | Integer image, Hansen grid (EPSG:4326, 0.00025° ≈ 30 m at equator), 1,440,000 × 548,000 px (80°N–57°S), ~9.3 GB, asset last updated 2025-06-09. **Built from only 33 of the 34 vector chunks** — see Known gaps |

## Processing chain

1. **Download** — Regional PBF extracts from Geofabrik (<https://download.geofabrik.de/>), accessed approx. 21 May 2025. The Europe regional file was too large to process in memory, so Europe was re-downloaded at country level (approx. 29 May 2025) and recombined later at the CSV stage.

2. **Extraction** ([osm_local_data_1_extract_flexible.ipynb](../preprocessing/osm_local/osm_local_data_1_extract_flexible.ipynb)) — Local parsing with `pyosmium` (`osmium.SimpleHandler`; Conda environment required — see the [osm_local README](../preprocessing/osm_local/README.md)). All OSM *ways* carrying a `highway` tag were kept — any `highway` value, so paths, tracks, footways and cycleways are included alongside vehicle roads (deliberate: still relevant to primary forest work). Ways with fewer than 2 valid nodes were dropped. Attributes retained per way: `id`, `name`, `highway`, `surface` (plus LineString geometry, EPSG:4326). Keeping all tags was attempted but failed — GeoDataFrame lower-casing of duplicate tag names in different cases produced duplicate-column errors — so only these few were ported. Output: one `{region-or-country}_highways.gpkg` per input PBF. (The same notebook also supports railways, waterways, boat access and ferry routes extracts.)

3. **GeoPackage → CSV** ([osm_local_data_2a_gpkg_to_csvs.ipynb](../preprocessing/osm_local/osm_local_data_2a_gpkg_to_csvs.ipynb)) — Each GeoPackage split into chunked CSVs with geometry as WKT, named `{prefix}_{start_idx}_to_{end_idx}_of_{total_rows}.csv`. CSV was chosen over shapefile because it allows larger files and has no DBF column-header limitations.

4. **Recombine** ([osm_local_data_2b_combine_csvs_small_to_large.ipynb](../preprocessing/osm_local/osm_local_data_2b_combine_csvs_small_to_large.ipynb)) — Country/region CSVs combined into larger regional chunks (target 10,000,000 rows per chunk), keeping each upload file under GEE's ~10 GB CSV limit.

5. **GEE ingestion** — Chunks uploaded as FeatureCollection assets under `.../crosscutting/infrastructure/roads_osm/`. Feature counts per region (from asset names):

   | Region | Chunks | Features |
   |---|---|---|
   | africa | 3 | 20,329,501 |
   | antartica *(sic)* | 1 | 1,102 |
   | asia | 7 | 62,409,033 (one chunk ingested late — see gap below) |
   | australia_oceania | 1 | 4,176,086 |
   | central_america | 1 | 2,174,319 |
   | europe | 13 | 96,258,629 |
   | north_america | 6 | 55,568,828 |
   | south_america | 2 | 13,549,774 |

6. **Merge and filter** — `getOsmRoadsAll()` in [modules/timeSeriesAnthro.js](../modules/timeSeriesAnthro.js) merges the 34 assets into one FeatureCollection and removes features with `highway` = `proposed` or `planned` (these values were found to be erroneous during ingestion). The asset description records that the same proposed/planned filter was applied before rasterization.

7. **Rasterization** — The combined, filtered collection was rasterized (constant value 1 via `reduceToImage` with `ee.Reducer.first()`, `int8`) and exported to asset on the Hansen `UMD/hansen/global_forest_change_2023_v1_11` projection and nominal scale (EPSG:4326, 0.00025° per pixel ≈ 30 m at the equator), region 180°W–180°E / 57°S–80°N, as `roadsAllImageOSM_v0` (since renamed `roadsAllImageOSM`). Original export script recovered from the Code Editor 2026-09-15: [gee_scripts/old_export_osm_roads_raster_v0.js](../gee_scripts/old_export_osm_roads_raster_v0.js). Re-export script (34 chunks, pixel-aligned via explicit `crsTransform`): [gee_scripts/export_osm_roads_raster.js](../gee_scripts/export_osm_roads_raster.js).

## Rasterization method and diagonal connectivity (v2 onward)

The v1 raster (`roadsAllImageOSM`, June 2025) was produced with `reduceToImage`,
which marks **every cell a line touches** (all-touched). As of 2026-09 that
method no longer completes at global scale in Earth Engine — see "Known gaps"
below — so the v2 re-export uses `ee.Image(0).paint(fc, 1)`, which draws a
~1-pixel line and completes in hours rather than weeks.

**Consequence for connectivity analyses.** A 1-px line is 8-connected but not
4-connected: where a road runs diagonally, the gap cells either side are
diagonally adjacent, so an 8-connected path (least-cost path, cumulative-cost
spread, fragmentation/barrier analysis) can cross the road. Measured on a 1°
box in Thailand at full resolution:

| Raster | road px | diagonal leak points |
|---|---|---|
| `paint` (v2 method) | 622,337 | 186,609 (30.0%) |
| `paint` + seal (below) | 987,572 | 1,724 (0.17%) |
| `reduceToImage` (v1 method) | 817,747 | 2,344 (0.29%) |

**This does not affect PFF**, which only ever uses roads as a *source* for
distance buffering (1000–1500 m) via `makeDistanceBuffer` — never as a barrier.
Buffers radiate from every road pixel independently, so diagonal gaps cannot
leak.

**If you are using this layer as a barrier or resistance surface, seal it
first.** The seal is a tile-local focal operation (1-pixel halo), cheap to run
on the fly over an AOI — there is no need for a separate sealed asset:

```javascript
// Fill any gap cell lying between two diagonally-adjacent road pixels,
// restoring 4-connectivity. Input/output: binary 1 = road, unmasked.
function sealDiagonals(img) {
  var n = img.neighborhoodToBands(ee.Kernel.square(1));
  var c = n.select('.*_0_0');
  var W = n.select('.*_-1_0'),  E = n.select('.*_1_0');
  var N = n.select('.*_0_1'),   S = n.select('.*_0_-1');
  var NW = n.select('.*_-1_1'), NE = n.select('.*_1_1');
  var SW = n.select('.*_-1_-1'),SE = n.select('.*_1_-1');
  var fill = c.not().and(
      W.and(N).and(NW.not())
    .or(E.and(N).and(NE.not()))
    .or(W.and(S).and(SW.not()))
    .or(E.and(S).and(SE.not())));
  return c.or(fill).rename('constant').toInt8();
}
```

Note the sealed result is **not** pixel-identical to the v1 all-touched raster:
it holds ~25% more pixels (it fills both gap cells at each pinch) and misses ~4%
that all-touched marks. It is slightly *better* sealed (0.17% vs 0.29% residual
leaks). For pixel-counting or road-length statistics the two are not
interchangeable; for buffering or barrier use they are.

## Known gaps and caveats

- **Missing Asia chunk (vector asset ingested 2026-09-15; raster NOT yet re-exported — `roadsAllImageOSM` still lacks it as of 2026-11-19)** — the chunk covering Asia rows 20,000,000–30,000,000 was produced locally (`asia_20000000_to_30000000_of_62409033.csv`, 3.2 GB, 29 May 2025, in the OneDrive `work_in_progress/roads/osm/osm_regional_250521/geo_csvs/` folder) but was never ingested into GEE.

  **Where to get the complete set.** The missing vector file is now the GEE FeatureCollection `projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/asia_20000000_to_30000000_of_62409033` (ingested 2026-09-15, ~4 GB). `getOsmRoadsAll(aoi)` includes it, so per-AOI **vector** exports are complete. The **raster** used in the analysis (`roadsMosaicStatic()` → `roadsAllImageOSM`) is not: the global 30 m re-export ([gee_scripts/export_osm_roads_raster.js](../gee_scripts/export_osm_roads_raster.js) and the `_tiled` / `_banded` variants) has not completed on the current GEE quota tier. Until it does, patch the raster over your AOI by painting the missing chunk on top:

  ```javascript
  var gap = ee.FeatureCollection('projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/asia_20000000_to_30000000_of_62409033')
      .filterBounds(aoi)
      .filter(ee.Filter.inList('highway', ['proposed', 'planned']).not());
  var roadsComplete = roadsMosaicStatic().unmask(0)
      .max(ee.Image(0).paint(gap, 1)).toInt8();
  ```

  `paint` draws ~1-px lines rather than all-touched cells — fine for distance buffering (see "Rasterization method" above before using it as a barrier). Sharing: public (`all_users_can_read`) since 2026-11-19, like the other 33 chunks — before that, accounts other than the owner (including the published app) could not read it.

  **Measured impact (2026-09-29, 1°×1° Thailand box 99–100°E / 16–17°N, full res):** the chunk *more than doubles* road pixels locally — 398,313 px from 33 chunks vs 817,746 px with the 34th (+105%). Impact is far larger than the chunk's 4%-of-global feature share implies, because chunks are ordered by OSM way ID (≈ creation date), so the missing slice is roads mapped ~2018–19 — a large share of the network in rapidly-mapped rural Asia. Impact is spatially uneven (a smaller 0.3° box in the same area showed +30%).

  **The existing raster is otherwise faithful.** A fresh 33-chunk render reproduces `roadsAllImageOSM` to within 2 px of 398,311 (0.0005%), and `old_roadsAllImageOSM` is identical to it — so the original export had no defect beyond the missing input. Consequence: PFF runs over affected parts of Asia used a locally ~50%-complete road layer, under-buffering disturbance and therefore **over-estimating primary forest** there. Verified 2026-09-15: no such asset exists (`earthengine ls` + direct `asset info`), and way IDs sampled from the CSV (e.g. 524463428, 720429220) match zero features in any of the six existing Asia assets. The rows are ordered by OSM way ID (524,463,428 → 720,429,220), so the missing ~10 M features are not one region — sampled vertices span 35°E–144°E / 10°S–65°N (Iran, Yemen, India, Thailand, Indonesia, Japan, Pakistan…), i.e. a diffuse Asia-wide thinning rather than a regional hole (approximately the slice of ways created ~2018–2019, since OSM way IDs are sequential). Spot checks (11 sampled roads) show `roadsAllImageOSM` also lacks pixels at 6 of them where no other road is within 60 m — the raster was built from the same incomplete merge. **Fix**: (1) upload the local CSV as the missing asset — done 2026-09-15; (2) add it to `getOsmRoadsAll()` — done; (3) share it publicly — done 2026-11-19; (4) re-export the global raster — outstanding (export has not completed).
- **No road-type differentiation** — all `highway` values are treated equally; some features are foot/bike-only and not vehicle-accessible. Buffered/distance products derived from this layer may overstate human accessibility in some regions.
- **Limited attributes** — only `id`, `name`, `highway`, `surface` were ported to the GEE vector assets; filtering on other OSM fields is not possible there.
- **OSM-only** — Congo Basin logging roads from the `wurnrt-loggingroads` project are *not* in this merge; they are handled separately by `getCongoRoadsUpToYear()` in the same module. Notable areas of forest roads are known to be missing from OSM itself in places.
- **Snapshot, not time series** — reflects OSM as of the May 2025 Geofabrik downloads.

## Intended use

- **Vector**: consumed via `getOsmRoadsAll(aoi)` (with AOI push-down filtering across the 34 child assets) — e.g. for `Export.table.toDrive` into the QGIS plugin's vector roads input slot.
- **Raster**: `roadsMosaicStatic()` returns `roadsAllImageOSM` directly (missing the late Asia chunk — see Known gaps). For time-aware raster roads the tool uses GRIP4 (`getRoadsCollection()` / `getGripRoadsForYear()`), a separate dataset.

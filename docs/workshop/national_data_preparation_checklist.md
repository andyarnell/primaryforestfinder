# National data preparation checklist

For countries bringing their own data into the **QGIS Plugin** (or as custom assets in the **GEE App**). Share with a country a couple of weeks before a workshop so inputs are ready on day one.

> Draft — created from the Day 2 data-format discussion and the participant sheets. Confirm against the plugin's processing spec (`../specs/PFF_QGIS_PROCESSING_TOOL_SPEC.md`).

---

## General rules

- **CRS:** projected, in **metres** (e.g. national UTM). Never geographic (EPSG:4326) for analysis — distances and areas need metres. The plugin can auto-suggest a UTM zone, but supplying data already in the correct national CRS avoids surprises.
- **Forest raster sets the reference grid.** Everything else is aligned to it (extent, resolution, pixel origin). Pick the forest layer deliberately.
- **Binary rasters:** `1` = presence, `0` = absence, GeoTIFF, `COMPRESS=LZW`, `TILED=YES`, `Byte` type.
- **Vectors are fine** — the plugin rasterises roads / built-up / agriculture / protected areas for you. You don't need to pre-rasterise.
- **One clean output folder per run** — avoids stale-cache and re-run errors.
- **Name files clearly and consistently** — ambiguous names caused upload confusion in the workshop.

---

## Per-input requirements

| Input | Geometry / type | CRS | Class field / codes | Required? |
|---|---|---|---|---|
| **Forest / tree cover** | Raster, binary (1 = forest) | Projected, m | — (binary) | **Required** — defines the reference grid |
| **Study-area boundary** | Vector polygon (national or sub-national) | Projected, m | — | Recommended (else uses GAUL) |
| **Roads** | Vector lines (or raster) | Projected, m | Optional class field if splitting major/minor/logging | Optional |
| **Built-up / settlements** | Vector polygons/points (or raster) | Projected, m | — | Optional |
| **Agriculture / cropland** | Vector polygons (or raster) | Projected, m | — | Optional |
| **Plantations / planted forest** | Vector polygons (or raster) | Projected, m | — | Optional — **needed to exclude rubber/acacia/etc.** |
| **Protected areas** | Vector polygons (or raster) | Projected, m | IUCN category field if filtering by category | Optional |
| **Slope / DEM** | Raster, continuous (Float32) | Projected, m | — (degrees or elevation) | Optional (for slope buffer exception) |
| **Fire / burned area** | Raster or vector | Projected, m | — | Optional (planned input) |

---

## Notes that caught people out

- **Datum consistency (Thailand).** Mixing WGS84 and a local datum (e.g. Indian 1975) across inputs can shift features. Reproject everything to one national CRS/datum first.
- **Plantations under FRA (Thailand).** If the forest layer includes managed plantations (rubber, acacia, eucalyptus), supply a plantation layer to exclude them — otherwise they appear as primary forest. Global plantation layers under-capture smallholder rubber in SE Asia.
- **Resolution and run time.** A 30 m forest raster runs ~5–10× slower than 90 m because everything aligns to it. If you don't need sub-90 m detail, resample the forest raster to 90 m first (resampling method **Mode** for binary). The human-influence buffers are ~1 km wide anyway.
- **Output rasters carry no attribute table** by design — class areas are in the statistics CSV, not the raster.

---

## Useful national datasets (examples offered at the workshop)

| Country | Examples |
|---|---|
| Bhutan | Forest management units; community forest; cultural sites; NWFP extraction sites (vector) |
| PNG | NFI plot locations; Collect Earth PNG 2019; logging concessions; protected areas; Key Biodiversity Areas |

Other countries pointed to national monitoring systems (Indonesia SIMONTANA / NFI 2.0; Lao NFMS + NFI stump data; Viet Nam NFI + national satellite monitoring; Thailand multi-agency forest data and aerial photography) — these can supply forest, boundary, road, plantation or disturbance inputs.

---

*Cross-references: input definitions → `../specs/PFF_QGIS_PROCESSING_TOOL_SPEC.md`; FAQ → `FAQ.md`.*

# PFF Global Datasets — Reference

Human-readable companion to [`datasets_global.json`](datasets_global.json) (the canonical machine-readable source — feed it to run-metadata, dataset pages, and (i) buttons).

Covers `pff_4.js` v4.16.0-beta.18 and `modules/timeSeriesAnthro.js`, checked against the code on 2026-11-19. Lists only the datasets each run actually loads; off-by-default / not-loaded datasets are recorded in the JSON only (see below) — including `rubber_sea_2020` (optional SE-Asia rubber → planted forest checkbox, added beta.18).

## How to read the status field

| Status | Meaning |
|---|---|
| `active` | Used in every default run — the only status listed individually below. |
| `optional_default_off` | Loaded in code but disabled or never folded into the default analysis. Kept in [`datasets_global.json`](datasets_global.json) only, not listed here — except the two opt-in reference overlays (FLII, FDaP), which are listed because they appear in the app's Reference panel. |
| `queued` | Referenced only in commented-out code / notes; not loaded today. Kept in [`datasets_global.json`](datasets_global.json) only, not listed here. |
| `deprecated` | Was used in a previous version; superseded. |

---

## Forest cover (binary baseline)

### Hansen Global Forest Change v1.12 — `active` (selectable forest source; default is GLAD below)
30 m global tree-cover-2000 + annual loss-year, Landsat-derived. Used when the tree-cover source is set to Hansen, Agreement or Combined extent, and for the optional raw-band export. PFF threshold default 10 % canopy; lossyear masks pixels lost up to analysisYear.
- **EE asset:** `UMD/hansen/global_forest_change_2024_v1_12`
- **Code:** `pff_4.js:505-520` (`gfcHansenTreecoverPrep`)
- **Cite:** Hansen et al. (2013) *Science* 342, 850–853. [doi:10.1126/science.1244693](https://doi.org/10.1126/science.1244693)
- **Docs:** <https://glad.umd.edu/dataset/global-forest-change>

### GLAD GLCLU 2000–2020 v2 — `active` (default forest source)
30 m global LCLU encoding tree height in metres (classes 25–48 / 125–148 → 3–26 m). PFF default ≥ 5 m.
- **EE assets:** `projects/glad/GLCLU2020/v2/LCLUC_<year>` (1990, 2000, 2005, 2010, 2015, 2020) + `projects/glad/OceanMask`
- **Code:** `pff_4.js:522-544` (`gladLulcForestPrep`)
- **Cite:** Potapov et al. (2022) *Frontiers in Remote Sensing* 3, 856903. [doi:10.3389/frsen.2022.856903](https://doi.org/10.3389/frsen.2022.856903)
- **Docs:** <https://glad.umd.edu/dataset/GLCLUC2020>

---

## Forest reference layers (visual comparison only)

Opt-in overlays: each has a checkbox in the app's Reference panel, off by default. Not used in the analysis chain.

### Forest Landscape Integrity Index (FLII) — `optional_default_off`
0–10 score per ~300 m forest pixel. PFF discretises into low / medium / high.
- **EE asset:** `users/openforisearthmap/World_EarthMap/flii_earth_20190824`
- **Code:** `pff_4.js:5517-5526`
- **Cite:** Grantham et al. (2020) *Nature Communications* 11, 5978. [doi:10.1038/s41467-020-19493-3](https://doi.org/10.1038/s41467-020-19493-3)
- **Docs:** <https://www.forestintegrity.com/>

### FDaP Forest Persistence v0 (2020) — `optional_default_off`
0–1 per-pixel score for undisturbed forest in 2020; PFF threshold 0.90.
- **EE asset:** `projects/forestdatapartnership/assets/community_forests/ForestPersistence_2020`
- **Code:** `pff_4.js:5527-5531`
- **Cite:** Forest Data Partnership / Google (2024). Community product, not yet peer-reviewed.
- **Docs:** <https://www.forestdatapartnership.org/>

---

## Administrative

### FAO GAUL 2024 (Level 0) — `active`
Country boundaries + simplified + raster derivatives for fast clipping.
- **EE assets:** `projects/sat-io/open-datasets/FAO/GAUL/GAUL_2024_L0` + custom simplified + 500 m raster
- **Code:** `pff_4.js:71-89`, `modules/gaulLut.js`
- **Cite:** FAO (2024) *Global Administrative Unit Layers (GAUL) 2024*.
- **Docs:** <https://data.apps.fao.org/catalog/dataset/global-administrative-unit-layers-gaul-2024>

---

## Protected areas

### WDPA (UNEP-WCMC) — `active`
Drives Tier 1.3 protected-area rescue (default IUCN Ia, Ib, II; min 30 yr designation). Pre-cached at startup.
- **EE asset:** `WCMC/WDPA/current/polygons`
- **Code:** `pff_4.js:136-159`
- **Cite:** UNEP-WCMC and IUCN (2026). [doi:10.34892/6fwd-af11](https://doi.org/10.34892/6fwd-af11)
- **Docs:** <https://www.protectedplanet.net/en/thematic-areas/wdpa>

---

## Terrain

### JAXA ALOS World 3D-30m DSM v3.2 — `active`
DEM for steep-slope rescue (Tier 1.2) + DEM/slope sidecar exports.
- **EE asset:** `JAXA/ALOS/AW3D30/V3_2`
- **Code:** `pff_4.js:2332-2337, 7189`
- **Cite:** Tadono et al. (2016) *Generation of the 30 m-mesh Global Digital Surface Model by ALOS PRISM*. ISPRS Archives XLI-B4, 157–162. [doi:10.5194/isprs-archives-XLI-B4-157-2016](https://doi.org/10.5194/isprs-archives-XLI-B4-157-2016) (v3 update: Takaku et al. 2020)
- **Docs:** <https://www.eorc.jaxa.jp/ALOS/en/dataset/aw3d30/aw3d30_e.htm>

---

## Built-up

### JRC GHSL — Settlement Model (SMOD) + Population (POP) P2023A — `active` (default ON)
Provides built-up small (SMOD 11–12) + built-up large (>12), masked by GHS_POP > 0.
- **EE assets:** `JRC/GHSL/P2023A/GHS_SMOD`, `JRC/GHSL/P2023A/GHS_POP`
- **Code:** `modules/timeSeriesAnthro.js:242-275`
- **Cite:** Pesaresi et al. (2024) *Int. J. Digital Earth* 17(1). [doi:10.1080/17538947.2024.2390454](https://doi.org/10.1080/17538947.2024.2390454)
- **Docs:** <https://human-settlement.emergency.copernicus.eu/>

### DLR World Settlement Footprint Evolution — `active` (default ON)
30 m annual settlement extent 1985–2015, OR'd into built-up small.
- **EE asset:** `projects/sat-io/open-datasets/WSF/WSF_EVO`
- **Code:** `modules/timeSeriesAnthro.js:381-397`
- **Cite:** Marconcini et al. (2020) *Scientific Data* 7, 242. [doi:10.1038/s41597-020-00580-5](https://doi.org/10.1038/s41597-020-00580-5)
- **Docs:** <https://geoservice.dlr.de/web/datasets/wsf_evo>

---

## Land cover / agriculture

The agriculture layer is GLAD cropland + Global Pasture Watch (cultivated) + Descals oil palm + SDPT (below). GLC_FCS30D is loaded but not folded in — see [Datasets not folded into a run](#datasets-not-folded-into-a-run).

### GLAD Cropland (Potapov) 2000–2019 — `active`
Forward-filled (cropland once present stays present). 1990 uses 2003 asset as proxy.
- **EE assets:** `users/potapovpeter/Global_cropland_<2003|2007|2011|2015|2019>`
- **Code:** `modules/timeSeriesAnthro.js:433-482, 588-638`
- **Cite:** Potapov et al. (2022) *Nature Food* 3, 19–28. [doi:10.1038/s43016-021-00429-z](https://doi.org/10.1038/s43016-021-00429-z)

### Global Pasture Watch — Annual Dominant Class of Grasslands v1 — `active`
Class 1 (cultivated) used as agriculture; class 2 (natural/semi-natural) is NOT excluded.
- **EE asset:** `projects/global-pasture-watch/assets/ggc-30m/v1/grassland_c`
- **Code:** `pff_4.js:2466-2469, 6723-6726`
- **Cite:** Parente et al. (2024) *Scientific Data* 11, 1303. [doi:10.1038/s41597-024-04139-6](https://doi.org/10.1038/s41597-024-04139-6)

---

## Plantations / tree crops

### Descals Global Oil Palm YoP (1990–2021) — `active`
Per-year palm extent from year-of-planting raster. Classified as OLTC (FRA Note 10), routed into agriculture / 02b.
- **EE asset:** `projects/ee-globaloilpalm/assets/shared/GlobalOilPalm_YoP_2021`
- **Code:** `modules/timeSeriesAnthro.js:666-695`
- **Cite:** Descals et al. (2024) *ESSD* 16, 5111–5129. [doi:10.5194/essd-16-5111-2024](https://doi.org/10.5194/essd-16-5111-2024)

### Spatial Database of Planted Trees (SDPT) v2 — `active`
Class 1 = Planted Forest (FRA-aligned, 02d); class 2 = Tree Crops (OLTC, 02b — includes rubber per SDPT, contra FRA Note 7; the optional `rubber_sea_2020` checkbox reroutes confirmed SE-Asia rubber to 02d).
- **EE asset:** `projects/sdpt-v2/assets/sdpt_v2_simpleType_v09032024_public`
- **Code:** `modules/timeSeriesAnthro.js:733-856`
- **Cite:** Richter et al. (2024) *Spatial Database of Planted Trees v2.0*. WRI Technical Note.
- **Docs:** <https://www.wri.org/research/spatial-database-planted-trees-sdpt-version-2>

---

## Roads / infrastructure

### OSM Roads (PFF custom regional merge) — `active`
Static global OSM roads collected May 2025. Used as the single roads raster for the roads buffer (the old small/large road split by GRIP4 traffic is switched off) + per-AOI vector export. **Provenance:** [`docs/osm_roads_prep.md`](osm_roads_prep.md) (full collection chain, dates, known gaps). **Scripts:** [`preprocessing/osm_local/`](../preprocessing/osm_local/README.md) (Conda + pyosmium notebooks).
- **EE assets:** `projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/roadsAllImageOSM` (raster) + 34 regional FCs (vector)
- **Code:** `modules/timeSeriesAnthro.js:1022-1116` (`getOsmRoadsAll`, vector), `1201-1244` (`roadsMosaicStatic`, raster)
- **Collection dates:** Geofabrik PBFs accessed ~2025-05-21 (rest-of-world), ~2025-05-29 (Europe by country, due to file size).
- **Caveats:** No road-class differentiation; `highway=proposed|planned` dropped.
- **⚠ Raster is missing one Asia chunk.** `roadsAllImageOSM` (June 2025) was built from 33 of the 34 vector chunks: `asia_20000000_to_30000000_of_62409033` (~10 M ways) was only uploaded on 2026-09-15, and the global raster re-export has not run yet. The gap is spread across Asia and is heavy in SE Asia (a 1° test box in Thailand holds about half its road pixels), so the analysis under-buffers roads there and over-estimates primary forest. The **vector** export is complete: `getOsmRoadsAll()` includes all 34 chunks. If you need the missing piece on its own, it is the GEE FeatureCollection `projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/asia_20000000_to_30000000_of_62409033`. To patch the raster over an AOI, see the note above `roadsMosaicStatic()` in the code or [`osm_roads_prep.md`](osm_roads_prep.md#known-gaps-and-caveats). **Status:** tracked in [issue #98](https://github.com/andyarnell/primaryforestfinder/issues/98) — if that issue is closed, the raster has been fixed.
- **Cite:** © OpenStreetMap contributors, ODbL 1.0.

---

## Datasets not folded into a run

Datasets the tool does **not** use in a run are kept only in [`datasets_global.json`](datasets_global.json), not listed individually above, so this reference stays a faithful list of what each run actually loads. Two groups (filter the JSON on `"status"`):

- **`optional_default_off`** — loaded in code but disabled or never folded into the default analysis: **GLC_FCS30D** (cropland classes are extracted in the analysis path, but the `.or()` that would add them to the agriculture layer is commented out — the noise-smoothing step was too slow — so it contributes nothing), the SE-Asia rubber + FDAP rubber 2026a checkbox, GISD30 / GISA built-up, LandScan population, FDAP palm/rubber/cocoa 2024a, GRIP4 + predicted-AADT roads, OSM Water Layer, and the PFF navigable-rivers assets.
- **`queued`** — not loaded in the current run path (commented-out code, notes, or uncalled functions): **JRC TMF Deforestation Year** (`forest_disturbances()` in `modules/timeSeriesAnthro.js` would combine it with Hansen loss, but nothing calls it — forest loss currently comes from the Hansen lossyear mask or the per-year GLAD maps), WRI SBTN Natural Lands, the European Primary Forests Database, the Tsinghua China Terrace Map, and several alternative road sources.

---

## Using these datasets in your own GEE script

The prepared human-influence, cropland, plantation and roads layers above come from one Earth Engine module, `modules/timeseriesAnthro.js`. (Tree cover, WDPA, the DEM, pasture and GAUL boundaries are loaded directly in `pff_4.js` from their public catalogue assets.) The module is in the public `users/andyarnellgee/apps` script repository. Any Earth Engine account can read it. Browse the source in the Code Editor at <https://code.earthengine.google.com/?scriptPath=users%2Fandyarnellgee%2Fapps%3Amodules%2FtimeseriesAnthro.js>, or load it from your own script:

```javascript
var anthro = require('users/andyarnellgee/apps:modules/timeseriesAnthro.js');
print('PFF datasets module v' + anthro.MODULE_VERSION, anthro.DATASET_VERSIONS);

var builtUp2020  = anthro.getGhslForYear(2020);           // 1 = small, 2 = large built-up
var cropland2020 = anthro.getCroplandsGladForYear(2020);  // GLAD cropland
var oilPalm2020  = anthro.getOilPalmDescalsForYear(2020); // Descals oil palm
var plantedSDPT  = anthro.processingPlantedForestSDPT();  // SDPT class 1 (planted forest)
var treeCrops    = anthro.processingTreeCropsSDPT();      // SDPT class 2 (tree crops)
var roadsRaster  = anthro.roadsMosaicStatic();            // OSM roads raster (see caveat below)
var roadsVector  = anthro.getOsmRoadsAll(aoi);            // OSM roads vector, all 34 chunks
```

- The path is lowercase `timeseriesAnthro.js` in Earth Engine, although the GitHub file is `timeSeriesAnthro.js`.
- You load the **live** copy, so updates reach you automatically. Check `MODULE_VERSION`, and record it with your results, if you need to reproduce a run. `DATASET_VERSIONS` lists the version of each dataset the module loads.
- The OSM roads **raster** is missing one Asia chunk (heavy in Southeast Asia). The vector is complete. See the OSM Roads entry above and [`osm_roads_prep.md`](osm_roads_prep.md#known-gaps-and-caveats).
- If you'd rather pin a version, copy the file from GitHub into your own repository.

---

_Maintainers / developers: see [`datasets_dev_notes.md`](datasets_dev_notes.md) for the run-metadata recipe, the datasets-panel UX plan, and the update workflow._

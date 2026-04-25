# Primary Forest Finder — QGIS Workshop Guide

**DRAFT** — Based on the workflow developed by Ann Cheptoo Rotich, FAO.

**Audience:** National authorities and GIS practitioners computing and reporting primary forests. Basic GIS knowledge (familiarity with QGIS) is assumed. No programming experience is required.

### Purpose

The QGIS Primary Forest Finder supports countries to:

- **Map** potential primary forest areas using national and/or global datasets
- **Monitor** change through consistent, repeatable criteria
- **Report** primary forests at national and global scales

### Why a QGIS version?

This workflow translates the logic of the GEE-based Primary Forest Finder into a fully offline, open-source QGIS workflow. Compared to the GEE tool, the QGIS version:

- Works offline — no cloud services or internet required
- Supports higher-resolution national datasets
- Produces explicit raster outputs at each step for review and validation
- Allows country-specific parameterisation (thresholds, datasets, protection criteria)

Both tools share the same decision-tree logic and default parameters (see Appendix D).

### Document conventions

Throughout this guide:

- **> NOTE:** Additional context or background
- **> WARNING:** Actions that can cause incorrect results
- **> TIP:** Shortcuts and best practices
- **> CHECKPOINT:** Describes what your results should look like at that stage

---

## 1. What is the Primary Forest Finder?

Primary forests are *naturally regenerating forest of native tree species, where there are no clearly visible indications of human activities and the ecological processes are not significantly disturbed* (FRA, 2025).

The Primary Forest Finder (PFF) identifies potential primary forest areas by combining treecover data with information about anthropogenic disturbance, terrain (natural protection) and legal protection.

It works through three tiers of logic:

| Tier | Rule | Rationale |
|------|------|-----------|
| **1 — Undisturbed** | Forest **outside** all anthropogenic disturbance buffers | No roads, settlements or agriculture nearby |
| **2 — Steep Slope** | Forest **inside** buffers but on **steep slopes** | Natural protection — terrain makes access and disturbance unlikely |
| **3 — Protected** | Forest **inside** buffers, on gentle slopes, but in a **protected area** | Legal protection preserves forest integrity |

The final primary forest map is the union of all three tiers, refined by a connectivity filter that removes small, isolated patches.

> **[Figure: Decision tree diagram]**

---

## 2. Prepare your data

You need these datasets, all in the **same projected CRS** (in metres):

- Treecover / forest extent (binary raster: 1 = forest, 0 = non-forest). Must represent natural forests — exclude planted forests and agroforestry systems
- Roads (vector)
- Built-up areas — small settlements (vector)
- Built-up areas — large / dense urban (vector)
- Agriculture / cropland (vector)
- DEM / elevation (raster)
- Protected areas (vector — e.g. WDPA)
- National boundary (vector — defines your AOI)

> **TIP — Coordinate Reference System**
> All layers must use a projected CRS in metres (e.g. EPSG:32717 for Ecuador). Never use geographic CRS (EPSG:4326) — distance and area calculations will be wrong.

### Step 1: Reproject all layers

- **Rasters:** Processing > Toolbox > GDAL > Raster Projections > Warp (Reproject)
- **Vectors:** Processing > Toolbox > Vector General > Reproject Layer

Set the output CRS to your chosen projected system. This step is batchable — right-click the tool > Execute as Batch Process to run all layers at once.

### Step 2: Create the AOI buffer

Apply a 2 km buffer around the national boundary to capture edge features (e.g. roads just outside the border).

- Processing > Toolbox > Vector Geometry > Buffer
- Distance: **2000** metres
- Dissolve: Yes
- Output: `AOI_Buffer.shp`

### Step 3: Clip all datasets to the AOI buffer

- **Vectors:** Processing > Toolbox > Vector Overlay > Clip
- **Rasters:** Processing > Toolbox > GDAL > Raster Extraction > Clip Raster by Mask Layer
- Mask layer: `AOI_Buffer.shp`

### Step 4: Rasterize vector datasets

Convert all vector layers to rasters so they can be combined in pixel-based analysis.

Processing > Toolbox > GDAL > Vector Conversion > Rasterize (Vector to Raster)

Set these parameters for each layer:

| Parameter | Value |
|-----------|-------|
| Burn-in value | 1 |
| Output extent | Calculate from `AOI_Buffer.shp` |
| Width/Height | Match forest raster resolution (e.g. 30 m) |
| Output data type | Byte |
| Pre-initialise with value | 0 |
| Output CRS | Your projected CRS |

Outputs: `Roads.tif`, `Builtup_Small.tif`, `Builtup_Large.tif`, `Agriculture.tif`, `PA_Mask.tif`

> **TIP — NoData**
> Set the **pre-initialise value** to 0 (so background pixels = 0). Do **not** set the GDAL NoData flag to 0 — this would make QGIS treat all background pixels as missing data, causing errors downstream.

> **TIP — Raster alignment**
> If layers don't overlay correctly, use Raster > Align Rasters with the forest raster as the reference layer. Set resampling to Nearest Neighbour for categorical data, Bilinear for the DEM.

> **CHECKPOINT — Verify your layers before proceeding**
> Before moving on, confirm all rasters are correctly prepared:
> - Toggle layers on/off to check visual alignment
> - Use the **Identify Tool** to sample pixel values (should be 0 or 1 for binary layers)
> - Right-click layer > Properties > Information to verify CRS, extent and resolution match across all layers

### Step 5: Create slope layers

Generate slope from the DEM, then classify into steep and gentle masks.

**Derive slope:** Processing > Toolbox > GDAL > Raster Analysis > Slope
- Input: clipped DEM
- Output measurement: Degrees
- Output: `Slope.tif`

**Create steep slope mask:** Processing > Toolbox > Raster Calculator
- Expression: `"Slope@1" >= 45`
- Output: `Steep_Slope.tif`

**Create gentle slope mask:**
- Expression: `"Slope@1" < 45`
- Output: `Gentle_Slope.tif`

> **[Figure: Slope classification result]**

### Step 6: Prepare the protected areas layer

Filter the WDPA (or national equivalent) to retain only areas with strong, long-standing legal protection. The GEE tool applies these default filters:

- **Exclude** STATUS = `'Proposed'` or `'Not Reported'`
- **Exclude** DESIG_ENG = `'UNESCO-MAB Biosphere Reserve'`
- **IUCN categories:** `Ia`, `Ib`, `II` (strictest categories only)
- **Minimum protection age:** 30 years (i.e. STATUS_YR ≤ current year − 30)

In QGIS, apply these filters using Select by Expression:

```
"STATUS" NOT IN ('Proposed', 'Not Reported')
AND "DESIG_ENG" != 'UNESCO-MAB Biosphere Reserve'
AND "IUCN_CAT" IN ('Ia','Ib','II')
AND "STATUS_YR" > 0
AND "STATUS_YR" <= 1996
```

> **TIP — Country-specific adjustments**
> These are the GEE tool defaults. You may need to adapt IUCN categories or the minimum protection age for your country's context. Document any changes for reporting.

Rasterize the filtered result as in Step 4.

---

## 3. Build the anthropogenic disturbance buffers

This creates a single binary raster showing where anthropogenic influence exists (the combined disturbance buffers).

### Step 1: Create distance rasters

For each anthropogenic layer, compute the distance from every pixel to the nearest feature using raster-based proximity (not vector buffers).

> **TIP — Why raster buffers, not vector buffers?**
> Vector buffers are geometrically precise but don't preserve raster grid alignment when converted, often producing slivers or misaligned pixels. Raster distance-based buffering operates directly on the pixel grid, keeping everything aligned for downstream calculations.

Processing > Toolbox > GDAL > Raster Analysis > Proximity (Raster Distance)

| Parameter | Value |
|-----------|-------|
| Input raster | e.g. `Roads.tif` |
| Target pixel values | 1 |
| Distance units | Georeferenced coordinates |
| Output data type | Float32 |

Outputs: `Dist_Roads.tif`, `Dist_Builtup_Small.tif`, `Dist_Builtup_Large.tif`, `Dist_Agriculture.tif`

This step is batchable.

### Step 2: Apply distance thresholds

Use the Raster Calculator to create binary buffers. Each expression identifies pixels within the influence zone of that feature.

| Layer | Expression | Default threshold |
|-------|-----------|-------------------|
| Roads | `"Dist_Roads@1" <= 1000` | 1000 m |
| Built-up (small) | `"Dist_Builtup_Small@1" <= 1000` | 1000 m |
| Built-up (large) | `"Dist_Builtup_Large@1" <= 2000` | 2000 m |
| Agriculture | `"Dist_Agriculture@1" <= 1000` | 1000 m |

Outputs: `Roads_Buffer.tif`, `Builtup_Small_Buffer.tif`, `Builtup_Large_Buffer.tif`, `Agriculture_Buffer.tif`

Result: 1 = within influence zone, 0 = outside.

> **TIP — Adjust thresholds for your country**
> These defaults are starting points. Local conditions (road quality, terrain, land use patterns) may require different values. Document any changes for reporting.

> **TIP — Optional: split roads by type**
> The default is a single roads layer with a 1000 m buffer, which is the standard threshold in the literature (e.g. Intact Forest Landscapes). If your roads dataset distinguishes road types (e.g. OSM `highway` tags), you can optionally create separate layers with different thresholds:
>
> | Road type | Suggested threshold |
> |-----------|-------------------|
> | Primary / paved | 1500 m |
> | Secondary / unpaved | 1000 m |
> | Tertiary / logging | 500 m |
>
> Process each layer through Steps 1–2 independently, then combine all road buffers with the other anthropogenic buffers in Step 3 using OR logic. This is not required — a single roads layer at 1000 m is well supported and matches the GEE tool.

### Step 3: Combine into one anthropogenic mask

Raster Calculator expression:

```
("Roads_Buffer@1" + "Builtup_Small_Buffer@1" +
 "Builtup_Large_Buffer@1" + "Agriculture_Buffer@1") >= 1
```

- Output: `Anthropogenic_Mask.tif`
- Result: **1 = inside anthropogenic disturbance buffers**, **0 = undisturbed (outside buffers)**

> **TIP — Validate binary outputs**
> Right-click layer > Properties > Information > Bands. Confirm min = 0, max = 1. Change the symbology to visually inspect the buffer network against the input features.

> **[Figure: Anthropogenic mask]**

---

## 4. Identify primary forest — the three tiers

All steps use the Raster Calculator. Set CRS, extent and resolution to match the forest raster for every output.

### Tier 1 — Undisturbed (outside buffers)

Forest pixels outside all anthropogenic disturbance buffers.

```
("Forest@1" = 1) AND ("Anthropogenic_Mask@1" = 0)
```

Output: `Tier1_Undisturbed.tif` — **1 = primary forest candidate (Tier 1)**

### Intermediate: Forest inside buffers

We also need the inverse — forest pixels that *are* inside the anthropogenic disturbance buffers. These will be tested against slope (natural protection) and protected areas (legal protection).

```
("Forest@1" = 1) AND ("Anthropogenic_Mask@1" = 1)
```

Output: `Forest_Inside_Buffers.tif`

### Tier 2 — Steep Slope in Buffer

Forest inside anthropogenic disturbance buffers but on steep terrain (natural protection — terrain makes access and disturbance unlikely).

```
("Forest_Inside_Buffers@1" = 1) AND ("Steep_Slope@1" = 1)
```

Output: `Tier2_Steep.tif` — **1 = primary forest candidate (Tier 2)**

### Tier 3 — Protected in Buffer

Forest inside anthropogenic disturbance buffers, on gentle slopes, but in a legally protected area.

```
("Forest_Inside_Buffers@1" = 1) AND ("Gentle_Slope@1" = 1) AND ("PA_Mask@1" = 1)
```

Output: `Tier3_Protected.tif` — **1 = primary forest candidate (Tier 3)**

### Combine all three tiers

```
("Tier1_Undisturbed@1" = 1) OR ("Tier2_Steep@1" = 1) OR
("Tier3_Protected@1" = 1)
```

Output: `Pre_Connectivity_Forest.tif` — **1 = potential primary forest (before refinement)**

> **[Figure: Pre-connectivity forest map]**

---

## 5. Refine output (connectivity filter)

Isolated forest pixels (small fragments) are unlikely to be functionally intact primary forest. This step removes them using a neighbourhood density approach — the same method used in the GEE tool's "Refine Output" step.

### Neighbourhood density method (matches GEE tool)

1. **Compute neighbourhood density:** Apply a focal (moving-window) mean with a circular kernel.
   - Processing > Toolbox > GDAL > Raster Analysis > Grid (Moving Average), or use the Raster Calculator with a neighbourhood function.
   - Kernel radius: **2000 m** (default in GEE tool; adjustable 0–5000 m)
   - Input: `Pre_Connectivity_Forest.tif`
   - Output: `Forest_Density.tif` (values 0–1, representing the proportion of forest pixels in the neighbourhood)

2. **Threshold the density surface:**
   - Raster Calculator: `"Forest_Density@1" >= 0.5`
   - Threshold: **0.5** (default in GEE tool; adjustable 0–1)
   - Output: `Density_Mask.tif`

3. **Mask the forest layer:**
   - Raster Calculator: `("Pre_Connectivity_Forest@1" = 1) AND ("Density_Mask@1" = 1)`
   - Output: `Primary_Forest_Final.tif`

> **TIP — Alternative: Sieve**
> For a simpler approach, you can use GDAL Sieve (Processing > Toolbox > GDAL > Raster Analysis > Sieve) to remove patches below a minimum size in pixels.
> `pixels = area_ha × 10,000 / (resolution_m × resolution_m)`
> Example: 10 ha at 30 m resolution = 10 × 10,000 / 900 ≈ 111 pixels.
> Note: this differs from the GEE tool's density-based method and may produce slightly different results.

> **[Figure: Final primary forest map]**

---

## 6. Quick reference — workflow summary

```
Reproject all layers (projected CRS, metres)
    --> Buffer AOI (2 km)
    --> Clip all layers to AOI buffer
    --> Rasterize vectors (burn=1, init=0, match forest grid)
    --> Align rasters (forest raster = reference)
    --> Compute slope --> steep + gentle masks
    --> Compute distance rasters (proximity)
    --> Apply distance thresholds --> binary buffers
    --> Combine buffers --> Anthropogenic Mask
    --> Tier 1 (Undisturbed): Forest AND NOT in buffers
    --> Tier 2 (Steep Slope): Forest AND in buffers AND Steep Slope
    --> Tier 3 (Protected): Forest AND in buffers AND Gentle Slope AND Protected Area
    --> Combine Tiers 1 + 2 + 3 --> Pre-connectivity Forest
    --> Refine output (neighbourhood density filter)
    --> Primary Forest Final
```

---

## Appendix A — Raster best practices

### Data types

Choose the smallest appropriate type for each layer. Right-click layer > Properties > Information > Data Type to check.

| Data type | Range | Use for |
|-----------|-------|---------|
| Byte (UInt8) | 0–255 | Binary masks, classification rasters (fastest) |
| Int16 | −32,768 to 32,767 | Count data, DEMs |
| Float32 | Decimal precision | Distance surfaces, slope, NDVI, continuous data |

In this workflow: use **Byte** for all binary rasters (forest, buffers, masks, tier outputs) and **Float32** for distance and slope rasters.

### NoData handling

- When rasterizing vectors, set the **pre-initialise value** to 0 (background = no feature). Do **not** set the GDAL NoData flag to 0 — QGIS would treat all background as missing data, breaking downstream calculations.
- When clipping rasters, check that the NoData value hasn't changed. Right-click layer > Properties > Information > Dimensions to see the NoData value.
- If a raster calculator output has unexpected gaps, check whether an input has NoData pixels propagating through.
- To fill NoData: GDAL > Raster Analysis > Fill NoData (interpolates from surrounding pixels).
- To convert NoData values: GDAL > Raster Conversion > Translate and set the NoData field in Advanced Parameters.

### Resampling methods

| Data type | Method | When |
|-----------|--------|------|
| Categorical (forest, land use, buffers) | Nearest Neighbour | Always — preserves class values |
| Continuous (DEM, slope, distance surfaces) | Bilinear or Cubic | Reprojection or resampling |

> **WARNING:** Resampling modifies raster values. Always verify results after resampling.

### Raster alignment

All rasters must share the same grid origin, cell size and extent before raster calculator operations. Use **Raster > Align Rasters** with the forest raster as the reference layer if layers don't overlay exactly. Right-click layer > Properties > Information to check pixel origin, grid alignment, extent, pixel size and CRS.

### Performance tips

- **Build pyramids** (overviews) for large rasters: Right-click layer > Properties > Pyramids. Speeds up display without changing the data. Note: may increase disk usage — back up the original first.
- **Use compression** when saving outputs: set Profile = High Compression or add `-co COMPRESS=LZW` in GDAL tools. LZW is lossless and recommended.
- **Virtual rasters (VRTs)** can mosaic tiles without creating large files: Processing > Toolbox > GDAL > Raster Miscellaneous > Build Virtual Raster. Pixel values are generated on the fly — useful for temporary or exploratory work.
- **Clip to AOI early** to reduce file sizes and processing time throughout the workflow.

---

## Appendix B — Default global datasets

National datasets are strongly encouraged where available. When unavailable, the following global and regional datasets can be used. Datasets marked with **[GEE]** are used by the GEE Primary Forest Finder tool.

### Land cover / forest products

| Product | Resolution | Coverage | Temporal | Notes |
|---------|-----------|----------|----------|-------|
| Hansen Global Forest Change (UMD) **[GEE]** | 30 m | Global | 2000 baseline + annual loss | Primary forest dataset in GEE tool |
| GLAD LULC **[GEE]** | 30 m | Global | 2000, 2020 | Alternative with treecover height classes |
| ESA WorldCover | 10 m | Global | 2020–2021 | 11 classes, ~75% accuracy |
| Copernicus Global Land Cover (CGLS-LC100) | 100 m | Global | 2015–2019 | 23 classes, ~80% accuracy |
| ESA-CCI Land Cover | 300 m | Global | 1992–2020 | 22 classes, long time series |
| MODIS Land Cover (MCD12Q1) | 500 m | Global | 2001–present | 17 classes |
| Dynamic World (Google) | 10 m | Global | 2015–present | Near-real-time, 9 classes |
| MAPBIOMAS | 30 m | Amazonia | 1985–2022 | 19 classes, >80% accuracy |

### Elevation

| Product | Resolution | Coverage | Accuracy | Notes |
|---------|-----------|----------|----------|-------|
| ALOS AW3D30 (JAXA) **[GEE]** | 30 m | Global | ~5 m vertical | Used in GEE tool |
| SRTM DEM | 30 m | 60°N–56°S | ~10 m vertical | Alternative |

### Roads / transport

| Product | Resolution | Coverage | Notes |
|---------|-----------|----------|-------|
| OpenStreetMap **[GEE]** | Vector | Global | Default in GEE tool. Download from Geofabrik |
| GRIP4 (Global Roads Inventory) | Vector | Global | Major road classes, ~2018 |
| Microsoft Roads | Raster | Global | Alternative global dataset |

### Built-up / settlements

| Product | Resolution | Coverage | Notes |
|---------|-----------|----------|-------|
| GHSL Built-up Grid **[GEE]** | 10–30 m | Global | Primary source in GEE tool. Small + large built-up |
| WSF (World Settlement Footprint) **[GEE]** | 10 m | Global | ~90% accuracy |
| GISD **[GEE]** | 30 m | Global | Impervious surfaces |
| GISA **[GEE]** | 30 m | Global | Annual impervious surface change |

### Agriculture / cropland

| Product | Resolution | Coverage | Notes |
|---------|-----------|----------|-------|
| GLAD Croplands **[GEE]** | 30 m | Global | Cropland extent, year-selectable |
| Global Pasture Watch **[GEE]** | 30 m | Global | Pasture and grassland |
| Oil Palm (Descals et al.) **[GEE]** | 10 m | Global (tropics) | Oil palm plantations |
| GFSAD Cropland Extent | 30 m | Global | Binary cropland, ~85% accuracy |

### Protected areas

| Product | Resolution | Coverage | Notes |
|---------|-----------|----------|-------|
| WDPA **[GEE]** | Vector | Global | Download from protectedplanet.net. Updated monthly |

### Country boundaries

| Product | Resolution | Coverage | Notes |
|---------|-----------|----------|-------|
| GAUL 2024 Level 0 (FAO) **[GEE]** | Vector | Global | Used for AOI in GEE tool |

> **TIP — Downloading data for QGIS**
> Most datasets are available from the source provider's website, or via platforms like Earth Engine Data Catalog, Zenodo, or the Humanitarian Data Exchange. For workshops, instructors should pre-download and clip data to the study area.

---

## Appendix C — Batch processing and QGIS Model Builder

### Batch processing

Many steps in the workflow (reprojection, clipping, rasterization, proximity) can be run on multiple layers at once:

1. Open the tool from Processing > Toolbox
2. Right-click the tool name > **Execute as Batch Process**
3. Add one row per input layer, set shared parameters (CRS, extent, resolution)
4. Run all at once

This is particularly useful for:
- Reprojecting all layers (Step 1)
- Clipping all layers to the AOI buffer (Step 3)
- Rasterizing all vector layers (Step 4)
- Computing distance surfaces (Section 3, Step 1)

### QGIS Model Builder

For a repeatable, shareable workflow, use Processing > Graphical Modeler to chain the full pipeline:

1. **Create a new model:** Processing > Graphical Modeler
2. **Add inputs:** define parameters for each input dataset, CRS, buffer distances, slope threshold
3. **Add algorithms:** drag in each processing step (reproject, buffer, clip, rasterize, proximity, raster calculator)
4. **Connect** outputs of one step to inputs of the next
5. **Save** the model as a `.model3` file — it can be shared with other users or run as a batch

> **TIP — Model Builder vs Python**
> Model Builder is visual and workshop-friendly. For full automation or scripting, the same workflow can be written in Python using `processing.run()`. See the PFF QGIS Python pseudocode reference for a scripted version.

---

## Appendix D — Alignment with the GEE Primary Forest Finder

This QGIS workflow replicates the logic of the GEE-based Primary Forest Finder tool. The table below maps the key concepts.

### Terminology mapping

| GEE tool (pff_4.js) | QGIS workflow | Notes |
|---------------------|---------------|-------|
| Treecover / Forest Definition | Forest extent raster | GEE supports Hansen % canopy or GLAD height thresholds |
| Human Influence (UI panel) | Anthropogenic disturbance buffers | Same concept, different label |
| Tier 1 — Undisturbed (outside buffers) | Tier 1 — Undisturbed | Identical logic |
| Tier 2 — Steep Slope in Buffer | Tier 2 — Steep Slope | Identical logic |
| Tier 3 — Protected in Buffer | Tier 3 — Protected | Identical logic |
| Pre-connectivity Forest | Pre_Connectivity_Forest.tif | Combined tiers before refinement |
| Refine Output | Refine output (connectivity filter) | Neighbourhood density method |
| Primary Forest | Primary_Forest_Final.tif | Final output |

### Parameter defaults

| Parameter | GEE default | QGIS default |
|-----------|------------|--------------|
| Roads buffer | 1000 m | 1000 m |
| Built-up (small) buffer | 1000 m | 1000 m |
| Built-up (large) buffer | 2000 m | 2000 m |
| Agriculture buffer | 1000 m | 1000 m |
| Slope threshold | 45° | 45° |
| WDPA IUCN categories | Ia, Ib, II | Ia, Ib, II |
| WDPA minimum protection age | 30 years | 30 years |
| Refine: neighbourhood radius | 2000 m | 2000 m |
| Refine: density threshold | 0.5 | 0.5 |
| AOI country buffer | 2000 m | 2000 m |

### Key differences

- **Data sources:** GEE accesses datasets directly from the Earth Engine Data Catalog. QGIS requires pre-downloaded, locally stored data.
- **Distance calculation:** GEE uses `ee.Image.fastDistanceTransform()`. QGIS uses GDAL Proximity. Results should be functionally equivalent.
- **Raster calculator syntax:** GEE uses JavaScript image algebra. QGIS uses its own raster calculator expression syntax (shown throughout this guide).
- **Refinement method:** Both use neighbourhood density. GEE uses `reduceNeighborhood` with a circular kernel; QGIS uses focal statistics or GDAL Grid (Moving Average). GEE also offers connected-component and vector-based patch filtering as alternatives.
- **Slope and Tier 2/3 are optional** in the GEE tool (toggleable via UI checkboxes). In the QGIS workflow they are always computed but could be skipped.

---

## Appendix E — Known limitations and caveats

### Important disclaimer

Maps produced through the PFF workflow do not confer legal status or formal designation of primary forests. The output represents spatial approximations of potential primary forest areas based on geospatial proxies, decision rules and available datasets. Results should be validated with field data where possible and reviewed with local experts. An iterative approach is recommended to produce a final useful product.

### Data limitations

- **Data quality:** The quality of results depends on the quality of input data. Countries are encouraged to use the best data available to them.
- **Road completeness:** OSM road coverage varies by country. In some regions, many roads (especially logging and informal roads) are missing. This can overestimate primary forest extent.
- **Built-up accuracy:** Settlement layers may miss small or informal settlements, particularly in remote areas.
- **Protected area effectiveness:** The WDPA records legal designation, not actual enforcement. A protected area may be degraded on the ground. Tier 3 results should be interpreted with this caveat.
- **Temporal mismatch:** Input datasets may represent different time periods. Ensure datasets are as temporally aligned as possible.

### Methodological limitations

- **Classification errors:** The workflow produces reliable results using a simple and transparent methodology, but will have areas of omission and commission in practice.
- **Geographic variability:** Primary forest characteristics vary globally. Threshold values used in the workflow are starting points. Local authorities should adjust these to suit their context and document any changes for reporting.
- **Binary buffers vs distance decay:** The PFF uses hard distance thresholds (e.g. 1000 m from a road = disturbed, 1001 m = undisturbed). In reality, disturbance intensity decays gradually with distance. The FLII (Grantham et al. 2020) uses a continuous pressure-response model which is more ecologically realistic but harder to implement.
- **Slope threshold:** A single 45° threshold is a simplification. The degree to which slope protects forest depends on local conditions (soil type, rainfall, road-building capacity).
- **Connectivity filter sensitivity:** The neighbourhood density method is sensitive to kernel radius and density threshold. Small changes in these parameters can significantly alter the final map. Document and justify your chosen values.
- **Edge effects at country borders:** The 2 km AOI buffer mitigates but does not fully resolve edge effects. Features (roads, agriculture) beyond 2 km of the border can still influence results.

### QGIS-specific caveats

- **Raster alignment:** If input rasters are not perfectly aligned (same origin, cell size, extent), raster calculator results will be incorrect. Always align rasters before analysis (see Appendix A).
- **NoData propagation:** QGIS raster calculator treats NoData as NoData in all operations. A single NoData input pixel will produce a NoData output pixel. Check for unexpected gaps.
- **Processing intensity:** The workflow can be computationally intensive, particularly for multi-temporal analyses. Use batch processing (Appendix C) and clip data to the AOI early to reduce overhead.
- **Memory:** Large rasters (national scale at 30 m) can exceed available RAM. Consider tiling your analysis or using GDAL command-line tools with streaming.
- **Coordinate system:** All distance and area calculations require a projected CRS in metres. Geographic CRS (EPSG:4326) will produce wrong results.

---

*Primary Forest Finder QGIS Workflow. Developed by Ann Cheptoo Rotich, FAO. Supervised by Xavier deLamo. Based on the GEE tool by Andy Arnell. Licensed under CC BY 4.0.*

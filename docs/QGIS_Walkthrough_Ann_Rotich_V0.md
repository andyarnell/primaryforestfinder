# PRIMARY FOREST FINDER Geospatial Workflow

## A QGIS WORKFLOW GUIDE

**Version 1**
**November 2025**

---

## Table of Contents

- [1.0. Document Information and Structure](#10-document-information-and-structure)
  - [1.1 About this guide](#11-about-this-guide)
  - [1.2. Structure of the Manual](#12-structure-of-the-manual)
  - [1.3. Who Should Use this Manual?](#13-who-should-use-this-manual)
  - [1.4. Document Conventions](#14-document-conventions)
  - [1.5. Help and Support](#15-help-and-support)
  - [1.6. Acknowledgements](#16-acknowledgements)
  - [1.7. Authors](#17-authors)
  - [1.8. License and Usage Terms](#18-license-and-usage-terms)
- [2.0. Background to the QGIS Primary Forest Finder](#20-background-to-the-qgis-primary-forest-finder)
  - [2.1. Introduction to the QGIS Primary Forest Finder Workflow](#21-introduction-to-the-qgis-primary-forest-finder-workflow)
  - [2.2. Purpose of the QGIS Primary Forest Finder](#22-purpose-of-the-qgis-primary-forest-finder)
- [3.0. Methodological Framework](#30-methodological-framework)
  - [3.1. Concept and Logic](#31-concept-and-logic)
  - [3.2. Potential Limitations](#32-potential-limitations)
  - [3.3. Alignment with the GEE Primary Forest Finder](#33-alignment-with-the-gee-primary-forest-finder)
- [4.0. Data Requirements](#40-data-requirements)
  - [4.1. Data Preparation](#41-data-preparation)
- [5.0. Analysis -- Applying the Primary Forest Finder](#50-analysis--applying-the-primary-forest-finder)
  - [5.1. Building the Anthropogenic Influence Mask Layer](#51-building-the-anthropogenic-influence-mask-layer)
  - [5.2. Building Forest Masks](#52-building-forest-masks)
  - [5.3. Integrating Ancillary Layers](#53-integrating-ancillary-layers)
  - [5.4. Building the Primary Forest Layer](#54-building-the-primary-forest-layer)
  - [5.5. Assessing Spatial Continuity](#55-assessing-spatial-continuity)
- [Annex A](#annex-a)
  - [A.1. Best practices for Working with Raster Data](#a1-best-practices-for-working-with-raster-data)
  - [A.2. Default Global Datasets](#a2-default-global-datasets)
- [Annex B](#annex-b)
  - [B.1 Batch Processing and Automation](#b1-batch-processing-and-automation)

---

## 1.0. Document Information and Structure

### 1.1. About this guide

| Field | Value |
|---|---|
| Version | 1.0 |
| Release Date | TBD |
| Compatible QGIS Versions | TBD |

### 1.2. Structure of the Manual

The guide is organized into the following modules;

- **Module 1:** Document Information and structure.
- **Module 2:** Background of the methodology.
- **Module 3:** Conceptual Framework.
- **Module 4:** Data Requirements and Preparation.
- **Module 5:** Analysis
- **Module 6:** Quality Control
- **Module 7:** Output Production and Reporting
- **Module 8:** Appendices

### 1.3. Who Should Use this Manual?

The PFF workflow is designed for national authorities to compute and report primary forests in their jurisdiction. We assume users have basic GIS knowledge including familiarity with GIS software (QGIS) and common workflows. No programming experience is required.

**Prerequisites:** Before using the manual, ensure you have QGIS installed.

### 1.4. Document Conventions

To navigate the workflow efficiently, the specific text formatting and visual elements have been used as follows;

- **Bold Text** indicates UI elements, menus, and buttons e.g., "Click **Processing > Toolbox > Raster Calculator.**"
- *Italics* represent important concepts e.g., *Primary Forest*
- `Monospace text` represents expressions, file paths, or field names.
- Internal references appear as hyperlinks.

**Visual Indicators**

Screenshots, diagrams, and videos are used to provide practical demonstrations. Throughout this manual, you will encounter these icons:

| Icon | Meaning | Usage |
|---|---|---|
| NOTE | Additional Information | Context, alternative or background |
| WARNING | Attention | Actions that can cause incorrect results |
| CHECKPOINT | Verify your progress | Describes what your results should look like at a stage |
| TIP | Workflow efficiency | Shortcuts/ best practices |
| TROUBLE SHOOTING | Common Issues | Solutions to problems others have encountered |

### 1.5. Help and Support

The Primary Forest Finder is still on its beta stage - therefore still under development. Please contact the development team with any feedback, improvement to the workflow or for technical support using the workflow.

For questions on QGIS, consult the QGIS documentation.

Video tutorials are included in the Annex B / Tutorials section for step-by-step screencasts.

The Primary Forest Finder is raster intensive. A comprehensive Best Practices when working with Rasters section has been included in the Annex.

### 1.6. Acknowledgements

This guide was developed with contributions from:

### 1.7. Authors

The QGIS PFF has been developed by the Food and Agriculture Organization of the United Nations (FAO). The workflow is based on the GEE-based tool developed by Andy Arnell. The QGIS workflow and its documentation were developed by Ann Cheptoo Rotich. Xavier deLamo supervised the production of both products with the leadership of Anne Branthrome.

### 1.8. License and Usage Terms

The Primary Forest Finder Workflow and its associated documentation is free and open-source made available under the terms of the Creative Commons Attribution 4.0 International License (CC BY 4.0).

---

## 2.0. Background to the QGIS Primary Forest Finder

### 2.1. Introduction to the QGIS Primary Forest Finder Workflow

The QGIS Primary Forest Finder is a geospatial framework designed to support countries identify and map potential primary forest areas using their own national datasets using QGIS.

It translates the analytical logic of the Primary Forest Finder tool developed in Google Earth Engine (GEE) environment into a fully offline, adaptable, open-source workflow suitable for national scale primary forest assessment.

The workflow is implemented as a sequence of modular geoprocessing steps -- each corresponding to one element of the primary forest decision tree. It can be executed manually or automated through QGIS Batch Processing, or via QGIS Model Builder for streamlined, consistent and repeatable assessments.

### 2.2. Purpose of the QGIS Primary Forest Finder

The QGIS Primary Forest Workflow provides a country-adaptable approach to identify, map, and quantify potential primary using geospatial techniques.

It offers a data-driven methodology that supports the use of national datasets and the customization of parameters to reflect country and biome-specific conditions.

By standardizing the methodology, the Primary Forests Finder contributes to a transparent, comparable, reproducible approach to primary forest monitoring and reporting at national and global scales.

At its core, the tool serves the following functions:

- Baseline mapping of potential primary forests.
- Change monitoring through consistent and repeatable criteria.
- Supports national primary forest reporting.
- Supports evidence-based management and planning of primary forests.

---

## 3.0. Methodological Framework

### 3.1. Concept and Logic

Primary forests are naturally regenerating forest of native tree species, where there are no clearly visible indications of human activities and the ecological processes are not significantly disturbed (FRA, 2025).

To approximate these areas spatially, the Primary Forest Finder applies a hierarchical decision tree that identifies and measures forests with minimal human influence or those with natural or legal protection that help preserve their ecological integrity.

At its core, the workflow works on the following decision parameters;

**Table 1: Primary Forest Finder Decision Parameters**

| Parameter | Metric | Rationale |
|---|---|---|
| Avoidance of human influence | Distance from anthropogenic features (roads, agriculture, built-up areas) | Forests far from human features are more likely to be intact and undisturbed. |
| Natural protection | Slope | Steep areas are less accessible, thus less likely to be exploited for anthropic functions. |
| Legal protection | IUCN protected categories | Legally conserved areas have restricted human access and disturbance -- thus they are likely to be intact. |

The identification of primary forests is guided by the assumption that;

> Forests are likely to be primary when they are both naturally and legally protected from human disturbance, and they demonstrate spatial continuity.

The workflow identifies primary forest through three sequential filters in a stepwise exclusion and inclusion process as shown in Figure 1.

> **[Figure 1: Primary Forest Finder Logic]**

Starting with a national forest layer as the baseline, we filter all forest pixels that are outside anthropogenic influence -- obtained by delimiting buffer zones around human features. Forests within these buffers are considered "influenced" and consequently, excluded. This captures the first tier of undisturbed primary forest.

Primary forests within anthropogenic influence are then evaluated further by applying a slope condition, we assume certain terrain characteristics (steep slopes) will naturally protect forests from human disturbances. This results in the second tier of primary forests -- Forests within anthropogenic areas but with steep slope.

Lastly the primary forest finder filters remaining forest pixels using protection filters (legal protection). Forests within gently sloping anthropogenic influenced areas are considered primary if they meet the defined criteria. This results in the last tier of primary forests; Forests within gently sloping anthropogenic areas with legal protection.

The resulting Primary Forest Candidate pixels are a composite of;

1. Forest pixels completely undisturbed by anthropogenic activity
2. Forest pixels within disturbed areas but located on steep terrain.
3. Forest pixels within gently sloping disturbed zones but inside protected areas.

These three classes of potential primary forest pixels that are then merged into a single output layer that is further refined by a connectivity mask.

**Assessing spatial connectivity**

Forests are not isolated patches of trees -- they exist as ecologically and spatially continuous systems. Therefore, retaining only large, connected patches ensures identifying forests that are functionally intact and not just structurally forested.

A moving window (circular kernel) is applied to all candidate primary forest pixels to assess spatial cohesion. Pixels that meet a density threshold are retained, ensuring the final output represents large, contiguous forest patches.

### 3.2. Potential Limitations

- **Classification errors:** The workflow aims to produce reliable primary forest maps relevant for reporting purposes, using a simple and transparent methodology. But of course in practice it will have areas of omission and commission. Results should be validated with field data when possible as well as reviewed with local experts. An iterative approach can therefore be used to produce a final useful product.
- **Data dependencies:** The quality of results is dependent on the quality of data used. Countries are encouraged to use the best data available to them.
- **Geographic variability:** Primary Forest characteristics vary globally. Threshold values used in the workflow should be considered as starting points. Local authorities are recommended to adjust these values to suit their local contexts. However, these values should be well documented for reporting purposes.
- **Legal Status:** Maps produced through the QGIS Primary Forest Finder workflow do not confer legal status or formal designation of primary forests. The output represents spatial approximations of potential primary forest areas based on geospatial proxies, decision rules, and available datasets.
- **Processing Intensity:** The QGIS workflow can be computationally and operationally intensive, particularly due to its repetitive processing steps when multi-temporal analyses are required. There are approaches such as batch processing to help limit repetitive operations.

### 3.3. Alignment with the GEE Primary Forest Finder

The QGIS Primary Forest Finder workflow is a no-code, desktop implementation of the Primary Forest Finder logic originally developed as a Google Earth Engine (GEE) application. Both workflows share the same conceptual basis and decision-tree logic, but the QGIS implementation differs in several key ways.

The QGIS workflow:

- Allows country-specific parameterization, such as distance thresholds, slope limits, and protection proxies that reflect local ecological and management conditions.
- Supports the use of higher-resolution national datasets, which may exceed practical processing limits in cloud-based environments when used extensively or iteratively.
- Produces explicit raster output at each decision step, enabling transparency, review, and validation of intermediate results.
- Can be executed offline, without reliance on cloud services or internet connectivity.
- It is free and open source, relying entirely on QGIS and GDAL tools.

---

## 4.0. Data Requirements

This section lists the required datasets, describing their characteristics required to implement the QGIS workflow.

Each dataset corresponds to a conceptual component defined in the previous section. National datasets are strongly encouraged where available, accurate and representative as they provide higher spatial accuracy, finer spatial detail and better alignment with local conditions and definitions.

In the case where national datasets are unavailable, global, and regional datasets can be used as an alternative or validation provided, they meet the criteria defined in the table 2 below. A summary of available global and regional datasets is available in the annex.

**Table 2: Data Requirements**

| Dataset | Purpose in Workflow | Format | Minimum Requirements | Additional Notes |
|---|---|---|---|---|
| Forest Layer | This is the baseline of the analysis that defines the forest extent. | Binary Raster where 1= forest, 0= non-forest | Spatial Resolution; Projected CRS corresponding to the country. | Forest definition: Adherent to FRA definitions -- forests excluding planted forests and agroforestry systems. Global or regional landcover maps can be used to derive forest layer. Annex A details global and regional landcover products that can be used as alternatives. |
| Anthropogenic Layers (Roads Layers disaggregated to major/minor roads, Built up areas, Agriculture, Plantations) | Identifies human influence | Binary Raster Layers where 1 = presence and 0= absence | Disaggregated layers preferred when thresholding e.g. large and small roads. | Global Alternatives; Roads -- OpenStreetMap (OSM); Built-up -- World Settlement Footprint / GHSL |
| Digital Elevation Model (DEM) | Derive slope | Raster (.tif) | Have sufficient resolution to capture terrain variation. 30-100 m resolution | Global alternatives; ALOS, SRTM |
| Protected Areas | Identifies legally protected forest areas | Raster (.tif) where 1= presence and 0= absence of protected area | Should capture IUCN category, status and establishment year or country's equivalent | UNEP WCMS's World Database of Protected Areas (WDPA) |
| Administrative Boundary (AOI) | Defines the computational area and delimits all layers consistently | Vector (.shp) | | |

> **NOTE:** Spatial datasets are often stored in traditional formats like shapefiles, CAD files or tabular records with spatial attributes. While these formats are optimal for storage and visualization, the primary forest finder workflow requires datasets to be converted into analysis-ready formats namely;
> - Discrete features like roads, protected areas and built-up areas will be converted to raster as detailed in the next section.
> - Continuous data types like DEM will be modified to binary rasters.

---

### 4.1. Data Preparation

This chapter guides users in the preparation of analysis-ready data layers to be used in the QGIS Primary Forest Workflow.

All steps will be demonstrated with QGIS version 3.30.2 using Ecuador as example.

The decision tree illustrated below can help guide assess the appropriate actions to be taken depending on the nature of their datasets.

> **WARNING:** All datasets, whether global or national, must be harmonized into standard and compatible formats including coordinate systems, data types and spatial extents. Small inconsistencies can cause misalignment, inaccurate thresholding, or incorrect computation.

> **[Figure 2: Data Readiness Preparation]**

> **[Figure 3: Data Readiness Decision Tree]**

#### Step 1: Coordinate Reference System Management (CRS)

> **WARNING:** Mixing geographic and projected coordinate datasets can shift layers by kilometers -- introducing errors in analysis.

All data layers (raster and vector) must be projected into a uniform, projected coordinate system (in meters) that preserves area, corresponding to the country of interest. This is essential for accurate buffering and areal measurements in subsequent steps.

Additional information on coordinate reference systems is available in the annex.

To reproject your data layers in QGIS,

1. Right-click each layer > **Properties** > **Source** > **CRS** to check the layer's projection.
2. If different, reproject as follows.
   - For rasters: Click **Processing** in the main ribbon > **Toolbox** > **GDAL** > **Raster Projections** > **Warp (Reproject)** > Choose an appropriate output CRS. In the case of Ecuador, we will use EPSG 32717.
   - For vector datasets: Click **Processing** > **Toolbox** > **Vector general** > **Reproject layer**. Define your input layer (layer to be reprojected) > Choose the appropriate projected coordinate system > Save appropriately the output file.
3. To reproject multiple layers at once (Batch-process as seen in figure 4 below) > Right-Click the tool > **Execute as a batch process** > Set all the inputs and parameters as before > **Run**.

More on batch processing and automation is detailed in the annex.

> **TIP:** Save as new layer to avoid overwriting original data. Name data layers clearly and consistently.

> **[Figure 4: Batch Processing in QGIS]**

#### Step 2: Defining the Area of Interest (AOI)

This step creates a uniform spatial extent for computation using the national boundary. A 2km buffer is applied on the national boundary to account for edge features such as roads.

To perform this in QGIS:

1. Load the national boundary shapefile (.shp)
2. Ensure the boundary layer is projected to the appropriate projected coordinate system.
3. Apply a 2 km buffer by clicking **Processing** > **Toolbox** > **Vector geometry** > **Buffer**.
4. Leaving other default parameters, set the buffer distance to 2000 meters and Click **Run**.

> **TIP:** In the case where the national boundary has internal boundaries e.g., provinces, check the dissolve option to merge the input into a single continuous input. Otherwise, buffers will be applied individually to the internal boundaries.

5. Optional: Check the **Dissolve Result** option.
6. Name your output appropriately e.g. `Ecuador_AOI_Mask.shp`

> **NOTE:** Make sure your layer is in a projected coordinated system -- Working in geographically coordinated systems will produce buffers that are distorted and incorrect as distances are interpreted in degrees as opposed to meters.

> **[Figure 5: Creating the AOI Mask Layer]**

#### Step 3: Clip Datasets to the AOI buffer

The buffered national boundary is then used to set the extent of all analysis layers -- the forest as well as anthropogenic layers.

In QGIS,

- For Vector Layers: From the processing tool box, navigate to **Vector Overlay** > **Clip**.
- For raster layers: **GDAL** > **Raster Extraction** > **Clip Raster by Mask Layer**.

Parameters:

- Input Dataset: Dataset to clip.
- Mask Layer: `Ecuador_AOI_Mask.shp`
- Output: Save Appropriately

#### Step 4: Rasterize vector datasets (batchable)

Vector data types will be converted to raster formats in this step allowing combination in pixel-based analyses.

To rasterize vector datasets in QGIS;

**Processing** > **Toolbox** > **GDAL** > **Vector Conversion** > **Rasterize (Vector to Raster)**

Set the parameters as follows:

- Input layer: e.g. `Major_Roads_Ecuador.shp`
- Field to use for a raster value: leave empty and use "Burn-in value" instead.
- Burn-in value: Use a constant value e.g. 1
- Output extent: "Calculate from layer" > AOI raster i.e. `Ecuador_AOI_Mask.shp`
- Output raster size units: Georeferenced Units (Meters)
- Width / Height: use the same as AOI raster (or click "Match layer" if available) or set the actual value e.g. 30.00 in our case.
- NoData value to output bands: 0. This ensures binary outputs where 1 = feature and 0 = background
- Output CRS: Ensure this is set to the same projected coordinate system identified earlier. E.g. EPSG 32717
- Click on the **Advanced Parameters** to expand it.
  - Output data type: Int16 or Byte
  - Pre-initialize the output image with value: 0.00 (Important -- This step helps to create a clean binary layer; all values are 0 except those burned with the set value 1)

> **[Figure 6: Rasterization in QGIS]**

> **TIP:** As explained earlier, all the layers need to have the same spatial resolution. We resample all layers to match the resolution of the forest layer as this is the most important layer.

#### Step 5: Aligning the resolution and extent of data layers (optional)

This step validates that all rasters share the exact same pixel grid. Misalignment can cause errors in subsequent analysis steps.

In QGIS;

1. Choose a reference raster -- We will use the forest raster.
2. Click **Raster** on the main ribbon > **Align Rasters**
3. In the tool, add all other rasters as inputs by clicking on the + symbol.
4. Set the CRS to the project CRS.
5. Set the cell size (resolution in meters)
6. Set the extent by clicking **Calculate from Layer**
7. Set the resampling method to nearest neighbor for categorical data. For continuous data types like DEM set this to bilinear or cubic convolution resampling.
8. Click **OK** to run the analysis.

#### Step 6: Pre-validation (Optional)

A quick validation check can be performed to confirm that all raster layers are correctly aligned, consistently structured, and contain valid binary values.

The validation step could include:

- Visually toggling layers on / off to ensure alignment.
- Use the **Identify Tool** on the main tool ribbon to sample pixel values (Values should be 1 or 0 -- binary values)
- Clicking on the layer > **Properties** to check the CRS, extent and resolution and ensure everything is aligned.

> **CHECKPOINT:** By this point, we should have our core layers i.e. the forest and individual anthropogenic layers in the correct projected coordinate system, clipped to the AOI extent.

#### Step 7: Preparation of Ancillary Data Layers

Now that the core datasets are completed, we will work on supporting data layers that will be used to refine the primary forest logic.

**Creating the slope layer**

We will start by generating a slope raster (in degrees) from the elevation raster before reclassifying it further into a binary slope raster where;

- 1 = Steep slopes (Above a threshold e.g., 45 degrees in this case)
- 0 = gentler slopes below the threshold

This step creates an analysis-ready layer that will be integrated later in the primary forest finder logic analysis. To carry it out in QGIS,

- Input Data: Elevation raster and extent layer (`Ecuador_AOI_Mask.shp`)

To derive slope:

**Processing** > **Toolbox** > **GDAL** > **Raster Analysis** > **Slope**

- Input layer: `Ecuador DEM.tif` (Clipped to the AOI mask layer)
- Output measurement: Degrees.
- Output raster type: Float.
- Output: `Ecuador_Slope.tif`

> **NOTE:** We will then create binary layers using thresholds above which forest is considered naturally protected due to difficulty of access. Countries can modify the threshold to reflect local circumstances. In our example we will set the threshold to 45 degrees.

To future proof our analysis, we will create the gentle and steep mask layers concurrently. Navigate to the Raster Calculator by clicking **Processing** > **Toolbox** > **Raster Miscellaneous** > **Raster Calculator** and apply the following expression;

```
"Ecuador_Slope@1" >= 45
```

For the other parameters;

- Cell-size: Use the spatial resolution of the forest raster e.g. 30 m in our case.
- Output extent: AOI mask layer (`Ecuador_AOI_Mask.shp`)
- Output CRS: Defined CRS e.g. EPSG 32717
- Output: Save appropriately e.g. `Steep_Slope.tif`

**Interpretation of results**

The results of this step yields a continuous layer (0 to 1) which shows;

- 1 = Steep slope
- 0 = Gentle slope

> **[Figure 7: Creating the Slope Mask Layers]**

We will replicate the same process for the gentle slope mask layer. We will only change the expression as follows;

```
"Ecuador_Slope@1" < 45
```

Replicate all other parameters. We will label this as `Gentle_Slope_.tif`.

**Interpretation of results**

Similar to the previous step, we will now have a continuous layer (0 to 1) which shows;

- 1 = Gentle Slope
- 0 = Steep Slope

> **TIP:** This step is batchable.

**Preparation of the protected areas layer**

We will proceed to create the protected areas layer using the UNEP-WCMC's World database on Protected Areas (WDPA) dataset.

Ensure the layer is projected, clipped and aligned to the extent layer i.e. (`Ecuador_AOI_Mask.shp`).

We will apply four filters on the layer's attributes to derive the Protected Areas Mask namely;

1. **Protected areas by legal status** -- demarcates the legal standing of an area. We will only choose areas categorized as "Designated."
2. **IUCN category** -- Shows the conservation intent and permittable activities. We will limit our selection to categories with the highest levels of protection i.e. Ia - Strict Nature Reserve, Ib -- Wilderness Area and II -- National Park
3. **Designation Name** as UNESCO MAB Biosphere Reserve (globally recognized areas for biodiversity conservation)
4. **Status Year** -- Indicates the year of designation. In our case we opted for areas under protection for at least 30 years.

We will use the **Select by Expression** Tool. Navigate to **Processing** > **Toolbox** > **Vector** > **Selection by Expression Tool**

Once in the tool, click on the Abacus Icon to open the expression builder.

Paste the following expression:

```sql
"STATUS" = 'Designated'
AND "IUCN_CAT" IN ('Ia','Ib','II')
AND "STATUS_YR" IS NOT NULL
AND "STATUS_YR" > 0
AND "STATUS_YR" <= 1995
AND "DESIG_ENG" ILIKE '%biosphere%'
```

Rasterize the output into a binary raster as explained in earlier sections.

---

## 5.0. Analysis -- Applying the Primary Forest Finder

This section describes the analytical steps used to derive potential primary forests and generate the final thematic outputs.

### 5.1. Building the Anthropogenic Influence Mask Layer

The anthropogenic mask layer represents areas influenced by human activities including infrastructure, agriculture, settlement, mining or industrial land uses. This section of the workflow guides users in preparing an anthropogenic pressure layer by applying distance-based thresholds. It standardizes all human-influence datasets into a single binary raster (where 0 = undisturbed, 1 = anthropogenic influence).

**Required Inputs**

Although inputs vary by country, it is recommended to have at least the following layers;

- Linear Infrastructure e.g. roads, railway
- Built-up areas
- Agriculture
- Extent Reference -- rasterized AOI mask layer

> **NOTE:** All input layers must be binary raster layers aligned to the same projected, coordinate reference system, resolution (pixel size), spatial extent (buffered national boundary), data type (Byte) or Int (16) and the No Data Value explicitly set to 0.

> **CHECKPOINT:** The previous chapter details the preparation of analysis-ready rasters. In the case of our workflow, we have the following data layers;
> - `Major_roads.tif`
> - `Minor_roads.tif`
> - `Builtup.tif`
> - `Agriculture.tif`
> - `Ecuador_AOI_Mask.tif`

#### Step 1: Creating Distance (Proximity) Rasters -- Batchable Step

As elaborated earlier, the QGIS PFF workflow creates buffers around anthropogenic features -- which identifies disturbed forest areas.

> **TIP:** Raster Buffers vs Vector Buffers -- Rasters operate on a fixed pixel grid, so buffer distances must align precisely with that grid to avoid spatial distortions. On the other hand, vector buffers, while geometrically precise, do not preserve raster alignment when converted, often producing slivers, irregular boundaries, or misaligned pixels. Common approaches in raster buffering include distance-based operations or focal/neighborhood operations. The PFF workflow employs a distance-based buffering that calculates threshold distances from anthropogenic cells which results in concentric rings (buffers).

**Calculating Euclidean Distance in QGIS**

Navigate to **Processing** > **Toolbox** > **Raster analysis** > **Proximity (Raster Distance)**

Set the following parameters:

- Input raster layer: `Major_roads.tif`
- Values to be considered as "target" pixels: 1
- Distance units: Georeferenced coordinates.
- NoData value: 0 (or leave default)
- Max distance: Leave empty.
- Output data type: Float32.
- Output raster: `Distance_Major_Roads.tif`

Batchable Step -- Replicate this step for all other layers i.e., large/small roads/built-up and agriculture as depicted in Figure 8 below. You can run these calls individually or use Batch Processing option (More on the batch processing is described in the annex).

> **[Figure 8: Calculating Euclidean Distance in QGIS]**

You should now have the following distance layers:

- `Distance_Major_Roads.tif`
- `Distance_Minor_Roads.tif`
- `Distance_Agriculture.tif`
- `Distance_Builtup.tif`

#### Step 2: Apply Distance Thresholds (Buffers)

> **TIP:** It is good practice to use locally defined thresholds that reflect the country's ecological conditions and local/expert knowledge.

Next, we set thresholds that define what counts as 'anthropogenic influence.'

In QGIS,

Navigate to the **Processing** > **Toolbox** > **Raster** > **Raster Calculator**.

Apply the following expression (Using the example of major roads) as shown in Figure 9:

```
"Distance_Major_Roads@1" <= 1500
```

> **[Figure 9: Buffering Rasters]**

- Set the extent: (Rasterized AOI mask) - `Ecuador_AOI_Mask.tif`
- Set the appropriate cell size and resolution.
- Output = `Major_Roads_Buffer.tif`
- Confirm the CRS, extent and resolution are the same for all layers.

**Interpretation of the results**

Running the analysis results into a continuous binary raster (0-1)

Where 1 = pixels within major roads influence zone and 0 = outside.

> **[Figure 10: Buffer around anthropogenic feature (roads)]**

> **[Figure 11: Buffer Network Around Roads]**

> **TIP:** Validate the Raster Calculator has handled the binary values correctly as follows: Right Click Layer > Properties > Information > Bands and confirm the min and max values are set to 0 and 1 respectively. No-Data should be 0.

Replicate this process for all the anthropogenic layers either manually or using the Batch Processing Option.

Expected outputs:

- `Major_Roads_Buffer.tif`
- `Minor_Roads_Buffer.tif`
- `Agriculture_Buffer.tif`
- `Builtup_Buffer.tif`

#### Step 3: Combine all anthropogenic buffers

We will combine the individual buffer layers into one raster layer that delimits anthropogenic influence where:

- 1 = within ANY anthropogenic buffer (road, built-up, agriculture)
- 0 = outside all buffers

We will use the Raster Calculator to combine these layers either using a logical OR operation or by summing the binary inputs.

Replicate the following expressions;

```
("Major_Roads_Buffer@1" + "Minor_Roads_Buffer@1" + "Agriculture_buffer@1" + "Builtup_buffer@1") >= 1
```

Or using this expression:

```
("Major_Roads_Buffer@1" = 1) OR ("Minor_Roads_Buffer@1" = 1) OR ("Agriculture_Buffer@1" = 1) OR ("Builtup_Buffer@1" = 1)
```

- Set the CRS, Extent and cell size appropriately.
- Data Type: Byte / Int16
- Output: `Anthropogenic_mask.tif`

**Interpretation:**

- 1 = Disturbed
- 0 = No anthropogenic influence

> **TIP:** Change the symbology to visually inspect the buffer network.

> **[Figure 12: Anthropogenic Mask Layer]**

---

### 5.2. Building Forest Masks

#### 5.2.1. Forest Raster in the AOI Buffer

As with the other anthropogenic layers, we will delimit the forest raster to the processing AOI.

> **NOTE:** The forest dataset used should reflect the natural forests within the country, excluding plantation forests and forests within agroforestry systems.

- Output: `Forest_Buffer.tif` where 1 = forest and 0 = non-forest.
- NoData: 0
- Extent: Same as `Ecuador_AOI_Mask.tif`
- Set the CRS and resolution appropriately.

> **NOTE:** Keep the original extent of the forest (without the buffer) for areal computation in later stages.

The output of this step will be the input for subsequent forests masks.

#### 5.2.2. Forest Outside Anthropogenic Influence

This is our first tier of primary forest -- all forests that are free from all anthropogenic influence.

**Data Inputs**

- **Forest Mask:** Binary raster (0 = non-forest, 1 = forest) i.e. `Forest_Buffer.tif`. Data Type: Int16 or Byte. Aligned to same CRS, extent and resolution.
- **Anthropogenic Impact Layer:** Binary raster (0 = no impact, 1 = anthropogenic impact) i.e. `Anthropogenic_mask.tif`. Data Type: Int16 or Byte. Aligned to the same CRS, extent and resolution.

For a pixel to be classified as Undisturbed Forest, it must be a forest pixel AND it must be outside the anthropogenic buffer.

To apply this logic, we will use the Raster Calculator. Apply either expression;

```
(("Forest_Buffer@1" = 1) AND ("Anthropogenic_mask@1" = 0)) * 1
```

Alternatively;

```
"Forest_Buffer@1" * ("Anthropogenic_mask@1" = 0)
```

- Output = `Forest_Undisturbed.tif`
- Data type = Byte / Int16
- Set the CRS, Resolution and Extent appropriately.

**Interpretation:**

- 1 = forest outside anthropogenic buffers (First Primary Candidate class)
- 0 = everything else

> **[Figure 13: Primary Forest Tier 1]**

#### 5.2.3. Forests inside Anthropogenic Influence

We will now identify all the forest pixels that fall within defined anthropogenic influence zones. This layer will subsequently be used to recover forests via natural and legal protection approaches.

**Data Input:**

- Anthropogenic Mask Layer i.e. `Anthropogenic_mask.tif`
- Forest Binary Layer i.e. `Forest_Buffer.tif`
- AOI extent: `Ecuador_AOI_Mask.tif`

To identify forests inside human influence zones, we will perform a pixel-wise AND operation using the Raster Calculator. We want all the pixels that are categorized as forest thus Forest = 1 and Anthropogenic Influence = 1.

Paste either expression;

```
("Forest_Buffer@1" = 1) AND ("Anthropogenic_mask@1" = 1) * 1
```

Or:

```
"Forest_Buffer@1" * ("Anthropogenic_mask@1" = 1)
```

> **[Figure 14: Forest in Anthropogenic Area Mask Creation]**

- Output: `Forest_Anthropogenic.tif`
- Data Type: Byte or UInt16
- NoData: 0
- Layer extent, resolution and extent set appropriately.

> **TIP:** Change the symbology or use the Identify Tool to visually inspect the disturbed forests visually comparing with the anthropogenic mask to confirm alignment.

**Interpretation:**

- 1 = Disturbed Forest
- 0 = Everything else

> **[Figure 15: Forest in Anthropogenic Mask Layer]**

This layer will be used as input of the proceeding analysis.

---

### 5.3. Integrating Ancillary Layers

#### 5.3.1. Forest in Anthropogenic zone and steep slopes

This step identifies forest areas that fall within anthropogenic influence but are also located on steep slopes. To create this second tier of primary forest, we assume that forests may be protected from disturbance due to terrain difficulty or limited accessibility.

We earlier created two binary slope layers in the Data Preparation Section.

In this first part we will use `Steep_Slope.tif` which labels all pixels with steep slopes as 1 and 0 to gently sloping areas. We will also use the `Forest_Anthropogenic.tif` created in the previous section.

We will classify a pixel as forest in steep anthropogenic zone if Forest_anthropogenic = 1 AND Steep Slope = 1.

To apply this logic in the Raster Calculator, apply either expression:

```
"Forest_anthropogenic@1" * ("Steep_Slope_@1" = 1)
```

Alternatively, we can use logical operator AND;

```
("Forest_anthropogenic@1" = 1) AND ("Steep_Slope_@1" = 1)
```

- Output = `Forest_Anthro_Steep.tif`
- Data Type = Byte or Int16
- NoData = 0
- Match CRS, extent and resolution to the rest of your layers.

**Interpretation:**

- 1 = Forest within the anthropogenic buffer but in steep, inaccessible terrain.
- 0 = All other areas.

> **[Figure 16: Forest in Steep Anthropogenic Areas]**

> **[Figure 17: Primary Forest Tier Two]**

#### 5.3.2. Incorporating Protected Areas

Tier three of the primary forest logic works on the assumption that forests in well-managed legally protected areas are likely to be undisturbed long-term even when they are within anthropogenic layers that are easily accessible.

**Required Binary Inputs:**

- Forest in anthropogenic area: `Forest_Anthropogenic.tif`
- Gentle Slope Mask: `Gentle_Slope.tif`
- Protected areas mask: `PA_mask.tif`

All three must share the same CRS, resolution, extent and NoData should be 0.

Paste either expression in the Raster Calculator:

```
"Forest_Anthropogenic@1" * "pa_mask@1" * ("Gentle_Slope@1" = 1)
```

Alternatively, we can use logical AND operator;

```
(("Forest_Anthropogenic@1" = 1) AND ("Gentle_Slope@1" = 1) AND ("PA_Mask@1" = 1)) * 1
```

- Output: `Forest_anthro_gentle_PA.tif`
- Data type: Byte / Int16
- NoData value: 0
- Match the CRS, resolution and extent with other processing layers.

**Interpreting the results:**

- 1 = forest in anthropogenic context, gentle sloping, but in a strict, long-term PA.
- 0 = Anything else

> **[Figure 18: Primary Forest Tier 3]**

---

### 5.4. Building the Primary Forest Layer

By now you should have three primary forest candidate layers that we will combine into the final primary forest layer;

1. Forest Undisturbed
2. Forest in steep anthropogenic areas
3. Forest in gently, protected anthropogenic areas.

In QGIS, navigate to the Raster Calculator;

We will apply this expression:

```
("Forest_Undisturbed@1" + "Forest_Anthro_steep@1" + "Forest_anthro_gentle_PA@1") >= 1
```

Optionally we can use logical operators:

```
("Forest_Undisturbed@1" = 1) OR ("Forest_Anthro_steep@1" = 1) OR ("Forest_anthro_gentle_PA@1" = 1)
```

- Output: `Primary_Forest_Candidate.tif`
- Data Type: Byte / Int16

**Results:** This results in a continuous raster (0-1) where 1 = potential primary forest pixels and 0 = everything else.

> **TIP:** Symbolizing the layers and overlaying with the anthropogenic buffers can help validate the accuracy of your analysis.

> **[Figure 19: Primary Forest Candidate]**

> **[Figure 20: Primary Forest Candidate]**

---

### 5.5. Assessing Spatial Continuity

---

## Annex A

### A.1. Best practices for Working with Raster Data

The Primary Forest Workflow relies extensively on raster data and therefore requires input layers that are consistent, clean, and spatially aligned. Mismatches in data type, spatial resolution, extent, or coordinate reference system can lead to processing errors or inaccurate results.

This section outlines essential considerations and best practices for preparing and working with raster datasets within the workflow.

#### Performance Optimization

Raster data has significant demands for storage and processing resources. Working with large, high-resolution rasters for repeated analyses can slow down the GIS software being used. Some considerations include;

**Building pyramids**

Raster pyramids are reduced-resolution representations of a raster dataset used to improve display performance and navigation at smaller map scales. They consist of multiple down sampled copies of the original raster, which QGIS automatically selects based on the current zoom level.

> **NOTE:** Building pyramids may increase disk usage and, for some formats, may modify the underlying raster file. It is good practice to create a backup copy of the original dataset before generating pyramids.

To build pyramids in QGIS: Right-click the raster layer > **Properties** > **Pyramids** tab, then select the desired pyramid levels and resampling method.

**Using Virtual Rasters / Catalog**

Virtual Rasters (VRTs) are GDAL-native text (XML) files that define how multiple raster datasets are accessed or combined on the fly, without physically merging them into a new raster file. Pixel values are generated only when required for visualization or analysis, which helps reduce disk usage.

When working with multiple raster files, a VRT can be used to reference and organize them as a single logical dataset (QGIS documentation). VRTs are particularly useful when disk space is limited or when performing temporary or exploratory analyses.

In QGIS, VRTs can be created as follows: **Processing** > **Toolbox** > **GDAL** > **Raster miscellaneous** > **Build virtual raster**.

**Data Storage and Compression**

*Applying compression* -- Lossless compression methods are recommended when working with raster data, as they reduce file size without altering pixel values. LZW (Lempel-Ziv-Welch) is one of the most commonly used lossless compression options for GeoTIFF files.

Compression can be applied through the **Advanced Parameters** > **Compression** settings when exporting or saving raster outputs.

*Limiting raster inputs to the analysis AOI* -- Clipping large raster datasets to the required area of interest (AOI) can significantly reduce processing time, disk usage, and memory consumption during analysis.

#### Coordinate Reference System (CRS) and Resolution Management

Before starting any processing, it is essential to verify the coordinate reference system (CRS) of all input raster layers. This can be checked under **Layer Properties** > **Information** in QGIS. Rasters with different CRSs cannot be accurately compared, combined, or analyzed without reprojection.

**Choosing an appropriate CRS**

Selecting the correct CRS is critical for ensuring spatial accuracy. An inappropriate CRS choice may lead to distortion, misalignment, and inaccurate distance, area, or slope calculations. The choice of CRS should be guided by the geographic extent of the study area, the type of analysis being performed, data compatibility, and the intended use of the outputs.

**Table 3: Summary of Coordinate Reference Systems**

| Coordinate System | Characteristics | Applications |
|---|---|---|
| Geographic Coordinate Systems (GCS) | Latitudes and Longitudes expressed in degrees e.g., WGS84 | Global-scale mapping, GPS data collection, Web mapping applications |
| Projected Coordinate Systems | X and Y coordinates are represented in linear units (m/km/feet). Flattens 3D earth onto 2D plane. The PCS sub-type to be used depends on the purpose. | Conformal projections like Web Mercator preserve angles/shape -- used for navigation and detailed mapping. Equal Area projections like Lambert Azimuthal Equal Area (Europe) preserve area -- best for area calculations and statistical mapping. Equidistant Projections like Azimuthal Equidistant preserve distance -- best when distance calculations on specific directions are required. |

To reproject rasters, the Warp tool in QGIS (**GDAL** > **Raster projections** > **Warp (reproject)**) allows reprojection of virtual rasters.

#### Data Properties

**Understanding Raster Data Types**

Different raster data types represent and store pixel values differently.

To verify the data type in a raster file, right-click the raster layer > **Properties** > **Information** > **Data Type**

**Table 4: Summary of Data Types used in GIS**

| Data Type | Characteristics | Common Uses |
|---|---|---|
| Byte (UInt8) | Eight-bit unsigned integer (0-255). Smallest and fastest processing. | Binary rasters and masks. Classification rasters (when <= 255). |
| Int8 | 8-bit signed integer (-128 to 127). Smaller storage requirements. | Simple classified/categorical rasters |
| Int16 | 16-bit signed integer (-32768 to 32767). Supports negative values. | Count Data / DEMs |
| UInt16 | 16-bit unsigned integer (0-65,535). Only positive integers. | Classification rasters (>=255 classes) |
| UInt32 / Int32 | 32 bits unsigned/signed respectively. Very large range and file sizes. | Exceptionally large ranges e.g. count data (rarely ever used) |
| Float32 | Decimal precision. | Continuous surfaces: Temperature, precipitation, NDVI, slope, distance rasters |
| Float64 | Scientific high precision. Large and slow to process. | Scientific calculations |

To set data type in QGIS, when exporting a raster: Right-click raster > **Export** > **Save As** and define the data type.

> **TIP:** The Translate tool also allows conversion between data types.

**Tips when choosing the data types to use:**

- Always match the data type to the data nature e.g., float for continuous data.
- Use the smallest appropriate type e.g., Int16/Int32 has different memory and processing requirements.
- Unsigned types for non-negative data.
- Apply compression when possible.
- Always verify after any conversion to ensure data is being handled as expected.

#### Resolution

When combining rasters, it is important that they align perfectly with each other to avoid computational errors. Always verify the pixel origin, grid alignment, extent, pixel size (resolution) and pixel count (width, height) and CRS.

In QGIS, right-clicking the layers > **Properties** > **Information** will show these properties.

If different, the **Align Raster Tool** from the Raster Tools can be used.

**Working with mixed resolution rasters**

When working with rasters of different resolutions; virtual rasters (VRTs) explained earlier are a viable option to create uniform temporary layers for visualization.

When analysis is required, resample all inputs to a common resolution appropriate for the analysis scale.

#### Resampling

Resampling is applied when rasters must match resolution, alignment, or coordinate reference system for pixel-sensitive analyses. The type of resampling method depends on the data type.

- Use **Nearest Neighbor** for categorical rasters e.g. landcover.
- **Bilinear** is typically used for continuous surfaces e.g., DEM.
- **Cubic convolution** for smooth, attractive images of continuous surfaces for visualization.
- **Average/Mode** is best for aggregation or when downscaling.

> **WARNING:** Resampling should be used carefully as it modifies raster values and may affect analysis results.

#### Batch processing

In the event where multiple, repetitive analyses are to be conducted -- batch processing is a viable option to reduce overhead, minimize user error and ensure consistency.

Batch processing is implemented by right-clicking the tool and choosing the **Execute as Batch process** option. The parameters are then set as usual.

#### Handling NoData

No data values represent missing or invalid data in a raster grid. In most GIS systems, NoData values are assigned numeric values to distinguish them from other cells. Common values include -9999, -999, -32768 or -3.4e38 depending on the dataset and software used.

To know the No Data value assigned to your dataset in QGIS, clicking the **Layer properties** > **Information Tab** > **Dimensions Section** should show the No data values.

**Visualizing No Data cells**

QGIS automatically renders No data values as transparent pixels. This can be altered by setting the Transparency settings in the layers' symbology.

**Raster operations involving No data**

When particularly working with raster calculator operations, No Data pixels can result in unexpected outputs. Consequently, it is important to deal with these values appropriately. Multiple solutions can be applied namely;

- **Interpolation:** The Fillnodata tool in QGIS under **GDAL** > **Raster Analysis** fills no data values by interpolating from surrounding data.
- **Conversion:** When the raster has an undefined No data value or you want to change the no data value, Translation (Format conversion) can be applied. To translate a raster in QGIS: Go to **Processing** > **Toolbox** > **GDAL** > **Raster conversion** > **Translate**. Once the input and output files are defined, clicking on the NoData field in the Advanced Parameters section allows you to set a specified no data value.
- **Replacing no data values:** In cases where a specific no data value is needed, for example in the case of PFF binary rasters, the Raster calculator can be used. Expressions like `("raster@1" > 0) * "raster@1" / (("raster@1" > 0) * 1)` can be used to map unwanted values to 0/0.

---

### A.2. Default Global Datasets

While national datasets provide the most authoritative results during computation, global datasets are a viable option when national datasets are unavailable or non-representative.

#### Landcover Products

**Table 5: Summary of global landcover products**

| Product | Measurement method | Geographical coverage | Spatial resolution | Thematic resolution | Temporal coverage | Reported accuracy | Link |
|---|---|---|---|---|---|---|---|
| ESA-CCI-LC | Based on AVHRR, SPOT, PROBA-V and Sentinel-3 satellite imagery | Global | 300 m | 22 classes | Every year from 1992 to 2020 | 73% | http://maps.elie.ucl.ac.be/CCI/viewer/index.php |
| MODIS Land Cover (MCD12Q1 v061) | MODIS sensors onboard the Terra and Aqua satellites | Global | 500 m | 17 classes | Every year from 2001 to 2021 | Not available | https://lpdaac.usgs.gov/products/mcd12q2v061/ |
| Copernicus Global Land cover (CGLS-LC100) | PROBA-V | Global | 100 m | 23 classes | Every year from 2015 to 2019 | 80% | https://land.copernicus.eu/global/products/lc |
| ESA World Cover | Sentinel-1 and Sentinel-2 data | Global | 10 m | 11 classes | Every year from 2020 to 2021 | 75% | https://esa-worldcover.org/en |
| Dynamic World | Sentinel-2 | Global | 10 m | 9 classes | Every 2-5 days from 2015 | 73.8% | https://dynamicworld.app/ |
| ESRI Land Use Land Cover | Sentinel-2 | Global | 10 m | 9 classes | Every year from 2017 to 2022 | 85% | https://livingatlas.arcgis.com/landcover/ |
| GlobLand30 | Landsat 4 and 7 | Global | 30 m | 10 classes | 2000 and 2010 only | 83% | http://glc30.tianditu.com |
| GLAD LCLU Change | Landsat 5, 7, and 8 scenes | Global | 30 m | 5 classes | 2000 and 2020 only | Above 85% | https://glad.umd.edu/dataset/GLCLUC2020 |
| CORINE Land Cover | Landsat 5, 7, 8, SPOT 4/5, IRS P6, and Sentinel 2 | Europe | 100 m | 44 classes | 1990, 2000, 2006, 2012 and 2018 only | 85% | https://land.copernicus.eu/pan-european/corine-land-cover |
| CLC+ Backbone | Sentinel-2 | Europe | 10 m (0.5 ha vector) | 11 (18) classes | 2018, 2021 in production | 92% | https://land.copernicus.eu/pan-european/clc-plus/clc-backbone |
| UK Land Cover Maps | Landsat 5, 7, 8, SPOT 4/5, IRS P6, and Sentinel 2 | UK | 25 m (0.5 ha vector) | 23 classes | 1990, 2000, 2007, 2015, 2017, 2018, 2019, 2020, 2021 | 79% | https://www.ceh.ac.uk/data/ukceh-land-cover-maps |
| MAPBIOMAS | Satellite imagery | Amazonia | 30 m | 19 classes | Every year from 1985 to 2022 | Above 80% | https://amazonia.mapbiomas.org/en |
| ICIMOD HKH Land Cover | Landsat and Sentinel-2 | Hindu Kush Himalaya | 30 m | 9 classes | Every year from 2000 to 2021 | 81% | http://rds.icimod.org/Home/DataDetail?metadataId=1972511 |
| NALCMS | Landsat 7-8, MODIS | North America, Canada, Mexico | 30 m / 250 m | 19 classes | 2005, 2010, 2015, 2020 | 69% | http://www.cec.org/north-american-land-change-monitoring-system/ |
| National Land Cover Database | Landsat TM | United States | 30 m | 20 classes | 1992, 2001, 2006, 2011, 2013, 2016, 2019, 2021 | 78% | https://www.mrlc.gov/ |
| Catastro de los Recursos Vegetacionales Nativos de Chile | Aerial photography, SPOT 5 and FORMOSAT-2 | Chile (mosaics of 15 regions) | -- | -- | 1997, 2001, 2007 and 2011 | -- | https://sit.conaf.cl/ |
| Dynamic Land Cover Dataset | MODIS EVI composites | Australia | 250 m | 30 classes | Every two years since 2001 (2001-2015) | None | https://www.agriculture.gov.au/abares/aclump/land-cover/dynamic-land-cover |

#### Digital Elevation Models (DEMs)

**Table 6: Global Elevation Datasets**

| Product | Measurement method | Geographical coverage | Spatial resolution | Thematic resolution | Temporal coverage | Reported accuracy | Link |
|---|---|---|---|---|---|---|---|
| SRTM DEM | Radar interferometry (C-band SAR) | Near-global (60N-56S) | 30 m (1 arc-second) | Elevation (meters) | 2000 | ~10 m vertical RMSE | https://www.usgs.gov/centers/eros/science/usgs-eros-archive-digital-elevation-shuttle-radar-topography-mission-srtm-non |
| ALOS World 3D (AW3D30) | Optical stereo imagery | Global | 30 m | Elevation (meters) | 2006-2011 | ~5 m vertical RMSE | https://www.eorc.jaxa.jp/ALOS/en/dataset/aw3d30/aw3d30_e.htm |

#### Protected Areas

**Table 7: Global Protected Areas Datasets**

| Product | Measurement method | Geographical coverage | Spatial resolution | Thematic resolution | Temporal coverage | Reported accuracy | Link |
|---|---|---|---|---|---|---|---|
| WDPA (World Database on Protected Areas) | Compiled national reporting | Global | Vector (polygon) | Protected area categories (IUCN) | Updated monthly | Varies by country | https://data-gis.unep-wcmc.org/portal/home/item.html?id=1919c32890074ce5a589a1a99b48994b |

#### Transportation datasets

**Table 8: Summary of Global Transport Datasets**

| Product | Measurement method | Geographical coverage | Spatial resolution | Thematic resolution | Temporal coverage | Reported accuracy | Link |
|---|---|---|---|---|---|---|---|
| OpenStreetMap (OSM) | Crowdsourced GPS and digitization | Global | Vector (line) | Road classes and attributes | Continuously updated | Variable; high in many regions | https://www.openstreetmap.org/ |
| GRIP4 (Global Roads Inventory Project) | Integrated national and global sources | Global | Vector (line) | Major road classes | ~2018 | Moderate, generalized | https://www.globio.info/download-grip-dataset |

#### Administrative Boundaries

**Table 9: Global Administrative Datasets**

| Product | Measurement method | Geographical coverage | Spatial resolution | Thematic resolution | Temporal coverage | Reported accuracy | Link |
|---|---|---|---|---|---|---|---|
| GAUL (Global Administrative Unit Layers) | National official sources harmonized | Global | Vector (polygon) | Admin levels 0-2 | Periodic updates | High at national level | https://data.apps.fao.org/catalog/organization/administrative-boundaries-fao |

#### Built-up Areas / Human Settlements

**Table 10: Summary of Urban Area Datasets**

| Product | Measurement method | Geographical coverage | Spatial resolution | Thematic resolution | Temporal coverage | Reported accuracy | Link |
|---|---|---|---|---|---|---|---|
| GHSL Built-up Grid | Optical imagery (Landsat, Sentinel) | Global | 10-30 m | Built-up presence/density | 1975-2018 (epochs) | >85% overall accuracy | https://human-settlement.emergency.copernicus.eu/ghs_bu.php |
| World Settlement Footprint (WSF) | SAR (Sentinel-1) + optical | Global | 10 m | Built-up extent | 2015-2019 | ~90% overall accuracy | https://geoservice.dlr.de/web/maps/eoc:wsf2019 |

#### Cropland / Agriculture

**Table 11: Global Cropland Datasets**

| Product | Measurement method | Geographical coverage | Spatial resolution | Thematic resolution | Temporal coverage | Reported accuracy | Link |
|---|---|---|---|---|---|---|---|
| ESA World Cover | Sentinel-1 & Sentinel-2 | Global | 10 m | Cropland class | 2020-2021 | ~75-85% (class-dependent) | https://esa-worldcover.org/en |
| GFSAD (Cropland Extent) | Multi-sensor optical | Global | 30 m | Cropland (binary) | ~2010-2015 | ~85% | https://www.usgs.gov/apps/croplands/gfsadce30info |
| MODIS Land Cover (MCD12Q1) | MODIS optical | Global | 500 m | Land cover classes | Annual (2001-present) | ~75% | https://lpdaac.usgs.gov/products/mcd12q2v061/ |

---

## Annex B

### B.1 Batch Processing and Automation

Batch processing is an effective option when carrying out repetitive, rule-based operations where inputs change but remain consistent. Batch processing allows for efficient, consistent and shortened data processing.

In the Primary Forest Finder, the following steps can be batched:

- Clipping analysis layers to the AOI
- Reprojecting layers
- Rasterization
- Generation of proximity layers
- Thresholding distance rasters into binary buffers
- Aligning rasters to the reference raster
- Data type conversion

**Batch Processing in QGIS**

**Execute as Batch Process**

This is best when one needs to run one tool repeatedly on a list of inputs.

1. Navigate to the Processing Toolbox (**Processing** > **Toolbox**)
2. Locate the desired tool. Right-click on the tool and select **Execute as Batch Process**.
3. Set the parameters as you would normally before running the analysis.

> **[Figure 21: Batch Processing in QGIS]**

**Graphical Modeler**

The QGIS graphical modeler allows the creation of custom workflows by chaining multiple processing algorithms together. Models are best if the same logic needs to be applied across different temporal or geographical scales.

To create a model in QGIS,

1. Navigate to **Processing** > **Graphical Modeler**
2. Design the model by adding inputs, algorithms and outputs.
3. Connecting the components defines the processing sequence.
4. Save the model for future use / reuse.

> **[Figure 22: QGIS Model Builder]**

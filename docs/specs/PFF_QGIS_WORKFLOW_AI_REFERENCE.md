# Primary Forest Finder (PFF) QGIS Workflow --- AI Reference

This document describes the full QGIS workflow used to derive **primary
forest candidate areas** based on a combination of forest cover,
anthropogenic influence, slope, and protected areas.

It is structured so that AI coding tools (GitHub Copilot, Cursor, Claude
Code, etc.) can read it and generate automation scripts in **Python /
PyQGIS / GDAL**.

------------------------------------------------------------------------

# 1. Conceptual Model

Primary forest candidates are derived using three logical tiers:

1.  Forest outside anthropogenic influence
2.  Forest inside anthropogenic areas but protected by steep slopes
3.  Forest inside anthropogenic areas but legally protected

The final primary forest map is the union of these tiers, optionally
filtered for spatial connectivity.

------------------------------------------------------------------------

# 2. Required Inputs

  Dataset                   Type     Description
  ------------------------- -------- ----------------------------------------
  Forest extent             Raster   Binary raster (1=forest, 0=non‑forest)
  Roads                     Vector   Major and minor roads
  Built‑up areas            Vector   Settlements or urban footprint
  Agriculture               Vector   Cropland extent
  DEM                       Raster   Used to derive slope
  Protected areas           Vector   WDPA or national equivalent
  Administrative boundary   Vector   Defines AOI

------------------------------------------------------------------------

# 3. Data Requirements

## CRS

All layers must use the **same projected CRS in metres**.

Example: EPSG:32717

Never use geographic CRS (EPSG:4326) for distance calculations.

## Raster Grid Consistency

All rasters must share:

-   identical resolution
-   identical extent
-   identical pixel alignment

Forest raster is used as the **reference grid**.

## Binary Convention

Binary rasters must follow:

1 = presence\
0 = absence\
NoData = 0

------------------------------------------------------------------------

# 4. Data Preparation

## Reproject datasets

Tools: - native:reprojectlayer - gdal:warpreproject

## Create AOI buffer

Tool: - native:buffer

Parameters: - distance = 2000 m - dissolve = true

## Clip datasets

Vector: - native:clip

Raster: - gdal:cliprasterbymasklayer

## Rasterize vectors

Tool: - gdal:rasterize

Parameters: - burn value = 1 - nodata = 0 - datatype = Byte - resolution
= forest raster resolution

Outputs: roads_major.tif roads_minor.tif builtup.tif agriculture.tif
protected.tif

## Align rasters

Tool: - native:alignrasters

Reference raster: forest raster

------------------------------------------------------------------------

# 5. Ancillary Layers

## Slope

Tool: gdal:slope

Output: slope.tif

## Slope classes

Steep: "slope \>= 45"

Gentle: "slope \< 45"

Tool: gdal:rastercalculator

------------------------------------------------------------------------

# 6. Anthropogenic Influence

Datasets used: - roads - built‑up - agriculture

## Distance rasters

Tool: gdal:proximity

Outputs: dist_roads_major.tif dist_roads_minor.tif dist_builtup.tif
dist_agriculture.tif

## Distance thresholds

Example:

major roads \<= 1500 m\
minor roads \<= 1000 m\
built‑up \<= 2000 m\
agriculture \<= 1000 m

Example expression:

dist_major_roads \<= 1500

Outputs: major_roads_buffer.tif minor_roads_buffer.tif
builtup_buffer.tif agriculture_buffer.tif

## Combine anthropogenic buffers

Expression:

(major_roads_buffer + minor_roads_buffer + builtup_buffer +
agriculture_buffer) \>= 1

Output: anthropogenic_mask.tif

Meaning: 1 = anthropogenic influence\
0 = no influence

------------------------------------------------------------------------

# 7. Forest Masks

## Forest outside anthropogenic influence

forest == 1 AND anthropogenic_mask == 0

Output: forest_undisturbed.tif

## Forest inside anthropogenic influence

forest == 1 AND anthropogenic_mask == 1

Output: forest_anthropogenic.tif

------------------------------------------------------------------------

# 8. Tier 2 --- Steep slope forests

forest_anthropogenic AND steep_slope

Output: forest_anthro_steep.tif

------------------------------------------------------------------------

# 9. Tier 3 --- Protected forests

forest_anthropogenic AND gentle_slope AND protected_mask

Output: forest_anthro_gentle_pa.tif

------------------------------------------------------------------------

# 10. Combine candidate layers

tier1 OR tier2 OR tier3

Output: primary_forest_candidate.tif

------------------------------------------------------------------------

# 11. Connectivity filtering

Goal: remove isolated forest pixels.

Possible tools: - focal statistics - gdal:sieve

Output: primary_forest_final.tif

------------------------------------------------------------------------

# 12. Known Gotchas

## CRS mismatch

Buffers calculated in geographic CRS will produce incorrect distances.

Always use projected CRS.

## Raster misalignment

All rasters must have identical: - extent - resolution - pixel origin

## NoData propagation

NoData should be set to 0.

## Binary validation

Binary rasters should contain only values 0 and 1.

------------------------------------------------------------------------

# Workflow Order

prepare datasets\
→ rasterize vectors\
→ align rasters\
→ distance rasters\
→ threshold buffers\
→ anthropogenic mask\
→ forest masks\
→ tier1/tier2/tier3\
→ combine tiers\
→ connectivity filter

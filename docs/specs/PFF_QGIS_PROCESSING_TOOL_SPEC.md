# PFF_QGIS_PROCESSING_TOOL_SPEC.md

Primary Forest Finder --- QGIS Processing Toolbox Tool Specification

This document defines how the Primary Forest Finder workflow should be
implemented as a set of **QGIS Processing Toolbox tools**.

The goal is to provide a clear specification so Python/PyQGIS scripts
can be generated automatically and remain maintainable across QGIS
versions.

------------------------------------------------------------------------

# 1. Toolbox Structure

Processing Toolbox group:

Primary Forest Finder

Tools:

1.  Validate Inputs
2.  Prepare Datasets
3.  Build Anthropogenic Mask
4.  Run Primary Forest Finder
5.  Connectivity Filter

Each tool performs a clearly defined stage of the workflow.

------------------------------------------------------------------------

# 2. Tool 1 --- Validate Inputs

Purpose: Ensure that datasets meet required conditions before
processing.

Inputs:

forest_raster roads_major_vector roads_minor_vector builtup_vector
agriculture_vector protected_areas_vector dem_raster aoi_boundary_vector

Validation checks:

CRS consistency across all layers

Raster resolution consistency

Binary raster validation:

values must be 0 or 1

Projected CRS requirement (units must be meters)

Outputs:

validation_report.txt

If validation fails the workflow should stop.

------------------------------------------------------------------------

# 3. Tool 2 --- Prepare Datasets

Purpose: Prepare datasets for raster-based analysis.

Inputs:

forest_raster (reference grid) roads_major_vector roads_minor_vector
builtup_vector agriculture_vector protected_areas_vector dem_raster
aoi_boundary_vector

Parameters:

AOI buffer distance (default = 2000 m)

Processing steps:

1.  Reproject all layers to forest raster CRS
2.  Buffer AOI boundary
3.  Clip datasets to buffered AOI
4.  Rasterize vectors
5.  Align rasters to forest raster grid

Recommended algorithms:

native:reprojectlayer native:buffer native:clip
gdal:cliprasterbymasklayer gdal:rasterize native:alignrasters

Outputs:

roads_major_raster roads_minor_raster builtup_raster agriculture_raster
protected_raster dem_aligned forest_aligned

------------------------------------------------------------------------

# 4. Tool 3 --- Build Anthropogenic Mask

Purpose: Construct anthropogenic influence raster.

Inputs:

roads_major_raster roads_minor_raster builtup_raster agriculture_raster

Parameters:

roads_major_distance roads_minor_distance builtup_distance
agriculture_distance

Processing steps:

1.  Compute distance rasters
2.  Apply distance thresholds
3.  Combine masks

Recommended algorithms:

gdal:proximity gdal:rastercalculator

Outputs:

dist_roads_major dist_roads_minor dist_builtup dist_agriculture

roads_major_buffer roads_minor_buffer builtup_buffer agriculture_buffer

anthropogenic_mask

------------------------------------------------------------------------

# 5. Tool 4 --- Run Primary Forest Finder

Purpose: Generate candidate primary forest layer.

Inputs:

forest_raster anthropogenic_mask protected_raster dem_aligned

Parameters:

slope_threshold (default = 45)

Processing steps:

1.  Calculate slope
2.  Create steep and gentle slope masks
3.  Identify forest outside anthropogenic influence
4.  Identify forest inside anthropogenic influence
5.  Generate tier2 and tier3 forests
6.  Combine tiers

Recommended algorithms:

gdal:slope gdal:rastercalculator

Outputs:

steep_slope gentle_slope

forest_undisturbed forest_anthropogenic

forest_anthro_steep forest_anthro_protected

primary_candidate

------------------------------------------------------------------------

# 6. Tool 5 --- Connectivity Filter

Purpose: Remove isolated forest pixels.

Inputs:

primary_candidate

Parameters:

minimum_patch_size

Processing options:

gdal:sieve or focal statistics

Outputs:

primary_forest_final

------------------------------------------------------------------------

# 7. Parameter Defaults

Recommended defaults:

roads_major_distance = 1500 roads_minor_distance = 1000 builtup_distance
= 2000 agriculture_distance = 1000

slope_threshold = 45

minimum_patch_size = user defined

------------------------------------------------------------------------

# 8. Intermediate Outputs

Tools should optionally export intermediate layers for debugging:

anthropogenic_mask forest_undisturbed forest_anthropogenic
forest_anthro_steep forest_anthro_protected

------------------------------------------------------------------------

# 9. Stability Considerations

Prefer QGIS processing providers:

native: gdal:

Avoid heavy reliance on:

saga: grass:

External providers may change between QGIS versions.

------------------------------------------------------------------------

# 10. Workshop Design Principles

Tools should:

require minimal inputs perform automatic validation enforce raster
alignment avoid manual raster calculator steps

------------------------------------------------------------------------

End of QGIS Processing Toolbox specification.

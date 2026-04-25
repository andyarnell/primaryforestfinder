# Primary Forest Finder Automation Recommendations

This document describes recommendations for building **Python / PyQGIS
automation tools** for the Primary Forest Finder workflow.

Goals:

-   reduce repetition
-   enforce CRS and resolution rules
-   simplify workshop usage
-   maintain stability across QGIS versions

------------------------------------------------------------------------

# 1. Recommended Architecture

Directory structure:

pff_tools/ prepare_inputs.py anthropogenic_mask.py
primary_forest_logic.py connectivity_filter.py run_workflow.py

Each script corresponds to a workflow stage.

------------------------------------------------------------------------

# 2. Stable Processing Providers

Prefer algorithms from:

native: gdal:

Avoid heavy dependence on:

saga: grass:

External providers are less stable across QGIS versions.

------------------------------------------------------------------------

# 3. Automate Data Preparation

Scripts should automatically perform:

-   CRS validation
-   rasterization
-   raster alignment

Example validation logic:

if layer.crs != target_crs: reproject layer

------------------------------------------------------------------------

# 4. Reference Grid

Use the forest raster as the reference grid.

Ensure matching:

-   extent
-   resolution
-   CRS
-   pixel origin

------------------------------------------------------------------------

# 5. Reduce Repetition

Instead of repeating operations manually for each dataset, use dataset
dictionaries.

Example:

anthropogenic_layers = { roads_major:1500, roads_minor:1000,
builtup:2000, agriculture:1000 }

------------------------------------------------------------------------

# 6. Distance Processing Loop

Pseudo‑code:

for layer, threshold in anthropogenic_layers:

    distance_surface = proximity(layer)

    buffer_mask = distance_surface <= threshold

------------------------------------------------------------------------

# 7. Cache Distance Surfaces

Distance calculations are computationally expensive.

Compute once:

dist_roads dist_builtup dist_agriculture

Reuse them for thresholds.

------------------------------------------------------------------------

# 8. Binary Raster Validation

Ensure binary rasters contain only:

0 1

Example:

if raster_max \> 1: raise error

------------------------------------------------------------------------

# 9. Automatic Raster Alignment

Before analysis run:

alignrasters(reference = forest_raster)

------------------------------------------------------------------------

# 10. Provide Intermediate Outputs

Useful layers:

anthropogenic_mask forest_undisturbed forest_anthropogenic
forest_anthro_steep forest_anthro_gentle_pa

These help debugging.

------------------------------------------------------------------------

# 11. Configurable Parameters

Expose parameters such as:

-   road buffer distance
-   built‑up buffer distance
-   agriculture buffer distance
-   slope threshold
-   connectivity radius
-   minimum patch size

------------------------------------------------------------------------

# 12. Suggested Toolbox Layout

Primary Forest Finder

Validate Inputs\
Prepare Datasets\
Build Anthropogenic Mask\
Run Primary Forest Finder\
Connectivity Filter

------------------------------------------------------------------------

# 13. Performance Tips

Use raster datatype:

Byte

Binary rasters do not require larger datatypes.

Distance surfaces should be cached where possible.

------------------------------------------------------------------------

# 14. Workshop Design

Automation scripts should:

-   minimise required inputs
-   validate datasets automatically
-   produce intermediate outputs
-   avoid manual raster calculator steps

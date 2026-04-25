# PFF_PYTHON_PSEUDOCODE.md

Primary Forest Finder --- Python / PyQGIS Pseudocode Specification

This document expresses the Primary Forest Finder workflow as structured
pseudocode. It is intended for AI coding assistants (GitHub Copilot,
Cursor, Claude Code) to generate reliable PyQGIS or GDAL-based
automation scripts.

The pseudocode mirrors the validated QGIS workflow but removes UI
details and focuses on logical operations and processing steps.

------------------------------------------------------------------------

# 1. Inputs

Required inputs:

forest_raster roads_major_vector roads_minor_vector builtup_vector
agriculture_vector protected_areas_vector dem_raster aoi_boundary_vector

------------------------------------------------------------------------

# 2. Global Parameters

buffer_aoi = 2000

thresholds = { roads_major : 1500, roads_minor : 1000, builtup : 2000,
agriculture : 1000 }

slope_threshold = 45 connectivity_patch_size = user_defined

------------------------------------------------------------------------

# 3. Preparation Stage

FUNCTION prepare_inputs():

    reproject all layers to common CRS

    AOI_buffer = buffer(aoi_boundary, buffer_aoi)

    clip all layers to AOI_buffer

    rasterize vectors using forest raster resolution

        rasterize roads_major_vector -> roads_major_raster
        rasterize roads_minor_vector -> roads_minor_raster
        rasterize builtup_vector -> builtup_raster
        rasterize agriculture_vector -> agriculture_raster
        rasterize protected_areas_vector -> protected_raster

    align all rasters to forest_raster grid

RETURN prepared rasters

------------------------------------------------------------------------

# 4. Slope Calculation

FUNCTION compute_slope():

    slope = calculate_slope(dem_raster)

    steep_slope = slope >= slope_threshold
    gentle_slope = slope < slope_threshold

RETURN steep_slope, gentle_slope

------------------------------------------------------------------------

# 5. Anthropogenic Distance Surfaces

FUNCTION build_distance_surfaces():

    anthropogenic_layers = [
        roads_major_raster,
        roads_minor_raster,
        builtup_raster,
        agriculture_raster
    ]

    FOR layer in anthropogenic_layers:

        distance_surface[layer] = proximity(layer)

RETURN distance_surface

------------------------------------------------------------------------

# 6. Anthropogenic Buffer Masks

FUNCTION build_anthropogenic_masks():

    FOR layer, threshold IN thresholds:

        buffer_mask[layer] = distance_surface[layer] <= threshold

    anthropogenic_mask = OR(
        buffer_mask[roads_major],
        buffer_mask[roads_minor],
        buffer_mask[builtup],
        buffer_mask[agriculture]
    )

RETURN anthropogenic_mask

------------------------------------------------------------------------

# 7. Forest Masks

FUNCTION build_forest_masks():

    forest_undisturbed =
        forest_raster == 1 AND anthropogenic_mask == 0

    forest_anthropogenic =
        forest_raster == 1 AND anthropogenic_mask == 1

RETURN forest_undisturbed, forest_anthropogenic

------------------------------------------------------------------------

# 8. Tier 2 --- Steep Slope Forests

FUNCTION compute_steep_tier():

    forest_anthro_steep =
        forest_anthropogenic AND steep_slope

RETURN forest_anthro_steep

------------------------------------------------------------------------

# 9. Tier 3 --- Protected Forests

FUNCTION compute_protected_tier():

    forest_anthro_protected =
        forest_anthropogenic
        AND gentle_slope
        AND protected_raster

RETURN forest_anthro_protected

------------------------------------------------------------------------

# 10. Combine Tiers

FUNCTION combine_primary_candidates():

    primary_candidate =
        forest_undisturbed
        OR forest_anthro_steep
        OR forest_anthro_protected

RETURN primary_candidate

------------------------------------------------------------------------

# 11. Connectivity Filtering

FUNCTION connectivity_filter():

    primary_filtered =
        remove_small_patches(primary_candidate, connectivity_patch_size)

RETURN primary_filtered

------------------------------------------------------------------------

# 12. Main Workflow

FUNCTION run_primary_forest_workflow():

    prepare_inputs()

    steep_slope, gentle_slope = compute_slope()

    distance_surface = build_distance_surfaces()

    anthropogenic_mask = build_anthropogenic_masks()

    forest_undisturbed, forest_anthropogenic =
        build_forest_masks()

    forest_anthro_steep =
        compute_steep_tier()

    forest_anthro_protected =
        compute_protected_tier()

    primary_candidate =
        combine_primary_candidates()

    primary_final =
        connectivity_filter()

RETURN primary_final

------------------------------------------------------------------------

# 13. Outputs

primary_forest_candidate.tif primary_forest_final.tif

intermediate layers:

anthropogenic_mask forest_undisturbed forest_anthropogenic
forest_anthro_steep forest_anthro_protected

------------------------------------------------------------------------

# 14. Critical Validation Checks

Before workflow execution ensure:

CRS consistency across all datasets

Raster alignment:

same extent same resolution same grid origin

Binary raster validation:

values must be 0 or 1

Distance thresholds must be defined in meters.

------------------------------------------------------------------------

End of pseudocode specification.

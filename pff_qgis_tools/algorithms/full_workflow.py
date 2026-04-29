"""
PFF Full Workflow – Run All Steps
==================================
One-click tool that chains Validate -> Prepare -> Distances ->
Anthropogenic Mask -> Primary Forest -> Refine Output.

All parameters from the individual tools are exposed so users can tweak
thresholds and re-run quickly.  Distance surfaces are cached -- only
threshold changes trigger fast re-computation.

Compatible with QGIS >= 3.38 (native: / gdal: providers only).
"""

import os
import shutil

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterCrs,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterField,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterString,
    QgsProcessingParameterDefinition,
)

from ..defaults import (
    ROADS_DIST, BUILTUP_DIST, BUILTUP_LARGE_DIST, AGRICULTURE_DIST,
    MAX_DISTANCE, AOI_BUFFER, SLOPE_THRESHOLD, SMOOTH_RADIUS,
    DENSITY_THRESHOLD,
)
from ..utils import (
    ensure_dir,
    validate_crs_projected,
    reproject_vector,
    reproject_raster,
    rasterize_vector,
    get_raster_info,
    run_processing,
    clip_raster_by_mask,
    proximity,
    raster_resolution,
    generate_layer_name,
    PLATFORM_QGIS,
)

# numpy / GDAL for the fast raster-algebra steps
import numpy as np
from osgeo import gdal


class FullWorkflowAlgorithm(QgsProcessingAlgorithm):
    # -- Inputs --
    FOREST_RASTER = "FOREST_RASTER"
    ROADS = "ROADS"
    ROADS_RASTER = "ROADS_RASTER"
    BUILTUP_SMALL_RASTER = "BUILTUP_SMALL_RASTER"
    BUILTUP_LARGE_RASTER = "BUILTUP_LARGE_RASTER"
    AGRICULTURE_RASTER = "AGRICULTURE_RASTER"
    # ISO3 country code prefix for output filenames (Option D / P1.13).
    # Optional; when blank, the prefix is omitted from filenames.
    ISO3_PREFIX = "ISO3_PREFIX"
    # Custom human-use disturbance slots (3, all optional, all FlagAdvanced).
    # Each slot has a raster input, a user-editable label (shown in logs +
    # metadata), and a per-slot buffer distance. Plumbed through prepare /
    # distance / anthro-mask stages alongside the built-in roads / builtup /
    # agriculture inputs.
    CUSTOM_1_RASTER = "CUSTOM_1_RASTER"
    CUSTOM_1_LABEL = "CUSTOM_1_LABEL"
    CUSTOM_1_DIST = "CUSTOM_1_DIST"
    CUSTOM_2_RASTER = "CUSTOM_2_RASTER"
    CUSTOM_2_LABEL = "CUSTOM_2_LABEL"
    CUSTOM_2_DIST = "CUSTOM_2_DIST"
    CUSTOM_3_RASTER = "CUSTOM_3_RASTER"
    CUSTOM_3_LABEL = "CUSTOM_3_LABEL"
    CUSTOM_3_DIST = "CUSTOM_3_DIST"
    DEM = "DEM"
    SLOPE_RASTER = "SLOPE_RASTER"
    PROTECTED_AREAS = "PROTECTED_AREAS"
    PROTECTED_RASTER = "PROTECTED_RASTER"
    PLANTATIONS_RASTER = "PLANTATIONS_RASTER"
    # P1.18: optional FRA-aligned agricultural tree cover raster
    # (Descals oil palm + SDPT class 2). Distinct from AGRICULTURE_RASTER
    # which is the broader buffered-disturbance agriculture (cropland +
    # pasture + everything). When supplied AND
    # EXCLUDE_AGRICULTURE_FROM_FOREST is on, this layer is subtracted
    # from the forest baseline to derive a FRA-strict Forest layer.
    FRA_AGRICULTURE_RASTER = "FRA_AGRICULTURE_RASTER"
    AOI = "AOI"
    # -- Parameters --
    TARGET_CRS = "TARGET_CRS"
    TARGET_CRS_EPSG = "TARGET_CRS_EPSG"
    AUTO_UTM = "AUTO_UTM"
    AOI_BUFFER = "AOI_BUFFER"
    ROADS_DIST = "ROADS_DIST"
    BUILTUP_DIST = "BUILTUP_DIST"
    BUILTUP_LARGE_DIST = "BUILTUP_LARGE_DIST"
    AGRICULTURE_DIST = "AGRICULTURE_DIST"
    MAX_DISTANCE = "MAX_DISTANCE"
    USE_SINGLE_DISTANCE = "USE_SINGLE_DISTANCE"
    ALL_BUFFERS_DIST = "ALL_BUFFERS_DIST"
    SLOPE_THRESHOLD = "SLOPE_THRESHOLD"
    SMOOTH_RADIUS = "SMOOTH_RADIUS"
    DENSITY_THRESHOLD = "DENSITY_THRESHOLD"
    FAST_APPROXIMATION = "FAST_APPROXIMATION"
    REFINE_MIN_PATCH_AREA_HA = "REFINE_MIN_PATCH_AREA_HA"
    SAVE_COMBINED_RASTER = "SAVE_COMBINED_RASTER"
    EXCLUDE_PLANTATIONS = "EXCLUDE_PLANTATIONS"
    EXCLUDE_AGRICULTURE_FROM_FOREST = "EXCLUDE_AGRICULTURE_FROM_FOREST"
    REUSE_DISTANCE_SURFACES = "REUSE_DISTANCE_SURFACES"
    REUSE_PREPARED = "REUSE_PREPARED"
    ADD_MAIN_OUTPUTS_TO_MAP = "ADD_MAIN_OUTPUTS_TO_MAP"
    ADD_HUMAN_INFLUENCE_LAYERS_TO_MAP = "ADD_HUMAN_INFLUENCE_LAYERS_TO_MAP"
    # -- Per-stage enable tickboxes (skip stages for faster runs) --
    ENABLE_ROADS_BUFFER = "ENABLE_ROADS_BUFFER"
    ENABLE_BUILTUP_SMALL_BUFFER = "ENABLE_BUILTUP_SMALL_BUFFER"
    ENABLE_BUILTUP_LARGE_BUFFER = "ENABLE_BUILTUP_LARGE_BUFFER"
    ENABLE_AGRICULTURE_BUFFER = "ENABLE_AGRICULTURE_BUFFER"
    ENABLE_REFINE_OUTPUT = "ENABLE_REFINE_OUTPUT"
    # -- Zonal statistics (optional) --
    RUN_ZONAL_STATS = "RUN_ZONAL_STATS"
    ZONE_LAYER = "ZONE_LAYER"
    ZONE_FIELD = "ZONE_FIELD"
    # -- Vectorisation (optional, advanced) --
    RUN_VECTORIZE = "RUN_VECTORIZE"
    VECTORIZE_PRIMARY = "VECTORIZE_PRIMARY"
    VECTORIZE_FOREST = "VECTORIZE_FOREST"
    VECTORIZE_NEST = "VECTORIZE_NEST"
    VECTORIZE_SIMPLIFY_M = "VECTORIZE_SIMPLIFY_M"
    # -- Output --
    OUTPUT_FOLDER = "OUTPUT_FOLDER"

    def name(self):
        return "full_workflow"

    def displayName(self):
        return "Run Full Workflow"

    def group(self):
        return "Primary Forest Finder"

    def groupId(self):
        return "pff"

    def shortHelpString(self):
        return (
            f"PFF Plugin v{self.PFF_VERSION} -- Full Workflow\n"
            "═══════════════════════════════════════════════\n\n"
            "Parameter labels carry a section prefix (e.g. '02 Tree Cover:') "
            "-- look up the matching section below for the full "
            "description, example sources, and caveats.\n\n"
            "WORKFLOW STAGES\n"
            "  1. Prepare datasets (reproject, rasterise, align)\n"
            "  2. Compute distance surfaces\n"
            "  3. Build anthropogenic mask + tier logic\n"
            "  4. Three-tier primary forest (undisturbed / steep / protected)\n"
            "  5. Refine Output -- ecological viability filter\n"
            "  6. Zonal Statistics (optional)\n"
            "  7. Vectorise outputs (optional)\n\n"
            "═══════════════════════════════════════════════\n"
            "§00 COUNTRY / CONTEXT\n"
            "═══════════════════════════════════════════════\n"
            "00 Country: AOI boundary (vector, optional)\n"
            "    Vector polygon defining country / region. Used to clip\n"
            "    rasters and as the boundary for stats.\n"
            "00 Country: ISO3 prefix\n"
            "    3-letter country code prepended to every output\n"
            "    filename (e.g. KEN -> KEN_qgis_04a_primary_forest.tif).\n"
            "    Leave blank to omit. Cased uppercase.\n"
            "00 Country: Auto UTM\n"
            "    Detects appropriate UTM zone from AOI / forest raster\n"
            "    centroid. Overrides Target CRS picker.\n"
            "00 Country: Target CRS\n"
            "    Manual projected CRS picker. Used when Auto UTM is off.\n"
            "00 Country: Target CRS EPSG (string fallback)\n"
            "    EPSG code as text (e.g. '5266' or 'EPSG:5266'). Workshop\n"
            "    fallback when picker can't find your zone. Overrides\n"
            "    Target CRS picker.\n"
            "00 Country: AOI buffer (advanced)\n"
            "    Extends analysis area past the country border so\n"
            "    edge-of-country anthropogenic features still influence\n"
            "    buffers. Default 2000 m.\n\n"
            "═══════════════════════════════════════════════\n"
            "§02 TREE COVER\n"
            "═══════════════════════════════════════════════\n"
            "Order matches the workflow sequence: forest input first,\n"
            "then FRA-agri exclusion (narrows tree cover -> FRA Forest),\n"
            "then plantations exclusion (narrows FRA Forest -> Naturally\n"
            "Regenerating).\n\n"
            "Forest raster (REQUIRED)\n"
            "    Binary 1/0 raster. Defines the reference grid (extent /\n"
            "    resolution / pixel origin) -- all other rasters align to it.\n"
            "    Example sources: Hansen GFC thresholded, GLAD LULC forest\n"
            "    class, national forest map. GEE filename: 02b_forest_*\n\n"
            "FRA agriculture raster (optional)\n"
            "    Binary 1/0. Tree-cover-meeting agricultural land only:\n"
            "    oil palm, tree crops, agroforestry. NOT the broader\n"
            "    buffered agriculture (cropland + pasture + everything).\n"
            "    Paired with 'Exclude agriculture' toggle. Example sources:\n"
            "    GEE export 03a_agriculture_tree_cover_fra (Descals oil palm\n"
            "    + SDPT class 2). When supplied AND toggle is on, narrows\n"
            "    the Forest baseline (02b) to FRA-strict Forest.\n\n"
            "Exclude agriculture from Forest baseline (FRA-aligned, default ON)\n"
            "    Requires FRA agri raster above. When on: narrows\n"
            "    02b_forest = tree_cover MINUS FRA agriculture, BEFORE the\n"
            "    plantations subtraction. Harmless no-op when no FRA agri\n"
            "    raster supplied.\n\n"
            "Plantations raster (optional)\n"
            "    Binary 1/0. Paired with 'Exclude plantations' toggle.\n"
            "    Example sources: SDPT class 1, national plantations\n"
            "    registry. When supplied AND toggle is on, workflow outputs\n"
            "    02d_naturally_regenerating_forest.tif (≈ FRA Naturally\n"
            "    Regenerating Forest = forest minus plantations -- proxy,\n"
            "    depends on plantations layer completeness).\n"
            "    GEE filename: 02c_plantations_*\n\n"
            "Exclude plantations from forest (default ON)\n"
            "    Requires Plantations raster above. When on: derives\n"
            "    02d_naturally_regenerating_forest as 02b MINUS 02c\n"
            "    (FRA Forest minus Plantations).\n\n"
            "═══════════════════════════════════════════════\n"
            "§03 HUMAN INFLUENCE -- (a) DISTURBANCE INPUTS\n"
            "═══════════════════════════════════════════════\n"
            "Inputs that get distance-buffered to remove nearby forest\n"
            "from candidate primary forest. The 'agriculture' here is the\n"
            "broader buffered concept -- includes cropland + pasture +\n"
            "everything human-use signalling, NOT FRA-aligned.\n\n"
            "03a Disturbance Inputs: Roads (vector, optional)\n"
            "03a Disturbance Inputs: Roads raster -- overrides vector. GEE: 03a_roads_*\n"
            "03a Disturbance Inputs: Built-up small raster -- GHS-BUILT (villages).\n"
            "    GEE: 03a_builtup_small_*\n"
            "03a Disturbance Inputs: Built-up large raster -- GHS-BUILT (cities).\n"
            "    GEE: 03a_builtup_large_*\n"
            "03a Disturbance Inputs: Agriculture raster -- GLAD LULC, ESA WorldCover, etc.\n"
            "    GEE: 03a_agriculture_*\n"
            "03a Disturbance Inputs: Custom 1 / 2 / 3 raster + label + buffer (advanced)\n"
            "    Three slots, each with its own raster + user-editable\n"
            "    label + per-slot buffer distance. Bring your own\n"
            "    disturbance: pipelines, mines, lights at night, navigable\n"
            "    waterways, country-specific layers. Label shows in logs +\n"
            "    metadata. Buffer 0 = apply input directly without expansion.\n\n"
            "═══════════════════════════════════════════════\n"
            "§03 HUMAN INFLUENCE -- (b) BUFFERS\n"
            "═══════════════════════════════════════════════\n"
            "Buffer = 0 rule: when a per-input buffer is 0 AND its\n"
            "'Include ... buffer' tickbox is on, the input footprint is\n"
            "applied DIRECTLY to the anthropogenic mask (no expansion). To\n"
            "skip an input entirely, UNTICK its 'Include ... buffer'.\n\n"
            "03b Buffers: Use single buffer distance for all anthropogenic layers\n"
            "    Overrides individual values when ticked.\n"
            "03b Buffers: Single buffer distance (m) (used when 03b ticked)\n"
            "03b Buffers: Roads buffer enable\n"
            "03b Buffers: Roads buffer distance (m)\n"
            "03b Buffers: Built-up small buffer enable\n"
            "03b Buffers: Built-up small buffer distance (m)\n"
            "03b Buffers: Built-up large buffer enable\n"
            "03b Buffers: Built-up large buffer distance (m)\n"
            "03b Buffers: Agriculture buffer enable\n"
            "03b Buffers: Agriculture buffer distance (m)\n"
            "03b Buffers: Maximum distance (m) (advanced)\n"
            "    Cap for speed; should be > largest buffer distance.\n\n"
            "═══════════════════════════════════════════════\n"
            "§03 HUMAN INFLUENCE -- (c) BUFFER EXCEPTIONS\n"
            "═══════════════════════════════════════════════\n"
            "Inputs that PRESERVE forest from disturbance buffering --\n"
            "naturally protected (steep slopes) or legally protected\n"
            "(WDPA pre-filtered to a year cutoff so PAs designated AFTER\n"
            "the analysis year aren't given retroactive credit).\n\n"
            "03c Buffer Exceptions: DEM (elevation, metres). Slope computed from this.\n"
            "    GEE: 03b_protection_natural_dem_*\n"
            "03c Buffer Exceptions: Slope raster (degrees, 0-90). Overrides DEM if both supplied.\n"
            "    GEE: 03b_protection_natural_slope_*\n"
            "03c Buffer Exceptions: Protected areas (vector, optional)\n"
            "03c Buffer Exceptions: Protected areas raster -- overrides vector.\n"
            "    GEE: 03b_protection_legal_*\n"
            "03c Buffer Exceptions: Slope threshold (degrees). Default 45.\n\n"
            "═══════════════════════════════════════════════\n"
            "§04 REFINE OUTPUT -- ECOLOGICAL VIABILITY\n"
            "═══════════════════════════════════════════════\n"
            "Produces 04a_primary_forest from 03c_pre_connectivity_primary_forest\n"
            "by removing patches that fail ecological viability criteria.\n"
            "Two optional sub-steps:\n\n"
            "04 Refine Output: Enable refine output (master toggle)\n"
            "04 Refine Output: Step (a): neighbourhood radius (m). 0 = skip step (a).\n"
            "    Smooths binary forest with a circular kernel; pixels below\n"
            "    density threshold are dropped.\n"
            "04 Refine Output: Step (a): minimum density to keep (0-1)\n"
            "04 Refine Output: Step (a): fast approximation (advanced)\n"
            "    Square kernel instead of circular -- faster, slight shape\n"
            "    difference. Off by default.\n"
            "04 Refine Output: Step (b): minimum patch area, hectares. 0 = skip step (b).\n"
            "    Uses gdal:sieve. Hole-fill is masked back to step input so\n"
            "    artefacts can't introduce pixels outside the input forest.\n\n"
            "═══════════════════════════════════════════════\n"
            "§05 STATISTICS\n"
            "═══════════════════════════════════════════════\n"
            "05 Statistics: Run zonal statistics (master toggle)\n"
            "05 Statistics: Zone layer (polygons)\n"
            "05 Statistics: Zone name / ID field\n\n"
            "═══════════════════════════════════════════════\n"
            "§06 VALIDATION / VECTORISE (advanced)\n"
            "═══════════════════════════════════════════════\n"
            "Polygonise + optional simplify + dissolve. Same pipeline as\n"
            "the standalone 'Vectorize PFF output' tool.\n\n"
            "06 Validation: Vectorise selected outputs (master toggle)\n"
            "06 Validation: Vectorise: primary forest\n"
            "06 Validation: Vectorise: forest input (uses naturally regenerating if\n"
            "    plantations refined)\n"
            "06 Validation: Vectorise: nest outputs (cut primary out of forest -- ideal\n"
            "    CEO stratification)\n"
            "06 Validation: Vectorise: simplify tolerance, metres. 0 = no simplify.\n"
            "    Use with caution -- can introduce geometry artefacts.\n\n"
            "═══════════════════════════════════════════════\n"
            "RUN OPTIONS / TIPS\n"
            "═══════════════════════════════════════════════\n"
            "Save combined coded raster: 4-class debug raster (0=none,\n"
            "    1=forest, 2=pre-connectivity, 3=primary).\n"
            "Reuse cached distance surfaces (default OFF, advanced)\n"
            "    Distance computation is the slowest stage. Output files\n"
            "    (intermediates/distances/dist_*.tif) can be reused across\n"
            "    runs when only tuning thresholds. OFF by default so stale\n"
            "    cache can't silently produce wrong results if inputs change.\n"
            "Reuse prepared/*.tif cache (default ON)\n"
            "    Skips reprojection of anthro inputs when cached aligned\n"
            "    raster matches the reference grid. Untick if you swapped a\n"
            "    source raster.\n"
            "Add main outputs to map (default ON)\n"
            "    Auto-loads Primary forest, Pre-connectivity forest, Forest,\n"
            "    Naturally regenerating forest after the run completes.\n"
            "    Order matches GEE legend: Primary on top.\n"
            "Add human influence layers to map (default OFF)\n"
            "    Mirrors GEE master toggle. Loads roads, builtup, ag,\n"
            "    plantations, slope, protected, custom slots.\n"
            "    Anthropogenic mask intentionally NOT auto-loaded -- it's\n"
            "    a debug intermediate; available at 04e_anthropogenic_mask.tif.\n\n"
            "Speed vs detail:\n"
            "  Runtime scales linearly with raster pixel count. Doubling\n"
            "  resolution (60m -> 30m) ~quadruples runtime. Linear features\n"
            "  (roads, narrow rivers) are 1-pixel-wide; coarser than ~45m\n"
            "  they get under-represented during rasterisation, so road\n"
            "  buffers may miss segments. Export at 30m or finer if road\n"
            "  buffers matter; 60-100m is fine for built-up / ag / protection.\n\n"
            "Fast re-run workflow (tuning thresholds only):\n"
            "  1. Point input rasters at [previous-out]/intermediates/prepared/\n"
            "     (already aligned to the reference grid).\n"
            "  2. Tick 'Reuse cached distance surfaces'.\n"
            "  3. Use the same output folder so the cache is found.\n"
            "  Result: reproject + distance stages skipped, only tier +\n"
            "  refine logic runs -- much faster iteration.\n\n"
            "═══════════════════════════════════════════════\n"
            "OUTPUT FOLDER LAYOUT\n"
            "═══════════════════════════════════════════════\n"
            "OUT = your chosen output folder. ISO3_ prefix when 00 set.\n\n"
            "  OUT/[ISO3_]qgis_02b_forest.tif (Forest baseline; FRA-strict\n"
            "      when 02 ticked)\n"
            "  OUT/[ISO3_]qgis_02d_naturally_regenerating_forest.tif\n"
            "      (if plantations refined)\n"
            "  OUT/[ISO3_]qgis_03c_pre_connectivity_primary_forest.tif\n"
            "      (after Step 03 disturbance + protection logic)\n"
            "  OUT/[ISO3_]qgis_03d_combined_coded_raster.tif\n"
            "      (if Save combined ticked; tier-logic debug)\n"
            "  OUT/[ISO3_]qgis_04a_primary_forest.tif\n"
            "      (after Step 04 viability filter -- HEADLINE result)\n"
            "  OUT/[ISO3_]qgis_04e_anthropogenic_mask.tif (intermediate)\n"
            "  OUT/[ISO3_]qgis_05a_area_statistics.csv (if 05 ticked)\n"
            "  OUT/[ISO3_]qgis_05b_area_statistics_by_zone.shp\n"
            "  OUT/[ISO3_]qgis_06a_primary_forest_vector.gpkg (if 06 ticked)\n"
            "  OUT/[ISO3_]qgis_06b_primary_forest_dissolved.gpkg\n"
            "  OUT/[ISO3_]qgis_06c_<forest>_vector.gpkg (if 06 ticked)\n"
            "  OUT/[ISO3_]qgis_06d_<forest>_dissolved.gpkg\n"
            "  OUT/[ISO3_]qgis_run_metadata.json\n"
            "  OUT/intermediates/ (tier rasters, prepared cache,\n"
            "                     distance cache, scratch workspaces)\n"
        )

    def createInstance(self):
        return FullWorkflowAlgorithm()

    # ------------------------------------------------------------------ #
    #  Parameters
    # ------------------------------------------------------------------ #

    def initAlgorithm(self, config=None):
        # Parameter labels use §x.y numbering matching the help panel
        # (shortHelpString) sections. Click Help in the dialog for full
        # descriptions, sources, and caveats per parameter.
        # Sections echo the GEE left-panel structure:
        #   00 Country / Context
        #   02 Forest Definition
        #   03a/b/c Human Influence
        #   04 Refine Output
        #   05 Statistics
        #   06 Validation / Vectorise
        #   (unnumbered) Run options + Output folder

        # ────────────────────────────────────────────────────────────
        # §00 — Country / Context
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.AOI, "00 Country: AOI boundary (vector, optional)",
            optional=True))
        self.addParameter(QgsProcessingParameterString(
            self.ISO3_PREFIX,
            "00 Country: ISO3 prefix (e.g. 'KEN'; leave blank to omit)",
            defaultValue="",
            optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.AUTO_UTM,
            "00 Country: Auto-detect UTM zone from AOI / forest centroid",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterCrs(
            self.TARGET_CRS,
            "00 Country: Target projected CRS (ignored when Auto UTM ticked)",
            defaultValue="EPSG:32717"))
        self.addParameter(QgsProcessingParameterString(
            self.TARGET_CRS_EPSG,
            "00 Country: OR target CRS as EPSG code (e.g. '5266'; overrides picker)",
            defaultValue="",
            optional=True))
        _aoi_buf_param = QgsProcessingParameterNumber(
            self.AOI_BUFFER,
            "00 Country: AOI buffer distance (m, advanced)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=AOI_BUFFER, minValue=0)
        _aoi_buf_param.setFlags(
            _aoi_buf_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_aoi_buf_param)

        # ────────────────────────────────────────────────────────────
        # §02 — Forest Definition
        # Order matches workflow sequence: tree cover input first, then
        # FRA agriculture (subtracted at 02a→02b to derive FRA Forest),
        # then plantations (subtracted at 02b→02d to derive Naturally
        # Regenerating). Toggles follow each input.
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.FOREST_RASTER,
            "02 Tree Cover: Forest raster (REQUIRED; binary 1/0; defines reference grid)"))
        # P1.22: paired plantations + planted-forest exclusions follow
        # the FRA forest-derivation flow:
        #   tree cover - plantations    = Forest (FRA Note 10 baseline)
        #   Forest    - planted forest = Naturally regenerating forest
        # Plantations FIRST in the parameter list so the UI reads in
        # workflow order. See About panel in GEE app for full FRA
        # definitions and rubber caveat.
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.FRA_AGRICULTURE_RASTER,
            "02 Tree Cover: Plantations raster -- agricultural tree crops "
            "(e.g. oil palm, fruit orchards, olive orchards, "
            "agroforestry-with-crops; SDPT class 2 + Descals oil palm). "
            "Per FRA Note 10 these are agricultural land regardless of "
            "tree biology. Used to narrow tree cover -> Forest (FRA "
            "baseline) when the toggle below is on. (binary 1/0, optional)",
            optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.EXCLUDE_AGRICULTURE_FROM_FOREST,
            "02 Tree Cover: Exclude plantations (e.g. oil palm, fruit, "
            "agroforestry) -- requires Plantations raster above; no-op "
            "when none supplied. Default ON for FRA-faithful output.",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.PLANTATIONS_RASTER,
            "02 Tree Cover: Planted forest raster -- FRA Planted Forest "
            "(timber/pulp/fibre, e.g. eucalyptus, pine, teak; SDPT class 1). "
            "Per FRA Note 7, rubber-wood plantations are also forest -- but "
            "SDPT v2 places rubber in tree crops, so rubber-bearing pixels "
            "land in the Plantations slot above by default. Supply a "
            "national rubber raster here to add it. (binary 1/0, optional)",
            optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.EXCLUDE_PLANTATIONS,
            "02 Tree Cover: Exclude planted forest (e.g. eucalyptus, "
            "pine, teak -- timber/pulp/fibre) -- requires Planted forest "
            "raster above. Derives 02d_naturally_regenerating_forest = "
            "02b_forest - 02c_planted_forest.",
            defaultValue=True))

        # ────────────────────────────────────────────────────────────
        # §03a — Human Influence: Disturbance inputs
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.ROADS, "03a Disturbance Inputs: Roads (vector, optional)",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.ROADS_RASTER,
            "03a Disturbance Inputs: Roads raster (binary 1/0; overrides vector)",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.BUILTUP_SMALL_RASTER,
            "03a Disturbance Inputs: Built-up small raster (binary 1/0)",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.BUILTUP_LARGE_RASTER,
            "03a Disturbance Inputs: Built-up large raster (binary 1/0)",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.AGRICULTURE_RASTER,
            "03a Disturbance Inputs: Agriculture raster (binary 1/0; broader buffered ag, "
            "NOT FRA-aligned)",
            optional=True))
        for _i in range(1, 4):
            _r_const = getattr(self, f"CUSTOM_{_i}_RASTER")
            _l_const = getattr(self, f"CUSTOM_{_i}_LABEL")
            _d_const = getattr(self, f"CUSTOM_{_i}_DIST")
            _base = 5 + (_i - 1) * 3  # 03a.6, 03a.9, 03a.12
            _r_param = QgsProcessingParameterRasterLayer(
                _r_const,
                f"03a.{_base + 1} Custom {_i} raster (advanced)",
                optional=True)
            _r_param.setFlags(_r_param.flags()
                              | QgsProcessingParameterDefinition.FlagAdvanced)
            self.addParameter(_r_param)
            _l_param = QgsProcessingParameterString(
                _l_const,
                f"03a.{_base + 2}     Custom {_i} label",
                defaultValue=f"Custom disturbance {_i}",
                optional=True)
            _l_param.setFlags(_l_param.flags()
                              | QgsProcessingParameterDefinition.FlagAdvanced)
            self.addParameter(_l_param)
            _d_param = QgsProcessingParameterNumber(
                _d_const,
                f"03a.{_base + 3}     Custom {_i} buffer distance (m; 0 = no buffer)",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1000.0, minValue=0.0)
            _d_param.setFlags(_d_param.flags()
                              | QgsProcessingParameterDefinition.FlagAdvanced)
            self.addParameter(_d_param)

        # ────────────────────────────────────────────────────────────
        # §03b — Human Influence: Buffer distances
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterBoolean(
            self.USE_SINGLE_DISTANCE,
            "03b Buffers: Use single buffer distance for all anthropogenic layers",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterNumber(
            self.ALL_BUFFERS_DIST,
            "03b Buffers: Single buffer distance (m; used when 03b ticked)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=1000, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_ROADS_BUFFER,
            "03b Buffers: Roads buffer enable",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.ROADS_DIST,
            "03b Buffers:     Roads buffer distance (m; 0 = no buffer)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=ROADS_DIST, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_BUILTUP_SMALL_BUFFER,
            "03b Buffers: Built-up (small) buffer enable",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.BUILTUP_DIST,
            "03b Buffers:     Built-up (small) buffer distance (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=BUILTUP_DIST, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_BUILTUP_LARGE_BUFFER,
            "03b Buffers: Built-up (large) buffer enable",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.BUILTUP_LARGE_DIST,
            "03b Buffers:     Built-up (large) buffer distance (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=BUILTUP_LARGE_DIST, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_AGRICULTURE_BUFFER,
            "03b Buffers: Agriculture buffer enable",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.AGRICULTURE_DIST,
            "03b Buffers:     Agriculture buffer distance (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=AGRICULTURE_DIST, minValue=0, maxValue=10000))
        _max_dist_param = QgsProcessingParameterNumber(
            self.MAX_DISTANCE,
            "03b Buffers: Maximum distance to compute (m, advanced)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=MAX_DISTANCE, minValue=100)
        _max_dist_param.setFlags(
            _max_dist_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_max_dist_param)

        # ────────────────────────────────────────────────────────────
        # §03c — Human Influence: Buffer Exceptions
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DEM,
            "03c Buffer Exceptions: DEM (elevation, m; slope computed from this)",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.SLOPE_RASTER,
            "03c Buffer Exceptions: OR Slope raster (degrees 0-90; overrides DEM)",
            optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.PROTECTED_AREAS,
            "03c Buffer Exceptions: Protected areas (vector, optional)",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.PROTECTED_RASTER,
            "03c Buffer Exceptions: OR protected areas raster (binary 1/0; overrides vector)",
            optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.SLOPE_THRESHOLD,
            "03c Buffer Exceptions: Slope threshold (degrees)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=SLOPE_THRESHOLD, minValue=0, maxValue=90))

        # ────────────────────────────────────────────────────────────
        # §04 — Refine Output (ecological viability filter)
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_REFINE_OUTPUT,
            "04 Refine Output: Enable refine (two optional steps below)",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.SMOOTH_RADIUS,
            "04 Refine Output:     Step (a): neighbourhood radius (m; 0 = skip)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=SMOOTH_RADIUS, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterNumber(
            self.DENSITY_THRESHOLD,
            "04 Refine Output:     Step (a): minimum density to keep (0-1)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=DENSITY_THRESHOLD, minValue=0, maxValue=1))
        _fast_approx_param = QgsProcessingParameterBoolean(
            self.FAST_APPROXIMATION,
            "04 Refine Output:     Step (a): fast approximation (square kernel, advanced)",
            defaultValue=False)
        _fast_approx_param.setFlags(
            _fast_approx_param.flags()
            | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_fast_approx_param)
        self.addParameter(QgsProcessingParameterNumber(
            self.REFINE_MIN_PATCH_AREA_HA,
            "04 Refine Output:     Step (b): minimum patch area, hectares (0 = skip)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.0, minValue=0.0))

        # ────────────────────────────────────────────────────────────
        # §05 — Statistics
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterBoolean(
            self.RUN_ZONAL_STATS,
            "05 Statistics: Run zonal statistics",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.ZONE_LAYER,
            "05 Statistics: Zone layer (polygons)",
            optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.ZONE_FIELD,
            "05 Statistics: Zone name / ID field",
            parentLayerParameterName=self.ZONE_LAYER,
            optional=True))

        # ────────────────────────────────────────────────────────────
        # §06 — Validation / Vectorise (advanced)
        # ────────────────────────────────────────────────────────────
        _v_run = QgsProcessingParameterBoolean(
            self.RUN_VECTORIZE,
            "06 Validation: Vectorise selected outputs (advanced)",
            defaultValue=False)
        _v_run.setFlags(_v_run.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_v_run)
        _v_primary = QgsProcessingParameterBoolean(
            self.VECTORIZE_PRIMARY,
            "06 Validation:     Vectorise: primary forest",
            defaultValue=True)
        _v_primary.setFlags(_v_primary.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_v_primary)
        _v_forest = QgsProcessingParameterBoolean(
            self.VECTORIZE_FOREST,
            "06 Validation:     Vectorise: forest input (or nat reg if refined)",
            defaultValue=False)
        _v_forest.setFlags(_v_forest.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_v_forest)
        _v_nest = QgsProcessingParameterBoolean(
            self.VECTORIZE_NEST,
            "06 Validation:     Vectorise: nest outputs (cut primary out of forest)",
            defaultValue=False)
        _v_nest.setFlags(_v_nest.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_v_nest)
        _v_simplify = QgsProcessingParameterNumber(
            self.VECTORIZE_SIMPLIFY_M,
            "06 Validation:     Vectorise: simplify tolerance (m; 0 = no simplify)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.0, minValue=0.0)
        _v_simplify.setFlags(_v_simplify.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_v_simplify)

        # ────────────────────────────────────────────────────────────
        # Run options (orthogonal to workflow steps)
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterBoolean(
            self.SAVE_COMBINED_RASTER,
            "Run: Save combined coded raster (debug)",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean(
            self.REUSE_DISTANCE_SURFACES,
            "Run: Reuse cached distance surfaces (advanced)",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean(
            self.REUSE_PREPARED,
            "Run: Reuse prepared/*.tif cache (default ON)",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ADD_MAIN_OUTPUTS_TO_MAP,
            "Run: Add main outputs to map after run",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ADD_HUMAN_INFLUENCE_LAYERS_TO_MAP,
            "Run: Add human-influence input + buffer layers to map (default OFF)",
            defaultValue=False))

        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_FOLDER, "Output folder"))

    # ------------------------------------------------------------------ #
    #  Workflow execution
    # ------------------------------------------------------------------ #

    PFF_VERSION = "0.9.6"

    def processAlgorithm(self, parameters, context, feedback):
        feedback.pushInfo(f"PFF plugin version: {self.PFF_VERSION}")

        # ── P1.13 ISO3 prefix ──
        # Read the optional ISO3 prefix once; the _out() closure that
        # uses it is defined further down (after out_dir is set).
        _iso3_raw = (self.parameterAsString(
            parameters, self.ISO3_PREFIX, context) or "").strip()
        _iso3 = _iso3_raw.upper() if _iso3_raw else None
        if _iso3:
            feedback.pushInfo(f"Output filename ISO3 prefix: {_iso3}")

        # Per-stage timing. _stage() closes the previous stage timer and
        # opens a new one; _close_last_stage() flushes the final stage
        # before the metadata write at the end. Times collected into
        # _pff_stage_times for run_metadata.json.
        import time as _pff_time
        _pff_t_start = _pff_time.monotonic()
        _pff_stage_times = {}
        _pff_last_stage = {"name": None, "t": _pff_t_start}

        def _stage(name):
            # P2.6: every stage transition is a graceful cancel point. If
            # the user clicked Cancel during the previous stage, raise here
            # with a clear "Cancelled by user" message instead of cascading
            # into the next stage and erroring on a half-finished file.
            if feedback.isCanceled():
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    "Cancelled by user (between stages -- no half-written "
                    "outputs from the new stage).")
            last = _pff_last_stage["name"]
            if last:
                elapsed = _pff_time.monotonic() - _pff_last_stage["t"]
                _pff_stage_times[last] = round(elapsed, 2)
                feedback.pushInfo(f"  [{last} took {elapsed:.1f}s]")
            _pff_last_stage["name"] = name
            _pff_last_stage["t"] = _pff_time.monotonic()
            feedback.pushInfo(f"=== {name} ===")

        def _close_last_stage():
            last = _pff_last_stage["name"]
            if last:
                elapsed = _pff_time.monotonic() - _pff_last_stage["t"]
                _pff_stage_times[last] = round(elapsed, 2)
                feedback.pushInfo(f"  [{last} took {elapsed:.1f}s]")
                _pff_last_stage["name"] = None

        out_dir = ensure_dir(
            self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))

        # Output filename helper: builds top-level paths per Option D
        # naming. Uses _iso3 from above; closes over out_dir.
        def _out(step, name, ext="tif"):
            return os.path.join(
                out_dir,
                generate_layer_name(_iso3, PLATFORM_QGIS, step, name, ext))

        save_combined = self.parameterAsBool(
            parameters, self.SAVE_COMBINED_RASTER, context)
        reuse_distances = self.parameterAsBool(
            parameters, self.REUSE_DISTANCE_SURFACES, context)
        reuse_prepared = self.parameterAsBool(
            parameters, self.REUSE_PREPARED, context)
        auto_utm = self.parameterAsBool(
            parameters, self.AUTO_UTM, context)
        aoi_buffer_dist = self.parameterAsDouble(
            parameters, self.AOI_BUFFER, context)
        max_dist = self.parameterAsDouble(
            parameters, self.MAX_DISTANCE, context)
        slope_thresh = self.parameterAsDouble(
            parameters, self.SLOPE_THRESHOLD, context)
        smooth_radius = self.parameterAsDouble(
            parameters, self.SMOOTH_RADIUS, context)
        density_thresh = self.parameterAsDouble(
            parameters, self.DENSITY_THRESHOLD, context)
        refine_min_patch_area_ha = self.parameterAsDouble(
            parameters, self.REFINE_MIN_PATCH_AREA_HA, context)

        use_single = self.parameterAsBool(
            parameters, self.USE_SINGLE_DISTANCE, context)
        single_dist = self.parameterAsDouble(
            parameters, self.ALL_BUFFERS_DIST, context)

        # Per-buffer enable flags. Unticking one skips both its distance
        # computation and its contribution to the anthropogenic mask.
        enable_buffers = {
            "roads": self.parameterAsBool(parameters, self.ENABLE_ROADS_BUFFER, context),
            "builtup": self.parameterAsBool(parameters, self.ENABLE_BUILTUP_SMALL_BUFFER, context),
            "builtup_large": self.parameterAsBool(parameters, self.ENABLE_BUILTUP_LARGE_BUFFER, context),
            "agriculture": self.parameterAsBool(parameters, self.ENABLE_AGRICULTURE_BUFFER, context),
        }
        enable_refine_output = self.parameterAsBool(
            parameters, self.ENABLE_REFINE_OUTPUT, context)

        add_main_outputs_to_map = self.parameterAsBool(
            parameters, self.ADD_MAIN_OUTPUTS_TO_MAP, context)
        add_human_influence_layers_to_map = self.parameterAsBool(
            parameters, self.ADD_HUMAN_INFLUENCE_LAYERS_TO_MAP, context)

        # Vectorise stage params (advanced).
        run_vectorize = self.parameterAsBool(
            parameters, self.RUN_VECTORIZE, context)
        vectorize_primary = self.parameterAsBool(
            parameters, self.VECTORIZE_PRIMARY, context)
        vectorize_forest = self.parameterAsBool(
            parameters, self.VECTORIZE_FOREST, context)
        vectorize_nest = self.parameterAsBool(
            parameters, self.VECTORIZE_NEST, context)
        vectorize_simplify_m = self.parameterAsDouble(
            parameters, self.VECTORIZE_SIMPLIFY_M, context)

        # Read individual distances even when single-mode is on, so we can
        # warn the user if they've customised them but ticked the single-mode
        # checkbox (their customisations would silently be ignored otherwise).
        individual_thresholds = {
            "roads": self.parameterAsDouble(
                parameters, self.ROADS_DIST, context),
            "builtup": self.parameterAsDouble(
                parameters, self.BUILTUP_DIST, context),
            "builtup_large": self.parameterAsDouble(
                parameters, self.BUILTUP_LARGE_DIST, context),
            "agriculture": self.parameterAsDouble(
                parameters, self.AGRICULTURE_DIST, context),
        }

        # Custom human-use slots: only included when the user provided a
        # raster for the slot. Each slot gets its own per-slot label and
        # buffer distance. Keys are custom_1 / custom_2 / custom_3 so they
        # slot cleanly into the existing rasters / thresholds / enable_buffers
        # dicts.
        custom_slot_labels = {}  # key -> user label (for logs / metadata)
        for _i in range(1, 4):
            _key = f"custom_{_i}"
            _r = self.parameterAsRasterLayer(
                parameters, getattr(self, f"CUSTOM_{_i}_RASTER"), context)
            if _r is None:
                continue
            _label = (self.parameterAsString(
                parameters, getattr(self, f"CUSTOM_{_i}_LABEL"), context)
                      or f"Custom disturbance {_i}").strip()
            _dist = self.parameterAsDouble(
                parameters, getattr(self, f"CUSTOM_{_i}_DIST"), context)
            individual_thresholds[_key] = _dist
            enable_buffers[_key] = True
            custom_slot_labels[_key] = _label

        if use_single and single_dist > 0:
            thresholds = {k: single_dist for k in individual_thresholds}
        else:
            thresholds = individual_thresholds

        # Prominent log block so the user always sees which distances were
        # actually applied — mitigates the "I forgot the single-distance
        # tickbox was on" silent-mistake risk.
        enabled_names = [n for n, v in enable_buffers.items() if v]
        disabled_names = [n for n, v in enable_buffers.items() if not v]
        feedback.pushInfo("")
        feedback.pushInfo("=== Buffer distances ===")
        if use_single:
            feedback.pushInfo(
                f"  Single {single_dist:g} m applied to all ticked buffers: "
                + (", ".join(enabled_names) if enabled_names else "(none!)"))
            if disabled_names:
                feedback.pushInfo(
                    f"  Skipped (tickbox off): " + ", ".join(disabled_names))
            # Warn only when the user has ACTIVELY customised individual fields
            # (i.e. changed them from their defaults) AND ticked single-mode —
            # their customisations are being silently ignored, which is the real
            # mistake. Don't fire when individuals are still at defaults and the
            # user is just using single-mode normally.
            defaults_map = {
                "roads": ROADS_DIST, "builtup": BUILTUP_DIST,
                "builtup_large": BUILTUP_LARGE_DIST,
                "agriculture": AGRICULTURE_DIST,
            }
            # Custom slots default to 1000m; treat that as the "default" so
            # we don't false-trigger the warning when the user just leaves
            # them at the slot default while using single-mode.
            customised = [
                f"{name}={individual_thresholds[name]:g}"
                for name in individual_thresholds
                if individual_thresholds[name] != defaults_map.get(name, 1000.0)
            ]
            if customised:
                feedback.pushWarning(
                    f"  ⚠ Using {single_dist:g}m (single). Ignored: "
                    + ", ".join(customised) + ".")
                feedback.pushWarning(
                    "  ⏳ 10s to Cancel. Fix: untick single-distance.")
                import time
                for tick in range(40):
                    if feedback.isCanceled():
                        feedback.pushInfo("Cancelled — fix & re-run.")
                        return {}
                    if tick == 20:  # 5s remaining
                        feedback.pushWarning("  ⏳ 5s left.")
                    time.sleep(0.25)
                feedback.pushInfo(f"  Continuing with {single_dist:g}m.")
        else:
            feedback.pushInfo("  INDIVIDUAL-DISTANCE mode:")
            for name, dist in thresholds.items():
                # Custom slots get their user label appended for clarity.
                _suffix = (f"  ('{custom_slot_labels[name]}')"
                           if name in custom_slot_labels else "")
                if enable_buffers.get(name, True):
                    feedback.pushInfo(f"    {name:<14} {dist:g} m{_suffix}")
                else:
                    feedback.pushInfo(f"    {name:<14} SKIPPED (Include-X-buffer is unticked){_suffix}")
        feedback.pushInfo("")

        # -- Resolve target CRS (auto UTM or manual) --
        forest_layer = self.parameterAsRasterLayer(
            parameters, self.FOREST_RASTER, context)
        aoi_layer = self.parameterAsVectorLayer(parameters, self.AOI, context)

        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsProcessingException,
        )

        # CRS resolution priority: AUTO_UTM > TARGET_CRS_EPSG (if non-empty)
        # > TARGET_CRS picker. The EPSG-string fallback exists because the
        # QGIS CRS picker is fiddly on some installs (no Choose button on
        # older QGIS-LTR) and workshop users get stuck.
        target_crs_epsg_str = (self.parameterAsString(
            parameters, self.TARGET_CRS_EPSG, context) or "").strip()

        if auto_utm:
            target_crs_str = _detect_utm_zone(forest_layer, aoi_layer, feedback)
            crs_source = "Auto UTM"
        elif target_crs_epsg_str:
            # Be permissive about format -- everyone uses EPSG codes, so
            # accept bare numbers ("5266"), lowercase ("epsg:5266"), or
            # the canonical "EPSG:5266". Normalise to "EPSG:<digits>"
            # before validating.
            _normalised = target_crs_epsg_str
            if _normalised.isdigit():
                _normalised = f"EPSG:{_normalised}"
            elif _normalised.lower().startswith("epsg:"):
                _normalised = "EPSG:" + _normalised.split(":", 1)[1].strip()
            candidate = QgsCoordinateReferenceSystem(_normalised)
            if not candidate.isValid():
                raise QgsProcessingException(
                    f"TARGET_CRS_EPSG '{target_crs_epsg_str}' is not a valid "
                    "CRS code. Expected an EPSG code -- either bare ('5266') "
                    "or prefixed ('EPSG:5266').")
            target_crs_str = candidate.authid() or _normalised
            crs_source = f"EPSG-string field ('{target_crs_epsg_str}')"
        else:
            target_crs = self.parameterAsCrs(
                parameters, self.TARGET_CRS, context)
            target_crs_str = target_crs.authid()
            crs_source = "CRS picker"

        target_crs = QgsCoordinateReferenceSystem(target_crs_str)

        # Validate the resolved CRS is projected (metres). Distance / area
        # operations downstream silently produce wrong values on geographic
        # CRS, so fail loud here.
        if target_crs.isGeographic():
            raise QgsProcessingException(
                f"Resolved target CRS '{target_crs_str}' is geographic "
                "(degrees). Choose a projected CRS in metres -- e.g. a UTM "
                "zone, a continental equal-area projection, or your country's "
                "national grid.")

        feedback.pushInfo(f"Target CRS: {target_crs_str} (source: {crs_source})")

        # All non-headline outputs (caches + tier rasters) nest under intermediates/.
        # Headlines (per Option D + P1.16 FRA-aligned schema:
        # 02c naturally_regenerating_forest, 04a primary_forest,
        # 04b pre_connectivity, 04c combined_coded, 04e anthropogenic_mask,
        # 05a area_statistics, 06a/b/c/d vectors, qgis_run_metadata.json)
        # stay at out_dir top level with ISO3+platform+step prefixes via _out().
        intermediates_dir = ensure_dir(os.path.join(out_dir, "intermediates"))
        prepared_dir = ensure_dir(os.path.join(intermediates_dir, "prepared"))
        dist_dir = ensure_dir(os.path.join(intermediates_dir, "distances"))
        # Scratch dir for per-input _reproj and _clipped intermediates. Keeps
        # prepared/ clean — only the 9 user-reusable final rasters sit there,
        # everything else (which users never repoint at) goes here.
        scratch_dir = ensure_dir(os.path.join(intermediates_dir, "_scratch"))

        # --- Pre-flight: check if any key output file is locked ---------
        # Frustrating to wait minutes for a run only to crash at the end
        # when an output file is open in QGIS. Check upfront.
        _run_zonal = self.parameterAsBool(
            parameters, self.RUN_ZONAL_STATS, context)
        # Likely outputs use the Option D filenames computed via _out().
        _likely_outputs = [
            _out("04a", "primary_forest"),
            _out("03c", "pre_connectivity_primary_forest"),
            _out("04e", "anthropogenic_mask"),
            _out("02b", "forest"),
            _out("02d", "naturally_regenerating_forest"),
            os.path.join(
                out_dir,
                (f"{_iso3}_qgis_run_metadata.json" if _iso3
                 else "qgis_run_metadata.json")),
        ]
        if save_combined:
            _likely_outputs.append(_out("03d", "combined_coded_raster"))
        if _run_zonal:
            _likely_outputs.append(_out("05a", "area_statistics", ext="csv"))
            _likely_outputs.append(_out("05b", "area_statistics_by_zone", ext="shp"))

        _locked = []
        for _p in _likely_outputs:
            if not os.path.exists(_p):
                continue
            # Reliable Windows lock check: try to rename. GDAL memory-maps
            # rasters with shared read+write but NOT shared delete, so
            # open(path, 'r+b') passes while os.remove() still fails later.
            # Rename hits the same permission path as delete, so it's the
            # probe that matches what _write() / os.remove() actually need.
            _probe = _p + ".__locktest__"
            try:
                os.rename(_p, _probe)
                os.rename(_probe, _p)
            except (PermissionError, OSError):
                _locked.append(os.path.basename(_p))

        if _locked:
            from qgis.core import QgsProcessingException
            raise QgsProcessingException(
                "Pre-flight check failed: output file(s) locked by another "
                "process (usually QGIS has them loaded as layers from a "
                "previous run):\n  - " + "\n  - ".join(_locked) +
                "\n\nFix: in QGIS Layers panel, right-click each and "
                "'Remove Layer…', or close the other program holding them, "
                "then re-run. (Your run hasn't started yet — no time wasted.)"
            )

        # ================================================================
        #  STAGE 1 -- Prepare datasets
        # ================================================================
        _stage("STAGE 1: Prepare Datasets")

        validate_crs_projected(forest_layer, feedback)
        forest_src = forest_layer.source()
        # Peek at AOI choice early so we can pick the right reproject target:
        # if AOI will be supplied we reproject to scratch/ so the AOI-clip step
        # can write the final prepared/forest.tif from a different source file
        # (avoids in-place overwrite + Windows file-lock problems with OneDrive).
        _will_clip_aoi = aoi_layer is not None
        prepared_forest_path = os.path.join(prepared_dir, "forest.tif")

        # Re-run short-circuit: if user already points at prepared/forest.tif
        # from this out_dir, it's already reprojected + AOI-clipped. Skip prep.
        if os.path.normpath(forest_src) == os.path.normpath(prepared_forest_path):
            feedback.pushInfo(
                "Forest input is already prepared/forest.tif — using as-is "
                "(re-run path; skipping reproject + AOI clip).")
        else:
            # First-run path: reproject forest.
            reproj_target = (os.path.join(scratch_dir, "forest_reproj.tif")
                             if _will_clip_aoi else prepared_forest_path)
            if forest_layer.crs() != target_crs:
                feedback.pushInfo("Reprojecting forest raster...")
                reproject_raster(forest_src, target_crs_str, reproj_target,
                                 context=context, feedback=feedback)
                forest_src = reproj_target
            else:
                if os.path.normpath(forest_src) != os.path.normpath(reproj_target):
                    run_processing("gdal:translate", {
                        "INPUT": forest_src, "OUTPUT": reproj_target,
                        "OPTIONS": "COMPRESS=LZW|TILED=YES",
                    }, context=context, feedback=feedback)
                    forest_src = reproj_target

        reference = forest_src

        # Buffer & clip AOI
        # AOI working files (reproj / buffered / rasterised) are internal —
        # users never repoint the plugin at them. Nest under prepared/_aoi/
        # so prepared/ shows only the 9 user-reusable inputs.
        aoi_mask = None
        if aoi_layer is not None:
            feedback.pushInfo(
                f"Buffering AOI by {aoi_buffer_dist:g} m "
                "(extends analysis past the boundary so edge-of-country "
                "anthropogenic features still influence buffers)...")
            aoi_workspace = ensure_dir(os.path.join(prepared_dir, "_aoi"))
            # Use .shp for reproject to avoid gpkg FID uniqueness dropping features
            aoi_reproj_raw = os.path.join(aoi_workspace, "aoi_reproj_raw.shp")
            reproject_vector(aoi_layer.source(), target_crs_str, aoi_reproj_raw,
                             context=context, feedback=feedback)
            # Dissolve to merge multi-feature AOIs (e.g. countries with
            # islands or diced polygons) into one multipart polygon
            aoi_reproj = os.path.join(aoi_workspace, "aoi_reproj.gpkg")
            run_processing("native:dissolve", {
                "INPUT": aoi_reproj_raw,
                "OUTPUT": aoi_reproj,
            }, context=context, feedback=feedback)
            aoi_buffered = os.path.join(aoi_workspace, "aoi_buffered.gpkg")
            run_processing("native:buffer", {
                "INPUT": aoi_reproj,
                "DISTANCE": aoi_buffer_dist,
                "DISSOLVE": True,
                "OUTPUT": aoi_buffered,
            }, context=context, feedback=feedback)
            aoi_mask = aoi_buffered

            # If forest is the re-run input (already prepared/forest.tif),
            # skip the re-clip — file is already AOI-clipped.
            if os.path.normpath(reference) == os.path.normpath(prepared_forest_path):
                feedback.pushInfo(
                    "Forest input is already prepared/forest.tif — skipping "
                    "AOI re-clip (it's already clipped).")
                # Still rasterise the AOI so it's available for stages that need it.
                aoi_rasterised = os.path.join(aoi_workspace, "aoi_raster.tif")
                rasterize_vector(aoi_buffered, reference, aoi_rasterised,
                                 context=context, feedback=feedback)
            else:
                # Normal first-run path: reprojected forest is in scratch_dir,
                # mask it to AOI and write the result to prepared/forest.tif.
                # Source and destination are DIFFERENT files → no in-place
                # overwrite, no Windows file-lock issues.
                aoi_rasterised = os.path.join(aoi_workspace, "aoi_raster.tif")
                rasterize_vector(aoi_buffered, reference, aoi_rasterised,
                                 context=context, feedback=feedback)
                _ds_ref = gdal.Open(reference, gdal.GA_ReadOnly)
                _forest_arr = _ds_ref.GetRasterBand(1).ReadAsArray()
                _gt_ref = _ds_ref.GetGeoTransform()
                _proj_ref = _ds_ref.GetProjection()
                _xsz = _ds_ref.RasterXSize
                _ysz = _ds_ref.RasterYSize
                _ds_ref = None
                _ds_aoi = gdal.Open(aoi_rasterised, gdal.GA_ReadOnly)
                _aoi_arr = _ds_aoi.GetRasterBand(1).ReadAsArray()
                _ds_aoi = None
                _masked = (_forest_arr * (_aoi_arr > 0)).astype(_forest_arr.dtype)
                _drv = gdal.GetDriverByName("GTiff")
                # Write clipped forest to prepared/forest.tif (different path
                # from the scratch reproj source — no in-place overwrite).
                if os.path.exists(prepared_forest_path):
                    try:
                        os.remove(prepared_forest_path)
                    except OSError as e:
                        raise RuntimeError(
                            f"Cannot write '{os.path.basename(prepared_forest_path)}' — "
                            "it is locked. Close any program using it and retry. "
                            f"(original: {e})")
                # Use _ds_out NOT _out -- _out is the helper closure for
                # building output filenames (defined ~line 625). Naming
                # this GDAL Dataset _out would shadow the closure for the
                # rest of processAlgorithm, breaking every subsequent
                # _out("step", "name") call. (Bug found in batch 11.)
                _ds_out = _drv.Create(prepared_forest_path, _xsz, _ysz, 1,
                                      gdal.GDT_Byte, ["COMPRESS=LZW"])
                _ds_out.SetGeoTransform(_gt_ref)
                _ds_out.SetProjection(_proj_ref)
                _ds_out.GetRasterBand(1).WriteArray(_masked)
                _ds_out.GetRasterBand(1).SetNoDataValue(0)
                _ds_out.FlushCache()
                _ds_out = None
                reference = prepared_forest_path  # downstream uses the clipped version

        # Keep the raw forest path for stats (before plantations exclusion).
        # If plantations exclusion is applied below, `reference` is redirected
        # to the forest-AND-NOT-plantations raster so downstream stages use it.
        forest_raw_path = reference

        # Helper: reproject + clip + rasterise a vector layer.
        # Intermediates go to _scratch/ so prepared/ stays clean with only the
        # final aligned .tif files (what users might repoint at for re-runs).
        def _prep_vector(param_key, filename):
            layer = self.parameterAsVectorLayer(parameters, param_key, context)
            if layer is None:
                return None
            feedback.pushInfo(f"Preparing {filename}...")
            reproj = os.path.join(scratch_dir, f"{filename}_reproj.gpkg")
            reproject_vector(layer.source(), target_crs_str, reproj,
                             context=context, feedback=feedback)
            if aoi_mask is not None:
                clipped = os.path.join(scratch_dir, f"{filename}_clip.gpkg")
                run_processing("native:clip", {
                    "INPUT": reproj, "OVERLAY": aoi_mask, "OUTPUT": clipped,
                }, context=context, feedback=feedback)
                reproj = clipped
            rasterised = os.path.join(prepared_dir, f"{filename}.tif")
            rasterize_vector(reproj, reference, rasterised,
                             context=context, feedback=feedback)
            return rasterised

        # Helper: align a raster input to the reference grid.
        # Intermediates go to _scratch/ (same rationale).
        def _prep_raster(param_key, filename):
            layer = self.parameterAsRasterLayer(parameters, param_key, context)
            if layer is None:
                return None
            aligned = os.path.join(prepared_dir, f"{filename}.tif")
            # Re-run short-circuit: if user points this input at the prepared/
            # output from a previous run (same path), don't re-process — it's
            # already aligned. Avoids the Windows "read + overwrite same file"
            # lock issue.
            if os.path.normpath(layer.source()) == os.path.normpath(aligned):
                feedback.pushInfo(
                    f"Raster {filename} is already prepared/{filename}.tif "
                    "— using as-is (re-run path).")
                return aligned
            # P0.3 REUSE_PREPARED: when the user toggle is on AND a cached
            # prepared/<filename>.tif exists AND its grid (x_size, y_size,
            # pixel size) matches the reference, skip the whole reproject +
            # clip + warp pipeline. The user's source raster is intentionally
            # NOT re-checked -- if they swapped sources, they're expected to
            # untick this option to force re-prep. Surfaces a clear log line
            # so the user can spot when reuse fired.
            if reuse_prepared and os.path.exists(aligned):
                try:
                    _, _ag_gt, _ag_x, _ag_y = get_raster_info(aligned)
                    _, _rf_gt, _rf_x, _rf_y = get_raster_info(reference)
                    _grid_match = (
                        _ag_x == _rf_x and _ag_y == _rf_y
                        and abs(abs(_ag_gt[1]) - abs(_rf_gt[1])) < 1e-6
                        and abs(abs(_ag_gt[5]) - abs(_rf_gt[5])) < 1e-6
                    )
                    if _grid_match:
                        feedback.pushInfo(
                            f"Reused cached: prepared/{filename}.tif "
                            "(matches reference grid; reproject skipped). "
                            "Untick 'Reuse prepared/*.tif cache' to force "
                            "re-prep if your source raster changed.")
                        return aligned
                    else:
                        feedback.pushInfo(
                            f"Cached prepared/{filename}.tif has mismatched "
                            "grid -- recomputing.")
                except Exception as _e:
                    feedback.pushDebugInfo(
                        f"Could not verify cached prepared/{filename}.tif: "
                        f"{_e}; recomputing to be safe.")
            feedback.pushInfo(f"Aligning raster {filename}...")
            reproj = os.path.join(scratch_dir, f"{filename}_reproj.tif")
            reproject_raster(layer.source(), target_crs_str, reproj,
                             context=context, feedback=feedback)
            if aoi_mask is not None:
                clipped = os.path.join(scratch_dir, f"{filename}_clipped.tif")
                clip_raster_by_mask(reproj, aoi_mask, clipped,
                                    context=context, feedback=feedback)
                # Remove intermediate reproj to free disk/memory (best-effort)
                try:
                    os.remove(reproj)
                except OSError:
                    pass
                reproj = clipped
            # 'aligned' already set above (for re-run short-circuit).
            _, gt_ref, xsz, ysz = get_raster_info(reference)
            res_x = abs(gt_ref[1])
            ext = (f"{gt_ref[0]},{gt_ref[0]+gt_ref[1]*xsz},"
                   f"{gt_ref[3]+gt_ref[5]*ysz},{gt_ref[3]}")
            run_processing("gdal:warpreproject", {
                "INPUT": reproj,
                "TARGET_CRS": target_crs,
                "TARGET_EXTENT": ext,
                "TARGET_EXTENT_CRS": target_crs,
                "TARGET_RESOLUTION": res_x,
                "RESAMPLING": 0,
                "OPTIONS": "COMPRESS=LZW|TILED=YES",
                "OUTPUT": aligned,
            }, context=context, feedback=feedback)
            # Remove intermediate clip/reproj to free disk space
            if reproj != aligned:
                try:
                    os.remove(reproj)
                except OSError:
                    pass
            return aligned

        # Limit GDAL cache to avoid memory pressure on large rasters
        gdal.SetCacheMax(512 * 1024 * 1024)  # 512 MB

        # Thin-feature resolution warning: roads (and to a lesser extent
        # waterways) are 1-pixel-wide linear features. At raster resolutions
        # coarser than ~45 m, single-cell roads disappear into surrounding
        # cells (the rasterisation collapses the geometry). Warn loud so the
        # user knows their roads input may under-represent the network.
        _ROADS_THIN_FEATURE_WARN_M = 45
        _user_roads_layer = self.parameterAsRasterLayer(
            parameters, self.ROADS_RASTER, context)
        if _user_roads_layer is not None:
            try:
                _roads_res = raster_resolution(_user_roads_layer.source())
                if _roads_res > _ROADS_THIN_FEATURE_WARN_M:
                    feedback.pushWarning(
                        f"Roads raster resolution is {_roads_res:g} m -- "
                        f"coarser than ~{_ROADS_THIN_FEATURE_WARN_M} m. "
                        "Linear features (roads / tracks) are likely under-"
                        "represented at this resolution. If road buffers "
                        "matter for your analysis, either re-export at "
                        "finer resolution OR supply roads as a vector "
                        "input (vectors get rasterised to the reference "
                        "grid, so no thin-feature loss).")
            except Exception as _e:
                # Resolution check is advisory; never block the run.
                feedback.pushDebugInfo(
                    f"Could not check roads raster resolution: {_e}")

        # Raster inputs override vectors when both are provided.
        # Process sequentially with GC + cancel checks between -- prep on
        # national rasters can run minutes per layer, so let cancel land
        # between layers without waiting for the full anthro batch.
        import gc
        roads_raster = _prep_raster(self.ROADS_RASTER, "roads")
        gc.collect()
        if feedback.isCanceled():
            from qgis.core import QgsProcessingException
            raise QgsProcessingException("Cancelled by user (after roads prep).")
        builtup_small_raster = _prep_raster(self.BUILTUP_SMALL_RASTER, "builtup_small")
        gc.collect()
        if feedback.isCanceled():
            from qgis.core import QgsProcessingException
            raise QgsProcessingException("Cancelled by user (after builtup_small prep).")
        builtup_large_raster = _prep_raster(self.BUILTUP_LARGE_RASTER, "builtup_large")
        gc.collect()
        if feedback.isCanceled():
            from qgis.core import QgsProcessingException
            raise QgsProcessingException("Cancelled by user (after builtup_large prep).")
        agri_raster = _prep_raster(self.AGRICULTURE_RASTER, "agriculture")
        gc.collect()

        # Custom human-use slots (P2.3): prep each provided raster the same
        # way as the built-in anthro inputs. Skipped slots stay None.
        custom_rasters = {}  # custom_1/2/3 -> prepped path or None
        for _i in range(1, 4):
            _key = f"custom_{_i}"
            _const = getattr(self, f"CUSTOM_{_i}_RASTER")
            _layer = self.parameterAsRasterLayer(parameters, _const, context)
            if _layer is None:
                custom_rasters[_key] = None
                continue
            _label_for_log = custom_slot_labels.get(_key, _key)
            feedback.pushInfo(
                f"Preparing custom slot {_i} ('{_label_for_log}')...")
            custom_rasters[_key] = _prep_raster(_const, _key)
            gc.collect()
            if feedback.isCanceled():
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    f"Cancelled by user (after custom_{_i} prep).")

        rasters = {
            "roads": roads_raster if roads_raster else _prep_vector(self.ROADS, "roads"),
            "builtup": builtup_small_raster,
            "builtup_large": builtup_large_raster,
            "agriculture": agri_raster,
            "custom_1": custom_rasters["custom_1"],
            "custom_2": custom_rasters["custom_2"],
            "custom_3": custom_rasters["custom_3"],
        }
        # Protected areas: raster overrides vector if both provided
        pa_raster_layer = self.parameterAsRasterLayer(
            parameters, self.PROTECTED_RASTER, context)
        if pa_raster_layer is not None:
            feedback.pushInfo("Aligning pre-rasterised protected areas...")
            pa_tif = _prep_raster(self.PROTECTED_RASTER, "protected")
        else:
            pa_tif = _prep_vector(self.PROTECTED_AREAS, "protected")

        # ─── P1.18: FRA-aligned Forest baseline ───────────────────────
        # When the user supplies an FRA agricultural tree cover layer
        # (Descals oil palm + SDPT class 2 + agroforestry) AND ticks
        # "Exclude agriculture from Forest baseline (FRA-aligned)", the
        # Forest baseline (forest_raw_path) is narrowed BEFORE the
        # plantations-exclusion / nat reg derivation. This produces a
        # FRA-strict Forest layer (tree cover meeting biophysical
        # thresholds AND not primarily agricultural land use).
        # Mirrors pff_4.js:4870 P1.18 logic.
        exclude_agriculture_from_forest = self.parameterAsBool(
            parameters, self.EXCLUDE_AGRICULTURE_FROM_FOREST, context)
        fra_agriculture_layer = self.parameterAsRasterLayer(
            parameters, self.FRA_AGRICULTURE_RASTER, context)
        fra_agriculture_tif = None
        if fra_agriculture_layer is not None:
            fra_agriculture_tif = _prep_raster(
                self.FRA_AGRICULTURE_RASTER, "fra_agriculture_tree_cover")

        if fra_agriculture_tif is not None and exclude_agriculture_from_forest:
            feedback.pushInfo(
                "P1.18: Excluding FRA agriculture (oil palm + tree crops) "
                "from Forest baseline (creating ≈ FRA-strict Forest)...")
            forest_fra_path = os.path.join(prepared_dir, "forest_fra.tif")
            _fds = gdal.Open(forest_raw_path, gdal.GA_ReadOnly)
            _farr = _fds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
            _fgt = _fds.GetGeoTransform()
            _fproj = _fds.GetProjection()
            _fxsz = _fds.RasterXSize
            _fysz = _fds.RasterYSize
            _fds = None
            _ads = gdal.Open(fra_agriculture_tif, gdal.GA_ReadOnly)
            _aarr = _ads.GetRasterBand(1).ReadAsArray().astype(np.uint8)
            _ads = None
            _farr_fra = ((_farr == 1) & (_aarr != 1)).astype(np.uint8)
            if os.path.exists(forest_fra_path):
                try:
                    os.remove(forest_fra_path)
                except OSError as e:
                    raise RuntimeError(
                        f"Cannot overwrite '{os.path.basename(forest_fra_path)}' — "
                        "it is locked. Remove it from QGIS Layers panel and retry. "
                        f"(original: {e})")
            _drv = gdal.GetDriverByName("GTiff")
            # _ds_out NOT _out -- avoid shadowing the closure helper
            _ds_out = _drv.Create(forest_fra_path, _fxsz, _fysz, 1,
                                  gdal.GDT_Byte,
                                  ["COMPRESS=LZW", "TILED=YES"])
            _ds_out.SetGeoTransform(_fgt)
            _ds_out.SetProjection(_fproj)
            _ds_out.GetRasterBand(1).WriteArray(_farr_fra)
            _ds_out.GetRasterBand(1).SetNoDataValue(0)
            _ds_out.FlushCache()
            _ds_out = None
            excluded_px = int((_farr == 1).sum() - _farr_fra.sum())
            feedback.pushInfo(
                f"  Excluded {excluded_px:,} agricultural-tree-cover pixels "
                "from Forest baseline.")
            # Switch downstream to use the FRA-stricter forest baseline.
            # The plantations exclusion block + nat reg derivation +
            # primary forest computation all read from forest_raw_path.
            forest_raw_path = forest_fra_path
            reference = forest_fra_path
        elif fra_agriculture_layer is not None and not exclude_agriculture_from_forest:
            feedback.pushInfo(
                "FRA agriculture raster prepared in "
                "intermediates/prepared/fra_agriculture_tree_cover.tif "
                "but 'Exclude agriculture from Forest baseline (FRA-aligned)' "
                "is off — Forest baseline NOT narrowed. Tick the option "
                "to apply the FRA-strict Forest definition.")

        # ─── Top-level 02b_forest.tif (FRA Forest baseline output) ───
        # Per spec, 02b_forest belongs at top level (not just as the
        # internal cache at intermediates/prepared/forest.tif). Writing
        # it as a separate file means QGIS can hold open the top-level
        # 02b_forest.tif (via auto-load) without locking the prepared/
        # cache file -- which would otherwise fail the next run's
        # forest preparation step (PermissionError on remove).
        # Reflects the post-P1.18 forest_raw_path: FRA-strict version
        # when the toggle is on, thresholded tree cover otherwise.
        forest_baseline_top_path = _out("02b", "forest")
        if os.path.exists(forest_baseline_top_path):
            try:
                os.remove(forest_baseline_top_path)
            except OSError as e:
                raise RuntimeError(
                    f"Cannot overwrite '{os.path.basename(forest_baseline_top_path)}' — "
                    "it is locked. Remove it from QGIS Layers panel and retry. "
                    f"(original: {e})")
        shutil.copy2(forest_raw_path, forest_baseline_top_path)
        feedback.pushInfo(
            f"Wrote Forest baseline to "
            f"{os.path.basename(forest_baseline_top_path)} "
            f"({'FRA-strict' if exclude_agriculture_from_forest and fra_agriculture_tif else 'thresholded tree cover'})")

        # Plantations: optional binary raster used to derive naturally
        # regenerating forest (forest AND NOT plantations).
        # Mirrors pff_4.js:4184 behaviour when "Exclude plantations" is on.
        # Always prep the raster when supplied (consistency with other anthro
        # inputs) — the file sits in prepared/ ready for re-runs even if the
        # "Exclude plantations" tickbox is off on the current run.
        # Note: when P1.18 runs above, forest_raw_path now points at
        # forest_fra.tif (FRA-stricter baseline), so the nat reg
        # derivation below operates on the FRA Forest baseline.
        exclude_plantations = self.parameterAsBool(
            parameters, self.EXCLUDE_PLANTATIONS, context)
        plantations_layer = self.parameterAsRasterLayer(
            parameters, self.PLANTATIONS_RASTER, context)
        plantations_tif = None
        forest_natreg_path = None
        if plantations_layer is not None:
            plantations_tif = _prep_raster(self.PLANTATIONS_RASTER, "plantations")

        if plantations_tif is not None and exclude_plantations:
            feedback.pushInfo(
                "Excluding plantations from forest "
                "(creating ≈ FRA Naturally Regenerating Forest layer)...")
            if True:  # (preserve existing indentation of block below)
                _fds = gdal.Open(forest_raw_path, gdal.GA_ReadOnly)
                _farr = _fds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
                _fgt = _fds.GetGeoTransform()
                _fproj = _fds.GetProjection()
                _fxsz = _fds.RasterXSize
                _fysz = _fds.RasterYSize
                _fds = None
                _pds = gdal.Open(plantations_tif, gdal.GA_ReadOnly)
                _parr = _pds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
                _pds = None
                _natreg = ((_farr == 1) & (_parr != 1)).astype(np.uint8)
                # Headline output (≈ FRA Naturally Regenerating Forest),
                # lives at top level. P1.16: renamed from
                # 04d_forest_naturally_regenerating to
                # 02d_naturally_regenerating_forest (workflow-progression
                # ordering: 02b forest -> 02c plantations -> 02d nat reg
                # = 02b minus 02c). The layer represents
                # Forest minus Plantations -- per FRA, this IS "Naturally
                # regenerating forest" (Forest decomposes as Naturally
                # regenerating + Planted). Primary forest is a subset of
                # naturally regenerating forest, not a sibling.
                forest_natreg_path = _out("02d", "naturally_regenerating_forest")
                _drv = gdal.GetDriverByName("GTiff")
                # Remove first so locked file gives a clear error.
                if os.path.exists(forest_natreg_path):
                    try:
                        os.remove(forest_natreg_path)
                    except OSError as e:
                        raise RuntimeError(
                            f"Cannot overwrite '{os.path.basename(forest_natreg_path)}' — "
                            "it is locked. Remove it from QGIS Layers panel and retry. "
                            f"(original: {e})")
                # _ds_out NOT _out -- shadowing _out (the closure helper)
                # would break downstream _out("step", "name") calls.
                _ds_out = _drv.Create(forest_natreg_path, _fxsz, _fysz, 1,
                                      gdal.GDT_Byte,
                                      ["COMPRESS=LZW", "TILED=YES"])
                _ds_out.SetGeoTransform(_fgt)
                _ds_out.SetProjection(_fproj)
                _ds_out.GetRasterBand(1).WriteArray(_natreg)
                _ds_out.GetRasterBand(1).SetNoDataValue(0)
                _ds_out.FlushCache()
                _ds_out = None
                excluded_px = int((_farr == 1).sum() - _natreg.sum())
                feedback.pushInfo(
                    f"  Excluded {excluded_px:,} plantation pixels from forest.")
                # Downstream stages operate on nat-regen forest
                reference = forest_natreg_path
        elif plantations_tif is not None and not exclude_plantations:
            feedback.pushInfo(
                "Plantations raster prepared in intermediates/prepared/plantations.tif "
                "but 'Exclude plantations' is off — plantations are NOT excluded "
                "from the forest input in this run.")
        elif plantations_layer is None and exclude_plantations:
            feedback.pushInfo(
                "'Exclude plantations' is on but no plantations raster"
                " provided — skipping exclusion.")

        # DEM / Slope: slope raster overrides DEM if provided
        slope_layer = self.parameterAsRasterLayer(
            parameters, self.SLOPE_RASTER, context)
        dem_layer = self.parameterAsRasterLayer(parameters, self.DEM, context)
        dem_path = None
        slope_path = None

        # Re-run short-circuit for slope/DEM: if the user points at our own
        # prepared/ output, skip re-processing.
        _prepared_slope = os.path.join(prepared_dir, "slope.tif")
        _prepared_dem = os.path.join(prepared_dir, "dem.tif")
        _slope_is_prepared = (
            slope_layer is not None
            and os.path.normpath(slope_layer.source()) == os.path.normpath(_prepared_slope)
        )
        _dem_is_prepared = (
            dem_layer is not None
            and os.path.normpath(dem_layer.source()) == os.path.normpath(_prepared_dem)
        )
        if _slope_is_prepared:
            feedback.pushInfo(
                "Slope input is already prepared/slope.tif — using as-is (re-run path).")
            slope_path = _prepared_slope
        elif _dem_is_prepared and slope_layer is None:
            # DEM supplied as re-run input, slope will be derived from prepared dem.tif
            feedback.pushInfo(
                "DEM input is already prepared/dem.tif — using as-is (re-run path).")
            dem_path = _prepared_dem
        elif slope_layer is not None:
            # Pre-computed slope -- align it to reference grid
            feedback.pushInfo("Aligning pre-computed slope raster...")
            slope_reproj = os.path.join(scratch_dir, "slope_reproj.tif")
            reproject_raster(slope_layer.source(), target_crs_str,
                             slope_reproj,
                             context=context, feedback=feedback)
            if aoi_mask is not None:
                slope_clip = os.path.join(scratch_dir, "slope_clipped.tif")
                clip_raster_by_mask(slope_reproj, aoi_mask, slope_clip,
                                    context=context, feedback=feedback)
                # Delete the reproj intermediate now that we have the clipped one
                try:
                    os.remove(slope_reproj)
                except OSError:
                    pass
                slope_reproj = slope_clip
            slope_path = os.path.join(prepared_dir, "slope.tif")
            _, gt_ref, xsz, ysz = get_raster_info(reference)
            ref_res = abs(gt_ref[1])
            ext = (f"{gt_ref[0]},{gt_ref[0]+gt_ref[1]*xsz},"
                   f"{gt_ref[3]+gt_ref[5]*ysz},{gt_ref[3]}")
            run_processing("gdal:warpreproject", {
                "INPUT": slope_reproj,
                "TARGET_CRS": target_crs,
                "TARGET_EXTENT": ext,
                "TARGET_EXTENT_CRS": target_crs,
                "TARGET_RESOLUTION": ref_res,
                "RESAMPLING": 0,
                "OPTIONS": "COMPRESS=LZW|TILED=YES",
                "OUTPUT": slope_path,
            }, context=context, feedback=feedback)
            # Delete the upstream intermediate now that slope.tif is final
            if slope_reproj != slope_path:
                try:
                    os.remove(slope_reproj)
                except OSError:
                    pass
        elif dem_layer is not None:
            feedback.pushInfo("Aligning DEM...")
            dem_reproj = os.path.join(scratch_dir, "dem_reproj.tif")
            reproject_raster(dem_layer.source(), target_crs_str, dem_reproj,
                             context=context, feedback=feedback)
            if aoi_mask is not None:
                dem_clip = os.path.join(scratch_dir, "dem_clipped.tif")
                clip_raster_by_mask(dem_reproj, aoi_mask, dem_clip,
                                    context=context, feedback=feedback)
                try:
                    os.remove(dem_reproj)
                except OSError:
                    pass
                dem_reproj = dem_clip
            dem_path = os.path.join(prepared_dir, "dem.tif")
            _, gt_ref, xsz, ysz = get_raster_info(reference)
            ref_res = abs(gt_ref[1])
            ext = (f"{gt_ref[0]},{gt_ref[0]+gt_ref[1]*xsz},"
                   f"{gt_ref[3]+gt_ref[5]*ysz},{gt_ref[3]}")
            run_processing("gdal:warpreproject", {
                "INPUT": dem_reproj,
                "TARGET_CRS": target_crs,
                "TARGET_EXTENT": ext,
                "TARGET_EXTENT_CRS": target_crs,
                "TARGET_RESOLUTION": ref_res,
                "RESAMPLING": 0,
                "OPTIONS": "COMPRESS=LZW|TILED=YES",
                "OUTPUT": dem_path,
            }, context=context, feedback=feedback)
            if dem_reproj != dem_path:
                try:
                    os.remove(dem_reproj)
                except OSError:
                    pass

        feedback.setProgress(20)

        # ================================================================
        #  STAGE 2 -- Distance surfaces
        # ================================================================
        _stage("STAGE 2: Distance Surfaces")
        if reuse_distances:
            feedback.pushInfo("  Reuse ticked: existing dist_*.tif will be reused if the grid matches.")
        else:
            feedback.pushInfo("  Reuse unticked (default): distances will be computed fresh.")
        # Read reference grid dimensions for cache validation
        _ref_ds = gdal.Open(reference, gdal.GA_ReadOnly)
        ref_x = _ref_ds.RasterXSize
        ref_y = _ref_ds.RasterYSize
        _ref_ds = None

        dist_paths = {}
        for name, raster_path in rasters.items():
            if feedback.isCanceled():
                # Was: silent break (continued into Stage 3 with partial
                # dist_paths and produced nonsense). Now raises so cancel
                # honoured loudly.
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    f"Cancelled by user (during distance surfaces, "
                    f"before completing '{name}').")
            if raster_path is None:
                continue
            if not enable_buffers.get(name, True):
                feedback.pushInfo(f"Skipping {name} — 'Include {name} buffer' is unticked.")
                continue
            dp = os.path.join(dist_dir, f"dist_{name}.tif")
            use_cache = False
            # Only consider cache reuse when user explicitly ticked Reuse.
            if reuse_distances and os.path.exists(dp):
                # Validate cached file matches reference grid
                _cds = gdal.Open(dp, gdal.GA_ReadOnly)
                if _cds and _cds.RasterXSize == ref_x and _cds.RasterYSize == ref_y:
                    use_cache = True
                    feedback.pushInfo(f"Using cached: {dp}")
                else:
                    feedback.pushInfo(f"Cached {name} has wrong dimensions, recomputing...")
                if _cds:
                    _cds = None
            if not use_cache:
                # Delete stale cached file before recomputing
                if os.path.exists(dp):
                    os.remove(dp)
                feedback.pushInfo(f"Computing distance for {name}...")
                proximity(raster_path, dp, max_distance=max_dist,
                          context=context, feedback=feedback)
            dist_paths[name] = dp

        feedback.setProgress(45)

        # ================================================================
        #  STAGE 3 -- Anthropogenic mask
        # ================================================================
        _stage("STAGE 3: Anthropogenic Mask")

        # Read reference dimensions
        ref_ds = gdal.Open(reference, gdal.GA_ReadOnly)
        x_size = ref_ds.RasterXSize
        y_size = ref_ds.RasterYSize
        gt = ref_ds.GetGeoTransform()
        proj = ref_ds.GetProjection()
        ref_ds = None

        combined_mask = np.zeros((y_size, x_size), dtype=np.uint8)
        for name, dp in dist_paths.items():
            if feedback.isCanceled():
                # Was: silent break (then wrote a half-built anthro mask).
                # Now raises so cancel honoured loudly.
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    f"Cancelled by user (during anthropogenic mask, "
                    f"before applying '{name}' threshold).")
            thresh = thresholds.get(name, 0)
            if thresh < 0:
                # Negative is invalid -- skip with a warning.
                feedback.pushWarning(
                    f"  Negative buffer ({thresh:g} m) for {name} -- skipping.")
                continue
            if thresh == 0:
                # P0.15 (zero-buffer rule, decided 2026-04-26): when input
                # is enabled AND buffer = 0, apply the input footprint
                # directly -- forest pixels coinciding with the input
                # become anthropogenic, but no buffer expansion. This is
                # the user's explicit "I want this layer to count but
                # without distance buffering" semantic.
                #
                # If thresh == 0 AND user didn't want the input at all,
                # they should untick the per-input enable_buffers checkbox
                # (which prevents the input ever entering rasters / dist_paths).
                input_path = rasters.get(name)
                if input_path is None or not os.path.exists(input_path):
                    feedback.pushInfo(
                        f"  Buffer = 0 for {name}, but no input raster "
                        "found in rasters dict -- skipping.")
                    continue
                feedback.pushInfo(
                    f"Buffer = 0 for {name}: applying input footprint "
                    "directly (no buffer expansion). To skip the input "
                    "entirely instead, untick its 'Include ... buffer' "
                    "checkbox.")
                ds = gdal.Open(input_path, gdal.GA_ReadOnly)
                arr = ds.GetRasterBand(1).ReadAsArray()
                ds = None
                combined_mask = np.maximum(
                    combined_mask, (arr == 1).astype(np.uint8))
                continue
            feedback.pushInfo(f"Thresholding {name} at {thresh} m...")
            ds = gdal.Open(dp, gdal.GA_ReadOnly)
            arr = ds.GetRasterBand(1).ReadAsArray()
            ds = None
            combined_mask = np.maximum(
                combined_mask, (arr <= thresh).astype(np.uint8))

        anthro_path = _out("04e", "anthropogenic_mask")
        _write(anthro_path, combined_mask, gt, proj, x_size, y_size)
        feedback.setProgress(55)

        # ================================================================
        #  STAGE 4 -- Primary forest tiers
        # ================================================================
        _stage("STAGE 4: Primary Forest Logic")

        forest_ds = gdal.Open(reference, gdal.GA_ReadOnly)
        forest = forest_ds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
        forest_ds = None

        # Tier 1 -- undisturbed forest (GEE canonical name: tier1_undisturbed)
        feedback.pushInfo("Tier 1 -- undisturbed forest...")
        tier1_undisturbed = ((forest == 1) & (combined_mask == 0)).astype(np.uint8)
        forest_inside_buffers = ((forest == 1) & (combined_mask == 1)).astype(np.uint8)
        _write(os.path.join(intermediates_dir, "tier1_undisturbed.tif"),
               tier1_undisturbed, gt, proj, x_size, y_size)
        _write(os.path.join(intermediates_dir, "forest_inside_buffers.tif"),
               forest_inside_buffers, gt, proj, x_size, y_size)

        # Slope -- use pre-computed slope if provided, else derive from DEM
        steep = None
        gentle = None
        slope_arr = None

        def _read_aligned(path, label):
            """Read a raster array, re-aligning to reference grid if needed."""
            ds = gdal.Open(path, gdal.GA_ReadOnly)
            arr = ds.GetRasterBand(1).ReadAsArray()
            ds = None
            if arr.shape != (y_size, x_size):
                feedback.pushInfo(
                    f"Re-aligning {label} from {arr.shape} to "
                    f"({y_size},{x_size})...")
                aligned_path = path.replace(".tif", "_realigned.tif")
                _, gt_ref, xsz, ysz = get_raster_info(reference)
                ref_res = abs(gt_ref[1])
                ext = (f"{gt_ref[0]},{gt_ref[0]+gt_ref[1]*xsz},"
                       f"{gt_ref[3]+gt_ref[5]*ysz},{gt_ref[3]}")
                run_processing("gdal:warpreproject", {
                    "INPUT": path,
                    "TARGET_CRS": target_crs,
                    "TARGET_EXTENT": ext,
                    "TARGET_EXTENT_CRS": target_crs,
                    "TARGET_RESOLUTION": ref_res,
                    "RESAMPLING": 0,
                    "OPTIONS": "COMPRESS=LZW|TILED=YES",
                    "OUTPUT": aligned_path,
                }, context=context, feedback=feedback)
                ds = gdal.Open(aligned_path, gdal.GA_ReadOnly)
                arr = ds.GetRasterBand(1).ReadAsArray()
                ds = None
            return arr

        if slope_path is not None:
            feedback.pushInfo("Using pre-computed slope raster...")
            slope_arr = _read_aligned(slope_path, "slope")
        elif dem_path is not None:
            feedback.pushInfo("Computing slope from DEM...")
            # Write into prepared/ so it sits alongside other aligned inputs
            # (consistent with anthro rasters, reusable in fast re-runs).
            slope_path = os.path.join(prepared_dir, "slope.tif")
            run_processing("gdal:slope", {
                "INPUT": dem_path,
                "BAND": 1, "SCALE": 1, "AS_PERCENT": False,
                "OPTIONS": "COMPRESS=LZW|TILED=YES",
                "OUTPUT": slope_path,
            }, context=context, feedback=feedback)
            slope_arr = _read_aligned(slope_path, "slope")

        if slope_arr is not None:
            steep = (slope_arr >= slope_thresh).astype(np.uint8)
            gentle = (slope_arr < slope_thresh).astype(np.uint8)
            _write(os.path.join(intermediates_dir, "steep_slope.tif"),
                   steep, gt, proj, x_size, y_size)
            _write(os.path.join(intermediates_dir, "gentle_slope.tif"),
                   gentle, gt, proj, x_size, y_size)

        # Tier 2 -- steep slope forest (GEE canonical name: tier2_steep)
        tier2_steep = np.zeros_like(forest)
        if steep is not None:
            feedback.pushInfo(
                f"Tier 2 -- steep slope forest (slope >= {slope_thresh:g} deg)...")
            tier2_steep = (
                (forest_inside_buffers == 1) & (steep == 1)
            ).astype(np.uint8)
            _write(os.path.join(intermediates_dir, "tier2_steep.tif"),
                   tier2_steep, gt, proj, x_size, y_size)

        # Tier 3 -- protected gentle-slope forest (GEE canonical name: tier3_protected)
        tier3_protected = np.zeros_like(forest)
        if pa_tif is not None and gentle is not None:
            feedback.pushInfo("Tier 3 -- protected gentle-slope forest...")
            pa = _read_aligned(pa_tif, "protected areas").astype(np.uint8)
            tier3_protected = (
                (forest_inside_buffers == 1) & (gentle == 1) & (pa == 1)
            ).astype(np.uint8)
            _write(os.path.join(intermediates_dir, "tier3_protected.tif"),
                   tier3_protected, gt, proj, x_size, y_size)

        # Combine
        feedback.pushInfo("Combining tiers -> pre_connectivity_forest...")
        primary_candidate = np.maximum(
            np.maximum(tier1_undisturbed, tier2_steep),
            tier3_protected,
        )
        # Aligned naming: pre_connectivity_forest (matches pFF_4)
        candidate_path = _out("03c", "pre_connectivity_primary_forest")
        _write(candidate_path, primary_candidate, gt, proj, x_size, y_size)
        feedback.setProgress(80)

        # ================================================================
        #  STAGE 5 -- Refine output: two optional steps
        #    (a) Neighbourhood density filter
        #    (b) Minimum patch size filter (raster sieve)
        #  Both off (or master tickbox unticked) -> primary_forest.tif
        #  is just a copy of pre_connectivity_forest.tif.
        # ================================================================
        # Aligned naming: primary_forest (matches pFF_4 GEE export name)
        final_path = _out("04a", "primary_forest")
        step_a_on = enable_refine_output and smooth_radius > 0
        step_b_on = enable_refine_output and refine_min_patch_area_ha > 0

        if step_a_on or step_b_on:
            _stage("STAGE 5: Refine Output")
            fast_approx = self.parameterAsBool(
                parameters, self.FAST_APPROXIMATION, context)

            # Decide intermediate path layout:
            #  both steps -> step (a) writes to scratch, step (b) -> final
            #  only (a)   -> step (a) writes to final
            #  only (b)   -> step (b) reads candidate, writes final
            if step_a_on and step_b_on:
                step_a_out = os.path.join(
                    intermediates_dir, "refine_step_a_neighbourhood.tif")
                step_b_in = step_a_out
            elif step_a_on:
                step_a_out = final_path
                step_b_in = None
            else:
                step_a_out = None
                step_b_in = candidate_path

            if step_a_on:
                feedback.pushInfo(
                    f"Step (a) Neighbourhood density "
                    f"(radius={smooth_radius:g} m, "
                    f"density>={density_thresh:g}, fast={fast_approx})...")
                from .connectivity_filter import refine_output
                refine_output(candidate_path, step_a_out,
                              radius_m=smooth_radius,
                              threshold=density_thresh,
                              fast_approximation=fast_approx,
                              feedback=feedback)

            if feedback.isCanceled():
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    "Cancelled by user (between Refine Output steps).")

            if step_b_on:
                # Compute pixel-count threshold from hectares + pixel area.
                _res = abs(gt[1])
                _pixel_area_m2 = _res * _res
                import math as _math
                _min_area_m2 = refine_min_patch_area_ha * 10000.0
                _threshold_px = max(
                    1, _math.ceil(_min_area_m2 / _pixel_area_m2))
                feedback.pushInfo(
                    f"Step (b) Minimum patch size: removing connected "
                    f"groups < {_threshold_px} px "
                    f"(~{refine_min_patch_area_ha:g} ha) via gdal:sieve...")

                # Sieve to scratch first, then mask back to step_b_in
                # (the input to step b). gdal:sieve fills small "0-holes"
                # inside larger "1" regions by replacing them with the
                # surrounding value -- without the mask-back, the final
                # output would include pixels that were never forest.
                # Mirrors the mask-back-to-input principle Step (a)'s
                # neighbourhood filter already applies internally.
                _sieve_tmp = os.path.join(
                    intermediates_dir, "refine_step_b_sieve_unmasked.tif")
                run_processing("gdal:sieve", {
                    "INPUT": step_b_in,
                    "THRESHOLD": _threshold_px,
                    "EIGHT_CONNECTEDNESS": False,
                    "OUTPUT": _sieve_tmp,
                }, context=context, feedback=feedback)

                feedback.pushInfo(
                    "Step (b) masking sieve result back to step (b) input "
                    "(prevents hole-fill from creating pixels outside the "
                    "input forest extent)...")
                _ds_sv = gdal.Open(_sieve_tmp, gdal.GA_ReadOnly)
                _sv_arr = _ds_sv.GetRasterBand(1).ReadAsArray()
                _sv_gt = _ds_sv.GetGeoTransform()
                _sv_proj = _ds_sv.GetProjection()
                _sv_xsz = _ds_sv.RasterXSize
                _sv_ysz = _ds_sv.RasterYSize
                _ds_sv = None
                _ds_in = gdal.Open(step_b_in, gdal.GA_ReadOnly)
                _in_arr = _ds_in.GetRasterBand(1).ReadAsArray()
                _ds_in = None
                _masked = (
                    (_sv_arr == 1) & (_in_arr == 1)).astype(np.uint8)
                if os.path.exists(final_path):
                    try:
                        os.remove(final_path)
                    except OSError:
                        pass
                _drv = gdal.GetDriverByName("GTiff")
                _ds_out = _drv.Create(final_path, _sv_xsz, _sv_ysz, 1,
                                      gdal.GDT_Byte,
                                      ["COMPRESS=LZW", "TILED=YES"])
                _ds_out.SetGeoTransform(_sv_gt)
                _ds_out.SetProjection(_sv_proj)
                _ob = _ds_out.GetRasterBand(1)
                _ob.WriteArray(_masked)
                _ob.SetNoDataValue(0)
                _ob.FlushCache()
                _ds_out = None
        else:
            if not enable_refine_output:
                feedback.pushInfo(
                    "Skipping Refine Output (master tickbox off) -- "
                    "04a_primary_forest.tif copied from "
                    "03c_pre_connectivity_primary_forest.tif.")
            else:
                feedback.pushInfo(
                    "Skipping Refine Output (both Step (a) radius and "
                    "Step (b) min patch area are 0).")
            run_processing("gdal:translate", {
                "INPUT": candidate_path, "OUTPUT": final_path,
            }, context=context, feedback=feedback)

        # -- Optional combined coded raster --
        if save_combined:
            feedback.pushInfo("Building combined coded raster...")
            final_ds = gdal.Open(final_path, gdal.GA_ReadOnly)
            final_arr = final_ds.GetRasterBand(1).ReadAsArray().astype(
                np.uint8)
            final_ds = None

            combined = np.zeros((y_size, x_size), dtype=np.uint8)
            combined[forest == 1] = 1
            combined[primary_candidate == 1] = 2
            combined[final_arr == 1] = 3

            combined_path = _out("03d", "combined_coded_raster")
            _write(combined_path, combined, gt, proj, x_size, y_size)
            feedback.pushInfo(
                "Combined coded raster: 0=none, 1=forest, "
                "2=pre-connectivity, 3=primary forest candidate")

        # ================================================================
        #  STAGE 6 -- Zonal statistics (optional)
        # ================================================================
        run_zonal = self.parameterAsBool(
            parameters, self.RUN_ZONAL_STATS, context)

        if run_zonal:
            _stage("STAGE 6: Zonal Statistics")

            from .zonal_statistics import (
                compute_zonal_stats, write_zonal_csv,
                join_stats_to_vector)

            # Three-tier FRA cascade when plantations exclusion is active:
            #   Forest (raw input, includes plantations)
            #   Naturally regenerating forest (= forest AND NOT plantations)
            #   Primary forest (final tier output)
            # Otherwise just Forest + Primary forest (two-tier).
            zonal_rasters = {"forest": forest_raw_path}
            if forest_natreg_path is not None:
                zonal_rasters["naturally_regenerating_forest"] = forest_natreg_path
            zonal_rasters["primary_forest"] = final_path

            zone_layer = self.parameterAsVectorLayer(
                parameters, self.ZONE_LAYER, context)
            zone_path = zone_layer.source() if zone_layer else None
            zone_field = None
            if zone_path:
                zone_field = (self.parameterAsString(
                    parameters, self.ZONE_FIELD, context).strip() or None)

            zonal_work = ensure_dir(os.path.join(intermediates_dir, "zonal_work"))

            results, totals = compute_zonal_stats(
                ref_raster_path=final_path,
                raster_paths=zonal_rasters,
                zone_layer_path=zone_path,
                zone_field=zone_field,
                target_crs_str=target_crs_str,
                work_dir=zonal_work,
                context=context,
                feedback=feedback,
            )

            # Print headline totals
            if totals:
                feedback.pushInfo("")
                feedback.pushInfo("========================================")
                for label, kha in totals.items():
                    feedback.pushInfo(f"  {label}: {kha} kha")
                feedback.pushInfo("========================================")
            elif results:
                feedback.pushInfo("")
                feedback.pushInfo("========================================")
                for label in zonal_rasters:
                    key = f"{label}_kha"
                    if key in results[0]:
                        feedback.pushInfo(
                            f"  {label}: {results[0][key]} kha")
                feedback.pushInfo("========================================")

            # CSV
            if results:
                zonal_csv = _out("05a", "area_statistics", ext="csv")
                write_zonal_csv(results, totals, zonal_csv, feedback)

            # Join to vector (if zones provided)
            if results and zone_path:
                zone_with_id = os.path.join(
                    zonal_work, "zones_with_id.shp")
                zonal_vec = _out("05b", "area_statistics_by_zone", ext="shp")
                join_stats_to_vector(
                    results, zone_with_id, zonal_vec,
                    target_crs_str, context, feedback)

        # ================================================================
        #  STAGE 7 -- Vectorise (optional, advanced)
        # ================================================================
        # Polygonises selected outputs (primary forest and/or forest
        # input) into .gpkg files, with optional Douglas-Peucker
        # simplification and optional CEO-style nesting (cut primary
        # out of forest so the two layers don't overlap).
        #
        # P1.13 filenames (Option D):
        #   primary forest -> 06a_primary_forest_vector.gpkg
        #                   + 06b_primary_forest_dissolved.gpkg
        #   forest input   -> 06c_<forest_layer_name>_vector.gpkg
        #                   + 06d_<forest_layer_name>_dissolved.gpkg
        # Whether naturally_regenerating_forest or forest is used is
        # determined by whether plantations refinement ran
        # (forest_natreg_path is non-None when it did). P1.16 renamed
        # the source layer to naturally_regenerating_forest; the
        # variable name forest_natreg_path was already aligned (natreg
        # = nat reg).
        # ================================================================
        if run_vectorize and (vectorize_primary or vectorize_forest):
            _stage("STAGE 7: Vectorise outputs")
            vector_scratch = ensure_dir(
                os.path.join(intermediates_dir, "_vectorize"))

            def _do_polygonise(src_raster_path, step, layer_name):
                """Mask + polygonise + optional simplify. Returns polys path.

                Args:
                    src_raster_path: source raster (binary 0/1).
                    step: Option D step substring e.g. '06a'.
                    layer_name: snake-case descriptor without _vector
                                suffix or extension (e.g. 'primary_forest').
                                The function appends '_vector' and '.gpkg'.
                """
                polys_path = _out(step, f"{layer_name}_vector", ext="gpkg")
                # Build mask raster with nodata=0 so polygonize skips
                # background efficiently. Source rasters are already
                # binary 0/1, so the mask is just (arr == 1).
                _ds_v = gdal.Open(src_raster_path, gdal.GA_ReadOnly)
                _v_arr = _ds_v.GetRasterBand(1).ReadAsArray()
                _v_gt = _ds_v.GetGeoTransform()
                _v_proj = _ds_v.GetProjection()
                _v_xsz = _ds_v.RasterXSize
                _v_ysz = _ds_v.RasterYSize
                _ds_v = None
                _v_mask = (_v_arr == 1).astype(np.uint8)
                _v_masked_tif = os.path.join(
                    vector_scratch, f"{layer_name}_masked.tif")
                if os.path.exists(_v_masked_tif):
                    try:
                        os.remove(_v_masked_tif)
                    except OSError:
                        pass
                _drv_v = gdal.GetDriverByName("GTiff")
                _ds_o = _drv_v.Create(_v_masked_tif, _v_xsz, _v_ysz, 1,
                                      gdal.GDT_Byte,
                                      ["COMPRESS=LZW", "TILED=YES"])
                _ds_o.SetGeoTransform(_v_gt)
                _ds_o.SetProjection(_v_proj)
                _ob = _ds_o.GetRasterBand(1)
                _ob.WriteArray(_v_mask)
                _ob.SetNoDataValue(0)
                _ob.FlushCache()
                _ds_o = None
                del _v_arr, _v_mask

                if vectorize_simplify_m > 0:
                    polys_tmp = os.path.join(
                        vector_scratch, f"{layer_name}_polys_raw.gpkg")
                else:
                    polys_tmp = polys_path

                feedback.pushInfo(
                    f"  Polygonising {layer_name} (gdal:polygonize, "
                    "4-connected)...")
                run_processing("gdal:polygonize", {
                    "INPUT": _v_masked_tif,
                    "BAND": 1,
                    "FIELD": "value",
                    "EIGHT_CONNECTEDNESS": False,
                    "EXTRA": "",
                    "OUTPUT": polys_tmp,
                }, context=context, feedback=feedback)

                if vectorize_simplify_m > 0:
                    feedback.pushInfo(
                        f"  Simplifying {layer_name} (Douglas-Peucker, "
                        f"tolerance={vectorize_simplify_m:g} m)...")
                    feedback.pushWarning(
                        "Simplify can introduce geometry artefacts; "
                        "reduce tolerance if downstream tools throw "
                        "errors.")
                    run_processing("native:simplifygeometries", {
                        "INPUT": polys_tmp,
                        "METHOD": 0,
                        "TOLERANCE": vectorize_simplify_m,
                        "OUTPUT": polys_path,
                    }, context=context, feedback=feedback)

                return polys_path

            # ── Vectorise primary forest ──
            primary_polys_path = None
            if vectorize_primary:
                primary_polys_path = _do_polygonise(
                    final_path, "06a", "primary_forest")

            if feedback.isCanceled():
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    "Cancelled by user (during vectorise stage).")

            # ── Vectorise forest input ──
            # Use naturally regenerating forest if plantations refinement
            # produced one, else the AOI-clipped forest input. Naming
            # carries to the output filenames so the user can tell
            # which they got.
            forest_polys_path = None
            forest_name_base = None
            if vectorize_forest:
                if forest_natreg_path is not None:
                    forest_src_path = forest_natreg_path
                    forest_name_base = "naturally_regenerating_forest"
                else:
                    forest_src_path = prepared_forest_path
                    forest_name_base = "forest"
                forest_polys_path = _do_polygonise(
                    forest_src_path, "06c", forest_name_base)

            if feedback.isCanceled():
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    "Cancelled by user (during vectorise stage).")

            # ── Optional nesting: cut primary out of forest ──
            # Only meaningful when both are vectorised. Result: primary
            # polygons are unchanged, forest polygons have primary
            # subtracted -- the two layers tile the forest extent
            # without overlap, which is the standard CEO stratified-
            # sampling layout (sample primary plots + non-primary
            # plots independently with no double-counting).
            if vectorize_nest:
                if vectorize_primary and vectorize_forest:
                    feedback.pushInfo(
                        f"  Nesting: cutting primary_forest out of "
                        f"{forest_name_base} so the two layers don't "
                        "overlap (CEO stratification)...")
                    _diff_tmp = os.path.join(
                        vector_scratch,
                        f"{forest_name_base}_minus_primary.gpkg")
                    if os.path.exists(_diff_tmp):
                        try:
                            os.remove(_diff_tmp)
                        except OSError:
                            pass
                    run_processing("native:difference", {
                        "INPUT": forest_polys_path,
                        "OVERLAY": primary_polys_path,
                        "OUTPUT": _diff_tmp,
                    }, context=context, feedback=feedback)
                    # Replace forest polygons with the differenced
                    # version. .gpkg can't be overwritten in-place, so
                    # delete + rename.
                    if os.path.exists(forest_polys_path):
                        try:
                            os.remove(forest_polys_path)
                        except OSError:
                            pass
                    os.rename(_diff_tmp, forest_polys_path)
                else:
                    feedback.pushWarning(
                        "Vectorise nesting is on but only one of "
                        "primary / forest was selected -- nesting "
                        "skipped (needs both).")

            if feedback.isCanceled():
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    "Cancelled by user (during vectorise stage).")

            # ── Dissolve each to multipart ──
            # Dissolve happens after potential nesting so the dissolved
            # output reflects the final (possibly differenced) geometry.
            if vectorize_primary:
                _primary_dissolved = _out(
                    "06b", "primary_forest_dissolved", ext="gpkg")
                feedback.pushInfo(
                    "  Dissolving primary_forest to multipart...")
                run_processing("native:dissolve", {
                    "INPUT": primary_polys_path,
                    "FIELD": [],
                    "OUTPUT": _primary_dissolved,
                }, context=context, feedback=feedback)

            if vectorize_forest:
                _forest_dissolved = _out(
                    "06d", f"{forest_name_base}_dissolved", ext="gpkg")
                feedback.pushInfo(
                    f"  Dissolving {forest_name_base} to multipart...")
                run_processing("native:dissolve", {
                    "INPUT": forest_polys_path,
                    "FIELD": [],
                    "OUTPUT": _forest_dissolved,
                }, context=context, feedback=feedback)

        # ================================================================
        #  Write run metadata
        # ================================================================
        _close_last_stage()
        _pff_total_runtime = round(_pff_time.monotonic() - _pff_t_start, 2)
        feedback.pushInfo(f"Total runtime: {_pff_total_runtime:.1f}s")

        import json
        from datetime import datetime
        metadata = {
            "pff_version": self.PFF_VERSION,
            "timestamp": datetime.now().isoformat(),
            "runtime_seconds": _pff_total_runtime,
            "stage_runtimes_seconds": _pff_stage_times,
            "target_crs": target_crs_str,
            "parameters": {
                "aoi_buffer_m": aoi_buffer_dist,
                "use_single_buffer_distance": use_single,
                "single_buffer_distance_m": single_dist if use_single else None,
                "reuse_cached_distances": reuse_distances,
                "reuse_prepared": reuse_prepared,
                "roads_dist_m": thresholds["roads"],
                "builtup_dist_m": thresholds["builtup"],
                "builtup_large_dist_m": thresholds["builtup_large"],
                "agriculture_dist_m": thresholds["agriculture"],
                "max_distance_m": max_dist,
                "slope_threshold_deg": slope_thresh,
                "smooth_radius_m": smooth_radius,
                "density_threshold": density_thresh,
                "refine_min_patch_area_ha": refine_min_patch_area_ha,
                "run_vectorize": run_vectorize,
                "vectorize_primary": vectorize_primary if run_vectorize else None,
                "vectorize_forest": vectorize_forest if run_vectorize else None,
                "vectorize_nest": vectorize_nest if run_vectorize else None,
                "vectorize_simplify_m": vectorize_simplify_m if run_vectorize else None,
                "auto_utm": auto_utm,
                "exclude_plantations": exclude_plantations,
                "plantations_applied": forest_natreg_path is not None,
                "exclude_agriculture_from_forest": exclude_agriculture_from_forest,
                "fra_agriculture_applied": (
                    fra_agriculture_tif is not None
                    and exclude_agriculture_from_forest),
                "custom_slots": {
                    key: {
                        "label": custom_slot_labels.get(key, key),
                        "buffer_dist_m": thresholds.get(key),
                    } for key in custom_slot_labels
                },
            },
            "inputs": {
                "forest_raster": forest_layer.source(),
                "aoi": aoi_layer.source() if aoi_layer else None,
                "dem": dem_layer.source() if dem_layer else None,
                "plantations": (plantations_layer.source()
                                if plantations_layer else None),
            },
            "outputs": {
                "primary_forest": final_path,
                "pre_connectivity_forest": candidate_path,
                "anthropogenic_mask": anthro_path,
                "forest": forest_baseline_top_path,
                "naturally_regenerating_forest": forest_natreg_path,
            },
            "raster_properties": {
                "x_size": x_size,
                "y_size": y_size,
                "resolution_m": abs(gt[1]),
            },
        }
        # P1.13: run metadata sidecar gets ISO3 prefix when set; otherwise
        # plain run_metadata.json. No step number — it's a contextual sidecar,
        # not a per-stage layer.
        meta_path = os.path.join(
            out_dir,
            (f"{_iso3}_qgis_run_metadata.json" if _iso3
             else "qgis_run_metadata.json"))
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        feedback.pushInfo(f"Metadata: {meta_path}")

        # ── Auto-load main outputs into the QGIS project (P0.5 partial) ──
        # Uses the standard Processing pattern -- works in GUI mode, no-ops
        # cleanly in headless mode. Layer styling defaults; QML preload is
        # a separate task (deferred -- needs a colour scheme decision).
        from qgis.core import QgsProcessingContext
        _layers_to_load = []  # list of (display_name, path) tuples

        if add_main_outputs_to_map:
            # Order matters: QGIS adds each new layer ABOVE the
            # previous one in the Layers panel, so to get the GEE
            # default panel order (Primary on top, then Pre-connectivity,
            # then Naturally regenerating, then Forest at the bottom)
            # we register in REVERSE -- last appended ends up on top.
            _forest_top_path = _out("02b", "forest")
            if os.path.exists(_forest_top_path):
                _layers_to_load.append(("Forest", _forest_top_path))
            if forest_natreg_path is not None and os.path.exists(forest_natreg_path):
                _layers_to_load.append(
                    ("Naturally regenerating forest", forest_natreg_path))
            if os.path.exists(candidate_path):
                _layers_to_load.append(
                    ("Pre-connectivity forest", candidate_path))
            _layers_to_load.append(("Primary forest", final_path))

        # P0.14: optional human-influence + buffer layers. Default OFF
        # (matches GEE master toggle). Adds the prepared anthro inputs +
        # protection inputs + plantations + custom slots + the combined
        # anthropogenic mask. Distance-surface intermediates are
        # deliberately skipped -- they're internal continuous-value
        # rasters that aren't useful as visual review layers without
        # styling.
        if add_human_influence_layers_to_map:
            _hi_candidates = [
                ("Input: Roads",            os.path.join(prepared_dir, "roads.tif")),
                ("Input: Built-up small",   os.path.join(prepared_dir, "builtup_small.tif")),
                ("Input: Built-up large",   os.path.join(prepared_dir, "builtup_large.tif")),
                ("Input: Agriculture",      os.path.join(prepared_dir, "agriculture.tif")),
                ("Input: Plantations",      os.path.join(prepared_dir, "plantations.tif")),
                ("Input: Protected areas",  os.path.join(prepared_dir, "protected.tif")),
                ("Input: Slope (degrees)",  os.path.join(prepared_dir, "slope.tif")),
            ]
            # Custom human-use slots get their user-editable label.
            for _i in (1, 2, 3):
                _key = f"custom_{_i}"
                _label = custom_slot_labels.get(
                    _key, f"Custom disturbance {_i}")
                _hi_candidates.append(
                    (f"Input: {_label}",
                     os.path.join(prepared_dir, f"{_key}.tif")))
            # Note: anthropogenic_mask intentionally NOT auto-loaded
            # by default -- it's a debug/intermediate output, not a
            # headline review layer. Available at <out>/04e_anthropogenic_mask.tif
            # for users who want to inspect it manually.
            for _name, _path in _hi_candidates:
                if os.path.exists(_path):
                    _layers_to_load.append((_name, _path))

        if _layers_to_load:
            for _name, _path in _layers_to_load:
                _details = QgsProcessingContext.LayerDetails(
                    _name, context.project(), _name)
                context.addLayerToLoadOnCompletion(_path, _details)
            feedback.pushInfo(
                f"Auto-loading {len(_layers_to_load)} layer(s) on "
                "completion: " + ", ".join(n for n, _ in _layers_to_load))

        feedback.setProgress(100)
        feedback.pushInfo("Done. Full PFF workflow complete.")
        feedback.pushInfo(f"Final output: {final_path}")
        return {self.OUTPUT_FOLDER: out_dir}


# -- Utilities --------------------------------------------------------

def _write(path, array, gt, proj, x_size, y_size):
    """Create a Byte GeoTIFF and write the array. Handles the common case
    where the destination file is locked by another process (typically QGIS
    itself holding it open as an already-added layer from a prior run).
    """
    driver = gdal.GetDriverByName("GTiff")
    # Try to remove the existing file first. If it's locked (Windows file
    # lock from QGIS, OneDrive sync, etc.), raise a clear error instead of
    # the bare "RuntimeError" GDAL produces.
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError as e:
            raise RuntimeError(
                f"Cannot overwrite output file '{os.path.basename(path)}' — "
                f"it is locked by another process. Remove the layer from "
                f"the QGIS Layers panel (right-click → Remove Layer), close "
                f"any program that has it open, then re-run. (original: {e})"
            )
    ds = driver.Create(path, x_size, y_size, 1, gdal.GDT_Byte,
                       options=["COMPRESS=LZW", "TILED=YES"])
    if ds is None:
        raise RuntimeError(
            f"Could not create output file '{os.path.basename(path)}' — "
            f"check folder permissions and disk space. Full path: {path}"
        )
    ds.SetGeoTransform(gt)
    ds.SetProjection(proj)
    band = ds.GetRasterBand(1)
    band.WriteArray(array)
    band.SetNoDataValue(0)
    band.FlushCache()
    ds = None


def _detect_utm_zone(forest_layer, aoi_layer, feedback):
    """Determine the appropriate UTM zone from AOI centroid or forest raster.

    Returns an EPSG code string like 'EPSG:32717'.
    """
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject

    # Get centroid in WGS84
    if aoi_layer is not None:
        extent = aoi_layer.extent()
        src_crs = aoi_layer.crs()
    else:
        extent = forest_layer.extent()
        src_crs = forest_layer.crs()

    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    if src_crs != wgs84:
        transform = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())
        extent = transform.transformBoundingBox(extent)

    lon = extent.center().x()
    lat = extent.center().y()
    lon_width = extent.width()

    # UTM zone number: 1-60
    zone = int((lon + 180) / 6) + 1
    zone = max(1, min(60, zone))

    # EPSG code: 326xx for north, 327xx for south
    if lat >= 0:
        epsg = 32600 + zone
    else:
        epsg = 32700 + zone

    feedback.pushInfo(
        f"Auto UTM: centroid ({lat:.2f}, {lon:.2f}) -> "
        f"EPSG:{epsg} (UTM zone {zone}{'N' if lat >= 0 else 'S'})")

    # Warn if AOI spans more than one UTM zone (>6 degrees longitude)
    if lon_width > 6:
        n_zones = int(lon_width / 6) + 1
        feedback.reportError(
            f"WARNING: AOI spans ~{lon_width:.0f} degrees of longitude "
            f"(~{n_zones} UTM zones). A single UTM zone may cause "
            f"significant distortion at the edges. Consider using a "
            f"wider-coverage CRS (e.g. a continental equal-area projection) "
            f"instead of Auto UTM.")

    return f"EPSG:{epsg}"

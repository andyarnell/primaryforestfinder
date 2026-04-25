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
    DEM = "DEM"
    SLOPE_RASTER = "SLOPE_RASTER"
    PROTECTED_AREAS = "PROTECTED_AREAS"
    PROTECTED_RASTER = "PROTECTED_RASTER"
    PLANTATIONS_RASTER = "PLANTATIONS_RASTER"
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
    SAVE_COMBINED_RASTER = "SAVE_COMBINED_RASTER"
    EXCLUDE_PLANTATIONS = "EXCLUDE_PLANTATIONS"
    REUSE_DISTANCE_SURFACES = "REUSE_DISTANCE_SURFACES"
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
            f"PFF Plugin v{self.PFF_VERSION}\n\n"
            "Runs the complete PFF workflow in one step:\n\n"
            "1. Prepare datasets (reproject, rasterise, align)\n"
            "2. Compute distance surfaces\n"
            "3. Build anthropogenic mask (threshold adjustable)\n"
            "4. Three-tier primary forest logic\n"
            "5. Refine output (neighbourhood density filter)\n\n"
            "Auto UTM: when enabled, the plugin detects the appropriate "
            "UTM zone from the AOI or forest raster centroid.\n\n"
            "Output folder layout:\n"
            "  <out>/primary_forest.tif, pre_connectivity_forest.tif,\n"
            "        forest_natreg.tif (if plantations), anthropogenic_mask.tif,\n"
            "        combined_coded_raster.tif (if ticked),\n"
            "        zonal_statistics.csv/.shp, run_metadata.json\n"
            "  <out>/intermediates/tier1_undisturbed.tif, tier2_steep.tif,\n"
            "        tier3_protected.tif, forest_inside_buffers.tif,\n"
            "        steep_slope.tif, gentle_slope.tif\n"
            "  <out>/intermediates/prepared/ -- reprojected + aligned inputs\n"
            "  <out>/intermediates/distances/ -- distance surfaces\n\n"
            "Distance surfaces caching:\n"
            "  The distance computation stage is the slowest step. "
            "Output files (intermediates/distances/dist_*.tif) can be "
            "reused across runs — useful when you're only tuning "
            "thresholds and anthro inputs haven't changed. "
            "'Reuse cached distance surfaces' is OFF by default: "
            "re-runs recompute distances so stale cache can't silently "
            "produce wrong results if inputs changed.\n\n"
            "Fast re-run workflow (when tuning thresholds only):\n"
            "  1. Point the raster input slots (Roads raster, Built-up "
            "raster, Agriculture raster, Protected raster, etc.) at the "
            "files inside <previous_output>/intermediates/prepared/ — "
            "e.g. prepared/roads.tif, prepared/builtup_small.tif. "
            "These are the aligned rasters from the previous run, "
            "guaranteed to match the reference grid so the distance "
            "cache is safe to reuse.\n"
            "  2. Tick 'Reuse cached distance surfaces'.\n"
            "  3. Use the same output folder as the previous run so "
            "the existing intermediates/distances/ cache is found.\n"
            "  Result: reproject/rasterise stage skipped (raster inputs "
            "already aligned), distance stage skipped (cache reused), "
            "only tier logic + refine output run — much faster iteration "
            "on thresholds."
        )

    def createInstance(self):
        return FullWorkflowAlgorithm()

    # ------------------------------------------------------------------ #
    #  Parameters
    # ------------------------------------------------------------------ #

    def initAlgorithm(self, config=None):
        # -- Data inputs --
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.FOREST_RASTER, "Forest extent raster (binary 1/0)"))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.ROADS, "Roads (vector)", optional=True))
        # Built-up and agriculture vector inputs removed v0.8.33 — in practice
        # most users supply raster equivalents (typically from GEE exports).
        # The raster-only inputs below are the ones people actually use.
        # Raster alternatives (e.g. from GEE COG exports) -- override vectors
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.ROADS_RASTER, "Roads raster (binary) -- overrides vector",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.BUILTUP_SMALL_RASTER,
            "Built-up small raster (binary) -- overrides vector",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.BUILTUP_LARGE_RASTER,
            "Built-up large raster (binary) -- overrides vector",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.AGRICULTURE_RASTER,
            "Agriculture raster (binary) -- overrides vector",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DEM,
            "Natural protection — DEM (elevation, metres). Slope is "
            "computed from this. [GEE filename pattern: _natural_dem_]",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.SLOPE_RASTER,
            "OR Natural protection — Slope raster (degrees, 0–90). "
            "Overrides DEM if both supplied. [GEE filename pattern: "
            "_natural_slope_]",
            optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.PROTECTED_AREAS, "Protected areas (vector)", optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.PROTECTED_RASTER,
            "OR protected areas raster (binary) -- overrides vector",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.PLANTATIONS_RASTER,
            "Plantations raster (binary) -- optional, paired with 'Exclude plantations'",
            optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.AOI, "Area of Interest boundary (vector)", optional=True))

        # -- CRS / AOI --
        self.addParameter(QgsProcessingParameterBoolean(
            self.AUTO_UTM,
            "Auto-detect UTM zone from AOI / forest raster centroid",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterCrs(
            self.TARGET_CRS,
            "Target projected CRS (ignored when Auto UTM is ticked)",
            defaultValue="EPSG:32717"))
        # Optional EPSG-string fallback. Workshop users sometimes can't find
        # the right CRS via the picker (no Choose button on QGIS-LTR; obscure
        # zones); typing "EPSG:32628" here overrides the picker entirely.
        self.addParameter(QgsProcessingParameterString(
            self.TARGET_CRS_EPSG,
            "OR target CRS as EPSG string (e.g. 'EPSG:32628') -- overrides "
            "the picker above when non-empty. Ignored when Auto UTM is ticked.",
            defaultValue="",
            optional=True))
        # AOI buffer distance — rarely tuned; stowed under Advanced.
        _aoi_buf_param = QgsProcessingParameterNumber(
            self.AOI_BUFFER,
            "AOI buffer distance (m) — extends analysis area slightly past the country border so edge-of-country anthropogenic features still influence buffers near the boundary",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=AOI_BUFFER, minValue=0)
        _aoi_buf_param.setFlags(
            _aoi_buf_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_aoi_buf_param)

        # -- Distance thresholds --
        self.addParameter(QgsProcessingParameterBoolean(
            self.USE_SINGLE_DISTANCE,
            "Use single buffer distance for all anthropogenic layers",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterNumber(
            self.ALL_BUFFERS_DIST,
            "Single buffer distance (m) — overrides individual values when ticked",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=1000, minValue=0, maxValue=10000))

        # Per-buffer enable tickbox + distance field pairs — kept in the main
        # dialog (not Advanced) so the grouping is visible at a glance. Each
        # tickbox sits directly above its distance field, mirroring the GEE
        # panel layout.

        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_ROADS_BUFFER,
            "Roads buffer",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.ROADS_DIST,
            "    Roads buffer distance (m)  [ignored when single-distance is ticked]",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=ROADS_DIST, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_BUILTUP_SMALL_BUFFER,
            "Built-up (small) buffer",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.BUILTUP_DIST,
            "    Built-up (small) buffer distance (m)  [ignored when single-distance is ticked]",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=BUILTUP_DIST, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_BUILTUP_LARGE_BUFFER,
            "Built-up (large) buffer",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.BUILTUP_LARGE_DIST,
            "    Built-up (large) buffer distance (m)  [ignored when single-distance is ticked]",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=BUILTUP_LARGE_DIST, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_AGRICULTURE_BUFFER,
            "Agriculture buffer",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.AGRICULTURE_DIST,
            "    Agriculture buffer distance (m)  [ignored when single-distance is ticked]",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=AGRICULTURE_DIST, minValue=0, maxValue=10000))
        # Max distance — technical cap for speed. Rarely needs tuning;
        # stowed under Advanced Parameters to avoid cluttering the main dialog.
        _max_dist_param = QgsProcessingParameterNumber(
            self.MAX_DISTANCE,
            "Maximum distance to compute (m) — cap for speed; should be > largest buffer distance",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=MAX_DISTANCE, minValue=100)
        _max_dist_param.setFlags(
            _max_dist_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_max_dist_param)

        # -- Slope / connectivity --
        self.addParameter(QgsProcessingParameterNumber(
            self.SLOPE_THRESHOLD, "Slope threshold (degrees)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=SLOPE_THRESHOLD, minValue=0, maxValue=90))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_REFINE_OUTPUT,
            "Refine Output (neighbourhood density filter)",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.SMOOTH_RADIUS,
            "    Refine output: neighbourhood radius (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=SMOOTH_RADIUS, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterNumber(
            self.DENSITY_THRESHOLD,
            "    Refine output: minimum density to keep (0-1)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=DENSITY_THRESHOLD, minValue=0, maxValue=1))

        self.addParameter(QgsProcessingParameterBoolean(
            self.FAST_APPROXIMATION,
            "    Refine output: fast approximation (square kernel — faster, slight shape difference)",
            defaultValue=False))

        # -- Options --
        self.addParameter(QgsProcessingParameterBoolean(
            self.SAVE_COMBINED_RASTER,
            "Save combined coded raster (0=none, 1=forest, 2=pre-connectivity, 3=primary forest)",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean(
            self.EXCLUDE_PLANTATIONS,
            "Exclude plantations from forest (requires Plantations raster input)",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.REUSE_DISTANCE_SURFACES,
            "Reuse cached distance surfaces (faster re-runs; only safe when anthro inputs and grid are unchanged)",
            defaultValue=False))

        # -- Zonal statistics (optional) --
        self.addParameter(QgsProcessingParameterBoolean(
            self.RUN_ZONAL_STATS,
            "Run zonal statistics",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.ZONE_LAYER,
            "Zone layer for zonal statistics (polygons)",
            optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.ZONE_FIELD,
            "Zone name / ID field",
            parentLayerParameterName=self.ZONE_LAYER,
            optional=True))

        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_FOLDER, "Output folder"))

    # ------------------------------------------------------------------ #
    #  Workflow execution
    # ------------------------------------------------------------------ #

    PFF_VERSION = "0.8.43"

    def processAlgorithm(self, parameters, context, feedback):
        feedback.pushInfo(f"PFF plugin version: {self.PFF_VERSION}")
        out_dir = ensure_dir(
            self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))
        save_combined = self.parameterAsBool(
            parameters, self.SAVE_COMBINED_RASTER, context)
        reuse_distances = self.parameterAsBool(
            parameters, self.REUSE_DISTANCE_SURFACES, context)
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
            customised = [
                f"{name}={individual_thresholds[name]:g}"
                for name in individual_thresholds
                if individual_thresholds[name] != defaults_map[name]
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
                if enable_buffers.get(name, True):
                    feedback.pushInfo(f"    {name:<14} {dist:g} m")
                else:
                    feedback.pushInfo(f"    {name:<14} SKIPPED (Include-X-buffer is unticked)")
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
            # Validate the typed string before trusting it.
            candidate = QgsCoordinateReferenceSystem(target_crs_epsg_str)
            if not candidate.isValid():
                raise QgsProcessingException(
                    f"TARGET_CRS_EPSG '{target_crs_epsg_str}' is not a valid "
                    "CRS authority string. Expected format e.g. 'EPSG:32628'.")
            target_crs_str = candidate.authid() or target_crs_epsg_str
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
        # Headlines (primary_forest, pre_connectivity_forest, forest_natreg,
        # anthropogenic_mask, combined_coded_raster, zonal_statistics, run_metadata)
        # stay at out_dir top level.
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
        _likely_outputs = [
            os.path.join(out_dir, "primary_forest.tif"),
            os.path.join(out_dir, "pre_connectivity_forest.tif"),
            os.path.join(out_dir, "anthropogenic_mask.tif"),
            os.path.join(out_dir, "forest_natreg.tif"),
            os.path.join(out_dir, "run_metadata.json"),
        ]
        if save_combined:
            _likely_outputs.append(os.path.join(out_dir, "combined_coded_raster.tif"))
        if _run_zonal:
            _likely_outputs.append(os.path.join(out_dir, "zonal_statistics.csv"))
            _likely_outputs.append(os.path.join(out_dir, "zonal_statistics.shp"))

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
        feedback.pushInfo("=== STAGE 1: Prepare Datasets ===")

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
                _out = _drv.Create(prepared_forest_path, _xsz, _ysz, 1,
                                   gdal.GDT_Byte, ["COMPRESS=LZW"])
                _out.SetGeoTransform(_gt_ref)
                _out.SetProjection(_proj_ref)
                _out.GetRasterBand(1).WriteArray(_masked)
                _out.GetRasterBand(1).SetNoDataValue(0)
                _out.FlushCache()
                _out = None
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

        # Raster inputs override vectors when both are provided
        # Process sequentially with GC between to avoid GDAL memory buildup
        import gc
        roads_raster = _prep_raster(self.ROADS_RASTER, "roads")
        gc.collect()
        builtup_small_raster = _prep_raster(self.BUILTUP_SMALL_RASTER, "builtup_small")
        gc.collect()
        builtup_large_raster = _prep_raster(self.BUILTUP_LARGE_RASTER, "builtup_large")
        gc.collect()
        agri_raster = _prep_raster(self.AGRICULTURE_RASTER, "agriculture")
        gc.collect()

        rasters = {
            "roads": roads_raster if roads_raster else _prep_vector(self.ROADS, "roads"),
            "builtup": builtup_small_raster,
            "builtup_large": builtup_large_raster,
            "agriculture": agri_raster,
        }
        # Protected areas: raster overrides vector if both provided
        pa_raster_layer = self.parameterAsRasterLayer(
            parameters, self.PROTECTED_RASTER, context)
        if pa_raster_layer is not None:
            feedback.pushInfo("Aligning pre-rasterised protected areas...")
            pa_tif = _prep_raster(self.PROTECTED_RASTER, "protected")
        else:
            pa_tif = _prep_vector(self.PROTECTED_AREAS, "protected")

        # Plantations: optional binary raster used to derive naturally
        # regenerating forest (forest AND NOT plantations).
        # Mirrors pff_4.js:4184 behaviour when "Exclude plantations" is on.
        # Always prep the raster when supplied (consistency with other anthro
        # inputs) — the file sits in prepared/ ready for re-runs even if the
        # "Exclude plantations" tickbox is off on the current run.
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
                "(creating naturally regenerating forest layer)...")
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
                # Headline output (FRA naturally regenerating forest), lives at top level.
                forest_natreg_path = os.path.join(
                    out_dir, "forest_natreg.tif")
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
                _out = _drv.Create(forest_natreg_path, _fxsz, _fysz, 1,
                                   gdal.GDT_Byte,
                                   ["COMPRESS=LZW", "TILED=YES"])
                _out.SetGeoTransform(_fgt)
                _out.SetProjection(_fproj)
                _out.GetRasterBand(1).WriteArray(_natreg)
                _out.GetRasterBand(1).SetNoDataValue(0)
                _out.FlushCache()
                _out = None
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
        feedback.pushInfo("=== STAGE 2: Distance Surfaces ===")
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
                break
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
        feedback.pushInfo("=== STAGE 3: Anthropogenic Mask ===")

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
                break
            thresh = thresholds.get(name, 0)
            if thresh <= 0:
                continue
            feedback.pushInfo(f"Thresholding {name} at {thresh} m...")
            ds = gdal.Open(dp, gdal.GA_ReadOnly)
            arr = ds.GetRasterBand(1).ReadAsArray()
            ds = None
            combined_mask = np.maximum(
                combined_mask, (arr <= thresh).astype(np.uint8))

        anthro_path = os.path.join(out_dir, "anthropogenic_mask.tif")
        _write(anthro_path, combined_mask, gt, proj, x_size, y_size)
        feedback.setProgress(55)

        # ================================================================
        #  STAGE 4 -- Primary forest tiers
        # ================================================================
        feedback.pushInfo("=== STAGE 4: Primary Forest Logic ===")

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
        candidate_path = os.path.join(out_dir, "pre_connectivity_forest.tif")
        _write(candidate_path, primary_candidate, gt, proj, x_size, y_size)
        feedback.setProgress(80)

        # ================================================================
        #  STAGE 5 -- Refine output (neighbourhood density filter)
        # ================================================================
        # Aligned naming: primary_forest (matches pFF_4 GEE export name)
        final_path = os.path.join(out_dir, "primary_forest.tif")
        if enable_refine_output and smooth_radius > 0:
            feedback.pushInfo("=== STAGE 5: Refine Output ===")
            from .connectivity_filter import refine_output
            fast_approx = self.parameterAsBool(
                parameters, self.FAST_APPROXIMATION, context)
            refine_output(candidate_path, final_path,
                          radius_m=smooth_radius,
                          threshold=density_thresh,
                          fast_approximation=fast_approx,
                          feedback=feedback)
        else:
            if not enable_refine_output:
                feedback.pushInfo("Skipping Refine Output (unticked) — primary_forest.tif = pre_connectivity_forest.tif.")
            else:
                feedback.pushInfo("Skipping refine output (radius = 0).")
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

            combined_path = os.path.join(out_dir, "combined_coded_raster.tif")
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
            feedback.pushInfo("=== STAGE 6: Zonal Statistics ===")

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
                zonal_rasters["forest_natreg"] = forest_natreg_path
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
                zonal_csv = os.path.join(out_dir, "zonal_statistics.csv")
                write_zonal_csv(results, totals, zonal_csv, feedback)

            # Join to vector (if zones provided)
            if results and zone_path:
                zone_with_id = os.path.join(
                    zonal_work, "zones_with_id.shp")
                zonal_vec = os.path.join(out_dir, "zonal_statistics.shp")
                join_stats_to_vector(
                    results, zone_with_id, zonal_vec,
                    target_crs_str, context, feedback)

        # ================================================================
        #  Write run metadata
        # ================================================================
        import json
        from datetime import datetime
        metadata = {
            "pff_version": self.PFF_VERSION,
            "timestamp": datetime.now().isoformat(),
            "target_crs": target_crs_str,
            "parameters": {
                "aoi_buffer_m": aoi_buffer_dist,
                "use_single_buffer_distance": use_single,
                "single_buffer_distance_m": single_dist if use_single else None,
                "reuse_cached_distances": reuse_distances,
                "roads_dist_m": thresholds["roads"],
                "builtup_dist_m": thresholds["builtup"],
                "builtup_large_dist_m": thresholds["builtup_large"],
                "agriculture_dist_m": thresholds["agriculture"],
                "max_distance_m": max_dist,
                "slope_threshold_deg": slope_thresh,
                "smooth_radius_m": smooth_radius,
                "density_threshold": density_thresh,
                "auto_utm": auto_utm,
                "exclude_plantations": exclude_plantations,
                "plantations_applied": forest_natreg_path is not None,
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
                "forest_natreg": forest_natreg_path,
            },
            "raster_properties": {
                "x_size": x_size,
                "y_size": y_size,
                "resolution_m": abs(gt[1]),
            },
        }
        meta_path = os.path.join(out_dir, "run_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        feedback.pushInfo(f"Metadata: {meta_path}")

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

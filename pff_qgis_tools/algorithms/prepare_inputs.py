"""
PFF Tool 2 – Prepare Datasets
===============================
Reprojects, rasterises and aligns all input datasets to the forest
raster reference grid.  Compatible with QGIS ≥ 3.38 (uses only
native: and gdal: providers).
"""

import os

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterCrs,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
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
)


class PrepareInputsAlgorithm(QgsProcessingAlgorithm):
    # -- Parameter keys (match spec Tool 2) --
    FOREST_RASTER = "FOREST_RASTER"
    ROADS = "ROADS"
    BUILTUP = "BUILTUP"
    AGRICULTURE = "AGRICULTURE"
    ROADS_RASTER = "ROADS_RASTER"
    BUILTUP_SMALL_RASTER = "BUILTUP_SMALL_RASTER"
    BUILTUP_LARGE_RASTER = "BUILTUP_LARGE_RASTER"
    AGRICULTURE_RASTER = "AGRICULTURE_RASTER"
    DEM = "DEM"
    PROTECTED_AREAS = "PROTECTED_AREAS"
    PROTECTED_RASTER = "PROTECTED_RASTER"
    AOI = "AOI"
    TARGET_CRS = "TARGET_CRS"
    AOI_BUFFER = "AOI_BUFFER"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"

    def name(self):
        return "prepare_datasets"

    def displayName(self):
        return "2 — Prepare Datasets"

    def group(self):
        return "Primary Forest Finder"

    def groupId(self):
        return "pff"

    def shortHelpString(self):
        return (
            "Reprojects all layers to a common projected CRS, buffers AOI, "
            "clips datasets, rasterises vectors and aligns every raster to "
            "the forest raster reference grid.\n\n"
            "Accepts vector OR raster inputs for roads, built-up, agriculture "
            "and protected areas. Raster inputs (e.g. GEE COG exports) "
            "override vectors when both are provided.\n\n"
            "Outputs: forest.tif, roads.tif, builtup_small.tif, "
            "builtup_large.tif, agriculture.tif, protected.tif, dem.tif"
        )

    def createInstance(self):
        return PrepareInputsAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.FOREST_RASTER, "Forest extent raster (binary 1/0)"))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.ROADS, "Roads (vector)", optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.BUILTUP, "Built-up areas (vector)", optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.AGRICULTURE, "Agriculture / cropland (vector)", optional=True))
        # Raster alternatives (e.g. from GEE COG exports) — override vectors
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.ROADS_RASTER, "Roads raster (binary) — overrides vector",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.BUILTUP_SMALL_RASTER,
            "Built-up small raster (binary) — overrides vector",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.BUILTUP_LARGE_RASTER,
            "Built-up large raster (binary) — overrides vector",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.AGRICULTURE_RASTER,
            "Agriculture raster (binary) — overrides vector",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DEM, "Digital Elevation Model (DEM)", optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.PROTECTED_AREAS, "Protected areas (vector)", optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.PROTECTED_RASTER,
            "OR protected areas raster (binary) — overrides vector",
            optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.AOI, "Area of Interest boundary (vector)", optional=True))
        self.addParameter(QgsProcessingParameterCrs(
            self.TARGET_CRS, "Target projected CRS (must be in metres)",
            defaultValue="EPSG:32717"))
        self.addParameter(QgsProcessingParameterNumber(
            self.AOI_BUFFER, "AOI buffer distance (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=2000, minValue=0))
        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_FOLDER, "Output folder for prepared datasets"))

    # ------------------------------------------------------------------ #

    def processAlgorithm(self, parameters, context, feedback):
        forest_layer = self.parameterAsRasterLayer(
            parameters, self.FOREST_RASTER, context)
        target_crs = self.parameterAsCrs(parameters, self.TARGET_CRS, context)
        aoi_buffer_dist = self.parameterAsDouble(parameters, self.AOI_BUFFER, context)
        out_dir = ensure_dir(
            self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))

        prepared_dir = ensure_dir(os.path.join(out_dir, "prepared"))
        target_crs_str = target_crs.authid()

        # ── 1. Validate & reproject forest raster (= reference grid) ─────
        validate_crs_projected(forest_layer, feedback)
        forest_src = forest_layer.source()

        if forest_layer.crs() != target_crs:
            feedback.pushInfo("Reprojecting forest raster…")
            forest_out = os.path.join(prepared_dir, "forest.tif")
            reproject_raster(forest_src, target_crs_str, forest_out,
                             context=context, feedback=feedback)
            forest_src = forest_out
        else:
            forest_out = os.path.join(prepared_dir, "forest.tif")
            if os.path.normpath(forest_src) != os.path.normpath(forest_out):
                run_processing("gdal:translate", {
                    "INPUT": forest_src,
                    "OUTPUT": forest_out,
                }, context=context, feedback=feedback)
                forest_src = forest_out

        reference = forest_src
        feedback.pushInfo(f"Reference grid: {reference}")

        # ── 2. Buffer AOI and clip reference raster ──────────────────────
        aoi_layer = self.parameterAsVectorLayer(parameters, self.AOI, context)
        aoi_mask = None  # vector mask for clipping other layers
        if aoi_layer is not None:
            feedback.pushInfo("Buffering AOI…")
            aoi_reproj = os.path.join(prepared_dir, "aoi_reproj.gpkg")
            reproject_vector(aoi_layer.source(), target_crs_str, aoi_reproj,
                             context=context, feedback=feedback)

            aoi_buffered = os.path.join(prepared_dir, "aoi_buffered.gpkg")
            run_processing("native:buffer", {
                "INPUT": aoi_reproj,
                "DISTANCE": aoi_buffer_dist,
                "DISSOLVE": True,
                "OUTPUT": aoi_buffered,
            }, context=context, feedback=feedback)
            aoi_mask = aoi_buffered

            # Clip to AOI and overwrite forest.tif in place (single consistent name).
            # Use a temp filename for the clip op, then replace forest.tif atomically.
            _tmp_clipped = os.path.join(prepared_dir, "_forest_clip_tmp.tif")
            clip_raster_by_mask(reference, aoi_mask, _tmp_clipped,
                                context=context, feedback=feedback)
            try:
                os.replace(_tmp_clipped, reference)
            except OSError:
                # On Windows os.replace may fail if reference is locked; fall back
                reference = _tmp_clipped

        # ── 3. Reproject, clip & rasterise each vector input ─────────────
        def _process_vector(param_key, filename):
            layer = self.parameterAsVectorLayer(parameters, param_key, context)
            if layer is None:
                return None
            feedback.pushInfo(f"Processing {filename}…")
            reproj = os.path.join(prepared_dir, f"{filename}_reproj.gpkg")
            reproject_vector(layer.source(), target_crs_str, reproj,
                             context=context, feedback=feedback)
            # Clip to AOI if available
            if aoi_mask is not None:
                clipped = os.path.join(prepared_dir, f"{filename}_clip.gpkg")
                run_processing("native:clip", {
                    "INPUT": reproj,
                    "OVERLAY": aoi_mask,
                    "OUTPUT": clipped,
                }, context=context, feedback=feedback)
                reproj = clipped

            rasterised = os.path.join(prepared_dir, f"{filename}.tif")
            rasterize_vector(reproj, reference, rasterised,
                             context=context, feedback=feedback)
            return rasterised

        roads_tif = _process_vector(self.ROADS, "roads")
        builtup_tif = _process_vector(self.BUILTUP, "builtup")
        agri_tif = _process_vector(self.AGRICULTURE, "agriculture")
        pa_tif = _process_vector(self.PROTECTED_AREAS, "protected")

        # Raster inputs override vectors when both are provided
        def _process_raster_input(param_key, filename, fallback_tif):
            layer = self.parameterAsRasterLayer(parameters, param_key, context)
            if layer is None:
                return fallback_tif
            feedback.pushInfo(f"Aligning raster input {filename}…")
            reproj = os.path.join(prepared_dir, f"{filename}_reproj.tif")
            reproject_raster(layer.source(), target_crs_str, reproj,
                             context=context, feedback=feedback)
            if aoi_mask is not None:
                clipped_r = os.path.join(prepared_dir, f"{filename}_clipped.tif")
                clip_raster_by_mask(reproj, aoi_mask, clipped_r,
                                    context=context, feedback=feedback)
                reproj = clipped_r
            aligned = os.path.join(prepared_dir, f"{filename}.tif")
            _, gt, xsz, ysz = get_raster_info(reference)
            extent_str = (
                f"{gt[0]},{gt[0] + gt[1] * xsz},"
                f"{gt[3] + gt[5] * ysz},{gt[3]}"
            )
            run_processing("gdal:warpreproject", {
                "INPUT": reproj,
                "TARGET_CRS": target_crs,
                "TARGET_EXTENT": extent_str,
                "TARGET_EXTENT_CRS": target_crs,
                "RESAMPLING": 0,
                "OUTPUT": aligned,
            }, context=context, feedback=feedback)
            return aligned

        roads_tif = _process_raster_input(
            self.ROADS_RASTER, "roads", roads_tif)
        builtup_tif = _process_raster_input(
            self.BUILTUP_SMALL_RASTER, "builtup_small", builtup_tif)
        builtup_large_tif = _process_raster_input(
            self.BUILTUP_LARGE_RASTER, "builtup_large", None)
        agri_tif = _process_raster_input(
            self.AGRICULTURE_RASTER, "agriculture_r", agri_tif)
        pa_tif = _process_raster_input(
            self.PROTECTED_RASTER, "protected_r", pa_tif)

        # ── 4. DEM → align (slope is computed later in Tool 4) ───────────
        dem_layer = self.parameterAsRasterLayer(parameters, self.DEM, context)
        dem_out = None
        if dem_layer is not None:
            feedback.pushInfo("Aligning DEM…")
            dem_reproj = os.path.join(prepared_dir, "dem_reproj.tif")
            reproject_raster(dem_layer.source(), target_crs_str, dem_reproj,
                             context=context, feedback=feedback)
            if aoi_mask is not None:
                dem_clipped = os.path.join(prepared_dir, "dem_clipped.tif")
                clip_raster_by_mask(dem_reproj, aoi_mask, dem_clipped,
                                    context=context, feedback=feedback)
                dem_reproj = dem_clipped
            dem_out = os.path.join(prepared_dir, "dem.tif")
            # Align to the reference grid
            _, gt, xsz, ysz = get_raster_info(reference)
            extent_str = (
                f"{gt[0]},{gt[0] + gt[1] * xsz},"
                f"{gt[3] + gt[5] * ysz},{gt[3]}"
            )
            run_processing("gdal:warpreproject", {
                "INPUT": dem_reproj,
                "TARGET_CRS": target_crs,
                "TARGET_EXTENT": extent_str,
                "TARGET_EXTENT_CRS": target_crs,
                "RESAMPLING": 0,
                "OUTPUT": dem_out,
            }, context=context, feedback=feedback)

        # ── 5. Align remaining rasters to reference grid ─────────────────
        rasters_to_align = [r for r in [
            roads_tif, builtup_tif, builtup_large_tif,
            agri_tif, pa_tif,
        ] if r is not None]

        if rasters_to_align:
            feedback.pushInfo("Aligning rasters to reference grid…")
            _, gt, xsz, ysz = get_raster_info(reference)
            extent_str = (
                f"{gt[0]},{gt[0] + gt[1] * xsz},"
                f"{gt[3] + gt[5] * ysz},{gt[3]}"
            )
            for raster_path in rasters_to_align:
                aligned = raster_path.replace(".tif", "_aligned.tif")
                run_processing("gdal:warpreproject", {
                    "INPUT": raster_path,
                    "TARGET_CRS": target_crs,
                    "TARGET_EXTENT": extent_str,
                    "TARGET_EXTENT_CRS": target_crs,
                    "RESAMPLING": 0,
                    "OUTPUT": aligned,
                }, context=context, feedback=feedback)
                os.replace(aligned, raster_path)

        feedback.pushInfo("✓ Dataset preparation complete.")
        return {self.OUTPUT_FOLDER: out_dir}

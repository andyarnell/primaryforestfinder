"""
PFF Tool 3a – Distance Surfaces (cache step)
==============================================
Computes proximity (distance) rasters for each anthropogenic layer.
These are cached so that threshold changes (Tool 3b) do not require
re‑computation.  Compatible with QGIS ≥ 3.38.
"""

import os

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFolderDestination,
)

from ..utils import ensure_dir, proximity, validate_crs_projected


class DistanceSurfacesAlgorithm(QgsProcessingAlgorithm):
    ROADS = "ROADS"
    BUILTUP = "BUILTUP"
    BUILTUP_LARGE = "BUILTUP_LARGE"
    AGRICULTURE = "AGRICULTURE"
    MAX_DISTANCE = "MAX_DISTANCE"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"

    def name(self):
        return "distance_surfaces"

    def displayName(self):
        return "3a — Distance Surfaces (cache)"

    def group(self):
        return "Primary Forest Finder"

    def groupId(self):
        return "pff"

    def shortHelpString(self):
        return (
            "Computes proximity (distance-to-nearest-pixel) rasters for each "
            "anthropogenic layer.\n\n"
            "These are computationally expensive — run once, then reuse "
            "with different thresholds in '3b — Build Anthropogenic Mask'.\n\n"
            "Outputs: dist_roads.tif, dist_builtup.tif, "
            "dist_builtup_large.tif, dist_agriculture.tif"
        )

    def createInstance(self):
        return DistanceSurfacesAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.ROADS, "Roads raster (binary)", optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.BUILTUP, "Built-up (small) raster (binary)", optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.BUILTUP_LARGE, "Built-up (large) raster (binary)",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.AGRICULTURE, "Agriculture raster (binary)", optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_DISTANCE,
            "Maximum distance to compute (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=5100, minValue=100))
        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_FOLDER, "Output folder for distance surfaces"))

    def processAlgorithm(self, parameters, context, feedback):
        max_dist = self.parameterAsDouble(parameters, self.MAX_DISTANCE, context)
        out_dir = ensure_dir(
            self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))
        dist_dir = ensure_dir(os.path.join(out_dir, "distances"))

        layers = {
            "roads": self.parameterAsRasterLayer(
                parameters, self.ROADS, context),
            "builtup": self.parameterAsRasterLayer(
                parameters, self.BUILTUP, context),
            "builtup_large": self.parameterAsRasterLayer(
                parameters, self.BUILTUP_LARGE, context),
            "agriculture": self.parameterAsRasterLayer(
                parameters, self.AGRICULTURE, context),
        }

        outputs = {}
        total = max(sum(1 for v in layers.values() if v is not None), 1)
        step = 0

        for name, layer in layers.items():
            if feedback.isCanceled():
                break
            if layer is None:
                continue

            validate_crs_projected(layer, feedback)
            out_path = os.path.join(dist_dir, f"dist_{name}.tif")

            # Skip if already computed (caching)
            if os.path.exists(out_path):
                feedback.pushInfo(f"Using cached: {out_path}")
                outputs[f"dist_{name}"] = out_path
            else:
                feedback.pushInfo(f"Computing distance surface for {name}...")
                proximity(layer.source(), out_path, max_distance=max_dist,
                          context=context, feedback=feedback)
                outputs[f"dist_{name}"] = out_path

            step += 1
            feedback.setProgress(int(step / total * 100))

        feedback.pushInfo("Distance surfaces complete.")
        return {self.OUTPUT_FOLDER: out_dir, **outputs}

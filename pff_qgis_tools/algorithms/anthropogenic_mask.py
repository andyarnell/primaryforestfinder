"""
PFF Tool 3b – Build Anthropogenic Mask
========================================
Applies distance thresholds to cached distance surfaces and combines
them into a single anthropogenic influence mask.
Re-run this with different threshold values without recomputing distances.
Compatible with QGIS >= 3.38.
"""

import os
import numpy as np
from osgeo import gdal

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
)

from ..utils import ensure_dir


class AnthropogenicMaskAlgorithm(QgsProcessingAlgorithm):
    DIST_ROADS = "DIST_ROADS"
    DIST_BUILTUP = "DIST_BUILTUP"
    DIST_BUILTUP_LARGE = "DIST_BUILTUP_LARGE"
    DIST_AGRICULTURE = "DIST_AGRICULTURE"
    ROADS_THRESHOLD = "ROADS_THRESHOLD"
    BUILTUP_THRESHOLD = "BUILTUP_THRESHOLD"
    BUILTUP_LARGE_THRESHOLD = "BUILTUP_LARGE_THRESHOLD"
    AGRICULTURE_THRESHOLD = "AGRICULTURE_THRESHOLD"
    OUTPUT = "OUTPUT"

    def name(self):
        return "anthropogenic_mask"

    def displayName(self):
        return "3b — Build Anthropogenic Mask"

    def group(self):
        return "Primary Forest Finder"

    def groupId(self):
        return "pff"

    def shortHelpString(self):
        return (
            "Applies distance thresholds to the cached distance surfaces "
            "and combines them into a single anthropogenic mask.\n\n"
            "You can re-run this tool with different threshold values "
            "without recomputing the expensive distance surfaces.\n\n"
            "Default thresholds:\n"
            "  Roads              = 1000 m\n"
            "  Built-up (small)   = 1000 m\n"
            "  Built-up (large)   = 2000 m\n"
            "  Agriculture        = 1000 m\n\n"
            "Output: anthropogenic_mask.tif (1=influenced, 0=not)"
        )

    def createInstance(self):
        return AnthropogenicMaskAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DIST_ROADS,
            "Distance surface — roads", optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DIST_BUILTUP,
            "Distance surface — built-up (small)", optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DIST_BUILTUP_LARGE,
            "Distance surface — built-up (large)", optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DIST_AGRICULTURE,
            "Distance surface — agriculture", optional=True))

        self.addParameter(QgsProcessingParameterNumber(
            self.ROADS_THRESHOLD, "Roads buffer distance (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=1000, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterNumber(
            self.BUILTUP_THRESHOLD, "Built-up (small) buffer distance (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=1000, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterNumber(
            self.BUILTUP_LARGE_THRESHOLD,
            "Built-up (large) buffer distance (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=2000, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterNumber(
            self.AGRICULTURE_THRESHOLD, "Agriculture buffer distance (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=1000, minValue=0, maxValue=10000))

        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT, "Anthropogenic mask output"))

    def processAlgorithm(self, parameters, context, feedback):
        # Gather distance layers and thresholds
        pairs = [
            (self.DIST_ROADS, self.ROADS_THRESHOLD, "roads"),
            (self.DIST_BUILTUP, self.BUILTUP_THRESHOLD, "built-up (small)"),
            (self.DIST_BUILTUP_LARGE, self.BUILTUP_LARGE_THRESHOLD,
             "built-up (large)"),
            (self.DIST_AGRICULTURE, self.AGRICULTURE_THRESHOLD, "agriculture"),
        ]

        # Read reference raster properties from the first available layer
        ref_ds = None
        active_pairs = []
        for dist_key, thresh_key, label in pairs:
            layer = self.parameterAsRasterLayer(parameters, dist_key, context)
            if layer is None:
                continue
            threshold = self.parameterAsDouble(parameters, thresh_key, context)
            active_pairs.append((layer.source(), threshold, label))
            if ref_ds is None:
                ref_ds = gdal.Open(layer.source(), gdal.GA_ReadOnly)

        if not active_pairs or ref_ds is None:
            feedback.reportError("No distance surfaces provided.")
            return {}

        x_size = ref_ds.RasterXSize
        y_size = ref_ds.RasterYSize
        gt = ref_ds.GetGeoTransform()
        proj = ref_ds.GetProjection()
        ref_ds = None

        # Build combined mask using numpy (fast, no temp files)
        combined = np.zeros((y_size, x_size), dtype=np.uint8)

        for i, (path, threshold, label) in enumerate(active_pairs):
            if feedback.isCanceled():
                break
            feedback.pushInfo(
                f"Thresholding {label} at {threshold} m...")
            ds = gdal.Open(path, gdal.GA_ReadOnly)
            arr = ds.GetRasterBand(1).ReadAsArray()
            ds = None
            buffer_mask = (arr <= threshold).astype(np.uint8)
            combined = np.maximum(combined, buffer_mask)
            feedback.setProgress(int((i + 1) / len(active_pairs) * 100))

        # Write output
        out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)
        driver = gdal.GetDriverByName("GTiff")
        out_ds = driver.Create(out_path, x_size, y_size, 1, gdal.GDT_Byte,
                               options=["COMPRESS=LZW", "TILED=YES"])
        out_ds.SetGeoTransform(gt)
        out_ds.SetProjection(proj)
        band = out_ds.GetRasterBand(1)
        band.WriteArray(combined)
        band.SetNoDataValue(0)
        band.FlushCache()
        out_ds = None

        feedback.pushInfo("Anthropogenic mask complete.")
        return {self.OUTPUT: out_path}

"""
PFF Tool 4 – Run Primary Forest Finder
========================================
Implements the three‑tier primary forest logic:
  Tier 1 — Forest outside anthropogenic influence
  Tier 2 — Forest in anthropogenic zone on steep slopes (≥ threshold)
  Tier 3 — Forest in anthropogenic zone on gentle slopes inside PAs

Combines tiers → pre_connectivity_forest.tif (feed into Refine Output for primary_forest.tif)
Compatible with QGIS ≥ 3.38.
"""

import os
import numpy as np
from osgeo import gdal

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFolderDestination,
)

from ..utils import ensure_dir, run_processing


class PrimaryForestAlgorithm(QgsProcessingAlgorithm):
    FOREST_RASTER = "FOREST_RASTER"
    ANTHROPOGENIC_MASK = "ANTHROPOGENIC_MASK"
    DEM = "DEM"
    SLOPE_RASTER = "SLOPE_RASTER"
    PROTECTED_RASTER = "PROTECTED_RASTER"
    SLOPE_THRESHOLD = "SLOPE_THRESHOLD"
    SAVE_INTERMEDIATES = "SAVE_INTERMEDIATES"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    OUTPUT = "OUTPUT"

    def name(self):
        return "primary_forest"

    def displayName(self):
        return "4 — Run Primary Forest Finder"

    def group(self):
        return "Primary Forest Finder"

    def groupId(self):
        return "pff"

    def shortHelpString(self):
        return (
            "Generates the primary forest candidate map using the three‑tier "
            "decision tree:\n\n"
            "Tier 1: Forest outside anthropogenic influence\n"
            "Tier 2: Forest inside anthropogenic zone AND on steep slopes\n"
            "Tier 3: Forest inside anthropogenic zone AND on gentle slopes "
            "AND inside protected areas\n\n"
            "Combines all tiers → pre_connectivity_forest.tif\n\n"
            "Optionally saves intermediate layers for debugging."
        )

    def createInstance(self):
        return PrimaryForestAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.FOREST_RASTER, "Forest raster (binary 1/0)"))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.ANTHROPOGENIC_MASK,
            "Anthropogenic mask (from Tool 3b)"))
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
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.PROTECTED_RASTER,
            "Protected areas raster (binary)", optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.SLOPE_THRESHOLD, "Slope threshold (degrees)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=45, minValue=0, maxValue=90))
        self.addParameter(QgsProcessingParameterBoolean(
            self.SAVE_INTERMEDIATES,
            "Save intermediate layers for debugging",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_FOLDER, "Output folder"))

    def processAlgorithm(self, parameters, context, feedback):
        out_dir = ensure_dir(
            self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))
        save_int = self.parameterAsBool(
            parameters, self.SAVE_INTERMEDIATES, context)
        slope_thresh = self.parameterAsDouble(
            parameters, self.SLOPE_THRESHOLD, context)

        # ── Read inputs as numpy arrays ──────────────────────────────────
        forest_layer = self.parameterAsRasterLayer(
            parameters, self.FOREST_RASTER, context)
        anthro_layer = self.parameterAsRasterLayer(
            parameters, self.ANTHROPOGENIC_MASK, context)

        forest_ds = gdal.Open(forest_layer.source(), gdal.GA_ReadOnly)
        forest = forest_ds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
        gt = forest_ds.GetGeoTransform()
        proj = forest_ds.GetProjection()
        x_size = forest_ds.RasterXSize
        y_size = forest_ds.RasterYSize
        forest_ds = None

        anthro_ds = gdal.Open(anthro_layer.source(), gdal.GA_ReadOnly)
        anthro = anthro_ds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
        anthro_ds = None

        # ── Tier 1: forest outside anthropogenic influence ───────────────
        feedback.pushInfo("Computing Tier 1 — undisturbed forest…")
        tier1_undisturbed = ((forest == 1) & (anthro == 0)).astype(np.uint8)
        forest_inside_buffers = ((forest == 1) & (anthro == 1)).astype(np.uint8)

        if save_int:
            self._write_raster(
                os.path.join(out_dir, "tier1_undisturbed.tif"),
                tier1_undisturbed, gt, proj, x_size, y_size)
            self._write_raster(
                os.path.join(out_dir, "forest_inside_buffers.tif"),
                forest_inside_buffers, gt, proj, x_size, y_size)
        feedback.setProgress(25)

        # ── Slope (Tier 2 & 3) ──────────────────────────────────────────
        slope_layer = self.parameterAsRasterLayer(
            parameters, self.SLOPE_RASTER, context)
        dem_layer = self.parameterAsRasterLayer(
            parameters, self.DEM, context)
        steep = None
        gentle = None

        slope_arr = None
        if slope_layer is not None:
            # Use pre-computed slope directly
            feedback.pushInfo("Using pre-computed slope raster…")
            slope_ds = gdal.Open(slope_layer.source(), gdal.GA_ReadOnly)
            slope_arr = slope_ds.GetRasterBand(1).ReadAsArray()
            slope_ds = None
        elif dem_layer is not None:
            # Compute slope from DEM
            feedback.pushInfo("Computing slope from DEM…")
            slope_path = os.path.join(out_dir, "slope.tif")
            run_processing("gdal:slope", {
                "INPUT": dem_layer.source(),
                "BAND": 1,
                "SCALE": 1,
                "AS_PERCENT": False,
                "OUTPUT": slope_path,
            }, context=context, feedback=feedback)
            slope_ds = gdal.Open(slope_path, gdal.GA_ReadOnly)
            slope_arr = slope_ds.GetRasterBand(1).ReadAsArray()
            slope_ds = None

        if slope_arr is not None:
            steep = (slope_arr >= slope_thresh).astype(np.uint8)
            gentle = (slope_arr < slope_thresh).astype(np.uint8)

            if save_int:
                self._write_raster(
                    os.path.join(out_dir, "steep_slope.tif"),
                    steep, gt, proj, x_size, y_size)
                self._write_raster(
                    os.path.join(out_dir, "gentle_slope.tif"),
                    gentle, gt, proj, x_size, y_size)
        feedback.setProgress(50)

        # ── Tier 2: anthropogenic forest on steep slopes ─────────────────
        tier2_steep = np.zeros_like(forest)
        if steep is not None:
            feedback.pushInfo("Computing Tier 2 — steep slope forest…")
            tier2_steep = (
                (forest_inside_buffers == 1) & (steep == 1)
            ).astype(np.uint8)
            if save_int:
                self._write_raster(
                    os.path.join(out_dir, "tier2_steep.tif"),
                    tier2_steep, gt, proj, x_size, y_size)
        feedback.setProgress(65)

        # ── Tier 3: anthropogenic forest on gentle slopes in PAs ─────────
        tier3_protected = np.zeros_like(forest)
        pa_layer = self.parameterAsRasterLayer(
            parameters, self.PROTECTED_RASTER, context)

        if pa_layer is not None and gentle is not None:
            feedback.pushInfo("Computing Tier 3 — protected gentle‑slope forest…")
            pa_ds = gdal.Open(pa_layer.source(), gdal.GA_ReadOnly)
            pa = pa_ds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
            pa_ds = None

            tier3_protected = (
                (forest_inside_buffers == 1) & (gentle == 1) & (pa == 1)
            ).astype(np.uint8)
            if save_int:
                self._write_raster(
                    os.path.join(out_dir, "tier3_protected.tif"),
                    tier3_protected, gt, proj, x_size, y_size)
        feedback.setProgress(80)

        # ── Combine tiers ────────────────────────────────────────────────
        feedback.pushInfo("Combining tiers → pre_connectivity_forest…")
        pre_connectivity_forest = np.maximum(
            np.maximum(tier1_undisturbed, tier2_steep),
            tier3_protected,
        )

        # Output is the combined tier1+tier2+tier3 mask — before Refine Output
        # (the connectivity filter). Naming matches GEE pff_4's tier4_pre_connectivity_forest
        # and full_workflow's pre_connectivity_forest.tif.
        out_path = os.path.join(out_dir, "pre_connectivity_forest.tif")
        self._write_raster(out_path, pre_connectivity_forest,
                           gt, proj, x_size, y_size)
        feedback.setProgress(100)
        feedback.pushInfo("✓ Primary forest candidate layer complete.")
        return {self.OUTPUT: out_path, self.OUTPUT_FOLDER: out_dir}

    @staticmethod
    def _write_raster(path, array, gt, proj, x_size, y_size):
        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(path, x_size, y_size, 1, gdal.GDT_Byte,
                           options=["COMPRESS=LZW", "TILED=YES"])
        ds.SetGeoTransform(gt)
        ds.SetProjection(proj)
        band = ds.GetRasterBand(1)
        band.WriteArray(array)
        band.SetNoDataValue(0)
        band.FlushCache()
        ds = None

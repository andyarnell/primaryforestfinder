"""
PFF Tool 7 -- Vectorize for CEO Validation
============================================
Post-processing tool: takes a binary or coded PFF raster and produces
up to three vector outputs in one run, sized for Collect Earth Online
(CEO) validation sampling.

Outputs:
  1. Raw vector polygonisation of the selected pixel value(s).
  2. Optional area-filtered vector (polygons below a min-area threshold
     dropped) -- trims small isolated patches.
  3. Dissolved multipart vector -- single feature suitable as a CEO
     sampling-area boundary.

Pixel value selector: comma-separated list, default '1'. Use '1,2,3'
to vectorize multiple classes from the combined coded raster (e.g.
for a broader sampling area than primary forest alone).

Background (0 / nodata) is masked before polygonisation so the tool
doesn't waste cycles on the country-wide background pixels.

No GRASS dependency -- uses gdal:polygonize which ships with QGIS core.

Compatible with QGIS >= 3.38.
"""

import os
import tempfile

import numpy as np
from osgeo import gdal

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFileDestination,
)

from ..utils import ensure_dir, run_processing


class VectorizeForCeoAlgorithm(QgsProcessingAlgorithm):
    """Polygonise + optional area filter + dissolve to multipart."""

    INPUT_RASTER = "INPUT_RASTER"
    PIXEL_VALUES = "PIXEL_VALUES"
    MIN_PATCH_AREA_HA = "MIN_PATCH_AREA_HA"
    OUTPUT_RAW = "OUTPUT_RAW"
    OUTPUT_FILTERED = "OUTPUT_FILTERED"
    OUTPUT_DISSOLVED = "OUTPUT_DISSOLVED"

    def name(self):
        return "vectorize_for_ceo"

    def displayName(self):
        return "7 -- Vectorize for CEO validation"

    def group(self):
        return "Primary Forest Finder"

    def groupId(self):
        return "pff"

    def shortHelpString(self):
        return (
            "Polygonise a binary or coded PFF raster and produce up to "
            "three vector outputs in one run, sized for Collect Earth "
            "Online (CEO) validation sampling.\n\n"
            "Inputs:\n"
            "  - Source raster (binary or coded).\n"
            "  - Pixel value(s) to vectorise (comma-separated, default "
            "'1'). Use e.g. '1,2,3' to vectorise multiple classes from "
            "the combined coded raster.\n"
            "  - Optional minimum patch area (hectares). Polygons below "
            "this are dropped from the area-filtered output. Leave at 0 "
            "(or blank) to skip filtering.\n\n"
            "Outputs:\n"
            "  1. Raw vector -- direct polygonisation of selected pixel "
            "values.\n"
            "  2. Area-filtered vector -- only used when min patch area "
            "is set above 0.\n"
            "  3. Dissolved multipart -- single feature, suitable as a "
            "CEO sampling-area boundary. Built from the area-filtered "
            "vector when filtering is on, otherwise from the raw vector.\n\n"
            "Background (0 / nodata) is masked before polygonisation -- "
            "the tool doesn't waste cycles on country-wide background "
            "pixels.\n\n"
            "Typical use cases (rerun with different class selections):\n"
            "  - default '1' on primary_forest.tif -> strict primary-"
            "forest sampling area.\n"
            "  - '1,2,3' on combined_coded_raster.tif -> broader forest "
            "sampling area for less-restrictive validation."
        )

    def createInstance(self):
        return VectorizeForCeoAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT_RASTER,
            "Source raster (binary or coded)"))

        self.addParameter(QgsProcessingParameterString(
            self.PIXEL_VALUES,
            "Pixel value(s) to vectorise (comma-separated, e.g. '1' or "
            "'1,2,3' for multi-class from combined raster)",
            defaultValue="1"))

        # Min patch area in hectares: 0 (or blank) = no filtering.
        # Hectares chosen as more human-readable than m^2 for the typical
        # workshop scale ("10 ha minimum patch" reads better than
        # "100,000 m^2 minimum patch").
        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_PATCH_AREA_HA,
            "Minimum patch area, hectares (0 = no filtering)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.0,
            minValue=0.0))

        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_RAW,
            "Output: raw vector",
            fileFilter="GeoPackage (*.gpkg);;Shapefile (*.shp)"))

        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_FILTERED,
            "Output: area-filtered vector (only written when min area > 0)",
            fileFilter="GeoPackage (*.gpkg);;Shapefile (*.shp)",
            optional=True))

        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_DISSOLVED,
            "Output: dissolved multipart (CEO sampling boundary)",
            fileFilter="GeoPackage (*.gpkg);;Shapefile (*.shp)"))

    def processAlgorithm(self, parameters, context, feedback):
        # ── Read parameters ──
        input_layer = self.parameterAsRasterLayer(
            parameters, self.INPUT_RASTER, context)
        if input_layer is None:
            raise QgsProcessingException("No source raster provided.")

        pixel_values_str = self.parameterAsString(
            parameters, self.PIXEL_VALUES, context) or "1"
        min_area_ha = self.parameterAsDouble(
            parameters, self.MIN_PATCH_AREA_HA, context)
        out_raw = self.parameterAsString(parameters, self.OUTPUT_RAW, context)
        out_filtered = self.parameterAsString(
            parameters, self.OUTPUT_FILTERED, context)
        out_dissolved = self.parameterAsString(
            parameters, self.OUTPUT_DISSOLVED, context)

        # Parse comma-separated pixel values to a sorted set of ints.
        try:
            pixel_values = sorted({
                int(s.strip()) for s in pixel_values_str.split(",")
                if s.strip()
            })
        except ValueError:
            raise QgsProcessingException(
                f"Pixel value(s) parse error: '{pixel_values_str}'. "
                "Expected comma-separated integers, e.g. '1' or '1,2,3'.")
        if not pixel_values:
            raise QgsProcessingException(
                "No pixel values to vectorise. Enter at least one integer "
                "(default '1').")

        feedback.pushInfo(f"Pixel values to vectorise: {pixel_values}")

        # ── Build masked raster ──
        # mask = 1 where input pixel is in pixel_values, else 0.
        # nodata=0 set on output band -> gdal:polygonize skips background
        # automatically (no country-wide sweep on the 0-pixels).
        src_path = input_layer.source()
        ds = gdal.Open(src_path, gdal.GA_ReadOnly)
        if ds is None:
            raise QgsProcessingException(f"Cannot open raster: {src_path}")
        band = ds.GetRasterBand(1)
        arr = band.ReadAsArray()
        gt = ds.GetGeoTransform()
        proj = ds.GetProjection()
        x_size = ds.RasterXSize
        y_size = ds.RasterYSize
        ds = None

        pixel_area_m2 = abs(gt[1] * gt[5])
        feedback.pushInfo(
            f"Pixel area: {pixel_area_m2:g} m^2 "
            f"({pixel_area_m2 / 10000:g} ha)")

        if feedback.isCanceled():
            raise QgsProcessingException("Cancelled by user.")

        mask = np.isin(arr, pixel_values).astype(np.uint8)
        n_kept_px = int(mask.sum())
        if n_kept_px == 0:
            feedback.pushWarning(
                f"No pixels match the selected values {pixel_values}. "
                "Outputs will be empty.")
        else:
            feedback.pushInfo(
                f"{n_kept_px:,} pixels match "
                f"(~{n_kept_px * pixel_area_m2 / 10000:,.0f} ha total)")

        # Scratch dir via tempfile -- works even when output path is
        # in-memory ('memory:...') or otherwise lacks a parent dir.
        scratch_dir = ensure_dir(tempfile.mkdtemp(prefix="pff_vectorize_"))
        masked_tif = os.path.join(scratch_dir, "input_masked.tif")
        drv = gdal.GetDriverByName("GTiff")
        out_ds = drv.Create(masked_tif, x_size, y_size, 1, gdal.GDT_Byte,
                            ["COMPRESS=LZW", "TILED=YES"])
        out_ds.SetGeoTransform(gt)
        out_ds.SetProjection(proj)
        out_band = out_ds.GetRasterBand(1)
        out_band.WriteArray(mask)
        out_band.SetNoDataValue(0)
        out_band.FlushCache()
        out_ds = None
        del arr, mask  # release before polygonize re-reads the file

        if feedback.isCanceled():
            raise QgsProcessingException("Cancelled by user.")

        # ── 1. Polygonize ──
        # gdal:polygonize honours the nodata value -> skips 0 pixels, so
        # only the masked-in cells become polygons.
        feedback.pushInfo("Polygonising (gdal:polygonize, 4-connected)...")
        run_processing("gdal:polygonize", {
            "INPUT": masked_tif,
            "BAND": 1,
            "FIELD": "value",
            "EIGHT_CONNECTEDNESS": False,
            "EXTRA": "",
            "OUTPUT": out_raw,
        }, context=context, feedback=feedback)
        feedback.pushInfo(f"Raw vector: {out_raw}")
        outputs = {self.OUTPUT_RAW: out_raw}

        if feedback.isCanceled():
            raise QgsProcessingException("Cancelled by user.")

        # ── 2. Area filter (optional) ──
        # Source for the dissolve step: filtered if filtering on, else raw.
        dissolve_source = out_raw
        if min_area_ha > 0:
            if not out_filtered:
                feedback.pushWarning(
                    "Min patch area set but no area-filtered output path -- "
                    "skipping area filter. Dissolve will use the raw vector.")
            else:
                min_area_m2 = min_area_ha * 10000.0
                feedback.pushInfo(
                    f"Filtering polygons by area >= {min_area_ha:g} ha "
                    f"({min_area_m2:g} m^2)...")
                # $area is in the layer CRS units. PFF rasters are
                # validated upstream as projected metres-CRS, so $area
                # comes out in m^2 directly.
                run_processing("native:extractbyexpression", {
                    "INPUT": out_raw,
                    "EXPRESSION": f"$area >= {min_area_m2}",
                    "OUTPUT": out_filtered,
                }, context=context, feedback=feedback)
                feedback.pushInfo(f"Area-filtered vector: {out_filtered}")
                outputs[self.OUTPUT_FILTERED] = out_filtered
                dissolve_source = out_filtered
        else:
            if out_filtered:
                feedback.pushInfo(
                    "Min patch area is 0 -- area-filtered output skipped.")

        if feedback.isCanceled():
            raise QgsProcessingException("Cancelled by user.")

        # ── 3. Dissolve to multipart ──
        # Empty FIELD list -> all features collapse into one multipart.
        feedback.pushInfo("Dissolving to multipart...")
        run_processing("native:dissolve", {
            "INPUT": dissolve_source,
            "FIELD": [],
            "OUTPUT": out_dissolved,
        }, context=context, feedback=feedback)
        feedback.pushInfo(
            f"Dissolved multipart (CEO sampling boundary): {out_dissolved}")
        outputs[self.OUTPUT_DISSOLVED] = out_dissolved

        return outputs

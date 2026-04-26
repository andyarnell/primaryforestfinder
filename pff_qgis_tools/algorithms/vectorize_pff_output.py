"""
PFF Tool 7 -- Vectorize PFF Output
====================================
Post-processing tool: takes a binary or coded PFF raster and produces
a vectorised version, with optional minimum-patch-size filtering done
at the raster stage (so the filtered raster is also returned and can
feed zonal statistics downstream).

Outputs (up to three in one run):
  1. Filtered raster -- only when minimum patch area is set above 0.
     The mask raster after small connected groups have been sieved
     out. Feeds naturally into the existing Zonal Statistics tool.
  2. Vector -- polygonisation of the (possibly filtered) mask.
  3. Dissolved multipart vector -- single feature suitable as a
     sampling-area boundary for validation tools (e.g. Collect Earth
     Online; see https://collect.earth/).

Pixel value selector: comma-separated list, default '1'. Use '1,2,3'
to vectorise multiple classes from the combined coded raster (e.g.
for a broader sampling area than primary forest alone).

Filtering happens at raster level via gdal:sieve so the result
is consistent across raster + vector outputs and the filtered raster
is available for downstream zonal stats. No GRASS dependency.

Compatible with QGIS >= 3.38.
"""

import math
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
    QgsProcessingParameterRasterDestination,
)

from ..utils import ensure_dir, run_processing


class VectorizePffOutputAlgorithm(QgsProcessingAlgorithm):
    """Polygonise + optional raster-level patch-size filter + dissolve."""

    INPUT_RASTER = "INPUT_RASTER"
    PIXEL_VALUES = "PIXEL_VALUES"
    MIN_PATCH_AREA_HA = "MIN_PATCH_AREA_HA"
    OUTPUT_FILTERED_RASTER = "OUTPUT_FILTERED_RASTER"
    OUTPUT_VECTOR = "OUTPUT_VECTOR"
    OUTPUT_DISSOLVED = "OUTPUT_DISSOLVED"

    def name(self):
        return "vectorize_pff_output"

    def displayName(self):
        return "7 -- Vectorize PFF output"

    def group(self):
        return "Primary Forest Finder"

    def groupId(self):
        return "pff"

    def shortHelpString(self):
        return (
            "Polygonise a binary or coded PFF raster, with optional "
            "minimum-patch-size filtering done at the raster stage so "
            "the filtered raster is also returned (and can feed Zonal "
            "Statistics downstream).\n\n"
            "Inputs:\n"
            "  - Source raster (binary or coded).\n"
            "  - Pixel value(s) to vectorise (comma-separated, default "
            "'1'). Use e.g. '1,2,3' to vectorise multiple classes from "
            "the combined coded raster -- useful for a broader sampling "
            "area than primary forest alone.\n"
            "  - Minimum patch area in hectares (default 0 = no "
            "filtering). When > 0, gdal:sieve removes connected "
            "raster groups smaller than the threshold before "
            "polygonisation.\n\n"
            "Outputs:\n"
            "  1. Filtered raster -- only written when minimum patch "
            "area > 0. The mask raster after sieving. Plug into "
            "Zonal Statistics for area numbers that match the vector.\n"
            "  2. Vector -- polygonisation of the (possibly filtered) "
            "mask.\n"
            "  3. Dissolved multipart -- single feature suitable as a "
            "sampling-area boundary for validation workflows. Built "
            "from the filtered mask when filtering is on, otherwise "
            "from the raw mask.\n\n"
            "The dissolved multipart format is compatible with sampling "
            "inputs for validation tools such as Collect Earth Online "
            "(CEO): https://collect.earth/\n\n"
            "Background (0 / nodata) is masked before polygonisation so "
            "the tool doesn't waste cycles on country-wide background "
            "pixels.\n\n"
            "Typical use cases (rerun with different class selections):\n"
            "  - default '1' on primary_forest.tif -> strict primary-"
            "forest sampling area.\n"
            "  - '1,2,3' on combined_coded_raster.tif -> broader forest "
            "sampling area (forest + pre-connectivity + primary)."
        )

    def createInstance(self):
        return VectorizePffOutputAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT_RASTER,
            "Source raster (binary or coded)"))

        self.addParameter(QgsProcessingParameterString(
            self.PIXEL_VALUES,
            "Pixel value(s) to vectorise (comma-separated, e.g. '1' or "
            "'1,2,3' for multi-class from combined raster)",
            defaultValue="1"))

        # Min patch area in hectares. 0 = no filtering. Hectares chosen
        # for human-readable workshop scale ("10 ha" reads better than
        # "100,000 m^2"). Sieve threshold (in pixels) is computed from
        # this and the raster pixel area at run time.
        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_PATCH_AREA_HA,
            "Minimum patch area, hectares (0 = no filtering)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.0,
            minValue=0.0))

        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT_FILTERED_RASTER,
            "Output: filtered raster (only written when min area > 0)",
            optional=True))

        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_VECTOR,
            "Output: vector (polygonisation of filtered mask)",
            fileFilter="GeoPackage (*.gpkg);;Shapefile (*.shp)"))

        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_DISSOLVED,
            "Output: dissolved multipart (sampling-area boundary)",
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
        out_filtered_raster = self.parameterAsOutputLayer(
            parameters, self.OUTPUT_FILTERED_RASTER, context)
        out_vector = self.parameterAsString(
            parameters, self.OUTPUT_VECTOR, context)
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

        # ── Build the keep-mask raster ──
        # mask = 1 where input pixel is in pixel_values, else 0.
        # NO nodata flag here -- we need 0 to be a real value so sieve
        # has something to merge small "1" islands into. The nodata=0
        # flag gets re-applied later, just before polygonisation.
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

        scratch_dir = ensure_dir(tempfile.mkdtemp(prefix="pff_vectorize_"))

        def _write_mask(path, with_nodata):
            """Write the current `mask` array to `path` as Byte GTIFF."""
            drv = gdal.GetDriverByName("GTiff")
            ds_out = drv.Create(path, x_size, y_size, 1, gdal.GDT_Byte,
                                ["COMPRESS=LZW", "TILED=YES"])
            ds_out.SetGeoTransform(gt)
            ds_out.SetProjection(proj)
            b = ds_out.GetRasterBand(1)
            b.WriteArray(mask)
            if with_nodata:
                b.SetNoDataValue(0)
            b.FlushCache()
            ds_out = None

        # Initial mask raster (no nodata) -- input for sieve when filtering.
        mask_tif = os.path.join(scratch_dir, "mask.tif")
        _write_mask(mask_tif, with_nodata=False)
        del arr  # free memory; mask still needed if we skip sieve

        # ── Optional raster-level sieve ──
        # Convert hectares -> pixel-count threshold. ceil() so a 10ha
        # threshold rounds UP to whole pixels (a 99-pixel patch when
        # threshold == 99.something gets dropped, not kept).
        outputs = {}
        sieved_tif = mask_tif  # default: skip sieve, polygonise raw mask
        if min_area_ha > 0:
            min_area_m2 = min_area_ha * 10000.0
            threshold_px = max(1, math.ceil(min_area_m2 / pixel_area_m2))
            feedback.pushInfo(
                f"Sieving: removing connected groups < {threshold_px} px "
                f"(~{min_area_ha:g} ha) via gdal:sieve...")

            # Decide where the sieved raster lands. If the user gave an
            # explicit OUTPUT_FILTERED_RASTER path, use it (so it lives
            # alongside the vector outputs as a real deliverable).
            # Otherwise drop a copy in the scratch dir for internal use.
            if out_filtered_raster:
                sieved_tif = out_filtered_raster
            else:
                sieved_tif = os.path.join(scratch_dir, "mask_sieved.tif")

            # 4-connectivity matches the gdal:polygonize call below, so
            # the sieve and vectorise stages agree on patch grouping.
            run_processing("gdal:sieve", {
                "INPUT": mask_tif,
                "THRESHOLD": threshold_px,
                "EIGHT_CONNECTEDNESS": False,
                "OUTPUT": sieved_tif,
            }, context=context, feedback=feedback)
            feedback.pushInfo(f"Filtered raster: {sieved_tif}")
            if out_filtered_raster:
                outputs[self.OUTPUT_FILTERED_RASTER] = sieved_tif
        else:
            if out_filtered_raster:
                feedback.pushInfo(
                    "Min patch area is 0 -- filtered raster output "
                    "skipped (use the source raster directly).")

        if feedback.isCanceled():
            raise QgsProcessingException("Cancelled by user.")

        # ── Re-stamp nodata=0 for polygonisation efficiency ──
        # gdal:polygonize honours the nodata flag and skips background
        # pixels -- avoids the country-wide background-sweep trap.
        # Re-write the (possibly sieved) raster with nodata=0 set.
        polygonize_input = os.path.join(scratch_dir, "polygonize_input.tif")
        _ds_in = gdal.Open(sieved_tif, gdal.GA_ReadOnly)
        mask = _ds_in.GetRasterBand(1).ReadAsArray()
        _ds_in = None
        _write_mask(polygonize_input, with_nodata=True)
        del mask

        if feedback.isCanceled():
            raise QgsProcessingException("Cancelled by user.")

        # ── Polygonise ──
        feedback.pushInfo("Polygonising (gdal:polygonize, 4-connected)...")
        run_processing("gdal:polygonize", {
            "INPUT": polygonize_input,
            "BAND": 1,
            "FIELD": "value",
            "EIGHT_CONNECTEDNESS": False,
            "EXTRA": "",
            "OUTPUT": out_vector,
        }, context=context, feedback=feedback)
        feedback.pushInfo(f"Vector: {out_vector}")
        outputs[self.OUTPUT_VECTOR] = out_vector

        if feedback.isCanceled():
            raise QgsProcessingException("Cancelled by user.")

        # ── Dissolve to multipart ──
        feedback.pushInfo("Dissolving to multipart...")
        run_processing("native:dissolve", {
            "INPUT": out_vector,
            "FIELD": [],
            "OUTPUT": out_dissolved,
        }, context=context, feedback=feedback)
        feedback.pushInfo(
            f"Dissolved multipart (sampling-area boundary): {out_dissolved}")
        outputs[self.OUTPUT_DISSOLVED] = out_dissolved

        return outputs

"""
PFF Tool 7 -- Vectorize PFF Output
====================================
Post-processing tool: takes a binary or coded PFF raster and produces
a vectorised version (polygons), with optional geometry simplification,
plus a dissolved-multipart version suitable as a sampling-area
boundary for validation workflows.

Outputs:
  1. Vector -- polygonisation of the selected pixel value(s),
     optionally simplified.
  2. Dissolved multipart vector -- single feature suitable as a
     sampling-area boundary for validation tools (e.g. Collect Earth
     Online; see https://collect.earth/).

Pixel value selector: comma-separated list, default '1'. Use '1,2,3'
to vectorise multiple classes from the combined coded raster (e.g.
for a broader sampling area than primary forest alone).

Patch-size filtering is NOT done here -- use the Refine Output stage
(in Full Workflow) or the standalone Refine Output tool, which has a
"minimum patch size" option that runs at raster level. Sieving at
raster level keeps a refined raster + vector pair consistent and
feeds zonal stats cleanly.

No GRASS dependency -- uses gdal:polygonize + native:simplifygeometries
+ native:dissolve, all QGIS core.

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


class VectorizePffOutputAlgorithm(QgsProcessingAlgorithm):
    """Polygonise + optional simplify + dissolve."""

    INPUT_RASTER = "INPUT_RASTER"
    PIXEL_VALUES = "PIXEL_VALUES"
    SIMPLIFY_TOLERANCE_M = "SIMPLIFY_TOLERANCE_M"
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
            "Polygonise a binary or coded PFF raster and (optionally) "
            "simplify the geometries, then produce a dissolved-multipart "
            "version for validation sampling.\n\n"
            "Inputs:\n"
            "  - Source raster (binary or coded).\n"
            "  - Pixel value(s) to vectorise (comma-separated, default "
            "'1'). Use e.g. '1,2,3' to vectorise multiple classes from "
            "the combined coded raster -- useful for a broader sampling "
            "area than primary forest alone.\n"
            "  - Simplify tolerance in metres (default 0 = no "
            "simplification). Applied via native:simplifygeometries "
            "(Douglas-Peucker); PFF rasters are in projected metres-CRS "
            "so the tolerance is in metres directly. Typical values: "
            "30-100 m for national-scale outputs to remove pixel-edge "
            "zigzag.\n"
            "    USE WITH CAUTION: simplification can introduce "
            "geometry artefacts (self-intersections, removed slivers, "
            "snapped vertices) -- especially when small patches are "
            "present in the input raster. If downstream tools throw "
            "geometry errors, reduce the tolerance. For sensitive "
            "patch-level analyses, run small-patch removal first via "
            "Refine Output Step (b) before vectorising.\n\n"
            "Outputs:\n"
            "  1. Vector -- polygonisation of the selected pixel "
            "values, optionally simplified.\n"
            "  2. Dissolved multipart -- single feature, suitable as a "
            "sampling-area boundary for validation workflows.\n\n"
            "The dissolved multipart format is compatible with sampling "
            "inputs for validation tools such as Collect Earth Online "
            "(CEO): https://collect.earth/\n\n"
            "Background (0 / nodata) is masked before polygonisation so "
            "the tool doesn't waste cycles on country-wide background "
            "pixels.\n\n"
            "Patch-size filtering is NOT done here -- use Refine Output "
            "(Step b: minimum patch size) for that. Filtering at raster "
            "level keeps the refined raster + vector pair consistent "
            "and feeds Zonal Statistics cleanly.\n\n"
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

        # Simplify tolerance in metres. 0 = no simplification.
        # PFF vectors are in projected metres-CRS so $tolerance is in
        # metres directly. Typical values: 30-100 m for national-scale
        # outputs to remove pixel-edge zigzag. CAUTION: simplification
        # can introduce self-intersections and other geometry artefacts,
        # especially when small patches are present.
        self.addParameter(QgsProcessingParameterNumber(
            self.SIMPLIFY_TOLERANCE_M,
            "Simplify tolerance, metres (0 = no simplification; use "
            "with caution -- can introduce geometry artefacts, see help)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.0,
            minValue=0.0))

        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_VECTOR,
            "Output: vector (polygonised, optionally simplified)",
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
        simplify_tol_m = self.parameterAsDouble(
            parameters, self.SIMPLIFY_TOLERANCE_M, context)
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

        # ── Build masked raster ──
        # mask = 1 where input pixel is in pixel_values, else nodata.
        # nodata=0 set on output band -> gdal:polygonize skips background
        # automatically (avoids country-wide background-sweep trap).
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
        masked_tif = os.path.join(scratch_dir, "input_masked.tif")
        drv = gdal.GetDriverByName("GTiff")
        ds_out = drv.Create(masked_tif, x_size, y_size, 1, gdal.GDT_Byte,
                            ["COMPRESS=LZW", "TILED=YES"])
        ds_out.SetGeoTransform(gt)
        ds_out.SetProjection(proj)
        b = ds_out.GetRasterBand(1)
        b.WriteArray(mask)
        b.SetNoDataValue(0)
        b.FlushCache()
        ds_out = None
        del arr, mask  # free before polygonize re-reads

        if feedback.isCanceled():
            raise QgsProcessingException("Cancelled by user.")

        # ── Polygonise ──
        # 4-connectivity matches sieve in Refine Output Step (b) so
        # patch grouping is consistent across the two tools.
        if simplify_tol_m > 0:
            # Polygonise to a scratch path, then simplify into the user
            # output. Two steps so simplify and polygonise outputs are
            # independently inspectable.
            polygonised_tmp = os.path.join(scratch_dir, "polygonised.gpkg")
        else:
            polygonised_tmp = out_vector

        feedback.pushInfo("Polygonising (gdal:polygonize, 4-connected)...")
        run_processing("gdal:polygonize", {
            "INPUT": masked_tif,
            "BAND": 1,
            "FIELD": "value",
            "EIGHT_CONNECTEDNESS": False,
            "EXTRA": "",
            "OUTPUT": polygonised_tmp,
        }, context=context, feedback=feedback)

        if feedback.isCanceled():
            raise QgsProcessingException("Cancelled by user.")

        # ── Optional simplify (Douglas-Peucker via native:simplifygeometries) ──
        # tolerance is in CRS units; PFF rasters validate to projected
        # metres-CRS upstream, so this is metres directly.
        if simplify_tol_m > 0:
            feedback.pushInfo(
                f"Simplifying geometries (Douglas-Peucker, "
                f"tolerance={simplify_tol_m:g} m)...")
            feedback.pushWarning(
                "Simplify can introduce geometry artefacts (self-"
                "intersections, removed slivers, snapped vertices), "
                "especially with small patches. If downstream tools "
                "throw geometry errors, reduce the tolerance or run "
                "Refine Output Step (b) first to remove small patches "
                "before vectorising.")
            run_processing("native:simplifygeometries", {
                "INPUT": polygonised_tmp,
                "METHOD": 0,  # 0 = Distance (Douglas-Peucker)
                "TOLERANCE": simplify_tol_m,
                "OUTPUT": out_vector,
            }, context=context, feedback=feedback)
        feedback.pushInfo(f"Vector: {out_vector}")
        outputs = {self.OUTPUT_VECTOR: out_vector}

        if feedback.isCanceled():
            raise QgsProcessingException("Cancelled by user.")

        # ── Dissolve to multipart ──
        # Empty FIELD list -> all features collapse into one multipart.
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

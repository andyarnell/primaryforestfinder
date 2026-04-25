"""
PFF Tool 1 -- Validate Inputs
==============================
Checks that all input datasets meet required conditions before processing:
CRS consistency, projected CRS, raster resolution match, binary values.

Compatible with QGIS >= 3.38.
"""

from osgeo import gdal

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFileDestination,
)

from ..utils import validate_crs_projected, get_raster_info, validate_binary_raster


class ValidateInputsAlgorithm(QgsProcessingAlgorithm):
    FOREST_RASTER = "FOREST_RASTER"
    ROADS = "ROADS"
    BUILTUP = "BUILTUP"
    AGRICULTURE = "AGRICULTURE"
    DEM = "DEM"
    PROTECTED_AREAS = "PROTECTED_AREAS"
    AOI = "AOI"
    OUTPUT_REPORT = "OUTPUT_REPORT"

    def name(self):
        return "validate_inputs"

    def displayName(self):
        return "1 -- Validate Inputs"

    def group(self):
        return "Primary Forest Finder"

    def groupId(self):
        return "pff"

    def shortHelpString(self):
        return (
            "Checks that all input datasets meet the requirements for "
            "the PFF workflow:\n\n"
            "- All layers share a projected CRS (units in metres)\n"
            "- Raster resolutions are consistent\n"
            "- Binary rasters contain only 0 and 1\n\n"
            "Produces a validation_report.txt.  If validation fails the "
            "workflow should not proceed."
        )

    def createInstance(self):
        return ValidateInputsAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.FOREST_RASTER, "Forest extent raster (binary 1/0)"))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.ROADS, "Roads (vector)", optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.BUILTUP, "Built-up areas (vector)", optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.AGRICULTURE, "Agriculture / cropland (vector)", optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DEM, "Digital Elevation Model (DEM)", optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.PROTECTED_AREAS, "Protected areas (vector)", optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.AOI, "Area of Interest boundary (vector)", optional=True))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_REPORT, "Validation report",
            fileFilter="Text files (*.txt)"))

    def processAlgorithm(self, parameters, context, feedback):
        report_lines = ["PFF Input Validation Report", "=" * 40, ""]
        errors = []
        warnings = []

        # -- Collect layers --
        forest = self.parameterAsRasterLayer(
            parameters, self.FOREST_RASTER, context)
        dem = self.parameterAsRasterLayer(parameters, self.DEM, context)

        vector_params = {
            "Roads": self.ROADS,
            "Built-up": self.BUILTUP,
            "Agriculture": self.AGRICULTURE,
            "Protected areas": self.PROTECTED_AREAS,
            "AOI": self.AOI,
        }

        all_layers = {"Forest raster": forest}
        for label, key in vector_params.items():
            layer = self.parameterAsVectorLayer(parameters, key, context)
            if layer is not None:
                all_layers[label] = layer
        if dem is not None:
            all_layers["DEM"] = dem

        # -- 1. Projected CRS check --
        report_lines.append("1. CRS checks")
        report_lines.append("-" * 30)
        ref_crs = forest.crs()
        if ref_crs.isGeographic():
            msg = (f"FAIL: Forest raster uses geographic CRS "
                   f"({ref_crs.authid()}). A projected CRS in metres "
                   f"is required.")
            errors.append(msg)
            report_lines.append(msg)
        else:
            report_lines.append(
                f"OK: Forest raster CRS = {ref_crs.authid()} (projected)")

        for label, layer in all_layers.items():
            if label == "Forest raster":
                continue
            crs = layer.crs()
            if crs != ref_crs:
                msg = (f"WARN: '{label}' CRS ({crs.authid()}) differs "
                       f"from forest raster ({ref_crs.authid()}). "
                       f"'Prepare Datasets' will reproject automatically.")
                warnings.append(msg)
                report_lines.append(msg)
            else:
                report_lines.append(
                    f"OK: '{label}' CRS matches ({crs.authid()})")
        report_lines.append("")

        # -- 2. Raster resolution consistency --
        report_lines.append("2. Raster resolution checks")
        report_lines.append("-" * 30)
        _, gt, _, _ = get_raster_info(forest.source())
        ref_res = abs(gt[1])
        report_lines.append(f"Reference resolution: {ref_res} m")

        if dem is not None:
            _, dgt, _, _ = get_raster_info(dem.source())
            dem_res = abs(dgt[1])
            if abs(dem_res - ref_res) > 0.01:
                msg = (f"WARN: DEM resolution ({dem_res}) differs from "
                       f"forest raster ({ref_res}). Will be resampled.")
                warnings.append(msg)
                report_lines.append(msg)
            else:
                report_lines.append(f"OK: DEM resolution matches ({dem_res})")
        report_lines.append("")

        # -- 3. Binary raster validation --
        report_lines.append("3. Binary raster validation")
        report_lines.append("-" * 30)
        if validate_binary_raster(forest.source(), feedback):
            report_lines.append("OK: Forest raster is binary (0/1)")
        else:
            msg = "FAIL: Forest raster is NOT binary (values outside 0-1)."
            errors.append(msg)
            report_lines.append(msg)
        report_lines.append("")

        # -- Summary --
        report_lines.append("=" * 40)
        if errors:
            report_lines.append(f"RESULT: FAILED -- {len(errors)} error(s), "
                                f"{len(warnings)} warning(s)")
            for e in errors:
                report_lines.append(f"  ERROR: {e}")
        elif warnings:
            report_lines.append(f"RESULT: PASSED with {len(warnings)} "
                                f"warning(s)")
        else:
            report_lines.append("RESULT: PASSED -- all checks OK")

        for w in warnings:
            report_lines.append(f"  WARNING: {w}")

        # -- Write report --
        report_path = self.parameterAsString(
            parameters, self.OUTPUT_REPORT, context)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))

        feedback.pushInfo("\n".join(report_lines))

        if errors:
            feedback.reportError(
                "Validation FAILED. Fix errors before running the workflow.")

        return {self.OUTPUT_REPORT: report_path}

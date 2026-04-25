"""
PFF Tool 7 -- Generate CEO validation plots
============================================
Stratified random sampling from PFF forest / primary rasters to produce
a Collect Earth Online (CEO) upload CSV.

Because primary is a subset of forest, the three strata collapse to a
single sum-raster (forest + primary) with values 0 / 1 / 2:
    0 = non-forest
    1 = forest but not primary
    2 = primary (also forest)

For each stratum the user specifies how many plots to sample. The tool
writes a CSV with: PLOTID, CENTER_LON, CENTER_LAT, STRATUM.

Optionally writes a stratum-area summary CSV (pixels x pixel area) for
later area-weighted accuracy calculations.

Uses only numpy + GDAL + QGIS core (no rasterio / pandas / scipy).
Compatible with QGIS >= 3.28.
"""

import csv
import os

import numpy as np
from osgeo import gdal

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFileDestination,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsPointXY,
)

from ..utils import get_raster_info


# Stratum coding: stratum_raster = forest + primary (primary implies forest)
STRATUM_LABELS = {
    0: "non_forest",
    1: "forest_only",
    2: "primary",
}


class GenerateCeoPlotsAlgorithm(QgsProcessingAlgorithm):
    FOREST_RASTER = "FOREST_RASTER"
    PRIMARY_RASTER = "PRIMARY_RASTER"
    N_PER_STRATUM = "N_PER_STRATUM"
    N_NON_FOREST = "N_NON_FOREST"
    RANDOM_SEED = "RANDOM_SEED"
    BLIND = "BLIND"
    WRITE_AREAS = "WRITE_AREAS"
    OUTPUT_CSV = "OUTPUT_CSV"

    def name(self):
        return "generate_ceo_plots"

    def displayName(self):
        return "7 -- Generate CEO validation plots"

    def group(self):
        return "Primary Forest Finder"

    def groupId(self):
        return "pff"

    def shortHelpString(self):
        return (
            "Generate a Collect Earth Online (CEO) upload CSV of stratified "
            "random plots from PFF forest and primary forest rasters.\n\n"
            "Three strata are sampled:\n"
            "  - non_forest\n"
            "  - forest_only (forest but not primary)\n"
            "  - primary (primary forest, also forest)\n\n"
            "Output CSV columns: PLOTID, CENTER_LON, CENTER_LAT, STRATUM.\n"
            "Coordinates written in WGS84 (EPSG:4326) for CEO compatibility.\n\n"
            "Tick 'Blind output' to omit the STRATUM column from the CSV "
            "(recommended for validation -- keep the STRATUM mapping locally).\n"
            "Tick 'Write stratum-area summary' to also write a sidecar CSV "
            "with total area per stratum for area-weighted accuracy analysis."
        )

    def createInstance(self):
        return GenerateCeoPlotsAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.FOREST_RASTER,
            "Forest raster (binary 1/0)"))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.PRIMARY_RASTER,
            "Primary forest raster (binary 1/0) -- optional",
            optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.N_PER_STRATUM,
            "Plots per forest and primary stratum",
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=50, minValue=1, maxValue=5000))
        self.addParameter(QgsProcessingParameterNumber(
            self.N_NON_FOREST,
            "Plots in non-forest stratum (0 to skip)",
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=50, minValue=0, maxValue=5000))
        self.addParameter(QgsProcessingParameterNumber(
            self.RANDOM_SEED,
            "Random seed (for reproducibility)",
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=42, minValue=0))
        self.addParameter(QgsProcessingParameterBoolean(
            self.BLIND,
            "Blind output -- omit STRATUM column from CSV",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean(
            self.WRITE_AREAS,
            "Also write stratum-area summary CSV",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_CSV, "Output CEO plots CSV",
            fileFilter="CSV files (*.csv)"))

    def processAlgorithm(self, parameters, context, feedback):
        forest_layer = self.parameterAsRasterLayer(
            parameters, self.FOREST_RASTER, context)
        primary_layer = self.parameterAsRasterLayer(
            parameters, self.PRIMARY_RASTER, context)
        n_per = self.parameterAsInt(parameters, self.N_PER_STRATUM, context)
        n_nf = self.parameterAsInt(parameters, self.N_NON_FOREST, context)
        seed = self.parameterAsInt(parameters, self.RANDOM_SEED, context)
        blind = self.parameterAsBool(parameters, self.BLIND, context)
        write_areas = self.parameterAsBool(parameters, self.WRITE_AREAS, context)
        out_csv = self.parameterAsFileOutput(
            parameters, self.OUTPUT_CSV, context)

        # ── Load forest raster ──
        forest_path = forest_layer.source()
        feedback.pushInfo(f"Reading forest raster: {forest_path}")
        forest_ds = gdal.Open(forest_path, gdal.GA_ReadOnly)
        forest_arr = forest_ds.GetRasterBand(1).ReadAsArray()
        gt = forest_ds.GetGeoTransform()
        proj = forest_ds.GetProjection()
        x_size = forest_ds.RasterXSize
        y_size = forest_ds.RasterYSize
        forest_ds = None

        # ── Load primary raster (optional, align shape) ──
        if primary_layer is not None:
            primary_path = primary_layer.source()
            feedback.pushInfo(f"Reading primary raster: {primary_path}")
            primary_ds = gdal.Open(primary_path, gdal.GA_ReadOnly)
            if (primary_ds.RasterXSize != x_size
                    or primary_ds.RasterYSize != y_size):
                feedback.reportError(
                    "Primary raster dimensions don't match forest raster. "
                    "Align them first (e.g. via Prepare Datasets).")
                primary_ds = None
                return {}
            primary_arr = primary_ds.GetRasterBand(1).ReadAsArray()
            primary_ds = None
        else:
            primary_arr = np.zeros_like(forest_arr)
            feedback.pushInfo(
                "No primary raster provided -- only non-forest + forest_only strata.")

        # ── Build stratum raster: 0 non-forest, 1 forest_only, 2 primary ──
        # Cast to uint8 to ensure sum stays bounded
        forest_bin = (forest_arr > 0).astype(np.uint8)
        primary_bin = (primary_arr > 0).astype(np.uint8)
        stratum = forest_bin + primary_bin  # values: 0, 1, 2

        # ── Set up CRS transform to WGS84 ──
        src_crs = QgsCoordinateReferenceSystem.fromWkt(proj) if proj else None
        if src_crs is None or not src_crs.isValid():
            feedback.reportError(
                "Could not read source CRS from forest raster.")
            return {}
        if src_crs.isGeographic():
            feedback.pushInfo(
                "Forest raster is in a geographic CRS; coordinates will be "
                "in degrees. CEO accepts EPSG:4326 directly.")
            do_transform = src_crs.authid() != "EPSG:4326"
        else:
            do_transform = True

        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        if do_transform:
            transform = QgsCoordinateTransform(
                src_crs, wgs84, QgsProject.instance())
        else:
            transform = None

        # ── Pixel area (for stratum summary) ──
        pixel_area_m2 = abs(gt[1] * gt[5])
        pixel_area_ha = pixel_area_m2 / 10000.0

        # ── Sample each stratum ──
        rng = np.random.default_rng(seed)
        rows = []
        plot_id = 1
        stratum_counts = {}

        targets = [(0, n_nf), (1, n_per), (2, n_per)]
        for val, n_samples in targets:
            if n_samples <= 0:
                continue
            yy, xx = np.where(stratum == val)
            total = len(yy)
            stratum_counts[val] = total
            label = STRATUM_LABELS[val]
            if total == 0:
                feedback.pushWarning(
                    f"Stratum '{label}' (value {val}) has 0 pixels -- skipping.")
                continue
            n_draw = min(n_samples, total)
            if n_draw < n_samples:
                feedback.pushWarning(
                    f"Stratum '{label}' has only {total} pixels, "
                    f"sampling {n_draw} of requested {n_samples}.")
            idx = rng.choice(total, size=n_draw, replace=False)

            feedback.pushInfo(
                f"Sampling {n_draw} pixels from stratum '{label}' "
                f"(total {total} pixels, "
                f"{total * pixel_area_ha:,.0f} ha).")

            for i in idx:
                row = int(yy[i])
                col = int(xx[i])
                # Pixel centre in source CRS
                src_x = gt[0] + (col + 0.5) * gt[1] + (row + 0.5) * gt[2]
                src_y = gt[3] + (col + 0.5) * gt[4] + (row + 0.5) * gt[5]
                if transform is not None:
                    pt = transform.transform(QgsPointXY(src_x, src_y))
                    lon, lat = pt.x(), pt.y()
                else:
                    lon, lat = src_x, src_y
                rows.append({
                    "PLOTID": plot_id,
                    "CENTER_LON": round(lon, 7),
                    "CENTER_LAT": round(lat, 7),
                    "STRATUM": label,
                })
                plot_id += 1

        if not rows:
            feedback.reportError("No plots sampled -- check inputs.")
            return {}

        # ── Shuffle so stratum order in CSV is random (avoids order bias
        # for participants who see the CSV) ──
        rng.shuffle(rows)
        # Reassign PLOTID in the new order so IDs are sequential
        for i, r in enumerate(rows, start=1):
            r["PLOTID"] = i

        # ── Write output CSV ──
        columns = ["PLOTID", "CENTER_LON", "CENTER_LAT"]
        if not blind:
            columns.append("STRATUM")
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        feedback.pushInfo(
            f"Wrote {len(rows)} plots -> {out_csv}"
            + (" (blind, STRATUM column omitted)" if blind else ""))

        # ── Optional: stratum-area summary CSV ──
        outputs = {self.OUTPUT_CSV: out_csv}
        if write_areas:
            area_path = os.path.splitext(out_csv)[0] + "_stratum_areas.csv"
            with open(area_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["stratum", "pixel_count", "area_ha",
                                 "area_kha", "sampled_plots"])
                sampled_per = {}
                for r in rows:
                    sampled_per[r["STRATUM"]] = (
                        sampled_per.get(r["STRATUM"], 0) + 1)
                for val, label in STRATUM_LABELS.items():
                    px = int(stratum_counts.get(val, 0))
                    ha = px * pixel_area_ha
                    writer.writerow([
                        label,
                        px,
                        round(ha, 1),
                        round(ha / 1000.0, 3),
                        sampled_per.get(label, 0),
                    ])
            feedback.pushInfo(f"Wrote stratum-area summary -> {area_path}")
            outputs["OUTPUT_AREAS"] = area_path

        if blind:
            feedback.pushInfo(
                "Reminder: keep a non-blind copy of this CSV locally for "
                "later validation analysis -- the STRATUM column is needed "
                "to match PFF classification against CEO responses.")

        return outputs

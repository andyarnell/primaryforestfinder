"""
PFF Tool 6 -- Zonal Statistics
================================
Computes total area (kha) for PFF raster outputs and prints the result.

By default computes a single total.  Tick "Per-zone breakdown" and
provide a zone layer to get per-zone rows.

Outputs a CSV table and optionally joins stats back onto the zone vector.

The core function ``compute_zonal_stats()`` is also called by the
Full Workflow when its "Run zonal statistics" option is enabled.

Compatible with QGIS >= 3.38.
"""

import csv
import os

import numpy as np
from osgeo import gdal

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterField,
    QgsCoordinateReferenceSystem,
)

from ..utils import (
    ensure_dir,
    get_raster_info,
    reproject_vector,
    run_processing,
)


# ── Reusable core ────────────────────────────────────────────────────

def compute_zonal_stats(ref_raster_path, raster_paths=None,
                        zone_layer_path=None, zone_field=None,
                        target_crs_str=None, work_dir=None,
                        context=None, feedback=None):
    """Compute area in kha for each binary raster.

    Without a zone layer, returns a single-row total.
    With a zone layer, returns one row per zone.

    Returns (results, totals) where:
      results = list[dict]  (per-zone or single-row)
      totals  = dict        {label: total_kha}
    """
    if raster_paths is None:
        raster_paths = {}
    if not raster_paths:
        if feedback:
            feedback.reportError("No raster inputs provided.")
        return [], {}

    ref_proj, gt, x_size, y_size = get_raster_info(ref_raster_path)
    pixel_area_m2 = abs(gt[1] * gt[5])
    pixel_area_kha = pixel_area_m2 / 1e7  # 1 kha = 10,000,000 m2

    # Pre-load rasters
    loaded = {}
    for label, rpath in raster_paths.items():
        ds = gdal.Open(rpath, gdal.GA_ReadOnly)
        loaded[label] = ds.GetRasterBand(1).ReadAsArray()
        ds = None

    # -- No zones: single total --
    if zone_layer_path is None:
        row = {"zone_name": "TOTAL"}
        for label, arr in loaded.items():
            if feedback:
                feedback.pushInfo(f"  Calculating {label} area...")
            count = int((arr == 1).sum())
            row[f"{label}_kha"] = round(count * pixel_area_kha, 1)
        return [row], {label: row[f"{label}_kha"] for label in loaded}

    # -- With zones --
    if target_crs_str is None:
        crs = QgsCoordinateReferenceSystem.fromWkt(ref_proj)
        target_crs_str = crs.authid()

    if work_dir is None:
        work_dir = ensure_dir(os.path.join(
            os.path.dirname(ref_raster_path), "_pff_zonal_work"))
    else:
        ensure_dir(work_dir)

    if feedback:
        feedback.pushInfo("Preparing zones...")
    # Use shapefile for intermediate to avoid gpkg FID uniqueness issues
    # when source has duplicate FIDs (e.g. GEE-exported country boundaries)
    zone_reproj = os.path.join(work_dir, "zones_reproj.shp")
    reproject_vector(zone_layer_path, target_crs_str,
                     zone_reproj, context=context, feedback=feedback)

    zone_with_id = os.path.join(work_dir, "zones_with_id.shp")
    run_processing("native:fieldcalculator", {
        "INPUT": zone_reproj,
        "FIELD_NAME": "_pff_zid",
        "FIELD_TYPE": 1,
        "FIELD_LENGTH": 10,
        "FORMULA": "@row_number + 1",
        "OUTPUT": zone_with_id,
    }, context=context, feedback=feedback)

    # Build name lookup and verify _pff_zid values
    from qgis.core import QgsVectorLayer
    zid_layer = QgsVectorLayer(zone_with_id, "z", "ogr")
    zone_names = {}
    zid_values = []
    for feat in zid_layer.getFeatures():
        zid = feat["_pff_zid"]
        zid_values.append(zid)
        if zone_field and zone_field in [f.name() for f in feat.fields()]:
            zone_names[zid] = str(feat[zone_field])
        else:
            zone_names[zid] = str(zid)
    if feedback:
        feedback.pushInfo(
            f"Zone IDs (_pff_zid): {zid_values[:20]}"
            f"{'...' if len(zid_values) > 20 else ''}"
            f" ({len(zid_values)} features)")

    # Rasterise zones
    if feedback:
        feedback.pushInfo("Rasterising zones...")
    zone_ras = os.path.join(work_dir, "zones.tif")
    res = abs(gt[1])
    ext = (f"{gt[0]},{gt[0] + gt[1] * x_size},"
           f"{gt[3] + gt[5] * y_size},{gt[3]}")
    run_processing("gdal:rasterize", {
        "INPUT": zone_with_id,
        "FIELD": "_pff_zid",
        "BURN": 0,
        "USE_Z": False,
        "UNITS": 1,
        "WIDTH": res,
        "HEIGHT": res,
        "EXTENT": ext,
        "NODATA": -1,
        "DATA_TYPE": 4,         # Int32 (supports -1)
        "INIT": -1,
        "OUTPUT": zone_ras,
    }, context=context, feedback=feedback)

    zone_ds = gdal.Open(zone_ras, gdal.GA_ReadOnly)
    zone_arr = zone_ds.GetRasterBand(1).ReadAsArray()
    zone_ds = None

    unique_zones = np.unique(zone_arr[zone_arr > 0])
    if len(unique_zones) == 0:
        if feedback:
            feedback.reportError("No zones rasterised — check overlap / CRS.")
        return [], {}

    # Compute per zone
    if feedback:
        for label in loaded:
            feedback.pushInfo(f"  Calculating {label} area per zone...")
    results = []
    totals = {label: 0.0 for label in loaded}

    for z_id in unique_zones:
        if feedback and feedback.isCanceled():
            break
        z_mask = (zone_arr == z_id)
        zone_name = zone_names.get(int(z_id), str(int(z_id)))
        row = {"zone_id": int(z_id), "zone_name": zone_name}
        for label, arr in loaded.items():
            count = int((arr[z_mask] == 1).sum())
            kha = round(count * pixel_area_kha, 1)
            row[f"{label}_kha"] = kha
            totals[label] += kha
        results.append(row)

    # Round totals
    totals = {k: round(v, 1) for k, v in totals.items()}

    return results, totals


def write_zonal_csv(results, totals, csv_path, feedback=None):
    """Write results + totals row to CSV."""
    if not results:
        return
    fieldnames = list(results[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
        # Totals row
        if len(results) > 1:
            total_row = {fieldnames[0]: "", "zone_name": "TOTAL"}
            for k, v in totals.items():
                total_row[f"{k}_kha"] = v
            writer.writerow(total_row)
    if feedback:
        feedback.pushInfo(f"CSV written: {csv_path}")


def _shp_field_name(name):
    """Shorten a stat field name to fit shapefile 10-char limit."""
    short = {
        "primary_forest_kha": "pf_kha",
        "pre_connectivity_forest_kha": "precon_kha",
        "input_forest_kha": "forest_kha",
    }
    if name in short:
        return short[name]
    # Generic truncation
    return name[:10]


def join_stats_to_vector(results, zone_with_id_path, output_path,
                         target_crs_str, context=None, feedback=None):
    """Copy zone vector and add stat columns via OGR."""
    from osgeo import ogr

    run_processing("native:reprojectlayer", {
        "INPUT": zone_with_id_path,
        "TARGET_CRS": QgsCoordinateReferenceSystem(target_crs_str),
        "OUTPUT": output_path,
    }, context=context, feedback=feedback)

    result_map = {r["zone_id"]: r for r in results}
    stat_fields = [k for k in results[0].keys()
                   if k not in ("zone_id", "zone_name")]

    # Use short names for shapefile compat
    is_shp = output_path.lower().endswith(".shp")
    field_map = {}  # original_name -> output_name
    for fname in stat_fields:
        field_map[fname] = _shp_field_name(fname) if is_shp else fname

    ds = ogr.Open(output_path, 1)
    lyr = ds.GetLayer(0)
    for fname in stat_fields:
        fld = ogr.FieldDefn(field_map[fname], ogr.OFTReal)
        fld.SetWidth(16)
        fld.SetPrecision(1)
        lyr.CreateField(fld)

    lyr.ResetReading()
    for feat in lyr:
        zid = feat.GetField("_pff_zid")
        if zid in result_map:
            for fname in stat_fields:
                feat.SetField(field_map[fname],
                              result_map[zid].get(fname, 0))
            lyr.SetFeature(feat)
    ds.FlushCache()
    ds = None

    if feedback:
        feedback.pushInfo(f"Stats joined to vector: {output_path}")


# ── QGIS Algorithm ──────────────────────────────────────────────────

class ZonalStatisticsAlgorithm(QgsProcessingAlgorithm):
    PRIMARY_FOREST = "PRIMARY_FOREST"
    PRE_CONNECTIVITY = "PRE_CONNECTIVITY"
    INPUT_FOREST = "INPUT_FOREST"
    USE_ZONES = "USE_ZONES"
    ZONE_LAYER = "ZONE_LAYER"
    ZONE_FIELD = "ZONE_FIELD"
    JOIN_TO_VECTOR = "JOIN_TO_VECTOR"
    OUTPUT_CSV = "OUTPUT_CSV"
    OUTPUT_VECTOR = "OUTPUT_VECTOR"

    def name(self):
        return "zonal_statistics"

    def displayName(self):
        return "6 -- Zonal Statistics"

    def group(self):
        return "Primary Forest Finder"

    def groupId(self):
        return "pff"

    def shortHelpString(self):
        return (
            "Computes total area (kha) for PFF raster outputs.\n\n"
            "By default prints a single total figure per raster.\n"
            "Tick 'Per-zone breakdown' and supply a zone layer for "
            "per-zone statistics.\n\n"
            "Tick 'Join stats to input vector' to get a copy of the "
            "zone layer with area columns added.\n\n"
            "Also available as an optional stage in the Full Workflow."
        )

    def createInstance(self):
        return ZonalStatisticsAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.PRIMARY_FOREST,
            "Primary forest candidate raster (binary)"))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.PRE_CONNECTIVITY,
            "Pre-connectivity forest raster (binary)",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT_FOREST,
            "Input forest raster (binary)",
            optional=True))

        self.addParameter(QgsProcessingParameterBoolean(
            self.USE_ZONES,
            "Per-zone breakdown",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.ZONE_LAYER,
            "Zone layer (polygons)",
            optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.ZONE_FIELD, "Zone name / ID field",
            parentLayerParameterName=self.ZONE_LAYER,
            optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.JOIN_TO_VECTOR,
            "Join stats to input vector",
            defaultValue=False))

        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_CSV, "Output CSV",
            fileFilter="CSV files (*.csv)"))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_VECTOR,
            "Output vector with stats (only when join is ticked)",
            fileFilter="Shapefile (*.shp)",
            optional=True))

    def processAlgorithm(self, parameters, context, feedback):
        # Rasters
        raster_paths = {}
        pf_layer = self.parameterAsRasterLayer(
            parameters, self.PRIMARY_FOREST, context)
        raster_paths["primary_forest"] = pf_layer.source()

        for param, label in [
            (self.PRE_CONNECTIVITY, "pre_connectivity_forest"),
            (self.INPUT_FOREST, "input_forest"),
        ]:
            layer = self.parameterAsRasterLayer(parameters, param, context)
            if layer is not None:
                raster_paths[label] = layer.source()

        use_zones = self.parameterAsBool(parameters, self.USE_ZONES, context)
        join_vec = self.parameterAsBool(
            parameters, self.JOIN_TO_VECTOR, context)
        csv_path = self.parameterAsString(
            parameters, self.OUTPUT_CSV, context)
        vec_path = self.parameterAsString(
            parameters, self.OUTPUT_VECTOR, context)

        zone_path = None
        zone_field = None
        if use_zones:
            zl = self.parameterAsVectorLayer(
                parameters, self.ZONE_LAYER, context)
            if zl:
                zone_path = zl.source()
                zone_field = (self.parameterAsString(
                    parameters, self.ZONE_FIELD, context).strip() or None)

        work_dir = ensure_dir(os.path.join(
            os.path.dirname(csv_path or pf_layer.source()),
            "_pff_zonal_work"))

        results, totals = compute_zonal_stats(
            ref_raster_path=pf_layer.source(),
            raster_paths=raster_paths,
            zone_layer_path=zone_path,
            zone_field=zone_field,
            work_dir=work_dir,
            context=context,
            feedback=feedback,
        )

        # -- Print headline totals --
        if totals:
            feedback.pushInfo("")
            feedback.pushInfo("========================================")
            for label, kha in totals.items():
                feedback.pushInfo(f"  {label}: {kha} kha")
            feedback.pushInfo("========================================")
            feedback.pushInfo("")
        elif results:
            # Single-row mode (no zones)
            feedback.pushInfo("")
            feedback.pushInfo("========================================")
            for label in raster_paths:
                key = f"{label}_kha"
                if key in results[0]:
                    feedback.pushInfo(
                        f"  {label}: {results[0][key]} kha")
            feedback.pushInfo("========================================")
            feedback.pushInfo("")

        # -- CSV --
        outputs = {}
        if csv_path and results:
            write_zonal_csv(results, totals, csv_path, feedback)
            outputs[self.OUTPUT_CSV] = csv_path

        # -- Join to vector --
        if join_vec and vec_path and zone_path and results:
            zone_with_id = os.path.join(work_dir, "zones_with_id.shp")
            ref_proj, _, _, _ = get_raster_info(pf_layer.source())
            crs = QgsCoordinateReferenceSystem.fromWkt(ref_proj)
            join_stats_to_vector(results, zone_with_id, vec_path,
                                 crs.authid(), context, feedback)
            outputs[self.OUTPUT_VECTOR] = vec_path

        feedback.setProgress(100)
        return outputs

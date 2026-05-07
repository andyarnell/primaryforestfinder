"""
PFF Tool 8 -- CEO Validation Export (experimental)
====================================================
Random / stratified-random sampling from a forest / primary forest
vector layer (e.g. PFF stage-6 nested polygons) into Collect Earth
Online (CEO) -compatible Plot + Sample layers. Ships GeoPackage and
optional zipped Shapefile so the user can upload only the SAMPLED
locations to CEO -- never the full national vector, which is too
geometry-heavy for CEO ingestion.

Two export methods:
  - Simple point plots: emit a single layer of point centres. CEO
    applies its default visualisation buffer (~500 m) on the server.
  - Custom circular ring boundaries: per-point thin annulus
    (radius .. radius + ring_width) PLUS a sample layer of either
    centre points OR 1 ha squares OR both. The ring layer goes to CEO
    as Plots (showing the interpretation boundary without obscuring
    imagery), the sample layer goes to CEO as Samples.

Field schema (CEO upload canonical):
  Plot layer:    PLOTID  (integer)
  Sample layer:  PLOTID  (integer), SAMPLEID (integer; == PLOTID)

Optional provenance fields (off by default):
  class_value, class_name, radius_m, ring_width_m,
  sample_type, sampling_method, random_seed, source_id

Geometry construction note:
  Rings are built per point in a Python loop (outer.difference(inner))
  so overlapping plots do NOT bite each other -- a global difference
  on the union of inner buffers would chew chunks out of neighbour
  rings.

Compatible with QGIS >= 3.28.
"""

from __future__ import annotations

import math
import os
import shutil
import tempfile
import zipfile

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsProject,
    QgsRectangle,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant


# --------------------------------------------------------------------- #
#  Internal helpers                                                     #
# --------------------------------------------------------------------- #

def _segments_for_circle() -> int:
    """Vertices per quarter-circle in buffer construction.

    16 segments per quarter * 4 = 64 segments total. Approximation
    error at r=2000m is ~5 m max chord deviation -- imperceptible on
    CEO's display, while keeping output Shapefile size manageable
    (rule 6 file-size sanity check enforces the budget). Test rule 3's
    0.5% area tolerance still passes comfortably (16-segment quarter
    circle has area within 0.16% of analytic).
    """
    return 16


def _hectare_square(centre: QgsPointXY, side_m: float) -> QgsGeometry:
    """Axis-aligned square of `side_m` x `side_m` centred on `centre`."""
    half = side_m / 2.0
    rect = QgsRectangle(centre.x() - half, centre.y() - half,
                        centre.x() + half, centre.y() + half)
    return QgsGeometry.fromRect(rect)


def _zip_shapefile_outputs(gpkg_path: str, zip_path: str,
                           layer_name: str) -> None:
    """Write the GPKG layer's contents as a Shapefile, then zip the
    .shp/.shx/.dbf/.prj/.cpg sidecar files into `zip_path`. Uses
    QgsVectorFileWriter directly so we don't depend on `processing`.
    """
    src = QgsVectorLayer(gpkg_path, layer_name, "ogr")
    if not src.isValid():
        raise QgsProcessingException(
            f"Cannot read GPKG for zip export: {gpkg_path}")
    with tempfile.TemporaryDirectory() as tmp:
        shp_path = os.path.join(tmp, layer_name + ".shp")
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "ESRI Shapefile"
        opts.fileEncoding = "UTF-8"
        opts.layerName = layer_name
        ctx = QgsProject.instance().transformContext()
        err = QgsVectorFileWriter.writeAsVectorFormatV3(
            src, shp_path, ctx, opts)
        # writeAsVectorFormatV3 returns a (code, message[, ...]) tuple.
        if err and isinstance(err, tuple) and err[0]:
            raise QgsProcessingException(
                f"Shapefile write failed for {layer_name}: {err[1]}")
        # Zip the family.
        with zipfile.ZipFile(zip_path, "w",
                             zipfile.ZIP_DEFLATED) as zf:
            base = os.path.splitext(shp_path)[0]
            for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
                p = base + ext
                if os.path.exists(p):
                    zf.write(p, arcname=layer_name + ext)


# --------------------------------------------------------------------- #
#  Algorithm                                                            #
# --------------------------------------------------------------------- #

class CeoValidationExportAlgorithm(QgsProcessingAlgorithm):
    """pff:ceo_validation_export"""

    # Param keys
    INPUT = "INPUT"
    CLASS_FIELD = "CLASS_FIELD"
    PRIMARY_CLASS_VALUE = "PRIMARY_CLASS_VALUE"
    OTHER_CLASS_VALUE = "OTHER_CLASS_VALUE"
    SAMPLING_DOMAIN = "SAMPLING_DOMAIN"
    STRATIFIED = "STRATIFIED"
    N_SAMPLES = "N_SAMPLES"
    N_PRIMARY = "N_PRIMARY"
    N_OTHER = "N_OTHER"
    MIN_DISTANCE = "MIN_DISTANCE"
    RANDOM_SEED = "RANDOM_SEED"
    EXPORT_METHOD = "EXPORT_METHOD"
    PLOT_RADIUS_M = "PLOT_RADIUS_M"
    RING_WIDTH_M = "RING_WIDTH_M"
    SAMPLE_GEOM_POINT = "SAMPLE_GEOM_POINT"
    SAMPLE_GEOM_SQUARE = "SAMPLE_GEOM_SQUARE"
    SQUARE_SIZE_M = "SQUARE_SIZE_M"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    OUTPUT_GEOPACKAGE = "OUTPUT_GEOPACKAGE"
    OUTPUT_ZIPPED_SHAPEFILE = "OUTPUT_ZIPPED_SHAPEFILE"
    ADD_PROVENANCE_FIELDS = "ADD_PROVENANCE_FIELDS"
    ALLOW_EMPTY_STRATUM = "ALLOW_EMPTY_STRATUM"

    # Domain enum (for SAMPLING_DOMAIN)
    DOMAIN_ALL = 0
    DOMAIN_PRIMARY = 1
    DOMAIN_OTHER = 2
    DOMAIN_LABELS = ["All forest", "Primary only", "Other forest only"]

    # Method enum (for EXPORT_METHOD)
    METHOD_SIMPLE_POINTS = 0
    METHOD_CIRCULAR = 1
    METHOD_LABELS = ["Simple point plots",
                     "Custom circular ring boundaries"]

    # ------------------------------------------------------------------ #
    #  QGIS metadata                                                     #
    # ------------------------------------------------------------------ #
    def name(self):
        return "ceo_validation_export"

    def displayName(self):
        return "8 -- CEO Validation Export (experimental)"

    def group(self):
        return "Primary Forest Finder"

    def groupId(self):
        return "pff"

    def shortHelpString(self):
        return (
            "EXPERIMENTAL. Generate Collect Earth Online (CEO) -ready "
            "Plot and Sample layers from a forest / primary forest "
            "vector. Outputs are lightweight (sampled locations only) "
            "so the user uploads only the small sample to CEO instead "
            "of the heavy national vector.\n\n"
            "Two methods:\n"
            "  - Simple point plots: emit point centres only. CEO "
            "applies a default visualisation buffer (~500 m) at "
            "ingestion time.\n"
            "  - Custom circular ring boundaries: per-point thin "
            "annulus polygon (Plot) plus a sample layer of centre "
            "points OR 1 ha squares OR both.\n\n"
            "Field schema for CEO upload:\n"
            "  Plot layer: PLOTID (integer)\n"
            "  Sample layer: PLOTID (integer), SAMPLEID (integer; "
            "always == PLOTID)\n\n"
            "Optional provenance fields off by default. Tick to enable "
            "for reproducibility / audit.\n\n"
            "Input must be in a projected CRS with metre units."
        )

    def createInstance(self):
        return CeoValidationExportAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT, "Forest / primary forest vector"))
        self.addParameter(QgsProcessingParameterField(
            self.CLASS_FIELD, "Class field",
            parentLayerParameterName=self.INPUT, type=QgsProcessingParameterField.Numeric,
            defaultValue="level"))
        self.addParameter(QgsProcessingParameterNumber(
            self.PRIMARY_CLASS_VALUE, "Primary forest class value",
            type=QgsProcessingParameterNumber.Integer, defaultValue=2))
        self.addParameter(QgsProcessingParameterNumber(
            self.OTHER_CLASS_VALUE, "Other-forest class value",
            type=QgsProcessingParameterNumber.Integer, defaultValue=1))
        self.addParameter(QgsProcessingParameterEnum(
            self.SAMPLING_DOMAIN, "Sampling domain",
            options=self.DOMAIN_LABELS,
            defaultValue=self.DOMAIN_ALL))
        self.addParameter(QgsProcessingParameterBoolean(
            self.STRATIFIED, "Stratified by class (primary vs other)",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterNumber(
            self.N_SAMPLES, "Number of samples (non-stratified)",
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=50, minValue=1, maxValue=100000))
        self.addParameter(QgsProcessingParameterNumber(
            self.N_PRIMARY, "N samples in primary stratum",
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=25, minValue=0, maxValue=100000))
        self.addParameter(QgsProcessingParameterNumber(
            self.N_OTHER, "N samples in other-forest stratum",
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=25, minValue=0, maxValue=100000))
        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_DISTANCE, "Minimum distance between samples (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0, minValue=0))
        self.addParameter(QgsProcessingParameterString(
            self.RANDOM_SEED, "Random seed (blank for system random)",
            defaultValue="", optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.EXPORT_METHOD, "Export method",
            options=self.METHOD_LABELS,
            defaultValue=self.METHOD_SIMPLE_POINTS))
        self.addParameter(QgsProcessingParameterNumber(
            self.PLOT_RADIUS_M, "Plot interpretation radius (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=2000, minValue=1))
        self.addParameter(QgsProcessingParameterNumber(
            self.RING_WIDTH_M, "Ring width (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=1, minValue=0.1))
        self.addParameter(QgsProcessingParameterBoolean(
            self.SAMPLE_GEOM_POINT, "Generate centre-point samples",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.SAMPLE_GEOM_SQUARE, "Generate 1 ha square samples",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterNumber(
            self.SQUARE_SIZE_M, "Sample square size (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=100, minValue=1))
        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_FOLDER, "Output folder"))
        self.addParameter(QgsProcessingParameterBoolean(
            self.OUTPUT_GEOPACKAGE, "Write GeoPackage outputs",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.OUTPUT_ZIPPED_SHAPEFILE,
            "Write zipped Shapefile outputs (CEO upload)",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ADD_PROVENANCE_FIELDS,
            "Add provenance fields (class_value, class_name, "
            "radius_m, ring_width_m, sample_type, sampling_method, "
            "random_seed, source_id)",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ALLOW_EMPTY_STRATUM,
            "Allow empty stratum (skip with warning instead of "
            "aborting)",
            defaultValue=False))

    # ------------------------------------------------------------------ #
    #  Run                                                               #
    # ------------------------------------------------------------------ #
    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsVectorLayer(
            parameters, self.INPUT, context)
        if layer is None or not layer.isValid():
            raise QgsProcessingException(
                "Input vector layer is missing or invalid.")

        crs = layer.crs()
        if not crs.isValid():
            raise QgsProcessingException(
                "Input layer has no CRS set.")
        if crs.isGeographic():
            raise QgsProcessingException(
                f"Input layer is in a geographic CRS ({crs.authid()}). "
                "CEO export needs a projected CRS in metres for "
                "buffering. Reproject the layer first, or run the PFF "
                "full workflow which writes projected outputs."
            )

        class_field = self.parameterAsString(
            parameters, self.CLASS_FIELD, context) or "level"
        primary_val = self.parameterAsInt(
            parameters, self.PRIMARY_CLASS_VALUE, context)
        other_val = self.parameterAsInt(
            parameters, self.OTHER_CLASS_VALUE, context)
        domain = self.parameterAsEnum(
            parameters, self.SAMPLING_DOMAIN, context)
        stratified = self.parameterAsBool(
            parameters, self.STRATIFIED, context)
        n_total = self.parameterAsInt(
            parameters, self.N_SAMPLES, context)
        n_primary = self.parameterAsInt(
            parameters, self.N_PRIMARY, context)
        n_other = self.parameterAsInt(
            parameters, self.N_OTHER, context)
        min_distance = self.parameterAsDouble(
            parameters, self.MIN_DISTANCE, context)
        seed_str = (self.parameterAsString(
            parameters, self.RANDOM_SEED, context) or "").strip()
        seed_int = None
        if seed_str:
            try:
                seed_int = int(seed_str)
            except ValueError:
                raise QgsProcessingException(
                    f"Random seed '{seed_str}' is not an integer.")
        method = self.parameterAsEnum(
            parameters, self.EXPORT_METHOD, context)
        radius = self.parameterAsDouble(
            parameters, self.PLOT_RADIUS_M, context)
        ring_w = self.parameterAsDouble(
            parameters, self.RING_WIDTH_M, context)
        gen_point = self.parameterAsBool(
            parameters, self.SAMPLE_GEOM_POINT, context)
        gen_square = self.parameterAsBool(
            parameters, self.SAMPLE_GEOM_SQUARE, context)
        square_side = self.parameterAsDouble(
            parameters, self.SQUARE_SIZE_M, context)
        out_dir = self.parameterAsString(
            parameters, self.OUTPUT_FOLDER, context)
        write_gpkg = self.parameterAsBool(
            parameters, self.OUTPUT_GEOPACKAGE, context)
        write_zip = self.parameterAsBool(
            parameters, self.OUTPUT_ZIPPED_SHAPEFILE, context)
        add_provenance = self.parameterAsBool(
            parameters, self.ADD_PROVENANCE_FIELDS, context)
        allow_empty = self.parameterAsBool(
            parameters, self.ALLOW_EMPTY_STRATUM, context)

        os.makedirs(out_dir, exist_ok=True)

        # Build the random number generator. Use stdlib `random` so we
        # don't add a numpy dependency to this algorithm; per-feature
        # area-weighted sampling is handled below.
        import random
        rng = random.Random(seed_int) if seed_int is not None else random.Random()

        # ── Pick features by class ──
        primary_feats = [f for f in layer.getFeatures()
                         if f.attribute(class_field) == primary_val]
        other_feats = [f for f in layer.getFeatures()
                       if f.attribute(class_field) == other_val]

        feedback.pushInfo(
            f"Input class counts: primary={len(primary_feats)} "
            f"(class_value={primary_val}), "
            f"other={len(other_feats)} (class_value={other_val})")

        # ── Sampling plan ──
        if stratified:
            plan = [(primary_val, n_primary, primary_feats),
                    (other_val, n_other, other_feats)]
        else:
            if domain == self.DOMAIN_PRIMARY:
                plan = [(primary_val, n_total, primary_feats)]
            elif domain == self.DOMAIN_OTHER:
                plan = [(other_val, n_total, other_feats)]
            else:  # DOMAIN_ALL
                plan = [("ALL", n_total, primary_feats + other_feats)]

        # ── Validate empty strata up front ──
        for class_id, n_req, feats in plan:
            if n_req > 0 and not feats:
                msg = (
                    f"Selected stratum (class_value={class_id}) has no "
                    "features in the input. ")
                if allow_empty:
                    feedback.pushWarning(msg + "Skipping (allow_empty).")
                else:
                    raise QgsProcessingException(
                        msg + "Set 'Allow empty stratum' to skip with "
                        "a warning instead of aborting.")

        # ── Generate centres ──
        all_centres = []  # list of (QgsPointXY, class_value, source_fid)
        method_name = ("stratified_random" if stratified
                       else ("minimum_distance_random"
                             if min_distance > 0 else "simple_random"))

        for class_id, n_req, feats in plan:
            if n_req <= 0 or not feats:
                continue
            label_for_log = (
                "primary" if class_id == primary_val else
                "other" if class_id == other_val else
                "all")
            centres = self._area_weighted_sample(
                feats, n_req, min_distance, rng, feedback,
                label_for_log)
            for pt, fid in centres:
                # Resolve class_value: if class_id is "ALL", look up from
                # the source feature.
                if class_id == "ALL":
                    src_class = next(
                        (f.attribute(class_field)
                         for f in primary_feats + other_feats
                         if f.id() == fid), None)
                else:
                    src_class = class_id
                all_centres.append((pt, src_class, fid))

        if not all_centres:
            raise QgsProcessingException(
                "Sampling produced 0 centres. Check class values, "
                "input feature counts, and N parameters.")

        # Sequential PLOTID after the full plan completes.
        plotid_seq = list(range(1, len(all_centres) + 1))

        # ── Write outputs ──
        outputs = {}
        provenance_meta = {
            "radius_m": int(radius) if method == self.METHOD_CIRCULAR else None,
            "ring_width_m": (int(ring_w)
                             if method == self.METHOD_CIRCULAR else None),
            "sampling_method": method_name,
            "random_seed": seed_int,
        }

        if method == self.METHOD_SIMPLE_POINTS:
            outputs.update(self._write_simple_points(
                out_dir, layer, all_centres, plotid_seq,
                add_provenance, provenance_meta,
                write_gpkg, write_zip,
                primary_val, other_val,
                feedback))
        else:
            outputs.update(self._write_circular(
                out_dir, layer, all_centres, plotid_seq,
                radius, ring_w, gen_point, gen_square, square_side,
                add_provenance, provenance_meta,
                write_gpkg, write_zip,
                primary_val, other_val,
                feedback))

        feedback.pushInfo(
            f"Done. {len(all_centres)} samples written to {out_dir}.")
        return outputs

    # ------------------------------------------------------------------ #
    #  Sampling                                                          #
    # ------------------------------------------------------------------ #
    def _area_weighted_sample(self, feats, n, min_distance, rng,
                              feedback, label):
        """Generate `n` random centres inside the union of `feats`.

        Centres are picked uniformly by AREA (each feature's chance of
        receiving a centre is proportional to its area). Within a
        feature, a point is drawn uniformly in the bbox and rejected if
        it falls outside the polygon. min_distance enforces no two
        centres closer than `min_distance` metres -- if the constraint
        becomes infeasible we warn and return fewer points than asked.
        """
        if not feats:
            return []
        if n <= 0:
            return []
        weights = [f.geometry().area() for f in feats]
        total_area = sum(weights)
        if total_area <= 0:
            raise QgsProcessingException(
                f"Stratum '{label}' has zero total area.")

        cum = []
        running = 0.0
        for w in weights:
            running += w
            cum.append(running)

        out = []  # list of (QgsPointXY, source_fid)
        max_attempts = n * 200
        attempts = 0
        while len(out) < n and attempts < max_attempts:
            attempts += 1
            r = rng.uniform(0.0, total_area)
            # Binary search would be faster; linear is fine at our N.
            i = 0
            for j, c in enumerate(cum):
                if r <= c:
                    i = j
                    break
            feat = feats[i]
            geom = feat.geometry()
            bbox = geom.boundingBox()
            x = rng.uniform(bbox.xMinimum(), bbox.xMaximum())
            y = rng.uniform(bbox.yMinimum(), bbox.yMaximum())
            pt = QgsPointXY(x, y)
            if not geom.intersects(QgsGeometry.fromPointXY(pt)):
                continue
            if min_distance > 0:
                ok = True
                for existing, _ in out:
                    dx = existing.x() - pt.x()
                    dy = existing.y() - pt.y()
                    if (dx * dx + dy * dy) < (min_distance * min_distance):
                        ok = False
                        break
                if not ok:
                    continue
            out.append((pt, feat.id()))

        if len(out) < n:
            feedback.pushWarning(
                f"Stratum '{label}': could only place {len(out)} of "
                f"{n} requested samples (attempted {attempts}). "
                "Try a smaller min_distance or reduce N.")
        return out

    # ------------------------------------------------------------------ #
    #  Output writing                                                    #
    # ------------------------------------------------------------------ #
    def _build_fields(self, with_sample_id, add_provenance):
        f = QgsFields()
        f.append(QgsField("PLOTID", QVariant.Int))
        if with_sample_id:
            f.append(QgsField("SAMPLEID", QVariant.Int))
        if add_provenance:
            f.append(QgsField("class_value", QVariant.Int))
            f.append(QgsField("class_name", QVariant.String, len=64))
            f.append(QgsField("radius_m", QVariant.Int))
            f.append(QgsField("ring_width_m", QVariant.Int))
            f.append(QgsField("sample_type", QVariant.String, len=32))
            f.append(QgsField("sampling_method", QVariant.String, len=32))
            f.append(QgsField("random_seed", QVariant.Int))
            f.append(QgsField("source_id", QVariant.Int))
        return f

    def _class_name(self, class_value, primary_val, other_val):
        if class_value == primary_val:
            return "primary forest"
        if class_value == other_val:
            return "other forest"
        return f"class_{class_value}"

    def _write_layer(self, fields, geometry_type, src_crs, features,
                     out_path, layer_name, feedback):
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = layer_name
        opts.fileEncoding = "UTF-8"
        ctx = QgsProject.instance().transformContext()
        # Build an in-memory provider then save -- simpler than the
        # raw VectorFileWriter writeFeature loop and avoids the
        # signature discrepancy between QGIS minor versions.
        mem = QgsVectorLayer(
            f"{geometry_type}?crs={src_crs.authid()}",
            layer_name, "memory")
        mem_pr = mem.dataProvider()
        mem_pr.addAttributes(list(fields))
        mem.updateFields()
        mem_pr.addFeatures(features)
        mem.updateExtents()
        err = QgsVectorFileWriter.writeAsVectorFormatV3(
            mem, out_path, ctx, opts)
        if err and isinstance(err, tuple) and err[0]:
            raise QgsProcessingException(
                f"Write failed for {out_path}: {err[1]}")
        feedback.pushInfo(
            f"Wrote {len(features)} features -> {out_path}")

    def _write_simple_points(self, out_dir, src_layer, centres, plotids,
                             add_provenance, provenance_meta,
                             write_gpkg, write_zip,
                             primary_val, other_val, feedback):
        """Single layer: ceo_point_plots (point geometry, with PLOTID
        and SAMPLEID == PLOTID; CEO accepts these as Plots and uses
        its default visualisation buffer)."""
        outputs = {}
        fields = self._build_fields(with_sample_id=True,
                                    add_provenance=add_provenance)
        feats = []
        for plotid, (pt, class_value, source_fid) in zip(plotids, centres):
            f = QgsFeature(fields)
            f.setGeometry(QgsGeometry.fromPointXY(pt))
            f.setAttribute("PLOTID", int(plotid))
            f.setAttribute("SAMPLEID", int(plotid))
            if add_provenance:
                f.setAttribute("class_value", int(class_value))
                f.setAttribute("class_name",
                               self._class_name(class_value,
                                                primary_val, other_val))
                # radius_m / ring_width_m don't apply to simple points.
                f.setAttribute("radius_m", None)
                f.setAttribute("ring_width_m", None)
                f.setAttribute("sample_type", "centre_point")
                f.setAttribute("sampling_method",
                               provenance_meta["sampling_method"])
                f.setAttribute("random_seed",
                               provenance_meta["random_seed"])
                f.setAttribute("source_id", int(source_fid))
            feats.append(f)

        gpkg = os.path.join(out_dir, "ceo_point_plots.gpkg")
        if write_gpkg or write_zip:  # always need GPKG to source the zip
            self._write_layer(fields, "Point", src_layer.crs(), feats,
                              gpkg, "ceo_point_plots", feedback)
            outputs["ceo_point_plots"] = gpkg
        if write_zip:
            zip_path = os.path.join(out_dir, "ceo_point_plots.zip")
            _zip_shapefile_outputs(gpkg, zip_path, "ceo_point_plots")
            outputs["ceo_point_plots_zip"] = zip_path
        return outputs

    def _write_circular(self, out_dir, src_layer, centres, plotids,
                        radius, ring_w, gen_point, gen_square,
                        square_side,
                        add_provenance, provenance_meta,
                        write_gpkg, write_zip,
                        primary_val, other_val, feedback):
        """Three potential layers:
          - ceo_plot_boundaries (ring polygon, PLOTID)
          - ceo_samples_points  (point geom, PLOTID + SAMPLEID)
          - ceo_samples_squares (square polygon, PLOTID + SAMPLEID)
        """
        if not (gen_point or gen_square):
            raise QgsProcessingException(
                "Circular method requires at least one sample geometry "
                "type (centre point or 1 ha square).")

        outputs = {}
        segments = _segments_for_circle()

        # --- Plot boundaries (rings) --- per-point construction so we
        # do not bite neighbour rings when plots overlap.
        plot_fields = self._build_fields(with_sample_id=False,
                                         add_provenance=add_provenance)
        ring_feats = []
        for plotid, (pt, class_value, source_fid) in zip(plotids, centres):
            outer = QgsGeometry.fromPointXY(pt).buffer(
                radius + ring_w, segments)
            inner = QgsGeometry.fromPointXY(pt).buffer(radius, segments)
            ring = outer.difference(inner)
            f = QgsFeature(plot_fields)
            f.setGeometry(ring)
            f.setAttribute("PLOTID", int(plotid))
            if add_provenance:
                f.setAttribute("class_value", int(class_value))
                f.setAttribute("class_name",
                               self._class_name(class_value,
                                                primary_val, other_val))
                f.setAttribute("radius_m", int(radius))
                f.setAttribute("ring_width_m", int(round(ring_w)))
                f.setAttribute("sample_type", "ring_boundary")
                f.setAttribute("sampling_method",
                               provenance_meta["sampling_method"])
                f.setAttribute("random_seed",
                               provenance_meta["random_seed"])
                f.setAttribute("source_id", int(source_fid))
            ring_feats.append(f)
        gpkg_rings = os.path.join(out_dir, "ceo_plot_boundaries.gpkg")
        self._write_layer(plot_fields, "Polygon", src_layer.crs(),
                          ring_feats, gpkg_rings,
                          "ceo_plot_boundaries", feedback)
        outputs["ceo_plot_boundaries"] = gpkg_rings
        if write_zip:
            zip_path = os.path.join(out_dir, "ceo_plot_boundaries.zip")
            _zip_shapefile_outputs(gpkg_rings, zip_path,
                                   "ceo_plot_boundaries")
            outputs["ceo_plot_boundaries_zip"] = zip_path

        # --- Sample point layer ---
        if gen_point:
            sample_fields = self._build_fields(
                with_sample_id=True, add_provenance=add_provenance)
            point_feats = []
            for plotid, (pt, class_value, source_fid) in zip(
                    plotids, centres):
                f = QgsFeature(sample_fields)
                f.setGeometry(QgsGeometry.fromPointXY(pt))
                f.setAttribute("PLOTID", int(plotid))
                f.setAttribute("SAMPLEID", int(plotid))
                if add_provenance:
                    f.setAttribute("class_value", int(class_value))
                    f.setAttribute("class_name",
                                   self._class_name(class_value,
                                                    primary_val, other_val))
                    f.setAttribute("radius_m", int(radius))
                    f.setAttribute("ring_width_m", int(round(ring_w)))
                    f.setAttribute("sample_type", "centre_point")
                    f.setAttribute("sampling_method",
                                   provenance_meta["sampling_method"])
                    f.setAttribute("random_seed",
                                   provenance_meta["random_seed"])
                    f.setAttribute("source_id", int(source_fid))
                point_feats.append(f)
            gpkg_points = os.path.join(out_dir, "ceo_samples_points.gpkg")
            self._write_layer(sample_fields, "Point", src_layer.crs(),
                              point_feats, gpkg_points,
                              "ceo_samples_points", feedback)
            outputs["ceo_samples_points"] = gpkg_points
            if write_zip:
                zp = os.path.join(out_dir, "ceo_samples_points.zip")
                _zip_shapefile_outputs(gpkg_points, zp,
                                       "ceo_samples_points")
                outputs["ceo_samples_points_zip"] = zp

        # --- Sample square layer ---
        if gen_square:
            sample_fields = self._build_fields(
                with_sample_id=True, add_provenance=add_provenance)
            square_feats = []
            for plotid, (pt, class_value, source_fid) in zip(
                    plotids, centres):
                f = QgsFeature(sample_fields)
                f.setGeometry(_hectare_square(pt, square_side))
                f.setAttribute("PLOTID", int(plotid))
                f.setAttribute("SAMPLEID", int(plotid))
                if add_provenance:
                    f.setAttribute("class_value", int(class_value))
                    f.setAttribute("class_name",
                                   self._class_name(class_value,
                                                    primary_val, other_val))
                    f.setAttribute("radius_m", int(radius))
                    f.setAttribute("ring_width_m", int(round(ring_w)))
                    f.setAttribute("sample_type", "one_ha_square")
                    f.setAttribute("sampling_method",
                                   provenance_meta["sampling_method"])
                    f.setAttribute("random_seed",
                                   provenance_meta["random_seed"])
                    f.setAttribute("source_id", int(source_fid))
                square_feats.append(f)
            gpkg_sq = os.path.join(out_dir, "ceo_samples_squares.gpkg")
            self._write_layer(sample_fields, "Polygon", src_layer.crs(),
                              square_feats, gpkg_sq,
                              "ceo_samples_squares", feedback)
            outputs["ceo_samples_squares"] = gpkg_sq
            if write_zip:
                zp = os.path.join(out_dir, "ceo_samples_squares.zip")
                _zip_shapefile_outputs(gpkg_sq, zp,
                                       "ceo_samples_squares")
                outputs["ceo_samples_squares_zip"] = zp

        return outputs

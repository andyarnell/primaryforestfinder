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

import datetime
import math
import os
import shutil
import tempfile
import zipfile

from ..utils import PLATFORM_QGIS, generate_layer_name

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

    Caller may delete the source GPKG afterwards (option A "honest
    tickbox" cleanup); we explicitly release the QgsVectorLayer +
    force GC at the end so Windows file locks don't block that cleanup.
    """
    import gc
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
        # V3 added in QGIS 3.20; fall back to V2 (3.10+) or the
        # legacy non-suffixed call (pre-3.10) so this path also works
        # on older QGIS without rebuilding the dock.
        if hasattr(QgsVectorFileWriter, "writeAsVectorFormatV3"):
            err = QgsVectorFileWriter.writeAsVectorFormatV3(
                src, shp_path, ctx, opts)
        elif hasattr(QgsVectorFileWriter, "writeAsVectorFormatV2"):
            err = QgsVectorFileWriter.writeAsVectorFormatV2(
                src, shp_path, ctx, opts)
        else:
            err = QgsVectorFileWriter.writeAsVectorFormat(
                src, shp_path, "UTF-8",
                src.crs(), "ESRI Shapefile")
        # writeAsVectorFormat* returns a (code, message[, ...]) tuple.
        if err and isinstance(err, tuple) and err[0]:
            raise QgsProcessingException(
                f"Shapefile write failed for {layer_name}: {err[1]}")
        # Zip the family. arcname uses the ZIP's filename stem (not the
        # generic layer name) so multi-country / multi-seed unzips into
        # the same folder don't collide. E.g. for a zip called
        # 'BTN_2020_qgis_07a_ceo_validation_plot_boundaries_seed_1_<ts>.zip',
        # internal members become
        # 'BTN_2020_qgis_07a_ceo_validation_plot_boundaries_seed_1_<ts>.shp/.shx/...'
        with zipfile.ZipFile(zip_path, "w",
                             zipfile.ZIP_DEFLATED) as zf:
            base = os.path.splitext(shp_path)[0]
            arc_base = os.path.splitext(os.path.basename(zip_path))[0]
            for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
                p = base + ext
                if os.path.exists(p):
                    zf.write(p, arcname=arc_base + ext)
    # Release the source layer so any caller-driven cleanup of
    # `gpkg_path` (option A) can succeed on Windows.
    del src
    gc.collect()


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
    REPROJECT_TO_WGS84 = "REPROJECT_TO_WGS84"
    ADD_PROVENANCE_FIELDS = "ADD_PROVENANCE_FIELDS"
    ALLOW_EMPTY_STRATUM = "ALLOW_EMPTY_STRATUM"
    # Batch 28.8 item 8: optional context for canonical filenames.
    # When supplied, outputs follow the PFF schema:
    #   <ISO3>_<year>_qgis_<step>_ceo_validation_<role>[_seed_N]_<HHhMMm>.<ext>
    # Both default empty; generate_layer_name drops missing pieces.
    ISO3 = "ISO3"
    YEAR = "YEAR"
    # Batch 29: optional pre-randomised points (e.g. FRA RSS). When
    # supplied, the algorithm reprojects them, spatially joins against
    # the input forest polygons, and draws plot centres from the
    # surviving points instead of from `_area_weighted_sample`.
    EXISTING_POINTS = "EXISTING_POINTS"

    # Domain enum (for SAMPLING_DOMAIN)
    DOMAIN_ALL = 0
    DOMAIN_PRIMARY = 1
    DOMAIN_OTHER = 2
    DOMAIN_LABELS = ["All forest (primary + other forest)",
                     "Primary only",
                     "Other forest only"]

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
        return "8 -- Validation sampling (experimental)"

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
            self.REPROJECT_TO_WGS84,
            "Reproject outputs to WGS84 (EPSG:4326)",
            defaultValue=True))
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
        # Batch 28.8 item 8: optional ISO3 + YEAR for canonical filenames
        # matching the rest of the PFF schema. Both default empty; the
        # generate_layer_name builder drops missing pieces gracefully.
        self.addParameter(QgsProcessingParameterString(
            self.ISO3, "ISO3 country code (optional, for filename prefix)",
            defaultValue="", optional=True))
        self.addParameter(QgsProcessingParameterString(
            self.YEAR, "Year tag (optional, for filename prefix)",
            defaultValue="", optional=True))
        # Batch 29: optional existing points (e.g. FRA RSS). When set,
        # plot centres are drawn from these points (after spatial join)
        # instead of from random-within-polygons sampling.
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.EXISTING_POINTS,
            "Existing pre-randomised points (e.g. FRA RSS) -- "
            "optional. When set, plot centres are drawn from these "
            "instead of randomly within forest polygons.",
            optional=True))

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
        reproject_to_wgs84 = self.parameterAsBool(
            parameters, self.REPROJECT_TO_WGS84, context)
        add_provenance = self.parameterAsBool(
            parameters, self.ADD_PROVENANCE_FIELDS, context)
        allow_empty = self.parameterAsBool(
            parameters, self.ALLOW_EMPTY_STRATUM, context)
        iso3 = (self.parameterAsString(
            parameters, self.ISO3, context) or "").strip()
        year = (self.parameterAsString(
            parameters, self.YEAR, context) or "").strip()
        # Batch 29: optional existing-points layer.
        existing_pts_layer = self.parameterAsVectorLayer(
            parameters, self.EXISTING_POINTS, context)

        # Shared run signature so all outputs of one invocation share
        # the same _<run_tag> tail. Disambiguates multiple same-day runs
        # and groups one bundle visually in the file listing.
        # ISO-8601 basic UTC: YYYYMMDDTHHMMZ. Strict standard (S3,
        # Sentinel, etc.). Sortable + unambiguous + no FS-invalid chars.
        # NOTE: seed value lives in the attribute table (`seed` column);
        # we no longer also encode it in the filename — keeps names
        # shorter and the file listing readable.
        run_tag = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%dT%H%MZ")

        # CEO-aligned naming. CEO has two upload slots: "Plot file" and
        # "Sample file". The symmetric `plot_<shape>` / `sample_<shape>`
        # suffix makes it obvious at a glance which file goes where.
        # Old verbose -> new short:
        #   point_plots     -> plot_points     (CEO plot upload, centres)
        #   plot_boundaries -> plot_rings      (CEO plot upload, rings)
        #   samples_points  -> sample_points   (CEO sample upload, centres)
        #   samples_squares -> sample_squares  (CEO sample upload, squares)
        _ROLE_SHORT = {
            "point_plots": "plot_points",
            "plot_boundaries": "plot_rings",
            "samples_points": "sample_points",
            "samples_squares": "sample_squares",
        }

        def _ceo_filename(role: str, substep: str, ext: str) -> str:
            """Build a canonical CEO-output filename per the PFF schema.

            Result: <ISO3>_<year>_qgis_<substep>_<short_descriptor>_<run_tag>.<ext>

            Seed is no longer in the filename (it's in the attribute
            table). ISO3 / year drop out when empty.
            """
            short = _ROLE_SHORT.get(role, role)
            return generate_layer_name(
                iso3, PLATFORM_QGIS, substep,
                f"{short}_{run_tag}",
                ext=ext, year=year)

        # P1.30 batch 21.1: target output CRS. CEO ingests WGS84, so the
        # default flips outputs to EPSG:4326 even though all sampling +
        # buffering happens in the projected source CRS (so distances
        # remain in metres). User can untick to keep outputs in the
        # source CRS for QGIS-side post-processing.
        if reproject_to_wgs84:
            output_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            feedback.pushInfo(
                "Outputs will be reprojected to WGS84 (EPSG:4326) for "
                "CEO upload.")
        else:
            output_crs = layer.crs()

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
        # Batch 29: when existing-points are supplied, sampling becomes
        # "pick from candidate point pool" instead of "draw inside
        # polygons". The method-name string reflects that for provenance.
        if existing_pts_layer is not None and existing_pts_layer.isValid():
            method_name = (
                "existing_points_stratified_random" if stratified else
                ("existing_points_minimum_distance_random"
                 if min_distance > 0 else "existing_points_random"))
        else:
            method_name = ("stratified_random" if stratified
                           else ("minimum_distance_random"
                                 if min_distance > 0 else "simple_random"))

        if existing_pts_layer is not None and existing_pts_layer.isValid():
            # Branch: sample from existing points after spatial-join.
            all_centres = self._sample_from_existing_points(
                existing_pts_layer, layer, primary_feats, other_feats,
                primary_val, other_val, class_field,
                plan, min_distance, rng, feedback, allow_empty)
        else:
            # Original path: random-within-polygons per stratum.
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
                    # Resolve class_value: if class_id is "ALL", look up
                    # from the source feature.
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
            # Batch 29.1: flag set when plot centres were drawn from
            # an existing-points layer (e.g. FRA RSS) instead of from
            # random-within-polygons sampling. Surfaces in the
            # `from_file` provenance field as "yes" / "no".
            "existing_points_used": (
                existing_pts_layer is not None
                and existing_pts_layer.isValid()),
        }

        if method == self.METHOD_SIMPLE_POINTS:
            outputs.update(self._write_simple_points(
                out_dir, layer, output_crs, all_centres, plotid_seq,
                add_provenance, provenance_meta,
                write_gpkg, write_zip,
                primary_val, other_val,
                _ceo_filename,
                feedback))
        else:
            outputs.update(self._write_circular(
                out_dir, layer, output_crs, all_centres, plotid_seq,
                radius, ring_w, gen_point, gen_square, square_side,
                add_provenance, provenance_meta,
                write_gpkg, write_zip,
                primary_val, other_val,
                _ceo_filename,
                feedback))

        feedback.pushInfo(
            f"Done. {len(all_centres)} samples written to {out_dir}.")
        return outputs

    # ------------------------------------------------------------------ #
    #  Sampling                                                          #
    # ------------------------------------------------------------------ #
    def _sample_from_existing_points(
            self, points_layer, src_layer,
            primary_feats, other_feats,
            primary_val, other_val, class_field,
            plan, min_distance, rng, feedback, allow_empty):
        """Batch 29: draw plot centres from a pre-randomised points
        shapefile (e.g. FRA RSS). Reprojects points to the source-layer
        CRS, spatial-joins against the union of primary + other-forest
        polygons, then picks N (or N per class) candidates without
        replacement, honouring `min_distance` if set.

        Returns the same shape as the random-within-polygons path:
        list of (QgsPointXY, class_value, source_polygon_fid). Caller
        appends to `all_centres`.
        """
        from qgis.core import (
            QgsCoordinateTransform, QgsProject as _QP,
            QgsSpatialIndex,
        )

        # Build candidate pool keyed by class_value.
        # candidates[class_value] = [(QgsPointXY, source_polygon_fid), ...]
        candidates = {primary_val: [], other_val: []}
        all_polys = list(primary_feats) + list(other_feats)
        if not all_polys:
            raise QgsProcessingException(
                "No polygons in input vector — nothing to spatial-join "
                "the existing points against.")

        # Build spatial index over polygons. QgsSpatialIndex.addFeatures
        # consumes a feature list; build features-by-id for retrieval.
        sp_index = QgsSpatialIndex()
        polys_by_id = {}
        for f in all_polys:
            sp_index.addFeature(f)
            polys_by_id[f.id()] = f

        pts_crs = points_layer.crs()
        src_crs = src_layer.crs()
        same_crs = (pts_crs.authid() and pts_crs.authid() == src_crs.authid())
        transform = (None if same_crs
                     else QgsCoordinateTransform(
                         pts_crs, src_crs, _QP.instance()))
        if not same_crs:
            feedback.pushInfo(
                f"Reprojecting existing points {pts_crs.authid()} -> "
                f"{src_crs.authid()} for spatial join...")

        n_in = 0
        n_out = 0
        n_unmatched = 0
        for pf in points_layer.getFeatures():
            n_in += 1
            geom = pf.geometry()
            if geom is None or geom.isEmpty():
                continue
            if transform is not None:
                # Copy then transform (don't mutate the original).
                geom = QgsGeometry(geom)
                try:
                    geom.transform(transform)
                except Exception:
                    n_out += 1
                    continue
            # Single-point: take first vertex; multipart: take centroid.
            try:
                pt_xy = geom.asPoint()
            except Exception:
                ctr = geom.centroid()
                pt_xy = ctr.asPoint() if ctr is not None else None
                if pt_xy is None:
                    continue
            # Spatial index lookup by bbox, then exact intersect test.
            cand_ids = sp_index.intersects(geom.boundingBox())
            matched = False
            for fid in cand_ids:
                poly = polys_by_id.get(fid)
                if poly is None:
                    continue
                if poly.geometry().intersects(geom):
                    cv = poly.attribute(class_field)
                    try:
                        cv = int(cv)
                    except (TypeError, ValueError):
                        continue
                    if cv in candidates:
                        candidates[cv].append((pt_xy, poly.id()))
                        matched = True
                        break
            if not matched:
                n_unmatched += 1

        feedback.pushInfo(
            f"Existing-points spatial join: scanned {n_in} input "
            f"points; {len(candidates[primary_val])} fall in primary, "
            f"{len(candidates[other_val])} fall in other forest; "
            f"{n_unmatched} fall outside any forest polygon.")

        # Pick from each stratum per the plan.
        out = []
        for class_id, n_req, _feats in plan:
            if n_req <= 0:
                continue
            if class_id == "ALL":
                pool = list(candidates[primary_val]) + \
                       list(candidates[other_val])
            else:
                pool = list(candidates.get(class_id, []))

            label = ("primary" if class_id == primary_val else
                     "other" if class_id == other_val else "all")
            if not pool:
                msg = (
                    f"Existing-points stratum '{label}' has no "
                    "candidates after the spatial join.")
                if allow_empty:
                    feedback.pushWarning(msg + " Skipping (allow_empty).")
                    continue
                raise QgsProcessingException(
                    msg + " Set 'Allow empty stratum' to skip with a "
                    "warning instead of aborting.")

            picks = self._pick_without_replacement(
                pool, n_req, min_distance, rng, feedback, label)
            for pt, fid in picks:
                if class_id == "ALL":
                    poly = polys_by_id.get(fid)
                    src_class = (
                        int(poly.attribute(class_field))
                        if poly is not None else None)
                else:
                    src_class = class_id
                out.append((pt, src_class, fid))

        if not out:
            raise QgsProcessingException(
                "Existing-points sampling produced 0 centres. Check "
                "the points file CRS, the input class_field, and "
                "whether any points fall inside the input polygons.")
        return out

    def _pick_without_replacement(
            self, pool, n, min_distance, rng, feedback, label):
        """Pick up to `n` items from `pool` (list of (QgsPointXY, fid))
        without replacement, optionally enforcing a minimum-spacing
        constraint. If `min_distance > 0`, picks are constrained so
        no two are within `min_distance` metres of each other -- if
        that becomes infeasible, returns fewer than `n` with a warning.
        """
        if n <= 0 or not pool:
            return []
        if n >= len(pool):
            n = len(pool)
            if min_distance <= 0:
                # Just take all in random order.
                shuffled = list(pool)
                rng.shuffle(shuffled)
                return shuffled
        # Randomised draw order; reject if too close to a prior pick.
        order = list(range(len(pool)))
        rng.shuffle(order)
        picked = []
        for idx in order:
            pt, fid = pool[idx]
            if min_distance > 0:
                ok = True
                for prev_pt, _ in picked:
                    dx = prev_pt.x() - pt.x()
                    dy = prev_pt.y() - pt.y()
                    if (dx * dx + dy * dy) < (min_distance * min_distance):
                        ok = False
                        break
                if not ok:
                    continue
            picked.append((pt, fid))
            if len(picked) >= n:
                break
        if len(picked) < n:
            feedback.pushWarning(
                f"Existing-points stratum '{label}': could only place "
                f"{len(picked)} of {n} requested (pool size "
                f"{len(pool)}). Min-distance constraint may be too "
                "strict; try a smaller value.")
        return picked

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
    def _build_fields(self, role, with_sample_id, add_provenance,
                      is_circular=False):
        """Field schema per output role (Batch 29.1 redesign).

        role = "plot"             -> PLOTID only (CEO ring boundary)
        role = "sample"           -> PLOTID [+ SAMPLEID] + value
                                     [+ minimal provenance extras]

        Names ≤ 10 chars so they survive Shapefile DBF truncation
        without silent renaming. The previous schema's 32-char
        `sampling_method` field overflowed in existing-points mode
        (`existing_points_stratified_random` = 33 chars) and silently
        rejected every feature; that field is dropped — it's constant
        per run and belongs in the filename + sidecar JSON, not
        repeated on every row. `radius_m` only added when the method
        is circular (it's meaningless for simple point plots which
        have no user-controlled boundary).
        """
        f = QgsFields()
        f.append(QgsField("PLOTID", QVariant.Int))
        if role == "plot":
            # Plot/ring boundary file: minimal. Analyst joins via
            # PLOTID to get value + interpretation results.
            return f
        # Sample-bearing file (sample point, sample square, or the
        # simple-method file that plays both roles).
        if with_sample_id:
            f.append(QgsField("SAMPLEID", QVariant.Int))
        # Always-on class identifier so the analyst sees primary vs
        # other on every sample row (no extra tickbox needed).
        f.append(QgsField("value", QVariant.Int))
        if add_provenance:
            # Human-readable class label paired with `value`.
            f.append(QgsField("value_name", QVariant.String, len=32))
            # Plot method short-code: "simple" or "circle". Length
            # capped to 16 so it can never overflow into the silent-
            # rejection bug that affected the previous schema.
            f.append(QgsField("method", QVariant.String, len=16))
            # Plot radius only meaningful for the circular method.
            if is_circular:
                f.append(QgsField("radius_m", QVariant.Int))
            f.append(QgsField("samp_type", QVariant.String, len=10))
            f.append(QgsField("seed", QVariant.Int))
            # "yes" if the plot centre was reused from an existing
            # points file (e.g. FRA RSS); "no" if randomly placed
            # inside the input polygons. Lets the analyst spot
            # design-based vs design-free plots at a glance.
            f.append(QgsField("from_file", QVariant.String, len=4))
        return f

    def _class_name(self, class_value, primary_val, other_val):
        """Human-readable class label for the `value_name` field."""
        if class_value == primary_val:
            return "primary forest"
        if class_value == other_val:
            return "other forest"
        return f"class_{class_value}"

    def _write_layer(self, fields, geometry_type, src_crs, target_crs,
                     features, out_path, layer_name, feedback):
        """Write *features* (built in *src_crs*) to a GPKG layer in
        *target_crs*. If the two CRSes differ, geometries are
        transformed before write.
        """
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = layer_name
        opts.fileEncoding = "UTF-8"
        ctx = QgsProject.instance().transformContext()

        # If reprojection is needed, transform each feature's geometry
        # before adding it to the in-memory layer (which will be in
        # target_crs). Sampling + buffering ran in src_crs (metres);
        # the transform is purely an output coordinate change.
        same_crs = (src_crs.authid() and
                    src_crs.authid() == target_crs.authid())
        if not same_crs:
            transform = QgsCoordinateTransform(
                src_crs, target_crs, QgsProject.instance())
            transformed = []
            for f in features:
                geom = QgsGeometry(f.geometry())
                try:
                    geom.transform(transform)
                except Exception as e:
                    raise QgsProcessingException(
                        f"Reprojection {src_crs.authid()} -> "
                        f"{target_crs.authid()} failed: {e}")
                new_f = QgsFeature(fields)
                new_f.setGeometry(geom)
                # Preserve attribute values
                for fld in fields:
                    new_f.setAttribute(fld.name(),
                                       f.attribute(fld.name()))
                transformed.append(new_f)
            features = transformed
            feedback.pushDebugInfo(
                f"  reprojected {len(features)} features to "
                f"{target_crs.authid()}")

        mem = QgsVectorLayer(
            f"{geometry_type}?crs={target_crs.authid()}",
            layer_name, "memory")
        mem_pr = mem.dataProvider()
        mem_pr.addAttributes(list(fields))
        mem.updateFields()
        mem_pr.addFeatures(features)
        mem.updateExtents()
        # writeAsVectorFormatV3 was introduced in QGIS 3.20. On 3.10-
        # 3.19 fall back to V2 (3.10+) or the legacy non-suffixed call
        # (pre-3.10). Same write semantics; the V3 signature just
        # accepts the new SaveVectorOptions extras gracefully.
        if hasattr(QgsVectorFileWriter, "writeAsVectorFormatV3"):
            err = QgsVectorFileWriter.writeAsVectorFormatV3(
                mem, out_path, ctx, opts)
        elif hasattr(QgsVectorFileWriter, "writeAsVectorFormatV2"):
            err = QgsVectorFileWriter.writeAsVectorFormatV2(
                mem, out_path, ctx, opts)
            feedback.pushInfo(
                "✔ Fallback OK: writeAsVectorFormatV2 (QGIS < 3.20).")
        else:
            err = QgsVectorFileWriter.writeAsVectorFormat(
                mem, out_path, "UTF-8", target_crs, "GPKG")
            feedback.pushInfo(
                "✔ Fallback OK: legacy writeAsVectorFormat (QGIS pre-3.10).")
        if err and isinstance(err, tuple) and err[0]:
            raise QgsProcessingException(
                f"Write failed for {out_path}: {err[1]}")
        feedback.pushInfo(
            f"Wrote {len(features)} features -> {out_path}")

    def _write_simple_points(self, out_dir, src_layer, output_crs,
                             centres, plotids,
                             add_provenance, provenance_meta,
                             write_gpkg, write_zip,
                             primary_val, other_val,
                             ceo_filename, feedback):
        """Single layer: ceo_validation_point_plots (point geometry,
        with PLOTID and SAMPLEID == PLOTID; CEO accepts these as Plots
        and uses its default visualisation buffer).

        Batch 28.8 item 8: filenames now follow the canonical PFF
        schema via *ceo_filename(role, substep, ext)*; the in-GPKG
        layer name stays terse (`ceo_validation_point_plots`)."""
        outputs = {}
        # Simple-method file plays both Plot AND Sample for CEO -- so
        # uses the sample-role schema (value always; provenance extras
        # when on). is_circular=False -> no radius_m field.
        fields = self._build_fields(role="sample", with_sample_id=True,
                                    add_provenance=add_provenance,
                                    is_circular=False)
        feats = []
        for plotid, (pt, class_value, source_fid) in zip(plotids, centres):
            f = QgsFeature(fields)
            f.setGeometry(QgsGeometry.fromPointXY(pt))
            f.setAttribute("PLOTID", int(plotid))
            f.setAttribute("SAMPLEID", int(plotid))
            f.setAttribute("value", int(class_value))
            if add_provenance:
                f.setAttribute("value_name",
                               self._class_name(class_value,
                                                primary_val,
                                                other_val))
                f.setAttribute("method", "simple")
                f.setAttribute("samp_type", "centre")
                seed_v = provenance_meta.get("random_seed")
                if seed_v is not None:
                    f.setAttribute("seed", int(seed_v))
                f.setAttribute(
                    "from_file",
                    "yes" if provenance_meta.get("existing_points_used")
                    else "no")
            feats.append(f)

        # Batch 28.8 option A: when user wants GPKG, write it to the
        # output folder (final). When user only wants ZIP, write the
        # GPKG to the system temp dir as a transient — keeps `out_dir`
        # honest (only zip lands there) AND sidesteps Windows file-lock
        # races that prevent post-write deletion.
        gpkg_basename = ceo_filename("point_plots", "07a", "gpkg")
        if write_gpkg:
            gpkg = os.path.join(out_dir, gpkg_basename)
        else:
            gpkg = os.path.join(tempfile.gettempdir(), gpkg_basename)
        if write_gpkg or write_zip:  # always need GPKG to source the zip
            self._write_layer(fields, "Point", src_layer.crs(),
                              output_crs, feats, gpkg,
                              "ceo_validation_point_plots", feedback)
            if write_gpkg:
                outputs["point_plots"] = gpkg
        if write_zip:
            zip_path = os.path.join(
                out_dir, ceo_filename("point_plots", "07a", "zip"))
            _zip_shapefile_outputs(
                gpkg, zip_path, "ceo_validation_point_plots")
            outputs["point_plots_zip"] = zip_path
        # Best-effort cleanup of the transient temp GPKG (best when
        # write_zip-only). Failure is harmless: temp dir gets cleaned
        # by the OS eventually.
        if write_zip and not write_gpkg and os.path.exists(gpkg):
            try:
                os.remove(gpkg)
            except OSError:
                pass
        return outputs

    def _write_circular(self, out_dir, src_layer, output_crs, centres,
                        plotids, radius, ring_w, gen_point, gen_square,
                        square_side,
                        add_provenance, provenance_meta,
                        write_gpkg, write_zip,
                        primary_val, other_val,
                        ceo_filename, feedback):
        """Three potential layers:
          - ceo_validation_plot_boundaries (ring polygon, PLOTID) [07a]
          - ceo_validation_samples_points  (point, PLOTID+SAMPLEID) [07b]
          - ceo_validation_samples_squares (square, PLOTID+SAMPLEID) [07c]

        Batch 28.8 item 8: filenames now follow the canonical PFF
        schema via *ceo_filename(role, substep, ext)*; in-GPKG layer
        names stay terse for clean CEO upload references.
        """
        if not (gen_point or gen_square):
            raise QgsProcessingException(
                "Circular method requires at least one sample geometry "
                "type (centre point or 1 ha square).")

        outputs = {}
        segments = _segments_for_circle()

        # --- Plot boundaries (rings) --- per-point construction so we
        # do not bite neighbour rings when plots overlap. Schema:
        # PLOTID-only ("plot" role) -- analyst joins by PLOTID for
        # value + provenance from the sample file.
        plot_fields = self._build_fields(role="plot", with_sample_id=False,
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
            ring_feats.append(f)
        # Batch 28.8 option A: temp gpkg in system temp dir when only
        # ZIP requested — keeps out_dir honest + avoids Windows locks.
        rings_basename = ceo_filename("plot_boundaries", "07a", "gpkg")
        if write_gpkg:
            gpkg_rings = os.path.join(out_dir, rings_basename)
        else:
            gpkg_rings = os.path.join(tempfile.gettempdir(), rings_basename)
        self._write_layer(plot_fields, "Polygon", src_layer.crs(),
                          output_crs, ring_feats, gpkg_rings,
                          "ceo_validation_plot_boundaries", feedback)
        if write_gpkg:
            outputs["plot_boundaries"] = gpkg_rings
        if write_zip:
            zip_path = os.path.join(
                out_dir, ceo_filename("plot_boundaries", "07a", "zip"))
            _zip_shapefile_outputs(
                gpkg_rings, zip_path, "ceo_validation_plot_boundaries")
            outputs["plot_boundaries_zip"] = zip_path
        if write_zip and not write_gpkg and os.path.exists(gpkg_rings):
            try:
                os.remove(gpkg_rings)
            except OSError:
                pass

        # --- Sample point layer ---
        if gen_point:
            sample_fields = self._build_fields(
                role="sample", with_sample_id=True,
                add_provenance=add_provenance, is_circular=True)
            point_feats = []
            for plotid, (pt, class_value, source_fid) in zip(
                    plotids, centres):
                f = QgsFeature(sample_fields)
                f.setGeometry(QgsGeometry.fromPointXY(pt))
                f.setAttribute("PLOTID", int(plotid))
                f.setAttribute("SAMPLEID", int(plotid))
                f.setAttribute("value", int(class_value))
                if add_provenance:
                    f.setAttribute("value_name",
                                   self._class_name(class_value,
                                                    primary_val,
                                                    other_val))
                    f.setAttribute("method", "circle")
                    f.setAttribute("radius_m", int(radius))
                    f.setAttribute("samp_type", "centre")
                    seed_v = provenance_meta.get("random_seed")
                    if seed_v is not None:
                        f.setAttribute("seed", int(seed_v))
                    f.setAttribute(
                        "from_file",
                        "yes" if provenance_meta.get(
                            "existing_points_used") else "no")
                point_feats.append(f)
            pts_basename = ceo_filename("samples_points", "07b", "gpkg")
            if write_gpkg:
                gpkg_points = os.path.join(out_dir, pts_basename)
            else:
                gpkg_points = os.path.join(
                    tempfile.gettempdir(), pts_basename)
            self._write_layer(sample_fields, "Point", src_layer.crs(),
                              output_crs, point_feats, gpkg_points,
                              "ceo_validation_samples_points", feedback)
            if write_gpkg:
                outputs["samples_points"] = gpkg_points
            if write_zip:
                zp = os.path.join(
                    out_dir, ceo_filename("samples_points", "07b", "zip"))
                _zip_shapefile_outputs(
                    gpkg_points, zp, "ceo_validation_samples_points")
                outputs["samples_points_zip"] = zp
            if write_zip and not write_gpkg and os.path.exists(gpkg_points):
                try:
                    os.remove(gpkg_points)
                except OSError:
                    pass

        # --- Sample square layer ---
        if gen_square:
            sample_fields = self._build_fields(
                role="sample", with_sample_id=True,
                add_provenance=add_provenance, is_circular=True)
            square_feats = []
            for plotid, (pt, class_value, source_fid) in zip(
                    plotids, centres):
                f = QgsFeature(sample_fields)
                f.setGeometry(_hectare_square(pt, square_side))
                f.setAttribute("PLOTID", int(plotid))
                f.setAttribute("SAMPLEID", int(plotid))
                f.setAttribute("value", int(class_value))
                if add_provenance:
                    f.setAttribute("value_name",
                                   self._class_name(class_value,
                                                    primary_val,
                                                    other_val))
                    f.setAttribute("method", "circle")
                    f.setAttribute("radius_m", int(radius))
                    f.setAttribute("samp_type", "square")
                    seed_v = provenance_meta.get("random_seed")
                    if seed_v is not None:
                        f.setAttribute("seed", int(seed_v))
                    f.setAttribute(
                        "from_file",
                        "yes" if provenance_meta.get(
                            "existing_points_used") else "no")
                square_feats.append(f)
            sq_basename = ceo_filename("samples_squares", "07c", "gpkg")
            if write_gpkg:
                gpkg_sq = os.path.join(out_dir, sq_basename)
            else:
                gpkg_sq = os.path.join(
                    tempfile.gettempdir(), sq_basename)
            self._write_layer(sample_fields, "Polygon", src_layer.crs(),
                              output_crs, square_feats, gpkg_sq,
                              "ceo_validation_samples_squares", feedback)
            if write_gpkg:
                outputs["samples_squares"] = gpkg_sq
            if write_zip:
                zp = os.path.join(
                    out_dir, ceo_filename("samples_squares", "07c", "zip"))
                _zip_shapefile_outputs(
                    gpkg_sq, zp, "ceo_validation_samples_squares")
                outputs["samples_squares_zip"] = zp
            if write_zip and not write_gpkg and os.path.exists(gpkg_sq):
                try:
                    os.remove(gpkg_sq)
                except OSError:
                    pass

        return outputs

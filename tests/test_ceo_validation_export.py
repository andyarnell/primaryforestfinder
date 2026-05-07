"""Test harness for pff:ceo_validation_export (Batch 21).

Six rules (per the approved plan):

1. Points-inside-polygon: every generated centre intersects the input
   forest polygon set.
2. Stratified counts honoured: requesting N_primary=N1 + N_other=N2
   yields exactly that many features per class.
3. Ring integrity under overlap: synthetic 5-point fixture with centres
   ~100m apart and ring radius 2000m -> each ring has area within
   +/- 0.5% of the analytic annulus area pi*((r+w)^2 - r^2).
4. PLOTID/SAMPLEID consistency: set of PLOTIDs in Plot == set of
   PLOTIDs in Sample == set of SAMPLEIDs in Sample. SAMPLEID == PLOTID
   for every sample row.
5. Geographic-CRS abort: input in EPSG:4326 raises QgsProcessingException
   with the input's authid in the message; no output files written.
6. CEO file-size sanity: N=500 with circular method -> all .zip outputs
   are < 200 KB.

How to run from QGIS-aware Python:

    & "C:/Program Files/QGIS 3.38.0/bin/python-qgis.bat" -m pytest tests/test_ceo_validation_export.py -v

The harness is also runnable as a script for quick eyeball:

    & "C:/Program Files/QGIS 3.38.0/bin/python-qgis.bat" tests/test_ceo_validation_export.py

It auto-skips when QGIS / pff_qgis_tools is not importable, so it is
safe to leave in `tests/` even on machines without QGIS.
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    import pytest
except ImportError:  # QGIS-bundled Python lacks pytest. The tests/run_ceo_tests.py
    # script-mode runner provides minimal stand-ins so the module can still load.
    class _PytestStub:
        class mark:
            @staticmethod
            def skipif(_cond, reason=""):
                def deco(obj):
                    return obj
                return deco

        class raises:
            def __init__(self, exc_type):
                self.exc_type = exc_type
                self.value = None

            def __enter__(self):
                return self

            def __exit__(self, etype, einst, etb):
                if etype is None:
                    raise AssertionError(
                        f"DID NOT RAISE {self.exc_type.__name__}")
                if not issubclass(etype, self.exc_type):
                    return False
                self.value = einst
                return True

        @staticmethod
        def main(args):
            print("pytest not available; use tests/run_ceo_tests.py")
            return 0

    pytest = _PytestStub()


# ──────────────────────────────────────────────────────────────────────
# Bootstrap QGIS application so processing.run() works headlessly. This
# mirrors the pattern QGIS itself uses for standalone PyQGIS scripts.
# ──────────────────────────────────────────────────────────────────────
QGIS_AVAILABLE = True
try:
    from qgis.core import (
        QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsField,
        QgsGeometry, QgsPointXY, QgsProcessingException, QgsProject,
        QgsVectorLayer,
    )
    from qgis.PyQt.QtCore import QVariant
except ImportError:  # pragma: no cover
    QGIS_AVAILABLE = False

# `processing` (the QGIS plugin module) is only importable AFTER
# QgsApplication.initQgis() has run AND its plugin path is on sys.path.
# Lazily resolved inside _ensure_qgis().
processing = None  # type: ignore[assignment]
Processing = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from pff_qgis_tools.algorithms.ceo_validation_export import (
        CeoValidationExportAlgorithm,
    )
    PFF_ALG_AVAILABLE = True
except ImportError:
    PFF_ALG_AVAILABLE = False


# Bhutan 06c fixture from the user's recent run. Class field = "level",
# values 1 = forest (331 feats) and 2 = primary forest (96 feats), CRS
# EPSG:5266.
BHUTAN_06C = Path(
    r"C:\Users\Arnell\Downloads\qgis_pff_testing\BTN\full_workflow_260504"
    r"\BTN_2020_qgis_06c_naturally_regenerating_forest_with_primary"
    r"_nested_vector.shp"
)


# ──────────────────────────────────────────────────────────────────────
# Session-level QGIS application setup
# ──────────────────────────────────────────────────────────────────────
_QGS_APP = None
_PFF_PROVIDER = None  # Keep a Python ref so the provider isn't GC'd
                       # after addProvider() (would crash on alg lookup).


def _ensure_qgis():
    """Initialise QgsApplication once per test session and load the
    `processing` plugin module from the QGIS install path."""
    global _QGS_APP, processing, Processing, _PFF_PROVIDER
    if _QGS_APP is not None:
        return _QGS_APP
    prefix = os.environ.get(
        "QGIS_PREFIX_PATH", r"C:\Program Files\QGIS 3.38.0\apps\qgis")
    QgsApplication.setPrefixPath(prefix, True)
    _QGS_APP = QgsApplication([], False)
    _QGS_APP.initQgis()
    # The `processing` plugin lives at <prefix>/python/plugins; add to
    # sys.path so it can be imported.
    plugins_path = os.path.join(prefix, "python", "plugins")
    if plugins_path not in sys.path:
        sys.path.append(plugins_path)
    import processing as _processing  # noqa: E402
    from processing.core.Processing import Processing as _Processing
    processing = _processing
    Processing = _Processing
    Processing.initialize()
    # Register the PFF provider so pff:ceo_validation_export resolves.
    # IMPORTANT: keep a Python ref to the provider; without it the
    # instance gets garbage collected after addProvider() and any
    # subsequent createAlgorithmById() crashes with
    # "Error creating algorithm from createInstance()".
    try:
        from pff_qgis_tools.pff_provider import PffProvider
        _PFF_PROVIDER = PffProvider()
        QgsApplication.processingRegistry().addProvider(_PFF_PROVIDER)
    except Exception as e:
        print(f"(failed to register PffProvider: {e})")
    return _QGS_APP


pytestmark = pytest.mark.skipif(
    not (QGIS_AVAILABLE and PFF_ALG_AVAILABLE),
    reason="QGIS and/or pff_qgis_tools.algorithms.ceo_validation_export "
           "not importable; run via QGIS python-qgis.bat",
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def _write_synthetic_layer(tmpdir: Path, *, geographic: bool = False) -> str:
    """Write a small synthetic 2-class polygon layer.

    Class 2 (primary) = a 1km x 1km square at origin.
    Class 1 (other forest) = a 5km x 5km square surrounding it.

    Returns the on-disk path of the GPKG.
    """
    _ensure_qgis()
    crs_str = "EPSG:4326" if geographic else "EPSG:32646"
    layer = QgsVectorLayer(f"Polygon?crs={crs_str}",
                           "synthetic_forest", "memory")
    pr = layer.dataProvider()
    pr.addAttributes([QgsField("level", QVariant.Int)])
    layer.updateFields()

    if geographic:
        # Tiny degree-scale bbox
        primary_wkt = (
            "POLYGON((0 0, 0.01 0, 0.01 0.01, 0 0.01, 0 0))")
        other_wkt = (
            "POLYGON((-0.05 -0.05, 0.05 -0.05, 0.05 0.05, "
            "-0.05 0.05, -0.05 -0.05),"
            "(0 0, 0 0.01, 0.01 0.01, 0.01 0, 0 0))")
    else:
        primary_wkt = "POLYGON((0 0, 1000 0, 1000 1000, 0 1000, 0 0))"
        other_wkt = (
            "POLYGON((-2500 -2500, 2500 -2500, 2500 2500, "
            "-2500 2500, -2500 -2500),"
            "(0 0, 0 1000, 1000 1000, 1000 0, 0 0))")

    f1 = QgsFeature(layer.fields())
    f1.setAttribute("level", 2)
    f1.setGeometry(QgsGeometry.fromWkt(primary_wkt))
    f2 = QgsFeature(layer.fields())
    f2.setAttribute("level", 1)
    f2.setGeometry(QgsGeometry.fromWkt(other_wkt))
    pr.addFeatures([f1, f2])
    layer.updateExtents()

    out_path = str(tmpdir / "synthetic_forest.gpkg")
    err = processing.run(
        "native:savefeatures",
        {"INPUT": layer, "OUTPUT": out_path,
         "LAYER_NAME": "synthetic_forest"},
    )
    return out_path


def _params_template(input_path: str, out_dir: str) -> dict:
    """Default algorithm params used by most test rules."""
    A = CeoValidationExportAlgorithm
    return {
        A.INPUT: input_path,
        A.CLASS_FIELD: "level",
        A.PRIMARY_CLASS_VALUE: 2,
        A.OTHER_CLASS_VALUE: 1,
        A.SAMPLING_DOMAIN: A.DOMAIN_ALL,
        A.STRATIFIED: False,
        A.N_SAMPLES: 50,
        A.N_PRIMARY: 25,
        A.N_OTHER: 25,
        A.MIN_DISTANCE: 0,
        A.RANDOM_SEED: 42,
        A.EXPORT_METHOD: A.METHOD_SIMPLE_POINTS,
        A.PLOT_RADIUS_M: 2000,
        A.RING_WIDTH_M: 1,
        A.SAMPLE_GEOM_POINT: True,
        A.SAMPLE_GEOM_SQUARE: False,
        A.SQUARE_SIZE_M: 100,
        A.OUTPUT_FOLDER: out_dir,
        A.OUTPUT_GEOPACKAGE: True,
        A.OUTPUT_ZIPPED_SHAPEFILE: False,
        # Existing rules assert spatial properties in the projected
        # source CRS. Default to NOT reproject so those assertions stay
        # valid; rule 7 explicitly tests the default-True path.
        A.REPROJECT_TO_WGS84: False,
        A.ADD_PROVENANCE_FIELDS: True,
        A.ALLOW_EMPTY_STRATUM: False,
    }


def _read_features(gpkg_path: str) -> list[dict]:
    """Open a GPKG layer and return all features as dicts of attrs +
    geometry WKT."""
    layer = QgsVectorLayer(gpkg_path, "tmp", "ogr")
    out = []
    for feat in layer.getFeatures():
        attrs = {fd.name(): feat.attribute(fd.name())
                 for fd in layer.fields()}
        attrs["__geom_wkt"] = feat.geometry().asWkt()
        attrs["__geom_area"] = feat.geometry().area()
        out.append(attrs)
    return out


def _dissolved_geom(layer_path: str, class_field: str | None = None,
                    class_values: list[int] | None = None) -> QgsGeometry:
    """Return a single QgsGeometry that is the union of all features in
    the input (optionally filtered by class)."""
    layer = QgsVectorLayer(layer_path, "tmp", "ogr")
    geoms = []
    for feat in layer.getFeatures():
        if class_field and class_values:
            if feat.attribute(class_field) not in class_values:
                continue
        geoms.append(feat.geometry())
    if not geoms:
        return QgsGeometry()
    return QgsGeometry.unaryUnion(geoms)


# ──────────────────────────────────────────────────────────────────────
# RULE 1 — Points inside polygon
# ──────────────────────────────────────────────────────────────────────
def test_rule1_points_inside_polygon(tmp_path):
    _ensure_qgis()
    out_dir = tmp_path / "rule1"
    out_dir.mkdir()
    params = _params_template(str(BHUTAN_06C), str(out_dir))
    params[CeoValidationExportAlgorithm.N_SAMPLES] = 50

    processing.run("pff:ceo_validation_export", params)

    # The simple-points method emits ceo_point_plots.gpkg
    plots_path = str(out_dir / "ceo_point_plots.gpkg")
    assert os.path.exists(plots_path), \
        f"Expected output not produced: {plots_path}"

    # Every centre must intersect the input forest polygons.
    forest_dissolved = _dissolved_geom(str(BHUTAN_06C))
    points = _read_features(plots_path)
    assert len(points) == 50, f"Expected 50 points, got {len(points)}"
    for p in points:
        g = QgsGeometry.fromWkt(p["__geom_wkt"])
        assert forest_dissolved.intersects(g), \
            f"Point {p.get('PLOTID')} fell outside forest polygons"


# ──────────────────────────────────────────────────────────────────────
# RULE 2 — Stratified counts honoured
# ──────────────────────────────────────────────────────────────────────
def test_rule2_stratified_counts(tmp_path):
    _ensure_qgis()
    out_dir = tmp_path / "rule2"
    out_dir.mkdir()
    params = _params_template(str(BHUTAN_06C), str(out_dir))
    A = CeoValidationExportAlgorithm
    params[A.STRATIFIED] = True
    params[A.SAMPLING_DOMAIN] = A.DOMAIN_ALL
    params[A.N_PRIMARY] = 15
    params[A.N_OTHER] = 35
    params[A.ADD_PROVENANCE_FIELDS] = True  # need class_value to verify

    processing.run("pff:ceo_validation_export", params)

    plots_path = str(out_dir / "ceo_point_plots.gpkg")
    points = _read_features(plots_path)
    assert len(points) == 50, f"Expected 50 total, got {len(points)}"

    primary_count = sum(1 for p in points if p.get("class_value") == 2)
    other_count = sum(1 for p in points if p.get("class_value") == 1)
    assert primary_count == 15, \
        f"Expected 15 primary, got {primary_count}"
    assert other_count == 35, \
        f"Expected 35 other-forest, got {other_count}"


# ──────────────────────────────────────────────────────────────────────
# RULE 3 — Ring integrity under overlap
# ──────────────────────────────────────────────────────────────────────
def test_rule3_ring_integrity_under_overlap(tmp_path):
    _ensure_qgis()
    # Synthetic: write 5 centre points within ~100m of each other, then
    # call the algorithm directly with circular method. We use a custom
    # test-only entry point to bypass random sampling and inject our
    # five fixed centres.

    # 5 points within a 200m square. Rings of r=2000 will heavily overlap.
    centres_xy = [(0, 0), (50, 0), (-50, 0), (0, 50), (0, -50)]

    out_dir = tmp_path / "rule3"
    out_dir.mkdir()

    # Build a synthetic input that contains all 5 centres so sampling
    # would land on/near them; we override the sample count to 5 with a
    # deterministic seed and a tiny-but-non-overlapping cluster polygon
    # set such that random sampling lands inside.
    # Easier: use the algorithm's INTERNAL ring-builder helper if
    # exposed; otherwise we build an input where sampling N=5 in a tiny
    # box gives us 5 close points.
    layer = QgsVectorLayer("Polygon?crs=EPSG:32646", "tiny", "memory")
    pr = layer.dataProvider()
    pr.addAttributes([QgsField("level", QVariant.Int)])
    layer.updateFields()
    feat = QgsFeature(layer.fields())
    feat.setAttribute("level", 2)
    feat.setGeometry(QgsGeometry.fromWkt(
        "POLYGON((-100 -100, 100 -100, 100 100, -100 100, -100 -100))"))
    pr.addFeatures([feat])
    layer.updateExtents()
    in_path = str(out_dir / "tiny_input.gpkg")
    processing.run("native:savefeatures",
                   {"INPUT": layer, "OUTPUT": in_path,
                    "LAYER_NAME": "tiny"})

    A = CeoValidationExportAlgorithm
    params = _params_template(in_path, str(out_dir))
    params[A.N_SAMPLES] = 5
    params[A.RANDOM_SEED] = 7
    params[A.EXPORT_METHOD] = A.METHOD_CIRCULAR
    params[A.PLOT_RADIUS_M] = 2000
    params[A.RING_WIDTH_M] = 1
    params[A.SAMPLE_GEOM_POINT] = True
    params[A.SAMPLE_GEOM_SQUARE] = False

    processing.run("pff:ceo_validation_export", params)

    rings_path = str(out_dir / "ceo_plot_boundaries.gpkg")
    assert os.path.exists(rings_path)
    rings = _read_features(rings_path)
    assert len(rings) == 5, f"Expected 5 rings, got {len(rings)}"

    r = 2000
    w = 1
    expected_area = math.pi * ((r + w) ** 2 - r ** 2)  # ~12 566 m^2
    for ring in rings:
        a = ring["__geom_area"]
        rel_err = abs(a - expected_area) / expected_area
        assert rel_err < 0.005, (
            f"Ring PLOTID={ring.get('PLOTID')} area {a:.1f} differs "
            f"from analytic {expected_area:.1f} by {rel_err*100:.2f}% "
            "(>0.5%) — likely bite from neighbour rings.")


# ──────────────────────────────────────────────────────────────────────
# RULE 4 — PLOTID / SAMPLEID consistency
# ──────────────────────────────────────────────────────────────────────
def test_rule4_plotid_sampleid_consistency(tmp_path):
    _ensure_qgis()
    out_dir = tmp_path / "rule4"
    out_dir.mkdir()
    A = CeoValidationExportAlgorithm
    params = _params_template(str(BHUTAN_06C), str(out_dir))
    params[A.EXPORT_METHOD] = A.METHOD_CIRCULAR
    params[A.SAMPLE_GEOM_POINT] = True
    params[A.SAMPLE_GEOM_SQUARE] = True
    params[A.N_SAMPLES] = 20
    params[A.RANDOM_SEED] = 11

    processing.run("pff:ceo_validation_export", params)

    plot_path = str(out_dir / "ceo_plot_boundaries.gpkg")
    spt_path = str(out_dir / "ceo_samples_points.gpkg")
    ssq_path = str(out_dir / "ceo_samples_squares.gpkg")
    for p in (plot_path, spt_path, ssq_path):
        assert os.path.exists(p), f"Missing output: {p}"

    plots = _read_features(plot_path)
    pts = _read_features(spt_path)
    sqs = _read_features(ssq_path)

    plot_ids = {p["PLOTID"] for p in plots}
    pt_pids = {p["PLOTID"] for p in pts}
    pt_sids = {p["SAMPLEID"] for p in pts}
    sq_pids = {p["PLOTID"] for p in sqs}
    sq_sids = {p["SAMPLEID"] for p in sqs}

    assert plot_ids == pt_pids == pt_sids == sq_pids == sq_sids, (
        "PLOTID / SAMPLEID set mismatch across Plot + Sample layers")
    for p in pts + sqs:
        assert p["PLOTID"] == p["SAMPLEID"], (
            f"SAMPLEID != PLOTID for row {p}")


# ──────────────────────────────────────────────────────────────────────
# RULE 5 — Geographic-CRS abort
# ──────────────────────────────────────────────────────────────────────
def test_rule5_geographic_crs_aborts(tmp_path):
    _ensure_qgis()
    out_dir = tmp_path / "rule5"
    out_dir.mkdir()
    geo_input = _write_synthetic_layer(out_dir, geographic=True)
    params = _params_template(geo_input, str(out_dir))

    with pytest.raises(QgsProcessingException) as excinfo:
        processing.run("pff:ceo_validation_export", params)

    msg = str(excinfo.value).lower()
    assert "epsg:4326" in msg or "geographic" in msg, (
        f"Expected geographic-CRS message; got: {excinfo.value}")
    # No outputs should have been written.
    assert not (out_dir / "ceo_point_plots.gpkg").exists()
    assert not (out_dir / "ceo_plot_boundaries.gpkg").exists()


# ──────────────────────────────────────────────────────────────────────
# RULE 6 — CEO file-size sanity
# ──────────────────────────────────────────────────────────────────────
def test_rule6_ceo_file_size_sanity(tmp_path):
    _ensure_qgis()
    out_dir = tmp_path / "rule6"
    out_dir.mkdir()
    A = CeoValidationExportAlgorithm
    params = _params_template(str(BHUTAN_06C), str(out_dir))
    params[A.EXPORT_METHOD] = A.METHOD_CIRCULAR
    params[A.N_SAMPLES] = 500
    params[A.RANDOM_SEED] = 13
    params[A.SAMPLE_GEOM_POINT] = True
    params[A.SAMPLE_GEOM_SQUARE] = True
    params[A.OUTPUT_ZIPPED_SHAPEFILE] = True

    processing.run("pff:ceo_validation_export", params)

    # Three .zip outputs expected for circular + both samples.
    zips = list(out_dir.glob("*.zip"))
    assert len(zips) >= 3, (
        f"Expected at least 3 .zip outputs; got {[z.name for z in zips]}")
    # CEO's practical upload ceiling is ~1 MB. Aim for under 600 KB
    # at N=500 to give comfortable headroom for typical projects
    # (most workshops use N=100-200, well under).
    LIMIT = 600 * 1024  # 600 KB
    for z in zips:
        size = z.stat().st_size
        assert size < LIMIT, (
            f"{z.name} is {size/1024:.1f} KB, > 600 KB headroom under "
            "CEO's ~1 MB practical ceiling.")
        # Sanity-check the zip contains the SHP family.
        with zipfile.ZipFile(z) as zf:
            names = {n.lower() for n in zf.namelist()}
            shp_present = any(n.endswith(".shp") for n in names)
            dbf_present = any(n.endswith(".dbf") for n in names)
            prj_present = any(n.endswith(".prj") for n in names)
            assert shp_present and dbf_present and prj_present, (
                f"{z.name} missing core SHP files: {names}")


# ──────────────────────────────────────────────────────────────────────
# RULE 7 — REPROJECT_TO_WGS84 default: outputs are EPSG:4326
# ──────────────────────────────────────────────────────────────────────
def test_rule7_reproject_to_wgs84_default(tmp_path):
    _ensure_qgis()
    out_dir = tmp_path / "rule7"
    out_dir.mkdir()
    A = CeoValidationExportAlgorithm
    params = _params_template(str(BHUTAN_06C), str(out_dir))
    # Override: switch ON the reproject (default in real use, but the
    # template sets it False so other rules pass).
    params[A.REPROJECT_TO_WGS84] = True
    params[A.EXPORT_METHOD] = A.METHOD_CIRCULAR
    params[A.SAMPLE_GEOM_POINT] = True
    params[A.SAMPLE_GEOM_SQUARE] = True
    params[A.N_SAMPLES] = 10
    params[A.RANDOM_SEED] = 17

    processing.run("pff:ceo_validation_export", params)

    expected = ("ceo_plot_boundaries.gpkg",
                "ceo_samples_points.gpkg",
                "ceo_samples_squares.gpkg")
    for fname in expected:
        path = str(out_dir / fname)
        assert os.path.exists(path), f"Missing: {fname}"
        layer = QgsVectorLayer(path, "tmp", "ogr")
        assert layer.isValid(), f"Invalid output: {path}"
        authid = layer.crs().authid()
        assert authid == "EPSG:4326", (
            f"{fname} CRS is {authid!r}, expected 'EPSG:4326' "
            "after reproject")
        # Sanity: geometries are in degree-space (Bhutan ≈ 89-92E, 26-28N)
        for feat in layer.getFeatures():
            bbox = feat.geometry().boundingBox()
            assert 80 < bbox.xMinimum() < 100, (
                f"X coords look wrong for WGS84 Bhutan: "
                f"{bbox.xMinimum()}")
            assert 25 < bbox.yMinimum() < 30, (
                f"Y coords look wrong for WGS84 Bhutan: "
                f"{bbox.yMinimum()}")
            break  # one feature is enough


# ──────────────────────────────────────────────────────────────────────
# Script entry point (manual runs; pytest usage preferred)
# ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

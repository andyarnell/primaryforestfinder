"""Shared helpers used by multiple PFF algorithms."""

import os
import processing
from osgeo import gdal, ogr
from qgis.core import (
    QgsProcessingFeedback,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsCoordinateReferenceSystem,
)


def ensure_dir(path: str) -> str:
    """Create directory if it does not exist and return the path."""
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Canonical PFF output filename builder (Option D, decided 2026-04-26)
# ---------------------------------------------------------------------------

# Stable platform tags. Use these exact strings -- not 'app' / 'plugin'.
PLATFORM_GEE = "gee"
PLATFORM_QGIS = "qgis"

# Stable step prefixes. Production stage of the file (where in the pipeline
# it was made), not the action that saves it. Sortable alphabetically =
# workflow order.
STEP_CONTEXT = "00"          # supplies ISO3 prefix; no files of its own
STEP_TIME_PERIOD = "01"      # supplies year; no files of its own
STEP_FOREST_INPUTS = "02"    # raw forest layers (when user opts to save)
STEP_HUMAN_INFLUENCE = "03"  # raw anthro layers (when user opts to save)
STEP_REFINE = "04"           # final refined rasters, pre-conn, combined
STEP_STATISTICS = "05"       # stats CSV / per-zone shapefile
STEP_VALIDATION = "06"       # vectorised + dissolved CEO outputs


def generate_layer_name(iso3, platform: str, step: str, name: str,
                        ext: str = "tif") -> str:
    """Build a canonical PFF output filename per the Option D schema.

    Format: ``{iso3}_{platform}_{step}_{name}.{ext}``  (ISO3 optional;
    omitted when no country selected).

    Args:
      iso3:     ISO3 country code (e.g. 'KEN'). Pass None / empty to omit.
                Cased uppercase if supplied.
      platform: 'gee' or 'qgis'. Use the PLATFORM_* constants in this
                module.
      step:     '00'-'06' with optional substep letter ('04a', '05b').
                Use the STEP_* constants for the base.
      name:     Snake-case layer name without step prefix or extension
                (e.g. 'primary_forest', 'area_statistics',
                'primary_forest_vector'). The step number already
                encodes the production stage, so no need to repeat
                'results_' / 'refined_' / 'validation_' qualifiers.
      ext:      Extension without leading dot (default 'tif'). Use
                'gpkg' for vectors, 'csv' for stats, 'shp' for
                shapefile-zone outputs, 'json' for metadata sidecars.

    Examples:
      >>> generate_layer_name('KEN', PLATFORM_QGIS, '04a',
      ...                     'primary_forest')
      'KEN_qgis_04a_primary_forest.tif'
      >>> generate_layer_name(None, PLATFORM_QGIS, '06b',
      ...                     'primary_forest_dissolved', ext='gpkg')
      'qgis_06b_primary_forest_dissolved.gpkg'
      >>> generate_layer_name('KEN', PLATFORM_GEE, '05a',
      ...                     'area_statistics', ext='csv')
      'KEN_gee_05a_area_statistics.csv'

    Foundation utility for P1.13 (full filename rename across both
    tools). Existing call sites currently use ad-hoc filenames; future
    work migrates them to call this helper for a single source of
    truth.
    """
    parts = []
    if iso3:
        parts.append(str(iso3).strip().upper())
    if platform not in (PLATFORM_GEE, PLATFORM_QGIS):
        raise ValueError(
            f"platform must be 'gee' or 'qgis' (got {platform!r}). "
            "Use the PLATFORM_GEE / PLATFORM_QGIS constants.")
    parts.append(platform)
    if not step:
        raise ValueError("step is required (e.g. '04a').")
    parts.append(str(step).strip())
    if not name:
        raise ValueError("name is required (e.g. 'primary_forest').")
    parts.append(str(name).strip())
    base = "_".join(parts)
    ext_clean = str(ext).strip().lstrip(".") if ext else ""
    return f"{base}.{ext_clean}" if ext_clean else base


def validate_crs_projected(layer, feedback: QgsProcessingFeedback):
    """Warn (via feedback) if *layer* uses a geographic CRS."""
    crs = layer.crs()
    if crs.isGeographic():
        feedback.reportError(
            f"Layer '{layer.name()}' uses geographic CRS ({crs.authid()}). "
            "Distance calculations require a projected CRS in metres."
        )
        return False
    return True


def get_raster_info(path: str):
    """Return (crs_wkt, geotransform, x_size, y_size) from a raster file."""
    ds = gdal.Open(path, gdal.GA_ReadOnly)
    if ds is None:
        raise FileNotFoundError(f"Cannot open raster: {path}")
    gt = ds.GetGeoTransform()
    crs_wkt = ds.GetProjection()
    x_size = ds.RasterXSize
    y_size = ds.RasterYSize
    ds = None
    return crs_wkt, gt, x_size, y_size


def raster_resolution(path: str) -> float:
    """Return pixel size (assumes square pixels) from a raster file."""
    _, gt, _, _ = get_raster_info(path)
    return abs(gt[1])


def validate_binary_raster(path: str, feedback: QgsProcessingFeedback) -> bool:
    """Check that a raster contains only 0 and 1 values."""
    ds = gdal.Open(path, gdal.GA_ReadOnly)
    if ds is None:
        return False
    band = ds.GetRasterBand(1)
    stats = band.ComputeStatistics(False)
    mn, mx = stats[0], stats[1]
    ds = None
    if mn < 0 or mx > 1:
        feedback.reportError(
            f"Raster '{path}' is not binary (min={mn}, max={mx}). Expected 0/1 only."
        )
        return False
    return True


def run_processing(alg_id: str, params: dict, context=None, feedback=None):
    """Thin wrapper around processing.run that passes context/feedback."""
    return processing.run(alg_id, params, context=context, feedback=feedback)


def reproject_vector(input_path, target_crs_str, output_path, context=None, feedback=None):
    """Reproject a vector layer to *target_crs_str* (e.g. 'EPSG:32717')."""
    return run_processing("native:reprojectlayer", {
        "INPUT": input_path,
        "TARGET_CRS": QgsCoordinateReferenceSystem(target_crs_str),
        "OUTPUT": output_path,
    }, context=context, feedback=feedback)


def reproject_raster(input_path, target_crs_str, output_path,
                     resolution=None, context=None, feedback=None):
    """Reproject a raster layer to *target_crs_str*."""
    params = {
        "INPUT": input_path,
        "TARGET_CRS": QgsCoordinateReferenceSystem(target_crs_str),
        "RESAMPLING": 0,  # nearest neighbour
        "DATA_TYPE": 0,   # use input data type
        "OPTIONS": "COMPRESS=LZW|TILED=YES",
        "OUTPUT": output_path,
    }
    if resolution is not None:
        params["TARGET_RESOLUTION"] = resolution
    return run_processing("gdal:warpreproject", params, context=context, feedback=feedback)


def rasterize_vector(vector_path, reference_raster_path, output_path,
                     burn_value=1, context=None, feedback=None):
    """Burn a vector into a raster grid aligned to *reference_raster_path*."""
    _, gt, x_size, y_size = get_raster_info(reference_raster_path)
    res = abs(gt[1])
    extent = f"{gt[0]},{gt[0] + gt[1] * x_size},{gt[3] + gt[5] * y_size},{gt[3]}"

    return run_processing("gdal:rasterize", {
        "INPUT": vector_path,
        "BURN": burn_value,
        "UNITS": 1,          # georeferenced units
        "WIDTH": res,
        "HEIGHT": res,
        "EXTENT": extent,
        "NODATA": 0,
        "DATA_TYPE": 0,      # Byte
        "INIT": 0,
        "OPTIONS": "COMPRESS=LZW|TILED=YES",
        "OUTPUT": output_path,
    }, context=context, feedback=feedback)


def clip_raster_by_mask(raster_path, mask_path, output_path,
                        context=None, feedback=None):
    """Clip a raster by a vector mask layer, preserving the input grid.

    Tries gdal:warpreproject with CUTLINE (no -tap, preserves grid origin).
    Falls back to gdal:cliprasterbymasklayer if the CUTLINE parameter is
    not supported (older QGIS versions) — this adds -tap which may shift
    the grid by up to one pixel.
    """
    from osgeo import gdal as _gdal
    ds = _gdal.Open(raster_path, _gdal.GA_ReadOnly)
    _gt = ds.GetGeoTransform()
    res_x = abs(_gt[1])
    ds = None

    try:
        return run_processing("gdal:warpreproject", {
            "INPUT": raster_path,
            "TARGET_RESOLUTION": res_x,
            "CROP_TO_CUTLINE": True,
            "CUTLINE": mask_path,
            "NODATA": 0,
            "OPTIONS": "COMPRESS=LZW|TILED=YES",
            "OUTPUT": output_path,
        }, context=context, feedback=feedback)
    except Exception:
        # Fallback for older QGIS versions where CUTLINE param
        # is not available in gdal:warpreproject
        if feedback:
            feedback.pushInfo(
                "Note: falling back to cliprasterbymasklayer "
                "(may shift grid by up to 1 pixel)")
        return run_processing("gdal:cliprasterbymasklayer", {
            "INPUT": raster_path,
            "MASK": mask_path,
            "NODATA": 0,
            "CROP_TO_CUTLINE": True,
            "KEEP_RESOLUTION": True,
            "OUTPUT": output_path,
        }, context=context, feedback=feedback)


def proximity(raster_path, output_path, max_distance=5100,
              context=None, feedback=None):
    """Compute a proximity (distance) raster from non‑zero pixels."""
    return run_processing("gdal:proximity", {
        "INPUT": raster_path,
        "BAND": 1,
        "VALUES": "1",
        "UNITS": 0,          # georeferenced (metres for projected CRS)
        "MAX_DISTANCE": max_distance,
        "NODATA": max_distance + 1,
        "DATA_TYPE": 5,      # Float32
        "OPTIONS": "COMPRESS=LZW|TILED=YES",
        "OUTPUT": output_path,
    }, context=context, feedback=feedback)


def raster_calc_expression(expression: str, layers: dict, output_path: str,
                           reference_path: str, context=None, feedback=None):
    """Evaluate a gdal_calc-style expression.

    *layers* maps single‑letter band references (A, B, …) to file paths.
    """
    params = {
        "EXPRESSION": expression,
        "OUTPUT": output_path,
        "NO_DATA": 0,
        "RTYPE": 0,          # Byte
        "OPTIONS": "",
    }
    # Map input layers A–Z
    for letter, path in layers.items():
        params[f"INPUT_{letter}"] = path
        params[f"BAND_{letter}"] = 1

    return run_processing("gdal:rastercalculator", params,
                          context=context, feedback=feedback)


def sieve_raster(raster_path, output_path, threshold=10,
                 context=None, feedback=None):
    """Remove raster patches smaller than *threshold* pixels."""
    return run_processing("gdal:sieve", {
        "INPUT": raster_path,
        "THRESHOLD": threshold,
        "EIGHT_CONNECTEDNESS": True,
        "OUTPUT": output_path,
    }, context=context, feedback=feedback)

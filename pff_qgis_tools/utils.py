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

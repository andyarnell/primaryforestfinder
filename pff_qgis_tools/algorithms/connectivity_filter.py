"""
PFF Tool 5 – Refine Output
============================
Removes isolated small forest patches using neighbourhood density
filtering.  A circular moving window computes the proportion of forest
pixels in each pixel's neighbourhood.  Pixels below the density threshold
are removed.  The result is masked to the input forest candidate layer.

Three computation backends (DO NOT remove the fallbacks — they exist
for portability, not dead code):

  1. **FFT circular** (``_circular_focal_mean_fft``)
     Uses ``scipy.signal.fftconvolve`` — O(n log n) regardless of kernel
     size.  Fast (~5 min for Ecuador 30m) with exact circular kernel.
     Requires scipy, which ships with QGIS on Windows/OSGeo4W and macOS
     .dmg since at least QGIS 3.16.

  2. **Integral-image circular** (``_circular_focal_mean_integral``)
     Pure numpy — no optional dependencies.  Guaranteed to work on ANY
     QGIS install (numpy is a hard QGIS dependency).  Slower than FFT
     (~45 min for Ecuador 30m) because it loops over the kernel diameter,
     but memory-efficient via slice-based views.  This is the fallback
     when scipy is not installed (e.g. some Linux package-manager QGIS
     builds).

  3. **Square box filter** (``_square_focal_mean_fast``)
     Single integral-image slice — O(1), near-instant.  ~27% shape
     difference at edges vs circle.  Used when the user ticks
     "Fast approximation" or when radius exceeds 5000 m.

The dispatcher ``_circular_focal_mean_fast`` picks (1) or (2) at
runtime based on scipy availability.  ``refine_output`` picks between
circular and square based on the ``fast_approximation`` flag and radius.

Processing is tiled (512-row strips with radius overlap) to keep peak
memory under ~1 GB per tile even for national-scale 30m rasters.

Compatible with QGIS >= 3.28.
"""

import os
import numpy as np
from osgeo import gdal

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterRasterDestination,
)

from ..utils import raster_resolution


class ConnectivityFilterAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    SMOOTH_RADIUS = "SMOOTH_RADIUS"
    DENSITY_THRESHOLD = "DENSITY_THRESHOLD"
    FAST_APPROXIMATION = "FAST_APPROXIMATION"
    OUTPUT = "OUTPUT"

    def name(self):
        return "refine_output"

    def displayName(self):
        return "5 — Refine Output"

    def group(self):
        return "Primary Forest Finder"

    def groupId(self):
        return "pff"

    def shortHelpString(self):
        return (
            "Removes isolated forest patches using neighbourhood density "
            "filtering.\n\n"
            "A circular kernel computes the proportion of forest pixels "
            "around each pixel. Pixels below the density threshold are "
            "removed. For radii above 5000 m a faster square kernel is "
            "used (approximate).\n\n"
            "Defaults:\n"
            "  Neighbourhood radius = 2000 m\n"
            "  Density threshold    = 0.5 (50%)\n\n"
            "Output: primary_forest.tif"
        )

    def createInstance(self):
        return ConnectivityFilterAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT, "Primary forest candidate raster"))
        self.addParameter(QgsProcessingParameterNumber(
            self.SMOOTH_RADIUS, "Neighbourhood radius (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=2000, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterNumber(
            self.DENSITY_THRESHOLD, "Minimum density to keep (0-1)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.5, minValue=0, maxValue=1))
        self.addParameter(QgsProcessingParameterBoolean(
            self.FAST_APPROXIMATION,
            "Fast approximation (square kernel — ~100x faster, ~27% shape difference at edges)",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT, "Primary forest (refined) output"))

    def processAlgorithm(self, parameters, context, feedback):
        input_layer = self.parameterAsRasterLayer(
            parameters, self.INPUT, context)
        radius_m = self.parameterAsDouble(
            parameters, self.SMOOTH_RADIUS, context)
        threshold = self.parameterAsDouble(
            parameters, self.DENSITY_THRESHOLD, context)
        fast = self.parameterAsBool(
            parameters, self.FAST_APPROXIMATION, context)
        out_path = self.parameterAsOutputLayer(
            parameters, self.OUTPUT, context)

        refine_output(
            input_layer.source(), out_path,
            radius_m=radius_m, threshold=threshold,
            fast_approximation=fast,
            feedback=feedback)

        feedback.pushInfo("Refine output complete.")
        return {self.OUTPUT: out_path}



def _circular_focal_mean_fft(arr, radius_px, feedback=None):
    """Compute circular neighbourhood mean via FFT convolution.

    Uses scipy.signal.fftconvolve — O(n log n) regardless of kernel size.
    Much faster than the integral-image loop for large radii while
    maintaining exact circular kernel shape.

    Requires scipy (ships with QGIS on Windows/OSGeo4W).
    """
    from scipy.signal import fftconvolve

    if feedback:
        feedback.pushInfo("Using FFT circular convolution (fast + exact)...")

    # Build normalised circular kernel
    y, x = np.ogrid[-radius_px:radius_px + 1, -radius_px:radius_px + 1]
    kernel = ((x * x + y * y) <= radius_px * radius_px).astype(np.float64)
    kernel /= kernel.sum()

    # FFT convolution (mode='same' returns same shape as input)
    density = fftconvolve(arr.astype(np.float64), kernel, mode='same')

    if feedback:
        feedback.setProgress(80)

    return density


def _circular_focal_mean_integral(arr, radius_px, feedback=None):
    """Compute circular neighbourhood mean using slice-based integral image.

    Fallback for systems without scipy.  Slower (loops over kernel diameter)
    but still memory-efficient via slice views.
    """
    rows, cols = arr.shape
    pad = radius_px + 1
    padded = np.pad(arr.astype(np.float64), pad, mode='constant',
                    constant_values=0)
    integral = padded.cumsum(axis=0).cumsum(axis=1)

    acc = np.zeros((rows, cols), dtype=np.float64)
    n_pixels = 0

    for dy in range(-radius_px, radius_px + 1):
        if feedback and feedback.isCanceled():
            return None
        dx_max = int(np.floor(np.sqrt(max(0, radius_px**2 - dy**2))))
        if dx_max < 0:
            continue

        n_pixels += 2 * dx_max + 1
        r1 = pad + dy - 1
        r2 = pad + dy
        c1 = pad - dx_max
        c2 = pad + dx_max + 1

        acc += (integral[r2:r2 + rows, c2:c2 + cols]
                - integral[r2:r2 + rows, c1:c1 + cols]
                - integral[r1:r1 + rows, c2:c2 + cols]
                + integral[r1:r1 + rows, c1:c1 + cols])

        if feedback:
            progress = int((dy + radius_px + 1) / (2 * radius_px + 1) * 80)
            feedback.setProgress(progress)

    if n_pixels == 0:
        n_pixels = 1
    return acc / n_pixels


# Check scipy availability once at import time
try:
    from scipy.signal import fftconvolve as _fft_check  # noqa: F401
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def _circular_focal_mean_fast(arr, radius_px, feedback=None):
    """Dispatch to FFT (preferred) or integral-image fallback."""
    if _HAS_SCIPY:
        return _circular_focal_mean_fft(arr, radius_px, feedback)
    else:
        if feedback:
            feedback.pushInfo(
                "scipy not available — using slower integral-image method.")
        return _circular_focal_mean_integral(arr, radius_px, feedback)


def _square_focal_mean_fast(arr, radius_px, feedback=None):
    """Compute square neighbourhood mean — uses scipy if available.

    With scipy: ``ndimage.uniform_filter`` — separable C implementation,
    O(1) per pixel, no allocations, extremely fast.
    Without scipy: numpy integral-image fallback.
    """
    side = 2 * radius_px + 1

    if feedback:
        feedback.pushInfo(
            f"Using square kernel (area-corrected, side={side}px)...")

    if _HAS_SCIPY:
        from scipy.ndimage import uniform_filter
        # uniform_filter uses 'reflect' mode by default; 'constant' matches
        # our zero-padding behaviour for edge pixels
        density = uniform_filter(
            arr.astype(np.float64), size=side, mode='constant', cval=0.0)
        if feedback:
            feedback.setProgress(80)
        return density

    # Fallback: numpy integral image
    rows, cols = arr.shape
    pad = radius_px + 1
    padded = np.pad(arr.astype(np.float64), pad, mode='constant',
                    constant_values=0)
    integral = padded.cumsum(axis=0).cumsum(axis=1)

    box_sum = (integral[side:side + rows, side:side + cols]
               - integral[0:rows, side:side + cols]
               - integral[side:side + rows, 0:cols]
               + integral[0:rows, 0:cols])

    if feedback:
        feedback.setProgress(80)

    return box_sum / (side * side)


# Threshold in metres: above this, use square kernel (fast approximate)
_CIRCLE_TO_SQUARE_THRESHOLD_M = 5000

# Target tile height in pixels — kept small to avoid OOM on wide rasters.
# Each tile uses ~3x (tile_h + 2*radius) * width * 8 bytes for float64.
_TARGET_TILE_ROWS = 512


def refine_output(input_path, output_path, radius_m=2000, threshold=0.5,
                  fast_approximation=False, feedback=None):
    """Neighbourhood density filter for removing isolated patches.

    Processes the raster in overlapping row-strips (tiles) to keep memory
    bounded.  Uses circular kernel up to 5000m, square above — unless
    fast_approximation=True which forces square at any radius (~100x faster).
    """
    ds = gdal.Open(input_path, gdal.GA_ReadOnly)
    band = ds.GetRasterBand(1)
    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()
    x_size = ds.RasterXSize
    y_size = ds.RasterYSize

    res = abs(gt[1])
    radius_px = max(1, int(round(radius_m / res)))
    use_square = fast_approximation or (radius_m > _CIRCLE_TO_SQUARE_THRESHOLD_M)

    # Area-correct the square radius so total kernel pixels ≈ circle's.
    # Without this, square has 4/π ≈ 27% more pixels → biases results.
    if use_square:
        radius_px = max(1, int(round(radius_px * 0.886)))

    if feedback:
        mode = "square (area-corrected)" if use_square else "circle (exact)"
        feedback.pushInfo(
            f"Refine output: radius={radius_m}m ({radius_px}px), "
            f"threshold={threshold}, kernel={mode}, "
            f"raster={x_size}x{y_size}")
        feedback.pushInfo(
            "Refine output: density result is masked back to input forest "
            "(matches GEE pff_4.js — pixels outside input forest are excluded)")

    # Determine tiling
    tile_rows = max(_TARGET_TILE_ROWS, 2 * radius_px + 1)
    n_tiles = max(1, (y_size + tile_rows - 1) // tile_rows)
    if n_tiles > 1 and feedback:
        feedback.pushInfo(
            f"Processing in {n_tiles} tiles (tile height={tile_rows}px, "
            f"overlap={radius_px}px)")

    # Create output
    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(output_path, x_size, y_size, 1, gdal.GDT_Byte,
                           options=["COMPRESS=LZW", "TILED=YES"])
    out_ds.SetGeoTransform(gt)
    out_ds.SetProjection(proj)
    out_band = out_ds.GetRasterBand(1)
    out_band.SetNoDataValue(0)

    original_count = 0
    refined_count = 0

    for tile_idx in range(n_tiles):
        if feedback and feedback.isCanceled():
            out_ds = None
            return output_path

        # Compute row range for this tile (with overlap)
        row_start = tile_idx * tile_rows
        row_end = min(row_start + tile_rows, y_size)

        # Expand by radius_px for overlap (clamped to raster bounds)
        read_start = max(0, row_start - radius_px)
        read_end = min(y_size, row_end + radius_px)

        # Read tile with overlap
        tile_arr = band.ReadAsArray(0, read_start, x_size,
                                    read_end - read_start).astype(np.float32)

        # Compute density for this tile
        tile_radius = radius_px
        if use_square:
            density = _square_focal_mean_fast(tile_arr, tile_radius)
        else:
            density = _circular_focal_mean_fast(tile_arr, tile_radius)

        if density is None:
            out_ds = None
            return output_path

        # Extract the non-overlapping core from the density result
        core_top = row_start - read_start
        core_bot = core_top + (row_end - row_start)
        core_density = density[core_top:core_bot, :]
        core_arr = tile_arr[core_top:core_bot, :]

        # Threshold and mask
        refined_tile = ((core_density >= threshold) &
                        (core_arr == 1)).astype(np.uint8)

        original_count += int((core_arr == 1).sum())
        refined_count += int(refined_tile.sum())

        # Write to output
        out_band.WriteArray(refined_tile, 0, row_start)

        if feedback:
            progress = int((tile_idx + 1) / n_tiles * 90)
            feedback.setProgress(progress)

    ds = None
    out_band.FlushCache()
    out_ds = None

    # Report
    removed = original_count - refined_count
    if feedback:
        feedback.pushInfo(
            f"Kept {refined_count:,} of {original_count:,} forest pixels "
            f"({removed:,} removed, "
            f"{100 * removed / max(original_count, 1):.1f}%)")
        feedback.setProgress(95)

    return output_path

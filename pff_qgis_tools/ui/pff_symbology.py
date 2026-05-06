"""Symbology helper for binary PFF output rasters.

PFF outputs binary {0, 1} Byte rasters. QGIS's default single-band gray
renderer stretches 0-255 so 1-on-0 looks black-on-black. This helper
applies a paletted renderer that maps 0 -> transparent and 1 -> a
step-specific colour, so users see the presence pixels at a glance.

Filename suffix drives the colour choice. If the basename doesn't match
a known PFF step, the helper no-ops (keeps the QGIS default), which is
the right call for unrelated rasters or vectors.
"""

import os

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsColorRampShader, QgsPalettedRasterRenderer, QgsRasterLayer,
)


# Filename-suffix -> hex colour for value=1. Suffix matched against the
# basename via "endswith(suffix)" before the extension. Order matters
# only for tie-breaking; entries are mutually exclusive in practice.
_PFF_STEP_COLOURS = (
    ("_02b_forest", "#7fc97f"),                          # light green
    ("_02d_naturally_regenerating_forest", "#41ab5d"),   # mid green
    ("_03c_pre_connectivity_primary_forest", "#7a9c2f"), # olive
    ("_04a_primary_forest", "#1b6e3a"),                  # dark green
    ("_04e_anthropogenic_mask", "#cf3a4a"),              # red
    ("_anthropogenic_mask", "#cf3a4a"),                  # legacy name
)


def _step_colour_for(path: str):
    """Return a QColor for the value=1 class, or None when no match."""
    base = os.path.basename(path or "")
    if not base:
        return None
    stem, _ext = os.path.splitext(base)
    for suffix, hex_code in _PFF_STEP_COLOURS:
        if stem.endswith(suffix):
            return QColor(hex_code)
    return None


def apply_pff_symbology(layer, path: str) -> bool:
    """Apply a binary 0/1 paletted renderer to *layer* based on *path*.

    Returns True when symbology was applied, False when the path didn't
    match a known PFF step (caller should leave the QGIS default in
    place).

    For non-raster layers, returns False without touching the layer.
    """
    if not isinstance(layer, QgsRasterLayer):
        return False
    colour = _step_colour_for(path)
    if colour is None:
        return False

    transparent = QColor(0, 0, 0, 0)
    classes = [
        QgsPalettedRasterRenderer.Class(0, transparent, "Absent"),
        QgsPalettedRasterRenderer.Class(1, colour, "Present"),
    ]
    renderer = QgsPalettedRasterRenderer(
        layer.dataProvider(), 1, classes)
    layer.setRenderer(renderer)
    layer.triggerRepaint()
    return True

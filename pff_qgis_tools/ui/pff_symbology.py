"""Symbology helper for PFF outputs.

For binary {0,1} rasters: paletted renderer (0 -> transparent, 1 -> a
step-specific colour) so values render visibly on the map (QGIS's
default grayscale stretch makes 1-on-0 look black-on-black).

For CEO export vectors (Batch 21): high-contrast styling so plot
boundaries / centre points / 1 ha squares stand out over imagery
without obscuring it.

Filename suffix drives the styling choice. Unknown filenames no-op.
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsColorRampShader, QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol,
    QgsPalettedRasterRenderer, QgsRasterLayer, QgsSingleSymbolRenderer,
    QgsVectorLayer,
)


# Filename-suffix -> hex colour for value=1. Suffix matched against the
# basename via "endswith(suffix)" before the extension. Order matters
# only for tie-breaking; entries are mutually exclusive in practice.
_PFF_STEP_COLOURS = (
    ("_02c_forest", "#7fc97f"),                          # light green
    ("_02e_naturally_regenerating_forest", "#41ab5d"),   # mid green
    ("_03c_pre_refinement_primary_forest", "#7a9c2f"), # olive (new)
    ("_03c_pre_connectivity_primary_forest", "#7a9c2f"), # olive (legacy name; symbology still applies)
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
    """Apply PFF-aware symbology to *layer* based on *path*.

    For raster layers: binary 0/1 paletted renderer (step-keyed colour).
    For CEO-export vector layers: high-contrast plot/sample styling.

    Returns True when styling was applied, False when no match
    (caller leaves the QGIS default).
    """
    if isinstance(layer, QgsRasterLayer):
        return _apply_raster_symbology(layer, path)
    if isinstance(layer, QgsVectorLayer):
        return _apply_ceo_vector_symbology(layer, path)
    return False


def _apply_raster_symbology(layer, path: str) -> bool:
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


def _apply_ceo_vector_symbology(layer, path: str) -> bool:
    """Style CEO export vectors so plot/sample geometry stays
    legible over imagery in CEO QC reviews. Recognises the four
    canonical CEO output basenames; everything else returns False.
    """
    base = os.path.basename(path or "")
    stem, _ext = os.path.splitext(base)

    # Plot ring boundaries — bright orange outline, transparent fill,
    # 1.2 mm line so it shows over imagery without hiding it.
    if stem.startswith("ceo_plot_boundaries"):
        sym = QgsFillSymbol.createSimple({
            "color": "0,0,0,0",
            "outline_color": "#ff7f00",
            "outline_width": "0.6",
            "outline_style": "solid",
        })
        layer.setRenderer(QgsSingleSymbolRenderer(sym))
        layer.triggerRepaint()
        return True

    # Centre-point samples — yellow circle with white stroke.
    if stem.startswith("ceo_samples_points") or stem.startswith(
            "ceo_point_plots"):
        sym = QgsMarkerSymbol.createSimple({
            "name": "circle",
            "color": "#ffd400",
            "outline_color": "#ffffff",
            "outline_width": "0.4",
            "size": "3.0",
        })
        layer.setRenderer(QgsSingleSymbolRenderer(sym))
        layer.triggerRepaint()
        return True

    # 1 ha square samples — yellow outline, transparent fill, dashed.
    if stem.startswith("ceo_samples_squares"):
        sym = QgsFillSymbol.createSimple({
            "color": "0,0,0,0",
            "outline_color": "#ffd400",
            "outline_width": "0.5",
            "outline_style": "dash",
        })
        layer.setRenderer(QgsSingleSymbolRenderer(sym))
        layer.triggerRepaint()
        return True

    return False

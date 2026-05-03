"""Layer-or-file pickers for the PFF dock.

QGIS users almost always already have their inputs loaded as layers in
the Layers panel. The dock should let them pick those layers from a
dropdown (the same affordance the auto-Processing dialog gives) AND
fall back to a file browse for ad-hoc paths. These widgets do both.

- ``LayerOrFilePicker`` — single-type filter (raster OR vector).
- ``SmartLayerPicker`` — accepts either raster or vector; reports which
  type was chosen via a small coloured badge (replaces SmartPicker).
- ``DemSlopeLayerPicker`` — single-raster picker that distinguishes
  DEM vs pre-computed slope (replaces DemSlopePicker).
"""

from qgis.PyQt.QtCore import pyqtSignal, Qt, QUrl
from qgis.PyQt.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QSizePolicy, QToolButton,
    QWidget
)
from qgis.core import (
    QgsMapLayer, QgsMapLayerProxyModel, QgsMimeDataUtils, QgsProject,
    QgsRasterLayer, QgsVectorLayer
)
from qgis.gui import QgsMapLayerComboBox


_BADGE_VECTOR = (
    "<span style='background:#cce5ff; color:#004085; "
    "padding:1px 5px; border-radius:3px;'>vector</span>"
)
_BADGE_RASTER = (
    "<span style='background:#d4edda; color:#155724; "
    "padding:1px 5px; border-radius:3px;'>raster</span>"
)
_BADGE_INVALID = (
    "<span style='background:#f8d7da; color:#721c24; "
    "padding:1px 5px; border-radius:3px;'>invalid</span>"
)


class LayerOrFilePicker(QWidget):
    """Pick from already-loaded layers OR browse a file path.

    The combo lists every loaded layer matching ``layer_filter``. The
    "…" button opens a file dialog using ``file_filter``; picked files
    are loaded into the project so they appear in the combo too.
    Whichever was set most recently wins; ``path()`` returns the
    underlying source path.
    """

    pathChanged = pyqtSignal()

    def __init__(self, *, layer_filter, file_filter,
                 browse_caption="Open file", parent=None):
        super().__init__(parent)
        self._file_filter = file_filter
        self._browse_caption = browse_caption
        self._explicit_path = ""

        # Accept drops of layers from the Layers panel + files from the OS.
        # The drop is non-destructive — we set a reference on the combo;
        # the source layer stays put in the Layers panel.
        self.setAcceptDrops(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._combo = QgsMapLayerComboBox(self)
        self._combo.setFilters(layer_filter)
        self._combo.setAllowEmptyLayer(True)
        # Combo expands; minimum width set so content (layer names) doesn't
        # collapse to nothing when the dock is narrow.
        self._combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._combo.setMinimumWidth(80)
        self._combo.layerChanged.connect(self._on_layer_changed)
        layout.addWidget(self._combo, 1)

        # Browse button has FIXED size policy so it can never be clipped
        # when the dock is narrow — the combo gives way instead.
        self._browse_btn = QToolButton(self)
        self._browse_btn.setText("…")
        self._browse_btn.setToolTip("Browse for file on disk")
        self._browse_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._browse_btn.setMinimumWidth(28)
        self._browse_btn.clicked.connect(self._on_browse)
        layout.addWidget(self._browse_btn, 0)

    # ── Public API ──────────────────────────────────────────────────
    def path(self) -> str:
        if self._explicit_path:
            return self._explicit_path
        layer = self._combo.currentLayer()
        if layer is None:
            return ""
        return layer.source() or ""

    def current_layer(self):
        if self._explicit_path:
            return None
        return self._combo.currentLayer()

    def clear(self):
        self._explicit_path = ""
        self._combo.setLayer(None)

    def set_path(self, path: str):
        """Restore a saved path: prefer matching a loaded layer; else
        treat as explicit file path. Used by Recent runs replay."""
        if not path:
            self.clear()
            return
        # Try to find an already-loaded layer with this source.
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr is not None and lyr.source() == path:
                self._explicit_path = ""
                self._combo.setLayer(lyr)
                self.pathChanged.emit()
                return
        # Not loaded — try to load it into the project.
        loaded = self._load_into_project(path)
        if loaded is not None:
            self._explicit_path = ""
            self._combo.setLayer(loaded)
        else:
            # Couldn't load (file missing, format wrong); record path
            # so user sees what was saved + can fix manually.
            self._explicit_path = path
            self._combo.setLayer(None)
        self.pathChanged.emit()

    # ── Slots ──────────────────────────────────────────────────────
    def _on_layer_changed(self, layer):
        self._explicit_path = ""
        self.pathChanged.emit()

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._browse_caption, "", self._file_filter)
        if not path:
            return
        # Try to load into the project so it shows up in the combo too.
        loaded = self._load_into_project(path)
        if loaded is not None:
            self._combo.setLayer(loaded)
            self._explicit_path = ""
        else:
            self._explicit_path = path
        self.pathChanged.emit()

    def _load_into_project(self, path: str):
        """Try to load ``path`` as the matching layer type.

        Subclasses override to scope the attempt (raster-only, etc.).
        Default tries raster then vector.
        """
        layer = QgsRasterLayer(path, _basename(path))
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer, True)
            return layer
        layer = QgsVectorLayer(path, _basename(path), "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer, True)
            return layer
        return None

    # ── Drag & drop ────────────────────────────────────────────────
    # Accept drops from the QGIS Layers panel (encoded as
    # application/x-vnd.qgis.qgis.uri) and OS file managers (text/uri-list).
    # The drop is non-destructive: we look up an already-loaded layer by
    # source URI and setLayer() it, or load a dropped file. The layer
    # stays in the Layers panel.
    def dragEnterEvent(self, event):
        md = event.mimeData()
        if (QgsMimeDataUtils.isUriList(md)
                or md.hasUrls()
                or md.hasText()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        md = event.mimeData()
        applied = False

        # 1. QGIS layer URIs from the Layers panel.
        if QgsMimeDataUtils.isUriList(md):
            uris = QgsMimeDataUtils.decodeUriList(md)
            for u in uris:
                # Try to find an already-loaded layer by URI source.
                target = None
                for lid, lyr in QgsProject.instance().mapLayers().items():
                    if lyr.source() == u.uri:
                        target = lyr
                        break
                if target is not None and self._combo_accepts(target):
                    self._combo.setLayer(target)
                    self._explicit_path = ""
                    applied = True
                    break
                # Not in project yet — try to load the URI's path.
                if u.uri and self._load_into_project(u.uri):
                    applied = True
                    break

        # 2. OS file drops (file://...).
        if not applied and md.hasUrls():
            for url in md.urls():
                if not url.isLocalFile():
                    continue
                path = url.toLocalFile()
                loaded = self._load_into_project(path)
                if loaded is not None:
                    self._combo.setLayer(loaded)
                    self._explicit_path = ""
                    applied = True
                    break

        if applied:
            self.pathChanged.emit()
            event.acceptProposedAction()
        else:
            event.ignore()

    def _combo_accepts(self, layer) -> bool:
        """Return True if ``layer`` matches the combo's filter."""
        # Approximate via type check (combo's filter mask isn't directly
        # queryable). Subclasses can override to be stricter.
        return layer is not None and layer.isValid()


class SmartLayerPicker(LayerOrFilePicker):
    """Layer-or-file picker that accepts either raster or vector.

    Adds a coloured badge showing which type the current selection is.
    """

    def __init__(self, parent=None):
        super().__init__(
            layer_filter=(QgsMapLayerProxyModel.RasterLayer
                          | QgsMapLayerProxyModel.VectorLayer),
            file_filter=("GIS files (*.tif *.tiff *.img *.vrt "
                         "*.gpkg *.shp *.geojson *.json *.kml *.gml);;"
                         "All files (*.*)"),
            browse_caption="Pick vector or raster file",
            parent=parent,
        )

        self._badge = QLabel(self)
        self._badge.setTextFormat(Qt.RichText)
        self._badge.setMinimumWidth(58)
        self.layout().addWidget(self._badge)

        self.pathChanged.connect(self._refresh_badge)
        self._refresh_badge()

    def vector_path(self) -> str:
        return self.path() if self.kind() == "vector" else ""

    def raster_path(self) -> str:
        return self.path() if self.kind() == "raster" else ""

    def kind(self) -> str:
        path = self.path()
        if not path:
            return ""
        layer = self.current_layer()
        if layer is not None:
            t = layer.type()
            if t == QgsMapLayer.RasterLayer:
                return "raster"
            if t == QgsMapLayer.VectorLayer:
                return "vector"
        # Explicit path -- probe via GDAL.
        try:
            from osgeo import gdal
            ds = gdal.OpenEx(path, gdal.OF_RASTER | gdal.OF_READONLY)
            if ds is not None:
                ds = None
                return "raster"
            ds = gdal.OpenEx(path, gdal.OF_VECTOR | gdal.OF_READONLY)
            if ds is not None:
                ds = None
                return "vector"
        except Exception:
            pass
        return ""

    def _refresh_badge(self):
        k = self.kind()
        if not self.path():
            self._badge.setText("")
        elif k == "raster":
            self._badge.setText(_BADGE_RASTER)
        elif k == "vector":
            self._badge.setText(_BADGE_VECTOR)
        else:
            self._badge.setText(_BADGE_INVALID)

    def _load_into_project(self, path: str):
        # Try raster first then vector (GDAL probe order).
        layer = QgsRasterLayer(path, _basename(path))
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer, True)
            return layer
        layer = QgsVectorLayer(path, _basename(path), "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer, True)
            return layer
        return None


class DemSlopeLayerPicker(QWidget):
    """Single-raster picker with DEM/Slope override dropdown."""

    pathChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._inner = LayerOrFilePicker(
            layer_filter=QgsMapLayerProxyModel.RasterLayer,
            file_filter="Raster (*.tif *.tiff *.img *.vrt);;All (*.*)",
            browse_caption="Pick DEM or Slope raster",
            parent=self,
        )
        self._inner.pathChanged.connect(self._on_inner_path_changed)
        layout.addWidget(self._inner, 1)

        self._kind_combo = QComboBox(self)
        self._kind_combo.addItem("DEM", "dem")
        self._kind_combo.addItem("Slope", "slope")
        self._kind_combo.setMinimumWidth(70)
        self._kind_combo.currentIndexChanged.connect(
            lambda _: self.pathChanged.emit())
        layout.addWidget(self._kind_combo)

    def path(self) -> str:
        return self._inner.path()

    def kind(self) -> str:
        return self._kind_combo.currentData()

    def dem_path(self) -> str:
        return self.path() if self.kind() == "dem" else ""

    def slope_path(self) -> str:
        return self.path() if self.kind() == "slope" else ""

    def clear(self):
        self._inner.clear()
        self._kind_combo.setCurrentIndex(0)

    def set_path(self, path: str, kind: str = "dem"):
        """Restore a saved path. ``kind`` is 'dem' or 'slope' to pick
        the right combo entry; defaults to 'dem'."""
        self._inner.set_path(path)
        self._kind_combo.setCurrentIndex(1 if kind == "slope" else 0)

    def _on_inner_path_changed(self):
        # Heuristic: if the basename contains 'slope' (case-insensitive),
        # default to Slope. User can override via the combo.
        path = self._inner.path()
        if path and "slope" in _basename(path).lower():
            self._kind_combo.setCurrentIndex(1)
        else:
            self._kind_combo.setCurrentIndex(0)
        self.pathChanged.emit()


def _basename(path: str) -> str:
    import os
    return os.path.splitext(os.path.basename(path))[0]

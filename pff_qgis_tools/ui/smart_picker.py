"""Smart file picker widgets for the PFF dock.

The full-workflow algorithm has a few inputs that accept either a vector
or a raster (Roads, Protected areas, DEM/Slope). Rather than expose two
adjacent fields per input (the auto-Processing-dialog approach), the
dock uses a single picker that probes the chosen file with GDAL and
shows a coloured badge indicating what was detected. The picker exposes
``vector_path`` / ``raster_path`` properties that the dock reads when
it builds the parameter dict — only one is non-empty at a time.
"""

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QSizePolicy, QWidget
)
from qgis.gui import QgsFileWidget

try:
    from osgeo import gdal
except ImportError:  # pragma: no cover - GDAL ships with QGIS
    gdal = None


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


def _probe_path(path: str) -> str:
    """Return ``'raster'``, ``'vector'``, or ``''`` if neither.

    Empty/missing paths return ``''``. Tries raster first because GDAL
    will happily open many vector formats as a (degenerate) raster
    otherwise.
    """
    if not path or gdal is None:
        return ""
    try:
        ds = gdal.OpenEx(path, gdal.OF_RASTER | gdal.OF_READONLY)
        if ds is not None:
            ds = None
            return "raster"
    except Exception:
        pass
    try:
        ds = gdal.OpenEx(path, gdal.OF_VECTOR | gdal.OF_READONLY)
        if ds is not None:
            ds = None
            return "vector"
    except Exception:
        pass
    return ""


class SmartPicker(QWidget):
    """File picker that accepts either vector or raster.

    The badge shows the detected type after a file is chosen. If the
    file fails both GDAL probes the badge reads ``invalid`` and the
    picker auto-clears so a bad path doesn't leak into the algorithm.
    """

    pathChanged = pyqtSignal()

    def __init__(self, *, label: str = "", parent: QWidget = None):
        super().__init__(parent)
        self._kind = ""  # 'vector' | 'raster' | ''

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        if label:
            lbl = QLabel(label)
            lbl.setMinimumWidth(140)
            layout.addWidget(lbl)

        self._file_widget = QgsFileWidget(self)
        self._file_widget.setStorageMode(QgsFileWidget.GetFile)
        self._file_widget.setFilter(
            "GIS files (*.tif *.tiff *.img *.vrt *.gpkg *.shp *.geojson "
            "*.json *.kml *.gml);;All files (*.*)"
        )
        self._file_widget.fileChanged.connect(self._on_file_changed)
        self._file_widget.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self._file_widget)

        self._badge = QLabel(self)
        self._badge.setMinimumWidth(60)
        self._badge.setTextFormat(0)  # Qt.RichText = 1
        from qgis.PyQt.QtCore import Qt as _Qt
        self._badge.setTextFormat(_Qt.RichText)
        layout.addWidget(self._badge)

    # ── Public API ──────────────────────────────────────────────────
    def path(self) -> str:
        return self._file_widget.filePath() or ""

    def vector_path(self) -> str:
        return self.path() if self._kind == "vector" else ""

    def raster_path(self) -> str:
        return self.path() if self._kind == "raster" else ""

    def kind(self) -> str:
        """Return ``'vector'``, ``'raster'``, or ``''`` if empty."""
        return self._kind

    def clear(self):
        self._file_widget.setFilePath("")

    def set_path(self, path: str):
        self._file_widget.setFilePath(path or "")

    # ── Signals ─────────────────────────────────────────────────────
    def _on_file_changed(self, path: str):
        if not path:
            self._kind = ""
            self._badge.setText("")
            self.pathChanged.emit()
            return
        kind = _probe_path(path)
        if kind == "raster":
            self._kind = "raster"
            self._badge.setText(_BADGE_RASTER)
        elif kind == "vector":
            self._kind = "vector"
            self._badge.setText(_BADGE_VECTOR)
        else:
            self._kind = ""
            self._badge.setText(_BADGE_INVALID)
            # Auto-clear so a bad path can't reach the algorithm.
            self._file_widget.blockSignals(True)
            self._file_widget.setFilePath("")
            self._file_widget.blockSignals(False)
        self.pathChanged.emit()


class DemSlopePicker(QWidget):
    """Single-raster picker that distinguishes DEM vs pre-computed slope.

    Both inputs are rasters; the user-meaningful distinction is which
    one they handed over. Heuristic: filename containing 'slope'
    (case-insensitive) is treated as Slope, else DEM. A small dropdown
    next to the badge lets the user override the heuristic.
    """

    pathChanged = pyqtSignal()

    def __init__(self, *, label: str = "", parent: QWidget = None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        if label:
            lbl = QLabel(label)
            lbl.setMinimumWidth(140)
            layout.addWidget(lbl)

        self._file_widget = QgsFileWidget(self)
        self._file_widget.setStorageMode(QgsFileWidget.GetFile)
        self._file_widget.setFilter(
            "Raster (*.tif *.tiff *.img *.vrt);;All files (*.*)")
        self._file_widget.fileChanged.connect(self._on_file_changed)
        layout.addWidget(self._file_widget, 1)

        self._kind_combo = QComboBox(self)
        self._kind_combo.addItem("DEM", "dem")
        self._kind_combo.addItem("Slope", "slope")
        self._kind_combo.setMinimumWidth(70)
        self._kind_combo.currentIndexChanged.connect(
            lambda _: self.pathChanged.emit())
        layout.addWidget(self._kind_combo)

    def path(self) -> str:
        return self._file_widget.filePath() or ""

    def kind(self) -> str:
        return self._kind_combo.currentData()

    def dem_path(self) -> str:
        return self.path() if self.kind() == "dem" else ""

    def slope_path(self) -> str:
        return self.path() if self.kind() == "slope" else ""

    def clear(self):
        self._file_widget.setFilePath("")
        self._kind_combo.setCurrentIndex(0)

    def _on_file_changed(self, path: str):
        if path and "slope" in path.lower().rsplit("/", 1)[-1].rsplit(
                "\\", 1)[-1]:
            self._kind_combo.setCurrentIndex(1)
        else:
            self._kind_combo.setCurrentIndex(0)
        self.pathChanged.emit()

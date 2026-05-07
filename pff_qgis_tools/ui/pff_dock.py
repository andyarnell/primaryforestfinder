"""Primary Forest Finder — custom dock widget (GEE-style left panel).

Replaces the auto-generated Processing dialog with a hand-built dock
that mirrors the GEE app's collapsible-section layout. Builds the
parameter dict for ``pff:full_workflow`` and runs the algorithm via
``processing.run(...)``. The Processing-toolbox entry stays available
for batch / model-builder use.

Section structure:
  §1 Study Area
  §2 Tree Cover
  §3 Human Influence (with nested ▸ Buffer Exceptions + ▸ Custom 1/2/3)
  §4 Refine Output
  §5 Area Statistics
  §6 Vectorise Outputs
  §7 Run Options
  [Run Workflow ▶] + log (resizable splitter)

FRA comparison panel + suggested-CRS dropdown are deferred to 20b.
"""

import json
import os

import processing
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel, QTextCursor
from qgis.PyQt.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QTextEdit, QToolButton, QVBoxLayout, QWidget
)
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsMapLayer,
    QgsMapLayerProxyModel, QgsProcessingContext, QgsProcessingFeedback,
    QgsProject, QgsRasterLayer, QgsVectorLayer
)
from qgis.gui import (
    QgsDockWidget, QgsFieldComboBox, QgsFileWidget,
    QgsProjectionSelectionDialog
)

from .collapsible_section import CollapsibleSection
from .layer_picker import (
    DemSlopeLayerPicker, LayerOrFilePicker, SmartLayerPicker
)
from .pff_symbology import apply_pff_symbology
from ..algorithms.full_workflow import FullWorkflowAlgorithm as FW
from ..defaults import (
    AGRICULTURE_DIST as D_AGRI,
    AOI_BUFFER as D_AOI_BUFFER,
    BUILTUP_DIST as D_BUILTUP_SM,
    BUILTUP_LARGE_DIST as D_BUILTUP_LG,
    DENSITY_THRESHOLD as D_DENSITY,
    MAX_DISTANCE as D_MAX_DIST,
    ROADS_DIST as D_ROADS,
    SLOPE_THRESHOLD as D_SLOPE,
    SMOOTH_RADIUS as D_SMOOTH,
)


# Tree-cover input-category options — copied verbatim from the GEE app
# (pff_4.js:3670-3673) so screenshots and workshop materials line up
# 1:1 across both tools. The dropdown drives:
#   1. visibility of OLWTC + Planted-forest sub-controls
#   2. the EXCLUDE_AGRICULTURE_FROM_FOREST + EXCLUDE_PLANTATIONS booleans
INPUT_CATEGORY_TREECOVER = (
    "Tree cover (includes oil palm, orchards, agroforestry etc)")
INPUT_CATEGORY_FOREST = (
    "Forest (excludes other land with tree cover e.g. oil palm, "
    "orchards, agroforestry etc)")
INPUT_CATEGORY_NRF = (
    "Naturally regenerating forest (also excludes planted forest)")
INPUT_CATEGORY_PRIMARY = (
    "Primary forest (for comparison/further analysis)")


# Path for the dock-local recent-runs history file. Lives under the
# QGIS profile dir so it persists across sessions but is per-profile.
def _history_path() -> str:
    base = QgsApplication.qgisSettingsDirPath()
    pff_dir = os.path.join(base, "PFF")
    os.makedirs(pff_dir, exist_ok=True)
    return os.path.join(pff_dir, "run_history.json")


_HISTORY_MAX_ENTRIES = 50

INPUT_CATEGORY_ITEMS = [
    INPUT_CATEGORY_TREECOVER,
    INPUT_CATEGORY_FOREST,
    INPUT_CATEGORY_NRF,
    INPUT_CATEGORY_PRIMARY,
]


class _DockFeedback(QgsProcessingFeedback):
    """Pipes algorithm log lines into the dock's log QTextEdit."""

    def __init__(self, log_widget: QTextEdit, progress_bar: QProgressBar):
        super().__init__()
        self._log = log_widget
        self._pb = progress_bar
        self.progressChanged.connect(self._on_progress)

    def _append(self, html: str):
        self._log.moveCursor(QTextCursor.End)
        self._log.insertHtml(html + "<br>")
        self._log.moveCursor(QTextCursor.End)
        # processing.run() blocks the GUI thread while the algorithm
        # runs, so without a manual processEvents() pump the log
        # appears empty until the run finishes. Pump after every line
        # so users see progress in real time.
        QApplication.processEvents()

    def pushInfo(self, info: str):
        self._append(f"<span>{_html_escape(info)}</span>")

    def pushDebugInfo(self, info: str):
        self._append(
            f"<span style='color:#888;'>{_html_escape(info)}</span>")

    def pushWarning(self, info: str):
        self._append(
            f"<span style='color:#b8860b;'>⚠ {_html_escape(info)}</span>")

    def reportError(self, error: str, fatalError: bool = False):
        self._append(
            f"<span style='color:#a00;'>✖ {_html_escape(error)}</span>")

    def _on_progress(self, value: float):
        self._pb.setValue(int(value))
        QApplication.processEvents()


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))


def _form() -> QFormLayout:
    """Build a QFormLayout with consistent spacing + tight label column.

    P1.30 batch 21: WrapLongRows -- when the dock is narrower than
    label+field can comfortably fit on one line, the field drops to the
    next line. Stops a wide field column (e.g. forced wide by a
    LayerOrFilePicker that needs to show its browse button) from
    pushing the dock's minimum width unnecessarily wide.
    """
    f = QFormLayout()
    f.setContentsMargins(0, 0, 0, 0)
    f.setSpacing(6)
    f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    f.setRowWrapPolicy(QFormLayout.WrapLongRows)
    return f


def _raster_picker(caption: str) -> "LayerOrFilePicker":
    """Helper for raster-only picker rows."""
    return LayerOrFilePicker(
        layer_filter=QgsMapLayerProxyModel.RasterLayer,
        file_filter="Raster (*.tif *.tiff *.img *.vrt);;All (*.*)",
        browse_caption=caption,
    )


def _serialise_params(params: dict) -> dict:
    """Convert a params dict to a JSON-serialisable form.

    QGIS objects like QgsCoordinateReferenceSystem need flattening to
    strings. Path-typed values pass through as-is. Booleans / numbers /
    strings / None are already JSON-friendly.
    """
    out = {}
    for k, v in params.items():
        if isinstance(v, QgsCoordinateReferenceSystem):
            out[k] = v.authid() or v.toWkt()
        else:
            out[k] = v
    return out


def _spin(default=0.0, mn=0.0, mx=10000.0, decimals=1, suffix=" m"):
    sb = QDoubleSpinBox()
    sb.setRange(mn, mx)
    sb.setDecimals(decimals)
    sb.setValue(default)
    if suffix:
        sb.setSuffix(suffix)
    sb.setMinimumWidth(100)
    return sb


def _row(*widgets, spacing=6):
    """Pack widgets into a horizontal layout. Returns the layout."""
    h = QHBoxLayout()
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(spacing)
    for w in widgets:
        if isinstance(w, int):
            h.addSpacing(w)
        elif isinstance(w, str):
            lbl = QLabel(w)
            h.addWidget(lbl)
        else:
            h.addWidget(w)
    return h


class PffDockWidget(QgsDockWidget):
    """Primary Forest Finder collapsible dock."""

    OBJECT_NAME = "PffDockWidget"

    def __init__(self, iface, parent=None):
        super().__init__("Primary Forest Finder", parent)
        self.setObjectName(self.OBJECT_NAME)
        self._iface = iface

        outer = QWidget(self)
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(6, 6, 6, 6)
        outer_layout.setSpacing(2)

        # P1.30 batch 20i: plugin version banner at the top so the
        # user can confirm at a glance which version they have loaded.
        # Pulls from FullWorkflowAlgorithm.PFF_VERSION (single source).
        version_label = QLabel(
            f"<b>Primary Forest Finder</b> "
            f"<span style='color:#666;'>v{FW.PFF_VERSION}</span>")
        version_label.setStyleSheet("padding: 2px 0;")
        outer_layout.addWidget(version_label)

        # Splitter so the user can drag the divider to give sections
        # vs log more or less space. Both panes can be dragged freely;
        # min heights enforced on the panes themselves.
        self._splitter = QSplitter(Qt.Vertical, outer)
        self._splitter.setChildrenCollapsible(True)
        self._splitter.setHandleWidth(6)

        # Scrollable sections area on top.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setMinimumHeight(120)

        body = QWidget(scroll)
        self._sections_layout = QVBoxLayout(body)
        self._sections_layout.setContentsMargins(0, 0, 0, 0)
        self._sections_layout.setSpacing(2)

        # Build each section. Each helper sets self._<widget> attrs that
        # _collect_params() reads at run time. Sections 1-4 numbering
        # matches the GEE app left panel (Time Period, Tree Cover,
        # Human Influence, Refine Output). Study Area is §0 because
        # it's QGIS-only project setup, sitting outside that ladder.
        self._build_section_0_study_area()
        self._build_section_1_time_period()
        self._build_section_2_tree_cover()
        self._build_section_3_human_influence()
        self._build_section_4_refine_output()
        # P1.30 batch 23: §6 Outputs is the new parent that consolidates
        # the former §6 Vectorise / §7 Run Options / §8 CEO Export +
        # Output folder (moved from §0) + Save list (moved from §7) +
        # Add-to-map toggle. Stats keeps its §5 slot.
        self._build_section_5_area_statistics()
        self._build_section_6_outputs()
        self._sections_layout.addStretch(1)

        # P1.30 batch 20i: accordion -- only one top-level section
        # expanded at a time. Collect refs to all top-level
        # CollapsibleSections that ended up in the sections layout
        # and wire their toggled() signal to a dispatcher.
        self._top_level_sections = []
        self._in_accordion_dispatch = False
        for i in range(self._sections_layout.count()):
            w = self._sections_layout.itemAt(i).widget()
            if isinstance(w, CollapsibleSection):
                self._top_level_sections.append(w)
                w.toggled.connect(
                    lambda expanded, sec=w:
                        self._on_section_toggled(sec, expanded))

        scroll.setWidget(body)
        self._splitter.addWidget(scroll)

        # Bottom pane: QTextEdit directly in the splitter (no extra
        # collapsible wrapper -- the splitter handle is the natural
        # affordance for resize and a CollapsibleSection wrapper here
        # fights the splitter's resize, so the user can't actually
        # grow the log content even though the pane resizes).
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(0)  # so the splitter can collapse
        self._splitter.addWidget(self._log)

        # Even stretch on resize; both panes share new space.
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([800, 100])
        outer_layout.addWidget(self._splitter, 1)

        # Run controls: button + progress + recent runs dropdown.
        # Single state-machine button: idle => "Run Workflow ▶";
        # running => "Cancel ✖". Click during run prompts confirmation.
        self._is_running = False
        self._active_feedback = None
        self._active_history_index = None  # index into the history file
        run_row = QHBoxLayout()
        run_row.setContentsMargins(0, 0, 0, 0)
        self._run_btn = QPushButton("Run Workflow ▶")
        self._run_btn.setMinimumHeight(32)
        self._run_btn.clicked.connect(self._on_run_or_cancel_clicked)
        run_row.addWidget(self._run_btn, 1)

        self._recent_combo = QComboBox()
        self._recent_combo.setMinimumWidth(160)
        self._recent_combo.setToolTip(
            "Recent runs — pick one to repopulate the dock with its "
            "saved parameters")
        self._recent_combo.activated.connect(self._on_recent_picked)
        run_row.addWidget(self._recent_combo, 0)
        outer_layout.addLayout(run_row)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        outer_layout.addWidget(self._progress)

        self._refresh_recent_combo()

        self.setWidget(outer)

    # ────────────────────────────────────────────────────────────────
    # Section builders
    # ────────────────────────────────────────────────────────────────
    def _build_section_0_study_area(self):
        sec = CollapsibleSection("0. Study Area", expanded=True)
        form = _form()

        self._aoi_picker = LayerOrFilePicker(
            layer_filter=QgsMapLayerProxyModel.VectorLayer,
            file_filter="Vector (*.gpkg *.shp *.geojson *.kml *.gml);;"
                        "All (*.*)",
            browse_caption="Pick AOI vector file")
        self._aoi_picker.pathChanged.connect(self._on_aoi_or_iso3_changed)
        form.addRow("AOI:", self._aoi_picker)

        self._iso3_edit = QLineEdit()
        self._iso3_edit.setMaxLength(8)
        self._iso3_edit.setPlaceholderText("e.g. KEN, BTN, BRA")
        self._iso3_edit.editingFinished.connect(self._on_aoi_or_iso3_changed)
        self._iso3_edit.textChanged.connect(self._refresh_prefix_preview)
        form.addRow("ISO3:", self._iso3_edit)

        # P1.30 batch 23: Output folder moved to §6 Outputs (alongside
        # Save list + Vectorise + Validation sampling). Tip below.
        _output_tip = QLabel(
            "<i>Output folder is now in §6 Outputs.</i>")
        _output_tip.setStyleSheet("color:#888;")
        _output_tip.setMinimumWidth(0)
        _output_tip.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        form.addRow("", _output_tip)

        # P1.30 batch 20j: live preview of the output filename prefix.
        # Built from ISO3 + year only -- AOI layer name no longer
        # contributes (was the source of noisy mechanical-named
        # filenames in 20c-20i). For sub-national runs, distinguish via
        # the output folder name instead.
        self._prefix_preview = QLabel("Prefix: —")
        self._prefix_preview.setToolTip(
            "Live preview of the output filename. Built from "
            "ISO3 + year. For sub-national runs, distinguish by the "
            "output folder name (full control of disambiguation).")
        self._prefix_preview.setStyleSheet("color:#666; font-style:italic;")
        form.addRow("", self._prefix_preview)

        # P1.30 batch 20i: single CRS picker replacing the previous
        # Suggested-CRS dropdown + Manual CRS + EPSG fields. Items are
        # grouped under disabled headers ("AOI-based suggestions",
        # "Recent", "Other"). The "Other" group has actions for
        # typing an EPSG code or browsing the full QGIS CRS list.
        # No default selection -- user must explicitly pick.
        crs_row = QHBoxLayout()
        crs_row.setContentsMargins(0, 0, 0, 0)
        crs_row.setSpacing(4)
        self._crs_combo = QComboBox()
        self._crs_combo.setToolTip(
            "Pick a CRS. Top entries are AOI-based suggestions from "
            "pyproj. 'Recent' lists CRSes used in past runs. 'Other' "
            "has actions for typing an EPSG code or browsing the "
            "full QGIS CRS list. No silent default -- you must pick.")
        self._crs_combo.activated.connect(self._on_crs_combo_picked)
        crs_row.addWidget(self._crs_combo, 1)
        # Quick-browse button: shorthand for the "Browse all CRSes" action.
        self._crs_browse_btn = QToolButton()
        self._crs_browse_btn.setText("…")
        self._crs_browse_btn.setToolTip(
            "Browse the full QGIS CRS list (same as 'Other > "
            "Browse all CRSes' in the dropdown)")
        self._crs_browse_btn.clicked.connect(self._on_crs_browse_clicked)
        crs_row.addWidget(self._crs_browse_btn)
        form.addRow("Target CRS:", crs_row)

        # Internal state: the chosen CRS as a QgsCoordinateReferenceSystem
        # (None until user picks). Drives _collect_params -- written to
        # both TARGET_CRS and TARGET_CRS_EPSG so the algorithm picks it
        # up regardless of which path it follows.
        self._chosen_crs = None  # type: ignore[assignment]
        self._chosen_crs_label = ""
        self._rebuild_crs_combo()

        sec.set_content_layout(form)

        # ── Advanced (collapsed) — AOI buffer only now ──
        adv = CollapsibleSection(
            "Advanced (AOI buffer)",
            expanded=False, indent_px=8, header_bold=False)
        adv_form = _form()

        self._aoi_buffer = _spin(default=D_AOI_BUFFER, mn=0.0, mx=100000.0)
        adv_form.addRow("AOI buffer:", self._aoi_buffer)

        adv.set_content_layout(adv_form)
        sec._content_outer_layout.addWidget(adv)

        self._sections_layout.addWidget(sec)

    def _on_aoi_or_iso3_changed(self, *_):
        """AOI path or ISO3 changed -- refresh prefix preview AND
        rebuild the CRS combo so suggestions track the new inputs."""
        self._refresh_prefix_preview()
        self._rebuild_crs_combo()

    # ────────────────────────────────────────────────────────────────
    # P1.30 batch 20i: CRS picker (single combobox + browse button)
    # ────────────────────────────────────────────────────────────────
    # Item UserRole sentinels — distinguish action items from real picks.
    _CRS_ROLE_HEADER = "header"
    _CRS_ROLE_NONE = "none"
    _CRS_ROLE_BROWSE = "browse"
    _CRS_ROLE_EPSG_INPUT = "epsg_input"

    def _rebuild_crs_combo(self):
        """Populate the CRS combobox with grouped sources.

        Three groups under disabled headers:
          - AOI-based suggestions (from utils_crs_suggest.suggest_crses)
          - Recent (last 10 unique CRSes from run_history.json)
          - Other (Type EPSG code…, Browse all CRSes…)

        Section headers are non-selectable. Selectable items carry an
        EPSG integer (for picks) or one of the role sentinels (for
        actions) in their UserRole data.

        If nothing is currently chosen AND there are no AOI/ISO3 inputs
        yet, the combo shows a single placeholder telling the user to
        provide AOI/ISO3 or pick manually.
        """
        try:
            from ..utils_crs_suggest import suggest_crses
        except ImportError:
            suggest_crses = None  # graceful when pyproj unavailable

        aoi_path = self._aoi_picker.path() or None
        iso3 = (self._iso3_edit.text().strip() or None)

        suggestions = []
        if suggest_crses is not None and (aoi_path or iso3):
            try:
                suggestions = suggest_crses(
                    aoi_path=aoi_path, iso3=iso3, max_results=5)
            except Exception:
                suggestions = []

        recents = self._recent_target_crses(n=10)

        model = QStandardItemModel(self._crs_combo)

        def _add_header(text):
            item = QStandardItem(f"── {text} ──")
            item.setData(self._CRS_ROLE_HEADER, Qt.UserRole)
            item.setSelectable(False)
            item.setEnabled(False)
            model.appendRow(item)

        def _add_action(text, role):
            item = QStandardItem(text)
            item.setData(role, Qt.UserRole)
            model.appendRow(item)

        def _add_epsg(epsg, label):
            item = QStandardItem(label)
            item.setData(int(epsg), Qt.UserRole)
            model.appendRow(item)

        # Track whether the chosen CRS appears in any group so we can
        # set the combo's currentIndex to it after population.
        chosen_idx = -1

        # If no AOI/ISO3 AND no recent runs AND no chosen CRS yet,
        # show a single placeholder + the Other actions only.
        has_anything = (
            bool(suggestions) or bool(recents) or self._chosen_crs is not None)

        if not has_anything:
            placeholder = QStandardItem(
                "(no CRS selected — set AOI or ISO3, or type/browse)")
            placeholder.setData(self._CRS_ROLE_NONE, Qt.UserRole)
            placeholder.setSelectable(False)
            placeholder.setEnabled(False)
            model.appendRow(placeholder)
        else:
            # If the user has already chosen a CRS, show it as the
            # current entry at the top so the combo reflects state.
            if self._chosen_crs is not None:
                _add_header("Current selection")
                _add_epsg(
                    self._chosen_crs_epsg() or 0,
                    self._chosen_crs_label or self._format_crs_label(
                        self._chosen_crs))
                chosen_idx = model.rowCount() - 1

            if suggestions:
                _add_header("AOI-based suggestions")
                for code, name, reason in suggestions:
                    label = f"EPSG:{code} — {name}"
                    if reason:
                        label += f"  [{reason}]"
                    _add_epsg(code, label)

            if recents:
                _add_header("Recent")
                for code, label in recents:
                    _add_epsg(code, label)

        _add_header("Other")
        _add_action("Type EPSG code…", self._CRS_ROLE_EPSG_INPUT)
        _add_action("Browse all CRSes (QGIS picker)…", self._CRS_ROLE_BROWSE)

        self._crs_combo.blockSignals(True)
        self._crs_combo.setModel(model)
        if chosen_idx >= 0:
            self._crs_combo.setCurrentIndex(chosen_idx)
        else:
            # Find first selectable row to land on.
            for r in range(model.rowCount()):
                if model.item(r).isSelectable():
                    self._crs_combo.setCurrentIndex(r)
                    break
        self._crs_combo.blockSignals(False)

    def _chosen_crs_epsg(self):
        """Return the integer EPSG code of the currently chosen CRS, or None."""
        if self._chosen_crs is None:
            return None
        authid = self._chosen_crs.authid() or ""
        if authid.startswith("EPSG:"):
            try:
                return int(authid.split(":", 1)[1])
            except ValueError:
                return None
        return None

    def _format_crs_label(self, crs):
        """Build a human-readable label for a QgsCoordinateReferenceSystem."""
        try:
            authid = crs.authid() or ""
            description = crs.description() or ""
            if authid and description:
                return f"{authid} — {description}"
            return authid or description or "(custom CRS)"
        except Exception:
            return "(custom CRS)"

    def _set_chosen_crs_from_epsg(self, epsg: int):
        """Set self._chosen_crs from an EPSG integer; refresh combo state."""
        crs = QgsCoordinateReferenceSystem(f"EPSG:{int(epsg)}")
        if not crs.isValid():
            QMessageBox.warning(
                self, "Primary Forest Finder",
                f"EPSG:{epsg} is not a valid CRS code.")
            return
        self._chosen_crs = crs
        self._chosen_crs_label = self._format_crs_label(crs)
        self._rebuild_crs_combo()

    def _set_chosen_crs(self, crs):
        """Set self._chosen_crs from a QgsCoordinateReferenceSystem."""
        if crs is None or not crs.isValid():
            return
        self._chosen_crs = crs
        self._chosen_crs_label = self._format_crs_label(crs)
        self._rebuild_crs_combo()

    def _on_crs_combo_picked(self, idx):
        """Handle a user pick from the CRS combobox."""
        if idx < 0:
            return
        model = self._crs_combo.model()
        if model is None:
            return
        item = model.item(idx)
        if item is None:
            return
        role = item.data(Qt.UserRole)
        if role == self._CRS_ROLE_HEADER or role == self._CRS_ROLE_NONE:
            return  # disabled, shouldn't fire — but be defensive
        if role == self._CRS_ROLE_BROWSE:
            self._on_crs_browse_clicked()
            return
        if role == self._CRS_ROLE_EPSG_INPUT:
            self._on_crs_epsg_input()
            return
        if isinstance(role, int):
            self._set_chosen_crs_from_epsg(role)
            return

    def _on_crs_browse_clicked(self):
        """Open the QGIS CRS picker dialog."""
        dlg = QgsProjectionSelectionDialog(self)
        if self._chosen_crs is not None:
            dlg.setCrs(self._chosen_crs)
        if dlg.exec_():
            crs = dlg.crs()
            if crs is not None and crs.isValid():
                self._set_chosen_crs(crs)
            else:
                # User confirmed an invalid/empty CRS; rebuild to drop
                # any partial state.
                self._rebuild_crs_combo()
        else:
            # Cancelled — restore the combo display.
            self._rebuild_crs_combo()

    def _on_crs_epsg_input(self):
        """Prompt the user to type an EPSG code."""
        text, ok = QInputDialog.getText(
            self, "Enter EPSG code",
            "EPSG code (e.g. 5266):")
        if not ok:
            self._rebuild_crs_combo()
            return
        text = (text or "").strip().upper()
        if text.startswith("EPSG:"):
            text = text.split(":", 1)[1].strip()
        try:
            epsg = int(text)
        except ValueError:
            QMessageBox.warning(
                self, "Primary Forest Finder",
                f"'{text}' is not a valid EPSG code.")
            self._rebuild_crs_combo()
            return
        self._set_chosen_crs_from_epsg(epsg)

    def _recent_target_crses(self, n: int = 10):
        """Read the run-history JSON and return the last N unique
        target_crs values as ``[(epsg_int, label), ...]``.

        Each label includes the relative-age string e.g.
        ``EPSG:5266 — DRUKREF 03 (used 2 runs ago)``. CRSes are de-
        duplicated by EPSG; the most recent occurrence wins.
        """
        try:
            entries = self._load_history()
        except Exception:
            return []
        seen = {}
        order = []
        for i, entry in enumerate(entries):
            crs_str = entry.get("target_crs") or ""
            if not crs_str:
                # Older entries pre-20i didn't track this. Skip.
                continue
            crs_str = str(crs_str).strip()
            if not crs_str.startswith("EPSG:"):
                continue
            try:
                epsg = int(crs_str.split(":", 1)[1])
            except (ValueError, IndexError):
                continue
            if epsg in seen:
                continue
            seen[epsg] = i  # 0 = most recent run
            order.append(epsg)
            if len(order) >= n:
                break
        out = []
        for epsg in order:
            crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg}")
            name = crs.description() if crs.isValid() else ""
            age_idx = seen[epsg]
            if age_idx == 0:
                age = "(used most recently)"
            elif age_idx == 1:
                age = "(used 1 run ago)"
            else:
                age = f"(used {age_idx} runs ago)"
            label = f"EPSG:{epsg}"
            if name:
                label += f" — {name}"
            label += f" {age}"
            out.append((epsg, label))
        return out

    def _on_section_toggled(self, section, expanded: bool):
        """Accordion: when one section expands, collapse the others.

        Only the top-level sections registered in self._top_level_sections
        participate -- nested collapsibles inside §3 (Buffer Exceptions,
        Custom 1/2/3) are independent.
        """
        if not expanded:
            return  # collapse events don't trigger the accordion
        if self._in_accordion_dispatch:
            return  # avoid reentrant storms when we collapse others
        self._in_accordion_dispatch = True
        try:
            for other in self._top_level_sections:
                if other is not section and other.is_expanded():
                    other.set_expanded(False)
        finally:
            self._in_accordion_dispatch = False

    def _refresh_prefix_preview(self, *_):
        """Render the live output-filename prefix preview in §0.

        Shows what `BTN_2020_qgis_04a_primary_forest.tif` will actually
        look like given the current ISO3 + year inputs. P1.30 batch 20j:
        the AOI layer name no longer feeds the prefix.
        """
        try:
            from ..utils import generate_layer_name, PLATFORM_QGIS
        except ImportError:
            return
        iso3 = self._iso3_edit.text().strip() or None
        # 20f: use _current_year_text() as single source of truth.
        year_text = self._current_year_text()
        # Multi-year: preview shows what the FIRST year would produce
        # so the user sees a concrete filename per iteration.
        try:
            from ..utils_year_iter import parse_year_list
            years = parse_year_list(year_text)
        except ImportError:
            years = [year_text] if year_text else []
        if years and "all" not in years:
            year = years[0]
        elif "all" in (years or []):
            year = "all"
        else:
            year = year_text or None
        try:
            sample = generate_layer_name(
                iso3, PLATFORM_QGIS, "04a", "primary_forest",
                ext="tif", year=year)
        except Exception:
            sample = "—"
        self._prefix_preview.setText(f"Prefix preview: {sample}")

    def _build_section_1_time_period(self):
        sec = CollapsibleSection("1. Time Period", expanded=False)
        form = _form()

        # P1.30 batch 20f: explicit single-vs-multi-year mode separation.
        #   - Single-year mode (default): non-editable QComboBox, the
        #     user picks one year from the dropdown. Cleanest UX for
        #     the common case.
        #   - Multi-year mode (tickbox): swap to a QLineEdit with a
        #     greyed placeholder example. User types a comma list.
        # The two widgets are stacked in a tiny QStackedWidget; only
        # one is visible at a time. Single-source-of-truth for the
        # YEAR param string is `_current_year_text()`.
        from qgis.PyQt.QtWidgets import QStackedWidget, QSizePolicy
        self._year_stack = QStackedWidget()
        # 20g: thinner. A 4-digit year only needs ~70 px; multi-year
        # field comfortably fits at ~180. Use Maximum so the field
        # stays compact rather than stretching to fill the dock.
        self._year_stack.setSizePolicy(
            QSizePolicy.Maximum, QSizePolicy.Fixed)

        # Index 0: single-year combobox.
        self._year_single_combo = QComboBox()
        self._year_single_combo.setEditable(False)
        self._year_single_combo.setToolTip(
            "Single-year mode. Pick a year from the dropdown. To run "
            "multiple years, tick 'Run for multiple years' below.")
        self._populate_year_dropdown(fra_only=False)
        self._year_single_combo.setCurrentText("2020")
        self._year_stack.addWidget(self._year_single_combo)

        # Index 1: multi-year text field.
        self._year_multi_edit = QLineEdit()
        self._year_multi_edit.setPlaceholderText("e.g. 2010, 2020")
        self._year_multi_edit.setToolTip(
            "Multi-year mode. Type a comma-separated list of years. "
            "The workflow runs once per year; year-varying inputs "
            "(forest, OLWTC, planted, agriculture, built-up, roads) "
            "are auto-detected by filename year token and globbed "
            "in the same folder. Static inputs (DEM, slope, "
            "protected) are reused across all years.")
        self._year_stack.addWidget(self._year_multi_edit)

        form.addRow("Year(s):", self._year_stack)

        # Tickboxes: FRA-only filter + multi-year mode + year=all.
        self._fra_only_chk = QCheckBox(
            "FRA reporting years only (1990, 2000, 2010, 2015, 2020)")
        self._fra_only_chk.setToolTip(
            "When ticked, the single-year dropdown shows only FAO FRA "
            "reporting years. Combined with 'Run for multiple years', "
            "pre-fills the multi-year field with the FRA ladder.")
        self._fra_only_chk.toggled.connect(self._on_fra_only_toggled)
        form.addRow("", self._fra_only_chk)

        self._multi_year_chk = QCheckBox(
            "Run for multiple years (comma-separated)")
        self._multi_year_chk.setToolTip(
            "When ticked, the Year(s) dropdown is replaced by a free-"
            "form text field. Type a comma-separated list. The "
            "workflow then iterates once per year.\n\n"
            "Convention: assumes year-varying inputs (forest, OLWTC, "
            "planted, agriculture, built-up, roads) for OTHER years "
            "are in the SAME FOLDER as the loaded inputs, with only "
            "the year token differing in the filename "
            "(e.g. forest_2010_*.tif <-> forest_2020_*.tif). Static "
            "inputs (DEM, slope, protected) are reused unchanged.")
        self._multi_year_chk.toggled.connect(self._on_multi_year_toggled)
        form.addRow("", self._multi_year_chk)

        self._year_all_since_2000 = QCheckBox("Year unspecified")
        self._year_all_since_2000.setToolTip(
            "When ticked, no year is recorded for this run. Output "
            "filenames omit the year segment. No iteration.")
        self._year_all_since_2000.toggled.connect(
            lambda on: self._year_stack.setEnabled(not on))
        # 20c: re-render prefix preview whenever year inputs change.
        self._year_single_combo.currentTextChanged.connect(
            self._refresh_prefix_preview)
        self._year_multi_edit.textChanged.connect(
            self._refresh_prefix_preview)
        self._year_all_since_2000.toggled.connect(
            self._refresh_prefix_preview)
        form.addRow("", self._year_all_since_2000)

        sec.set_content_layout(form)
        self._sections_layout.addWidget(sec)

    def _current_year_text(self) -> str:
        """Single source of truth for the YEAR param string."""
        if self._year_all_since_2000.isChecked():
            return "all"
        if self._multi_year_chk.isChecked():
            return self._year_multi_edit.text().strip()
        return self._year_single_combo.currentText().strip()

    def _populate_year_dropdown(self, fra_only: bool):
        """Rebuild the single-year combobox items."""
        FRA_YEARS = ("1990", "2000", "2010", "2015", "2020")
        ALL_YEARS = tuple(str(y) for y in range(1990, 2026))
        years = FRA_YEARS if fra_only else ALL_YEARS
        current = (self._year_single_combo.currentText()
                   if hasattr(self, "_year_single_combo") else "")
        self._year_single_combo.blockSignals(True)
        self._year_single_combo.clear()
        for y in years:
            self._year_single_combo.addItem(y, y)
        if current and current in years:
            self._year_single_combo.setCurrentText(current)
        else:
            self._year_single_combo.setCurrentText("2020")
        self._year_single_combo.blockSignals(False)

    def _on_fra_only_toggled(self, on: bool):
        self._populate_year_dropdown(fra_only=on)
        # If multi-year is also ticked, refresh placeholder + pre-fill.
        if self._multi_year_chk.isChecked():
            self._on_multi_year_toggled(True)

    def _on_multi_year_toggled(self, on: bool):
        if on:
            # Switch to the multi-year text field.
            self._year_stack.setCurrentIndex(1)
            if self._fra_only_chk.isChecked():
                example = "1990, 2000, 2010, 2015, 2020"
                if not self._year_multi_edit.text().strip():
                    self._year_multi_edit.setText(example)
                self._year_multi_edit.setPlaceholderText(f"e.g. {example}")
            else:
                self._year_multi_edit.setPlaceholderText("e.g. 2010, 2020")
        else:
            # Switch back to single-year dropdown.
            self._year_stack.setCurrentIndex(0)

    def _build_section_2_tree_cover(self):
        sec = CollapsibleSection("2. Tree Cover", expanded=True)
        form = _form()

        self._forest_raster = LayerOrFilePicker(
            layer_filter=QgsMapLayerProxyModel.RasterLayer,
            file_filter="Raster (*.tif *.tiff *.img *.vrt);;All (*.*)",
            browse_caption="Pick forest raster")
        form.addRow("Forest raster *:", self._forest_raster)

        self._input_category = QComboBox()
        for it in INPUT_CATEGORY_ITEMS:
            self._input_category.addItem(it)
        # P1.30 batch 21: cap combo's reported sizeHint width so the
        # full GEE-verbatim string ("Tree cover (includes oil palm,
        # orchards, agroforestry etc)") doesn't force the form field
        # column to ~450 px — which would clip the LayerOrFilePicker
        # browse buttons in nearby rows. The combo can still show the
        # full text at runtime; the dropdown is unaffected.
        self._input_category.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._input_category.setMinimumContentsLength(15)
        self._input_category.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._input_category.currentIndexChanged.connect(
            self._on_input_category_changed)
        form.addRow("My tree cover\nrepresents:", self._input_category)

        # OLWTC group
        self._olwtc_label = QLabel("OLWTC raster:")
        self._olwtc_raster = LayerOrFilePicker(
            layer_filter=QgsMapLayerProxyModel.RasterLayer,
            file_filter="Raster (*.tif *.tiff *.img *.vrt);;All (*.*)",
            browse_caption="Pick OLWTC raster")
        self._olwtc_refine = QCheckBox("Refine to forest (exclude OLWTC)")
        self._olwtc_refine.setChecked(True)
        form.addRow(self._olwtc_label, self._olwtc_raster)
        form.addRow("", self._olwtc_refine)

        # Planted forest group
        self._planted_label = QLabel("Planted forest:")
        self._planted_raster = LayerOrFilePicker(
            layer_filter=QgsMapLayerProxyModel.RasterLayer,
            file_filter="Raster (*.tif *.tiff *.img *.vrt);;All (*.*)",
            browse_caption="Pick planted-forest raster")
        self._planted_refine = QCheckBox(
            "Refine to NRF (exclude planted forest)")
        self._planted_refine.setChecked(True)
        form.addRow(self._planted_label, self._planted_raster)
        form.addRow("", self._planted_refine)

        sec.set_content_layout(form)
        self._sections_layout.addWidget(sec)

        self._on_input_category_changed()  # set initial visibility

    def _on_input_category_changed(self):
        cat = self._input_category.currentText()
        show_olwtc = (cat == INPUT_CATEGORY_TREECOVER)
        show_planted = show_olwtc or (cat == INPUT_CATEGORY_FOREST)
        for w in (self._olwtc_label, self._olwtc_raster, self._olwtc_refine):
            w.setVisible(show_olwtc)
        for w in (self._planted_label, self._planted_raster,
                  self._planted_refine):
            w.setVisible(show_planted)
        # Functional: when input is already filtered, the corresponding
        # refine checkbox flips OFF so the run doesn't double-subtract.
        if not show_olwtc:
            self._olwtc_refine.setChecked(False)
        if not show_planted:
            self._planted_refine.setChecked(False)

    def _build_section_3_human_influence(self):
        sec = CollapsibleSection("3. Human Influence", expanded=False)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)

        self._add_human_layers_to_map = QCheckBox(
            "Add human-influence input + buffer layers to map after run")
        body.addWidget(self._add_human_layers_to_map)

        # GEE wording (pff_4.js:1865): "Use single distance for all:"
        self._use_single_buffer = QCheckBox("Use single distance for all:")
        body.addWidget(self._use_single_buffer)

        master_row = QHBoxLayout()
        master_row.setContentsMargins(20, 0, 0, 0)
        master_row.addWidget(QLabel("All:"))
        self._master_buffer = _spin(default=D_ROADS, mn=0, mx=5000)
        master_row.addWidget(self._master_buffer)
        master_row.addStretch(1)
        body.addLayout(master_row)

        # Per-driver rows: [enable] [smart-picker] [buffer m]
        # Roads accepts vector or raster -> smart picker.
        # Defaults match GEE (pff_4.js:1842-1846): all 1000 m, 0-5000 range.
        self._roads_picker = SmartLayerPicker()
        self._roads_enable = QCheckBox("Roads")
        self._roads_enable.setChecked(True)
        self._roads_buffer = _spin(default=D_ROADS, mn=0, mx=5000)
        body.addLayout(self._driver_row(
            self._roads_enable, self._roads_picker, self._roads_buffer))

        self._builtup_small_picker = _raster_picker("Pick built-up small raster")
        self._builtup_small_enable = QCheckBox("Built-up sm.")
        self._builtup_small_enable.setChecked(True)
        self._builtup_small_buffer = _spin(
            default=D_BUILTUP_SM, mn=0, mx=5000)
        body.addLayout(self._driver_row(
            self._builtup_small_enable, self._builtup_small_picker,
            self._builtup_small_buffer))

        self._builtup_large_picker = _raster_picker("Pick built-up large raster")
        self._builtup_large_enable = QCheckBox("Built-up lg.")
        self._builtup_large_enable.setChecked(True)
        self._builtup_large_buffer = _spin(
            default=D_BUILTUP_LG, mn=0, mx=5000)
        body.addLayout(self._driver_row(
            self._builtup_large_enable, self._builtup_large_picker,
            self._builtup_large_buffer))

        self._agriculture_picker = _raster_picker("Pick agriculture raster")
        self._agriculture_enable = QCheckBox("Agriculture")
        self._agriculture_enable.setChecked(True)
        self._agriculture_buffer = _spin(
            default=D_AGRI, mn=0, mx=5000)
        body.addLayout(self._driver_row(
            self._agriculture_enable, self._agriculture_picker,
            self._agriculture_buffer))

        # Wire master buffer to grey-and-sync per-driver sliders. When
        # the master checkbox is ticked: per-driver spinboxes go disabled
        # (greyed) and their values track the master slider — matches
        # GEE pff_4.js:1879-1880. Untick to edit per-driver again; the
        # last master-propagated value is retained.
        self._per_driver_buffers = (
            self._roads_buffer,
            self._builtup_small_buffer,
            self._builtup_large_buffer,
            self._agriculture_buffer,
        )
        self._use_single_buffer.toggled.connect(
            self._on_single_buffer_toggled)
        self._master_buffer.valueChanged.connect(
            self._on_master_value_changed)
        # Initial state: single-buffer off, per-driver sliders editable.
        self._on_single_buffer_toggled(False)

        self._max_distance = _spin(default=D_MAX_DIST, mn=100, mx=100000)
        adv_dist = QHBoxLayout()
        adv_dist.setContentsMargins(20, 4, 0, 0)
        adv_dist.addWidget(QLabel("Max distance to compute (advanced):"))
        adv_dist.addWidget(self._max_distance)
        adv_dist.addStretch(1)
        body.addLayout(adv_dist)

        # ── Buffer Exceptions (collapsed) ──
        bx = CollapsibleSection("Buffer Exceptions",
                                expanded=False, indent_px=8,
                                header_bold=False)
        bx_form = _form()

        self._dem_slope_picker = DemSlopeLayerPicker()
        bx_form.addRow("DEM/Slope:", self._dem_slope_picker)

        self._slope_threshold = _spin(default=30, mn=0, mx=90, suffix=" °")
        bx_form.addRow("Threshold:", self._slope_threshold)

        self._protected_picker = SmartLayerPicker()
        bx_form.addRow("Protected:", self._protected_picker)

        bx.set_content_layout(bx_form)
        body.addWidget(bx)

        # ── Custom drivers gate ──
        self._enable_custom = QCheckBox("Enable custom data inputs")
        body.addWidget(self._enable_custom)

        self._custom_sections = []
        for i in (1, 2, 3):
            cs = CollapsibleSection(f"Custom {i}",
                                    expanded=False, indent_px=8,
                                    header_bold=False)
            cf = _form()

            label_edit = QLineEdit(f"Custom disturbance {i}")
            cf.addRow("Label:", label_edit)

            picker = _raster_picker(f"Pick custom {i} raster")
            cf.addRow("Raster:", picker)

            buf = _spin(default=1000, mn=0, mx=10000)
            cf.addRow("Buffer:", buf)

            cs.set_content_layout(cf)
            cs.setVisible(False)  # hidden until master toggle ticks
            body.addWidget(cs)
            self._custom_sections.append((cs, label_edit, picker, buf))

        self._enable_custom.toggled.connect(self._on_enable_custom_toggled)

        sec.set_content_layout(body)
        self._sections_layout.addWidget(sec)

    def _driver_row(self, enable_chk, picker_widget, buffer_spin):
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        enable_chk.setMinimumWidth(110)
        h.addWidget(enable_chk)
        h.addWidget(picker_widget, 1)
        buffer_spin.setMinimumWidth(110)
        h.addWidget(buffer_spin)
        return h

    def _on_enable_custom_toggled(self, on: bool):
        for cs, _, _, _ in self._custom_sections:
            cs.setVisible(on)

    def _on_single_buffer_toggled(self, on: bool):
        """Grey + sync per-driver sliders when 'Use single distance' is on.

        Matches GEE pff_4.js:1864-1881 — ticking 'Use single distance for
        all' propagates the master value to every per-driver slider and
        prevents per-driver edits. Untick to edit individually again
        (last propagated value is retained).
        """
        for sb in self._per_driver_buffers:
            sb.setEnabled(not on)
        if on:
            self._on_master_value_changed(self._master_buffer.value())

    def _on_master_value_changed(self, value):
        if not self._use_single_buffer.isChecked():
            return
        for sb in self._per_driver_buffers:
            # Block signals to avoid feedback loops on the spinbox.
            sb.blockSignals(True)
            sb.setValue(value)
            sb.blockSignals(False)

    def _build_section_4_refine_output(self):
        sec = CollapsibleSection("4. Refine Output", expanded=False)
        form = _form()

        self._enable_refine = QCheckBox("Enable refine")
        self._enable_refine.setChecked(True)
        form.addRow("", self._enable_refine)

        self._smooth_radius = _spin(default=1500, mn=0, mx=10000)
        form.addRow("Smooth radius:", self._smooth_radius)

        self._density_threshold = _spin(
            default=0.5, mn=0.0, mx=1.0, decimals=2, suffix="")
        form.addRow("Min density:", self._density_threshold)

        self._refine_min_patch = _spin(
            default=0.0, mn=0.0, mx=100000.0, suffix=" ha")
        form.addRow("Min patch:", self._refine_min_patch)

        self._fast_approx = QCheckBox("Fast approx (advanced)")
        form.addRow("", self._fast_approx)

        sec.set_content_layout(form)
        self._sections_layout.addWidget(sec)

    def _build_section_5_area_statistics(self):
        # P1.30 batch 23: stays at §5 (unchanged). New §6 Outputs is
        # the consolidated parent for Vectorise / Validation sampling /
        # Save list / Run config / Performance.
        sec = CollapsibleSection("5. Area Statistics", expanded=False)
        form = _form()

        self._run_zonal = QCheckBox("Run zonal statistics")
        form.addRow("", self._run_zonal)

        self._zone_layer_combo = LayerOrFilePicker(
            layer_filter=QgsMapLayerProxyModel.PolygonLayer,
            file_filter="Vector (*.gpkg *.shp *.geojson);;All (*.*)",
            browse_caption="Pick zone polygons")
        form.addRow("Zone layer:", self._zone_layer_combo)

        self._zone_field = QgsFieldComboBox()
        self._zone_field.setAllowEmptyFieldName(True)
        self._zone_layer_combo.pathChanged.connect(self._refresh_zone_field)
        form.addRow("Zone field:", self._zone_field)

        sec.set_content_layout(form)
        self._sections_layout.addWidget(sec)

    def _refresh_zone_field(self):
        layer = self._zone_layer_combo.current_layer()
        self._zone_field.setLayer(layer)

    def _build_subsection_vectorise(self):
        # P1.30 batch 23: was top-level §6 "Vectorise Outputs"; now a
        # sub-section inside §6 Outputs. Caller adds the returned
        # CollapsibleSection to the §6 body layout.
        sec = CollapsibleSection(
            "Vectorise outputs", expanded=False,
            indent_px=8, header_bold=False)
        form = _form()

        self._vec_primary = QCheckBox("Primary forest")
        form.addRow("", self._vec_primary)

        self._vec_forest = QCheckBox("Forest (or nat-reg if refined)")
        form.addRow("", self._vec_forest)

        self._vec_nest = QCheckBox("Nested (cut primary out of forest)")
        form.addRow("", self._vec_nest)

        self._vec_dissolve = QCheckBox(
            "Also dissolve nested to multipart by level")
        self._vec_dissolve.setChecked(True)
        # Dissolve only applies to the nested output, so it follows the
        # nest tick: enabled iff nest is ticked, otherwise greyed out.
        self._vec_dissolve.setEnabled(False)
        self._vec_nest.toggled.connect(self._vec_dissolve.setEnabled)
        form.addRow("", self._vec_dissolve)

        self._vec_min_patch_ha = _spin(
            default=0.0, mn=0.0, mx=100000.0, suffix=" ha")
        self._vec_min_patch_ha.setToolTip(
            "Drop connected components below this area from primary + "
            "forest-backdrop rasters BEFORE polygonising. Speeds up "
            "vectorise + simplify on noisy inputs and reduces output "
            "polygon count. 0 = no sieve. The on-disk 04a primary forest "
            "raster is NOT modified — only the polygonised outputs are "
            "filtered.")
        form.addRow("Min patch (pre-sieve):", self._vec_min_patch_ha)

        self._vec_remove_pixel_stairs = QCheckBox(
            "Auto-clean pixel-stair vertices (advanced)")
        self._vec_remove_pixel_stairs.setChecked(True)
        self._vec_remove_pixel_stairs.setToolTip(
            "After polygonise, run a Visvalingam pass at half-pixel "
            "tolerance to drop redundant collinear vertices on raster-"
            "aligned edges. Shape-preserving — typically halves vertex "
            "count without visible change. Default ON.")
        form.addRow("", self._vec_remove_pixel_stairs)

        self._vec_simplify = _spin(default=0.0, mn=0.0, mx=1000.0)
        form.addRow("Simplify:", self._vec_simplify)

        self._vec_as_shp = QCheckBox("Output as .shp instead of .gpkg")
        form.addRow("", self._vec_as_shp)

        sec.set_content_layout(form)
        return sec

    # P1.30 batch 23: §7 Run Options replaced. Save list moved to §6
    # Outputs top via _build_save_list_form_rows. Reuse-cache toggles
    # moved to the Performance sub-section. Add-to-map moved to §6
    # Outputs top.

    def _build_save_list_form_rows(self, form):
        """Add the Save outputs summary + Customise sub-section to the
        passed-in form layout. Used by _build_section_6_outputs.
        """
        from qgis.PyQt.QtWidgets import QPushButton as _QPushButton
        # P1.30 batch 22: per-layer Save list. Default view shows a
        # summary line + small reset button + collapsible Customise.
        # Each output raster has its own tickbox; defaults match
        # historical behaviour (Forest + NRF + Primary saved; pre-conn
        # + anthro mask off). The 5 SAVE_* algorithm params route
        # un-saved layers to scratch instead of out_dir.
        self._save_layers = [
            ("save_02b_forest", "Forest", "(02b)", True),
            ("save_02d_nrf", "Naturally regenerating forest", "(02d)", True),
            ("save_03c_pre_conn", "Pre-connectivity primary forest",
             "(03c, intermediate)", False),
            ("save_04a_primary", "Primary forest", "(04a, final)", True),
            ("save_04e_anthro_mask", "Anthropogenic mask",
             "(04e, debug)", False),
        ]
        self._save_checkboxes = {}

        save_summary_row = QHBoxLayout()
        save_summary_row.setContentsMargins(0, 0, 0, 0)
        self._save_summary_label = QLabel("")
        self._save_summary_label.setStyleSheet("color:#444;")
        save_summary_row.addWidget(self._save_summary_label, 1)
        self._save_reset_btn = QToolButton()
        self._save_reset_btn.setText("↺")
        self._save_reset_btn.setToolTip(
            "Reset Save list to defaults: Forest, Naturally regenerating "
            "forest, Primary forest.")
        self._save_reset_btn.clicked.connect(self._on_save_defaults)
        save_summary_row.addWidget(self._save_reset_btn, 0)
        form.addRow("Save outputs:", save_summary_row)

        self._save_customise_section = CollapsibleSection(
            "Customise output rasters", expanded=False,
            indent_px=8, header_bold=False)
        cust_layout = QVBoxLayout()
        cust_layout.setContentsMargins(0, 0, 0, 0)
        cust_layout.setSpacing(4)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        for label, handler in (
                ("Defaults", self._on_save_defaults),
                ("Select all", self._on_save_all),
                ("Select none", self._on_save_none)):
            b = _QPushButton(label)
            b.setMinimumHeight(22)
            b.clicked.connect(handler)
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        cust_layout.addLayout(btn_row)

        for key, name, suffix, default in self._save_layers:
            cb = QCheckBox(f"{name}  {suffix}")
            cb.setChecked(default)
            cb.toggled.connect(self._refresh_save_summary)
            cust_layout.addWidget(cb)
            self._save_checkboxes[key] = cb

        self._save_customise_section.set_content_layout(cust_layout)
        form.addRow("", self._save_customise_section)
        # Initial summary
        self._refresh_save_summary()

    def _build_subsection_performance(self):
        """Performance / cache sub-section for §6 Outputs."""
        sec = CollapsibleSection(
            "Performance / cache", expanded=False,
            indent_px=8, header_bold=False)
        form = _form()

        self._reuse_distance = QCheckBox("Reuse cached distance surfaces")
        form.addRow("", self._reuse_distance)

        self._reuse_prepared = QCheckBox("Reuse prepared cache")
        self._reuse_prepared.setChecked(True)
        form.addRow("", self._reuse_prepared)

        sec.set_content_layout(form)
        return sec

    def _build_subsection_save_load_config(self):
        """Save / Load run config sub-section for §6 Outputs.

        P1.30 batch 23: lets users persist the dock's full panel state
        as a human-readable JSON, then reload it later. Mirrors the
        GEE app's Save Settings feature for cross-tool parity.
        """
        from qgis.PyQt.QtWidgets import QPushButton as _QPushButton
        sec = CollapsibleSection(
            "Run config (save / load)", expanded=False,
            indent_px=8, header_bold=False)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)

        intro = QLabel(
            "<i>Save the dock's current settings to a JSON file you "
            "can reload later. Mirrors the GEE app's Save Settings.</i>")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#666;")
        intro.setMinimumWidth(0)
        intro.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        body.addWidget(intro)

        save_btn = _QPushButton("Save current settings to file…")
        save_btn.clicked.connect(self._on_save_run_config)
        body.addWidget(save_btn)

        load_btn = _QPushButton("Load settings from file…")
        load_btn.clicked.connect(self._on_load_run_config)
        body.addWidget(load_btn)

        sec.set_content_layout(body)
        return sec

    def _build_section_6_outputs(self):
        """§6 Outputs — consolidated parent for everything output-
        related. Contains:
          - Output folder picker (moved from §0)
          - Save list summary + Customise (moved from §7, batch 22)
          - "Add saved outputs to map" toggle (renamed from §7)
          - ▸ Vectorise outputs (was §6)
          - ▸ Validation sampling (experimental) (was §8, renamed)
          - ▸ Run config (save / load) (NEW in batch 23)
          - ▸ Performance / cache (was rest of §7)
        """
        sec = CollapsibleSection("6. Outputs", expanded=False)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)

        form = _form()

        self._output_folder = QgsFileWidget()
        self._output_folder.setStorageMode(QgsFileWidget.GetDirectory)
        self._output_folder.setToolTip(
            "Folder where all PFF outputs land. Disambiguate runs by "
            "naming this folder descriptively (e.g. BTN/aberdares_2020).")
        form.addRow("Output folder:", self._output_folder)

        self._build_save_list_form_rows(form)

        self._add_main_to_map = QCheckBox("Add saved outputs to map")
        self._add_main_to_map.setChecked(True)
        self._add_main_to_map.setToolTip(
            "After run, load the saved output rasters into the QGIS "
            "Layers panel with PFF symbology. Honours the Save list "
            "above — only saved layers are added.")
        form.addRow("", self._add_main_to_map)

        body.addLayout(form)

        # Sub-sections (collapsed by default).
        body.addWidget(self._build_subsection_vectorise())
        body.addWidget(self._build_subsection_validation_sampling())
        body.addWidget(self._build_subsection_save_load_config())
        body.addWidget(self._build_subsection_performance())

        sec.set_content_layout(body)
        self._sections_layout.addWidget(sec)

    # ── Run config save / load handlers ───────────────────────────────
    def _on_save_run_config(self):
        from qgis.PyQt.QtWidgets import QFileDialog
        path, _flt = QFileDialog.getSaveFileName(
            self, "Save PFF run config", "",
            "PFF config JSON (*.json);;All (*.*)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            params = self._collect_params()
            from datetime import datetime
            payload = {
                "_pff_config_format": 1,
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "pff_version": FW.PFF_VERSION,
                "params": _serialise_params(params),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
            self._log.append(
                f"<span>Run config saved to {_html_escape(path)}</span>")
        except Exception as e:
            QMessageBox.warning(
                self, "Primary Forest Finder",
                f"Could not save run config:\n{e}")

    def _on_load_run_config(self):
        from qgis.PyQt.QtWidgets import QFileDialog
        path, _flt = QFileDialog.getOpenFileName(
            self, "Load PFF run config", "",
            "PFF config JSON (*.json);;All (*.*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            params = payload.get("params") or payload  # tolerate flat dicts
            self._apply_params(params)
            saved_at = payload.get("saved_at", "?")
            self._log.append(
                f"<span>Run config loaded from "
                f"{_html_escape(path)} (saved {_html_escape(saved_at)})"
                "</span>")
        except Exception as e:
            QMessageBox.warning(
                self, "Primary Forest Finder",
                f"Could not load run config:\n{e}")

    # ── Save-list handlers ────────────────────────────────────────────
    def _on_save_defaults(self):
        for key, _name, _suffix, default in self._save_layers:
            self._save_checkboxes[key].setChecked(default)

    def _on_save_all(self):
        for cb in self._save_checkboxes.values():
            cb.setChecked(True)

    def _on_save_none(self):
        for cb in self._save_checkboxes.values():
            cb.setChecked(False)

    def _refresh_save_summary(self):
        """Live summary line above the Customise sub-section."""
        ticked = [name for key, name, _suffix, _default in self._save_layers
                  if self._save_checkboxes[key].isChecked()]
        defaults_set = {name for _key, name, _suffix, default
                        in self._save_layers if default}
        ticked_set = set(ticked)
        if not ticked:
            text = "Saved: nothing"
        elif ticked_set == defaults_set:
            text = "Saved: " + ", ".join(ticked)
        elif len(ticked) <= 3:
            text = "Saved: " + ", ".join(ticked)
        else:
            text = f"Saved: {len(ticked)} of {len(self._save_layers)} layers"
        self._save_summary_label.setText(text)

    # ────────────────────────────────────────────────────────────────
    # P1.30 batch 21: §8 CEO Validation Export (experimental)
    # Independent flow from full_workflow -- has its own Run button.
    # ────────────────────────────────────────────────────────────────
    def _build_subsection_validation_sampling(self):
        # P1.30 batch 23: was top-level §8 "Validation: CEO Export";
        # now a sub-section inside §6 Outputs. Renamed to "Validation
        # sampling" per user feedback (more descriptive of what the
        # section does — generates samples for validation; CEO is the
        # downstream consumer).
        from qgis.PyQt.QtWidgets import QSpinBox, QDoubleSpinBox, QStackedWidget
        sec = CollapsibleSection(
            "Validation sampling (experimental)", expanded=False,
            indent_px=8, header_bold=False)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)

        banner = QLabel(
            "<i>Experimental — generates lightweight CEO Plot + Sample "
            "layers from a forest vector. Tested against Bhutan 06c.</i>")
        banner.setWordWrap(True)
        banner.setStyleSheet("color:#666;")
        # Critical: explicit min width so wordWrap can actually shrink
        # the label below its natural single-line sizeHint. Without
        # this, the banner forces the whole §8 section minimum to
        # ~1000 px on Windows.
        banner.setMinimumWidth(0)
        banner.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        body.addWidget(banner)

        form = _form()

        # P1.30 batch 21: helper to wrap a small widget + stretch in an
        # HBox so the form field column doesn't grow to fit a greedy
        # spinbox / lineedit. Without this, even one un-stretched
        # numeric field forces the whole field column wide enough to
        # clip the LayerOrFilePicker browse button.
        def _row(*widgets):
            r = QHBoxLayout()
            r.setContentsMargins(0, 0, 0, 0)
            r.setSpacing(6)
            for w in widgets:
                if isinstance(w, str):
                    r.addWidget(QLabel(w))
                elif isinstance(w, int):
                    r.addSpacing(w)
                else:
                    r.addWidget(w)
            r.addStretch(1)
            return r

        self._ceo_input = LayerOrFilePicker(
            layer_filter=QgsMapLayerProxyModel.PolygonLayer,
            file_filter="Vector (*.gpkg *.shp *.geojson);;All (*.*)",
            browse_caption="Pick forest / primary forest vector")
        self._ceo_input.setToolTip(
            "Forest / primary forest polygon layer (e.g. PFF stage-6 "
            "nested vector). Must be in a projected CRS with metre "
            "units.")
        form.addRow("Input vector:", self._ceo_input)

        self._ceo_class_field = QgsFieldComboBox()
        self._ceo_class_field.setAllowEmptyFieldName(False)
        self._ceo_class_field.setToolTip(
            "Integer field that distinguishes primary forest from other "
            "forest. Auto-picks 'level' for PFF stage-6 outputs.")
        # Cap natural width so this combo doesn't dominate the field column.
        self._ceo_class_field.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._ceo_input.pathChanged.connect(self._refresh_ceo_class_field)
        form.addRow("Class field:", self._ceo_class_field)

        self._ceo_primary_value = QSpinBox()
        self._ceo_primary_value.setRange(-99, 9999)
        self._ceo_primary_value.setValue(2)
        self._ceo_primary_value.setMaximumWidth(70)
        self._ceo_primary_value.setToolTip(
            "Field value that flags primary-forest features "
            "(default 2 in PFF outputs).")
        self._ceo_other_value = QSpinBox()
        self._ceo_other_value.setRange(-99, 9999)
        self._ceo_other_value.setValue(1)
        self._ceo_other_value.setMaximumWidth(70)
        self._ceo_other_value.setToolTip(
            "Field value that flags other-forest features "
            "(default 1 in PFF outputs).")
        form.addRow("Class values:", _row(
            "Primary:", self._ceo_primary_value, 8,
            "Other:", self._ceo_other_value))

        self._ceo_domain = QComboBox()
        self._ceo_domain.addItems(
            ["All forest", "Primary only", "Other forest only"])
        self._ceo_domain.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._ceo_domain.setToolTip(
            "Which class(es) to sample from. Ignored when 'Stratified "
            "by class' is ticked (stratified always samples both).")
        form.addRow("Sampling domain:", self._ceo_domain)

        self._ceo_stratified = QCheckBox("Stratified by class")
        self._ceo_stratified.setToolTip(
            "When ticked, sample N_primary + N_other independently per "
            "class. When unticked, sample N_total uniformly across the "
            "selected sampling domain.")
        self._ceo_stratified.toggled.connect(
            self._on_ceo_stratified_toggled)
        form.addRow("", self._ceo_stratified)

        self._ceo_n_total = QSpinBox()
        self._ceo_n_total.setRange(1, 100000)
        self._ceo_n_total.setValue(50)
        self._ceo_n_total.setMaximumWidth(110)
        self._ceo_n_total.setToolTip(
            "Total number of random samples to generate. Used in "
            "non-stratified mode only.")
        form.addRow("N samples:", _row(self._ceo_n_total))

        self._ceo_n_primary = QSpinBox()
        self._ceo_n_primary.setRange(0, 100000)
        self._ceo_n_primary.setValue(25)
        self._ceo_n_primary.setMaximumWidth(80)
        self._ceo_n_primary.setToolTip(
            "Random samples to generate inside primary-forest polygons. "
            "Used in stratified mode only.")
        self._ceo_n_other = QSpinBox()
        self._ceo_n_other.setRange(0, 100000)
        self._ceo_n_other.setValue(25)
        self._ceo_n_other.setMaximumWidth(80)
        self._ceo_n_other.setToolTip(
            "Random samples to generate inside other-forest polygons. "
            "Used in stratified mode only.")
        form.addRow("N per class:", _row(
            "Primary:", self._ceo_n_primary, 8,
            "Other:", self._ceo_n_other))

        # Min spacing + Random seed moved into the Advanced sub-section
        # below to keep §8 default uncluttered. Widgets stay top-level
        # attributes so handlers + collect_params keep working.
        self._ceo_min_distance = QDoubleSpinBox()
        self._ceo_min_distance.setRange(0, 1000000)
        self._ceo_min_distance.setValue(0)
        self._ceo_min_distance.setSuffix(" m")
        self._ceo_min_distance.setDecimals(0)
        self._ceo_min_distance.setMaximumWidth(110)
        self._ceo_min_distance.setToolTip(
            "Minimum distance between any two sample centres. 0 = no "
            "constraint. Useful to reduce overlap of interpretation "
            "areas — but it is NOT the fix for the ring-bite issue "
            "(rings are built per-point regardless).")

        self._ceo_seed = QLineEdit()
        self._ceo_seed.setPlaceholderText("blank = system random")
        self._ceo_seed.setMaximumWidth(160)
        self._ceo_seed.setToolTip(
            "Integer seed for reproducible sampling. Leave blank for "
            "system-random (different each run). Saved into provenance "
            "fields when those are enabled.")

        self._ceo_method = QComboBox()
        self._ceo_method.addItems(
            ["Simple point plots",
             "Custom circular ring boundaries"])
        self._ceo_method.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._ceo_method.setToolTip(
            "Simple = point centres only (CEO renders a default ~500 m "
            "visualisation buffer). Custom circular = thin ring "
            "polygons + your choice of sample geometry; gives you "
            "control over the interpretation radius.")
        self._ceo_method.currentIndexChanged.connect(
            self._on_ceo_method_changed)
        form.addRow("Export method:", self._ceo_method)

        self._ceo_radius = QDoubleSpinBox()
        self._ceo_radius.setRange(1, 100000)
        self._ceo_radius.setValue(2000)
        self._ceo_radius.setSuffix(" m")
        self._ceo_radius.setDecimals(0)
        self._ceo_radius.setMaximumWidth(110)
        self._ceo_radius.setToolTip(
            "Half-width of the interpretation area for each plot. The "
            "ring's inner radius. Default 2000 m matches a 2 km plot "
            "used in many CEO workshops.")
        self._ceo_ring_w = QDoubleSpinBox()
        self._ceo_ring_w.setRange(0.1, 1000)
        self._ceo_ring_w.setValue(1)
        self._ceo_ring_w.setSuffix(" m")
        self._ceo_ring_w.setDecimals(1)
        self._ceo_ring_w.setMaximumWidth(90)
        self._ceo_ring_w.setToolTip(
            "Thickness of the ring polygon (outer_radius − inner_"
            "radius). 1 m keeps the ring visible at typical CEO zoom "
            "levels without obscuring the imagery.")
        form.addRow("Circular:", _row(
            "Radius:", self._ceo_radius, 8,
            "Ring:", self._ceo_ring_w))

        self._ceo_sample_point = QCheckBox("Centre point")
        self._ceo_sample_point.setChecked(True)
        self._ceo_sample_point.setToolTip(
            "Emit a centre-point sample layer. Each row's "
            "PLOTID == SAMPLEID.")
        self._ceo_sample_square = QCheckBox("1 ha square")
        self._ceo_sample_square.setToolTip(
            "Emit a 1 ha square sample layer (separate file). Centred "
            "on the random point. PLOTID and SAMPLEID also match per "
            "row.")
        self._ceo_sample_square.toggled.connect(
            self._on_ceo_sample_square_toggled)
        form.addRow("Sample geom:", _row(
            self._ceo_sample_point, self._ceo_sample_square))

        self._ceo_square_size = QDoubleSpinBox()
        self._ceo_square_size.setRange(1, 10000)
        self._ceo_square_size.setValue(100)
        self._ceo_square_size.setSuffix(" m")
        self._ceo_square_size.setDecimals(0)
        self._ceo_square_size.setMaximumWidth(110)
        self._ceo_square_size.setToolTip(
            "Side length of the 1 ha square sample. Default 100 m → "
            "1 hectare.")
        form.addRow("Square size:", _row(self._ceo_square_size))

        self._ceo_output_folder = QgsFileWidget()
        self._ceo_output_folder.setStorageMode(QgsFileWidget.GetDirectory)
        self._ceo_output_folder.setToolTip(
            "Folder where ceo_*.gpkg / .zip files are written. "
            "Disambiguate runs via the folder name "
            "(e.g. BTN/aberdares_2020).")
        form.addRow("Output folder:", self._ceo_output_folder)

        # Output format + provenance moved into Advanced sub-section.
        self._ceo_out_gpkg = QCheckBox("GeoPackage")
        self._ceo_out_gpkg.setChecked(True)
        self._ceo_out_gpkg.setToolTip(
            "Write outputs as .gpkg (single file, full attribute "
            "names).")
        self._ceo_out_zip = QCheckBox("Zipped SHP (CEO upload)")
        self._ceo_out_zip.setChecked(True)
        self._ceo_out_zip.setToolTip(
            "Write outputs as zipped .shp (CEO's most reliable upload "
            "format). Note: DBF truncates field names > 10 chars "
            "(class_value → class_valu, etc.).")

        self._ceo_reproject_wgs84 = QCheckBox(
            "Reproject outputs to WGS84 (EPSG:4326)")
        self._ceo_reproject_wgs84.setChecked(True)
        self._ceo_reproject_wgs84.setToolTip(
            "Default ON. CEO uses WGS84 (EPSG:4326) — geographic "
            "lat/lon — as its standard upload format. Buffering and "
            "sampling still happen in the projected source CRS so all "
            "distances are correct in metres; only the final written "
            "geometry is reprojected. Untick to keep outputs in the "
            "input layer's projected CRS for QGIS-side post-processing.")

        self._ceo_provenance = QCheckBox("Add provenance fields")
        self._ceo_provenance.setToolTip(
            "Off by default. When ON, every output row gets auto-"
            "generated tracing fields: class_value, class_name, "
            "radius_m, ring_width_m, sample_type, sampling_method, "
            "random_seed, source_id. Note: Shapefile DBF truncates "
            "names > 10 chars (class_value -> class_valu); GeoPackage "
            "keeps full names.")

        # Stash form ref + row indices so the toggle handlers can hide
        # rows. PyQt5 in QGIS 3.38 doesn't expose QFormLayout's Qt 5.15
        # `setRowVisible`; we walk row items by index instead.
        self._ceo_form = form
        self._ceo_rows = {
            "input": 0,
            "class_field": 1,
            "class_values": 2,
            "domain": 3,
            "stratified": 4,
            "n_total": 5,
            "n_per_class": 6,
            "method": 7,
            "circular": 8,
            "sample_geom": 9,
            "square_size": 10,
            "output_folder": 11,
        }
        body.addLayout(form)

        # ── Advanced (collapsed by default) ──
        adv = CollapsibleSection(
            "Advanced", expanded=False, indent_px=8, header_bold=False)
        adv_form = _form()
        adv_form.addRow("Min spacing:", _row(self._ceo_min_distance))
        adv_form.addRow("Random seed:", _row(self._ceo_seed))
        adv_form.addRow("Output format:", _row(
            self._ceo_out_gpkg, self._ceo_out_zip))
        adv_form.addRow("", self._ceo_reproject_wgs84)
        adv_form.addRow("", self._ceo_provenance)
        adv.set_content_layout(adv_form)
        body.addWidget(adv)

        self._ceo_run_btn = QPushButton("Generate CEO inputs ▶")
        self._ceo_run_btn.setMinimumHeight(28)
        self._ceo_run_btn.clicked.connect(self._on_generate_ceo_clicked)
        body.addWidget(self._ceo_run_btn)

        sec.set_content_layout(body)
        # P1.30 batch 23: initial enabled state for the three
        # mutually-exclusive control axes (stratified, method,
        # sample-square). Each handler is idempotent and references the
        # current widget values, so calling them in any order is safe.
        self._on_ceo_method_changed(self._ceo_method.currentIndex())
        self._on_ceo_stratified_toggled(self._ceo_stratified.isChecked())
        self._on_ceo_sample_square_toggled(
            self._ceo_sample_square.isChecked())
        return sec

    def _refresh_ceo_class_field(self):
        layer = self._ceo_input.current_layer()
        self._ceo_class_field.setLayer(layer)
        # Auto-pick "level" if present (PFF stage-6 convention).
        if layer is not None:
            for f in layer.fields():
                if f.name().lower() == "level":
                    self._ceo_class_field.setField(f.name())
                    break

    def _set_ceo_row_visible(self, row_key, visible):
        """Hide / show one row of the §8 form by row-key index.

        Walks the row's label item and field item (which may be a
        widget or a child layout) and toggles visibility on every
        widget under it. PyQt5/Qt5 here doesn't have
        QFormLayout.setRowVisible (Qt 5.15+ only) so we DIY.
        """
        from qgis.PyQt.QtWidgets import QFormLayout
        idx = self._ceo_rows.get(row_key)
        if idx is None:
            return
        for role in (QFormLayout.LabelRole, QFormLayout.FieldRole):
            item = self._ceo_form.itemAt(idx, role)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.setVisible(visible)
                continue
            sublayout = item.layout()
            if sublayout is not None:
                self._set_layout_widgets_visible(sublayout, visible)

    def _set_layout_widgets_visible(self, layout, visible):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget()
            if w is not None:
                w.setVisible(visible)
                continue
            sub = item.layout()
            if sub is not None:
                self._set_layout_widgets_visible(sub, visible)

    def _on_ceo_method_changed(self, idx):
        """Hide circular-only rows when method = Simple.

        Custom circular: Radius/Ring + Sample geom + (conditionally)
        Square size are visible. Simple point plots: all of those rows
        disappear from the form -- cleaner than greying.
        """
        circular = (idx == 1)
        self._set_ceo_row_visible("circular", circular)
        self._set_ceo_row_visible("sample_geom", circular)
        # square_size visibility delegated to the dedicated handler.
        self._on_ceo_sample_square_toggled(
            self._ceo_sample_square.isChecked())

    def _on_ceo_stratified_toggled(self, on):
        """Stratified ON  -> per-class row visible, single-N + domain
        rows hidden. Stratified OFF -> single-N + domain visible,
        per-class hidden.
        """
        self._set_ceo_row_visible("n_total", not on)
        self._set_ceo_row_visible("domain", not on)
        self._set_ceo_row_visible("n_per_class", on)

    def _on_ceo_sample_square_toggled(self, on):
        """Square size row is shown only when method = circular AND
        the 1-ha-square sample geometry is ticked."""
        circular = (self._ceo_method.currentIndex() == 1)
        self._set_ceo_row_visible("square_size", circular and on)

    def _on_generate_ceo_clicked(self):
        from ..algorithms.ceo_validation_export import (
            CeoValidationExportAlgorithm as A,
        )
        # Validate
        path = self._ceo_input.path()
        if not path:
            QMessageBox.warning(
                self, "Primary Forest Finder",
                "§8 requires an input vector layer.")
            return
        out_dir = self._ceo_output_folder.filePath()
        if not out_dir:
            QMessageBox.warning(
                self, "Primary Forest Finder",
                "§8 requires an output folder.")
            return
        cf = self._ceo_class_field.currentField() or "level"

        params = {
            A.INPUT: path,
            A.CLASS_FIELD: cf,
            A.PRIMARY_CLASS_VALUE: int(self._ceo_primary_value.value()),
            A.OTHER_CLASS_VALUE: int(self._ceo_other_value.value()),
            A.SAMPLING_DOMAIN: self._ceo_domain.currentIndex(),
            A.STRATIFIED: self._ceo_stratified.isChecked(),
            A.N_SAMPLES: int(self._ceo_n_total.value()),
            A.N_PRIMARY: int(self._ceo_n_primary.value()),
            A.N_OTHER: int(self._ceo_n_other.value()),
            A.MIN_DISTANCE: float(self._ceo_min_distance.value()),
            A.RANDOM_SEED: self._ceo_seed.text().strip(),
            A.EXPORT_METHOD: self._ceo_method.currentIndex(),
            A.PLOT_RADIUS_M: float(self._ceo_radius.value()),
            A.RING_WIDTH_M: float(self._ceo_ring_w.value()),
            A.SAMPLE_GEOM_POINT: self._ceo_sample_point.isChecked(),
            A.SAMPLE_GEOM_SQUARE: self._ceo_sample_square.isChecked(),
            A.SQUARE_SIZE_M: float(self._ceo_square_size.value()),
            A.OUTPUT_FOLDER: out_dir,
            A.OUTPUT_GEOPACKAGE: self._ceo_out_gpkg.isChecked(),
            A.OUTPUT_ZIPPED_SHAPEFILE: self._ceo_out_zip.isChecked(),
            A.REPROJECT_TO_WGS84: self._ceo_reproject_wgs84.isChecked(),
            A.ADD_PROVENANCE_FIELDS: self._ceo_provenance.isChecked(),
            A.ALLOW_EMPTY_STRATUM: False,
        }

        self._log.append(
            "<b>=== §8 CEO Validation Export (experimental) ===</b>")
        feedback = _DockFeedback(self._log, self._progress)
        ctx = self._make_processing_context(feedback)
        self._ceo_run_btn.setEnabled(False)
        try:
            try:
                processing.run("pff:ceo_validation_export", params,
                               context=ctx, feedback=feedback)
                self._log.append("<span style='color:#080;'>✔ "
                                 "CEO export complete.</span>")
                if self._add_main_to_map.isChecked():
                    self._add_outputs_to_project(ctx)
            except Exception as e:
                # Empty-stratum prompt: catch and offer to retry with
                # ALLOW_EMPTY_STRATUM=True.
                msg = str(e)
                if "Allow empty stratum" in msg:
                    ans = QMessageBox.question(
                        self, "Primary Forest Finder",
                        msg + "\n\nProceed without that class?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No)
                    if ans == QMessageBox.Yes:
                        params[A.ALLOW_EMPTY_STRATUM] = True
                        ctx2 = self._make_processing_context(feedback)
                        processing.run("pff:ceo_validation_export",
                                       params, context=ctx2,
                                       feedback=feedback)
                        if self._add_main_to_map.isChecked():
                            self._add_outputs_to_project(ctx2)
                        self._log.append("<span style='color:#080;'>✔ "
                                         "CEO export complete (with "
                                         "skipped class).</span>")
                    else:
                        self._log.append(
                            "<span style='color:#a00;'>"
                            "Aborted by user.</span>")
                else:
                    feedback.reportError(f"§8 failed: {e}")
        finally:
            self._ceo_run_btn.setEnabled(True)

    # ────────────────────────────────────────────────────────────────
    # Run flow
    # ────────────────────────────────────────────────────────────────
    def _validate(self):
        issues = []
        if not self._forest_raster.path():
            issues.append("Forest raster (§2) is required.")
        if not self._output_folder.filePath():
            issues.append("Output folder (§1) is required.")
        return issues

    def _collect_params(self) -> dict:
        params: dict = {}

        # §0 Study Area
        params[FW.AOI] = self._aoi_picker.path() or None
        params[FW.ISO3_PREFIX] = self._iso3_edit.text().strip()
        params[FW.OUTPUT_FOLDER] = self._output_folder.filePath()
        # P1.30 batch 20b.1: AUTO_UTM is deprecated. The dock never
        # ticks it; the algorithm ignores the parameter at run time.
        # Saved Recent runs that have AUTO_UTM=True still load (the
        # param is parsed and dropped) -- replay still works because
        # the algorithm now ignores it regardless.
        params[FW.AUTO_UTM] = False
        # P1.30 batch 20i: single chosen CRS feeds both algorithm params.
        # TARGET_CRS_EPSG (string) takes priority; TARGET_CRS (object)
        # mirrors it so the auto-Processing dialog also shows correctly
        # if the user replays via Processing > History.
        epsg = self._chosen_crs_epsg()
        if epsg is not None:
            params[FW.TARGET_CRS_EPSG] = str(epsg)
            params[FW.TARGET_CRS] = QgsCoordinateReferenceSystem(
                f"EPSG:{epsg}")
        elif self._chosen_crs is not None and self._chosen_crs.isValid():
            # Custom (non-EPSG) CRS — pass the object only.
            params[FW.TARGET_CRS_EPSG] = ""
            params[FW.TARGET_CRS] = self._chosen_crs
        else:
            params[FW.TARGET_CRS_EPSG] = ""
            params[FW.TARGET_CRS] = QgsCoordinateReferenceSystem()
        params[FW.AOI_BUFFER] = self._aoi_buffer.value()

        # §1 Time Period (single source of truth via _current_year_text)
        params[FW.YEAR] = self._current_year_text() or "2020"

        # §2 Tree Cover
        params[FW.FOREST_RASTER] = self._forest_raster.path()
        params[FW.FRA_AGRICULTURE_RASTER] = (
            self._olwtc_raster.path() or None)
        params[FW.EXCLUDE_AGRICULTURE_FROM_FOREST] = (
            self._olwtc_refine.isChecked())
        params[FW.PLANTATIONS_RASTER] = (
            self._planted_raster.path() or None)
        params[FW.EXCLUDE_PLANTATIONS] = self._planted_refine.isChecked()

        # §3 Human Influence -- drivers
        params[FW.ROADS] = self._roads_picker.vector_path() or None
        params[FW.ROADS_RASTER] = self._roads_picker.raster_path() or None
        params[FW.ENABLE_ROADS_BUFFER] = self._roads_enable.isChecked()
        params[FW.ROADS_DIST] = self._roads_buffer.value()

        params[FW.BUILTUP_SMALL_RASTER] = (
            self._builtup_small_picker.path() or None)
        params[FW.ENABLE_BUILTUP_SMALL_BUFFER] = (
            self._builtup_small_enable.isChecked())
        params[FW.BUILTUP_DIST] = self._builtup_small_buffer.value()

        params[FW.BUILTUP_LARGE_RASTER] = (
            self._builtup_large_picker.path() or None)
        params[FW.ENABLE_BUILTUP_LARGE_BUFFER] = (
            self._builtup_large_enable.isChecked())
        params[FW.BUILTUP_LARGE_DIST] = self._builtup_large_buffer.value()

        params[FW.AGRICULTURE_RASTER] = (
            self._agriculture_picker.path() or None)
        params[FW.ENABLE_AGRICULTURE_BUFFER] = (
            self._agriculture_enable.isChecked())
        params[FW.AGRICULTURE_DIST] = self._agriculture_buffer.value()

        params[FW.USE_SINGLE_DISTANCE] = self._use_single_buffer.isChecked()
        params[FW.ALL_BUFFERS_DIST] = self._master_buffer.value()
        params[FW.MAX_DISTANCE] = self._max_distance.value()

        # Buffer exceptions
        params[FW.DEM] = self._dem_slope_picker.dem_path() or None
        params[FW.SLOPE_RASTER] = (
            self._dem_slope_picker.slope_path() or None)
        params[FW.PROTECTED_AREAS] = (
            self._protected_picker.vector_path() or None)
        params[FW.PROTECTED_RASTER] = (
            self._protected_picker.raster_path() or None)
        params[FW.SLOPE_THRESHOLD] = self._slope_threshold.value()

        # Custom drivers
        for i, (sec_w, label, picker, buf) in enumerate(
                self._custom_sections, start=1):
            r_const = getattr(FW, f"CUSTOM_{i}_RASTER")
            l_const = getattr(FW, f"CUSTOM_{i}_LABEL")
            d_const = getattr(FW, f"CUSTOM_{i}_DIST")
            if self._enable_custom.isChecked() and picker.path():
                params[r_const] = picker.path()
                params[l_const] = label.text() or f"Custom disturbance {i}"
                params[d_const] = buf.value()
            else:
                params[r_const] = None
                params[l_const] = label.text() or f"Custom disturbance {i}"
                params[d_const] = buf.value()

        # §4 Refine Output
        params[FW.ENABLE_REFINE_OUTPUT] = self._enable_refine.isChecked()
        params[FW.SMOOTH_RADIUS] = self._smooth_radius.value()
        params[FW.DENSITY_THRESHOLD] = self._density_threshold.value()
        params[FW.FAST_APPROXIMATION] = self._fast_approx.isChecked()
        params[FW.REFINE_MIN_PATCH_AREA_HA] = self._refine_min_patch.value()

        # §5 Area Statistics
        params[FW.RUN_ZONAL_STATS] = self._run_zonal.isChecked()
        params[FW.ZONE_LAYER] = self._zone_layer_combo.path() or None
        params[FW.ZONE_FIELD] = self._zone_field.currentField() or None

        # §6 Vectorise Outputs
        params[FW.VECTORIZE_PRIMARY] = self._vec_primary.isChecked()
        params[FW.VECTORIZE_FOREST] = self._vec_forest.isChecked()
        params[FW.VECTORIZE_NEST] = self._vec_nest.isChecked()
        # Dissolve only meaningful when nest is on; force False otherwise
        # so the algorithm doesn't bother even if the box was left ticked.
        params[FW.VECTORIZE_DISSOLVE_MULTIPART] = (
            self._vec_nest.isChecked()
            and self._vec_dissolve.isChecked())
        params[FW.VECTORIZE_SIMPLIFY_M] = self._vec_simplify.value()
        params[FW.VECTORIZE_MIN_PATCH_AREA_HA] = self._vec_min_patch_ha.value()
        params[FW.VECTORIZE_REMOVE_PIXEL_STAIRS] = (
            self._vec_remove_pixel_stairs.isChecked())
        params[FW.VECTORIZE_OUTPUT_AS_SHAPEFILE] = self._vec_as_shp.isChecked()

        # §7 Run Options
        # P1.30 batch 22: per-layer Save flags.
        params[FW.SAVE_02B_FOREST] = (
            self._save_checkboxes["save_02b_forest"].isChecked())
        params[FW.SAVE_02D_NRF] = (
            self._save_checkboxes["save_02d_nrf"].isChecked())
        params[FW.SAVE_03C_PRE_CONN] = (
            self._save_checkboxes["save_03c_pre_conn"].isChecked())
        params[FW.SAVE_04A_PRIMARY] = (
            self._save_checkboxes["save_04a_primary"].isChecked())
        params[FW.SAVE_04E_ANTHRO_MASK] = (
            self._save_checkboxes["save_04e_anthro_mask"].isChecked())
        # P1.30 batch 22.1: SAVE_COMBINED_RASTER tickbox removed from
        # the dock; default to False here. Param is still registered
        # on the algorithm so toolbox users / saved Recent runs still
        # work.
        params[FW.SAVE_COMBINED_RASTER] = False
        params[FW.REUSE_DISTANCE_SURFACES] = self._reuse_distance.isChecked()
        params[FW.REUSE_PREPARED] = self._reuse_prepared.isChecked()
        params[FW.ADD_MAIN_OUTPUTS_TO_MAP] = (
            self._add_main_to_map.isChecked())
        params[FW.ADD_HUMAN_INFLUENCE_LAYERS_TO_MAP] = (
            self._add_human_layers_to_map.isChecked())

        return params

    def _on_run_or_cancel_clicked(self):
        """Single click handler — branches on running state."""
        if self._is_running:
            self._on_cancel_clicked()
        else:
            self._on_run_clicked()

    def _on_cancel_clicked(self):
        if self._active_feedback is None:
            return
        ans = QMessageBox.question(
            self, "Primary Forest Finder",
            "Cancel the running workflow? "
            "Partial outputs may be left on disk.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        self._active_feedback.pushWarning("Cancellation requested by user…")
        self._active_feedback.cancel()

    def _enter_running_state(self):
        self._is_running = True
        self._run_btn.setText("Cancel ✖")
        self._run_btn.setEnabled(True)

    def _leave_running_state(self):
        self._is_running = False
        self._active_feedback = None
        self._run_btn.setText("Run Workflow ▶")
        self._run_btn.setEnabled(True)

    def _on_run_clicked(self):
        issues = self._validate()
        if issues:
            QMessageBox.warning(
                self, "Primary Forest Finder",
                "Cannot run yet:\n\n• " + "\n• ".join(issues))
            return

        self._log.clear()
        self._progress.setValue(0)

        params = self._collect_params()
        # Persist the run BEFORE invoking processing.run so the entry
        # is preserved even if the run fails or is cancelled.
        self._active_history_index = self._record_run_history(
            params, status="started")
        self._refresh_recent_combo()

        feedback = _DockFeedback(self._log, self._progress)
        self._active_feedback = feedback
        self._enter_running_state()

        # P1.30 batch 20d: parse YEAR as comma-separated list. Single
        # year (or "all") runs once as before. Multi-year runs the
        # workflow once per year, substituting year-varying input
        # paths between iterations.
        from ..utils_year_iter import parse_year_list
        year_list = parse_year_list(params.get(FW.YEAR, "") or "")

        status = "failed"
        try:
            if len(year_list) > 1 and "all" not in year_list:
                self._run_multi_year(params, year_list, feedback)
                status = ("cancelled" if feedback.isCanceled()
                          else "finished")
            else:
                feedback.pushInfo("Starting workflow…")
                QApplication.processEvents()
                # P1.30 batch 20j: project-bound context so the
                # algorithm's addLayerToLoadOnCompletion list can be
                # harvested + loaded with PFF symbology.
                ctx = self._make_processing_context(feedback)
                processing.run("pff:full_workflow", params,
                               context=ctx, feedback=feedback)
                if feedback.isCanceled():
                    status = "cancelled"
                    feedback.pushWarning("⚠ Workflow cancelled by user.")
                else:
                    status = "finished"
                    feedback.pushInfo("✔ Workflow finished.")
                    self._add_outputs_to_project(ctx)
        except Exception as e:
            if feedback.isCanceled():
                status = "cancelled"
                feedback.pushWarning(
                    f"⚠ Workflow cancelled by user ({e}).")
            else:
                status = "failed"
                feedback.reportError(f"Workflow failed: {e}")
        finally:
            self._leave_running_state()
            if status == "finished":
                self._progress.setValue(100)
            self._progress.repaint()
            self._update_history_status(self._active_history_index, status)
            self._refresh_recent_combo()
            self._active_history_index = None
            if status == "finished":
                self._record_qgis_history(params)

    def _run_multi_year(self, base_params, year_list, feedback):
        """Iterate the workflow once per year in `year_list`, with
        year-varying input paths substituted between runs.

        Anchor year = first year in the list. Inputs whose filenames
        contain the anchor year token get substituted for each target
        year via filename glob. Inputs without a year token (DEM,
        slope, protected, AOI vector) are passed through unchanged.
        """
        from ..utils_year_iter import build_year_paths

        # The set of param names whose values are file paths we want
        # to consider for year substitution. Output folder + ISO3 +
        # numeric params are skipped.
        path_param_names = [
            FW.FOREST_RASTER, FW.AOI, FW.FRA_AGRICULTURE_RASTER,
            FW.PLANTATIONS_RASTER, FW.ROADS, FW.ROADS_RASTER,
            FW.BUILTUP_SMALL_RASTER, FW.BUILTUP_LARGE_RASTER,
            FW.AGRICULTURE_RASTER, FW.DEM, FW.SLOPE_RASTER,
            FW.PROTECTED_AREAS, FW.PROTECTED_RASTER,
            FW.CUSTOM_1_RASTER, FW.CUSTOM_2_RASTER, FW.CUSTOM_3_RASTER,
            FW.ZONE_LAYER,
        ]

        anchor_year = year_list[0]
        feedback.pushInfo(
            f"=== Multi-year run: {len(year_list)} years "
            f"({', '.join(year_list)}) ===")
        feedback.pushInfo(f"Anchor year: {anchor_year}")

        # Pre-flight: resolve every (year, input) cell so the user
        # sees what's about to happen BEFORE iterating.
        feedback.pushInfo("\n--- Per-year input availability ---")
        per_year_resolved = {}
        for year in year_list:
            resolved = build_year_paths(
                [(name, base_params.get(name) or "")
                 for name in path_param_names],
                anchor_year, year)
            per_year_resolved[year] = resolved
            missing = [k for k, v in resolved.items()
                       if v["status"] == "missing"]
            feedback.pushInfo(f"  Year {year}:")
            for label, info in resolved.items():
                # 20e hotfix: skip "empty" silently. "empty" means the
                # user didn't set this param (e.g. ROADS vector when
                # they used ROADS_RASTER instead). Not a missing-file.
                if info["status"] in ("static", "anchor", "empty"):
                    continue
                if info["status"] == "missing":
                    feedback.pushWarning(
                        f"    [missing] {label}: no file matching "
                        f"year={year} found in same folder")
                else:
                    feedback.pushInfo(
                        f"    [{info['status']}] {label}: "
                        f"{os.path.basename(info['path'])}")

        # Confirm with user if any year has missing inputs.
        missing_years = [
            y for y, r in per_year_resolved.items()
            if any(v["status"] == "missing" for v in r.values())
        ]
        if missing_years:
            ans = QMessageBox.question(
                self, "Primary Forest Finder",
                f"Some inputs are missing for year(s): "
                f"{', '.join(missing_years)}.\n\n"
                "Skip those years and continue with the rest? "
                "(Choose No to abort the whole run.)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes)
            if ans != QMessageBox.Yes:
                feedback.pushWarning("⚠ Multi-year run aborted by user.")
                feedback.cancel()
                return
            year_list = [y for y in year_list if y not in missing_years]
            if not year_list:
                feedback.pushWarning(
                    "⚠ No years remaining after skipping missing. "
                    "Nothing to run.")
                return

        # Iterate.
        for i, year in enumerate(year_list, start=1):
            if feedback.isCanceled():
                feedback.pushWarning(
                    f"⚠ Cancelled before year {year}.")
                return
            feedback.pushInfo(
                f"\n=== YEAR {year} ({i} of {len(year_list)}) ===")
            QApplication.processEvents()
            year_params = dict(base_params)
            resolved = per_year_resolved[year]
            for name, info in resolved.items():
                if info["status"] == "empty":
                    # User didn't set this param; leave whatever was
                    # in base_params (probably None) untouched.
                    continue
                if info["status"] in ("matched", "ambiguous", "static",
                                      "anchor"):
                    if info["path"]:
                        year_params[name] = info["path"]
                    else:
                        year_params[name] = base_params.get(name)
            year_params[FW.YEAR] = year
            try:
                # P1.30 batch 20j: per-iteration project-bound context
                # so each year's outputs land in the project as that
                # year completes (with PFF symbology applied).
                ctx = self._make_processing_context(feedback)
                processing.run("pff:full_workflow", year_params,
                               context=ctx, feedback=feedback)
                if feedback.isCanceled():
                    feedback.pushWarning(
                        f"⚠ Cancelled during year {year}.")
                    return
                self._add_outputs_to_project(ctx)
            except Exception as e:
                if feedback.isCanceled():
                    feedback.pushWarning(
                        f"⚠ Cancelled during year {year} ({e}).")
                    return
                feedback.reportError(
                    f"Year {year} failed: {e}. Continuing with "
                    "remaining years.")
        feedback.pushInfo(
            f"\n✔ Multi-year run complete ({len(year_list)} years).")

    # ────────────────────────────────────────────────────────────────
    # P1.30 batch 20j: project-bound context + add-to-map helpers
    # ────────────────────────────────────────────────────────────────
    def _make_processing_context(self, feedback) -> QgsProcessingContext:
        """Build a project-bound QgsProcessingContext for one run.

        The dock's processing.run() calls have to pass a context bound
        to the active QgsProject so the algorithm's
        addLayerToLoadOnCompletion list can be harvested and loaded
        post-run. Without setProject(), the algorithm's registrations
        land on a detached context that gets discarded.
        """
        ctx = QgsProcessingContext()
        ctx.setFeedback(feedback)
        ctx.setProject(QgsProject.instance())
        return ctx

    def _add_outputs_to_project(self, ctx) -> None:
        """Walk ctx.layersToLoadOnCompletion() and add each layer to
        the project, applying PFF symbology to recognised binary
        rasters.

        Called after a successful processing.run() from the dock.
        Tolerates missing files / invalid layers silently -- a single
        bad entry shouldn't stop the rest from loading.
        """
        try:
            details_map = ctx.layersToLoadOnCompletion() or {}
        except Exception as e:
            self._log.append(
                f"<span style='color:#888;'>(add-to-map skipped: "
                f"{_html_escape(str(e))})</span>")
            return
        if not details_map:
            return
        loaded = 0
        for path, details in details_map.items():
            try:
                if not path or not os.path.exists(path):
                    continue
                name = (getattr(details, "name", None) or "").strip() \
                    or os.path.splitext(os.path.basename(path))[0]
                ext = os.path.splitext(path)[1].lower()
                if ext in (".gpkg", ".shp", ".geojson", ".kml", ".gml"):
                    layer = QgsVectorLayer(path, name, "ogr")
                else:
                    layer = QgsRasterLayer(path, name)
                if not layer.isValid():
                    continue
                apply_pff_symbology(layer, path)
                QgsProject.instance().addMapLayer(layer)
                loaded += 1
            except Exception as e:
                self._log.append(
                    f"<span style='color:#888;'>(skipped "
                    f"{_html_escape(os.path.basename(path or ''))}: "
                    f"{_html_escape(str(e))})</span>")
        if loaded:
            self._log.append(
                f"<span>Added {loaded} layer(s) to the map "
                "with PFF symbology.</span>")

    # ────────────────────────────────────────────────────────────────
    # Run history
    # ────────────────────────────────────────────────────────────────
    def _record_run_history(self, params: dict, status: str = "started"):
        """Persist a run attempt to the dock-local history JSON.

        Called at Run-click (status="started"), then updated to
        "finished" / "failed" / "cancelled" via _update_history_status
        once the run ends. Returns the new entry's index (always 0
        because we insert at the head) so the caller can update it.
        """
        try:
            entries = self._load_history()
            from datetime import datetime
            # P1.30 batch 20i: capture the chosen CRS at top level so
            # _recent_target_crses() can read it without parsing every
            # entry's full params blob. Prefer EPSG, fall back to authid.
            crs_str = ""
            epsg_val = (params.get(FW.TARGET_CRS_EPSG) or "").strip()
            if epsg_val:
                try:
                    crs_str = f"EPSG:{int(epsg_val)}"
                except (ValueError, TypeError):
                    pass
            if not crs_str:
                tc = params.get(FW.TARGET_CRS)
                if isinstance(tc, QgsCoordinateReferenceSystem):
                    crs_str = tc.authid() or ""
                elif isinstance(tc, str):
                    crs_str = tc
            entry = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "iso3": params.get(FW.ISO3_PREFIX, "") or "",
                "output": params.get(FW.OUTPUT_FOLDER, "") or "",
                "target_crs": crs_str,
                "status": status,
                "params": _serialise_params(params),
            }
            entries.insert(0, entry)
            entries = entries[:_HISTORY_MAX_ENTRIES]
            with open(_history_path(), "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, default=str)
            return 0
        except Exception as e:
            self._log.append(
                f"<span style='color:#888;'>"
                f"(History write failed: {_html_escape(str(e))})</span>")
            return None

    def _update_history_status(self, idx, status: str):
        """Mark a previously-recorded entry with the final status."""
        if idx is None:
            return
        try:
            entries = self._load_history()
            if 0 <= idx < len(entries):
                entries[idx]["status"] = status
                with open(_history_path(), "w", encoding="utf-8") as f:
                    json.dump(entries, f, indent=2, default=str)
        except Exception:
            pass

    def _record_qgis_history(self, params: dict):
        """Best-effort: log a successful run to QGIS Processing History."""
        try:
            from qgis.gui import QgsGui
            from qgis.core import QgsHistoryEntry
            registry = QgsGui.historyProviderRegistry()
            alg = QgsApplication.processingRegistry().algorithmById(
                "pff:full_workflow")
            if alg is None or registry is None:
                return
            cmd = alg.asPythonCommand(_serialise_params(params), None)
            entry_data = {
                "python_command": cmd,
                "algorithm_id": "pff:full_workflow",
                "parameters": _serialise_params(params),
            }
            history_entry = QgsHistoryEntry("processing", entry_data)
            registry.addEntry(history_entry)
        except Exception:
            # Older QGIS releases don't have the history-provider API.
            pass

    def _load_history(self) -> list:
        try:
            with open(_history_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return []

    def _refresh_recent_combo(self):
        self._recent_combo.blockSignals(True)
        self._recent_combo.clear()
        self._recent_combo.addItem("Recent runs ▾", None)
        for i, entry in enumerate(self._load_history()[:10]):
            iso3 = entry.get("iso3") or "—"
            ts = entry.get("timestamp", "")
            short_ts = ts.replace("T", " ")[:16] if ts else ""
            status = entry.get("status", "")
            prefix = ""
            if status in ("failed", "cancelled"):
                prefix = "✖ "
            elif status == "started":
                prefix = "… "  # in-progress (or interrupted by QGIS quit)
            label = f"{prefix}{iso3} • {short_ts}"
            self._recent_combo.addItem(label, i)
        self._recent_combo.blockSignals(False)

    def _on_recent_picked(self, idx: int):
        if idx <= 0:
            return
        history_idx = self._recent_combo.itemData(idx)
        if history_idx is None:
            return
        try:
            entries = self._load_history()
            entry = entries[history_idx]
            self._apply_params(entry.get("params", {}))
            self._log.append(
                f"<span style='color:#666;'>(Restored params from "
                f"{entry.get('timestamp', '?')} • {entry.get('iso3') or '—'}"
                f")</span>")
        except Exception as e:
            QMessageBox.warning(
                self, "PFF",
                f"Could not restore that run: {e}")

    def _apply_params(self, p: dict):
        """Set every dock widget from a saved params dict.

        Skips missing keys silently (older history entries may lack new
        params added in later versions).
        """
        def s(key, default=""):
            return p.get(key, default) or default
        def b(key, default=False):
            v = p.get(key)
            return bool(v) if v is not None else default
        def n(key, default=0):
            v = p.get(key)
            try:
                return float(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        # §0
        self._aoi_picker.set_path(s(FW.AOI))
        self._iso3_edit.setText(s(FW.ISO3_PREFIX))
        self._output_folder.setFilePath(s(FW.OUTPUT_FOLDER))
        # P1.30 batch 20b.1: AUTO_UTM is deprecated and the dock no
        # longer has a checkbox for it. Saved values are ignored.
        # P1.30 batch 20i: restore _chosen_crs from saved EPSG (preferred)
        # or QgsCoordinateReferenceSystem authid string. Empty / unset =
        # leave the dock with no chosen CRS so the user must pick again.
        self._chosen_crs = None
        self._chosen_crs_label = ""
        crs_epsg_str = s(FW.TARGET_CRS_EPSG)
        crs_str = s(FW.TARGET_CRS)  # may be authid like "EPSG:5266"
        if crs_epsg_str:
            try:
                self._set_chosen_crs_from_epsg(int(crs_epsg_str))
            except (TypeError, ValueError):
                pass
        elif crs_str:
            try:
                crs = QgsCoordinateReferenceSystem(str(crs_str))
                if crs.isValid():
                    self._set_chosen_crs(crs)
            except Exception:
                pass
        self._rebuild_crs_combo()
        self._aoi_buffer.setValue(n(FW.AOI_BUFFER))

        # §1 Time Period — restore mode based on the saved YEAR value.
        year_val = s(FW.YEAR, "2020") or "2020"
        is_all = (year_val == "all")
        is_multi = ("," in year_val)
        self._year_all_since_2000.setChecked(is_all)
        if is_multi:
            self._multi_year_chk.setChecked(True)
            self._year_multi_edit.setText(year_val)
        else:
            self._multi_year_chk.setChecked(False)
            if not is_all:
                idx = self._year_single_combo.findText(year_val)
                if idx >= 0:
                    self._year_single_combo.setCurrentIndex(idx)
                else:
                    self._year_single_combo.setCurrentText("2020")
        self._year_stack.setEnabled(not is_all)

        # §2
        self._forest_raster.set_path(s(FW.FOREST_RASTER))
        self._olwtc_raster.set_path(s(FW.FRA_AGRICULTURE_RASTER))
        self._olwtc_refine.setChecked(b(FW.EXCLUDE_AGRICULTURE_FROM_FOREST,
                                        True))
        self._planted_raster.set_path(s(FW.PLANTATIONS_RASTER))
        self._planted_refine.setChecked(b(FW.EXCLUDE_PLANTATIONS, True))

        # §3
        self._roads_picker.set_path(
            s(FW.ROADS_RASTER) or s(FW.ROADS))
        self._roads_enable.setChecked(b(FW.ENABLE_ROADS_BUFFER, True))
        self._roads_buffer.setValue(n(FW.ROADS_DIST, 1500))
        self._builtup_small_picker.set_path(s(FW.BUILTUP_SMALL_RASTER))
        self._builtup_small_enable.setChecked(
            b(FW.ENABLE_BUILTUP_SMALL_BUFFER, True))
        self._builtup_small_buffer.setValue(n(FW.BUILTUP_DIST, 1500))
        self._builtup_large_picker.set_path(s(FW.BUILTUP_LARGE_RASTER))
        self._builtup_large_enable.setChecked(
            b(FW.ENABLE_BUILTUP_LARGE_BUFFER, True))
        self._builtup_large_buffer.setValue(n(FW.BUILTUP_LARGE_DIST, 2500))
        self._agriculture_picker.set_path(s(FW.AGRICULTURE_RASTER))
        self._agriculture_enable.setChecked(
            b(FW.ENABLE_AGRICULTURE_BUFFER, True))
        self._agriculture_buffer.setValue(n(FW.AGRICULTURE_DIST, 1000))
        self._use_single_buffer.setChecked(b(FW.USE_SINGLE_DISTANCE))
        self._master_buffer.setValue(n(FW.ALL_BUFFERS_DIST, 1000))
        self._max_distance.setValue(n(FW.MAX_DISTANCE, 20000))

        # Buffer exceptions
        if s(FW.SLOPE_RASTER):
            self._dem_slope_picker.set_path(s(FW.SLOPE_RASTER), kind="slope")
        elif s(FW.DEM):
            self._dem_slope_picker.set_path(s(FW.DEM), kind="dem")
        else:
            self._dem_slope_picker.clear()
        self._slope_threshold.setValue(n(FW.SLOPE_THRESHOLD, 30))
        self._protected_picker.set_path(
            s(FW.PROTECTED_RASTER) or s(FW.PROTECTED_AREAS))

        # Custom slots
        any_custom = False
        for i, (sec_w, label, picker, buf) in enumerate(
                self._custom_sections, start=1):
            r_const = getattr(FW, f"CUSTOM_{i}_RASTER")
            l_const = getattr(FW, f"CUSTOM_{i}_LABEL")
            d_const = getattr(FW, f"CUSTOM_{i}_DIST")
            picker.set_path(s(r_const))
            label.setText(s(l_const) or f"Custom disturbance {i}")
            buf.setValue(n(d_const, 1000))
            if s(r_const):
                any_custom = True
        self._enable_custom.setChecked(any_custom)
        self._on_enable_custom_toggled(any_custom)

        # §4
        self._enable_refine.setChecked(b(FW.ENABLE_REFINE_OUTPUT, True))
        self._smooth_radius.setValue(n(FW.SMOOTH_RADIUS, 1500))
        self._density_threshold.setValue(n(FW.DENSITY_THRESHOLD, 0.5))
        self._fast_approx.setChecked(b(FW.FAST_APPROXIMATION))
        self._refine_min_patch.setValue(n(FW.REFINE_MIN_PATCH_AREA_HA))

        # §5
        self._run_zonal.setChecked(b(FW.RUN_ZONAL_STATS))
        self._zone_layer_combo.set_path(s(FW.ZONE_LAYER))
        # Field combo is repopulated by the layer change signal.

        # §6
        self._vec_primary.setChecked(b(FW.VECTORIZE_PRIMARY))
        self._vec_forest.setChecked(b(FW.VECTORIZE_FOREST))
        self._vec_nest.setChecked(b(FW.VECTORIZE_NEST))
        self._vec_dissolve.setChecked(b(FW.VECTORIZE_DISSOLVE_MULTIPART, True))
        self._vec_simplify.setValue(n(FW.VECTORIZE_SIMPLIFY_M))
        self._vec_min_patch_ha.setValue(n(FW.VECTORIZE_MIN_PATCH_AREA_HA))
        self._vec_remove_pixel_stairs.setChecked(
            b(FW.VECTORIZE_REMOVE_PIXEL_STAIRS, True))
        self._vec_as_shp.setChecked(b(FW.VECTORIZE_OUTPUT_AS_SHAPEFILE))

        # §7
        # P1.30 batch 22: per-layer Save flags. Defaults match the
        # historical de-facto behaviour for entries saved before this
        # batch (ie. defaults pre-set; old run replays produce the
        # same on-disk artefacts as they always did).
        self._save_checkboxes["save_02b_forest"].setChecked(
            b(FW.SAVE_02B_FOREST, True))
        self._save_checkboxes["save_02d_nrf"].setChecked(
            b(FW.SAVE_02D_NRF, True))
        self._save_checkboxes["save_03c_pre_conn"].setChecked(
            b(FW.SAVE_03C_PRE_CONN, False))
        self._save_checkboxes["save_04a_primary"].setChecked(
            b(FW.SAVE_04A_PRIMARY, True))
        self._save_checkboxes["save_04e_anthro_mask"].setChecked(
            b(FW.SAVE_04E_ANTHRO_MASK, False))
        self._refresh_save_summary()
        # P1.30 batch 22.1: SAVE_COMBINED_RASTER tickbox removed; nothing
        # to restore on the dock side. Saved value is still in params
        # dict (preserved through _record_run_history) for fidelity.
        self._reuse_distance.setChecked(b(FW.REUSE_DISTANCE_SURFACES))
        self._reuse_prepared.setChecked(b(FW.REUSE_PREPARED, True))
        self._add_main_to_map.setChecked(b(FW.ADD_MAIN_OUTPUTS_TO_MAP, True))
        self._add_human_layers_to_map.setChecked(
            b(FW.ADD_HUMAN_INFLUENCE_LAYERS_TO_MAP))

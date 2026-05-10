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
import re

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


# Tree-cover input-category options. Colon separates the FRA category
# name from the short description. Tooltips (set in
# _build_section_2_tree_cover) provide dataset-focused detail + FRA
# definition on hover. The dropdown drives:
#   1. visibility of OLWTC + Planted-forest sub-controls
#   2. the EXCLUDE_AGRICULTURE_FROM_FOREST + EXCLUDE_PLANTATIONS booleans
INPUT_CATEGORY_TREECOVER = (
    "Tree cover: includes oil palm, orchards, agroforestry etc")
INPUT_CATEGORY_FOREST = (
    "Forest: excludes other land with tree cover e.g. oil palm, "
    "orchards, agroforestry etc")
INPUT_CATEGORY_NRF = (
    "Naturally regenerating forest: also excludes planted forest")
INPUT_CATEGORY_PRIMARY = (
    "Primary forest: for comparison / further analysis")


# Path for the dock-local recent-runs history file. Lives under the
# QGIS profile dir so it persists across sessions but is per-profile.
def _history_path() -> str:
    base = QgsApplication.qgisSettingsDirPath()
    pff_dir = os.path.join(base, "PFF")
    os.makedirs(pff_dir, exist_ok=True)
    return os.path.join(pff_dir, "run_history.json")


_HISTORY_MAX_ENTRIES = 50

INPUT_CATEGORY_PLACEHOLDER = "— Select one —"

INPUT_CATEGORY_ITEMS = [
    INPUT_CATEGORY_TREECOVER,
    INPUT_CATEGORY_FOREST,
    INPUT_CATEGORY_NRF,
    INPUT_CATEGORY_PRIMARY,
]


class _DockFeedback(QgsProcessingFeedback):
    """Pipes algorithm log lines into the dock's log QTextEdit.

    Batch 28.6: also accumulates warnings/errors into a categorised
    ledger so the dock can print an end-of-run summary (resolved
    auto-recoveries / skipped steps / quality concerns / other).
    Long algorithm logs scroll past the user; the summary surfaces
    what's worth attention.
    """

    def __init__(self, log_widget: QTextEdit, progress_bar: QProgressBar):
        super().__init__()
        self._log = log_widget
        self._pb = progress_bar
        self.progressChanged.connect(self._on_progress)
        # Ledger entries: (severity, message). Severity is one of
        # "resolved" / "skipped" / "concern" / "warning" / "error".
        self._ledger = []

    def _append(self, html: str):
        self._log.moveCursor(QTextCursor.End)
        self._log.insertHtml(html + "<br>")
        self._log.moveCursor(QTextCursor.End)
        # processing.run() blocks the GUI thread while the algorithm
        # runs, so without a manual processEvents() pump the log
        # appears empty until the run finishes. Pump after every line
        # so users see progress in real time.
        QApplication.processEvents()

    @staticmethod
    def _categorize(msg: str) -> str:
        """Bucket a warning/error message into a summary severity."""
        m = msg.lower()
        # Special-case messages that come through reportError but are
        # actually pre-emptive notices the workflow auto-handles.
        # E.g. "Layer X uses geographic CRS" -- the next line is
        # always "Reprojecting X..." in our pipeline, so this isn't
        # fatal even though it has the red ✖ icon inline.
        for kw in (
                "uses geographic crs",
                "requires a projected crs",
                "distance calculations require a projected crs"):
            if kw in m:
                return "resolved"
        # Resolved: auto-handled by the plugin (fallback / reproj /
        # auto-tick). Worth noting but not actionable.
        for kw in (
                "falling back", "fall back to ", "fallback ok", "fallback",
                "reprojecting ", "reprojected ",
                "auto-ticked", "auto-tick", "auto-fill",
                "✔ fallback"):
            if kw in m:
                return "resolved"
        # Skipped: a step did not run, output missing.
        for kw in (
                "skipping ", "skipped",
                "could not find", "did not produce",
                "missing for year", "missing roads", "missing forest",
                "no 06c", "stage 6", "auto-validation"):
            if kw in m:
                return "skipped"
        # Output-quality concern: something is potentially wrong with
        # what's being computed.
        for kw in (
                "wrong sub-slot", "likely wrong sub-slot",
                "outlier ", "mismatch",
                "different year", "different iso3",
                "single-year mismatch"):
            if kw in m:
                return "concern"
        return "warning"

    def _consolidate_ledger(self):
        """Retroactive downgrade pass: an "Algorithm X not found"
        error that is followed by a "Fallback OK" / "falling back"
        entry should be re-categorised as resolved -- the run handled
        it. Same for any "Error:" line that has a matching resolution
        downstream. Returns a new ledger list; doesn't mutate.
        """
        out = []
        for i, (sev, msg) in enumerate(self._ledger):
            if sev == "error":
                m_low = msg.lower()
                # Algorithm-not-found / missing-method patterns --
                # check for any later "fallback" entry that resolved it.
                if (("algorithm" in m_low and "not found" in m_low)
                        or "no attribute" in m_low
                        or "writeasvectorformat" in m_low):
                    for sev2, msg2 in self._ledger[i + 1:]:
                        m2 = msg2.lower()
                        if ("fallback ok" in m2
                                or "falling back" in m2
                                or "fall back to " in m2):
                            sev = "resolved"
                            msg = (msg.rstrip() +
                                   " [resolved by fallback below]")
                            break
                # Geographic-CRS pattern -- workflow always reprojects
                # right after, so look for a "Reprojecting" / "Aligning"
                # info line as the resolution marker.
                elif ("geographic crs" in m_low
                        or "projected crs" in m_low):
                    for sev2, msg2 in self._ledger[i + 1:]:
                        m2 = msg2.lower()
                        if (m2.startswith("reprojecting ")
                                or m2.startswith("aligning ")
                                or "reprojected " in m2):
                            sev = "resolved"
                            msg = (msg.rstrip() +
                                   " [resolved by reprojection below]")
                            break
            out.append((sev, msg))
        return out

    def pushInfo(self, info: str):
        # "✔ Fallback OK" style lines come through pushInfo; track them
        # too so the summary acknowledges resolved cases.
        if info.startswith("✔ Fallback") or "fallback ok" in info.lower():
            self._ledger.append(("resolved", info))
        self._append(f"<span>{_html_escape(info)}</span>")

    def pushDebugInfo(self, info: str):
        self._append(
            f"<span style='color:#888;'>{_html_escape(info)}</span>")

    def pushWarning(self, info: str):
        self._ledger.append((self._categorize(info), info))
        self._append(
            f"<span style='color:#b8860b;'>⚠ {_html_escape(info)}</span>")

    def reportError(self, error: str, fatalError: bool = False):
        # Run the categorizer first so known-handled patterns
        # (geographic CRS / projected CRS reminder, fallback markers)
        # don't get hard-tagged as fatal errors. Anything the
        # categorizer doesn't recognise stays as "error".
        sev = self._categorize(error)
        if sev == "warning":
            sev = "error"
        self._ledger.append((sev, error))
        # The visual ✖ icon stays even for downgraded entries -- the
        # log line was already printed before this categorisation
        # happened, and we want the user to see "the workflow logged
        # this as an error originally". The end-of-run summary
        # bucketing is the reliable signal of resolution.
        self._append(
            f"<span style='color:#a00;'>✖ {_html_escape(error)}</span>")

    def _on_progress(self, value: float):
        self._pb.setValue(int(value))
        QApplication.processEvents()

    def print_summary(self):
        """Emit a categorised end-of-run summary of accumulated
        warnings/errors. Called by the dock after processing.run()
        returns. No-op when the ledger is empty."""
        if not self._ledger:
            return
        # Run the retroactive consolidation pass first so known-handled
        # cases (algorithm-not-found + matching fallback) get
        # downgraded out of the Errors bucket.
        consolidated = self._consolidate_ledger()
        bucket = {}
        for sev, msg in consolidated:
            bucket.setdefault(sev, []).append(msg)
        sections = (
            ("error",    "Errors (fatal -- run did not finish cleanly)", "✖"),
            ("concern",  "Output-quality concerns (worth checking)",     "⚠"),
            ("skipped",  "Steps skipped or outputs missing",             "⚠"),
            ("resolved", "Resolved automatically (informational)",       "✔"),
            ("warning",  "Other warnings",                                "⚠"),
        )
        self._append("<br><b>=== Run summary ===</b>")
        empty = True
        for sev, label, icon in sections:
            items = bucket.get(sev, [])
            if not items:
                continue
            empty = False
            self._append(
                f"<b>{icon} {_html_escape(label)} ({len(items)})</b>")
            # Cap each entry for log readability
            for m in items:
                clipped = m if len(m) <= 220 else m[:217] + "…"
                self._append(
                    f"<span style='margin-left:1em;'>"
                    f"&nbsp;&nbsp;&bull; {_html_escape(clipped)}</span>")
        if empty:
            self._append(
                "<span style='color:#888;'>"
                "(no warnings, errors, or auto-recoveries to report)"
                "</span>")


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
            f"<span style='font-size:15px; font-weight:bold;'>Primary Forest Finder</span> "
            f"<span style='font-size:12px; color:#666;'>v{FW.PFF_VERSION}</span>")
        version_label.setStyleSheet("padding: 4px 0;")
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
        self._build_section_5_area_statistics()
        self._build_section_6_outputs()
        self._build_section_7_validation()
        self._build_section_config()
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

        # Run controls. Two rows so the dock stays narrow-friendly:
        #   row 1: Run Workflow ▶ (stretch) + ↺ (icon-only reset)
        #   row 2: Recent runs combo (stretch)
        # Single state-machine button on row 1: idle => "Run Workflow ▶";
        # running => "Cancel ✖". Click during run prompts confirmation.
        self._is_running = False
        self._active_feedback = None
        self._active_history_index = None  # index into the history file

        run_row = QHBoxLayout()
        run_row.setContentsMargins(0, 0, 0, 0)
        run_row.setSpacing(4)
        self._run_btn = QPushButton("Run Workflow ▶")
        self._run_btn.setMinimumHeight(32)
        self._run_btn.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._run_btn.clicked.connect(self._on_run_or_cancel_clicked)
        run_row.addWidget(self._run_btn, 1)

        # Batch 28.8: dock-wide "Reset all" button. Confirmation prompt
        # before action; Recent runs / saved settings files are NOT
        # touched. Icon-only (↺) with full label in the tooltip so the
        # button stays narrow.
        self._reset_all_btn = QToolButton()
        self._reset_all_btn.setText("↺")
        self._reset_all_btn.setToolTip(
            "Reset all inputs to defaults.\n\n"
            "Resets every input on the dock back to its default value. "
            "Recent runs and saved settings files are NOT affected; "
            "you can still restore from those.")
        self._reset_all_btn.setAutoRaise(True)
        self._reset_all_btn.setMinimumHeight(32)
        self._reset_all_btn.clicked.connect(self._on_reset_all_clicked)
        run_row.addWidget(self._reset_all_btn, 0)
        outer_layout.addLayout(run_row)

        # Row 2: Recent runs on its own row so the combo can shrink to
        # any width without forcing the dock wider than the section
        # forms above.
        recent_row = QHBoxLayout()
        recent_row.setContentsMargins(0, 0, 0, 0)
        self._recent_combo = QComboBox()
        self._recent_combo.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._recent_combo.setToolTip(
            "Recent runs — pick one to repopulate the dock with its "
            "saved parameters")
        self._recent_combo.activated.connect(self._on_recent_picked)
        recent_row.addWidget(self._recent_combo, 1)
        outer_layout.addLayout(recent_row)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        outer_layout.addWidget(self._progress)

        self._refresh_recent_combo()

        # Batch 28.8: capture the dock's freshly-built widget state as
        # the canonical "defaults" for the Reset all button. Round-trips
        # via the same _collect_params / _apply_params pair that Recent
        # runs uses, so anything restorable from a Recent run is also
        # resettable. Done LAST in __init__ so every section builder
        # has finished setting its widgets to their default values.
        try:
            self._initial_defaults = self._collect_params()
        except Exception:
            # If anything goes wrong, fall back to an empty dict --
            # Reset all will become a no-op rather than crash the dock.
            self._initial_defaults = {}

        self.setWidget(outer)

    # ────────────────────────────────────────────────────────────────
    # Section builders
    # ────────────────────────────────────────────────────────────────
    def _build_section_0_study_area(self):
        # Batch 27.1: §0 starts COLLAPSED on first install (was True).
        # Multiple sections opening at first launch was distracting;
        # accordion-managed expand state takes over on subsequent uses.
        sec = CollapsibleSection("0. Study Area", expanded=False)
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
        # Batch 28.8: shrink to whatever the form column gives us so the
        # dock can be dragged narrow without ISO3 forcing it wider.
        self._iso3_edit.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._iso3_edit.setMinimumWidth(0)
        self._iso3_edit.editingFinished.connect(self._on_aoi_or_iso3_changed)
        # Live CRS-suggestion rebuild as the user types ISO3, not just
        # on focus-loss/Enter. pyproj's query is fast enough (~50ms);
        # without this the dropdown stays empty until the user tabs
        # away from the field, which feels broken.
        self._iso3_edit.textChanged.connect(self._on_aoi_or_iso3_changed)
        self._iso3_edit.textChanged.connect(self._refresh_prefix_preview)
        form.addRow("ISO3:", self._iso3_edit)

        # Batch 30: optional sub-national / ecosystem area name.
        # Tickbox is hidden until ticked; reveals an Area name field
        # whose value gets inserted between ISO3 and year in output
        # filenames. ISO3 stays a strict 3-letter code so CRS
        # suggestion + filename-sanity checks keep working alongside.
        self._use_subnational_chk = QCheckBox("Sub-national AOI?")
        self._use_subnational_chk.setToolTip(
            "Reveals an 'Area name:' field added to output filenames.")
        self._use_subnational_chk.toggled.connect(
            self._on_subnational_toggled)
        form.addRow("", self._use_subnational_chk)

        self._region_edit = QLineEdit()
        self._region_edit.setMaxLength(16)
        self._region_edit.setPlaceholderText(
            "e.g. aberdares_district, coastal_ecosystem")
        self._region_edit.setToolTip(
            "Free-form name for the sub-national area you're running. "
            "Lowercase letters, digits and underscores; spaces and "
            "special characters auto-convert. Max 16 chars. Inserted "
            "between ISO3 and year in output filenames, e.g. "
            "KEN_aberdares_district_2020_qgis_04a_primary_forest.tif.")
        self._region_edit.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._region_edit.setMinimumWidth(0)
        self._region_edit.textChanged.connect(self._refresh_prefix_preview)
        form.addRow("Area name:", self._region_edit)

        self._region_tip = QLabel(
            "<i>Tip: aberdares_district, coastal_ecosystem, "
            "mekong_basin, tarangire_park, pilot_north, sites_2026</i>")
        self._region_tip.setStyleSheet("color:#888;")
        self._region_tip.setWordWrap(True)
        self._region_tip.setMinimumWidth(0)
        self._region_tip.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred)
        form.addRow("", self._region_tip)

        # Track the row indices of the two rows that hide/show with
        # the tickbox. _on_subnational_toggled walks them by index.
        self._subnational_row_indices = (
            form.rowCount() - 2,  # Area name row
            form.rowCount() - 1,  # tip row
        )

        # Batch 27.2: Output folder lives in §6 Outputs (where it sat
        # before 27.1 briefly tried moving it here). Tip below points
        # the user there.
        _output_tip = QLabel(
            "<i>Output folder is set in §6 Outputs.</i>")
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
        # Batch 28.8: shrink to whatever the form column gives us so
        # the … browse button never gets clipped.
        self._crs_combo.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._crs_combo.setMinimumWidth(0)
        from qgis.PyQt.QtWidgets import QComboBox as _QCB
        self._crs_combo.setSizeAdjustPolicy(
            _QCB.AdjustToMinimumContentsLengthWithIcon)
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
        # Batch 30: collapse the Sub-national rows to match the
        # default-unticked checkbox state. (The rows are added to
        # the form above so we can capture their indices; this call
        # hides them until the user ticks.)
        self._on_subnational_toggled(self._use_subnational_chk.isChecked())

    def _on_aoi_or_iso3_changed(self, *_):
        """AOI path or ISO3 changed -- refresh prefix preview AND
        rebuild the CRS combo so suggestions track the new inputs.
        Clears the previous CRS choice so the user consciously picks
        the right one for the new country."""
        self._refresh_prefix_preview()
        self._chosen_crs = None
        self._chosen_crs_label = ""
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
            placeholder = QStandardItem("— Select one —")
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
        look like given the current ISO3 + year inputs. P1.30 batch 20j
        dropped the AOI-layer-name auto-feed; Batch 30 re-enables the
        slot via the explicit Sub-national AOI? tickbox + Area name
        field. When the tickbox is ticked, both forms are previewed
        side-by-side so the user sees what the area name buys them.
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
            sample_no_region = generate_layer_name(
                iso3, PLATFORM_QGIS, "04a", "primary_forest",
                ext="tif", year=year)
        except Exception:
            sample_no_region = "—"
        # Batch 30: dual-line preview when sub-national tickbox is on.
        sub_on = (hasattr(self, "_use_subnational_chk")
                  and self._use_subnational_chk.isChecked())
        if sub_on:
            region = (self._region_edit.text().strip()
                      if hasattr(self, "_region_edit") else "")
            try:
                sample_with_region = generate_layer_name(
                    iso3, PLATFORM_QGIS, "04a", "primary_forest",
                    ext="tif", year=year, aoi_label=region)
            except Exception:
                sample_with_region = "—"
            self._prefix_preview.setText(
                f"Prefix preview:<br>"
                f"&nbsp;&nbsp;Without area name: {sample_no_region}<br>"
                f"&nbsp;&nbsp;With area name:&nbsp;&nbsp;&nbsp; "
                f"{sample_with_region}")
        else:
            self._prefix_preview.setText(
                f"Prefix preview: {sample_no_region}")

    def _on_subnational_toggled(self, on: bool):
        """Batch 30: show / hide the Area name + tip rows when the
        Sub-national AOI? tickbox flips. Walks the form by row index
        and toggles widget visibility so the rows fully collapse
        (not just grey out)."""
        from qgis.PyQt.QtWidgets import QFormLayout
        if not hasattr(self, "_subnational_row_indices"):
            return
        # Find the section's form layout via the Area-name widget's
        # parent. (The form is local to _build_section_0_study_area;
        # we don't keep a direct reference, but the row indices we
        # captured are valid for that form.)
        form = self._region_edit.parentWidget().layout()
        if not isinstance(form, QFormLayout):
            return
        for idx in self._subnational_row_indices:
            for role in (QFormLayout.LabelRole, QFormLayout.FieldRole):
                item = form.itemAt(idx, role)
                if item is None:
                    continue
                w = item.widget()
                if w is not None:
                    w.setVisible(on)
        if not on:
            # Clear the field when collapsed so empty state matches
            # the empty-string state in collected params.
            self._region_edit.clear()
        self._refresh_prefix_preview()

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

        # Batch 27.2: dropdown shows ONLY FRA reporting years (mirrors
        # the GEE app's [2000, 2010, 2015, 2020] choice). The previous
        # "FRA reporting years only" tickbox is gone -- always FRA-only
        # in the dropdown. Custom years go through the multi-year text
        # field which now doubles as a custom single-year input (type
        # "2021" -> single year; type "2010, 2020" -> multi-year).

        # Index 0: single-year combobox (FRA years only).
        self._year_single_combo = QComboBox()
        self._year_single_combo.setEditable(False)
        self._year_single_combo.setToolTip(
            "Single-year FRA-reporting-year dropdown. To pick a "
            "non-FRA year (e.g. 2021) or run multiple years, tick "
            "'Custom / run multiple' below.")
        self._populate_year_dropdown(fra_only=True)
        self._year_single_combo.setCurrentText("2020")
        self._year_stack.addWidget(self._year_single_combo)

        # Index 1: multi-year / custom text field. Doubles as custom
        # single-year input (type one year, no comma) and as the
        # multi-year list. Wider than 27.1 so the placeholder fits.
        self._year_multi_edit = QLineEdit()
        self._year_multi_edit.setPlaceholderText(
            "single e.g. 2021, or multiple e.g. 2000, 2020")
        self._year_multi_edit.setMinimumWidth(240)
        self._year_multi_edit.setToolTip(
            "Custom / multi-year mode. Type one year (e.g. 2021) for "
            "a single non-FRA year, or a comma-separated list "
            "(e.g. 2000, 2020) to iterate. For multi-year, "
            "year-varying inputs (forest, OLTC, planted, agriculture, "
            "built-up, roads) are auto-detected by filename year "
            "token and globbed in the same folder; static inputs "
            "(DEM, slope, protected) are reused across all years.")
        self._year_stack.addWidget(self._year_multi_edit)

        form.addRow("Year(s):", self._year_stack)

        self._multi_year_chk = QCheckBox(
            "Custom / run multiple (comma-separated)")
        self._multi_year_chk.setToolTip(
            "When ticked, the FRA dropdown is replaced by a free-"
            "form text field. Type a single year for a non-FRA year, "
            "or a comma-separated list to iterate.\n\n"
            "Convention: assumes year-varying inputs (forest, OLTC, "
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
            "filenames omit the year segment. No iteration. All "
            "year-related controls above are disabled.")
        self._year_all_since_2000.toggled.connect(
            self._on_year_unspecified_toggled)
        # Backwards-compat: keep the FRA-only checkbox attribute as a
        # no-op stub so any saved-Recent-Run / _apply_params code path
        # that flips it doesn't AttributeError. Hidden from the form.
        self._fra_only_chk = QCheckBox()
        self._fra_only_chk.setVisible(False)
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
        """Single source of truth for the YEAR param string.

        Defensive: returns "" when called BEFORE §1 has been built
        (e.g. from §0 initial-toggle handlers during dock construction).
        Section build order is §0 -> §1 -> ..., so §0 wiring that
        triggers a prefix-preview refresh would otherwise hit
        AttributeError on `_year_all_since_2000`.
        """
        if not hasattr(self, "_year_all_since_2000"):
            return ""
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
        # Batch 27.2: stub kept for backwards-compat with saved Recent
        # Runs; the FRA-only filter is now ALWAYS on (the dropdown
        # only ever shows FRA years). No-op.
        return

    def _on_multi_year_toggled(self, on: bool):
        # Batch 27.2: simplified -- the multi-year text field doubles
        # as a custom single-year input. No FRA-only branch (dropdown
        # is always FRA-only). No greyed reference label (dropped).
        self._year_stack.setCurrentIndex(1 if on else 0)

    def _on_year_unspecified_toggled(self, on: bool):
        """Batch 27.2: when 'Year unspecified' ticks ON, grey out
        every year-related control (dropdown + custom edit + the
        Custom/multi tickbox) so the user can't accidentally set
        conflicting values."""
        enabled = not on
        self._year_stack.setEnabled(enabled)
        self._multi_year_chk.setEnabled(enabled)

    def _build_section_2_tree_cover(self):
        sec = CollapsibleSection("2. Tree Cover", expanded=False)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)

        # --- Forest / tree-cover raster picker ---
        raster_form = _form()
        self._forest_raster = LayerOrFilePicker(
            layer_filter=QgsMapLayerProxyModel.RasterLayer,
            file_filter="Raster (*.tif *.tiff *.img *.vrt);;All (*.*)",
            browse_caption="Pick tree cover / forest raster")
        raster_form.addRow("Tree cover / forest raster *:", self._forest_raster)
        body.addLayout(raster_form)

        # --- FRA-aligned checkbox ---
        self._fra_aligned = QCheckBox("FRA-aligned")
        self._fra_aligned.setToolTip(
            "Align categories with FAO Forest Resources\n"
            "Assessment (FRA 2025) definitions.\n\n"
            "When ticked, choose your input type so the\n"
            "tool shows which exclusion steps apply.")
        body.addWidget(self._fra_aligned)

        # FRA-only: input type dropdown (indented)
        fra_row = QHBoxLayout()
        fra_row.setContentsMargins(22, 0, 0, 0)
        self._fra_input_type_label = QLabel("Select input type:")
        self._fra_input_type_label.setStyleSheet(
            "color: #555; font-size: 11px;")
        self._fra_input_type_label.setToolTip(
            "Select which FRA category matches your input data")
        fra_row.addWidget(self._fra_input_type_label)
        self._input_category = QComboBox()
        self._input_category.addItem(INPUT_CATEGORY_PLACEHOLDER)
        for it in INPUT_CATEGORY_ITEMS:
            self._input_category.addItem(it)
        self._input_category.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._input_category.setMinimumContentsLength(15)
        self._input_category.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        fra_row.addWidget(self._input_category, 1)
        _tooltips = {
            INPUT_CATEGORY_TREECOVER: (
                "• Excludes: nothing — all land with tree cover,\n"
                "  regardless of land use.\n\n"
                "• FRA definition: Land spanning more than\n"
                "  0.5 ha with trees higher than 5 m and\n"
                "  canopy cover >10%, or trees able to reach\n"
                "  these thresholds in situ."),
            INPUT_CATEGORY_FOREST: (
                "• Excludes: Other Land with Tree Cover (OLTC)\n"
                "  — oil palm, orchards, agroforestry, urban\n"
                "  trees etc.\n\n"
                "• FRA definition: Land spanning more than\n"
                "  0.5 ha with trees higher than 5 m and\n"
                "  canopy cover >10%, or trees able to reach\n"
                "  these thresholds in situ, where land use\n"
                "  is forest. Excludes tree stands in\n"
                "  agricultural production systems and\n"
                "  urban parks."),
            INPUT_CATEGORY_NRF: (
                "• Excludes: planted forest — eucalyptus,\n"
                "  pine, teak, timber/pulp/fibre etc.\n\n"
                "• FRA definition: Forest predominantly\n"
                "  composed of trees established through\n"
                "  natural regeneration. Includes forests\n"
                "  where it is not possible to distinguish\n"
                "  whether planted or naturally regenerated.\n"
                "  Includes coppice from trees originally\n"
                "  established through natural regeneration."),
            INPUT_CATEGORY_PRIMARY: (
                "• Input is already primary forest — no\n"
                "  further exclusions apply. Human\n"
                "  influence removal (§3) still runs.\n\n"
                "• FRA definition: Naturally regenerating\n"
                "  forest of native tree species, where there\n"
                "  are no clearly visible indications of human\n"
                "  activities and the ecological processes are\n"
                "  not significantly disturbed."),
        }
        for i in range(self._input_category.count()):
            txt = self._input_category.itemText(i)
            if txt in _tooltips:
                self._input_category.setItemData(
                    i, _tooltips[txt], Qt.ToolTipRole)
        body.addLayout(fra_row)

        # Separator (between data inputs and refine groups)
        self._refine_sep = QWidget()
        self._refine_sep.setFixedHeight(1)
        self._refine_sep.setStyleSheet("background-color: #ddd;")
        body.addWidget(self._refine_sep)

        # --- Create intermediate layers toggle ---
        self._create_intermediate = QCheckBox("Refine input")
        self._create_intermediate.setToolTip(
            "Save each exclusion step as a separate output\n"
            "layer, useful for comparing against primary\n"
            "forest extent or FRA reporting categories.\n\n"
            "Primary forest is still created either way —\n"
            "these intermediate layers are optional extras.")
        body.addWidget(self._create_intermediate)

        self._refine_input_hint = QLabel("Creates intermediate layer(s) (optional)")
        self._refine_input_hint.setStyleSheet(
            "color: #666; font-size: 10px; font-style: italic;"
            " margin-left: 22px;")
        body.addWidget(self._refine_input_hint)

        # --- Refine to forest ---
        self._olwtc_refine = QCheckBox("Refine to forest")
        self._olwtc_refine.setToolTip(
            "Exclude other land with tree cover (OLTC)\n"
            "— e.g. oil palm, orchards, agroforestry.")
        self._olwtc_refine.setChecked(False)
        self._olwtc_refine.setStyleSheet("margin-left: 18px;")
        body.addWidget(self._olwtc_refine)

        olwtc_row = QHBoxLayout()
        olwtc_row.setContentsMargins(40, 0, 0, 0)
        self._olwtc_label = QLabel("Other land with tree cover:")
        self._olwtc_label.setStyleSheet("color: #555; font-size: 11px;")
        self._olwtc_label.setToolTip(
            "Binary raster masking areas like oil palm,\n"
            "orchards, and agroforestry that have tree\n"
            "cover but are not classified as forest\n"
            "under FRA definitions.")
        olwtc_row.addWidget(self._olwtc_label)
        self._olwtc_raster = LayerOrFilePicker(
            layer_filter=QgsMapLayerProxyModel.RasterLayer,
            file_filter="Raster (*.tif *.tiff *.img *.vrt);;All (*.*)",
            browse_caption="Pick OLTC raster")
        olwtc_row.addWidget(self._olwtc_raster, 1)
        body.addLayout(olwtc_row)

        # --- Refine to naturally regenerating forest ---
        self._planted_refine = QCheckBox(
            "Refine to naturally regenerating forest")
        self._planted_refine.setToolTip(
            "Exclude planted forest\n"
            "— e.g. eucalyptus, pine, teak, timber/pulp/fibre.")
        self._planted_refine.setChecked(False)
        self._planted_refine.setStyleSheet("margin-left: 18px;")
        body.addWidget(self._planted_refine)

        planted_row = QHBoxLayout()
        planted_row.setContentsMargins(40, 0, 0, 0)
        self._planted_label = QLabel("Planted forest:")
        self._planted_label.setStyleSheet("color: #555; font-size: 11px;")
        self._planted_label.setToolTip(
            "Binary raster masking planted forest\n"
            "— e.g. eucalyptus, pine, teak, and other\n"
            "timber, pulp, or fibre plantations.")
        planted_row.addWidget(self._planted_label)
        self._planted_raster = LayerOrFilePicker(
            layer_filter=QgsMapLayerProxyModel.RasterLayer,
            file_filter="Raster (*.tif *.tiff *.img *.vrt);;All (*.*)",
            browse_caption="Pick planted-forest raster")
        planted_row.addWidget(self._planted_raster, 1)
        body.addLayout(planted_row)

        sec.set_content_layout(body)
        self._sections_layout.addWidget(sec)

        # Wire signals
        self._fra_aligned.toggled.connect(self._update_refine_visibility)
        self._create_intermediate.toggled.connect(
            self._update_refine_visibility)
        self._input_category.currentIndexChanged.connect(
            self._update_refine_visibility)
        self._update_refine_visibility()

    def _update_refine_visibility(self):
        fra = self._fra_aligned.isChecked()
        intermediate = self._create_intermediate.isChecked()

        # Dynamic checkbox labels — match GEE pff_4.js updateRefineVisibility()
        self._olwtc_refine.setText(
            "Refine to forest" if fra
            else "Exclude other land with tree cover")
        self._planted_refine.setText(
            "Refine to naturally regenerating forest" if fra
            else "Exclude planted forest")

        # FRA-only widgets
        self._fra_input_type_label.setVisible(fra)
        self._input_category.setVisible(fra)

        # Grey out "Create intermediate" when FRA input is NRF or Primary
        # (nothing left to refine).
        if fra:
            cat = self._input_category.currentText()
            no_refine_possible = cat in (INPUT_CATEGORY_NRF,
                                         INPUT_CATEGORY_PRIMARY)
            self._create_intermediate.setEnabled(not no_refine_possible)
            self._refine_input_hint.setVisible(not no_refine_possible)
            if no_refine_possible:
                self._create_intermediate.setChecked(False)
                intermediate = False
        else:
            self._create_intermediate.setEnabled(True)
            self._refine_input_hint.setVisible(True)

        if not intermediate:
            self._refine_sep.setVisible(False)
            for w in (self._olwtc_refine,
                      self._olwtc_label, self._olwtc_raster,
                      self._planted_refine,
                      self._planted_label, self._planted_raster):
                w.setVisible(False)
            self._olwtc_refine.setChecked(False)
            self._planted_refine.setChecked(False)
            return

        if not fra:
            self._refine_sep.setVisible(True)
            for w in (self._olwtc_refine,
                      self._olwtc_label, self._olwtc_raster,
                      self._planted_refine,
                      self._planted_label, self._planted_raster):
                w.setVisible(True)
            self._olwtc_refine.setChecked(True)
            self._planted_refine.setChecked(True)
            return

        # FRA + intermediate: conditional on input type
        cat = self._input_category.currentText()
        is_placeholder = (cat == INPUT_CATEGORY_PLACEHOLDER)
        show_olwtc = (cat == INPUT_CATEGORY_TREECOVER)
        show_planted = show_olwtc or (cat == INPUT_CATEGORY_FOREST)
        self._refine_sep.setVisible(not is_placeholder)
        for w in (self._olwtc_refine,
                  self._olwtc_label, self._olwtc_raster):
            w.setVisible(show_olwtc)
        for w in (self._planted_refine,
                  self._planted_label, self._planted_raster):
            w.setVisible(show_planted)
        if not show_olwtc:
            self._olwtc_refine.setChecked(False)
        if not show_planted:
            self._planted_refine.setChecked(False)

    def _build_section_3_human_influence(self):
        sec = CollapsibleSection("3. Human Influence", expanded=False)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)

        # Batch 27.1: "Add to map" toggle moved to the BOTTOM of this
        # section. Top placement was distracting; users rarely flip it.
        # Default OFF (Qt QCheckBox default).
        self._add_human_layers_to_map = QCheckBox(
            "Add human-influence input + buffer layers to map after run")
        # (added to body at the END of this method)

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
        bx_form.addRow("Slope (°) >", self._slope_threshold)

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

        # Batch 27.1: "Add to map" toggle at the BOTTOM of §3. Default
        # OFF. Less distracting than top placement.
        body.addWidget(self._add_human_layers_to_map)

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

        self._smooth_radius = _spin(default=2000, mn=0, mx=10000)
        form.addRow("Neighbourhood radius:", self._smooth_radius)

        self._density_threshold = _spin(
            default=0.5, mn=0.0, mx=1.0, decimals=2, suffix="")
        form.addRow("Min. density to keep:", self._density_threshold)

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

        # Batch 28.8 item 5: nest + dissolve as exclusive options on
        # one row. nest=on + dissolve=off -> 06c only (un-dissolved).
        # nest+dissolve=on -> 06d only (dissolved). Dissolve sits to
        # the right of nest in the same row.
        self._vec_nest = QCheckBox("Nested (cut primary out of forest)")
        self._vec_dissolve = QCheckBox("Dissolve to multipart by level")
        self._vec_dissolve.setChecked(False)
        self._vec_dissolve.setToolTip(
            "When ticked alongside Nested, write ONLY the dissolved "
            "06d output (one multipart feature per level). When unticked, "
            "write ONLY the un-dissolved 06c nested vector. Dissolve "
            "requires Nested.")
        # Dissolve only applies to the nested output, so it follows the
        # nest tick: enabled iff nest is ticked, otherwise greyed out.
        self._vec_dissolve.setEnabled(False)
        self._vec_nest.toggled.connect(self._vec_dissolve.setEnabled)
        _nest_row = QHBoxLayout()
        _nest_row.setContentsMargins(0, 0, 0, 0)
        _nest_row.setSpacing(12)
        _nest_row.addWidget(self._vec_nest)
        _nest_row.addWidget(self._vec_dissolve)
        _nest_row.addStretch(1)
        form.addRow("", _nest_row)

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

        # Batch 28.8 item 7: per-section "Add to map" toggle for
        # vectorised outputs. Default OFF -- user often wants only the
        # rasters auto-added; vectors can be heavy and clutter the
        # Layers panel. Mirrors the §8 _ceo_add_to_map pattern.
        self._vec_add_to_map = QCheckBox(
            "Add vectorised outputs to map after run")
        self._vec_add_to_map.setChecked(False)
        self._vec_add_to_map.setToolTip(
            "When ticked, vector outputs (06a/06c/06d) are loaded into "
            "the QGIS project after the run completes. Default OFF -- "
            "vectors can be large and the user often wants only the "
            "rasters auto-added.")
        form.addRow("", self._vec_add_to_map)

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
        # Note: tuple keys (save_02b_forest, save_02d_nrf) are stable
        # widget identifiers — they don't change with the Batch 25.1
        # filename re-letter (SAVE_* algorithm params kept the same
        # symbolic names for backwards-compat). The display suffix
        # "(02c)" / "(02e)" reflects the NEW filename letters.
        self._save_layers = [
            # ── Main (default ON) ──
            ("save_02b_forest", "Forest", "(02c)", True, "main"),
            ("save_02d_nrf", "Naturally regenerating forest",
             "(02e)", True, "main"),
            ("save_04a_primary", "Primary forest",
             "(04a)", True, "main"),
            # ── Intermediates (default OFF) ──
            ("save_03c_pre_conn", "Pre-refinement primary forest",
             "(03c)", False, "intermediate"),
            ("save_04e_anthro_mask", "Anthropogenic mask",
             "(04e)", False, "intermediate"),
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
            "Select outputs to save", expanded=False,
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

        _prev_group = None
        for key, name, suffix, default, group in self._save_layers:
            if group != _prev_group:
                _header = QLabel(
                    "Main" if group == "main" else "Intermediates")
                _header.setStyleSheet(
                    "font-weight:bold; font-size:11px; color:#555; "
                    "margin-top:4px;")
                cust_layout.addWidget(_header)
                _prev_group = group
            cb = QCheckBox(f"{name}  {suffix}")
            cb.setChecked(default)
            cb.toggled.connect(self._refresh_save_summary)
            cust_layout.addWidget(cb)
            self._save_checkboxes[key] = cb

        self._save_customise_section.set_content_layout(cust_layout)
        # Batch 27.1: spanning row (single arg) so the Customise
        # sub-section sits flush with the form's left edge instead of
        # being pushed into the field column. Aligns it with sibling
        # §6 sub-sections (Vectorise, Validation, Performance/cache)
        # that are added at body-level outside the form.
        form.addRow(self._save_customise_section)
        # Initial summary
        self._refresh_save_summary()

    def _build_subsection_performance(self):
        """Performance / cache sub-section for Config."""
        sec = CollapsibleSection(
            "Performance / cache", expanded=False,
            indent_px=8, header_bold=False)
        form = _form()

        self._reuse_distance = QCheckBox("Reuse cached distance surfaces")
        form.addRow("", self._reuse_distance)

        self._reuse_prepared = QCheckBox("Reuse preprocessing cache")
        self._reuse_prepared.setChecked(True)
        form.addRow("", self._reuse_prepared)

        sec.set_content_layout(form)
        return sec

    def _build_subsection_save_load_config(self):
        """Save / Load run config sub-section for Config.

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
            "<i>Save the dock's current settings to a portable JSON "
            "you can share with colleagues or reload later. Distinct "
            "from <b>qgis_run_metadata.json</b> (auto-emitted alongside "
            "every run as a per-run snapshot — use that to trace what "
            "produced a given output file). Mirrors the GEE app's Save "
            "Settings.</i>")
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
        """§6 Outputs — output folder, save list, add-to-map."""
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
        self._output_folder.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._output_folder.setMinimumWidth(0)
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

        # Customise save-list accordion (only sub-section left in §6)
        self._outputs_subsections = [self._save_customise_section]
        for _sub in self._outputs_subsections:
            _sub.toggled.connect(self._on_outputs_subsection_toggled)

        sec.set_content_layout(body)
        self._sections_layout.addWidget(sec)

    def _build_section_7_validation(self):
        """§7 Validation — vectorise + validation sampling.
        Both steps are standalone but auto-chain after Run Workflow.
        """
        sec = CollapsibleSection("7. Validation", expanded=False)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)

        _vec_sec = self._build_subsection_vectorise()
        _val_sec = self._build_subsection_validation_sampling()
        body.addWidget(_vec_sec)
        body.addWidget(_val_sec)

        self._validation_subsections = [_vec_sec, _val_sec]
        for _sub in self._validation_subsections:
            _sub.toggled.connect(self._on_validation_subsection_toggled)

        sec.set_content_layout(body)
        self._sections_layout.addWidget(sec)

    def _build_section_config(self):
        """Config — save/load settings + performance/cache.
        Mirrors GEE app's Config panel.
        """
        sec = CollapsibleSection("Config", expanded=False)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)

        _sav_sec = self._build_subsection_save_load_config()
        _perf_sec = self._build_subsection_performance()
        body.addWidget(_sav_sec)
        body.addWidget(_perf_sec)

        self._config_subsections = [_sav_sec, _perf_sec]
        for _sub in self._config_subsections:
            _sub.toggled.connect(self._on_config_subsection_toggled)

        sec.set_content_layout(body)
        self._sections_layout.addWidget(sec)

    def _on_outputs_subsection_toggled(self, expanded: bool):
        """Mutual-exclusion accordion for §6 Outputs sub-sections."""
        if not expanded:
            return
        sender = self.sender()
        for sub in getattr(self, "_outputs_subsections", []):
            if sub is not sender and sub.is_expanded():
                sub.set_expanded(False)

    def _on_validation_subsection_toggled(self, expanded: bool):
        """Mutual-exclusion accordion for §7 Validation sub-sections."""
        if not expanded:
            return
        sender = self.sender()
        for sub in getattr(self, "_validation_subsections", []):
            if sub is not sender and sub.is_expanded():
                sub.set_expanded(False)

    def _on_config_subsection_toggled(self, expanded: bool):
        """Mutual-exclusion accordion for Config sub-sections."""
        if not expanded:
            return
        sender = self.sender()
        for sub in getattr(self, "_config_subsections", []):
            if sub is not sender and sub.is_expanded():
                sub.set_expanded(False)

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
        for key, _name, _suffix, default, *_ in self._save_layers:
            self._save_checkboxes[key].setChecked(default)

    def _on_save_all(self):
        for cb in self._save_checkboxes.values():
            cb.setChecked(True)

    def _on_save_none(self):
        for cb in self._save_checkboxes.values():
            cb.setChecked(False)

    def _refresh_save_summary(self):
        """Live summary line above the Customise sub-section."""
        ticked = [name for key, name, _suffix, _default, *_ in self._save_layers
                  if self._save_checkboxes[key].isChecked()]
        defaults_set = {name for _key, name, _suffix, default, *_
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
            "<i>Experimental — schema and outputs may change between "
            "plugin versions. Generates lightweight Plot + Sample layers "
            "from a forest vector, designed for upload to validation "
            "tools such as Collect Earth Online (CEO), for example. "
            "Tested against Bhutan 06c.</i>")
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

        # Batch 28.4: Source dropdown -- lets the user choose between
        # picking a vector file/layer manually OR auto-chaining off
        # the Vectorise stage's 06c nested output for this run. When
        # "auto" is selected, validation fires automatically AFTER
        # Run Workflow completes -- one click runs the whole pipeline.
        self._ceo_source = QComboBox()
        self._ceo_source.addItems([
            "Pick a file/layer (manual)",
            "Auto: use this run's nested vector (06c)",
        ])
        self._ceo_source.setToolTip(
            "Where the validation input vector comes from.\n\n"
            "• Manual: you pick a file or layer below.\n"
            "• Auto: validation fires automatically after Run Workflow\n"
            "  completes, using the 06c nested vector that the\n"
            "  Vectorise stage produces this run. Requires Vectorise\n"
            "  outputs > Vectorise nested outputs to be on.")
        self._ceo_source.currentIndexChanged.connect(
            self._on_ceo_source_changed)
        form.addRow("Source:", self._ceo_source)

        self._ceo_input = LayerOrFilePicker(
            layer_filter=QgsMapLayerProxyModel.PolygonLayer,
            file_filter="Vector (*.gpkg *.shp *.geojson);;All (*.*)",
            browse_caption="Pick forest / primary forest vector")
        self._ceo_input.setToolTip(
            "Forest / primary forest polygon layer (e.g. PFF stage-6 "
            "nested vector). Must be in a projected CRS with metre "
            "units.")
        form.addRow("Input vector:", self._ceo_input)

        self._ceo_auto_hint = QLabel(
            "<i>Auto mode: validation will fire after Run Workflow "
            "completes, using the 06c nested vector this run "
            "produces. The picker above is ignored in this mode.</i>")
        self._ceo_auto_hint.setStyleSheet("color:#666;")
        self._ceo_auto_hint.setWordWrap(True)
        self._ceo_auto_hint.setMinimumWidth(0)
        self._ceo_auto_hint.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._ceo_auto_hint.setVisible(False)
        form.addRow("", self._ceo_auto_hint)

        self._ceo_class_field = QgsFieldComboBox()
        self._ceo_class_field.setAllowEmptyFieldName(False)
        self._ceo_class_field.setToolTip(
            "Integer field that distinguishes primary forest from other "
            "forest. Auto-picks 'level' for PFF stage-6 outputs.")
        # Cap natural width so this combo doesn't dominate the field column.
        self._ceo_class_field.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._ceo_input.pathChanged.connect(self._refresh_ceo_class_field)
        # Batch 28.8 item 6: hint shown when Source = Auto so the user
        # sees the field is auto-detected from the workflow's 06c output.
        self._ceo_class_field_hint = QLabel(
            "<i>= 'level' (auto from 06c)</i>")
        self._ceo_class_field_hint.setStyleSheet("color:#666;")
        self._ceo_class_field_hint.setVisible(False)
        form.addRow("Class field:",
                    _row(self._ceo_class_field, self._ceo_class_field_hint))

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
            ["All forest (primary + other forest)",
             "Primary only",
             "Other forest only"])
        self._ceo_domain.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._ceo_domain.setToolTip(
            "Which class(es) plots are drawn from. Ignored when 'Set "
            "counts per class (stratified)' is ticked — that mode "
            "always samples both classes.")
        form.addRow("Plots from:", self._ceo_domain)

        self._ceo_stratified = QCheckBox("Set counts per class (stratified)")
        self._ceo_stratified.setToolTip(
            "When ticked, you set the primary count + the other-forest "
            "count independently — they don't have to be equal "
            "(CEO/stats term: stratified). When unticked, draw a "
            "single 'Number of plots' total uniformly from the "
            "selected 'Plots from' domain.")
        self._ceo_stratified.toggled.connect(
            self._on_ceo_stratified_toggled)
        # Batch 28.8 item 10: row label "Sampling:" (was "Mode:") so
        # the row reads as a single sentence:
        #   Sampling: Equal counts per class (stratified)
        form.addRow("Sampling:", self._ceo_stratified)

        # Batch 29: existing-points mode (e.g. FRA RSS plots). Three
        # rows: tickbox, file-picker + count button, grey readout.
        # Hidden when tickbox unticked. Counts cached in
        # `self._ceo_existing_counts` and used to clamp spinbox maxes.
        self._ceo_use_existing = QCheckBox(
            "Use existing points (e.g. FRA RSS plots)")
        self._ceo_use_existing.setToolTip(
            "Tick to draw plot centres from a pre-randomised points "
            "shapefile (e.g. FAO Remote Sensing Survey points) "
            "instead of generating new random points within the "
            "forest polygons. Points are reprojected + spatially "
            "joined against the input vector; only points that fall "
            "in forest are eligible. The N spinboxes are clamped to "
            "the available counts after you click 'Count available'.")
        self._ceo_use_existing.toggled.connect(
            self._on_ceo_existing_toggled)
        form.addRow("Existing points:", self._ceo_use_existing)

        # Batch 29 fix: use a plain QgsFileWidget here instead of
        # LayerOrFilePicker. QgsMapLayerComboBox only shows project
        # layers, so a Browse'd file (which we don't auto-load to
        # avoid Layers-panel pollution) was invisible — the user
        # couldn't see what they picked. QgsFileWidget shows the path
        # in a line edit, has a built-in browse button, and accepts
        # drag-and-drop from the OS. Path-only is the right model for
        # heavy global files (RSS).
        self._ceo_existing_picker = QgsFileWidget()
        self._ceo_existing_picker.setStorageMode(QgsFileWidget.GetFile)
        self._ceo_existing_picker.setFilter(
            "Vector (*.gpkg *.shp *.geojson *.gml *.kml "
            "*.fgb *.geoparquet);;"
            "GeoPackage (*.gpkg);;Shapefile (*.shp);;"
            "GeoJSON (*.geojson);;All (*.*)")
        self._ceo_existing_picker.setDialogTitle(
            "Pick existing points (e.g. FRA RSS plots)")
        self._ceo_existing_picker.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._ceo_existing_picker.setMinimumWidth(0)
        self._ceo_existing_picker.setToolTip(
            "Points file in any vector format (GeoPackage, Shapefile, "
            "GeoJSON, etc.) and any CRS (auto-reprojected). Typical: "
            "FAO RSS global points layer covering many countries. The "
            "spatial join filters to points falling in the input "
            "forest polygons, so multi-country files are OK.")
        # QgsFileWidget signal is fileChanged(str). Adapt to our
        # invalidator (which accepts *args).
        self._ceo_existing_picker.fileChanged.connect(
            self._on_ceo_existing_invalidated)
        self._ceo_count_btn = QToolButton()
        self._ceo_count_btn.setText("Count available")
        self._ceo_count_btn.setToolTip(
            "Reproject the points to the input vector's CRS, spatial-"
            "join them against the input forest polygons, and count "
            "how many fall in primary vs other forest. The N spinbox "
            "max values get clamped to these counts after.")
        self._ceo_count_btn.clicked.connect(self._on_ceo_count_clicked)
        _existing_row = QHBoxLayout()
        _existing_row.setContentsMargins(0, 0, 0, 0)
        _existing_row.setSpacing(4)
        _existing_row.addWidget(self._ceo_existing_picker, 1)
        _existing_row.addWidget(self._ceo_count_btn, 0)
        form.addRow("Points file:", _existing_row)

        self._ceo_existing_readout = QLabel(
            "<i>Available: — (click 'Count available')</i>")
        self._ceo_existing_readout.setStyleSheet("color:#666;")
        form.addRow("", self._ceo_existing_readout)

        # Cached counts (filled by _on_ceo_count_clicked). None when
        # invalidated / not yet counted.
        self._ceo_existing_counts = None

        # Batch 29 UX: per-spinbox max suffix replaced with row-end
        # grey labels. Cleaner; per-class row shows the combined
        # readout (a + b = total) so the user sees the budget as one.
        self._ceo_n_total = QSpinBox()
        self._ceo_n_total.setRange(1, 100000)
        self._ceo_n_total.setValue(50)
        self._ceo_n_total.setMaximumWidth(110)
        self._ceo_n_total.setToolTip(
            "Total number of plots to generate. Used in non-stratified "
            "mode only. Each plot becomes one row in the CEO upload.")
        self._ceo_n_total_max_label = QLabel("")
        self._ceo_n_total_max_label.setStyleSheet(
            "color:#666; font-style:italic;")
        form.addRow("Number of plots:", _row(
            self._ceo_n_total, self._ceo_n_total_max_label))

        self._ceo_n_primary = QSpinBox()
        self._ceo_n_primary.setRange(0, 100000)
        self._ceo_n_primary.setValue(25)
        self._ceo_n_primary.setMaximumWidth(80)
        self._ceo_n_primary.setToolTip(
            "Plots to draw inside primary-forest polygons. Used when "
            "'Set counts per class (stratified)' is ticked. After "
            "'Count available' fires, this is hard-capped at the "
            "primary candidate count.")
        self._ceo_n_other = QSpinBox()
        self._ceo_n_other.setRange(0, 100000)
        self._ceo_n_other.setValue(25)
        self._ceo_n_other.setMaximumWidth(80)
        self._ceo_n_other.setToolTip(
            "Plots to draw inside other-forest polygons. Used when "
            "'Set counts per class (stratified)' is ticked. After "
            "'Count available' fires, this is hard-capped at the "
            "other-forest candidate count.")
        self._ceo_n_per_class_max_label = QLabel("")
        self._ceo_n_per_class_max_label.setStyleSheet(
            "color:#666; font-style:italic;")
        form.addRow("Plots per class:", _row(
            "Primary:", self._ceo_n_primary, 8,
            "Other:", self._ceo_n_other,
            8, self._ceo_n_per_class_max_label))

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
            "Minimum distance between any two plot centres. 0 = no "
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
            ["Simple (CEO draws default)",
             "Custom ring boundary"])
        self._ceo_method.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._ceo_method.setToolTip(
            "What plot boundary the upload includes.\n\n"
            "• Simple: upload only the centre points; CEO renders its "
            "default boundary (~500 m by default; configurable in CEO).\n"
            "• Custom ring boundary: upload a thin annulus polygon per "
            "plot so the interpretation radius is fixed by you "
            "regardless of CEO's default.")
        self._ceo_method.currentIndexChanged.connect(
            self._on_ceo_method_changed)
        form.addRow("Plot boundary:", self._ceo_method)

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
        form.addRow("Plot dimensions:", _row(
            "Radius:", self._ceo_radius, 8,
            "Ring:", self._ceo_ring_w))

        self._ceo_sample_point = QCheckBox("Centre point")
        self._ceo_sample_point.setChecked(True)
        self._ceo_sample_point.setToolTip(
            "Emit a centre-point sample layer. Each row's "
            "PLOTID == SAMPLEID.")
        self._ceo_sample_square = QCheckBox("Square")
        self._ceo_sample_square.setToolTip(
            "Emit a square sample layer (separate file). Centred on "
            "the random point. PLOTID and SAMPLEID match per row. "
            "Square size set below; the area is shown live next to "
            "the size spinbox so you can pick a non-1ha size if "
            "wanted (e.g. 70.7 m -> 0.5 ha; 200 m -> 4 ha).")
        self._ceo_sample_square.toggled.connect(
            self._on_ceo_sample_square_toggled)
        form.addRow("Sample within plot:", _row(
            self._ceo_sample_point, self._ceo_sample_square))

        self._ceo_square_size = QDoubleSpinBox()
        self._ceo_square_size.setRange(1, 10000)
        self._ceo_square_size.setValue(100)
        self._ceo_square_size.setSuffix(" m")
        self._ceo_square_size.setDecimals(0)
        self._ceo_square_size.setMaximumWidth(110)
        self._ceo_square_size.setToolTip(
            "Side length of the square sample. 100 m -> 1 ha (default); "
            "70.7 m -> 0.5 ha; 200 m -> 4 ha. Live calculation shown "
            "next to this field.")
        # Batch 28.7: live hectares label that updates as the size
        # spinbox changes -- so the user can pick a non-1ha size and
        # see the area immediately.
        self._ceo_square_ha_label = QLabel("(= 1.00 ha)")
        self._ceo_square_ha_label.setStyleSheet(
            "color:#666; font-style:italic;")

        def _update_ceo_square_ha(_v=None):
            try:
                size_m = float(self._ceo_square_size.value())
            except Exception:
                size_m = 0.0
            ha = (size_m * size_m) / 10000.0
            self._ceo_square_ha_label.setText(f"(= {ha:.2f} ha)")
        self._ceo_square_size.valueChanged.connect(_update_ceo_square_ha)
        _update_ceo_square_ha()
        form.addRow("Sample square size:", _row(
            self._ceo_square_size, self._ceo_square_ha_label))

        self._ceo_output_folder = QgsFileWidget()
        self._ceo_output_folder.setStorageMode(QgsFileWidget.GetDirectory)
        self._ceo_output_folder.setToolTip(
            "Folder where validation sampling outputs land. Defaults "
            "to the main output folder set in §0 Study Area when that "
            "is set; can be overridden here.")
        # Batch 28.8: shrink with the form column so the browse button
        # stays visible at narrow dock widths.
        self._ceo_output_folder.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._ceo_output_folder.setMinimumWidth(0)
        # P1.30 Batch 27.1: auto-fill from §0 Output folder on first
        # set + on every change while still empty. User-typed value
        # wins after that (we only auto-fill if the field is blank).
        if hasattr(self, "_output_folder"):
            def _autofill_ceo_folder(path):
                if path and not self._ceo_output_folder.filePath():
                    self._ceo_output_folder.setFilePath(path)
            self._output_folder.fileChanged.connect(_autofill_ceo_folder)
            # Seed initial value if §0 already has a path set.
            _seed = self._output_folder.filePath()
            if _seed and not self._ceo_output_folder.filePath():
                self._ceo_output_folder.setFilePath(_seed)
        form.addRow("Output folder:", self._ceo_output_folder)

        # Batch 28.6: per-section "add to map" tickbox for validation
        # outputs. Independent from the §6 "Add saved outputs to map"
        # toggle which controls the main raster outputs. Default ON --
        # matches what was happening implicitly (via the §6 toggle)
        # before this batch.
        self._ceo_add_to_map = QCheckBox(
            "Add validation outputs to map after run")
        self._ceo_add_to_map.setChecked(True)
        self._ceo_add_to_map.setToolTip(
            "After validation sampling, load the produced ceo_*.gpkg / "
            ".zip layers into the QGIS Layers panel with PFF symbology. "
            "Independent from the main §6 'Add saved outputs to map' "
            "toggle.")
        form.addRow("", self._ceo_add_to_map)

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
        # / enable rows. PyQt5 in QGIS 3.38 doesn't expose QFormLayout's
        # Qt 5.15 `setRowVisible`; we walk row items by index instead.
        # NOTE: indices must match the actual form.addRow() call order.
        # Adding / reordering rows above this dict means updating these
        # numbers too -- there is no symbolic anchor.
        # Batch 28.8 fix: indices were off by 2 (didn't count the new
        # Source row at the top, nor the always-present-but-hidden
        # auto_hint row), which made handlers grey the wrong rows in
        # the screenshot user reported.
        self._ceo_form = form
        # Batch 29: three new rows for existing-points mode inserted
        # after `stratified` (row 6) -> `use_existing` (7),
        # `existing_picker` (8), `existing_readout` (9). Subsequent
        # rows shift by +3.
        self._ceo_rows = {
            "source": 0,
            "input": 1,
            "auto_hint": 2,
            "class_field": 3,
            "class_values": 4,
            "domain": 5,
            "stratified": 6,
            "use_existing": 7,
            "existing_picker": 8,
            "existing_readout": 9,
            "n_total": 10,
            "n_per_class": 11,
            "method": 12,
            "circular": 13,
            "sample_geom": 14,
            "square_size": 15,
            "output_folder": 16,
            "add_to_map": 17,
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

        self._ceo_run_btn = QPushButton("Generate validation samples ▶")
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
        # Batch 29: initial visibility for existing-points rows + wire
        # stale-count invalidation so a change to anything that affects
        # counts resets the cache + spinbox maxes.
        self._on_ceo_existing_toggled(self._ceo_use_existing.isChecked())
        self._ceo_input.pathChanged.connect(
            self._on_ceo_existing_invalidated)
        self._ceo_class_field.fieldChanged.connect(
            self._on_ceo_existing_invalidated)
        self._ceo_primary_value.valueChanged.connect(
            self._on_ceo_existing_invalidated)
        self._ceo_other_value.valueChanged.connect(
            self._on_ceo_existing_invalidated)
        # Live running-sum label on the per-class spinboxes. Each box
        # is independently capped via setMaximum(); no cross-clamping.
        self._ceo_n_primary.valueChanged.connect(
            lambda _: self._refresh_ceo_per_class_label())
        self._ceo_n_other.valueChanged.connect(
            lambda _: self._refresh_ceo_per_class_label())
        return sec

    def _refresh_ceo_class_field(self):
        # Batch 28.8 item 11: when the picker holds an explicit FILE
        # path (not a project layer), `current_layer()` returns None
        # and the QgsFieldComboBox stays blank even though the file
        # has perfectly readable fields. Probe the path with a temp
        # QgsVectorLayer (NOT added to the project) just to populate
        # the field combo. This restores the auto-pick of `level`
        # for users who Browse to a 06c/06d file rather than dragging
        # it onto QGIS first.
        layer = self._ceo_input.current_layer()
        if layer is None:
            try:
                path = self._ceo_input.path()
            except Exception:
                path = ""
            if path:
                from qgis.core import QgsVectorLayer as _QVL
                tmp = _QVL(path, "__pff_ceo_field_probe__", "ogr")
                if tmp.isValid():
                    layer = tmp
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

    def _set_ceo_row_enabled(self, row_key, enabled):
        """Batch 28.8: enable/grey one row of the §8 form. Same DIY
        walk as `_set_ceo_row_visible` but flips `setEnabled` instead
        of `setVisible`. Used for method-dependent + stratified-
        dependent rows so the user always sees them but can only edit
        the relevant ones.
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
                w.setEnabled(enabled)
                continue
            sublayout = item.layout()
            if sublayout is not None:
                self._set_layout_widgets_enabled(sublayout, enabled)

    def _set_layout_widgets_enabled(self, layout, enabled):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.setEnabled(enabled)
                continue
            sub = item.layout()
            if sub is not None:
                self._set_layout_widgets_enabled(sub, enabled)

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
        """Grey circular-only rows when method = Simple (Batch 28.8).

        Custom circular: Radius/Ring + Sample geom + (conditionally)
        Square size are enabled. Simple point plots: those rows go
        grey but stay visible so the user knows they exist.
        """
        circular = (idx == 1)
        self._set_ceo_row_enabled("circular", circular)
        self._set_ceo_row_enabled("sample_geom", circular)
        # square_size enabled state delegated to the dedicated handler.
        self._on_ceo_sample_square_toggled(
            self._ceo_sample_square.isChecked())

    def _on_ceo_stratified_toggled(self, on):
        """Stratified ON  -> per-class row enabled, single-N + domain
        rows greyed. Stratified OFF -> single-N + domain enabled,
        per-class greyed (Batch 28.8: grey-out instead of hide).
        """
        self._set_ceo_row_enabled("n_total", not on)
        self._set_ceo_row_enabled("domain", not on)
        self._set_ceo_row_enabled("n_per_class", on)

    def _on_ceo_sample_square_toggled(self, on):
        """Square size row is enabled only when method = circular AND
        the Square sample geometry is ticked (Batch 28.8: grey-out)."""
        circular = (self._ceo_method.currentIndex() == 1)
        self._set_ceo_row_enabled("square_size", circular and on)

    # ── Batch 29: existing-points mode handlers ─────────────────────
    def _on_ceo_existing_toggled(self, on: bool):
        """Show / hide the points-file picker + readout rows. When
        unticked, also clear any cached counts and reset spinbox
        maxes back to the original 100000 / suffixes back to empty.
        """
        for key in ("existing_picker", "existing_readout"):
            self._set_ceo_row_visible(key, on)
        if not on:
            self._on_ceo_existing_invalidated()

    def _on_ceo_existing_invalidated(self, *_):
        """Reset cached counts + spinbox maxes whenever an input that
        affects the count changes (input vector, class field/values,
        existing-points file, or the use-existing tickbox itself)."""
        self._ceo_existing_counts = None
        for sb, default_max in (
                (self._ceo_n_total, 100000),
                (self._ceo_n_primary, 100000),
                (self._ceo_n_other, 100000)):
            sb.setMaximum(default_max)
            sb.setSuffix("")
        if hasattr(self, "_ceo_n_total_max_label"):
            self._ceo_n_total_max_label.setText("")
        if hasattr(self, "_ceo_n_per_class_max_label"):
            self._ceo_n_per_class_max_label.setText("")
        if hasattr(self, "_ceo_existing_readout"):
            self._ceo_existing_readout.setText(
                "<i>Available: — (click 'Count available')</i>")

    def _ceo_count_existing_vs_input(self, pts_path: str,
                                     in_path: str,
                                     class_field: str,
                                     primary_val: int,
                                     other_val: int):
        """Spatial-join existing points against an input forest vector
        on disk. Returns (primary_count, other_count, unmatched). Used
        by both the dock button (count vs §8 input) and the auto-chain
        path (count vs the workflow's 06c). Returns (0, 0, 0) if
        either file cannot be loaded.
        """
        from qgis.core import (
            QgsVectorLayer as _QVL,
            QgsCoordinateTransform as _QCT,
            QgsProject as _QP,
            QgsSpatialIndex as _QSI,
            QgsGeometry as _QG)
        pts = _QVL(pts_path, "__pff_pts_count__", "ogr")
        if not pts.isValid():
            return (0, 0, 0)
        src = _QVL(in_path, "__pff_in_count__", "ogr")
        if not src.isValid():
            return (0, 0, 0)
        pts_crs = pts.crs()
        src_crs = src.crs()
        same_crs = (pts_crs.authid()
                    and pts_crs.authid() == src_crs.authid())
        transform = (None if same_crs
                     else _QCT(pts_crs, src_crs, _QP.instance()))
        sp_index = _QSI()
        polys_by_id = {}
        for f in src.getFeatures():
            sp_index.addFeature(f)
            polys_by_id[f.id()] = f
        primary_count = 0
        other_count = 0
        unmatched = 0
        for pf in pts.getFeatures():
            geom = pf.geometry()
            if geom is None or geom.isEmpty():
                continue
            if transform is not None:
                geom = _QG(geom)
                try:
                    geom.transform(transform)
                except Exception:
                    continue
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
                    if cv == primary_val:
                        primary_count += 1
                        matched = True
                        break
                    if cv == other_val:
                        other_count += 1
                        matched = True
                        break
            if not matched:
                unmatched += 1
        return (primary_count, other_count, unmatched)

    def _on_ceo_count_clicked(self):
        """Spatial-join existing points against the input vector,
        report counts by class, clamp spinbox maxes."""
        if not self._ceo_use_existing.isChecked():
            return
        pts_path = self._ceo_existing_picker.filePath()
        in_path = self._ceo_input.path()
        if not pts_path:
            QMessageBox.warning(
                self, "Primary Forest Finder",
                "Pick a points file first.")
            return
        if not in_path:
            QMessageBox.warning(
                self, "Primary Forest Finder",
                "Pick an input vector (the forest polygons) first.")
            return

        cf = self._ceo_class_field.currentField() or "level"
        primary_val = int(self._ceo_primary_value.value())
        other_val = int(self._ceo_other_value.value())
        self._ceo_existing_readout.setText(
            "<i style='color:#888;'>Counting — this may take a moment "
            "for large point sets…</i>")
        from qgis.PyQt.QtWidgets import QApplication
        QApplication.processEvents()
        primary_count, other_count, unmatched = (
            self._ceo_count_existing_vs_input(
                pts_path, in_path, cf, primary_val, other_val))
        total = primary_count + other_count
        self._ceo_existing_counts = {
            "primary": primary_count,
            "other": other_count,
            "total": total,
        }
        self._ceo_existing_readout.setText(
            f"<span style='color:#444;'>Available: <b>{total}</b> "
            f"total ({primary_count} primary, {other_count} other "
            f"forest; {unmatched} fall outside any forest "
            f"polygon)</span>")

        # Per-class hard caps stay (typing can't exceed availability).
        # Suffixes cleared; max info now shown via row-end grey labels.
        self._ceo_n_total.setMaximum(max(1, total))
        self._ceo_n_total.setSuffix("")
        self._ceo_n_total_max_label.setText(f"(max {total})")
        if total > 0 and self._ceo_n_total.value() > total:
            self._ceo_n_total.setValue(total)

        self._ceo_n_primary.setMaximum(max(0, primary_count))
        self._ceo_n_primary.setSuffix("")
        self._ceo_n_other.setMaximum(max(0, other_count))
        self._ceo_n_other.setSuffix("")
        # Refresh the per-class label (live sum updates on edit too).
        self._refresh_ceo_per_class_label()

        # Auto-equal-split heuristic: when stratified mode is on,
        # redistribute Primary + Other to the equal-as-possible split,
        # capped per-class. Triggered on every count completion --
        # the user can still manually adjust afterwards. Mirrors how
        # most validation campaigns start: 50/50 unless one stratum
        # is genuinely tiny (then fill primary, give the rest to other).
        if total > 0:
            half = total // 2
            new_p = min(half, primary_count)
            # Whatever the primary stratum can't take, push to other
            # (still capped at other_count).
            new_o = min(total - new_p, other_count)
            # If other is also short, primary picks up the slack.
            if new_p + new_o < total:
                new_p = min(total - new_o, primary_count)
            # Block cross-clamp recursion during the paired write --
            # otherwise the first setValue triggers the partner's
            # cross-clamp handler before the second has even fired.
            self._ceo_pair_updating = True
            try:
                self._ceo_n_primary.setValue(new_p)
                self._ceo_n_other.setValue(new_o)
            finally:
                self._ceo_pair_updating = False
            # Also clamp non-stratified value to total (don't auto-
            # set, just clamp downwards).
            if self._ceo_n_total.value() > total:
                self._ceo_n_total.setValue(total)
        # Refresh the live label with the freshly-set values.
        self._refresh_ceo_per_class_label()

    def _refresh_ceo_per_class_label(self):
        """Batch 29.1: live running-sum readout next to the per-class
        row. Shows `(current P + O = sum / max P_max + O_max = total)`
        in soft green when sum == total else grey. Also handles the
        empty-state when counts aren't cached or existing-mode is off.
        """
        counts = self._ceo_existing_counts
        if (not counts
                or not self._ceo_use_existing.isChecked()):
            self._ceo_n_per_class_max_label.setText("")
            return
        p_count = int(counts.get("primary", 0))
        o_count = int(counts.get("other", 0))
        total = p_count + o_count
        p_used = int(self._ceo_n_primary.value())
        o_used = int(self._ceo_n_other.value())
        s = p_used + o_used
        colour = "#4a8a4a" if (total > 0 and s == total) else "#666"
        self._ceo_n_per_class_max_label.setStyleSheet(
            f"color:{colour}; font-style:italic;")
        self._ceo_n_per_class_max_label.setText(
            f"(current {p_used} + {o_used} = {s} / "
            f"max {p_count} + {o_count} = {total})")

    def _on_ceo_n_primary_changed(self, value):
        """Refresh the live label when Primary changes. Each spinbox is
        independently capped at its per-class max via setMaximum() —
        no cross-clamp (the user sets each count freely).
        """
        self._refresh_ceo_per_class_label()

    def _on_ceo_n_other_changed(self, value):
        """Refresh the live label when Other changes."""
        self._refresh_ceo_per_class_label()

    def _on_ceo_source_changed(self, idx: int):
        """Toggle the §8 Input vector picker grey-out + auto hint
        based on the Source dropdown. Batch 28.8 item 6: also grey
        the Class field combo + show its hint when Auto is selected
        (the workflow's 06c output always uses field='level').
        """
        is_auto = (idx == 1)  # 0 = manual, 1 = auto
        self._ceo_input.setEnabled(not is_auto)
        if hasattr(self, "_ceo_auto_hint"):
            self._ceo_auto_hint.setVisible(is_auto)
        if hasattr(self, "_ceo_class_field"):
            self._ceo_class_field.setEnabled(not is_auto)
        if hasattr(self, "_ceo_class_field_hint"):
            self._ceo_class_field_hint.setVisible(is_auto)

    def _ceo_use_auto_source(self) -> bool:
        """Return True iff the §8 Source dropdown is set to auto-chain."""
        try:
            return self._ceo_source.currentIndex() == 1
        except Exception:
            return False

    def _find_06d_nested_dissolved(self, year: str = None) -> str:
        """Locate the 06d dissolved nested-vector file the workflow just
        produced in the output folder. Returns the path or '' if not found.

        Checks both .gpkg AND .shp extensions (user may have
        Vectorise outputs > 'Output as Shapefile' ticked) and both
        forest-name variants (naturally_regenerating_forest /
        forest)."""
        from ..utils import generate_layer_name, PLATFORM_QGIS
        out_dir = (self._output_folder.filePath() or "").strip()
        if not out_dir or not os.path.isdir(out_dir):
            return ""
        iso3 = (self._iso3_edit.text() or "").upper().strip()
        year_str = (year or "").strip()
        candidates = []
        for forest_name in (
                "naturally_regenerating_forest", "forest"):
            for ext in ("gpkg", "shp"):
                try:
                    cand = generate_layer_name(
                        iso3, PLATFORM_QGIS, "06d",
                        f"{forest_name}_with_primary_nested_dissolved",
                        ext=ext, year=year_str)
                except Exception:
                    cand = ""
                if cand:
                    candidates.append(cand)
        for cand in candidates:
            full = os.path.join(out_dir, cand)
            if os.path.exists(full):
                return full
        import glob as _glob
        for ext in ("gpkg", "shp"):
            if year_str:
                pat = os.path.join(
                    out_dir,
                    f"*{year_str}*_06d_*_nested_dissolved.{ext}")
            else:
                pat = os.path.join(
                    out_dir,
                    f"*_06d_*_nested_dissolved.{ext}")
            hits = _glob.glob(pat)
            if hits:
                return hits[0]
        return ""

    def _add_ceo_outputs_to_project(self, out_dir: str, feedback) -> int:
        """Scan the CEO output folder for ceo_*.gpkg files and add
        them to the QGIS project with PFF symbology. Returns the count
        loaded.

        The validation algorithm writes files directly (doesn't use
        layersToLoadOnCompletion), so the dock's main
        _add_outputs_to_project(ctx) walks an empty list. This
        helper plugs that gap by enumerating the on-disk outputs
        directly. Zip-shapefile outputs are skipped (not directly
        loadable in QGIS without vsizip:// VFS); the .gpkg companion
        carries the same data and IS loadable.
        """
        if not out_dir or not os.path.isdir(out_dir):
            return 0
        import glob as _glob
        from qgis.core import (
            QgsRasterLayer as _QRL, QgsVectorLayer as _QVL,
            QgsProject as _QP)
        # Match the canonical schema (`*qgis_07*_ceo_validation_*.gpkg`,
        # with or without an ISO3/year prefix) AND the legacy `ceo_*.gpkg`
        # form so v0.14.5 outputs still get auto-loaded. Batch 28.8 fix:
        # the previous pattern required a leading underscore (`*_qgis_...`)
        # which silently missed files emitted with empty ISO3/year prefix
        # (e.g. `qgis_07a_ceo_validation_*.gpkg`).
        gpkg_hits = sorted(set(
            _glob.glob(os.path.join(
                out_dir, "*qgis_07*_ceo_validation_*.gpkg"))
            + _glob.glob(os.path.join(out_dir, "ceo_*.gpkg"))))
        # Track which output role-tokens we've already loaded as GPKG so
        # we don't double-add the zip's shapefile of the same role.
        loaded_roles = set()
        for p in gpkg_hits:
            stem = os.path.splitext(os.path.basename(p))[0]
            for role in ("plot_boundaries", "samples_points",
                         "samples_squares", "point_plots"):
                if role in stem:
                    loaded_roles.add(role)
                    break

        loaded = 0
        for path in gpkg_hits:
            try:
                name = os.path.splitext(os.path.basename(path))[0]
                lyr = _QVL(path, name, "ogr")
                if not lyr.isValid():
                    continue
                apply_pff_symbology(lyr, path)
                _QP.instance().addMapLayer(lyr)
                loaded += 1
            except Exception as e:
                if feedback:
                    feedback.pushDebugInfo(
                        f"(ceo add-to-map skip {os.path.basename(path)}: {e})")

        # Batch 28.8 option A: when the user unticked GPKG output, only
        # the zipped-shapefile is on disk. Load the .shp inside the zip
        # via GDAL's /vsizip/ VFS -- supported in QGIS 3.10+ since GDAL
        # 1.8. Path syntax: /vsizip/<full-zip-path>/<basename>.shp.
        zip_hits = sorted(set(
            _glob.glob(os.path.join(
                out_dir, "*qgis_07*_ceo_validation_*.zip"))
            + _glob.glob(os.path.join(out_dir, "ceo_*.zip"))))
        for zpath in zip_hits:
            stem = os.path.splitext(os.path.basename(zpath))[0]
            # Skip the zip if we already loaded the same role from GPKG.
            role_match = next(
                (r for r in ("plot_boundaries", "samples_points",
                             "samples_squares", "point_plots")
                 if r in stem),
                None)
            if role_match and role_match in loaded_roles:
                continue
            try:
                # Inside the zip, the .shp uses the role-only stem
                # (`ceo_validation_<role>`) per `_zip_shapefile_outputs`,
                # not the full ISO3/year file stem. Probe both forms;
                # the role-only form is canonical for v0.14.6+, and we
                # also try the file stem as a fallback for legacy zips.
                vsi_paths = []
                if role_match:
                    vsi_paths.append(
                        f"/vsizip/{zpath}/ceo_validation_{role_match}.shp")
                vsi_paths.append(f"/vsizip/{zpath}/{stem}.shp")
                lyr = None
                for vsi in vsi_paths:
                    cand = _QVL(vsi, stem, "ogr")
                    if cand.isValid():
                        lyr = cand
                        break
                if lyr is None:
                    continue
                apply_pff_symbology(lyr, zpath)
                _QP.instance().addMapLayer(lyr)
                loaded += 1
                if role_match:
                    loaded_roles.add(role_match)
            except Exception as e:
                if feedback:
                    feedback.pushDebugInfo(
                        f"(ceo add-to-map zip skip "
                        f"{os.path.basename(zpath)}: {e})")

        if loaded and feedback:
            feedback.pushInfo(
                f"Added {loaded} CEO output(s) to the map "
                "with PFF symbology.")
        return loaded

    def _add_ceo_outputs_from_result(self, result, feedback) -> int:
        """Batch 28.8 fix: load CEO outputs from THIS run's result dict
        instead of globbing the output folder. Result keys are role
        tokens like ``point_plots`` or ``samples_squares_zip``; values
        are the freshly-written file paths. Loads .gpkg directly,
        .zip via the GDAL ``/vsizip/`` VFS so option-A's "ZIP-only"
        mode still gets layers on the map. Skips a zip whose role was
        already loaded as a .gpkg in the SAME run (avoids double-add
        when both formats are emitted).

        Used by the standalone Generate button; the auto-chain code
        path still uses ``_add_ceo_outputs_to_project`` (folder glob)
        because it doesn't have direct access to this run's result.
        """
        if not result:
            return 0
        from qgis.core import (
            QgsVectorLayer as _QVL, QgsProject as _QP)
        role_tokens = ("plot_boundaries", "samples_points",
                       "samples_squares", "point_plots")
        loaded_roles = set()
        loaded = 0

        # Pass 1: GPKG.
        for _key, path in result.items():
            if not isinstance(path, str) or not path.endswith(".gpkg"):
                continue
            if not os.path.exists(path):
                continue
            stem = os.path.splitext(os.path.basename(path))[0]
            role = next((r for r in role_tokens if r in stem), None)
            try:
                lyr = _QVL(path, stem, "ogr")
                if not lyr.isValid():
                    continue
                apply_pff_symbology(lyr, path)
                _QP.instance().addMapLayer(lyr)
                if role:
                    loaded_roles.add(role)
                loaded += 1
            except Exception as e:
                if feedback:
                    feedback.pushDebugInfo(
                        f"(ceo add-to-map skip {os.path.basename(path)}: "
                        f"{e})")

        # Pass 2: ZIP via /vsizip/ for any role not already loaded.
        for _key, path in result.items():
            if not isinstance(path, str) or not path.endswith(".zip"):
                continue
            if not os.path.exists(path):
                continue
            stem = os.path.splitext(os.path.basename(path))[0]
            role = next((r for r in role_tokens if r in stem), None)
            if role is None or role in loaded_roles:
                continue
            shp_inside = f"ceo_validation_{role}.shp"
            vsi = f"/vsizip/{path}/{shp_inside}"
            try:
                lyr = _QVL(vsi, stem, "ogr")
                if not lyr.isValid():
                    continue
                apply_pff_symbology(lyr, path)
                _QP.instance().addMapLayer(lyr)
                loaded_roles.add(role)
                loaded += 1
            except Exception as e:
                if feedback:
                    feedback.pushDebugInfo(
                        f"(ceo add-to-map zip skip "
                        f"{os.path.basename(path)}: {e})")

        if loaded and feedback:
            feedback.pushInfo(
                f"Added {loaded} CEO output(s) to the map "
                "with PFF symbology.")
        return loaded

    def _build_ceo_params_from_path(self, input_path: str):
        """Construct the §8 algorithm-params dict from the dock state,
        substituting the given input_path for the manual picker. Used
        by both manual and auto-chain code paths."""
        from ..algorithms.ceo_validation_export import (
            CeoValidationExportAlgorithm as A,
        )
        out_dir = self._ceo_output_folder.filePath()
        cf = self._ceo_class_field.currentField() or "level"
        # Batch 28.8 item 8: pass ISO3 + YEAR through so CEO outputs
        # follow the canonical PFF filename schema. Both safely default
        # empty when the §0/§1 widgets aren't filled.
        try:
            iso3 = (self._iso3_edit.text() or "").strip().upper()
        except Exception:
            iso3 = ""
        try:
            year = (self._year_combo.currentText() or "").strip()
        except Exception:
            year = ""
        return {
            A.INPUT: input_path,
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
            A.ISO3: iso3,
            A.YEAR: year,
            # Batch 29: pass through existing-points file path when
            # the dock has it ticked (auto-chain path also gets it).
            A.EXISTING_POINTS: (
                self._ceo_existing_picker.filePath()
                if (hasattr(self, "_ceo_use_existing")
                    and self._ceo_use_existing.isChecked())
                else None),
        }

    def _run_ceo_chain_after_workflow(self, year: str, feedback):
        """Auto-chain helper: called from Run Workflow handler after a
        successful single-year (or per-year multi-year iteration). If
        the §8 Source dropdown is set to auto, locate the 06d dissolved
        nested vector that the just-completed workflow produced and fire
        the validation algorithm against it. Non-blocking: surfaces a
        warning + returns silently if anything is missing."""
        if not self._ceo_use_auto_source():
            return
        nested_path = self._find_06d_nested_dissolved(year=year)
        if not nested_path:
            feedback.pushWarning(
                f"⚠ Auto-validation: could not find a 06d dissolved "
                f"nested vector for year={year} in the output folder. "
                "Skipping validation. (Make sure 'Vectorise nested "
                "outputs' and 'Dissolve' are ticked in §6.)")
            return
        if not self._ceo_output_folder.filePath():
            feedback.pushWarning(
                "⚠ Auto-validation: §8 output folder is empty. "
                "Set it (or auto-fills from §0).")
            return
        feedback.pushInfo(
            f"=== Auto-validation: sampling from {os.path.basename(nested_path)} ===")
        ctx = self._make_processing_context(feedback)
        try:
            params = self._build_ceo_params_from_path(nested_path)
            # Batch 29: when existing-points is also ticked, run the
            # spatial-join count NOW (against the workflow-produced
            # 06c) and clamp the requested N values to availability.
            if self._ceo_use_existing.isChecked():
                pts_path = self._ceo_existing_picker.filePath()
                if pts_path:
                    cf = (self._ceo_class_field.currentField()
                          or "level")
                    pv = int(self._ceo_primary_value.value())
                    ov = int(self._ceo_other_value.value())
                    feedback.pushInfo(
                        "  Counting existing points against this "
                        "run's 06c...")
                    p_cnt, o_cnt, _u = (
                        self._ceo_count_existing_vs_input(
                            pts_path, nested_path, cf, pv, ov))
                    total = p_cnt + o_cnt
                    feedback.pushInfo(
                        f"  Available in 06c: {total} total "
                        f"({p_cnt} primary, {o_cnt} other forest).")
                    from ..algorithms.ceo_validation_export import (
                        CeoValidationExportAlgorithm as A)
                    # Clamp; log when a clamp actually occurred.
                    n_total_req = int(params.get(A.N_SAMPLES, 0))
                    n_p_req = int(params.get(A.N_PRIMARY, 0))
                    n_o_req = int(params.get(A.N_OTHER, 0))
                    n_total_new = min(n_total_req, total) if total > 0 else 0
                    n_p_new = min(n_p_req, p_cnt) if p_cnt > 0 else 0
                    n_o_new = min(n_o_req, o_cnt) if o_cnt > 0 else 0
                    if n_total_new != n_total_req:
                        feedback.pushInfo(
                            f"  Clamped Number of plots: "
                            f"{n_total_req} -> {n_total_new}")
                    if n_p_new != n_p_req:
                        feedback.pushInfo(
                            f"  Clamped N per class (primary): "
                            f"{n_p_req} -> {n_p_new}")
                    if n_o_new != n_o_req:
                        feedback.pushInfo(
                            f"  Clamped N per class (other): "
                            f"{n_o_req} -> {n_o_new}")
                    params[A.N_SAMPLES] = n_total_new
                    params[A.N_PRIMARY] = n_p_new
                    params[A.N_OTHER] = n_o_new
                    if total == 0:
                        feedback.pushWarning(
                            "⚠ Auto-validation: 0 existing points "
                            "fall in this run's forest. Skipping.")
                        return
            processing.run("pff:ceo_validation_export", params,
                           context=ctx, feedback=feedback)
            feedback.pushInfo(
                "✔ Auto-validation complete (year=" + str(year) + ").")
            if self._ceo_add_to_map.isChecked():
                # Walk the context first (in case the CEO algo ever
                # registers outputs) AND scan the output folder
                # directly (current behaviour: it doesn't register).
                self._add_outputs_to_project(ctx)
                self._add_ceo_outputs_to_project(
                    self._ceo_output_folder.filePath(), feedback)
        except Exception as e:
            feedback.pushWarning(
                f"⚠ Auto-validation failed for year={year}: {e}. "
                "Primary forest + other rasters are unaffected.")

    def _on_generate_ceo_clicked(self):
        from ..algorithms.ceo_validation_export import (
            CeoValidationExportAlgorithm as A,
        )
        # Validate
        path = self._ceo_input.path()
        if self._ceo_use_auto_source():
            QMessageBox.information(
                self, "Primary Forest Finder",
                "§8 Source is set to 'Auto: use this run's nested "
                "vector'. Validation will fire automatically after "
                "you click Run Workflow -- no need to click this "
                "button. Switch Source to 'Pick a file/layer' to use "
                "the picker manually.")
            return
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
        # Batch 28.8 fix: read ISO3 + YEAR from §0/§1 widgets so the
        # standalone Generate button produces canonically-named files
        # (matching the auto-chain path's output names).
        try:
            iso3 = (self._iso3_edit.text() or "").strip().upper()
        except Exception:
            iso3 = ""
        try:
            year = (self._year_combo.currentText() or "").strip()
        except Exception:
            year = ""

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
            A.ISO3: iso3,
            A.YEAR: year,
            # Batch 29: existing-points file (None when unticked).
            A.EXISTING_POINTS: (
                self._ceo_existing_picker.filePath()
                if self._ceo_use_existing.isChecked() else None),
        }

        # Batch 29: auto-count if user hasn't clicked Count yet.
        # Aborts cleanly when no eligible points after the join.
        if self._ceo_use_existing.isChecked():
            if self._ceo_existing_counts is None:
                self._on_ceo_count_clicked()
            counts = self._ceo_existing_counts or {}
            if not counts.get("total"):
                QMessageBox.warning(
                    self, "Primary Forest Finder",
                    "Existing-points spatial join produced 0 "
                    "candidates. None of the points fall inside "
                    "your input forest polygons. Pick a different "
                    "points file or check the input vector.")
                return

        self._log.append(
            "<b>=== Validation sampling (experimental) ===</b>")
        feedback = _DockFeedback(self._log, self._progress)
        ctx = self._make_processing_context(feedback)
        self._ceo_run_btn.setEnabled(False)
        try:
            try:
                # Batch 28.8 fix: capture the result dict so add-to-map
                # loads ONLY this run's outputs (the dict's values are
                # the freshly-written paths). The earlier folder-glob
                # implementation re-loaded every prior run's CEO files
                # too, which then blocked future workflow writes via
                # file locks.
                result = processing.run("pff:ceo_validation_export",
                                        params,
                                        context=ctx, feedback=feedback)
                self._log.append("<span style='color:#080;'>✔ "
                                 "Validation sampling complete.</span>")
                if self._ceo_add_to_map.isChecked():
                    self._add_outputs_to_project(ctx)
                    self._add_ceo_outputs_from_result(result, feedback)
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
                        result2 = processing.run(
                            "pff:ceo_validation_export",
                            params, context=ctx2,
                            feedback=feedback)
                        if self._ceo_add_to_map.isChecked():
                            self._add_outputs_to_project(ctx2)
                            self._add_ceo_outputs_from_result(
                                result2, feedback)
                        self._log.append("<span style='color:#080;'>✔ "
                                         "Validation sampling complete "
                                         "(with skipped class).</span>")
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
            issues.append("Tree cover / forest raster (§2) is required.")
        if (self._fra_aligned.isChecked()
                and self._input_category.currentText()
                == INPUT_CATEGORY_PLACEHOLDER):
            issues.append(
                "FRA-aligned is ticked but no input type "
                "has been chosen (§2). Select what your data represents.")
        if not self._output_folder.filePath():
            issues.append("Output folder (§1) is required.")
        return issues

    def _collect_params(self) -> dict:
        params: dict = {}

        # §0 Study Area
        params[FW.AOI] = self._aoi_picker.path() or None
        params[FW.ISO3_PREFIX] = self._iso3_edit.text().strip()
        # Batch 30: sub-national / ecosystem area name. Empty when the
        # Sub-national AOI? tickbox is off.
        params[FW.REGION_LABEL] = (
            self._region_edit.text().strip()
            if (hasattr(self, "_use_subnational_chk")
                and self._use_subnational_chk.isChecked())
            else "")
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
        params["TREE_COVER_MODE"] = (
            "fra" if self._fra_aligned.isChecked() else "simple")
        params["INPUT_CATEGORY"] = self._input_category.currentText()
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

        # Batch 27.2: empty year guard. If "Custom / run multiple"
        # tickbox is on but the text field is blank, _current_year_text
        # returns "" and _collect_params used to fall back to "2020"
        # silently. That caused "empty string seems to run for years"
        # (and ran 2020 logic on whatever inputs were loaded). Block
        # explicitly here.
        if (self._multi_year_chk.isChecked()
                and not self._year_all_since_2000.isChecked()
                and not self._year_multi_edit.text().strip()):
            QMessageBox.warning(
                self, "Primary Forest Finder",
                "Custom / run multiple is ticked but no year(s) are "
                "typed.\n\nType a single year (e.g. 2021) or a "
                "comma-separated list (e.g. 2010, 2020), OR untick "
                "the box to use the FRA dropdown.")
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

        # Batch 27.2: single-year filename sanity check. When the user
        # picks one year (e.g. 2020) but the loaded input filenames
        # carry a DIFFERENT year token (e.g. *_2010_*.tif), warn before
        # running. Mirrors the multi-year alignment check; non-blocking
        # (Yes/No prompt) because the user might genuinely want to run
        # 2020 logic against differently-named inputs.
        if (len(year_list) == 1 and year_list[0] != "all"
                and not self._single_year_filenames_aligned(
                    params, year_list[0], feedback)):
            self._leave_running_state()
            return

        # Batch 28.5: auto-validation preflight gate. If §8 Source is
        # set to "Auto" but Vectorise nested outputs is OFF, the
        # Auto-validation needs the 06d dissolved nested vector.
        # If nest or dissolve is off, offer to auto-tick both.
        if self._ceo_use_auto_source() and (
                not self._vec_nest.isChecked()
                or not self._vec_dissolve.isChecked()):
            missing = []
            if not self._vec_nest.isChecked():
                missing.append("Vectorise nested outputs")
            if not self._vec_dissolve.isChecked():
                missing.append("Dissolve to multipart")
            ans = QMessageBox.question(
                self, "Primary Forest Finder",
                "Auto-validation is enabled in §8 (Source = 'Auto') "
                "but needs the dissolved nested vector (06d).\n\n"
                "Currently off: " + ", ".join(missing) + ".\n\n"
                "Tick these now and continue?\n"
                "(No = abort, fix manually. "
                "Cancel = run anyway and accept the auto-validation "
                "skip.)",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes)
            if ans == QMessageBox.Yes:
                self._vec_nest.setChecked(True)
                self._vec_dissolve.setEnabled(True)
                self._vec_dissolve.setChecked(True)
                params[FW.VECTORIZE_NEST] = True
                params[FW.VECTORIZE_DISSOLVE_MULTIPART] = True
                feedback.pushInfo(
                    "Auto-ticked: Vectorise nested + Dissolve (so "
                    "auto-validation has its 06d input).")
            elif ans == QMessageBox.No:
                feedback.pushWarning(
                    "Run aborted -- enable Vectorise nested + Dissolve "
                    "or change §8 Source to 'Pick a file/layer' before "
                    "running again.")
                self._leave_running_state()
                return

        # Batch 29: auto-chain + existing-points combo. Allowed but
        # the user can't pre-count (06d doesn't exist yet). Brief
        # information prompt explains the clamp behaviour; user can
        # cancel or continue.
        if (self._ceo_use_auto_source()
                and self._ceo_use_existing.isChecked()
                and self._ceo_existing_picker.filePath()):
            ans3 = QMessageBox.question(
                self, "Primary Forest Finder",
                "§8 has both 'Auto: use this run's nested vector' AND "
                "'Use existing points' on. Plot/sample counts will be "
                "clamped to what's available after counting against "
                "this run's 06c output. (Validation against a known "
                "input file is more predictable.)\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes)
            if ans3 != QMessageBox.Yes:
                feedback.pushWarning(
                    "Run aborted -- combo not confirmed.")
                self._leave_running_state()
                return

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
                    # Batch 28.4: auto-chain validation if enabled.
                    self._run_ceo_chain_after_workflow(
                        year_list[0] if year_list else "", feedback)
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
            # Batch 28.6: emit the categorised summary of warnings/
            # errors accumulated during the run. Easy to miss the
            # warnings inline in a long algorithm log; the summary
            # surfaces what's worth attention (resolved auto-recoveries,
            # skipped steps, output-quality concerns).
            try:
                feedback.print_summary()
            except Exception:
                pass

    def _single_year_filenames_aligned(self, params, declared_year,
                                        feedback) -> bool:
        """Batch 27.2: scan input file paths for 4-digit year tokens
        and warn if any differ from the declared single-year. Returns
        True to continue, False to abort (user clicked No to the
        confirm prompt).

        Tokens scanned: substrings matching ``_\\d{4}_`` in the
        filename basename. Years outside [1990, 2030] are ignored
        (avoid false positives on EPSG / scale / time-hash substrings).
        """
        try:
            declared = int(declared_year)
        except (ValueError, TypeError):
            return True  # malformed -- skip the check
        token_rx = re.compile(r"_(\d{4})_")
        path_param_names = [
            FW.FOREST_RASTER, FW.AOI, FW.FRA_AGRICULTURE_RASTER,
            FW.PLANTATIONS_RASTER, FW.ROADS, FW.ROADS_RASTER,
            FW.BUILTUP_SMALL_RASTER, FW.BUILTUP_LARGE_RASTER,
            FW.AGRICULTURE_RASTER,
            FW.CUSTOM_1_RASTER, FW.CUSTOM_2_RASTER, FW.CUSTOM_3_RASTER,
        ]
        mismatches = []
        for name in path_param_names:
            p = params.get(name) or ""
            if not p:
                continue
            base = os.path.basename(str(p))
            for m in token_rx.finditer(base):
                tok = int(m.group(1))
                if 1990 <= tok <= 2030 and tok != declared:
                    mismatches.append((name, base, tok))
                    break  # one mismatch per input is enough
        if not mismatches:
            return True
        # Build a readable list (max 6 lines)
        sample = "\n".join(
            f"  • {os.path.basename(b)} contains year {t}"
            for _, b, t in mismatches[:6])
        more = (f"\n  …and {len(mismatches) - 6} more"
                if len(mismatches) > 6 else "")
        feedback.pushWarning(
            f"⚠ Single-year mismatch: you picked {declared} but "
            f"{len(mismatches)} input(s) contain a different year "
            f"in their filename.")
        ans = QMessageBox.question(
            self, "Primary Forest Finder",
            f"You picked year = {declared}, but {len(mismatches)} "
            f"input(s) appear to be from a different year:\n\n"
            f"{sample}{more}\n\n"
            "Run anyway? (Yes proceeds with year=" + str(declared)
            + "; No aborts so you can change the year or pick "
              "different inputs.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)
        if ans != QMessageBox.Yes:
            feedback.pushWarning("⚠ Run aborted by user.")
            return False
        return True

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

        # Batch 27.2: anchor-year sanity check. If the loaded input
        # filenames don't contain the anchor year token (e.g. user
        # typed "2020, 2010" but loaded *_2010_*.tif files), the per-
        # year resolution silently misclassifies the anchor's inputs
        # as anchor-year data. Warn before iterating.
        if not self._single_year_filenames_aligned(
                base_params, anchor_year, feedback):
            return

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
                # Batch 28.4: auto-chain validation per year if enabled.
                self._run_ceo_chain_after_workflow(year, feedback)
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
                # Batch 27.1: append year to display name when present
                # in the filename (BTN_2010_qgis_*.tif). Disambiguates
                # multi-year auto-loaded layers in the Layers panel.
                # Skip if the year is already part of the display name.
                _ym = re.search(r"_(\d{4})_",
                                os.path.basename(path or ""))
                if _ym and _ym.group(1) not in name:
                    name = f"{name} {_ym.group(1)}"
                ext = os.path.splitext(path)[1].lower()
                is_vector = ext in (
                    ".gpkg", ".shp", ".geojson", ".kml", ".gml")
                # Batch 28.8 item 7: respect the per-section vectorise
                # add-to-map toggle. Vectors only load when ticked.
                # Rasters keep loading per their own toggle (handled by
                # the algorithm's loadOnCompletion registrations -- if
                # the user unticked "Add main outputs to map" the
                # algorithm wouldn't have registered them).
                if is_vector and hasattr(self, "_vec_add_to_map") \
                        and not self._vec_add_to_map.isChecked():
                    continue
                if is_vector:
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
        for i, entry in enumerate(self._load_history()[:20]):
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

    def _on_reset_all_clicked(self):
        """Batch 28.8: dock-wide reset to the captured initial defaults.

        Confirms with the user before clearing every dock input. Recent
        runs (history file) and saved settings JSONs on disk are NOT
        touched -- the user can still re-pick a Recent run after reset.
        """
        if not self._initial_defaults:
            QMessageBox.warning(
                self, "Primary Forest Finder",
                "Could not capture default values when the dock was "
                "built; Reset all is unavailable. Reload the plugin to "
                "try again.")
            return
        ans = QMessageBox.question(
            self, "Primary Forest Finder",
            "<b>Reset every input back to its default?</b><br><br>"
            "All pickers, toggles and numeric values across §0–§7 + Config "
            "will be cleared / restored to the values they had when "
            "you first opened the dock.<br><br>"
            "Your Recent runs and any settings files you've saved are "
            "<b>not</b> affected — you can still pick a Recent run "
            "afterwards to bring those values back.",
            QMessageBox.Reset | QMessageBox.Cancel,
            QMessageBox.Cancel)
        if ans != QMessageBox.Reset:
            return
        try:
            self._apply_params(self._initial_defaults)
            self._log.append(
                "<span style='color:#444;'>↺ All dock inputs reset to "
                "defaults.</span>")
        except Exception as e:
            QMessageBox.warning(
                self, "Primary Forest Finder",
                f"Reset failed partway through: {e}\n\nReload the "
                "plugin to get a clean slate.")

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
        # Batch 30: restore Region/Area name. Tick the Sub-national
        # AOI? checkbox iff a non-empty value was saved; otherwise
        # leave it unticked + field hidden.
        _saved_region = s(FW.REGION_LABEL)
        if _saved_region:
            self._use_subnational_chk.setChecked(True)
            self._region_edit.setText(_saved_region)
        else:
            self._use_subnational_chk.setChecked(False)
            self._region_edit.clear()
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
        _tc_mode = p.get("TREE_COVER_MODE", "simple")
        self._fra_aligned.setChecked(_tc_mode == "fra")
        _saved_cat = p.get("INPUT_CATEGORY", INPUT_CATEGORY_PLACEHOLDER)
        idx = self._input_category.findText(_saved_cat)
        self._input_category.setCurrentIndex(idx if idx >= 0 else 0)
        self._forest_raster.set_path(s(FW.FOREST_RASTER))
        self._olwtc_raster.set_path(s(FW.FRA_AGRICULTURE_RASTER))
        _has_refine = (b(FW.EXCLUDE_AGRICULTURE_FROM_FOREST, False)
                       or b(FW.EXCLUDE_PLANTATIONS, False))
        self._create_intermediate.setChecked(_has_refine)
        self._olwtc_refine.setChecked(b(FW.EXCLUDE_AGRICULTURE_FROM_FOREST,
                                        False))
        self._planted_raster.set_path(s(FW.PLANTATIONS_RASTER))
        self._planted_refine.setChecked(b(FW.EXCLUDE_PLANTATIONS, False))
        self._update_refine_visibility()

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

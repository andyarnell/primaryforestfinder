"""Headless probe: instantiate the PFF dock and inspect per-section
minimum widths to verify the Layer picker browse button stays
visible at narrow dock widths.

Reports:
  - Each top-level section's `minimumSizeHint().width()` and
    `sizeHint().width()` after layout.
  - For each LayerOrFilePicker found, its computed combo + browse
    widths at sequential dock-width tests (200, 300, 400, 600 px).
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from qgis.core import QgsApplication
prefix = r"C:\Program Files\QGIS 3.38.0\apps\qgis"
QgsApplication.setPrefixPath(prefix, True)
app = QgsApplication([], True)  # GUI = True so Qt widgets work
app.initQgis()
sys.path.append(os.path.join(prefix, "python", "plugins"))
from processing.core.Processing import Processing
Processing.initialize()


# Fake iface stub; PffDockWidget only stores it.
class FakeIface:
    def mainWindow(self):
        return None


from pff_qgis_tools.ui.pff_dock import PffDockWidget
from pff_qgis_tools.ui.layer_picker import LayerOrFilePicker
from pff_qgis_tools.ui.collapsible_section import CollapsibleSection
from qgis.PyQt.QtWidgets import QFormLayout

dock = PffDockWidget(FakeIface())
# Force layouts to compute (no need to .show() — for sizeHint we just
# need the layout system to run).
dock.adjustSize()

print("\n=== Top-level dock metrics ===")
print(f"dock.minimumSizeHint().width(): "
      f"{dock.minimumSizeHint().width()} px")
print(f"dock.sizeHint().width():        "
      f"{dock.sizeHint().width()} px")

print("\n=== Per top-level section ===")
sections = dock._top_level_sections
for sec in sections:
    title = sec._title
    sec.set_expanded(True)
    sec.adjustSize()
    msh = sec.minimumSizeHint().width()
    sh = sec.sizeHint().width()
    print(f"  {title!s:<60} min={msh:4d}  hint={sh:4d}")

# Find every LayerOrFilePicker in the tree and report its min/hint.
print("\n=== LayerOrFilePicker instances ===")
def find_pickers(widget, out=None):
    if out is None:
        out = []
    for child in widget.findChildren(LayerOrFilePicker):
        out.append(child)
    return out

pickers = find_pickers(dock)
for p in pickers:
    p.adjustSize()
    msh = p.minimumSizeHint().width()
    sh = p.sizeHint().width()
    btn_visible = p._browse_btn.isVisibleTo(p)
    btn_w = p._browse_btn.width()
    combo_w = p._combo.width()
    print(f"  picker  min={msh:4d}  hint={sh:4d}  "
          f"combo_w={combo_w}  btn_w={btn_w}  btn_visible={btn_visible}")

# Force the dock through several widths to see if widgets still render.
print("\n=== Resize test ===")
for width in (220, 280, 320, 400, 500, 800):
    dock.resize(width, 800)
    dock.adjustSize()
    # Look at a §8 picker
    sec_8 = sections[-1]  # last is §8 by build order
    sec_8.set_expanded(True)
    pickers8 = find_pickers(sec_8)
    for p in pickers8:
        # Process events so Qt re-layouts
        app.processEvents()
        btn_w = p._browse_btn.width()
        combo_w = p._combo.width()
        print(f"  dock_w={width:4d}  combo_w={combo_w:3d}  "
              f"btn_w={btn_w:3d}  picker_w={p.width()}")

# Also report form's row-wrap policy state.
print("\n=== QFormLayout policies (samples) ===")
forms = dock.findChildren(QFormLayout)
print(f"  found {len(forms)} QFormLayouts")
if forms:
    f0 = forms[0]
    print(f"  rowWrapPolicy = {f0.rowWrapPolicy()}  "
          f"(WrapLongRows={QFormLayout.WrapLongRows})")
    print(f"  fieldGrowthPolicy = {f0.fieldGrowthPolicy()}  "
          f"(AllNonFixedFieldsGrow={QFormLayout.AllNonFixedFieldsGrow})")

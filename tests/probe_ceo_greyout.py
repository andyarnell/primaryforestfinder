"""Probe: verify §8 hide/show wiring across (stratified, method,
sample_square) combinations. Also verifies tooltips + label rename +
that Advanced sub-section exists with the moved widgets.
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
app = QgsApplication([], True)
app.initQgis()
sys.path.append(os.path.join(prefix, "python", "plugins"))
from processing.core.Processing import Processing
Processing.initialize()


class FakeIface:
    def mainWindow(self):
        return None


from pff_qgis_tools.ui.pff_dock import PffDockWidget
from pff_qgis_tools.ui.collapsible_section import CollapsibleSection

dock = PffDockWidget(FakeIface())
# P1.30 batch 23: Validation sampling is now a sub-section of §6
# Outputs (was top-level §8). Walk all top-level sections + all their
# nested CollapsibleSections to find the "Validation sampling" one.
adv = None
val_sec = None
for top in dock._top_level_sections:
    top.set_expanded(True)
    for child in top.findChildren(CollapsibleSection):
        title = getattr(child, "_title", "") or ""
        if "Validation sampling" in title:
            val_sec = child
            val_sec.set_expanded(True)
        elif "Advanced" == title:
            adv = child
            adv.set_expanded(True)
# Process events so layout settles.
app.processEvents()


def is_row_visible(widget):
    """Use isVisibleTo(parent) to bypass the fact that the dock itself
    isn't show()'d in headless probe; isVisible() returns False for
    everything otherwise. isVisibleTo(None) returns the widget's own
    explicit visibility regardless of ancestors."""
    return widget.isVisibleTo(widget.parentWidget())


# Reference shortcuts (form-row widgets).
w = {
    "n_total": dock._ceo_n_total,
    "domain": dock._ceo_domain,
    "n_primary": dock._ceo_n_primary,
    "n_other": dock._ceo_n_other,
    "radius": dock._ceo_radius,
    "ring_w": dock._ceo_ring_w,
    "samp_point": dock._ceo_sample_point,
    "samp_square": dock._ceo_sample_square,
    "square_size": dock._ceo_square_size,
}


def expected(stratified, method_circular, square_on):
    return {
        "n_total": not stratified,
        "domain": not stratified,
        "n_primary": stratified,
        "n_other": stratified,
        "radius": method_circular,
        "ring_w": method_circular,
        "samp_point": method_circular,
        "samp_square": method_circular,
        "square_size": method_circular and square_on,
    }


def report(state, stratified, method_circular, square_on):
    exp = expected(stratified, method_circular, square_on)
    actual = {k: is_row_visible(v) for k, v in w.items()}
    diffs = [k for k in exp if exp[k] != actual[k]]
    print(f"\nstrat={stratified} circ={method_circular} sq={square_on}: "
          + state)
    for k in exp:
        marker = "OK" if exp[k] == actual[k] else "FAIL"
        print(f"  {marker:4}  {k:12} expected={exp[k]} actual={actual[k]}")
    return len(diffs) == 0


# Sequence of toggles
all_ok = True
all_ok &= report("init defaults", False, False, False)

dock._ceo_stratified.setChecked(True)
all_ok &= report("after tick stratified", True, False, False)

dock._ceo_method.setCurrentIndex(1)
all_ok &= report("after method=circular", True, True, False)

dock._ceo_sample_square.setChecked(True)
all_ok &= report("after tick square", True, True, True)

dock._ceo_stratified.setChecked(False)
all_ok &= report("after untick stratified", False, True, True)

dock._ceo_method.setCurrentIndex(0)
all_ok &= report("after method=simple", False, False, True)

dock._ceo_sample_square.setChecked(False)
all_ok &= report("after untick square", False, False, False)

dock._ceo_method.setCurrentIndex(1)
all_ok &= report("after method=circular, square off", False, True, False)

# Advanced sub-section sanity: the moved widgets should be findable
# inside the Advanced collapsible (lives under Validation sampling).
print("\n=== Advanced sub-section ===")
if adv is None:
    print("  FAIL: Advanced sub-section not found in widget tree")
    all_ok = False
else:
    adv_widgets = [
        ("ceo_min_distance", dock._ceo_min_distance),
        ("ceo_seed", dock._ceo_seed),
        ("ceo_out_gpkg", dock._ceo_out_gpkg),
        ("ceo_out_zip", dock._ceo_out_zip),
        ("ceo_provenance", dock._ceo_provenance),
    ]
    adv_descendants = set(adv.findChildren(type(dock._ceo_min_distance)) +
                          adv.findChildren(type(dock._ceo_seed)) +
                          adv.findChildren(type(dock._ceo_out_gpkg)))
    for name, widget in adv_widgets:
        found = widget in adv_descendants
        print(f"  {'OK' if found else 'FAIL':4}  {name}")
        if not found:
            all_ok = False

# Tooltip presence
print("\n=== Tooltip presence check ===")
tt_widgets = [
    ("ceo_input", dock._ceo_input),
    ("ceo_class_field", dock._ceo_class_field),
    ("ceo_primary_value", dock._ceo_primary_value),
    ("ceo_other_value", dock._ceo_other_value),
    ("ceo_domain", dock._ceo_domain),
    ("ceo_stratified", dock._ceo_stratified),
    ("ceo_n_total", dock._ceo_n_total),
    ("ceo_n_primary", dock._ceo_n_primary),
    ("ceo_n_other", dock._ceo_n_other),
    ("ceo_min_distance", dock._ceo_min_distance),
    ("ceo_seed", dock._ceo_seed),
    ("ceo_method", dock._ceo_method),
    ("ceo_radius", dock._ceo_radius),
    ("ceo_ring_w", dock._ceo_ring_w),
    ("ceo_sample_point", dock._ceo_sample_point),
    ("ceo_sample_square", dock._ceo_sample_square),
    ("ceo_square_size", dock._ceo_square_size),
    ("ceo_output_folder", dock._ceo_output_folder),
    ("ceo_out_gpkg", dock._ceo_out_gpkg),
    ("ceo_out_zip", dock._ceo_out_zip),
    ("ceo_provenance", dock._ceo_provenance),
]
missing = [n for n, ww in tt_widgets if not (ww.toolTip() or "").strip()]
if missing:
    print(f"  FAIL: {len(missing)} widgets without tooltip:")
    for n in missing:
        print(f"    - {n}")
    all_ok = False
else:
    print(f"  OK: all {len(tt_widgets)} widgets have tooltips")

print()
print("=" * 40)
print("ALL OK" if all_ok else "SOME FAILED")
sys.exit(0 if all_ok else 1)

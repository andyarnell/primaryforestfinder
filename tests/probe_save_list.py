"""Fast probe for Batch 22 — per-layer Save list wiring.

Three checks (all sub-second):

1. Algorithm registers the 5 SAVE_* params with correct defaults.
2. Dock §7 builds the Customise sub-section with 5 tickboxes wired
   to the right defaults; summary line + reset/all/none buttons exist.
3. Dock _collect_params returns the 5 SAVE_* keys from the params
   dict; toggling a tickbox changes the collected dict.

End-to-end "does the algorithm actually route un-saved layers to
scratch?" is left for live user smoke-test in QGIS GUI — running
the full Bhutan workflow per-rule headlessly takes 5+ min and
duplicates what the user verifies after reload.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from qgis.core import QgsApplication  # noqa: E402
prefix = r"C:\Program Files\QGIS 3.38.0\apps\qgis"
QgsApplication.setPrefixPath(prefix, True)
app = QgsApplication([], True)
app.initQgis()
sys.path.append(os.path.join(prefix, "python", "plugins"))
from processing.core.Processing import Processing  # noqa: E402
Processing.initialize()

from pff_qgis_tools.pff_provider import PffProvider  # noqa: E402
from pff_qgis_tools.algorithms.full_workflow import (  # noqa: E402
    FullWorkflowAlgorithm as FW,
)

_PROVIDER = PffProvider()
QgsApplication.processingRegistry().addProvider(_PROVIDER)


# ──────────────────────────────────────────────────────────────────────
# 1. Algorithm param registration
# ──────────────────────────────────────────────────────────────────────
print("\n=== 1. Algorithm param registration ===")
alg = QgsApplication.processingRegistry().createAlgorithmById(
    "pff:full_workflow")
expected_save_params = (
    (FW.SAVE_02B_FOREST, True),
    (FW.SAVE_02D_NRF, True),
    (FW.SAVE_03C_PRE_CONN, False),
    (FW.SAVE_04A_PRIMARY, True),
    (FW.SAVE_04E_ANTHRO_MASK, False),
)
all_ok = True
for name, expected_default in expected_save_params:
    pdef = alg.parameterDefinition(name)
    if pdef is None:
        print(f"  FAIL: {name} not registered")
        all_ok = False
        continue
    actual_default = pdef.defaultValue()
    marker = "OK" if actual_default == expected_default else "FAIL"
    print(f"  {marker}: {name} default={actual_default} "
          f"(expected {expected_default})")
    if actual_default != expected_default:
        all_ok = False


# ──────────────────────────────────────────────────────────────────────
# 2. Dock §7 wiring
# ──────────────────────────────────────────────────────────────────────
print("\n=== 2. Dock §7 Customise sub-section ===")


class FakeIface:
    def mainWindow(self):
        return None


from pff_qgis_tools.ui.pff_dock import PffDockWidget  # noqa: E402
dock = PffDockWidget(FakeIface())

expected_keys = (
    "save_02b_forest", "save_02d_nrf", "save_03c_pre_conn",
    "save_04a_primary", "save_04e_anthro_mask")
for key in expected_keys:
    if key in dock._save_checkboxes:
        print(f"  OK: tickbox {key} present, "
              f"checked={dock._save_checkboxes[key].isChecked()}")
    else:
        print(f"  FAIL: tickbox {key} missing")
        all_ok = False

# Defaults
expected_defaults = {
    "save_02b_forest": True,
    "save_02d_nrf": True,
    "save_03c_pre_conn": False,
    "save_04a_primary": True,
    "save_04e_anthro_mask": False,
}
for key, exp in expected_defaults.items():
    actual = dock._save_checkboxes[key].isChecked()
    marker = "OK" if actual == exp else "FAIL"
    print(f"  {marker}: {key} default={actual} (expected {exp})")
    if actual != exp:
        all_ok = False

# Summary widget exists + initial summary text
if hasattr(dock, "_save_summary_label") and dock._save_summary_label is not None:
    summary = dock._save_summary_label.text()
    expected_keywords = ("Forest", "Naturally", "Primary forest")
    if all(k in summary for k in expected_keywords):
        print(f"  OK: summary line = {summary!r}")
    else:
        print(f"  FAIL: summary line = {summary!r} (missing default names)")
        all_ok = False
else:
    print("  FAIL: _save_summary_label missing")
    all_ok = False

# Reset button + Customise sub-section
if hasattr(dock, "_save_reset_btn") and dock._save_reset_btn is not None:
    print("  OK: reset button present")
else:
    print("  FAIL: _save_reset_btn missing")
    all_ok = False
if hasattr(dock, "_save_customise_section"):
    expanded = dock._save_customise_section.is_expanded()
    print(f"  OK: Customise sub-section present, "
          f"initially expanded={expanded}")
    if expanded:
        print("  WARN: Customise should default-collapsed")
else:
    print("  FAIL: _save_customise_section missing")
    all_ok = False


# ──────────────────────────────────────────────────────────────────────
# 3. _collect_params threads the 5 keys
# ──────────────────────────────────────────────────────────────────────
print("\n=== 3. _collect_params ===")
# We can't fully drive _collect_params without a forest raster set, but
# we can call it and check the SAVE_* keys come through. Path validation
# happens later in _on_run_clicked, not in _collect_params.
try:
    params = dock._collect_params()
except Exception as e:
    print(f"  FAIL: _collect_params raised: {e}")
    all_ok = False
    params = {}

for save_key in (FW.SAVE_02B_FOREST, FW.SAVE_02D_NRF, FW.SAVE_03C_PRE_CONN,
                 FW.SAVE_04A_PRIMARY, FW.SAVE_04E_ANTHRO_MASK):
    if save_key in params:
        print(f"  OK: params[{save_key}] = {params[save_key]}")
    else:
        print(f"  FAIL: {save_key} not in collected params")
        all_ok = False

# Toggle one tickbox + recollect
dock._save_checkboxes["save_03c_pre_conn"].setChecked(True)
params2 = dock._collect_params()
if params2.get(FW.SAVE_03C_PRE_CONN) is True:
    print("  OK: tickbox toggle propagates to collected params")
else:
    print(f"  FAIL: SAVE_03C_PRE_CONN should be True after toggle, "
          f"got {params2.get(FW.SAVE_03C_PRE_CONN)}")
    all_ok = False

# Defaults button restores
dock._on_save_defaults()
if dock._save_checkboxes["save_03c_pre_conn"].isChecked() is False:
    print("  OK: Defaults button restores 03c to False")
else:
    print("  FAIL: Defaults didn't restore 03c")
    all_ok = False

# Select-all + Select-none
dock._on_save_all()
all_on = all(cb.isChecked() for cb in dock._save_checkboxes.values())
print(f"  {'OK' if all_on else 'FAIL'}: Select all -> {all_on}")
if not all_on:
    all_ok = False
dock._on_save_none()
all_off = all(not cb.isChecked() for cb in dock._save_checkboxes.values())
print(f"  {'OK' if all_off else 'FAIL'}: Select none -> {all_off}")
if not all_off:
    all_ok = False

# Summary line under various states
dock._on_save_defaults()
dock._save_checkboxes["save_04a_primary"].setChecked(False)
summary = dock._save_summary_label.text()
print(f"  Summary after unticking primary: {summary!r}")

dock._on_save_all()
summary_all = dock._save_summary_label.text()
expected_all = "5 of 5 layers"
if expected_all in summary_all:
    print(f"  OK: Select-all summary = {summary_all!r}")
else:
    print(f"  FAIL: Select-all summary = {summary_all!r} "
          f"(expected to contain '{expected_all}')")
    all_ok = False

print()
print("=" * 40)
print("ALL OK" if all_ok else "SOME FAILED")
sys.exit(0 if all_ok else 1)

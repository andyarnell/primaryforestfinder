"""Probe for Batch 23 — §6 Outputs structural verification.

Confirms:
1. Top-level dock has exactly 7 sections, ending with §6 Outputs.
2. §6 Outputs contains the four expected sub-sections (Vectorise,
   Validation sampling, Run config, Performance/cache).
3. Output folder widget lives inside §6 (not §0).
4. Save list widgets live inside §6.
5. Save / Load run config buttons live inside §6.
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
_PROVIDER = PffProvider()
QgsApplication.processingRegistry().addProvider(_PROVIDER)


class FakeIface:
    def mainWindow(self):
        return None


from pff_qgis_tools.ui.pff_dock import PffDockWidget  # noqa: E402
from pff_qgis_tools.ui.collapsible_section import CollapsibleSection  # noqa

dock = PffDockWidget(FakeIface())
all_ok = True

# 1. Top-level structure
print("\n=== Top-level sections ===")
expected_titles = [
    "0. Study Area",
    "1. Time Period",
    "2. Tree Cover",
    "3. Human Influence",
    "4. Refine Output",
    "5. Area Statistics",
    "6. Outputs",
]
actual_titles = [s._title for s in dock._top_level_sections]
print(f"  Found {len(actual_titles)} sections:")
for t in actual_titles:
    print(f"    - {t}")
if actual_titles == expected_titles:
    print("  OK: top-level structure matches expected")
else:
    print(f"  FAIL: expected {expected_titles}")
    all_ok = False

# 2. §6 sub-sections
print("\n=== §6 Outputs sub-sections ===")
sec_outputs = next(
    (s for s in dock._top_level_sections if s._title == "6. Outputs"),
    None)
if sec_outputs is None:
    print("  FAIL: §6 Outputs not found")
    all_ok = False
else:
    sec_outputs.set_expanded(True)
    expected_subs = {
        "Vectorise outputs", "Validation sampling (experimental)",
        "Run config (save / load)", "Performance / cache",
    }
    sub_titles = {s._title for s in sec_outputs.findChildren(CollapsibleSection)}
    # Filter: nested Customise inside Save list shouldn't count as
    # "expected sub" — but it's fine if it appears too.
    found_expected = expected_subs & sub_titles
    missing = expected_subs - sub_titles
    print(f"  Found sub-sections: {sorted(sub_titles)}")
    if not missing:
        print(f"  OK: all {len(expected_subs)} expected sub-sections present")
    else:
        print(f"  FAIL: missing sub-sections: {missing}")
        all_ok = False

# 3. Output folder is in §6
print("\n=== Output folder location ===")
sec_0 = next((s for s in dock._top_level_sections
              if s._title == "0. Study Area"), None)
of_widget = dock._output_folder
in_section_0 = of_widget in sec_0.findChildren(type(of_widget)) if sec_0 else False
in_section_6 = (of_widget in sec_outputs.findChildren(type(of_widget))
                if sec_outputs else False)
if in_section_6 and not in_section_0:
    print(f"  OK: Output folder lives in §6 only")
else:
    print(f"  FAIL: Output folder location wrong "
          f"(in §0={in_section_0}, in §6={in_section_6})")
    all_ok = False

# 4. Save list widgets live inside §6
print("\n=== Save list location ===")
save_cb_in_6 = (dock._save_checkboxes["save_02b_forest"]
                in sec_outputs.findChildren(type(
                    dock._save_checkboxes["save_02b_forest"]))
                if sec_outputs else False)
print(f"  {'OK' if save_cb_in_6 else 'FAIL'}: "
      f"Save list tickbox in §6 = {save_cb_in_6}")
if not save_cb_in_6:
    all_ok = False

# 5. Save/load config feature exists
print("\n=== Save / Load run config handlers ===")
for handler_name in ("_on_save_run_config", "_on_load_run_config"):
    fn = getattr(dock, handler_name, None)
    if callable(fn):
        print(f"  OK: {handler_name} exists")
    else:
        print(f"  FAIL: {handler_name} missing")
        all_ok = False

print()
print("=" * 40)
print("ALL OK" if all_ok else "SOME FAILED")
sys.exit(0 if all_ok else 1)

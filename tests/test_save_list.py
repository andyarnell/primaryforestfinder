"""Test harness for Batch 22 — per-layer Save list.

Three rules:

1. **Defaults match historical behaviour** — run with all SAVE_* at
   their algorithm defaults; verify out_dir contains 02b + 02d + 04a;
   intermediates_dir contains 03c + 04e (when produced by the run
   options).
2. **All on** — set every SAVE_* to True; verify all 5 final rasters
   appear in out_dir.
3. **All off** — set every SAVE_* to False; verify NONE of the 5 land
   in out_dir (algorithm still finishes — outputs sit in scratch).

The harness builds a FAST Bhutan-flavoured run by reusing the existing
06c / Bhutan inputs the user has on disk.

Run via:
    & "C:/Program Files/QGIS 3.38.0/bin/python-qgis.bat" tests/test_save_list.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Bootstrap QGIS app + load processing.
from qgis.core import QgsApplication  # noqa: E402
prefix = r"C:\Program Files\QGIS 3.38.0\apps\qgis"
QgsApplication.setPrefixPath(prefix, True)
app = QgsApplication([], False)
app.initQgis()
sys.path.append(os.path.join(prefix, "python", "plugins"))
import processing  # noqa: E402
from processing.core.Processing import Processing  # noqa: E402
Processing.initialize()

from pff_qgis_tools.pff_provider import PffProvider  # noqa: E402
from pff_qgis_tools.algorithms.full_workflow import (  # noqa: E402
    FullWorkflowAlgorithm as FW,
)

# Keep ref to provider so it's not GC'd post-add.
_PROVIDER = PffProvider()
QgsApplication.processingRegistry().addProvider(_PROVIDER)


# Bhutan inputs — copy from the user's last full-workflow run-metadata
# JSON so paths line up. The cheapest run we can do is one with no
# vectorise + no zonal stats — just produces the 5 raster outputs.
BHUTAN_BASE = Path(
    r"C:\Users\Arnell\Downloads\qgis_pff_testing\BTN")


def _find_bhutan_inputs():
    """Walk the Bhutan test dir for the most recent run-metadata JSON
    and extract input paths. Returns dict suitable for params or None
    if not found."""
    import json
    runs = sorted(BHUTAN_BASE.glob("full_workflow_*"))
    if not runs:
        return None
    for run in reversed(runs):
        for meta in run.glob("*qgis_run_metadata.json"):
            with open(meta, encoding="utf-8") as f:
                data = json.load(f)
            params = data.get("parameters", {})
            return params
    return None


_LAYER_BASES = (
    "qgis_02c_forest.tif",
    "qgis_02e_naturally_regenerating_forest.tif",
    "qgis_03c_pre_connectivity_primary_forest.tif",
    "qgis_04a_primary_forest.tif",
    "qgis_04e_anthropogenic_mask.tif",
)


def _list_finals(folder: Path) -> set[str]:
    """Return the set of final-raster basenames present in `folder`."""
    found = set()
    for p in folder.glob("*.tif"):
        for base in _LAYER_BASES:
            if p.name.endswith(base):
                found.add(base)
                break
    return found


def _run_with_save_flags(out_dir: Path, save_flags: dict) -> dict:
    """Build a minimal full-workflow params dict + run; return the
    raw processing.run result.

    save_flags keys: SAVE_02B_FOREST, SAVE_02D_NRF, SAVE_03C_PRE_CONN,
                     SAVE_04A_PRIMARY, SAVE_04E_ANTHRO_MASK.
    """
    base = _find_bhutan_inputs()
    if base is None:
        raise RuntimeError(
            "No Bhutan run-metadata JSON found under "
            f"{BHUTAN_BASE} — run the full workflow once first.")
    params = dict(base)  # copy
    params[FW.OUTPUT_FOLDER] = str(out_dir)
    # Disable side-features to keep run fast (no vectorise / no zonal /
    # no map-add side effects).
    params[FW.RUN_ZONAL_STATS] = False
    params[FW.VECTORIZE_PRIMARY] = False
    params[FW.VECTORIZE_FOREST] = False
    params[FW.VECTORIZE_NEST] = False
    params[FW.ADD_MAIN_OUTPUTS_TO_MAP] = False
    params[FW.ADD_HUMAN_INFLUENCE_LAYERS_TO_MAP] = False
    # Reuse caches if available (same Bhutan run dir; speeds up).
    params[FW.REUSE_PREPARED] = True
    params[FW.REUSE_DISTANCE_SURFACES] = True
    # Disable cleanup so we can inspect intermediates afterwards.
    params[FW.LOCAL_SCRATCH_INTERMEDIATES] = True
    params[FW.CLEANUP_INTERMEDIATES] = False
    params.update(save_flags)
    return processing.run("pff:full_workflow", params)


# ──────────────────────────────────────────────────────────────────────
# RULE 1 — defaults match historical behaviour
# ──────────────────────────────────────────────────────────────────────
def test_rule1_defaults():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        out = Path(t) / "rule1"
        out.mkdir()
        _run_with_save_flags(out, {
            # All defaults — leave SAVE_* unset; algorithm uses
            # default values (True/True/False/True/False).
        })
        finals = _list_finals(out)
        expected = {
            "qgis_02c_forest.tif",
            "qgis_02e_naturally_regenerating_forest.tif",
            "qgis_04a_primary_forest.tif",
        }
        # 03c + 04e are NOT expected by default.
        unexpected = {
            "qgis_03c_pre_connectivity_primary_forest.tif",
            "qgis_04e_anthropogenic_mask.tif",
        }
        assert expected.issubset(finals), (
            f"Default Save list should produce {expected}; got {finals}")
        unexpected_present = unexpected & finals
        assert not unexpected_present, (
            f"Default Save list should NOT have {unexpected_present} "
            "in out_dir (they should be in scratch).")


# ──────────────────────────────────────────────────────────────────────
# RULE 2 — all SAVE flags on
# ──────────────────────────────────────────────────────────────────────
def test_rule2_all_on():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        out = Path(t) / "rule2"
        out.mkdir()
        _run_with_save_flags(out, {
            FW.SAVE_02B_FOREST: True,
            FW.SAVE_02D_NRF: True,
            FW.SAVE_03C_PRE_CONN: True,
            FW.SAVE_04A_PRIMARY: True,
            FW.SAVE_04E_ANTHRO_MASK: True,
        })
        finals = _list_finals(out)
        expected = set(_LAYER_BASES)
        missing = expected - finals
        assert not missing, (
            f"All-on Save list should produce all 5 finals; "
            f"missing: {missing}")


# ──────────────────────────────────────────────────────────────────────
# RULE 3 — all SAVE flags off
# ──────────────────────────────────────────────────────────────────────
def test_rule3_all_off():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        out = Path(t) / "rule3"
        out.mkdir()
        _run_with_save_flags(out, {
            FW.SAVE_02B_FOREST: False,
            FW.SAVE_02D_NRF: False,
            FW.SAVE_03C_PRE_CONN: False,
            FW.SAVE_04A_PRIMARY: False,
            FW.SAVE_04E_ANTHRO_MASK: False,
        })
        finals = _list_finals(out)
        assert not finals, (
            f"All-off Save list should produce NO finals in out_dir; "
            f"found: {finals}")


# ──────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────
def main():
    tests = [
        test_rule1_defaults,
        test_rule2_all_on,
        test_rule3_all_off,
    ]
    results = []
    for fn in tests:
        name = fn.__name__
        print(f"\n=== {name} ===")
        try:
            fn()
            results.append((name, True, None))
            print("PASS")
        except AssertionError as e:
            results.append((name, False, str(e)))
            print(f"FAIL: {e}")
        except Exception as e:
            results.append((name, False, f"{type(e).__name__}: {e}"))
            print(f"ERROR: {e}")
            traceback.print_exc()
    print("\n=== Summary ===")
    n_fail = 0
    for name, ok, err in results:
        marker = "PASS" if ok else "FAIL"
        print(f"  {marker}: {name}")
        if err and not ok:
            print(f"      {err}")
        if not ok:
            n_fail += 1
    if n_fail:
        print(f"\n{n_fail} of {len(tests)} failed.")
        return 1
    print(f"\nAll {len(tests)} green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

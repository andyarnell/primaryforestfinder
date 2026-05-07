"""Pytest-free runner for the CEO export harness so we can drive it
through python-qgis.bat without needing pytest installed in QGIS's
bundled Python.

Usage:
    & "C:/Program Files/QGIS 3.38.0/bin/python-qgis.bat" tests/run_ceo_tests.py

Calls each test function from test_ceo_validation_export, prints
PASS/FAIL with the assertion message, exits non-zero on any failure.
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Reuse the test module
from tests import test_ceo_validation_export as T  # noqa: E402


# Import order matters: _ensure_qgis() must run BEFORE any QGIS-aware
# code in the test module is exercised.
T._ensure_qgis()


def run_one(fn_name: str) -> bool:
    """Run a single test function with its own tmp_path. Returns
    True on pass."""
    fn = getattr(T, fn_name)
    print(f"\n=== {fn_name} ===")
    # ignore_cleanup_errors=True: on Windows, QGIS holds GPKG file
    # handles open across the test boundary. Skip cleanup errors so
    # one stuck file doesn't crash the runner.
    with tempfile.TemporaryDirectory(
            ignore_cleanup_errors=True) as tmp:
        try:
            fn(Path(tmp))
        except AssertionError as e:
            print(f"FAIL: {e}")
            return False
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
            return False
    print("PASS")
    return True


def main():
    tests = [
        "test_rule1_points_inside_polygon",
        "test_rule2_stratified_counts",
        "test_rule3_ring_integrity_under_overlap",
        "test_rule4_plotid_sampleid_consistency",
        "test_rule5_geographic_crs_aborts",
        "test_rule6_ceo_file_size_sanity",
        "test_rule7_reproject_to_wgs84_default",
    ]
    results = {n: run_one(n) for n in tests}
    print("\n=== Summary ===")
    failed = [n for n, p in results.items() if not p]
    for n, p in results.items():
        print(f"  {'PASS' if p else 'FAIL'}: {n}")
    if failed:
        print(f"\n{len(failed)} of {len(tests)} failed.")
        return 1
    print(f"\nAll {len(tests)} green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

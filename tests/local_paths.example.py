"""Template for tests/local_paths.py — copy this file to local_paths.py
and fill in absolute paths to your local test-data folders.

local_paths.py is gitignored. Each contributor maintains their own.
Tests that need these paths skip gracefully when local_paths.py is missing
or any path is absent.

Alternative: set the corresponding PFF_* environment variables instead.
"""

# GEE export bundle for Bhutan — directory containing BTN_*.tif rasters,
# the AOI .shp + sidecars, and (optionally) the reference outputs
# BTN_4_pre_connectivity_forest_*.tif / BTN_5_primary_forest_*.tif.
# Env override: PFF_BHUTAN_GEE_DIR
BHUTAN_GEE_DIR = r"C:\path\to\PFF_export_Bhutan"

# Plugin baseline output — directory from a successful full_workflow run
# on Bhutan. Used as a regression baseline for new plugin runs.
# Env override: PFF_BHUTAN_PLUGIN_OUT
BHUTAN_PLUGIN_OUT = r"C:\path\to\full_workflow_260424_yr2020"

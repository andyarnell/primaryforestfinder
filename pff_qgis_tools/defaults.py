"""Centralised default values for all PFF algorithms.

Single source of truth — every algorithm imports from here.
Matches pff_4.js defaults for cross-workflow consistency.
"""

# Distance thresholds (metres) — all 1000m by default for consistency.
# Tick "Use single distance for all" in the Full Workflow dialog to bind them
# to one value via the ALL_BUFFERS_DIST slider.
ROADS_DIST = 1000
BUILTUP_DIST = 1000
BUILTUP_LARGE_DIST = 1000
AGRICULTURE_DIST = 1000
MAX_DISTANCE = 5100

# AOI
AOI_BUFFER = 2000

# Slope
SLOPE_THRESHOLD = 45  # degrees

# Refine Output (connectivity filter)
SMOOTH_RADIUS = 2000  # metres
DENSITY_THRESHOLD = 0.5  # 0-1


# ---------------------------------------------------------------------------
# Canonical PFF class registry.
#
# Single source of truth for the human-readable labels and (eventually) the
# numeric class codes used in the optional combined coded raster output.
#
# String labels are wired in now; numeric `code` slots are parked until the
# coded-raster pyramiding artefact decision (planning task 15) lands.
# ---------------------------------------------------------------------------
PFF_CLASSES = {
    "forest": {
        "label": "Forest",
        "filename": "forest.tif",
    },
    "naturally_regenerating_forest": {
        "label": "Naturally regenerating forest",
        "filename": "naturally_regenerating_forest.tif",
    },
    "pre_connectivity_forest": {
        "label": "Pre-connectivity forest",
        "filename": "pre_connectivity_forest.tif",
    },
    "primary_forest": {
        "label": "Primary forest",
        "filename": "primary_forest.tif",
    },
    "input_forest": {
        "label": "Input forest",
        "filename": "forest.tif",
    },
}


def class_label(key: str) -> str:
    """Return the canonical human-readable label for a PFF class key.

    Falls back to the key itself if not registered, so existing call sites
    that pass arbitrary strings (zone-stats column names, etc.) don't break
    when migrated piecemeal.
    """
    entry = PFF_CLASSES.get(key)
    return entry["label"] if entry else key

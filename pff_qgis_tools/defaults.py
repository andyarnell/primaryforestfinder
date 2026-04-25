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

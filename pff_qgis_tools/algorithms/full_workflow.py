"""
PFF Full Workflow – Run All Steps
==================================
One-click tool that chains Validate -> Prepare -> Distances ->
Anthropogenic Mask -> Primary Forest -> Refine Output.

All parameters from the individual tools are exposed so users can tweak
thresholds and re-run quickly.  Distance surfaces are cached -- only
threshold changes trigger fast re-computation.

Compatible with QGIS >= 3.38 (native: / gdal: providers only).
"""

import os
import shutil
import time

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterCrs,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterField,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterString,
    QgsProcessingParameterDefinition,
    QgsProject,
)

from ..defaults import (
    ROADS_DIST, BUILTUP_DIST, BUILTUP_LARGE_DIST, AGRICULTURE_DIST,
    MAX_DISTANCE, AOI_BUFFER, SLOPE_THRESHOLD, SMOOTH_RADIUS,
    DENSITY_THRESHOLD,
)
from ..utils import (
    ensure_dir,
    validate_crs_projected,
    reproject_vector,
    reproject_raster,
    rasterize_vector,
    get_raster_info,
    run_processing,
    clip_raster_by_mask,
    proximity,
    raster_resolution,
    generate_layer_name,
    PLATFORM_QGIS,
)

# numpy / GDAL for the fast raster-algebra steps
import numpy as np
from osgeo import gdal


# =============================================================================
# P1.28: locked-file handling
# =============================================================================
# Windows holds OS-level locks on files for several reasons even when QGIS
# itself doesn't have them open: OneDrive / Dropbox / iCloud sync, Windows
# Defender real-time scan, File Explorer preview pane, and another QGIS
# session. The plugin's delete-before-write pattern (os.remove + write)
# breaks any time one of these holds a transient handle.
#
# These helpers + the preflight checks below let the run survive most of
# those situations: auto-release layers we ourselves loaded into QgsProject,
# retry os.remove with backoff (handles OneDrive sync windows), warn upfront
# when the output folder is on a cloud-synced drive, and abort early if the
# folder isn't writable at all.

def _release_layers_at_path(path):
    """Best-effort: remove any QgsProject layer at `path` so the file
    is unlocked. Silent on failure -- caller's os.remove() will raise
    the proper error if still locked."""
    try:
        proj = QgsProject.instance()
        target = os.path.normcase(os.path.abspath(path))
        for layer in list(proj.mapLayers().values()):
            # GPKG layer sources can be 'path|layername=foo' -- strip the
            # provider suffix before path comparison.
            src = layer.source().split('|')[0]
            if os.path.normcase(os.path.abspath(src)) == target:
                proj.removeMapLayer(layer.id())
    except Exception:
        pass


def _try_rename_aside(path):
    """Try to rename `path` to a `.pff_old` sidecar -- sometimes succeeds
    on Windows even when os.remove() fails, because rename uses a
    different syscall path (DELETE+RENAME atomically) that doesn't need
    the same access bits as plain delete. If rename works, the canonical
    path is freed for new writes; the .pff_old leftover gets best-effort
    deleted (silent if it fails).

    Returns True if the rename succeeded, False otherwise.
    """
    if not os.path.exists(path):
        return True  # already gone -- canonical path is free
    junk = path + '.pff_old'
    # Stale .pff_old from a prior run might still be locked too --
    # best-effort delete; if it sticks around, we'll fail the rename
    # below anyway.
    if os.path.exists(junk):
        try:
            os.remove(junk)
        except OSError:
            pass
    try:
        os.rename(path, junk)
    except OSError:
        return False
    try:
        os.remove(junk)
    except OSError:
        pass  # locked .pff_old is harmless -- canonical path is free
    return True


def _safe_remove(path, attempts=10, delay_s=0.5, feedback=None):
    """Best-effort delete for paths the run is about to overwrite.

    P1.28a: Two strategies, in order:
      1. Try renaming `path` aside to `.pff_old` (often succeeds on
         Windows when plain delete fails -- different syscall path).
      2. Retry os.remove() with exponential backoff for OneDrive sync,
         Windows Defender, File Explorer preview locks. Auto-releases
         QgsProject layers before each retry.

    Default attempts bumped from 5 to 10 (~30s total wait with 1.5x
    backoff) -- OneDrive sync windows on big GPKG files can be 20-30s.
    Periodic progress feedback so users know the run isn't hung.

    Raises RuntimeError with an actionable message if still locked.
    """
    if not os.path.exists(path):
        return
    # Strategy 1 -- the rename trick. Often resolves OneDrive-grabbed
    # files in one syscall.
    _release_layers_at_path(path)
    if _try_rename_aside(path):
        return
    # Strategy 2 -- retried delete with progress messages.
    last_err = None
    notified = False
    cur_delay = delay_s
    for attempt in range(attempts):
        _release_layers_at_path(path)
        try:
            os.remove(path)
            return
        except PermissionError as e:
            last_err = e
            if attempt < attempts - 1:
                if feedback is not None and not notified:
                    feedback.pushInfo(
                        f"  (file '{os.path.basename(path)}' is locked; "
                        f"retrying for up to ~30s -- likely OneDrive "
                        "sync, antivirus, or File Explorer preview)")
                    notified = True
                # Periodic progress so user knows we're alive
                elif feedback is not None and attempt > 0 and attempt % 3 == 0:
                    feedback.pushInfo(
                        f"  (still waiting for '{os.path.basename(path)}' "
                        f"lock to release -- attempt {attempt + 1}/{attempts})")
                time.sleep(cur_delay)
                cur_delay *= 1.5  # gentle exponential backoff
                # One last shot at the rename trick mid-retry: a sync
                # window may have closed since the first attempt.
                if attempt == attempts // 2 and _try_rename_aside(path):
                    return
    raise RuntimeError(
        f"Cannot overwrite '{os.path.basename(path)}' after {attempts} "
        f"attempts. The file is locked by another process. Common causes: "
        f"OneDrive/Dropbox sync, antivirus scan, File Explorer preview, "
        f"another QGIS session. Pause the syncing app or close the file "
        f"and re-run. (original: {last_err})")


def _is_cloud_synced_path(path):
    """Heuristic: detect common cloud-sync folder names in the path.
    Returns the matched provider name or None."""
    if not path:
        return None
    norm = path.replace('\\', '/').lower()
    # Match folder boundaries to avoid false positives in user names.
    for marker, label in [
        ('/onedrive', 'OneDrive'),
        ('/dropbox', 'Dropbox'),
        ('/google drive', 'Google Drive'),
        ('/googledrive', 'Google Drive'),
        ('/icloud drive', 'iCloud Drive'),
        ('/icloudrive', 'iCloud Drive'),
        ('/box/', 'Box'),
    ]:
        if marker in norm:
            return label
    # Also match OneDrive variants like "OneDrive - Company Name"
    if '/onedrive ' in norm or norm.endswith('/onedrive'):
        return 'OneDrive'
    return None


def _run_preflight_checks(output_folder, feedback):
    """Run preflight checks on OUTPUT_FOLDER before STAGE 1. Emits
    warnings for soft issues (continue), raises QgsProcessingException
    for hard ones (abort early so the user doesn't waste compute).

    Checks:
      a) Cloud-sync detection (warn)
      b) Write permission probe (abort if fails)
      c) Free disk space (warn if <2 GB)
      d) Pre-existing locked outputs in OUTPUT_FOLDER (warn; auto-
         release any QgsProject layers we control)
    """
    feedback.pushInfo("=== PREFLIGHT CHECKS ===")

    # (a) Cloud-sync detection
    provider = _is_cloud_synced_path(output_folder)
    if provider:
        feedback.pushWarning(
            f"Output folder is on a cloud-synced drive ({provider}). "
            "File locks during sync can cause mid-run write failures. "
            "If you hit a 'PermissionError' mid-run, either pause sync "
            "for this folder or use a local path "
            "(e.g. C:\\Users\\<you>\\Documents\\PFF_outputs).")

    # (b) Write permission probe -- hard fail if folder isn't writable
    try:
        os.makedirs(output_folder, exist_ok=True)
    except OSError as e:
        raise QgsProcessingException(
            f"Cannot create OUTPUT_FOLDER '{output_folder}'. "
            f"Check the path and permissions. (original: {e})")
    probe_path = os.path.join(output_folder, ".pff_preflight_probe")
    try:
        with open(probe_path, 'wb') as f:
            f.write(b'pff')
        os.remove(probe_path)
    except OSError as e:
        raise QgsProcessingException(
            f"Cannot write to OUTPUT_FOLDER '{output_folder}'. "
            "Check folder permissions / read-only flag. "
            f"(original: {e})")

    # (c) Free disk space
    try:
        usage = shutil.disk_usage(output_folder)
        free_mb = usage.free / (1024 * 1024)
        if free_mb < 2048:  # < 2 GB
            feedback.pushWarning(
                f"Only {free_mb:,.0f} MB free in output drive. PFF "
                "outputs (intermediates + final rasters/vectors) can be "
                "100s of MB per run; consider freeing space or using a "
                "different drive.")
    except OSError:
        pass  # disk_usage on weird paths -- skip silently

    # (d) Pre-existing locked outputs. Auto-release QgsProject layers
    # we control; warn about any that remain locked. We probe a curated
    # list of stable output filenames the run will overwrite.
    candidate_subpaths = [
        # Top-level canonical outputs
        "intermediates/_vectorize/forest_full.gpkg",
        "intermediates/_vectorize/primary_forest_full.gpkg",
        "intermediates/_vectorize/primary_forest_polys_raw.gpkg",
        "intermediates/_vectorize/forest_polys_raw.gpkg",
        "intermediates/preprocessing/forest.tif",
        "intermediates/preprocessing/dem.tif",
        "intermediates/preprocessing/slope.tif",
    ]
    locked_remaining = []
    for sub in candidate_subpaths:
        p = os.path.join(output_folder, sub)
        if not os.path.exists(p):
            continue
        try:
            # Probe with append mode -- doesn't truncate, just opens for
            # write to detect locks. Same lock semantics as os.remove on
            # Windows.
            with open(p, 'r+b'):
                pass
        except (PermissionError, OSError):
            # Locked. Try to release any QgsProject layer at this path.
            _release_layers_at_path(p)
            try:
                with open(p, 'r+b'):
                    pass
            except (PermissionError, OSError):
                locked_remaining.append(os.path.basename(p))
    if locked_remaining:
        feedback.pushWarning(
            "Some existing output files are locked by another process: "
            + ", ".join(locked_remaining)
            + ". The run will retry mid-run; if it fails, close the "
            "file in any other application and re-run.")

    feedback.pushInfo("Preflight checks complete.")


# P1.30 batch 20c: input-filename consistency check.
#
# Scans loaded input layer source paths for tokens that look like ISO3
# country codes or 4-digit years. If a different value appears in any
# input filename AND the declared value (typed by the user in the dock)
# is absent from that filename, push a non-blocking warning. Catches the
# "loaded the 2010 forest raster but typed year=2020" class of error.
#
# Conservative rule: only warn on EXPLICIT mismatch. False-positive risk
# (e.g. coincidental three-letter substrings in a path) is the price for
# the "user error caught early" benefit. Warnings include the filename
# so the user can fix-or-ignore.

_ISO3_TOKEN_RE = None  # lazy
_YEAR_TOKEN_RE = None


def _scan_filename_tokens(filename):
    """Return (iso3_tokens, year_tokens) found in a filename.

    ISO3 tokens: bare 3-letter uppercase tokens between word boundaries.
    Year tokens: 4-digit tokens in 1990-2030.
    """
    global _ISO3_TOKEN_RE, _YEAR_TOKEN_RE
    if _ISO3_TOKEN_RE is None:
        import re as _re
        _ISO3_TOKEN_RE = _re.compile(r"(?<![A-Za-z0-9])([A-Z]{3})(?![A-Za-z0-9])")
        _YEAR_TOKEN_RE = _re.compile(r"(?<![0-9])(19[9][0-9]|20[0-3][0-9])(?![0-9])")
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    iso3s = set(_ISO3_TOKEN_RE.findall(base))
    years = set(_YEAR_TOKEN_RE.findall(base))
    return iso3s, years


def _check_input_naming_consistency(declared_iso3, declared_year,
                                    input_paths, feedback):
    """Warn (non-blocking) on ISO3/year mismatches in loaded input paths.

    `declared_iso3` may be None/empty; `declared_year` is the YEAR string
    (could be a comma list, "all", or single year). `input_paths` is a
    list of (label, path) tuples for the inputs to scan.
    """
    feedback.pushInfo("=== Input filename sanity check ===")
    declared_iso3 = (declared_iso3 or "").upper().strip()
    # Parse declared year(s) into a set of single-year strings; "all"
    # means "anything goes — don't warn on year".
    declared_years = set()
    declared_year_str = (declared_year or "").strip()
    if declared_year_str.lower() == "all":
        check_year = False
    else:
        check_year = True
        for tok in declared_year_str.replace(",", " ").split():
            tok = tok.strip()
            if tok.isdigit() and len(tok) == 4:
                declared_years.add(tok)
        if not declared_years:
            check_year = False  # nothing to check
    n_warned = 0
    for label, path in input_paths:
        if not path:
            continue
        iso3s, years = _scan_filename_tokens(path)
        # ISO3 mismatch warning
        if declared_iso3 and iso3s:
            other_iso3s = iso3s - {declared_iso3}
            if other_iso3s and declared_iso3 not in iso3s:
                feedback.pushWarning(
                    f"Input '{label}' has filename containing "
                    f"'{', '.join(sorted(other_iso3s))}' but you declared "
                    f"ISO3='{declared_iso3}'. Confirm the right input is "
                    f"loaded, or update the ISO3 prefix.")
                n_warned += 1
        # Year mismatch warning
        if check_year and years:
            other_years = years - declared_years
            if other_years and not (declared_years & years):
                feedback.pushWarning(
                    f"Input '{label}' has filename containing year "
                    f"'{', '.join(sorted(other_years))}' but you declared "
                    f"year='{declared_year_str}'. Confirm the right input "
                    f"is loaded, or update the year tag.")
                n_warned += 1
    # 20f cross-input consistency: even if every input matches the
    # declared values individually, an OUTLIER in the input set is
    # still suspect. E.g. user declared year=2020 and 4 of 5 inputs
    # have 2020 in the filename, but 1 has 2010 -- worth flagging
    # the odd one out.
    iso3_distribution = {}  # iso3 -> [labels...]
    year_distribution = {}  # year -> [labels...]
    for label, path in input_paths:
        if not path:
            continue
        iso3s, years = _scan_filename_tokens(path)
        for tok in iso3s:
            iso3_distribution.setdefault(tok, []).append(label)
        for tok in years:
            year_distribution.setdefault(tok, []).append(label)

    def _flag_outliers(distribution, kind):
        nonlocal n_warned
        if len(distribution) < 2:
            return
        # An outlier is a value held by exactly 1 input when at least
        # one OTHER value is held by 2+ inputs. Avoids noise when the
        # distribution is balanced (e.g. 2 inputs say 2010 + 2 say
        # 2020 -- could be intentional).
        majority_values = [
            v for v, labels in distribution.items() if len(labels) >= 2]
        if not majority_values:
            return
        for value, labels in distribution.items():
            if len(labels) == 1 and value not in majority_values:
                feedback.pushWarning(
                    f"Outlier {kind} in input '{labels[0]}': "
                    f"filename contains '{value}' while "
                    f"{', '.join(majority_values)} appear(s) in "
                    f"other inputs. Confirm this is the right file.")
                n_warned += 1

    _flag_outliers(iso3_distribution, "ISO3")
    _flag_outliers(year_distribution, "year")

    if n_warned == 0:
        feedback.pushInfo("Input filenames look consistent with "
                          "declared ISO3 / year.")


# ---------------------------------------------------------------------------
# Batch 28.3: slot-vs-filename hint check
# ---------------------------------------------------------------------------
# Per-input heuristic. For each named input slot, if the loaded file's
# basename contains a substring associated with a SIBLING slot (e.g.
# 'small' loaded into the 'large' slot), warn. Non-blocking. Catches
# the most common dock-side picker mistake -- user picks a same-family
# raster but for the wrong sub-slot.
#
# Each rule entry: slot label -> (expected_substrings, alarm_substrings).
# - expected: at least one of these SHOULD be in the basename.
# - alarm:   if any of these is in the basename, that's a likely
#            wrong-sub-slot pick.
# Substring matching is case-insensitive.
_SLOT_FILENAME_HINTS = {
    "forest_raster": (
        ("forest", "treecover", "tree_cover", "tree_height", "hansen", "glad"),
        ("plantation", "planted_forest", "agriculture", "roads", "builtup",
         "dem", "slope", "protect"),
    ),
    "olwtc": (
        ("plantation", "tree_crops", "other_land_with_tree_cover",
         "agri_tree_cover", "agriculture_tree_cover", "fra_agri", "olwtc",
         "oltc"),
        ("roads", "builtup", "dem", "slope", "protect"),
    ),
    "planted_forest": (
        ("plantation", "planted_forest", "planted"),
        ("roads", "builtup", "dem", "slope", "protect", "agriculture",
         "tree_crops"),
    ),
    "roads_vector": (
        ("road",),
        ("forest", "plantation", "builtup", "dem", "slope", "protect",
         "agriculture"),
    ),
    "roads_raster": (
        ("road",),
        ("forest", "plantation", "builtup", "dem", "slope", "protect",
         "agriculture"),
    ),
    "builtup_small": (
        ("small",),
        ("_large_", "_large.", "large_"),
    ),
    "builtup_large": (
        ("large",),
        ("_small_", "_small.", "small_"),
    ),
    "agriculture": (
        ("agriculture",),
        ("forest", "roads", "builtup", "dem", "slope", "protect",
         "plantation", "tree_crops", "other_land_with_tree_cover"),
    ),
    "dem": (
        ("dem", "elevation", "alos", "srtm"),
        ("slope",),
    ),
    "slope": (
        ("slope",),
        ("dem", "elevation"),
    ),
    "protected_vector": (
        ("protect", "wdpa"),
        ("forest", "plantation", "agriculture", "roads", "builtup", "dem",
         "slope"),
    ),
    "protected_raster": (
        ("protect", "wdpa"),
        ("forest", "plantation", "agriculture", "roads", "builtup", "dem",
         "slope"),
    ),
    "aoi": (
        ("aoi", "boundary", "vector"),
        ("forest", "plantation", "agriculture", "roads", "builtup", "dem",
         "slope", "protect"),
    ),
}


def _check_input_slot_filename_hints(input_paths, feedback):
    """Heuristic slot-vs-filename consistency check.

    For each (label, path) pair in ``input_paths``, look at the filename
    against the slot's expected/alarm substring rules in
    ``_SLOT_FILENAME_HINTS``. Emit non-blocking warnings on suspected
    wrong-slot picks. Catches the BUILTUP_LARGE-with-a-small-file class
    of dock-side mistake.

    Custom slots (custom_1/2/3) are skipped -- user-defined, no rule.
    Slots not in the rules dict are skipped silently.
    """
    feedback.pushInfo("=== Input slot vs filename heuristic ===")
    n_warned = 0
    for label, path in input_paths:
        if not path:
            continue
        rule = _SLOT_FILENAME_HINTS.get(label)
        if rule is None:
            continue
        expected, alarm = rule
        base = os.path.basename(path).lower()
        # Alarm substrings are the strongest signal of a wrong-slot pick
        for alarm_str in alarm:
            if alarm_str in base:
                feedback.pushWarning(
                    f"Slot '{label}' got file with '{alarm_str}' in its "
                    f"name: {os.path.basename(path)}. "
                    f"Likely wrong sub-slot -- expected hint: "
                    f"{', '.join(expected)}.")
                n_warned += 1
                break  # one alarm per slot is enough
        else:
            # No alarm match; check that at least one expected hint is
            # present. A file lacking ALL expected hints is a softer
            # signal (could be a user-renamed file or a national variant
            # we haven't seen) -- emit a quieter Info note rather than
            # a Warning, only when something else looked off.
            has_expected = any(e in base for e in expected)
            if not has_expected:
                # Skip the soft Info -- many user-renamed files won't
                # contain canonical hints and that's fine. Only the
                # alarm cases (above) are worth surfacing.
                pass
    if n_warned == 0:
        feedback.pushInfo("Input slot/filename hints look consistent.")


class FullWorkflowAlgorithm(QgsProcessingAlgorithm):
    # -- Inputs --
    FOREST_RASTER = "FOREST_RASTER"
    ROADS = "ROADS"
    ROADS_RASTER = "ROADS_RASTER"
    BUILTUP_SMALL_RASTER = "BUILTUP_SMALL_RASTER"
    BUILTUP_LARGE_RASTER = "BUILTUP_LARGE_RASTER"
    AGRICULTURE_RASTER = "AGRICULTURE_RASTER"
    # ISO3 country code prefix for output filenames (Option D / P1.13).
    # Optional; when blank, the prefix is omitted from filenames.
    ISO3_PREFIX = "ISO3_PREFIX"
    # Batch 30: optional sub-national / ecosystem area name. Inserted
    # between ISO3 and year in output filenames when set; e.g.
    # KEN_aberdares_district_2020_qgis_04a_primary_forest.tif. Free-
    # form (sanitised by utils._sanitise_label), max 16 chars in the
    # dock. ISO3 stays a strict 3-letter code so CRS suggestion +
    # filename-sanity checks keep working.
    REGION_LABEL = "REGION_LABEL"
    # Custom human-use disturbance slots (3, all optional, all FlagAdvanced).
    # Each slot has a raster input, a user-editable label (shown in logs +
    # metadata), and a per-slot buffer distance. Plumbed through prepare /
    # distance / anthro-mask stages alongside the built-in roads / builtup /
    # agriculture inputs.
    CUSTOM_1_RASTER = "CUSTOM_1_RASTER"
    CUSTOM_1_LABEL = "CUSTOM_1_LABEL"
    CUSTOM_1_DIST = "CUSTOM_1_DIST"
    CUSTOM_2_RASTER = "CUSTOM_2_RASTER"
    CUSTOM_2_LABEL = "CUSTOM_2_LABEL"
    CUSTOM_2_DIST = "CUSTOM_2_DIST"
    CUSTOM_3_RASTER = "CUSTOM_3_RASTER"
    CUSTOM_3_LABEL = "CUSTOM_3_LABEL"
    CUSTOM_3_DIST = "CUSTOM_3_DIST"
    DEM = "DEM"
    SLOPE_RASTER = "SLOPE_RASTER"
    PROTECTED_AREAS = "PROTECTED_AREAS"
    PROTECTED_RASTER = "PROTECTED_RASTER"
    PLANTATIONS_RASTER = "PLANTATIONS_RASTER"
    # P1.18: optional FRA-aligned agricultural tree cover raster
    # (Descals oil palm + SDPT class 2). Distinct from AGRICULTURE_RASTER
    # which is the broader buffered-disturbance agriculture (cropland +
    # pasture + everything). When supplied AND
    # EXCLUDE_AGRICULTURE_FROM_FOREST is on, this layer is subtracted
    # from the forest baseline to derive a FRA-strict Forest layer.
    FRA_AGRICULTURE_RASTER = "FRA_AGRICULTURE_RASTER"
    AOI = "AOI"
    # -- Parameters --
    # P1.30 batch 20a.3: free-form year string. Either a calendar year
    # (e.g. "2020") or "all" when the dock's "All years since 2000"
    # checkbox is on. Metadata-only for now -- the workflow runs once
    # per invocation regardless. Future batch may iterate when "all".
    YEAR = "YEAR"
    TARGET_CRS = "TARGET_CRS"
    TARGET_CRS_EPSG = "TARGET_CRS_EPSG"
    AUTO_UTM = "AUTO_UTM"
    AOI_BUFFER = "AOI_BUFFER"
    ROADS_DIST = "ROADS_DIST"
    BUILTUP_DIST = "BUILTUP_DIST"
    BUILTUP_LARGE_DIST = "BUILTUP_LARGE_DIST"
    AGRICULTURE_DIST = "AGRICULTURE_DIST"
    MAX_DISTANCE = "MAX_DISTANCE"
    USE_SINGLE_DISTANCE = "USE_SINGLE_DISTANCE"
    ALL_BUFFERS_DIST = "ALL_BUFFERS_DIST"
    SLOPE_THRESHOLD = "SLOPE_THRESHOLD"
    SMOOTH_RADIUS = "SMOOTH_RADIUS"
    DENSITY_THRESHOLD = "DENSITY_THRESHOLD"
    FAST_APPROXIMATION = "FAST_APPROXIMATION"
    REFINE_MIN_PATCH_AREA_HA = "REFINE_MIN_PATCH_AREA_HA"
    SAVE_COMBINED_RASTER = "SAVE_COMBINED_RASTER"
    # P1.30 batch 22: per-layer Save list. Each flag gates whether the
    # corresponding final output is COPIED from scratch into out_dir.
    # Defaults preserve historical behaviour: 02b/02d/04a always saved
    # (today's de-facto), 03c/04e default OFF (intermediate / debug).
    # Algorithm always computes the rasters internally; flags only
    # control disk presence in the user's output folder.
    SAVE_02B_FOREST = "SAVE_02B_FOREST"
    SAVE_02D_NRF = "SAVE_02D_NRF"
    SAVE_03C_PRE_CONN = "SAVE_03C_PRE_CONN"
    SAVE_04A_PRIMARY = "SAVE_04A_PRIMARY"
    SAVE_04E_ANTHRO_MASK = "SAVE_04E_ANTHRO_MASK"
    EXCLUDE_PLANTATIONS = "EXCLUDE_PLANTATIONS"
    EXCLUDE_AGRICULTURE_FROM_FOREST = "EXCLUDE_AGRICULTURE_FROM_FOREST"
    REUSE_DISTANCE_SURFACES = "REUSE_DISTANCE_SURFACES"
    REUSE_PREPARED = "REUSE_PREPARED"
    ADD_MAIN_OUTPUTS_TO_MAP = "ADD_MAIN_OUTPUTS_TO_MAP"
    ADD_HUMAN_INFLUENCE_LAYERS_TO_MAP = "ADD_HUMAN_INFLUENCE_LAYERS_TO_MAP"
    # P1.30 (batch 20a.2): redirect intermediates to a non-cloud-synced
    # scratch dir under the QGIS profile to sidestep OneDrive CFAPI
    # placeholder issues that bite on subprocess reads of just-written
    # rasters (gdal:polygonize, gdalwarp). Default ON. Power users can
    # opt out for debugging or to keep everything next to outputs.
    LOCAL_SCRATCH_INTERMEDIATES = "LOCAL_SCRATCH_INTERMEDIATES"
    CLEANUP_INTERMEDIATES = "CLEANUP_INTERMEDIATES"
    # -- Per-stage enable tickboxes (skip stages for faster runs) --
    ENABLE_ROADS_BUFFER = "ENABLE_ROADS_BUFFER"
    ENABLE_BUILTUP_SMALL_BUFFER = "ENABLE_BUILTUP_SMALL_BUFFER"
    ENABLE_BUILTUP_LARGE_BUFFER = "ENABLE_BUILTUP_LARGE_BUFFER"
    ENABLE_AGRICULTURE_BUFFER = "ENABLE_AGRICULTURE_BUFFER"
    ENABLE_REFINE_OUTPUT = "ENABLE_REFINE_OUTPUT"
    # -- Zonal statistics (optional) --
    RUN_ZONAL_STATS = "RUN_ZONAL_STATS"
    ZONE_LAYER = "ZONE_LAYER"
    ZONE_FIELD = "ZONE_FIELD"
    # -- Vectorisation (optional, advanced) --
    # Vectorise runs whenever any of VECTORIZE_PRIMARY / VECTORIZE_FOREST
    # / VECTORIZE_NEST is ticked. P1.28c semantics: each tick produces
    # ONLY its named output (no auto-enables, no side-effect outputs).
    VECTORIZE_PRIMARY = "VECTORIZE_PRIMARY"
    VECTORIZE_FOREST = "VECTORIZE_FOREST"
    VECTORIZE_NEST = "VECTORIZE_NEST"
    VECTORIZE_DISSOLVE_MULTIPART = "VECTORIZE_DISSOLVE_MULTIPART"
    VECTORIZE_SIMPLIFY_M = "VECTORIZE_SIMPLIFY_M"
    # P1.30 batch 20a.4: drop small connected components from the
    # rasters BEFORE polygonising. Speeds up vectorise + simplify on
    # noisy inputs and reduces output polygon count. Threshold in
    # hectares -- converted to pixels using the raster pixel size at
    # run time. 0 = off.
    VECTORIZE_MIN_PATCH_AREA_HA = "VECTORIZE_MIN_PATCH_AREA_HA"
    # P1.30 batch 20a.5: auto-remove redundant collinear vertices
    # introduced by gdal:polygonize on raster-aligned edges. Runs
    # native:simplifygeometries METHOD=2 (Visvalingam-Whyatt area)
    # at half-pixel tolerance after polygonise -- shape-preserving
    # but drops 60-80% of vertex count. Default ON.
    VECTORIZE_REMOVE_PIXEL_STAIRS = "VECTORIZE_REMOVE_PIXEL_STAIRS"
    VECTORIZE_OUTPUT_AS_SHAPEFILE = "VECTORIZE_OUTPUT_AS_SHAPEFILE"
    # -- Output --
    OUTPUT_FOLDER = "OUTPUT_FOLDER"

    def name(self):
        return "full_workflow"

    def displayName(self):
        return "Run Full Workflow"

    def group(self):
        return "Primary Forest Finder"

    def groupId(self):
        return "pff"

    def shortHelpString(self):
        return (
            f"PFF Plugin v{self.PFF_VERSION} -- Full Workflow\n"
            "═══════════════════════════════════════════════\n\n"
            "Parameter labels carry a section prefix (e.g. '02 Tree Cover:') "
            "-- look up the matching section below for the full "
            "description, example sources, and caveats.\n\n"
            "WORKFLOW STAGES\n"
            "  1. Prepare datasets (reproject, rasterise, align)\n"
            "  2. Compute distance surfaces\n"
            "  3. Build anthropogenic mask + tier logic\n"
            "  4. Three-tier primary forest (undisturbed / steep / protected)\n"
            "  5. Refine Output -- ecological viability filter\n"
            "  6. Zonal Statistics (optional)\n"
            "  7. Vectorise outputs (optional)\n\n"
            "═══════════════════════════════════════════════\n"
            "§00 COUNTRY / CONTEXT\n"
            "═══════════════════════════════════════════════\n"
            "00 Country: AOI boundary (vector, optional)\n"
            "    Vector polygon defining country / region. Used to clip\n"
            "    rasters and as the boundary for stats.\n"
            "00 Country: ISO3 prefix\n"
            "    3-letter country code prepended to every output\n"
            "    filename (e.g. KEN -> KEN_qgis_04a_primary_forest.tif).\n"
            "    Leave blank to omit. Cased uppercase.\n"
            "00 Country: Auto UTM\n"
            "    Detects appropriate UTM zone from AOI / forest raster\n"
            "    centroid. Overrides Target CRS picker.\n"
            "00 Country: Target CRS\n"
            "    Manual projected CRS picker. Used when Auto UTM is off.\n"
            "00 Country: Target CRS EPSG (string fallback)\n"
            "    EPSG code as text (e.g. '5266' or 'EPSG:5266'). Workshop\n"
            "    fallback when picker can't find your zone. Overrides\n"
            "    Target CRS picker.\n"
            "00 Country: AOI buffer (advanced)\n"
            "    Extends analysis area past the country border so\n"
            "    edge-of-country anthropogenic features still influence\n"
            "    buffers. Default 2000 m.\n\n"
            "═══════════════════════════════════════════════\n"
            "§02 TREE COVER\n"
            "═══════════════════════════════════════════════\n"
            "Order matches the workflow sequence: forest input first,\n"
            "then OLTC exclusion (narrows tree cover -> FRA Forest), then\n"
            "planted-forest exclusion (narrows Forest -> Naturally\n"
            "Regenerating).\n\n"
            "Forest raster (REQUIRED)\n"
            "    Binary 1/0 raster. Defines the reference grid (extent /\n"
            "    resolution / pixel origin) -- all other rasters align to it.\n"
            "    Example sources: Hansen GFC thresholded, GLAD LULC forest\n"
            "    class, national forest map. GEE filename: 02c_forest_*\n\n"
            "Other land with tree cover raster (optional)\n"
            "    Binary 1/0. FRA-Note-10 'other land with tree cover':\n"
            "    oil palm, orchards, agroforestry-with-crops, urban trees.\n"
            "    NOT the broader buffered agriculture (cropland + pasture).\n"
            "    Paired with 'Refine to forest' toggle. Example sources:\n"
            "    GEE export 02b_other_land_with_tree_cover (Descals oil\n"
            "    palm + SDPT class 2 + urban tree cover).\n\n"
            "Refine to forest (default ON)\n"
            "    Requires OLTC raster above. When on: narrows\n"
            "    02c_forest = tree_cover MINUS other land with tree cover,\n"
            "    BEFORE the planted-forest subtraction. Harmless no-op when\n"
            "    no OLTC raster supplied.\n\n"
            "Planted forest raster (optional)\n"
            "    Binary 1/0. FRA Planted Forest (timber/pulp/fibre):\n"
            "    eucalyptus, pine, teak. Paired with 'Refine to naturally\n"
            "    regenerating forest' toggle. Example sources: SDPT class 1,\n"
            "    national planted-forest registry. When supplied AND toggle\n"
            "    is on, workflow outputs 02e_naturally_regenerating_forest.tif\n"
            "    (≈ FRA NRF = Forest minus planted forest -- proxy, depends\n"
            "    on planted-forest layer completeness).\n"
            "    GEE filename: 02d_planted_forest_*\n\n"
            "Refine to naturally regenerating forest (default ON)\n"
            "    Requires Planted forest raster above. When on: derives\n"
            "    02e_naturally_regenerating_forest as 02c MINUS 02d\n"
            "    (Forest minus Planted forest).\n\n"
            "═══════════════════════════════════════════════\n"
            "§03 HUMAN INFLUENCE -- (a) DISTURBANCE INPUTS\n"
            "═══════════════════════════════════════════════\n"
            "Inputs that get distance-buffered to remove nearby forest\n"
            "from candidate primary forest. The 'agriculture' here is the\n"
            "broader buffered concept -- includes cropland + pasture +\n"
            "everything human-use signalling, NOT FRA-aligned.\n\n"
            "03a Disturbance Inputs: Roads (vector, optional)\n"
            "03a Disturbance Inputs: Roads raster -- overrides vector. GEE: 03a_roads_*\n"
            "03a Disturbance Inputs: Built-up small raster -- GHS-BUILT (villages).\n"
            "    GEE: 03a_builtup_small_*\n"
            "03a Disturbance Inputs: Built-up large raster -- GHS-BUILT (cities).\n"
            "    GEE: 03a_builtup_large_*\n"
            "03a Disturbance Inputs: Agriculture raster -- GLAD LULC, ESA WorldCover, etc.\n"
            "    GEE: 03a_agriculture_*\n"
            "03a Disturbance Inputs: Custom 1 / 2 / 3 raster + label + buffer (advanced)\n"
            "    Three slots, each with its own raster + user-editable\n"
            "    label + per-slot buffer distance. Bring your own\n"
            "    disturbance: pipelines, mines, lights at night, navigable\n"
            "    waterways, country-specific layers. Label shows in logs +\n"
            "    metadata. Buffer 0 = apply input directly without expansion.\n\n"
            "═══════════════════════════════════════════════\n"
            "§03 HUMAN INFLUENCE -- (b) BUFFERS\n"
            "═══════════════════════════════════════════════\n"
            "Buffer = 0 rule: when a per-input buffer is 0 AND its\n"
            "'Include ... buffer' tickbox is on, the input footprint is\n"
            "applied DIRECTLY to the anthropogenic mask (no expansion). To\n"
            "skip an input entirely, UNTICK its 'Include ... buffer'.\n\n"
            "03b Buffers: Use single buffer distance for all anthropogenic layers\n"
            "    Overrides individual values when ticked.\n"
            "03b Buffers: Single buffer distance (m) (used when 03b ticked)\n"
            "03b Buffers: Roads buffer enable\n"
            "03b Buffers: Roads buffer distance (m)\n"
            "03b Buffers: Built-up small buffer enable\n"
            "03b Buffers: Built-up small buffer distance (m)\n"
            "03b Buffers: Built-up large buffer enable\n"
            "03b Buffers: Built-up large buffer distance (m)\n"
            "03b Buffers: Agriculture buffer enable\n"
            "03b Buffers: Agriculture buffer distance (m)\n"
            "03b Buffers: Maximum distance (m) (advanced)\n"
            "    Cap for speed; should be > largest buffer distance.\n\n"
            "═══════════════════════════════════════════════\n"
            "§03 HUMAN INFLUENCE -- (c) BUFFER EXCEPTIONS\n"
            "═══════════════════════════════════════════════\n"
            "Inputs that PRESERVE forest from disturbance buffering --\n"
            "naturally protected (steep slopes) or legally protected\n"
            "(WDPA pre-filtered to a year cutoff so PAs designated AFTER\n"
            "the analysis year aren't given retroactive credit).\n\n"
            "03c Buffer Exceptions: DEM (elevation, metres). Slope computed from this.\n"
            "    GEE: 03b_protection_natural_dem_*\n"
            "03c Buffer Exceptions: Slope raster (degrees, 0-90). Overrides DEM if both supplied.\n"
            "    GEE: 03b_protection_natural_slope_*\n"
            "03c Buffer Exceptions: Protected areas (vector, optional)\n"
            "03c Buffer Exceptions: Protected areas raster -- overrides vector.\n"
            "    GEE: 03b_protection_legal_*\n"
            "03c Buffer Exceptions: Slope threshold (degrees). Default 45.\n\n"
            "═══════════════════════════════════════════════\n"
            "§04 REFINE OUTPUT -- ECOLOGICAL VIABILITY\n"
            "═══════════════════════════════════════════════\n"
            "Produces 04a_primary_forest from 03c_pre_refinement_primary_forest\n"
            "by removing patches that fail ecological viability criteria.\n"
            "Two optional sub-steps:\n\n"
            "04 Refine Output: Enable refine output (master toggle)\n"
            "04 Refine Output: Step (a): neighbourhood radius (m). 0 = skip step (a).\n"
            "    Smooths binary forest with a circular kernel; pixels below\n"
            "    density threshold are dropped.\n"
            "04 Refine Output: Step (a): minimum density to keep (0-1)\n"
            "04 Refine Output: Step (a): fast approximation (advanced)\n"
            "    Square kernel instead of circular -- faster, slight shape\n"
            "    difference. Off by default.\n"
            "04 Refine Output: Step (b): minimum patch area, hectares. 0 = skip step (b).\n"
            "    Uses gdal:sieve. Hole-fill is masked back to step input so\n"
            "    artefacts can't introduce pixels outside the input forest.\n\n"
            "═══════════════════════════════════════════════\n"
            "§05 STATISTICS\n"
            "═══════════════════════════════════════════════\n"
            "05 Statistics: Run zonal statistics (master toggle)\n"
            "05 Statistics: Zone layer (polygons)\n"
            "05 Statistics: Zone name / ID field\n\n"
            "═══════════════════════════════════════════════\n"
            "§06 VALIDATION / VECTORISE (advanced)\n"
            "═══════════════════════════════════════════════\n"
            "Polygonise + optional simplify + dissolve. Same pipeline as\n"
            "the standalone 'Vectorize PFF output' tool.\n\n"
            "Stage runs whenever any of the layer ticks below is set.\n\n"
            "06 Validation: Vectorise: primary forest\n"
            "06 Validation: Vectorise: forest input (uses naturally regenerating if\n"
            "    plantations refined)\n"
            "06 Validation: Vectorise: nest outputs (cut primary out of forest -- ideal\n"
            "    CEO stratification)\n"
            "06 Validation: Vectorise: simplify tolerance, metres. 0 = no simplify.\n"
            "    Use with caution -- can introduce geometry artefacts.\n\n"
            "═══════════════════════════════════════════════\n"
            "RUN OPTIONS / TIPS\n"
            "═══════════════════════════════════════════════\n"
            "Save combined coded raster: 4-class debug raster (0=none,\n"
            "    1=forest, 2=pre-connectivity, 3=primary).\n"
            "Reuse cached distance surfaces (default OFF, advanced)\n"
            "    Distance computation is the slowest stage. Output files\n"
            "    (intermediates/distances/dist_*.tif) can be reused across\n"
            "    runs when only tuning thresholds. OFF by default so stale\n"
            "    cache can't silently produce wrong results if inputs change.\n"
            "Reuse preprocessing/*.tif cache (default ON)\n"
            "    Skips reprojection of anthro inputs when cached aligned\n"
            "    raster matches the reference grid. Untick if you swapped a\n"
            "    source raster.\n"
            "Add main outputs to map (default ON)\n"
            "    Auto-loads Primary forest, Pre-connectivity forest, Forest,\n"
            "    Naturally regenerating forest after the run completes.\n"
            "    Order matches GEE legend: Primary on top.\n"
            "Add human influence layers to map (default OFF)\n"
            "    Mirrors GEE master toggle. Loads roads, builtup, ag,\n"
            "    plantations, slope, protected, custom slots.\n"
            "    Anthropogenic mask intentionally NOT auto-loaded -- it's\n"
            "    a debug intermediate; available at 04e_anthropogenic_mask.tif.\n\n"
            "Speed vs detail:\n"
            "  Runtime scales linearly with raster pixel count. Doubling\n"
            "  resolution (60m -> 30m) ~quadruples runtime. Linear features\n"
            "  (roads, narrow rivers) are 1-pixel-wide; coarser than ~45m\n"
            "  they get under-represented during rasterisation, so road\n"
            "  buffers may miss segments. Export at 30m or finer if road\n"
            "  buffers matter; 60-100m is fine for built-up / ag / protection.\n\n"
            "Fast re-run workflow (tuning thresholds only):\n"
            "  1. Point input rasters at [previous-out]/intermediates/preprocessing/\n"
            "     (already aligned to the reference grid).\n"
            "  2. Tick 'Reuse cached distance surfaces'.\n"
            "  3. Use the same output folder so the cache is found.\n"
            "  Result: reproject + distance stages skipped, only tier +\n"
            "  refine logic runs -- much faster iteration.\n\n"
            "═══════════════════════════════════════════════\n"
            "OUTPUT FOLDER LAYOUT\n"
            "═══════════════════════════════════════════════\n"
            "OUT = your chosen output folder. ISO3_ prefix when 00 set.\n\n"
            "  OUT/[ISO3_]qgis_02c_forest.tif (Forest baseline; FRA-strict\n"
            "      when 02 ticked)\n"
            "  OUT/[ISO3_]qgis_02e_naturally_regenerating_forest.tif\n"
            "      (if plantations refined)\n"
            "  OUT/[ISO3_]qgis_03c_pre_refinement_primary_forest.tif\n"
            "      (after Step 03 disturbance + protection logic)\n"
            "  OUT/[ISO3_]qgis_03d_combined_coded_raster.tif\n"
            "      (if Save combined ticked; tier-logic debug)\n"
            "  OUT/[ISO3_]qgis_04a_primary_forest.tif\n"
            "      (after Step 04 viability filter -- HEADLINE result)\n"
            "  OUT/[ISO3_]qgis_04e_anthropogenic_mask.tif (intermediate)\n"
            "  OUT/[ISO3_]qgis_05a_area_statistics.csv (if 05 ticked)\n"
            "  OUT/[ISO3_]qgis_05b_area_statistics_by_zone.gpkg\n"
            "  OUT/[ISO3_]qgis_06a_primary_forest_vector.gpkg\n"
            "      (if Vectorise: primary ticked)\n"
            "  OUT/[ISO3_]qgis_06c_<forest>_vector.gpkg\n"
            "      (if Vectorise: forest ticked)\n"
            "  OUT/[ISO3_]qgis_06c_<forest>_with_primary_nested_vector.gpkg\n"
            "      (if Vectorise: nest ticked)\n"
            "  OUT/[ISO3_]qgis_06d_<forest>_with_primary_nested_dissolved.gpkg\n"
            "      (if Vectorise: nest + dissolve_multipart ticked)\n"
            "  OUT/[ISO3_]qgis_run_metadata.json\n"
            "  OUT/intermediates/ (tier rasters, preprocessing cache,\n"
            "                     distance cache, scratch workspaces)\n"
        )

    def createInstance(self):
        return FullWorkflowAlgorithm()

    # ------------------------------------------------------------------ #
    #  Parameters
    # ------------------------------------------------------------------ #

    def initAlgorithm(self, config=None):
        # Parameter labels use §x.y numbering matching the help panel
        # (shortHelpString) sections. Click Help in the dialog for full
        # descriptions, sources, and caveats per parameter.
        # Sections echo the GEE left-panel structure:
        #   00 Country / Context
        #   02 Forest Definition
        #   03a/b/c Human Influence
        #   04 Refine Output
        #   05 Statistics
        #   06 Validation / Vectorise
        #   (unnumbered) Run options + Output folder

        # ────────────────────────────────────────────────────────────
        # §00 — Country / Context
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.AOI, "00 Country: AOI boundary (vector, optional)",
            optional=True))
        self.addParameter(QgsProcessingParameterString(
            self.ISO3_PREFIX,
            "00 Country: ISO3 prefix (e.g. 'KEN'; leave blank to omit)",
            defaultValue="",
            optional=True))
        # Batch 30: optional sub-national / ecosystem area name.
        self.addParameter(QgsProcessingParameterString(
            self.REGION_LABEL,
            "00 Country: Sub-national area name (optional; e.g. "
            "'aberdares_district', 'coastal_ecosystem'; max 16 chars)",
            defaultValue="",
            optional=True))
        # P1.30 batch 20a.3: time-period tag (metadata-only).
        self.addParameter(QgsProcessingParameterString(
            self.YEAR,
            "00 Country: Year tag (e.g. '2020' or 'all'; metadata only)",
            defaultValue="2020",
            optional=True))
        # P1.30 batch 20b.1: AUTO_UTM is deprecated. The dock no longer
        # exposes the checkbox; the parameter is parsed and ignored at
        # run time so saved Recent runs / Processing > History entries
        # with AUTO_UTM=True don't crash on replay. Failure modes: zone-
        # straddling AOIs, countries with proper national grids, silent
        # mismatch between heuristic and real-world expectations. Use
        # the dock's suggested-CRS dropdown or set Target CRS / EPSG.
        self.addParameter(QgsProcessingParameterBoolean(
            self.AUTO_UTM,
            "00 Country: Auto-detect UTM (DEPRECATED -- set Target CRS "
            "explicitly; this flag is ignored)",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterCrs(
            self.TARGET_CRS,
            "00 Country: Target projected CRS (ignored when Auto UTM ticked)",
            defaultValue="EPSG:32717"))
        self.addParameter(QgsProcessingParameterString(
            self.TARGET_CRS_EPSG,
            "00 Country: OR target CRS as EPSG code (e.g. '5266'; overrides picker)",
            defaultValue="",
            optional=True))
        _aoi_buf_param = QgsProcessingParameterNumber(
            self.AOI_BUFFER,
            "00 Country: AOI buffer distance (m, advanced)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=AOI_BUFFER, minValue=0)
        _aoi_buf_param.setFlags(
            _aoi_buf_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_aoi_buf_param)

        # ────────────────────────────────────────────────────────────
        # §02 — Forest Definition
        # Order matches workflow sequence: tree cover input first, then
        # FRA agriculture (subtracted at 02a→02b to derive FRA Forest),
        # then plantations (subtracted at 02b→02d to derive Naturally
        # Regenerating). Toggles follow each input.
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.FOREST_RASTER,
            "02 Tree Cover: Forest raster (REQUIRED; binary 1/0; defines reference grid)"))
        # P1.22: paired plantations + planted-forest exclusions follow
        # the FRA forest-derivation flow:
        #   tree cover - plantations    = Forest (FRA Note 10 baseline)
        #   Forest    - planted forest = Naturally regenerating forest
        # Plantations FIRST in the parameter list so the UI reads in
        # workflow order. See About panel in GEE app for full FRA
        # definitions and rubber caveat.
        # P1.27: parallel/aligned shorter labels. FRA Note 7 / Note 10
        # caveats + rubber caveat live in the GEE app About panel and the
        # workshop guide -- keeping the parameter labels short is far
        # better UX in the QGIS Processing dialog.
        #   raster: "02 Tree Cover: <NAME> raster -- e.g. <examples> ..."
        #   toggle: "02 Tree Cover: Refine to <result> (exclude <NAME> raster above)"
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.FRA_AGRICULTURE_RASTER,
            "02 Tree Cover: Other land with tree cover raster -- e.g. oil "
            "palm, orchards, agroforestry (binary 1/0, optional)",
            optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.EXCLUDE_AGRICULTURE_FROM_FOREST,
            "02 Tree Cover: Refine to forest (exclude other land with tree "
            "cover raster above)",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.PLANTATIONS_RASTER,
            "02 Tree Cover: Planted forest raster -- e.g. eucalyptus, pine, "
            "teak (binary 1/0, optional)",
            optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.EXCLUDE_PLANTATIONS,
            "02 Tree Cover: Refine to naturally regenerating forest "
            "(exclude planted forest raster above)",
            defaultValue=True))

        # ────────────────────────────────────────────────────────────
        # §03a — Human Influence: Disturbance inputs
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.ROADS, "03a Disturbance Inputs: Roads (vector, optional)",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.ROADS_RASTER,
            "03a Disturbance Inputs: Roads raster (binary 1/0; overrides vector)",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.BUILTUP_SMALL_RASTER,
            "03a Disturbance Inputs: Built-up small raster (binary 1/0)",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.BUILTUP_LARGE_RASTER,
            "03a Disturbance Inputs: Built-up large raster (binary 1/0)",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.AGRICULTURE_RASTER,
            "03a Disturbance Inputs: Agriculture raster (binary 1/0; broader buffered ag, "
            "NOT FRA-aligned)",
            optional=True))
        for _i in range(1, 4):
            _r_const = getattr(self, f"CUSTOM_{_i}_RASTER")
            _l_const = getattr(self, f"CUSTOM_{_i}_LABEL")
            _d_const = getattr(self, f"CUSTOM_{_i}_DIST")
            _base = 5 + (_i - 1) * 3  # 03a.6, 03a.9, 03a.12
            _r_param = QgsProcessingParameterRasterLayer(
                _r_const,
                f"03a.{_base + 1} Custom {_i} raster (advanced)",
                optional=True)
            _r_param.setFlags(_r_param.flags()
                              | QgsProcessingParameterDefinition.FlagAdvanced)
            self.addParameter(_r_param)
            _l_param = QgsProcessingParameterString(
                _l_const,
                f"03a.{_base + 2}     Custom {_i} label",
                defaultValue=f"Custom disturbance {_i}",
                optional=True)
            _l_param.setFlags(_l_param.flags()
                              | QgsProcessingParameterDefinition.FlagAdvanced)
            self.addParameter(_l_param)
            _d_param = QgsProcessingParameterNumber(
                _d_const,
                f"03a.{_base + 3}     Custom {_i} buffer distance (m; 0 = no buffer)",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1000.0, minValue=0.0)
            _d_param.setFlags(_d_param.flags()
                              | QgsProcessingParameterDefinition.FlagAdvanced)
            self.addParameter(_d_param)

        # ────────────────────────────────────────────────────────────
        # §03b — Human Influence: Buffer distances
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterBoolean(
            self.USE_SINGLE_DISTANCE,
            "03b Buffers: Use single buffer distance for all anthropogenic layers",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterNumber(
            self.ALL_BUFFERS_DIST,
            "03b Buffers: Single buffer distance (m; used when 03b ticked)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=1000, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_ROADS_BUFFER,
            "03b Buffers: Roads buffer enable",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.ROADS_DIST,
            "03b Buffers:     Roads buffer distance (m; 0 = no buffer)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=ROADS_DIST, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_BUILTUP_SMALL_BUFFER,
            "03b Buffers: Built-up (small) buffer enable",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.BUILTUP_DIST,
            "03b Buffers:     Built-up (small) buffer distance (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=BUILTUP_DIST, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_BUILTUP_LARGE_BUFFER,
            "03b Buffers: Built-up (large) buffer enable",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.BUILTUP_LARGE_DIST,
            "03b Buffers:     Built-up (large) buffer distance (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=BUILTUP_LARGE_DIST, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_AGRICULTURE_BUFFER,
            "03b Buffers: Agriculture buffer enable",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.AGRICULTURE_DIST,
            "03b Buffers:     Agriculture buffer distance (m)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=AGRICULTURE_DIST, minValue=0, maxValue=10000))
        _max_dist_param = QgsProcessingParameterNumber(
            self.MAX_DISTANCE,
            "03b Buffers: Maximum distance to compute (m, advanced)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=MAX_DISTANCE, minValue=100)
        _max_dist_param.setFlags(
            _max_dist_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_max_dist_param)

        # ────────────────────────────────────────────────────────────
        # §03c — Human Influence: Buffer Exceptions
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DEM,
            "03c Buffer Exceptions: DEM (elevation, m; slope computed from this)",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.SLOPE_RASTER,
            "03c Buffer Exceptions: OR Slope raster (degrees 0-90; overrides DEM)",
            optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.PROTECTED_AREAS,
            "03c Buffer Exceptions: Protected areas (vector, optional)",
            optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.PROTECTED_RASTER,
            "03c Buffer Exceptions: OR protected areas raster (binary 1/0; overrides vector)",
            optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.SLOPE_THRESHOLD,
            "03c Buffer Exceptions: Slope threshold (degrees)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=SLOPE_THRESHOLD, minValue=0, maxValue=90))

        # ────────────────────────────────────────────────────────────
        # §04 — Refine Output (ecological viability filter)
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterBoolean(
            self.ENABLE_REFINE_OUTPUT,
            "04 Refine Output: Enable refine (two optional steps below)",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.SMOOTH_RADIUS,
            "04 Refine Output:     Step (a): neighbourhood radius (m; 0 = skip)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=SMOOTH_RADIUS, minValue=0, maxValue=10000))
        self.addParameter(QgsProcessingParameterNumber(
            self.DENSITY_THRESHOLD,
            "04 Refine Output:     Step (a): minimum density to keep (0-1)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=DENSITY_THRESHOLD, minValue=0, maxValue=1))
        _fast_approx_param = QgsProcessingParameterBoolean(
            self.FAST_APPROXIMATION,
            "04 Refine Output:     Step (a): fast approximation (square kernel, advanced)",
            defaultValue=False)
        _fast_approx_param.setFlags(
            _fast_approx_param.flags()
            | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_fast_approx_param)
        self.addParameter(QgsProcessingParameterNumber(
            self.REFINE_MIN_PATCH_AREA_HA,
            "04 Refine Output:     Step (b): minimum patch area, hectares (0 = skip)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.0, minValue=0.0))

        # ────────────────────────────────────────────────────────────
        # §05 — Statistics
        # ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterBoolean(
            self.RUN_ZONAL_STATS,
            "05 Statistics: Run zonal statistics",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.ZONE_LAYER,
            "05 Statistics: Zone layer (polygons)",
            optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.ZONE_FIELD,
            "05 Statistics: Zone name / ID field",
            parentLayerParameterName=self.ZONE_LAYER,
            optional=True))

        # ────────────────────────────────────────────────────────────
        # §06 — Validation / Vectorise (advanced)
        # Vectorise runs whenever primary or forest below is ticked; no
        # separate enable flag.
        # ────────────────────────────────────────────────────────────
        _v_primary = QgsProcessingParameterBoolean(
            self.VECTORIZE_PRIMARY,
            "06 Validation:     Vectorise: primary forest",
            defaultValue=False)
        _v_primary.setFlags(_v_primary.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_v_primary)
        _v_forest = QgsProcessingParameterBoolean(
            self.VECTORIZE_FOREST,
            "06 Validation:     Vectorise: forest input (or nat reg if refined)",
            defaultValue=False)
        _v_forest.setFlags(_v_forest.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_v_forest)
        _v_nest = QgsProcessingParameterBoolean(
            self.VECTORIZE_NEST,
            "06 Validation:     Vectorise: nest outputs (cut primary out of forest)",
            defaultValue=False)
        _v_nest.setFlags(_v_nest.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_v_nest)
        _v_dissolve = QgsProcessingParameterBoolean(
            self.VECTORIZE_DISSOLVE_MULTIPART,
            "06 Validation:     Vectorise: also dissolve nested output to "
            "multipart by level (CEO-relevant; slow on big countries with "
            "low simplify)",
            defaultValue=True)
        _v_dissolve.setFlags(_v_dissolve.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_v_dissolve)
        _v_simplify = QgsProcessingParameterNumber(
            self.VECTORIZE_SIMPLIFY_M,
            "06 Validation:     Vectorise: simplify tolerance (m; 0 = no simplify)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.0, minValue=0.0)
        _v_simplify.setFlags(_v_simplify.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_v_simplify)
        _v_min_patch = QgsProcessingParameterNumber(
            self.VECTORIZE_MIN_PATCH_AREA_HA,
            "06 Validation:     Vectorise: min patch area before polygonise "
            "(ha; 0 = no sieve; applies to primary + forest backdrop)",
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.0, minValue=0.0)
        _v_min_patch.setFlags(_v_min_patch.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_v_min_patch)
        _v_pixel_stairs = QgsProcessingParameterBoolean(
            self.VECTORIZE_REMOVE_PIXEL_STAIRS,
            "06 Validation:     Vectorise: auto-clean pixel-stair vertices "
            "(Visvalingam @ half-pixel; drops redundant collinear vertices "
            "from polygonise output)",
            defaultValue=True)
        _v_pixel_stairs.setFlags(_v_pixel_stairs.flags()
                                  | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_v_pixel_stairs)
        _v_format = QgsProcessingParameterBoolean(
            self.VECTORIZE_OUTPUT_AS_SHAPEFILE,
            "06 Validation:     Output as Shapefile (.shp) instead of "
            "GeoPackage (.gpkg) -- default OFF (.gpkg recommended; .shp "
            "limited to 10-char field names + 2GB cap)",
            defaultValue=False)
        _v_format.setFlags(_v_format.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_v_format)

        # ────────────────────────────────────────────────────────────
        # Run options (orthogonal to workflow steps)
        # ────────────────────────────────────────────────────────────
        # P1.30 batch 22: per-layer Save flags. Default values preserve
        # historical behaviour. Marked FlagAdvanced so the auto-
        # Processing-dialog tucks them away under "Advanced parameters".
        for _save_param, _label, _default in (
            (self.SAVE_02B_FOREST,
             "Run: Save 02b forest output",
             True),
            (self.SAVE_02D_NRF,
             "Run: Save 02d naturally regenerating forest output",
             True),
            (self.SAVE_03C_PRE_CONN,
             "Run: Save 03c pre-refinement primary forest "
             "(intermediate)",
             False),
            (self.SAVE_04A_PRIMARY,
             "Run: Save 04a primary forest output (final)",
             True),
            (self.SAVE_04E_ANTHRO_MASK,
             "Run: Save 04e anthropogenic mask (debug)",
             False),
        ):
            _save_p = QgsProcessingParameterBoolean(
                _save_param, _label, defaultValue=_default)
            _save_p.setFlags(
                _save_p.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
            self.addParameter(_save_p)

        self.addParameter(QgsProcessingParameterBoolean(
            self.SAVE_COMBINED_RASTER,
            "Run: Save combined coded raster (debug)",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean(
            self.REUSE_DISTANCE_SURFACES,
            "Run: Reuse cached distance surfaces (advanced)",
            defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean(
            self.REUSE_PREPARED,
            "Run: Reuse preprocessing/*.tif cache (default ON)",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ADD_MAIN_OUTPUTS_TO_MAP,
            "Run: Add main outputs to map after run",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ADD_HUMAN_INFLUENCE_LAYERS_TO_MAP,
            "Run: Add human-influence input + buffer layers to map (default OFF)",
            defaultValue=False))
        # P1.30 batch 20a.2: local-scratch intermediates (sidesteps
        # OneDrive CFAPI placeholder issues). Default ON.
        _ls_param = QgsProcessingParameterBoolean(
            self.LOCAL_SCRATCH_INTERMEDIATES,
            "Run: Use local scratch for intermediates (recommended; "
            "sidesteps OneDrive sync issues)",
            defaultValue=True)
        _ls_param.setFlags(_ls_param.flags()
                           | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_ls_param)
        _cl_param = QgsProcessingParameterBoolean(
            self.CLEANUP_INTERMEDIATES,
            "Run: Clean up intermediates after a successful run "
            "(default OFF — useful for debugging)",
            defaultValue=False)
        _cl_param.setFlags(_cl_param.flags()
                           | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(_cl_param)

        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_FOLDER, "Output folder"))

    # ------------------------------------------------------------------ #
    #  Workflow execution
    # ------------------------------------------------------------------ #

    PFF_VERSION = "0.16.0-beta.7"

    def processAlgorithm(self, parameters, context, feedback):
        feedback.pushInfo(f"PFF plugin version: {self.PFF_VERSION}")

        # ── P1.13 ISO3 prefix ──
        # Read the optional ISO3 prefix once; the _out() closure that
        # uses it is defined further down (after out_dir is set).
        _iso3_raw = (self.parameterAsString(
            parameters, self.ISO3_PREFIX, context) or "").strip()
        _iso3 = _iso3_raw.upper() if _iso3_raw else None
        if _iso3:
            feedback.pushInfo(f"Output filename ISO3 prefix: {_iso3}")
        # P1.30 batch 20a.3: optional time-period tag (metadata only).
        _year_tag = (self.parameterAsString(
            parameters, self.YEAR, context) or "").strip() or "2020"
        feedback.pushInfo(f"Year tag: {_year_tag}")
        # P1.30 batch 20j: AOI-name auto-prefix dropped (mechanical-
        # noise problem on real data).
        # Batch 30: re-enable the slot via an explicit user-typed
        # Region / Area name. ISO3 stays a strict 3-letter code so
        # CRS suggestion + filename-sanity checks keep working. The
        # `_aoi_label` variable name is kept (it's wired through every
        # _out() call) — only the SOURCE of the value changes.
        _aoi_label = (self.parameterAsString(
            parameters, self.REGION_LABEL, context) or "").strip()
        # Sanitisation (lowercase snake-case) is handled by
        # generate_layer_name() via utils._sanitise_label.
        if _aoi_label:
            feedback.pushInfo(
                f"Sub-national / ecosystem area name: {_aoi_label}")

        # Per-stage timing. _stage() closes the previous stage timer and
        # opens a new one; _close_last_stage() flushes the final stage
        # before the metadata write at the end. Times collected into
        # _pff_stage_times for run_metadata.json.
        import time as _pff_time
        _pff_t_start = _pff_time.monotonic()
        _pff_stage_times = {}
        _pff_last_stage = {"name": None, "t": _pff_t_start}

        def _stage(name):
            # P2.6: every stage transition is a graceful cancel point. If
            # the user clicked Cancel during the previous stage, raise here
            # with a clear "Cancelled by user" message instead of cascading
            # into the next stage and erroring on a half-finished file.
            if feedback.isCanceled():
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    "Cancelled by user (between stages -- no half-written "
                    "outputs from the new stage).")
            last = _pff_last_stage["name"]
            if last:
                elapsed = _pff_time.monotonic() - _pff_last_stage["t"]
                _pff_stage_times[last] = round(elapsed, 2)
                feedback.pushInfo(f"  [{last} took {elapsed:.1f}s]")
            _pff_last_stage["name"] = name
            _pff_last_stage["t"] = _pff_time.monotonic()
            feedback.pushInfo(f"=== {name} ===")

        def _close_last_stage():
            last = _pff_last_stage["name"]
            if last:
                elapsed = _pff_time.monotonic() - _pff_last_stage["t"]
                _pff_stage_times[last] = round(elapsed, 2)
                feedback.pushInfo(f"  [{last} took {elapsed:.1f}s]")
                _pff_last_stage["name"] = None

        out_dir = ensure_dir(
            self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))

        # P1.28: preflight checks. Detects cloud-sync output folders +
        # locked existing outputs upfront so users don't waste 1+
        # minutes of analysis on a failure that was predictable. Hard
        # failures (folder not writable) abort here; soft failures
        # (cloud sync, low disk space) just emit warnings.
        _run_preflight_checks(out_dir, feedback)

        # P1.30 batch 20c: input-filename consistency check. Reads the
        # source paths of the major loaded inputs and warns (non-
        # blocking) on ISO3 / year mismatch with the user's declared
        # values. Catches the "loaded the wrong year by mistake" class
        # of user error.
        try:
            _input_paths_for_sanity = []
            for _label, _param_name in [
                ("forest_raster", self.FOREST_RASTER),
                ("aoi", self.AOI),
                ("olwtc", self.FRA_AGRICULTURE_RASTER),
                ("planted_forest", self.PLANTATIONS_RASTER),
                ("roads_vector", self.ROADS),
                ("roads_raster", self.ROADS_RASTER),
                ("builtup_small", self.BUILTUP_SMALL_RASTER),
                ("builtup_large", self.BUILTUP_LARGE_RASTER),
                ("agriculture", self.AGRICULTURE_RASTER),
                ("dem", self.DEM),
                ("slope", self.SLOPE_RASTER),
                ("protected_vector", self.PROTECTED_AREAS),
                ("protected_raster", self.PROTECTED_RASTER),
            ]:
                try:
                    _layer = self.parameterAsLayer(
                        parameters, _param_name, context)
                    if _layer is not None:
                        _input_paths_for_sanity.append(
                            (_label, _layer.source() or ""))
                except Exception:
                    pass
            _check_input_naming_consistency(
                _iso3, _year_tag, _input_paths_for_sanity, feedback)
            # Batch 28.3: slot-vs-filename heuristic. Catches the
            # BUILTUP_LARGE-with-small-file class of mistake (and any
            # other sibling-slot mix-up) -- non-blocking warning.
            _check_input_slot_filename_hints(
                _input_paths_for_sanity, feedback)
        except Exception as _e:
            feedback.pushDebugInfo(
                f"(input naming sanity check skipped: {_e})")

        # P1.30 batch 22: per-layer Save list. _step_save_map gates
        # whether a final output file lands in out_dir (saved) or in
        # intermediates_dir (computed for the pipeline but not exposed
        # to the user). Steps not listed default to "save" — that
        # covers vector outputs (06a/c/d), CSVs (05a/b), and any
        # future stages that don't have a Save flag yet.
        _step_save_map = {}
        # _intermediates_dir_holder is mutable so the closure below
        # picks it up after intermediates_dir is created (line ~1614).
        # Until then, _out() falls back to out_dir.
        _intermediates_dir_holder = []

        def _out(step, name, ext="tif"):
            save_flag = _step_save_map.get(step, True)
            if save_flag or not _intermediates_dir_holder:
                target_dir = out_dir
            else:
                target_dir = _intermediates_dir_holder[0]
            return os.path.join(
                target_dir,
                generate_layer_name(
                    _iso3, PLATFORM_QGIS, step, name, ext,
                    year=_year_tag, aoi_label=_aoi_label))

        save_combined = self.parameterAsBool(
            parameters, self.SAVE_COMBINED_RASTER, context)
        # P1.30 batch 22: per-layer Save flags.
        save_02b_forest = self.parameterAsBool(
            parameters, self.SAVE_02B_FOREST, context)
        save_02d_nrf = self.parameterAsBool(
            parameters, self.SAVE_02D_NRF, context)
        save_03c_pre_conn = self.parameterAsBool(
            parameters, self.SAVE_03C_PRE_CONN, context)
        save_04a_primary = self.parameterAsBool(
            parameters, self.SAVE_04A_PRIMARY, context)
        save_04e_anthro_mask = self.parameterAsBool(
            parameters, self.SAVE_04E_ANTHRO_MASK, context)
        # Batch 25.1: step letters re-lettered to match new GEE schema
        # (OLWTC at 02b, forest at 02c, NRF at 02e). SAVE_* symbolic
        # param names kept unchanged for backwards-compat with saved
        # Recent runs / Processing-toolbox callers.
        _step_save_map.update({
            "02c": save_02b_forest,
            "02e": save_02d_nrf,
            "03c": save_03c_pre_conn,
            "04a": save_04a_primary,
            "04e": save_04e_anthro_mask,
        })
        reuse_distances = self.parameterAsBool(
            parameters, self.REUSE_DISTANCE_SURFACES, context)
        reuse_prepared = self.parameterAsBool(
            parameters, self.REUSE_PREPARED, context)
        local_scratch_intermediates = self.parameterAsBool(
            parameters, self.LOCAL_SCRATCH_INTERMEDIATES, context)
        cleanup_intermediates = self.parameterAsBool(
            parameters, self.CLEANUP_INTERMEDIATES, context)
        # P1.30 batch 20b.1: AUTO_UTM is deprecated. Parameter still
        # parsed (so saved runs replay without crash) but the value is
        # FORCED TO FALSE here -- the centroid-derived UTM heuristic
        # was a footgun for zone-straddling AOIs / countries with
        # proper national grids. Users now pick a CRS explicitly via
        # the dock's suggested-CRS dropdown OR Manual CRS / EPSG fields.
        _auto_utm_user = self.parameterAsBool(
            parameters, self.AUTO_UTM, context)
        if _auto_utm_user:
            feedback.pushWarning(
                "AUTO_UTM=True is DEPRECATED and will be ignored. Set "
                "Target CRS explicitly in dock §0 (or via Manual CRS / "
                "EPSG override). The centroid-derived UTM heuristic is "
                "removed because it silently gave the wrong answer for "
                "zone-straddling AOIs and countries with proper national "
                "grids.")
        auto_utm = False
        aoi_buffer_dist = self.parameterAsDouble(
            parameters, self.AOI_BUFFER, context)
        max_dist = self.parameterAsDouble(
            parameters, self.MAX_DISTANCE, context)
        slope_thresh = self.parameterAsDouble(
            parameters, self.SLOPE_THRESHOLD, context)
        smooth_radius = self.parameterAsDouble(
            parameters, self.SMOOTH_RADIUS, context)
        density_thresh = self.parameterAsDouble(
            parameters, self.DENSITY_THRESHOLD, context)
        refine_min_patch_area_ha = self.parameterAsDouble(
            parameters, self.REFINE_MIN_PATCH_AREA_HA, context)

        use_single = self.parameterAsBool(
            parameters, self.USE_SINGLE_DISTANCE, context)
        single_dist = self.parameterAsDouble(
            parameters, self.ALL_BUFFERS_DIST, context)

        # Per-buffer enable flags. Unticking one skips both its distance
        # computation and its contribution to the anthropogenic mask.
        enable_buffers = {
            "roads": self.parameterAsBool(parameters, self.ENABLE_ROADS_BUFFER, context),
            "builtup": self.parameterAsBool(parameters, self.ENABLE_BUILTUP_SMALL_BUFFER, context),
            "builtup_large": self.parameterAsBool(parameters, self.ENABLE_BUILTUP_LARGE_BUFFER, context),
            "agriculture": self.parameterAsBool(parameters, self.ENABLE_AGRICULTURE_BUFFER, context),
        }
        enable_refine_output = self.parameterAsBool(
            parameters, self.ENABLE_REFINE_OUTPUT, context)

        add_main_outputs_to_map = self.parameterAsBool(
            parameters, self.ADD_MAIN_OUTPUTS_TO_MAP, context)
        add_human_influence_layers_to_map = self.parameterAsBool(
            parameters, self.ADD_HUMAN_INFLUENCE_LAYERS_TO_MAP, context)

        # Vectorise stage params (advanced). The stage runs whenever
        # any of primary / forest / nest is ticked.
        vectorize_primary = self.parameterAsBool(
            parameters, self.VECTORIZE_PRIMARY, context)
        vectorize_forest = self.parameterAsBool(
            parameters, self.VECTORIZE_FOREST, context)
        vectorize_nest = self.parameterAsBool(
            parameters, self.VECTORIZE_NEST, context)
        vectorize_dissolve_multipart = self.parameterAsBool(
            parameters, self.VECTORIZE_DISSOLVE_MULTIPART, context)
        # P1.28c: tick-what-it-says semantics. Each VECTORIZE_* toggle
        # produces ONLY its named output. Ticking nest no longer auto-
        # enables primary/forest -- the coded-raster nest path uses the
        # source RASTERS directly (final_path, forest_src_path) and
        # never needed the polygonised vector primary/forest. Dissolve
        # is scoped to the nested output only (CEO-relevant): primary-
        # alone and forest-alone outputs are NOT dissolved.
        run_vectorize = bool(vectorize_primary or vectorize_forest
                             or vectorize_nest)
        vectorize_simplify_m = self.parameterAsDouble(
            parameters, self.VECTORIZE_SIMPLIFY_M, context)
        vectorize_min_patch_ha = self.parameterAsDouble(
            parameters, self.VECTORIZE_MIN_PATCH_AREA_HA, context)
        vectorize_remove_pixel_stairs = self.parameterAsBool(
            parameters, self.VECTORIZE_REMOVE_PIXEL_STAIRS, context)
        # User-toggleable output format. Default GPKG; ESRI Shapefile
        # available for legacy / CEO workflows that require .shp.
        _vec_as_shp = self.parameterAsBool(
            parameters, self.VECTORIZE_OUTPUT_AS_SHAPEFILE, context)
        vec_ext = "shp" if _vec_as_shp else "gpkg"
        vec_format = "ESRI Shapefile" if _vec_as_shp else "GPKG"

        # Read individual distances even when single-mode is on, so we can
        # warn the user if they've customised them but ticked the single-mode
        # checkbox (their customisations would silently be ignored otherwise).
        individual_thresholds = {
            "roads": self.parameterAsDouble(
                parameters, self.ROADS_DIST, context),
            "builtup": self.parameterAsDouble(
                parameters, self.BUILTUP_DIST, context),
            "builtup_large": self.parameterAsDouble(
                parameters, self.BUILTUP_LARGE_DIST, context),
            "agriculture": self.parameterAsDouble(
                parameters, self.AGRICULTURE_DIST, context),
        }

        # Custom human-use slots: only included when the user provided a
        # raster for the slot. Each slot gets its own per-slot label and
        # buffer distance. Keys are custom_1 / custom_2 / custom_3 so they
        # slot cleanly into the existing rasters / thresholds / enable_buffers
        # dicts.
        custom_slot_labels = {}  # key -> user label (for logs / metadata)
        for _i in range(1, 4):
            _key = f"custom_{_i}"
            _r = self.parameterAsRasterLayer(
                parameters, getattr(self, f"CUSTOM_{_i}_RASTER"), context)
            if _r is None:
                continue
            _label = (self.parameterAsString(
                parameters, getattr(self, f"CUSTOM_{_i}_LABEL"), context)
                      or f"Custom disturbance {_i}").strip()
            _dist = self.parameterAsDouble(
                parameters, getattr(self, f"CUSTOM_{_i}_DIST"), context)
            individual_thresholds[_key] = _dist
            enable_buffers[_key] = True
            custom_slot_labels[_key] = _label

        if use_single and single_dist > 0:
            thresholds = {k: single_dist for k in individual_thresholds}
        else:
            thresholds = individual_thresholds

        # Warn upfront if any active buffer distance exceeds MAX_DISTANCE.
        # Distance computation (gdal_proximity) is capped at MAX_DISTANCE
        # for speed; pixels beyond it report nodata. If a buffer threshold
        # is larger than the cap, all pixels at that range get treated as
        # "outside buffer" (i.e. forest preserved when it should be
        # removed) -- silent wrong-result bug. Better to flag now and ask
        # the user to bump MAX_DISTANCE in the advanced parameters.
        _exceeded = []
        for _name, _dist in thresholds.items():
            if not enable_buffers.get(_name, True):
                continue
            if _dist > max_dist:
                _exceeded.append(f"{_name}={_dist:g} m")
        if _exceeded:
            from qgis.core import QgsProcessingException
            raise QgsProcessingException(
                "Buffer distance(s) exceed Maximum Distance "
                f"({max_dist:g} m): " + ", ".join(_exceeded) + ". "
                "Distance computation is capped at MAX_DISTANCE for speed; "
                "pixels beyond it report nodata, so any buffer threshold "
                "larger than the cap silently produces wrong results. "
                "Fix: open the advanced parameters and increase "
                "'00 Country: Maximum distance to compute (m, advanced)' "
                "to at least the largest buffer distance + ~100 m headroom. "
                "(Then re-run.)"
            )

        # Prominent log block so the user always sees which distances were
        # actually applied — mitigates the "I forgot the single-distance
        # tickbox was on" silent-mistake risk.
        enabled_names = [n for n, v in enable_buffers.items() if v]
        disabled_names = [n for n, v in enable_buffers.items() if not v]
        feedback.pushInfo("")
        feedback.pushInfo("=== Buffer distances ===")
        if use_single:
            feedback.pushInfo(
                f"  Single {single_dist:g} m applied to all ticked buffers: "
                + (", ".join(enabled_names) if enabled_names else "(none!)"))
            if disabled_names:
                feedback.pushInfo(
                    f"  Skipped (tickbox off): " + ", ".join(disabled_names))
            # Warn only when the user has ACTIVELY customised individual fields
            # (i.e. changed them from their defaults) AND ticked single-mode —
            # their customisations are being silently ignored, which is the real
            # mistake. Don't fire when individuals are still at defaults and the
            # user is just using single-mode normally.
            defaults_map = {
                "roads": ROADS_DIST, "builtup": BUILTUP_DIST,
                "builtup_large": BUILTUP_LARGE_DIST,
                "agriculture": AGRICULTURE_DIST,
            }
            # Custom slots default to 1000m; treat that as the "default" so
            # we don't false-trigger the warning when the user just leaves
            # them at the slot default while using single-mode.
            customised = [
                f"{name}={individual_thresholds[name]:g}"
                for name in individual_thresholds
                if individual_thresholds[name] != defaults_map.get(name, 1000.0)
            ]
            if customised:
                feedback.pushWarning(
                    f"  ⚠ Using {single_dist:g}m (single). Ignored: "
                    + ", ".join(customised) + ".")
                feedback.pushWarning(
                    "  ⏳ 10s to Cancel. Fix: untick single-distance.")
                import time
                for tick in range(40):
                    if feedback.isCanceled():
                        feedback.pushInfo("Cancelled — fix & re-run.")
                        return {}
                    if tick == 20:  # 5s remaining
                        feedback.pushWarning("  ⏳ 5s left.")
                    time.sleep(0.25)
                feedback.pushInfo(f"  Continuing with {single_dist:g}m.")
        else:
            feedback.pushInfo("  INDIVIDUAL-DISTANCE mode:")
            for name, dist in thresholds.items():
                # Custom slots get their user label appended for clarity.
                _suffix = (f"  ('{custom_slot_labels[name]}')"
                           if name in custom_slot_labels else "")
                if enable_buffers.get(name, True):
                    feedback.pushInfo(f"    {name:<14} {dist:g} m{_suffix}")
                else:
                    feedback.pushInfo(f"    {name:<14} SKIPPED (Include-X-buffer is unticked){_suffix}")
        feedback.pushInfo("")

        # -- Resolve target CRS (auto UTM or manual) --
        forest_layer = self.parameterAsRasterLayer(
            parameters, self.FOREST_RASTER, context)
        aoi_layer = self.parameterAsVectorLayer(parameters, self.AOI, context)

        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsProcessingException,
        )

        # CRS resolution priority: AUTO_UTM > TARGET_CRS_EPSG (if non-empty)
        # > TARGET_CRS picker. The EPSG-string fallback exists because the
        # QGIS CRS picker is fiddly on some installs (no Choose button on
        # older QGIS-LTR) and workshop users get stuck.
        target_crs_epsg_str = (self.parameterAsString(
            parameters, self.TARGET_CRS_EPSG, context) or "").strip()

        if auto_utm:
            target_crs_str = _detect_utm_zone(forest_layer, aoi_layer, feedback)
            crs_source = "Auto UTM"
        elif target_crs_epsg_str:
            # Be permissive about format -- everyone uses EPSG codes, so
            # accept bare numbers ("5266"), lowercase ("epsg:5266"), or
            # the canonical "EPSG:5266". Normalise to "EPSG:<digits>"
            # before validating.
            _normalised = target_crs_epsg_str
            if _normalised.isdigit():
                _normalised = f"EPSG:{_normalised}"
            elif _normalised.lower().startswith("epsg:"):
                _normalised = "EPSG:" + _normalised.split(":", 1)[1].strip()
            candidate = QgsCoordinateReferenceSystem(_normalised)
            if not candidate.isValid():
                raise QgsProcessingException(
                    f"TARGET_CRS_EPSG '{target_crs_epsg_str}' is not a valid "
                    "CRS code. Expected an EPSG code -- either bare ('5266') "
                    "or prefixed ('EPSG:5266').")
            target_crs_str = candidate.authid() or _normalised
            crs_source = f"EPSG-string field ('{target_crs_epsg_str}')"
        else:
            target_crs = self.parameterAsCrs(
                parameters, self.TARGET_CRS, context)
            target_crs_str = target_crs.authid()
            crs_source = "CRS picker"

        target_crs = QgsCoordinateReferenceSystem(target_crs_str)

        # Validate the resolved CRS is projected (metres). Distance / area
        # operations downstream silently produce wrong values on geographic
        # CRS, so fail loud here.
        if target_crs.isGeographic():
            raise QgsProcessingException(
                f"Resolved target CRS '{target_crs_str}' is geographic "
                "(degrees). Choose a projected CRS in metres -- e.g. a UTM "
                "zone, a continental equal-area projection, or your country's "
                "national grid.")

        feedback.pushInfo(f"Target CRS: {target_crs_str} (source: {crs_source})")

        # All non-headline outputs (caches + tier rasters) nest under intermediates/.
        # Headlines (per Option D + P1.16 FRA-aligned schema:
        # 02c naturally_regenerating_forest, 04a primary_forest,
        # 04b pre_connectivity, 04c combined_coded, 04e anthropogenic_mask,
        # 05a area_statistics, 06a/b/c/d vectors, qgis_run_metadata.json)
        # stay at out_dir top level with ISO3+platform+step prefixes via _out().
        #
        # P1.30 batch 20a.2: when LOCAL_SCRATCH_INTERMEDIATES is on
        # (the default), redirect intermediates to a non-cloud-synced
        # scratch dir under the QGIS profile. Sidesteps OneDrive CFAPI
        # placeholder issues that bite on subprocess reads of just-
        # written rasters. Final outputs still land in out_dir.
        if local_scratch_intermediates:
            from qgis.core import QgsApplication
            from datetime import datetime
            _run_slug = (f"{_iso3}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                         if _iso3 else
                         datetime.now().strftime('run_%Y%m%d_%H%M%S'))
            intermediates_dir = ensure_dir(os.path.join(
                QgsApplication.qgisSettingsDirPath(),
                "PFF", "intermediates", _run_slug))
            feedback.pushInfo(
                f"Intermediates: {intermediates_dir} "
                "(local scratch — sidesteps OneDrive sync)")
        else:
            intermediates_dir = ensure_dir(
                os.path.join(out_dir, "intermediates"))
            feedback.pushInfo(
                f"Intermediates: {intermediates_dir} "
                "(next to outputs — opt-in)")
        # P1.30 batch 22: now that intermediates_dir exists, plug it
        # into the _out() closure so un-saved final outputs route here
        # instead of out_dir.
        _intermediates_dir_holder.append(intermediates_dir)

        # Batch 27.1: folder renamed prepared/ -> preprocessing/.
        # Variable names (prepared_dir, REUSE_PREPARED, reuse_prepared)
        # kept for backwards-compat with saved Recent Runs + minimal-
        # diff churn; only the on-disk folder name + user-visible
        # strings change.
        prepared_dir = ensure_dir(os.path.join(intermediates_dir, "preprocessing"))
        dist_dir = ensure_dir(os.path.join(intermediates_dir, "distances"))
        # Scratch dir for per-input _reproj and _clipped intermediates. Keeps
        # prepared/ clean — only the 9 user-reusable final rasters sit there,
        # everything else (which users never repoint at) goes here.
        scratch_dir = ensure_dir(os.path.join(intermediates_dir, "_scratch"))

        # --- Pre-flight: check if any key output file is locked ---------
        # Frustrating to wait minutes for a run only to crash at the end
        # when an output file is open in QGIS. Check upfront.
        _run_zonal = self.parameterAsBool(
            parameters, self.RUN_ZONAL_STATS, context)
        # Likely outputs use the Option D filenames computed via _out().
        _likely_outputs = [
            _out("04a", "primary_forest"),
            _out("03c", "pre_refinement_primary_forest"),
            _out("04e", "anthropogenic_mask"),
            _out("02c", "forest"),
            _out("02e", "naturally_regenerating_forest"),
            os.path.join(
                out_dir,
                (f"{_iso3}_qgis_run_metadata.json" if _iso3
                 else "qgis_run_metadata.json")),
        ]
        if save_combined:
            _likely_outputs.append(_out("03d", "combined_coded_raster"))
        if _run_zonal:
            _likely_outputs.append(_out("05a", "area_statistics", ext="csv"))
            _likely_outputs.append(_out("05b", "area_statistics_by_zone", ext="gpkg"))
        # Vectorise outputs (06a/c/d). P1.28c output matrix:
        #   - vectorize_primary -> 06a primary_forest_vector
        #   - vectorize_forest  -> 06c <forest|naturally_regenerating_forest>_vector
        #   - vectorize_nest    -> 06c <base>_with_primary_nested_vector
        #                          + 06d <base>_with_primary_nested_dissolved
        #                            (only if vectorize_dissolve_multipart)
        # Forest-vector basename depends on whether nat reg derivation
        # runs (chosen later in workflow); check both candidate names
        # since either may exist from a previous run. Non-existent
        # files are silently skipped by the lock check loop below.
        if run_vectorize:
            if vectorize_primary:
                _likely_outputs.append(_out("06a", "primary_forest_vector", ext=vec_ext))
            if vectorize_forest:
                _likely_outputs.append(_out("06c", "forest_vector", ext=vec_ext))
                _likely_outputs.append(_out("06c", "naturally_regenerating_forest_vector", ext=vec_ext))
            if vectorize_nest:
                # Batch 28.8 item 5: nest+dissolve are exclusive --
                # 06c is dropped from the likely-outputs lock-check
                # when dissolve is on (only 06d emerges in out_dir).
                if not vectorize_dissolve_multipart:
                    _likely_outputs.append(_out("06c", "forest_with_primary_nested_vector", ext=vec_ext))
                    _likely_outputs.append(_out("06c", "naturally_regenerating_forest_with_primary_nested_vector", ext=vec_ext))
                if vectorize_dissolve_multipart:
                    _likely_outputs.append(_out("06d", "forest_with_primary_nested_dissolved", ext=vec_ext))
                    _likely_outputs.append(_out("06d", "naturally_regenerating_forest_with_primary_nested_dissolved", ext=vec_ext))

        _locked = []
        for _p in _likely_outputs:
            if not os.path.exists(_p):
                continue
            # Reliable Windows lock check: try to rename. GDAL memory-maps
            # rasters with shared read+write but NOT shared delete, so
            # open(path, 'r+b') passes while os.remove() still fails later.
            # Rename hits the same permission path as delete, so it's the
            # probe that matches what _write() / os.remove() actually need.
            _probe = _p + ".__locktest__"
            try:
                os.rename(_p, _probe)
                os.rename(_probe, _p)
            except (PermissionError, OSError):
                _locked.append(os.path.basename(_p))

        if _locked:
            from qgis.core import QgsProcessingException
            raise QgsProcessingException(
                "Pre-flight check failed: output file(s) locked by another "
                "process (usually QGIS has them loaded as layers from a "
                "previous run):\n  - " + "\n  - ".join(_locked) +
                "\n\nFix: in QGIS Layers panel, right-click each and "
                "'Remove Layer…', or close the other program holding them, "
                "then re-run. (Your run hasn't started yet — no time wasted.)"
            )

        # ================================================================
        #  STAGE 1 -- Prepare datasets
        # ================================================================
        _stage("STAGE 1: Prepare Datasets")

        validate_crs_projected(forest_layer, feedback)
        forest_src = forest_layer.source()
        # Peek at AOI choice early so we can pick the right reproject target:
        # if AOI will be supplied we reproject to scratch/ so the AOI-clip step
        # can write the final preprocessing/forest.tif from a different source file
        # (avoids in-place overwrite + Windows file-lock problems with OneDrive).
        _will_clip_aoi = aoi_layer is not None
        prepared_forest_path = os.path.join(prepared_dir, "forest.tif")

        # Re-run short-circuit: if user already points at preprocessing/forest.tif
        # from this out_dir, it's already reprojected + AOI-clipped. Skip prep.
        if os.path.normpath(forest_src) == os.path.normpath(prepared_forest_path):
            feedback.pushInfo(
                "Forest input is already preprocessing/forest.tif — using as-is "
                "(re-run path; skipping reproject + AOI clip).")
        else:
            # First-run path: reproject forest.
            reproj_target = (os.path.join(scratch_dir, "forest_reproj.tif")
                             if _will_clip_aoi else prepared_forest_path)
            if forest_layer.crs() != target_crs:
                feedback.pushInfo("Reprojecting forest raster...")
                reproject_raster(forest_src, target_crs_str, reproj_target,
                                 context=context, feedback=feedback)
                forest_src = reproj_target
            else:
                if os.path.normpath(forest_src) != os.path.normpath(reproj_target):
                    run_processing("gdal:translate", {
                        "INPUT": forest_src, "OUTPUT": reproj_target,
                        "OPTIONS": "COMPRESS=LZW|TILED=YES",
                    }, context=context, feedback=feedback)
                    forest_src = reproj_target

        reference = forest_src

        # Buffer & clip AOI
        # AOI working files (reproj / buffered / rasterised) are internal —
        # users never repoint the plugin at them. Nest under prepared/_aoi/
        # so prepared/ shows only the 9 user-reusable inputs.
        aoi_mask = None
        if aoi_layer is not None:
            feedback.pushInfo(
                f"Buffering AOI by {aoi_buffer_dist:g} m "
                "(extends analysis past the boundary so edge-of-country "
                "anthropogenic features still influence buffers)...")
            aoi_workspace = ensure_dir(os.path.join(prepared_dir, "_aoi"))
            # Use .shp for reproject to avoid gpkg FID uniqueness dropping features
            aoi_reproj_raw = os.path.join(aoi_workspace, "aoi_reproj_raw.shp")
            reproject_vector(aoi_layer.source(), target_crs_str, aoi_reproj_raw,
                             context=context, feedback=feedback)
            # Dissolve to merge multi-feature AOIs (e.g. countries with
            # islands or diced polygons) into one multipart polygon
            aoi_reproj = os.path.join(aoi_workspace, "aoi_reproj.gpkg")
            run_processing("native:dissolve", {
                "INPUT": aoi_reproj_raw,
                "OUTPUT": aoi_reproj,
            }, context=context, feedback=feedback)
            aoi_buffered = os.path.join(aoi_workspace, "aoi_buffered.gpkg")
            run_processing("native:buffer", {
                "INPUT": aoi_reproj,
                "DISTANCE": aoi_buffer_dist,
                "DISSOLVE": True,
                "OUTPUT": aoi_buffered,
            }, context=context, feedback=feedback)
            aoi_mask = aoi_buffered

            # If forest is the re-run input (already preprocessing/forest.tif),
            # skip the re-clip — file is already AOI-clipped.
            if os.path.normpath(reference) == os.path.normpath(prepared_forest_path):
                feedback.pushInfo(
                    "Forest input is already preprocessing/forest.tif — skipping "
                    "AOI re-clip (it's already clipped).")
                # Still rasterise the AOI so it's available for stages that need it.
                aoi_rasterised = os.path.join(aoi_workspace, "aoi_raster.tif")
                rasterize_vector(aoi_buffered, reference, aoi_rasterised,
                                 context=context, feedback=feedback)
            else:
                # Normal first-run path: reprojected forest is in scratch_dir,
                # mask it to AOI and write the result to preprocessing/forest.tif.
                # Source and destination are DIFFERENT files → no in-place
                # overwrite, no Windows file-lock issues.
                aoi_rasterised = os.path.join(aoi_workspace, "aoi_raster.tif")
                rasterize_vector(aoi_buffered, reference, aoi_rasterised,
                                 context=context, feedback=feedback)
                _ds_ref = gdal.Open(reference, gdal.GA_ReadOnly)
                _forest_arr = _ds_ref.GetRasterBand(1).ReadAsArray()
                _gt_ref = _ds_ref.GetGeoTransform()
                _proj_ref = _ds_ref.GetProjection()
                _xsz = _ds_ref.RasterXSize
                _ysz = _ds_ref.RasterYSize
                _ds_ref = None
                _ds_aoi = gdal.Open(aoi_rasterised, gdal.GA_ReadOnly)
                _aoi_arr = _ds_aoi.GetRasterBand(1).ReadAsArray()
                _ds_aoi = None
                _masked = (_forest_arr * (_aoi_arr > 0)).astype(_forest_arr.dtype)
                _drv = gdal.GetDriverByName("GTiff")
                # Write clipped forest to preprocessing/forest.tif (different path
                # from the scratch reproj source — no in-place overwrite).
                # P1.28: _safe_remove handles transient locks (OneDrive etc.).
                _safe_remove(prepared_forest_path, feedback=feedback)
                # Use _ds_out NOT _out -- _out is the helper closure for
                # building output filenames (defined ~line 625). Naming
                # this GDAL Dataset _out would shadow the closure for the
                # rest of processAlgorithm, breaking every subsequent
                # _out("step", "name") call. (Bug found in batch 11.)
                _ds_out = _drv.Create(prepared_forest_path, _xsz, _ysz, 1,
                                      gdal.GDT_Byte, ["COMPRESS=LZW"])
                _ds_out.SetGeoTransform(_gt_ref)
                _ds_out.SetProjection(_proj_ref)
                _ds_out.GetRasterBand(1).WriteArray(_masked)
                _ds_out.GetRasterBand(1).SetNoDataValue(0)
                _ds_out.FlushCache()
                _ds_out = None
                reference = prepared_forest_path  # downstream uses the clipped version

        # Keep the raw forest path for stats (before plantations exclusion).
        # If plantations exclusion is applied below, `reference` is redirected
        # to the forest-AND-NOT-plantations raster so downstream stages use it.
        forest_raw_path = reference

        # Helper: reproject + clip + rasterise a vector layer.
        # Intermediates go to _scratch/ so prepared/ stays clean with only the
        # final aligned .tif files (what users might repoint at for re-runs).
        def _prep_vector(param_key, filename):
            layer = self.parameterAsVectorLayer(parameters, param_key, context)
            if layer is None:
                return None
            feedback.pushInfo(f"Preparing {filename}...")
            reproj = os.path.join(scratch_dir, f"{filename}_reproj.gpkg")
            reproject_vector(layer.source(), target_crs_str, reproj,
                             context=context, feedback=feedback)
            if aoi_mask is not None:
                clipped = os.path.join(scratch_dir, f"{filename}_clip.gpkg")
                run_processing("native:clip", {
                    "INPUT": reproj, "OVERLAY": aoi_mask, "OUTPUT": clipped,
                }, context=context, feedback=feedback)
                reproj = clipped
            rasterised = os.path.join(prepared_dir, f"{filename}.tif")
            rasterize_vector(reproj, reference, rasterised,
                             context=context, feedback=feedback)
            return rasterised

        # Helper: align a raster input to the reference grid.
        # Intermediates go to _scratch/ (same rationale).
        def _prep_raster(param_key, filename):
            layer = self.parameterAsRasterLayer(parameters, param_key, context)
            if layer is None:
                return None
            aligned = os.path.join(prepared_dir, f"{filename}.tif")
            # Re-run short-circuit: if user points this input at the prepared/
            # output from a previous run (same path), don't re-process — it's
            # already aligned. Avoids the Windows "read + overwrite same file"
            # lock issue.
            if os.path.normpath(layer.source()) == os.path.normpath(aligned):
                feedback.pushInfo(
                    f"Raster {filename} is already preprocessing/{filename}.tif "
                    "— using as-is (re-run path).")
                return aligned
            # P0.3 REUSE_PREPARED: when the user toggle is on AND a cached
            # prepared/<filename>.tif exists AND its grid (x_size, y_size,
            # pixel size) matches the reference, skip the whole reproject +
            # clip + warp pipeline. The user's source raster is intentionally
            # NOT re-checked -- if they swapped sources, they're expected to
            # untick this option to force re-prep. Surfaces a clear log line
            # so the user can spot when reuse fired.
            if reuse_prepared and os.path.exists(aligned):
                try:
                    _, _ag_gt, _ag_x, _ag_y = get_raster_info(aligned)
                    _, _rf_gt, _rf_x, _rf_y = get_raster_info(reference)
                    _grid_match = (
                        _ag_x == _rf_x and _ag_y == _rf_y
                        and abs(abs(_ag_gt[1]) - abs(_rf_gt[1])) < 1e-6
                        and abs(abs(_ag_gt[5]) - abs(_rf_gt[5])) < 1e-6
                    )
                    if _grid_match:
                        feedback.pushInfo(
                            f"Reused cached: preprocessing/{filename}.tif "
                            "(matches reference grid; reproject skipped). "
                            "Untick 'Reuse preprocessing/*.tif cache' to force "
                            "re-prep if your source raster changed.")
                        return aligned
                    else:
                        feedback.pushInfo(
                            f"Cached preprocessing/{filename}.tif has mismatched "
                            "grid -- recomputing.")
                except Exception as _e:
                    feedback.pushDebugInfo(
                        f"Could not verify cached preprocessing/{filename}.tif: "
                        f"{_e}; recomputing to be safe.")
            feedback.pushInfo(f"Aligning raster {filename}...")
            reproj = os.path.join(scratch_dir, f"{filename}_reproj.tif")
            reproject_raster(layer.source(), target_crs_str, reproj,
                             context=context, feedback=feedback)
            if aoi_mask is not None:
                clipped = os.path.join(scratch_dir, f"{filename}_clipped.tif")
                clip_raster_by_mask(reproj, aoi_mask, clipped,
                                    context=context, feedback=feedback)
                # Remove intermediate reproj to free disk/memory (best-effort)
                try:
                    os.remove(reproj)
                except OSError:
                    pass
                reproj = clipped
            # 'aligned' already set above (for re-run short-circuit).
            _, gt_ref, xsz, ysz = get_raster_info(reference)
            res_x = abs(gt_ref[1])
            ext = (f"{gt_ref[0]},{gt_ref[0]+gt_ref[1]*xsz},"
                   f"{gt_ref[3]+gt_ref[5]*ysz},{gt_ref[3]}")
            run_processing("gdal:warpreproject", {
                "INPUT": reproj,
                "TARGET_CRS": target_crs,
                "TARGET_EXTENT": ext,
                "TARGET_EXTENT_CRS": target_crs,
                "TARGET_RESOLUTION": res_x,
                "RESAMPLING": 0,
                "OPTIONS": "COMPRESS=LZW|TILED=YES",
                "OUTPUT": aligned,
            }, context=context, feedback=feedback)
            # Remove intermediate clip/reproj to free disk space
            if reproj != aligned:
                try:
                    os.remove(reproj)
                except OSError:
                    pass
            return aligned

        # Limit GDAL cache to avoid memory pressure on large rasters
        gdal.SetCacheMax(512 * 1024 * 1024)  # 512 MB

        # Thin-feature resolution warning: roads (and to a lesser extent
        # waterways) are 1-pixel-wide linear features. At raster resolutions
        # coarser than ~45 m, single-cell roads disappear into surrounding
        # cells (the rasterisation collapses the geometry). Warn loud so the
        # user knows their roads input may under-represent the network.
        _ROADS_THIN_FEATURE_WARN_M = 45
        _user_roads_layer = self.parameterAsRasterLayer(
            parameters, self.ROADS_RASTER, context)
        if _user_roads_layer is not None:
            try:
                _roads_res = raster_resolution(_user_roads_layer.source())
                if _roads_res > _ROADS_THIN_FEATURE_WARN_M:
                    feedback.pushWarning(
                        f"Roads raster resolution is {_roads_res:g} m -- "
                        f"coarser than ~{_ROADS_THIN_FEATURE_WARN_M} m. "
                        "Linear features (roads / tracks) are likely under-"
                        "represented at this resolution. If road buffers "
                        "matter for your analysis, either re-export at "
                        "finer resolution OR supply roads as a vector "
                        "input (vectors get rasterised to the reference "
                        "grid, so no thin-feature loss).")
            except Exception as _e:
                # Resolution check is advisory; never block the run.
                feedback.pushDebugInfo(
                    f"Could not check roads raster resolution: {_e}")

        # Raster inputs override vectors when both are provided.
        # Process sequentially with GC + cancel checks between -- prep on
        # national rasters can run minutes per layer, so let cancel land
        # between layers without waiting for the full anthro batch.
        import gc
        roads_raster = _prep_raster(self.ROADS_RASTER, "roads")
        gc.collect()
        if feedback.isCanceled():
            from qgis.core import QgsProcessingException
            raise QgsProcessingException("Cancelled by user (after roads prep).")
        builtup_small_raster = _prep_raster(self.BUILTUP_SMALL_RASTER, "builtup_small")
        gc.collect()
        if feedback.isCanceled():
            from qgis.core import QgsProcessingException
            raise QgsProcessingException("Cancelled by user (after builtup_small prep).")
        builtup_large_raster = _prep_raster(self.BUILTUP_LARGE_RASTER, "builtup_large")
        gc.collect()
        if feedback.isCanceled():
            from qgis.core import QgsProcessingException
            raise QgsProcessingException("Cancelled by user (after builtup_large prep).")
        agri_raster = _prep_raster(self.AGRICULTURE_RASTER, "agriculture")
        gc.collect()

        # Custom human-use slots (P2.3): prep each provided raster the same
        # way as the built-in anthro inputs. Skipped slots stay None.
        custom_rasters = {}  # custom_1/2/3 -> prepped path or None
        for _i in range(1, 4):
            _key = f"custom_{_i}"
            _const = getattr(self, f"CUSTOM_{_i}_RASTER")
            _layer = self.parameterAsRasterLayer(parameters, _const, context)
            if _layer is None:
                custom_rasters[_key] = None
                continue
            _label_for_log = custom_slot_labels.get(_key, _key)
            feedback.pushInfo(
                f"Preparing custom slot {_i} ('{_label_for_log}')...")
            custom_rasters[_key] = _prep_raster(_const, _key)
            gc.collect()
            if feedback.isCanceled():
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    f"Cancelled by user (after custom_{_i} prep).")

        rasters = {
            "roads": roads_raster if roads_raster else _prep_vector(self.ROADS, "roads"),
            "builtup": builtup_small_raster,
            "builtup_large": builtup_large_raster,
            "agriculture": agri_raster,
            "custom_1": custom_rasters["custom_1"],
            "custom_2": custom_rasters["custom_2"],
            "custom_3": custom_rasters["custom_3"],
        }
        # Protected areas: raster overrides vector if both provided
        pa_raster_layer = self.parameterAsRasterLayer(
            parameters, self.PROTECTED_RASTER, context)
        if pa_raster_layer is not None:
            feedback.pushInfo("Aligning pre-rasterised protected areas...")
            pa_tif = _prep_raster(self.PROTECTED_RASTER, "protected")
        else:
            pa_tif = _prep_vector(self.PROTECTED_AREAS, "protected")

        # ─── P1.18: FRA-aligned Forest baseline ───────────────────────
        # When the user supplies an FRA agricultural tree cover layer
        # (Descals oil palm + SDPT class 2 + agroforestry) AND ticks
        # "Exclude agriculture from Forest baseline (FRA-aligned)", the
        # Forest baseline (forest_raw_path) is narrowed BEFORE the
        # plantations-exclusion / nat reg derivation. This produces a
        # FRA-strict Forest layer (tree cover meeting biophysical
        # thresholds AND not primarily agricultural land use).
        # Mirrors pff_4.js:4870 P1.18 logic.
        exclude_agriculture_from_forest = self.parameterAsBool(
            parameters, self.EXCLUDE_AGRICULTURE_FROM_FOREST, context)
        fra_agriculture_layer = self.parameterAsRasterLayer(
            parameters, self.FRA_AGRICULTURE_RASTER, context)
        fra_agriculture_tif = None
        if fra_agriculture_layer is not None:
            fra_agriculture_tif = _prep_raster(
                self.FRA_AGRICULTURE_RASTER, "fra_agriculture_tree_cover")

        if fra_agriculture_tif is not None and exclude_agriculture_from_forest:
            feedback.pushInfo(
                "Refining tree cover to Forest by excluding other land "
                "with tree cover (oil palm, orchards, agroforestry)...")
            forest_fra_path = os.path.join(prepared_dir, "forest_fra.tif")
            _fds = gdal.Open(forest_raw_path, gdal.GA_ReadOnly)
            _farr = _fds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
            _fgt = _fds.GetGeoTransform()
            _fproj = _fds.GetProjection()
            _fxsz = _fds.RasterXSize
            _fysz = _fds.RasterYSize
            _fds = None
            _ads = gdal.Open(fra_agriculture_tif, gdal.GA_ReadOnly)
            _aarr = _ads.GetRasterBand(1).ReadAsArray().astype(np.uint8)
            _ads = None
            _farr_fra = ((_farr == 1) & (_aarr != 1)).astype(np.uint8)
            # P1.28: _safe_remove handles transient locks (OneDrive etc.).
            _safe_remove(forest_fra_path, feedback=feedback)
            _drv = gdal.GetDriverByName("GTiff")
            # _ds_out NOT _out -- avoid shadowing the closure helper
            _ds_out = _drv.Create(forest_fra_path, _fxsz, _fysz, 1,
                                  gdal.GDT_Byte,
                                  ["COMPRESS=LZW", "TILED=YES"])
            _ds_out.SetGeoTransform(_fgt)
            _ds_out.SetProjection(_fproj)
            _ds_out.GetRasterBand(1).WriteArray(_farr_fra)
            _ds_out.GetRasterBand(1).SetNoDataValue(0)
            _ds_out.FlushCache()
            _ds_out = None
            excluded_px = int((_farr == 1).sum() - _farr_fra.sum())
            feedback.pushInfo(
                f"  Excluded {excluded_px:,} other-land-with-tree-cover pixels "
                "from Forest baseline.")
            # Switch downstream to use the FRA-stricter forest baseline.
            # The plantations exclusion block + nat reg derivation +
            # primary forest computation all read from forest_raw_path.
            forest_raw_path = forest_fra_path
            reference = forest_fra_path
        elif fra_agriculture_layer is not None and not exclude_agriculture_from_forest:
            feedback.pushInfo(
                "Other land with tree cover raster prepared in "
                "intermediates/preprocessing/fra_agriculture_tree_cover.tif "
                "but 'Refine to forest' is off — Forest baseline NOT "
                "narrowed. Tick the option to derive FRA-strict Forest.")

        # ─── Top-level 02c_forest.tif (FRA Forest baseline output) ───
        # Per spec (Batch 25.1), 02c_forest belongs at top level (not
        # just as the internal cache at intermediates/preprocessing/forest.
        # tif). Writing it as a separate file means QGIS can hold open
        # the top-level 02c_forest.tif (via auto-load) without locking
        # the prepared/ cache file -- which would otherwise fail the
        # next run's forest preparation step (PermissionError on
        # remove). Reflects the post-P1.18 forest_raw_path: FRA-strict
        # version when the toggle is on, thresholded tree cover
        # otherwise.
        forest_baseline_top_path = _out("02c", "forest")
        # P1.28: _safe_remove handles transient locks (OneDrive etc.).
        _safe_remove(forest_baseline_top_path, feedback=feedback)
        shutil.copy2(forest_raw_path, forest_baseline_top_path)
        feedback.pushInfo(
            f"Wrote Forest baseline to "
            f"{os.path.basename(forest_baseline_top_path)} "
            f"({'FRA-strict' if exclude_agriculture_from_forest and fra_agriculture_tif else 'thresholded tree cover'})")

        # Plantations: optional binary raster used to derive naturally
        # regenerating forest (forest AND NOT plantations).
        # Mirrors pff_4.js:4184 behaviour when "Exclude plantations" is on.
        # Always prep the raster when supplied (consistency with other anthro
        # inputs) — the file sits in prepared/ ready for re-runs even if the
        # "Exclude plantations" tickbox is off on the current run.
        # Note: when P1.18 runs above, forest_raw_path now points at
        # forest_fra.tif (FRA-stricter baseline), so the nat reg
        # derivation below operates on the FRA Forest baseline.
        exclude_plantations = self.parameterAsBool(
            parameters, self.EXCLUDE_PLANTATIONS, context)
        plantations_layer = self.parameterAsRasterLayer(
            parameters, self.PLANTATIONS_RASTER, context)
        plantations_tif = None
        forest_natreg_path = None
        if plantations_layer is not None:
            plantations_tif = _prep_raster(self.PLANTATIONS_RASTER, "plantations")

        if plantations_tif is not None and exclude_plantations:
            feedback.pushInfo(
                "Refining Forest to naturally regenerating forest by "
                "excluding planted forest...")
            if True:  # (preserve existing indentation of block below)
                _fds = gdal.Open(forest_raw_path, gdal.GA_ReadOnly)
                _farr = _fds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
                _fgt = _fds.GetGeoTransform()
                _fproj = _fds.GetProjection()
                _fxsz = _fds.RasterXSize
                _fysz = _fds.RasterYSize
                _fds = None
                _pds = gdal.Open(plantations_tif, gdal.GA_ReadOnly)
                _parr = _pds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
                _pds = None
                _natreg = ((_farr == 1) & (_parr != 1)).astype(np.uint8)
                # Headline output (≈ FRA Naturally Regenerating Forest),
                # lives at top level. Batch 25.1: renumbered to 02e to
                # accommodate new 02b_other_land_with_tree_cover slot
                # (workflow-progression ordering: 02a raw -> 02b OLWTC ->
                # 02c forest -> 02d planted forest -> 02e nat reg = 02c
                # minus 02d). The layer represents Forest minus Planted
                # Forest -- per FRA, this IS "Naturally regenerating
                # forest" (Forest decomposes as Naturally regenerating +
                # Planted). Primary forest is a subset of naturally
                # regenerating forest, not a sibling.
                forest_natreg_path = _out("02e", "naturally_regenerating_forest")
                _drv = gdal.GetDriverByName("GTiff")
                # P1.28: _safe_remove handles transient locks (OneDrive etc.).
                _safe_remove(forest_natreg_path, feedback=feedback)
                # _ds_out NOT _out -- shadowing _out (the closure helper)
                # would break downstream _out("step", "name") calls.
                _ds_out = _drv.Create(forest_natreg_path, _fxsz, _fysz, 1,
                                      gdal.GDT_Byte,
                                      ["COMPRESS=LZW", "TILED=YES"])
                _ds_out.SetGeoTransform(_fgt)
                _ds_out.SetProjection(_fproj)
                _ds_out.GetRasterBand(1).WriteArray(_natreg)
                _ds_out.GetRasterBand(1).SetNoDataValue(0)
                _ds_out.FlushCache()
                _ds_out = None
                excluded_px = int((_farr == 1).sum() - _natreg.sum())
                feedback.pushInfo(
                    f"  Excluded {excluded_px:,} planted-forest pixels from forest.")
                # Downstream stages operate on nat-regen forest
                reference = forest_natreg_path
        elif plantations_tif is not None and not exclude_plantations:
            feedback.pushInfo(
                "Planted forest raster prepared in intermediates/preprocessing/plantations.tif "
                "but 'Refine to naturally regenerating forest' is off — planted forest "
                "is NOT excluded from the forest input in this run.")
        elif plantations_layer is None and exclude_plantations:
            feedback.pushInfo(
                "'Refine to naturally regenerating forest' is on but no Planted "
                "forest raster provided — skipping exclusion.")

        # DEM / Slope: slope raster overrides DEM if provided
        slope_layer = self.parameterAsRasterLayer(
            parameters, self.SLOPE_RASTER, context)
        dem_layer = self.parameterAsRasterLayer(parameters, self.DEM, context)
        dem_path = None
        slope_path = None

        # Re-run short-circuit for slope/DEM: if the user points at our own
        # prepared/ output, skip re-processing.
        _prepared_slope = os.path.join(prepared_dir, "slope.tif")
        _prepared_dem = os.path.join(prepared_dir, "dem.tif")
        _slope_is_prepared = (
            slope_layer is not None
            and os.path.normpath(slope_layer.source()) == os.path.normpath(_prepared_slope)
        )
        _dem_is_prepared = (
            dem_layer is not None
            and os.path.normpath(dem_layer.source()) == os.path.normpath(_prepared_dem)
        )
        if _slope_is_prepared:
            feedback.pushInfo(
                "Slope input is already preprocessing/slope.tif — using as-is (re-run path).")
            slope_path = _prepared_slope
        elif _dem_is_prepared and slope_layer is None:
            # DEM supplied as re-run input, slope will be derived from prepared dem.tif
            feedback.pushInfo(
                "DEM input is already preprocessing/dem.tif — using as-is (re-run path).")
            dem_path = _prepared_dem
        elif slope_layer is not None:
            # Pre-computed slope -- align it to reference grid
            feedback.pushInfo("Aligning pre-computed slope raster...")
            slope_reproj = os.path.join(scratch_dir, "slope_reproj.tif")
            reproject_raster(slope_layer.source(), target_crs_str,
                             slope_reproj,
                             context=context, feedback=feedback)
            if aoi_mask is not None:
                slope_clip = os.path.join(scratch_dir, "slope_clipped.tif")
                clip_raster_by_mask(slope_reproj, aoi_mask, slope_clip,
                                    context=context, feedback=feedback)
                # Delete the reproj intermediate now that we have the clipped one
                try:
                    os.remove(slope_reproj)
                except OSError:
                    pass
                slope_reproj = slope_clip
            slope_path = os.path.join(prepared_dir, "slope.tif")
            _, gt_ref, xsz, ysz = get_raster_info(reference)
            ref_res = abs(gt_ref[1])
            ext = (f"{gt_ref[0]},{gt_ref[0]+gt_ref[1]*xsz},"
                   f"{gt_ref[3]+gt_ref[5]*ysz},{gt_ref[3]}")
            run_processing("gdal:warpreproject", {
                "INPUT": slope_reproj,
                "TARGET_CRS": target_crs,
                "TARGET_EXTENT": ext,
                "TARGET_EXTENT_CRS": target_crs,
                "TARGET_RESOLUTION": ref_res,
                "RESAMPLING": 0,
                "OPTIONS": "COMPRESS=LZW|TILED=YES",
                "OUTPUT": slope_path,
            }, context=context, feedback=feedback)
            # Delete the upstream intermediate now that slope.tif is final
            if slope_reproj != slope_path:
                try:
                    os.remove(slope_reproj)
                except OSError:
                    pass
        elif dem_layer is not None:
            feedback.pushInfo("Aligning DEM...")
            dem_reproj = os.path.join(scratch_dir, "dem_reproj.tif")
            reproject_raster(dem_layer.source(), target_crs_str, dem_reproj,
                             context=context, feedback=feedback)
            if aoi_mask is not None:
                dem_clip = os.path.join(scratch_dir, "dem_clipped.tif")
                clip_raster_by_mask(dem_reproj, aoi_mask, dem_clip,
                                    context=context, feedback=feedback)
                try:
                    os.remove(dem_reproj)
                except OSError:
                    pass
                dem_reproj = dem_clip
            dem_path = os.path.join(prepared_dir, "dem.tif")
            _, gt_ref, xsz, ysz = get_raster_info(reference)
            ref_res = abs(gt_ref[1])
            ext = (f"{gt_ref[0]},{gt_ref[0]+gt_ref[1]*xsz},"
                   f"{gt_ref[3]+gt_ref[5]*ysz},{gt_ref[3]}")
            run_processing("gdal:warpreproject", {
                "INPUT": dem_reproj,
                "TARGET_CRS": target_crs,
                "TARGET_EXTENT": ext,
                "TARGET_EXTENT_CRS": target_crs,
                "TARGET_RESOLUTION": ref_res,
                "RESAMPLING": 0,
                "OPTIONS": "COMPRESS=LZW|TILED=YES",
                "OUTPUT": dem_path,
            }, context=context, feedback=feedback)
            if dem_reproj != dem_path:
                try:
                    os.remove(dem_reproj)
                except OSError:
                    pass

        feedback.setProgress(20)

        # ================================================================
        #  STAGE 2 -- Distance surfaces
        # ================================================================
        _stage("STAGE 2: Distance Surfaces")
        if reuse_distances:
            feedback.pushInfo("  Reuse ticked: existing dist_*.tif will be reused if the grid matches.")
        else:
            feedback.pushInfo("  Reuse unticked (default): distances will be computed fresh.")
        # Read reference grid dimensions for cache validation
        _ref_ds = gdal.Open(reference, gdal.GA_ReadOnly)
        ref_x = _ref_ds.RasterXSize
        ref_y = _ref_ds.RasterYSize
        _ref_ds = None

        dist_paths = {}
        for name, raster_path in rasters.items():
            if feedback.isCanceled():
                # Was: silent break (continued into Stage 3 with partial
                # dist_paths and produced nonsense). Now raises so cancel
                # honoured loudly.
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    f"Cancelled by user (during distance surfaces, "
                    f"before completing '{name}').")
            if raster_path is None:
                continue
            if not enable_buffers.get(name, True):
                feedback.pushInfo(f"Skipping {name} — 'Include {name} buffer' is unticked.")
                continue
            dp = os.path.join(dist_dir, f"dist_{name}.tif")
            use_cache = False
            # Only consider cache reuse when user explicitly ticked Reuse.
            if reuse_distances and os.path.exists(dp):
                # Validate cached file matches reference grid
                _cds = gdal.Open(dp, gdal.GA_ReadOnly)
                if _cds and _cds.RasterXSize == ref_x and _cds.RasterYSize == ref_y:
                    use_cache = True
                    feedback.pushInfo(f"Using cached: {dp}")
                else:
                    feedback.pushInfo(f"Cached {name} has wrong dimensions, recomputing...")
                if _cds:
                    _cds = None
            if not use_cache:
                # P1.28: _safe_remove handles transient locks (OneDrive etc.).
                _safe_remove(dp, feedback=feedback)
                feedback.pushInfo(f"Computing distance for {name}...")
                proximity(raster_path, dp, max_distance=max_dist,
                          context=context, feedback=feedback)
            dist_paths[name] = dp

        feedback.setProgress(45)

        # ================================================================
        #  STAGE 3 -- Anthropogenic mask
        # ================================================================
        _stage("STAGE 3: Anthropogenic Mask")

        # Read reference dimensions
        ref_ds = gdal.Open(reference, gdal.GA_ReadOnly)
        x_size = ref_ds.RasterXSize
        y_size = ref_ds.RasterYSize
        gt = ref_ds.GetGeoTransform()
        proj = ref_ds.GetProjection()
        ref_ds = None

        combined_mask = np.zeros((y_size, x_size), dtype=np.uint8)
        for name, dp in dist_paths.items():
            if feedback.isCanceled():
                # Was: silent break (then wrote a half-built anthro mask).
                # Now raises so cancel honoured loudly.
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    f"Cancelled by user (during anthropogenic mask, "
                    f"before applying '{name}' threshold).")
            thresh = thresholds.get(name, 0)
            if thresh < 0:
                # Negative is invalid -- skip with a warning.
                feedback.pushWarning(
                    f"  Negative buffer ({thresh:g} m) for {name} -- skipping.")
                continue
            if thresh == 0:
                # P0.15 (zero-buffer rule, decided 2026-04-26): when input
                # is enabled AND buffer = 0, apply the input footprint
                # directly -- forest pixels coinciding with the input
                # become anthropogenic, but no buffer expansion. This is
                # the user's explicit "I want this layer to count but
                # without distance buffering" semantic.
                #
                # If thresh == 0 AND user didn't want the input at all,
                # they should untick the per-input enable_buffers checkbox
                # (which prevents the input ever entering rasters / dist_paths).
                input_path = rasters.get(name)
                if input_path is None or not os.path.exists(input_path):
                    feedback.pushInfo(
                        f"  Buffer = 0 for {name}, but no input raster "
                        "found in rasters dict -- skipping.")
                    continue
                feedback.pushInfo(
                    f"Buffer = 0 for {name}: applying input footprint "
                    "directly (no buffer expansion). To skip the input "
                    "entirely instead, untick its 'Include ... buffer' "
                    "checkbox.")
                ds = gdal.Open(input_path, gdal.GA_ReadOnly)
                arr = ds.GetRasterBand(1).ReadAsArray()
                ds = None
                combined_mask = np.maximum(
                    combined_mask, (arr == 1).astype(np.uint8))
                continue
            feedback.pushInfo(f"Thresholding {name} at {thresh} m...")
            ds = gdal.Open(dp, gdal.GA_ReadOnly)
            arr = ds.GetRasterBand(1).ReadAsArray()
            ds = None
            combined_mask = np.maximum(
                combined_mask, (arr <= thresh).astype(np.uint8))

        anthro_path = _out("04e", "anthropogenic_mask")
        _write(anthro_path, combined_mask, gt, proj, x_size, y_size)
        feedback.setProgress(55)

        # ================================================================
        #  STAGE 4 -- Primary forest tiers
        # ================================================================
        _stage("STAGE 4: Primary Forest Logic")

        forest_ds = gdal.Open(reference, gdal.GA_ReadOnly)
        forest = forest_ds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
        forest_ds = None

        # Tier 1 -- undisturbed forest (GEE canonical name: tier1_undisturbed)
        feedback.pushInfo("Tier 1 -- undisturbed forest...")
        tier1_undisturbed = ((forest == 1) & (combined_mask == 0)).astype(np.uint8)
        forest_inside_buffers = ((forest == 1) & (combined_mask == 1)).astype(np.uint8)
        _write(os.path.join(intermediates_dir, "tier1_undisturbed.tif"),
               tier1_undisturbed, gt, proj, x_size, y_size)
        _write(os.path.join(intermediates_dir, "forest_inside_buffers.tif"),
               forest_inside_buffers, gt, proj, x_size, y_size)

        # Slope -- use pre-computed slope if provided, else derive from DEM
        steep = None
        gentle = None
        slope_arr = None

        def _read_aligned(path, label):
            """Read a raster array, re-aligning to reference grid if needed."""
            ds = gdal.Open(path, gdal.GA_ReadOnly)
            arr = ds.GetRasterBand(1).ReadAsArray()
            ds = None
            if arr.shape != (y_size, x_size):
                feedback.pushInfo(
                    f"Re-aligning {label} from {arr.shape} to "
                    f"({y_size},{x_size})...")
                aligned_path = path.replace(".tif", "_realigned.tif")
                _, gt_ref, xsz, ysz = get_raster_info(reference)
                ref_res = abs(gt_ref[1])
                ext = (f"{gt_ref[0]},{gt_ref[0]+gt_ref[1]*xsz},"
                       f"{gt_ref[3]+gt_ref[5]*ysz},{gt_ref[3]}")
                run_processing("gdal:warpreproject", {
                    "INPUT": path,
                    "TARGET_CRS": target_crs,
                    "TARGET_EXTENT": ext,
                    "TARGET_EXTENT_CRS": target_crs,
                    "TARGET_RESOLUTION": ref_res,
                    "RESAMPLING": 0,
                    "OPTIONS": "COMPRESS=LZW|TILED=YES",
                    "OUTPUT": aligned_path,
                }, context=context, feedback=feedback)
                ds = gdal.Open(aligned_path, gdal.GA_ReadOnly)
                arr = ds.GetRasterBand(1).ReadAsArray()
                ds = None
            return arr

        if slope_path is not None:
            feedback.pushInfo("Using pre-computed slope raster...")
            slope_arr = _read_aligned(slope_path, "slope")
        elif dem_path is not None:
            feedback.pushInfo("Computing slope from DEM...")
            # Write into prepared/ so it sits alongside other aligned inputs
            # (consistent with anthro rasters, reusable in fast re-runs).
            slope_path = os.path.join(prepared_dir, "slope.tif")
            run_processing("gdal:slope", {
                "INPUT": dem_path,
                "BAND": 1, "SCALE": 1, "AS_PERCENT": False,
                "OPTIONS": "COMPRESS=LZW|TILED=YES",
                "OUTPUT": slope_path,
            }, context=context, feedback=feedback)
            slope_arr = _read_aligned(slope_path, "slope")

        if slope_arr is not None:
            steep = (slope_arr >= slope_thresh).astype(np.uint8)
            gentle = (slope_arr < slope_thresh).astype(np.uint8)
            _write(os.path.join(intermediates_dir, "steep_slope.tif"),
                   steep, gt, proj, x_size, y_size)
            _write(os.path.join(intermediates_dir, "gentle_slope.tif"),
                   gentle, gt, proj, x_size, y_size)

        # Tier 2 -- steep slope forest (GEE canonical name: tier2_steep)
        tier2_steep = np.zeros_like(forest)
        if steep is not None:
            feedback.pushInfo(
                f"Tier 2 -- steep slope forest (slope >= {slope_thresh:g} deg)...")
            tier2_steep = (
                (forest_inside_buffers == 1) & (steep == 1)
            ).astype(np.uint8)
            _write(os.path.join(intermediates_dir, "tier2_steep.tif"),
                   tier2_steep, gt, proj, x_size, y_size)

        # Tier 3 -- protected gentle-slope forest (GEE canonical name: tier3_protected)
        tier3_protected = np.zeros_like(forest)
        if pa_tif is not None and gentle is not None:
            feedback.pushInfo("Tier 3 -- protected gentle-slope forest...")
            pa = _read_aligned(pa_tif, "protected areas").astype(np.uint8)
            tier3_protected = (
                (forest_inside_buffers == 1) & (gentle == 1) & (pa == 1)
            ).astype(np.uint8)
            _write(os.path.join(intermediates_dir, "tier3_protected.tif"),
                   tier3_protected, gt, proj, x_size, y_size)

        # Combine
        feedback.pushInfo("Combining tiers -> pre_connectivity_forest...")
        primary_candidate = np.maximum(
            np.maximum(tier1_undisturbed, tier2_steep),
            tier3_protected,
        )
        # Aligned naming: pre_connectivity_forest (matches pFF_4)
        candidate_path = _out("03c", "pre_refinement_primary_forest")
        _write(candidate_path, primary_candidate, gt, proj, x_size, y_size)
        feedback.setProgress(80)

        # ================================================================
        #  STAGE 5 -- Refine output: two optional steps
        #    (a) Neighbourhood density filter
        #    (b) Minimum patch size filter (raster sieve)
        #  Both off (or master tickbox unticked) -> primary_forest.tif
        #  is just a copy of pre_connectivity_forest.tif.
        # ================================================================
        # Aligned naming: primary_forest (matches pFF_4 GEE export name)
        final_path = _out("04a", "primary_forest")
        step_a_on = enable_refine_output and smooth_radius > 0
        step_b_on = enable_refine_output and refine_min_patch_area_ha > 0

        if step_a_on or step_b_on:
            _stage("STAGE 5: Refine Output")
            fast_approx = self.parameterAsBool(
                parameters, self.FAST_APPROXIMATION, context)

            # Decide intermediate path layout:
            #  both steps -> step (a) writes to scratch, step (b) -> final
            #  only (a)   -> step (a) writes to final
            #  only (b)   -> step (b) reads candidate, writes final
            if step_a_on and step_b_on:
                step_a_out = os.path.join(
                    intermediates_dir, "refine_step_a_neighbourhood.tif")
                step_b_in = step_a_out
            elif step_a_on:
                step_a_out = final_path
                step_b_in = None
            else:
                step_a_out = None
                step_b_in = candidate_path

            if step_a_on:
                feedback.pushInfo(
                    f"Step (a) Neighbourhood density "
                    f"(radius={smooth_radius:g} m, "
                    f"density>={density_thresh:g}, fast={fast_approx})...")
                from .connectivity_filter import refine_output
                refine_output(candidate_path, step_a_out,
                              radius_m=smooth_radius,
                              threshold=density_thresh,
                              fast_approximation=fast_approx,
                              feedback=feedback)

            if feedback.isCanceled():
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    "Cancelled by user (between Refine Output steps).")

            if step_b_on:
                # Compute pixel-count threshold from hectares + pixel area.
                _res = abs(gt[1])
                _pixel_area_m2 = _res * _res
                import math as _math
                _min_area_m2 = refine_min_patch_area_ha * 10000.0
                _threshold_px = max(
                    1, _math.ceil(_min_area_m2 / _pixel_area_m2))
                feedback.pushInfo(
                    f"Step (b) Minimum patch size: removing connected "
                    f"groups < {_threshold_px} px "
                    f"(~{refine_min_patch_area_ha:g} ha) via gdal:sieve...")

                # Sieve to scratch first, then mask back to step_b_in
                # (the input to step b). gdal:sieve fills small "0-holes"
                # inside larger "1" regions by replacing them with the
                # surrounding value -- without the mask-back, the final
                # output would include pixels that were never forest.
                # Mirrors the mask-back-to-input principle Step (a)'s
                # neighbourhood filter already applies internally.
                _sieve_tmp = os.path.join(
                    intermediates_dir, "refine_step_b_sieve_unmasked.tif")
                run_processing("gdal:sieve", {
                    "INPUT": step_b_in,
                    "THRESHOLD": _threshold_px,
                    "EIGHT_CONNECTEDNESS": False,
                    "OUTPUT": _sieve_tmp,
                }, context=context, feedback=feedback)

                feedback.pushInfo(
                    "Step (b) masking sieve result back to step (b) input "
                    "(prevents hole-fill from creating pixels outside the "
                    "input forest extent)...")
                _ds_sv = gdal.Open(_sieve_tmp, gdal.GA_ReadOnly)
                _sv_arr = _ds_sv.GetRasterBand(1).ReadAsArray()
                _sv_gt = _ds_sv.GetGeoTransform()
                _sv_proj = _ds_sv.GetProjection()
                _sv_xsz = _ds_sv.RasterXSize
                _sv_ysz = _ds_sv.RasterYSize
                _ds_sv = None
                _ds_in = gdal.Open(step_b_in, gdal.GA_ReadOnly)
                _in_arr = _ds_in.GetRasterBand(1).ReadAsArray()
                _ds_in = None
                _masked = (
                    (_sv_arr == 1) & (_in_arr == 1)).astype(np.uint8)
                if os.path.exists(final_path):
                    try:
                        os.remove(final_path)
                    except OSError:
                        pass
                _drv = gdal.GetDriverByName("GTiff")
                _ds_out = _drv.Create(final_path, _sv_xsz, _sv_ysz, 1,
                                      gdal.GDT_Byte,
                                      ["COMPRESS=LZW", "TILED=YES"])
                _ds_out.SetGeoTransform(_sv_gt)
                _ds_out.SetProjection(_sv_proj)
                _ob = _ds_out.GetRasterBand(1)
                _ob.WriteArray(_masked)
                _ob.SetNoDataValue(0)
                _ob.FlushCache()
                _ds_out = None
        else:
            if not enable_refine_output:
                feedback.pushInfo(
                    "Skipping Refine Output (master tickbox off) -- "
                    "04a_primary_forest.tif copied from "
                    "03c_pre_refinement_primary_forest.tif.")
            else:
                feedback.pushInfo(
                    "Skipping Refine Output (both Step (a) radius and "
                    "Step (b) min patch area are 0).")
            run_processing("gdal:translate", {
                "INPUT": candidate_path, "OUTPUT": final_path,
            }, context=context, feedback=feedback)

        # -- Optional combined coded raster --
        if save_combined:
            feedback.pushInfo("Building combined coded raster...")
            final_ds = gdal.Open(final_path, gdal.GA_ReadOnly)
            final_arr = final_ds.GetRasterBand(1).ReadAsArray().astype(
                np.uint8)
            final_ds = None

            combined = np.zeros((y_size, x_size), dtype=np.uint8)
            combined[forest == 1] = 1
            combined[primary_candidate == 1] = 2
            combined[final_arr == 1] = 3

            combined_path = _out("03d", "combined_coded_raster")
            _write(combined_path, combined, gt, proj, x_size, y_size)
            feedback.pushInfo(
                "Combined coded raster: 0=none, 1=forest, "
                "2=pre-connectivity, 3=primary forest candidate")

        # ================================================================
        #  STAGE 6 -- Zonal statistics (optional)
        # ================================================================
        run_zonal = self.parameterAsBool(
            parameters, self.RUN_ZONAL_STATS, context)

        if run_zonal:
            _stage("STAGE 6: Zonal Statistics")

            from .zonal_statistics import (
                compute_zonal_stats, write_zonal_csv,
                join_stats_to_vector)

            # Stage 6 fail-soft wrapper: primary forest output is
            # already on disk by this point (stage 5 produced 04a).
            # If stats fail -- for example on QGIS < 3.16 where the
            # modern field-calculator algorithm IDs differ -- log a
            # warning + skip stats but DON'T fail the whole run.
            try:
                # Three-tier FRA cascade when plantations exclusion is active:
                #   Forest (raw input, includes plantations)
                #   Naturally regenerating forest (= forest AND NOT plantations)
                #   Primary forest (final tier output)
                # Otherwise just Forest + Primary forest (two-tier).
                zonal_rasters = {"forest": forest_raw_path}
                if forest_natreg_path is not None:
                    zonal_rasters["naturally_regenerating_forest"] = forest_natreg_path
                zonal_rasters["primary_forest"] = final_path

                zone_layer = self.parameterAsVectorLayer(
                    parameters, self.ZONE_LAYER, context)
                zone_path = zone_layer.source() if zone_layer else None
                zone_field = None
                if zone_path:
                    zone_field = (self.parameterAsString(
                        parameters, self.ZONE_FIELD, context).strip() or None)

                zonal_work = ensure_dir(os.path.join(intermediates_dir, "zonal_work"))

                results, totals = compute_zonal_stats(
                    ref_raster_path=final_path,
                    raster_paths=zonal_rasters,
                    zone_layer_path=zone_path,
                    zone_field=zone_field,
                    target_crs_str=target_crs_str,
                    work_dir=zonal_work,
                    context=context,
                    feedback=feedback,
                )

                # Print headline totals
                if totals:
                    feedback.pushInfo("")
                    feedback.pushInfo("========================================")
                    for label, kha in totals.items():
                        feedback.pushInfo(f"  {label}: {kha} kha")
                    feedback.pushInfo("========================================")
                elif results:
                    feedback.pushInfo("")
                    feedback.pushInfo("========================================")
                    for label in zonal_rasters:
                        key = f"{label}_kha"
                        if key in results[0]:
                            feedback.pushInfo(
                                f"  {label}: {results[0][key]} kha")
                    feedback.pushInfo("========================================")

                # CSV
                if results:
                    zonal_csv = _out("05a", "area_statistics", ext="csv")
                    write_zonal_csv(results, totals, zonal_csv, feedback)

                # Join to vector (if zones provided). Final OUTPUT 05b is
                # .gpkg (avoids shapefile field-name truncation + 2GB cap),
                # but the zone_with_id intermediate stays .shp because
                # zonal_statistics.py creates it upstream as .shp on
                # purpose (avoids gpkg FID uniqueness issues with GEE-
                # exported country boundaries that have duplicate FIDs).
                # native:reprojectlayer in join_stats_to_vector will convert
                # the .shp intermediate to .gpkg by extension on output.
                if results and zone_path:
                    zone_with_id = os.path.join(
                        zonal_work, "zones_with_id.shp")
                    zonal_vec = _out("05b", "area_statistics_by_zone", ext="gpkg")
                    join_stats_to_vector(
                        results, zone_with_id, zonal_vec,
                        target_crs_str, context, feedback)
            except Exception as _e_stage6:
                feedback.pushWarning(
                    f"⚠ STAGE 6 (Zonal Statistics) failed: {_e_stage6}")
                feedback.pushWarning(
                    "  -> Primary forest + forest + NRF rasters are "
                    "already on disk; only the area-statistics CSV / "
                    "per-zone GPKG were skipped.")

        # ================================================================
        #  STAGE 7 -- Vectorise (optional, advanced)
        # ================================================================
        # Polygonises selected outputs into .gpkg/.shp files with
        # optional Douglas-Peucker simplification. P1.28c semantics:
        # tick-what-it-says -- each VECTORIZE_* tick produces ONLY its
        # named output, no auto-enables, no side-effect outputs. CEO-
        # style nesting (cut primary out of forest) uses a coded raster
        # built from final_path + forest_src_path RASTERS directly, so
        # ticking nest does NOT require ticking forest or primary.
        #
        # Output filenames:
        #   primary tick -> 06a_primary_forest_vector
        #   forest tick  -> 06c_<forest_layer_name>_vector
        #   nest tick    -> 06c_<forest_layer_name>_with_primary_nested_vector
        #                 + 06d_<forest_layer_name>_with_primary_nested_dissolved
        #                   (when VECTORIZE_DISSOLVE_MULTIPART is on)
        # Whether naturally_regenerating_forest or forest is used is
        # determined by whether plantations refinement ran
        # (forest_natreg_path is non-None when it did). P1.16 renamed
        # the source layer to naturally_regenerating_forest; the
        # variable name forest_natreg_path was already aligned (natreg
        # = nat reg).
        # ================================================================
        if run_vectorize:
            _stage("STAGE 7: Vectorise outputs")
            vector_scratch = ensure_dir(
                os.path.join(intermediates_dir, "_vectorize"))

            # P1.30 batch 20a.4: optional pre-polygonise sieve. Drops
            # connected components below `vectorize_min_patch_ha` from
            # the binary rasters BEFORE polygonising. Applied to both
            # primary and the forest backdrop so the nest output also
            # benefits. The on-disk 04a primary_forest.tif and the
            # forest baseline rasters are NOT modified -- the sieve
            # writes into vector_scratch and only those scratch copies
            # feed the polygonise + nest steps.
            import math as _pff_math
            _v_pix_ds = gdal.Open(final_path, gdal.GA_ReadOnly)
            _v_pix_gt = _v_pix_ds.GetGeoTransform()
            _v_pixel_area_m2 = abs(_v_pix_gt[1] * _v_pix_gt[5])
            _v_pix_ds = None

            def _maybe_sieve(src_raster_path, layer_name):
                """Return a sieved-copy path if vectorize_min_patch_ha > 0,
                else the original path unchanged.

                NO_MASK=True is critical: the binary primary/forest rasters
                set nodata=0, so by default sieve treats 0 as excluded.
                A single isolated 1-pixel surrounded by 0s would then have
                no valid neighbour to reassign to and would survive.
                NO_MASK=True makes 0 a valid neighbour value, so isolated
                small 1-patches get reassigned to 0 (dropped). For the
                coded nested raster this also fills tiny 0-holes inside
                forest with 1 -- desired behaviour (those holes are noise).
                """
                if vectorize_min_patch_ha <= 0:
                    return src_raster_path
                threshold_px = max(1, int(_pff_math.ceil(
                    vectorize_min_patch_ha * 10000.0
                    / max(_v_pixel_area_m2, 1e-6))))
                _sieved = os.path.join(
                    vector_scratch, f"{layer_name}_sieved.tif")
                feedback.pushInfo(
                    f"  Pre-vectorise sieve: dropping {layer_name} patches "
                    f"< {vectorize_min_patch_ha} ha "
                    f"({threshold_px} px @ {_v_pixel_area_m2:.0f} m^2/px)...")
                _safe_remove(_sieved, feedback=feedback)
                run_processing("gdal:sieve", {
                    "INPUT": src_raster_path,
                    "THRESHOLD": threshold_px,
                    "EIGHT_CONNECTEDNESS": False,
                    "NO_MASK": True,
                    "MASK_LAYER": None,
                    "EXTRA": "",
                    "OUTPUT": _sieved,
                }, context=context, feedback=feedback)
                return _sieved

            # P1.30 batch 20a.5: auto-clean pixel-stair vertices.
            # gdal:polygonize stamps a vertex on every pixel boundary,
            # so straight raster edges carry many redundant collinear
            # points. Visvalingam-Whyatt @ half-pixel tolerance drops
            # those without changing visible shape. Runs after
            # polygonise and before any user-driven Douglas-Peucker
            # simplify (which then has fewer vertices to chew through).
            _v_pixel_size_m = abs(_v_pix_gt[1])
            _stair_tol = _v_pixel_size_m / 2.0

            def _maybe_pixel_stair_clean(polys_tmp_path, layer_name):
                if not vectorize_remove_pixel_stairs:
                    return polys_tmp_path
                _stair_clean = os.path.join(
                    vector_scratch, f"{layer_name}_stairfree.gpkg")
                feedback.pushInfo(
                    f"  Auto-cleaning pixel-stair vertices on "
                    f"{layer_name} (Visvalingam @ {_stair_tol:.1f} m)...")
                _safe_remove(_stair_clean, feedback=feedback)
                run_processing("native:simplifygeometries", {
                    "INPUT": polys_tmp_path,
                    "METHOD": 2,  # Visvalingam-Whyatt area
                    "TOLERANCE": _stair_tol,
                    "OUTPUT": _stair_clean,
                }, context=context, feedback=feedback)
                return _stair_clean

            def _do_polygonise(src_raster_path, step, layer_name,
                               target_path=None):
                """Mask + polygonise + optional simplify. Returns polys path.

                Args:
                    src_raster_path: source raster (binary 0/1).
                    step: Option D step substring e.g. '06a'.
                    layer_name: snake-case descriptor without _vector
                                suffix or extension (e.g. 'primary_forest').
                                The function appends '_vector' and '.gpkg'.
                    target_path: optional override for the output path.
                                When set, polygonise writes here instead of
                                the canonical _out(step, ...) location. Used
                                by nesting flow to write to scratch first
                                then diff into the canonical file.
                """
                polys_path = (target_path if target_path is not None
                              else _out(step, f"{layer_name}_vector", ext=vec_ext))
                # Build mask raster with nodata=0 so polygonize skips
                # background efficiently. Source rasters are already
                # binary 0/1, so the mask is just (arr == 1).
                _ds_v = gdal.Open(src_raster_path, gdal.GA_ReadOnly)
                _v_arr = _ds_v.GetRasterBand(1).ReadAsArray()
                _v_gt = _ds_v.GetGeoTransform()
                _v_proj = _ds_v.GetProjection()
                _v_xsz = _ds_v.RasterXSize
                _v_ysz = _ds_v.RasterYSize
                _ds_v = None
                _v_mask = (_v_arr == 1).astype(np.uint8)
                _v_masked_tif = os.path.join(
                    vector_scratch, f"{layer_name}_masked.tif")
                if os.path.exists(_v_masked_tif):
                    try:
                        os.remove(_v_masked_tif)
                    except OSError:
                        pass
                _drv_v = gdal.GetDriverByName("GTiff")
                _ds_o = _drv_v.Create(_v_masked_tif, _v_xsz, _v_ysz, 1,
                                      gdal.GDT_Byte,
                                      ["COMPRESS=LZW", "TILED=YES"])
                _ds_o.SetGeoTransform(_v_gt)
                # Defensive: if source raster has empty/missing CRS,
                # fall back to the target_crs_str so polygonize doesn't
                # produce pixel-coordinate polygons. (Pixel-coord polys
                # would render at lat/long 0 with target-CRS metadata
                # stamped -- the "polygons in wrong place" bug.)
                if _v_proj:
                    _ds_o.SetProjection(_v_proj)
                else:
                    from qgis.core import QgsCoordinateReferenceSystem
                    _fallback_crs = QgsCoordinateReferenceSystem(target_crs_str)
                    _ds_o.SetProjection(_fallback_crs.toWkt())
                    feedback.pushWarning(
                        f"  Source raster for {layer_name} had no CRS; "
                        f"using target {target_crs_str} as fallback.")
                _ob = _ds_o.GetRasterBand(1)
                _ob.WriteArray(_v_mask)
                _ob.SetNoDataValue(0)
                _ob.FlushCache()
                _ds_o = None
                del _v_arr, _v_mask

                # Always polygonise to scratch first, then pass through
                # gdal.VectorTranslate to canonical with explicit
                # -a_srs (and optional -simplify). Uniform path means
                # canonical always has CRS metadata stamped, regardless
                # of simplify=0 vs >0. Avoids "polygons in wrong place"
                # bug when polygonize output lacks CRS metadata.
                polys_tmp = os.path.join(
                    vector_scratch, f"{layer_name}_polys_raw.gpkg")

                feedback.pushInfo(
                    f"  Polygonising {layer_name} (gdal:polygonize, "
                    "4-connected)...")
                run_processing("gdal:polygonize", {
                    "INPUT": _v_masked_tif,
                    "BAND": 1,
                    "FIELD": "value",
                    "EIGHT_CONNECTEDNESS": False,
                    "EXTRA": "",
                    "OUTPUT": polys_tmp,
                }, context=context, feedback=feedback)

                # P1.30 batch 20a.5: drop redundant collinear vertices
                # from the polygonise output (raster pixel stairs)
                # before any user simplify runs.
                polys_for_translate = _maybe_pixel_stair_clean(
                    polys_tmp, layer_name)

                # Always pass through ogr2ogr to set -a_srs explicitly.
                # If simplify is on, fold it into the same pass.
                if vectorize_simplify_m > 0:
                    feedback.pushInfo(
                        f"  Simplifying {layer_name} (ogr2ogr "
                        f"-simplify, tolerance={vectorize_simplify_m:g} m)...")
                    feedback.pushWarning(
                        "Simplify can introduce geometry artefacts; "
                        "reduce tolerance if downstream tools throw "
                        "errors.")
                    _vt_options = [
                        '-simplify', str(vectorize_simplify_m),
                        '-a_srs', target_crs_str,
                    ]
                else:
                    feedback.pushInfo(
                        f"  Stamping {layer_name} with target CRS "
                        f"({target_crs_str})...")
                    _vt_options = ['-a_srs', target_crs_str]
                # P1.28: _safe_remove handles transient locks. The
                # forest_full.gpkg failure on OneDrive paths happened
                # right here -- the helper retries with backoff so a
                # transient sync lock doesn't abort the whole run.
                _safe_remove(polys_path, feedback=feedback)
                gdal.VectorTranslate(
                    polys_path, polys_for_translate,
                    format=vec_format,
                    options=_vt_options,
                )

                return polys_path

            # ── Vectorise primary forest ──
            # Tick produces 06a only -- no dissolve (CEO-relevant
            # dissolve is nested-only; users wanting a dissolved primary
            # can run native:dissolve themselves).
            # Resolve sieved-or-original primary path once so the nest
            # path below (which builds the coded raster directly from
            # the primary + forest backdrop rasters) gets the same
            # patch-filtering treatment as the standalone polygonise.
            primary_for_vec = _maybe_sieve(final_path, "primary_forest")
            primary_polys_path = None
            if vectorize_primary:
                primary_polys_path = _do_polygonise(
                    primary_for_vec, "06a", "primary_forest")

            if feedback.isCanceled():
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    "Cancelled by user (during vectorise stage).")

            # ── Resolve forest source (used by forest tick AND nest tick) ──
            # Use naturally regenerating forest if plantations refinement
            # produced one, else the AOI-clipped forest input. Naming
            # carries through to output filenames so the user can tell
            # which they got. Computed once because both vectorize_forest
            # and vectorize_nest read this raster.
            forest_src_path = None
            forest_name_base = None
            forest_src_for_vec = None
            if vectorize_forest or vectorize_nest:
                if forest_natreg_path is not None:
                    forest_src_path = forest_natreg_path
                    forest_name_base = "naturally_regenerating_forest"
                else:
                    forest_src_path = prepared_forest_path
                    forest_name_base = "forest"
                forest_src_for_vec = _maybe_sieve(
                    forest_src_path, forest_name_base)

            # ── Vectorise forest input (plain, non-nested) ──
            # Tick produces 06c_<base>_vector only. No dissolve. When
            # vectorize_nest is also ticked the user gets BOTH this plain
            # 06c AND the nested 06c below (different filenames).
            forest_polys_path = None
            if vectorize_forest:
                forest_polys_path = _do_polygonise(
                    forest_src_for_vec, "06c", forest_name_base)

            if feedback.isCanceled():
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    "Cancelled by user (during vectorise stage).")

            # ── Nested output: primary as level=2, surrounding nat-reg as
            #    level=1 in a single coded raster, polygonised in one pass.
            # Reads forest_src_path + final_path as RASTERS directly (no
            # dependency on the polygonised forest/primary vectors). This
            # is why ticking nest no longer auto-enables forest/primary.
            nested_polys_path = None
            if vectorize_nest:
                # Batch 28.8 item 5: nest+dissolve are exclusive.
                # When dissolve is on, the canonical 06c becomes an
                # intermediate (in scratch) -- only 06d emerges in
                # out_dir. When dissolve is off, the canonical 06c IS
                # the user-facing nest output.
                if vectorize_dissolve_multipart:
                    _canonical_forest_polys = os.path.join(
                        vector_scratch,
                        f"{forest_name_base}_with_primary_"
                        f"nested_vector_intermediate.{vec_ext}")
                else:
                    _canonical_forest_polys = _out(
                        "06c",
                        f"{forest_name_base}_with_primary_nested_vector",
                        ext=vec_ext)
                feedback.pushInfo(
                    f"  Nesting (coded-raster path): building "
                    f"2-level coded raster (1={forest_name_base} "
                    "outside primary, 2=primary) and polygonising "
                    "in one pass -- avoids slow vector difference.")
                # Build a 2-level coded raster from the nat-reg
                # baseline + primary forest. Polygonising this in
                # one pass produces a single vector with a 'level'
                # attribute (1 or 2) that perfectly tiles nat reg
                # without overlap. Much faster than the previous
                # polygonise + native:difference + fieldcalculator
                # + mergevectorlayers chain, and geometrically
                # cleaner (no slivers from vector subtraction).
                # Use the (possibly sieved) backdrop + primary so the
                # nested output benefits from the same patch filter as
                # the standalone vectorise paths above.
                _nat_reg_src = forest_src_for_vec  # sieved-or-original
                _ds_n = gdal.Open(_nat_reg_src, gdal.GA_ReadOnly)
                _n_arr = _ds_n.GetRasterBand(1).ReadAsArray()
                _n_gt = _ds_n.GetGeoTransform()
                _n_proj = _ds_n.GetProjection()
                _n_xsz = _ds_n.RasterXSize
                _n_ysz = _ds_n.RasterYSize
                _ds_n = None
                _ds_p = gdal.Open(primary_for_vec, gdal.GA_ReadOnly)
                _p_arr = _ds_p.GetRasterBand(1).ReadAsArray()
                _ds_p = None
                # 2 = primary, 1 = nat reg outside primary, 0 = none
                _nested_arr = np.where(
                    _p_arr == 1, 2,
                    np.where(_n_arr == 1, 1, 0)).astype(np.uint8)
                del _n_arr, _p_arr
                _nested_tif = os.path.join(
                    vector_scratch,
                    f"{forest_name_base}_with_primary_nested_coded.tif")
                if os.path.exists(_nested_tif):
                    try:
                        os.remove(_nested_tif)
                    except OSError:
                        pass
                _drv_v = gdal.GetDriverByName("GTiff")
                _ds_n_out = _drv_v.Create(
                    _nested_tif, _n_xsz, _n_ysz, 1,
                    gdal.GDT_Byte,
                    ["COMPRESS=LZW", "TILED=YES"])
                _ds_n_out.SetGeoTransform(_n_gt)
                if _n_proj:
                    _ds_n_out.SetProjection(_n_proj)
                else:
                    from qgis.core import QgsCoordinateReferenceSystem
                    _ds_n_out.SetProjection(
                        QgsCoordinateReferenceSystem(target_crs_str).toWkt())
                _b_n = _ds_n_out.GetRasterBand(1)
                _b_n.WriteArray(_nested_arr)
                _b_n.SetNoDataValue(0)
                _b_n.FlushCache()
                _ds_n_out = None
                del _nested_arr
                # P1.30: OneDrive CFAPI defence. After we close the
                # GTiff dataset, OneDrive may briefly leave the file in
                # a placeholder state that the gdal:polygonize child
                # process can't open ("does not exist in the file
                # system"). Verify the file is openable here, retrying
                # for up to ~5s, before invoking polygonize.
                import time as _pff_time_mod
                _verified = False
                for _retry in range(20):
                    if os.path.exists(_nested_tif):
                        _verify = gdal.Open(_nested_tif, gdal.GA_ReadOnly)
                        if _verify is not None:
                            _verify = None
                            _verified = True
                            break
                    _pff_time_mod.sleep(0.25)
                if not _verified:
                    from qgis.core import QgsProcessingException
                    raise QgsProcessingException(
                        f"Nested coded raster was written but is not "
                        f"readable after 5s: {_nested_tif}. If your "
                        f"output folder is on OneDrive / Dropbox / "
                        f"another sync provider, try moving it to a "
                        f"local drive or pause sync for the run.")
                # P1.30 batch 20a.5b: sieve on the CODED raster too.
                # The earlier sieve only ran on the binary primary +
                # forest rasters before they were combined. Combining
                # can produce small level=1 slivers (forest where a
                # primary patch cuts a hole) that escape that sieve.
                # Sieving the coded raster catches those: gdal:sieve
                # operates per-class, dropping small connected
                # components in any value class.
                _nested_tif_for_polygonize = _maybe_sieve(
                    _nested_tif,
                    f"{forest_name_base}_with_primary_nested_coded")
                # P1.28: _safe_remove handles transient locks (OneDrive etc.).
                _safe_remove(_canonical_forest_polys, feedback=feedback)
                # Polygonise to scratch always; final pass through
                # ogr2ogr applies -a_srs (and optional -simplify).
                # Uniform CRS handling regardless of simplify state.
                _nested_polys_raw = os.path.join(
                    vector_scratch,
                    f"{forest_name_base}_with_primary_nested_polys_raw.gpkg")
                feedback.pushInfo(
                    "  Polygonising nested coded raster...")
                run_processing("gdal:polygonize", {
                    "INPUT": _nested_tif_for_polygonize,
                    "BAND": 1,
                    "FIELD": "level",
                    "EIGHT_CONNECTEDNESS": False,
                    "EXTRA": "",
                    "OUTPUT": _nested_polys_raw,
                }, context=context, feedback=feedback)
                # Polygonize ran in a child process -- same OneDrive
                # CFAPI symptom can hit the OUTPUT gpkg before we hand
                # it to VectorTranslate below. Verify before continuing.
                _verified_polys = False
                for _retry in range(20):
                    if (os.path.exists(_nested_polys_raw)
                            and os.path.getsize(_nested_polys_raw) > 0):
                        _verified_polys = True
                        break
                    _pff_time_mod.sleep(0.25)
                if not _verified_polys:
                    from qgis.core import QgsProcessingException
                    raise QgsProcessingException(
                        f"gdal:polygonize did not produce a readable "
                        f"output: {_nested_polys_raw}. Check the run "
                        f"log above for the underlying GDAL error. "
                        f"If output is on OneDrive, try a local path.")
                # P1.30 batch 20a.5: pixel-stair clean on the nested
                # raw polygons before the canonical write.
                _nested_polys_for_translate = _maybe_pixel_stair_clean(
                    _nested_polys_raw,
                    f"{forest_name_base}_with_primary_nested")
                if vectorize_simplify_m > 0:
                    feedback.pushInfo(
                        f"  Simplifying nested polygons (ogr2ogr "
                        f"-simplify, tolerance="
                        f"{vectorize_simplify_m:g} m)...")
                    _nest_vt_options = [
                        '-simplify', str(vectorize_simplify_m),
                        '-a_srs', target_crs_str,
                    ]
                else:
                    feedback.pushInfo(
                        f"  Stamping nested polygons with target "
                        f"CRS ({target_crs_str})...")
                    _nest_vt_options = ['-a_srs', target_crs_str]
                gdal.VectorTranslate(
                    _canonical_forest_polys, _nested_polys_for_translate,
                    format=vec_format,
                    options=_nest_vt_options,
                )
                nested_polys_path = _canonical_forest_polys

            if feedback.isCanceled():
                from qgis.core import QgsProcessingException
                raise QgsProcessingException(
                    "Cancelled by user (during vectorise stage).")

            # ── Collect nested output into multiparts by level ──
            # Scoped to the nested case only -- this is the CEO-relevant
            # output (level=1 surrounding nat-reg + level=2 primary as
            # two multipart features for stratified sampling). Primary
            # 06a and forest 06c are NOT collected; users wanting that
            # can run native:collect / native:dissolve themselves.
            #
            # P1.30 batch 20a.5: switched from native:dissolve to
            # native:collect. Collect groups features by attribute into
            # multiparts WITHOUT unioning touching neighbours -- way
            # faster on dense polygon sets (the union work in dissolve
            # is wasted here; for stratified sampling only the level
            # grouping matters, not whether touching parts are merged).
            nested_dissolved_path = None
            if vectorize_nest and vectorize_dissolve_multipart:
                nested_dissolved_path = _out(
                    "06d",
                    f"{forest_name_base}_with_primary_nested_dissolved",
                    ext=vec_ext)
                feedback.pushInfo(
                    f"  Collecting {forest_name_base} (nested, by "
                    "level) into multipart features...")
                run_processing("native:collect", {
                    "INPUT": nested_polys_path,
                    "FIELD": ["level"],
                    "OUTPUT": nested_dissolved_path,
                }, context=context, feedback=feedback)
            elif vectorize_nest and not vectorize_dissolve_multipart:
                feedback.pushInfo(
                    "  Nested collect skipped (VECTORIZE_DISSOLVE_"
                    "MULTIPART unticked) -- 06d_*_nested_dissolved "
                    "not produced.")

            # Defensive CRS stamp: gdal:polygonize occasionally writes
            # vector outputs without proper CRS metadata even when the
            # source raster has it (intermittent on Windows + some
            # QGIS / GDAL combos). Two paths:
            #   - Shapefile: write the .prj sidecar directly with the
            #     target WKT. No temp file, no rename -- avoids both
            #     the .gpkg-to-.shp format mismatch and the OneDrive
            #     file-lock window during atomic replace.
            #   - GPKG / other single-file: VectorTranslate to a temp
            #     in the same format, then atomic os.replace.
            def _stamp_crs(path):
                if not os.path.exists(path):
                    return
                # P1.30 batch 20a.5: skip the rewrite if CRS is already
                # set on the file. Every polygonise output now goes
                # through ogr2ogr -a_srs at write time (or
                # VectorTranslate -a_srs in the nest path), so the
                # redundant rewrite was wasting I/O and occasionally
                # failing with a Windows file-lock when native:collect
                # had just held the file open.
                try:
                    _check_ds = gdal.OpenEx(
                        path, gdal.OF_VECTOR | gdal.OF_READONLY)
                    if _check_ds is not None:
                        _layer = _check_ds.GetLayer(0)
                        if _layer is not None:
                            _srs = _layer.GetSpatialRef()
                            if _srs is not None:
                                # Any SRS set is enough. We don't
                                # validate authority code -- legacy
                                # files may have only WKT.
                                _check_ds = None
                                return
                        _check_ds = None
                except Exception:
                    pass  # fall through to defensive stamp
                if vec_ext == "shp":
                    try:
                        from osgeo import osr
                        _srs = osr.SpatialReference()
                        _srs.SetFromUserInput(target_crs_str)
                        _prj = os.path.splitext(path)[0] + ".prj"
                        with open(_prj, "w") as _f:
                            _f.write(_srs.ExportToWkt())
                    except Exception as _e:
                        feedback.pushWarning(
                            f"  CRS stamp failed for {os.path.basename(path)}: "
                            f"{_e}. File may load without CRS.")
                    return
                _tmp = path + ".__crsfix__." + vec_ext
                try:
                    gdal.VectorTranslate(
                        _tmp, path, format=vec_format,
                        options=['-a_srs', target_crs_str])
                    os.replace(_tmp, path)
                except Exception as _e:
                    feedback.pushWarning(
                        f"  CRS stamp failed for {os.path.basename(path)}: "
                        f"{_e}. File may load without CRS.")
                    if os.path.exists(_tmp):
                        try:
                            os.remove(_tmp)
                        except OSError:
                            pass

            # CRS stamp uses the actual produced paths. Only the four
            # outputs that this batch can produce: 06a primary, 06c plain
            # forest, 06c nested, 06d nested_dissolved.
            for _vec in [
                primary_polys_path,
                forest_polys_path,
                nested_polys_path,
                nested_dissolved_path,
            ]:
                if _vec:
                    _stamp_crs(_vec)

        # ================================================================
        #  Write run metadata
        # ================================================================
        _close_last_stage()
        _pff_total_runtime = round(_pff_time.monotonic() - _pff_t_start, 2)
        feedback.pushInfo(f"Total runtime: {_pff_total_runtime:.1f}s")

        import json
        from datetime import datetime
        metadata = {
            "pff_version": self.PFF_VERSION,
            "timestamp": datetime.now().isoformat(),
            "runtime_seconds": _pff_total_runtime,
            "stage_runtimes_seconds": _pff_stage_times,
            "target_crs": target_crs_str,
            "intermediates_dir": intermediates_dir,
            "local_scratch_intermediates": local_scratch_intermediates,
            "parameters": {
                "year": _year_tag,
                "aoi_buffer_m": aoi_buffer_dist,
                "use_single_buffer_distance": use_single,
                "single_buffer_distance_m": single_dist if use_single else None,
                "reuse_cached_distances": reuse_distances,
                "reuse_prepared": reuse_prepared,
                "roads_dist_m": thresholds["roads"],
                "builtup_dist_m": thresholds["builtup"],
                "builtup_large_dist_m": thresholds["builtup_large"],
                "agriculture_dist_m": thresholds["agriculture"],
                "max_distance_m": max_dist,
                "slope_threshold_deg": slope_thresh,
                "smooth_radius_m": smooth_radius,
                "density_threshold": density_thresh,
                "refine_min_patch_area_ha": refine_min_patch_area_ha,
                "run_vectorize": run_vectorize,
                "vectorize_primary": vectorize_primary if run_vectorize else None,
                "vectorize_forest": vectorize_forest if run_vectorize else None,
                "vectorize_nest": vectorize_nest if run_vectorize else None,
                "vectorize_dissolve_multipart": (
                    vectorize_dissolve_multipart if run_vectorize else None),
                "vectorize_simplify_m": vectorize_simplify_m if run_vectorize else None,
                "auto_utm": auto_utm,
                "exclude_plantations": exclude_plantations,
                "plantations_applied": forest_natreg_path is not None,
                "exclude_agriculture_from_forest": exclude_agriculture_from_forest,
                "fra_agriculture_applied": (
                    fra_agriculture_tif is not None
                    and exclude_agriculture_from_forest),
                "custom_slots": {
                    key: {
                        "label": custom_slot_labels.get(key, key),
                        "buffer_dist_m": thresholds.get(key),
                    } for key in custom_slot_labels
                },
            },
            "inputs": {
                "forest_raster": forest_layer.source(),
                "aoi": aoi_layer.source() if aoi_layer else None,
                "dem": dem_layer.source() if dem_layer else None,
                "plantations": (plantations_layer.source()
                                if plantations_layer else None),
            },
            "outputs": {
                "primary_forest": final_path,
                "pre_connectivity_forest": candidate_path,
                "anthropogenic_mask": anthro_path,
                "forest": forest_baseline_top_path,
                "naturally_regenerating_forest": forest_natreg_path,
            },
            "raster_properties": {
                "x_size": x_size,
                "y_size": y_size,
                "resolution_m": abs(gt[1]),
            },
        }
        # P1.13: run metadata sidecar gets ISO3 prefix when set; otherwise
        # plain run_metadata.json. No step number — it's a contextual sidecar,
        # not a per-stage layer.
        # P1.30 batch 20c: route through generate_layer_name so the
        # metadata sidecar gets the same year + AOI prefix as the
        # other outputs (consistency for trends + sub-national runs).
        # Use a synthetic step "00" since metadata isn't a numbered
        # stage; the helper still applies the prefix correctly.
        _meta_basename = generate_layer_name(
            _iso3, PLATFORM_QGIS, "00", "run_metadata", ext="json",
            year=_year_tag, aoi_label=_aoi_label)
        # Strip the "00_" step prefix to preserve the current semantic
        # (no step number on the sidecar).
        _meta_basename = _meta_basename.replace("_qgis_00_", "_qgis_")
        if _meta_basename.startswith("qgis_00_"):
            _meta_basename = "qgis_" + _meta_basename[len("qgis_00_"):]
        meta_path = os.path.join(out_dir, _meta_basename)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        feedback.pushInfo(f"Metadata: {meta_path}")

        # P1.30 batch 20a.2: optional cleanup of the per-run scratch
        # intermediates dir. Only happens on the local-scratch path
        # (never deletes anything next to the user's outputs) and only
        # when the user explicitly opted in.
        # NOTE: shutil is imported at module level (line 15); no local
        # import here -- a local `import shutil` here would shadow the
        # module-level name and break shutil.copy2() / disk_usage()
        # called earlier in this function.
        if local_scratch_intermediates and cleanup_intermediates:
            try:
                shutil.rmtree(intermediates_dir, ignore_errors=True)
                feedback.pushInfo(
                    f"Cleaned up scratch intermediates: {intermediates_dir}")
            except Exception as _e:
                feedback.pushWarning(
                    f"Could not clean up intermediates "
                    f"{intermediates_dir}: {_e}")

        # ── Auto-load main outputs into the QGIS project (P0.5 partial) ──
        # Uses the standard Processing pattern -- works in GUI mode, no-ops
        # cleanly in headless mode. Layer styling defaults; QML preload is
        # a separate task (deferred -- needs a colour scheme decision).
        from qgis.core import QgsProcessingContext
        _layers_to_load = []  # list of (display_name, path) tuples

        if add_main_outputs_to_map:
            # Order matters: QGIS adds each new layer ABOVE the
            # previous one in the Layers panel, so to get the GEE
            # default panel order (Primary on top, then Pre-connectivity,
            # then Naturally regenerating, then Forest at the bottom)
            # we register in REVERSE -- last appended ends up on top.
            #
            # P1.30 batch 22: gate each registration by the per-layer
            # SAVE flag. When SAVE=False the layer file lives in
            # scratch (cleaned up post-run); loading it to map would
            # produce a broken layer reference. Skip those.
            _fra_tag = (
                "" if parameters.get("TREE_COVER_MODE") == "fra"
                else " (non-FRA-aligned)")
            _forest_top_path = _out("02c", "forest")
            if save_02b_forest and os.path.exists(_forest_top_path):
                _layers_to_load.append(
                    ("Forest" + _fra_tag, _forest_top_path))
            if (save_02d_nrf and forest_natreg_path is not None
                    and os.path.exists(forest_natreg_path)):
                _layers_to_load.append(
                    ("Naturally regenerating forest" + _fra_tag,
                     forest_natreg_path))
            if save_03c_pre_conn and os.path.exists(candidate_path):
                _layers_to_load.append(
                    ("Pre-connectivity forest", candidate_path))
            if save_04a_primary:
                _layers_to_load.append(("Primary forest", final_path))
            # Vectorise outputs auto-load when produced. P1.28c output
            # matrix: 06a (primary), 06c plain forest, 06c nested, 06d
            # nested_dissolved. Loaded ABOVE primary so the user sees the
            # polygon outputs as the topmost layers (CEO sampling
            # boundary on top makes most sense).
            if run_vectorize:
                if (vectorize_forest and forest_polys_path is not None
                        and os.path.exists(forest_polys_path)):
                    _layers_to_load.append(
                        ("Forest polygons (06c)", forest_polys_path))
                if (vectorize_nest and nested_polys_path is not None
                        and os.path.exists(nested_polys_path)):
                    _layers_to_load.append(
                        ("Forest with primary nested (06c)",
                         nested_polys_path))
                if (vectorize_nest and nested_dissolved_path is not None
                        and os.path.exists(nested_dissolved_path)):
                    _layers_to_load.append(
                        ("Forest with primary nested, dissolved (06d)",
                         nested_dissolved_path))
                if (vectorize_primary and primary_polys_path is not None
                        and os.path.exists(primary_polys_path)):
                    _layers_to_load.append(
                        ("Primary forest polygons (06a)", primary_polys_path))

        # P0.14: optional human-influence + buffer layers. Default OFF
        # (matches GEE master toggle). Adds the prepared anthro inputs +
        # protection inputs + plantations + custom slots + the combined
        # anthropogenic mask. Distance-surface intermediates are
        # deliberately skipped -- they're internal continuous-value
        # rasters that aren't useful as visual review layers without
        # styling.
        if add_human_influence_layers_to_map:
            _hi_candidates = [
                ("Input: Roads",            os.path.join(prepared_dir, "roads.tif")),
                ("Input: Built-up small",   os.path.join(prepared_dir, "builtup_small.tif")),
                ("Input: Built-up large",   os.path.join(prepared_dir, "builtup_large.tif")),
                ("Input: Agriculture",      os.path.join(prepared_dir, "agriculture.tif")),
                ("Input: Plantations",      os.path.join(prepared_dir, "plantations.tif")),
                ("Input: Protected areas",  os.path.join(prepared_dir, "protected.tif")),
                ("Input: Slope (degrees)",  os.path.join(prepared_dir, "slope.tif")),
            ]
            # Custom human-use slots get their user-editable label.
            for _i in (1, 2, 3):
                _key = f"custom_{_i}"
                _label = custom_slot_labels.get(
                    _key, f"Custom disturbance {_i}")
                _hi_candidates.append(
                    (f"Input: {_label}",
                     os.path.join(prepared_dir, f"{_key}.tif")))
            # Note: anthropogenic_mask intentionally NOT auto-loaded
            # by default -- it's a debug/intermediate output, not a
            # headline review layer. Available at <out>/04e_anthropogenic_mask.tif
            # for users who want to inspect it manually.
            for _name, _path in _hi_candidates:
                if os.path.exists(_path):
                    _layers_to_load.append((_name, _path))

        if _layers_to_load:
            for _name, _path in _layers_to_load:
                _details = QgsProcessingContext.LayerDetails(
                    _name, context.project(), _name)
                context.addLayerToLoadOnCompletion(_path, _details)
            feedback.pushInfo(
                f"Auto-loading {len(_layers_to_load)} layer(s) on "
                "completion: " + ", ".join(n for n, _ in _layers_to_load))

        feedback.setProgress(100)
        feedback.pushInfo("Done. Full PFF workflow complete.")
        feedback.pushInfo(f"Final output: {final_path}")
        return {self.OUTPUT_FOLDER: out_dir}


# -- Utilities --------------------------------------------------------

def _write(path, array, gt, proj, x_size, y_size):
    """Create a Byte GeoTIFF and write the array. Handles the common case
    where the destination file is locked by another process (typically QGIS
    itself holding it open as an already-added layer from a prior run).
    """
    driver = gdal.GetDriverByName("GTiff")
    # Try to remove the existing file first. If it's locked (Windows file
    # lock from QGIS, OneDrive sync, etc.), raise a clear error instead of
    # the bare "RuntimeError" GDAL produces.
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError as e:
            raise RuntimeError(
                f"Cannot overwrite output file '{os.path.basename(path)}' — "
                f"it is locked by another process. Remove the layer from "
                f"the QGIS Layers panel (right-click → Remove Layer), close "
                f"any program that has it open, then re-run. (original: {e})"
            )
    ds = driver.Create(path, x_size, y_size, 1, gdal.GDT_Byte,
                       options=["COMPRESS=LZW", "TILED=YES"])
    if ds is None:
        raise RuntimeError(
            f"Could not create output file '{os.path.basename(path)}' — "
            f"check folder permissions and disk space. Full path: {path}"
        )
    ds.SetGeoTransform(gt)
    ds.SetProjection(proj)
    band = ds.GetRasterBand(1)
    band.WriteArray(array)
    band.SetNoDataValue(0)
    band.FlushCache()
    ds = None


def _detect_utm_zone(forest_layer, aoi_layer, feedback):
    """Determine the appropriate UTM zone from AOI centroid or forest raster.

    Returns an EPSG code string like 'EPSG:32717'.
    """
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject

    # Get centroid in WGS84
    if aoi_layer is not None:
        extent = aoi_layer.extent()
        src_crs = aoi_layer.crs()
    else:
        extent = forest_layer.extent()
        src_crs = forest_layer.crs()

    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    if src_crs != wgs84:
        transform = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())
        extent = transform.transformBoundingBox(extent)

    lon = extent.center().x()
    lat = extent.center().y()
    lon_width = extent.width()

    # UTM zone number: 1-60
    zone = int((lon + 180) / 6) + 1
    zone = max(1, min(60, zone))

    # EPSG code: 326xx for north, 327xx for south
    if lat >= 0:
        epsg = 32600 + zone
    else:
        epsg = 32700 + zone

    feedback.pushInfo(
        f"Auto UTM: centroid ({lat:.2f}, {lon:.2f}) -> "
        f"EPSG:{epsg} (UTM zone {zone}{'N' if lat >= 0 else 'S'})")

    # Warn if AOI spans more than one UTM zone (>6 degrees longitude)
    if lon_width > 6:
        n_zones = int(lon_width / 6) + 1
        feedback.reportError(
            f"WARNING: AOI spans ~{lon_width:.0f} degrees of longitude "
            f"(~{n_zones} UTM zones). A single UTM zone may cause "
            f"significant distortion at the edges. Consider using a "
            f"wider-coverage CRS (e.g. a continental equal-area projection) "
            f"instead of Auto UTM.")

    return f"EPSG:{epsg}"

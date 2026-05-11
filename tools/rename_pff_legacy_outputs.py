"""Rename legacy PFF GEE export filenames to the current schema.

Maps OLD <ISO3>_<digit>_<name>_<rest> pattern to NEW
<ISO3>_gee_<NN><letter>_<name>_<rest>, with text renames applied per
the post-Batch 25.1 / 27.1 schema:

  plantations              -> planted_forest
  pre_connectivity_forest  -> pre_refinement_primary_forest
  agriculture_tree_cover_fra -> other_land_with_tree_cover

Designed for in-place rename against a Google Drive for Desktop
mount (or any local folder). Drive treats it as a metadata rename
when the file content is unchanged -- no re-upload.

Usage:
  # Dry run (default) -- prints proposed renames; nothing changes:
  python rename_pff_legacy_outputs.py "G:/Shared drives/PFF_Asia_Pacific_data"

  # Apply for real (after reviewing dry-run output):
  python rename_pff_legacy_outputs.py "G:/Shared drives/PFF_Asia_Pacific_data" --apply

The script:
  - Walks the tree recursively.
  - Skips files already in the new schema (containing "_gee_").
  - For ambiguous "_1_forest_" matches: lists them and prompts
    once per directory for the desired step letter (default 02c).
  - Groups shapefile sidecars (.shp/.shx/.dbf/.prj/.cpg/.qpj +
    .aux.xml/.qix etc.) so they rename together.
  - Logs a summary of renamed / skipped / unmapped files.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────
# Mapping table
# ─────────────────────────────────────────────────────────────────────
# Each entry maps OLD layer-name regex -> NEW layer-name template.
# The full filename is then rebuilt as
#   <ISO3>_gee_<NEW_PREFIX>_<rest><ext>
# where <rest> is everything after the OLD prefix in the matched name.
#
# Special: "_1_forest_" requires user choice. Handled separately below.

# Regex matches the OLD prefix segment AFTER the ISO3 underscore, e.g.
# "1_forest", "4_pre_connectivity_forest", "0_aoi_<X>_vector".
# Group 1 captures the rest (everything we keep verbatim except for
# text-renames applied via REPLACEMENT_RULES below).

LAYER_RULES: List[Tuple[str, str]] = [
    # (OLD prefix regex from after ISO3_, NEW prefix to substitute)
    # Country name may include underscores (e.g. Viet_Nam,
    # Lao_Peoples_Democratic_Republic). Non-greedy capture between
    # "0_aoi_" and the literal "_vector" anchor.
    (r"^0_aoi_(.+?)_vector$", "00a_aoi_{0}_vector"),
    (r"^1_hansen_treecover2000_raw$", "02a_hansen_treecover2000_raw"),
    (r"^1_hansen_lossyear_raw$", "02a_hansen_lossyear_raw"),
    (r"^1_glad_tree_height_m$", "02a_glad_tree_height_m"),
    # _1_forest handled by ASK_FOREST below (multiple valid mappings)
    (r"^2_roads$", "03a_roads"),
    (r"^2_builtup_small$", "03a_builtup_small"),
    (r"^2_builtup_large$", "03a_builtup_large"),
    (r"^2_agriculture$", "03a_agriculture"),
    (r"^2_plantations$", "02d_planted_forest"),
    (r"^2_agriculture_tree_cover_fra$", "02b_other_land_with_tree_cover"),
    (r"^3_protection_legal$", "03b_protection_legal"),
    (r"^3_protection_legal_unfilt_vector$",
     "03b_protection_legal_unfiltered_vector"),
    (r"^3_protection_natural_dem$", "03b_protection_natural_dem"),
    (r"^3_protection_natural_slope$", "03b_protection_natural_slope"),
    (r"^4_pre_connectivity_forest$",
     "03c_pre_refinement_primary_forest"),
    (r"^5_primary_forest$", "04a_primary_forest"),
    # Run-metadata sidecar (no leading digit, special form):
    (r"^pff_run_metadata$", "gee_run_metadata"),
]
COMPILED_RULES = [(re.compile(p), t) for p, t in LAYER_RULES]

# Forest ambiguity: "_1_forest_" can map to several step letters.
# We'll prompt the user once per directory.
FOREST_OPTIONS = {
    "1": ("02c_forest", "Input forest baseline (FRA-aligned, default)"),
    "2": ("02a_forest_raw", "Raw thresholded tree cover (no FRA filter)"),
    "3": ("__SKIP__", "Skip these — leave as-is"),
}

# Shapefile / GeoTIFF sidecar extensions that travel with the main file
# and must be renamed atomically.
PRIMARY_EXTS = {".tif", ".tiff", ".shp", ".geojson", ".gpkg", ".kml"}
SIDECAR_EXTS = {
    ".shx", ".dbf", ".prj", ".cpg", ".qpj", ".qix", ".fix",
    ".aux.xml", ".tif.aux.xml", ".sbn", ".sbx", ".cpg.aux.xml",
    ".dbf.aux.xml", ".shp.xml",
}

# Filename suffix-stripping for grouping shapefile sidecars.
def _stem_for_grouping(filename: str) -> Tuple[str, str]:
    """Return (stem, full-extension-suffix) where stem is everything
    before the recognised primary/sidecar suffix. Multi-dot suffixes
    like .tif.aux.xml are preserved."""
    lower = filename.lower()
    for ext in sorted(SIDECAR_EXTS | PRIMARY_EXTS,
                      key=len, reverse=True):
        if lower.endswith(ext):
            return (filename[:-len(ext)], filename[-len(ext):])
    # Generic fallback: split at the last dot
    if "." in filename:
        i = filename.rfind(".")
        return (filename[:i], filename[i:])
    return (filename, "")


# ─────────────────────────────────────────────────────────────────────
# Core rename logic
# ─────────────────────────────────────────────────────────────────────

ISO3_RX = re.compile(r"^([A-Z]{3})_(.+)$")


def parse_legacy_stem(stem: str) -> Optional[Tuple[str, str, str]]:
    """If the stem starts with `<ISO3>_<digit>_<name>_<year>_<scale>m_*`
    or similar, return (iso3, layer_prefix, rest).

    layer_prefix is the OLD prefix portion BEFORE the year/scale tail.
    rest is the trailing year/scale/timehash portion (or "").

    Returns None for stems that don't match the legacy pattern.
    """
    m = ISO3_RX.match(stem)
    if not m:
        return None
    iso3, after = m.group(1), m.group(2)
    # Skip files already in NEW schema:
    if after.startswith("gee_") or after.startswith("qgis_"):
        return None
    # Find the boundary between layer_prefix and trailing year/scale.
    # The layer_prefix is everything up to the FIRST "_<year>_<scale>m"
    # or the END of the stem (for static files like
    # "0_aoi_<X>_vector" or "3_protection_legal_<s>m").
    # Trailing form (all parts optional, in order):
    #   _YYYY            -- year
    #   _NNNm            -- scale
    #   _HHhMMm          -- time-hash suffix
    #   -NNNNN-NNNNN     -- GEE tile-split suffix (large countries)
    tail_rx = re.compile(
        r"(.*?)("
        r"(?:_\d{4})?"
        r"(?:_\d+m)?"
        r"(?:_\d{2}h\d{2}m)?"
        r"(?:-\d+-\d+)?"
        r")$")
    tm = tail_rx.match(after)
    if not tm:
        return (iso3, after, "")
    layer_prefix = tm.group(1).rstrip("_")
    rest = tm.group(2)  # starts with "_" if non-empty
    return (iso3, layer_prefix, rest)


def map_layer_prefix(layer_prefix: str,
                     forest_choice: Optional[str]
                     ) -> Optional[str]:
    """Map an OLD layer prefix to a NEW one. Returns None if no rule
    matches OR if the user chose to skip "_1_forest_" files."""
    for rx, template in COMPILED_RULES:
        m = rx.match(layer_prefix)
        if m:
            return template.format(*m.groups())
    if layer_prefix.startswith("1_forest"):
        if forest_choice is None:
            return None  # caller hasn't prompted yet
        if forest_choice == "__SKIP__":
            return None
        return forest_choice + layer_prefix[len("1_forest"):]
    return None


def build_new_name(old_filename: str,
                   forest_choice: Optional[str]
                   ) -> Optional[str]:
    """Given an OLD filename (just the basename), return the NEW name
    or None if no rule matches.

    Forest mapping requires forest_choice (the chosen step prefix from
    FOREST_OPTIONS) when the filename contains _1_forest_.
    """
    stem, ext = _stem_for_grouping(old_filename)
    parsed = parse_legacy_stem(stem)
    if not parsed:
        return None
    iso3, layer_prefix, rest = parsed
    new_prefix = map_layer_prefix(layer_prefix, forest_choice)
    if new_prefix is None:
        return None
    new_stem = f"{iso3}_gee_{new_prefix}{rest}"
    return new_stem + ext


# ─────────────────────────────────────────────────────────────────────
# Folder-walking + apply
# ─────────────────────────────────────────────────────────────────────

_IGNORE_BASENAMES = {"desktop.ini", "Thumbs.db", ".DS_Store"}


def walk_targets(root: str) -> List[str]:
    """List all candidate file basenames in the tree (full paths)."""
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden/system folders sync engines may create
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in (
                           "__pycache__", ".tmp.driveupload",
                           ".tmp.drivedownload")]
        for fn in filenames:
            if fn in _IGNORE_BASENAMES:
                continue
            out.append(os.path.join(dirpath, fn))
    return out


def has_forest_ambiguity(paths: List[str]) -> List[str]:
    """Filter paths whose basename starts with <ISO3>_1_forest_."""
    rx = re.compile(r"^[A-Z]{3}_1_forest_")
    return [p for p in paths if rx.match(os.path.basename(p))]


def pick_forest_option(prompt_label: str) -> str:
    """Prompt the user to pick a mapping for _1_forest_ files."""
    print(f"\n┌─ Forest-name mapping for {prompt_label} " + "─" * 30)
    for k, (target, descr) in FOREST_OPTIONS.items():
        print(f"│  {k}. {descr}")
    print("└" + "─" * 60)
    while True:
        ans = input("Pick 1/2/3: ").strip()
        if ans in FOREST_OPTIONS:
            return FOREST_OPTIONS[ans][0]
        print("Invalid input. Type 1, 2, or 3.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="Root folder to walk (e.g. the "
                    "PFF_Asia_Pacific_data Drive mount path).")
    ap.add_argument("--apply", action="store_true",
                    help="Actually rename files. Default is dry-run.")
    ap.add_argument("--forest-choice",
                    choices=list(FOREST_OPTIONS.keys()),
                    help="Pre-pick the _1_forest_ mapping (1/2/3) to "
                         "skip the per-folder prompt.")
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        print(f"ERROR: not a directory: {args.root}", file=sys.stderr)
        sys.exit(1)

    print(f"Walking: {args.root}")
    print(f"Mode:    {'APPLY (live rename)' if args.apply else 'DRY RUN'}")

    all_paths = walk_targets(args.root)
    print(f"Files found: {len(all_paths)}")

    # Determine forest choice (per-directory if not pre-picked).
    forest_paths_by_dir: Dict[str, List[str]] = defaultdict(list)
    for p in has_forest_ambiguity(all_paths):
        forest_paths_by_dir[os.path.dirname(p)].append(p)

    forest_choice_by_dir: Dict[str, str] = {}
    if forest_paths_by_dir and not args.forest_choice:
        print(
            f"\nFound _1_forest_ files in {len(forest_paths_by_dir)} "
            "folder(s). You'll be prompted per folder.")
        for d, paths in forest_paths_by_dir.items():
            print(f"\nFolder: {d}")
            print(f"  ({len(paths)} matching files)")
            for p in paths[:5]:
                print(f"    - {os.path.basename(p)}")
            if len(paths) > 5:
                print(f"    …and {len(paths) - 5} more")
            forest_choice_by_dir[d] = pick_forest_option(
                os.path.basename(d))
    elif args.forest_choice:
        chosen = FOREST_OPTIONS[args.forest_choice][0]
        for d in forest_paths_by_dir:
            forest_choice_by_dir[d] = chosen

    # Build rename plan.
    plan: List[Tuple[str, str]] = []
    skipped_already_new = 0
    skipped_unmapped: List[str] = []
    for old_path in all_paths:
        old_basename = os.path.basename(old_path)
        # Skip files already in new schema
        if "_gee_" in old_basename or "_qgis_" in old_basename:
            skipped_already_new += 1
            continue
        forest_choice = forest_choice_by_dir.get(
            os.path.dirname(old_path))
        new_basename = build_new_name(old_basename, forest_choice)
        if new_basename is None:
            skipped_unmapped.append(old_path)
            continue
        if new_basename == old_basename:
            continue
        new_path = os.path.join(os.path.dirname(old_path), new_basename)
        plan.append((old_path, new_path))

    # Print summary.
    print("\n" + "=" * 60)
    print(f"Rename plan: {len(plan)} file(s)")
    print(f"Already-new (skipped): {skipped_already_new}")
    print(f"Unmapped (skipped):    {len(skipped_unmapped)}")
    print("=" * 60)
    for old, new in plan[:25]:
        print(f"  {os.path.basename(old)}")
        print(f"    -> {os.path.basename(new)}")
    if len(plan) > 25:
        print(f"  …and {len(plan) - 25} more")
    if skipped_unmapped:
        print("\nUnmapped (no rule matched -- will NOT rename):")
        for p in skipped_unmapped[:10]:
            print(f"  {os.path.basename(p)}")
        if len(skipped_unmapped) > 10:
            print(f"  …and {len(skipped_unmapped) - 10} more")

    if not args.apply:
        print("\nDRY RUN -- no files renamed. Re-run with --apply "
              "to perform the renames.")
        return 0

    # Apply.
    print("\nApplying renames…")
    ok, fail = 0, 0
    for old, new in plan:
        try:
            if os.path.exists(new):
                print(f"  [SKIP] target exists: {new}")
                continue
            os.rename(old, new)
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  [FAIL] {old} -> {new}: {e}")
    print(f"\nDone. Renamed: {ok}. Failed: {fail}.")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

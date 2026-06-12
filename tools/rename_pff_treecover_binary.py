"""Rename previously-exported PFF GeoTIFFs to the post-2026-06 naming.

Two `02a` exports were renamed (GEE v4.16.0-beta.14 / plugin 0.16.0-beta.16):

    02a_forest_raw          ->  02a_tree_cover_binary    (thresholded tree-cover input)
    02a_glad_tree_height_m  ->  02a_glad_tree_height_raw (continuous GLAD height)

`forest_raw` clashed with the genuine Hansen/GLAD `*_raw` *source* exports, so it
read like raw source data. The new names follow the convention
`raw` = continuous source, `binary` = thresholded mask.

The GEE app and QGIS plugin still AUTO-MATCH the old `02a_forest_raw` files, so
this rename is optional housekeeping — it just makes already-downloaded folders
line up with the new names.

What it does:
  - Walks a folder recursively (sub-folders included).
  - Renames any file whose name contains an old token — including GeoTIFF
    sidecars (`.tif.aux.xml`, `.tfw`, `.tif.ovr`, ...) so they stay paired with
    their raster.
  - Lists every change (old name -> new name); optionally writes a CSV manifest.
  - Skips (never overwrites) a file whose new name already exists.
  - Idempotent: safe to re-run; already-renamed files are left alone.

What it does NOT do:
  - Touch the band name *inside* a raster (that only affects newly-exported
    files and isn't used for matching).
  - Edit file contents (e.g. paths inside run-metadata JSON).

Stdlib only — no GDAL. On a Google Drive for Desktop mount a rename is a
metadata-only change (no re-upload of file content).

Usage:
  # Dry run (default) -- lists proposed renames; nothing changes:
  python rename_pff_treecover_binary.py "G:/Shared drives/PFF_data"

  # Apply for real, after reviewing the dry-run list:
  python rename_pff_treecover_binary.py "G:/Shared drives/PFF_data" --apply

  # Also write a CSV record of what changed:
  python rename_pff_treecover_binary.py "<folder>" --apply --manifest changes.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

# OLD filename token -> NEW token. Applied as a plain substring replacement on
# each basename, in order. (Neither old token is a substring of the other, and
# the full token is matched, so e.g. the "30m" scale suffix is never touched.)
RENAMES = [
    ("02a_forest_raw", "02a_tree_cover_binary"),
    ("02a_glad_tree_height_m", "02a_glad_tree_height_raw"),
]

_IGNORE_BASENAMES = {"desktop.ini", "Thumbs.db", ".DS_Store"}
_SKIP_DIRS = {"__pycache__", ".tmp.driveupload", ".tmp.drivedownload"}


def new_basename(name: str) -> str:
    """Apply the token renames to a single basename (returns it unchanged if
    no token is present)."""
    out = name
    for old, new in RENAMES:
        out = out.replace(old, new)
    return out


def build_plan(root):
    """Walk `root` recursively.

    Returns (plan, conflicts):
      plan      -- list of (old_path, new_path) for files whose name changes
                   and whose target does NOT already exist.
      conflicts -- list of (old_path, new_path) where the target already
                   exists (left untouched, never overwritten).
    """
    plan = []
    conflicts = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in _SKIP_DIRS]
        for fn in filenames:
            if fn in _IGNORE_BASENAMES:
                continue
            new_fn = new_basename(fn)
            if new_fn == fn:
                continue
            old_path = os.path.join(dirpath, fn)
            new_path = os.path.join(dirpath, new_fn)
            if os.path.exists(new_path):
                conflicts.append((old_path, new_path))
            else:
                plan.append((old_path, new_path))
    return plan, conflicts


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="Folder to walk recursively.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually rename. Default is a dry run (list only).")
    ap.add_argument("--manifest", metavar="CSV",
                    help="Write a CSV record (old_path, new_name, status).")
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        print(f"ERROR: not a directory: {args.root}", file=sys.stderr)
        return 1

    print(f"Walking: {args.root}")
    print(f"Mode:    {'APPLY (live rename)' if args.apply else 'DRY RUN (list only)'}\n")

    plan, conflicts = build_plan(args.root)

    if not plan and not conflicts:
        print("No files matched the old names — nothing to do "
              "(already renamed, or none present).")
        if args.manifest:
            _write_manifest(args.manifest, [], [], applied=args.apply)
        return 0

    # The list the user asked for: what changes, and into what.
    print(f"{len(plan)} file(s) to rename:")
    for old, new in plan:
        print(f"  {os.path.relpath(old, args.root)}")
        print(f"    -> {os.path.basename(new)}")

    if conflicts:
        print(f"\n{len(conflicts)} skipped — a file with the new name already "
              "exists (NOT overwritten):")
        for old, new in conflicts:
            print(f"  {os.path.relpath(old, args.root)}  ->  "
                  f"{os.path.basename(new)}  [TARGET EXISTS]")

    results = []  # (old_path, new_path, status)
    if not args.apply:
        results = [(o, n, "would-rename") for o, n in plan]
        results += [(o, n, "conflict-skip") for o, n in conflicts]
        print(f"\nDRY RUN — nothing changed. Re-run with --apply to rename "
              f"the {len(plan)} file(s).")
    else:
        print(f"\nApplying {len(plan)} rename(s)…")
        ok = fail = 0
        for old, new in plan:
            try:
                os.rename(old, new)
                results.append((old, new, "renamed"))
                ok += 1
            except OSError as e:
                results.append((old, new, f"failed: {e}"))
                fail += 1
                print(f"  [FAIL] {old} -> {new}: {e}")
        results += [(o, n, "conflict-skip") for o, n in conflicts]
        print(f"\nDone. Renamed: {ok}. Failed: {fail}. "
              f"Skipped (conflicts): {len(conflicts)}.")

    if args.manifest:
        _write_manifest(args.manifest, plan, conflicts, applied=args.apply,
                        results=results)
        print(f"Wrote manifest: {args.manifest}")

    if args.apply and any(s.startswith("failed") for _, _, s in results):
        return 2
    return 0


def _write_manifest(path, plan, conflicts, applied, results=None):
    rows = results if results is not None else (
        [(o, n, "would-rename") for o, n in plan]
        + [(o, n, "conflict-skip") for o, n in conflicts])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["old_path", "new_name", "status"])
        for old, new, status in rows:
            w.writerow([old, os.path.basename(new), status])


if __name__ == "__main__":
    sys.exit(main())

"""Adapt a PFF settings.json template for a different country's GEE export folder.

Takes a known-good settings.json (e.g. from a Thailand run) and rewrites
file paths, ISO3, year, CRS, and output folder to match a different
country's GEE batch export.  All thresholds, toggles, and buffer distances
are preserved from the template.

Pure Python — no QGIS dependency.  Run from any terminal.

Usage:
  # Single country:
  python tools/adapt_settings.py \\
    --template  "C:/pff_outputs/THA/settings.json" \\
    --folder    "G:/My Drive/PFF_Asia_Pacific_data/PFF_export_Bhutan" \\
    --year 2020 --crs 32646

  # Batch (all PFF_export_* subfolders):
  python tools/adapt_settings.py \\
    --template  "C:/pff_outputs/THA/settings.json" \\
    --folder    "G:/My Drive/PFF_Asia_Pacific_data" \\
    --batch --year 2020

Output:
  {folder}/settings.json          — adapted config (load via Config > Load)
  {folder}/settings_report.md     — what was matched, what's missing
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from collections import namedtuple
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ── GEE filename parser ────────────────────────────────────────────────

GeeFile = namedtuple("GeeFile", [
    "path", "iso3", "step", "description", "year", "scale", "timestamp",
    "tiles", "ext",
])

STEM_RX = re.compile(
    r"^(?P<iso3>[A-Z]{3})_gee_"
    r"(?P<step>\d{2}[a-z]?)_"
    r"(?P<body>.+)_"
    r"(?P<timestamp>\d{2}h\d{2}m)"
    r"(?P<tiles>(?:-\d{10,})+)?$"
)

BODY_TAIL_RX = re.compile(
    r"^(?P<desc>.+?)"
    r"(?:_(?P<year>\d{4}))"
    r"(?:_(?P<scale>\d+)m)?$"
)

BODY_NOYEAR_RX = re.compile(
    r"^(?P<desc>.+?)"
    r"(?:_(?P<scale>\d+)m)?$"
)

SIDECAR_EXTS = {".shx", ".dbf", ".prj", ".cpg", ".fix", ".qpj", ".qix",
                ".aux.xml", ".tif.aux.xml", ".xml"}

SKIP_DIRS = {"_duplicates", "__pycache__"}


def parse_gee_filename(filepath: str) -> Optional[GeeFile]:
    basename = os.path.basename(filepath)
    # strip extension(s)
    if basename.lower().endswith(".tif.aux.xml"):
        return None
    if basename.lower().endswith(".aux.xml"):
        return None

    name, ext = os.path.splitext(basename)
    ext_lower = ext.lower()
    if ext_lower in SIDECAR_EXTS:
        return None
    if ext_lower not in (".tif", ".shp", ".gpkg", ".geojson"):
        return None

    m = STEM_RX.match(name)
    if not m:
        return None

    iso3 = m.group("iso3")
    step = m.group("step")
    body = m.group("body")
    timestamp = m.group("timestamp")
    tiles = m.group("tiles") or ""

    # try body with year first
    bm = BODY_TAIL_RX.match(body)
    if bm:
        desc = bm.group("desc")
        year = bm.group("year")
        scale = bm.group("scale")
    else:
        bm2 = BODY_NOYEAR_RX.match(body)
        if bm2:
            desc = bm2.group("desc")
            year = None
            scale = bm2.group("scale")
        else:
            desc = body
            year = None
            scale = None

    return GeeFile(
        path=filepath, iso3=iso3, step=step, description=desc,
        year=year, scale=scale, timestamp=timestamp, tiles=tiles,
        ext=ext_lower,
    )


# ── Slot mapping rules ─────────────────────────────────────────────────

SlotRule = namedtuple("SlotRule", [
    "param_key", "step", "desc_match", "ext_pref", "year_varying", "notes",
])

SLOT_RULES = [
    SlotRule("AOI",                    "00a", "aoi",                       ".shp",  False, ""),
    SlotRule("FOREST_RASTER",          "02a", "forest_raw",                ".tif",  True,  ""),
    SlotRule("FRA_AGRICULTURE_RASTER", "02b", "other_land_with_tree_cover",".tif",  True,  "prefer_90m"),
    SlotRule("PLANTATIONS_RASTER",     "02d", "planted_forest",            ".tif",  True,  "prefer_90m"),
    SlotRule("ROADS",                  "03a", "roads_osm_vector",          ".shp",  False, ""),
    SlotRule("BUILTUP_SMALL_RASTER",   "03a", "builtup_small",             ".tif",  True,  ""),
    SlotRule("BUILTUP_LARGE_RASTER",   "03a", "builtup_large",             ".tif",  True,  ""),
    SlotRule("AGRICULTURE_RASTER",     "03a", "agriculture",               ".tif",  True,  ""),
    SlotRule("PROTECTED_RASTER",       "03b", "protection_legal",          ".tif",  False, "exact"),
    SlotRule("DEM",                    "03b", "protection_natural_dem",     ".tif",  False, "warn_tiles"),
]

# ── Folder scanner ──────────────────────────────────────────────────────

def scan_folder(folder: str) -> List[GeeFile]:
    inventory = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            gf = parse_gee_filename(fpath)
            if gf:
                inventory.append(gf)
    return inventory


def auto_detect_year(inventory: List[GeeFile]) -> Optional[str]:
    years = [gf.year for gf in inventory if gf.year]
    if not years:
        return None
    from collections import Counter
    counts = Counter(years)
    return max(counts, key=lambda y: (counts[y], y))


def auto_detect_iso3(inventory: List[GeeFile]) -> Optional[str]:
    codes = [gf.iso3 for gf in inventory]
    if not codes:
        return None
    from collections import Counter
    return Counter(codes).most_common(1)[0][0]


# ── Slot matcher ────────────────────────────────────────────────────────

def match_slots(
    inventory: List[GeeFile],
    target_year: Optional[str],
) -> Tuple[Dict[str, str], List[str], List[str]]:
    matched: Dict[str, str] = {}
    warnings: List[str] = []
    missing: List[str] = []

    for rule in SLOT_RULES:
        candidates = [
            gf for gf in inventory
            if gf.step == rule.step
            and gf.ext == rule.ext_pref
        ]

        # description matching
        if "exact" in rule.notes:
            candidates = [
                gf for gf in candidates
                if gf.description == rule.desc_match
            ]
        else:
            candidates = [
                gf for gf in candidates
                if gf.description.startswith(rule.desc_match)
            ]

        # year filter
        if rule.year_varying and target_year:
            year_match = [gf for gf in candidates if gf.year == target_year]
            if year_match:
                candidates = year_match

        # prefer 90m over 30m
        if "prefer_90m" in rule.notes and len(candidates) > 1:
            has_90 = [gf for gf in candidates if gf.scale == "90"]
            if has_90:
                candidates = has_90

        # tile handling for DEM
        if "warn_tiles" in rule.notes:
            tile_files = [gf for gf in candidates if gf.tiles]
            if tile_files:
                first_tile = sorted(tile_files, key=lambda gf: gf.tiles)[0]
                non_tile = [gf for gf in candidates if not gf.tiles]
                if non_tile:
                    candidates = non_tile
                else:
                    candidates = [first_tile]
                    warnings.append(
                        f"DEM: {len(tile_files)} tile files found (GEE split export). "
                        f"Only first tile mapped. Consider merging with: "
                        f"gdalbuildvrt dem_merged.vrt *_dem_*.tif"
                    )

        if candidates:
            best = sorted(candidates, key=lambda gf: gf.timestamp)[-1]
            matched[rule.param_key] = best.path
        else:
            missing.append(rule.param_key)

    return matched, warnings, missing


# ── Settings adapter ────────────────────────────────────────────────────

def adapt_settings(
    template: dict,
    matched: Dict[str, str],
    iso3: str,
    year: str,
    crs: Optional[str],
    output_folder: str,
) -> dict:
    result = copy.deepcopy(template)
    params = result.get("params") or result
    if "params" in result:
        params = result["params"]

    for key, path in matched.items():
        params[key] = path.replace("\\", "/")

    # clear unmatched file slots that the template had
    file_keys = {r.param_key for r in SLOT_RULES}
    for key in file_keys:
        if key not in matched and key in params:
            params[key] = None

    params["ISO3_PREFIX"] = iso3
    params["YEAR"] = year or params.get("YEAR", "2020")
    params["OUTPUT_FOLDER"] = output_folder.replace("\\", "/")
    params["AUTO_UTM"] = False
    params["REGION_LABEL"] = ""

    if crs:
        params["TARGET_CRS_EPSG"] = str(crs)
        params["TARGET_CRS"] = f"EPSG:{crs}"
    else:
        params["TARGET_CRS_EPSG"] = ""
        params["TARGET_CRS"] = ""

    # ZONE_LAYER = same as AOI
    if "AOI" in matched:
        params["ZONE_LAYER"] = matched["AOI"].replace("\\", "/")

    # ROADS: clear ROADS_RASTER if we mapped vector
    if "ROADS" in matched:
        params["ROADS_RASTER"] = None

    result["saved_at"] = datetime.now().isoformat(timespec="seconds")

    return result


# ── Report generator ────────────────────────────────────────────────────

def generate_report(
    template_path: str,
    folder: str,
    iso3: str,
    year: str,
    crs: Optional[str],
    matched: Dict[str, str],
    missing: List[str],
    warnings: List[str],
) -> str:
    lines = [
        "# PFF Settings Adaptation Report",
        "",
        f"**Template:** `{template_path}`",
        f"**Target folder:** `{folder}`",
        f"**ISO3:** {iso3}",
        f"**Year:** {year or '(auto)'}",
        f"**CRS:** {f'EPSG:{crs}' if crs else '(not set — pick in QGIS dock)'}",
        f"**Generated:** {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]

    lines.append("## Matched Slots")
    lines.append("")
    lines.append("| Param | File |")
    lines.append("|-------|------|")
    for rule in SLOT_RULES:
        if rule.param_key in matched:
            fname = os.path.basename(matched[rule.param_key])
            lines.append(f"| {rule.param_key} | `{fname}` |")
    lines.append("")

    if missing:
        lines.append("## Missing Slots")
        lines.append("")
        lines.append("| Param | Notes |")
        lines.append("|-------|-------|")
        for key in missing:
            lines.append(f"| {key} | No matching file found in folder |")
        lines.append("")

    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("## Settings Preserved from Template")
    lines.append("")
    lines.append("All buffer distances, toggles, refine output settings, save list "
                 "preferences, and validation settings are carried over unchanged.")
    lines.append("")

    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Adapt a PFF settings.json template for a different "
                    "country's GEE export folder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--template", required=True,
                    help="Path to template settings.json")
    ap.add_argument("--folder", required=True,
                    help="Path to target GEE export folder (or parent for --batch)")
    ap.add_argument("--year",
                    help="Analysis year (default: auto-detect latest)")
    ap.add_argument("--crs",
                    help="EPSG code for target CRS (e.g. 32645). "
                         "Omit to leave blank (dock prompts user)")
    ap.add_argument("--output",
                    help="Output path for settings.json "
                         "(default: {folder}/settings.json)")
    ap.add_argument("--batch", action="store_true",
                    help="Batch: --folder is parent dir, process each "
                         "PFF_export_* subfolder")
    return ap.parse_args()


def process_one(
    template: dict,
    template_path: str,
    folder: str,
    year: Optional[str],
    crs: Optional[str],
    output_path: Optional[str],
) -> bool:
    inventory = scan_folder(folder)
    if not inventory:
        print(f"  ERROR: no GEE files found in {folder}")
        return False

    iso3 = auto_detect_iso3(inventory)
    if not iso3:
        print(f"  ERROR: could not detect ISO3 from filenames")
        return False

    target_year = year or auto_detect_year(inventory)
    print(f"  ISO3: {iso3}, year: {target_year or '?'}, "
          f"files found: {len(inventory)}")

    matched, warnings, missing = match_slots(inventory, target_year)
    print(f"  Matched: {len(matched)}/{len(SLOT_RULES)} slots")
    if missing:
        print(f"  Missing: {', '.join(missing)}")
    for w in warnings:
        print(f"  WARNING: {w}")

    out_folder = os.path.join(folder, f"qgis_output_{iso3}_{target_year or 'unknown'}")
    adapted = adapt_settings(template, matched, iso3, target_year, crs, out_folder)

    out_json = output_path or os.path.join(folder, "settings.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(adapted, f, indent=2, default=str)
    print(f"  Wrote: {out_json}")

    report = generate_report(
        template_path, folder, iso3, target_year, crs,
        matched, missing, warnings,
    )
    out_md = os.path.splitext(out_json)[0] + "_report.md"
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  Report: {out_md}")

    return True


def main() -> int:
    args = parse_args()

    if not os.path.isfile(args.template):
        print(f"ERROR: template not found: {args.template}")
        return 1

    with open(args.template, "r", encoding="utf-8") as f:
        template = json.load(f)

    if args.batch:
        if not os.path.isdir(args.folder):
            print(f"ERROR: parent folder not found: {args.folder}")
            return 1
        subdirs = sorted([
            os.path.join(args.folder, d)
            for d in os.listdir(args.folder)
            if d.startswith("PFF_export_") and os.path.isdir(os.path.join(args.folder, d))
        ])
        if not subdirs:
            print(f"ERROR: no PFF_export_* subfolders in {args.folder}")
            return 1
        print(f"Batch mode: {len(subdirs)} folders")
        ok = 0
        for sd in subdirs:
            print(f"\n--- {os.path.basename(sd)} ---")
            if process_one(template, args.template, sd, args.year, args.crs, None):
                ok += 1
        print(f"\nDone: {ok}/{len(subdirs)} succeeded")
        return 0 if ok == len(subdirs) else 1
    else:
        if not os.path.isdir(args.folder):
            print(f"ERROR: folder not found: {args.folder}")
            return 1
        print(f"Adapting template for: {args.folder}")
        return 0 if process_one(
            template, args.template, args.folder,
            args.year, args.crs, args.output,
        ) else 1


if __name__ == "__main__":
    sys.exit(main())

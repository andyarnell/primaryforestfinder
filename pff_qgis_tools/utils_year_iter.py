"""Multi-year iteration helpers for the PFF dock.

The dock parses the year field as a comma-separated list and, when
multiple years are listed, runs the workflow once per year. Between
iterations, year-varying input paths are substituted by globbing the
same folder for the equivalent file with the year token swapped.

Convention: any input filename containing a 4-digit year token between
underscores (e.g. ``BTN_1_forest_2010_90m_16h03m.tif``) is treated as
year-varying. Inputs without a year token in the filename (DEM, slope,
protected areas) are reused unchanged across all years.

Time-hash style suffixes (``_16h03m``, ``_20h10m``) are common in the
real Bhutan dataset and vary between files even for the same input,
so substitution globs the suffix portion rather than doing a strict
text replace.
"""

import glob
import os
import re
from typing import List, Optional, Tuple


# Year tokens between word boundaries; conservative range 1990-2030.
_YEAR_TOKEN_RE = re.compile(
    r"(?<![0-9])(19[9][0-9]|20[0-3][0-9])(?![0-9])")
# Time-hash suffix: e.g. _16h03m, _20h10m, _21h56m. We replace the
# token + everything from there to the extension with a glob wildcard
# when substituting years -- the source file's time-hash for year N
# is unrelated to year N+1's time-hash.
_TIMEHASH_RE = re.compile(r"(_\d{2}h\d{2}m)(?=\.[A-Za-z]+$)")


def parse_year_list(year_str: str) -> List[str]:
    """Parse a comma-separated year string into an ordered list of
    4-digit year strings. ``"all"`` returns ``["all"]``. Empty / blank
    returns ``[]``.

    Examples:
      >>> parse_year_list("2020")
      ['2020']
      >>> parse_year_list("2010, 2020")
      ['2010', '2020']
      >>> parse_year_list("1990,2000,2010,2015,2020")
      ['1990', '2000', '2010', '2015', '2020']
      >>> parse_year_list("all")
      ['all']
      >>> parse_year_list("")
      []
    """
    if not year_str:
        return []
    s = year_str.strip()
    if not s:
        return []
    if s.lower() == "all":
        return ["all"]
    out: List[str] = []
    seen = set()
    for tok in s.replace(",", " ").split():
        tok = tok.strip()
        if not tok:
            continue
        if tok.isdigit() and len(tok) == 4:
            if tok not in seen:
                seen.add(tok)
                out.append(tok)
    return out


def find_year_token(path: str, candidate_year: Optional[str] = None) -> Optional[str]:
    """Return the year token found in the filename, or None.

    If ``candidate_year`` is supplied AND that year appears in the
    filename, prefer it (handles filenames with multiple year tokens
    like ``BTN_1_hansen_treecover2000_raw_2010_*.tif`` — pick the one
    matching the user's anchor year, not just the first one).
    """
    base = os.path.basename(path or "")
    if not base:
        return None
    matches = _YEAR_TOKEN_RE.findall(base)
    if not matches:
        return None
    if candidate_year and candidate_year in matches:
        return candidate_year
    return matches[0]


def substitute_year_in_path(path: str,
                            anchor_year: str,
                            target_year: str) -> Tuple[Optional[str], str]:
    """Substitute the anchor year token with target_year in the
    filename and return ``(resolved_path, status)``.

    ``status`` is one of:
      - ``"empty"``   — input path is None / empty (the param wasn't
                        set by the user); ``resolved_path`` is None.
                        Caller should skip silently — this is NOT a
                        missing-file condition.
      - ``"static"``  — no year token in filename; ``resolved_path``
                        is the original ``path`` unchanged.
      - ``"anchor"``  — anchor_year == target_year; ``resolved_path``
                        is the original.
      - ``"matched"`` — substitution found exactly one matching file;
                        ``resolved_path`` is that file.
      - ``"missing"`` — anchor path was set, year token was found, but
                        no target-year file exists in the same folder;
                        ``resolved_path`` is None.
      - ``"ambiguous"`` — multiple matching files; ``resolved_path``
                         is the first (lex-sorted) match.

    Substitution strategy: replace the year token with ``target_year``
    AND replace any time-hash suffix (e.g. ``_16h03m``) with ``_*``
    so the glob also matches files with different time hashes for the
    target year.
    """
    if not path:
        # "empty" distinguishes "user didn't set this param" from
        # "param set but year-N file not found". Important for the
        # vector/raster pair params (ROADS vs ROADS_RASTER, etc.) where
        # the dock fills only ONE side and leaves the other blank.
        return (None, "empty")
    if anchor_year == target_year:
        return (path, "anchor")
    base = os.path.basename(path)
    folder = os.path.dirname(path) or "."
    found_year = find_year_token(base, candidate_year=anchor_year)
    if found_year is None:
        return (path, "static")
    # Build the substitution. Replace the FIRST occurrence of the anchor
    # year token (other year-shaped tokens in the filename, e.g.
    # "treecover2000", get left alone — they're part of a different
    # name).
    new_base_str = _YEAR_TOKEN_RE.sub(
        lambda m: target_year if m.group(0) == found_year else m.group(0),
        base, count=1)
    # Replace time-hash suffix with wildcard so we glob.
    glob_base = _TIMEHASH_RE.sub("_*", new_base_str)
    # If no time-hash was present, use the substituted base directly.
    candidates = glob.glob(os.path.join(folder, glob_base))
    if not candidates and glob_base == new_base_str:
        # No time-hash; check exact match.
        exact = os.path.join(folder, new_base_str)
        if os.path.exists(exact):
            candidates = [exact]
    if not candidates:
        return (None, "missing")
    if len(candidates) == 1:
        return (candidates[0], "matched")
    return (sorted(candidates)[0], "ambiguous")


def build_year_paths(input_paths: List[Tuple[str, str]],
                     anchor_year: str,
                     target_year: str) -> dict:
    """For each (label, path) pair, resolve the target-year file.

    Returns a dict keyed by label with values
    ``{path, status, original}`` so the caller can build a per-year
    availability summary AND swap input dicts before running.
    """
    out = {}
    for label, path in input_paths:
        resolved, status = substitute_year_in_path(
            path, anchor_year, target_year)
        out[label] = {
            "path": resolved,
            "status": status,
            "original": path,
        }
    return out

"""Offline CRS suggestion helper for the PFF dock.

Given an AOI bbox and/or an ISO3 country code, return a ranked list of
projected CRS candidates pulled from pyproj's bundled EPSG database.
No internet required — pyproj ships the same data EPSG.io serves.

The dock uses this to populate a "Target CRS:" dropdown in §0 Study
Area, replacing the deprecated Auto-UTM heuristic. Top result becomes
the default; user can pick any other or fall through to a Custom EPSG
field.

Ranking: overlap-area ratio between the CRS's registered area-of-use
and the AOI bbox, plus a small boost when the CRS name contains the
country name (catches national grids whose registered area-of-use is
sometimes too generous to rank by overlap alone).
"""

from typing import List, Tuple, Optional

try:
    from pyproj.database import query_crs_info
    _HAS_PYPROJ = True
except ImportError:  # pragma: no cover — pyproj ships with QGIS via PROJ
    _HAS_PYPROJ = False

# AreaOfInterest is only used when pyproj's query_crs_info supports the
# area_of_use kwarg (pyproj >= ~3.7). Older versions (3.6.x bundled with
# QGIS 3.38) raise TypeError when passed that kwarg. We probe at first
# call and cache the result in _SUPPORTS_AOI_KWARG.
try:
    from pyproj.aoi import AreaOfInterest
    _HAS_AOI_TYPE = True
except ImportError:
    _HAS_AOI_TYPE = False
_SUPPORTS_AOI_KWARG = None  # tri-state: None (untested), True, False


# Curated ISO3 → preferred projected EPSG.
#
# Entries below have been validated against ≥3 distinct sources (epsg.io,
# spatialreference.org, ASPRS Grids-and-Datums, national mapping-agency
# pages, expertgps, gis.stackexchange). All sources had to agree on the
# UTM zone NUMBER. Where datum picks varied (national vs WGS84), we choose
# WGS84-UTM (32xxx) for global-pipeline consistency: Hansen / GLAD / WDPA /
# OSM / WorldPop all ship in WGS84, and at 30-90 m forest resolution the
# cm-level differences between current national datums and WGS84 are
# below pixel size.
#
# Methodology + cite trail logged in the validation session 2026-05-14.
# Add new entries only after running the same multi-source consensus check.
_ISO3_TO_PREFERRED_EPSG = {
    # Asia-Pacific PFF workshop set — all validated 2026-05-14.
    "LAO":  32648,  # WGS84 / UTM 48N — 4/4 sources agree, unanimous
    "THA":  32647,  # WGS84 / UTM 47N — 3 sources for 32647 + 4 sources
                    # for the older Indian 1975/UTM 47N (24047). UTM 47N
                    # consensus is unanimous (5/5).
    "VNM":  32648,  # WGS84 / UTM 48N — 3/3 sources agree on zone 48N;
                    # datum tied 3-3 between VN-2000 (EPSG:3405) and WGS84.
    "PNG":  32755,  # WGS84 / UTM 55S — 3-source consensus on zone 55;
                    # alt PNG94 (EPSG:5551) for national-datum runs.
    "BTN":  32645,  # WGS84 / UTM 45N — country straddles 90°E so 45N
                    # (84-90°E) covers the central + western half;
                    # eastern strip is in 46N. 3 sources prefer 45N.
    # Indonesia OMITTED: no single-EPSG consensus (country spans zones
    # 47-54, BIG uses 16 different TM-3 zones). User must set per-region.
}


# Minimal ISO3 → country name lookup. Used by the name-match boost. Kept
# small (~80 entries — common FRA reporting countries + commonly tested);
# unmapped ISO3 codes just skip the boost. The 20b.2 batch will replace
# this with the full 235-entry map shared with the FRA port.
_ISO3_TO_NAME = {
    "AFG": "Afghanistan", "AGO": "Angola", "ARG": "Argentina",
    "AUS": "Australia", "AUT": "Austria", "BDI": "Burundi",
    "BEL": "Belgium", "BEN": "Benin", "BFA": "Burkina Faso",
    "BGD": "Bangladesh", "BGR": "Bulgaria", "BHR": "Bahrain",
    "BLR": "Belarus", "BOL": "Bolivia", "BRA": "Brazil",
    "BRB": "Barbados", "BRN": "Brunei", "BTN": "Bhutan",
    "BWA": "Botswana", "CAF": "Central African Republic",
    "CAN": "Canada", "CHE": "Switzerland", "CHL": "Chile",
    "CHN": "China", "CIV": "Ivory Coast", "CMR": "Cameroon",
    "COD": "Congo", "COG": "Congo", "COL": "Colombia",
    "CRI": "Costa Rica", "CUB": "Cuba", "CYP": "Cyprus",
    "CZE": "Czechia", "DEU": "Germany", "DJI": "Djibouti",
    "DNK": "Denmark", "DOM": "Dominican Republic", "DZA": "Algeria",
    "ECU": "Ecuador", "EGY": "Egypt", "ERI": "Eritrea",
    "ESP": "Spain", "EST": "Estonia", "ETH": "Ethiopia",
    "FIN": "Finland", "FJI": "Fiji", "FRA": "France",
    "GAB": "Gabon", "GBR": "United Kingdom", "GEO": "Georgia",
    "GHA": "Ghana", "GIN": "Guinea", "GMB": "Gambia",
    "GNB": "Guinea-Bissau", "GNQ": "Equatorial Guinea", "GRC": "Greece",
    "GTM": "Guatemala", "GUY": "Guyana", "HND": "Honduras",
    "HRV": "Croatia", "HTI": "Haiti", "HUN": "Hungary",
    "IDN": "Indonesia", "IND": "India", "IRL": "Ireland",
    "IRN": "Iran", "IRQ": "Iraq", "ISL": "Iceland", "ISR": "Israel",
    "ITA": "Italy", "JAM": "Jamaica", "JOR": "Jordan",
    "JPN": "Japan", "KAZ": "Kazakhstan", "KEN": "Kenya",
    "KGZ": "Kyrgyzstan", "KHM": "Cambodia", "KOR": "Korea",
    "KWT": "Kuwait", "LAO": "Laos", "LBN": "Lebanon",
    "LBR": "Liberia", "LBY": "Libya", "LKA": "Sri Lanka",
    "LSO": "Lesotho", "LTU": "Lithuania", "LUX": "Luxembourg",
    "LVA": "Latvia", "MAR": "Morocco", "MDA": "Moldova",
    "MDG": "Madagascar", "MEX": "Mexico", "MKD": "Macedonia",
    "MLI": "Mali", "MMR": "Myanmar", "MNE": "Montenegro",
    "MNG": "Mongolia", "MOZ": "Mozambique", "MRT": "Mauritania",
    "MUS": "Mauritius", "MWI": "Malawi", "MYS": "Malaysia",
    "NAM": "Namibia", "NER": "Niger", "NGA": "Nigeria",
    "NIC": "Nicaragua", "NLD": "Netherlands", "NOR": "Norway",
    "NPL": "Nepal", "NZL": "New Zealand", "OMN": "Oman",
    "PAK": "Pakistan", "PAN": "Panama", "PER": "Peru",
    "PHL": "Philippines", "PNG": "Papua New Guinea", "POL": "Poland",
    "PRK": "Korea", "PRT": "Portugal", "PRY": "Paraguay",
    "QAT": "Qatar", "ROU": "Romania", "RUS": "Russia",
    "RWA": "Rwanda", "SAU": "Saudi Arabia", "SDN": "Sudan",
    "SEN": "Senegal", "SGP": "Singapore", "SLB": "Solomon Islands",
    "SLE": "Sierra Leone", "SLV": "El Salvador", "SOM": "Somalia",
    "SRB": "Serbia", "SSD": "South Sudan", "SUR": "Suriname",
    "SVK": "Slovakia", "SVN": "Slovenia", "SWE": "Sweden",
    "SWZ": "Eswatini", "SYR": "Syria", "TCD": "Chad",
    "TGO": "Togo", "THA": "Thailand", "TJK": "Tajikistan",
    "TKM": "Turkmenistan", "TLS": "Timor-Leste", "TUN": "Tunisia",
    "TUR": "Turkey", "TZA": "Tanzania", "UGA": "Uganda",
    "UKR": "Ukraine", "URY": "Uruguay", "USA": "United States",
    "UZB": "Uzbekistan", "VEN": "Venezuela", "VNM": "Vietnam",
    "YEM": "Yemen", "ZAF": "South Africa", "ZMB": "Zambia",
    "ZWE": "Zimbabwe",
}


def aoi_bbox_from_path(aoi_path: str) -> Optional[Tuple[float, float, float, float]]:
    """Return (west, south, east, north) lon/lat bbox for a vector path,
    or None if the path can't be opened. Reprojects to EPSG:4326."""
    if not aoi_path:
        return None
    try:
        from osgeo import gdal, osr
        ds = gdal.OpenEx(aoi_path, gdal.OF_VECTOR | gdal.OF_READONLY)
        if ds is None:
            return None
        layer = ds.GetLayer(0)
        if layer is None:
            ds = None
            return None
        src_srs = layer.GetSpatialRef()
        ext = layer.GetExtent()  # (minX, maxX, minY, maxY)
        ds = None
        if src_srs is None:
            return None
        # Reproject extent corners to WGS84 lon/lat.
        tgt = osr.SpatialReference()
        tgt.ImportFromEPSG(4326)
        # GDAL >= 3 axis-order quirk: force traditional lon/lat.
        try:
            tgt.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        except AttributeError:
            pass
        tx = osr.CoordinateTransformation(src_srs, tgt)
        corners = [
            (ext[0], ext[2]), (ext[1], ext[2]),
            (ext[1], ext[3]), (ext[0], ext[3]),
        ]
        lonlats = []
        for x, y in corners:
            r = tx.TransformPoint(x, y)
            lonlats.append((r[0], r[1]))
        west = min(p[0] for p in lonlats)
        east = max(p[0] for p in lonlats)
        south = min(p[1] for p in lonlats)
        north = max(p[1] for p in lonlats)
        if west >= east or south >= north:
            return None
        return (west, south, east, north)
    except Exception:
        return None


def _lookup_curated_epsg(iso3: Optional[str]):
    """If ISO3 has a curated preferred EPSG, return (code, name, reason)
    using pyproj for the human-readable name. Else None."""
    if not iso3:
        return None
    code = _ISO3_TO_PREFERRED_EPSG.get(iso3.upper())
    if not code:
        return None
    try:
        from pyproj import CRS
        crs = CRS.from_epsg(code)
        name = crs.name
    except Exception:
        name = f"EPSG:{code}"
    return (code, name,
            f"Curated default for {iso3.upper()} "
            f"(≥3-source consensus, WGS84-UTM family)")


def suggest_crses(aoi_path: Optional[str] = None,
                  iso3: Optional[str] = None,
                  max_results: int = 5) -> List[Tuple[int, str, str]]:
    """Return a ranked list of `(epsg_code, display_name, reason)` tuples
    for projected CRSes appropriate for the given AOI / country.

    Strategy:
      1. If ``iso3`` is in the curated _ISO3_TO_PREFERRED_EPSG table, use
         that as the top result (validated against ≥3 published sources).
      2. When ``aoi_path`` is set, query pyproj for projected CRSes whose
         registered area-of-use intersects the AOI bbox; rank by overlap-
         area ratio. Use as fallback / for runner-up suggestions.
      3. When ``iso3`` is set, boost CRSes whose name contains the country
         name (catches national grids that have over-broad areas-of-use).
      4. Skip deprecated CRSes.
      5. Cap at ``max_results`` (default 5).

    Returns an empty list if pyproj is not available or no candidates
    were found. The dock falls back to its existing manual CRS picker
    in that case.
    """
    if not _HAS_PYPROJ:
        return []

    # Step 1: curated lookup. Top result if ISO3 known.
    curated = _lookup_curated_epsg(iso3)

    bbox = aoi_bbox_from_path(aoi_path) if aoi_path else None
    country_name = (_ISO3_TO_NAME.get(iso3.upper())
                    if iso3 else None) or ""

    candidates = []

    if bbox is not None:
        west, south, east, north = bbox
        infos = _query_projected(west, south, east, north)
        for info in infos:
            try:
                if info.auth_name != "EPSG":
                    continue
                if info.area_of_use is None:
                    continue
                aou = info.area_of_use
                try:
                    aw, asout, ae, an = aou.bounds
                except (AttributeError, TypeError):
                    aw, asout, ae, an = aou.west, aou.south, aou.east, aou.north
                # Overlap ratio
                ow = max(0.0, min(east, ae) - max(west, aw))
                oh = max(0.0, min(north, an) - max(south, asout))
                aoi_area = (east - west) * (north - south)
                aou_area = max(
                    1e-6,
                    (ae - aw) * (an - asout))
                overlap = ow * oh
                if overlap <= 0 or aoi_area <= 0:
                    continue
                # Score = how much of the AOI is covered, penalised when
                # the CRS area-of-use is much larger than the AOI (broad
                # regional CRSes get demoted).
                aoi_coverage = overlap / aoi_area
                generosity = aou_area / max(aoi_area, 1e-6)
                score = aoi_coverage / max(1.0, generosity ** 0.3)
                # Name-match boost
                if (country_name
                        and country_name.lower() in info.name.lower()):
                    score *= 1.5
                reason = _short_reason(info, aoi_coverage, country_name)
                candidates.append(
                    (int(info.code), info.name, reason, score))
            except Exception:
                continue

    # Also do a name-match-only pass for ISO3 cases where bbox missed
    # (e.g. national grid registered with a tight area-of-use that
    # doesn't quite cover the user's AOI).
    if country_name:
        try:
            extra = query_crs_info(
                pj_types=("PROJECTED_CRS",),
                allow_deprecated=False,
            )
        except Exception:
            extra = []
        seen_codes = {c[0] for c in candidates}
        for info in extra:
            try:
                if info.auth_name != "EPSG":
                    continue
                if int(info.code) in seen_codes:
                    continue
                if country_name.lower() not in info.name.lower():
                    continue
                # Lower-priority because no bbox confirmation.
                candidates.append(
                    (int(info.code), info.name,
                     f"Name matches '{country_name}'", 0.4))
            except Exception:
                continue

    # Sort by score descending, drop score from output.
    candidates.sort(key=lambda c: c[3], reverse=True)
    seen = set()
    out = []
    # Step 1 result: curated pick always wins the top slot.
    if curated:
        out.append(curated)
        seen.add(curated[0])
    for code, name, reason, _ in candidates:
        if code in seen:
            continue
        seen.add(code)
        out.append((code, name, reason))
        if len(out) >= max_results:
            break
    return out


def _query_projected(west, south, east, north):
    """Probe pyproj's query_crs_info for area_of_use kwarg support; fall
    back to "query all PROJECTED + filter by intersection" on older
    versions (3.6.x bundled with QGIS 3.38). Returns a list of CRSInfo
    that intersect the given bbox."""
    global _SUPPORTS_AOI_KWARG
    if _SUPPORTS_AOI_KWARG is None and _HAS_AOI_TYPE:
        try:
            _ = query_crs_info(
                pj_types=("PROJECTED_CRS",),
                area_of_use=AreaOfInterest(0, 0, 1, 1),
                allow_deprecated=False,
            )
            _SUPPORTS_AOI_KWARG = True
        except TypeError:
            _SUPPORTS_AOI_KWARG = False
        except Exception:
            _SUPPORTS_AOI_KWARG = False

    if _SUPPORTS_AOI_KWARG:
        try:
            return list(query_crs_info(
                pj_types=("PROJECTED_CRS",),
                area_of_use=AreaOfInterest(
                    west_lon_degree=west,
                    south_lat_degree=south,
                    east_lon_degree=east,
                    north_lat_degree=north,
                ),
                allow_deprecated=False,
            ))
        except Exception:
            return []

    # Fallback: query all projected, filter by bbox intersection in Python.
    try:
        all_infos = query_crs_info(
            pj_types=("PROJECTED_CRS",),
            allow_deprecated=False,
        )
    except Exception:
        return []
    out = []
    for info in all_infos:
        aou = info.area_of_use
        if aou is None:
            continue
        # bounds tuple is (west, south, east, north) per pyproj.
        try:
            aw, asout, ae, an = aou.bounds
        except (AttributeError, TypeError):
            aw, asout, ae, an = aou.west, aou.south, aou.east, aou.north
        if aw >= east or ae <= west:
            continue
        if asout >= north or an <= south:
            continue
        out.append(info)
    return out


def _short_reason(info, coverage: float, country_name: str) -> str:
    parts = []
    if country_name and country_name.lower() in info.name.lower():
        parts.append(f"named for {country_name}")
    parts.append(f"covers ~{coverage * 100:.0f}% of AOI")
    return "; ".join(parts)

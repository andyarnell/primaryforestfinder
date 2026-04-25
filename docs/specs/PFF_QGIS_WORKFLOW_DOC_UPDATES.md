# PFF QGIS Workflow Docs — Suggested Updates

Issues and ambiguities found in the original specification documents
during implementation. These should be clarified so that future
implementers (human or AI) don't hit the same problems.

---

## 1. NoData vs initialisation value (HIGH PRIORITY)

**Doc:** PFF_QGIS_WORKFLOW_AI_REFERENCE.md §3

**Current text:** `NoData = 0`

**Problem:** This is ambiguous. It reads as "set the GDAL NoData flag
to 0", but 0 is a valid data value in every binary mask (0 = absence).
Setting NoData=0 causes downstream GDAL tools to skip those pixels,
breaks area statistics, and makes QGIS render them as transparent.

**Suggested fix:** Clarify that 0 is the **fill/initialisation value**,
not the NoData flag:

```
Initialisation value = 0
NoData value = None (no NoData) or 255
```

---

## 2. CRS: "reproject to forest raster CRS" vs explicit CRS parameter

**Docs:** PFF_QGIS_PROCESSING_TOOL_SPEC.md §3, PFF_QGIS_PYTHON_PSEUDOCODE.md §3

**Current text:** "Reproject all layers to forest raster CRS" /
"reproject all layers to common CRS"

**Problem:** These two statements conflict slightly. The spec says use
the forest raster's CRS; the pseudocode says "common CRS" without
specifying which. Neither mentions what to do if the forest raster is
in a geographic CRS (EPSG:4326).

**Suggested fix:** Clarify the intended behaviour:

- Option A: Always use the forest raster's CRS (validate it is
  projected first)
- Option B: Accept an explicit target CRS parameter (useful when the
  forest raster arrives in 4326 and must be reprojected)

State which option is preferred.

---

## 3. Validation: should failure stop the workflow?

**Doc:** PFF_QGIS_PROCESSING_TOOL_SPEC.md §2

**Current text:** "If validation fails the workflow should stop."

**Problem:** In a QGIS Processing tool, "stopping" can mean raising an
exception (tool fails with error) or returning a report and letting the
user decide. The spec doesn't clarify which, or whether the full
workflow runner should embed validation as a blocking gate.

**Suggested fix:** Specify:

- Should errors raise a `QgsProcessingException` (hard stop)?
- Or report errors and return, leaving the user to check the report?
- Should the full workflow tool run validation first and abort on
  failure?

---

## 4. Intermediate buffer mask outputs

**Doc:** PFF_QGIS_PROCESSING_TOOL_SPEC.md §4

**Current text lists these outputs:**
```
roads_major_buffer
roads_minor_buffer
builtup_buffer
agriculture_buffer
```

**Problem:** These are the thresholded binary buffers (e.g.
`dist_roads_major <= 1500`). The spec lists them as outputs but they
are only used momentarily to build `anthropogenic_mask`. Saving 4
extra rasters adds disk I/O for files most users won't inspect.

**Suggested fix:** Clarify whether these are:

- Required outputs (always written)
- Optional debug outputs (controlled by a "save intermediates" flag)
- Not needed (only the combined `anthropogenic_mask` matters)

---

## 5. Slope calculation: which tool does it?

**Doc:** PFF_QGIS_PROCESSING_TOOL_SPEC.md §5

**Current text:** Tool 4 (Primary Forest Finder) lists "Calculate slope"
as step 1. But Tool 2 (Prepare Datasets) outputs `dem_aligned`.

**Problem:** The pseudocode (§4) puts `compute_slope()` as a standalone
step between preparation and distance surfaces. The spec puts it inside
Tool 4. The prepare tool spec outputs `dem_aligned` not `slope`. It's
unclear whether slope should be pre-computed in preparation or computed
on-the-fly in Tool 4.

**Suggested fix:** State explicitly:

- Tool 2 aligns the DEM only (no slope)
- Tool 4 computes slope from the aligned DEM

Or move slope computation into Tool 2 and output `slope.tif`.

---

## 6. Naming inconsistency: `forest_anthro_protected` vs `forest_anthro_gentle_pa`

**Docs:**
- PFF_QGIS_WORKFLOW_AI_REFERENCE.md §9: `forest_anthro_gentle_pa`
- PFF_QGIS_PROCESSING_TOOL_SPEC.md §5: `forest_anthro_protected`
- PFF_QGIS_AUTOMATION_RECOMMENDATIONS.md §10: `forest_anthro_gentle_pa`

**Problem:** Two different names for the same layer across documents.

**Suggested fix:** Pick one and use it consistently everywhere.

---

## 7. `minimum_patch_size` — pixels or hectares?

**Doc:** PFF_QGIS_PROCESSING_TOOL_SPEC.md §6

**Current text:** `minimum_patch_size` with no unit specified.

**Problem:** `gdal:sieve` works in pixels. Users think in hectares.
The conversion depends on raster resolution (e.g. 10 ha ≈ 111 pixels
at 30 m, ≈ 10 pixels at 100 m). Without stating the unit, users will
guess wrong.

**Suggested fix:** State the unit (pixels) and provide a conversion
formula or lookup table:

```
minimum_patch_size (pixels)
Conversion: pixels = area_ha × 10000 / (resolution_m × resolution_m)
```

---

## 8. Raster alignment: `native:alignrasters` vs `gdal:warpreproject`

**Doc:** PFF_QGIS_PROCESSING_TOOL_SPEC.md §3

**Current text recommends:** `native:alignrasters`

**Problem:** `native:alignrasters` aligns multiple rasters in one call
but requires all inputs up front and has limited error reporting.
`gdal:warpreproject` with explicit extent/CRS from the reference grid
achieves the same result and is more flexible for per-layer processing.

**Suggested fix:** Either:

- Keep `native:alignrasters` as preferred and note it must be called
  after all rasters are prepared
- Or state that `gdal:warpreproject` with reference extent is an
  acceptable alternative

---

## 9. Distance surface caching — when to invalidate?

**Doc:** PFF_QGIS_AUTOMATION_RECOMMENDATIONS.md §7

**Current text:** "Compute once … Reuse them for thresholds."

**Problem:** No guidance on when cached distance surfaces become stale.
If the user changes input data (different roads layer, different AOI)
but the output folder already contains `dist_roads_major.tif`, the
cached file will be silently reused with wrong data.

**Suggested fix:** Add a note:

```
Cache is valid only while the input rasters are unchanged.
If input data or AOI changes, delete the distances/ folder
or use a new output folder.
```

---

## 10. Dataset dictionaries (Recommendations §5) not reflected in spec

**Doc:** PFF_QGIS_AUTOMATION_RECOMMENDATIONS.md §5

**Current text suggests:**
```python
anthropogenic_layers = {
    roads_major: 1500,
    roads_minor: 1000,
    builtup: 2000,
    agriculture: 1000
}
```

**Problem:** This pattern implies a generic loop over layer/threshold
pairs, but the spec (Tool 3) lists each layer as a separate named
parameter. These are two different design approaches — the spec wins
but the recommendations doc creates ambiguity.

**Suggested fix:** Align the recommendations doc to match the spec's
explicit-parameter approach, or note that the dictionary is an internal
implementation detail only.

---

## Summary

| # | Issue | Priority |
|---|-------|----------|
| 1 | NoData=0 ambiguity | High |
| 2 | CRS source (forest vs explicit) | Medium |
| 3 | Validation failure behaviour | Medium |
| 4 | Buffer mask intermediates required? | Low |
| 5 | Slope: Tool 2 or Tool 4? | Low |
| 6 | Naming inconsistency | Low |
| 7 | Patch size units | Medium |
| 8 | Alignment algorithm preference | Low |
| 9 | Cache invalidation guidance | Medium |
| 10 | Dictionary pattern vs named params | Low |

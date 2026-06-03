# Known Issues — PFF QGIS Plugin

Active list of bugs / gotchas with workarounds. Severity reflects workshop / user impact, not code difficulty.

---

## 🟡 §5 — Per-zone GPKG (`*_05b_area_statistics_by_zone.gpkg`) fails on re-run

**Symptom:** Running the workflow into the same output folder twice produces a scary error in the log:

> *Feature could not be written to ...05b_area_statistics_by_zone.gpkg: Feature creation error (OGR error: failed to execute insert : UNIQUE constraint failed...)*

**Cause:** `join_stats_to_vector()` ([`pff_qgis_tools/algorithms/zonal_statistics.py:267`](../pff_qgis_tools/algorithms/zonal_statistics.py)) calls `native:reprojectlayer` with an `output_path` that already exists on disk. Instead of overwriting cleanly, GPKG attempts to append features with the same FIDs → UNIQUE constraint failure.

**Impact:** The per-zone *mappable* GPKG (used for choropleth styling) ends up stale or incomplete. **Everything else is fine:**

| Output | Affected? |
|---|---|
| `05a_area_statistics.csv` (headline numbers, per-zone in CSV form) | ❌ Written before the GPKG step — unaffected |
| Primary forest raster | ❌ |
| Forest / NRF / other rasters | ❌ |
| Vector outputs (`06a`, `06c`, `06d`) | ❌ |
| Run metadata JSON | ❌ |

**Workaround:** Delete the existing `*_05b_area_statistics_by_zone.gpkg` from the output folder before re-running, or use a fresh output folder.

**Workshop guidance:** participants who follow Step 6 ("Pick a fresh output folder") won't hit this. If anyone re-runs over a previous folder, point them at the workaround — the CSV result is still correct.

**Status:** Patch deferred. Will land as a small standalone fix off `main`. One-line change: delete `output_path` before the reprojectlayer call, or pass `OVERWRITE_OUTPUT_LAYER: True`.

---

## 🟡 Slow runs when forest input is fine resolution (e.g. 30m)

**Symptom:** A user supplies their own forest raster at 30m (or finer) and the workflow takes much longer than the 2–5 minutes typical of the 90m GEE batch exports. Distance surfaces and output rasters scale with pixel count — a 30m forest raster contains ~9× the pixels of a 90m one, so runs become 5–10× slower (or more on large countries).

**Why:** The forest raster defines the **reference grid** ([`full_workflow.py:744`](../pff_qgis_tools/algorithms/full_workflow.py)). All other inputs (roads, built-up, agriculture, DEM, etc.) are aligned to that grid. So if forest is at 30m, everything in the pipeline runs at 30m.

**Workaround — resample ONLY the forest raster to 90m. Everything else aligns to it automatically.**

The forest raster defines the reference grid; the plugin's prepare stage snaps every other input (roads, built-up, agriculture, DEM, slope, protected areas, OLTC, planted) to that grid using `gdal:warpreproject`. So you only need to resample one file:

- ✅ Resample forest input → 90m, save as new file
- ✅ Feed the 90m forest as §2 input
- ❌ No need to resample roads / DEM / built-up / agriculture / anything else — leave them as-is

Most workshop analyses don't gain much from sub-90m primary forest mapping — the human-influence buffers are ~1 km wide anyway.

### Option 1 — QGIS Processing Toolbox

1. Open **Raster → Projections → Warp (reproject)**
2. Input: your fine-resolution forest raster
3. Resampling method: **Mode** (best for binary categorical data)
4. Output file resolution: **90** (in target CRS metre units)
5. Run → use the output as the §2 Tree cover / forest raster

### Option 2 — Command line (GDAL)

```bash
gdalwarp -tr 90 90 -r mode -tap-out-off input_30m.tif output_90m.tif
```

⚠️ **Do NOT use `-tap`** in gdalwarp — it shifts the pixel grid origin and the plugin's alignment logic relies on a stable grid. Just set `-tr 90 90` without `-tap`.

### Option 3 — Accept the slowness

If 30m is genuinely needed (e.g. detecting small patches < 90m), expect run times in the 30+ minute range for medium countries and considerably more for large ones. PNG-sized countries at 30m may exceed an hour.

**Impact:** Long wait, but results are still correct. Workshop time budget is the main constraint.

**Status:** No code fix planned — supporting native 30m without major refactor would require a coarser internal grid for distance surfaces. Documentation + facilitator guidance is the current approach.

---

## 🟢 Planned: in-plugin reproject to coarser resolution (for quick runs)

**Background:** today the plugin uses the forest raster's native resolution as the reference grid for everything else ([`full_workflow.py:744`](../pff_qgis_tools/algorithms/full_workflow.py)). If a user supplies their own 30m forest raster, the whole pipeline runs at 30m — 5–10× slower than the 90m GEE batch exports. Current workaround documented in this file: resample the forest raster externally (`gdalwarp -tr 90 90 -r mode ...`) before loading.

**Proposed:** add an optional **Target resolution** field in §2 Tree Cover. When set, the plugin resamples the forest raster as Stage 1's first step; all other inputs then align to this coarser grid automatically.

### UI

Inside the "Tree-cover input definition" group box, just below the input raster picker:

```
Target resolution (m):  [    ] (blank = use native)
```

- Empty / 0 → current behaviour (use native)
- > 0 → resample forest raster to this resolution before becoming the reference grid

### Algorithm changes

1. **New param** `FW.TARGET_RESOLUTION_OVERRIDE` (float, default 0 = "off").
2. **Stage 1 prepare step** (in `prepare_inputs.py` or near the forest reproject in `full_workflow.py`): if override > native, resample with `gdalwarp -tr X X -r mode` (binary mask) before reproject. If override <= native, skip (don't upsample — warn the user).
3. **Reference grid** then comes from the resampled forest, so DEM / built-up / agriculture / OLTC / planted all align to the coarsened grid automatically. No other code changes.

### Resampling method

- **Mode** for binary 0/1 rasters (current forest input convention).
- **Nearest** as fallback for older GDAL builds.
- Continuous rasters not applicable — forest is binary.

### Edge cases

- **Override = native** → no-op, log "target equals native, skipping resample".
- **Override < native** → reject with clear error ("won't upsample low-res input").
- **Override much coarser than reasonable** (e.g. 5000 m) → run anyway but warn.
- **Multi-year mode** → each year's forest input gets resampled separately with the same target resolution.

### Performance impact

For a Thailand 30m input at default settings:
- 30m native → ~10 min total runtime (per workshop log)
- 90m via this feature → ~2 min total (estimated, matches GEE-export experience)

### Backward compat

New param defaults to 0 in saved settings. Old settings.json files don't have it → 0 → current behaviour preserved.

### Effort

~30–45 min. Single Stage 1 addition + one new dock widget + tooltip + sanity checks. Low risk because the resampling produces a standard binary raster that the existing pipeline already handles.

### Why this matters

The current workaround (external gdalwarp) requires the user to know how to use GDAL + know the workflow's "Mode resampling is best for binary" detail. Most workshop participants will just feed in their 30m data and wait the extra time. This feature gives them an in-plugin one-line knob.

---

## ✅ Resolved (v0.16.0-beta.13): Dynamic forest layers inflated later-year primary forest

**Symptom (pre-beta.13):** In multi-year runs using a dynamic tree-cover input (e.g. GLAD annual forest, Hansen treecover with year-specific gain), candidate primary forest could appear to **grow** between baseline and later years — e.g. Indonesia / Kalimantan showed more "primary" pixels in 2020 than in 2000. Visually striking; methodologically misleading because the FRA definition of primary forest does not allow new primary pixels to appear.

**Cause:** Each year iteration in `_run_multi_year()` ran fully independently. The forest raster for year N was substituted by filename token and fed to the algorithm with no reference to year-0's forest extent. Any pixel that GLAD newly classified as forest in year N, if it happened to fall in a low-anthropogenic-pressure zone, became candidate primary in year N even though it was not forest in year 0.

**Fix:**
1. Multi-year iteration now sorts the year list chronologically (earliest first) regardless of input order.
2. After the earliest year's run, the dock captures the path to its `02c_forest.tif` output.
3. For each subsequent year, the dock passes that path as a new (hidden) `BASELINE_FOREST_MASK` parameter.
4. The algorithm ANDs the year-N forest array with the baseline-year forest mask before Tier 1/2/3 derivation. Newly-detected forest pixels are dropped from the primary candidate.

**What this allows / disallows:**
- A pixel that was forest in year 0 but later got cut → can still drop OUT of primary in year N (correct).
- A pixel that was non-primary forest in year 0 (e.g. inside a 1 km road buffer) → can BECOME primary in year N if the buffer no longer reaches it (correct — "recovery" within stable forest is allowed).
- A pixel that was NOT forest in year 0 but is forest in year N (GLAD's "new forest") → cannot become primary in year N (the new behaviour).

**User-visible cues in the log:**
- `Iteration order (chronological): 2000, 2010, 2020`
- `Captured baseline forest mask for year 2000: BTN_2000_qgis_02c_forest.tif`
- `Constrained forest to baseline mask (...): 1,234,567 -> 1,180,432 forest pixels (54,135 newly-detected pixels excluded).`

**Opt-out:** None in the UI yet. If a user genuinely wants each year's primary forest to reflect a refreshed baseline (e.g. methodology revision rather than ecological continuity), run each year as a separate single-year run with a fresh output folder. A future release can add a §4 Refine Output checkbox if demand surfaces.

**Affected versions:** Pre-`beta.13` multi-year runs with dynamic forest layers. Single-year runs were never affected.

---

## ✅ Resolved (v0.16.0-beta.11): NoData=0 silently zeroed primary forest output

**Symptom (pre-beta.11):** Some runs produced empty stats — `forest: 0.0 kha`, `primary_forest: 0.0 kha` — even with correct inputs. GDAL log showed:

> *Warning 1: Value 0 in the source dataset has been changed to 1 in the destination dataset to avoid being treated as NoData.*

**Cause:** `clip_raster_by_mask()` in `pff_qgis_tools/utils.py` passed `NODATA=0` to GDAL's clip step. The binary driver rasters (built-up, agriculture) legitimately use 0 for "absent". Some GDAL builds (notably macOS's bundled GDAL) defensively flipped source 0-pixels to 1 in the destination to disambiguate them from NoData — silently inverting the entire mask. Whole country then read as "built-up" or "agriculture", the 1 km human-influence buffer covered everything, no primary forest survived.

This bug was present in `pff_qgis_tools/utils.py` from at least plugin v0.8.40 (months before the workshop). It only manifested on GDAL versions that took the "flip 0→1" path. Windows-bundled GDAL typically did NOT flip, so the bug went unnoticed in dev.

**Fix:** `NODATA` changed from `0` to `255` (outside the binary 0/1 data range, so source values round-trip cleanly).

**Affected versions:** ALL plugin versions before `0.16.0-beta.11`. If you have a pre-beta.11 zip installed, update to beta.12+ via the [`dist/`](../dist/) folder.

**How to detect if you were hit:** look for the "Value 0 ... changed to 1" warning in your run log, or `primary_forest: 0.0 kha` in the stats with non-empty input data. Either is a red flag.

---

## 🟢 Planned: separate "Run preprocessing" step (replace dangerous cache toggle)

**Background:** the dock has a "Reuse preprocessing cache" toggle in Config that, when on, skips the Stage 1 prepare step and uses already-prepared rasters from the intermediates folder. Workshop feedback (2026-05-12) flagged this as **very dangerous**: cached files can carry latent bugs (e.g. the NoData=0 mask-flipping fixed in v0.16.0-beta.11) and silently produce wrong stats long after the source fix lands. The reuse toggle's default was flipped to OFF in beta.11 to mitigate this.

**Better approach (planned):** turn the cache reuse into an **explicit "Run preprocessing" step**:
- User clicks **Preprocess inputs** once (Stage 1 only).
- Plugin writes the prepared rasters to a known location with a version stamp.
- User can then **Run analysis only** as many times as they want with different thresholds — the prepared rasters are reused explicitly, NOT silently.
- Plugin checks the version stamp on the cached files; if from an older plugin version, refuses to reuse and forces a fresh preprocess.

**Why this is better than a checkbox:**
- Explicit user action — no accidental reuse.
- Version-stamped cache — bug fixes invalidate stale caches automatically.
- Speeds up workflow for power users (only the analysis stages re-run on threshold changes).

**Effort:** ~half a day. New Processing algorithm + dock button + version-stamp logic. Post-workshop work.

---

## ℹ️ Conventions for this page

- 🔴 Critical — blocks core workflow or corrupts headline result
- 🟡 Moderate — annoying / confusing but doesn't corrupt the CSV / primary forest raster
- 🟢 Minor — cosmetic / log noise

When an issue is patched, move it under a **Resolved** heading with the fixing commit / version.

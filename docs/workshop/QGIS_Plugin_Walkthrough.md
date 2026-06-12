# PFF — Have a Go (updated 2026-05-10)

Quick run-through to show you the tool and let you try it on a country.

**Time:** about 90 min.

---

## 1. Install the plugin

1. Download `pff_qgis_tools.zip` from the shared drive to your local disk.
2. QGIS (v3.10+): **Plugins → Manage and Install Plugins → Install from ZIP** → pick the downloaded zip.
3. Restart QGIS.
4. A **Primary Forest Finder** dock panel should appear on the right side of the QGIS window. If not, go to **View → Panels → Primary Forest Finder** to toggle it on.
5. Confirm the version: the dock shows a version banner at the top — should read `v0.15.1` or higher.

**Replacing an older install:** Install-from-ZIP overwrites in place, no extra steps needed. If you hit any odd behaviour that looks like an old version lingering, uninstall first (Plugins → Manage → Installed → Primary Forest Finder → Uninstall) then install the new zip.

---

## 2. Get your data

Download your country's folder from the shared drive to your local disk (don't run the plugin directly against the online folder — too slow and unstable). If it is in a zip file, unzip it.

**One folder per country, but it contains two kinds of file mixed together:**

- **Plugin inputs** (files you'll wire into the plugin in Step 4) — forest, built-up (small + large), agriculture, planted forest, DEM (or slope).
- **GEE reference outputs** (for comparing against the plugin's results later — NOT fed into the plugin) — `*_03c_pre_refinement_primary_forest_*.tif`, `*_04a_primary_forest_*.tif`.
- **Not included in the batch export** — roads, protected areas, and AOI vector are not in the GEE batch export (they update independently). These need to be prepared separately — ask the facilitator.

The filename step prefixes tell them apart: `_02a/02b/02d_` and `_03a/03b_` = inputs; `_03c_` and `_04a_` = reference outputs. Full breakdown table in Step 3.

GEE exports are in **EPSG:4326 (geographic, lat/lon)** — they're not projected. The plugin needs a projected CRS (metres) for its buffer / distance calculations, so you'll pick one in Step 4.

---

## 3. Load in QGIS and have a look

Add the rasters + AOI vector, zoom to AOI. Click through the layers briefly — get a sense of the forest distribution, where the roads and protected areas are, whether the planted forest layer looks sensible for your country.

**Note — the GEE bundle contains two kinds of file.** Most are **inputs** you'll feed into the plugin. A couple are GEE's own **reference outputs** included for comparison (the same thing the plugin will compute, but done in GEE) — you do NOT feed these into the plugin:

| File pattern | Purpose |
|---|---|
| `*_02a_tree_cover_binary_*.tif` | **Plugin input** — tree cover (binary; GLAD LULC ≥ 5 m height, before FRA filtering) |
| `*_03a_builtup_small_*.tif`, `*_03a_builtup_large_*.tif` | **Plugin input** — built-up areas |
| `*_03a_agriculture_*.tif` | **Plugin input** — agriculture |
| `*_02d_planted_forest_*.tif` | **Plugin input** — planted forest |
| `*_03b_protection_natural_dem_*.tif` | **Plugin input** — DEM |
| `*_03b_protection_natural_slope_*.tif` | Info only — slope (generated from DEM; not normally needed as input) |
| `*_02a_glad_tree_height_raw_*.tif` | Info only — continuous tree height in metres |
| `*_02b_other_land_with_tree_cover_*.tif` | Info only — OLWTC layer (oil palm, tree crops, urban tree cover) |
| `*_03c_pre_refinement_primary_forest_*.tif` | **GEE reference output** — compare against the plugin's own pre-refinement result |
| `*_04a_primary_forest_*.tif` | **GEE reference output** — compare against the plugin's own primary forest result |

**Not in the batch export (prepared separately):** roads (`*_03a_roads_*.tif`), protected areas (`*_03b_protection_legal_*.tif`), AOI vector (`*_00a_aoi_*.shp`). Ask the facilitator for these files.

**Optional tip — organising data in the Layers tab (in QGIS)** — make two groups to keep these straight:

- `GEE inputs` — the input files + AOI
- `GEE reference outputs` — the `_03c_pre_refinement_` and `_04a_primary_forest_`

Later in Step 5 you'd add a third group (`PFF outputs`) for the plugin's own results. Side-by-side comparison of `GEE reference` vs `PFF outputs` is the interesting content for the debrief.

**Moving layers in / out of groups (in the Layers tab):** drag-and-drop works but is fiddly with many layers. The reliable way: right-click a layer (or multi-select with Ctrl/Shift first) → **Move to Group → \<group name\>**. Same menu has **Move Out of Group** to lift a layer back to the top level. Create the empty group first (right-click in the Layers tab → **Add Group**), then move layers in.

---

## 4. Run it

The plugin runs from a **dock panel** on the right side of the QGIS window (not the Processing Toolbox). The dock has collapsible sections numbered §0 through §6.

Fill in the sections:

**§0 Study Area:**

| Field | What to enter |
|---|---|
| AOI | `*_00a_aoi_*.shp` (prepared separately — not in batch export) |
| ISO3 | Your country's 3-letter ISO code (e.g. `BTN` for Bhutan, `KEN` for Kenya) |
| CRS | The dock suggests projected CRS options based on your ISO3 — pick one from the dropdown. For compact countries the first suggestion is usually fine. For archipelagos, check with the facilitator. |

**§1 Time Period:**

| Field | What to enter |
|---|---|
| Year | The analysis year (e.g. `2000`) |

**§2 Tree Cover:**

| Field | File |
|---|---|
| Tree cover / forest raster | `*_02a_tree_cover_binary_*.tif` |

The input category dropdown should be set to **"Tree cover"** (this is the raw GLAD tree cover ≥ 5 m, before FRA filtering — the plugin handles OLWTC exclusion itself).

**§3 Human Influence:**

| Slot | File |
|---|---|
| Roads raster | `*_03a_roads_*.tif` (prepared separately — not in batch export) |
| Built-up small | `*_03a_builtup_small_*.tif` |
| Built-up large | `*_03a_builtup_large_*.tif` |
| Agriculture raster | `*_03a_agriculture_*.tif` |
| Protected areas raster | `*_03b_protection_legal_*.tif` (prepared separately — not in batch export) |
| DEM | `*_03b_protection_natural_dem_*.tif` (the `_dem_` file, not slope) |

**§4 Refine Output:** Leave defaults (neighbourhood density filter). Optionally enable minimum patch size filter.

**§5 Area Statistics:** Tick **Run zonal statistics** and point it at the AOI.

**§6 Outputs:** Pick a fresh output folder. Leave the save-list defaults.

Click **Run** at the bottom of the dock.

Run times: Bhutan near-instant, most countries 2–5 min, PNG ~6 min.

---

## 5. Look at the results

The plugin auto-loads key outputs into the Layers panel with colour symbology applied (green for primary forest, etc.) — no manual symbology fix needed.

Output files follow the naming pattern `<ISO3>_<year>_qgis_<step>_<name>.tif`, e.g. `BTN_2020_qgis_04a_primary_forest.tif`.

Key outputs:

- `*_04a_primary_forest.tif` — what the tool called primary forest (the headline result)
- `*_03c_pre_refinement_primary_forest.tif` — forest outside human-influence buffers + steep-slope and protected exclusions, before the Refine Output filter
- `*_02e_naturally_regenerating_forest.tif` — forest minus planted forest (FRA naturally regenerating forest), if planted forest exclusion was on
- `*_04e_anthropogenic_mask.tif` — combined buffered disturbance zone
- `*_03d_combined_coded_raster.tif` — optional. One raster with codes 0/1/2/3 = none/forest/pre-refinement/primary. Easiest single layer for seeing the tier cascade.
- `*_05a_area_statistics.csv` — `primary_forest_kha` column is the headline number
- `*_00_run_metadata.json` — records the parameters you used for this run

**Optional tip — organising plugin outputs in the Layers tab (in QGIS):** if you set up the groups in Step 3, add a third one here (right-click in the Layers tab → **Add Group** → rename `PFF outputs`) and move the plugin results into it via right-click → **Move to Group → PFF outputs**. The Layers tab now looks like:

```
▸ PFF outputs              (the plugin's primary_forest, pre_refinement, etc.)
▸ GEE reference outputs    (GEE's pre_refinement + primary — same concept, different engine)
▸ GEE inputs                (the rasters you fed in)
```

Tidy, and the side-by-side `PFF outputs` vs `GEE reference outputs` is exactly what the debrief is about. Flick visibility on/off to see where they disagree.

---

## 6. Optional: compare to GEE

Open pff_4.js in GEE, select your country, click **Show Area Statistics**. Jot the GEE number and the plugin's `primary_forest_kha` side-by-side on the shared board.

**Scale / resolution matters.** The on-the-fly stats compute at the scale set by the **Resolution slider** in that same panel, not the native forest resolution. Coarser scale = faster but less accurate; native scale can time out for large countries. Click the `i` button next to Show Area Statistics for GEE's own note on this.

- **Quick look:** leave the slider at its default — fine for a sanity check against the plugin number.
- **Accurate number:** drag slider toward native resolution. If on-the-fly times out, use **Export Statistics to Drive** (same section) — larger memory / time budget, result lands as a CSV in your Drive.
- When comparing to the plugin, both the plugin and GEE should be at broadly comparable scales — don't compare a 500 m GEE estimate to a 30 m plugin run and read the difference as a methodological gap.

---

## 7. Run a second time period (2020)

A key question: how much primary forest has your country lost between 2000 and 2020?

1. **You already have a year-2000 run** from Step 4. Note the `primary_forest_kha` number from the area statistics CSV (or the §5 panel output).
2. **Switch the input files to year 2020.** In §2 Tree Cover, swap in the `*_2020_*` tree-cover-binary raster. In §3, swap the `*_2020_*` built-up, agriculture, and planted forest files. DEM, slope, roads, and protected areas are the same for both years.
3. **Change the year** in §1 Time Period to `2020`.
4. **Pick a different output folder** (or rename the first run's folder) so the two sets of results don't overwrite each other.
5. **Click Run.**

---

## 8. Compare 2000 vs 2020 — the trend

Open both area statistics CSVs side by side. Key columns to compare:

- `primary_forest_kha` — the headline number. How much changed?
- `pre_refinement_forest_kha` — change before the connectivity filter
- `forest_kha` — total tree cover change (not just primary)

**Compare against FRA:** Open pff_4.js in GEE, select your country, and click **Show Area Statistics** for both years. Jot the GEE numbers alongside the plugin's numbers and your country's official FRA figures on the shared board. Three columns: **FRA official | GEE | QGIS plugin**.

**Discussion points for the debrief:**
- Is the direction and magnitude of change what you'd expect for your country?
- Which driver appears biggest — agriculture expansion, settlement growth, or road building?
- Are there areas the tool marks as "lost" that you know are still forested? (Commission errors in the input data.)
- How does the 2000 → 2020 difference compare to official FRA reporting for your country?
- Where do the GEE and plugin numbers diverge? (Resolution, CRS, and edge handling all play a role.)

---

## 9. Create validation sample points for CEO

The plugin can generate a set of random sample points inside your primary forest and other-forest areas. These are designed for upload to Collect Earth Online (CEO) for visual interpretation at a later date — you don't need to do the interpretation now.

**Use the results from your most recent run (the 2020 run from Step 7).**

1. In the dock panel, expand **§7 Validation sampling (experimental)**.
2. Set the fields as follows:

| Field | Setting |
|---|---|
| Source | **Pick a file/layer** — point it at the `*_06d_*_nested_dissolved.*` file from your 2020 output folder |
| Class field | `level` (auto-detected from PFF outputs) |
| Class values | Primary: `2`, Other: `1` (defaults) |
| Plots from | All forest (primary + other forest) |
| Sampling | Tick **Set counts per class (stratified)** |
| Plots per class | Primary: `50`, Other: `50` |
| Plot boundary | **Simple (CEO draws default)** |

3. Click the **Generate** button inside the Validation sampling section.

The plugin produces two output files in a `ceo/` subfolder of your output directory:

- **Plots layer** — 100 point locations (50 in primary forest, 50 in other forest), each tagged with its stratum
- **Sample layer** — the same points formatted for CEO upload (with plot ID, lat/lon, and class label columns)

**What to do with these later:** upload the sample layer to a CEO project. Each point becomes a plot that an interpreter visits in high-resolution imagery to confirm whether the PFF classification is correct. This is how you measure the tool's accuracy — but the interpretation itself is a separate task for after the workshop.

**Tip:** if you want reproducible results (same points each time), type a seed number into the Advanced → Random seed box before generating.

---

## 10. Have more time? Try one of these

- **Change a threshold and rerun** (e.g. roads buffer 1000 → 2000 m). See the "Fast re-runs" note below.
- **Try a sub-national run** — tick "Sub-national AOI?" in §0, type an area name (e.g. `coastal_zone`), and supply a sub-national AOI vector.
- **In GEE, try a different forest dataset** (EUFO 2020).

---

## Fast re-runs — use the prepared/ folder

Each input goes through three stages in order: **Reproject → Clip to AOI → Align to forest grid**. Only the final aligned file is kept, as `intermediates/prepared/{name}.tif`.

**For a fast re-run, point the slots at these prepared files** and untick "Reuse preprocessing cache":

| Plugin input slot | File to pick |
|---|---|
| Tree cover / forest raster | `intermediates/prepared/forest.tif` |
| Roads raster | `intermediates/prepared/roads.tif` |
| Built-up small / large | `intermediates/prepared/builtup_small.tif`, `builtup_large.tif` |
| Agriculture raster | `intermediates/prepared/agriculture.tif` |
| Planted forest raster | `intermediates/prepared/planted_forest.tif` |
| Protected areas raster | `intermediates/prepared/protected.tif` |
| DEM | `intermediates/prepared/dem.tif` |
| Slope (if DEM-derived or supplied) | `intermediates/prepared/slope.tif` |
| AOI | **leave empty** — see below |

Alternatively, just leave "Reuse preprocessing cache" ticked (on by default) and "Reuse cached distance surfaces" ticked — the plugin will detect that prepared files already exist and skip straight to the analysis stages.

**Tip: leave the AOI field empty for re-runs.** `forest.tif` you're pointing at is already AOI-clipped, and the other prepared rasters are too. The plugin skips the entire AOI prep stage (reproject + buffer + rasterize the country vector) when no AOI is supplied — a real speedup for re-runs.

---

## Things that might trip you up

- **DEM vs Slope slots** — the `_dem_` file goes in the DEM slot (the plugin derives slope from DEM internally)
- **Input category dropdown** — make sure you select one (it starts on "— Select one —"); for the batch-exported `02a_tree_cover_binary` file, pick "Tree cover"
- **Cancel** — takes a minute to actually stop
- **CRS** — the dock suggests CRS options once you type an ISO3 code; if none appear, type an EPSG code directly (e.g. `EPSG:32645`)

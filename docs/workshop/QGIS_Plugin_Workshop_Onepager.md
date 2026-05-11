# PFF QGIS Plugin — Workshop One-Pager

**Hands-on testing · plugin v0.16.0-beta.10**

## The plugin sections (dock panel)

```
§0 Study area              ← country / sub-national area, CRS
§1 Time period             ← analysis year(s)
§2 Tree cover              ← forest raster + optional OLTC / planted-forest
§3 Human influence         ← roads, built-up, agriculture buffers
                              + Buffer Exceptions (slope, protected areas)
§4 Refine output           ← spatial cleanup of small / thin patches
§5 Area statistics         ← per-class and per-zone areas
§6 Outputs                 ← output folder + save list + add-to-map
§7 Validation              ← vectorise + validation sampling (WIP)
Config                     ← save/load settings + performance options
```

## Run

1. Open the **Primary Forest Finder** dock (toolbar icon or **Plugins → Primary Forest Finder → Show PFF Panel**).
2. Set the output folder in **§6 Outputs** — pick a fresh folder each run.
3. Fill in §0 → §4 (national or global inputs).
4. Click **Run** at the bottom of the dock.
5. Watch the Processing log for progress and errors.

## Add-to-map and styling

- Tick **Add layers to map** in **§6** to push outputs onto the canvas after the run.
- Visibility, transparency and styling are controlled in the standard QGIS **Layers panel**.

---

## Known issues in this version

| Section | Issue | Workaround |
|---|---|---|
| §5 Area statistics | Per-zone GPKG (`*_05b_area_statistics_by_zone.gpkg`) fails on re-run into the same folder | Use a fresh output folder, or delete that GPKG before re-running. CSV stats and rasters are unaffected. |
| Run speed | Runs at fine resolution (e.g. 30 m) are 5–10× slower than 90 m | Resample only the **forest raster** to 90 m before feeding it to §2 (use *Warp (reproject)* with resampling method **Mode**). Everything else aligns to it automatically. See *Coarsening the forest raster* below. |
| §7 Validation | Vectorise + validation sampling is **work in progress**, mostly produced for this workshop's validation session. Schema and outputs may change between plugin versions. | Treat outputs as draft. Tested with Bhutan data. |

For the full list see [`known_issues.md`](known_issues.md).

---

## Coarsening the forest raster (optional)

If your forest raster is at 30 m, coarsen it to 90 m before §2 to speed up the run. Find the tool via **Processing Toolbox** (Ctrl+Alt+T) → search **`warp`** → **Warp (reproject)** (under GDAL → Raster projections); or via the menu **Raster → Projections → Warp (Reproject)…**

Settings:
- **Output file resolution in target georeferenced units:** `90`
- **Resampling method:** see below
- Leave any "target-aligned pixels" / `-tap` option **off** — it shifts the pixel grid and breaks alignment downstream.

### Resampling method — what to pick

| Method | Behaviour | Use when |
|---|---|---|
| **Mode** | Majority vote in the input block — output pixel = most common class | **Default for forest / binary / categorical** masks |
| **Nearest neighbour** | Single nearest input pixel | Fastest; can be biased |
| **Average** | Fractional value (e.g. 0.55 = 55 % forest) | If you want a forest *fraction* layer |
| **Min** | Output forest only if *all* sub-pixels are forest | Most conservative — strict forest |
| **Max** | Output forest if *any* sub-pixel is forest | Most permissive |
| **Bilinear / Cubic** | Distance-weighted average | Continuous data only (DEM / slope); **don't use on binary** |

For a standard run, **Mode** is the right pick.

---

## Data and install

| Resource | Link |
|---|---|
| **Country test data** (all workshop countries — pick your own) | [Google Drive folder](https://drive.google.com/drive/folders/1PCuTzOISfQ6uArx6HIRruSBNf3vKe6Do?usp=drive_link) |
| **Plugin install zip** — latest version (quick fixes may land here during the workshop) | [dist folder on GitHub](https://github.com/andyarnell/primaryforestfinder/tree/main/dist) — grab the highest `pff_qgis_tools_0.16.0-betaN.zip` |

### Install steps

1. From the [dist folder](https://github.com/andyarnell/primaryforestfinder/tree/main/dist), click the highest-numbered zip → **Download raw file**.
2. **QGIS → Plugins → Manage and Install Plugins… → Install from ZIP** → browse to the zip → **Install Plugin**.
3. Start the plugin: **Plugins → Primary Forest Finder → Show PFF Panel** (or click the PFF toolbar icon). The dock appears on the right; version is shown at the top.

> **Quick fixes:** if a new zip lands mid-workshop, install over the top, then **Plugin Reloader → Reload** (no QGIS restart).

---

## Feedback — please fill in

### Bugs / glitches
| Section | What you did | What went wrong |
|---|---|---|
|   |   |   |
|   |   |   |
|   |   |   |
|   |   |   |

### Confusing wording, layout, or missing instructions
- 
- 
- 
- 

### Features you looked for and couldn't find
- 
- 
- 
- 

### National data you'd most want to plug in
| Section | National data |
|---|---|
|   |   |
|   |   |
|   |   |

### Overall
- One thing that worked well: 
- One thing to change first: 
- Likelihood you'd use the plugin for national reporting (1 – 5): __

**Name / country (optional):** ____________________

---

*QGIS one-pager · 2026-05-12 · companion to GEE_App_Workshop_Onepager.md*

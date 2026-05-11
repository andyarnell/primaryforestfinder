# PFF QGIS Plugin — Workshop One-Pager

**Hands-on testing · plugin v0.16.0-beta.1**

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

1. Open the **Primary Forest Finder** dock (Plugins → Primary Forest Finder).
2. Set the output folder in **§6 Outputs** — pick a fresh folder each run.
3. Fill in §0 → §4 (national or global inputs).
4. Click **Run** at the bottom of the dock.
5. Watch the Processing log for progress and errors.

## Add-to-map and styling

- Tick **Add layers to map** in **§6** to push outputs onto the canvas after the run.
- Visibility, transparency and styling are controlled in the standard QGIS **Layers panel** on the left of the QGIS window.

---

## Known issues in this version

| Section | Issue | Workaround |
|---|---|---|
| §5 Area statistics | Per-zone GPKG (`*_05b_area_statistics_by_zone.gpkg`) fails on re-run into the same folder | Use a fresh output folder, or delete that GPKG before re-running. CSV stats and rasters are unaffected. |
| Run speed | Runs at fine resolution (e.g. 30 m) are 5–10× slower than 90 m | Resample only the **forest raster** to 90 m before feeding it to §2 (everything else aligns to it). Don't use `-tap` in gdalwarp. |
| §7 Validation | Vectorise + validation sampling is **work in progress**, mostly produced for this workshop's validation session. Schema and outputs may change between plugin versions. | Treat outputs as draft. Tested with Bhutan data. |

For the full list see [`known_issues.md`](known_issues.md).

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

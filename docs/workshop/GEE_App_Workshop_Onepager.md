# PFF GEE App — Workshop One-Pager

**Hands-on testing · v4.15.7-beta.1** · open the browser app: [primary-forest-finder](https://ee-andyarnellgee.projects.earthengine.app/view/primary-forest-finder)

## The four sections (left panel)

```
▶ 1. Time Period           ← year(s) + split-screen
▶ 2. Tree Cover            ← GLAD or Hansen + optional Refine input (OLTC, planted forest)
▶ 3. Human Influence       ← buffer exclusions (roads, built-up, agriculture)
                              + Buffer Exceptions (slope, protected areas)
▶ 4. Refine Output         ← spatial cleanup of small / thin patches
```

Right panel: **▶ Area Statistics · ▶ Outputs · ▶ Validation**
Top bar: country selector · **↻ recenter** · **⚙ Config** · **ⓘ About**

## Run

1. Pick country (top bar).
2. Click **↻ Update Analysis** (green button, top of left panel).
3. First run ≈ 20–30 s on big countries.

`*` on the Update button = settings changed since last run.

## Layers and legend

- Tick **Add input + buffer layers to map** (bottom of left panel) to see the inputs that drive the analysis.
- Visibility and transparency are controlled from the **Layers** dropdown (top-right of map; hover for slider).
- Legend doesn't always auto-refresh — re-click **↻ Update Analysis** if stale (WIP).

---

## Known issues in this version

| Section | Issue | Workaround |
|---|---|---|
| §2 Tree Cover | **Hansen** tree cover renders inaccurately when zoomed out (GEE tiling quirk, not a real data difference) | Zoom into your country / province before judging it. Fix planned |
| §3 Human Influence | **Protected areas** filter is strict by default (IUCN Ia, Ib, II). If nothing shows when added to map, the filter is the likely reason | Untick categories on the left of each row in §3 → Buffer Exceptions. Move *Established before* slider toward 2025 to include more PAs |
| §Area Statistics | Very fine **Resolution (m)** can time out on large countries | Use a coarser resolution; export stats from Code-Editor mode instead |
| Legend | Legend in the bottom-left doesn't always auto-refresh after settings change | Re-click **↻ Update Analysis** to force a refresh. Improved auto-refresh is WIP |

---

## Access and data

| Resource | Link |
|---|---|
| **Browser app** — no account needed | [ee-andyarnellgee.projects.earthengine.app/view/primary-forest-finder](https://ee-andyarnellgee.projects.earthengine.app/view/primary-forest-finder) |
| **Code Editor script** — save settings, export to Drive, edit the script (free GEE account) | [code.earthengine.google.com/66503aadedcb379433227212fa3e29a6](https://code.earthengine.google.com/66503aadedcb379433227212fa3e29a6) |
| **Country test data** (all workshop countries — pick your own) | [Google Drive folder](https://drive.google.com/drive/folders/1PCuTzOISfQ6uArx6HIRruSBNf3vKe6Do?usp=drive_link) |
| **QGIS plugin** (companion offline tool) | [dist folder on GitHub](https://github.com/andyarnell/primaryforestfinder/tree/main/dist) |

---

## Feedback — please fill in

### Bugs / glitches
| Module | What you did | What went wrong |
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
- Likelihood you'd use PFF for national reporting (1 – 5): __

**Name / country (optional):** ____________________

---

*GEE one-pager · 2026-05-12 · companion to QGIS_Plugin_Workshop_Onepager.md*

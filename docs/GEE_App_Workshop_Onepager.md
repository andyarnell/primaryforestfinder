# PFF GEE App — Workshop One-Pager

**1-hour testing · v4.15.7-beta.1**

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
3. First run ≈ 20-30 s on big countries.

`*` on the Update button = settings changed since last run.

## Layers and legend

- Tick **Add input + buffer layers to map** (bottom of left panel) to see the inputs that drive the analysis.
- Visibility and transparency are controlled from the **Layers** dropdown (top-right of map; hover for slider).
- Legend doesn't always auto-refresh — re-click **↻ Update Analysis** if stale (WIP).

## Known caveats

- **Hansen tree cover** looks wrong when zoomed out (GEE tiling quirk). Zoom into your country before judging it.
- **Protected areas** filter is strict by default (IUCN Ia, Ib, II). If nothing shows on map, untick categories on the left of each row. **Established before** → 2025 = more inclusive.
- Very fine **Resolution (m)** can time out on large countries.

---

## Feedback — please fill in

### Bugs / glitches
| Module | What you did | What went wrong |
|---|---|---|
|   |   |   |
|   |   |   |
|   |   |   |

### Confusing wording, layout, or missing instructions
- 
- 
- 

### Features you looked for and couldn't find
- 
- 
- 

### National data you'd most want to plug in
| Section | National data |
|---|---|
|   |   |
|   |   |

### Overall
- One thing that worked well: 
- One thing to change first: 
- Likelihood you'd use PFF for national reporting (1 – 5): __

**Name / country (optional):** ____________________

---

*One-pager · 2026-05-12 · companion to GEE_App_Walkthrough.md*

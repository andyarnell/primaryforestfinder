# Primary Forest Finder — GEE App Workshop

**A 1-hour hands-on testing session**

Companion to the QGIS walkthrough ([`QGIS_Walkthrough_Ann_Rotich_V0.md`](QGIS_Walkthrough_Ann_Rotich_V0.md)). This sheet covers the cloud-based GEE app using global default datasets. Data export is currently script-mode only and is not covered here.

**Audience:** national authorities and GIS practitioners. No programming required — everything is point-and-click in a browser.

---

## Document conventions

- **Bold text** indicates app elements, buttons or section names — e.g. *Click* **↻ Update Analysis**.
- *Italics* denote important concepts — e.g. *Primary Forest*.
- > **NOTE:** background information
- > **TIP:** shortcut or best practice
- > **CAVEAT:** a known limitation to be aware of
- > **CHECKPOINT:** what the result should look like at that stage

---

## Before you start

1. Open the PFF app link (provided in the workshop).
2. Wait for the map to load. The title bar shows the version (e.g. `v4.15.7-beta.1`).
3. The app has three areas:
   - **Top bar** — country selector, recenter button, **⚙ Config**, **ⓘ About**
   - **Left panel** — analysis controls in four numbered sections
   - **Right panel** — *Area Statistics*, *Outputs*, *Validation*

> **CAVEAT — Hansen tree cover at low zoom**
> When zoomed out (whole continent or globe), the Hansen tree-cover layer can render inaccurately. This is a GEE tiling quirk, not a real data difference. Zoom into a country or province and the layer looks correct. A fix is planned.

> **NOTE — Layers and legend**
> Tick **Add input + buffer layers to map** (at the bottom of the left panel) to push all the input layers onto the map. After that, visibility and transparency are set from the **Layers** dropdown (top-right of the map; hover for the slider). The legend may not auto-refresh — re-click **↻ Update Analysis** if it looks stale (WIP).

---

## Module 1 — Run with global defaults

1. Pick your country from the top-bar selector.
2. Click **↻ Update Analysis** (green button, top of left panel).
3. Wait for the map to update.

> **CHECKPOINT:** the legend (bottom-left) shows *Tree cover*, *Pre-refinement primary forest*, and *Primary forest*. Primary forest appears clustered in remote/mountainous/protected areas.

> **TIP:** an asterisk (*) on the Update button means settings have changed since the last run.

---

## Module 2 — Section 2: Tree Cover

### 2.1 Switch the forest source

1. Open **▶ 2. Tree Cover**.
2. Change the source: **GLAD ↔ Hansen**.
3. Click **↻ Update Analysis**.
4. Compare the new tree-cover mask with the previous run.

> **CAVEAT:** zoom in before comparing Hansen — the low-zoom rendering is unreliable.

### 2.2 Optional Refine input — OLTC and Planted Forest

1. In **§ 2**, expand **▶ Refine input (optional, experimental)**.
2. Choose an *Input category* from the dropdown — e.g. *Forest* or *Naturally Regenerating Forest*.
3. Tick **Exclude OLTC** (oil palm / orchards / agroforestry — FRA Note 10).
4. Tick **Exclude planted forest** (FRA Planted Forest, e.g. timber / pulp).
5. Click **↻ Update Analysis**.

> **CHECKPOINT:** primary forest extent should decrease where oil palm or planted forest is present.

---

## Module 3 — Section 3: Human Influence

### 3.1 Adjust a buffer

1. Open **▶ 3. Human Influence**.
2. Move the **Roads** buffer slider.
3. Click **↻ Update Analysis**.
4. Try the **Agriculture** buffer too.

### 3.2 Buffer exceptions (slope and protected areas)

1. Expand **▶ Buffer Exceptions**.
2. Toggle the *steep slope* exception on/off, re-run, and observe rescued areas in mountainous terrain.
3. Toggle the *protected area* exception on/off, re-run, and observe rescued areas inside PAs.
4. **Established before:** moving this slider toward 2025 includes more PAs (more inclusive); older years are stricter.
5. **IUCN categories:** strict by default (Ia, Ib, II only). If you add PAs to the map and nothing shows, the filter is the likely reason — untick categories you don't want using the checkboxes on the left of each row.

> **CHECKPOINT:** the status label below each exception confirms whether it is enabled.

---

## Module 4 — Section 4: Refine Output

1. Open **▶ 4. Refine Output**.
2. Adjust the neighbourhood radius and minimum density sliders.
3. Click **↻ Update Analysis**.
4. Watch small isolated patches and thin sections come and go.

---

## Module 5 — Reference layers

1. Open **▶ Validation** (right panel).
2. Tick **FLII** and **Forest Persistence (FDaP)**.
3. Click **↻ Update Analysis**.
4. Where does PFF agree with both? Where does it disagree?

> **NOTE:** these layers are overlays only — they do not affect the PFF result.

---

## Module 6 — Stats at different resolutions

1. Open **▶ Area Statistics** (right panel).
2. Note the current *Resolution (m)* value.
3. Click **↻ Show Area Statistics** and read off the areas.
4. Change the *Resolution (m)* to a coarser value, click **↻ Show Area Statistics** again, and compare.
5. If your country isn't too large, try a finer value too.

> **TIP:** stats stabilise once resolution is fine enough to capture small patches. Coarse values are faster but may miss area.

> **CAVEAT:** very fine values can time out on large countries.

---

## Module 7 — Compare two years

1. Open **▶ 1. Time Period**.
2. Set Year 1 and Year 2 to different years (e.g. 2000 vs 2020).
3. Optional: tick *split-screen* to view side-by-side.
4. Click **↻ Update Analysis**.
5. Where has primary forest changed? Are losses near roads, settlements, or agriculture?

---

## Module 8 — Save your configuration

1. Open **⚙ Config** in the top bar.
2. *Save settings* → downloads a small JSON file.
3. *Load settings* → restores a run later.

---

## Optional extension — Inspect the buffer-exclusion data

If you want to see what's driving the *Human Influence* mask:

1. Tick **Add input + buffer layers to map** (bottom of the left panel) and click **↻ Update Analysis**.
2. Use the **Layers** dropdown (top-right of the map) to toggle each input layer on/off and adjust transparency.
3. Compare areas where multiple inputs overlap vs. where only one drives the buffer.
4. Try unticking individual exclusions in **§ 3** (e.g. agriculture) and re-running — does the candidate primary-forest extent change much in your country?

---

## Optional extension — Use your own data as a GEE asset

If you already have national data ingested into your GEE assets:

1. Open the relevant section — e.g. **§ 2** for a custom forest mask, **§ 3** for custom agriculture / roads / PAs.
2. Tick the *Custom data* checkbox for that input.
3. Paste the asset path (e.g. `projects/your-project/assets/your-layer`).
4. Choose a *Mode*: **Replace global**, **Add to global**, or **Agreement** (only pixels in both).
5. Configure the preprocessing (band, classes, threshold) as needed.
6. Click **↻ Update Analysis** and compare to the global-only run.

> **NOTE:** the asset must be visible to the GEE account running the app. Public assets work; private assets must be shared with you.

---

## Discussion prompts

- Where does PFF identify primary forest in your country? Does it match local knowledge?
- Which parameter mattered most when you adjusted it?
- Which dataset seemed most decisive — forest source, roads, PAs, slope?
- Where does the tool clearly get it wrong, and why?
- Would national data be needed to improve the result?

---

## User feedback

Please jot down notes as you work — we'll collect them at the end. Don't worry about being polite, blunt is more useful.

**Bugs / glitches encountered**
| Module | What you did | What went wrong |
|---|---|---|
|   |   |   |
|   |   |   |
|   |   |   |

**Things that confused you (wording, layout, missing instructions)**
- 
- 
- 

**Features you looked for and couldn't find**
- 
- 
- 

**National-data needs** — what national data would you most want to plug in, in what section?
- 
- 

**Overall**
- One thing that worked well:
- One thing to change first:
- Likelihood you'd use this in your country's reporting (1–5): __

---

## Suggested time budget (≈ 60 min)

| Module | Time |
|---|---:|
| 1. Run with defaults | 5 min |
| 2. Tree Cover + Refine input | 12 min |
| 3. Human Influence | 10 min |
| 4. Refine Output | 4 min |
| 5. Reference layers | 5 min |
| 6. Stats at different resolutions | 8 min |
| 7. Compare two years | 8 min |
| 8. Save config | 2 min |
| Discussion | 6 min |
| **Total core** | **≈ 60 min** |
| *Optional — GEE asset* | + 10 min |

---

*Workshop walkthrough · 2026-05-12 · pff_4.js v4.15.7-beta.1 · companion to QGIS Workflow Guide*

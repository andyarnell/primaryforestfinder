# PFF Datasets — developer & maintainer notes

Dev-facing companion to the user-facing [`datasets_global.md`](datasets_global.md) and its canonical machine-readable source [`datasets_global.json`](datasets_global.json).

These notes were split out of `datasets_global.md` so that page stays a clean public reference — it's linked from the GEE app's About panel ("Data inputs (global datasets)"), so workshop users land on it. Nothing below is needed by end users.

---

## Run-metadata recipe

For the run-metadata sidecar emitted alongside an export:

```js
const datasets = require('./docs/datasets_global.json');
const usedInRun = datasets.datasets.filter(d => d.status === 'active' || d.active_in_default_run === true);
// Embed { id, name, version, ee_assets, citation: { text, doi, documentation } } per entry.
```

For the (i)-button popup body, render: `description` + blank line + `citation.text` + DOI link + documentation link.

---

## UX plan — adding info without making the page busy

> **Status: not yet implemented.** The `datasets_panel_mockup.js` file referenced below does **not** currently exist in the repo — create it (or drop the reference) when building the panel. The `pff_4.js:NNNN` line numbers are from v4.14.1 and have since drifted; treat them as approximate.

The PFF GEE app side panel is already dense (forest source + sliders + buffer toggles + tier rescues + exports + legend + stats). The plan below adds dataset info using **one entry point** plus **two narrow exceptions** — no per-slider clutter.

### 1. Single primary entry — top-bar "📊 Datasets" button
- Add one button in the top bar (mirroring the existing About / Recenter buttons at `pff_4.js:2055-2070`).
- Click → opens [`datasets_panel_mockup.js`](datasets_panel_mockup.js) `datasetsContent` panel (scrollable, grouped, status-chipped). This is where 95% of dataset curiosity gets answered.
- **Cost:** one new top-bar button, one panel, zero changes to the analysis workflow.
- **Lazy-render:** build the panel on first click, not at app start, so cold-load speed is unaffected.

### 2. Inline ⓘ ONLY where the user is making a *choice*
Every other input (sliders, IUCN category list, slope thresholds) operates on a fixed dataset — the Datasets panel covers them. Only one place in v4.14.1 has a real source choice:
- **Forest source dropdown** (`pff_4.js:3775` — Hansen / GLAD / Agreement / Combined). Add a single ⓘ *next to the dropdown*, not per option. The popup contextualises which dataset(s) drive the chosen mode.
- **(Future-only) Roads vector source** if a multi-source roads dropdown is ever added.

That's it. No ⓘ on canopy slider, road buffer slider, slope threshold, etc. — the panel is the canonical reference; spamming ⓘ everywhere would crowd the UI for no extra information.

### 3. About panel: link, don't duplicate
The existing About panel (`pff_4.js:1901-1988`) already lists FRA categories + the FRA URL. Add **one line**:

> *Datasets used: see the 📊 Datasets panel.*

Don't copy citations into About — keep About focused on the conceptual / FRA narrative.

### 4. Legend stays untouched
The legend is the busiest pane on screen. Don't add ⓘ to legend entries. If a user wants to know which dataset drove a layer, the Datasets panel is one click away.

### 5. Right-panel layout: where to place the button row
Existing top-bar order (`pff_4.js:2056`): `[appTitle, countrySelector, countryWarningLabel, recenterButton, titleSpacer]`.

Proposed: `[appTitle, countrySelector, countryWarningLabel, recenterButton, datasetsButton, aboutButton, titleSpacer]` — keeps user-control buttons (recenter) before info buttons (datasets, about) and uses the spacer to right-align consistently.

### 6. QGIS plugin parity (defer, but plan)
Both the GEE app and the QGIS plugin can read [`datasets_global.json`](datasets_global.json) — one source of truth. The plugin can render the same per-section ⓘ next to its forest-source combo box (see `pff_qgis_tools/ui/pff_dock.py`). Defer the plugin wiring until after the GEE app pattern proves out in a workshop.

### Visual sketch — what the user sees

```
┌─────────────────────────────────────────────────────────────┐
│ Primary Forest Finder    [Bhutan ▾]  [↻]  [📊]  [ⓘ]         │  ← top bar (📊 = Datasets, ⓘ = About)
├──────────────────────┬──────────────────────────────────────┤
│ TIER 0 — Tree cover  │                                       │
│ Source: [GLAD LULC ▾] ⓘ ← single info button, *not* per row │
│ Tree height ≥ [5  ▭]                                          │
│ ─────────────────                                             │
│ TIER 1 — Disturbance buffers                                  │
│ Roads     [1000 ▭]                                            │
│ Built-up  [1000 ▭]                                            │
│ Built-up  [1000 ▭]    ← no ⓘ here; covered by 📊 panel       │
│ Agri      [1000 ▭]                                            │
│ ...                                                           │
└──────────────────────┴──────────────────────────────────────┘

When user clicks 📊:
┌─ Datasets used by Primary Forest Finder ──────────[×]┐
│ Legend: [ACTIVE]=run [OPT]=off [QUEUED]=available    │
│                                                       │
│ Forest cover                                          │
│ ┌──────────────────────────────────────────────────┐ │
│ │ Hansen Global Forest Change v1.12  [ACTIVE]      │ │
│ │ Role: Tree-cover-2000 + lossyear...              │ │
│ │ Preprocessing: tree2000 > thresh AND no-loss...  │ │
│ │ Hansen, M.C. et al. (2013). Science 342, 850–853.│ │
│ │ DOI  Docs                                        │ │
│ └──────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────┐ │
│ │ GLAD GLCLU 2000–2020 v2  [ACTIVE]                │ │
│ │ ...                                               │ │
│ └──────────────────────────────────────────────────┘ │
│                                                       │
│ Protected areas                                       │
│ ┌──────────────────────────────────────────────────┐ │
│ │ WDPA  [ACTIVE]                                   │ │
│ │ ...                                               │ │
│ └──────────────────────────────────────────────────┘ │
│ ...                                                   │
└───────────────────────────────────────────────────────┘
```

### Mockup file
[`docs/datasets_panel_mockup.js`](datasets_panel_mockup.js) is a drop-in GEE-UI module that implements both patterns. To wire up: import it in `pff_4.js`, place `datasetsButton` in the top bar, place `datasetsContent` and `infoPopupContent` somewhere on the page (e.g. main map overlay), and call `makeInfoButton('hansen_gfc_v1_12')` on the forest dropdown row.

---

## Update workflow

When `pff_4.js` adds, removes, or flips a flag for a dataset:

1. Update `datasets_global.json` — change `status` / `active_in_default_run` / `code_refs`.
2. Bump `covers_pff_script_version`.
3. Run a Bhutan self-test (per `feedback_pff_self_test_before_zip`) to confirm the swap works.
4. Update `datasets_global.md`'s status badges to match.

When a citation needs updating (new DOI, new release year), update `citation` in the JSON; `datasets_global.md` can be regenerated from JSON if a script is added.

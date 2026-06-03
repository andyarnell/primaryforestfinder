# Trend reporting and FRA category translation

Guidance on two issues that recurred across the Asia-Pacific workshop (Days 2–3): (1) reporting primary-forest **trends** consistently through time, and (2) translating **national forest classes** into FRA reporting categories.

> Draft — created from the guidance-document discussion. Align with the FRA guidance document before circulating.

---

## Part 1 — Trends and time-series consistency

### The core rule
Primary forest is a **one-way** category through time: a stand can **leave** primary (through human disturbance) but cannot **enter** it. So a time series of primary-forest area should be **non-increasing** unless you are deliberately revising the method.

### Distinguishing real change from methodological revision
Apparent change in a primary-forest time series has two very different sources:

| Apparent change | Likely cause | How to treat it |
|---|---|---|
| Decrease over time | Real human disturbance reaching previously-intact forest | Real loss — report as trend |
| **Increase** over time | Dynamic forest layer (e.g. GLAD) adding "new" forest, or a method/data change | **Not** real gain — fix or label as a methods revision |
| Step change at a method switch | New satellite system, new definition, new threshold | Methodological revision — recompute earlier years on the same basis (backcasting) where possible |

Indonesia's Kalimantan example (more "primary" in 2020 than 2000) is the classic dynamic-layer artefact. Viet Nam's monitoring-system change in 2015 is the classic method-switch case.

### Practical recommendations
- **Constrain later years to the baseline forest mask** so new forest can't become primary. (Implemented in the QGIS plugin's multi-year runs; being ported to the GEE app.)
- **Hold method and data fixed across the series** where possible; if you must change them, **recompute earlier years** on the new basis and note it.
- **Document** the forest source (Hansen vs GLAD), thresholds, buffers and baseline year alongside every reported figure — these drive comparability more than anything else.
- Report a **methods-revision** flag separately from real ecological change.

---

## Part 2 — FRA category translation

### National classes don't map one-to-one
National legends are built for national purposes and rarely align with FRA categories. The most common mismatch: a national **"secondary forest"** class.

- **"Secondary forest" is not an FRA reporting class.** Don't report it as such.
- Forest that is not primary is generally **naturally regenerating forest** (or planted / other), depending on origin and management.

### A simple decision frame
For each national forest class, ask:

1. **Native species, naturally regenerated?** If no (planted, introduced/GM material) → not primary; likely *planted forest* or *other*.
2. **Clearly visible human activity / significantly disturbed ecological processes?** If yes (and human-induced) → not primary; *naturally regenerating forest*.
3. **Disturbance present but natural** (storm, natural fire, landslide, insect)? → can still be *primary*.
4. **No visible human activity, processes intact, native** → *primary forest*.

### Three country situations (from the Day 3 discussion)
- **Official data already aligned** with FRA primary — may only need minor adjustment (e.g. handling natural disturbance). *Indonesia reported ~90% alignment.*
- **Official data / similar concept needing alignment or reclassification** — e.g. classes that allow human disturbance, or that need time-series clarification. *PNG, Viet Nam.*
- **No official primary-forest data** — estimate via a decision-tree / hybrid (landscape filtering + stand-level NFI / field data). *Bhutan, Lao PDR, Thailand.*

### Things that are not FRA categories but still matter
Forests that are **not** primary may still hold high biodiversity, cultural or conservation value (recurring workshop point). Capturing that is a national/biodiversity concern, separate from FRA primary-forest reporting.

---

*Cross-references: FAQ → `../workshop/FAQ.md`; connectivity / patch size → `../connectivity_methods.md`; national data prep → `../workshop/national_data_preparation_checklist.md`.*

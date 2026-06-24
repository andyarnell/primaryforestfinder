# Primary Forest Finder — FAQ

Short answers to the questions that recurred most across the Asia-Pacific workshop (Bangkok, May 2026). Aimed at national reporting teams using the GEE App, the QGIS Plugin, or the CEO validation workflow.

> Draft — created from workshop discussions (Days 1–3). Refine against the guidance document before circulating.

---

## Definitions

### What counts as "primary forest" under FRA?
Naturally regenerated forest of native species where there are **no clearly visible indications of human activity** and the **ecological processes are not significantly disturbed**. There is **no minimum area** in the FRA definition — minimum mapping unit and patch-size choices are left to the country (and should be documented).

### Is the forest that isn't primary automatically "secondary forest"?
No. "Secondary forest" is **not an FRA reporting class**. National "secondary forest" classes do not map one-to-one onto FRA categories. Forest that is not primary is reported under the broader **naturally regenerating forest** category (or planted/other, as appropriate) — see the FRA category-translation note.

### Does natural disturbance make a forest non-primary?
No — not on its own. Forest affected by **natural** disturbance (storm, fire of natural origin, landslide, insect outbreak) can still qualify as primary if the disturbance is part of the natural ecological cycle. **Human-induced** disturbance is what generally moves a forest outside the primary class. Several countries (e.g. Indonesia) flagged that an apparent loss-then-regrowth from natural disturbance should not drop a stand out of primary.

### Native species, planted or assisted — does it matter?
Primary forest is **native species, naturally regenerated**. Planted stands, or stands established from introduced/genetically-modified material, are not primary even if the species is native.

---

## Mapping and thresholds

### Can primary forest *increase* over time?
**No.** Primary forest cannot appear where it was absent at the baseline — a pixel that was not primary in 2000 cannot become primary in 2020. If your map shows an increase (Indonesia saw this in Kalimantan), it is almost always a **methodological artefact** of a dynamic forest layer (e.g. GLAD adding "new" forest), not real gain. Constrain later years to the **baseline forest mask**, and treat any apparent gain as a methods revision, not ecological recovery. *(This is enforced in the QGIS plugin's multi-year runs and is being ported to the GEE app.)*

### Hansen vs GLAD — which forest source should I use?
- **Hansen** is a **baseline + loss** product: a 2000 baseline with annual loss. It does not add new forest.
- **GLAD** is a **dynamic annual** product: forest can appear *and* disappear year to year.

For primary-forest **trends**, a dynamic layer can introduce apparent gains (see above). If you use GLAD, apply the baseline constraint. Document which source you used — it materially affects the result.

### Why does a small road or clearing remove so much primary forest?
Roads, built-up and agriculture are buffered (commonly ~1 km) to capture edge effects. A small road or a patch of grassland/rock inside otherwise-intact forest can therefore exclude a large area (Thailand and Viet Nam both noted this). Options: use a **smaller buffer** for minor/forest roads, supply **national classified roads**, or use the **protected-area / slope buffer exceptions** where justified.

### Small fragments — are they automatically non-primary?
No. Patch-size and connectivity thresholds are a **modelling choice**, not part of the FRA definition. Naturally fragmented forests (e.g. on rugged terrain) can be primary. Set minimum-patch thresholds per ecosystem and **document them**; don't assume a single threshold suits every landscape.

### Protected-area status — does it prove a forest is primary?
No. Long-established protected areas can contain both long-persistent forest **and** areas recovering from historical settlement or cultivation (the Khao Yai field visit illustrated this). PA status helps, but historical evidence, local knowledge and ecological interpretation are still needed.

---

## Tools

### When should I use the GEE App vs the QGIS Plugin?
- **GEE App** — fast, global default datasets, no install, good for a consistent first-pass and for exports you can drop into QGIS.
- **QGIS Plugin** — offline, flexible, designed to mix **national** data with global defaults and do bespoke analysis.

They are complementary; GEE exports are valid QGIS inputs. Differences in results usually come from dataset, resolution, projection or threshold choices — see the GEE-vs-QGIS comparison note.

### Why do results differ between the two tools, or between runs?
Common causes: different forest/road/plantation inputs, different resolution, different CRS, or different thresholds. In the QGIS plugin specifically, **re-running into the same folder with the "Reuse preprocessing cache" option on can reuse stale prepared inputs** — use a fresh output folder when you change inputs.

### Plantations (rubber, acacia, eucalyptus) are showing as primary forest — why?
Global forest layers (and the FAO forest raw data) include managed plantations such as Para rubber. They only get excluded if a **plantation/planted-forest layer** is supplied — and the global SDPT layer under-captures SE Asian smallholder rubber. For affected regions, supply a **national plantation layer**.

---

## Validation (CEO)

### Is the assessment about the centroid point or the surrounding area?
Both, but for **different questions** — and the workflow should state which level each question applies to (centroid vs buffer). This was the most common validation confusion; the form is being revised to separate the two explicitly.

### Should I start from the most recent imagery or the historical imagery?
Starting from **historical** imagery and working forward was felt to be more logical and systematic — it lets you establish whether the plot was primary at baseline before judging later change.

### Remote sensing alone isn't enough — what else?
For disturbance history, traditional use, access and species composition, **local experts, provincial officers and Indigenous Peoples / local communities** are often needed. Supporting layers people asked for: NDVI / NDMI / NDFI, fire data, Hansen loss, slope, elevation, and higher-resolution imagery (Sentinel-2) where available.

---

*Cross-references: trend reporting and FRA category translation → `PFF_TRENDS_AND_FRA_CATEGORY_TRANSLATION.md`; national data prep → `national_data_preparation_checklist.md`; tool differences → `../pff4_vs_qgis_plugin_comparison.md`.*

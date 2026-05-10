# Datasets Used by Primary Forest Finder

Workshop presentation companion. For full technical details see [`datasets_global.md`](datasets_global.md).

---

## How PFF works — the logic

1. **Map all tree cover** — where are the trees?
2. **Subtract human influence** — anything near roads, towns, farms, or plantations is unlikely to be undisturbed
3. **Rescue exceptions** — forest on steep mountains or inside old protected areas may be undisturbed despite being near activity
4. **Remove tiny fragments** — isolated patches too small to function as intact forest

Each step uses freely available global datasets. You can adjust the thresholds to fit your country's context.

---

## Step 1 — Where are the trees?

| Dataset | What it shows | Coverage |
|---|---|---|
| **GLAD GLCLU v2** (default) | Tree height estimated from satellite imagery — we keep everything ≥ 5 m | Global, 6 time steps (1990–2020) |
| **Hansen Global Forest Change** | Alternative: canopy cover + where forest has been lost each year since 2000 | Global, updated annually |

Why two options? GLAD gives tree height at multiple dates (good for change over time). Hansen gives annual loss detection (good for pinpointing when deforestation happened). PFF defaults to GLAD but you can switch.

---

## Step 2a — Subtract settlements and towns

Forest within 1 km of built-up areas is excluded — human activity nearby makes undisturbed forest unlikely.

| Dataset | What it shows |
|---|---|
| **JRC Global Human Settlement Layer** | Distinguishes small rural settlements from cities — sourced from satellite imagery and population data |
| **DLR World Settlement Footprint** | Tracks settlement growth year by year from 1985 — useful for seeing how towns expanded into forest over time |

Small settlements and large urban areas are treated separately — a logging town and a city have different zones of influence.

---

## Step 2b — Subtract agriculture

Agricultural land also generates a 1 km buffer. Three datasets are combined to get a comprehensive picture:

| Dataset | What it covers |
|---|---|
| **GLC_FCS30D** | Broad land-cover classification including cropland types |
| **GLAD Cropland** | Dedicated cropland mapping |
| **Global Pasture Watch** | Distinguishes cultivated grassland from natural grassland — only cultivated is excluded |

The distinction matters: natural grasslands in highland areas should not count as "human disturbance."

---

## Step 2c — Subtract plantations and tree crops

Oil palm, rubber, and timber plantations look like forest from above but are not primary forest.

| Dataset | What it covers | Relevant countries |
|---|---|---|
| **Descals Oil Palm** | Maps oil palm extent with year of planting | Indonesia, Malaysia, Thailand, PNG |
| **SDPT v2** (WRI) | Separates planted forest from tree crops (rubber, cocoa, etc.) | Global |

Following FAO FRA definitions: oil palm and tree crops = "Other Land with Tree Cover" (not forest). Timber plantations = forest, but not *naturally regenerating* forest — excluded separately.

---

## Step 2d — Subtract roads

Roads are a strong indicator of human access to forest. Forest within 1 km of a road is excluded.

| Dataset | What it covers |
|---|---|
| **GRIP4** (Globio) | Major road network with estimated traffic volume — larger roads have bigger influence |
| **OpenStreetMap** | Community-mapped roads including logging tracks, rural paths — fills gaps where official data misses smaller roads |

The combination matters especially in SE Asia, where logging roads may not appear in official road databases but are well-mapped by OSM contributors.

---

## Step 3a — Rescue: steep slopes

Not all forest near roads or farms is disturbed. Very steep terrain (> 45°) is difficult to access — forest there may be undisturbed even if a road passes below.

| Dataset | What it provides |
|---|---|
| **JAXA ALOS 30m DEM** | Elevation data from which slope steepness is calculated |

This is important in countries like Bhutan, Laos, and Vietnam where steep terrain protects significant areas of forest from logging and agriculture.

---

## Step 3b — Rescue: protected areas

Forest inside well-established, strictly protected areas gets a second chance — even if it falls within a road or settlement buffer.

| Dataset | What it provides |
|---|---|
| **WDPA** (World Database on Protected Areas) | Boundaries, IUCN category, and year of designation for every protected area globally |

Default settings: only the strictest categories (Ia, Ib, II) and only areas designated ≥ 30 years ago. The rationale: recently designated areas may not yet be effectively protected, and lower-category areas often allow extractive use.

---

## Comparison layers (not used in the analysis)

These are shown alongside PFF results for context — a "second opinion" on forest condition.

| Dataset | What it shows |
|---|---|
| **Forest Landscape Integrity Index** (Grantham et al. 2020) | How "intact" the surrounding landscape is — considers fragmentation, edge effects, human pressure |
| **Forest Persistence** (Forest Data Partnership) | Likelihood that a pixel has been continuously forested — high values suggest long-term stability |

If PFF identifies an area as primary forest AND these layers agree it's intact and persistent — that's a strong signal.

---

## Country boundaries

| Dataset | What it provides |
|---|---|
| **FAO GAUL 2024** | Country and sub-national boundaries — defines your study area |

---

## Summary — what goes in, what comes out

```
 All tree cover (GLAD / Hansen)
   minus  settlements (GHSL + WSF)
   minus  agriculture (GLC-FCS + GLAD Cropland + Pasture Watch)
   minus  plantations (SDPT + Descals oil palm)
   minus  roads (GRIP4 + OpenStreetMap)
   rescue  steep slopes > 45° (ALOS DEM)
   rescue  strict protected areas ≥ 30 yr (WDPA)
   filter  remove small isolated fragments
   ════════════════════════════════════════
   = Primary Forest candidate map
```

All thresholds (buffer distances, slope angle, protection age, IUCN categories) are adjustable. The defaults are a starting point — your national knowledge is what makes the map meaningful.

---
---

# Backup slides — datasets available but not currently used

These are built into the tool but switched off by default. They can be turned on for experimentation or discussion.

---

## Additional settlement data (off)

| Dataset | Why it's switched off |
|---|---|
| **GISD30** (Global Impervious Surface, 1985–2020) | Misclassifies rock formations as built-up in mountainous and arid areas |
| **GISA** (Global Impervious Surface Area, 1972–2019) | Longest time span available but largely duplicates GHSL + WSF coverage |

---

## FDaP plantation model (off)

| Dataset | Why it's switched off |
|---|---|
| **FDaP Palm / Rubber / Cocoa** (2024a) | Over-detects plantations in dense tropical forest — wrongly removes genuine primary forest. The Descals + SDPT combination is more conservative and reliable. |

This is particularly relevant in SE Asia where dense dipterocarp forest can be misclassified as rubber or oil palm by the FDaP model.

---

## Population data (available, unused)

| Dataset | Status |
|---|---|
| **LandScan Global** (ORNL) | Loaded in the code but not wired into the analysis — available for future experiments, e.g. population-density-weighted buffers |

---

## Water and waterways (available, unused)

| Dataset | Status |
|---|---|
| **OSM Water Layer** (canals) | Canal network extracted but not yet included in the disturbance buffers |
| **Navigable Rivers** (WDB-derived) | River navigation routes — could indicate forest access via waterways, especially relevant for PNG and Indonesia |

A future version could buffer navigable waterways the same way roads are buffered.

---

## Regional road datasets (not loaded)

| Dataset | Region | Notes |
|---|---|---|
| **Ghost Roads Asia** | SE Asia | Academic dataset mapping logging roads — could improve road coverage for this workshop's countries |
| **WUR Congo Logging Roads** | Central Africa | Useful for Congo Basin work |
| **Microsoft Global Roads** | Global | ML-detected from satellite imagery — not yet evaluated |
| **MapBiomas Brazil Roads** | Brazil | Country-specific |
| **USA TIGER Roads** | USA | Not relevant for this workshop |

---

## Other datasets on the radar

| Dataset | What it could add |
|---|---|
| **WRI SBTN Natural Lands** | Alternative classification of "natural" land — potential cross-check against PFF results |
| **European Primary Forests Database** | Mapped primary forest locations in Europe — validation reference |
| **Tsinghua China Terrace Map** | Identifies agricultural terraces — could improve agriculture detection in terraced landscapes |

---

## Disturbance history (active, works behind the scenes)

| Dataset | What it does |
|---|---|
| **JRC Tropical Moist Forests** | Detects deforestation year in tropical regions — combined with Hansen loss data to build a more complete picture of where forest has been cleared |

You don't interact with this directly — it feeds into the forest-loss timeline automatically.

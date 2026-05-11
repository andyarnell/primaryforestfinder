# PFF — Dataset Info

Organised by the four numbered sections in the app: **1. Time Period · 2. Tree Cover · 3. Human Influence · 4. Refine Output**. Each table includes the citation and source page so you can follow up on any dataset.

For full machine-readable metadata see [`datasets_global.json`](datasets_global.json).

---

## How PFF works — the logic

1. **Map all tree cover** — where are the trees?
2. **(Optional) Refine the tree-cover input** — separate OLTC and planted forest out of the starting mask
3. **Subtract human influence** — buffer exclusions around built-up areas, agriculture, and roads, with exceptions for steep slopes and long-protected areas
4. **Refine output** — remove small isolated patches and thin sections

National data can replace, add to, or be intersected with any global layer at each step.

---

## Section 1 — Time Period

No datasets selected here. You pick the analysis year(s); each dataset is then loaded for the corresponding time step (or its nearest available year).

---

## Section 2 — Tree Cover

The starting tree-cover mask. Choose one source — the other can be loaded as a comparison.

| Dataset | Role | Citation & source |
|---|---|---|
| **GLAD GLCLU v2** *(default)* <br>*Global 30 m land cover and land use with per-pixel tree-height estimates at 6 time steps from 1990 to 2020* | Tree height from satellite imagery → tree-cover mask | Potapov et al. (2022). [doi:10.3389/frsen.2022.856903](https://doi.org/10.3389/frsen.2022.856903). [glad.umd.edu](https://glad.umd.edu/dataset/GLCLUC2020) |
| **Hansen Global Forest Change v1.12** <br>*Global 30 m tree-cover-2000 layer plus annual forest loss year, updated annually* | Tree-cover-2000 + annual loss; alternative tree-cover mask | Hansen et al. (2013). [doi:10.1126/science.1244693](https://doi.org/10.1126/science.1244693). [glad.umd.edu](https://glad.umd.edu/dataset/global-forest-change) |

→ Output of this section: a binary tree-cover mask for the chosen year.

Why two options? There are not many high-resolution tree-cover datasets covering the time period needed — GLAD and Hansen are the two practical global choices. National data can also be plugged in here.

### Section 2 — Refine input *(optional, experimental)*

Narrows the tree-cover mask into the FRA Forest definition by subtracting two categories. Off by default.

| Toggle | Datasets | Role | Citation & source |
|---|---|---|---|
| **Exclude OLTC** (oil palm / orchards / agroforestry) | SDPT v2 class 2; Descals Oil Palm | Pixels with tree cover but not FRA Forest (Note 10) are split out | Richter et al. (2024) — [WRI SDPT v2](https://www.wri.org/research/spatial-database-planted-trees-sdpt-version-2); Descals et al. (2024), [doi:10.5194/essd-16-5111-2024](https://doi.org/10.5194/essd-16-5111-2024) |
| **Exclude planted forest** | SDPT v2 class 1 | FRA Planted Forest (timber, pulp, fibre) is split out so the remainder is naturally regenerating forest | Richter et al. (2024) — [WRI SDPT v2](https://www.wri.org/research/spatial-database-planted-trees-sdpt-version-2) |

*Used twice: SDPT v2 and Descals Oil Palm also appear in Section 3 (agriculture buffer), since FRA classifies tree crops and oil palm as agricultural land use.*

---

## Section 3 — Human Influence

Buffer exclusions: pixels of the tree-cover/forest mask near human activity are subtracted from the candidate primary forest.

### Built-up buffer

| Dataset | Role | Citation & source |
|---|---|---|
| **JRC GHSL — Settlement Model (SMOD) + Population (POP) P2023A** <br>*Built-up classification distinguishing small settlements from larger urban areas, masked by population presence* | Used twice: small built-up and larger urban areas (separately buffered), masked by population presence | Pesaresi et al. (2024). [doi:10.1080/17538947.2024.2390454](https://doi.org/10.1080/17538947.2024.2390454). [GHSL site](https://human-settlement.emergency.copernicus.eu/) |
| **DLR World Settlement Footprint Evolution** <br>*Annual 30 m global settlement footprint from 1985 to 2015* | Combined with the small built-up class to extend built-up extent backward to 1985 | Marconcini et al. (2020). [doi:10.1038/s41597-020-00580-5](https://doi.org/10.1038/s41597-020-00580-5). [DLR WSF EVO](https://geoservice.dlr.de/web/datasets/wsf_evo) |

### Agriculture buffer

| Dataset | Role | Citation & source |
|---|---|---|
| **GLAD Cropland (Potapov)** <br>*Global 30 m cropland presence at multiple time steps between 2000 and 2019* | Cropland presence at multiple time steps | Potapov et al. (2022). [doi:10.1038/s43016-021-00429-z](https://doi.org/10.1038/s43016-021-00429-z). [glad.umd.edu](https://glad.umd.edu/dataset/croplands) |
| **Global Pasture Watch v1** <br>*Annual 30 m grassland map separating cultivated from natural/semi-natural grasslands* | Cultivated grassland only — natural grasslands are not excluded | Parente et al. (2024). [doi:10.1038/s41597-024-04139-6](https://doi.org/10.1038/s41597-024-04139-6). [WRI / GitHub](https://github.com/wri/global-pasture-watch) |
| **Descals Oil Palm** *(also in Section 2 refine)* <br>*Global per-pixel year of oil palm establishment from 1990 to 2021* | Oil palm extent enters the agriculture composite | Descals et al. (2024). [doi:10.5194/essd-16-5111-2024](https://doi.org/10.5194/essd-16-5111-2024). [Catalog](https://gee-community-catalog.org/projects/global_palm_oil/) |
| **SDPT v2** *(also in Section 2 refine)* <br>*Global polygons of planted trees, separating planted forest from tree crops* | Tree-crop class (class 2) enters the agriculture composite | Richter et al. (2024). [WRI SDPT v2](https://www.wri.org/research/spatial-database-planted-trees-sdpt-version-2) |

### Roads buffer

| Dataset | Role | Citation & source |
|---|---|---|
| **OSM Roads (PFF 33-region merge)** <br>*OpenStreetMap road network collected globally in May 2025* | Active road raster — global OpenStreetMap collected May 2025 | © OpenStreetMap contributors (2025), ODbL 1.0. [openstreetmap.org](https://www.openstreetmap.org/) |

*Note: GRIP4 with predicted traffic is in the codebase but currently switched off — see backup section.*

### Buffer Exceptions

Forest in the buffered area is rescued back into the candidate primary forest if either condition holds.

| Dataset | Role | Citation & source |
|---|---|---|
| **JAXA ALOS World 3D-30m DSM v3.2** <br>*Global 30 m digital surface model* | Used twice: source of the slope-rescue layer AND exported as DEM/slope sidecar | Tadono et al. (2016). [doi:10.5194/isprs-archives-XLI-B4-157-2016](https://doi.org/10.5194/isprs-archives-XLI-B4-157-2016). [JAXA AW3D30](https://www.eorc.jaxa.jp/ALOS/en/dataset/aw3d30/aw3d30_e.htm) |
| **WDPA — World Database on Protected Areas** <br>*Global protected-area polygons with IUCN category and year of designation* | Long-designated strictly protected areas qualify forest for rescue | UNEP-WCMC & IUCN (2026). [doi:10.34892/6fwd-af11](https://doi.org/10.34892/6fwd-af11). [Protected Planet](https://www.protectedplanet.net/en/thematic-areas/wdpa) |

---

## Section 4 — Refine Output

A spatial filter: removes small isolated patches and thin sections. No new datasets are introduced here — it operates on the candidate map produced by Section 3.

---

## Reference layers (overlays only, not in analysis)

Optional overlays toggled in the Validation panel.

| Dataset | Role | Citation & source |
|---|---|---|
| **Forest Landscape Integrity Index (FLII) 2019** <br>*0–10 score per ~300 m pixel summarising landscape-scale forest integrity* | Landscape-scale integrity score | Grantham et al. (2020). [doi:10.1038/s41467-020-19493-3](https://doi.org/10.1038/s41467-020-19493-3). [forestintegrity.com](https://www.forestintegrity.com/) |
| **FDaP Forest Persistence 2020** <br>*Per-pixel 0–1 probability of continuous forest cover at 2020* | Per-pixel probability of continuous forest cover | Forest Data Partnership / Google (2024). [forestdatapartnership.org](https://www.forestdatapartnership.org/) |

---

## Country & area boundaries

| Dataset | Role | Citation & source |
|---|---|---|
| **FAO GAUL 2024 (Level 0)** <br>*Global country boundary polygons maintained by FAO* | Country boundaries + clipping; drives the country selector | FAO (2024). [FAO catalog](https://data.apps.fao.org/catalog/dataset/global-administrative-unit-layers-gaul-2024) |

---

## Summary — pipeline at a glance

```
SECTION 2: Tree Cover           (GLAD or Hansen)
   + (optional) Refine input:
       – Exclude OLTC           (SDPT class 2 + Descals oil palm)
       – Exclude Planted Forest (SDPT class 1)
SECTION 3: Human Influence (buffer exclusions)
   – Built-up buffer            (GHSL + WSF Evolution)
   – Agriculture buffer         (GLAD Cropland + Pasture Watch
                                 + Descals + SDPT class 2)
   – Roads buffer               (OSM)
   + Buffer Exceptions (rescues):
       + Steep slopes           (JAXA ALOS)
       + Long-protected areas   (WDPA)
SECTION 4: Refine Output
   – remove small / thin patches
   ══════════════════════════════════════
   = Primary Forest candidates
```

---
---

# Backup — datasets in the tool but switched off

Wired into the code but currently disabled. Can be re-enabled for workshops or experimentation.

## Section 3 — Roads buffer (alternatives)

| Dataset | Citation & source |
|---|---|
| **GRIP4 + AADT** | Meijer et al. (2018). [doi:10.1088/1748-9326/aabd42](https://doi.org/10.1088/1748-9326/aabd42). [GLOBIO GRIP](https://www.globio.info/download-grip-dataset) |
| USA TIGER Roads | [US Census TIGER](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html) |
| WUR Congo Basin Logging Roads | Kleinschroth et al. (2019). [doi:10.1038/s41893-019-0310-6](https://doi.org/10.1038/s41893-019-0310-6) |
| Microsoft Global Roads | [Microsoft RoadDetections](https://github.com/microsoft/RoadDetections) |
| Ghost Roads Asia / New Guinea | Engert et al. (2024). [doi:10.1038/s41586-024-07303-5](https://doi.org/10.1038/s41586-024-07303-5) |
| MapBiomas Brazil Roads | [MapBiomas Brazil](https://brasil.mapbiomas.org/) |

## Section 3 — Disturbance composite (alternative)

| Dataset | Citation & source |
|---|---|
| **JRC TMF v1_2025 — Deforestation Year** | Vancutsem et al. (2021). [doi:10.1126/sciadv.abe1603](https://doi.org/10.1126/sciadv.abe1603). [JRC TMF](https://forobs.jrc.ec.europa.eu/TMF/) |

## Section 3 — Built-up buffer (alternatives)

| Dataset | Citation & source |
|---|---|
| GISD30 1985–2020 | Zhang et al. (2022). [doi:10.5194/essd-14-1831-2022](https://doi.org/10.5194/essd-14-1831-2022). [Catalog](https://gee-community-catalog.org/projects/gisd30/) |
| GISA 1972–2019 | Huang et al. (2021). [doi:10.1007/s11430-020-9797-9](https://doi.org/10.1007/s11430-020-9797-9). [Catalog](https://gee-community-catalog.org/projects/gisa/) |
| DLR WSF 2015 | Marconcini et al. (2020). [doi:10.1038/s41597-020-00580-5](https://doi.org/10.1038/s41597-020-00580-5). [DLR WSF 2015](https://geoservice.dlr.de/web/datasets/wsf_2015) |
| DLR WSF 2019 | Marconcini et al. (2021). [doi:10.1553/giscience2021_01_s33](https://doi.org/10.1553/giscience2021_01_s33). [DLR WSF 2019](https://geoservice.dlr.de/web/datasets/wsf_2019) |

## Section 3 — Agriculture buffer (alternative)

| Dataset | Citation & source |
|---|---|
| **GLC_FCS30D** | Zhang et al. (2024). [doi:10.5194/essd-16-1353-2024](https://doi.org/10.5194/essd-16-1353-2024). [Catalog](https://gee-community-catalog.org/projects/glc_fcs/) |

## Section 2 refine input — Plantations (alternatives)

| Dataset | Citation & source |
|---|---|
| FDAP Palm 2024a | Forest Data Partnership / Google (2024). [forestdatapartnership.org](https://www.forestdatapartnership.org/data-approach) |
| FDAP Rubber 2024a | Forest Data Partnership / Google (2024). [forestdatapartnership.org](https://www.forestdatapartnership.org/data-approach) |
| FDAP Cocoa 2024a | Forest Data Partnership / Google (2024). [forestdatapartnership.org](https://www.forestdatapartnership.org/data-approach) |

## Population

| Dataset | Citation & source |
|---|---|
| LandScan Global | Rose et al. (2025). [doi:10.1038/s41597-025-04817-z](https://doi.org/10.1038/s41597-025-04817-z). [ORNL LandScan](https://landscan.ornl.gov/documentation) |

## Waterways

| Dataset | Citation & source |
|---|---|
| OSM Water Layer (canals) | Yamazaki Lab, U-Tokyo. [OSM Water](https://hydro.iis.u-tokyo.ac.jp/~yamadai/OSM_water/) |
| PFF Navigable Rivers (WDB) | Custom PFF derivative; original World Data Bank navigable rivers |
| Navigable Waterways USA | USACE / NOAA navigable waterways |

## Reference layers (alternatives)

| Dataset | Citation & source |
|---|---|
| WRI SBTN Natural Lands v1.1 | Mazur et al. (2025). [Land & Carbon Lab](https://landcarbonlab.org/data/natural-lands-map/) |
| European Primary Forests Database v2 | Sabatini et al. (2018). [doi:10.1111/ddi.12778](https://doi.org/10.1111/ddi.12778) |
| Tsinghua DESS China Terrace Map v1 | Cao et al. (2021). [doi:10.5194/essd-13-2437-2021](https://doi.org/10.5194/essd-13-2437-2021) |

---

## Counts

| Category | Count |
|---|---:|
| ✅ Actively used in main pipeline | 14 |
| 🟠 Loaded but currently off | 12 |
| 🔵 Commented-out alternatives | 10 |
| **Total** | **36** |

Verified against pff_4.js v4.15.7-beta.1 + QGIS plugin v0.16.0-beta.1 on 2026-05-11.

# PFF Datasets — Workshop Handout

Two pages: **page 1** lists datasets included in the analysis; **page 2** lists those available in the tool but not currently driving outputs. Thresholds (canopy, height, slope, buffer distance, protection age, IUCN category) are adjustable in the app, so are not stated below.

---

## Page 1 — Datasets included in the analysis

| Dataset | What it is | How it is used in PFF |
|---|---|---|
| **GLAD GLCLU v2** (Potapov et al., 2022) | Global 30 m land cover and land use with per-pixel tree-height estimates at 6 time steps from 1990 to 2020 | Default forest baseline — pixels meeting the tree-height threshold define the starting forest mask |
| **Hansen Global Forest Change v1.12** (Hansen et al., 2013; UMD) | Global 30 m tree-cover-2000 layer plus annual forest loss year, updated annually | Alternative forest baseline — tree-cover threshold defines forest; loss year is used to back-date the mask |
| **FAO GAUL 2024 (Level 0)** | Global country boundary polygons maintained by FAO | Country selection and study-area clipping for every analysis |
| **JRC GHSL — Settlement Model + Population P2023A** (Pesaresi et al., 2024) | Built-up classification distinguishing small settlements from larger urban areas, masked by population presence | Small and large built-up classes contribute to the settlement-disturbance buffer |
| **DLR World Settlement Footprint Evolution** (Marconcini et al., 2020) | Annual 30 m global settlement footprint from 1985 to 2015 | Combined with GHSL to extend small-settlement extent further back in time |
| **GLAD Global Cropland (Potapov)** (Potapov et al., 2022) | Global 30 m cropland presence at multiple time steps between 2000 and 2019 | Cropland layer in the agriculture-disturbance buffer |
| **Global Pasture Watch v1** (Parente et al., 2024) | Annual 30 m grassland map separating cultivated from natural/semi-natural grasslands | Cultivated-grassland class contributes to the agriculture-disturbance buffer |
| **Descals Global Oil Palm Year-of-Planting** (Descals et al., 2024) | Global per-pixel year of oil palm establishment from 1990 to 2021 | Oil palm extent feeds both the agriculture-disturbance buffer and the plantation mask |
| **SDPT v2 — Spatial Database of Planted Trees** (Richter et al., 2024; WRI) | Global polygons of planted trees, separating planted forest from tree crops | Planted-forest class is reported separately as planted forest; tree-crop class contributes to the agriculture-disturbance buffer |
| **OSM Roads — PFF 33-region merge** (OpenStreetMap contributors, 2025) | OpenStreetMap road network collected globally in May 2025 | Road raster used in the road-disturbance buffer |
| **JAXA ALOS World 3D-30m DSM v3.2** (Tadono et al., 2016) | Global 30 m digital surface model | Source of the slope layer used to rescue forest on steep terrain; also exported as DEM and slope sidecars |
| **WDPA — World Database on Protected Areas** (UNEP-WCMC & IUCN, 2026) | Global protected-area polygons with IUCN category and year of designation | Long-designated strictly protected areas qualify forest for rescue from the disturbance mask |
| **FLII — Forest Landscape Integrity Index 2019** (Grantham et al., 2020) | 0–10 score per ~300 m pixel summarising landscape-scale forest integrity | Optional reference overlay shown alongside PFF outputs for comparison |
| **FDaP Forest Persistence 2020** (Forest Data Partnership, 2024) | Per-pixel 0–1 probability of continuous forest cover at 2020 | Optional reference overlay shown alongside PFF outputs for comparison |

---

## Page 2 — Datasets available in the tool but not currently driving outputs

| Dataset | What it is |
|---|---|
| **GRIP4 + Predicted AADT** (Meijer et al., 2018) | Global major-roads network with modelled annual average daily traffic at 1990, 2000 and 2015 |
| **JRC TMF v1_2025 — Deforestation Year** (Vancutsem et al., 2021) | Annual tropical-belt deforestation year layer |
| **GLC_FCS30D 1985–2022** (Zhang et al., 2024) | Global 30 m 35-class land cover with annual and 5-year products |
| **GISD30 1985–2020** (Zhang et al., 2022) | Global 30 m impervious-surface dynamic dataset |
| **GISA 1972–2019** (Huang et al., 2021) | Global 30 m impervious-surface area dataset with long time span |
| **DLR WSF 2015** | Single-year 10 m global settlement footprint for 2015 |
| **DLR WSF 2019** | Single-year global settlement footprint for 2019 |
| **LandScan Global** (Rose et al., 2025; ORNL) | Annual global population distribution at ~1 km |
| **FDAP Palm 2024a** (Forest Data Partnership, 2024) | Per-pixel oil palm probability layer |
| **FDAP Rubber 2024a** (Forest Data Partnership, 2024) | Per-pixel rubber probability layer |
| **FDAP Cocoa 2024a** (Forest Data Partnership, 2024) | Per-pixel cocoa probability layer |
| **OSM Water Layer** (sat-io / U-Tokyo) | Global water-body and canal raster derived from OpenStreetMap |
| **PFF Navigable Rivers (WDB)** | Navigable-river network derived from the World Data Bank river dataset |
| **Navigable Waterways USA** | National-scale navigable-waterway vector for the United States |
| **USA TIGER Roads** | National-scale US road vector from the US Census TIGER programme |
| **WUR Congo Basin Logging Roads** | Logging-road vector for the Congo Basin compiled by Wageningen University |
| **Microsoft Global Roads** | Global road vector released by Microsoft |
| **Ghost Roads — Asia / New Guinea** | Hand-mapped informal road network for Asia and New Guinea |
| **MapBiomas Brazil Roads** | National-scale Brazil road vector from MapBiomas |
| **WRI SBTN Natural Lands v1.1 (2020)** (Mazur et al., 2025) | Global natural-lands map at 2020 produced under the Science Based Targets Network |
| **European Primary Forests Database v2** (Sabatini et al., 2018) | Polygon database of mapped primary forest patches across Europe |
| **Tsinghua DESS China Terrace Map v1** (Cao et al., 2021) | National-scale terrace agriculture map for China |

---

Verified against pff_4.js v4.15.7-beta.1 and QGIS plugin v0.16.0-beta.1 on 2026-05-11.

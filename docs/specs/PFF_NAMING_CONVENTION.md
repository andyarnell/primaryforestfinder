# PFF Output Naming Convention (Option D)

*Decided 2026-04-26, refined with FRA-aligned schema 2026-04-27. See [planning/tasks_260425_merged.md → P1.13, P1.16, P1.19, P1.20](../../planning/tasks_260425_merged.md) for the backlog. Helper utility implemented in `pff_qgis_tools/utils.py` (Python) and `pff_4.js` (JavaScript) — see those modules for the canonical reference implementation.*

## Schema

```
[ISO3]_[platform]_[step][substep]_[layer_name].[ext]
```

| Component | Required | Notes |
|---|---|---|
| `[ISO3]_` | optional | ISO3 country code (e.g. `KEN`). Omit when no country selected. Always uppercase when present. Trailing underscore included. |
| `[platform]` | required | `gee` or `qgis`. **Use these exact strings — not `app` / `plugin`.** |
| `[step][substep]` | required | Two-digit step (`00`-`06`) optionally followed by a substep letter (`a`-`z`). Always leading-zero on the step. |
| `[layer_name]` | required | Snake-case layer descriptor. Drop `results_` / `refined_` / `validation_` qualifiers — the step number already encodes the production stage. |
| `.[ext]` | required | Standard file extension. `tif` for rasters, `gpkg` for vectors, `csv` for tables, `shp` for shapefile-zone outputs, `json` for metadata sidecars. |

## Step numbers

Step prefix encodes the **production stage** (where in the pipeline the file was made), not the action that saves it. Sortable alphabetically = workflow order. Numbers are policy-stable (changing them later is a breaking change).

| Step | Stage | Example file | UI section in plugin |
|---|---|---|---|
| `00` | Context (supplies ISO3) | — (no files of its own) | Country / Context |
| `01` | Time Period (supplies year) | — (no files of its own) | Time Period |
| `02` | **Forest Definition** | `02b_forest.tif`, `02d_naturally_regenerating_forest.tif`, `02c_plantations.tif` (when produced) | Forest Inputs / Forest Definition |
| `03` | Human Influence Inputs | `03a_roads.tif`, `03b_protection_legal.tif` (when user opts to save) | Human Influence Layers |
| `04` | **Refine — ecological viability** | `04a_primary_forest.tif` (the only Step 04 output -- pre-connectivity + combined coded moved to 03c/03d as outputs of the disturbance+protection tier logic) | Refine Output |
| `05` | Statistics | `05a_area_statistics.csv`, `05b_area_statistics_by_admin1.shp` | (right-panel in GEE; standard form section in QGIS) |
| `06` | Validation / Export | `06a_primary_forest_vector.gpkg`, `06b_primary_forest_dissolved.gpkg` | (right-panel in GEE; standard form section in QGIS) |

Step 02 is a **reframe** — formerly "Forest Inputs", now "Forest Definition" — because it covers both raw source layers (`02a_*`) and the FRA-aligned forest-type derivations (`02b`, `02c`, `02d`). See [Forest Definition (Step 02)](#forest-definition-step-02) below.

Step 04 means **ecological viability filtering only** — patch/thin-section removal via neighbourhood density + raster sieve. Anything that isn't viability-related does NOT belong at step 04, regardless of whether the word "refine" sounds general. Forest-type derivations (e.g. naturally regenerating forest = Natural − Primary) are stats numbers, not new step-04 outputs.

## Substep policy (DECIDED 2026-04-27)

**Input steps (`02`, `03`) — substep letter encodes semantic category.** Multiple files share a letter; the `layer_name` field disambiguates. This scales to user custom slots and dataset additions (e.g. splitting roads into small/large) without enumerating letters.

**Output steps (`04`, `05`, `06`) — substep letter is a unique, position-stable file ID.** `04a` always means "the headline result", etc. Adding a new substep is allowed; reusing or shifting existing letters is a breaking change.

| Step | Substep meaning | Why |
|---|---|---|
| `02` (input) | category-letter | Open set; `02b_forest`, `02d_naturally_regenerating_forest`, `02c_plantations` etc. — name disambiguates within categories |
| `03` (input) | category-letter | `03a_*` = disturbance inputs; `03b_*` = protection exceptions. New layers don't push toward `03j`/`03k`/... |
| `04` (output) | unique-letter | Small fixed set with meaningful production order |
| `05` (output) | unique-letter | Small fixed set |
| `06` (output) | unique-letter | Small fixed set |

## Forest Definition (Step 02)

Step 02 produces three forest-type layers that map onto the FRA hierarchy. Whichever ones get produced depends on user inputs (see [Variable output set](#variable-output-set-by-input-declaration) below).

```
02a_*                                 Source components (Hansen treecover2000_raw,
                                      Hansen lossyear_raw, GLAD tree_height_m) — when
                                      GEE produces them and user opts to save
02b_forest                            ≈ FRA Forest baseline (thresholded tree cover)
02d_naturally_regenerating_forest     ≈ FRA Naturally Regenerating Forest
                                      (Forest minus planted forest; INCLUDES primary as subset)
02c_plantations                       ≈ FRA Planted Forest (SDPT class 1 only — see P1.20)
```

### FRA framework + caveats

The tool's forest layers are **operational proxies** — they lean on the best globally-consistent datasets and apply the FRA framework as faithfully as those datasets allow. They are NOT an FRA classification. Official FRA numbers come from country submissions with local context the tool cannot replicate. Compare in spirit, not as ground truth.

**FRA decomposition (canonical):**

```
Forest = Naturally regenerating forest + Planted forest                  (mutually exclusive)
Naturally regenerating forest = Primary forest + Other naturally regenerating forest  (subset)
```

So "Primary forest" is a **subset of** Naturally regenerating forest, not a sibling category. There is no standalone "Natural forest" parent category in FRA — that term is sometimes used colloquially to mean either Primary or Naturally regenerating, but FRA uses the precise terms.

**The PFF mapping:**

```
Tree cover (Hansen + GLAD, thresholded)     ← physical canopy + height
   │
   ├─ 02b_forest                                ≈ FRA Forest
   │     │                                       (caveat: agricultural tree cover not yet
   │     │                                        filtered — see P1.18)
   │     │
   │     ├─ 02c_plantations                     ≈ FRA Planted forest
   │     │                                       (caveat: SDPT incompleteness, smallholders
   │     │                                        missing)
   │     │
   │     └─ 02d_naturally_regenerating_forest   ≈ FRA Naturally regenerating forest
   │            │                                (caveat: SDPT incompleteness; agricultural
   │            │                                 tree cover may remain pre-P1.18)
   │            │
   │            └─ 04a_primary_forest            ← naturally regenerating forest minus
   │                                              disturbance buffers + viability filter.
   │                                              SUBSET of 02c, not a separate category.
   │                                              (The headline PFF output.)
   │
   └─ Agricultural tree cover (oil palm, tree crops, agroforestry)
                                                ← routed via agriculture buffering toward
                                                  primary forest; NOT in 02c_plantations
                                                  (per P1.20 — FRA-correct mapping)
```

**Why 02b is "≈ FRA Forest" not "FRA Forest":** Hansen tree cover above thresholds doesn't exclude agricultural land use the way FRA does. Oil palm, agroforestry, and orchards meeting the canopy/height thresholds remain in `02b_forest` until removed downstream via the agriculture disturbance buffer. P1.18 may add an option to exclude agriculture from the Forest baseline directly.

**Why 02d is "≈ FRA Naturally Regenerating Forest" not "FRA Naturally Regenerating Forest":** The plantations layer used for subtraction (`02c`) is SDPT class 1 + national overrides; it misses smallholder plantations and may include some misclassified natural forest pixels. The result is "tree-covered areas not identified as planted" — a reasonable global-scale proxy, not a strict classification.

**Two tree-bearing FRA categories — important distinction:**

Both have trees meeting biophysical thresholds, both are human-managed, but FRA classifies them as fundamentally different things:

| FRA category | Examples | FRA Forest? | Schema position | Removed at |
|---|---|---|---|---|
| **Plantation Forest / Planted Forest** | Timber plantations (pine, eucalyptus), SDPT class 1, national plantations registries | YES — it's a *forest sub-type* (Forest = Naturally Regenerating + Planted) | `02c_plantations` | `02b → 02d` (subtracted from Forest to derive Naturally Regenerating) |
| **Agricultural tree cover** | Oil palm, rubber, fruit trees, agroforestry, orchards, SDPT class 2 (tree crops), Descals oil palm | NO — agricultural land use, not forest | (no top-level slot — input to P1.18 toggle) | `02a → 02b` (excluded from Forest baseline per P1.18 toggle) |

The everyday English word "plantations" is ambiguous — it can mean either. Per strict FRA terminology, the schema names follow:
- `02c_plantations` (today's name) ≈ FRA **Plantation Forest** (intensive monoculture forestry, narrow definition).
- "Agricultural tree cover" has no separate top-level filename — it's optionally subtracted from Forest at the 02a → 02b step (P1.18) and is also part of the broader `03a_agriculture` buffer source.

So an oil palm pixel:
- **Pre-P1.18**: stays in 02b_forest (agriculture filter not yet applied at baseline) → gets removed via the agriculture buffer toward primary forest
- **Post-P1.18 (toggle ON)**: removed at 02a → 02b → never enters the forest pipeline at all

A pine timber plantation pixel:
- Stays in 02b_forest (it IS forest per FRA — just planted, not natural)
- Removed at 02b → 02d (subtracted via 02c_plantations)
- May also contribute to the 03a_agriculture buffer (Role B — see "Plantations dual-role" below)

**Two distinct meanings of "agriculture" — important:**

- **FRA-aligned agriculture** (excluded from Forest baseline per FRA): the *tree-cover-meeting subset* of agricultural land — oil palm (Descals), SDPT class 2 tree crops, orchards, agroforestry. Things that have trees AND are managed for crop production. P1.18 uses this subset to derive a stricter `02b_forest`.
- **PFF buffered agriculture** (used for primary-forest disturbance buffering): a *broader* concept covering all human-use land that signals "humans nearby producing something" — cropland (annual crops without trees), pasture, oil palm, tree crops, etc. Not FRA-aligned and intentionally so — its purpose is proximity-based disturbance detection, not forest-type classification.

These two "agricultures" aren't interchangeable. Most of buffered agriculture (cropland, pasture) doesn't even meet tree cover thresholds, so it's not in `02b_forest` to begin with. Only the tree-cover-meeting subset matters for the FRA Forest derivation.

**Plantations dual-role — same layer, two consumption paths:**

`02c_plantations` lives in one file but feeds two distinct purposes:

- **Role A — Forest-type discriminator** (Step 02): subtracted from `02b_forest` to derive `02d_naturally_regenerating_forest`. The origin-based filter — plantations are removed because they're planted, not naturally regenerated.
- **Role B — Buffered disturbance signal** (Step 03): currently OR'd into the broader `03a_agriculture` source layer that gets distance-buffered toward primary forest. The proximity-based filter — pixels NEAR plantations are removed from candidate primary forest because plantations represent human management intensity (similar to agriculture).

These aren't double-counting: in Role A, plantation pixels themselves are removed (so they're already gone before primary is computed). Role B's effect on `04a_primary_forest` is the *buffer halo around plantation patches*, removing nearby naturally regenerating forest pixels within the buffer distance.

Currently no toggle to disable Role B; potential future UX = `[✓] Include plantations in disturbance buffer` checkbox.

**Primary vs Naturally regenerating: not separate stats rows.** Older drafts of this doc had "Naturally regenerating = `02d − 04a`" as a separate stats row. That was based on a wrong framing where Natural forest was a parent of Primary + Nat Reg as siblings. Per FRA, Primary IS a subset of Naturally regenerating — so the area `02d − 04a` is "Other naturally regenerating forest" (a sub-subset rarely worth surfacing), not a separate FRA category.

### Variable output set (by input declaration)

User declares what their forest input represents via the Step 02 dropdown (P1.19 — multi-level input declaration). What gets produced depends on declaration + which auxiliary layers are provided:

| Forest input declared as | Plantations layer | Files produced (Step 02) |
|---|---|---|
| Tree cover | yes (+ FRA agriculture) | `02b_forest`, `02d_naturally_regenerating_forest`, `02c_plantations` |
| Tree cover | yes (only) | `02d_naturally_regenerating_forest` (loose — agricultural tree cover not filtered), `02c_plantations` |
| Tree cover | no | None at step 02 (input passes through to 04 directly) |
| Forest (FRA) | yes | `02b_forest` (= input), `02d_naturally_regenerating_forest`, `02c_plantations` |
| Forest (FRA) | no | `02b_forest` (= input) |
| Naturally regenerating forest | n/a | `02d_naturally_regenerating_forest` (= input) |

Files only exist when actually computed. `run_metadata.json` records which layers were produced, which were skipped, and why.

## FRA mapping reference

Final state after P1.16 + P1.18 + P1.20 land. "Today" deltas noted in caveats column.

### FRA mapping by schema slot

| Slot | FRA name | Built from | What's removed at this step | Caveats |
|---|---|---|---|---|
| `02a_hansen_treecover2000_raw` | Tree cover (canopy %) | Hansen GFC treecover2000 | — (raw data) | Year-2000 baseline; doesn't account for subsequent loss/gain |
| `02a_hansen_lossyear_raw` | Tree-cover loss year | Hansen GFC lossyear | — (raw data) | Encodes year of detected loss 2001-2024; not absence at year 2000 |
| `02a_glad_tree_height_m` | Tree canopy height | GLAD tree height (per year) | — (raw data) | Per-year snapshot; height-only — no land-use info |
| `02b_forest` | ≈ Forest (FRA) | Tree cover (canopy ≥ X% AND height ≥ Y m) | **After P1.18**: agriculture pixels removed (cropland + pasture + oil palm + SDPT class 2 tree crops). **Today (pre-P1.18)**: nothing removed at this step — agriculture filtering only happens at the disturbance-buffer stage on the way to primary | "≈" because: (a) thresholds are biophysical proxies for FRA's land-use definition; (b) without P1.18, agricultural tree cover stays in baseline; (c) FRA's 0.5 ha minimum patch size not enforced here |
| `02d_naturally_regenerating_forest` | ≈ Naturally regenerating forest (FRA) | `02b_forest` MINUS `02c_plantations` | Planted forest (SDPT class 1 — timber, eucalyptus, pine, national overrides) subtracted | "≈" because: (a) SDPT misses smallholders → some planted areas remain in "naturally regenerating"; (b) SDPT misclassifications → some real natural forest wrongly excluded; (c) **today (pre-P1.20)** also subtracts SDPT class 2 + Descals oil palm via wrong-bucket — area is smaller-but-mislabelled today, will rebalance after P1.18+P1.20. **Includes Primary as a subset.** |
| `02c_plantations` | ≈ Planted forest (FRA) | SDPT class 1 (Planted Forests) ∪ national plantations override | — (this IS the planted forest layer, not derived by subtraction) | "≈" because: (a) SDPT incomplete; (b) **today (pre-P1.20)** also includes SDPT class 2 (tree crops) + Descals oil palm — stat is inflated for FRA Planted Forest comparison; (c) FDAP commodity layers stay disabled (commission errors in primary forest) |
| `03c_pre_connectivity_primary_forest` | (Step 03 OUTPUT) | Tier analysis output (combined disturbance + protection logic) | Forest pixels that survived disturbance buffers AND/OR got rescued by protection exceptions. The OUTPUT of Step 03's tier logic; INPUT to Step 04's viability filter. | Useful for diagnosing whether the viability filter (Step 04) is removing too much / too little |
| `03d_combined_coded_raster` | (Step 03 debug) | Tier outcomes per pixel | 6-class coded raster (1-6) showing which tier rule kept/excluded each pixel: 1=inside buffer, 2=outside buffer, 3=steep slope rescue, 4=not rescued by slope, 5=protected rescue, 6=not rescued | Optional output; off by default |
| `04a_primary_forest` | ≈ Primary forest (PFF target — subset of `02d`) | `03c_pre_connectivity_primary_forest` MINUS ecological viability fails | Patch geometry too small (sieve) or too thin (neighbourhood density). The Step 04 ecological viability filter is the ONLY transformation here -- disturbance buffer + protection logic happened upstream at Step 03. | "≈" because: (a) "naturalness" inferred from disturbance proximity (Step 03) — not species/origin data; (b) buffer distances are heuristics, not field-validated; (c) viability thresholds (min hectare, density radius) are global defaults not country-tuned; (d) inherits all upstream `02d` caveats. **Per FRA, Primary is a subset of Naturally regenerating, not a separate category.** |
| (stats panel inline) Naturally regenerating forest area | ≈ FRA Naturally regenerating forest area | `02d_naturally_regenerating_forest` raster | Pixel-counted area at the user-selected stats scale | Includes Primary by design (subset). Stats panel renders as parent of Primary in the hierarchy view |
| `05a_area_statistics` | (stats summary) | Forest-class layers (`02b`, `02c`, `02d`, `04a`) | Zonal area sums per class, in kha | Plus per-zone breakdowns when user supplies admin zones |
| `05b_area_statistics_by_admin1` | (zonal breakdown — plugin only) | Same as 05a + admin1 polygons | Per-zone area totals as shapefile attributes | Useful for sub-national reporting |
| `06a_primary_forest_vector` | (Stage 7 vector) | `04a_primary_forest` raster | Polygonise + optional simplify (CEO sampling prep) | Caveat: simplify > 0 can introduce self-intersection artefacts |
| `06b_primary_forest_dissolved` | (sampling boundary) | `06a` polygons | Dissolve to multipart for area-stratified sampling boundary | — |
| `06c_<forest>_vector` | (forest baseline vector) | `02d` if available, else `02b` | Polygonise the upstream forest baseline | Filename carries the upstream layer name (`naturally_regenerating_forest_*` or `forest_*`) |
| `06d_<forest>_dissolved` | (forest baseline dissolved) | `06c` polygons | Dissolve to multipart | — |

### Step 03 inputs — not FRA categories themselves

These are inputs *to* the primary forest computation, not FRA forest categories. No FRA name applies.

| Slot | What it is | Source | Role |
|---|---|---|---|
| `03a_roads` | Roads raster | OSM / Microsoft Roads | Disturbance — buffered, removes nearby pixels |
| `03a_builtup_small` / `03a_builtup_large` | Built-up areas | GHSL / WSF / GISD / GISA | Disturbance — buffered |
| `03a_agriculture` | Agricultural land | GLAD croplands ∪ pasture ∪ Descals oil palm ∪ SDPT class 2 (post-P1.20) | Disturbance — buffered |
| `03a_custom_<userlabel>` | User-supplied | User raster | Disturbance — buffered |
| `03b_protection_legal` | WDPA protected areas | WDPA filtered by status + designation date | Protection exception — preserves forest from disturbance buffer |
| `03b_protection_legal_unfiltered_vector` | WDPA raw | WDPA all features | Reference vector |
| `03b_protection_natural_dem` | Elevation | ALOS DSM | Source for slope computation |
| `03b_protection_natural_slope` | Steep slope | Slope ≥ threshold from DEM | Protection exception — naturally protected |

### Two "agricultures" — distinction matters

| | FRA-aligned agriculture (P1.18) | PFF buffered agriculture (existing) |
|---|---|---|
| **What's in it** | Oil palm + SDPT class 2 tree crops + agroforestry + orchards (tree-cover-meeting subset only) | Cropland + pasture + oil palm + SDPT class 2 + plantations (broader) |
| **Used for** | Excluded from Forest baseline (per FRA Forest = land use + biophysical) — derives FRA-strict `02b_forest` | Distance-buffered as disturbance signal toward primary forest |
| **FRA-aligned?** | Yes | No (intentionally — proximity-based, not classification-based) |
| **Schema slot** | Subset of `03a_agriculture` (or future dedicated layer) | `03a_agriculture` |

These are different things and shouldn't be conflated. Most of buffered agriculture (cropland, pasture without trees) doesn't even meet tree cover thresholds, so isn't in `02b_forest` to begin with — only the tree-cover-meeting subset matters for the FRA Forest derivation.

### Stats panel layout (after P1.16 + P1.17)

When plantations refinement runs, the stats panel renders the FRA hierarchy with Primary as a subset of Naturally regenerating:

```
Forest (≈FRA def):                            X km²    [FRA 2025: Y ✓]
   └─ Naturally regenerating forest:          X km²    [FRA 2025: Y ✓]
         └─ Primary forest:                   X km²    [FRA 2025: Y ✓]   ← subset
```

No separate "Planted forest" / Plantations area row — the layer is used as an
input to the nat-reg derivation, not reported as a forest-type stat. Users who
want planted-forest area can compute it directly from `02c_plantations.tif`.

When NO plantations layer is provided: only Forest + Primary rows shown — no nat reg derivation possible. Rows are hidden (not "—") when the corresponding layer wasn't produced.

### Cross-step caveats (apply throughout)

These limitations propagate down the hierarchy and are worth surfacing once on the About page rather than repeating per layer:

| Caveat | Affects | Why it matters |
|---|---|---|
| Hansen tree cover only counts canopy ≥ 5m at maturity | `02a`, all downstream | Misses regenerating forest under 5m; misses sparse woodland canopies |
| Hansen tree cover thresholds (10-30%) are user-tunable | `02b`, all downstream | Different runs use different thresholds; comparisons need to match |
| FRA's 0.5 ha minimum patch size not enforced at `02b` | `02b`, `02c` | Tiny tree clusters that wouldn't be FRA Forest still count |
| FRA's land-use definition not strictly captured | `02b`, `02c` | Even with P1.18, agriculture detection is dataset-limited; agroforestry edge cases hard to classify |
| SDPT v2 incomplete | `02c`, `02d` | Smallholder plantations missing; older plantings underrepresented in some regions |
| Descals oil palm time series only | `03a_agriculture` | Pre-2010 oil palm may be missed; uncertainty in recent years |
| FDAP commodity layers DISABLED | `03a_agriculture` | Smallholder rubber, cocoa, palm not captured outside SDPT — commission errors in primary forest too high to enable (see memory `project_fdap_commission_errors.md`) |
| Disturbance buffer distances are global defaults | `04a` | Country-specific tuning would improve accuracy but isn't workflow default |
| FRA submission numbers come from country reports | All comparator rows | Tool numbers compared in spirit, not as ground truth — country submissions include local context the tool can't replicate |

### Pixel flow for a single forest area

```
Tree cover pixel exists? (Hansen + GLAD thresholds)
   │
   ├─ NO  → not in any layer
   │
   └─ YES → enters 02b_forest
              │
              │   [P1.18 if shipped:]
              │   Is it FRA-aligned agriculture (oil palm / tree crops /
              │   agroforestry — i.e. tree-cover-meeting agricultural land)?
              │      ├─ YES → removed from 02b_forest, stays in 03a_agriculture
              │      └─ NO  → stays in 02b_forest
              │
              │   (Note: cropland/pasture without trees are NOT relevant here
              │    — they don't meet tree cover thresholds, so they were never
              │    in 02b_forest in the first place. They DO appear in the
              │    broader buffered 03a_agriculture, but only matter for primary
              │    forest disturbance buffering, not for Forest definition.)
              │
              ├─ Is it planted forest (SDPT class 1)?
              │      ├─ YES → in 02c_plantations, NOT in 02d_naturally_regenerating_forest
              │      └─ NO  → in 02d_naturally_regenerating_forest
              │
              └─ [for 02c pixels:]
                  Is it within disturbance buffer (and not under protection)?
                      ├─ YES → removed (counts as "Other naturally regenerating", a sub-subset)
                      └─ NO  → in 04a_primary_forest (subset of 02d)
```

## Step 03 — Human Influence Inputs

Two semantic categories under Step 03; substep letter encodes the category.

```
03a_roads                                    ← disturbance inputs (get buffered)
03a_builtup_small
03a_builtup_large
03a_agriculture                              ← cropland + pasture + oil palm + SDPT class 2 (per P1.20)
03a_custom_<userlabel>                       ← unbounded — N user custom slots
03b_protection_legal                         ← protection exceptions (preserve forest from buffers)
03b_protection_legal_unfiltered_vector
03b_protection_natural_dem
03b_protection_natural_slope
```

Splitting an existing layer (e.g. `03a_roads_small` and `03a_roads_large`) requires no schema change — the category letter accommodates open-ended additions.

**Plantations does NOT have its own Step 03 entry.** The raw plantations layer lives at `02c_plantations` (Forest Definition), where its primary semantic role (forest-type discriminator) sits. If the user opts to also use plantations as a buffered disturbance, that's a checkbox toggle that consumes the `02c` layer into the agriculture buffer — no separate `03_plantations` file is produced.

## Step 04 — Refine Output (ecological viability)

```
04a_primary_forest                          ← headline PFF result (after viability filter)
```

(Pre-connectivity primary forest and combined coded raster moved to `03c` / `03d` as outputs of the Step 03 disturbance+protection tier logic, since they're produced before the Step 04 viability filter.)

`04a` is the only Step 04 output. **Nothing else lives at step 04** — forest-type derivations (Forest, Naturally regenerating, Planted) belong at step 02; tier-logic outputs (pre-connectivity, combined coded) belong at step 03; stats CSV belongs at step 05; vectorisations belong at step 06.

Substeps are stable: adding a new substep is allowed (`04d`, `04e`); reusing or shifting existing letters is a breaking change.

## Stats panel (Step 05) — FRA-faithful breakdown

Stats reports areas matching FRA reportable categories. Hidden rows when input/data isn't available — don't surface things that didn't happen.

```
─────────────────────────────────────────────────────────────────
Forest (≈FRA def):                            2,705 km²    [FRA 2025: 2,725 ✓ within 1%]
   └─ Naturally regenerating forest:          2,612 km²    [FRA 2025: 2,650 ✓ within 1.5%]
         └─ Primary forest:                   1,418 km²    [FRA 2025: 1,400 ✓ within 1.4%]
─────────────────────────────────────────────────────────────────
```

- Per FRA: Forest = Naturally regenerating forest + Planted forest (mutually exclusive)
- Per FRA: Naturally regenerating forest INCLUDES Primary forest as a subset
- FRA comparators come from `modules/fraStats.js`: forest area (235 countries), primary forest (56), naturally regenerating (86)
- **Planted forest area is NOT shown as a stats row** — `02c_plantations` is consumed as an input to the nat-reg derivation, not reported as a separate forest-type. Users who want plantation area can compute it directly from the saved `02c_plantations.tif` raster.
- Rows are hidden (not shown as "—") when the corresponding layer wasn't produced this run
- "Other naturally regenerating forest" = `02c − 04a` is rarely worth a separate row — surface only if a workflow specifically needs that subset

## Intermediates

Files that aren't headline outputs (working files, prepared inputs, distance surfaces) live under `intermediates/` with **no top-level step prefix**. The folder location + platform tag (`qgis_` — only QGIS produces intermediates) carries the "this is a working file" semantic.

```
intermediates/
  prepared/                ← reprojected + aligned inputs (reusable across runs)
    forest.tif
    naturally_regenerating_forest.tif     ← when computed
    plantations.tif
    roads.tif, builtup_small.tif, builtup_large.tif, agriculture.tif
    protected.tif, dem.tif, slope.tif
    custom_1.tif, custom_2.tif, custom_3.tif

  distances/               ← cached distance surfaces
    dist_roads.tif, dist_builtup.tif, dist_builtup_large.tif,
    dist_agriculture.tif
    dist_custom_1.tif, ...

  tier1_undisturbed.tif    ← tier-logic byproducts
  tier2_steep.tif
  tier3_protected.tif
  forest_inside_buffers.tif
  steep_slope.tif, gentle_slope.tif

  anthropogenic_mask.tif   ← combined buffered disturbance mask

  refine_step_a_neighbourhood.tif    ← (only when both refine steps run)
  refine_step_b_sieve_unmasked.tif   ← (only when refine step b runs)

  _vectorize/              ← Stage 7 vectorise scratch
  _zonal_work/             ← Stage 6 zonal stats temporary workspace
```

## Rules

1. **Always leading zero** on step (`01`, not `1`).
2. **No colons in filenames.** Use underscores or dashes if you need separators within a layer name.
3. **Numbering is stable.** Once published, step numbers + substep letters don't change without a documented breaking-change migration.
4. **Platform tag is `gee` or `qgis`.** Never `app`, `plugin`, `module`, or anything else.
5. **Filename step encodes production stage**, not the user-facing UI section it's controlled from. (UI sections may rearrange; file numbers don't.)
6. **Layer names drop the production-category prefix.** `04a_primary_forest.tif`, not `04a_results_primary_forest.tif` — the `04` already says "this came from Refine".
7. **ISO3 prefix is optional.** Include when a country was selected in the run; omit otherwise.
8. **Input substeps are category-letters; output substeps are unique-letters.** See [Substep policy](#substep-policy-decided-2026-04-27).
9. **Step 02 file slots are fixed** (`02a_*` source / `02b_forest` / `02d_naturally_regenerating_forest` / `02c_plantations`). New forest-type derivations don't get new Step 02 letters — they live in stats or as intermediates.
10. **Step 04 = ecological viability only.** Anything that isn't patch/sieve viability filtering does not belong at step 04.

## Helper utility

Both tools ship a `generate_layer_name()` / `generateLayerName()` helper that constructs filenames per this schema. Use it instead of manual string concatenation so all call sites are consistent.

**Python** (`pff_qgis_tools/utils.py`):
```python
from pff_qgis_tools.utils import generate_layer_name, PLATFORM_QGIS

generate_layer_name('KEN', PLATFORM_QGIS, '04a', 'primary_forest')
# -> 'KEN_qgis_04a_primary_forest.tif'

generate_layer_name(None, PLATFORM_QGIS, '06b',
                    'primary_forest_dissolved', ext='gpkg')
# -> 'qgis_06b_primary_forest_dissolved.gpkg'
```

**JavaScript** (`pff_4.js`):
```javascript
generateLayerName('KEN', PLATFORM_GEE, '05a', 'area_statistics', 'csv')
// -> 'KEN_gee_05a_area_statistics.csv'

generateLayerName(null, PLATFORM_GEE, '04a', 'primary_forest')
// -> 'gee_04a_primary_forest.tif'
```

Both helpers raise / throw on `platform ∉ {'gee', 'qgis'}`, missing `step`, or missing `name` — typos at call sites fail fast.

## Folder examples

### Plugin run, no country selected (single export)

```
my-output-folder/
  qgis_02b_forest.tif                        ← when input declared as Forest or derived from tree cover
  qgis_02d_naturally_regenerating_forest.tif ← when plantations subtraction ran
  qgis_04a_primary_forest.tif
  qgis_03c_pre_connectivity_primary_forest.tif
  qgis_03d_combined_coded_raster.tif         ← (when ticked)
  qgis_05a_area_statistics.csv
  qgis_06a_primary_forest_vector.gpkg        ← (when Stage 7 ticked)
  qgis_06b_primary_forest_dissolved.gpkg     ← (when Stage 7 ticked)
  run_metadata.json
  intermediates/
    ... (see Intermediates section above)
```

### Plugin run, ISO3 = KEN, Forest input + plantations

```
my-output-folder/
  KEN_qgis_02b_forest.tif
  KEN_qgis_02d_naturally_regenerating_forest.tif
  KEN_qgis_04a_primary_forest.tif
  KEN_qgis_03c_pre_connectivity_primary_forest.tif
  KEN_qgis_05a_area_statistics.csv
  KEN_qgis_05b_area_statistics_by_admin1.shp ← (when zonal stats ticked)
  KEN_qgis_06a_primary_forest_vector.gpkg
  KEN_qgis_06b_primary_forest_dissolved.gpkg
  KEN_run_metadata.json
  intermediates/...
```

### GEE run, ISO3 = KEN, two years (2010 + 2020)

```
GEE Drive folder/
  KEN_gee_02a_hansen_treecover2000_raw_30m.tif
  KEN_gee_02a_hansen_lossyear_raw_30m.tif
  KEN_gee_02a_glad_tree_height_m_2010_30m.tif
  KEN_gee_02a_glad_tree_height_m_2020_30m.tif
  KEN_gee_02b_forest_2010_30m.tif
  KEN_gee_02b_forest_2020_30m.tif
  KEN_gee_02d_naturally_regenerating_forest_2010_30m.tif    ← (P1.16 — new export)
  KEN_gee_02d_naturally_regenerating_forest_2020_30m.tif
  KEN_gee_02c_plantations_2010_30m.tif       ← SDPT class 1 only (per P1.20)
  KEN_gee_02c_plantations_2020_30m.tif
  KEN_gee_03a_roads_2010_30m.tif
  KEN_gee_03a_roads_2020_30m.tif
  ... (per-year for each step)
  KEN_gee_04a_primary_forest_2010_30m.tif
  KEN_gee_04a_primary_forest_2020_30m.tif
  KEN_gee_05a_area_statistics_2010.csv
  KEN_gee_05a_area_statistics_2020.csv
  KEN_gee_run_metadata_2010_30m.geojson
  KEN_gee_run_metadata_2020_30m.geojson
```

(Year suffixes — `_YYYY` — on per-year files. Stable substep letters across years so e.g. `04a_primary_forest_2010.tif` and `04a_primary_forest_2020.tif` pair up cleanly.)

### Mixed GEE + QGIS folder (the auto-pairing motivation)

```
country-bundle/
  KEN_gee_02b_forest_2020_30m.tif             ← raw input from GEE
  KEN_qgis_04a_primary_forest.tif             ← QGIS-derived result
  KEN_gee_04a_primary_forest_2020_30m.tif     ← GEE-derived result for compare
  KEN_qgis_05a_area_statistics.csv
  KEN_gee_05a_area_statistics_2020.csv
```

Sorted alphabetically the file groups naturally by country + step, with the platform tag making the source obvious. A future auto-collection tool (P2.21) can scan this folder, pair `gee_` and `qgis_` outputs at matching steps, and drive automated comparison workflows.

## What NOT to use

- `app`, `plugin`, `tool`, `module` as platform tags. Use `gee` / `qgis`.
- `1`, `2`, `3` (no leading zero) for step numbers. Use `01`, `02`, `03`.
- Colons (`:`) anywhere in filenames.
- `results_`, `refined_`, `validation_` prefixes on layer names. Step number encodes that.
- Spaces. Use underscores.
- Capital letters in layer names (snake_case only). ISO3 is the only uppercase part.
- `04d_*` for forest-type derivations. Step 04 is ecological viability only.
- Unique substep letters on input steps (no `03e_plantations`, `03f_protection_*`). Use category letters (`03a` / `03b`).
- "Naturally regenerating forest" as a saved file. Stats only.
- "Plantations" as the bucket name for oil palm + tree crops + planted forest. Per FRA, plantations = planted forest only; oil palm + tree crops = agriculture (per P1.20).

## Migration status

- **P1.13 plugin side:** ✅ shipped 2026-04-27 (commit `8bf5960`). All plugin output paths migrated to Option D via `generate_layer_name()`. Filename `04d_forest_naturally_regenerating.tif` slated for rename to `02d_naturally_regenerating_forest.tif` per the FRA-aligned schema (P1.16).
- **P1.13 GEE side:** WIP on branch `feat/v1-release-batch10` (uncommitted). All `Export.image.toDrive` / `Export.table.toDrive` description / fileNamePrefix calls migrated via new `mkExportName()` helper. Pending paste-into-Code-Editor verify cycle.
- **P1.16-P1.20:** captured in `planning/tasks_260425_merged.md`. Code changes not yet started.

## See also

- [`planning/tasks_260425_merged.md`](../../planning/tasks_260425_merged.md) — backlog entries P1.13, P1.16, P1.17, P1.18, P1.19, P1.20, P2.20, P2.21
- [`pff_qgis_tools/utils.py`](../../pff_qgis_tools/utils.py) — Python helper + constants
- [`pff_4.js`](../../pff_4.js) — JavaScript helper + constants
- [`modules/fraStats.js`](../../modules/fraStats.js) — FRA 2025 lookup tables (forest area, primary forest, naturally regenerating)
- [`modules/timeseriesAnthro.js`](../../modules/timeseriesAnthro.js) — `processingPlantationsMosaic()` (slated for FRA-correct refactor per P1.20)

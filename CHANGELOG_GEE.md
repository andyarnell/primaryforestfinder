# Changelog — pff_4.js (GEE app)

## v4.16.0-beta.9 (validation overlays + download UX)
About panel (PR #42):
- Added two links after "Source code on GitHub": "Data inputs (global datasets)" (→ docs/datasets_global.md) and "Report an issue / request a feature" (→ GitHub issues).
- "Save to computer" → "Save to computer (experimental)"; an "⚠ Experimental" note added at the top of the Validation panel.

Validation / reference overlays (PR #42):
- Toggling a reference overlay (FLII / FDaP / Custom) now adds/removes just that overlay instead of re-running the whole analysis (reference layers are independent of the primary-forest computation). New buildReferenceLayers() (shared with the full run) + refreshReferenceLayers() targeted swap; the Validation checkboxes call the latter. No "Update Analysis" press needed.
- Legend: reference layers now appear. FLII rendered GIS-style — a "FLII (forest integrity)" title with indented class rows: high (≥ 9.6) blue, medium (6.0–9.6) orange (colours match the map palette). FDaP label gains its >0.90 cutoff. Generic {title, classes:[…]} legend form for any multi-class layer.

Download panel (PR #43):
- "Save to computer" no longer appears to hang: the blocking work (autoGrid + bounds.getInfo() + tiling) is deferred one tick via ui.util.setTimeout so the "Calculating tiles…" message paints first.
- Script mode: the "mosaic the tiles" note now follows the run instruction (run script → tiles download → mosaic), then the "links expire" note. The full Python script is no longer dumped inline by default — a new "Preview Python code" toggle in Advanced (off by default) shows it under a "Code preview:" header.
- "Preview tiles" button → "Check tile count", its result now shows directly beneath the button (was the far-down status label) with a one-line description; its blocking getInfo() is likewise deferred.

## Changes vs v4.14.0 (Export panel labels + ordering)
- Every Export-Layers tickbox label now shows the step prefix in parentheses (e.g. "(02c)", "(03a)") so users see which file-name segment the export will produce.
- Tickbox declaration order, the select-all-toggle list, and the panel widget order all rewritten to follow the schema: 00 -> 02 -> 03 (a then b) -> 03c -> 04 -> sidecar. Matches the production-step order used in mkExportName().
- "Pre-connectivity forest" tickbox renamed to "Pre-refinement primary forest (03c)". The exported filename also changes from 03c_pre_connectivity_primary_forest_*.tif to 03c_pre_refinement_primary_forest_*.tif -- matching the Batch 27.1 layer/legend rename. Files exported under v4.14.0 or earlier with the legacy name are still valid as standalone files; just won't auto-fit pipelines that hardcode the new name.
- "Primary forest (final)" -> "Primary forest -- final (04a)".
- "Built-up (small)" / "Built-up (large)" -> "Built-up small (03a)" / "Built-up large (03a)".
- "DEM" / "Slope" -> "DEM (03b)" / "Slope (03b)".
- Other labels reorganised similarly for consistency.

## Changes vs v4.13.4 (Batch 28 -- forest-export naming truthfulness)
- 02c_forest export now honours its FRA-Forest name. When the existing "Refine to forest" toggle is on (default), the export contains forest_map MINUS olwtc -- matching FRA-Forest = Tree cover - OLTC. When the toggle is off, falls back to the pre-Batch-28 behaviour (raw thresholded tree cover) and surfaces a Note in the export-status label so the user knows the file isn't FRA-narrowed in that mode.
- 02e_naturally_regenerating_forest now chains off the FRA-narrowed Forest baseline (forest_map_fra) instead of raw forest_map. Matches the FRA hierarchy: Tree cover -> Forest (-OLTC) -> NRF (-Planted) -> Primary. When the toggle is off, forest_map_fra == forest_map so 02e behaviour is identical to pre-Batch-28.
- New 02a_forest_raw export tickbox ("Tree cover -- thresholded, pre-FRA-filter (02a)"). Default OFF. Exports the pre-OLTC raw thresholded tree cover. Useful for users who want to apply FRA-narrowing themselves with a national OLTC dataset different from the global one, or as a debugging baseline.
- 02c_forest tickbox label updated to make the FRA semantics explicit: "Forest -- FRA-aligned baseline (02c)".
- Files exported under v4.13.4 with the same toggle-on settings will differ in v4.14.0: 02c_forest will be smaller (urban tree cover removed; oil palm + tree-crops removed). 02e likewise. 04a_primary_forest unchanged (was already OLTC-narrowed via the analysis tier-logic path).
- BREAKING IF YOU HAVE TIGHT EXTERNAL TOOLS that hardcoded pre-Batch-28 02c content semantics. The legacy-rename script earlier today mapped pre-Batch-28 _1_forest_* legacy files to _02a_forest_raw_* on disk -- this batch makes that mapping retroactively correct. New 02c_forest exports are the different (FRA-narrowed) version that pre-Batch-28 was missing.

## Changes vs v4.13.3 (OSM vector clip tightening)
- getOsmRoadsAll(aoi) in modules/timeSeriesAnthro.js now applies a TWO-STAGE clip per child FC: filterBounds(aoi) for the cheap spatial-index fast-path, plus ee.Filter.intersects for polygon-precise filtering that drops features which pass the bbox but don't actually touch the AOI polygon. For narrow / irregular countries (Bhutan, Indonesia archipelago) the bbox includes a lot of empty corner area that the index filter alone can't reject; the second-stage intersects fixes that without sacrificing the per-asset spatial-index pushdown across 33 children. Per-feature cost is bounded by the AOI's road density, not the global dataset, so this remains cheap on small AOIs.
- User-side test recommended on Indonesia / Russia / Brazil to quantify the runtime + file-size improvement on bbox-loose AOIs.

## Changes vs v4.13.2 (Batch 27.1 -- UX feedback round, GEE side)
- Right-panel section "Export Layers" renamed to "Outputs" to mirror the QGIS plugin's §6 Outputs.
- Stats waiting-label bug fix: when "Show Area Statistics" was clicked, the in-flight calcLabel could read e.g. "Calculating naturally regenerating forest area..." while the row actually computing was Primary (or vice versa). Replaced the parallel-fired evaluate() pattern with a sequential row queue that advances calcLabel as each item begins. Slightly slower but the label now always matches the row in flight.
- Legend Forest group reordered: HEADLINE OUTPUT FIRST (Primary forest), then back DOWN the refinement chain (Pre-refinement primary, Naturally regenerating, Forest, Tree cover). Reads top-to-bottom as "what I made" preceding "what it was made from".
- "Forest outside buffers" layer + legend label renamed to "Pre-refinement primary" -- the old name misled (the layer INCLUDES forest INSIDE buffers rescued by slope or protected-area status). New name pairs with "Refine Output" section: Refine Output produces primary forest from the pre-refinement primary forest. NAME_TO_KEY + pffLayerNames maps gain the new name; legacy "Forest outside buffers" string kept so users with stale projects can still see the old layer get cleaned up.
- Buffer Exceptions OFF by default: enableSlope + enableProtectedAreas ship unticked. Steep-slope and protected-area rescues are explicit opt-in to avoid surprising "primary forest in cropland" pixels in countries with sparse PA coverage. Reset Defaults matches.
- "Add input + buffer layers to map" toggle moved from TOP of the Human Influence panel to the BOTTOM. Distracting at the top. Default value (false) unchanged.
- About panel: re-added a small ✕ close button at the top-right of the content as a redundant-but-helpful close shortcut for users who've scrolled inside the panel. Toggle button still works as the primary affordance.
- Settings panel: small grey hint labels under Save/Load Settings + Download Run Metadata clarify the split (portable config vs per-run snapshot). Both artifacts stay; the wording explains when to use each.

## Changes vs v4.13.1 (About panel tidy + relocated to right-side dropdown)
- Removed verbatim FRA 2025 definitions block from the About panel (FOREST / NRF / PRIMARY FOREST). Definitions live on the FAO site; the panel now links there instead. Reduces scroll length + avoids duplicating canonical text we don't own.
- Rewrote the "How PFF outputs map to FRA" section as long-form paragraphs (one per output: 02b, 02c, 02d, 02e, 04a) instead of a cramped ≈ table. Reads cleanly without monospace alignment.
- Dropped the "Thresholds vs declaration" paragraph (too detailed for the About panel; covered by the dropdown's own tooltip and the workshop guide).
- Kept the rubber caveat (SDPT class 2 vs FRA Note 7) -- workshop-relevant for rubber-heavy countries.
- Resources section: dropped placeholder Documentation link (no separate docs site exists); replaced placeholder source-code link with the canonical GitHub repo (https://github.com/andyarnell/primaryforestfinder); contact updated to andrew.arnell@fao.org.
- About is no longer a full-width banner below the top bar. It is now a right-panel dropdown ('▶ About') matching the existing Stats / Config / Export pattern -- mutually exclusive with its peers (opening one closes the others). The top-bar 'About' button is removed; the in-app FRA-info ⓘ link in the Tree Cover panel now opens the right-panel About dropdown directly.

## Changes vs v4.13.0 (Batch 25.1 -- 02-step renumber for OLWTC)
- Re-lettered step 02 so OLWTC slots in BEFORE planted forest, matching the Tree Cover panel's pipeline order (raw tree cover -> subtract OLWTC = Forest -> subtract Planted forest = NRF). Each "discriminator letter N" is now followed by its "output letter N+1" -- pipeline reads top-to-bottom alphabetically.

  | NEW SCHEMA | OLD | ROLE |
  |---|---|---|
  | 02a_hansen_* / glad_* | (unchanged) | Raw inputs |
  | 02b_other_land_with_tree_cover | 03a_other_land_with_tree_cover | OLWTC discriminator (subtracted at step 1) |
  | 02c_forest | 02b_forest | FRA Forest (output of step 1) |
  | 02d_planted_forest | 02c_planted_forest | Planted-forest discriminator (subtracted at step 2) |
  | 02e_naturally_regenerating_forest | 02d_naturally_regenerating_forest | FRA NRF (output of step 2) |

- Export tickbox labels updated to show new letters. About-panel "How PFF outputs map to FRA" block updated + new entry for 02b_other_land_with_tree_cover.
- BREAKING: any cached GEE outputs from v4.13.0 or earlier with the old filenames (03a_other_land_with_tree_cover, 02b_forest, 02c_planted_forest, 02d_naturally_regenerating_forest) keep working as standalone files but won't auto-fit any pipeline that hardcodes the new names. Plugin updated in lockstep (v0.13.0) so plugin-side outputs use the same letters.

## Changes vs v4.12.2 (Batch 25 -- OLWTC includes urban tree cover)
- OLWTC bucket expanded to match FRA Note 10 ("Other Land with Tree Cover" = non-Forest land that is tree-covered, including urban tree cover). Previously OLWTC was only oil palm + SDPT class 2 tree crops. Now it also includes URBAN TREE COVER: tree-covered pixels falling inside built-up small or large. Each urban-tree-cover pixel must genuinely have tree cover (intersection with the chosen tree-cover source) -- so no bare-rooftop overshoot in the OLWTC layer.
- Affected sites:
  - Forest-baseline exclusion (analysis "Refine to forest"): narrows 02b_forest by ALL of OLWTC including urban tree cover -- FRA-strict (urban land is non-Forest).
  - 03a_other_land_with_tree_cover export: includes urban tree cover. Cleaner FRA-aligned export for plugin / external use.
- Behaviour:
  - 02b_forest area shrinks slightly in cities -- FRA-correct.
  - 04a_primary_forest essentially unchanged: built-up was already removed via the disturbance-buffer step at any positive built-up buffer distance.
  - Agriculture aggregation (used for buffer calc) is NOT changed: built-up has its own bucket / buffer there. OLWTC and the buffered "agriculture" bucket are conceptually different (FRA non-Forest tree-cover vs disturbance source).
- Implementation: defined a single `olwtc` variable per year in both exportRastersToDrive() and addLayersToMap(). In the analysis path, the built-up block + national built-up overrides relocated UP to be above the OLWTC exclusion (downstream distance-buffer code unchanged; same vars in scope).

## Changes vs v4.12.1 (Batch 24.3 -- 03a filename FRA realignment)
- Renamed export 03a_plantations_tree_crops -> 03a_other_land_with_tree_cover. The new name matches FRA 2025 Note 10 wording (the canonical category for the non-Forest tree-cover bucket: oil palm, fruit orchards, agroforestry, urban trees) AND the QGIS plugin's user-facing input slot label, so a user downloading this file from GEE no longer has to mentally translate when loading it into the plugin. Concept unchanged: still SDPT class 2 + Descals oil palm.
- Renamed export tickbox label "Plantations (agri tree crops, 03a)" -> "Other land with tree cover (03a)" to match.
- About-panel "Plantations layer" wording (in the rubber caveat block) intentionally LEFT IN PLACE because that paragraph is educational -- it explains why the everyday word "plantation" fits these crops better than timber forestry. Filename + UI align to FRA; the explanatory text retains the everyday term.
- BREAKING: any cached GEE outputs from v4.12.1 or earlier with the old name will need to be renamed manually if downstream tooling references the old filename.

## Changes vs v4.12.0 (Batch 24.2 -- export panel polish)
- Drop redundant "_<scale>m" suffix from the OSM roads vector filename. Vectors don't have a pixel size; the existing AOI + WDPA vector exports already drop the suffix. Result: BTN_gee_03a_roads_osm_vector_<HHhMMm>.shp instead of BTN_gee_03a_roads_osm_vector_30m_<HHhMMm>.shp.
- Add a "Select all / none" master tickbox at the top of the Export All Layers tickbox list. One-click bulk on/off for every per-layer checkbox below. Default unticked (per-layer defaults are mixed). Toggling overwrites all children; manual per-layer edits afterwards don't auto-resync the master.

## Changes vs v4.11.0 (Batch 24 / 24.1 -- OSM roads vector export)
- New "Roads (vector, OSM)" tickbox in the Export All Layers panel (default OFF). When ticked, exports the OSM roads merge clipped to country + buffer as a zipped Shapefile (LineString geometry). Drives the QGIS plugin's vector roads input slot for users who want vector roads (e.g. for finer buffer modelling) instead of the raster mosaic.
- Renamed existing "Roads" tickbox to "Roads (binary image, OSM+)" so the pair reads consistently. The "+" anticipates future multi-source merging (today the raster IS OSM-only).
- timeseriesAnthro.js gains a new function getOsmRoadsAll(aoi). Merges the 33 regional OSM CSV-uploaded FeatureCollections, filters out highway = 'proposed' / 'planned' (data-quality issue noted during ingestion), and returns the result. Optional aoi argument applies filterBounds INSIDE the per-asset map BEFORE flatten() -- mirrors WDPA's spatial-index pushdown so GEE skips non-overlapping assets via index lookup. Bhutan benchmark: 7+ min today; per-asset filtering is incremental but the WDPA pattern.
- doExportTable() helper extended with optional geometryTypes argument (defaults to ['Polygon','MultiPolygon'] for backwards compat). OSM roads pass ['LineString','MultiLineString'] so the SHP exports include the LineStrings (default polygon-only filter would silently empty the export).
- OSM caveats inline in the new module function's comments:
  - OSM-only (Congo logging roads via getCongoRoadsUpToYear stay separate, sourced from wurnrt-loggingroads).
  - No road-type differentiation -- some highways may be foot/bike-only and not vehicle-accessible. Buffered outputs may overstate accessibility in some regions.

## Changes vs v4.8.4 (P1.23 -- Custom forest section + input declaration)
- "Custom Forest" pulled out of the Source dropdown into its own discoverable checkbox-style panel (nationalForest), echoing the existing Custom road / built-up / agriculture / plantations / protected sections via createNationalAssetInputs. Most users never noticed the dropdown's Custom Forest option; the new section appears in the Tree Cover panel between the threshold sliders and the divider.
- New panel-level "My tree cover represents:" declaration dropdown with four options: All tree cover / Forest only / Naturally regenerating forest / Primary forest. Plain-language labels; FRA mapping reachable via a small "ⓘ How does this map to FRA categories?" button that opens the existing About panel. Default value "All tree cover" preserves pre-P1.23 behaviour for users who don't engage with the dropdown.
- Exclusion-toggle visibility now driven by the declaration:
  - All tree cover -> OLWTC + Planted forest both shown
  - Forest only -> Planted forest only
  - Naturally regenerating -> neither
  - Primary forest -> neither
  - Hidden toggles are never applied in analysis (exclusionActive() helper guards against stale `true` values from earlier UI state).
- Custom exclusion data section (renamed from "Custom plantations data") follows the same visibility rules. Variable name and saved-settings keys kept as nationalPlantations for backwards compat.
- createNationalAssetInputs factory extended:
  - mode label "Add to global" renamed to "Add to global extent" everywhere (clearer about what's being unioned). Old saved settings carrying the legacy string are forward-migrated on load.
  - new optional config flag `allowAgreement: true` adds a third merge mode "Agreement with global" (intersection). Enabled for area-based raster sections (forest, plantations, agri, large built-up, protected). Skipped for vector-derived narrow features (roads, small built-up) where pixel-perfect alignment is unreliable without buffering.
- Run-info table now records: declared input category, custom forest active flag + merge mode, plus the *effectively* applied exclusion state (via exclusionActive) instead of the raw checkbox value -- so the saved metadata matches the run.
- About panel: rubber caveat updated to reference "Custom exclusion data" (was "Custom plantations override"); new orthogonality note clarifying that thresholds and declaration are independent (thresholds are biophysical filters; declaration is FRA semantic category).

## Changes vs v4.8.3 ("Input: Forest" -> "Forest")
- Renamed map layer "Input: Forest" -> "Forest". Tree cover is the actual user input now (added v4.8.1); Forest is derived inside the tool (tree cover MINUS FRA agriculture). The "Input:" prefix was misleading.
- Wiring updates to handle exact-match (not prefix-match) for 'Forest' since plain 'Forest' as a prefix would over-match 'Forest outside buffers' (a different layer):
  - LAYER_PREFIX_MAP: removed 'Forest' prefix entry
  - pffLayerNames: added 'Forest' as exact-match entry
  - pffPrefixes: removed 'Forest' (was 'Input: Forest')
  - nameToKey: added 'Forest' -> 'forest' explicit entry
  - syncVisibleLayersFromMap: prefix check replaced with exact check; layer-shown read switched to exact match

## Changes vs v4.8.2 (Tree cover stats)
- Tree cover now reported in the stats panel as the top of the FRA progression: Tree cover -> Forest -> Naturally regenerating -> Primary forest. Matches the on-map progression.
- Drive stats export gains a Tree cover row when "Export Statistics to Drive" is clicked.
- latestMaskedTreeCover dict + reset wiring + storage at end of addLayersToMap, mirrored from the existing latestMasked* pattern.

## Changes vs v4.8.1 (legend refresh + button polish)
- Legend refresh button enlarged to "↻ Refresh" text label (80x32, was 32x28 icon-only). Self-explanatory + easier to hit.
- Bug fix: legend refresh was wiping the new "Input: Tree cover" layer because syncVisibleLayersFromMap()'s local NAME_TO_KEY dict didn't know about the treeCover key (added in v4.8.1). Each refresh reset visibleLayers.treeCover to false then never restored it. Added 'Input: Tree cover': 'treeCover' to the NAME_TO_KEY dict + a prefix match. Naturally regenerating forest also added (was missing too -- silent bug since v4.3.x that Tree cover exposed because it shared the issue).
- Legend toggle button bumped to width 80, fontSize 11px to match.

## Changes vs v4.8.0
- New "Input: Tree cover" map layer + legend entry. Shows the thresholded tree cover BEFORE the P1.18 FRA-agriculture exclusion -- workshop users see the full FRA forest-derivation progression on the map: Tree cover -> Forest -> Naturally regenerating -> Forest outside buffers -> Primary.
- tree_cover_clip variable saves forest_map_clip pre-P1.18 so the pre-FRA-filter layer survives even when FRA toggle is on.
- New binary_palegreen_palette (#c8e6c9, Material Green 100) extends the light->dark green ramp at the broadest end.
- visibleLayers.treeCover (default true), legend checkbox, LEGEND_ENTRIES, pffLayerNames cleanup, LAYER_PREFIX_MAP, nameToKey -- all wired so the layer participates in the standard show/hide + remove-on-update behaviour.

## Changes vs v4.7.0 (P1.22 follow-up -- checkbox reorder + About FRA block)
- Tree Cover panel: paired exclusion checkboxes reordered + relabelled to match the FRA forest-derivation flow:
  - tree cover - plantations = Forest (FRA Note 10 baseline)
  - Forest - planted forest = Naturally regenerating forest

  | OLD | NEW |
  |---|---|
  | "Exclude planted forest (derives ...)" | "Exclude plantations (e.g. oil palm, fruit, agroforestry)" -- FIRST |
  | "Exclude agriculture from Forest baseline (FRA-aligned)" | "Exclude planted forest (e.g. eucalyptus, pine, teak -- timber/pulp/fibre)" -- SECOND |

  Code logic + state management unchanged -- excludeAgriculture- and includePlantationsCheckbox kept their existing variable names + saved-settings keys for backward compat. Only labels + display order moved.
- About panel expanded with FRA 2025 definitions block (Forest / NRF / Primary Forest, verbatim from FAO), FRA Note 7 inclusions (rubber-wood, cork oak, Christmas trees) and Note 10 exclusions (oil palm, fruit, olive, agroforestry-with-crops). Plus a "How PFF outputs map to FRA" block with explicit ≈ proxies and the rubber caveat (SDPT class 2 vs FRA Note 7 mismatch). Workshop users now have the canonical definitions in-app rather than hunting the FAO website.
- Plugin side mirrors the same reorder + relabel pair (PLANTATIONS_RASTER + EXCLUDE_PLANTATIONS now appear AFTER FRA_AGRICULTURE_RASTER + EXCLUDE_AGRICULTURE_FROM_FOREST in full_workflow.py initAlgorithm). Symbolic parameter names kept for backward compat with processing.run() callers.

## Changes vs v4.6.0 (P1.22 -- terminology rename: Planted forest / Plantations)
Per FRA Notes 7 + 10, the everyday word "plantation" actually fits agricultural tree crops (oil palm, fruit) BETTER than timber forestry plantations. Swap labels to match intuition:

| OLD | NEW |
|---|---|
| "Plantations" layer (SDPT class 1) | "Planted forest" (timber/pulp/fibre, e.g. eucalyptus, pine, teak) |
| "FRA agriculture (tree-cover subset)" layer (SDPT class 2 + Descals oil palm) | "Plantations" (agricultural tree crops, e.g. oil palm, fruit orchards, olive orchards, agroforestry-with-crops) |

Filename renames (BREAKING):
- 02c_plantations -> 02c_planted_forest
- 03a_agriculture_tree_cover_fra -> 03a_plantations_tree_crops

Stats panel "Plantations Included" -> "Planted Forest Excluded". Backward-compat: load-settings still reads old keys.

RUBBER CAVEAT (documented, not fixed): per FRA Note 7, rubber-wood plantations ARE forest. SDPT v2 puts rubber in class 2 (Tree Crops), so rubber-bearing pixels currently land in 03a_plantations_tree_crops rather than 02c_planted_forest. Workshop guide notes this -- users in rubber-heavy countries (Indonesia, Malaysia, Thailand) can supply a national rubber raster via the existing nationalPlantations override to add it to 02c. Rubber rerouting via FDAP is not used (FDAP has commission errors in primary forest -- see memory note).

PRIMARY FOREST honesty caveat (documented in About + workshop guide): PFF's 04a_primary_forest is a geographic-proxy filter. It DOES NOT directly check FRA Primary Forest's "native species" criterion or "no significant hunting/poaching/gathering" criterion. Treat as a starting point for FRA Primary Forest reporting, refined by national context.

NRF Note 4 caveat (documented): per FRA, naturally regenerated trees of introduced species count as Naturally Regenerating Forest. The tool can't distinguish volunteer regeneration from active planting, so abandoned planted-forest blocks where trees have volunteered appear in 02c_planted_forest rather than 02d_naturally_regenerating. National data on actively-managed planted forest can correct this.

## Changes vs v4.5.0 (P1.20 -- FRA-correct plantations layer)
- Plantations layer narrowed to SDPT class 1 only (FRA Planted Forest -- timber/pulp/fibre plantations: eucalyptus, pine, teak). Per FRA, tree crops (SDPT class 2 -- rubber, fruit, agroforestry) and Descals oil palm are agricultural land regardless of tree biology and now route through the agriculture aggregation instead. Affects:
  - 02c_plantations export (FRA Planted Forest only)
  - 02d_naturally_regenerating_forest derivation (= 02b - 02c, FRA-faithful)
  - Behaviour: 02c_plantations area SHRINKS in oil-palm-heavy countries (Indonesia, Malaysia, Nigeria) -- now matches FRA Planted Forest reporting. 02d_naturally_regenerating_forest pixels unchanged from pre-P1.20 because P1.18 already excluded tree-cover-meeting agriculture at the baseline. 04a_primary_forest pixels unchanged -- agriculture aggregation explicitly includes tree crops + oil palm so disturbance buffering content is the same as before P1.20.
- New helper modules/timeseriesAnthro.js processingPlantedForestSDPT() exposes SDPT class 1 (Planted Forests) as a separate layer. Sibling to processingTreeCropsSDPT() added in v4.5.0 prep.
- processingPlantationsMosaic() retained for backwards compat but no longer called by pff_4.js -- consumers should migrate to processingPlantedForestSDPT() + processingTreeCropsSDPT() pair.
- National plantations override (nationalPlantations.checkbox) semantics unchanged BUT users should now supply FRA Planted Forest only (not their full national "plantations" registry if that bundles tree crops). Workshop guide gains a one-paragraph note on the SDPT class 1 vs class 2 distinction.

## Changes vs v4.4.0 (workflow-progression schema reorder)
- File numbers now reflect "more removed = higher number" through the pipeline. Three swaps:
  - 02c plantations (was 02d) -- INPUT for nat reg derivation
  - 02d naturally_regenerating_forest (was 02c) -- output of (02b - 02c)
  - 03c pre_connectivity_primary_forest (was 04b) -- output of Step 03 tier logic (disturbance buffers + protection rescues), feeds into Step 04 viability filter
  - 03d combined_coded_raster (was 04c) -- debug of Step 03 tier logic
  - 04a primary_forest (unchanged) -- final output of Step 04 ecological viability filter
- Step 04 collapses to a single output (04a primary_forest), matching "Refine Output = ecological viability filter only".
- Anthropogenic mask still at 04e for now -- spec says it should move to intermediates/ (no top-level number); flagged for follow-up batch.

## Changes vs v4.3.1 (P1.18 -- FRA-aligned Forest baseline)
- New checkbox "Exclude agriculture from Forest baseline (FRA-aligned)" in Tree Cover section, default ON (FRA-correct). When ticked, forest_map_clip is masked by NOT(Descals oil palm OR SDPT class 2 tree crops) BEFORE the P1.16 plantations subtraction. This narrows the Forest baseline (02b) to the FRA-strict definition: tree cover meeting biophysical thresholds AND not primarily agricultural land. Safe as a default because when SDPT class 2 / Descals are empty for a country, the mask is empty and the layer is unchanged.
- Per FRA, "agriculture" here means the *tree-cover-meeting subset* only (oil palm, tree crops, agroforestry). The broader PFF buffered agriculture (cropland + pasture + everything for primary-forest disturbance) is intentionally NOT FRA-aligned -- it serves a different role (proximity-based disturbance signal, not classification).
- Behaviour change when on: 02b_forest area shrinks (agricultural tree cover removed at baseline). 02c_naturally_regenerating area also shrinks (inherits the narrower baseline). 04a_primary is essentially unchanged -- those pixels were already removed via disturbance buffering toward primary.
- Run metadata bundle gains "FRA Agriculture Excluded from Forest" boolean. Settings save/load + reset wired. Backward-compat: older saved settings without this key default to false.
- New helper modules/timeseriesAnthro.js processingTreeCropsSDPT() exposes SDPT class 2 (Tree Crops) as a separate layer so P1.18 can use it without manually replicating the SDPT loading logic. Sets the stage for P1.20 (FRA-correct plantations refactor) which will reroute SDPT class 2 + Descals oil palm out of the plantations layer entirely.
- **P1.18 must ship before P1.20** -- without it, P1.20's plantations rebucketing would leave 02c_naturally_regenerating containing agricultural tree cover (oil palm, rubber). With P1.18 first, the baseline already excludes that tree cover so P1.20 just refines what counts as "Planted forest" without re-introducing agricultural pixels into Naturally regenerating.

## Changes vs v4.3.0 (P1.16 follow-up fixes)
- Naturally regenerating forest layer was stacking on each re-update because its name wasn't in the PFF-managed-layers cleanup list at line ~4454. Added 'Naturally regenerating forest' to pffLayerNames AND nameToKey so the existing "remove + readd" pattern picks it up.
- Forest-type colour ramp redesigned to make Primary STAND OUT. Primary pushed to a very dark green (#0b3d1f) and the other forest layers pulled into notably lighter shades that are still distinguishable from each other. New constant binary_medgreen_palette added for the new Naturally regenerating forest layer.
  - Forest: binary_lightgreen / lightgreen (#90EE90)
  - Naturally regenerating forest: binary_medgreen / #81c784 (Mat 300)
  - Forest outside buffers: binary_green / #4caf50 (Mat 500)
  - Primary forest: binary_darkgreen / #0b3d1f (very dark)
  - Plantations keeps its distinct gold (#d4a017) outside the ramp.
- LEGEND_ENTRIES colours updated to match the new palette.
- Legend + visibility-panel order rationalised for the Forest group: headline-first (Primary), then dark -> light through the green ramp (Forest outside buffers, Naturally regenerating, Input: Forest), then Plantations last (distinct gold).
- Legend refresh button (↻) bumped from 24x24 with 10px font to 32x28 with 14px font so the icon glyph renders reliably across browser combos.

## Changes vs v4.2.0 (P1.16 -- FRA-aligned forest-type schema)
- New 02c_naturally_regenerating_forest output. Previously the "Exclude plantations" toggle silently overwrote forest_map_clip in-place; now forest_map_clip stays as the FRA Forest baseline and a parallel forest_natreg_image is computed when the toggle is on. Downstream tier analysis switches to a forest_baseline selector (= natreg if available, else forest).
- Per FRA: Forest decomposes as Naturally regenerating + Planted. Primary forest is a SUBSET of naturally regenerating (not a sibling). The new 02c layer represents the FRA "Naturally regenerating forest" category (≈ Forest minus Planted).
- New export tickbox "Naturally regenerating forest (02c)" in the Export-all panel. File name pattern: <iso3>_gee_02c_naturally_regenerating_forest_<y>_<s>m.tif.
- Map: forest layer always labeled "Forest" (no longer conditionally relabeled to "Input: Forest (excl. plantations)"). New "Naturally regenerating forest" map layer added when forest_natreg_image is produced -- default visible, palette #1a6334 (medium green between Forest's light green and Primary's dark green).
- Stats: existing label conditional removed. Forest area always reports as "Forest" (= forest_map_clip = FRA Forest baseline). When plantations refinement runs, an additional "Naturally regenerating forest" row appears (= forest_natreg_image area). Primary forest is reported under naturally regenerating in the hierarchy (subset, not sibling). Both export to the Drive CSV as separate columns when "Export Statistics" is run.
- Legend: new "Naturally regenerating forest" checkbox between "Forest" and "Plantations" in the Layer Visibility panel.
- Substep migration: input steps (02, 03) move from per-file unique-letter scheme to semantic category-letter scheme. Files that were unique-lettered in v4.2.0 now share a substep letter:
  - 02a = forest source components (was 02a/b/c each): 02a_hansen_treecover2000_raw, 02a_hansen_lossyear_raw, 02a_glad_tree_height_m
  - 02b = forest baseline (was 02d_forest)
  - 02c = naturally regenerating forest (NEW)
  - 02d = plantations (was 03e_plantations)
  - 03a = disturbance inputs (was 03a/b/c/d each): 03a_roads, 03a_builtup_small, 03a_builtup_large, 03a_agriculture
  - 03b = protection exceptions (was 03f/g/h/i each): 03b_protection_legal, 03b_protection_legal_unfiltered_vector, 03b_protection_natural_dem, 03b_protection_natural_slope
  - Output steps (04, 05, 06) keep unique-letter scheme.

## Changes vs v4.1.16 (BREAKING -- minor bump to mark filename schema change)
- P1.13: All Export.image.toDrive / Export.table.toDrive descriptions + fileNamePrefixes migrated to the Option D naming schema (see docs/specs/PFF_NAMING_CONVENTION.md). Schema: `<ISO3>_gee_<step><substep>_<layer_name>_<year>_<scale>m`
- Renames:
  - 0_aoi_<country>_vector -> 00a_aoi_<country>_vector
  - 1_hansen_treecover2000_raw_<s> -> 02a_hansen_treecover2000_raw_<s>
  - 1_hansen_lossyear_raw_<s> -> 02b_hansen_lossyear_raw_<s>
  - 1_glad_tree_height_m_<y>_<s> -> 02c_glad_tree_height_m_<y>_<s>
  - 1_forest_<y>_<s> -> 02d_forest_<y>_<s>
  - 2_roads_<y>_<s> -> 03a_roads_<y>_<s>
  - 2_builtup_small_<y>_<s> -> 03b_builtup_small_<y>_<s>
  - 2_builtup_large_<y>_<s> -> 03c_builtup_large_<y>_<s>
  - 2_agriculture_<y>_<s> -> 03d_agriculture_<y>_<s>
  - 2_plantations_<y>_<s> -> 03e_plantations_<y>_<s>
  - 3_protection_legal_<s> -> 03f_protection_legal_<s>
  - 3_protection_legal_unfilt_vector -> 03g_protection_legal_unfiltered_vector
  - 3_protection_natural_dem_<s> -> 03h_protection_natural_dem_<s>
  - 3_protection_natural_slope_<s> -> 03i_protection_natural_slope_<s>
  - 4_pre_connectivity_forest_<y>_<s> -> 04b_pre_connectivity_primary_forest_<y>_<s>
  - 5_primary_forest_<y>_<s> -> 04a_primary_forest_<y>_<s>
  - <iso3>_pff_run_metadata_<y>_<s>m -> <iso3>_gee_run_metadata_<y>_<s>m
- Implementation: new mkExportName(step, name) helper inside exportRastersToDrive() that calls generateLayerName(iso3, PLATFORM_GEE, step, name, '') and appends runTag. doExport / doExportInt16 / doExportTable refactored to NOT prepend iso3 themselves -- the caller's mkExportName() output is used as-is.

## Changes vs v4.1.15
- P0.15 (zero-buffer rule) verified for GEE side: existing applyDistanceThreshold(dist, threshold) already produces the correct footprint-only result when threshold == 0 (because .lte(0) keeps only the source pixels at distance 0). No code change needed -- just an explanatory comment block on the function so future maintainers don't accidentally regress it (e.g. by switching to .lt() or adding a misguided special case). Plugin shipped the equivalent change in batch 9 (v0.8.66).

## Changes vs v4.1.14
- JS mirror of Python pff_qgis_tools.utils.generate_layer_name(): adds PLATFORM_GEE / PLATFORM_QGIS + STEP_* constants and a generateLayerName(iso3, platform, step, name, ext='tif') helper. Foundation for P1.13 (full filename rename across both tools to Option D schema). No consumers in pff_4.js yet -- existing Export.image.toDrive description / fileNamePrefix call sites migrate later.

## Changes vs v4.1.13
- P0.10 stats button hygiene:
  - statsScaleSlider onChange now marks the Show Area Statistics button stale (was a no-op). The slider only affects stats reduction, not analysis cache, so it doesn't trigger markNeedsUpdate -- just paints the stats * directly.
  - Show Area Statistics now prepends an "⚠ Analysis is OUT OF DATE" warning row when needsUpdate=true. Previously the user could change a slider, click Show Stats, and silently see numbers computed from stale forest cache as if they were current.
- Audit findings (no change needed): country/year selectors call updateMap() directly so they don't need a stale flag; threshold sliders + buffer sliders + checkboxes already hook markNeedsUpdate.

## Changes vs v4.1.12
- P1.6 + P1.7 (combined): per-run metadata bundle JSON. Single source of truth for "what was this run?" provenance, since Export.image.toDrive can't write arbitrary GDAL metadata tags during export (the original P1.6 plan). Two surfaces:
  1. Tickbox in Export-all panel ("Run metadata JSON (config + run snapshot)", default ON). Queues an Export.table.toDrive (or Cloud Storage) GeoJSON sidecar per analysis year alongside the raster batch. Filename: `<iso3>_gee_run_metadata_<year>_<scale>m.geojson` (P1.13 -- was pff_)
  2. New "Download Run Metadata" button in the Save-settings panel. In-browser download via getDownloadURL -- snapshots current config + selected year/scale without queueing a Drive task.
- Bundle structure: flat dict with config__* keys mirroring collectSettings() and run__* keys for pff_script_version, timestamp, country, iso3, year_exported, scale_m, export_destination, export_folder. Flat-prefixed because EE's getDownloadURL serialises Feature properties best as flat KV.
- Tickbox state persists in saved settings as 'Export Run Metadata JSON'.

## Changes vs v4.1.11
- P0.8 master toggle: new "Add input + buffer layers to map" checkbox in the Human Influence section (default OFF). When unchecked, the 11 input/buffer/exception layers (Plantations, Slope, Protected Areas, 4 Buffer:* and 4 Input:* layers) are NOT added to the map -- keeps the EE Layers dropdown tidy at first paint. Per-layer enable* checkboxes still control whether the layer is computed; this toggle only controls map-add. markNeedsUpdate on change so next Update Analysis honours the new state. Saved/loaded with settings as 'Add Input Layers To Map'.

## Changes vs v4.1.10
- P0.8: Default visible layers expanded to include the input forest layer ("Forest") and the supporting pre-connectivity output ("Forest outside buffers"), in addition to "Primary Forest" which was already on. Anthro/buffer/exception inputs remain off by default. Mirrors the user-facing intent: see the headline output, its supporting layer, and the input it derives from at first paint.

## Changes vs v4.1.9
- P2.16: Both export-panel "Options" toggles renamed to "Advanced". A 1-pixel slate-grey horizontal-rule panel separates the in-browser Download and Drive Export sections (replacing the empty-label spacer).
- P2.15: Legend panel widened from 160 to 180px and toggle button shrunk from 80 to 72px so the refresh icon stays visible at narrower panel widths.
- P1.1: FRA comparison line (modules/fraStats.js formatFRA) now reads "FRA 2025 (YYYY): ..." instead of "FRA (YYYY): ..." -- making clear that "2025" is the source REPORT version (FAO Forest Resources Assessment 2025) while the parenthesised year is the data reference year being compared. Note: fraStats.js is loaded as a GEE script repo dependency (users/andyarnellgee/apps:modules/fraStats.js); the local file under modules/ is the source of truth but must also be pushed to the GEE repo for the change to surface in the app.

## Changes vs v4.1.8
- P2.14: Primary Forest map layer now uses the named binary_darkgreen_palette (#26600e) instead of CSS 'darkgreen' (#006400). Fixes the legend/layer colour mismatch (legend already used #26600e) and gives a cleaner contrast with the "Forest outside buffers" pre-connectivity layer (#228B22).
- P0.12: Slope input layer recoloured brown (#8B4513) -> slate grey (#708090) on both map layer and legend swatch. Brown was easily confused with the agriculture/built-up palette family.

## Changes vs v4.1.7
- FRA terminology renames (P0.13b, completes 14b rename table):
  - Slider labels: "Hansen Cover (%) >" -> "Tree canopy threshold (%):"; "GLAD Height (m) >" -> "Tree height threshold (m):". Source-agnostic wording (these sliders also drive Agreement / Combined extent).
  - Stats display labels: "Total Treecover (incl. plantations)" -> "Forest"; "Total Treecover (excl. plantations)" -> "Naturally regenerating forest". Matches FRA cascade.
  - Download dropdown: "Tier 0: Input Treecover (raw Hansen)" -> "Tier 0: Input forest cover (before thresholding)". Source-agnostic.
- Stats CSV column headers ("Treecover Threshold (%)", "GLAD Treecover Height (m)") preserved as downstream-consumer contracts. "Primary Forest" capitalization preserved for layer-key string-equality checks.

## Changes vs v4.1.6
- IS_APP flag renamed to IS_PUBLISHED_APP for clarity. When true, hides both the "Export to Google Drive" raster panel AND the "Export Statistics to Drive" button. Rationale: published-app users typically lack Drive write permissions, so any Drive export silently fails. The in-browser "Download to Computer" path remains for both rasters and stats. (P0.9)

## Changes vs v4.1.1
- Bugfix: export region now uses .bounds() of the buffered country polygon instead of the polygon itself. GEE writes rectangular GeoTIFFs regardless of region shape, so using .bounds() (5 vertices) gives identical output extent without the vertex-limit overflow that was failing Indonesia and other archipelago countries. Non-archipelago countries produce identical output.

## Changes vs v4.1.0
- New "Plantations" export tickbox under Select Layers -- dispatches a separate binary plantations raster ('2_plantations_<year>_<scale>.tif'). The forest export itself remains raw (unchanged behaviour). The QGIS plugin then applies the forest-AND-NOT-plantations mask at ingest time, echoing the "Exclude plantations" checkbox in GEE. This enables the full FRA stats cascade (Forest -> Naturally regenerating forest -> Primary forest) without re-exporting.

## Changes vs v3
- preprocessAsset() -- each custom dataset asset path now supports a full preprocessing pipeline: source type (image / image_collection / feature_collection), band selection, class remapping, threshold, mosaic, year_filter, and feature_collection inList filter.
- All custom asset paths now accept gs:// Cloud Storage COG URIs in addition to standard GEE asset IDs (users/... or projects/...).
- A collapsible "⚙ Preprocessing" panel is shown below each custom dataset textbox group; it defaults to 'image' with no extra transforms.

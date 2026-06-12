/**
 * Provenance "methods narrative" generator for the PFF GEE app.
 *
 * Produces a Markdown methods paragraph + an FRA-alignment caveats block +
 * a numbered reference list, from a run-config object (the collectSettings()
 * output plus a few run params). Pure string logic -- NO ee.* calls, so it is
 * cheap and deterministic.
 *
 * Citations mirror docs/datasets_global.json -- keep that JSON the source of
 * truth and update both together. The processing chain follows
 * docs/specs/PFF_NAMING_CONVENTION.md.
 *
 * Usage (in pff_4.js):
 *   var prov = require('users/andyarnellgee/apps:modules/provenanceNarrative.js');
 *   var md = prov.buildNarrative(collectSettings(), {
 *     country: 'Bhutan', iso3: 'BTN', year: 2020, scale: 30,
 *     pffVersion: PFF_SCRIPT_VERSION, length: 'extended'   // or 'short'
 *   });
 *   print(md);
 *
 * NOTE (v1): the narrative describes the canonical FRA chain with the run's
 * source / thresholds / buffers / scale filled in. Per-toggle dropping of
 * individual steps (e.g. "slope tier off") is a follow-up refinement.
 */

// -- Citation library: analysis-chain subset of docs/datasets_global.json --
var CITATIONS = {
  glad_glclu: {
    short: 'Potapov et al., 2022a',
    full: 'Potapov, P. et al. (2022a). The Global 2000-2020 Land Cover and Land Use Change Dataset Derived From the Landsat Archive. Front. Remote Sens. 3, 856903.',
    url: 'https://doi.org/10.3389/frsen.2022.856903'},
  hansen_gfc: {
    short: 'Hansen et al., 2013',
    full: 'Hansen, M.C. et al. (2013). High-Resolution Global Maps of 21st-Century Forest Cover Change. Science 342, 850-853.',
    url: 'https://doi.org/10.1126/science.1244693'},
  sdpt: {
    short: 'Richter et al., 2024',
    full: 'Richter, J. et al. (2024). Spatial Database of Planted Trees (SDPT Version 2.0). World Resources Institute, Washington, DC.',
    url: 'https://www.wri.org/research/spatial-database-planted-trees-sdpt-version-2',
    isStatic: true},
  descals_palm: {
    short: 'Descals et al., 2024',
    full: 'Descals, A. et al. (2024). Global mapping of oil palm planting year from 1990 to 2021. Earth Syst. Sci. Data 16, 5111-5129.',
    url: 'https://doi.org/10.5194/essd-16-5111-2024'},
  osm: {
    short: 'OpenStreetMap contributors, 2025',
    full: 'OpenStreetMap contributors (2025). Geofabrik regional extracts (~May 2025), ODbL 1.0.',
    url: 'https://www.openstreetmap.org',
    isStatic: true},
  ghsl: {
    short: 'Pesaresi et al., 2024',
    full: 'Pesaresi, M. et al. (2024). Advances on the Global Human Settlement Layer by Joint Assessment of Earth Observation and Population Survey Data. Int. J. Digital Earth 17(1).',
    url: 'https://doi.org/10.1080/17538947.2024.2390454'},
  glad_cropland: {
    short: 'Potapov et al., 2022b',
    full: 'Potapov, P. et al. (2022b). Global maps of cropland extent and change show accelerated cropland expansion in the twenty-first century. Nat. Food 3, 19-28.',
    url: 'https://doi.org/10.1038/s43016-021-00429-z'},
  glc_fcs30d: {
    short: 'Zhang et al., 2024',
    full: 'Zhang, X. et al. (2024). GLC_FCS30D: the first global 30 m land-cover dynamics monitoring product for 1985-2022. Earth Syst. Sci. Data 16, 1353-1381.',
    url: 'https://doi.org/10.5194/essd-16-1353-2024'},
  pasture: {
    short: 'Parente et al., 2024',
    full: 'Parente, L. et al. (2024). Annual 30-m maps of global grassland class and extent (2000-2022). Sci. Data 11, 1303.',
    url: 'https://doi.org/10.1038/s41597-024-04139-6'},
  alos_dem: {
    short: 'Tadono et al., 2016',
    full: 'Tadono, T. et al. (2016). Generation of the 30 m-mesh Global Digital Surface Model by ALOS PRISM. ISPRS Archives XLI-B4, 157-162.',
    url: 'https://doi.org/10.5194/isprs-archives-XLI-B4-157-2016',
    isStatic: true},
  wdpa: {
    short: 'UNEP-WCMC & IUCN, 2026',
    full: 'UNEP-WCMC & IUCN (2026). Protected Planet: The World Database on Protected Areas (WDPA). UNEP-WCMC and IUCN, Cambridge, UK.',
    url: 'https://doi.org/10.34892/6fwd-af11'},
  gaul: {
    short: 'FAO, 2024',
    full: 'FAO (2024). Global Administrative Unit Layers (GAUL) 2024. FAO, Rome.',
    url: 'https://data.apps.fao.org/catalog/dataset/global-administrative-unit-layers-gaul-2024',
    isStatic: true},
  fra: {
    short: 'FAO, 2025',
    full: 'FAO (2025). Global Forest Resources Assessment 2025: Terms and Definitions. FAO, Rome.',
    url: 'https://fra-data.fao.org/definitions/fra/2025/en/tad#1b'}
};
exports.CITATIONS = CITATIONS;

// -- Per-exported-layer recipes: datasets + one-line processing per file. --
// `cites: ['source']` is expanded to the run's actual tree-cover source(s).
var LAYER_RECIPES = {
  aoi:                {stem: '00a_aoi', text: 'Country / area-of-interest boundary.', cites: ['gaul']},
  tree_cover_binary:  {stem: '02a_tree_cover_binary', text: 'Thresholded binary tree cover -- the input that defines the reference grid.', cites: ['source']},
  hansen_raw:         {stem: '02a_hansen_treecover2000_raw / _lossyear_raw', text: 'Raw Hansen GFC bands (canopy cover 2000 and annual loss year), un-thresholded, for re-thresholding.', cites: ['hansen_gfc']},
  glad_tree_height_raw: {stem: '02a_glad_tree_height_raw', text: 'Raw GLAD continuous tree height (m), un-thresholded, for re-thresholding.', cites: ['glad_glclu']},
  other_land_with_tree_cover: {stem: '02b_other_land_with_tree_cover', text: 'Non-forest tree cover (oil palm, tree crops/SDPT class 2, urban tree cover) removed from tree cover en route to Forest.', cites: ['descals_palm', 'sdpt']},
  forest:             {stem: '02c_forest', text: 'Tree cover minus other land with tree cover approx. FRA Forest.', cites: []},
  planted_forest:     {stem: '02d_planted_forest', text: 'Planted forest (SDPT class 1: timber/pulp + national overrides).', cites: ['sdpt']},
  naturally_regenerating_forest: {stem: '02e_naturally_regenerating_forest', text: 'Forest minus planted forest approx. FRA naturally regenerating forest.', cites: []},
  roads:              {stem: '03a_roads', text: 'Roads rasterised for the disturbance buffer.', cites: ['osm']},
  roads_osm_vector:   {stem: '03a_roads_osm_vector', text: 'Roads as supplied vector.', cites: ['osm']},
  builtup_small:      {stem: '03a_builtup_small', text: 'Built-up (rural settlement) extent for the disturbance buffer.', cites: ['ghsl']},
  builtup_large:      {stem: '03a_builtup_large', text: 'Built-up (urban centre) extent for the disturbance buffer.', cites: ['ghsl']},
  agriculture:        {stem: '03a_agriculture', text: 'Agriculture (cropland, pasture, oil palm, tree crops) for the disturbance buffer.', cites: ['glad_cropland', 'glc_fcs30d', 'pasture', 'descals_palm', 'sdpt']},
  protection_natural_dem: {stem: '03b_protection_natural_dem', text: 'Digital surface model for the steep-slope rescue tier.', cites: ['alos_dem']},
  protection_natural_slope: {stem: '03b_protection_natural_slope', text: 'Slope derived from the DEM for the steep-slope rescue tier.', cites: ['alos_dem']},
  protection_legal:   {stem: '03b_protection_legal', text: 'Legally protected areas for the protection rescue tier.', cites: ['wdpa']},
  protection_legal_unfiltered_vector: {stem: '03b_protection_legal_unfiltered_vector', text: 'Protected areas as supplied vector.', cites: ['wdpa']},
  pre_refinement_primary_forest: {stem: '03c_pre_refinement_primary_forest', text: 'Forest surviving the buffers and exceptions, before the Refine Output (ecological-viability) step.', cites: []},
  primary_forest:     {stem: '04a_primary_forest', text: 'Final primary forest after the Refine Output (ecological-viability) step.', cites: []}
};

// FRA category definitions -- KEEP IN SYNC with the app's "FRA 2025 definitions"
// popup in pff_4.js (currently ~L1681-1685). Reproduced here so the methods note
// states the same definitions the user sees in the app.
var FRA_DEFINITIONS = [
  ['Forest', 'As tree cover, but land use is forest (excludes agricultural & urban tree stands).'],
  ['Naturally regenerating forest', 'Forest established through natural regeneration.'],
  ['Primary forest', 'Naturally regenerating, native species, no visible human activity.']
];

function num(v, dflt) {
  return (v === undefined || v === null || v === '') ? dflt : v;
}

exports.buildNarrative = function(settings, run) {
  settings = settings || {};
  run = run || {};
  var length = run.length || 'extended';
  function s(key, dflt) {
    var v = settings[key];
    return (v === undefined || v === null || v === '') ? dflt : v;
  }

  // Citation bookkeeping -- track which datasets are cited (for the References
  // list). cite() returns an author-year string, e.g. "Potapov et al., 2022a".
  var order = [], seen = {};
  function cite(id) {
    if (!CITATIONS[id]) { return ''; }
    if (!seen[id]) { seen[id] = true; order.push(id); }
    return CITATIONS[id].short;
  }

  var height = num(s('GLAD Treecover Height (m)', 5), 5);
  var canopy = num(s('Treecover Threshold (%)', 10), 10);
  var scale  = num(run.scale, 30);

  // Source + threshold phrasing.
  var sourceSentence;
  if (s('Use Hansen (GFC) Tree Cover', false) === true) {
    sourceSentence = 'Tree cover was derived from the Hansen Global Forest Change product (' +
      cite('hansen_gfc') + '), retaining pixels with canopy cover >= ' + canopy + '% to give a binary tree-cover layer';
  } else if (s('Use Agreement Forest', false) === true) {
    sourceSentence = 'Tree cover was taken as the agreement (intersection) of GLAD GLCLU (' + cite('glad_glclu') +
      ') and Hansen GFC (' + cite('hansen_gfc') + '), retaining pixels with tree height >= ' + height +
      ' m AND canopy cover >= ' + canopy + '% to give a binary tree-cover layer';
  } else if (s('Use Combined Extent Forest', false) === true) {
    sourceSentence = 'Tree cover was taken as the combined extent (union) of GLAD GLCLU (' + cite('glad_glclu') +
      ') and Hansen GFC (' + cite('hansen_gfc') + '), retaining pixels with tree height >= ' + height +
      ' m OR canopy cover >= ' + canopy + '% to give a binary tree-cover layer';
  } else {
    sourceSentence = 'Tree cover was derived from the GLAD Global Land Cover & Land Use product (GLCLU 2020 v2; ' +
      cite('glad_glclu') + '), retaining pixels with tree height >= ' + height + ' m to give a binary tree-cover layer';
  }

  // Custom national tree-cover input overrides the source sentence.
  // Custom forest is signalled by the caller (the checkbox state), NOT the
  // mode-select value -- the mode select defaults to "Replace global" even
  // when the custom-forest checkbox is off, so keying off it false-positives.
  var customForestMode = String(s('Custom Forest Mode', '') || '');
  var customForest = (run.customForest === true);
  if (customForest) {
    sourceSentence = 'Tree cover was supplied as a custom national raster (mode: ' + customForestMode +
      ') to give a binary tree-cover layer';
  }

  // Tree-cover source id(s), for the per-layer list's `cites: ['source']`.
  var srcIds;
  if (customForest) {
    srcIds = [];
  } else if (s('Use Hansen (GFC) Tree Cover', false) === true) {
    srcIds = ['hansen_gfc'];
  } else if (s('Use Agreement Forest', false) === true || s('Use Combined Extent Forest', false) === true) {
    srcIds = ['glad_glclu', 'hansen_gfc'];
  } else {
    srcIds = ['glad_glclu'];
  }

  var resPhrase = ' at ' + scale + ' m';
  var ts = run.timestamp || '';
  // Human-readable UTC stamp from the ISO timestamp (e.g. 2026-06-12 13:04 UTC).
  var whenLine = ts ? (ts.substring(0, 10) + ' ' + ts.substring(11, 16) + ' UTC') : '';
  var title = '**Primary forest -- ' + (run.country || 'country') +
    (run.iso3 ? ' (' + run.iso3 + ')' : '') + ', ' + (run.year || '') + ', ' + scale + ' m**';
  var subline = '';
  if (whenLine) { subline = 'Generated ' + whenLine; }
  if (run.pffVersion) { subline += (subline ? ' | ' : '') + 'Primary Forest Finder v' + run.pffVersion; }

  var p1, p2 = '';
  if (length === 'short') {
    p1 = sourceSentence + resPhrase +
      ', refined toward the FAO FRA forest definition by removing other land with tree cover (oil palm (' +
      cite('descals_palm') + '), tree crops/agroforestry (SDPT class 2; ' + cite('sdpt') + '), urban tree cover) and ' +
      'planted forest (SDPT class 1; ' + cite('sdpt') + '), then removing forest within buffers around likely human influence (roads (' + cite('osm') +
      '), built-up (' + cite('ghsl') + '), agriculture (' + cite('glad_cropland') + ')) while retaining steep-slope (' +
      cite('alos_dem') + ') and legally protected (' + cite('wdpa') + ') forest, producing the final primary-forest map' +
      resPhrase + '.';
  } else {
    p1 = sourceSentence + resPhrase + ' (`02a_tree_cover_binary`). This was refined toward the FAO Forest Resources ' +
      'Assessment (FRA) forest definition: *other land with tree cover* -- oil palm (' + cite('descals_palm') +
      '), rubber/tree-crop and agroforestry plantations (SDPT class 2; ' + cite('sdpt') + '), and urban tree cover -- ' +
      'was removed to give Forest (`02c`), and planted forest (SDPT class 1: timber/pulp and national overrides; ' +
      cite('sdpt') + ') was subtracted to give naturally regenerating forest (`02e`).';

    var roadBuf  = num(s('Road Small Buffer (m)', 1000), 1000);
    var builtBuf = num(s('Built-Up Small Buffer (m)', 1000), 1000);
    var agriBuf  = num(s('Agriculture Buffer (m)', 1000), 1000);
    var slopeDeg = num(s('Slope to keep (degrees)', 45), 45);
    var wdpaYear = s('WDPA Established Before', null);
    var smoothR  = num(s('Forest Smoothing Radius (m)', 2000), 2000);
    var densPct  = Math.round(num(s('Forest Smoothing Threshold', 0.5), 0.5) * 100);

    p2 = 'To represent likely human influence, the following were buffered and any forest falling within those buffers was removed from the analysis: roads (OpenStreetMap; ' +
      cite('osm') + ') by ' + roadBuf + ' m, built-up areas (JRC GHSL; ' + cite('ghsl') + ') by ' + builtBuf +
      ' m, and agriculture -- cropland (GLAD, ' + cite('glad_cropland') + '; GLC_FCS30D, ' + cite('glc_fcs30d') +
      '), pasture (Global Pasture Watch; ' + cite('pasture') + '), oil palm (' + cite('descals_palm') + ') and tree crops (' +
      cite('sdpt') + ') -- by ' + agriBuf + ' m. Two exceptions were kept within those buffers: forest on ' +
      'slopes >= ' + slopeDeg + ' deg (JAXA ALOS AW3D30 DEM; ' + cite('alos_dem') + ') and forest in legally ' +
      'protected areas' + (wdpaYear ? ' established before ' + wdpaYear : ' (established >= 30 years before the analysis year)') +
      ' (WDPA; ' + cite('wdpa') + '). The surviving forest (`03c`) was then passed through the Refine Output step ' +
      '-- ecological-viability filtering by neighbourhood-density smoothing (' + smoothR + ' m radius, keeping ' +
      'pixels with >= ' + densPct + '% forest density) -- producing the final primary-forest map (`04a_primary_forest`)' + resPhrase + '.';
  }

  // Caveats / FRA-alignment notes.
  var caveats = [];
  caveats.push('SDPT class 2 (tree crops) is treated as *other land with tree cover* and removed from Forest. ' +
    'SDPT v2 (' + cite('sdpt') + ') does not separate **rubber** from other tree crops, so rubber plantations are excluded ' +
    'here -- but the FAO FRA forest definition *can* include rubber. Where rubber is present, this map will diverge ' +
    'from (under-count relative to) the FRA forest definition.');
  if (scale > 30) {
    caveats.push('Exported at ' + scale + ' m (coarser than the 30 m source). At coarse resolution a vector ' +
      'representation preserves the true forest extent and avoids the sampling bias introduced by majority / ' +
      'nearest-neighbour raster resampling.');
  }
  if (customForest) {
    caveats.push('The tree-cover input was a user-supplied national dataset, so the global-source provenance above ' +
      'applies only to the non-forest inputs.');
  }

  // Per-exported-layer list (cite() runs here so the References include them).
  var layersBlock = '';
  if (run.exportedLayers && run.exportedLayers.length) {
    layersBlock = '**Layers in this export**\n';
    run.exportedLayers.forEach(function(key) {
      var r = LAYER_RECIPES[key];
      if (!r) { return; }
      // No footnote markers here -- the per-layer list would otherwise cluster
      // numbers (e.g. agriculture's many sources). Citations live in the prose
      // and References; this list just names each file. (`cites`/`srcIds` kept
      // for possible future use.)
      layersBlock += '- `' + r.stem + '` -- ' + r.text + '\n';
    });
  }

  // FRA definitions block (cite('fra') here so the source lands in References).
  var fraDefsBlock = '**FRA 2025 definitions** (' + cite('fra') + ')\n';
  FRA_DEFINITIONS.forEach(function(d) { fraDefsBlock += '- *' + d[0] + '*: ' + d[1] + '\n'; });

  // References -- alphabetical (fulls start with author surname), unnumbered,
  // since in-text citations are author-year. A trailing "*" marks static
  // inputs (applied the same regardless of the analysis year).
  var anyStatic = false;
  var refs = order.map(function(id) {
    var c = CITATIONS[id];
    if (c.isStatic) { anyStatic = true; }
    return c.full + (c.url ? ' ' + c.url : '') + (c.isStatic ? ' *' : '');
  });
  refs.sort();

  // Year analysed -- stated explicitly (not just in the title). Save to
  // computer is single-year; if Compare Years was on, note this covers one
  // year only and the other year has its own note.
  var yearLine = '**Year analysed:** ' + (run.year || '');
  if (run.compare && run.year2 && String(run.year2) !== String(run.year)) {
    yearLine += ' (single-year note -- Compare Years also showed ' + run.year2 +
      '; that year has its own note)';
  }

  // Assemble.
  var md = title + (subline ? '\n' + subline : '') + '\n' + yearLine + '\n\n' + p1;
  if (p2) { md += '\n\n' + p2; }
  if (layersBlock) { md += '\n\n' + layersBlock; }
  md += '\n\n' + fraDefsBlock;
  if (caveats.length) {
    md += '\n\n**Notes on FRA alignment**\n';
    caveats.forEach(function(c) { md += '- ' + c + '\n'; });
  }
  if (refs.length) {
    md += '\n**References**\n' + refs.join('\n') + '\n';
    if (anyStatic) {
      md += '\n\\* Static input -- applied the same regardless of the analysis year ' +
        '(not year-specific), so it may not represent conditions in the analysis year. ' +
        'All other inputs are selected for the analysis year.\n';
    }
  }
  return md;
};

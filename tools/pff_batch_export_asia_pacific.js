// ═══════════════════════════════════════════════════════════════════════
// PFF Batch Export — Asia-Pacific Workshop Countries
// ═══════════════════════════════════════════════════════════════════════
//
// Standalone GEE script that queues Drive export tasks for 6 countries.
// Replicates the pff_4.js analysis pipeline with hardcoded defaults —
// no UI dependencies.
//
// Usage:
//   1. Paste into GEE Code Editor
//   2. Click Run — tasks appear in the Tasks tab
//   3. Click Run on each task (or use "Run all" userscript)
//
// Excludes time-varying layers (roads, protected areas, Hansen raw, AOI)
// that update independently. Exports land in PFF_export_<country>/
// folders on Google Drive.
// ═══════════════════════════════════════════════════════════════════════

// ═══ 1. CONFIGURATION ═══════════════════════════════════════════════

var SCRIPT_VERSION = '1.0.0';
var EXPORT_SCALE = 90;
var EXPORT_CRS = 'EPSG:4326';

var COUNTRIES = [
  // BTN, LAO, THA already have year-2000 exports — only gap-fill below
  {name: 'Indonesia',                           iso3: 'IDN', years: [2000]},
  {name: 'Papua New Guinea',                    iso3: 'PNG', years: [2000]},
  {name: 'Viet Nam',                            iso3: 'VNM', years: [2000]}
];

// Analysis parameters (all defaults except slope + PA = ON)
var TREE_HEIGHT_THRESHOLD = 5;       // metres (GLAD LULC)
var COUNTRY_BUFFER_THRESHOLD = 2000; // metres
var NEIGHBORHOOD_SIZE = 170;
var FAST_BUFFER = true;
var ALL_BUFFER_DISTANCE = 1000;      // metres — roads, builtup_small, builtup_large, agriculture
var SLOPE_THRESHOLD = 45;            // degrees — slope exception ON
var YEARS_PROTECTED = 30;            // PA exception ON
var SELECTED_IUCN_CATEGORIES = ['Ia', 'Ib', 'II']; // strict
var SMOOTH_RADIUS = 2000;            // connectivity neighbourhood radius (m)
var SMALL_PIXEL_THRESHOLD = 0.5;     // connectivity density threshold
var ENABLE_REFINE_OUTPUT = true;
var ENABLE_SLOPE = true;
var ENABLE_PROTECTED_AREAS = true;
var REFINE_TO_FOREST = true;         // exclude OLWTC from forest baseline
var REFINE_TO_NRF = true;            // exclude planted forest

var INCLUDE_WSF = true;
var INCLUDE_GHSL = true;

var FORWARD_FILL_YEARS = [2000, 2010, 2015, 2020];

// ═══ 2. SHARED MODULES ══════════════════════════════════════════════

var gaulLut = require('users/andyarnellgee/apps:modules/gaulLut.js');
var timeseriesAnthroModule = require('users/andyarnellgee/apps:modules/timeseriesAnthro.js');

// ═══ 3. SHARED ASSETS ═══════════════════════════════════════════════

var countries = ee.FeatureCollection('projects/sat-io/open-datasets/FAO/GAUL/GAUL_2024_L0');
var countries_simple = ee.FeatureCollection(
    'projects/ee-andyarnellgee/assets/crosscutting/GAUL_2024_L0_simplify_0_001deg_dice10k');
var gaul_raster = ee.Image('projects/ee-andyarnellgee/assets/gaul_2024_level_0_code_500m');

var current_year = new Date().getFullYear();
var wdpaBase = ee.FeatureCollection('WCMC/WDPA/current/polygons')
  .filter(ee.Filter.and(
    ee.Filter.neq('STATUS', 'Proposed'),
    ee.Filter.neq('STATUS', 'Not Reported'),
    ee.Filter.neq('DESIG_ENG', 'UNESCO-MAB Biosphere Reserve')
  ));
var wdpaStatusYearGlobal = wdpaBase.reduceToImage({
  properties: ['STATUS_YR'],
  reducer: ee.Reducer.min()
});
var allWdpaCategories = ['Ia','Ib','II','III','IV','V','VI','Not Reported','Not Assigned','Not Applicable'];
var wdpaCategoryMasks = {};
allWdpaCategories.forEach(function(cat) {
  wdpaCategoryMasks[cat] = wdpaBase.filter(ee.Filter.eq('IUCN_CAT', cat))
    .reduceToImage({properties: ['WDPAID'], reducer: ee.Reducer.first()})
    .unmask(0).gt(0);
});

var alos_30m_elev = ee.ImageCollection('JAXA/ALOS/AW3D30/V3_2').select('DSM');

// ═══ 4. UTILITY FUNCTIONS ═══════════════════════════════════════════

function cleanCountryName(name) {
  return name.replace(/[̀-ͯ]/g, '').replace(/[^a-zA-Z0-9 ]/g, '')
    .trim().replace(/\s+/g, '_');
}

function getCountryClip(countryName) {
  var code = gaulLut.nameToCode(countryName);
  return gaul_raster.eq(code).selfMask();
}

function getCountryFeatures(countryName) {
  var info = gaulLut.GAUL_LUT[gaulLut.nameToCode(countryName)];
  if (!info) return countries.filter(ee.Filter.eq('gaul0_name', countryName));
  var iso3 = info.iso3;
  if (iso3 === 'IDN' || iso3 === 'THA' || iso3 === 'DZA' || iso3 === 'AUS' || iso3 === 'CHN') {
    return countries_simple.filter(ee.Filter.eq('iso3_code', iso3));
  }
  return countries.filter(ee.Filter.eq('gaul0_name', countryName));
}

function makeDistanceBuffer(sourceImage, threshold) {
  return sourceImage.fastDistanceTransform({neighborhood: NEIGHBORHOOD_SIZE}).sqrt()
    .multiply(ee.Image.pixelArea().sqrt()).lte(threshold).selfMask();
}

function makeDistanceSurface(sourceImage) {
  return sourceImage.fastDistanceTransform({neighborhood: NEIGHBORHOOD_SIZE}).sqrt()
    .multiply(ee.Image.pixelArea().sqrt());
}

function applyDistanceThreshold(distanceImage, threshold) {
  return distanceImage.lte(threshold).selfMask();
}

function forwardFillBinaryTimeSeries(imageCollection, targetYears) {
  var sorted = imageCollection.sort('year');
  var initial = {cumulative: ee.Image(0), list: ee.List([])};
  var result = ee.List(targetYears).iterate(function(year, prev) {
    year = ee.Number(year);
    prev = ee.Dictionary(prev);
    var cumulative = ee.Image(prev.get('cumulative'));
    var imageForYear = ee.Image(
      sorted.filter(ee.Filter.eq('year', year)).first()
    ).unmask(0).gt(0);
    var updatedCumulative = cumulative.or(imageForYear);
    var yearImage = updatedCumulative.rename('forwardfill').set({
      'year': year,
      'system:time_start': ee.Date.fromYMD(year, 1, 1).millis(),
      'system:index': year.format()
    });
    var updatedList = ee.List(prev.get('list')).add(yearImage);
    return ee.Dictionary({cumulative: updatedCumulative, list: updatedList});
  }, initial);
  return ee.ImageCollection.fromImages(ee.Dictionary(result).get('list'));
}

function remapClassesToOne(image, classList) {
  return image.remap(classList, ee.List.repeat(1, classList.length)).selfMask();
}

function calculateSlope(elevation, aoi_mask) {
  var proj = elevation.first().select(0).projection();
  var processed_elevation = elevation.mosaic();
  if (aoi_mask) {
    processed_elevation = processed_elevation.updateMask(aoi_mask);
  }
  return ee.Terrain.slope(processed_elevation.setDefaultProjection(proj));
}

function generateOutcomeMaps(input_layer, mask_layer) {
  return {
    yes: input_layer.updateMask(mask_layer).selfMask(),
    no: input_layer.updateMask(mask_layer.not())
  };
}

function gladLulcForestPrep(analysisYear, treeHeightThreshold) {
  var gladLandcoverLand = ee.Image('projects/glad/GLCLU2020/v2/LCLUC_' + analysisYear)
    .updateMask(ee.Image('projects/glad/OceanMask').lte(1));
  var fromValues = [
    25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,
    125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147
  ];
  var toValues = [
    3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,
    3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25
  ];
  var gladLandcoverRemapped = gladLandcoverLand.remap(fromValues, toValues);
  return gladLandcoverRemapped.gte(treeHeightThreshold).rename('gladLulcForestSel_' + analysisYear);
}

// ═══ 5. EXPORT HELPERS ══════════════════════════════════════════════

var runNow = new Date();
var runPad = function(n) { return n < 10 ? '0' + n : n; };
var runTag = '_' + runPad(runNow.getHours()) + 'h' + runPad(runNow.getMinutes()) + 'm';
var taskCount = 0;

function mkExportName(iso3, step, name) {
  var parts = [];
  if (iso3) parts.push(iso3.toUpperCase());
  parts.push('gee');
  parts.push(step);
  parts.push(name);
  return parts.join('_') + runTag;
}

function doExport(image, description, folder, exportRegion) {
  Export.image.toDrive({
    image: image.toByte(),
    description: description,
    folder: folder,
    region: exportRegion,
    scale: EXPORT_SCALE,
    crs: EXPORT_CRS,
    maxPixels: 1e13,
    fileFormat: 'GeoTIFF',
    formatOptions: {cloudOptimized: true}
  });
  taskCount++;
}

function doExportInt16(image, description, folder, exportRegion) {
  Export.image.toDrive({
    image: image.toInt16(),
    description: description,
    folder: folder,
    region: exportRegion,
    scale: EXPORT_SCALE,
    crs: EXPORT_CRS,
    maxPixels: 1e13,
    fileFormat: 'GeoTIFF',
    formatOptions: {cloudOptimized: true}
  });
  taskCount++;
}

// ═══ 6. ANALYSIS PIPELINE ═══════════════════════════════════════════

function runCountry(countryName, iso3, analysisYears) {
  var countryClean = cleanCountryName(countryName);
  var folder = 'PFF_export_' + countryClean;
  var s = EXPORT_SCALE + 'm';

  var country_sel = getCountryFeatures(countryName);
  var country_geom = country_sel.geometry();
  var exportRegion = country_geom.buffer(COUNTRY_BUFFER_THRESHOLD + 1000).bounds();

  var country_clip = getCountryClip(countryName);
  var country_buffer = makeDistanceBuffer(country_clip, COUNTRY_BUFFER_THRESHOLD);
  var country_and_buffer_mask = country_buffer.where(country_clip, 1).selfMask();

  // ── DEM + slope (once per country, not per year) ──
  var alos_mosaic = alos_30m_elev.mosaic();
  doExportInt16(alos_mosaic.updateMask(country_and_buffer_mask).unmask(0),
    mkExportName(iso3, '03b', 'protection_natural_dem_' + s), folder, exportRegion);

  var slopeImage = calculateSlope(alos_30m_elev, country_and_buffer_mask);
  doExport(slopeImage.updateMask(country_and_buffer_mask).unmask(0).toByte(),
    mkExportName(iso3, '03b', 'protection_natural_slope_' + s), folder, exportRegion);

  // ── Slope areas for tier analysis ──
  var slopeAreasToKeep = slopeImage.gt(SLOPE_THRESHOLD);

  // ── Protected areas (once per country) ──
  var wdpaYearCutoff = current_year - YEARS_PROTECTED;
  var wdpa_filt_by_date_image = wdpaStatusYearGlobal.lte(wdpaYearCutoff);
  if (SELECTED_IUCN_CATEGORIES.length > 0 && SELECTED_IUCN_CATEGORIES.length < 10) {
    var combinedCategoryMask = ee.Image(0);
    for (var i = 0; i < SELECTED_IUCN_CATEGORIES.length; i++) {
      combinedCategoryMask = combinedCategoryMask.or(wdpaCategoryMasks[SELECTED_IUCN_CATEGORIES[i]]);
    }
    wdpa_filt_by_date_image = wdpa_filt_by_date_image.updateMask(combinedCategoryMask);
  }
  wdpa_filt_by_date_image = wdpa_filt_by_date_image.selfMask()
    .updateMask(country_and_buffer_mask);

  // ── Per-year layers ──
  analysisYears.forEach(function(analysisYear) {

    // 1. Forest source (GLAD LULC)
    var forest_map = gladLulcForestPrep(analysisYear, TREE_HEIGHT_THRESHOLD);

    // GLAD raw tree height
    var gladLandcoverLand = ee.Image('projects/glad/GLCLU2020/v2/LCLUC_' + analysisYear)
      .updateMask(ee.Image('projects/glad/OceanMask').lte(1));
    var heightFrom = [
      25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,
      125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147
    ];
    var heightTo = [
      3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,
      3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25
    ];
    var gladTreeHeight = gladLandcoverLand.remap(heightFrom, heightTo)
      .updateMask(country_and_buffer_mask).unmask(0).toByte().rename('tree_height_m');
    doExport(gladTreeHeight,
      mkExportName(iso3, '02a', 'glad_tree_height_m_' + analysisYear + '_' + s), folder, exportRegion);

    // 2. Anthropogenic layers
    // Built-up
    var builtUpSmall = ee.Image(0);
    var builtUpLargeImg = ee.Image(0);
    if (INCLUDE_WSF) {
      var wsfCollection = timeseriesAnthroModule.getWSFCollection();
      builtUpSmall = builtUpSmall.or(
        wsfCollection.filter(ee.Filter.eq('year', analysisYear)).first().eq(1)
      ).updateMask(country_and_buffer_mask);
    }
    if (INCLUDE_GHSL) {
      var ghslCollection = timeseriesAnthroModule.getGhslCollection();
      var ghslSel = ghslCollection.filter(ee.Filter.eq('year', analysisYear)).first()
        .updateMask(country_and_buffer_mask);
      builtUpSmall = builtUpSmall.or(ghslSel.eq(1));
      builtUpLargeImg = ghslSel.eq(2);
    }
    doExport(builtUpSmall.updateMask(country_and_buffer_mask).unmask(0),
      mkExportName(iso3, '03a', 'builtup_small_' + analysisYear + '_' + s), folder, exportRegion);
    doExport(builtUpLargeImg.updateMask(country_and_buffer_mask).unmask(0),
      mkExportName(iso3, '03a', 'builtup_large_' + analysisYear + '_' + s), folder, exportRegion);

    // Agriculture components
    var pastureDataset = ee.ImageCollection('projects/global-pasture-watch/assets/ggc-30m/v1/grassland_c');
    var pastureDatasetCultivated = pastureDataset.map(function(image) {
      return image.eq(1).set('year', ee.Number.parse(image.get('system:index')));
    });
    var pastureDatasetFF = forwardFillBinaryTimeSeries(
      pastureDatasetCultivated, FORWARD_FILL_YEARS.filter(function(y) { return y >= 2000; }));
    var pastureDatasetSel = pastureDatasetFF.filter(ee.Filter.eq('year', analysisYear)).first()
      .updateMask(country_and_buffer_mask);

    var oilPalmDescalsCollection = timeseriesAnthroModule.processingOilPalmDescals();
    var oilPalmDescalsSel = ee.Image(
      oilPalmDescalsCollection.filter(ee.Filter.eq('year', analysisYear)).first()
    ).updateMask(country_and_buffer_mask);

    var plantedForestSDPT = timeseriesAnthroModule.processingPlantedForestSDPT()
      .updateMask(country_and_buffer_mask);
    var treeCropsSDPT = timeseriesAnthroModule.processingTreeCropsSDPT()
      .updateMask(country_and_buffer_mask);
    var allPlantationsSel = plantedForestSDPT;

    // OLWTC bucket (FRA Note 10)
    var _treeCoverForOlwtc = forest_map.updateMask(country_and_buffer_mask);
    var urbanTreeCover = builtUpSmall.unmask(0)
      .or(builtUpLargeImg.unmask(0))
      .and(_treeCoverForOlwtc.unmask(0));
    var olwtc = oilPalmDescalsSel.unmask(0)
      .or(treeCropsSDPT.unmask(0))
      .or(urbanTreeCover);

    // FRA Forest baseline (02c) = tree cover minus OLWTC
    var forest_map_fra = REFINE_TO_FOREST
      ? forest_map.updateMask(olwtc.not())
      : forest_map;

    // OLWTC (02b) — other land with tree cover (FRA Note 10)
    doExport(olwtc.updateMask(country_and_buffer_mask).unmask(0).toByte(),
      mkExportName(iso3, '02b', 'other_land_with_tree_cover_' + analysisYear + '_' + s), folder, exportRegion);

    // Export 02a forest raw — thresholded tree cover (GLAD LULC ≥ 5 m)
    doExport(forest_map.updateMask(country_and_buffer_mask).unmask(0),
      mkExportName(iso3, '02a', 'forest_raw_' + analysisYear + '_' + s), folder, exportRegion);

    // Planted forest (02d)
    doExport(allPlantationsSel.unmask(0).toByte(),
      mkExportName(iso3, '02d', 'planted_forest_' + analysisYear + '_' + s), folder, exportRegion);

    // Agriculture aggregation
    var croplandGladCollection = timeseriesAnthroModule.processingCroplandsGlad();
    var croplandGladCollectionFF = forwardFillBinaryTimeSeries(croplandGladCollection, FORWARD_FILL_YEARS);
    var croplandGladSel = ee.Image(
      croplandGladCollectionFF.filter(ee.Filter.eq('year', analysisYear)).first()
    ).updateMask(country_and_buffer_mask);

    var agriculture = pastureDatasetSel
      .or(plantedForestSDPT.unmask())
      .or(treeCropsSDPT.unmask())
      .or(oilPalmDescalsSel.unmask())
      .or(croplandGladSel);
    doExport(agriculture.unmask(0),
      mkExportName(iso3, '03a', 'agriculture_' + analysisYear + '_' + s), folder, exportRegion);

    // 3. Analysis pipeline — tier cascade
    // Forest baseline for tier analysis
    var forest_baseline = REFINE_TO_NRF
      ? forest_map_fra.updateMask(allPlantationsSel.unmask().not())
      : forest_map_fra;
    forest_baseline = forest_baseline.updateMask(country_and_buffer_mask);

    // Roads (static)
    var roadsMosaicStatic = timeseriesAnthroModule.roadsMosaicStatic()
      .updateMask(country_and_buffer_mask);

    // Distance surfaces + thresholds
    var dist_road_small = makeDistanceSurface(roadsMosaicStatic);
    var dist_built_up_small = makeDistanceSurface(builtUpSmall);
    var dist_built_up_large = makeDistanceSurface(builtUpLargeImg);
    var dist_agriculture = makeDistanceSurface(agriculture);

    var buffer_from_road_small = applyDistanceThreshold(dist_road_small, ALL_BUFFER_DISTANCE);
    var buffer_from_built_up_small = applyDistanceThreshold(dist_built_up_small, ALL_BUFFER_DISTANCE);
    var buffer_from_built_up_large = applyDistanceThreshold(dist_built_up_large, ALL_BUFFER_DISTANCE);
    var buffer_from_agriculture = applyDistanceThreshold(dist_agriculture, ALL_BUFFER_DISTANCE);

    // Combine all buffers (all enabled)
    var buffer_from_anthro = ee.ImageCollection([
      buffer_from_road_small,
      buffer_from_built_up_small,
      buffer_from_built_up_large,
      buffer_from_agriculture
    ]).reduce(ee.Reducer.anyNonZero());
    var all_edge_effects = buffer_from_anthro.unmask();

    // Tier 1: outside buffers
    var step_1_1 = generateOutcomeMaps(forest_baseline, all_edge_effects);
    var forest_map_1_1_y = step_1_1.yes;
    var forest_map_1_1_n = step_1_1.no;

    // Tier 2: slope rescue
    var forest_map_1_2_y, forest_map_1_2_n;
    if (ENABLE_SLOPE) {
      var step_1_2 = generateOutcomeMaps(forest_map_1_1_y, slopeAreasToKeep);
      forest_map_1_2_y = step_1_2.yes;
      forest_map_1_2_n = step_1_2.no;
    } else {
      forest_map_1_2_y = forest_map_1_1_y.updateMask(ee.Image(0));
      forest_map_1_2_n = forest_map_1_1_y;
    }

    // Tier 3: protected area rescue
    var forest_map_1_3_y, forest_map_1_3_n;
    if (ENABLE_PROTECTED_AREAS) {
      var step_1_3 = generateOutcomeMaps(forest_map_1_2_n, wdpa_filt_by_date_image);
      forest_map_1_3_y = step_1_3.yes;
      forest_map_1_3_n = step_1_3.no;
    } else {
      forest_map_1_3_y = forest_map_1_2_n.updateMask(ee.Image(0));
      forest_map_1_3_n = forest_map_1_2_n;
    }

    // Combine tiers: T1 outside + T2 steep rescue + T3 PA rescue
    var combined_map = forest_map
      .where(forest_map_1_1_y.mask(), 1)
      .where(forest_map_1_1_n.mask(), 2)
      .where(forest_map_1_2_y.mask(), 3)
      .where(forest_map_1_2_n.mask(), 4)
      .where(forest_map_1_3_y.mask(), 5)
      .where(forest_map_1_3_n.mask(), 6)
      .where(forest_map.eq(0), 0);
    var all_forest_pre_refinement = combined_map.eq(2).or(combined_map.eq(3)).or(combined_map.eq(5));

    // Export pre-refinement (03c)
    doExport(all_forest_pre_refinement.updateMask(country_clip).unmask(0),
      mkExportName(iso3, '03c', 'pre_refinement_primary_forest_' + analysisYear + '_' + s), folder, exportRegion);

    // Connectivity refinement (04a)
    var primaryForest;
    if (ENABLE_REFINE_OUTPUT) {
      var density = all_forest_pre_refinement.reduceNeighborhood({
        reducer: ee.Reducer.sum(),
        kernel: ee.Kernel.circle({radius: SMOOTH_RADIUS, units: 'meters'}),
        skipMasked: false
      });
      primaryForest = density.gt(SMALL_PIXEL_THRESHOLD)
        .updateMask(all_forest_pre_refinement);
    } else {
      primaryForest = all_forest_pre_refinement;
    }
    doExport(primaryForest.updateMask(country_clip).unmask(0),
      mkExportName(iso3, '04a', 'primary_forest_' + analysisYear + '_' + s), folder, exportRegion);

    print(iso3 + ' ' + analysisYear + ' — raster tasks queued');
  }); // end per-year loop

  // ── Run metadata (one per year) ──
  analysisYears.forEach(function(metaYear) {
    var bundle = {
      'config__forest_source':         'GLAD LULC',
      'config__tree_height_threshold': TREE_HEIGHT_THRESHOLD,
      'config__buffer_roads_m':        ALL_BUFFER_DISTANCE,
      'config__buffer_builtup_small_m': ALL_BUFFER_DISTANCE,
      'config__buffer_builtup_large_m': ALL_BUFFER_DISTANCE,
      'config__buffer_agriculture_m':  ALL_BUFFER_DISTANCE,
      'config__enable_roads':          true,
      'config__enable_builtup_small':  true,
      'config__enable_builtup_large':  true,
      'config__enable_agriculture':    true,
      'config__enable_slope':          ENABLE_SLOPE,
      'config__slope_threshold_deg':   SLOPE_THRESHOLD,
      'config__enable_protected_areas': ENABLE_PROTECTED_AREAS,
      'config__iucn_categories':       SELECTED_IUCN_CATEGORIES.join(','),
      'config__years_protected':       YEARS_PROTECTED,
      'config__refine_output':         ENABLE_REFINE_OUTPUT,
      'config__smooth_radius_m':       SMOOTH_RADIUS,
      'config__density_threshold':     SMALL_PIXEL_THRESHOLD,
      'config__refine_to_forest':      REFINE_TO_FOREST,
      'config__refine_to_nrf':         REFINE_TO_NRF,
      'config__country_buffer_m':      COUNTRY_BUFFER_THRESHOLD,
      'config__fast_buffer':           FAST_BUFFER,
      'run__batch_script_version':     SCRIPT_VERSION,
      'run__pff_script_version':       '4.15.2',
      'run__timestamp':                new Date().toISOString(),
      'run__country':                  countryName,
      'run__iso3':                     iso3,
      'run__year_exported':            metaYear,
      'run__scale_m':                  EXPORT_SCALE,
      'run__export_destination':       'google_drive',
      'run__export_folder':            folder
    };
    var bundleFC = ee.FeatureCollection([ee.Feature(null, bundle)]);
    var bundlePrefix = iso3 + '_gee_run_metadata_' + metaYear + '_' + s + 'm';
    var bundleDesc = bundlePrefix + runTag;
    Export.table.toDrive({
      collection: bundleFC,
      description: bundleDesc,
      folder: folder,
      fileNamePrefix: bundlePrefix,
      fileFormat: 'GeoJSON'
    });
    taskCount++;
  });

  print(iso3 + ' — all tasks queued → Drive folder: ' + folder);
}

// ═══ 7. BATCH LOOP ══════════════════════════════════════════════════

print('PFF Batch Export v' + SCRIPT_VERSION);
print('Queueing exports for ' + COUNTRIES.length + ' countries at ' + EXPORT_SCALE + ' m...');
print('');

COUNTRIES.forEach(function(c) {
  runCountry(c.name, c.iso3, c.years);
});

print('');
print('Done — ' + taskCount + ' tasks queued. Go to the Tasks tab to run them.');

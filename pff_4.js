// Primary Forest Finder App
var PFF_SCRIPT_VERSION = "4.1.5";

// Changes vs v4.1.1:
//  • Bugfix: export region now uses .bounds() of the buffered country polygon
//    instead of the polygon itself. GEE writes rectangular GeoTIFFs regardless
//    of region shape, so using .bounds() (5 vertices) gives identical output
//    extent without the vertex-limit overflow that was failing Indonesia and
//    other archipelago countries. Non-archipelago countries produce identical
//    output.

// Changes vs v4.1.0:
//  • New "Plantations" export tickbox under Select Layers → dispatches a
//    separate binary plantations raster ('2_plantations_<year>_<scale>.tif').
//    The forest export itself remains raw (unchanged behaviour). The QGIS
//    plugin then applies the forest-AND-NOT-plantations mask at ingest time,
//    echoing the "Exclude plantations" checkbox in GEE. This enables the full
//    FRA stats cascade (Forest → Naturally regenerating forest → Primary
//    forest) without re-exporting.

// Changes vs v3:
//  • preprocessAsset() — each custom dataset asset path now supports a full
//    preprocessing pipeline: source type (image / image_collection /
//    feature_collection), band selection, class remapping, threshold, mosaic,
//    year_filter, and feature_collection inList filter.
//  • All custom asset paths now accept gs:// Cloud Storage COG URIs in addition
//    to standard GEE asset IDs (users/... or projects/...).
//  • A collapsible "⚙ Preprocessing" panel is shown below each custom dataset
//    textbox group; it defaults to 'image' with no extra transforms.

// AIM: run decision tree for primary forest delineation
print('Primary Forest Finder v' + PFF_SCRIPT_VERSION);

// Set to true when publishing as a GEE App (hides Export panel,
// which requires the Code Editor Tasks tab to function).
var IS_APP = false;

var latestMaskedForest = {};
var latestMaskedPrimaryForest = {};
var latestPreConnectivityForest = {};
var latestTier1Undisturbed = {};
var latestTier2Steep = {};
var latestTier3Protected = {};
var latestAnalysisYear = null;

//distance buffer calculations, when need to only (faster refresh when only changing slider vals)
var useCachingCheckbox = true

// Static GAUL LUT — eliminates blocking .getInfo() at startup
var gaulLut = require("users/andyarnellgee/apps:modules/gaulLut.js");
var fraStats = require("users/andyarnellgee/apps:modules/fraStats.js");
var country_names = gaulLut.country_names;     // pre-sorted, no server call

// GAUL 2024 boundaries: vector for geometry ops, raster for fast masking
var countries = ee.FeatureCollection("projects/sat-io/open-datasets/FAO/GAUL/GAUL_2024_L0");
var property_name = "gaul0_name"
// Simplified geometries (0.001° tolerance, diced to 10k vertices) for countries
// whose original GAUL polygons exceed the GEE vertex limit on .geometry().
var countries_simple = ee.FeatureCollection(
    "projects/ee-andyarnellgee/assets/crosscutting/GAUL_2024_L0_simplify_0_001deg_dice10k");
var gaul_raster = ee.Image("projects/ee-andyarnellgee/assets/gaul_2024_level_0_code_500m");
var default_country_selection = null;
var country_buffer_threshold = 2000

// Fast raster country mask (avoids vector .clip() per tile)
function getCountryClip(countryName) {
  var code = gaulLut.nameToCode(countryName);
  return gaul_raster.eq(code).selfMask();
}

/**
 * Get the country FeatureCollection, using the simplified asset for countries
 * with overly complex geometries that exceed GEE vertex limits.
 * @param {string} countryName - Country name (gaul0_name).
 * @return {ee.FeatureCollection} Filtered FC (one or more features).
 */
function getCountryFeatures(countryName) {
  var info = gaulLut.GAUL_LUT[gaulLut.nameToCode(countryName)];
  if (!info) return countries.filter(ee.Filter.eq(property_name, countryName));
  var iso3 = info.iso3;
  // Use simplified geometries for countries known to hit vertex limits
  if (iso3 === 'IDN' || iso3 === 'THA' || iso3 === 'DZA' || iso3 === 'AUS' || iso3 === 'CHN') {
    return countries_simple.filter(ee.Filter.eq('iso3_code', iso3));
  }
  return countries.filter(ee.Filter.eq(property_name, countryName));
}

//distance thresholds
var neighborhoodSize = 170 // 167 is about 5km at 30m resolution (30*167 = 5010)

var maxForAllDistances = 5100 // don't run any distance calcs over this distance (m) 
var roadSizeThreshold = 750 
var years_protected = 30; 
//slope_threshold_1_2 = 45, 
var fastBuffer = true

//built up data (currently code for checkboxes to include/exclude these are hidden for keeping interface simple)
var includeGISD = false // rock formation false positives (leaving out for now)
var includeGISA = false // rock formation false positives (leaving out for now)
var includeWSF = true
var includeGHSL = true

// IUCN categories
var categories = {
  strict: ['Ia', 'Ib','II'],
  no_filter: ["Not Assigned", "Not Reported", "IV", "II", "III", "V", "Ia", "VI", "Ib", "Not Applicable"]
};
var current_year = ee.Date(Date.now()).get('year').getInfo(); 
var selected_iucn_categories = categories['strict'];

// ============================================
// PRE-COMPUTE WDPA CATEGORY MASKS (cached once)
// ============================================
var allWdpaCategories = ['Ia', 'Ib', 'II', 'III', 'IV', 'V', 'VI', 'Not Reported', 'Not Assigned', 'Not Applicable'];
var wdpaCategoryMasks = {};

// Pre-compute all category masks at startup
var wdpaBase = ee.FeatureCollection("WCMC/WDPA/current/polygons")
  .filter(ee.Filter.and(
    ee.Filter.neq('STATUS', 'Proposed'), 
    ee.Filter.neq('STATUS', 'Not Reported'), 
    ee.Filter.neq('DESIG_ENG', 'UNESCO-MAB Biosphere Reserve')
  ));

// Cache the STATUS_YR layer (all PAs with year values)
var wdpaStatusYearGlobal = wdpaBase
  .reduceToImage({
    properties: ['STATUS_YR'],
    reducer: ee.Reducer.min()
  });

// Pre-compute category masks for each IUCN category
allWdpaCategories.forEach(function(cat) {
  wdpaCategoryMasks[cat] = wdpaBase.filter(ee.Filter.eq('IUCN_CAT', cat))
    .reduceToImage({properties: ['WDPAID'], reducer: ee.Reducer.first()})
    .unmask(0).gt(0);
});

// Visualization parameters
var binary_lightgreen_palette = {min:0, max:1, palette:["white","lightgreen"]};
var binary_green_palette = {min:0, max:1, palette:["white","#228B22"]};
var binary_darkgreen_palette = {min:0, max:1, palette:["white","#26600e"]};

// Utility functions
var makeDistanceBuffer = function(sourceImage, threshold, fastBuffer) {
  fastBuffer = (typeof fastBuffer !== 'undefined') ? fastBuffer : true;
  if (fastBuffer) {
    return sourceImage.fastDistanceTransform({neighborhood: neighborhoodSize}).sqrt()
      .multiply(ee.Image.pixelArea().sqrt()).lte(threshold).selfMask();
  } else {
    return ee.Image(1).cumulativeCost({source: sourceImage, maxDistance: threshold*1.2})
      .lte(threshold).selfMask();
  }
};



// =============================================================================
// ASSET LOADING WITH PREPROCESSING
// Supports GEE asset IDs (users/..., projects/...) and gs:// Cloud Storage
// COG URIs.  Returns a binary 0/1 ee.Image named 'presence'.
// =============================================================================
var preprocessAsset = function(assetPath, preprocessing) {
  preprocessing = preprocessing || {};
  var sourceType = preprocessing.source_type || 'image';
  var result;

  if (sourceType === 'feature_collection' || sourceType === 'table') {
    var fc = ee.FeatureCollection(assetPath);
    if (preprocessing.filter) {
      fc = fc.filter(ee.Filter.inList(
        preprocessing.filter.field, preprocessing.filter.values));
    }
    result = ee.Image(0).byte().paint(fc, 1).rename('presence');

  } else if (sourceType === 'image_collection') {
    var ic = ee.ImageCollection(assetPath);
    if (preprocessing.year_filter) {
      ic = ic.filter(ee.Filter.eq(
        preprocessing.year_filter.field, preprocessing.year_filter.value));
    }
    result = preprocessing.mosaic ? ic.max() : ic.first();

  } else {
    // Single image — accept GEE asset IDs or gs:// Cloud-Optimised GeoTIFF URIs
    if (assetPath.indexOf('gs://') === 0) {
      result = ee.Image.loadGeoTIFF(assetPath);
    } else {
      result = ee.Image(assetPath);
    }
  }

  // Band selection
  if (preprocessing.band !== undefined && preprocessing.band !== '') {
    result = result.select(preprocessing.band);
  }
  // Class remapping
  if (preprocessing.classes && preprocessing.classes.length > 0) {
    var classes = preprocessing.classes;
    var ones = ee.List.repeat(1, classes.length);
    result = result.remap(classes, ones, 0).gt(0);
  }
  // Threshold (threshold_min / threshold_max come from textboxes as strings)
  var tMin = preprocessing.threshold_min;
  var tMax = preprocessing.threshold_max;
  if ((tMin !== undefined && tMin !== '') || (tMax !== undefined && tMax !== '')) {
    var hasMin = tMin !== undefined && tMin !== '';
    var hasMax = tMax !== undefined && tMax !== '';
    if (hasMin && hasMax) {
      result = result.gte(Number(tMin)).and(result.lte(Number(tMax)));
    } else if (hasMin) {
      result = result.gte(Number(tMin));
    } else {
      result = result.lte(Number(tMax));
    }
  }

  return result.gt(0).unmask(0).byte().rename('presence');
};

var GRAYMAP = [
  {   // Dial down the map saturation.
    stylers: [ { saturation: -100 } ]
  },{ // Dial down the label darkness.
    elementType: 'labels',
    stylers: [ { lightness: 20 } ]
  },{ // Simplify the road geometries.
    featureType: 'road',
    elementType: 'geometry',
    stylers: [ { visibility: 'simplified' } ]
  },{ // Turn off road labels.
    featureType: 'road',
    elementType: 'labels',
    stylers: [ { visibility: 'off' } ]
  },{ // Turn off all icons.
    elementType: 'labels.icon',
    stylers: [ { visibility: 'off' } ]
  },{ // Turn off all POIs.
    featureType: 'poi',
    elementType: 'all',
    stylers: [ { visibility: 'off' }]
  }
];



// var property_name = "shapeName";
var cachedState = {
  country: null,
  year1: null,
  year2: null,
  distanceImages: {},
  slopeImage: null
};

////////////////////
// distance function 
var makeDistanceSurface = function(sourceImage, fastBuffer) {
  fastBuffer = (typeof fastBuffer !== 'undefined') ? fastBuffer : true;
  if (fastBuffer) {
    return sourceImage.fastDistanceTransform({neighborhood: neighborhoodSize}).sqrt()
      .multiply(ee.Image.pixelArea().sqrt());
  } else {
    // For cumulativeCost, we need a max distance - using a large value
    var MAX_BUFFER = maxForAllDistances; // Large enough for all your buffers
    return ee.Image(1).cumulativeCost({
      source: sourceImage, 
      maxDistance: MAX_BUFFER*1.2
    });
  }
};

//thresholding function
var applyDistanceThreshold = function(distanceImage, threshold) {
  return distanceImage.lte(threshold).selfMask();
};

// Zoom-dependent scale calculation for Hansen GFC visualization
// Adjusts rendering scale based on zoom level to prevent masking issues
function scaleForZoom(z, base_scale, pivot_z, r, min_scale, max_scale) {
  var s = base_scale * Math.pow(r, (pivot_z - z));
  s = Math.round(s);
  return Math.min(max_scale, Math.max(min_scale, s));
}

////////////
  function forwardFillBinaryTimeSeries(imageCollection, targetYears) {
      var sorted = imageCollection.sort('year');
    
      var initial = {
        cumulative: ee.Image(0),
        list: ee.List([])
      };
    
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
    
        return ee.Dictionary({
          cumulative: updatedCumulative,
          list: updatedList
        });
      }, initial);
    
      return ee.ImageCollection.fromImages(ee.Dictionary(result).get('list'));
    }
    



///////////


function remapClassesToOne(image, classList) {
  return image.remap(classList, ee.List.repeat(1, classList.length)).selfMask();
}

function calculateSlope(elevation, aoi_mask) {
  var proj = elevation.first().select(0).projection();
  
  // Mosaic elevation dataset
  var processed_elevation = elevation.mosaic();
  
  // Apply mask only if aoi_mask is provided
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



function cleanCountryName(name) {
  return name.replace(/[\u0300-\u036f]/g, "").replace(/[^a-zA-Z0-9 ]/g, "")
    .trim().replace(/\s+/g, "_");
}

// function tmfUndisturbedForestPrep(year) {
//   var tmfAnnual = ee.ImageCollection("projects/JRC/TMF/v1_2024/AnnualChanges").mosaic();
  
//   // Get binary undisturbed forest mask for given year (class 1 = undisturbed TMF)
//   var bandName = 'Dec' + year;
//   var undisturbed = tmfAnnual.select(bandName).eq(1);
  
//   return undisturbed.rename("TMF_Undisturbed_" + year);
// }

// var driversOfLoss = ee.Image("projects/landandcarbon/assets/wri_gdm_drivers_forest_loss_1km/v1_2_2001_2024");
// var driversOfLossNatural = drivers_1km.select("classification").remap([5,7],[1,1],0)

// Map.addLayer(driversOfLossNatural,{min:0,max:1,palette:["blue","red"]})


function gfcHansenTreecoverPrep(analysisYear, treecoverPercentThreshold) {
  // Use Hansen GFC v1.12 (2000–2024) for latest data
  var gfc = ee.Image('UMD/hansen/global_forest_change_2024_v1_12');
  
  var tree2000 = gfc.select('treecover2000').gt(treecoverPercentThreshold);
  var lossyear = gfc.select('lossyear').unmask(0); // 0=no loss
  
  // Keep = forest in 2000 AND (no loss OR loss after target year)
  // This properly handles the loss masking by year
  var keep = tree2000.and(lossyear.eq(0).or(lossyear.gt(analysisYear - 2000)));
  
  // Apply mask and keep transparent background
  var gfcHansenSel = tree2000.updateMask(keep).selfMask();
  
  return gfcHansenSel.rename("GFC_Hansen_" + analysisYear);
}

function gladLulcForestPrep(analysisYear, treeHeightThreshold) {
  var gladLandcoverLand = ee.Image('projects/glad/GLCLU2020/v2/LCLUC_' + analysisYear)
    .updateMask(ee.Image("projects/glad/OceanMask").lte(1));

  // Define remapping values
  var fromValues = [
    25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48,
    125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147
  ];
  var toValues = [
    3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26,
    3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25
  ];

  // Remap landcover classes to tree height values
  var gladLandcoverRemapped = gladLandcoverLand.remap(fromValues, toValues);

  // Apply tree height threshold (binary output)
  var gladLulcForestSel = gladLandcoverRemapped.gte(treeHeightThreshold);

  return gladLulcForestSel.rename("gladLulcForestSel_" + analysisYear);
}

function agreementForestPrep(analysisYear, treecoverPercentThreshold, treeHeightThreshold) {
  // Get both Hansen and GLAD forest layers
  var hansenForest = gfcHansenTreecoverPrep(analysisYear, treecoverPercentThreshold);
  var gladForest = gladLulcForestPrep(analysisYear, treeHeightThreshold);
  
  // Both datasets (AND) — conservative, highest confidence
  var agreementForest = hansenForest.and(gladForest);
  
  return agreementForest.rename("Agreement_" + analysisYear);
}

function unionForestPrep(analysisYear, treecoverPercentThreshold, treeHeightThreshold) {
  // Get both Hansen and GLAD forest layers
  var hansenForest = gfcHansenTreecoverPrep(analysisYear, treecoverPercentThreshold);
  var gladForest = gladLulcForestPrep(analysisYear, treeHeightThreshold);
  
  // Either dataset (OR) — inclusive, maximum coverage
  var unionForest = hansenForest.or(gladForest);
  
  return unionForest.rename("Union_" + analysisYear);
}

///to fix toggle shoukd work with

function toggleTreecoverSlider(value) {
  treecoverThresholdSlider.style().set('shown', value);
}

///to fix toggle shoukd work with
function toggleTreecoverHeightThresholdSlider(value) {
  treecoverHeightThresholdSlider.style().set('shown', value);
}


// UI setup
var years = [2000, 2010, 2015, 2020];

// var onTheFlyStatsRes = 900; // now controlled via statsScaleSlider

// =============================================================================
// PREPROCESSING UI FACTORY
// =============================================================================
// Creates a collapsible panel of preprocessing options for a custom dataset.
// Returns: { panel, getConfig(), collectSettings(), applySettings(s) }

function createPreprocessingUi() {
  var sourceTypeSelect = ui.Select({
    items: ['image', 'image_collection', 'feature_collection'],
    value: 'image',
    style: {fontSize: '10px', stretch: 'horizontal'},
    onChange: function(v) {
      var isRaster = (v !== 'feature_collection');
      rasterPanel.style().set('shown', isRaster);
      icPanel.style().set('shown', v === 'image_collection');
      fcPanel.style().set('shown', v === 'feature_collection');
    }
  });

  // Raster-only controls (hidden for feature_collection)
  var bandInput = ui.Textbox({
    placeholder: 'band name (optional)',
    style: {fontSize: '10px', stretch: 'horizontal'}
  });
  var classesInput = ui.Textbox({
    placeholder: 'pixel classes, e.g. 1,2,3 (optional)',
    style: {fontSize: '10px', stretch: 'horizontal'}
  });
  var threshMinInput = ui.Textbox({
    placeholder: 'min', style: {fontSize: '10px', width: '72px'}
  });
  var threshMaxInput = ui.Textbox({
    placeholder: 'max', style: {fontSize: '10px', width: '72px'}
  });
  var rasterPanel = ui.Panel({
    widgets: [
      ui.Panel(
        [ui.Label('Band:', {fontSize: '10px', margin: '4px 4px 0 0', width: '36px'}), bandInput],
        ui.Panel.Layout.flow('horizontal'), {margin: '2px 0'}),
      ui.Panel(
        [ui.Label('Classes:', {fontSize: '10px', margin: '4px 4px 0 0', width: '46px'}), classesInput],
        ui.Panel.Layout.flow('horizontal'), {margin: '2px 0'}),
      ui.Panel(
        [ui.Label('Threshold:', {fontSize: '10px', margin: '4px 4px 0 0'}),
         threshMinInput, ui.Label('–', {fontSize: '10px', margin: '4px 2px 0 2px'}), threshMaxInput],
        ui.Panel.Layout.flow('horizontal'), {margin: '2px 0'})
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: true, margin: '0'}
  });

  // ImageCollection-only controls
  var mosaicCheckbox = ui.Checkbox({label: 'max mosaic', value: true, style: {fontSize: '10px'}});
  var yrFilterFieldInput = ui.Textbox({placeholder: 'field', style: {fontSize: '10px', width: '80px'}});
  var yrFilterValInput   = ui.Textbox({placeholder: 'value', style: {fontSize: '10px', width: '60px'}});
  var icPanel = ui.Panel({
    widgets: [
      mosaicCheckbox,
      ui.Panel(
        [ui.Label('Year filter:', {fontSize: '10px', margin: '4px 4px 0 0'}), yrFilterFieldInput, yrFilterValInput],
        ui.Panel.Layout.flow('horizontal'), {margin: '2px 0'})
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, margin: '2px 0 0 8px'}
  });

  // FeatureCollection-only controls
  var fcFilterFieldInput = ui.Textbox({placeholder: 'field', style: {fontSize: '10px', width: '80px'}});
  var fcFilterValsInput  = ui.Textbox({placeholder: 'values, e.g. 1,2 or Ia,Ib', style: {fontSize: '10px', stretch: 'horizontal'}});
  var fcPanel = ui.Panel({
    widgets: [
      ui.Panel(
        [ui.Label('Filter field:', {fontSize: '10px', margin: '4px 4px 0 0'}), fcFilterFieldInput],
        ui.Panel.Layout.flow('horizontal'), {margin: '2px 0'}),
      ui.Panel(
        [ui.Label('Values:', {fontSize: '10px', margin: '4px 4px 0 0'}), fcFilterValsInput],
        ui.Panel.Layout.flow('horizontal'), {margin: '2px 0'})
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, margin: '2px 0 0 8px'}
  });

  var content = ui.Panel({
    widgets: [
      ui.Panel(
        [ui.Label('Type:', {fontSize: '10px', margin: '4px 4px 0 0', width: '36px'}), sourceTypeSelect],
        ui.Panel.Layout.flow('horizontal'), {margin: '2px 0'}),
      rasterPanel,
      icPanel,
      fcPanel
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, margin: '0', padding: '4px',
            backgroundColor: '#f5f5f5', border: '1px solid #ddd'}
  });

  var toggleBtn = ui.Button({
    label: '⚙ Preprocessing',
    onClick: function() {
      var s = content.style().get('shown');
      content.style().set({shown: !s});
      toggleBtn.setLabel(s ? '⚙ Preprocessing' : '▾ Preprocessing');
    },
    style: {fontSize: '10px', padding: '1px 6px', margin: '2px 0 0 0',
            backgroundColor: '#ebebeb'}
  });

  var panel = ui.Panel({
    widgets: [toggleBtn, content],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {margin: '0'}
  });

  return {
    panel: panel,

    getConfig: function() {
      var cfg = {source_type: sourceTypeSelect.getValue()};

      // Band / classes / threshold are raster-only — skip for feature_collection
      if (cfg.source_type !== 'feature_collection') {
        var band = bandInput.getValue();
        if (band && band.trim() !== '') cfg.band = band.trim();

        var classesStr = classesInput.getValue();
        if (classesStr && classesStr.trim() !== '') {
          cfg.classes = classesStr.split(',')
            .map(function(s) { return parseInt(s.trim()); })
            .filter(function(n) { return !isNaN(n); });
        }

        var tMin = threshMinInput.getValue();
        var tMax = threshMaxInput.getValue();
        if ((tMin && tMin.trim() !== '') || (tMax && tMax.trim() !== '')) {
          if (tMin && tMin.trim() !== '') cfg.threshold_min = tMin.trim();
          if (tMax && tMax.trim() !== '') cfg.threshold_max = tMax.trim();
        }
      }

      if (cfg.source_type === 'image_collection') {
        cfg.mosaic = mosaicCheckbox.getValue();
        var yrField = yrFilterFieldInput.getValue();
        var yrVal   = yrFilterValInput.getValue();
        if (yrField && yrField.trim() !== '' && yrVal && yrVal.trim() !== '') {
          var parsed = parseInt(yrVal.trim());
          cfg.year_filter = {
            field: yrField.trim(),
            value: isNaN(parsed) ? yrVal.trim() : parsed
          };
        }
      }

      if (cfg.source_type === 'feature_collection') {
        var fcField = fcFilterFieldInput.getValue();
        var fcVals  = fcFilterValsInput.getValue();
        if (fcField && fcField.trim() !== '' && fcVals && fcVals.trim() !== '') {
          var parsedVals = fcVals.split(',').map(function(s) {
            var t = s.trim();
            var n = parseInt(t);
            return isNaN(n) ? t : n;
          });
          cfg.filter = {field: fcField.trim(), values: parsedVals};
        }
      }

      return cfg;
    },

    collectSettings: function() {
      return {
        source_type:     sourceTypeSelect.getValue(),
        band:            bandInput.getValue(),
        classes:         classesInput.getValue(),
        threshold_min:   threshMinInput.getValue(),
        threshold_max:   threshMaxInput.getValue(),
        mosaic:          mosaicCheckbox.getValue(),
        yr_filter_field: yrFilterFieldInput.getValue(),
        yr_filter_val:   yrFilterValInput.getValue(),
        fc_filter_field: fcFilterFieldInput.getValue(),
        fc_filter_vals:  fcFilterValsInput.getValue()
      };
    },

    applySettings: function(s) {
      if (!s) return;
      if (s.source_type)     sourceTypeSelect.setValue(s.source_type, true);
      if (s.band        !== undefined) bandInput.setValue(s.band);
      if (s.classes     !== undefined) classesInput.setValue(s.classes);
      if (s.threshold_min !== undefined) threshMinInput.setValue(s.threshold_min);
      if (s.threshold_max !== undefined) threshMaxInput.setValue(s.threshold_max);
      if (s.mosaic      !== undefined) mosaicCheckbox.setValue(s.mosaic);
      if (s.yr_filter_field !== undefined) yrFilterFieldInput.setValue(s.yr_filter_field);
      if (s.yr_filter_val   !== undefined) yrFilterValInput.setValue(s.yr_filter_val);
      if (s.fc_filter_field !== undefined) fcFilterFieldInput.setValue(s.fc_filter_field);
      if (s.fc_filter_vals  !== undefined) fcFilterValsInput.setValue(s.fc_filter_vals);
    }
  };
}

// =============================================================================
// REUSABLE ASSET INPUT FACTORY
// =============================================================================
// Creates dynamic year-based asset input UI components for any dataset type.
// Returns an object with: panel, getAsset(year), updateVisibility(), getPreprocessingConfig()

function createYearAssetInputs(config) {
  var placeholder = config.placeholder || 'users/username/asset';

  var inputs = {};
  var panels = {};
  var containerPanel = ui.Panel({style: {shown: false, margin: '2px 0 0 12px'}});

  years.forEach(function(year) {
    var yearPanel = ui.Panel({
      layout: ui.Panel.Layout.flow('horizontal'),
      style: {margin: '2px 0', shown: false}
    });
    yearPanel.add(ui.Label(year + ':', {fontSize: '10px', margin: '5px 4px 0 0', width: '36px'}));
    var assetInput = ui.Textbox({
      placeholder: placeholder.replace('{year}', year),
      style: {fontSize: '10px', stretch: 'horizontal'}
    });
    inputs[year] = assetInput;
    panels[year] = yearPanel;
    yearPanel.add(assetInput);
    containerPanel.add(yearPanel);
  });

  // Preprocessing UI — one shared config for all years of this dataset
  var prepUi = createPreprocessingUi();
  containerPanel.add(prepUi.panel);

  return {
    panel: containerPanel,
    inputs: inputs,

    // Get asset ID for a specific year
    getAsset: function(year) {
      return inputs[year] ? inputs[year].getValue() : '';
    },

    // Get preprocessing config (shared across all years)
    getPreprocessingConfig: function() {
      return prepUi.getConfig();
    },

    // Update visibility based on selected years
    updateVisibility: function(splitScreenEnabled, year1, year2) {
      years.forEach(function(year) {
        var showYear = false;
        if (splitScreenEnabled) {
          showYear = (year === year1 || year === year2);
        } else {
          showYear = (year === year2);
        }
        panels[year].style().set('shown', showYear);
      });
    },

    // Show/hide entire panel
    setShown: function(shown) {
      containerPanel.style().set('shown', shown);
    }
  };
}

// =============================================================================
// STATE MANAGEMENT
// =============================================================================

var appState = {
  ui: {
    datesCollapsed: true,
    treeCoverCollapsed: true,
    anthropogenicCollapsed: true,
    limitedAccessCollapsed: true,
    connectivityCollapsed: true,
    layersPanelCollapsed: true,
    leftPanelCollapsed: false,
    rightPanelCollapsed: false
  },
  map: {
    currentMode: 'single',
    lastCenter: null,
    lastZoom: null,
    previousCountry: null
  }
};

// Track year label widgets so we can remove them on update
var yearLabel1Widget = null;
var yearLabel2Widget = null;

// Track which layers are currently visible (state persistence)
var _legendRefreshFns = [];  // legend refresh callbacks

var visibleLayers = {
  // Analysis outputs
  primaryForest: true,       // Default on
  forestOutsideBuffers: false,
  forest: false,
  // Processed binary inputs (what feeds the distance transforms)
  inputRoads: false,
  inputBuiltupSmall: false,
  inputBuiltupLarge: false,
  inputAgriculture: false,
  // Buffer zones
  roadSmallBuffer: false,
  // roadLargeBuffer removed — single roads category only
  builtSmallBuffer: false,
  builtLargeBuffer: false,
  agriBuffer: false,
  // Other
  plantations: false,
  slope: false,
  protectedAreas: false,
  flii: false,
  countryOutline: true
};

// Reset layer visibility to defaults (primary forest on, everything else off)
function resetVisibleLayers() {
  visibleLayers.primaryForest = true;
  visibleLayers.forestOutsideBuffers = false;
  visibleLayers.forest = false;
  visibleLayers.inputRoads = false;
  visibleLayers.inputBuiltupSmall = false;
  visibleLayers.inputBuiltupLarge = false;
  visibleLayers.inputAgriculture = false;
  visibleLayers.roadSmallBuffer = false;
  visibleLayers.builtSmallBuffer = false;
  visibleLayers.builtLargeBuffer = false;
  visibleLayers.agriBuffer = false;
  visibleLayers.plantations = false;
  visibleLayers.slope = false;
  visibleLayers.protectedAreas = false;
  visibleLayers.flii = false;
  visibleLayers.countryOutline = true;
}

// toggleLayerByName uses prefix matching for Slope / Protected Areas
// (their layer names include dynamic values like degrees or year).
var LAYER_PREFIX_MAP = [
  {prefix: 'Input: Slope',       key: 'slope'},
  {prefix: 'Input: Protected',   key: 'protectedAreas'},
  {prefix: 'Input: Forest',       key: 'Input: Forest'}
];

// Toggle a named layer on both maps without triggering a full recompute.
// Used by the layer-panel checkboxes.
function toggleLayerByName(name, shown) {
  [map1, map2].forEach(function(m) {
    if (!m) return;
    var layers = m.layers();
    for (var i = 0; i < layers.length(); i++) {
      var layer = layers.get(i);
      var lname = layer.getName();
      var match = (lname === name);
      if (!match) {
        // prefix match for dynamic names
        for (var j = 0; j < LAYER_PREFIX_MAP.length; j++) {
          if (LAYER_PREFIX_MAP[j].key === name && lname.indexOf(LAYER_PREFIX_MAP[j].prefix) === 0) {
            match = true; break;
          }
        }
      }
      if (match) layer.setShown(shown);
    }
  });
  // Refresh all legend panels to show only visible layers
  _legendRefreshFns.forEach(function(fn) { fn(); });
}

var updateLeftPanelWidth = function() {
  var allCollapsed = appState.ui.datesCollapsed &&
                     appState.ui.treeCoverCollapsed && 
                     appState.ui.anthropogenicCollapsed && 
                     appState.ui.limitedAccessCollapsed && 
                     appState.ui.connectivityCollapsed;
  
  if (allCollapsed) {
    leftPanel.style().set({width: '150px'});
  } else {
    leftPanel.style().set({width: '310px'});
  }
};

var updateRightPanelWidth = function() {
  var statsShown = statsContent.style().get('shown');
  var configShown = settingsContent.style().get('shown');
  var downloadsShown = downloadsContent && downloadsContent.style().get('shown');
  
  if (!statsShown && !configShown && !downloadsShown) {
    rightPanel.style().set({width: '120px'});
  } else if (downloadsShown) {
    rightPanel.style().set({width: '340px'});
  } else if (statsShown) {
    rightPanel.style().set({width: '320px'});
  } else {
    rightPanel.style().set({width: '280px'});
  }
};

// Accordion helper - collapses all panels except the specified one
var collapseAllPanelsExcept = function(exceptPanel) {
  // This will be populated after panel definitions
};

// =============================================================================
// UI COMPONENTS - TOP BAR
// =============================================================================

var countryWarningLabel = ui.Label('', {color: '#cc6666', fontSize: '11px', margin: '6px 0 0 0', shown: false});

var countrySelector = ui.Select({
  items: country_names,
  placeholder: 'Choose country',
  onChange: function(value) {
    // Clear red highlight and warning when a country is selected
    countrySelector.style().set({border: '1px solid #ccc', color: 'black'});
    countryWarningLabel.style().set({shown: false});
    updateMap();
  },
  style: {width: '150px', margin: '4px 8px'}
});

// Recenter button - zooms to selected country on demand
var recenterButton = ui.Button({
  label: '⊕',
  onClick: function() {
    var selectedCountry = countrySelector.getValue();
    if (!selectedCountry) return;
    var country_features = getCountryFeatures(selectedCountry);
    var centroid = country_features.geometry().centroid().coordinates().getInfo();
    var useSplitScreen = enableSplitScreenCheckbox.getValue();
    if (useSplitScreen && map1) {
      map1.setCenter(centroid[0], centroid[1], 6);
      if (map2) {
        map2.setCenter(centroid[0], centroid[1], 6);
      }
    } else if (map2) {
      map2.setCenter(centroid[0], centroid[1], 6);
    }
  },
  style: {margin: '4px 2px', padding: '0px 4px', fontSize: '24px'}
});

var yearSelector1Label = ui.Label('Year 1:', {margin: '4px 0px'});

var yearSelector1 = ui.Select({
  items: years.map(String), 
  value: '2000', 
  onChange: function(value) {
    updateVisibleAssetInputs();
    updateMap();
  },
  style: {width: '80px', margin: '4px 8px'}
});
yearSelector1.style().set({shown: false});
yearSelector1Label.style().set({shown: false});

var yearSelector2Label = ui.Label('Year:', {margin: '4px 0px'});

var yearSelector2 = ui.Select({
  items: years.map(String), 
  value: '2020', 
  onChange: function(value) {
    updateVisibleAssetInputs();
    updateMap();
  },
  style: {width: '80px', margin: '4px 8px'}
});

var enableSplitScreenCheckbox = ui.Checkbox({
  label: 'Compare Years',
  value: false,
  onChange: function(checked) {
    yearSelector1Label.style().set({shown: checked});
    yearSelector1.style().set({shown: checked});
    yearSelector2Label.setValue(checked ? 'Year 2:' : 'Year:');
    updateVisibleAssetInputs();
    updateMap();
  },
  style: {margin: '4px 8px'}
});

var appTitle = ui.Label('Primary Forest Finder (Beta)', {
  fontWeight: 'bold',
  fontSize: '18px',
  margin: '4px 8px',
  textAlign: 'center'
});


var titleSpacer = ui.Panel({style: {stretch: 'horizontal'}});

// About popup — full-width banner below the top bar, with an X close button
var aboutCloseButton = ui.Button({
  label: '✕',
  onClick: function() { aboutContent.style().set({shown: false}); },
  style: {margin: '0', padding: '0 6px', fontSize: '12px', backgroundColor: '#e8e8e8'}
});

var aboutHeaderRow = ui.Panel({
  widgets: [
    ui.Label('Primary Forest Finder', {fontWeight: 'bold', fontSize: '14px', margin: '0', stretch: 'horizontal'}),
    aboutCloseButton
  ],
  layout: ui.Panel.Layout.flow('horizontal'),
  style: {stretch: 'horizontal', margin: '0 0 6px 0'}
});

var aboutContent = ui.Panel({
  widgets: [
    aboutHeaderRow,
    ui.Label(
      'An open tool for delineating primary and intact forests using ' +
      'satellite-derived tree cover, anthropogenic disturbance buffers, ' +
      'protected area status, terrain analysis, and connectivity filtering. ' +
      'Designed to support national forest monitoring and reporting ' +
      '(e.g. FAO FRA) with transparent, reproducible methods.',
      {fontSize: '11px', margin: '0 0 8px 0'}),
    ui.Label('Resources:', {fontWeight: 'bold', fontSize: '11px', margin: '0 0 2px 0'}),
    ui.Label('Documentation — https://example.com/pff-docs', {fontSize: '11px', margin: '0 0 2px 4px'}),
    ui.Label('Source code — https://example.com/pff-source', {fontSize: '11px', margin: '0 0 2px 4px'}),
    ui.Label('Contact — primaryforestfinder@example.com', {fontSize: '11px', margin: '0 0 0 4px'})
  ],
  style: {
    shown: false, stretch: 'horizontal', padding: '10px',
    backgroundColor: 'rgba(255, 255, 255, 0.98)',
    border: '1px solid #ccc'
  }
});

var aboutButton = ui.Button({
  label: 'About',
  onClick: function() {
    var isShown = aboutContent.style().get('shown');
    aboutContent.style().set({shown: !isShown});
  },
  style: {margin: '4px 8px', padding: '2px 8px', fontSize: '11px', backgroundColor: '#e8e8e8'}
});

// RUN BUTTON - triggers analysis (instead of auto-update on slider change)
var runButton = ui.Button({
  label: '↻ Update Analysis',
  onClick: function() {
    // Clear stats when updating to prevent stale data
    if (typeof areaStatsPanel !== 'undefined') {
      areaStatsPanel.clear();
    }
    updateMap();
  },
  style: {
    fontWeight: 'bold',
    fontSize: '12px',
    padding: '2px 12px',
    margin: '2px 8px',
    backgroundColor: '#4CAF50',
    color: '#333333'
  }
});

// Track if parameters have changed since last update
var needsUpdate = false;

function markNeedsUpdate() {
  if (!needsUpdate) {
    needsUpdate = true;
    runButton.setLabel('↻ Update Analysis *');
  }
  showStatsButton.setLabel('↻ Show Area\nStatistics *');
}

function markUpToDate() {
  needsUpdate = false;
  runButton.setLabel('↻ Update Analysis');
}

var topBarRow = ui.Panel({
  widgets: [appTitle, countrySelector, countryWarningLabel, recenterButton, titleSpacer, aboutButton],
  layout: ui.Panel.Layout.flow('horizontal'),
  style: {stretch: 'horizontal', padding: '0'}
});

var topBar = ui.Panel({
  widgets: [topBarRow, aboutContent],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {
    stretch: 'horizontal',
    backgroundColor: 'rgba(255, 255, 255, 0.95)',
    padding: '4px',
    border: '1px solid #ccc'
  }
});

// =============================================================================
// SLIDERS (using pff2 values)
// =============================================================================

var treecoverThresholdSlider = ui.Slider({min: 0, max: 100, value: 10, step: 5, onChange: markNeedsUpdate});
var treecoverHeightThresholdSlider = ui.Slider({min: 3, max: 25, value: 5, step: 1, onChange: markNeedsUpdate});
var roadSmallBufferSlider = ui.Slider({min: 0, max: 5000, value: 1000, step: 50, onChange: markNeedsUpdate});
// roadLargeBufferSlider removed — single roads category only
var builtUpSmallBufferSlider = ui.Slider({min: 0, max: 5000, value: 1000, step: 50, onChange: markNeedsUpdate});
var builtUpLargeBufferSlider = ui.Slider({min: 0, max: 5000, value: 1000, step: 50, onChange: markNeedsUpdate});
var agriBufferSlider = ui.Slider({min: 0, max: 5000, value: 1000, step: 50, onChange: markNeedsUpdate});

// Master buffer slider — sets all influence buffer distances at once
var masterBufferSlider = ui.Slider({
  min: 0, max: 5000, value: 1000, step: 50,
  onChange: function(value) {
    roadSmallBufferSlider.setValue(value, false);
    builtUpSmallBufferSlider.setValue(value, false);
    builtUpLargeBufferSlider.setValue(value, false);
    agriBufferSlider.setValue(value, false);
    markNeedsUpdate();
  }
});

// Panels that hold individual slider rows (created later, referenced here)
var individualBufferRows = null; // set after anthropogenicContent is built
var masterBufferRow = null;      // set after anthropogenicContent is built

var useMasterBufferCheckbox = ui.Checkbox({
  label: 'Use single distance for all:',
  value: false,
  onChange: function(checked) {
    if (individualBufferRows) {
      individualBufferRows.forEach(function(row) {
        row.style().set({shown: !checked});
      });
    }
    if (masterBufferRow) {
      masterBufferRow.style().set({shown: checked});
    }
    if (checked) {
      // Sync all sliders to master value
      var val = masterBufferSlider.getValue();
      roadSmallBufferSlider.setValue(val, false);
      builtUpSmallBufferSlider.setValue(val, false);
      builtUpLargeBufferSlider.setValue(val, false);
      agriBufferSlider.setValue(val, false);
      markNeedsUpdate();
    }
  },
  style: {fontSize: '11px', margin: '4px 0 0 0'}
});
var slopeToKeepSlider = ui.Slider({min: 0, max: 90, value: 45, step: 5, onChange: markNeedsUpdate});

  
// Cache for country hex grids
var countryHexGridCache = {};

// Format a number string with commas for thousands (e.g. "1234567.8" -> "1,234,567.8")
function formatWithCommas(numStr) {
  var parts = numStr.split('.');
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return parts.join('.');
}

function processForestAreaStats(image, name, year, scale, exportToDrive, country, panel, onComplete) {
  var pixelArea = ee.Image.pixelArea();
  var forestArea = image.multiply(pixelArea);

  // Use the country from parameter or global
  var countryName = country || selectedCountry;
  // Use cache for country hex grid
  if (!countryHexGridCache[countryName]) {
    var country_features = getCountryFeatures(countryName);
    countryHexGridCache[countryName] = country_features.geometry().coveringGrid('EPSG:4326', 50000);
  }
  var country_hex_grid = countryHexGridCache[countryName];

  var stats = forestArea.reduceRegions({
    collection: country_hex_grid,
    reducer: ee.Reducer.sum(),
    scale: scale
  });

  var totalArea = stats.aggregate_sum('sum');

  if (!exportToDrive) {
    totalArea.evaluate(function(result) {
      var msg;
      if (result !== null && result !== undefined) {
        var formattedResultKha = formatWithCommas(Number(result / 1e7).toFixed(1));
        msg = "✓ " + name + ": " + formattedResultKha + " kha";
      } else {
        msg = "✗ " + name + " (" + year + "): No valid data / processing timeout";
      }
      if (panel) {
        panel.add(ui.Label(msg));
      } else {
        print(msg);
      }
      if (onComplete) {
        onComplete();
      }
    });
  } else {
    // Only include relevant thresholds for each dataset
    var isHansen = name.indexOf('Treecover') !== -1;
    var isGlad = name.indexOf('Primary Forest') !== -1;
    var feature = ee.Feature(null, {
      'Country': countryName,
      'Year': year,
      'Forest Type': name,
      'Area (sq km)': totalArea.divide(1e6),
      'Resolution (m)': scale,
      "Treecover Threshold (%)": isHansen ? treecoverThresholdSlider.getValue() : '',
      'GLAD Treecover Height (m)': isGlad ? treecoverHeightThresholdSlider.getValue() : '',
      "Road Small Buffer (m)": roadSmallBufferSlider.getValue(),
      "Built-Up Small Buffer (m)": builtUpSmallBufferSlider.getValue(),
      "Built-Up Large Buffer (m)": builtUpLargeBufferSlider.getValue(),
      "Agriculture Buffer (m)": agriBufferSlider.getValue(),
      // "Other Natural Buffer (m)": otherNatBuffer,
      "Slope to Keep": slopeToKeepSlider.getValue(),
      // "Slope Threshold (%)": ,
      "Years Protected": years_protected,
      // "Fast Buffer Used": fastBuffer ? "Yes" : "No",
      "Strict IUCN Categories": selected_iucn_categories.join(", "),
      "Plantations Included": includePlantationsCheckbox.getValue() ? "No" : "Yes"
    });
    
    Export.table.toDrive({
      collection: ee.FeatureCollection([feature]),
      description: "Area_" + name.replace(/[\s.()]+/g, "_").replace(/_+/g, "_").replace(/_$/, "") + "_" + year + "_" +
                  cleanCountryName(countryName) + "_" + scale + "m",
      fileFormat: "CSV"
    });
  }
}


var showStatsButton = ui.Button({
  label: '↻ Show Area\nStatistics',
  style: {width: '180px', margin: '8px 0 8px 8px', fontWeight: 'bold', fontSize: '11px', whiteSpace: 'pre-wrap'},
  onClick: function() {
    showStatsButton.setLabel('↻ Show Area\nStatistics');
    areaStatsPanel.clear();
    var selectedCountry = countrySelector.getValue();
    if (!selectedCountry) {
      areaStatsPanel.add(ui.Label('Please select a country first.'));
      return;
    }
    if (Object.keys(latestMaskedForest).length === 0) {
      areaStatsPanel.add(ui.Label('No forest data available. Please wait for the map to load first.'));
      return;
    }
    var selectedCountry = countrySelector.getValue();
    areaStatsPanel.add(ui.Label(selectedCountry, {fontWeight: 'bold'}));
    var statsScale = statsScaleSlider.getValue();
    areaStatsPanel.add(ui.Label('(Estimated at ' + statsScale + 'm resolution)', {fontSize: '11px', color: '#666', margin: '0 0 8px 0'}));

    // Create a panel for each year so results appear in order
    Object.keys(latestMaskedForest).forEach(function(year) {
      var yearInt = parseInt(year);
      var yearPanel = ui.Panel({layout: ui.Panel.Layout.flow('vertical')});
      yearPanel.add(ui.Label('Year ' + year + ':', {fontWeight: 'bold', margin: '4px 0 2px 0'}));
      areaStatsPanel.add(yearPanel);

      // FRA comparison line (static, instant) — shown first
      var fraLabel = fraStats.formatFRA(selectedCountry, yearInt);
      yearPanel.add(ui.Label('  ' + fraLabel, {fontSize: '11px', color: '#555', margin: '0 0 2px 4px'}));
      // Separator between FRA and calculated values
      yearPanel.add(ui.Label('  ───────────', {color: '#ccc', fontSize: '9px', margin: '0 0 2px 4px'}));
      // Progress indicator — updates per step
      var calcLabel = ui.Label('  Calculating total forest area...', {color: '#888', fontStyle: 'italic'});
      yearPanel.add(calcLabel);

      // Track pending calculations for this year
      var pending = latestMaskedPrimaryForest[year] ? 2 : 1;
      var checkDone = function() {
        pending--;
        if (pending === 0) {
          yearPanel.remove(calcLabel);
        }
      };

      var treecoverLabel = includePlantationsCheckbox.getValue() ? 'Total Treecover (excl. plantations)' : 'Total Treecover (incl. plantations)';
      processForestAreaStats(latestMaskedForest[year], treecoverLabel, yearInt, statsScale, false, selectedCountry, yearPanel, function() {
        if (latestMaskedPrimaryForest[year]) {
          calcLabel.setValue('  Calculating primary forest area...');
        }
        checkDone();
      });
      if (latestMaskedPrimaryForest[year]) {
        processForestAreaStats(latestMaskedPrimaryForest[year], "Primary Forest", yearInt, statsScale, false, selectedCountry, yearPanel, checkDone);
      }
    });
  }
});



// Helper to get native resolution string based on selected forest data source
function getNativeResolutionText() {
  var src = treecoverSourceSelect.getValue();
  if (src === 'Hansen GFC') return '~30m (Hansen GFC)';
  if (src === 'GLAD LULC') return '~30m (GLAD LULC)';
  if (src === 'Custom Forest') return 'unknown (custom asset)';
  return '~30m (Hansen GFC & GLAD LULC)';
}

// Info popup for area statistics
var statsInfoContent = ui.Panel({
  widgets: [
    ui.Label('Area Statistics — Notes', {fontWeight: 'bold', fontSize: '12px', margin: '0 0 4px 0'}),
    ui.Label('On-the-fly statistics may time out at high resolutions ' +
             'for large countries. If this happens, try increasing the ' +
             'Resolution slider or use "Export Statistics to Drive" which has ' +
             'larger time and memory allowances.',
             {fontSize: '11px', margin: '0 0 6px 0'}),
    ui.Label('Note: statistics computed at a resolution coarser than the ' +
             'native resolution of the forest data ' +
             'can differ significantly from native-resolution results.',
             {fontSize: '11px', margin: '0 0 6px 0'}),
    ui.Label('FRA values shown are reported national statistics from the ' +
             'FAO Forest Resources Assessment (FRA 2025).',
             {fontSize: '11px', margin: '0 0 6px 0'}),
    ui.Label('─── Definitions ───', {fontWeight: 'bold', fontSize: '11px', color: '#888', margin: '4px 0 2px 0'}),
    ui.Label('FOREST: Land spanning more than 0.5 hectares with trees ' +
             'higher than 5 meters and a canopy cover of more than 10 percent, ' +
             'or trees able to reach these thresholds in situ. It does not ' +
             'include land that is predominantly under agricultural or urban land use.',
             {fontSize: '10px', margin: '0 0 4px 0'}),
    ui.Label('NATURALLY REGENERATING FOREST: Forest predominantly composed ' +
             'of trees established through natural regeneration.',
             {fontSize: '10px', margin: '0 0 4px 0'}),
    ui.Label('PRIMARY FOREST: Naturally regenerating forest of native tree ' +
             'species, where there are no clearly visible indications of human ' +
             'activities and the ecological processes are not significantly disturbed.',
             {fontSize: '10px', margin: '0 0 4px 0'}),
    ui.Label({
      value: 'FRA 2025 Definitions',
      style: {fontSize: '10px', color: 'blue', textDecoration: 'underline', margin: '0 0 0 0'},
      targetUrl: 'https://fra-data.fao.org/definitions/fra/2025/en/tad#1b'
    })
  ],
  style: {shown: false, padding: '6px', margin: '4px 0 4px 8px', backgroundColor: '#fff8e1', border: '1px solid #e0c050', width: '240px'}
});

var statsInfoButton = ui.Button({
  label: ' i ',
  onClick: function() {
    var isShown = statsInfoContent.style().get('shown');
    // Refresh native resolution text each time
    statsInfoContent.widgets().set(2,
      ui.Label('Note: statistics computed at a resolution coarser than the ' +
               'native resolution of the forest data (currently ' + getNativeResolutionText() + ') ' +
               'can differ significantly from native-resolution results.',
               {fontSize: '11px', margin: '0 0 6px 0'})
    );
    statsInfoContent.style().set({shown: !isShown});
  },
  style: {padding: '4px 8px', margin: '12px 0 0 4px', fontSize: '13px', fontWeight: 'bold', backgroundColor: '#e0e0e0'}
});

// Panel to display area statistics results (must be defined before showStatsButton)
var areaStatsPanel = ui.Panel({
  layout: ui.Panel.Layout.flow('vertical'),
  style: {
    margin: '8px 0 8px 8px', 
    padding: '8px', 
    backgroundColor: '#f7f7f7', 
    border: '1px solid #ccc',
    width: '250px'
  }
});

// Button to clear the area statistics panel
var clearStatsButton = ui.Button({
  label: 'Clear Statistics',
  style: {width: '180px', margin: '0 0 6px 8px', backgroundColor: '#eee', color: '#888', fontSize: '10px'},
  onClick: function() {
    areaStatsPanel.clear();
    exportStatusLabel.setValue('');
  }
});




// Shared scale slider for both on-the-fly and export statistics
var statsScaleSlider = ui.Slider({
  min: 30, max: 3000, value: 900, step: 30,
  style: {margin: '0 0 6px 0', stretch: 'horizontal'},
  onChange: function() {}
});
var statsScaleLabel = ui.Label('Resolution (m):', {margin: '0 8px 0 0'});

// Label for export status message
var exportStatusLabel = ui.Label('', {margin: '4px 0 0 8px', width: '280px'});

// Button to export statistics as CSV
var exportStatsButton = ui.Button({
  label: 'Export Statistics to Drive',
  style: {width: '180px', margin: '0 0 6px 8px', backgroundColor: '#e0ffe0'},
  onClick: function() {
    exportStatusLabel.setValue('');
    if (Object.keys(latestMaskedForest).length === 0) {
      exportStatusLabel.setValue('No forest data to export.');
      return;
    }
    var selectedCountry = countrySelector.getValue();
    if (!selectedCountry) {
      exportStatusLabel.setValue('Please select a country first.');
      return;
    }
    var exportScale = statsScaleSlider.getValue();
    Object.keys(latestMaskedForest).forEach(function(year) {
      var yearInt = parseInt(year);
      var treecoverLabel = includePlantationsCheckbox.getValue() ? 'Total Treecover (excl. plantations)' : 'Total Treecover (incl. plantations)';
      processForestAreaStats(latestMaskedForest[year], treecoverLabel, yearInt, exportScale, true, selectedCountry);
      if (latestMaskedPrimaryForest[year]) {
        processForestAreaStats(latestMaskedPrimaryForest[year], "Primary Forest", yearInt, exportScale, true, selectedCountry);
      }
    });
    exportStatusLabel.setValue('Export submitted. Check Tasks tab to start processing output table(s) to your Drive.');
  }
});

// Panel to hold export button on top, scale label and slider below
var exportStatsPanel = ui.Panel({
  widgets: [
    exportStatsButton,
    // Scale slider moved to shared statsScaleSlider above
    // ui.Panel([statsScaleLabel, statsScaleSlider], ...)
  ],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {margin: '6px 0 0 8px', width: '280px'}
});

// ──────────────────────────────────────────────
// Export Rasters (for QGIS / offline use)
// ──────────────────────────────────────────────
var exportRasterScaleSlider = ui.Slider({
  min: 30, max: 1000, value: 30, step: 10,
  style: {margin: '0 0 6px 0', stretch: 'horizontal'}
});
var exportToCloudCheckbox = ui.Checkbox({
  label: 'Export as COGs to Cloud Storage',
  value: false
});
var gcsBucketInput = ui.Textbox({
  placeholder: 'my-gcs-bucket',
  style: {width: '160px', shown: false}
});
exportToCloudCheckbox.onChange(function(checked) {
  gcsBucketInput.style().set('shown', checked);
});
var exportRasterStatusLabel = ui.Label('', {margin: '4px 0 0 8px', width: '280px'});

// ── Selective export controls ──
var exportChkStyle = {fontSize: '11px', margin: '1px 0'};
var exportChk_final           = ui.Checkbox({label: 'Primary forest (final)',        value: true,  style: exportChkStyle});
var exportChk_preConnectivity = ui.Checkbox({label: 'Pre-connectivity forest',       value: true,  style: exportChkStyle});
var exportChk_inputForest     = ui.Checkbox({label: 'Input forest',                  value: true,  style: exportChkStyle});
var exportChk_roads           = ui.Checkbox({label: 'Roads',                         value: true,  style: exportChkStyle});
var exportChk_builtupSmall    = ui.Checkbox({label: 'Built-up (small)',              value: true,  style: exportChkStyle});
var exportChk_builtupLarge    = ui.Checkbox({label: 'Built-up (large)',              value: true,  style: exportChkStyle});
var exportChk_agriculture     = ui.Checkbox({label: 'Agriculture',                   value: true,  style: exportChkStyle});
var exportChk_plantations     = ui.Checkbox({label: 'Plantations',                   value: true,  style: exportChkStyle});
var exportChk_dem             = ui.Checkbox({label: 'DEM',                           value: true,  style: exportChkStyle});
var exportChk_slope           = ui.Checkbox({label: 'Slope',                         value: false, style: exportChkStyle});
var exportChk_protLegal       = ui.Checkbox({label: 'Protected areas (binary image)', value: true,  style: exportChkStyle});
var exportChk_protVector      = ui.Checkbox({label: 'Protected areas (vector)',      value: false, style: exportChkStyle});
var exportChk_aoi             = ui.Checkbox({label: 'AOI boundary (vector)',         value: true,  style: exportChkStyle});
var exportChk_hansenRaw       = ui.Checkbox({label: 'Hansen raw (treecover + loss)', value: false, style: exportChkStyle});
var exportChk_gladHeight      = ui.Checkbox({label: 'GLAD tree height',              value: false, style: exportChkStyle});

var exportSelectPanel = ui.Panel({
  widgets: [
    ui.Label('Select layers to export:', {fontWeight: 'bold', fontSize: '11px', margin: '4px 0 2px 0'}),
    ui.Panel([exportChk_final, exportChk_preConnectivity, exportChk_inputForest],
      ui.Panel.Layout.flow('vertical'), {margin: '0'}),
    ui.Panel([exportChk_roads, exportChk_builtupSmall, exportChk_builtupLarge, exportChk_agriculture, exportChk_plantations],
      ui.Panel.Layout.flow('vertical'), {margin: '0'}),
    ui.Panel([exportChk_dem, exportChk_slope, exportChk_protLegal, exportChk_protVector, exportChk_aoi],
      ui.Panel.Layout.flow('vertical'), {margin: '0'}),
    ui.Panel([exportChk_hansenRaw, exportChk_gladHeight],
      ui.Panel.Layout.flow('vertical'), {margin: '0'})
  ],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {margin: '0 0 4px 0'}
});

function exportRastersToDrive() {
  exportRasterStatusLabel.setValue('');

  var selectedCountry = countrySelector.getValue();
  if (!selectedCountry) {
    exportRasterStatusLabel.setValue('Please select a country first.');
    return;
  }
  var analysisYear1 = parseInt(yearSelector1.getValue());
  var analysisYear2 = parseInt(yearSelector2.getValue());
  var exportScale = exportRasterScaleSlider.getValue();
  // Unique run tag so GEE doesn't reject duplicate task descriptions
  var runNow = new Date();
  var runPad = function(n) { return n < 10 ? '0' + n : n; };
  var runTag = '_' + runPad(runNow.getHours()) + 'h' + runPad(runNow.getMinutes()) + 'm';
  var countryClean = cleanCountryName(selectedCountry);
  var countryInfo = gaulLut.GAUL_LUT[gaulLut.nameToCode(selectedCountry)];
  var iso3 = countryInfo ? countryInfo.iso3 : countryClean.substring(0, 3).toUpperCase();

  var country_sel = getCountryFeatures(selectedCountry);
  var country_geom = country_sel.geometry();

  // Export in native GEE CRS (EPSG:4326) — matches how analysis was computed
  var targetCRS = 'EPSG:4326';

  // Export region: bounding box of the buffered country boundary. GEE always
  // writes a rectangular GeoTIFF covering the region's bbox, so using .bounds()
  // makes the region match the actual output extent while keeping the geometry
  // to 5 vertices — avoids vertex-limit overflow for archipelago countries
  // (Indonesia, Philippines, etc.) whose coastlines re-densify under .buffer().
  var exportRegion = country_geom.buffer(country_buffer_threshold + 1000).bounds();

  // Export destination: Cloud Storage (COG) or Drive (GeoTIFF COG)
  var useCloud = exportToCloudCheckbox.getValue();
  var gcsBucket = gcsBucketInput.getValue();
  if (useCloud && (!gcsBucket || gcsBucket.trim() === '')) {
    exportRasterStatusLabel.setValue('Please enter a GCS bucket name.');
    return;
  }

  // Shared export helper (binary/byte images)
  // description doubles as filename (Drive) — keep filesystem-safe with ISO3 prefix
  function doExport(image, description, folder) {
    var desc = iso3 + '_' + description + runTag;
    if (useCloud) {
      Export.image.toCloudStorage({
        image: image.toByte(),
        description: desc,
        bucket: gcsBucket.trim(),
        fileNamePrefix: folder + '/' + iso3 + '_' + description,
        region: exportRegion,
        scale: exportScale,
        crs: targetCRS,
        maxPixels: 1e13,
        fileFormat: 'GeoTIFF',
        formatOptions: {cloudOptimized: true}
      });
    } else {
      Export.image.toDrive({
        image: image.toByte(),
        description: desc,
        folder: folder,
        region: exportRegion,
        scale: exportScale,
        crs: targetCRS,
        maxPixels: 1e13,
        fileFormat: 'GeoTIFF',
        formatOptions: {cloudOptimized: true}
      });
    }
  }

  // Int16 export helper (for DEM)
  function doExportInt16(image, description, folder) {
    var desc = iso3 + '_' + description + runTag;
    if (useCloud) {
      Export.image.toCloudStorage({
        image: image.toInt16(),
        description: desc,
        bucket: gcsBucket.trim(),
        fileNamePrefix: folder + '/' + iso3 + '_' + description,
        region: exportRegion,
        scale: exportScale,
        crs: targetCRS,
        maxPixels: 1e13,
        fileFormat: 'GeoTIFF',
        formatOptions: {cloudOptimized: true}
      });
    } else {
      Export.image.toDrive({
        image: image.toInt16(),
        description: desc,
        folder: folder,
        region: exportRegion,
        scale: exportScale,
        crs: targetCRS,
        maxPixels: 1e13,
        fileFormat: 'GeoTIFF',
        formatOptions: {cloudOptimized: true}
      });
    }
  }

  // Vector export helper
  function doExportTable(collection, description, folder) {
    var desc = iso3 + '_' + description + runTag;
    // SHP requires a single geometry type. Some source FCs (WDPA, the
    // simplified/diced GAUL asset used for IDN/THA/DZA/AUS/CHN) carry stray
    // LineString / Point features that trigger GEE Error 3 ("multiple
    // geometry types"). Filter to polygons only before export.
    var polyOnly = collection.map(function(f) {
      return f.set('_pff_gt', f.geometry().type());
    }).filter(ee.Filter.inList('_pff_gt', ['Polygon', 'MultiPolygon']))
      .map(function(f) { return f.set('_pff_gt', null); });
    if (useCloud) {
      Export.table.toCloudStorage({
        collection: polyOnly,
        description: desc,
        bucket: gcsBucket.trim(),
        fileNamePrefix: folder + '/' + iso3 + '_' + description,
        fileFormat: 'SHP'
      });
    } else {
      Export.table.toDrive({
        collection: polyOnly,
        description: desc,
        folder: folder,
        fileFormat: 'SHP'
      });
    }
  }

  var useSplitScreen = enableSplitScreenCheckbox.getValue();
  var uniqueYears;
  if (useSplitScreen) {
    uniqueYears = (analysisYear1 === analysisYear2) ? [analysisYear1] : [analysisYear1, analysisYear2];
  } else {
    uniqueYears = [analysisYear2];
  }
  var folder = 'PFF_export_' + countryClean;
  var s = exportScale + 'm';  // scale suffix for filenames

  // Country mask + buffer (raster-based, no vector .clip())
  var country_clip = getCountryClip(selectedCountry);
  var country_buffer = makeDistanceBuffer(country_clip, country_buffer_threshold, fastBuffer);
  var country_and_buffer_mask = country_buffer.where(country_clip, 1).selfMask();

  // ═══ Canonical export order (matches QGIS plugin input order) ═══
  // 0 — AOI boundary (vector)
  // 1 — Forest (binary) + raw reference bands (Hansen, GLAD height)
  // 2 — Anthropogenic: roads, builtup_small, builtup_large, agriculture
  // 3 — Protection: legal (WDPA raster + vector), natural (DEM, slope)
  // 4 — Pre-connectivity forest (combined tiers before density filter)
  // 5 — Primary forest (final output)
  // ══════════════════════════════════════════════════════
  //  0 — AOI & reference layers
  // ══════════════════════════════════════════════════════
  if (exportChk_aoi.getValue()) {
    doExportTable(country_sel, '0_aoi_' + countryClean + '_vector', folder);
  }

  // ══════════════════════════════════════════════════════
  //  1 — Tree cover / forest (static raw + per-year thresholded)
  // ══════════════════════════════════════════════════════

  // Hansen raw bands (export once — for re-thresholding in QGIS)
  if (exportChk_hansenRaw.getValue()) {
    var gfc = ee.Image('UMD/hansen/global_forest_change_2024_v1_12');
    doExport(gfc.select('treecover2000').updateMask(country_and_buffer_mask).unmask(0),
      '1_hansen_treecover2000_raw_' + s, folder);
    doExport(gfc.select('lossyear').updateMask(country_and_buffer_mask).unmask(0),
      '1_hansen_lossyear_raw_' + s, folder);
  }

  // ══════════════════════════════════════════════════════
  //  3 — Protection: legal (WDPA) + natural (DEM for slope)
  // ══════════════════════════════════════════════════════

  // 3a — Legal protection (WDPA filtered raster + unfiltered vector)
  var wdpaYearCutoff = current_year - years_protected;
  var wdpa_filt_by_date_image = wdpaStatusYearGlobal.lte(wdpaYearCutoff);
  if (selected_iucn_categories.length > 0 && selected_iucn_categories.length < 10) {
    var combinedCategoryMask = ee.Image(0);
    for (var i = 0; i < selected_iucn_categories.length; i++) {
      combinedCategoryMask = combinedCategoryMask.or(wdpaCategoryMasks[selected_iucn_categories[i]]);
    }
    wdpa_filt_by_date_image = wdpa_filt_by_date_image.updateMask(combinedCategoryMask);
  }
  var wdpa_raster = wdpa_filt_by_date_image.selfMask()
    .updateMask(country_and_buffer_mask).unmask(0).toByte().rename('protected');
  if (exportChk_protLegal.getValue()) {
    doExport(wdpa_raster, '3_protection_legal_' + s, folder);
  }

  if (exportChk_protVector.getValue()) {
    var wdpa_raw = ee.FeatureCollection("WCMC/WDPA/current/polygons").filter(
      ee.Filter.and(ee.Filter.neq('STATUS', 'Proposed'),
                    ee.Filter.neq('STATUS', 'Not Reported'))
    ).filterBounds(exportRegion);
    doExportTable(wdpa_raw, '3_protection_legal_unfilt_vector', folder);
  }

  // 3b — Natural protection (DEM for slope computation in QGIS)
  var alos_30m_elev = ee.ImageCollection('JAXA/ALOS/AW3D30/V3_2').select('DSM').mosaic();
  if (exportChk_dem.getValue()) {
    doExportInt16(alos_30m_elev.updateMask(country_and_buffer_mask).unmask(0),
      '3_protection_natural_dem_' + s, folder);
  }

  // 3c — Slope (optional — computed from DEM)
  if (exportChk_slope.getValue()) {
    var slopeImage = ee.Terrain.slope(alos_30m_elev.setDefaultProjection('EPSG:4326', null, 30));
    doExport(slopeImage.updateMask(country_and_buffer_mask).unmask(0).toByte(),
      '3_protection_natural_slope_' + s, folder);
  }

  // ══════════════════════════════════════════════════════
  //  PER-YEAR layers
  // ══════════════════════════════════════════════════════

  var treecoverPercentThreshold = treecoverThresholdSlider.getValue();
  var treecoverHeightThreshold = treecoverHeightThresholdSlider.getValue();
  var useHansenTreecover = (treecoverSourceSelect.getValue() === 'Hansen GFC');
  var useGladLulcForest = (treecoverSourceSelect.getValue() === 'GLAD LULC');
  var useAgreementForest = (treecoverSourceSelect.getValue() === 'Both datasets (Hansen & GLAD)');
  var useUnionForest = (treecoverSourceSelect.getValue() === 'Either dataset (Hansen | GLAD)');
  var timeseriesAnthroModule = require("users/andyarnellgee/apps:modules/timeseriesAnthro.js");

  uniqueYears.forEach(function(analysisYear) {

    // ── 1 — Forest (as configured in the app) ──
    var forest_map;
    var customForestAsset = forestAssets.getAsset(analysisYear);
    if (treecoverSourceSelect.getValue() === 'Custom Forest' && customForestAsset) {
      forest_map = preprocessAsset(customForestAsset, forestAssets.getPreprocessingConfig());
    } else if (useAgreementForest) {
      forest_map = agreementForestPrep(analysisYear, treecoverPercentThreshold, treecoverHeightThreshold);
    } else if (useUnionForest) {
      forest_map = unionForestPrep(analysisYear, treecoverPercentThreshold, treecoverHeightThreshold);
    } else if (useGladLulcForest) {
      forest_map = gladLulcForestPrep(analysisYear, treecoverHeightThreshold);
    } else if (useHansenTreecover) {
      forest_map = gfcHansenTreecoverPrep(analysisYear, treecoverPercentThreshold);
    }
    if (!forest_map) {
      exportRasterStatusLabel.setValue('No forest data selected.');
      return;
    }
    if (exportChk_inputForest.getValue()) {
      doExport(forest_map.updateMask(country_and_buffer_mask).unmask(0),
        '1_forest_' + analysisYear + '_' + s, folder);
    }

    // GLAD raw tree height (so user can re-threshold at any height in QGIS)
    if (exportChk_gladHeight.getValue()) {
      var gladLandcoverLand = ee.Image('projects/glad/GLCLU2020/v2/LCLUC_' + analysisYear)
        .updateMask(ee.Image("projects/glad/OceanMask").lte(1));
      var fromValues = [
        25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48,
        125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147
      ];
      var toValues = [
        3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26,
        3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25
      ];
      var gladTreeHeight = gladLandcoverLand.remap(fromValues, toValues)
        .updateMask(country_and_buffer_mask).unmask(0).toByte()
        .rename('tree_height_m');
      doExport(gladTreeHeight, '1_glad_tree_height_m_' + analysisYear + '_' + s, folder);
    }

    // ── 2 — Anthropogenic: roads, built-up (small + large), agriculture ──
    var roadsMosaicStatic = timeseriesAnthroModule.roadsMosaicStatic().updateMask(country_and_buffer_mask);
    if (exportChk_roads.getValue()) {
      doExport(roadsMosaicStatic.unmask(0), '2_roads_' + analysisYear + '_' + s, folder);
    }

    // Built-up small
    var builtUpSmall = ee.Image(0);
    var builtUpLargeImg = ee.Image(0);
    if (includeWSF) {
      var wsfCollection = timeseriesAnthroModule.getWSFCollection();
      builtUpSmall = builtUpSmall.or(wsfCollection.filter(ee.Filter.eq('year', analysisYear)).first().eq(1)).updateMask(country_and_buffer_mask);
    }
    if (includeGHSL) {
      var ghslCollection = timeseriesAnthroModule.getGhslCollection();
      var ghslSel = ghslCollection.filter(ee.Filter.eq('year', analysisYear)).first().updateMask(country_and_buffer_mask);
      builtUpSmall = builtUpSmall.or(ghslSel.eq(1));
      builtUpLargeImg = ghslSel.eq(2);
    }
    if (includeGISD) {
      var gisdCollection = timeseriesAnthroModule.getGISDCollection();
      builtUpSmall = builtUpSmall.or(gisdCollection.filter(ee.Filter.eq('year', analysisYear)).first().eq(1)).updateMask(country_and_buffer_mask);
    }
    if (includeGISA) {
      var gisaCollection = timeseriesAnthroModule.getGISACollection();
      builtUpSmall = builtUpSmall.or(gisaCollection.filter(ee.Filter.eq('year', analysisYear)).first().eq(1)).updateMask(country_and_buffer_mask);
    }
    if (exportChk_builtupSmall.getValue()) {
      doExport(builtUpSmall.updateMask(country_and_buffer_mask).unmask(0),
        '2_builtup_small_' + analysisYear + '_' + s, folder);
    }
    if (exportChk_builtupLarge.getValue()) {
      doExport(builtUpLargeImg.updateMask(country_and_buffer_mask).unmask(0),
        '2_builtup_large_' + analysisYear + '_' + s, folder);
    }

    // Agriculture
    var glcFcs30dCollection = timeseriesAnthroModule.preprocessGlc();
    var landcover = glcFcs30dCollection.filter(ee.Filter.eq("year", analysisYear)).first().updateMask(country_and_buffer_mask);
    var pastureDataset = ee.ImageCollection("projects/global-pasture-watch/assets/ggc-30m/v1/grassland_c");
    var pastureDatasetCultivated = pastureDataset.map(function(image){return image.eq(1).set('year',ee.Number.parse(image.get("system:index")))});
    var pastureDatasetFF = forwardFillBinaryTimeSeries(pastureDatasetCultivated, years.filter(function(year) {return year >= 2000}));
    var pastureDatasetSel = pastureDatasetFF.filter(ee.Filter.eq("year", analysisYear)).first().updateMask(country_and_buffer_mask);
    var oilPalmDescalsCollection = timeseriesAnthroModule.processingOilPalmDescals();
    var oilPalmDescalsSel = ee.Image(oilPalmDescalsCollection.filter(ee.Filter.eq("year", analysisYear)).first()).updateMask(country_and_buffer_mask);
    var plantationsMosaicStatic = timeseriesAnthroModule.processingPlantationsMosaic().updateMask(country_and_buffer_mask);
    var allPlantationsSel = plantationsMosaicStatic.unmask().where(oilPalmDescalsSel.eq(1), 1).updateMask(country_and_buffer_mask);
    if (exportChk_plantations.getValue()) {
      // Separate plantations export so the QGIS plugin can echo the GEE
      // "Exclude plantations" logic (forest AND NOT plantations). Enables
      // full FRA stats cascade (Forest → Nat. regen. forest → Primary forest).
      doExport(allPlantationsSel.unmask(0).toByte(),
        '2_plantations_' + analysisYear + '_' + s, folder);
    }
    var croplandGladCollection = timeseriesAnthroModule.processingCroplandsGlad();
    var croplandGladCollectionFF = forwardFillBinaryTimeSeries(croplandGladCollection, years);
    var croplandGladSel = ee.Image(croplandGladCollectionFF.filter(ee.Filter.eq("year", analysisYear)).first()).updateMask(country_and_buffer_mask);
    var agriculture = pastureDatasetSel.or(allPlantationsSel.unmask()).or(croplandGladSel);
    if (exportChk_agriculture.getValue()) {
      doExport(agriculture.unmask(0), '2_agriculture_' + analysisYear + '_' + s, folder);
    }

    // ── 4 — Pre-connectivity Forest & Primary Forest (from analysis cache) ──
    if (exportChk_preConnectivity.getValue() && latestPreConnectivityForest[analysisYear]) {
      doExport(latestPreConnectivityForest[analysisYear].unmask(0),
        '4_pre_connectivity_forest_' + analysisYear + '_' + s, folder);
    }
    if (exportChk_final.getValue() && latestMaskedPrimaryForest[analysisYear]) {
      doExport(latestMaskedPrimaryForest[analysisYear].unmask(0),
        '5_primary_forest_' + analysisYear + '_' + s, folder);
    }
  });

  var yearStr = uniqueYears.join(' & ');
  var destStr = useCloud ? 'gs://' + gcsBucket.trim() + '/' + folder : 'Google Drive → ' + folder;
  var missingAnalysis = uniqueYears.filter(function(y) {
    return !latestMaskedPrimaryForest[y];
  });
  var note = '';
  if (missingAnalysis.length > 0) {
    note = ' NOTE: Run analysis first for year(s) ' + missingAnalysis.join(', ') +
      ' to include Primary & Pre-connectivity Forest exports.';
  }
  exportRasterStatusLabel.setValue(
    'Export tasks queued for ' + countryClean + ' (' + yearStr + ') → ' + destStr +
    '. Check the Tasks tab to run them. [pff v' + PFF_SCRIPT_VERSION + ']' + note);
}

var exportRastersButton = ui.Button({
  label: 'Export All Layers to Drive',
  style: {width: '220px', margin: '0 0 4px 0', fontWeight: 'bold', backgroundColor: '#d4edda'},
  onClick: exportRastersToDrive
});

var driveOptionsContent = ui.Panel({
  widgets: [
    ui.Panel([ui.Label('Resolution (m):', {margin: '0 8px 0 0', fontSize: '11px'}), exportRasterScaleSlider],
      ui.Panel.Layout.flow('horizontal'), {stretch: 'horizontal'}),
    exportToCloudCheckbox,
    ui.Panel([ui.Label('GCS Bucket:', {margin: '0 8px 0 0', fontSize: '11px'}), gcsBucketInput],
      ui.Panel.Layout.flow('horizontal'))
  ],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {shown: false, margin: '0 0 0 4px'}
});
var driveOptionsToggle = ui.Button({
  label: '▸ Options',
  onClick: function() {
    var s = driveOptionsContent.style().get('shown');
    driveOptionsContent.style().set({shown: !s});
    driveOptionsToggle.setLabel(s ? '▸ Options' : '▾ Options');
  },
  style: {fontSize: '11px', color: '#555', margin: '2px 0', padding: '2px 6px', backgroundColor: '#ffffff'}
});

var exportRastersPanel = ui.Panel({
  widgets: [
    exportRastersButton,
    exportRasterStatusLabel,
    driveOptionsToggle,
    driveOptionsContent,
    exportSelectPanel
  ],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {margin: '0', stretch: 'horizontal'}
});

// ──────────────────────────────────────────────
// Download Layer (via getDownloadURL — works in App & Script)
// ──────────────────────────────────────────────
var dlModule = require('users/andyarnellgee/apps:modules/downloadViaUrl.js');

var downloadLayerSelect = ui.Select({
  items: [
    'Tier 0: Input Treecover (raw Hansen)',
    'Tier 1: Undisturbed (outside buffers)',
    'Tier 2: Steep Slope in Buffer',
    'Tier 3: Protected in Buffer',
    'Tier 4: Pre-connectivity Forest',
    'Primary Forest (final mask)'
  ],
  value: 'Tier 0: Input Treecover (raw Hansen)',
  style: {margin: '0 0 4px 0', stretch: 'horizontal'}
});
var downloadScaleSlider = ui.Slider({
  min: 30, max: 1000, value: 90, step: 10,
  style: {margin: '0 0 6px 0', stretch: 'horizontal'},
  onChange: function(val) { downloadScaleInput.setValue(val.toString(), false); }
});
var downloadScaleInput = ui.Textbox({
  value: '90',
  style: {width: '55px', fontSize: '11px', margin: '0 0 0 4px'},
  onChange: function(val) {
    var n = parseInt(val);
    if (!isNaN(n) && n >= 30 && n <= 1000) {
      downloadScaleSlider.setValue(n, false);
    }
  }
});
// Custom AOI for downloads (drawn polygon overrides country boundary)
var userDrawnAoi = null;

var drawAoiStatusLabel = ui.Label('', {fontSize: '10px', color: '#666', margin: '0 0 4px 0'});

var useCustomAoiCheckbox = ui.Checkbox({
  label: 'Use custom AOI (draw on map)',
  value: false,
  style: {margin: '0 0 4px 0', fontSize: '12px'},
  onChange: function(checked) {
    var activeMap = map2 || map1;
    if (checked) {
      // Activate drawing
      if (!activeMap) {
        drawAoiStatusLabel.setValue('No map available yet.');
        useCustomAoiCheckbox.setValue(false, false);
        return;
      }
      var dt = activeMap.drawingTools();
      dt.layers().reset();
      dt.setShown(true);
      dt.setShape('polygon');
      dt.draw();
      drawAoiStatusLabel.setValue('Draw a polygon on the map. Double-click last vertex to finish.');
      dt.onDraw(function(geom) {
        if (geom) {
          userDrawnAoi = geom;
          drawAoiStatusLabel.setValue('\u2714 Custom AOI set. Grid & tiles will use this area.');
          drawAoiStatusLabel.style().set('color', '#2a7f2a');
        }
        dt.stop();
      });
    } else {
      // Clear everything
      userDrawnAoi = null;
      drawAoiStatusLabel.setValue('');
      drawAoiStatusLabel.style().set('color', '#666');
      if (activeMap) {
        var dt = activeMap.drawingTools();
        dt.stop();
        dt.layers().reset();
        dt.setShown(false);
      }
    }
  }
});

var downloadAutoGridButton = ui.Button({
  label: 'Preview tiles',
  style: {width: '100px', fontSize: '11px', margin: '0 0 4px 0'},
  onClick: function() {
    var selectedCountry = countrySelector.getValue();
    var country_sel = getCountryFeatures(selectedCountry);
    var dlRegion = userDrawnAoi || country_sel.geometry();
    var dlScale = downloadScaleSlider.getValue();
    downloadStatusLabel.setValue('Calculating grid…');

    var grid = dlModule.autoGrid(dlRegion, dlScale);

    // Safety: ensure each tile fits within GEE's 32768px hard limit
    var MAX_PX = 30000;
    var bounds = dlRegion.bounds();
    var coords = bounds.coordinates().get(0).getInfo();
    if (coords) {
      var lons = coords.map(function(c) { return c[0]; });
      var lats = coords.map(function(c) { return c[1]; });
      var lonSpan = Math.max.apply(null, lons) - Math.min.apply(null, lons);
      var latSpan = Math.max.apply(null, lats) - Math.min.apply(null, lats);
      var metersPerDeg = 111320;
      var widthPx = (lonSpan * metersPerDeg / dlScale) / grid.cols;
      var heightPx = (latSpan * metersPerDeg / dlScale) / grid.rows;
      while (widthPx > MAX_PX) { grid.cols += 1; widthPx = (lonSpan * metersPerDeg / dlScale) / grid.cols; }
      while (heightPx > MAX_PX) { grid.rows += 1; heightPx = (latSpan * metersPerDeg / dlScale) / grid.rows; }
    }

    if (!grid.feasible) {
      downloadStatusLabel.setValue(grid.message);
      downloadStatusLabel.style().set('color', 'red');
    } else {
      downloadStatusLabel.style().set('color', '#333');
      // Show actual tile count after overlap filtering
      var result = dlModule.makeTiles(dlRegion, grid.rows, grid.cols);
      var msg = grid.rows + '×' + grid.cols;
      if (grid.rows === 1 && grid.cols === 1) {
        msg = 'Single file download (area fits in one tile)';
      } else if (result.skipped > 0) {
        msg += ' → ' + result.tiles.length + ' tiles overlap boundary' +
          ' (skipped ' + result.skipped + ' empty)';
      } else {
        msg += ' = ' + result.tiles.length + ' tiles';
      }
      if (grid.rows > 1 || grid.cols > 1) {
        msg += ' [~' + Math.round(grid.tileAreaKm2) + ' km² each]';
      }
      downloadStatusLabel.setValue(msg);
    }
  }
});
var downloadTileGridPanel = ui.Panel({
  widgets: [downloadAutoGridButton],
  layout: ui.Panel.Layout.flow('vertical')
});
var downloadStatusLabel = ui.Label('', {margin: '4px 0 0 8px', width: '280px', fontSize: '11px'});
var downloadLinksPanel = ui.Panel({
  layout: ui.Panel.Layout.flow('vertical'),
  style: {margin: '4px 0 0 8px', width: '280px'}
});
var downloadItems = [];  // collect {name, url} for script
var downloadFolder = '';  // folder name for script (includes country)

function downloadLayer() {
  downloadStatusLabel.setValue('');
  downloadLinksPanel.clear();
  psScriptButton.style().set('shown', false);
  scriptTypeSelect.style().set('shown', false);
  psScriptPanel.style().set('shown', false);

  var layerChoice = downloadLayerSelect.getValue();
  var sourceDict;
  var nameBase;
  if (layerChoice === 'Tier 0: Input Treecover (raw Hansen)') {
    sourceDict = latestMaskedForest;
    nameBase = 'tier0_treecover';
  } else if (layerChoice === 'Tier 1: Undisturbed (outside buffers)') {
    sourceDict = latestTier1Undisturbed;
    nameBase = 'tier1_undisturbed';
  } else if (layerChoice === 'Tier 2: Steep Slope in Buffer') {
    sourceDict = latestTier2Steep;
    nameBase = 'tier2_steep';
  } else if (layerChoice === 'Tier 3: Protected in Buffer') {
    sourceDict = latestTier3Protected;
    nameBase = 'tier3_protected';
  } else if (layerChoice === 'Tier 4: Pre-connectivity Forest') {
    sourceDict = latestPreConnectivityForest;
    nameBase = 'tier4_pre_connectivity_forest';
  } else {
    sourceDict = latestMaskedPrimaryForest;
    nameBase = 'primary_forest_final';
  }

  var years = Object.keys(sourceDict);
  if (years.length === 0) {
    downloadStatusLabel.setValue('No ' + layerChoice + ' data. Run the analysis first.');
    return;
  }

  var selectedCountry = countrySelector.getValue();
  var countryClean = cleanCountryName(selectedCountry);
  var country_sel = getCountryFeatures(selectedCountry);
  var region = country_sel.geometry();
  var dlScale = downloadScaleSlider.getValue();

  // Build folder name: pff_<country>_<date>_<time>
  var now = new Date();
  var pad = function(n) { return n < 10 ? '0' + n : n; };
  downloadFolder = 'pff_' + countryClean + '_' +
    now.getFullYear() + '-' + pad(now.getMonth()+1) + '-' + pad(now.getDate()) + '_' +
    pad(now.getHours()) + 'h' + pad(now.getMinutes()) + 'm';

  downloadStatusLabel.setValue('Calculating tiles…');
  downloadStatusLabel.style().set('color', '#333');

  // Determine download region: drawn AOI takes precedence, else country
  var dlRegion = userDrawnAoi || region;
  var yearsArr = Object.keys(sourceDict);

  // Always auto-compute grid — tiles when needed, single file when small enough
  var grid = dlModule.autoGrid(dlRegion, dlScale);

  // Safety: ensure each tile fits within GEE's 32768px hard limit
  var MAX_PX = 30000;
  var bounds = dlRegion.bounds();
  var coords = bounds.coordinates().get(0).getInfo();
  if (coords) {
    var lons = coords.map(function(c) { return c[0]; });
    var lats = coords.map(function(c) { return c[1]; });
    var lonSpan = Math.max.apply(null, lons) - Math.min.apply(null, lons);
    var latSpan = Math.max.apply(null, lats) - Math.min.apply(null, lats);
    var metersPerDeg = 111320;
    var widthPx = (lonSpan * metersPerDeg / dlScale) / grid.cols;
    var heightPx = (latSpan * metersPerDeg / dlScale) / grid.rows;
    while (widthPx > MAX_PX) { grid.cols += 1; widthPx = (lonSpan * metersPerDeg / dlScale) / grid.cols; }
    while (heightPx > MAX_PX) { grid.rows += 1; heightPx = (latSpan * metersPerDeg / dlScale) / grid.rows; }
  }
  var tileRows = grid.rows;
  var tileCols = grid.cols;

  if (!grid.feasible) {
    downloadStatusLabel.setValue(grid.message);
    downloadStatusLabel.style().set('color', 'red');
    return;
  }

  // Build tiles — automatically skips tiles outside the actual geometry
  var tileResult = dlModule.makeTiles(dlRegion, tileRows, tileCols);
  var useTiled = (tileRows > 1 || tileCols > 1);
  var expectedLinks = yearsArr.length * tileResult.tiles.length;

  if (tileResult.skipped > 0) {
    downloadStatusLabel.setValue(
      tileRows + '×' + tileCols + ' grid → ' + tileResult.tiles.length +
      ' tiles overlap boundary (skipped ' + tileResult.skipped + ' empty)');
  } else if (useTiled) {
    downloadStatusLabel.setValue(
      tileRows + '×' + tileCols + ' = ' + tileResult.tiles.length + ' tiles');
  }

  // Helper: add a clickable link to the panel
  var linksReady = 0;
  downloadItems = [];  // reset for new download
  function addLink(label, url, fileName) {
    linksReady++;
    downloadItems.push({name: fileName || label.replace(/[^a-zA-Z0-9_\-]/g, '_'), url: url});
    downloadLinksPanel.add(ui.Label({
      value: '⬇ ' + label,
      style: {color: 'blue', textDecoration: 'underline', fontSize: '12px'},
      targetUrl: url
    }));
    // Show clear and script buttons once we have links
    clearDownloadLinksButton.style().set({shown: true});
    psScriptButton.style().set('shown', true);
    scriptTypeSelect.style().set('shown', true);
    if (linksReady === expectedLinks) {
      downloadStatusLabel.setValue(linksReady + ' link(s) ready. ⚠ Links expire in ~2 hours — download soon.');
    }
  }
  function addError(msg) {
    downloadLinksPanel.add(ui.Label(msg, {color: 'red', fontSize: '11px'}));
  }

  years.forEach(function(year) {
    var yearInt = parseInt(year);
    var layer = sourceDict[year];
    if (!layer) return;
    var image = layer.unmask(0).toByte();
    var dlName = nameBase + '_' + countryClean + '_' + yearInt + '_' + dlScale + 'm';

    // Use pre-computed tiles (1×1 for small areas, N×M for large)
    tileResult.tiles.forEach(function(t) {
      image.getDownloadURL({
        name: dlName + (useTiled ? '_' + t.name : ''),
        region: t.geom,
        scale: dlScale,
        crs: 'EPSG:4326',
        maxPixels: 1e9,
        filePerBand: false,
        format: 'GeoTIFF'
      }, function(url, err) {
        if (err) { addError('Error ' + (useTiled ? t.name : yearInt) + ': ' + err); return; }
        var label = useTiled
          ? layerChoice + ' ' + yearInt + ' – ' + t.name + ' (' + dlScale + 'm)'
          : layerChoice + ' ' + yearInt + ' (' + dlScale + 'm)';
        addLink(label, url);
      });
    });
  });

  var limitNote = useTiled
    ? 'Generating ' + tileResult.tiles.length + ' tiles × ' + yearsArr.length + ' year(s) = ' + expectedLinks + ' links…'
    : 'Generating download link…';
  downloadStatusLabel.setValue(limitNote);
}

var downloadButton = ui.Button({
  label: 'Get Download Links',
  style: {width: '220px', margin: '0 0 4px 0', fontWeight: 'bold', backgroundColor: '#d4edda'},
  onClick: downloadLayer
});

var psScriptPanel = ui.Panel({layout: ui.Panel.Layout.flow('vertical'), style: {shown: false}});
var scriptTypeSelect = ui.Select({
  items: ['PowerShell (Windows)', 'Python (all platforms)'],
  value: 'Python (all platforms)',
  style: {width: '180px', fontSize: '11px', margin: '4px 0 0 8px', shown: false}
});
var psScriptButton = ui.Button({
  label: 'Batch Download Script',
  style: {width: '180px', fontSize: '11px', margin: '4px 0 0 8px', shown: false},
  onClick: function() {
    psScriptPanel.clear();
    if (!downloadItems || downloadItems.length === 0) {
      psScriptPanel.add(ui.Label('No download links yet.', {fontSize: '11px'}));
      psScriptPanel.style().set('shown', true);
      return;
    }
    var isPython = scriptTypeSelect.getValue() === 'Python (all platforms)';
    var script, dataUri, instructions;
    try {
    if (isPython) {
      script = dlModule.buildPythonScript(downloadItems, downloadFolder);
      dataUri = 'data:application/octet-stream;charset=utf-8,' + encodeURIComponent(script);
      instructions = 'Save as download_tiles.py  (rename extension to .py)\n' +
        'Run:  python download_tiles.py\n\n' +
        '⚠ Links expire ~2 hours after generation. Re-run can reuse links within that window.';
    } else {
      script = dlModule.buildPowerShellScript(downloadItems, downloadFolder);
      dataUri = 'data:application/octet-stream;charset=utf-8,' + encodeURIComponent(script);
      instructions = 'Save as download_tiles.ps1  (rename extension to .ps1)\n' +
        'Then either:\n' +
        '  1. Right-click the .ps1 file \u2192 Run with PowerShell (Windows)\n' +
        '  2. Run:  PowerShell -ExecutionPolicy Bypass -File .\\download_tiles.ps1\n' +
        '  3. Or paste the script below directly into a PowerShell window\n\n' +
        '⚠ Links expire ~2 hours after generation. Re-run can reuse links within that window.';
    }
    } catch (e) {
      psScriptPanel.add(ui.Label('Error: update the downloadViaUrl module in GEE Code Editor.', {color: 'red', fontSize: '11px'}));
      psScriptPanel.style().set('shown', true);
      return;
    }
    psScriptPanel.add(ui.Label({
      value: '\u2b07  Download ' + (isPython ? 'Python' : 'PowerShell') + ' Script',
      targetUrl: dataUri,
      style: {fontSize: '11px', color: '#1a73e8', fontWeight: 'bold', margin: '4px 0 2px 0'}
    }));
    psScriptPanel.add(ui.Label(instructions,
      {fontSize: '10px', margin: '2px 0', whiteSpace: 'pre'}));
    psScriptPanel.add(ui.Label(script, {
      fontSize: '9px',
      whiteSpace: 'pre',
      margin: '4px 0',
      border: '1px solid #ccc',
      padding: '4px'
    }));
    psScriptPanel.style().set('shown', true);
  }
});

var downloadClearButton = ui.Button({
  label: 'Clear',
  style: {width: '80px', fontSize: '11px', margin: '0 0 4px 8px', backgroundColor: '#f8d7da'},
  onClick: function() {
    downloadStatusLabel.setValue('');
    downloadLinksPanel.clear();
    psScriptButton.style().set('shown', false);
    scriptTypeSelect.style().set('shown', false);
    psScriptPanel.clear();
    psScriptPanel.style().set('shown', false);
  }
});

var downloadAdvancedContent = ui.Panel({
  widgets: [
    ui.Panel([ui.Label('Resolution (m):', {margin: '0 8px 0 0', fontSize: '11px'}), downloadScaleSlider, downloadScaleInput],
      ui.Panel.Layout.flow('horizontal'), {stretch: 'horizontal'}),
    useCustomAoiCheckbox,
    drawAoiStatusLabel,
    downloadTileGridPanel,
    ui.Panel([psScriptButton, scriptTypeSelect], ui.Panel.Layout.flow('horizontal'), {margin: '0'}),
    psScriptPanel,
    downloadClearButton
  ],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {shown: false, margin: '0 0 0 4px'}
});
var downloadAdvancedToggle = ui.Button({
  label: '▸ Options',
  onClick: function() {
    var s = downloadAdvancedContent.style().get('shown');
    downloadAdvancedContent.style().set({shown: !s});
    downloadAdvancedToggle.setLabel(s ? '▸ Options' : '▾ Options');
  },
  style: {fontSize: '11px', color: '#555', margin: '2px 0', padding: '2px 6px', backgroundColor: '#ffffff'}
});

var clearDownloadLinksButton = ui.Button({
  label: 'Clear Links',
  style: {width: '100px', margin: '2px 0 2px 8px', fontSize: '10px', backgroundColor: '#eee', color: '#888', shown: false},
  onClick: function() {
    downloadLinksPanel.clear();
    downloadStatusLabel.setValue('');
    downloadItems = [];
    clearDownloadLinksButton.style().set({shown: false});
  }
});

var downloadPanel = ui.Panel({
  widgets: [
    ui.Panel([ui.Label('Layer:', {margin: '0 8px 0 0', fontSize: '12px'}), downloadLayerSelect],
      ui.Panel.Layout.flow('horizontal'), {stretch: 'horizontal', margin: '0 0 4px 0'}),
    downloadButton,
    downloadStatusLabel,
    clearDownloadLinksButton,
    downloadLinksPanel,
    downloadAdvancedToggle,
    downloadAdvancedContent
  ],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {margin: '0', stretch: 'horizontal'}
});

var smoothRadiusForestSlider = ui.Slider({min: 0, max: 5000, value: 2000, step: 500, onChange: markNeedsUpdate});
var smallPixelThresholdForestSlider = ui.Slider({min: 0, max: 1, value: 0.5, step: 0.1, onChange: markNeedsUpdate});

// ============================================
// WDPA UI CONTROLS
// ============================================

// Year slider for WDPA (minimum years protected becomes direct year cutoff)
var wdpaYearSlider = ui.Slider({
  min: 1900, max: 2025, value: current_year - years_protected, step: 5,
  onChange: function(value) {
    years_protected = current_year - value;
    markNeedsUpdate();
  }
});

// Individual WDPA category checkboxes
var wdpaCategoryCheckboxes = {};
var wdpaCategoryCheckboxPanel = ui.Panel({layout: ui.Panel.Layout.flow('horizontal', true)});

allWdpaCategories.forEach(function(cat) {
  wdpaCategoryCheckboxes[cat] = ui.Checkbox({
    label: cat,
    value: selected_iucn_categories.indexOf(cat) >= 0,
    onChange: function() {
      if (wdpaCategoryLabel.style().get('shown') !== false) {
        wdpaPresetSelect.setValue('Manual Selection', false);
      }
      updateSelectedCategories();
      markNeedsUpdate();
    }
  });
  wdpaCategoryCheckboxPanel.add(wdpaCategoryCheckboxes[cat]);
});

var wdpaCategoryLabel = ui.Label('IUCN Categories:');

function updateSelectedCategories() {
  selected_iucn_categories = allWdpaCategories.filter(function(cat) { 
    return wdpaCategoryCheckboxes[cat].getValue(); 
  });
}

function showHideWdpaCheckboxes(show) {
  wdpaCategoryLabel.style().set('shown', show);
  wdpaCategoryCheckboxPanel.style().set('shown', show);
}

// WDPA preset dropdown
var wdpaPresetSelect = ui.Select({
  items: ['All Categories', 'Strict (Ia, Ib, II)', 'Manual Selection'],
  value: 'Strict (Ia, Ib, II)',
  onChange: function(value) {
    var strictCats = ['Ia', 'Ib', 'II'];
    allWdpaCategories.forEach(function(cat) {
      var shouldCheck = value === 'All Categories' || (value === 'Strict (Ia, Ib, II)' && strictCats.indexOf(cat) >= 0);
      wdpaCategoryCheckboxes[cat].setValue(shouldCheck, false);
    });
    showHideWdpaCheckboxes(value === 'Manual Selection');
    updateSelectedCategories();
    markNeedsUpdate();
  }
});

showHideWdpaCheckboxes(false);

// Treecover threshold panels - compact inline layout
var treecoverPanel = ui.Panel({
  layout: ui.Panel.Layout.flow('horizontal'),
  widgets: [
    ui.Label('Hansen Cover (%) >', {margin: '6px 2px 0 0'}),
    treecoverThresholdSlider
  ],
  style: {margin: '0px', shown: false}
});

var treecoverHeightPanel = ui.Panel({
  layout: ui.Panel.Layout.flow('horizontal'),
  widgets: [
    ui.Label('GLAD Height (m) >', {margin: '6px 2px 0 0'}),
    treecoverHeightThresholdSlider
  ],
  style: {margin: '0px', shown: true}
});

// Dropdown for treecover source — Custom Forest is a permanent peer option
var treecoverSourceSelect = ui.Select({
  items: ['Hansen GFC', 'GLAD LULC', 'Both datasets (Hansen & GLAD)', 'Either dataset (Hansen | GLAD)', 'Custom Forest'],
  value: 'GLAD LULC',
  onChange: function(value) {
    var isCustom = (value === 'Custom Forest');
    var isHansen = (value === 'Hansen GFC');
    var isGlad   = (value === 'GLAD LULC');
    treecoverPanel.style().set('shown', isHansen || (!isGlad && !isCustom));
    treecoverHeightPanel.style().set('shown', isGlad || (!isHansen && !isCustom));
    forestAssets.setShown(isCustom);
    if (isCustom) updateVisibleAssetInputs();
    markNeedsUpdate();
  }
});

// Custom forest asset inputs using reusable factory
// Accepts GEE asset IDs (users/..., projects/...) or gs:// Cloud Storage COG URIs
var forestAssets = createYearAssetInputs({
  placeholder: 'users/username/forestAsset or gs://bucket/file.tif'
});

var includePlantationsCheckbox = ui.Checkbox({
  label: 'Exclude plantations from treecover',
  value: true,
  onChange: function() { markNeedsUpdate(); }
});

// Function to update which asset inputs are visible based on selected years
function updateVisibleAssetInputs() {
  var useSplitScreen = enableSplitScreenCheckbox.getValue();
  var year1 = parseInt(yearSelector1.getValue());
  var year2 = parseInt(yearSelector2.getValue());
  
  forestAssets.updateVisibility(useSplitScreen, year1, year2);
  nationalRoads.updateVisibility(useSplitScreen, year1, year2);
  nationalBuiltupSmall.updateVisibility(useSplitScreen, year1, year2);
  nationalBuiltupLarge.updateVisibility(useSplitScreen, year1, year2);
  nationalAgri.updateVisibility(useSplitScreen, year1, year2);
  nationalPlantations.updateVisibility(useSplitScreen, year1, year2);
  nationalProtected.updateVisibility(useSplitScreen, year1, year2);
}

// =============================================================================
// CUSTOM DATA OVERRIDES
// Each pair: checkbox (enable toggle) + textbox (asset ID). Shown inline.
// Convention: binary 0/1 image, clipped or unclipped — country mask is applied.
// Roads / built-up / protected: merged (union) with global defaults.
// Agriculture / plantations: replaces global defaults.
// =============================================================================
// Factory for per-year custom asset inputs (mirrors createYearAssetInputs).
// Returns {checkbox, modeSelect, panel, getAsset(year), updateVisibility(split,y1,y2), setShown(bool), reset()}
function createNationalAssetInputs(config) {
  var label      = config.label;
  var placeholder = config.placeholder || 'users/me/asset  (binary 0/1)';
  var defaultMode = config.defaultMode || 'Add to global';

  var modeSelect = ui.Select({
    items: ['Add to global', 'Replace global'], value: defaultMode,
    onChange: function() { markNeedsUpdate(); },
    style: {shown: false, fontSize: '10px', margin: '0 0 0 4px'}
  });

  var inputs = {};
  var yearPanels = {};
  var yearInputsContainer = ui.Panel({
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, margin: '2px 0 0 12px'}
  });

  years.forEach(function(year) {
    var row = ui.Panel({
      layout: ui.Panel.Layout.flow('horizontal'),
      style: {margin: '2px 0', shown: false}
    });
    row.add(ui.Label(year + ':', {fontSize: '10px', margin: '5px 4px 0 0', width: '36px'}));
    var tb = ui.Textbox({
      placeholder: placeholder,
      style: {fontSize: '10px', stretch: 'horizontal'}
    });
    inputs[year] = tb;
    yearPanels[year] = row;
    row.add(tb);
    yearInputsContainer.add(row);
  });

  var checkbox = ui.Checkbox({
    label: label, value: false,
    onChange: function(v) {
      modeSelect.style().set('shown', v);
      yearInputsContainer.style().set('shown', v);
      if (v) updateVisibleAssetInputs(); // show correct year rows
      markNeedsUpdate();
    },
    style: {fontSize: '11px'}
  });

  var headerRow = ui.Panel({
    widgets: [checkbox, modeSelect],
    layout: ui.Panel.Layout.flow('horizontal'),
    style: {margin: '0'}
  });

  // Preprocessing UI — one shared config for all years of this dataset
  var prepUi = createPreprocessingUi();

  var outerPanel = ui.Panel({
    widgets: [headerRow, yearInputsContainer, prepUi.panel],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {margin: '0 0 4px 0'}
  });

  // Only show preprocessing panel when checkbox is enabled
  prepUi.panel.style().set('shown', false);
  checkbox.onChange(function(v) {
    prepUi.panel.style().set('shown', v);
  });

  return {
    checkbox: checkbox,
    modeSelect: modeSelect,
    panel: outerPanel,

    getAsset: function(year) {
      return inputs[year] ? inputs[year].getValue() : '';
    },

    // Get preprocessing config (shared across all years)
    getPreprocessingConfig: function() {
      return prepUi.getConfig();
    },

    updateVisibility: function(splitScreenEnabled, year1, year2) {
      years.forEach(function(year) {
        var show = splitScreenEnabled ? (year === year1 || year === year2) : (year === year2);
        yearPanels[year].style().set('shown', show);
      });
    },

    setShown: function(shown) {
      outerPanel.style().set('shown', shown);
    },

    reset: function() {
      checkbox.setValue(false);
      modeSelect.setValue(defaultMode);
      modeSelect.style().set('shown', false);
      yearInputsContainer.style().set('shown', false);
      prepUi.panel.style().set('shown', false);
      years.forEach(function(year) { inputs[year].setValue(''); });
    },

    // For settings serialisation
    collectAssets: function(checkboxVal) {
      if (!checkboxVal) return {};
      var out = {};
      years.forEach(function(year) {
        var v = inputs[year].getValue();
        if (v) out[year] = v;
      });
      return out;
    },

    applyAssets: function(assetsByYear) {
      years.forEach(function(year) {
        if (assetsByYear[year]) inputs[year].setValue(assetsByYear[year]);
      });
    },

    collectPreprocessing: function() { return prepUi.collectSettings(); },
    applyPreprocessing:   function(s) { prepUi.applySettings(s); }
  };
}

// Each accepts GEE asset IDs (users/..., projects/...) or gs:// Cloud Storage COG URIs.
// Use ⚙ Preprocessing to configure source type, band, classes, or threshold.
var nationalRoads      = createNationalAssetInputs({label: 'Custom road data',            defaultMode: 'Add to global',  placeholder: 'users/me/roads or gs://bucket/roads.tif'});
var nationalBuiltupSmall = createNationalAssetInputs({label: 'Custom small built-up data',  defaultMode: 'Add to global',  placeholder: 'users/me/builtup_small or gs://...'});
var nationalBuiltupLarge = createNationalAssetInputs({label: 'Custom large built-up data',  defaultMode: 'Add to global',  placeholder: 'users/me/builtup_large or gs://...'});
var nationalAgri       = createNationalAssetInputs({label: 'Custom agriculture data',     defaultMode: 'Replace global', placeholder: 'users/me/agri or gs://bucket/agri.tif'});
var nationalPlantations= createNationalAssetInputs({label: 'Custom plantations data',     defaultMode: 'Replace global', placeholder: 'users/me/plantations or gs://bucket/plantations.tif'});
var nationalProtected  = createNationalAssetInputs({label: 'Custom protected areas data', defaultMode: 'Add to global',  placeholder: 'users/me/protected or gs://bucket/protected.tif'});

// Slope is non-temporal — single textbox kept intentionally
var useCustomSlopeCheckbox = ui.Checkbox({
  label: 'Custom slope data (0–90°)', value: false,
  onChange: function(v) { customSlopeInput.style().set('shown', v); markNeedsUpdate(); },
  style: {fontSize: '11px'}
});
var customSlopeInput = ui.Textbox({
  placeholder: 'users/me/custom_slope  (0–90 degrees)',
  style: {shown: false, fontSize: '10px', stretch: 'horizontal', margin: '2px 0 0 12px'}
});

// =============================================================================
// COLLAPSIBLE PANELS (pff_layout style)
// =============================================================================

// DATES & VIEW PANEL
var datesContent = ui.Panel({
  widgets: [
    yearSelector1Label, yearSelector1,
    yearSelector2Label, yearSelector2,
    enableSplitScreenCheckbox
  ],
  style: {shown: false, padding: '8px'}
});

var datesToggle = ui.Button({
  label: '▶ 1. Time Period',
  onClick: function() {
    var wasCollapsed = appState.ui.datesCollapsed;
    if (wasCollapsed) {
      collapseAllPanelsExcept('dates');
    }
    appState.ui.datesCollapsed = !appState.ui.datesCollapsed;
    datesContent.style().set({shown: !appState.ui.datesCollapsed});
    datesToggle.setLabel(appState.ui.datesCollapsed ? '▶ 1. Time Period' : '▼ 1. Time Period');
    updateLeftPanelWidth();
  },
  style: {stretch: 'horizontal', textAlign: 'left', padding: '6px', margin: '2px', backgroundColor: '#f0f0f0'}
});

var datesPanelCollapsible = ui.Panel({
  widgets: [datesToggle, datesContent],
  layout: ui.Panel.Layout.flow('vertical')
});

// TREE COVER PANEL
var treeCoverContent = ui.Panel({
  widgets: [
    ui.Label('Define Tree Cover:', {fontWeight: 'bold', margin: '0 0 4px 0'}),
    createCompactRow('Source:', treecoverSourceSelect),
    treecoverPanel,
    treecoverHeightPanel,
    forestAssets.panel,
    ui.Panel({style: {height: '1px', backgroundColor: '#ddd', margin: '6px 0', stretch: 'horizontal'}}),
    includePlantationsCheckbox,
    nationalPlantations.panel
  ],
  style: {shown: false, padding: '8px'}
});

var treeCoverToggle = ui.Button({
  label: '▶ 2. Tree Cover',
  onClick: function() {
    var wasCollapsed = appState.ui.treeCoverCollapsed;
    if (wasCollapsed) {
      // Opening - close all others first
      collapseAllPanelsExcept('treeCover');
    }
    appState.ui.treeCoverCollapsed = !appState.ui.treeCoverCollapsed;
    treeCoverContent.style().set({shown: !appState.ui.treeCoverCollapsed});
    treeCoverToggle.setLabel(appState.ui.treeCoverCollapsed ? '▶ 2. Tree Cover' : '▼ 2. Tree Cover');
    updateLeftPanelWidth();
  },
  style: {stretch: 'horizontal', textAlign: 'left', padding: '6px', margin: '2px', backgroundColor: '#f0f0f0'}
});

var treeCoverPanelCollapsible = ui.Panel({
  widgets: [treeCoverToggle, treeCoverContent],
  layout: ui.Panel.Layout.flow('vertical')
});

// Helper to create compact label+slider rows
function createBufferRow(label, slider) {
  return ui.Panel({
    layout: ui.Panel.Layout.flow('horizontal'),
    widgets: [
      ui.Label(label, {width: '100px', margin: '6px 0 0 0'}),
      slider
    ],
    style: {margin: '0px'}
  });
}

// Helper to create compact label+widget rows for selects/sliders
function createCompactRow(label, widget) {
  return ui.Panel({
    layout: ui.Panel.Layout.flow('horizontal'),
    widgets: [
      ui.Label(label, {margin: '6px 4px 0 0'}),
      widget
    ],
    style: {margin: '0px'}
  });
}

var slopePanel = ui.Panel({
  layout: ui.Panel.Layout.flow('horizontal'),
  widgets: [
    ui.Label('Slope (degrees) >', {margin: '6px 2px 0 0'}),
    slopeToKeepSlider
  ],
  style: {margin: '0px'}
});

// ANTHROPOGENIC PANEL — slope and protected areas with enable toggles
var slopeControls = ui.Panel({
  widgets: [
    slopePanel,
    ui.Panel({widgets: [useCustomSlopeCheckbox, customSlopeInput], layout: ui.Panel.Layout.flow('vertical'), style: {margin: '0 0 4px 0'}})
  ],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {margin: '0'}
});
var enableSlope = ui.Checkbox({
  label: 'Steep slope:',
  value: true,
  onChange: function(checked) {
    slopeControls.style().set({shown: checked});
    markNeedsUpdate();
  }
});

var protectedControls = ui.Panel({
  widgets: [
    createCompactRow('IUCN Categories:', wdpaPresetSelect),
    wdpaCategoryLabel, wdpaCategoryCheckboxPanel,
    createCompactRow('Designated Before:', wdpaYearSlider),
    nationalProtected.panel
  ],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {margin: '0'}
});
var enableProtectedAreas = ui.Checkbox({
  label: 'Protected areas:',
  value: true,
  onChange: function(checked) {
    protectedControls.style().set({shown: checked});
    markNeedsUpdate();
  }
});

var bufferExceptionsContent = ui.Panel({
  widgets: [
    enableSlope, slopeControls,
    enableProtectedAreas, protectedControls
  ],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {shown: false, margin: '0 0 0 4px'}
});
var bufferExceptionsToggle = ui.Button({
  label: '▸ Buffer Exceptions',
  onClick: function() {
    var s = bufferExceptionsContent.style().get('shown');
    bufferExceptionsContent.style().set({shown: !s});
    bufferExceptionsToggle.setLabel(s ? '▸ Buffer Exceptions' : '▾ Buffer Exceptions');
    updateLeftPanelWidth();
  },
  style: {fontSize: '11px', color: '#555', margin: '6px 0 2px 0', padding: '2px 4px', backgroundColor: '#f0f0f0'}
});

// Helper: create a combined checkbox + slider row for a buffer type
// Slider hides when checkbox is unticked
function createToggleBufferRow(label, slider) {
  var sliderPanel = ui.Panel({widgets: [slider], style: {stretch: 'horizontal', margin: '0'}});
  var checkbox = ui.Checkbox({
    label: label, value: true,
    onChange: function(checked) {
      sliderPanel.style().set({shown: checked});
      markNeedsUpdate();
    }
  });
  var row = ui.Panel({
    layout: ui.Panel.Layout.flow('horizontal'),
    widgets: [checkbox, sliderPanel],
    style: {margin: '0px'}
  });
  return {checkbox: checkbox, row: row, sliderPanel: sliderPanel};
}

var roadsToggle = createToggleBufferRow('Roads:', roadSmallBufferSlider);
var builtUpSmallToggle = createToggleBufferRow('Small Built-Up:', builtUpSmallBufferSlider);
var builtUpLargeToggle = createToggleBufferRow('Large Built-Up:', builtUpLargeBufferSlider);
var agriToggle = createToggleBufferRow('Agriculture:', agriBufferSlider);

// Expose checkboxes for use in analysis and settings
var enableRoadsBuffer = roadsToggle.checkbox;
var enableBuiltUpSmallBuffer = builtUpSmallToggle.checkbox;
var enableBuiltUpLargeBuffer = builtUpLargeToggle.checkbox;
var enableAgriBuffer = agriToggle.checkbox;

masterBufferRow = ui.Panel({
  layout: ui.Panel.Layout.flow('horizontal'),
  widgets: [ui.Label('All:', {margin: '6px 4px 0 0'}), masterBufferSlider],
  style: {margin: '0px', shown: false}
});
individualBufferRows = [roadsToggle.row, builtUpSmallToggle.row, builtUpLargeToggle.row, agriToggle.row];

// Custom data inputs toggle
var enableCustomDataCheckbox = ui.Checkbox({
  label: 'Enable custom data inputs',
  value: false,
  onChange: function(checked) {
    nationalRoads.panel.style().set({shown: checked});
    nationalBuiltupSmall.panel.style().set({shown: checked});
    nationalBuiltupLarge.panel.style().set({shown: checked});
    nationalAgri.panel.style().set({shown: checked});
    nationalProtected.panel.style().set({shown: checked});
    useCustomSlopeCheckbox.style().set({shown: checked});
    if (!checked) customSlopeInput.style().set({shown: false});
    updateLeftPanelWidth();
  },
  style: {fontSize: '11px', color: '#555', margin: '6px 0 2px 0'}
});

var anthropogenicContent = ui.Panel({
  widgets: [
    ui.Label('Define Human Influence (m):', {fontWeight: 'bold', margin: '0 0 4px 0'}),
    useMasterBufferCheckbox,
    masterBufferRow,
    roadsToggle.row,
    nationalRoads.panel,
    builtUpSmallToggle.row,
    nationalBuiltupSmall.panel,
    builtUpLargeToggle.row,
    nationalBuiltupLarge.panel,
    agriToggle.row,
    nationalAgri.panel,
    bufferExceptionsToggle,
    bufferExceptionsContent,
    enableCustomDataCheckbox
  ],
  style: {shown: false, padding: '8px'}
});

// Hide custom data panels by default (shown when "Enable custom data inputs" is ticked)
nationalRoads.panel.style().set({shown: false});
nationalBuiltupSmall.panel.style().set({shown: false});
nationalBuiltupLarge.panel.style().set({shown: false});
nationalAgri.panel.style().set({shown: false});
nationalProtected.panel.style().set({shown: false});
useCustomSlopeCheckbox.style().set({shown: false});

var anthropogenicToggle = ui.Button({
  label: '▶ 3. Human Influence',
  onClick: function() {
    var wasCollapsed = appState.ui.anthropogenicCollapsed;
    if (wasCollapsed) {
      collapseAllPanelsExcept('anthropogenic');
    }
    appState.ui.anthropogenicCollapsed = !appState.ui.anthropogenicCollapsed;
    anthropogenicContent.style().set({shown: !appState.ui.anthropogenicCollapsed});
    anthropogenicToggle.setLabel(appState.ui.anthropogenicCollapsed ? '▶ 3. Human Influence' : '▼ 3. Human Influence');
    updateLeftPanelWidth();
  },
  style: {stretch: 'horizontal', textAlign: 'left', padding: '6px', margin: '2px', backgroundColor: '#f0f0f0'}
});

var anthropogenicPanel = ui.Panel({
  widgets: [anthropogenicToggle, anthropogenicContent],
  layout: ui.Panel.Layout.flow('vertical')
});

// CONNECTIVITY PANEL
var connectivityControls = ui.Panel({
  widgets: [
    ui.Label('Pixels with too few forest neighbours within this radius are removed.', {fontSize: '11px', color: '#555', margin: '0 0 6px 0'}),
    ui.Label('Neighbourhood Radius (m):'), smoothRadiusForestSlider,
    ui.Label('Min. Density to Keep:'), smallPixelThresholdForestSlider
  ],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {margin: '0'}
});
var enableRefineOutput = ui.Checkbox({
  label: 'Refine output:',
  value: true,
  onChange: function(checked) {
    connectivityControls.style().set({shown: checked});
    markNeedsUpdate();
  }
});
var connectivityContent = ui.Panel({
  widgets: [enableRefineOutput, connectivityControls],
  style: {shown: false, padding: '8px'}
});

var connectivityToggle = ui.Button({
  label: '▶ 4. Refine Output',
  onClick: function() {
    var wasCollapsed = appState.ui.connectivityCollapsed;
    if (wasCollapsed) {
      collapseAllPanelsExcept('connectivity');
    }
    appState.ui.connectivityCollapsed = !appState.ui.connectivityCollapsed;
    connectivityContent.style().set({shown: !appState.ui.connectivityCollapsed});
    connectivityToggle.setLabel(appState.ui.connectivityCollapsed ? '▶ 4. Refine Output' : '▼ 4. Refine Output');
    updateLeftPanelWidth();
  },
  style: {stretch: 'horizontal', textAlign: 'left', padding: '6px', margin: '2px', backgroundColor: '#f0f0f0'}
});

var connectivityPanel = ui.Panel({
  widgets: [connectivityToggle, connectivityContent],
  layout: ui.Panel.Layout.flow('vertical')
});

// Implement accordion behavior - now that all panels are defined
collapseAllPanelsExcept = function(exceptPanel) {
  if (exceptPanel !== 'dates' && !appState.ui.datesCollapsed) {
    appState.ui.datesCollapsed = true;
    datesContent.style().set({shown: false});
    datesToggle.setLabel('▶ 1. Time Period');
  }
  if (exceptPanel !== 'treeCover' && !appState.ui.treeCoverCollapsed) {
    appState.ui.treeCoverCollapsed = true;
    treeCoverContent.style().set({shown: false});
    treeCoverToggle.setLabel('▶ 2. Tree Cover');
  }
  if (exceptPanel !== 'anthropogenic' && !appState.ui.anthropogenicCollapsed) {
    appState.ui.anthropogenicCollapsed = true;
    anthropogenicContent.style().set({shown: false});
    anthropogenicToggle.setLabel('▶ 3. Human Influence');
  }
  if (exceptPanel !== 'connectivity' && !appState.ui.connectivityCollapsed) {
    appState.ui.connectivityCollapsed = true;
    connectivityContent.style().set({shown: false});
    connectivityToggle.setLabel('▶ 4. Refine Output');
  }
};

// =============================================================================
// FLOATING LAYER PANEL (on map) - created as function for reuse
// =============================================================================

function createFloatingLayerPanel() {
  var layerScrollPanel = ui.Panel({
    widgets: [
      ui.Label('Layer Visibility', {fontWeight: 'bold', fontSize: '14px'}),
      ui.Label('─────────────────', {color: 'gray'}),
      ui.Checkbox({label: 'Primary Forest',        value: visibleLayers.primaryForest,       onChange: function(v) { visibleLayers.primaryForest       = v; toggleLayerByName('Primary Forest', v); }}),
      ui.Checkbox({label: 'Forest Outside Buffers', value: visibleLayers.forestOutsideBuffers, onChange: function(v) { visibleLayers.forestOutsideBuffers = v; toggleLayerByName('Forest outside buffers', v); }}),
      ui.Checkbox({label: 'Input: Forest',            value: visibleLayers.forest,               onChange: function(v) { visibleLayers.forest               = v; toggleLayerByName('Input: Forest', v); }}),
      ui.Checkbox({label: 'Plantations',            value: visibleLayers.plantations,          onChange: function(v) { visibleLayers.plantations          = v; toggleLayerByName('Plantations', v); }}),
      ui.Label(''),
      ui.Label('Disturbance inputs:', {fontWeight: 'bold'}),
      ui.Checkbox({label: 'Agriculture',  value: visibleLayers.inputAgriculture,  onChange: function(v) { visibleLayers.inputAgriculture  = v; toggleLayerByName('Input: Agriculture', v); }}),
      ui.Checkbox({label: 'Roads',        value: visibleLayers.inputRoads,        onChange: function(v) { visibleLayers.inputRoads        = v; toggleLayerByName('Input: Roads', v); }}),
      ui.Checkbox({label: 'Built-up',     value: visibleLayers.inputBuiltupSmall, onChange: function(v) { visibleLayers.inputBuiltupSmall = v; toggleLayerByName('Input: Small Built-up', v); }}),
      ui.Checkbox({label: 'Built-up Large', value: visibleLayers.inputBuiltupLarge, onChange: function(v) { visibleLayers.inputBuiltupLarge = v; toggleLayerByName('Input: Large Built-up', v); }}),
      ui.Label(''),
      ui.Label('Buffers:', {fontWeight: 'bold'}),
      ui.Checkbox({label: 'Agriculture',  value: visibleLayers.agriBuffer,       onChange: function(v) { visibleLayers.agriBuffer       = v; toggleLayerByName('Buffer: Agriculture', v); }}),
      ui.Checkbox({label: 'Roads',        value: visibleLayers.roadSmallBuffer, onChange: function(v) { visibleLayers.roadSmallBuffer = v; toggleLayerByName('Buffer: Roads', v); }}),
      ui.Checkbox({label: 'Built-up Large', value: visibleLayers.builtLargeBuffer, onChange: function(v) { visibleLayers.builtLargeBuffer = v; toggleLayerByName('Buffer: Large Built-up', v); }}),
      ui.Label(''),
      ui.Label('Other:', {fontWeight: 'bold'}),
      ui.Checkbox({label: 'Slope',           value: visibleLayers.slope,          onChange: function(v) { visibleLayers.slope          = v; toggleLayerByName('Input: Slope', v); }}),
      ui.Checkbox({label: 'Protected Areas', value: visibleLayers.protectedAreas, onChange: function(v) { visibleLayers.protectedAreas = v; toggleLayerByName('Input: Protected', v); }}),
      ui.Checkbox({label: 'FLII Comparison', value: visibleLayers.flii,           onChange: function(v) { visibleLayers.flii           = v; toggleLayerByName('Reference: FLII (high/med)', v); }})
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {padding: '8px'}
  });

  var layerControlContent = ui.Panel({
    widgets: [layerScrollPanel],
    style: {shown: !appState.ui.layersPanelCollapsed, width: '200px', maxHeight: '400px', border: '1px solid #ccc', backgroundColor: 'rgba(255, 255, 255, 0.95)'}
  });

  var layerToggleButton = ui.Button({
    label: appState.ui.layersPanelCollapsed ? '▶ Layers' : '▼ Layers',
    onClick: function() {
      appState.ui.layersPanelCollapsed = !appState.ui.layersPanelCollapsed;
      layerControlContent.style().set({shown: !appState.ui.layersPanelCollapsed});
      layerToggleButton.setLabel(appState.ui.layersPanelCollapsed ? '▶ Layers' : '▼ Layers');
    },
    style: {width: '90px', padding: '4px', margin: '4px'}
  });

  return ui.Panel({
    widgets: [layerToggleButton, layerControlContent],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {position: 'top-left', margin: '8px 0px 0px 8px', padding: '0px', backgroundColor: 'rgba(255, 255, 255, 0.95)', border: '2px solid #ccc'}
  });
}

// =============================================================================
// LEGEND PANEL (floating on map, bottom-left)
// =============================================================================

function createLegendItem(color, label) {
  var colorBox = ui.Label({
    style: {
      backgroundColor: color,
      padding: '8px',
      margin: '0 4px 0 0',
      border: '1px solid #666'
    }
  });
  var description = ui.Label({
    value: label,
    style: {margin: '0', fontSize: '11px'}
  });
  return ui.Panel({
    widgets: [colorBox, description],
    layout: ui.Panel.Layout.flow('horizontal'),
    style: {margin: '2px 0'}
  });
}

// Canonical legend definition: visibleLayers key → [colour, label]
var LEGEND_ENTRIES = [
  {key: 'primaryForest',       color: '#26600e', label: 'Primary Forest',         group: 'Forest'},
  {key: 'forestOutsideBuffers',color: '#228B22', label: 'Forest outside buffers', group: 'Forest'},
  {key: 'forest',              color: '#90EE90', label: 'Input: Forest',           group: 'Forest'},
  {key: 'plantations',         color: '#d4a017', label: 'Plantations',            group: 'Forest'},
  {key: 'agriBuffer',          color: '#ffcc00', label: 'Buffer: Agriculture',    group: 'Human Influence'},
  {key: 'roadSmallBuffer',     color: '#ff6600', label: 'Buffer: Roads',          group: 'Human Influence'},
  {key: 'builtSmallBuffer',    color: '#cc00cc', label: 'Buffer: Small Built-up', group: 'Human Influence'},
  {key: 'builtLargeBuffer',    color: '#3333cc', label: 'Buffer: Large Built-up', group: 'Human Influence'},
  {key: 'inputRoads',          color: '#993d00', label: 'Input: Roads',           group: 'Human Influence'},
  {key: 'inputBuiltupSmall',   color: '#800080', label: 'Input: Small Built-up',  group: 'Human Influence'},
  {key: 'inputBuiltupLarge',   color: '#1a1a80', label: 'Input: Large Built-up',  group: 'Human Influence'},
  {key: 'inputAgriculture',    color: '#b38f00', label: 'Input: Agriculture',     group: 'Human Influence'},
  {key: 'protectedAreas',      color: '#00cccc', label: 'Input: Protected Areas', group: 'Buffer Exceptions'},
  {key: 'slope',               color: '#8B4513', label: 'Input: Slope',           group: 'Buffer Exceptions'}
];

function createLegendPanel() {
  var legendItemsPanel = ui.Panel({
    widgets: [ui.Label('Legend', {fontWeight: 'bold', fontSize: '12px', margin: '0 0 4px 0'})],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {padding: '6px'}
  });

  // Read actual layer visibility from the map (handles native layer control)
  function syncVisibleLayersFromMap() {
    // Check map2 (always exists), fall back to map1
    var m = map2 || map1;
    if (!m) return;
    var layers = m.layers();
    // Build a set of visible layer names from the map
    var visibleNames = {};
    for (var i = 0; i < layers.length(); i++) {
      var layer = layers.get(i);
      if (layer.getShown()) {
        visibleNames[layer.getName()] = true;
      }
    }
    // Update visibleLayers state from map reality
    // Map layer names back to visibleLayers keys
    var NAME_TO_KEY = {
      'Primary Forest': 'primaryForest',
      'Forest outside buffers': 'forestOutsideBuffers',
      'Input: Forest': 'forest',
      'Plantations': 'plantations',
      'Buffer: Agriculture': 'agriBuffer',
      'Buffer: Roads': 'roadSmallBuffer',
      'Buffer: Small Built-up': 'builtSmallBuffer',
      'Buffer: Large Built-up': 'builtLargeBuffer',
      'Input: Roads': 'inputRoads',
      'Input: Small Built-up': 'inputBuiltupSmall',
      'Input: Large Built-up': 'inputBuiltupLarge',
      'Input: Agriculture': 'inputAgriculture'
    };
    // Reset all to false, then set visible ones
    Object.keys(visibleLayers).forEach(function(k) { visibleLayers[k] = false; });
    Object.keys(visibleNames).forEach(function(name) {
      if (NAME_TO_KEY[name]) {
        visibleLayers[NAME_TO_KEY[name]] = true;
      }
      // Prefix match for slope / protected / forest (dynamic names)
      if (name.indexOf('Input: Slope') === 0) visibleLayers.slope = true;
      if (name.indexOf('Input: Protected') === 0) visibleLayers.protectedAreas = true;
      if (name.indexOf('Reference: FLII') === 0) visibleLayers.flii = true;
      if (name.indexOf('Input: Forest') === 0) visibleLayers.forest = true;
    });
  }

  var _initialBuild = true;

  // Rebuild legend from visibleLayers state
  function refreshLegend() {
    if (!_initialBuild) {
      syncVisibleLayersFromMap();
    }
    _initialBuild = false;
    // Clear all except the title label
    while (legendItemsPanel.widgets().length() > 1) {
      legendItemsPanel.remove(legendItemsPanel.widgets().get(1));
    }
    var lastGroup = '';
    var anyShown = false;
    LEGEND_ENTRIES.forEach(function(entry) {
      if (visibleLayers[entry.key]) {
        if (entry.group !== lastGroup) {
          legendItemsPanel.add(ui.Label(entry.group + ':', {fontWeight: 'bold', fontSize: '11px', margin: '4px 0 2px 0'}));
          lastGroup = entry.group;
        }
        legendItemsPanel.add(createLegendItem(entry.color, entry.label));
        anyShown = true;
      }
    });
    if (!anyShown) {
      legendItemsPanel.add(ui.Label('(no layers visible)', {fontSize: '11px', color: '#888'}));
    }
  }

  // Initial build (just show Primary Forest since that's the default)
  refreshLegend();

  // Store refresh callback globally so toggleLayerByName can trigger it
  _legendRefreshFns.push(refreshLegend);

  var legendContent = ui.Panel({
    widgets: [legendItemsPanel],
    style: {shown: true, width: '160px', border: '1px solid #ccc', backgroundColor: 'rgba(255, 255, 255, 0.95)'}
  });

  var legendRefreshButton = ui.Button({
    label: '↻',
    onClick: refreshLegend,
    style: {fontSize: '10px', padding: '1px 4px', margin: '4px 0 4px 2px', width: '24px', height: '24px'}
  });

  var legendToggleButton = ui.Button({
    label: '▼ Legend',
    onClick: function() {
      var isShown = legendContent.style().get('shown');
      legendContent.style().set({shown: !isShown});
      legendToggleButton.setLabel(isShown ? '▶ Legend' : '▼ Legend');
    },
    style: {width: '80px', padding: '4px', margin: '4px'}
  });

  return ui.Panel({
    widgets: [
      ui.Panel([legendToggleButton, legendRefreshButton], ui.Panel.Layout.flow('horizontal'), {margin: '0', padding: '0'}),
      legendContent
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {position: 'bottom-left', margin: '0px 0px 8px 8px', padding: '0px', backgroundColor: 'rgba(255, 255, 255, 0.95)', border: '2px solid #ccc'}
  });
}

// =============================================================================
// UN MAP DISCLAIMER (floating, bottom-right)
// =============================================================================

function createDisclaimerPanel() {
  var disclaimerText = 'The designations employed and the presentation of material on this map ' +
    'do not imply the expression of any opinion whatsoever on the part of the Secretariat of the ' +
    'United Nations concerning the legal status of any country, territory, city or area or of its ' +
    'authorities, or concerning the delimitation of its frontiers or boundaries. Dotted line represents ' +
    'approximately the Line of Control in Jammu and Kashmir agreed upon by India and Pakistan. The ' +
    'final status of Jammu and Kashmir has not yet been agreed upon by the parties. Final boundary ' +
    'between the Republic of Sudan and the Republic of South Sudan has not yet been determined. ' +
    'Final status of the Abyei area is not yet determined. A dispute exists between the Governments ' +
    'of Argentina and the United Kingdom of Great Britain and Northern Ireland concerning sovereignty ' +
    'over the Falkland Islands (Malvinas).';

  var disclaimerContent = ui.Panel({
    widgets: [ui.Label(disclaimerText, {fontSize: '9px', color: '#555', margin: '4px'})],
    style: {shown: false, width: '320px', backgroundColor: 'rgba(255,255,255,0.95)', border: '1px solid #ccc', padding: '4px'}
  });

  var disclaimerButton = ui.Button({
    label: 'ℹ Map disclaimer',
    onClick: function() {
      var s = disclaimerContent.style().get('shown');
      disclaimerContent.style().set({shown: !s});
    },
    style: {fontSize: '9px', color: '#555', padding: '2px 6px', margin: '0', backgroundColor: 'rgba(255,255,255,0.85)', border: '1px solid #ccc'}
  });

  return ui.Panel({
    widgets: [disclaimerButton, disclaimerContent],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {position: 'bottom-right', margin: '0 8px 8px 0', padding: '0'}
  });
}

// =============================================================================
// STATS PANEL (collapsible, right side)
// =============================================================================

var statsWidgets = [
  ui.Panel([showStatsButton, statsInfoButton], ui.Panel.Layout.flow('horizontal'), {margin: '0'}),
  statsInfoContent,
  clearStatsButton,
  ui.Panel([statsScaleLabel, statsScaleSlider], ui.Panel.Layout.flow('horizontal'), {stretch: 'horizontal', margin: '0 0 0 8px'}),
  areaStatsPanel,
  exportStatsPanel,
  exportStatusLabel
];

var statsContent = ui.Panel({
  widgets: statsWidgets,
  layout: ui.Panel.Layout.flow('vertical'),
  style: {shown: false, padding: '8px', backgroundColor: 'rgba(255,255,255,0.9)'}
});

var statsToggle = ui.Button({
  label: '▶ Area Statistics',
  onClick: function() {
    var isShown = statsContent.style().get('shown');
    if (!isShown) {
      // Opening Results - close Config and Export
      settingsContent.style().set({shown: false});
      settingsToggle.setLabel('▶ Config');
      downloadsContent.style().set({shown: false});
      downloadsToggle.setLabel('▶ Export Layers');
    }
    statsContent.style().set({shown: !isShown});
    statsToggle.setLabel(isShown ? '▶ Area Statistics' : '▼ Area Statistics');
    updateRightPanelWidth();
  },
  style: {stretch: 'horizontal', textAlign: 'left', padding: '6px', margin: '2px', backgroundColor: '#f0f0f0'}
});

var statsPanel = ui.Panel({
  widgets: [statsToggle, statsContent],
  layout: ui.Panel.Layout.flow('vertical')
});

// =============================================================================
// SETTINGS PANEL (collapsible, right side)
// =============================================================================

var exportSettingsButton = ui.Button({label: 'Save Settings', onClick: exportSettings, style: {width: '140px', margin: '4px 0px'}});
var importSettingsButton = ui.Button({label: 'Load Settings', onClick: showTextInput, style: {width: '140px', margin: '4px 0px'}});

// Reset function to restore all parameters to defaults
function resetToDefaults() {
  // Tree Cover
  treecoverThresholdSlider.setValue(10);
  treecoverHeightThresholdSlider.setValue(5);
  treecoverSourceSelect.setValue('GLAD LULC');
  
  // Anthropogenic buffers
  useMasterBufferCheckbox.setValue(false);
  masterBufferSlider.setValue(1000);
  enableRoadsBuffer.setValue(true);
  enableBuiltUpSmallBuffer.setValue(true);
  enableBuiltUpLargeBuffer.setValue(true);
  enableAgriBuffer.setValue(true);
  roadSmallBufferSlider.setValue(1000);
  builtUpSmallBufferSlider.setValue(1000);
  builtUpLargeBufferSlider.setValue(1000);
  agriBufferSlider.setValue(1000);
  
  // Protection
  enableSlope.setValue(true);
  enableProtectedAreas.setValue(true);
  enableRefineOutput.setValue(true);
  slopeToKeepSlider.setValue(45);
  wdpaYearSlider.setValue(current_year - 30);
  wdpaPresetSelect.setValue('Strict (Ia, Ib, II)');
  
  // Connectivity
  smoothRadiusForestSlider.setValue(2000);
  smallPixelThresholdForestSlider.setValue(0.5);
  
  // Reset plantations and custom assets
  includePlantationsCheckbox.setValue(true);
  if (treecoverSourceSelect.getValue() === 'Custom Forest') {
    treecoverSourceSelect.setValue('GLAD LULC');
  }

  // Reset national data overrides
  nationalRoads.reset();
  nationalBuiltupSmall.reset();
  nationalBuiltupLarge.reset();
  nationalAgri.reset();
  nationalPlantations.reset();
  nationalProtected.reset();
  useCustomSlopeCheckbox.setValue(false);
  customSlopeInput.setValue('');
  customSlopeInput.style().set('shown', false);

  // Reset layer visibility to defaults
  resetVisibleLayers();
}

var resetSettingsButton = ui.Button({label: 'Reset Defaults', onClick: resetToDefaults, style: {width: '90px', margin: '2px 0px', fontSize: '10px', color: '#888'}});

var settingsContent = ui.Panel({
  widgets: [exportSettingsButton, importSettingsButton],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {shown: false, padding: '8px', backgroundColor: 'rgba(255,255,255,0.9)'}
});

var settingsToggle = ui.Button({
  label: '▶ Config',
  onClick: function() {
    var isShown = settingsContent.style().get('shown');
    if (!isShown) {
      // Opening Config - close Results and Export
      statsContent.style().set({shown: false});
      statsToggle.setLabel('▶ Area Statistics');
      downloadsContent.style().set({shown: false});
      downloadsToggle.setLabel('▶ Export Layers');
    }
    settingsContent.style().set({shown: !isShown});
    settingsToggle.setLabel(isShown ? '▶ Config' : '▼ Config');
    updateRightPanelWidth();
  },
  style: {stretch: 'horizontal', textAlign: 'left', padding: '6px', margin: '2px', backgroundColor: '#f0f0f0'}
});

var settingsPanel = ui.Panel({
  widgets: [settingsToggle, settingsContent],
  layout: ui.Panel.Layout.flow('vertical')
});

// =============================================================================
// EXPORT PANEL (collapsible, right side)
// =============================================================================

var saveDataWidgets = [
  ui.Label('Download to Computer', {fontWeight: 'bold', fontSize: '11px', margin: '4px 0 4px 0', color: '#333'}),
  downloadPanel
];
if (!IS_APP) {
  saveDataWidgets.push(ui.Label('', {margin: '6px 0 0 0'})); // spacer
  saveDataWidgets.push(ui.Label('Export to Google Drive', {fontWeight: 'bold', fontSize: '11px', margin: '4px 0 4px 0', color: '#333'}));
  saveDataWidgets.push(exportRastersPanel);
}

var downloadsContent = ui.Panel({
  widgets: saveDataWidgets,
  layout: ui.Panel.Layout.flow('vertical'),
  style: {shown: false, padding: '8px', backgroundColor: 'rgba(255,255,255,0.9)'}
});

var downloadsToggle = ui.Button({
  label: '▶ Export Layers',
  onClick: function() {
    var isShown = downloadsContent.style().get('shown');
    if (!isShown) {
      // Opening Export - close Results and Config
      statsContent.style().set({shown: false});
      statsToggle.setLabel('▶ Area Statistics');
      settingsContent.style().set({shown: false});
      settingsToggle.setLabel('▶ Config');
    }
    downloadsContent.style().set({shown: !isShown});
    downloadsToggle.setLabel(isShown ? '▶ Export Layers' : '▼ Export Layers');
    updateRightPanelWidth();
  },
  style: {stretch: 'horizontal', textAlign: 'left', padding: '6px', margin: '2px', backgroundColor: '#d4edda'}
});

var downloadsPanel = ui.Panel({
  widgets: [downloadsToggle, downloadsContent],
  layout: ui.Panel.Layout.flow('vertical')
});

// =============================================================================
// LAYOUT PANELS
// =============================================================================

// Left panel with collapsible sections and scroll
var leftPanel = ui.Panel({
  widgets: [runButton, resetSettingsButton, datesPanelCollapsible, treeCoverPanelCollapsible, anthropogenicPanel, connectivityPanel],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {width: '150px', backgroundColor: 'rgba(255, 255, 255, 0.95)', padding: '2px', maxHeight: '600px'}
});

// Right panel with results, config, and export
var rightPanel = ui.Panel({
  widgets: [statsPanel, settingsPanel, downloadsPanel],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {width: '120px', backgroundColor: 'rgba(255, 255, 255, 0.95)', padding: '2px', maxHeight: '600px'}
});

// Variable to keep track of the download link panel
var downloadLinkPanel;

// Add a loading label
var loadingLabel = ui.Label({
  value: 'Loading...',
  style: {color: 'red', fontWeight: 'bold', shown: false}
});

// Function to collect current settings
function collectSettings() {
  var settings = {
    'Country': countrySelector.getValue(),
    'Year 1': yearSelector1.getValue(),
    'Year 2': yearSelector2.getValue(),
    'Treecover Threshold (%)': treecoverThresholdSlider.getValue(),
    'GLAD Treecover Height (m)': treecoverHeightThresholdSlider.getValue(),
    'Road Small Buffer (m)': roadSmallBufferSlider.getValue(),
    'Built-Up Small Buffer (m)': builtUpSmallBufferSlider.getValue(),
    'Built-Up Large Buffer (m)': builtUpLargeBufferSlider.getValue(),
    'Slope to keep (degrees)': slopeToKeepSlider.getValue(),
    'Agriculture Buffer (m)': agriBufferSlider.getValue(),
    // 'Other Natural Buffer (m)': otherNatBufferSlider.getValue(),
    'Forest Smoothing Radius (m)': smoothRadiusForestSlider.getValue(),
    'Forest Smoothing Threshold': smallPixelThresholdForestSlider.getValue(),
    // 'Use Accurate Distance Buffers': fastBufferCheckbox.getValue(),
    // 'Include GISD': includeGISDCheckbox.getValue(),
    // 'Include GISA': includeGISACheckbox.getValue(),
    // 'Include WSF': includeWSFCheckbox.getValue(),
    // 'Include BuiltUp': includeGHSLCheckbox.getValue(),
  'Use Hansen (GFC) Tree Cover': (treecoverSourceSelect.getValue() === 'Hansen GFC'),
  'Use GLAD LULC Forest': (treecoverSourceSelect.getValue() === 'GLAD LULC'),
  'Use Both Datasets Forest': (treecoverSourceSelect.getValue() === 'Both datasets (Hansen & GLAD)'),
  'Use Either Dataset Forest': (treecoverSourceSelect.getValue() === 'Either dataset (Hansen | GLAD)'),
    'Exclude Plantations': includePlantationsCheckbox.getValue(),
    'WDPA Preset': wdpaPresetSelect.getValue(),
    'WDPA Designated Before': wdpaYearSlider.getValue(),
    'WDPA Selected Categories': selected_iucn_categories.join(', '),
    'Custom Roads Mode': nationalRoads.modeSelect.getValue(),
    'Custom BuiltUp Small Mode': nationalBuiltupSmall.modeSelect.getValue(),
    'Custom BuiltUp Large Mode': nationalBuiltupLarge.modeSelect.getValue(),
    'Custom Agri Mode': nationalAgri.modeSelect.getValue(),
    'Custom Plantations Mode': nationalPlantations.modeSelect.getValue(),
    'Custom Protected Mode': nationalProtected.modeSelect.getValue(),
    'Custom Slope Asset': useCustomSlopeCheckbox.getValue() ? customSlopeInput.getValue() : '',
    'Use Master Buffer': useMasterBufferCheckbox.getValue(),
    'Master Buffer (m)': masterBufferSlider.getValue(),
    'Enable Roads Buffer': enableRoadsBuffer.getValue(),
    'Enable Small BuiltUp Buffer': enableBuiltUpSmallBuffer.getValue(),
    'Enable Large BuiltUp Buffer': enableBuiltUpLargeBuffer.getValue(),
    'Enable Agriculture Buffer': enableAgriBuffer.getValue(),
    'Enable Slope': enableSlope.getValue(),
    'Enable Protected Areas': enableProtectedAreas.getValue(),
    'Enable Refine Output': enableRefineOutput.getValue()
  };

  // Add custom forest asset inputs if used
  if (treecoverSourceSelect.getValue() === 'Custom Forest') {
    years.forEach(function(year) {
      var assetInputValue = forestAssets.getAsset(year);
      if (assetInputValue) {
        settings['Custom Forest Asset ' + year] = assetInputValue;
      }
    });
  }

  // Add custom asset inputs per year
  var nationalDatasets = {
    'Custom Roads': nationalRoads,
    'Custom BuiltUp Small': nationalBuiltupSmall,
    'Custom BuiltUp Large': nationalBuiltupLarge,
    'Custom Agri': nationalAgri,
    'Custom Plantations': nationalPlantations,
    'Custom Protected': nationalProtected
  };
  Object.keys(nationalDatasets).forEach(function(key) {
    var obj = nationalDatasets[key];
    if (obj.checkbox.getValue()) {
      years.forEach(function(year) {
        var v = obj.getAsset(year);
        if (v) settings[key + ' Asset ' + year] = v;
      });
    }
  });

  return settings;
}

// Function to export settings
function exportSettings() {
  var settings = collectSettings();
  var settingsFeature = ee.Feature(null, settings);
  var settingsCollection = ee.FeatureCollection([settingsFeature]);

  var url = settingsCollection.getDownloadURL({
    format: 'json',
    filename: 'settings_primary_forest_app.json'
  });

  // Remove the previous download link panel if it exists
  if (downloadLinkPanel) {
    ui.root.widgets().remove(downloadLinkPanel);
  }

  // Create a new download link
  var downloadLink = ui.Label({
    value: 'Download Settings',
    style: {color: 'blue', textDecoration: 'underline'},
    targetUrl: url
  });

  // Create a close button
  var closeButton = ui.Button({
    label: '✖',
    style: {margin: '0 0 0 10px'},
    onClick: function() {
      ui.root.widgets().remove(downloadLinkPanel);
      downloadLinkPanel = null;
    }
  });

  // Create a panel to hold the download link and close button
  downloadLinkPanel = ui.Panel({
    widgets: [downloadLink, closeButton],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {margin: '10px 0'}
  });

  ui.root.widgets().add(downloadLinkPanel);
}


// Function to show text input for importing settings
function showTextInput() {
  var textInputPanel = ui.Panel({
    widgets: [
      ui.Label('Paste Settings from JSON (and press enter):'),
      ui.Textbox({
        placeholder: 'Paste settings JSON here',
        onChange: ui.util.debounce(function(value) {
          // Show loading label
          loadingLabel.style().set('shown', true);
          var success = false;
          
          try {
            var settings = JSON.parse(value);
            if (settings.type === 'FeatureCollection' && settings.features.length > 0) {
              settings = settings.features[0].properties;
            }
            applySettings(settings);
            success = true;
          } catch (e) {
            print('Invalid JSON format: ' + e.message);
            // Add more detailed error message to help users
            print('Check that you copied the entire file content, including { and } characters');
          } finally {
            // Hide loading label
            loadingLabel.style().set('shown', false);
            
            // Only remove the panel if successful
            if (success) {
              ui.root.widgets().remove(textInputPanel);
            }
          }
        },300),
        style: {width: '400px', height: '200px'}
      }),
      
      // Add a close button
      ui.Button({
        label: 'Cancel',
        onClick: function() {
          ui.root.widgets().remove(textInputPanel);
        },
        style: {margin: '5px 0'}
      })
    ],
    style: {margin: '10px 0', padding: '10px'}
  });

  ui.root.widgets().add(textInputPanel);
}
 
// Function to apply settings
function applySettings(settings) {
  
  countrySelector.setValue(settings['Country']);
  yearSelector1.setValue(settings['Year 1']);
  yearSelector2.setValue(settings['Year 2']);
  treecoverThresholdSlider.setValue(settings['Treecover Threshold (%)']);
  treecoverHeightThresholdSlider.setValue(settings['GLAD Treecover Height (m)']);
  roadSmallBufferSlider.setValue(settings['Road Small Buffer (m)']);
  builtUpSmallBufferSlider.setValue(settings['Built-Up Small Buffer (m)']);
  builtUpLargeBufferSlider.setValue(settings['Built-Up Large Buffer (m)']);
  agriBufferSlider.setValue(settings['Agriculture Buffer (m)']);
  // Master buffer
  if (settings['Use Master Buffer'] !== undefined) {
    useMasterBufferCheckbox.setValue(settings['Use Master Buffer']);
  }
  if (settings['Master Buffer (m)'] !== undefined) {
    masterBufferSlider.setValue(settings['Master Buffer (m)']);
  }
  if (settings['Enable Roads Buffer'] !== undefined) enableRoadsBuffer.setValue(settings['Enable Roads Buffer']);
  if (settings['Enable Small BuiltUp Buffer'] !== undefined) enableBuiltUpSmallBuffer.setValue(settings['Enable Small BuiltUp Buffer']);
  if (settings['Enable Large BuiltUp Buffer'] !== undefined) enableBuiltUpLargeBuffer.setValue(settings['Enable Large BuiltUp Buffer']);
  if (settings['Enable Agriculture Buffer'] !== undefined) enableAgriBuffer.setValue(settings['Enable Agriculture Buffer']);
  if (settings['Enable Slope'] !== undefined) enableSlope.setValue(settings['Enable Slope']);
  if (settings['Enable Protected Areas'] !== undefined) enableProtectedAreas.setValue(settings['Enable Protected Areas']);
  if (settings['Enable Refine Output'] !== undefined) enableRefineOutput.setValue(settings['Enable Refine Output']);
  slopeToKeepSlider.setValue(settings['Slope to keep (degrees)']);
  // otherNatBufferSlider.setValue(settings['Other Natural Buffer (m)']);
  smoothRadiusForestSlider.setValue(settings['Forest Smoothing Radius (m)']);
  smallPixelThresholdForestSlider.setValue(settings['Forest Smoothing Threshold']);
  // fastBufferCheckbox.setValue(settings['Use Accurate Distance Buffers']);
  // includeGISDCheckbox.setValue(settings['Include GISD']);
  // includeGISACheckbox.setValue(settings['Include GISA']);
  // includeWSFCheckbox.setValue(settings['Include WSF']);
  // includeGHSLCheckbox.setValue(settings['Include BuiltUp']);
  if (settings['Use Hansen (GFC) Tree Cover']) {
    treecoverSourceSelect.setValue('Hansen GFC');
  } else if (settings['Use GLAD LULC Forest']) {
    treecoverSourceSelect.setValue('GLAD LULC');
  } else if (settings['Use Both Datasets Forest']) {
    treecoverSourceSelect.setValue('Both datasets (Hansen & GLAD)');
  } else if (settings['Use Either Dataset Forest']) {
    treecoverSourceSelect.setValue('Either dataset (Hansen | GLAD)');
  } else if (settings['Use Agreement Forest']) { // backward compat
    treecoverSourceSelect.setValue('Both datasets (Hansen & GLAD)');
  }
  
  // Restore custom forest selection: handled by treecoverSourceSelect restore above
  if (settings['Exclude Plantations'] !== undefined) {
    includePlantationsCheckbox.setValue(settings['Exclude Plantations']);
  } else if (settings['Include Plantations'] !== undefined) {
    // Backward compatibility: invert old "Include" to new "Exclude" semantic
    includePlantationsCheckbox.setValue(!settings['Include Plantations']);
  }

  if (treecoverSourceSelect.getValue() === 'Custom Forest') {
    years.forEach(function(year) {
      if (settings['Custom Forest Asset ' + year]) {
        forestAssets.inputs[year].setValue(settings['Custom Forest Asset ' + year]);
      }
    });
  }

  // Restore custom asset overrides (per-year)
  var nationalRestoreMap = {
    'Custom Roads': nationalRoads,
    'Custom BuiltUp Small': nationalBuiltupSmall,
    'Custom BuiltUp Large': nationalBuiltupLarge,
    'Custom Agri': nationalAgri,
    'Custom Plantations': nationalPlantations,
    'Custom Protected': nationalProtected
  };
  Object.keys(nationalRestoreMap).forEach(function(key) {
    var obj = nationalRestoreMap[key];
    var modeKey = key + ' Mode';
    var hasAny = false;
    years.forEach(function(year) {
      if (settings[key + ' Asset ' + year]) hasAny = true;
    });
    if (hasAny) {
      obj.checkbox.setValue(true);
      obj.modeSelect.style().set('shown', true);
      if (settings[modeKey]) obj.modeSelect.setValue(settings[modeKey]);
      var assetsByYear = {};
      years.forEach(function(year) {
        if (settings[key + ' Asset ' + year]) assetsByYear[year] = settings[key + ' Asset ' + year];
      });
      obj.applyAssets(assetsByYear);
      // trigger visibility so year rows appear
      var useSplitScreen = enableSplitScreenCheckbox.getValue();
      var y1 = parseInt(yearSelector1.getValue());
      var y2 = parseInt(yearSelector2.getValue());
      obj.updateVisibility(useSplitScreen, y1, y2);
      obj.setShown(true);
    }
  });
  if (settings['Custom Slope Asset']) {
    useCustomSlopeCheckbox.setValue(true);
    customSlopeInput.setValue(settings['Custom Slope Asset']);
    customSlopeInput.style().set('shown', true);
  }

  updateMap();
}

// Create maps (will be recreated on mode changes to avoid parent conflicts)
var map1 = null;
var map2 = null; // initialized below with globe view

// Explicitly tracked centers/zooms (avoid relying on ui.Map.getCenter())
var map1Center = null; // [lon, lat]
var map1Zoom = null;   // number
var map2Center = null; // [lon, lat]
var map2Zoom = null;   // number

// Main container with left panel, map, and right panel
var mainContainer = ui.Panel({
  layout: ui.Panel.Layout.flow('horizontal'),
  style: {stretch: 'both', backgroundColor: 'white'}
});

// Root container with top bar and main content
var rootContainer = ui.Panel({
  widgets: [topBar, mainContainer],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {stretch: 'both'}
});

// Initialize the UI
ui.root.widgets().reset([rootContainer]);

// Set initial globe view
map2 = ui.Map();
map2.setCenter(0, 20, 2);
map2.setControlVisibility({all: true, zoomControl: true});
map2.add(createLegendPanel());
map2.add(createDisclaimerPanel());
map2.setOptions('Gray', {Gray: GRAYMAP});
mainContainer.add(leftPanel);
mainContainer.add(map2);
mainContainer.add(rightPanel);

// splitPanel will be created on-demand when needed
var splitPanel = null;

// Create ui.Map.Layer objects for Hansen GFC that can be dynamically updated
var hansenLayer1 = ui.Map.Layer(null, {min:0, max:1, palette:['white','lightgreen']}, 'Forest (GFC Hansen)', false);
var hansenLayer2 = ui.Map.Layer(null, {min:0, max:1, palette:['white','lightgreen']}, 'Forest (GFC Hansen)', false);

// Store reference to the current forest data for each map
var currentForestData = {
  map1: {forest_map_clip: null, analysisYear: null, country_sel: null},
  map2: {forest_map_clip: null, analysisYear: null, country_sel: null}
};

// Function to update Hansen layer with new zoom-dependent scale
// This prevents masking issues at different zoom levels
function updateHansenLayer(map, mapName, hansenLayer) {
  // Check if Hansen is enabled and has data
  if (treecoverSourceSelect.getValue() !== 'Hansen GFC') {
    // Hansen is not enabled - zoom rendering only works with Hansen GFC
    return;
  }
  
  var data = currentForestData[mapName];
  if (!data.forest_map_clip) {
    // Data not loaded yet - this is normal on initial setup
    return;
  }
  
  var z = map.getZoom();
  var s = scaleForZoom(z, 30, 10, 1.8, 30, 900)
  // var s = scaleForZoom({z:z, base_scale:30, pivot_z:10, r:1.8, min_scale:30, max_scale:900}) ;
  
  // Get base projection
  var baseProj = data.forest_map_clip.projection();
  
  // Reproject with zoom-dependent scale
  var forest_rendered = data.forest_map_clip.reproject({
    crs: baseProj, 
    scale: s
  });
  
  // Update the layer with new rendering (same pattern as test file)
  hansenLayer.setEeObject(forest_rendered);
  hansenLayer.setName('Forest (GFC Hansen ' + data.analysisYear + ' @ ' + s + 'm)');
  hansenLayer.setShown(false);
}

// Note: Zoom listeners will be attached when maps are created in updateMap

// Linker will be created only when split screen is enabled
var linker = null;

// Track current display mode
var currentMode = 'single';

// Track previous state to detect actual changes vs mode switches
var previousState = {
  country: null,
  splitScreen: false,
  mapCenter: null,
  mapZoom: null
};

// Preserve view for manual recentering
var lastCenter = null; // ee.Geometry.Point
var lastZoom = null;   // number
var previousCountry = null; // Track last selected country name

// (visibleLayers defined above layerPanel)

// Helper to log current map center and zoom
function logCenterExplicit(label, centerArr, zoomVal) {
  if (centerArr && centerArr.length === 2 && typeof zoomVal === 'number') {
    print(label + ' center lon/lat: ' + centerArr[0] + ', ' + centerArr[1] + ' | zoom: ' + zoomVal);
  } else {
    print(label + ' center unavailable');
  }
}

// WORKAROUND: Linked maps may not fire zoom change events reliably
// Poll for zoom changes as backup
var lastZoomPoll = {map1: null, map2: null};
ui.util.setInterval(function() {
  if (treecoverSourceSelect.getValue() !== 'Hansen GFC') return;
  
  // Guard against null maps (not yet initialized)
  if (!map1 || !map2) return;
  
  var z1 = map1.getZoom();
  var z2 = map2.getZoom();
  
  if (z1 !== lastZoomPoll.map1 && currentForestData.map1.forest_map_clip) {
    lastZoomPoll.map1 = z1;
    updateHansenLayer(map1, 'map1', hansenLayer1);
  }
  
  if (z2 !== lastZoomPoll.map2 && currentForestData.map2.forest_map_clip) {
    lastZoomPoll.map2 = z2;
    updateHansenLayer(map2, 'map2', hansenLayer2);
  }
}, 500); // Check every 500ms

// updateMap() // removed to see if needed


// Main update function

function updateMap()  { 
  markUpToDate();
  // Clear stale on-the-fly stats whenever parameters change
  areaStatsPanel.clear();
  exportStatusLabel.setValue('');
  var useSplitScreen = enableSplitScreenCheckbox.getValue();
  var analysisYear1 = parseInt(yearSelector1.getValue());
  var analysisYear2 = parseInt(yearSelector2.getValue());

  // Reset stored forest data so only currently-active years appear in stats
  latestMaskedForest = {};
  latestMaskedPrimaryForest = {};
  latestPreConnectivityForest = {};
  latestTier1Undisturbed = {};
  latestTier2Steep = {};
  latestTier3Protected = {};
  var selectedCountry = countrySelector.getValue();
  
  if (!selectedCountry || selectedCountry === '') {
    countrySelector.style().set({border: '2px solid #cc6666', color: '#cc6666'});
    countryWarningLabel.setValue('Please choose a country');
    countryWarningLabel.style().set({shown: true});
    return;
  }

  ////////////////////////////////
  // Check if country or years changed (requires clearing cache)
  if (selectedCountry !== cachedState.country || 
      analysisYear1 !== cachedState.year1 || 
      analysisYear2 !== cachedState.year2) {
    // Clear cache when fundamental parameters change
    cachedState.distanceImages = {};
    cachedState.country = selectedCountry;
    cachedState.year1 = analysisYear1;
    cachedState.year2 = analysisYear2;
  }
  /////////////////////////////

  var treecoverPercentThreshold = treecoverThresholdSlider.getValue();
  var treecoverHeightThreshold = treecoverHeightThresholdSlider.getValue();
  var roadSmallBuffer = roadSmallBufferSlider.getValue();
  var builtUpSmallBuffer = builtUpSmallBufferSlider.getValue();
  var builtUpLargeBuffer = builtUpLargeBufferSlider.getValue();
  var agriBuffer = agriBufferSlider.getValue();
  var slopeToKeepValue = slopeToKeepSlider.getValue();
  // var otherNatBuffer = otherNatBufferSlider.getValue();
  // var includeGISD = includeGISDCheckbox.getValue();
  // var includeGISA = includeGISACheckbox.getValue();
  // var includeWSF = includeWSFCheckbox.getValue();
  // var includeGHSL = includeGHSLCheckbox.getValue();
  var useHansenTreecover = (treecoverSourceSelect.getValue() === 'Hansen GFC');
  var useGladLulcForest = (treecoverSourceSelect.getValue() === 'GLAD LULC');
  var useAgreementForest = (treecoverSourceSelect.getValue() === 'Both datasets (Hansen & GLAD)');
  var useUnionForest = (treecoverSourceSelect.getValue() === 'Either dataset (Hansen | GLAD)');
  // var fastBuffer = fastBufferCheckbox.getValue();
  var smoothRadiusForest = smoothRadiusForestSlider.getValue();
  var smallPixelThresholdForest = smallPixelThresholdForestSlider.getValue();

  print('=== updateMap START ===');
  print('updateMap: country=' + selectedCountry + ' | split=' + useSplitScreen);
  print('Visible layers: Primary=' + visibleLayers.primaryForest +
        ' | ForestOutside=' + visibleLayers.forestOutsideBuffers +
        ' | Forest=' + visibleLayers.forest +
        ' | RoadSmall=' + visibleLayers.roadSmallBuffer);
  
  var country_sel = getCountryFeatures(selectedCountry);
  
  var requestedMode = useSplitScreen ? 'split' : 'single';
  var modeChanged = (currentMode !== requestedMode);
  var countryChanged = (previousCountry !== selectedCountry);

  // Reset layer visibility when country changes so primary forest shows by default
  if (countryChanged && previousCountry !== null) {
    resetVisibleLayers();
  }

  // Force initialization on first run
  var needsInit = (requestedMode === 'single' && !map2) || (requestedMode === 'split' && (!map1 || !map2));
  if (needsInit) {
    modeChanged = true;
    print('First run - forcing initialization');
  }
  
  print('Mode check: current=' + currentMode + ' | requested=' + requestedMode + ' | changed=' + modeChanged);
  
  // Capture current view before potential rebuild (always capture to preserve view across mode changes)
  // Prefer map2 in single mode, map1 in split mode
  var activeMapPre = (currentMode === 'split' && map1) ? map1 : map2;
  if (activeMapPre) {
    try {
      lastZoom = activeMapPre.getZoom();
      var cPre = activeMapPre.getCenter(); // returns {lon, lat}
      if (cPre && typeof cPre.lon === 'number' && typeof cPre.lat === 'number') {
        lastCenter = ee.Geometry.Point([cPre.lon, cPre.lat]);
        print('Captured view: ' + cPre.lon + ', ' + cPre.lat + ' @ zoom ' + lastZoom);
      }
    } catch (e) {
      print('Error capturing view: ' + e);
    }
  }

  // Only rebuild UI if mode changed
  if (modeChanged) {
    print('Mode change: ' + currentMode + ' -> ' + requestedMode);

    // Clear main container and previous structures
    mainContainer.clear();
    linker = null;
    splitPanel = null;

    if (requestedMode === 'split') {
      // Recreate maps fresh
      map1 = ui.Map();
      map2 = ui.Map();
      map1.setControlVisibility({all: true, zoomControl: true});
      map2.setControlVisibility({all: true, zoomControl: true});
      
      // Add legend to first map
      map1.add(createLegendPanel());
      map1.add(createDisclaimerPanel());
      
      // Reset tracked centers/zooms when maps are recreated
      map1Center = null;
      map1Zoom = null;
      map2Center = null;
      map2Zoom = null;

      // Build split mode
      splitPanel = ui.SplitPanel({
        firstPanel: map1,
        secondPanel: map2,
        orientation: 'horizontal',
        wipe: true
      });
      
      // Assemble main container: left panel + split maps + right panel
      mainContainer.add(leftPanel);
      mainContainer.add(splitPanel);
      mainContainer.add(rightPanel);
      
      linker = ui.Map.Linker([map1, map2]);
      
      // Re-attach zoom listeners for Hansen
      map1.onChangeZoom(function() {
        updateHansenLayer(map1, 'map1', hansenLayer1);
      });
      map2.onChangeZoom(function() {
        updateHansenLayer(map2, 'map2', hansenLayer2);
      });
      
      print('Split mode initialized');
    } else {
      // Recreate single map fresh
      map2 = ui.Map();
      map2.setControlVisibility({all: true, zoomControl: true});
      
      // Add legend to map
      map2.add(createLegendPanel());
map2.add(createDisclaimerPanel());
      
      // Reset tracked center/zoom for single map
      map2Center = null;
      map2Zoom = null;

      // Assemble main container: left panel + map + right panel
      mainContainer.add(leftPanel);
      mainContainer.add(map2);
      mainContainer.add(rightPanel);
      
      // Re-attach zoom listener for Hansen
      map2.onChangeZoom(function() {
        updateHansenLayer(map2, 'map2', hansenLayer2);
      });
      
      print('Single mode initialized');
    }

    currentMode = requestedMode;
  } else {
    // Same mode — remove only PFF-managed layers; preserve user-added layers
    var pffLayerNames = [
      'Buffer: Roads', 'Buffer: Small Built-up', 'Buffer: Large Built-up',
      'Buffer: Agriculture', 'Input: Roads', 'Input: Small Built-up',
      'Input: Large Built-up', 'Input: Agriculture', 'Plantations',
      'Forest outside buffers', 'Primary Forest',
      'Reference: FLII (high/med)', 'Reference: Forest Persistence (FDaP)'
    ];
    // Also match dynamic names like "Slope > 45°", "WDPA ..."
    var pffPrefixes = ['Input: Slope', 'Input: Protected', 'Hansen ', 'Input: Forest'];
    function isPffLayer(name) {
      if (pffLayerNames.indexOf(name) !== -1) return true;
      for (var p = 0; p < pffPrefixes.length; p++) {
        if (name.indexOf(pffPrefixes[p]) === 0) return true;
      }
      return false;
    }
    // Map layer names to visibleLayers keys so we can capture user toggles
    var nameToKey = {
      'Primary Forest': 'primaryForest',
      'Forest outside buffers': 'forestOutsideBuffers',
      // 'Input: Forest' handled via prefix matching below
      'Input: Roads': 'inputRoads',
      'Input: Small Built-up': 'inputBuiltupSmall',
      'Input: Large Built-up': 'inputBuiltupLarge',
      'Input: Agriculture': 'inputAgriculture',
      'Buffer: Roads': 'roadSmallBuffer',
      'Buffer: Small Built-up': 'builtSmallBuffer',
      'Buffer: Large Built-up': 'builtLargeBuffer',
      'Buffer: Agriculture': 'agriBuffer',
      'Plantations': 'plantations',
      'Reference: FLII (high/med)': 'flii'
    };
    function syncAndRemovePffLayers(m) {
      if (!m) return;
      var layers = m.layers();
      // First pass: capture current shown state from the map
      for (var i = 0; i < layers.length(); i++) {
        var layer = layers.get(i);
        var key = nameToKey[layer.getName()];
        if (key) visibleLayers[key] = layer.getShown();
        // Handle dynamic prefix names
        var lname = layer.getName();
        if (lname.indexOf('Input: Slope') === 0) visibleLayers.slope = layer.getShown();
        if (lname.indexOf('Input: Protected') === 0) visibleLayers.protectedAreas = layer.getShown();
        if (lname.indexOf('Input: Forest') === 0) visibleLayers.forest = layer.getShown();
      }
      // Second pass: remove PFF layers
      for (var j = layers.length() - 1; j >= 0; j--) {
        if (isPffLayer(layers.get(j).getName())) layers.remove(layers.get(j));
      }
    }
    syncAndRemovePffLayers(map1);
    syncAndRemovePffLayers(map2);
  }
  
  // After rebuild or clear, ensure maps are centered to avoid default USA view
  // Priority: restore last view if available; otherwise center on selected country
  var centroid = country_sel.geometry().centroid().coordinates().getInfo();
  if (useSplitScreen) {
    if (map1 && (!map1Center || !map1Zoom)) {
      if (lastCenter && lastZoom) {
        var lc1 = lastCenter.coordinates().getInfo();
        map1.setCenter(lc1[0], lc1[1], lastZoom);
        map1Center = [lc1[0], lc1[1]];
        map1Zoom = lastZoom;
        print('map1 restored to: ' + lc1[0] + ', ' + lc1[1] + ' @ ' + lastZoom);
      } else {
        map1.setCenter(centroid[0], centroid[1], 6);
        map1Center = [centroid[0], centroid[1]];
        map1Zoom = 6;
        print('map1 centered to country centroid');
      }
    }
    if (map2 && (!map2Center || !map2Zoom)) {
      if (lastCenter && lastZoom) {
        var lc2 = lastCenter.coordinates().getInfo();
        map2.setCenter(lc2[0], lc2[1], lastZoom);
        map2Center = [lc2[0], lc2[1]];
        map2Zoom = lastZoom;
        print('map2 restored to: ' + lc2[0] + ', ' + lc2[1] + ' @ ' + lastZoom);
      } else {
        map2.setCenter(centroid[0], centroid[1], 6);
        map2Center = [centroid[0], centroid[1]];
        map2Zoom = 6;
        print('map2 centered to country centroid');
      }
    }
  } else {
    if (map2 && (!map2Center || !map2Zoom)) {
      if (lastCenter && lastZoom) {
        var lc = lastCenter.coordinates().getInfo();
        map2.setCenter(lc[0], lc[1], lastZoom);
        map2Center = [lc[0], lc[1]];
        map2Zoom = lastZoom;
        print('map2 restored to: ' + lc[0] + ', ' + lc[1] + ' @ ' + lastZoom);
      } else {
        map2.setCenter(centroid[0], centroid[1], 6);
        map2Center = [centroid[0], centroid[1]];
        map2Zoom = 6;
        print('map2 centered to country centroid');
      }
    }
  }
  
  // Configure map layout based on split screen setting
  if (useSplitScreen) {
    // Split screen mode - remove old year labels if they exist
    if (yearLabel1Widget && map1) {
      try { map1.remove(yearLabel1Widget); } catch(e) {}
    }
    if (yearLabel2Widget && map2) {
      try { map2.remove(yearLabel2Widget); } catch(e) {}
    }
    
    // Create new year labels
    yearLabel1Widget = ui.Label({
      value: 'Year: ' + yearSelector1.getValue(),
      style: {
        position: 'top-left',
        backgroundColor: 'rgba(255, 255, 255, 0.8)',
        padding: '8px',
        margin: '3px',
        fontSize: '20px',
        fontWeight: 'bold'
      }
    });
    
    yearLabel2Widget = ui.Label({
      value: 'Year: ' + yearSelector2.getValue(),
      style: {
        position: 'top-right',
        backgroundColor: 'rgba(255, 255, 255, 0.8)',
        padding: '8px',
        margin: '3px',
        fontSize: '20px',
        fontWeight: 'bold'
      }
    });
    
    map1.add(yearLabel1Widget);
    map2.add(yearLabel2Widget);
    
    // Apply gray map style to both maps
    map1.setOptions('Gray', {Gray: GRAYMAP});
    map2.setOptions('Gray', {Gray: GRAYMAP});
    
    // Auto-zoom on first load or country change
    if (countryChanged) {
      print('Zooming to: ' + selectedCountry);
      map1.setCenter(centroid[0], centroid[1], 6);
      map1Center = [centroid[0], centroid[1]];
      map1Zoom = 6;
      logCenterExplicit('map1 after zoom', map1Center, map1Zoom);
    }
  } else {
    // Single map mode - remove old year labels if they exist
    if (yearLabel1Widget && map1) {
      try { map1.remove(yearLabel1Widget); } catch(e) {}
    }
    if (yearLabel2Widget && map2) {
      try { map2.remove(yearLabel2Widget); } catch(e) {}
    }
    
    // Create new year label
    yearLabel2Widget = ui.Label({
      value: 'Year: ' + yearSelector2.getValue(),
      style: {
        position: 'top-center',
        backgroundColor: 'rgba(255, 255, 255, 0.8)',
        padding: '8px',
        margin: '3px',
        fontSize: '20px',
        fontWeight: 'bold'
      }
    });
    yearLabel1Widget = null;  // Clear split-mode label reference
    
    map2.add(yearLabel2Widget);
    map2.setOptions('Gray', {Gray: GRAYMAP});
    
    // Auto-zoom on first load or country change
    if (countryChanged) {
      print('Zooming to: ' + selectedCountry);
      map2.setCenter(centroid[0], centroid[1], 6);
      map2Center = [centroid[0], centroid[1]];
      map2Zoom = 6;
      logCenterExplicit('map2 after zoom', map2Center, map2Zoom);
    }
  }
  //old
  // // Function to add layers to a map for a given year
  // function addLayersToMap(map, analysisYear) {
  //   // Forest cover processing
  //   var gfc_hansen = ee.Image("UMD/hansen/global_forest_change_2023_v1_11");
  //   var gfc_hansen_2000 = gfc_hansen.select("treecover2000").gt(treecoverPercentThreshold);
  //   var gfc_hansen_sel = gfc_hansen_2000.where(gfc_hansen.select("lossyear").lte(analysisYear - 2000), 0);
  //   var forest_map = gfc_hansen_sel;
  
  // Function to add layers to a map for a given year
  function addLayersToMap(map, analysisYear) {
    // Forest cover processing - with custom asset support
     var forest_map;
    
    // Check if a custom forest asset is provided
    var customForestAsset = forestAssets.getAsset(analysisYear);
    if (treecoverSourceSelect.getValue() === 'Custom Forest' && customForestAsset) {
      try {
        forest_map = preprocessAsset(customForestAsset, forestAssets.getPreprocessingConfig());
        print('Using custom forest asset for ' + analysisYear + ': ' + customForestAsset);
      } catch (e) {
        print('Error loading custom forest asset. Using fallback forest data.');
        e;
      }
    }
    
    // If no custom asset is set or it fails, select an alternative dataset
    if (!forest_map) {
      if (useAgreementForest) {
        forest_map = agreementForestPrep(analysisYear, treecoverPercentThreshold, treecoverHeightThreshold);
      } else if (useUnionForest) {
        forest_map = unionForestPrep(analysisYear, treecoverPercentThreshold, treecoverHeightThreshold);
      } else if (useGladLulcForest) {
        forest_map = gladLulcForestPrep(analysisYear,treecoverHeightThreshold);
      } 
      // Uncomment when needed
      // else if (useGlcFlsd30Forest) {
      //   forest_map = glc_flsd30_forest;
      //   print('Using GLC FLSD30 forest data for ' + analysisYear);
      // } 
      // else if (useEsaCciForest) {
      //   forest_map = esa_cci_forest;
      //   print('Using ESA CCI forest data for ' + analysisYear);
      // } 
      else if (useHansenTreecover) {
        // var treecoverPercentThreshold = 10
        forest_map = gfcHansenTreecoverPrep(analysisYear,treecoverPercentThreshold);
        //debug print('Using Hansen Treecover data for ' + analysisYear);
      } 
    }
    
    // Final check: If no forest dataset was selected, print a warning
    if (!forest_map) {
      print("No forest data selected — skipping layer build for " + analysisYear);
      return; // Prevent downstream errors
    }

    // Country mask preparation (raster-based, no vector .clip())
    var country_clip = getCountryClip(selectedCountry);
    // var country_buffer = ee.Image(1).cumulativeCost({
    //   source: country_clip, maxDistance: country_buffer_threshold, geodeticDistance: false
    // });
    
    var country_buffer = makeDistanceBuffer(country_clip, country_buffer_threshold, fastBuffer)
    var country_and_buffer_mask = country_buffer.where(country_clip, 1).selfMask();
    var forest_map_clip = forest_map.updateMask(country_and_buffer_mask);
    
    // var country_buffer = country_sel.geometry().buffer(country_buffer_threshold);
    
    // var country_buffer = (country_sel instanceof ee.FeatureCollection) ? 
    // country_sel.map(function(feat) {
    //     return feat.buffer(country_buffer_threshold);
    // }).union() :
    // country_sel.buffer(country_buffer_threshold);
    
    // map.addLayer(country_buffer)
    
    
    // var country_and_buffer_mask = ee.Image(1).clip(country_buffer);
    // var forest_map_clip = forest_map.clip(country_buffer);
    
    // map.addLayer(forest_map_clip, binary_lightgreen_palette, "Forest", 0, 1);
    
    /////////
    // Anthropogenic features
    var timeseriesAnthroModule = require("users/andyarnellgee/apps:modules/timeseriesAnthro.js");
    var glcFcs30dCollection = timeseriesAnthroModule.preprocessGlc();
    var landcover = glcFcs30dCollection.filter(ee.Filter.eq("year", analysisYear)).first().updateMask(country_and_buffer_mask);
    
    // Agricultural data
    var pastureDataset = ee.ImageCollection("projects/global-pasture-watch/assets/ggc-30m/v1/grassland_c");
    
    // var pastureDatasetSel = pastureDataset.filter(ee.Filter.eq("system:index", analysisYear.toString())).first().eq(1).unmask().updateMask(country_and_buffer_mask);
    var pastureDatasetCultivated = pastureDataset.map(function(image){return image.eq(1).set('year',ee.Number.parse(image.get("system:index")))})
    var pastureDatasetFF = forwardFillBinaryTimeSeries(pastureDatasetCultivated, years.filter(function(year) {return year >= 2000}));//forward filled version  i.e., anthropogenic LU remains anthropogenic 
    var pastureDatasetSel = pastureDatasetFF.filter(ee.Filter.eq("year", analysisYear)).first().updateMask(country_and_buffer_mask)
    var oilPalmDescalsCollection = timeseriesAnthroModule.processingOilPalmDescals();
    var oilPalmDescalsSel = ee.Image(oilPalmDescalsCollection.filter(ee.Filter.eq("year", analysisYear)).first()).updateMask(country_and_buffer_mask)
    var plantationsMosaicStatic = timeseriesAnthroModule.processingPlantationsMosaic().updateMask(country_and_buffer_mask)
    var allPlantationsSel = plantationsMosaicStatic.unmask().where(oilPalmDescalsSel.eq(1), 1).updateMask(country_and_buffer_mask)

    // Override plantations with national data if provided
    if (nationalPlantations.checkbox.getValue()) {
      var natPlantationsAsset = nationalPlantations.getAsset(analysisYear);
      if (natPlantationsAsset) {
        var natPlantations = preprocessAsset(natPlantationsAsset, nationalPlantations.getPreprocessingConfig()).updateMask(country_and_buffer_mask);
        if (nationalPlantations.modeSelect.getValue() === 'Add to global') {
          allPlantationsSel = allPlantationsSel.unmask(0).or(natPlantations).selfMask();
        } else {
          allPlantationsSel = natPlantations;
        }
      }
    }

    // Optionally remove plantations from forest input (default: excluded)
    if (includePlantationsCheckbox.getValue()) {
      forest_map_clip = forest_map_clip.updateMask(allPlantationsSel.unmask().not());
    }

    var croplandGladCollection = timeseriesAnthroModule.processingCroplandsGlad() 
 
  
    var croplandGladCollectionFF = forwardFillBinaryTimeSeries(croplandGladCollection, years);//forward filled version of processingCroplandsGlad i.e., cropland remains cropland 
    
    var croplandGladSel = ee.Image(croplandGladCollectionFF.filter(ee.Filter.eq("year",analysisYear)).first()).updateMask(country_and_buffer_mask)
    
    // var croplandGladSel = ee.Image(croplandGladCollection.filter(ee.Filter.eq("year",analysisYear)).first()).updateMask(country_and_buffer_mask)
    
    
    
    // Land cover classes
    var croplandClasses = [11, 12, 10];
    // var otherNatClasses = [120, 121, 122, 130, 140, 181, 182, 150, 152, 153];
    var croplandSel = remapClassesToOne(landcover, croplandClasses,0).unmask().updateMask(country_and_buffer_mask);
 
    // Processing parameters
    //many small cropland patches in forest - some are artefacts/noise. Smoothing can limit this effect
    var agriSmoothRadius = 30, agriSmallPixelThreshold = 0.5;
    
    
    var boxcar = ee.Kernel.circle({radius: agriSmoothRadius, units: 'meters', normalize: true});
    
    // Process cropland and agriculture
    // var croplandSelLessNoise = croplandSel.convolve(boxcar).gt(agriSmallPixelThreshold).convolve(boxcar).gt(agriSmallPixelThreshold);
    var croplandComb = croplandGladSel //.or(croplandSelLessNoise)// the removing small patches is slow for tihs

    var agriculture = pastureDatasetSel.or(allPlantationsSel.unmask()).or(croplandComb);

    // Override agriculture with national data if provided
    if (nationalAgri.checkbox.getValue()) {
      var natAgriAsset = nationalAgri.getAsset(analysisYear);
      if (natAgriAsset) {
        var natAgri = preprocessAsset(natAgriAsset, nationalAgri.getPreprocessingConfig()).updateMask(country_and_buffer_mask);
        if (nationalAgri.modeSelect.getValue() === 'Add to global') {
          agriculture = agriculture.unmask(0).or(natAgri).selfMask();
        } else {
          agriculture = natAgri;
        }
      }
    }

    // map.addLayer(plantationsMosaicStatic,"","plantationsMosaicStatic")

    // map.addLayer(country_and_buffer_mask,'',"country_and_buffer_mask")

    map.addLayer(allPlantationsSel.selfMask(), {palette: '#d4a017'}, 'Plantations', visibleLayers.plantations, 0.7);
    // map.addLayer(pastureDatasetSel,"","pastureDatasetSel")
    // map.addLayer(croplandComb,"","croplandComb")

    // Road data
    var roadsMosaicStatic = timeseriesAnthroModule.roadsMosaicStatic().updateMask(country_and_buffer_mask);
  
    // var msRoadsImage = ee.Image("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_microsoft/roadsAllImageGlobal");
    // var msRoadsImageBinary = msRoadsImage.gt(0).rename("constant")//change any width values 1 and rename
    // var roadsMosaicStatic = msRoadsImageBinary.updateMask(country_and_buffer_mask);
  
    var roadsCollection = timeseriesAnthroModule.getRoadsCollection();//has traffic inlcuded
    var roadsSel = roadsCollection.filter(ee.Filter.eq('year', analysisYear)).first().updateMask(country_and_buffer_mask);
    
    //test speed without vector roads
    // var roadsSmall = roadsSel.lte(roadSizeThreshold).unmask().or(roadsMosaicStatic);
    // var roadsLarge = roadsSel.gt(roadSizeThreshold);
    
    var roadsSmall = roadsMosaicStatic;

    // Merge national roads with global
    if (nationalRoads.checkbox.getValue()) {
      var natRoadsAsset = nationalRoads.getAsset(analysisYear);
      if (natRoadsAsset) {
        var natRoads = preprocessAsset(natRoadsAsset, nationalRoads.getPreprocessingConfig()).updateMask(country_and_buffer_mask);
        if (nationalRoads.modeSelect.getValue() === 'Replace global') {
          roadsSmall = natRoads;
        } else {
          roadsSmall = roadsSmall.unmask(0).or(natRoads).selfMask();
        }
      }
    }

    //waterways
    var wdb_nav_rivers = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/wdb_navigable_rivers")
    var nav_rivers = ee.Image().paint(wdb_nav_rivers, 1).updateMask(country_and_buffer_mask);
    
    var nav_wways_usa = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/nav_wways_usa");
    var osm_water = ee.ImageCollection("projects/sat-io/open-datasets/OSM_waterLayer");
    var osmCanals = osm_water.median().eq(4)
    
    // Map.addLayer(osmCanals,{min:0,max:1,palette:["blue"]},'OSM Water Global -canals')
    
    // Map.addLayer(nav_wways_usa,{min:0,max:1,palette:["red"]},"nav_wways_usa" )
    
    // Built-up areas
    var builtUpSmall = ee.Image(0);
    if (includeGISD) {
      var gisdCollection = timeseriesAnthroModule.getGISDCollection();
      builtUpSmall = builtUpSmall.or(gisdCollection.filter(ee.Filter.eq('year', analysisYear)).first().eq(1)).updateMask(country_and_buffer_mask);
    }
    if (includeGISA) {
      var gisaCollection = timeseriesAnthroModule.getGISACollection();
      builtUpSmall = builtUpSmall.or(gisaCollection.filter(ee.Filter.eq('year', analysisYear)).first().eq(1)).updateMask(country_and_buffer_mask);
    }
    if (includeWSF) {
      var wsfCollection = timeseriesAnthroModule.getWSFCollection();
      builtUpSmall = builtUpSmall.or(wsfCollection.filter(ee.Filter.eq('year', analysisYear)).first().eq(1)).updateMask(country_and_buffer_mask);
    }
    if (includeGHSL) {
      var ghslCollection = timeseriesAnthroModule.getGhslCollection();
      var ghslSel = ghslCollection.filter(ee.Filter.eq('year', analysisYear)).first().updateMask(country_and_buffer_mask);
      builtUpSmall = builtUpSmall.or(ghslSel.eq(1));
      var builtUpLarge = ghslSel.eq(2);
    }

    // Merge national small built-up with global
    if (nationalBuiltupSmall.checkbox.getValue()) {
      var natBuiltupSmallAsset = nationalBuiltupSmall.getAsset(analysisYear);
      if (natBuiltupSmallAsset) {
        var natBuiltupSmallData = preprocessAsset(natBuiltupSmallAsset, nationalBuiltupSmall.getPreprocessingConfig()).updateMask(country_and_buffer_mask);
        if (nationalBuiltupSmall.modeSelect.getValue() === 'Replace global') {
          builtUpSmall = natBuiltupSmallData;
        } else {
          builtUpSmall = builtUpSmall.unmask(0).or(natBuiltupSmallData).selfMask();
        }
      }
    }

    // Merge national large built-up with global
    if (nationalBuiltupLarge.checkbox.getValue()) {
      var natBuiltupLargeAsset = nationalBuiltupLarge.getAsset(analysisYear);
      if (natBuiltupLargeAsset) {
        var natBuiltupLargeData = preprocessAsset(natBuiltupLargeAsset, nationalBuiltupLarge.getPreprocessingConfig()).updateMask(country_and_buffer_mask);
        if (nationalBuiltupLarge.modeSelect.getValue() === 'Replace global') {
          builtUpLarge = natBuiltupLargeData;
        } else {
          builtUpLarge = builtUpLarge.unmask(0).or(natBuiltupLargeData).selfMask();
        }
      }
    }
    
    
     
    // Check cache first before calculating distance transforms
    var dist_road_small, dist_built_up_small, dist_built_up_large, dist_agriculture;
    
    
        
        
    // caching check box in addLayersToMap function
    if (useCachingCheckbox/*.getValue()*/ && cachedState.distanceImages[analysisYear + '_road_small']) {
      // Use cached distance images
      dist_road_small = cachedState.distanceImages[analysisYear + '_road_small'];
      dist_built_up_small = cachedState.distanceImages[analysisYear + '_built_up_small'];
      dist_built_up_large = cachedState.distanceImages[analysisYear + '_built_up_large'];
      dist_agriculture = cachedState.distanceImages[analysisYear + '_agriculture'];
      //debug print('Using cached distance images for year: ' + analysisYear);
    } else {
      // Calculate distance transforms
        dist_road_small = makeDistanceSurface(roadsSmall, fastBuffer);
        dist_built_up_small = makeDistanceSurface(builtUpSmall, fastBuffer);
        dist_built_up_large = makeDistanceSurface(ghslSel.eq(2), fastBuffer);
        dist_agriculture = makeDistanceSurface(agriculture, fastBuffer);
      
      // Only cache if caching is enabled
      if (useCachingCheckbox/*.getValue()*/) {
        cachedState.distanceImages[analysisYear + '_road_small'] = dist_road_small;
        cachedState.distanceImages[analysisYear + '_built_up_small'] = dist_built_up_small;
        cachedState.distanceImages[analysisYear + '_built_up_large'] = dist_built_up_large;
        cachedState.distanceImages[analysisYear + '_agriculture'] = dist_agriculture;
        //debug print('Calculated and cached distance images for year: ' + analysisYear);
      } else {
        //debug print('Calculated distance images without caching for year: ' + analysisYear);
      }
    }
    
    
    // ///////////////// testing caching
    // var distImageTest = cachedState.distanceImages[analysisYear + '_road_small'];

    // if (distImageTest) {
    //   map.addLayer(
    //     distImageTest, 
    //     {min: 0, max: 5000, palette: ['white', 'blue', 'darkblue']}, 
    //     'Distance to small roads (' + analysisYear + ')'
    //   );
    // } else {
    //   print('No cached distance image found for:', analysisYear + '_road_small');
    // }
    
    // if (cachedState.distanceImages[analysisYear + '_road_small']) {
    //   // Use cached distance images
    //   dist_road_small = cachedState.distanceImages[analysisYear + '_road_small'];
    //   dist_road_large = cachedState.distanceImages[analysisYear + '_road_large'];
    //   dist_built_up_small = cachedState.distanceImages[analysisYear + '_built_up_small'];
    //   dist_built_up_large = cachedState.distanceImages[analysisYear + '_built_up_large'];
    //   dist_agriculture = cachedState.distanceImages[analysisYear + '_agriculture'];
    //   print('Using cached distance images for year: ' + analysisYear);
    // } else {
    //   // Calculate distance transforms ONCE and cache them
    //   dist_road_small = makeDistanceSurface(roadsSmall, fastBuffer);
    //   dist_road_large = makeDistanceSurface(roadsLarge, fastBuffer);
    //   dist_built_up_small = makeDistanceSurface(builtUpSmall, fastBuffer);
    //   dist_built_up_large = makeDistanceSurface(ghslSel.eq(2), fastBuffer);
    //   dist_agriculture = makeDistanceSurface(agriculture, fastBuffer);
      
    //   // Cache distance images
    //   cachedState.distanceImages[analysisYear + '_road_small'] = dist_road_small;
    //   cachedState.distanceImages[analysisYear + '_road_large'] = dist_road_large;
    //   cachedState.distanceImages[analysisYear + '_built_up_small'] = dist_built_up_small;
    //   cachedState.distanceImages[analysisYear + '_built_up_large'] = dist_built_up_large;
    //   cachedState.distanceImages[analysisYear + '_agriculture'] = dist_agriculture;
    //   print('Calculated and cached distance images for year: ' + analysisYear);
    // }
   
    
    // 3. Apply thresholds 
    var buffer_from_road_small = applyDistanceThreshold(dist_road_small, roadSmallBuffer);
    // large roads removed — single roads category only
    var buffer_from_built_up_small = applyDistanceThreshold(dist_built_up_small, builtUpSmallBuffer);
    var buffer_from_built_up_large = applyDistanceThreshold(dist_built_up_large, builtUpLargeBuffer);
    var buffer_from_agriculture = applyDistanceThreshold(dist_agriculture, agriBuffer);
    
    
    ///////////////
    // // Buffer calculations
    // var buffer_from_road_small = makeDistanceBuffer(roadsSmall, roadSmallBuffer, fastBuffer);
    // var buffer_from_road_large = makeDistanceBuffer(roadsLarge, roadLargeBuffer, fastBuffer);
    // var buffer_from_built_up_small = makeDistanceBuffer(builtUpSmall, builtUpSmallBuffer, fastBuffer);
    // var buffer_from_built_up_large = makeDistanceBuffer(ghslSel.eq(2), builtUpLargeBuffer, fastBuffer);
    // var buffer_from_agriculture = makeDistanceBuffer(agriculture, agriBuffer, fastBuffer);
    // // var buffer_from_otherNatural = makeDistanceBuffer(otherNaturalDataset, otherNatBuffer, fastBuffer);
    
    
   ////////////// 
        // Define visualization parameters for each binary buffer
    var visParams = [
        {image: buffer_from_road_small,   color: 'red',         name: 'Buffer: Roads'},
        // large roads removed
        {image: buffer_from_built_up_small, color: 'brown',    name: 'Buffer: Small Built-up'},
        {image: buffer_from_built_up_large, color: 'orange',    name: 'Buffer: Large Built-up'},
        {image: buffer_from_agriculture,  color: 'pink',       name: 'Buffer: Agriculture'},
        // {image: buffer_from_otherNatural, color: 'purple',      name: 'Buffer: Other Natural'}
    ];
    
    // Function to generate visualization parameters for binary masks
    function getVisParams(color) {
        return {
            min: 0,
            max: 1,
            palette: [color]
        };
    }
    
    // Add buffer layers — only for enabled buffers
    // Order: agriculture (bottom), roads, small built-up, large built-up (top)
    if (enableAgriBuffer.getValue())
      map.addLayer(buffer_from_agriculture, getVisParams('#ffcc00'), 'Buffer: Agriculture', visibleLayers.agriBuffer, 0.5);
    if (enableRoadsBuffer.getValue())
      map.addLayer(buffer_from_road_small, getVisParams('#ff6600'), 'Buffer: Roads', visibleLayers.roadSmallBuffer, 0.5);
    if (enableBuiltUpSmallBuffer.getValue())
      map.addLayer(buffer_from_built_up_small, getVisParams('#cc00cc'), 'Buffer: Small Built-up', visibleLayers.builtSmallBuffer, 0.5);
    if (enableBuiltUpLargeBuffer.getValue())
      map.addLayer(buffer_from_built_up_large, getVisParams('#3333cc'), 'Buffer: Large Built-up', visibleLayers.builtLargeBuffer, 0.5);

    // Processed binary inputs — what actually feeds the distance transforms
    // Order: agriculture (bottom), roads, small built-up, large built-up (top)
    map.addLayer(agriculture.selfMask(), getVisParams('#b38f00'), 'Input: Agriculture',   visibleLayers.inputAgriculture, 0.9);
    map.addLayer(roadsSmall.selfMask(),   getVisParams('#993d00'), 'Input: Roads',         visibleLayers.inputRoads,       0.9);
    map.addLayer(builtUpSmall.selfMask(), getVisParams('#800080'), 'Input: Small Built-up',visibleLayers.inputBuiltupSmall,0.9);
    if (builtUpLarge) {
      map.addLayer(builtUpLarge.selfMask(), getVisParams('#1a1a80'), 'Input: Large Built-up',visibleLayers.inputBuiltupLarge, 0.9);
    }

  ///////////////
    
    
    
    // Combine buffers (only include enabled ones)
    var activeBuffers = [];
    if (enableRoadsBuffer.getValue()) activeBuffers.push(buffer_from_road_small);
    if (enableBuiltUpSmallBuffer.getValue()) activeBuffers.push(buffer_from_built_up_small);
    if (enableBuiltUpLargeBuffer.getValue()) activeBuffers.push(buffer_from_built_up_large);
    if (enableAgriBuffer.getValue()) activeBuffers.push(buffer_from_agriculture);
    // Fallback: if nothing enabled, use an empty (all-zero) buffer
    var buffer_from_anthro = activeBuffers.length > 0
        ? ee.ImageCollection(activeBuffers).reduce(ee.Reducer.anyNonZero())
        : ee.Image(0);


    var all_edge_effects = buffer_from_anthro.unmask()//.or(buffer_from_otherNatural.unmask());
    // var all_edge_effects = buffer_from_anthro.unmask().or(buffer_from_otherNatural.unmask());
    
    // Slope analysis (with caching)
    // Calculate slope only once per country, then reuse with different thresholds
    var slopeAreasToKeep;
    if (useCustomSlopeCheckbox.getValue() && customSlopeInput.getValue()) {
      // National slope raster (0-90°): apply threshold directly
      slopeAreasToKeep = ee.Image(customSlopeInput.getValue()).updateMask(country_and_buffer_mask).gt(slopeToKeepValue);
    } else {
      if (!cachedState.slopeImage || cachedState.country !== selectedCountry) {
        var alos_30m_elev = ee.ImageCollection('JAXA/ALOS/AW3D30/V3_2').select('DSM');
        cachedState.slopeImage = calculateSlope(alos_30m_elev, country_and_buffer_mask);
      }
      slopeAreasToKeep = cachedState.slopeImage.gt(slopeToKeepValue);
    }
    
    if (enableSlope.getValue())
      map.addLayer(slopeAreasToKeep.selfMask(), {palette: '#8B4513'}, 'Input: Slope > ' + slopeToKeepValue + '°', visibleLayers.slope, 0.5);
    
    // Protected areas analysis (using cached category masks)
    var wdpaYearCutoff = current_year - years_protected;
    var wdpa_filt_by_date_image = wdpaStatusYearGlobal.lte(wdpaYearCutoff);
    
    // Apply category mask if not using all categories
    if (selected_iucn_categories.length > 0 && selected_iucn_categories.length < 10) {
      var combinedCategoryMask = ee.Image(0);
      for (var i = 0; i < selected_iucn_categories.length; i++) {
        combinedCategoryMask = combinedCategoryMask.or(wdpaCategoryMasks[selected_iucn_categories[i]]);
      }
      wdpa_filt_by_date_image = wdpa_filt_by_date_image.updateMask(combinedCategoryMask);
    }
    
    wdpa_filt_by_date_image = wdpa_filt_by_date_image.selfMask().updateMask(country_and_buffer_mask);

    // Merge national protected areas with WDPA
    if (nationalProtected.checkbox.getValue()) {
      var natProtectedAsset = nationalProtected.getAsset(analysisYear);
      if (natProtectedAsset) {
        var natProtected = preprocessAsset(natProtectedAsset, nationalProtected.getPreprocessingConfig()).updateMask(country_and_buffer_mask);
        if (nationalProtected.modeSelect.getValue() === 'Replace global') {
          wdpa_filt_by_date_image = natProtected;
        } else {
          wdpa_filt_by_date_image = wdpa_filt_by_date_image.unmask(0).or(natProtected).selfMask();
        }
      }
    }
    
    var wdpaLabel = 'Input: Protected Areas (≤' + wdpaYearCutoff + ', ' +
      (selected_iucn_categories.length === 10 ? 'All' : selected_iucn_categories.join(', ')) + ')';
    if (enableProtectedAreas.getValue())
      map.addLayer(wdpa_filt_by_date_image, {palette: '#00cccc'}, wdpaLabel, visibleLayers.protectedAreas, 0.5);
    
    // Add forest layer AFTER slope and WDPA so it appears above them
    if (useHansenTreecover) {
      // Determine which map this is
      var mapName = (map === map1) ? 'map1' : 'map2';
      var hansenLayer = (map === map1) ? hansenLayer1 : hansenLayer2;
      
      // Store forest data for later zoom updates
      currentForestData[mapName] = {
        forest_map_clip: forest_map_clip,
        analysisYear: analysisYear,
        country_sel: country_sel
      };
      
      // Add the Hansen layer to the map if not already added
      var layers = map.layers();
      var layerExists = false;
      for (var i = 0; i < layers.length(); i++) {
        if (layers.get(i) === hansenLayer) {
          layerExists = true;
          break;
        }
      }
      if (!layerExists) {
        map.layers().add(hansenLayer);
      }
      
      // Initial render with current zoom
      updateHansenLayer(map, mapName, hansenLayer);
      
    } else {
      var forestLayerName = includePlantationsCheckbox.getValue() ? "Input: Forest (excl. plantations)" : "Input: Forest";
      map.addLayer(forest_map_clip.selfMask(), binary_lightgreen_palette, forestLayerName, visibleLayers.forest, 1);
    }
    
    // Decision tree
    var step_1_1 = generateOutcomeMaps(forest_map_clip, all_edge_effects);
    var forest_map_1_1_y = step_1_1.yes;  // inside buffers
    var forest_map_1_1_n = step_1_1.no;   // outside buffers

    // Step 1.2: slope rescue (optional)
    var forest_map_1_2_y, forest_map_1_2_n;
    if (enableSlope.getValue()) {
      var step_1_2 = generateOutcomeMaps(forest_map_1_1_y, slopeAreasToKeep);
      forest_map_1_2_y = step_1_2.yes;  // steep slope rescue
      forest_map_1_2_n = step_1_2.no;   // not rescued by slope
    } else {
      forest_map_1_2_y = forest_map_1_1_y.updateMask(ee.Image(0)); // empty — no rescue
      forest_map_1_2_n = forest_map_1_1_y; // all go to next step
    }

    // Step 1.3: protected area rescue (optional)
    var forest_map_1_3_y, forest_map_1_3_n;
    if (enableProtectedAreas.getValue()) {
      var step_1_3 = generateOutcomeMaps(forest_map_1_2_n, wdpa_filt_by_date_image);
      forest_map_1_3_y = step_1_3.yes;  // protected rescue
      forest_map_1_3_n = step_1_3.no;   // not rescued
    } else {
      forest_map_1_3_y = forest_map_1_2_n.updateMask(ee.Image(0)); // empty — no rescue
      forest_map_1_3_n = forest_map_1_2_n;
    }

    // Combine outcomes
    var combined_map = forest_map
      .where(forest_map_1_1_y.mask(), 1)
      .where(forest_map_1_1_n.mask(), 2)
      .where(forest_map_1_2_y.mask(), 3)
      .where(forest_map_1_2_n.mask(), 4)
      .where(forest_map_1_3_y.mask(), 5)
      .where(forest_map_1_3_n.mask(), 6)
      .where(forest_map.eq(0), 0);

    // Primary forest identification
    var all_forest_1_1_to_1_3 = combined_map.eq(2).or(combined_map.eq(3)).or(combined_map.eq(5));
      map.addLayer(all_forest_1_1_to_1_3.selfMask(), binary_green_palette, "Forest outside buffers", visibleLayers.forestOutsideBuffers, 1);

    // Large forest patches (connectivity filtering)
    var largeForestPatches;
    if (enableRefineOutput.getValue()) {
      var density = all_forest_1_1_to_1_3.reduceNeighborhood({
        reducer: ee.Reducer.sum(),
        kernel: ee.Kernel.circle({radius: smoothRadiusForest, units: 'meters'}),
        skipMasked: false,
      });
      largeForestPatches = density.gt(smallPixelThresholdForest).updateMask(all_forest_1_1_to_1_3);
    } else {
      // Skip refinement — all pre-connectivity forest becomes primary
      largeForestPatches = all_forest_1_1_to_1_3;
    }
      map.addLayer(largeForestPatches.selfMask(), {palette: 'darkgreen'}, 'Primary Forest', visibleLayers.primaryForest, 1);

    // Additional datasets 
    
    //for comparison / verification
    
    // //forest landsacpe integrity index (with threshold)
    // //FLII scores range from 0 (lowest integrity) to 10 (highest). We discretized this range to define three broad illustrative categories: low (≤6.0); medium (>6.0 and <9.6); and high integrity (≥9.6) 
    var flii = ee.Image("users/openforisearthmap/World_EarthMap/flii_earth_20190824");
    var low = 6.0, high = 9.6;
    
    var flii_class = flii.expression(
      "(b1 > low) ? ((b1 < high) ? 2 : 3) : 0", {b1: flii, low: low, high: high}
    )
    .updateMask(country_and_buffer_mask).selfMask();
    //.clip(country_buffer)
      map.addLayer(flii_class, {min: 2, max: 3, palette: ["orange", "blue"]}, "Reference: FLII (high/med)", visibleLayers.flii, 1);
    
    var forestPersistence = ee.Image("projects/forestdatapartnership/assets/community_forests/ForestPersistence_2020")
        .updateMask(country_and_buffer_mask).selfMask();

    map.addLayer(forestPersistence.gt(.90), {min: 0, max: 1, palette: ["white", "blue"]},"Reference: Forest Persistence (FDaP)",0,1); //v0 2020 (Threshold:0.9)


    //european primary forests database    
    // var epfd_2018_polys = ee.FeatureCollection("HU_BERLIN/EPFD/V2/polygons");
    // var epfd_2018_image = ee.Image(0).paint(epfd_2018_polys, 1).int8().selfMask();
    // map.addLayer(epfd_2018_image.updateMask(country_and_buffer_mask),{min:0, max:1, palette:["brown"]}, "EPFD 2018", 0, 1);

    // Area calculations - store for later stats button
    var masked_forest = forest_map_clip.updateMask(country_clip);
    var masked_primary_forest = largeForestPatches.updateMask(country_clip);
    
    // Store forest data for statistics (accessed by "Show Area Statistics" button)
    latestMaskedForest[analysisYear] = masked_forest;
    latestMaskedPrimaryForest[analysisYear] = masked_primary_forest;
    latestPreConnectivityForest[analysisYear] = all_forest_1_1_to_1_3.updateMask(country_clip);
    latestTier1Undisturbed[analysisYear] = forest_map_1_1_n.updateMask(country_clip);
    latestTier2Steep[analysisYear] = forest_map_1_2_y.updateMask(country_clip);
    latestTier3Protected[analysisYear] = forest_map_1_3_y.updateMask(country_clip);
  }
  
  // print('Cached distance keys:', Object.keys(cachedState.distanceImages));
  
  // Add layers to maps
  if (useSplitScreen) {
    addLayersToMap(map1, analysisYear1);
    addLayersToMap(map2, analysisYear2);
  } else {
    // Single map mode - only render map2
    addLayersToMap(map2, analysisYear2);
  }
  
  // Always print current centers at end for debugging
  if (map1) logCenterExplicit('map1 final', map1Center, map1Zoom);
  if (map2) logCenterExplicit('map2 final', map2Center, map2Zoom);
  
  // Update previous state
  previousState.country = selectedCountry;
  previousState.splitScreen = useSplitScreen;
  previousCountry = selectedCountry;
}

// Initial map update
updateMap();
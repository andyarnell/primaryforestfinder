// Primary Forest Finder App

// AIM: run decision tree for primary forest delineation 


var latestMaskedForest = {};
var latestMaskedPrimaryForest = {};
var latestAnalysisYear = null;

//distance buffer calculations when need to only (faster refresh when only changing slider vals)
var useCachingCheckbox = true

// Static GAUL LUT — eliminates blocking .getInfo() at startup
var gaulLut = require("users/andyarnellgee/apps:modules/gaulLut.js");
var country_names = gaulLut.country_names;     // pre-sorted, no server call

// GAUL 2024 boundaries (replaces LSIB)
var countries = ee.FeatureCollection("projects/sat-io/open-datasets/FAO/GAUL/GAUL_2024_L0");
var property_name = "gaul0_name"
var default_country_selection = "Canada" //"Cote d'Ivoire";
var country_buffer_threshold = 2000

//distance thresholds
var neighborhoodSize = 170 // 167 is about 5km at 30m resolution (30*167 = 5010)

var maxForAllDistances = 5100 // don't run any distance calcs over this distance (m) 
var roadSizeThreshold = 750 
var years_protected_1_3 = 30; 
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
  distanceImages: {}
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

///to fix toggle shoukd work with

function toggleTreecoverSlider(value) {
  treecoverThresholdSlider.style().set('shown', value);
}

///to fix toggle shoukd work with
function toggleTreecoverHeightThresholdSlider(value) {
  treecoverHeightThresholdSlider.style().set('shown', value);
}


// UI setup
var years = [2000,2010, 2015, 2020];
// var years = [1990, 2000, 2010, 2015, 2020];

var yearSelector1 = ui.Select({items: years.map(String), value: '2000', onChange: updateMap});
var yearSelector2 = ui.Select({items: years.map(String), value: '2020', onChange: updateMap});
var treecoverThresholdSlider = ui.Slider({min: 0, max: 100, value: 10, step: 5, onChange: updateMap});
var treecoverHeightThresholdSlider = ui.Slider({min: 3, max: 25, value: 5, step: 1, onChange: updateMap});

var roadSmallBufferSlider = ui.Slider({min: 0, max: 5000, value: 1000, step: 50, onChange: updateMap});
var roadLargeBufferSlider = ui.Slider({min: 0, max: 5000, value: 1500, step: 50, onChange: updateMap});
var builtUpSmallBufferSlider = ui.Slider({min: 0, max: 5000, value: 1000, step: 50, onChange: updateMap});
var builtUpLargeBufferSlider = ui.Slider({min: 0, max: 5000, value: 2000, step: 50, onChange: updateMap});
var agriBufferSlider = ui.Slider({min: 0, max: 5000, value: 1000, step: 50, onChange: updateMap});
var slopeToKeepSlider = ui.Slider({min: 0, max: 90, value: 45, step: 5, onChange: updateMap});

var onTheFlyStatsRes = 900 // resolution for simple stats calculations

// var otherNatBufferSlider = ui.Slider({min: 0, max: 5000, value: 100, step: 50, onChange: updateMap});
var countrySelector = ui.Select({items: country_names, value: default_country_selection, onChange: updateMap});

  
// Cache for country hex grids
var countryHexGridCache = {};

function processForestAreaStats(image, name, year, scale, exportToDrive, country, panel) {
  var pixelArea = ee.Image.pixelArea();
  var forestArea = image.multiply(pixelArea);

  // Use the country from parameter or global
  var countryName = country || selectedCountry;
  // Use cache for country hex grid
  if (!countryHexGridCache[countryName]) {
    var country_features = countries.filter(ee.Filter.eq(property_name, countryName));
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
        var formattedResultKm2 = Number(result / 1e6).toFixed(2);
        var formattedResult1000ha = Number(result / 1e7).toFixed(2);
        msg = "✓ " + name + " (" + year + "): " + formattedResultKm2 + " sq km (" + formattedResult1000ha + " x 1,000 ha)";
      } else {
        msg = "✗ " + name + " (" + year + "): No valid data / processing timeout";
      }
      if (panel) {
        panel.add(ui.Label(msg));
      } else {
        print(msg);
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
      'Stats resolution (m)': scale,
      "Treecover Threshold (%)": isHansen ? treecoverThresholdSlider.getValue() : '',
      'GLAD Treecover Height (m)': isGlad ? treecoverHeightThresholdSlider.getValue() : '',
      "Road Small Buffer (m)": roadSmallBufferSlider.getValue(),
      "Road Large Buffer (m)": roadLargeBufferSlider.getValue(),
      "Built-Up Small Buffer (m)": builtUpSmallBufferSlider.getValue(),
      "Built-Up Large Buffer (m)": builtUpLargeBufferSlider.getValue(),
      "Agriculture Buffer (m)": agriBufferSlider.getValue(),
      // "Other Natural Buffer (m)": otherNatBuffer,
      "Slope to Keep": slopeToKeepSlider.getValue(),
      // "Slope Threshold (%)": ,
      "Years Protected": years_protected_1_3,
      // "Fast Buffer Used": fastBuffer ? "Yes" : "No",
      "Strict IUCN Categories": selected_iucn_categories.join(", ")
    });
    
    Export.table.toDrive({
      collection: ee.FeatureCollection([feature]),
      description: "Area_" + name.replace(/\s+/g, "_") + "_" + year + "_" + 
                  cleanCountryName(countryName) + "_" + scale + "m",
      fileFormat: "CSV"
    });
  }
}


var showStatsButton = ui.Button({
  label: 'Show Area Statistics',
  style: {stretch: 'horizontal', margin: '8px 0', fontWeight: 'bold'},
  onClick: function() {
    areaStatsPanel.clear();
    if (Object.keys(latestMaskedForest).length === 0) {
      areaStatsPanel.add(ui.Label('No forest data available. Please wait for the map to load first.'));
      return;
    }
    var selectedCountry = countrySelector.getValue();
    areaStatsPanel.add(ui.Label('═════════════════════════════════════════'));
    areaStatsPanel.add(ui.Label('CALCULATING AREA STATISTICS'));
    areaStatsPanel.add(ui.Label('Country: ' + selectedCountry));
    areaStatsPanel.add(ui.Label('═════════════════════════════════════════'));
    Object.keys(latestMaskedForest).forEach(function(year) {
      var yearInt = parseInt(year);
      areaStatsPanel.add(ui.Label('--- Year: ' + year + ' ---'));
      processForestAreaStats(latestMaskedForest[year], "Total Treecover", yearInt, onTheFlyStatsRes, false, selectedCountry, areaStatsPanel);
      if (latestMaskedPrimaryForest[year]) {
        processForestAreaStats(latestMaskedPrimaryForest[year], "Primary Forest", yearInt, onTheFlyStatsRes, false, selectedCountry, areaStatsPanel);
      }
    });
    areaStatsPanel.add(ui.Label('Results will appear below (NB estimated at '+onTheFlyStatsRes+'m resolution)'));
    areaStatsPanel.add(ui.Label('═════════════════════════════════════════'));
  }
});



// Panel to display area statistics results (must be defined before showStatsButton)
var areaStatsPanel = ui.Panel({
  layout: ui.Panel.Layout.flow('vertical'),
  style: {margin: '8px 0', padding: '8px', backgroundColor: '#f7f7f7', border: '1px solid #ccc'}
});

// Button to clear the area statistics panel
var clearStatsButton = ui.Button({
  label: 'Clear Results',
  style: {margin: '0 0 6px 0', backgroundColor: '#eee'},
  onClick: function() {
    areaStatsPanel.clear();
  }
});




// Slider for export statistics scale
var exportStatsScaleSlider = ui.Slider({
  min: 30, max: 2000, value: 900, step: 30,
  style: {margin: '0 0 6px 0', width: '120px'},
  onChange: function() {}
});
var exportStatsScaleLabel = ui.Label('Export Scale (m):', {margin: '0 8px 0 0'});

// Label for export status message
var exportStatusLabel = ui.Label('', {margin: '4px 0 0 0'});

// Button to export statistics as CSV
var exportStatsButton = ui.Button({
  label: 'Export Statistics to Drive',
  style: {margin: '0 0 6px 0', backgroundColor: '#e0ffe0'},
  onClick: function() {
    exportStatusLabel.setValue('');
    if (Object.keys(latestMaskedForest).length === 0) {
      exportStatusLabel.setValue('No forest data to export.');
      return;
    }
    var selectedCountry = countrySelector.getValue();
    var exportScale = exportStatsScaleSlider.getValue();
    Object.keys(latestMaskedForest).forEach(function(year) {
      var yearInt = parseInt(year);
      processForestAreaStats(latestMaskedForest[year], "Total Treecover", yearInt, exportScale, true, selectedCountry);
      if (latestMaskedPrimaryForest[year]) {
        processForestAreaStats(latestMaskedPrimaryForest[year], "Primary Forest", yearInt, exportScale, true, selectedCountry);
      }
    });
    exportStatusLabel.setValue('Exported started: Check the Tasks tab to download your CSV(s).');
  }
});

// Panel to hold export button on top, scale label and slider below
var exportStatsPanel = ui.Panel({
  widgets: [
    exportStatsButton,
    ui.Panel([exportStatsScaleLabel, exportStatsScaleSlider], ui.Panel.Layout.flow('horizontal'))
  ],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {margin: '6px 0 0 0'}
});

// var countrySelector = ui.Select({
//   items: [''].concat(country_names),  // Add an empty option at the top
//   placeholder: 'Select a country',
//   onChange: updateMap
// });


var smoothRadiusForestSlider = ui.Slider({min: 0, max: 5000, value: 2000, step: 500, onChange: updateMap});
var smallPixelThresholdForestSlider = ui.Slider({min: 0, max: 1, value: 0.5, step: 0.1, onChange: updateMap});

// Checkboxes
var zoomToCountryCheckbox = ui.Checkbox({label: 'Zoom to Country', value: true, onChange: updateMap});
// var fastBufferCheckbox = ui.Checkbox({label: 'Use accurate distance buffers', value: true, onChange: updateMap});
// var includeGISDCheckbox = ui.Checkbox({label: 'Include built up: GISD', value: true, onChange: updateMap});
// var includeGISACheckbox = ui.Checkbox({label: 'Include built up:  GISA', value: true, onChange: updateMap});
// var includeWSFCheckbox = ui.Checkbox({label: 'Include built up:  WSF', value: true, onChange: updateMap});
// var includeGHSLCheckbox = ui.Checkbox({label: 'Include built up: GHSL', value: true, onChange: updateMap});



// Treecover threshold panels (must be defined before dropdown logic)
var treecoverPanel = ui.Panel({
  widgets: [
    ui.Label('GFC Treecover Threshold (%)'),
    treecoverThresholdSlider
  ],
  layout: ui.Panel.Layout.flow('vertical')
});
treecoverPanel.style().set('shown', false);

var treecoverHeightPanel = ui.Panel({
  widgets: [
    ui.Label('GLAD Treecover Height (m)'),
    treecoverHeightThresholdSlider
  ],
  layout: ui.Panel.Layout.flow('vertical')
});
treecoverHeightPanel.style().set('shown', true);

// Dropdown for treecover source
var treecoverSourceSelect = ui.Select({
  items: ['Hansen GFC', 'GLAD LULC'],
  value: 'GLAD LULC',
  onChange: function(value) {
    if (value === 'Hansen GFC') {
      treecoverPanel.style().set('shown', true);
      treecoverHeightPanel.style().set('shown', false);
    } else {
      treecoverPanel.style().set('shown', false);
      treecoverHeightPanel.style().set('shown', true);
    }
    updateMap();
  }
});

// Initialize both sliders based on dropdown value (GLAD is default, so hide Hansen slider)
treecoverPanel.style().set('shown', false);
treecoverHeightPanel.style().set('shown', true);



// Custom forest asset input components
var forestAssetInputs = {};
var forestAssetPanel = ui.Panel({
  style: {
    margin: '10px 0px',
    padding: '6px',
    border: '1px solid #ccc',
    backgroundColor: '#f8f9fa'
  }
});

// Add a label and checkbox to toggle custom assets
var useCustomAssetsCheckbox = ui.Checkbox({
  label: 'Use custom forest assets',
  value: false,
  onChange: function(checked) {
    forestAssetPanel.style().set('shown', checked);
    updateMap();
    // debouncedUpdateMap();
  }
});

// Create text input for each year
forestAssetPanel.add(ui.Label('Enter custom forest asset IDs (ee.Image with 0=non-forest, 1=forest):'));

years.forEach(function(year) {
  var yearPanel = ui.Panel({
    layout: ui.Panel.Layout.flow('horizontal'),
    style: {margin: '4px 0px'}
  });
  
  yearPanel.add(ui.Label('Year ' + year + ':', {width: '80px'}));
  
  var assetInput = ui.Textbox({
    placeholder: 'users/username/forestAsset_' + year,
    // onChange: debouncedUpdateMap,
    onChange: updateMap,
    
    style: {width: '200px'}
  });
  
  forestAssetInputs[year] = assetInput;
  yearPanel.add(assetInput);
  forestAssetPanel.add(yearPanel);
});

// Hide asset panel initially
forestAssetPanel.style().set('shown', false);


var treecoverPanel = ui.Panel({
  widgets: [
    ui.Label('GFC Treecover Threshold (%)'),
    treecoverThresholdSlider
  ],
  layout: ui.Panel.Layout.flow('vertical')
});

var treecoverHeightPanel = ui.Panel({
  widgets: [
    ui.Label('GLAD Treecover Height (m)'),
    treecoverHeightThresholdSlider
  ],
  layout: ui.Panel.Layout.flow('vertical')
});




// Control panel
var controlPanel = ui.Panel({
  widgets: [
    ui.Label({
      value: 'Primary Forest Finder',
      style: {
        fontSize: '22px',
        fontWeight: 'bold',
        textAlign: 'center',
        stretch: 'horizontal',
        margin: '10px 0px'
      }
    }),
    ui.Label('Select Country:'), countrySelector, zoomToCountryCheckbox,// fastBufferCheckbox,
    ui.Label('Select Year 1:'), yearSelector1, ui.Label('Select Year 2:'), yearSelector2,

    // Move treecover section here
    ui.Label('Treecover Source:'),
    treecoverSourceSelect,
    treecoverPanel,
    treecoverHeightPanel,

    // ...existing code...
    ui.Label('Road Small Buffer (m):'), roadSmallBufferSlider, 
    ui.Label('Road Large Buffer (m):'), roadLargeBufferSlider,
    ui.Label('Built-Up Small Buffer (m):'), builtUpSmallBufferSlider, 
    ui.Label('Built-Up Large Buffer (m):'), builtUpLargeBufferSlider,
    ui.Label('Agriculture Buffer (m):'), agriBufferSlider, 
    ui.Label('Slope to keep (degrees)'),slopeToKeepSlider,
    // ui.Label('Other Natural Buffer (m):'), otherNatBufferSlider,
    ui.Label('Connectivity: Forest Smoothing Radius (m):'), smoothRadiusForestSlider,
    ui.Label('Connectivity: Forest Smoothing Threshold:'), smallPixelThresholdForestSlider,
  // includeGISDCheckbox, includeGISACheckbox, includeWSFCheckbox, includeGHSLCheckbox,

    useCustomAssetsCheckbox,
    forestAssetPanel
  ],
  style: {width: '300px'}
});

// Add custom asset controls to panel
// controlPanel.insert(8, useCustomAssetsCheckbox);
// controlPanel.insert(9, forestAssetPanel);

// ...existing code...

controlPanel.add(showStatsButton);
controlPanel.add(clearStatsButton);
controlPanel.add(areaStatsPanel);
controlPanel.add(exportStatsPanel);
controlPanel.add(exportStatusLabel);

// Add a button to export settings
var exportSettingsButton = ui.Button({
  label: 'Export Settings',
  onClick: exportSettings
});
controlPanel.add(exportSettingsButton);

// Add a button to import settings
var importSettingsButton = ui.Button({
  label: 'Import Settings',
  onClick: showTextInput
});
controlPanel.add(importSettingsButton);

// ──────────────────────────────────────────────
// Export Rasters to Drive (for QGIS / offline use)
// ──────────────────────────────────────────────
var exportRasterScaleSlider = ui.Slider({
  min: 30, max: 1000, value: 30, step: 10,
  style: {margin: '0 0 6px 0', width: '120px'}
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
var exportRasterStatusLabel = ui.Label('', {margin: '4px 0 0 0'});

function exportRastersToDrive() {
  exportRasterStatusLabel.setValue('');

  var selectedCountry = countrySelector.getValue();
  var analysisYear1 = parseInt(yearSelector1.getValue());
  var analysisYear2 = parseInt(yearSelector2.getValue());
  var exportScale = exportRasterScaleSlider.getValue();
  var countryClean = cleanCountryName(selectedCountry);

  var country_sel = countries.filter(ee.Filter.eq(property_name, selectedCountry));
  var country_geom = country_sel.geometry();

  // Determine target CRS: UTM zone from country centroid
  var centroid = country_geom.centroid(100);
  var lon = ee.Number(centroid.coordinates().get(0));
  var utmZone = lon.add(180).divide(6).ceil().int();
  var isNorth = ee.Number(centroid.coordinates().get(1)).gte(0);
  var epsgCode = isNorth.multiply(32600).add(isNorth.not().multiply(32700)).add(utmZone);
  var targetCRS = ee.Algorithms.If(isNorth, 
    ee.String('EPSG:').cat(ee.Number(32600).add(utmZone).int().format()),
    ee.String('EPSG:').cat(ee.Number(32700).add(utmZone).int().format())
  );

  // Export region: buffer country boundary slightly for edge effects
  var exportRegion = country_geom.buffer(country_buffer_threshold + 1000);

  // Export destination: Cloud Storage (COG) or Drive (GeoTIFF)
  var useCloud = exportToCloudCheckbox.getValue();
  var gcsBucket = gcsBucketInput.getValue();
  if (useCloud && (!gcsBucket || gcsBucket.trim() === '')) {
    exportRasterStatusLabel.setValue('Please enter a GCS bucket name.');
    return;
  }

  // Shared export helper
  function doExport(image, description, folder) {
    if (useCloud) {
      Export.image.toCloudStorage({
        image: image.toByte(),
        description: description,
        bucket: gcsBucket.trim(),
        fileNamePrefix: folder + '/' + description,
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
        description: description,
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

  var uniqueYears = (analysisYear1 === analysisYear2) ? [analysisYear1] : [analysisYear1, analysisYear2];
  var folder = 'PFF_export_' + countryClean;

  // ══════════════════════════════════════════════════════
  //  STATIC layers (exported once — no time series)
  // ══════════════════════════════════════════════════════

  // Country mask + buffer (shared across years)
  var country_clip = ee.Image(1).clip(country_sel);
  var country_buffer = makeDistanceBuffer(country_clip, country_buffer_threshold, fastBuffer);
  var country_and_buffer_mask = country_buffer.where(country_clip, 1).selfMask();

  // DEM (Int16 — not binary, so call export directly)
  var alos_30m_elev = ee.ImageCollection('JAXA/ALOS/AW3D30/V3_2').select('DSM').mosaic();
  if (useCloud) {
    Export.image.toCloudStorage({
      image: alos_30m_elev.updateMask(country_and_buffer_mask).unmask(0).toInt16(),
      description: 'dem_alos30',
      bucket: gcsBucket.trim(),
      fileNamePrefix: folder + '/dem_alos30',
      region: exportRegion, scale: exportScale,
      crs: targetCRS, maxPixels: 1e13, fileFormat: 'GeoTIFF',
      formatOptions: {cloudOptimized: true}
    });
  } else {
    Export.image.toDrive({
      image: alos_30m_elev.updateMask(country_and_buffer_mask).unmask(0).toInt16(),
      description: 'dem_alos30',
      folder: folder, region: exportRegion, scale: exportScale,
      crs: targetCRS, maxPixels: 1e13, fileFormat: 'GeoTIFF',
      formatOptions: {cloudOptimized: true}
    });
  }

  // Hansen raw bands (treecover2000 + lossyear — no time series, export once)
  var gfc = ee.Image('UMD/hansen/global_forest_change_2024_v1_12');
  doExport(gfc.select('treecover2000').updateMask(country_and_buffer_mask).unmask(0),
    'hansen_treecover2000_raw', folder);
  doExport(gfc.select('lossyear').updateMask(country_and_buffer_mask).unmask(0),
    'hansen_lossyear_raw', folder);

  // Protected areas — filtered raster (default) + unfiltered vector
  var wdpa_poly = ee.FeatureCollection("WCMC/WDPA/current/polygons");
  var wdpa_filt = wdpa_poly.filter(
    ee.Filter.and(ee.Filter.neq('STATUS', 'Proposed'), 
                  ee.Filter.neq('STATUS', 'Not Reported'), 
                  ee.Filter.neq('DESIG_ENG', 'UNESCO-MAB Biosphere Reserve'))
  );
  var wdpa_filt_strict = wdpa_filt.filter(ee.Filter.inList('IUCN_CAT', selected_iucn_categories));
  var wdpa_filt_by_date = wdpa_filt_strict.filter(ee.Filter.gte('STATUS_YR', current_year - years_protected_1_3));
  var wdpa_clipped = wdpa_filt_by_date.filterBounds(exportRegion);
  var wdpa_raster = ee.Image().paint(wdpa_clipped, 1).unmask(0)
    .clip(exportRegion).toByte().rename('protected');
  doExport(wdpa_raster, 'protected_areas', folder);

  var wdpa_raw = wdpa_poly.filter(
    ee.Filter.and(ee.Filter.neq('STATUS', 'Proposed'),
                  ee.Filter.neq('STATUS', 'Not Reported'))
  ).filterBounds(exportRegion);
  if (useCloud) {
    Export.table.toCloudStorage({
      collection: wdpa_raw,
      description: 'protected_areas_wdpa_vector',
      bucket: gcsBucket.trim(),
      fileNamePrefix: folder + '/protected_areas_wdpa_vector',
      fileFormat: 'SHP'
    });
  } else {
    Export.table.toDrive({
      collection: wdpa_raw,
      description: 'protected_areas_wdpa_vector',
      folder: folder, fileFormat: 'SHP'
    });
  }

  // AOI boundary
  if (useCloud) {
    Export.table.toCloudStorage({
      collection: country_sel,
      description: 'aoi_' + countryClean,
      bucket: gcsBucket.trim(),
      fileNamePrefix: folder + '/aoi_' + countryClean,
      fileFormat: 'SHP'
    });
  } else {
    Export.table.toDrive({
      collection: country_sel,
      description: 'aoi_' + countryClean,
      folder: folder, fileFormat: 'SHP'
    });
  }

  // ══════════════════════════════════════════════════════
  //  PER-YEAR layers (for each selected year)
  // ══════════════════════════════════════════════════════

  var treecoverPercentThreshold = treecoverThresholdSlider.getValue();
  var treecoverHeightThreshold = treecoverHeightThresholdSlider.getValue();
  var useHansenTreecover = (treecoverSourceSelect.getValue() === 'Hansen GFC');
  var useGladLulcForest = (treecoverSourceSelect.getValue() === 'GLAD LULC');
  var timeseriesAnthroModule = require("users/andyarnellgee/apps:modules/timeseriesAnthro.js");

  uniqueYears.forEach(function(analysisYear) {

    // ── Forest (as configured in the app) ──
    var forest_map;
    if (useCustomAssetsCheckbox.getValue() && 
        forestAssetInputs[analysisYear] && 
        forestAssetInputs[analysisYear].getValue()) {
      forest_map = ee.Image(forestAssetInputs[analysisYear].getValue());
    } else if (useGladLulcForest) {
      forest_map = gladLulcForestPrep(analysisYear, treecoverHeightThreshold);
    } else if (useHansenTreecover) {
      forest_map = gfcHansenTreecoverPrep(analysisYear, treecoverPercentThreshold);
    }
    if (!forest_map) {
      exportRasterStatusLabel.setValue('No forest data selected.');
      return;
    }
    doExport(forest_map.updateMask(country_and_buffer_mask).unmask(0),
      'forest_' + analysisYear, folder);

    // GLAD raw tree height (so user can re-threshold at any height in QGIS)
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
    doExport(gladTreeHeight, 'glad_tree_height_m_' + analysisYear, folder);

    // ── Roads ──
    var roadsMosaicStatic = timeseriesAnthroModule.roadsMosaicStatic().updateMask(country_and_buffer_mask);
    var roadsCollection = timeseriesAnthroModule.getRoadsCollection();
    var roadsSel = roadsCollection.filter(ee.Filter.eq('year', analysisYear)).first().updateMask(country_and_buffer_mask);
    var roadsSmall = roadsSel.lte(roadSizeThreshold).unmask().or(roadsMosaicStatic);
    var roadsLarge = roadsSel.gt(roadSizeThreshold);
    doExport(roadsSmall.unmask(0), 'roads_minor_' + analysisYear, folder);
    doExport(roadsLarge.unmask(0), 'roads_major_' + analysisYear, folder);

    // ── Built-up ──
    var builtUpSmall = ee.Image(0);
    if (includeWSF) {
      var wsfCollection = timeseriesAnthroModule.getWSFCollection();
      builtUpSmall = builtUpSmall.or(wsfCollection.filter(ee.Filter.eq('year', analysisYear)).first().eq(1)).updateMask(country_and_buffer_mask);
    }
    var builtUpLargeImg = ee.Image(0);
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
    var builtUpCombined = builtUpSmall.unmask().or(builtUpLargeImg.unmask());
    doExport(builtUpCombined.updateMask(country_and_buffer_mask).unmask(0),
      'builtup_' + analysisYear, folder);

    // ── Agriculture ──
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
    var croplandGladCollection = timeseriesAnthroModule.processingCroplandsGlad();
    var croplandGladCollectionFF = forwardFillBinaryTimeSeries(croplandGladCollection, years);
    var croplandGladSel = ee.Image(croplandGladCollectionFF.filter(ee.Filter.eq("year", analysisYear)).first()).updateMask(country_and_buffer_mask);
    var agriculture = pastureDatasetSel.or(allPlantationsSel.unmask()).or(croplandGladSel);
    doExport(agriculture.unmask(0), 'agriculture_' + analysisYear, folder);
  });

  var yearStr = uniqueYears.join(' & ');
  var destStr = useCloud ? 'gs://' + gcsBucket.trim() + '/' + folder : 'Google Drive → ' + folder;
  exportRasterStatusLabel.setValue(
    'Export tasks queued for ' + countryClean + ' (' + yearStr + ') → ' + destStr + '. Check the Tasks tab to run them.');
}

var exportRastersButton = ui.Button({
  label: 'Export Rasters to Drive (for QGIS)',
  style: {stretch: 'horizontal', margin: '8px 0', fontWeight: 'bold', backgroundColor: '#d4edda'},
  onClick: exportRastersToDrive
});

controlPanel.add(ui.Label('─────────────────────────────'));
controlPanel.add(exportRastersButton);
controlPanel.add(ui.Panel([
  ui.Label('Export Scale (m):', {margin: '0 8px 0 0'}),
  exportRasterScaleSlider
], ui.Panel.Layout.flow('horizontal')));
controlPanel.add(exportToCloudCheckbox);
controlPanel.add(ui.Panel([
  ui.Label('GCS Bucket:', {margin: '0 8px 0 0'}),
  gcsBucketInput
], ui.Panel.Layout.flow('horizontal')));
controlPanel.add(exportRasterStatusLabel);

// Variable to keep track of the download link panel
var downloadLinkPanel;


// Add a loading label
var loadingLabel = ui.Label({
  value: 'Loading...',
  style: {color: 'red', fontWeight: 'bold', shown: false}
});
ui.root.add(loadingLabel);

// Function to collect current settings
function collectSettings() {
  var settings = {
    'Country': countrySelector.getValue(),
    'Year 1': yearSelector1.getValue(),
    'Year 2': yearSelector2.getValue(),
    'Treecover Threshold (%)': treecoverThresholdSlider.getValue(),
    'GLAD Treecover Height (m)': treecoverHeightThresholdSlider.getValue(),
    'Road Small Buffer (m)': roadSmallBufferSlider.getValue(),
    'Road Large Buffer (m)': roadLargeBufferSlider.getValue(),
    'Built-Up Small Buffer (m)': builtUpSmallBufferSlider.getValue(),
    'Built-Up Large Buffer (m)': builtUpLargeBufferSlider.getValue(),
    'Slope to keep (degrees)': slopeToKeepSlider.getValue(),
    'Agriculture Buffer (m)': agriBufferSlider.getValue(),
    // 'Other Natural Buffer (m)': otherNatBufferSlider.getValue(),
    'Forest Smoothing Radius (m)': smoothRadiusForestSlider.getValue(),
    'Forest Smoothing Threshold': smallPixelThresholdForestSlider.getValue(),
    'Zoom to Country': zoomToCountryCheckbox.getValue(),
    // 'Use Accurate Distance Buffers': fastBufferCheckbox.getValue(),
    // 'Include GISD': includeGISDCheckbox.getValue(),
    // 'Include GISA': includeGISACheckbox.getValue(),
    // 'Include WSF': includeWSFCheckbox.getValue(),
    // 'Include BuiltUp': includeGHSLCheckbox.getValue(),
  'Use Hansen (GFC) Tree Cover': (treecoverSourceSelect.getValue() === 'Hansen GFC'),
  'Use GLAD LULC Forest': (treecoverSourceSelect.getValue() === 'GLAD LULC'),
    'Use Custom Forest Assets': useCustomAssetsCheckbox.getValue()
  };

  // Add custom forest asset inputs if used
  if (useCustomAssetsCheckbox.getValue()) {
    years.forEach(function(year) {
      var assetInputValue = forestAssetInputs[year].getValue();
      if (assetInputValue) {
        settings['Custom Forest Asset ' + year] = assetInputValue;
      }
    });
  }

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
  roadLargeBufferSlider.setValue(settings['Road Large Buffer (m)']);
  builtUpSmallBufferSlider.setValue(settings['Built-Up Small Buffer (m)']);
  builtUpLargeBufferSlider.setValue(settings['Built-Up Large Buffer (m)']);
  agriBufferSlider.setValue(settings['Agriculture Buffer (m)']);
  slopeToKeepSlider.setValue(settings['Slope to keep (degrees)']);
  // otherNatBufferSlider.setValue(settings['Other Natural Buffer (m)']);
  smoothRadiusForestSlider.setValue(settings['Forest Smoothing Radius (m)']);
  smallPixelThresholdForestSlider.setValue(settings['Forest Smoothing Threshold']);
  zoomToCountryCheckbox.setValue(settings['Zoom to Country']);
  // fastBufferCheckbox.setValue(settings['Use Accurate Distance Buffers']);
  // includeGISDCheckbox.setValue(settings['Include GISD']);
  // includeGISACheckbox.setValue(settings['Include GISA']);
  // includeWSFCheckbox.setValue(settings['Include WSF']);
  // includeGHSLCheckbox.setValue(settings['Include BuiltUp']);
  if (settings['Use Hansen (GFC) Tree Cover']) {
    treecoverSourceSelect.setValue('Hansen GFC');
  } else if (settings['Use GLAD LULC Forest']) {
    treecoverSourceSelect.setValue('GLAD LULC');
  }
  
  useCustomAssetsCheckbox.setValue(settings['Use Custom Forest Assets']);

  if (settings['Use Custom Forest Assets']) {
    years.forEach(function(year) {
      if (settings['Custom Forest Asset ' + year]) {
        forestAssetInputs[year].setValue(settings['Custom Forest Asset ' + year]);
      }
    });
  }

  updateMap();
}

// ...existing code...

///////existing cdoe

ui.root.insert(0, controlPanel);

// Create maps
var map1 = ui.Map(), map2 = ui.Map();



map1.setControlVisibility(false);
map2.setControlVisibility(false);


var splitPanel = ui.SplitPanel({
  firstPanel: map1, secondPanel: map2, orientation: 'horizontal', wipe: true
});


ui.root.widgets().reset([splitPanel, controlPanel]);

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

// CRITICAL FIX: Add zoom listeners to BOTH maps before linking
// The linker synchronizes zoom but individual listeners still need to be set
map1.onChangeZoom(function() {
  updateHansenLayer(map1, 'map1', hansenLayer1);
});

map2.onChangeZoom(function() {
  updateHansenLayer(map2, 'map2', hansenLayer2);
});

// Link the maps AFTER setting up zoom listeners
var linker = ui.Map.Linker([map1, map2]);

// WORKAROUND: Linked maps may not fire zoom change events reliably
// Poll for zoom changes as backup
var lastZoom = {map1: null, map2: null};
ui.util.setInterval(function() {
  if (treecoverSourceSelect.getValue() !== 'Hansen GFC') return;
  
  var z1 = map1.getZoom();
  var z2 = map2.getZoom();
  
  if (z1 !== lastZoom.map1 && currentForestData.map1.forest_map_clip) {
    lastZoom.map1 = z1;
    updateHansenLayer(map1, 'map1', hansenLayer1);
  }
  
  if (z2 !== lastZoom.map2 && currentForestData.map2.forest_map_clip) {
    lastZoom.map2 = z2;
    updateHansenLayer(map2, 'map2', hansenLayer2);
  }
}, 500); // Check every 500ms

// updateMap() // removed to see if needed


// Main update function

function updateMap()  { 
  var analysisYear1 = parseInt(yearSelector1.getValue());
  var analysisYear2 = parseInt(yearSelector2.getValue());
  var selectedCountry = countrySelector.getValue();
  
  
  // if (!selectedCountry || selectedCountry === '') {
  //   print('Please select a country to begin.');
  //   // Map.setCenter(0, 20, 2);
  //   return;
  // }

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
  var roadLargeBuffer = roadLargeBufferSlider.getValue();
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
  var zoomToCountry = zoomToCountryCheckbox.getValue();
  // var fastBuffer = fastBufferCheckbox.getValue();
  var smoothRadiusForest = smoothRadiusForestSlider.getValue();
  var smallPixelThresholdForest = smallPixelThresholdForestSlider.getValue();

  var country_sel = countries.filter(ee.Filter.eq(property_name, selectedCountry));
  
  map1.clear();
  map2.clear();

    // Add year labels to maps
  var yearLabel1 = ui.Label({
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
  
  var yearLabel2 = ui.Label({
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
  
  map1.add(yearLabel1);
  map2.add(yearLabel2);
  
  // Apply gray map style to both maps
  map1.setOptions('Gray', {Gray: GRAYMAP});
  map2.setOptions('Gray', {Gray: GRAYMAP});
  
  // Zoom
  if (zoomToCountry === true) {
    map1.centerObject(country_sel, 6);
    map2.centerObject(country_sel, 6);
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
    if (useCustomAssetsCheckbox.getValue() && 
        forestAssetInputs[analysisYear] && 
        forestAssetInputs[analysisYear].getValue()) {
      try {
        var assetId = forestAssetInputs[analysisYear].getValue();
        forest_map = ee.Image(assetId);
        print('Using custom forest asset for ' + analysisYear + ': ' + assetId);
      } catch (e) {
        print('Error loading custom asset. Using fallback forest data.')
        e;
      }
    }
    
    // If no custom asset is set or it fails, select an alternative dataset
    if (!forest_map) {
      if (useGladLulcForest) {
        forest_map = gladLulcForestPrep(analysisYear,treecoverHeightThreshold);
        //debug print('Using GLAD LULC forest data for ' + analysisYear); 
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

    // Country mask preparation
    try{
      //var country_clip = forest_map.gte(0).clip(country_sel);//
      var country_clip = ee.Image(1).clip(country_sel);//
      
    }
    catch(e)
    { print("WARNING: No forest map selected"+ (e))
    
    }
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
    var croplandComb = croplandGladSel//.or(croplandSelLessNoise)

    var agriculture = pastureDatasetSel.or(allPlantationsSel.unmask()).or(croplandComb);

    // map.addLayer(plantationsMosaicStatic,"","plantationsMosaicStatic")

    // map.addLayer(country_and_buffer_mask,'',"country_and_buffer_mask")

    // map.addLayer(allPlantationsSel,"","allPlantationsSel")
    // map.addLayer(pastureDatasetSel,"","pastureDatasetSel")
    // map.addLayer(croplandComb,"","croplandComb")

    // Road data
    var roadsMosaicStatic = timeseriesAnthroModule.roadsMosaicStatic().updateMask(country_and_buffer_mask);
  
    // var msRoadsImage = ee.Image("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_microsoft/roadsAllImageGlobal");
    // var msRoadsImageBinary = msRoadsImage.gt(0).rename("constant")//change any width values 1 and rename
    // var roadsMosaicStatic = msRoadsImageBinary.updateMask(country_and_buffer_mask);
  
    var roadsCollection = timeseriesAnthroModule.getRoadsCollection();
    var roadsSel = roadsCollection.filter(ee.Filter.eq('year', analysisYear)).first().updateMask(country_and_buffer_mask);
    var roadsSmall = roadsSel.lte(roadSizeThreshold).unmask().or(roadsMosaicStatic);
    var roadsLarge = roadsSel.gt(roadSizeThreshold);



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
    
    
    
     
    // Check cache first before calculating distance transforms
    var dist_road_small, dist_road_large, dist_built_up_small, dist_built_up_large, dist_agriculture;
    
    
        
        
    // caching check box in addLayersToMap function
    if (useCachingCheckbox/*.getValue()*/ && cachedState.distanceImages[analysisYear + '_road_small']) {
      // Use cached distance images
      dist_road_small = cachedState.distanceImages[analysisYear + '_road_small'];
      dist_road_large = cachedState.distanceImages[analysisYear + '_road_large'];
      dist_built_up_small = cachedState.distanceImages[analysisYear + '_built_up_small'];
      dist_built_up_large = cachedState.distanceImages[analysisYear + '_built_up_large'];
      dist_agriculture = cachedState.distanceImages[analysisYear + '_agriculture'];
      //debug print('Using cached distance images for year: ' + analysisYear);
    } else {
      // Calculate distance transforms
        dist_road_small = makeDistanceSurface(roadsSmall, fastBuffer);
        dist_road_large = makeDistanceSurface(roadsLarge, fastBuffer);
        dist_built_up_small = makeDistanceSurface(builtUpSmall, fastBuffer);
        dist_built_up_large = makeDistanceSurface(ghslSel.eq(2), fastBuffer);
        dist_agriculture = makeDistanceSurface(agriculture, fastBuffer);
      
      // Only cache if caching is enabled
      if (useCachingCheckbox/*.getValue()*/) {
        cachedState.distanceImages[analysisYear + '_road_small'] = dist_road_small;
        cachedState.distanceImages[analysisYear + '_road_large'] = dist_road_large;
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
    var buffer_from_road_large = applyDistanceThreshold(dist_road_large, roadLargeBuffer);
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
        {image: buffer_from_road_small,   color: 'red',         name: 'Buffer: Small Roads'},
        {image: buffer_from_road_large,   color: 'blue',        name: 'Buffer: Large Roads'},
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
    
    // Loop through layers and add them to the map
    visParams.forEach(function(layer) {
        map.addLayer(layer.image, getVisParams(layer.color), layer.name,0,.5);
    });
    
    //add forest with zoom-dependent rendering for Hansen GFC
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
      // Standard rendering for non-Hansen datasets
      map.addLayer(forest_map_clip, binary_lightgreen_palette, "Forest", 0, 1);
    }

  ///////////////
    
    
    
    // Combine buffers
    var buffer_from_anthro = ee.ImageCollection([
        buffer_from_road_small, 
        buffer_from_road_large, 
        buffer_from_built_up_small, 
        buffer_from_built_up_large, 
        buffer_from_agriculture
    ]).reduce(ee.Reducer.anyNonZero());


    var all_edge_effects = buffer_from_anthro.unmask()//.or(buffer_from_otherNatural.unmask());
    // var all_edge_effects = buffer_from_anthro.unmask().or(buffer_from_otherNatural.unmask());
    
    // Slope analysis
    var alos_30m_elev = ee.ImageCollection('JAXA/ALOS/AW3D30/V3_2').select('DSM');
    var slopeAreasToKeep = calculateSlope(alos_30m_elev,country_and_buffer_mask).gt(slopeToKeepValue);
    
    // Protected areas analysis
    var wdpa_poly = ee.FeatureCollection("WCMC/WDPA/current/polygons");
    var wdpa_filt = wdpa_poly.filter(
      ee.Filter.and(ee.Filter.neq('STATUS', 'Proposed'), 
                    ee.Filter.neq('STATUS', 'Not Reported'), 
                    ee.Filter.neq('DESIG_ENG', 'UNESCO-MAB Biosphere Reserve'))
    );
    var wdpa_filt_strict = wdpa_filt.filter(ee.Filter.inList('IUCN_CAT', selected_iucn_categories));
    var wdpa_filt_by_date = wdpa_filt_strict.filter(ee.Filter.gte('STATUS_YR', current_year - years_protected_1_3));
    var wdpa_filt_by_date_image = ee.Image().paint(wdpa_filt_by_date, 1).updateMask(country_and_buffer_mask);
    
    // Decision tree
    var step_1_1 = generateOutcomeMaps(forest_map_clip, all_edge_effects);
    var forest_map_1_1_y = step_1_1.yes;
    var forest_map_1_1_n = step_1_1.no;
    var step_1_2 = generateOutcomeMaps(forest_map_1_1_y, slopeAreasToKeep);
    var forest_map_1_2_y = step_1_2.yes;
    var forest_map_1_2_n = step_1_2.no;
    var step_1_3 = generateOutcomeMaps(forest_map_1_2_n, wdpa_filt_by_date_image);
    var forest_map_1_3_y = step_1_3.yes;
    var forest_map_1_3_n = step_1_3.no;

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
    map.addLayer(all_forest_1_1_to_1_3.selfMask(), binary_green_palette, "Forest - outside anthropegenic buffers", 0, 1);

    // Large forest patches
    var boxcarForest = ee.Kernel.circle({radius: smoothRadiusForest, units: 'meters', normalize: true});
    var density = all_forest_1_1_to_1_3.reduceNeighborhood({
      reducer: ee.Reducer.sum(),
      kernel: ee.Kernel.circle({radius: smoothRadiusForest, units: 'meters'}),
      skipMasked: false, //by default this is true
      // optimization: 'window' // only for square or rectangle
      
    });
    
    //apply threshold to reduceNeighbourhood result 
    //and mask by input forest (i.e., all_forest_1_1_to_1_3)
    var largeForestPatches = density.gt(smallPixelThresholdForest).updateMask(all_forest_1_1_to_1_3)
    map.addLayer(largeForestPatches.selfMask()
    , {palette: 'darkgreen'}, 'Primary Forest', 1, 1);

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
    map.addLayer(flii_class, {min: 2, max: 3, palette: ["orange", "blue"]}, "Comparison: Forest landscape integrity index (FLII) - 2019 (Medium: Orange, High: Blue)", false);
    var forestPersistence = ee.Image("projects/forestdatapartnership/assets/community_forests/ForestPersistence_2020")
        .updateMask(country_and_buffer_mask).selfMask();

    map.addLayer(forestPersistence.gt(.90), {min: 0, max: 1, palette: ["white", "blue"]},"FDaP Forest Persistence v0 2020 (Threshold:0.9)",0,1);


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
  }
  
  // print('Cached distance keys:', Object.keys(cachedState.distanceImages));
  
  // Add layers to both maps
  addLayersToMap(map1, analysisYear1);
  addLayersToMap(map2, analysisYear2);
}

// }
// Initial map update
updateMap();
// debouncedUpdateMap();
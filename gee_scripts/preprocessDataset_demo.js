// =====================================================================
// preprocessDataset_demo.js
//
// Demo GEE app showing the preprocessDataset module in action.
// Uses real public datasets to demonstrate each preprocessing operation.
// Paste this into the GEE Code Editor to run.
// =====================================================================

// --- Load the preprocessing module ---
// In GEE Code Editor, require from your repository:
// var preprocess = require('users/andyarnellgee/apps:modules/preprocessDataset');
// For this demo, inline the function so it runs standalone:

var preprocessAsset = function(assetPath, preprocessing, sourceType) {
  preprocessing = preprocessing || {};
  sourceType = sourceType || 'image';
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
    if (preprocessing.mosaic) {
      result = ic.max();
    } else {
      result = ic.first();
    }

  } else {
    result = ee.Image(assetPath);
  }

  if (preprocessing.band !== undefined) {
    result = result.select(preprocessing.band);
  }
  if (preprocessing.classes) {
    var classes = preprocessing.classes;
    var ones = ee.List.repeat(1, classes.length);
    result = result.remap(classes, ones, 0).gt(0);
  }
  if (preprocessing.threshold) {
    var t = preprocessing.threshold;
    if (t.min !== undefined && t.max !== undefined) {
      result = result.gte(t.min).and(result.lte(t.max));
    } else if (t.min !== undefined) {
      result = result.gte(t.min);
    } else if (t.max !== undefined) {
      result = result.lte(t.max);
    }
  }

  result = result.gt(0).unmask(0).byte().rename('presence');
  return result;
};


// =====================================================================
// Define example datasets — each demonstrates a different operation
// =====================================================================

var examples = [
  // -----------------------------------------------------------------
  // 1. LULC raster — select forest classes from GLC-FCS30D (band + classes)
  //    GLC-FCS30D 30m land cover: select broadleaf forest classes
  //    Classes: 51=open EBF, 52=closed EBF, 61=open DBF, 62=closed DBF,
  //             71=open ENF, 72=closed ENF, 81=open DNF, 82=closed DNF
  //    Bands: b1=2000 ... b21=2020 (annual collection)
  // -----------------------------------------------------------------
  {
    name: 'Forest from LULC (GLC-FCS30D)',
    asset: 'projects/sat-io/open-datasets/GLC-FCS30D/annual',
    source_type: 'image_collection',
    preprocessing: {
      mosaic: true,
      band: 'b21',  // b21 = year 2020 (b1=2000, b2=2001, ...)
      classes: [51, 52, 61, 62, 71, 72, 81, 82]
    },
    viz: {palette: ['white', 'darkgreen']},
    visible: true
  },

  // -----------------------------------------------------------------
  // 2. Continuous raster — threshold tree cover from Hansen GFC
  //    Hansen 'treecover2000' band: select pixels >= 30% canopy cover
  // -----------------------------------------------------------------
  {
    name: 'Forest from canopy cover (Hansen >= 30%)',
    asset: 'UMD/hansen/global_forest_change_2023_v1_11',
    source_type: 'image',
    preprocessing: {
      band: 'treecover2000',
      threshold: {min: 30}
    },
    viz: {palette: ['white', 'green']},
    visible: false
  },

  // -----------------------------------------------------------------
  // 3. Vector FeatureCollection — filter GRIP4 roads by GP_RTP attribute
  //    GP_RTP: 1=highways, 2=primary, 3=secondary, 4=tertiary, 5=local
  //    Major roads = 1, 2, 3
  // -----------------------------------------------------------------
  {
    name: 'Major roads (GRIP4 vector, types 1-3)',
    asset: 'projects/ee-andyarnellgee/assets/p0002_primary_forest_support/raw/GRIP4_ExSet_2015_AADTpred_20240312',
    source_type: 'feature_collection',
    preprocessing: {
      filter: {field: 'GP_RTP', values: [1, 2, 3]}
    },
    viz: {palette: ['white', 'red']},
    visible: false
  },

  // -----------------------------------------------------------------
  // 4. ImageCollection mosaic — GISA built-up tiles
  //    GISA: pixel value = year of first urbanisation since 1972
  //    Threshold <= 2020 means "built-up by 2020"
  // -----------------------------------------------------------------
  {
    name: 'Built-up (GISA tiles, mosaic + threshold)',
    asset: 'projects/sat-io/open-datasets/GISA_1972_2019',
    source_type: 'image_collection',
    preprocessing: {
      mosaic: true,
      threshold: {max: 48}  // 48 = 2020 - 1972 (GISA uses years since 1972)
    },
    viz: {palette: ['white', 'red']},
    visible: false
  },

  // -----------------------------------------------------------------
  // 5. Single-band static raster — SDPT v2 planted trees
  //    Values: 1 = planted forests, 2 = tree crops
  //    Select class 2 (tree crops) only
  // -----------------------------------------------------------------
  {
    name: 'Tree crops (SDPT v2, class 2)',
    asset: 'projects/sdpt-v2/assets/sdpt_v2_simpleType_v09032024_public',
    source_type: 'image',
    preprocessing: {
      classes: [2]
    },
    viz: {palette: ['white', 'purple']},
    visible: false
  },

  // -----------------------------------------------------------------
  // 6. Already binary — WSF 2015 (built-up pixels = 255)
  //    No band/class/threshold needed — just .gt(0) normalises to 1
  // -----------------------------------------------------------------
  {
    name: 'Built-up (WSF 2015, already binary)',
    asset: 'DLR/WSF/WSF2015/v1',
    source_type: 'image',
    preprocessing: {},
    viz: {palette: ['white', 'orange']},
    visible: false
  },

  // -----------------------------------------------------------------
  // 7. WDPA protected areas — vector with attribute filter
  //    Filter to strictly protected categories (IUCN Ia, Ib, II)
  // -----------------------------------------------------------------
  {
    name: 'Protected areas (WDPA, IUCN Ia/Ib/II)',
    asset: 'WCMC/WDPA/current/polygons',
    source_type: 'feature_collection',
    preprocessing: {
      filter: {field: 'IUCN_CAT', values: ['Ia', 'Ib', 'II']}
    },
    viz: {palette: ['white', 'blue']},
    visible: false
  }
];


// =====================================================================
// Build the UI
// =====================================================================

// Left panel
var panel = ui.Panel({
  style: {width: '340px', padding: '8px'}
});
ui.root.insert(0, panel);

panel.add(ui.Label('preprocessAsset Demo', {
  fontWeight: 'bold', fontSize: '16px', margin: '0 0 8px 0'
}));

panel.add(ui.Label(
  'Each layer applies preprocessAsset() to a real GEE dataset ' +
  'with different preprocessing configs. Toggle layers via checkboxes.',
  {fontSize: '12px', color: 'gray', margin: '0 0 12px 0'}
));

// Store map layers keyed by name so checkboxes can toggle them
var layerMap = {};

// Process each example and add a checkbox + config display
examples.forEach(function(ex) {
  // Run preprocessAsset
  var binary = preprocessAsset(ex.asset, ex.preprocessing, ex.source_type);

  // Add to map
  var mapLayer = ui.Map.Layer(binary.selfMask(), ex.viz, ex.name, ex.visible);
  Map.layers().add(mapLayer);
  layerMap[ex.name] = mapLayer;

  // Checkbox to toggle visibility
  var cb = ui.Checkbox({
    label: ex.name,
    value: ex.visible,
    style: {fontWeight: 'bold', margin: '8px 0 2px 0'},
    onChange: function(checked) {
      layerMap[ex.name].setShown(checked);
    }
  });
  panel.add(cb);

  // Show the preprocessing config as text
  var configStr = JSON.stringify(ex.preprocessing);
  if (configStr === '{}') configStr = '(none — already binary)';
  panel.add(ui.Label('source: ' + ex.source_type, {
    fontSize: '11px', color: '#666', margin: '0 0 0 20px'
  }));
  panel.add(ui.Label('config: ' + configStr, {
    fontSize: '11px', color: '#666', margin: '0 0 0 20px'
  }));
});

// Separator
panel.add(ui.Label('', {margin: '12px 0 0 0'}));
panel.add(ui.Label(
  'Tip: Each layer is a binary 0/1 ee.Image ready for the PFF distance pipeline.',
  {fontSize: '11px', color: 'gray'}
));

// Centre on a tropical area
Map.setCenter(15, 0, 5);  // Congo Basin

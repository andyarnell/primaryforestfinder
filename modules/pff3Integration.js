/**
 * PFF_3 Preprocessing Pipeline Integration Example
 *
 * Shows how to use the flexible preprocessing pipeline with Primary Forest Finder
 * Allows switching between different preprocessing strategies without changing core logic
 */

// Load the preprocessing modules
var PreprocessingPipeline = require("users/andyarnellgee/apps:modules/preprocessingPipeline.js");
var PreprocessingConfigs = require("users/andyarnellgee/apps:modules/preprocessingConfigs.js");

/**
 * Main preprocessing configuration for PFF
 * Users can change this to switch between strategies
 */
var PREPROCESSING_CONFIG = 'weighted_composite';  // or 'binary', 'continuous', 'ensemble', etc.

/**
 * Execute preprocessing with selected strategy
 *
 * @param {Object} inputs - Object containing ee.Image layers for input
 *   - forest_raster: Main forest layer
 *   - forest_optical: (optional) Optical-based forest classification
 *   - forest_radar: (optional) Radar-based forest classification
 *   - forest_lidar: (optional) LIDAR-based forest classification
 *   - dem_raster: (optional) Digital elevation model
 *   - distance_to_developed: (optional) Distance from development
 *
 * @return {ee.Image} Preprocessed forest layer
 */
function preprocessForest(inputs, configName) {
  configName = configName || PREPROCESSING_CONFIG;

  try {
    var result = PreprocessingPipeline.execute(configName, inputs);

    // Log execution details
    var log = PreprocessingPipeline.getLog();
    print('Preprocessing log (' + configName + '):');
    log.forEach(function(msg) { print('  ' + msg); });

    return result;
  } catch(e) {
    print('Error in preprocessing: ' + e);
    // Fallback to binary if preprocessing fails
    return inputs.forest_raster.gt(0.5).selfMask();
  }
}

/**
 * Prepare multi-source forest inputs for preprocessing
 * This bridges various data sources into a common format
 */
function prepareForestInputs(params) {
  params = params || {};

  var inputs = {};

  // Main forest layer (required)
  if (params.forest_raster) {
    inputs.forest_raster = params.forest_raster;
  } else {
    throw new Error('forest_raster is required');
  }

  // Optional: Multiple forest classifications from different sources
  if (params.forest_optical) {
    inputs.forest_optical = params.forest_optical;
  }

  if (params.forest_radar) {
    inputs.forest_radar = params.forest_radar;
  }

  if (params.forest_lidar) {
    inputs.forest_lidar = params.forest_lidar;
  }

  // Optional: Topographic and distance layers
  if (params.dem_raster) {
    inputs.dem_raster = params.dem_raster;
  }

  if (params.distance_to_developed) {
    inputs.distance_to_developed = params.distance_to_developed;
  }

  return inputs;
}

/**
 * Example: Traditional PFF workflow using preprocessing pipeline
 */
function runPFFWithPreprocessing(country, year, preprocessingConfig) {
  preprocessingConfig = preprocessingConfig || PREPROCESSING_CONFIG;

  print('Running PFF with preprocessing: ' + preprocessingConfig);

  // 1. Get base datasets
  var countryFeatures = getCountryFeatures(country);
  var aoi = countryFeatures.geometry();

  // Load primary forest data (example - adapt to your actual sources)
  var hansenForest = gfcHansenTreecoverPrep(year, 30);  // 30% tree cover threshold

  // Optional: Load auxiliary data for sensor fusion
  var opticalForest = hansenForest;  // In real workflow, load actual optical classification
  var radarForest = hansenForest;    // In real workflow, load actual radar classification

  // 2. Prepare inputs for preprocessing pipeline
  var inputs = prepareForestInputs({
    forest_raster: hansenForest,
    forest_optical: opticalForest,
    forest_radar: radarForest,
    // forest_lidar: lidarForest,  // Add if available
    // dem_raster: dem,
    // distance_to_developed: distToDeveloped
  });

  // 3. Apply preprocessing pipeline
  var preprocessedForest = preprocessForest(inputs, preprocessingConfig);

  // 4. Continue with standard PFF analysis
  var slope = calculateSlope(ee.ImageCollection([]));
  var anthropogenicMask = getCountryClip(country);  // Example

  // 5. Apply decision tree logic
  var undisturbedForest = preprocessedForest.and(anthropogenicMask.not());

  return {
    preprocessedForest: preprocessedForest,
    undisturbedForest: undisturbedForest,
    visualizationParams: {
      min: 0,
      max: 1,
      palette: ['white', '#228B22']
    }
  };
}

/**
 * Advanced: Chain preprocessing operations for custom workflows
 */
function createCustomPreprocessing(name, steps) {
  PreprocessingPipeline.registerConfig(name, {
    name: 'Custom: ' + name,
    description: 'User-defined preprocessing pipeline',
    steps: steps,
    normalizeOutput: true,
    outputMin: 0,
    outputMax: 1
  });

  print('Registered custom preprocessing: ' + name);
  return PreprocessingPipeline.getConfig(name);
}

/**
 * Comparison: Run multiple preprocessing strategies on same input
 * Useful for sensitivity analysis
 */
function comparePreprocessingStrategies(inputs, configNames) {
  configNames = configNames || ['binary', 'continuous', 'weighted_composite'];

  var results = {};

  configNames.forEach(function(configName) {
    try {
      results[configName] = PreprocessingPipeline.execute(configName, inputs);
      print('✓ ' + configName);
    } catch(e) {
      print('✗ ' + configName + ': ' + e);
      results[configName] = null;
    }
  });

  return results;
}

/**
 * Export preprocessing output for external analysis
 */
function exportPreprocessedForest(forest, geometry, description) {
  var exportParams = {
    image: forest,
    description: description || 'preprocessed_forest',
    geometry: geometry,
    scale: 30,
    maxPixels: 1e13
  };

  Export.image.toDrive(exportParams);
  print('Export queued: ' + description);
}

/**
 * USAGE EXAMPLES
 * ===============
 */

// Example 1: Simple binary preprocessing
function example_binaryPreprocessing() {
  var hansenForest = gfcHansenTreecoverPrep(2023, 30);

  var inputs = {
    forest_raster: hansenForest
  };

  var binaryForest = preprocessForest(inputs, 'binary');
  // Map.addLayer(binaryForest, {min:0, max:1, palette:['white','green']}, 'Binary Forest');
}

// Example 2: Weighted multi-sensor fusion
function example_weightedFusion() {
  // In a real workflow, you would load these from different sources
  var opticalForest = ee.Image('example/optical_forest_classification');
  var radarForest = ee.Image('example/radar_forest_classification');
  var lidarForest = ee.Image('example/lidar_forest_classification');

  var inputs = {
    forest_optical: opticalForest,
    forest_radar: radarForest,
    forest_lidar: lidarForest
  };

  var composite = preprocessForest(inputs, 'weighted_composite');
  // Map.addLayer(composite, {min:0, max:1, palette:['white','darkgreen']}, 'Weighted Composite');
}

// Example 3: Custom multi-stage pipeline
function example_customPipeline() {
  var customSteps = [
    {
      type: 'threshold',
      input: 'forest_raster',
      params: { value: 0.6 },
      output: 'forest_initial'
    },
    {
      type: 'distance',
      input: 'forest_initial',
      params: { threshold: 500 },
      output: 'forest_buffered'
    },
    {
      type: 'mask',
      input: 'forest_buffered',
      params: { mask: 'protected_mask' },
      output: 'forest_protected'
    }
  ];

  createCustomPreprocessing('protected_forest_pipeline', customSteps);

  var inputs = {
    forest_raster: ee.Image('example/forest'),
    protected_mask: ee.Image('example/protected_areas')
  };

  var result = preprocessForest(inputs, 'protected_forest_pipeline');
}

// Example 4: Sensitivity analysis
function example_sensitivityAnalysis() {
  var hansenForest = gfcHansenTreecoverPrep(2023, 30);

  var inputs = {
    forest_raster: hansenForest,
    forest_optical: hansenForest,
    forest_radar: hansenForest
  };

  var results = comparePreprocessingStrategies(inputs,
    ['binary', 'continuous', 'weighted_composite']);

  print('Results:', results);
}

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    preprocessForest: preprocessForest,
    prepareForestInputs: prepareForestInputs,
    runPFFWithPreprocessing: runPFFWithPreprocessing,
    createCustomPreprocessing: createCustomPreprocessing,
    comparePreprocessingStrategies: comparePreprocessingStrategies,
    exportPreprocessedForest: exportPreprocessedForest
  };
}

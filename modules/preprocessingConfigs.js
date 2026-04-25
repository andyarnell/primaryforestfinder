/**
 * Preprocessing Pipeline Configurations
 * Preset configurations for common preprocessing workflows
 */

// Ensure PreprocessingPipeline is loaded
var PreprocessingPipeline = require("users/andyarnellgee/apps:modules/preprocessingPipeline.js");

/**
 * BINARY CONFIG
 * Traditional binary classification: forest (1) or not (0)
 * Input: forest_raster (must be binary 0/1)
 * Output: Binary forest mask
 */
PreprocessingPipeline.registerConfig('binary', {
  name: 'Binary Forest Classification',
  description: 'Simple binary forest/non-forest classification',
  steps: [
    {
      type: 'threshold',
      input: 'forest_raster',
      params: { value: 0.5 },
      output: 'forest_binary'
    }
  ],
  normalizeOutput: false,
  outputMin: 0,
  outputMax: 1
});

/**
 * CONTINUOUS CONFIG
 * Preserves continuous forest probability values (0-1)
 * Input: forest_probability_raster (values 0-1)
 * Output: Continuous forest probability
 */
PreprocessingPipeline.registerConfig('continuous', {
  name: 'Continuous Forest Probability',
  description: 'Preserves continuous probability values from forest classifier',
  steps: [
    // No threshold - pass through
    {
      type: 'multiply',
      input: 'forest_raster',
      params: { multiplier: 1 },
      output: 'forest_probability'
    }
  ],
  normalizeOutput: true,
  outputMin: 0,
  outputMax: 1
});

/**
 * WEIGHTED COMPOSITE CONFIG
 * Combines multiple forest indicators with weights
 * Input: forest_optical, forest_radar, forest_lidar (each 0-1)
 * Output: Weighted composite decision
 */
PreprocessingPipeline.registerConfig('weighted_composite', {
  name: 'Weighted Multi-Sensor Composite',
  description: 'Combines optical, radar, and LIDAR forest indicators',
  steps: [
    {
      type: 'combine',
      params: {
        layers: ['forest_optical', 'forest_radar', 'forest_lidar'],
        operator: 'weighted',
        weights: [0.5, 0.3, 0.2]  // optical: 50%, radar: 30%, LIDAR: 20%
      },
      output: 'forest_composite'
    },
    {
      type: 'threshold',
      input: 'forest_composite',
      params: { value: 0.6 },
      output: 'forest_binary'
    }
  ],
  normalizeOutput: true,
  outputMin: 0,
  outputMax: 1
});

/**
 * CONFIDENCE STRATIFICATION CONFIG
 * Stratifies forest by confidence levels
 * Input: forest_probability, forest_confidence
 * Output: High, medium, low confidence forest patches
 */
PreprocessingPipeline.registerConfig('confidence_strata', {
  name: 'Confidence-Stratified Forest',
  description: 'Stratifies forest into confidence tiers',
  steps: [
    {
      type: 'threshold',
      input: 'forest_probability',
      params: { value: 0.8 },
      output: 'forest_high_confidence'  // >= 0.8
    },
    {
      type: 'threshold',
      input: 'forest_probability',
      params: { value: 0.6 },
      output: 'forest_medium_raw'  // >= 0.6
    },
    {
      type: 'max',
      input: 'forest_medium_raw',
      params: { with: 'forest_high_confidence' },
      output: 'forest_medium_confidence'  // >= 0.6 but not high
    }
  ],
  normalizeOutput: false
});

/**
 * MORPHOLOGICAL FILTER CONFIG
 * Applies morphological operations to clean up forest patterns
 * Input: forest_raster
 * Output: Cleaned forest mask with removed noise
 */
PreprocessingPipeline.registerConfig('morphological', {
  name: 'Morphologically Filtered Forest',
  description: 'Applies morphological cleaning: despeckle, gaps',
  steps: [
    {
      type: 'threshold',
      input: 'forest_raster',
      params: { value: 0.5 },
      output: 'forest_binary'
    },
    {
      type: 'distance',
      input: 'forest_binary',
      params: {
        threshold: 100,  // Remove isolated pixels < 100m from edge
        fastBuffer: true,
        neighborhood: 50
      },
      output: 'forest_despeckled'
    }
  ]
});

/**
 * CONDITIONAL PROBABILITY CONFIG
 * Forest probability conditional on slope and other factors
 * Input: forest_raster, dem_raster
 * Output: Forest probability weighted by topographic position
 */
PreprocessingPipeline.registerConfig('conditional_probability', {
  name: 'Conditional Forest Probability',
  description: 'Modulates forest probability by slope and elevation',
  steps: [
    // Slope-based weighting: steeper = higher confidence
    {
      type: 'custom',  // Would be implemented with GEE expressions
      input: 'dem_raster',
      params: {
        expression: 'slope_weight',
        description: 'Steeper terrain gets higher probability weight'
      },
      output: 'slope_weight'
    },
    {
      type: 'multiply',
      input: 'forest_raster',
      params: { by: 'slope_weight' },
      output: 'forest_conditional'
    }
  ]
});

/**
 * ENSEMBLE CONFIG
 * Averages multiple forest classification methods
 * Input: forest_ml, forest_spectral, forest_texture
 * Output: Ensemble decision
 */
PreprocessingPipeline.registerConfig('ensemble', {
  name: 'Ensemble Forest Classification',
  description: 'Averages multiple classification methods for robustness',
  steps: [
    {
      type: 'combine',
      params: {
        layers: ['forest_ml', 'forest_spectral', 'forest_texture'],
        operator: 'mean'
      },
      output: 'forest_ensemble_probability'
    },
    {
      type: 'threshold',
      input: 'forest_ensemble_probability',
      params: { value: 0.6 },
      output: 'forest_ensemble_binary'
    }
  ]
});

/**
 * TEMPORAL CONSISTENCY CONFIG
 * Computes forested areas consistent across multiple years
 * Input: forest_2020, forest_2021, forest_2022
 * Output: Consistently forested areas
 */
PreprocessingPipeline.registerConfig('temporal_consistency', {
  name: 'Temporally Consistent Forest',
  description: 'Forest consistently detected across multiple years',
  steps: [
    {
      type: 'combine',
      params: {
        layers: ['forest_2020', 'forest_2021', 'forest_2022'],
        operator: 'mean'
      },
      output: 'forest_temporal_average'
    },
    {
      type: 'threshold',
      input: 'forest_temporal_average',
      params: { value: 0.67 },  // Detected in 2+ of 3 years
      output: 'forest_consistent'
    }
  ]
});

/**
 * CUSTOM MULTI-STEP CONFIG
 * Demonstrates full preprocessing pipeline combining multiple techniques
 * Input: forest_optical, forest_radar, dem, distance_to_developed
 * Output: Primary forest candidate
 */
PreprocessingPipeline.registerConfig('multi_stage', {
  name: 'Multi-Stage Primary Forest Pipeline',
  description: 'Full preprocessing combining sensors, topography, and development distance',
  steps: [
    // Stage 1: Fuse optical and radar
    {
      type: 'combine',
      params: {
        layers: ['forest_optical', 'forest_radar'],
        operator: 'weighted',
        weights: [0.6, 0.4]
      },
      output: 'forest_fused'
    },

    // Stage 2: Apply confidence threshold
    {
      type: 'threshold',
      input: 'forest_fused',
      params: { value: 0.6 },
      output: 'forest_confident'
    },

    // Stage 3: Filter by development distance
    {
      type: 'distance',
      input: 'distance_to_developed',
      params: { threshold: 1000 },
      output: 'away_from_development'
    },

    // Stage 4: Combine forest and distance
    {
      type: 'combine',
      params: {
        layers: ['forest_confident', 'away_from_development'],
        operator: 'and'
      },
      output: 'forest_undisturbed'
    }
  ]
});

// Export function to get a config
function getPreprocessingConfig(name) {
  return PreprocessingPipeline.getConfig(name);
}

// Export function to list available configs
function listPreprocessingConfigs() {
  var configs = PreprocessingPipeline.getAllConfigs();
  print('Available preprocessing configurations:');
  configs.forEach(function(config) {
    print(' - ' + config.name + ' (' + config.description + ')');
  });
  return configs;
}

// Export
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    getPreprocessingConfig: getPreprocessingConfig,
    listPreprocessingConfigs: listPreprocessingConfigs
  };
}

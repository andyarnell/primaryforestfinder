# Flexible Preprocessing Pipeline for Primary Forest Finder

## Overview

The **Preprocessing Pipeline** system allows chaining of preprocessing operations with full flexibility beyond binary classification. This enables:

- **Flexible input types**: Beyond binary images (continuous values, probabilities, confidence scores)
- **Chainable operations**: Combine distance buffers, thresholds, masking, and math operations
- **Custom workflows**: Register custom preprocessing configurations
- **Sensitivity analysis**: Compare multiple strategies on the same input
- **Multi-sensor fusion**: Combine optical, radar, LIDAR, and other data sources

## Architecture

Three core modules:

1. **`preprocessingPipeline.js`** - Core pipeline engine
2. **`preprocessingConfigs.js`** - Preset configurations
3. **`pff3Integration.js`** - Integration with PFF_3.js

## Core Concepts

### Steps

Each preprocessing step is an operation that transforms data:

```javascript
{
  type: 'operation_type',
  input: 'input_name_or_image',
  params: { /* operation-specific parameters */ },
  output: 'output_variable_name'
}
```

### Step Types

| Type | Purpose | Parameters |
|------|---------|------------|
| `threshold` | Binary classification | `value` (threshold value) |
| `distance` | Distance buffer | `threshold`, `fastBuffer`, `neighborhood` |
| `multiply` | Scale values | `multiplier` or `by` (ee.Image) |
| `add` | Add constant | `value` or `to` (ee.Image) |
| `max` | Element-wise maximum | `with` (ee.Image\|string) |
| `min` | Element-wise minimum | `with` (ee.Image\|string) |
| `combine` | Merge layers | `layers`, `operator`, `weights` |
| `mask` | Apply mask | `mask` (ee.Image\|string) |
| `remap` | Remap values | `from` (Array), `to` (Array) |

### Combine Operators

- **`and`** - Logical AND of layers
- **`or`** - Logical OR of layers
- **`add`** - Sum layers (useful for counting)
- **`mean`** - Average of layers
- **`weighted`** - Weighted combination (requires `weights` array)
- **`max`** - Maximum across layers
- **`min`** - Minimum across layers

## Preset Configurations

### 1. Binary
Simple binary forest/non-forest classification:

```javascript
preprocessFe.execute('binary', {
  forest_raster: myForestImage
});
```

### 2. Continuous
Preserves continuous probability values (0-1):

```javascript
PreprocessingPipeline.execute('continuous', {
  forest_raster: probabilityImage
});
```

### 3. Weighted Composite
Combines optical, radar, and LIDAR with weights:

```javascript
PreprocessingPipeline.execute('weighted_composite', {
  forest_optical: opticalClassification,    // 50% weight
  forest_radar: radarClassification,        // 30% weight
  forest_lidar: lidarClassification         // 20% weight
});
```

### 4. Confidence Stratification
Stratifies forest by confidence levels:

```javascript
var result = PreprocessingPipeline.execute('confidence_strata', {
  forest_probability: probabilityImage,
  forest_confidence: confidenceImage
});

// Output contains:
// - forest_high_confidence (>= 0.8)
// - forest_medium_confidence (0.6-0.8)
// - forest_low_confidence (< 0.6)
```

### 5. Morphological
Applies morphological cleaning:

```javascript
PreprocessingPipeline.execute('morphological', {
  forest_raster: rawForestImage
});
```

### 6. Ensemble
Averages multiple classification methods:

```javascript
PreprocessingPipeline.execute('ensemble', {
  forest_ml: mlClassifier,
  forest_spectral: spectralClassifier,
  forest_texture: textureClassifier
});
```

### 7. Temporal Consistency
Identifies forest consistently detected across years:

```javascript
PreprocessingPipeline.execute('temporal_consistency', {
  forest_2020: year2020,
  forest_2021: year2021,
  forest_2022: year2022
});

// 2+ of 3 years = forest detected
```

### 8. Multi-Stage
Full preprocessing combining multiple techniques:

```javascript
PreprocessingPipeline.execute('multi_stage', {
  forest_optical: opticalData,
  forest_radar: radarData,
  dem: elevationData,
  distance_to_developed: distanceImage
});
```

## Usage Examples

### Basic Usage

```javascript
// Load modules
var PreprocessingPipeline = require(...);

// Prepare inputs
var inputs = {
  forest_raster: myForestImage,
  forest_optical: opticalClassification,
  forest_radar: radarClassification
};

// Execute preprocessing
var forest = PreprocessingPipeline.execute('weighted_composite', inputs);

// Use result
Map.addLayer(forest, {min:0, max:1, palette:['white','green']}, 'Forest');
```

### Custom Preprocessing Configuration

```javascript
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
    params: { threshold: 1000 },
    output: 'forest_buffered'
  },
  {
    type: 'mask',
    input: 'forest_buffered',
    params: { mask: 'protected_areas' },
    output: 'forest_final'
  }
];

PreprocessingPipeline.registerConfig('my_custom', {
  name: 'My Custom Workflow',
  steps: customSteps,
  normalizeOutput: true
});

var result = PreprocessingPipeline.execute('my_custom', {
  forest_raster: forest,
  protected_areas: protectedAreasImage
});
```

### Comparing Multiple Strategies

```javascript
var inputs = {
  forest_raster: myForestImage,
  forest_optical: opticalData,
  forest_radar: radarData
};

var results = {};
['binary', 'continuous', 'weighted_composite', 'ensemble'].forEach(function(config) {
  results[config] = PreprocessingPipeline.execute(config, inputs);
});

// Visualize all three
results.forEach(function(name, image) {
  Map.addLayer(image, {min:0, max:1, palette:['white','green']}, name);
});
```

### Sensitivity Analysis

```javascript
// Test how results change with different weights
var weights = [
  [0.5, 0.3, 0.2],    // Optical-heavy
  [0.33, 0.33, 0.34], // Equal
  [0.2, 0.3, 0.5]     // LIDAR-heavy
];

weights.forEach(function(w, i) {
  // Register variant config
  var configName = 'variant_' + i;
  var steps = [...]; // Define steps with weight w
  PreprocessingPipeline.registerConfig(configName, {...});

  var result = PreprocessingPipeline.execute(configName, inputs);
  Map.addLayer(result, {...}, 'Variant ' + i);
});
```

## Integration with PFF_3

### In PFF_3 At Runtime

```javascript
// At top of pff_3.js
var PreprocessingPipeline = require("users/andyarnellgee/apps:modules/preprocessingPipeline.js");
var pff3Integration = require("users/andyarnellgee/apps:modules/pff3Integration.js");

// When loading forest data
var hansenForest = gfcHansenTreecoverPrep(analysisYear, treecoverThreshold);

var inputs = {
  forest_raster: hansenForest,
  forest_optical: opticalForest,
  forest_radar: radarForest
};

// Use selected preprocessing strategy
var preprocessedForest = pff3Integration.preprocessForest(
  inputs,
  'weighted_composite'  // or 'binary', 'ensemble', etc.
);

// Continue with standard PFF decision tree
var primaryForest = preprocessedForest.and(anthropogenicMask.not());
```

### Switching Strategies With UI Control

```javascript
// Define preprocessing options
var preprocessingOptions = {
  'binary': 'Binary (0-1 only)',
  'continuous': 'Continuous Probability',
  'weighted_composite': 'Optical + Radar + LIDAR',
  'ensemble': 'Ensemble Average',
  'temporal_consistency': 'Multi-year Consensus'
};

// Add dropdown to UI
var preprocessingSelect = ui.Select({
  items: Object.keys(preprocessingOptions),
  value: 'weighted_composite',
  onChange: function(configName) {
    var forest = pff3Integration.preprocessForest(inputs, configName);
    // Update visualization
  }
});

ui.root.add(preprocessingSelect);
```

## Advanced: Operator Chaining

Create complex workflows by chaining operations:

```javascript
var complexSteps = [
  // Step 1: Initial classification
  {
    type: 'combine',
    params: {
      layers: ['forest_ml', 'forest_spectral'],
      operator: 'weighted',
      weights: [0.6, 0.4]
    },
    output: 'forest_weighted'
  },

  // Step 2: High confidence only
  {
    type: 'threshold',
    input: 'forest_weighted',
    params: { value: 0.75 },
    output: 'forest_hc'
  },

  // Step 3: Buffer by 500m
  {
    type: 'distance',
    input: 'forest_hc',
    params: { threshold: 500 },
    output: 'forest_buffered'
  },

  // Step 4: Remove forest near development
  {
    type: 'combine',
    params: {
      layers: ['forest_buffered', 'distance_to_development'],
      operator: 'and'
    },
    output: 'final_forest'
  }
];

PreprocessingPipeline.registerConfig('complex', {
  name: 'Complex Chained Pipeline',
  steps: complexSteps
});
```

## Configuration Parameters

### Global Config Parameters

```javascript
{
  name: 'Pipeline Name',                    // Required: descriptive name
  description: 'What this does',           // Optional: description
  steps: [],                                // Required: array of steps
  normalizeOutput: true,                    // Optional: normalize to 0-1
  outputMin: 0,                             // Optional: min output value
  outputMax: 1                              // Optional: max output value
}
```

## Debugging

### View Execution Log

```javascript
var result = PreprocessingPipeline.execute('my_config', inputs);
var log = PreprocessingPipeline.getLog();

log.forEach(function(msg) {
  print(msg);
});
```

### Inspect Intermediate Variables

```javascript
// After execution
var step3Result = PreprocessingPipeline.getVariable('step_3');
Map.addLayer(step3Result, {...}, 'Debug: Step 3');
```

### List All Configurations

```javascript
PreprocessingPipeline.getAllConfigs().forEach(function(config) {
  print(config.name + ': ' + config.description);
});
```

## Performance Considerations

- **Distance transforms**: Use `fastBuffer: true` for large areas (default)
- **Layer combinations**: Order doesn't matter for `or`/`and`; order matters for `add`/`subtract`
- **Normalization**: Automatic normalization is applied if requested
- **Memory**: Complex chains can increase memory usage; simplify if needed

## Future Extensions

Possible additions:

- [ ] Gaussian smoothing operations
- [ ] Median filtering
- [ ] Conditional rasters (If-then-else logic)
- [ ] Temporal differencing
- [ ] Spectral indices (NDVI, etc.)
- [ ] Custom expression support
- [ ] Parameter optimization/tuning
- [ ] Output statistics and validation

## File Structure

```
modules/
├── preprocessingPipeline.js      # Core engine
├── preprocessingConfigs.js       # Preset configurations
└── pff3Integration.js            # PFF_3 integration examples

docs/
└── PREPROCESSING_PIPELINE.md     # This documentation
```

## Contact & Support

For questions or custom requirements, refer to the source code docstrings and examples in `pff3Integration.js`.

# Preprocessing Pipeline - Quick Reference

## TL;DR

Switch preprocessing strategies without changing core PFF code:

```javascript
// Load modules
var Pipeline = require("users/andyarnellgee/apps:modules/preprocessingPipeline.js");
var Configs = require("users/andyarnellgee/apps:modules/preprocessingConfigs.js");

// One-liner for forest preprocessing
var forest = Pipeline.execute('weighted_composite', {
  forest_optical: opticalData,
  forest_radar: radarData,
  forest_lidar: lidarData
});
```

---

## Available Presets (Copy-Paste Ready)

### Binary Classification (Traditional)
```javascript
Pipeline.execute('binary', { forest_raster: image })
```
✓ Simple 0/1 output
✗ Loses probabilistic information

### Continuous Probability (Hansen-style)
```javascript
Pipeline.execute('continuous', { forest_raster: image })
```
✓ Preserves confidence values
✓ Allows custom thresholding downstream

### Multi-Sensor Fusion (Recommended)
```javascript
Pipeline.execute('weighted_composite', {
  forest_optical: opticalImage,     // 50%
  forest_radar: radarImage,          // 30%
  forest_lidar: lidarImage           // 20%
})
```
✓ Robust to sensor artifacts
✓ Reduces bias

### Ensemble Voting (Most Robust)
```javascript
Pipeline.execute('ensemble', {
  forest_ml: mlResult,
  forest_spectral: spectralResult,
  forest_texture: textureResult
})
```
✓ Highest accuracy
✗ More compute

### Multi-Year Consensus (For Change Detection)
```javascript
Pipeline.execute('temporal_consistency', {
  forest_2020: year2020,
  forest_2021: year2021,
  forest_2022: year2022
})
```
✓ Stable forest only (>= 2/3 years)

---

## Custom Single-Step Workflows

### Just Threshold
```javascript
var forest = image.gt(0.6).selfMask();
// Equivalent to:
Pipeline.registerConfig('simple_threshold', {
  steps: [{
    type: 'threshold',
    input: 'forest',
    params: { value: 0.6 },
    output: 'result'
  }]
});
```

### Threshold + Distance Buffer
```javascript
Pipeline.registerConfig('threshold_buffer', {
  steps: [
    {
      type: 'threshold',
      input: 'forest',
      params: { value: 0.5 },
      output: 'forest_binary'
    },
    {
      type: 'distance',
      input: 'forest_binary',
      params: { threshold: 1000 },  // 1km buffer
      output: 'forest_buffered'
    }
  ]
});

Pipeline.execute('threshold_buffer', { forest: image });
```

### Sensor Fusion + Masking
```javascript
Pipeline.registerConfig('fusion_with_mask', {
  steps: [
    {
      type: 'combine',
      params: {
        layers: ['optical', 'radar'],
        operator: 'weighted',
        weights: [0.6, 0.4]
      },
      output: 'fused'
    },
    {
      type: 'mask',
      input: 'fused',
      params: { mask: 'protected_areas' },
      output: 'result'
    }
  ]
});

Pipeline.execute('fusion_with_mask', {
  optical: opticalImage,
  radar: radarImage,
  protected_areas: paImage
});
```

---

## Common Recipes

### Recipe: High Confidence Forest
Requires forest detection in 2/3 sensors:
```javascript
Pipeline.registerConfig('high_confidence', {
  steps: [{
    type: 'combine',
    params: {
      layers: ['optical', 'radar', 'lidar'],
      operator: 'add'
    },
    output: 'count'
  }],
  normalizeOutput: false
});

// Then threshold manually: count >= 2
```

### Recipe: Conservative to Permissive Toggle

**Conservative** (only obvious forest):
```javascript
{ type: 'threshold', input: 'probability', params: { value: 0.8 }, output: 'result' }
```

**Moderate** (balanced):
```javascript
{ type: 'threshold', input: 'probability', params: { value: 0.6 }, output: 'result' }
```

**Permissive** (include uncertain):
```javascript
{ type: 'threshold', input: 'probability', params: { value: 0.4 }, output: 'result' }
```

### Recipe: Weighted by Slope
(More confident in steep areas)
```javascript
var slopeWeight = slope.gt(30).multiply(0.5).add(0.5);  // 0.5-1.0
var weightedForest = probability.multiply(slopeWeight);
```

### Recipe: Distance-Based Confidence Decay
(Lower confidence far from reference)
```javascript
var referenceDistance = ee.Image(1).cumulativeCost({source: referenceRaster});
var distanceWeight = referenceDistance.divide(1000).min(1);  // Decay over 1km
var weightedForest = probability.multiply(distanceWeight);
```

---

## Debugging Checklist

**Issue:** Pipeline not found
```javascript
Pipeline.getAllConfigs().forEach(function(c) { print(c.name); });
// → See list of available configurations
```

**Issue:** Wrong output at step 3
```javascript
var result = Pipeline.execute('myconfig', inputs);
var step3 = Pipeline.getVariable('step_3');
Map.addLayer(step3, {...}, 'Debug Step 3');
```

**Issue:** Unexpected values
```javascript
var log = Pipeline.getLog();
log.forEach(function(msg) { print(msg); });
// → See step-by-step execution trace
```

---

## Performance Tips

| Operation | Speed | Notes |
|-----------|-------|-------|
| threshold | ⚡ Fast | 1 second |
| distance (fast) | ⚡ Fast | 5-10 seconds |
| distance (slow) | 🐢 Slow | 30+ seconds |
| combine (and/or) | ⚡ Fast | 1-2 seconds |
| combine (add/mean) | ⚡ Fast | 1-2 seconds |
| weighted combine | 🟡 Medium | 2-5 seconds |

**Optimization:**
- Use `fastBuffer: true` (default) for distance
- Combine layers before thresholding
- Avoid redundant operations

---

## Integration with PFF_3.js

At top of script:
```javascript
var Pipeline = require("users/andyarnellgee/apps:modules/preprocessingPipeline.js");

// Global config - change this to switch strategies
var PREPROCESSING = 'weighted_composite';
```

When loading forest:
```javascript
var forest = gfcHansenTreecoverPrep(year, threshold);

var result = Pipeline.execute(PREPROCESSING, {
  forest_raster: forest,
  // Add optional sensors
});

// Continue as normal
```

---

## What's Not Supported (Yet)

- ❌ Spectral indices (NDVI, etc.) - pre-compute and pass in
- ❌ Gaussian smoothing - use distance buffer instead
- ❌ If-then-else logic - use `max(min(...))` or register custom
- ❌ Temporal derivatives - pre-compute and pass in
- ❌ Multilayer conditional - break into steps

For these, either:
1. Pre-compute externally and pass as input
2. Post-process the result
3. Register a custom step

---

## Code Examples by Complexity

### Level 1: Swap Data Source
```javascript
// Change this line
var forest = Pipeline.execute('binary', { forest_raster: oldForest });
// To this
var forest = Pipeline.execute('weighted_composite', {
  forest_optical: newOptical,
  forest_radar: newRadar
});
```

### Level 2: Adjust Thresholds
```javascript
Pipeline.registerConfig('custom_threshold', {
  steps: [{
    type: 'threshold',
    input: 'forest',
    params: { value: 0.65 },  // ← Change this
    output: 'result'
  }]
});
```

### Level 3: Multi-Step Custom
```javascript
Pipeline.registerConfig('my_workflow', {
  steps: [
    { type: 'combine', params: {...}, output: 'step1' },
    { type: 'threshold', input: 'step1', params: {...}, output: 'step2' },
    { type: 'distance', input: 'step2', params: {...}, output: 'step3' }
  ]
});
```

### Level 4: Conditional via Operators
```javascript
// "Apply buffer IF high confidence"
Pipeline.registerConfig('conditional', {
  steps: [
    {
      type: 'combine',
      params: {
        layers: [
          { type: 'distance', input: 'forest_hc', output: 'buffered' },
          'forest_low'
        ],
        operator: 'max'  // High-conf buffered OR low-conf as-is
      },
      output: 'result'
    }
  ]
});
```

---

## See Also

- Full documentation: `docs/PREPROCESSING_PIPELINE.md`
- Code examples: `modules/pff3Integration.js`
- All configurations: `modules/preprocessingConfigs.js`
- Core API: `modules/preprocessingPipeline.js`

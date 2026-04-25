/**
 * pff_cepi.js
 * Core-Edge-Periphery-Isolated (CEPI) Classification for Primary Forest Finder
 * 
 * Based on David Theobald's approach (2024)
 * Modified for scale-stability using .reproject()
 * 
 * CLASSIFICATION:
 * - Core (3): Forest pixels far from edge (distance >= coreDistance)
 * - Edge (2): Non-core forest adjacent to core
 * - Periphery (1): Forest not connected to any core
 * - Isolated (0): Removed - patches with no core pixels
 * 
 * The .reproject() calls ensure results don't change when zooming.
 */

// ============================================================================
// CEPI CLASSIFICATION - THEOBALD APPROACH WITH SCALE STABILITY
// ============================================================================

/**
 * Classify forest into Core, Edge, Periphery zones
 * 
 * Uses Theobald's d4Edge approach:
 * 1. Calculate distance to forest edge
 * 2. Smooth with circular kernel (finds "chunky" interior areas)
 * 3. Threshold for core
 * 4. Spread from core to find edge vs periphery
 * 
 * @param {ee.Image} mask - Binary forest mask (1 = forest)
 * @param {Object} [options] - Classification options
 * @param {Number} [options.coreDistance=100] - Distance from edge to be "core" (meters)
 * @param {Number} [options.radius=200] - Smoothing kernel radius (meters), typically 2x coreDistance
 * @param {Number} [options.edgeDistance=500] - Max distance from core to be "edge" (meters)
 * @param {Number} [options.scale=30] - Pixel resolution (meters)
 * @returns {ee.Image} Classification with values: 3=core, 2=edge, 1=periphery
 */
exports.classify = function(mask, options) {
  options = options || {};
  var coreDistance = options.coreDistance || 100;
  var radius = options.radius || coreDistance * 2;  // Smoothing kernel radius
  var edgeDistance = options.edgeDistance || 500;   // How far from core = "edge"
  var scale = options.scale || 30;
  var maxEuclidean = options.maxEuclidean || 20000;
  
  // Get projection for scale-stable operations
  var proj = mask.projection();
  
  // Ensure mask is binary
  mask = mask.gt(0).unmask(0);
  
  // ─── Step 1: Calculate distance to forest edge ───
  // Theobald's approach: cumulativeCost from non-forest
  var notForest = mask.not().selfMask();
  
  var distToEdge = ee.Image(1)
    .cumulativeCost({
      source: notForest,
      maxDistance: maxEuclidean,
      geodeticDistance: true
    })
    .reproject({crs: proj, scale: scale});
  
  // ─── Step 2: Smooth distance with circular kernel ───
  // This finds "chunky" interior areas, not just far-from-edge pixels
  var kernel = ee.Kernel.circle({radius: radius, units: 'meters'});
  var distSmoothed = distToEdge
    .reduceNeighborhood({
      reducer: ee.Reducer.mean(),
      kernel: kernel,
      skipMasked: false
    })
    .reproject({crs: proj, scale: scale});
  
  // ─── Step 3: Identify Core pixels ───
  // Core = smoothed distance exceeds threshold
  var core = distSmoothed.gt(coreDistance)
    .updateMask(mask)
    .selfMask()
    .reproject({crs: proj, scale: scale});
  
  // ─── Step 4: Find Edge pixels ───
  // Edge = forest within edgeDistance of core (via cost distance through forest)
  var resistance = mask.remap([1], [1]);  // Only travel through forest
  var cdFromCore = resistance
    .cumulativeCost({
      source: core,
      maxDistance: edgeDistance,
      geodeticDistance: true
    })
    .reproject({crs: proj, scale: scale});
  
  var edge = cdFromCore.lt(edgeDistance)
    .and(mask)
    .and(core.unmask(0).not())  // Not already core
    .selfMask()
    .reproject({crs: proj, scale: scale});
  
  // ─── Step 5: Find Periphery pixels ───
  // Periphery = forest that is NOT core and NOT edge
  var periphery = mask
    .and(core.unmask(0).not())
    .and(edge.unmask(0).not())
    .selfMask()
    .reproject({crs: proj, scale: scale});
  
  // ─── Step 6: Combine into single classification ───
  // Core = 3, Edge = 2, Periphery = 1
  var classification = ee.Image(0)
    .where(periphery.unmask(0), 1)
    .where(edge.unmask(0), 2)
    .where(core.unmask(0), 3)
    .updateMask(mask)
    .rename('cepi')
    .reproject({crs: proj, scale: scale});
  
  return classification;
};

/**
 * Simplified CEPI using fastDistanceTransform (faster but less accurate for complex shapes)
 * 
 * @param {ee.Image} mask - Binary forest mask (1 = forest)
 * @param {Object} [options] - Classification options
 * @param {Number} [options.coreDistance=100] - Distance from edge to be "core" (meters)
 * @param {Number} [options.scale=30] - Pixel resolution (meters)
 * @returns {ee.Image} Classification with values: 3=core, 2=edge, 1=periphery
 */
exports.classifyFast = function(mask, options) {
  options = options || {};
  var coreDistance = options.coreDistance || 100;
  var scale = options.scale || 30;
  
  var proj = mask.projection();
  mask = mask.gt(0).unmask(0);
  
  // Neighborhood size for distance transform (in pixels)
  var neighborhood = Math.ceil(coreDistance * 2 / scale);
  
  // ─── Distance to edge using fastDistanceTransform ───
  // Source = non-forest pixels (value 1), forest = 0
  var nonForest = mask.not();
  
  var distToEdge = nonForest
    .fastDistanceTransform({neighborhood: neighborhood})
    .sqrt()
    .multiply(scale)  // Convert pixels to meters
    .reproject({crs: proj, scale: scale});
  
  // ─── Core: far from edge ───
  var core = distToEdge.gte(coreDistance)
    .updateMask(mask)
    .selfMask();
  
  // ─── Edge: adjacent to core ───
  var coreExpanded = core.unmask(0)
    .focal_max({radius: scale * 1.5, units: 'meters'})
    .reproject({crs: proj, scale: scale});
  
  var edge = coreExpanded
    .and(mask)
    .and(core.unmask(0).not())
    .selfMask();
  
  // ─── Periphery: remaining forest ───
  var periphery = mask
    .and(core.unmask(0).not())
    .and(edge.unmask(0).not())
    .selfMask();
  
  // ─── Combine ───
  return ee.Image(0)
    .where(periphery.unmask(0), 1)
    .where(edge.unmask(0), 2)
    .where(core.unmask(0), 3)
    .updateMask(mask)
    .rename('cepi')
    .reproject({crs: proj, scale: scale});
};

/**
 * Get visualization parameters for CEPI classification
 * @returns {Object} Visualization parameters for Map.addLayer
 */
exports.getVis = function() {
  return {
    min: 1,
    max: 3,
    palette: ['#FDE725', '#21918C', '#440154']  // Periphery=yellow, Edge=teal, Core=purple
  };
};

/**
 * Get legend labels
 * @returns {Object} Class values and labels
 */
exports.getLegend = function() {
  return {
    1: 'Periphery',
    2: 'Edge', 
    3: 'Core'
  };
};

// ============================================================================
// USAGE EXAMPLE
// ============================================================================

// // Get forest mask
// var forest = ee.Image('UMD/hansen/global_forest_change_2023_v1_11')
//   .select('treecover2000').gte(30);

// // Classify - core = 100m from edge
// var cepi = exports.classify(forest, {
//   coreDistance: 100,
//   scale: 30
// });

// // Or use fast version
// var cepiFast = exports.classifyFast(forest, {
//   coreDistance: 100,
//   scale: 30
// });

// // Visualize
// Map.addLayer(cepi, exports.getVis(), 'CEPI Classification');

/**
 * pff_connectivity.js
 * 
 * Connectivity filtering module for Primary Forest Finder (PFF)
 * Based on Dave's methodology: pre-clean inputs, morphological shrink→grow, patch-based filtering
 * 
 * Key concepts:
 * - Pre-clean anthropogenic layers BEFORE masking forest (erode small features)
 * - Apply morphological operations (erode then dilate) to clean forest edges
 * - Filter by connected patch area, not by pixel neighborhood density
 */

// ============================================================================
// MORPHOLOGICAL OPERATIONS
// ============================================================================

/**
 * Apply morphological erosion (shrink) to a binary mask
 * Uses focal_min which shrinks white (1) regions
 * 
 * @param {ee.Image} binaryMask - Binary image (0/1)
 * @param {Number} radiusMeters - Erosion radius in meters
 * @param {Number} pixelSize - Pixel size in meters for kernel calculation
 * @returns {ee.Image} Eroded binary mask
 */
exports.erode = function(binaryMask, radiusMeters) {
  if (radiusMeters <= 0) return binaryMask;
  
  // Use meters directly - works regardless of image resolution
  return binaryMask.focal_min({
    radius: radiusMeters,
    kernelType: 'circle',
    units: 'meters'
  });
};
// Debug viz:
// var geometry; // Define your geometry here
// var testMask = ee.Image('UMD/hansen/global_forest_change_2023_v1_11').select('treecover2000').gte(60);
// var eroded = exports.erode(testMask, 90);
// Map.addLayer(testMask, {min: 0, max: 1, palette: ['white', 'green']}, 'Original Mask', false);
// Map.addLayer(eroded, {min: 0, max: 1, palette: ['white', 'red']}, 'Eroded 90m', true);

/**
 * Apply morphological dilation (grow) to a binary mask
 * Uses focal_max which expands white (1) regions
 * 
 * @param {ee.Image} binaryMask - Binary image (0/1)
 * @param {Number} radiusMeters - Dilation radius in meters
 * @param {Number} pixelSize - Pixel size in meters for kernel calculation
 * @returns {ee.Image} Dilated binary mask
 */
exports.dilate = function(binaryMask, radiusMeters) {
  if (radiusMeters <= 0) return binaryMask;
  
  // Use meters directly - works regardless of image resolution
  return binaryMask.focal_max({
    radius: radiusMeters,
    kernelType: 'circle',
    units: 'meters'
  });
};
// Debug viz:
// var geometry; // Define your geometry here
// var testMask = ee.Image('UMD/hansen/global_forest_change_2023_v1_11').select('treecover2000').gte(60);
// var dilated = exports.dilate(testMask, 90);
// Map.addLayer(testMask, {min: 0, max: 1, palette: ['white', 'green']}, 'Original Mask', false);
// Map.addLayer(dilated, {min: 0, max: 1, palette: ['white', 'blue']}, 'Dilated 90m', true);

/**
 * Apply morphological opening (erode then dilate)
 * Removes small protrusions and thin connections
 * 
 * @param {ee.Image} binaryMask - Binary image (0/1)
 * @param {Number} radiusMeters - Radius in meters for both operations
 * @returns {ee.Image} Opened binary mask
 */
exports.open = function(binaryMask, radiusMeters) {
  var eroded = exports.erode(binaryMask, radiusMeters);
  return exports.dilate(eroded, radiusMeters);
};
// Debug viz:
// var geometry; // Define your geometry here
// var testMask = ee.Image('UMD/hansen/global_forest_change_2023_v1_11').select('treecover2000').gte(60);
// var opened = exports.open(testMask, 90);
// Map.addLayer(testMask, {min: 0, max: 1, palette: ['white', 'green']}, 'Original Mask', false);
// Map.addLayer(opened, {min: 0, max: 1, palette: ['white', 'orange']}, 'Opened 90m (erode→dilate)', true);

/**
 * Apply morphological closing (dilate then erode)
 * Fills small holes and gaps
 * 
 * @param {ee.Image} binaryMask - Binary image (0/1)
 * @param {Number} radiusMeters - Radius in meters for both operations
 * @returns {ee.Image} Closed binary mask
 */
exports.close = function(binaryMask, radiusMeters) {
  var dilated = exports.dilate(binaryMask, radiusMeters);
  return exports.erode(dilated, radiusMeters);
};
// Debug viz:
// var geometry; // Define your geometry here
// var testMask = ee.Image('UMD/hansen/global_forest_change_2023_v1_11').select('treecover2000').gte(60);
// var closed = exports.close(testMask, 90);
// Map.addLayer(testMask, {min: 0, max: 1, palette: ['white', 'green']}, 'Original Mask', false);
// Map.addLayer(closed, {min: 0, max: 1, palette: ['white', 'purple']}, 'Closed 90m (dilate→erode)', true);

/**
 * Apply custom morphological clean: erode then dilate with different radii
 * Dave's approach: shrink forest by X, then grow back by Y
 * If erodeRadius > dilateRadius: net shrinkage (more conservative)
 * If dilateRadius > erodeRadius: can reconnect nearby patches
 * 
 * @param {ee.Image} binaryMask - Binary image (0/1)
 * @param {Number} erodeRadiusMeters - Erosion radius in meters
 * @param {Number} dilateRadiusMeters - Dilation radius in meters
 * @returns {ee.Image} Cleaned binary mask
 */
exports.morphologicalClean = function(binaryMask, erodeRadiusMeters, dilateRadiusMeters) {
  var eroded = exports.erode(binaryMask, erodeRadiusMeters);
  return exports.dilate(eroded, dilateRadiusMeters);
};
// Debug viz:
// var geometry; // Define your geometry here
// var testMask = ee.Image('UMD/hansen/global_forest_change_2023_v1_11').select('treecover2000').gte(60);
// var cleaned = exports.morphologicalClean(testMask, 90, 90);
// Map.addLayer(testMask, {min: 0, max: 1, palette: ['white', 'green']}, 'Original Mask', false);
// Map.addLayer(cleaned, {min: 0, max: 1, palette: ['white', 'darkgreen']}, 'Morph Cleaned 90m/90m', true);

// ============================================================================
// CONNECTED COMPONENT / PATCH FILTERING
// ============================================================================

/**
 * Filter binary mask to keep only patches >= minimum area
 * Uses connected components with pixelArea() for resolution-independent area calculation.
 * 
 * @param {ee.Image} binaryMask - Binary image (0/1) to filter
 * @param {Number} minAreaHa - Minimum patch area in hectares
 * @param {Object} options - Optional parameters
 * @param {Number} options.maxPatchSize - Max size for component labeling (default: 65536, ~5900ha)
 * @param {ee.Image} options.countryMask - Optional mask to clip results
 * @returns {ee.Image} Filtered binary mask with only large patches
 */
exports.filterByPatchArea = function(binaryMask, minAreaHa, options) {
  options = options || {};
  // GEE limit: maxSize must be in range (0, 1024]
  // At 30m: 1024 pixels * 900m²/pixel = 921,600 m² = ~92 ha
  var maxPatchSize = options.maxPatchSize || 1024;
  
  // Convert hectares to m²
  var minAreaM2 = minAreaHa * 10000;
  
  // Label connected components
  var components = binaryMask.selfMask().connectedComponents({
    connectedness: ee.Kernel.plus(1),
    maxSize: maxPatchSize
  });
  
  // Use pixelArea() for resolution-independent area calculation
  var pixelArea = ee.Image.pixelArea();
  
  // Sum area per component using reduceConnectedComponents
  var patchAreas = pixelArea.addBands(components.select('labels'))
    .reduceConnectedComponents({
      reducer: ee.Reducer.sum(),
      labelBand: 'labels',
      maxSize: maxPatchSize
    });
  
  // Keep only patches >= minimum area
  var largePatchMask = patchAreas.gte(minAreaM2);
  
  // Apply country mask if provided
  if (options.countryMask) {
    largePatchMask = largePatchMask.updateMask(options.countryMask);
  }
  
  return largePatchMask.unmask(0).rename('filtered');
};
// Debug viz:
// var geometry; // Define your geometry here
// var testMask = ee.Image('UMD/hansen/global_forest_change_2023_v1_11').select('treecover2000').gte(60);
// var filtered = exports.filterByPatchArea(testMask, 50, {maxPatchSize: 1024});
// Map.addLayer(filtered, {min: 0, max: 1, palette: ['white', 'darkgreen']}, 'Patches >=50ha', true);

/**
 * Alternative patch filter using reduceConnectedComponents for area calculation
 * More accurate for irregular shapes but slower
 * 
 * @param {ee.Image} binaryMask - Binary image (0/1) to filter
 * @param {Number} minAreaHa - Minimum patch area in hectares
 * @param {Number} pixelSize - Pixel size in meters
 * @returns {ee.Image} Filtered binary mask
 */
exports.filterByPatchAreaAccurate = function(binaryMask, minAreaHa, pixelSize) {
  pixelSize = pixelSize || 30;
  var minAreaM2 = minAreaHa * 10000;
  
  // Create pixel area image
  var pixelArea = ee.Image.pixelArea();
  
  // Label connected components
  var components = binaryMask.selfMask().connectedComponents({
    connectedness: ee.Kernel.plus(1),
    maxSize: 1024
  });
  
  // Sum area per component
  var patchAreas = pixelArea.addBands(components.select('labels'))
    .reduceConnectedComponents({
      reducer: ee.Reducer.sum(),
      labelBand: 'labels',
      maxSize: 1024
    });
  
  // Keep only patches >= minimum area
  return patchAreas.gte(minAreaM2).rename('filtered');
};
// Debug viz:
// var geometry; // Define your geometry here
// var testMask = ee.Image('UMD/hansen/global_forest_change_2023_v1_11').select('treecover2000').gte(60);
// var filtered = exports.filterByPatchAreaAccurate(testMask, 50, 30);
// Map.addLayer(testMask, {min: 0, max: 1, palette: ['white', 'green']}, 'Original Mask', false);
// Map.addLayer(filtered, {min: 0, max: 1, palette: ['white', 'darkgreen']}, 'Patches >=50ha (accurate)', true);

/**
 * Filter patches by area using vector conversion (reduceToVectors)
 * Use this when minAreaHa exceeds the connected components limit (~92ha at 30m, 1024 pixels)
 * 
 * This runs on output of CC approach when threshold exceeds CC limit.
 * 
 * LIMITS:
 * - reduceToVectors maxPixels: default 1e9, max 1e13 (1e8 covers ~90,000ha at 30m)
 * - Geometry complexity: polygons with too many vertices may fail
 * - FeatureCollection size: ~10 million features max
 * - Computation timeout: ~5 minutes server-side
 * - bestEffort=true can coarsen scale, potentially affecting results
 * - For very large areas, consider using tileScale option
 * 
 * @param {ee.Image} binaryMask - Binary image (0/1) to filter
 * @param {Number} minAreaHa - Minimum patch area in hectares
 * @param {Object} options - Optional parameters
 * @param {Number} options.scale - Scale for vectorization in meters (default: 30)
 * @param {ee.Geometry} options.geometry - Region to process (required for large areas)
 * @param {Number} options.maxPixels - Max pixels for reduceToVectors (default: 1e9, max: 1e13)
 * @param {Boolean} options.bestEffort - If true, use larger scale if needed (default: false)
 * @param {Number} options.tileScale - Tile scale factor 1-16, higher = less memory per tile (default: 1)
 * @returns {ee.Image} Filtered binary mask with only large patches
 */
exports.filterByPatchAreaVector = function(binaryMask, minAreaHa, options) {
  options = options || {};
  var scale = options.scale || 30;
  var maxPixels = options.maxPixels || 1e9;  // Increased from 1e8, covers ~900,000 ha
  var bestEffort = options.bestEffort !== undefined ? options.bestEffort : false;  // Changed to false
  var tileScale = options.tileScale || 1;
  
  // Convert hectares to m²
  var minAreaM2 = minAreaHa * 10000;
  
  // Convert binary mask to vectors
  var vectors = binaryMask.selfMask().reduceToVectors({
    reducer: ee.Reducer.countEvery(),
    geometry: options.geometry,
    scale: scale,
    maxPixels: maxPixels,
    bestEffort: bestEffort,
    tileScale: tileScale,
    geometryType: 'polygon',
    eightConnected: false,
    labelProperty: 'zone'
  });
  
  // Calculate area in hectares for each polygon (computed property)
  var withArea = vectors.map(function(feature) {
    var areaM2 = feature.geometry().area(scale); // area in m², error margin = scale
    var areaHa = ee.Number(areaM2).divide(10000);
    return feature.set('area_ha', areaHa, 'area_m2', areaM2);
  });
  
  // Filter to keep only polygons >= minimum area
  var largePatches = withArea.filter(ee.Filter.gte('area_m2', minAreaM2));
  
  // Convert back to raster
  var filtered = largePatches
    .reduceToImage(['zone'], ee.Reducer.first())
    .gt(0)
    .unmask(0)
    .rename('filtered');
  
  return filtered;
};
// Debug viz:
// var geometry; // Define your geometry here, e.g.: ee.Geometry.Rectangle([-60, -5, -55, 0])
// var testMask = ee.Image('UMD/hansen/global_forest_change_2023_v1_11').select('treecover2000').gte(60);
// var filtered = exports.filterByPatchAreaVector(testMask, 500, {scale: 30, geometry: geometry});
// Map.addLayer(testMask.clip(geometry), {min: 0, max: 1, palette: ['white', 'green']}, 'Original Mask', false);
// Map.addLayer(filtered.clip(geometry), {min: 0, max: 1, palette: ['white', 'darkgreen']}, 'Patches >=500ha (vector)', true);
// Map.centerObject(geometry, 8);

/**
 * Smart patch area filter - auto-chooses CC or CC+vector method based on threshold
 * 
 * Strategy:
 * - If threshold <= CC limit (~5900ha at 30m): Use CC only (fast)
 * - If threshold > CC limit: Use CC prefilter + vector (accurate for large patches)
 * 
 * CC prefilter removes small patches quickly, then vector accurately measures 
 * remaining patches. Large patches pass CC even with truncated area measurement.
 * 
 * @param {ee.Image} binaryMask - Binary image (0/1) to filter
 * @param {Number} minAreaHa - Minimum patch area in hectares
 * @param {Object} options - Optional parameters
 * @param {Number} options.scale - Scale for vector method in meters (default: 30)
 * @param {Number} options.maxPatchSize - Max CC size in pixels (default: 1024, max ~92ha at 30m)
 * @param {ee.Geometry} options.geometry - Recommended for vector method on large areas
 * @param {ee.Image} options.countryMask - Optional mask to clip results
 * @param {Number} options.maxPixels - Max pixels for vector method (default: 1e9)
 * @param {Number} options.tileScale - Tile scale for vector method 1-16 (default: 1)
 * @returns {ee.Image} Filtered binary mask
 */
exports.filterByPatchAreaSmart = function(binaryMask, minAreaHa, options) {
  options = options || {};
  var scale = options.scale || 30;
  // GEE limit: maxSize must be in range (0, 1024]
  // At 30m: 1024 pixels * 900m²/pixel = 921,600 m² = ~92 ha
  var maxPatchSize = options.maxPatchSize || 1024;
  
  // CC limit based on NATIVE resolution (30m for Hansen), not scale parameter
  // At 30m: 1024 pixels * 900m²/pixel = 921,600 m² = ~92 ha
  var nativePixelSize = 30; // Hansen/Landsat native resolution
  var maxCCAreaHa = (maxPatchSize * nativePixelSize * nativePixelSize) / 10000;
  
  var filtered;
  
  if (minAreaHa <= maxCCAreaHa) {
    // Use connected components (works for smaller thresholds)
    print('filterByPatchAreaSmart: Using CC approach (threshold: ' + 
          minAreaHa + 'ha <= limit: ' + maxCCAreaHa.toFixed(0) + 'ha)');
    filtered = exports.filterByPatchArea(binaryMask, minAreaHa, {
      maxPatchSize: maxPatchSize,
      countryMask: options.countryMask
    });
  } else {
    // Use CC as prefilter then vector for accurate large-patch filtering
    // CC keeps patches >= threshold (even if large ones have truncated area measurement)
    // Vector then accurately measures the remaining patches
    print('filterByPatchAreaSmart: Using CC prefilter + vector approach (threshold: ' + 
          minAreaHa + 'ha > CC limit: ' + maxCCAreaHa.toFixed(0) + 'ha)');
    if (!options.geometry) {
      print('WARNING: geometry option recommended for vector approach on large areas');
    }
    
    // Step 1: CC prefilter - removes small fragments quickly
    // IMPORTANT: Use CC limit as threshold, NOT user's threshold!
    // Large patches (>92ha) have truncated area measurement, so using minAreaHa
    // would incorrectly filter them out. Using maxCCAreaHa keeps all patches
    // that MIGHT be >= minAreaHa for accurate vector measurement.
    var prefiltered = exports.filterByPatchArea(binaryMask, maxCCAreaHa, {
      maxPatchSize: maxPatchSize,
      countryMask: options.countryMask
    });
    
    // Step 2: Vector - accurately filters remaining patches by area
    filtered = exports.filterByPatchAreaVector(prefiltered, minAreaHa, {
      scale: scale,
      geometry: options.geometry,
      maxPixels: options.maxPixels,
      tileScale: options.tileScale,
      bestEffort: false
    });
    
    // Apply country mask if provided (vector method doesn't have this option)
    if (options.countryMask) {
      filtered = filtered.updateMask(options.countryMask);
    }
  }
  
  return filtered;
};

// ============================================================================
// GLAD LULC FOREST MASK HELPER
// ============================================================================

/**
 * Prepare GLAD LULC forest mask from tree height classes
 * 
 * @param {Number} analysisYear - Year to analyze (e.g., 2020)
 * @param {Number} treeHeightThreshold - Minimum tree height in meters
 * @returns {ee.Image} Binary forest mask
 */
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

exports.gladLulcForestPrep = gladLulcForestPrep;

// ============================================================================
// DEBUG / TEST VISUALIZATION
// ============================================================================

// var geometry; // Define your geometry here, e.g.: ee.Geometry.Rectangle([-60, -5, -55, 0])
// var testMask = gladLulcForestPrep(2020, 5);
// var filtered = exports.filterByPatchAreaSmart(testMask, 500, {geometry: geometry});
// Map.addLayer(testMask.clip(geometry), {min: 0, max: 1, palette: ['white', 'lightgreen']}, 'Forest Mask', true);
// Map.addLayer(filtered.clip(geometry), {min: 0, max: 1, palette: ['white', 'darkgreen']}, 'Patches >=500ha', true);
// Map.centerObject(geometry, 8);

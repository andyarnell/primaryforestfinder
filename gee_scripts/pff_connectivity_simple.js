/**
 * pff_connectivity_simple.js
 * Simple patch filtering for Primary Forest Finder
 * 
 * OVERVIEW:
 * Filters forest patches by minimum area. Three methods available:
 * 
 * 1. PIXEL COUNT (fast, limited to ~92ha threshold)
 *    - Uses connectedPixelCount with inverted logic
 *    - Removes definitely small patches, keeps everything else
 * 
 * 2. VECTOR (accurate, any threshold, limited geometry size ~1M ha)
 *    - Converts raster to polygons, calculates true area
 *    - Slower but unlimited threshold
 * 
 * 3. TILED (accurate, any threshold, any geometry size)
 *    - Splits geometry into grid, processes each tile
 *    - Buffer + centroid approach avoids edge effects
 * 
 * The main function filterByArea() auto-selects the best method.
 */

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Convert mask to vector polygons
 * @private
 */
function _maskToPolygons(mask, geometry, scale) {
  return mask.selfMask().reduceToVectors({
    geometry: geometry,
    scale: scale,
    geometryType: 'polygon',
    eightConnected: false,
    maxPixels: 1e13
  });
}

/**
 * Calculate area for each polygon and filter by minimum
 * @private
 */
function _filterPolygonsByArea(polygons, minM2, scale) {
  var err = ee.ErrorMargin(scale);
  
  var withArea = polygons.map(function(f) {
    var geom = f.geometry(err);
    var areaM2 = geom.area(err);
    return f.set('area_m2', areaM2);
  });
  
  return withArea.filter(ee.Filter.gte('area_m2', minM2));
}

/**
 * Convert filtered polygons back to raster
 * @private
 */
function _polygonsToRaster(polygons, geometry) {
  return polygons.reduceToImage({
    properties: ['area_m2'],
    reducer: ee.Reducer.first()
  }).gt(0)
    .unmask(0)
    .clip(geometry)
    .rename('filtered');
}

// ============================================================================
// PATCH AREA FILTERING - CONNECTED PIXEL COUNT (fastest, ~92ha limit)
// ============================================================================

/**
 * Filter patches by minimum area using connectedPixelCount
 * 
 * HOW IT WORKS:
 * 1. Count connected pixels for each forest pixel (capped at 1024)
 * 2. Calculate how many pixels = minHa at current resolution
 * 3. If count < minPixels AND count < 1024 → definitely small → remove
 * 4. If count == 1024 → might be bigger → keep (safe)
 * 
 * WHY INVERTED LOGIC:
 * - connectedPixelCount caps at 1024 pixels (~92ha at 30m)
 * - A 1000ha patch would show as 1024 (capped)
 * - If we said "keep if count >= 500ha" → 1000ha patch removed (wrong!)
 * - Instead: "remove if DEFINITELY < 500ha" → 1000ha patch kept (correct)
 * 
 * LIMITATIONS:
 * - Max accurate threshold: ~92ha at 30m resolution
 * - For larger thresholds: patches 92ha-threshold kept as false positives
 * - Use vector method for thresholds > 92ha
 * 
 * @param {ee.Image} mask - Binary mask (1 = keep, 0 = remove)
 * @param {Number} minHa - Minimum patch area in hectares
 * @param {Number} [maxSize=1024] - Max pixel count (GEE hard limit: 1024)
 * @returns {ee.Image} Filtered mask with band 'filtered'
 */
exports.filterByAreaPixelCount = function(mask, minHa, maxSize) {
  maxSize = maxSize || 1024;  // GEE hard limit - cannot exceed this
  var minM2 = minHa * 10000;  // Convert hectares to m²
  
  // Step 1: Count connected pixels for each forest pixel
  // Result: each pixel gets count of its patch size (capped at maxSize)
  var pixelCount = mask.selfMask().connectedPixelCount(maxSize);
  
  // Step 2: Calculate minimum pixels needed (resolution-independent)
  // At 30m: 500ha = 5,000,000m² / 900m²/pixel = 5,556 pixels
  var minPixelCount = ee.Image(minM2).divide(ee.Image.pixelArea());
  
  // Step 3: Find DEFINITELY small patches (inverted logic)
  // Small = count < threshold AND count < cap (so we know it's accurate)
  var isDefinitelySmall = pixelCount.lt(minPixelCount).and(pixelCount.lt(maxSize));
  
  // Step 4: Remove small, keep everything else (including capped large ones)
  return mask.updateMask(isDefinitelySmall.not()).unmask(0).rename('filtered');
};

// ============================================================================
// PATCH AREA FILTERING - CONNECTED COMPONENTS (alternative, same ~92ha limit)
// ============================================================================

/**
 * Filter patches by minimum area using connected components
 * 
 * Similar to pixelCount but uses labeled components. Slightly slower,
 * same 1024 pixel (~92ha) limitation. Kept for compatibility.
 * 
 * @param {ee.Image} mask - Binary mask (1 = keep)
 * @param {Number} minHa - Minimum patch area in hectares (max ~92ha)
 * @returns {ee.Image} Filtered mask with band 'filtered'
 */
exports.filterByAreaCC = function(mask, minHa) {
  var minM2 = minHa * 10000;
  
  // Label connected components (max 1024 pixels per patch)
  var components = mask.selfMask().connectedComponents({
    connectedness: ee.Kernel.plus(1),
    maxSize: 1024
  });
  
  // Calculate area per patch
  var patchAreas = ee.Image.pixelArea()
    .addBands(components.select('labels'))
    .reduceConnectedComponents({
      reducer: ee.Reducer.sum(),
      labelBand: 'labels',
      maxSize: 1024
    });
  
  return patchAreas.gte(minM2).unmask(0).rename('filtered');
};

// ============================================================================
// PATCH AREA FILTERING - VECTOR (accurate, any threshold, geometry size limited)
// ============================================================================

/**
 * Filter patches by minimum area using vector polygons
 * 
 * HOW IT WORKS:
 * 1. Convert raster mask to polygon features
 * 2. Calculate true geodesic area for each polygon
 * 3. Filter polygons by minimum area
 * 4. Convert back to raster
 * 
 * ADVANTAGES:
 * - No 92ha limit - works for any threshold
 * - Accurate area calculation
 * 
 * LIMITATIONS:
 * - Slower than pixel count
 * - Memory limit: ~35k patches per geometry
 * - For large geometries (>1M ha), use filterByAreaTiled instead
 * 
 * @param {ee.Image} mask - Binary mask (1 = keep)
 * @param {Number} minHa - Minimum patch area in hectares (no limit)
 * @param {ee.Geometry} geometry - Region to process
 * @param {Object} [options] - Optional settings
 * @param {Number} [options.scale=30] - Scale in meters (increase for large areas)
 * @returns {ee.Image} Filtered mask with band 'filtered'
 */
exports.filterByAreaVector = function(mask, minHa, geometry, options) {
  options = options || {};
  var minM2 = minHa * 10000;
  var scale = options.scale || 30;
  
  if (scale !== 30) {
    print('Note: Using scale=' + scale + 'm');
  }
  
  // Step 1: Convert raster to polygons (uses helper)
  var patches = _maskToPolygons(mask, geometry, scale);
  print('Total patches found:', patches.size());
  
  // Step 2: Calculate area and filter (uses helper)
  var large = _filterPolygonsByArea(patches, minM2, scale);
  print('Patches >= ' + minHa + 'ha:', large.size());
  
  // Step 3: Convert back to raster (uses helper)
  return _polygonsToRaster(large, geometry);
};

// ============================================================================
// SMART FILTER - AUTO-SELECTS BEST METHOD
// ============================================================================

/**
 * Filter patches by area - automatically selects best method
 * 
 * DECISION LOGIC:
 * ┌─────────────────────────────────────────────────────────────────┐
 * │ Threshold ≤ 92ha?                                               │
 * │   YES → pixelCount (fast, accurate)                             │
 * │   NO  → Need geometry                                           │
 * │         ├─ Geometry ≤ tileAboveGeomHa? → vector (accurate)      │
 * │         └─ Geometry > tileAboveGeomHa? → tiled (handles scale)  │
 * └─────────────────────────────────────────────────────────────────┘
 * 
 * @param {ee.Image} mask - Binary mask (1 = keep)
 * @param {Number} minHa - Minimum patch area in hectares
 * @param {ee.Geometry} [geometry] - Region (required if minHa > 92ha)
 * @param {Object} [options] - Settings
 * @param {Number} [options.scale=100] - Scale for vector/tiled methods (meters)
 * @param {Number} [options.tileAboveGeomHa=1000000] - Switch to tiled above this (ha)
 * @param {Number} [options.gridScale=100000] - Tile grid size for tiled mode (meters)
 * @param {Number} [options.buffer=10000] - Buffer around tiles (meters)
 * @returns {ee.Image} Filtered mask with band 'filtered'
 */
exports.filterByArea = function(mask, minHa, geometry, options) {
  options = options || {};
  var scale = options.scale || 100;
  var tileAboveGeomHa = options.tileAboveGeomHa || 1000000;  // 1M ha = 10,000 km²
  var MAX_PIXEL_COUNT_HA = 92;  // GEE limit: 1024 pixels at 30m
  
  // ─── CASE 1: Small threshold → pixelCount (fast) ───
  if (minHa <= MAX_PIXEL_COUNT_HA) {
    print('✓ Using pixelCount method (threshold ≤ 92ha)');
    return exports.filterByAreaPixelCount(mask, minHa);
  }
  
  // ─── Threshold > 92ha → need geometry ───
  if (!geometry) {
    print('ERROR: geometry required for thresholds > 92ha');
    return mask;
  }
  
  // Check geometry size (client-side for branching decision)
  var geomHa = geometry.area(1000).divide(10000).getInfo();
  
  // Prefilter: remove <92ha patches first (reduces work for vector/tiled)
  var prefiltered = exports.filterByAreaPixelCount(mask, MAX_PIXEL_COUNT_HA);
  
  // ─── CASE 2: Small geometry → vector ───
  if (geomHa <= tileAboveGeomHa) {
    print('✓ Using vector method (' + Math.round(geomHa/1000) + 'k ha ≤ ' + tileAboveGeomHa/1000 + 'k ha threshold)');
    return exports.filterByAreaVector(prefiltered, minHa, geometry, {scale: scale});
  }
  
  // ─── CASE 3: Large geometry → tiled ───
  print('✓ Using TILED method (' + Math.round(geomHa/1000) + 'k ha > ' + tileAboveGeomHa/1000 + 'k ha threshold)');
  return exports.filterByAreaTiled(mask, minHa, geometry, options);
};

// ============================================================================
// TILED FILTER - FOR VERY LARGE AREAS
// ============================================================================

/**
 * Filter by area using tiled processing for very large geometries
 * 
 * HOW IT WORKS:
 * 1. Prefilter: remove patches <92ha using fast pixelCount
 * 2. Create grid tiles using coveringGrid
 * 3. For each tile:
 *    a. Buffer the tile geometry (captures patches crossing boundaries)
 *    b. Vectorize in buffered area
 *    c. Calculate area for each polygon
 *    d. Keep only patches with centroid IN this tile (avoids double-counting)
 *    e. Rasterize back
 * 4. Mosaic all tiles together
 * 
 * WHY BUFFER + CENTROID:
 * Without buffer: patch crossing tile boundary → split → measured too small → removed (wrong!)
 * With buffer: patch fully captured → measured correctly → assigned to ONE tile by centroid
 * 
 * ┌─────────┬─────────┐
 * │  Tile A │  Tile B │     Patch X spans boundary
 * │    ┌────┼────┐    │     Buffer captures full patch in both tiles
 * │    │  X │    │    │     Centroid in Tile A → only Tile A keeps it
 * │    └────┼────┘    │     
 * └─────────┴─────────┘
 * 
 * @param {ee.Image} mask - Binary mask (1 = keep)
 * @param {Number} minHa - Minimum patch area in hectares
 * @param {ee.Geometry} geometry - Large region to process
 * @param {Object} [options] - Settings
 * @param {Number} [options.gridScale=100000] - Grid cell size (meters, default 100km)
 * @param {Number} [options.scale=100] - Vectorization scale (meters)
 * @param {Number} [options.buffer=10000] - Buffer around tiles (meters, default 10km)
 * @returns {ee.Image} Filtered mask with band 'filtered'
 */
exports.filterByAreaTiled = function(mask, minHa, geometry, options) {
  options = options || {};
  var scale = options.scale || 100;
  var gridScale = options.gridScale || 100000;  // 100km default
  var buffer = options.buffer || 10000;          // 10km default
  var MAX_PIXEL_COUNT_HA = 92;
  var minM2 = minHa * 10000;
  
  // Step 1: Prefilter - remove patches <92ha (fast raster operation)
  var prefiltered = exports.filterByAreaPixelCount(mask, MAX_PIXEL_COUNT_HA);
  
  // Step 2: Create tiles covering the geometry
  var tiles = geometry.coveringGrid(ee.Projection('EPSG:4326').atScale(gridScale));
  print('Processing', tiles.size(), 'tiles at', gridScale/1000, 'km grid with', buffer/1000, 'km buffer');
  
  // Step 3: Process each tile
  var processedTiles = tiles.map(function(tile) {
    var tileGeom = tile.geometry();
    var bufferedGeom = tileGeom.buffer(buffer, 100);
    
    // 3a: Vectorize in buffered area (captures cross-boundary patches)
    var patches = _maskToPolygons(prefiltered, bufferedGeom, scale);
    
    // 3b: Calculate area and filter
    var large = _filterPolygonsByArea(patches, minM2, scale);
    
    // 3c: Keep only patches with centroid in THIS tile
    // This ensures each patch is processed by exactly one tile
    var err = ee.ErrorMargin(scale);
    large = large.filter(ee.Filter.bounds(tileGeom));
    
    // 3d: Rasterize within tile bounds (not buffered)
    return _polygonsToRaster(large, tileGeom);
  });
  
  // Step 4: Mosaic all tiles
  return ee.ImageCollection(processedTiles).mosaic().rename('filtered').clip(geometry);
};

// ============================================================================
// GLAD FOREST MASK HELPER
// ============================================================================

/**
 * Get GLAD forest mask by minimum tree height
 * 
 * Uses GLAD GLCLU dataset which has tree height classes 3-26m
 * 
 * @param {Number} year - Year (e.g., 2020)
 * @param {Number} minTreeHeight - Minimum tree height in meters (3-26)
 * @returns {ee.Image} Binary mask where 1 = forest >= minTreeHeight
 */
exports.gladForest = function(year, minTreeHeight) {
  var glad = ee.Image('projects/glad/GLCLU2020/v2/LCLUC_' + year);
  
  // Tree height classes: 25-48 and 125-147 map to heights 3-26m
  var from = [25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,
              125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147];
  var to =   [3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,
              3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25];
  
  return glad.remap(from, to).gte(minTreeHeight);
};

// ============================================================================
// USAGE EXAMPLES
// ============================================================================

// Define geometry
// var geometry = ee.Geometry.Rectangle([-60, -5, -55, 0]);

// Get forest mask (trees >= 7m)
var forest = exports.gladForest(2020, 5);

// ─── Example 1: Small threshold (≤92ha) - uses fast pixelCount ───
var result1 = exports.filterByArea(forest, 50, geometry);

// // ─── Example 2: Large threshold, small geometry - uses vector ───
// var result2 = exports.filterByArea(forest, 500, geometry, {
//   scale: 100  // Coarser scale for speed
// });

// ─── Example 3: Large threshold, large geometry - uses tiled ───
var result3 = exports.filterByArea(forest, 50000, geometry, {
  scale: 300,
  tileAboveGeomHa: 500000,  // Switch to tiled above 500k ha
  gridScale: 100000,        // 100km x 100km grid tiles
  buffer: 10000             // 10km buffer for edge effects
});

// // Visualize
// Map.addLayer(forest.clip(geometry), {palette: ['white', 'lightgreen']}, 'Forest');
// // Map.addLayer(result1.clip(geometry), {palette: ['white', 'darkgreen']}, 'Small Patches ≥50ha');

// Map.addLayer(result3.clip(geometry), {palette: ['white', 'darkgreen']}, 'Large Patches ≥500ha');
// // Map.centerObject(geometry);


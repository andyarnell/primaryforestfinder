/**
 * preprocessDataset.js
 *
 * Generic preprocessing for national / custom datasets.
 * Converts raw GEE assets (images, image collections, feature collections)
 * into binary 0/1 ee.Image objects suitable for the PFF pipeline.
 *
 * Supported preprocessing operations (via config object):
 *   band         - select a single band by name or index
 *   classes      - reclassify a list of class values to 1, all others to 0
 *   threshold    - binarize a continuous raster ({min}, {max}, or both)
 *   filter       - select vector features by attribute field + value list
 *   year_filter  - filter an image collection by a year property
 *   mosaic       - reduce a multi-image collection to a single image (.max)
 *
 * Operations NOT handled here (covered elsewhere in the PFF pipeline):
 *   - Distance buffering  (makeDistanceBuffer)
 *   - Forward-fill        (forwardFillBinaryTimeSeries)
 *   - Clip to AOI         (pipeline-level)
 *   - Reproject / resample (GEE implicit)
 *   - NoData cleanup      (.unmask(0) applied at the end of this function)
 */

/**
 * Apply preprocessing steps to a raw GEE asset based on a config object.
 *
 * @param {string} assetPath - GEE asset path (e.g. 'users/someone/roads_2020')
 * @param {Object} [preprocessing={}] - Config object with optional keys:
 *   {string|number} band - Band name or 0-based index to select
 *   {number[]} classes - List of class values to reclassify to 1
 *   {Object} threshold - {min: number} and/or {max: number}
 *   {Object} filter - {field: string, values: string[]} for vector filtering
 *   {Object} year_filter - {field: string, value: number} for collection filtering
 *   {boolean} mosaic - If true, reduce collection with .max()
 * @param {string} [sourceType='image'] - 'image', 'image_collection', or 'feature_collection' (alias: 'table')
 * @return {ee.Image} Binary image (0 = absence, 1 = presence), single band named 'presence'
 */
exports.preprocessAsset = function(assetPath, preprocessing, sourceType) {
  preprocessing = preprocessing || {};
  sourceType = sourceType || 'image';

  var result;

  // ---------------------------------------------------------------
  // Load asset by type
  // ---------------------------------------------------------------
  if (sourceType === 'feature_collection' || sourceType === 'table') {
    // Vector: FeatureCollection (polygons, lines, or points)
    var fc = ee.FeatureCollection(assetPath);

    // Attribute filter (e.g. select road types by highway tag)
    if (preprocessing.filter) {
      fc = fc.filter(ee.Filter.inList(
        preprocessing.filter.field,
        preprocessing.filter.values
      ));
    }

    // Rasterize to binary — paint features as 1, background 0.
    // For point/line features the distance buffer step in the main
    // pipeline expands their single-pixel footprint to the configured
    // threshold, so no pre-buffering is needed here or at least if 
    // this isnt feasible due to being mixed with othetr datasets that are already the correct width, they should be processed before GEE upload to have the correct width. 
    result = ee.Image(0).byte()
      .paint(fc, 1)
      .rename('presence');

  } else if (sourceType === 'image_collection') {
    // ImageCollection: tiled datasets or time-series
    var ic = ee.ImageCollection(assetPath);

    // Year filter (e.g. pick images where property 'year' == 2020)
    if (preprocessing.year_filter) {
      ic = ic.filter(ee.Filter.eq(
        preprocessing.year_filter.field,
        preprocessing.year_filter.value
      ));
    }

    // Mosaic tiles — .max() for binary layers (equivalent to OR)
    if (preprocessing.mosaic) {
      result = ic.max();
    } else {
      result = ic.first();
    }

  } else {
    // Single ee.Image (most common case)
    result = ee.Image(assetPath);
  }

  // ---------------------------------------------------------------
  // Band selection
  // ---------------------------------------------------------------
  if (preprocessing.band !== undefined) {
    result = result.select(preprocessing.band);
  }

  // ---------------------------------------------------------------
  // Class selection: reclassify categorical raster to binary
  // e.g. classes [1, 2, 5] from an LULC map → 1, everything else → 0
  // ---------------------------------------------------------------
  if (preprocessing.classes) {
    var classes = preprocessing.classes;
    var ones = ee.List.repeat(1, classes.length);
    result = result.remap(classes, ones, 0).gt(0);
  }

  // ---------------------------------------------------------------
  // Threshold a continuous value to binary
  // e.g. canopy cover >= 30%  → {min: 30}
  //      slope <= 45°         → {max: 45}
  //      height 10–80 m       → {min: 10, max: 80}
  // ---------------------------------------------------------------
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

  // ---------------------------------------------------------------
  // Ensure binary output and clean NoData
  // .gt(0) normalises any non-zero values to 1
  // .unmask(0) fills masked pixels with 0 (absence)
  // ---------------------------------------------------------------
  result = result.gt(0).unmask(0).byte().rename('presence');

  return result;
};


// ---------------------------------------------------------------
// Visualization helper (commented out — uncomment for debugging)
// ---------------------------------------------------------------
// exports.vizPreprocessed = function(assetPath, preprocessing, sourceType) {
//   var img = exports.preprocessAsset(assetPath, preprocessing, sourceType);
//   Map.addLayer(img, {min: 0, max: 1, palette: ['white', 'red']}, 'preprocessed');
//   return img;
// };


// ---------------------------------------------------------------
// Import forward-fill from timeSeriesAnthro
// ---------------------------------------------------------------
var timeSeriesAnthro = require('users/andyarnellgee/apps:modules/timeSeriesAnthro');
var forwardFillBinaryTimeSeries = timeSeriesAnthro.forwardFillBinaryTimeSeries;


/**
 * Build an ImageCollection from a dataset config object (JSON pattern D).
 * Each asset is preprocessed to binary, tagged with year metadata, and
 * optionally forward-filled.
 *
 * @param {Object} ds - Single dataset config with keys:
 *   {string} name - Human-readable identifier
 *   {string} category - Pipeline role (e.g. 'roads_major', 'agriculture')
 *   {string} [source_type='image'] - 'image', 'image_collection', or 'feature_collection'
 *   {Object} [preprocessing={}] - Preprocessing config for preprocessAsset()
 *   {Object} assets - Map of year strings to GEE asset paths, e.g. {"2020": "users/..."}
 *   {number} threshold_m - Distance buffer in metres
 *   {boolean} [forward_fill=false] - Apply cumulative forward-fill across years
 * @param {number[]} targetYears - e.g. [1990, 2000, 2010, 2015, 2020]
 * @return {Object} {collection: ee.ImageCollection, threshold: number, name: string}
 */
exports.buildDatasetFromConfig = function(ds, targetYears) {
  var sourceType = ds.source_type || 'image';
  var preprocessing = ds.preprocessing || {};

  // Build one binary image per year from asset paths
  var images = Object.keys(ds.assets).map(function(yearStr) {
    var year = parseInt(yearStr, 10);
    var img = exports.preprocessAsset(ds.assets[yearStr], preprocessing, sourceType);
    return img.set({
      'year': year,
      'system:time_start': ee.Date.fromYMD(year, 1, 1).millis(),
      'system:index': yearStr
    });
  });
  var collection = ee.ImageCollection.fromImages(images);

  // Forward-fill if specified (once present, stays present)
  if (ds.forward_fill) {
    collection = forwardFillBinaryTimeSeries(collection, targetYears);
  }

  return {
    collection: collection,
    threshold: ds.threshold_m,
    name: ds.name
  };
};


/**
 * Apply a full datasets config array (JSON pattern D).
 * Returns an object keyed by category, each with {collection, threshold, name}.
 *
 * @param {Object[]} datasets - Array of dataset config objects
 * @param {number[]} targetYears - e.g. [1990, 2000, 2010, 2015, 2020]
 * @return {Object} Map of category → {collection, threshold, name}
 */
exports.applyDatasetConfig = function(datasets, targetYears) {
  var result = {};
  datasets.forEach(function(ds) {
    result[ds.category] = exports.buildDatasetFromConfig(ds, targetYears);
  });
  return result;
};

// Global OSM roads raster -> TILED IMAGE COLLECTION (recommended route).
//
// WHY A COLLECTION RATHER THAN ONE IMAGE
// The single global Export.image.toAsset does not fit GEE's per-attempt
// envelope any more: two runs both stalled at ~10.7% (stage 2/18),
// restarted internally (attempt #3) and burned >4M EECU-s without
// finishing. Small areas compute fine (18-44 s for a 0.3 deg box at full
// res), so the job is failing on total size, not on the data or method.
//
// Splitting into tiles and keeping them AS A COLLECTION also removes the
// final combine step: ee.ImageCollection(...).mosaic() is evaluated
// lazily at read time, so there is no second 9.3 GB global export at all.
// This is the standard shape for global 30 m products in GEE -- Hansen
// GFC, JRC TMF and FDAP model_2026a (~5,516 images/year) are all tiled
// collections consumed via mosaic().
//
// METHOD is unchanged from the v0/original export: reduceToImage
// all-touched rasterisation, so lines stay 4-connected (no diagonal
// leaks -- measured 0.2% pinch points vs 32.8% for paint(), which
// matters if roads are ever used unbuffered as a barrier/resistance
// layer for least-cost-path or fragmentation work).
//
// filterBounds is applied INSIDE each child FeatureCollection, per the
// P1.30 pattern in modules/timeSeriesAnthro.js:998 -- filtering after
// .flatten() defeats per-child spatial-index pushdown and makes the
// planner scan all 34 assets for every tile.
//
// ---------------------------------------------------------------
// SETUP (once, before running) -- create the destination collection:
//   earthengine --project ee-andyarnellgee create collection \
//     projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/roadsAllImageOSM_v2_tiles
//
// THEN: run this script and press Run on each tile task. Tiles are
// independent -- a finished tile is banked and never recomputed, and a
// failed tile can be re-run or split further on its own.
//
// AFTER: point consumers at the collection (see CONSUMING, bottom).
// ---------------------------------------------------------------

var outputBandName = "constant";
var scaleFactor = 1;              // 1 = full res (~27.8 m); 3 = coarse test
var FOLDER = "projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/";
var DEST   = FOLDER + "roadsAllImageOSM_v2_tiles";

var assetIds = [
  "africa_0_to_10000000_of_20329501",
  "africa_10000000_to_20000000_of_20329501",
  "africa_20000000_to_20329501_of_20329501",
  "antartica_0_to_1102_of_1102",
  "asia_0_to_10000000_of_62409033",
  "asia_10000000_to_20000000_of_62409033",
  "asia_20000000_to_30000000_of_62409033", // previously missing chunk
  "asia_30000000_to_40000000_of_62409033",
  "asia_40000000_to_50000000_of_62409033",
  "asia_50000000_to_60000000_of_62409033",
  "asia_60000000_to_62409033_of_62409033",
  "australia_oceania_0_to_4176086_of_4176086",
  "central_america_0_to_2174319_of_2174319",
  "europe_0_to_9945776_of_96258629",
  "europe_9945776_to_11974838_of_96258629",
  "europe_11974838_to_21974838_of_96258629",
  "europe_21974838_to_23598911_of_96258629",
  "europe_23598911_to_33598911_of_96258629",
  "europe_33598911_to_42897747_of_96258629",
  "europe_42897747_to_50932175_of_96258629",
  "europe_50932175_to_55425784_of_96258629",
  "europe_55425784_to_63749243_of_96258629",
  "europe_63749243_to_73035626_of_96258629",
  "europe_73035626_to_81889699_of_96258629",
  "europe_81889699_to_88610282_of_96258629",
  "europe_88610282_to_96258629_of_96258629",
  "north_america_0_to_10000000_of_55568828",
  "north_america_10000000_to_20000000_of_55568828",
  "north_america_20000000_to_30000000_of_55568828",
  "north_america_30000000_to_40000000_of_55568828",
  "north_america_40000000_to_50000000_of_55568828",
  "north_america_50000000_to_55568828_of_55568828",
  "south_america_0_to_10000000_of_13549774",
  "south_america_10000000_to_13549774_of_13549774"
];

// Per-asset filterBounds BEFORE flatten (P1.30 pushdown pattern), then
// the same proposed/planned filter the original export used.
function roadsIn(region) {
  var parts = assetIds.map(function (id) {
    return ee.FeatureCollection(FOLDER + id).filterBounds(region);
  });
  return ee.FeatureCollection(parts).flatten()
    .filter(ee.Filter.neq('highway', 'proposed'))
    .filter(ee.Filter.neq('highway', 'planned'));
}

// Rasterise: constant 1 per feature -> reduceToImage (all-touched)
function reduceToConstantImage(fc, value) {
  value = value || 1;
  var fc_with_value = fc.map(function (f) {
    return f.set('constant_value', value);
  });
  return fc_with_value.reduceToImage({
    properties: ['constant_value'],
    reducer: ee.Reducer.first()
  });
}

var templateImage = ee.Image("UMD/hansen/global_forest_change_2023_v1_11").select(0);
var exportScale = templateImage.projection().nominalScale()
    .multiply(scaleFactor).getInfo();

// Tile grid. 8 x 2 = 16 tiles covering the original extent exactly.
// Raise LON_STEP/LAT_STEP counts if any single tile still fails.
var LON_EDGES = [-180, -135, -90, -45, 0, 45, 90, 135, 180];
var LAT_EDGES = [-57, 12, 80];

var tileCount = 0;
for (var xi = 0; xi < LON_EDGES.length - 1; xi++) {
  for (var yi = 0; yi < LAT_EDGES.length - 1; yi++) {
    var x0 = LON_EDGES[xi], x1 = LON_EDGES[xi + 1];
    var y0 = LAT_EDGES[yi], y1 = LAT_EDGES[yi + 1];

    // filterBounds SELECTS whole features (it does not clip geometry), so a
    // road crossing a tile edge is rasterised in full and the export region
    // trims it -- pixels inside the tile are identical to the global run.
    var tileRegion = ee.Geometry.Rectangle([x0, y0, x1, y1], null, false);

    var tileImage = reduceToConstantImage(roadsIn(tileRegion))
        .rename(outputBandName)
        .toInt8()
        .reproject({crs: "EPSG:4326", scale: exportScale});

    var name = "roads_x" + xi + "_y" + yi;
    Export.image.toAsset({
      image: tileImage,
      description: name,
      assetId: DEST + "/" + name,   // lands INSIDE the collection
      region: tileRegion,
      scale: exportScale,
      maxPixels: 10e11
    });
    tileCount++;
  }
}
print("tile export tasks created:", tileCount);

// Check area: Thailand, roads from the previously missing chunk
Map.setCenter(99.2695, 16.6762, 14);
Map.setOptions('SATELLITE');
Map.addLayer(
  reduceToConstantImage(roadsIn(ee.Geometry.Rectangle([99.0, 16.4, 99.6, 17.0], null, false)))
    .rename(outputBandName).toInt8().selfMask(),
  {min: 0, max: 1, palette: ['red']}, 'roads (check area)');

// ---------------------------------------------------------------
// CONSUMING the finished collection -- no combine export needed.
// In modules/timeSeriesAnthro.js, roadsMosaicStatic() becomes:
//
//   function roadsMosaicStatic() {
//     return ee.ImageCollection(
//       "projects/ee-andyarnellgee/assets/crosscutting/infrastructure/" +
//       "roads_osm/roadsAllImageOSM_v2_tiles").mosaic();
//   }
//
// mosaic() is lazy: only the tiles overlapping the AOI are read, so a
// country-scale run touches 1-2 tiles instead of a 9.3 GB global image.
// ---------------------------------------------------------------

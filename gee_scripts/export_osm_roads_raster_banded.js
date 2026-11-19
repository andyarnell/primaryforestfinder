// Global OSM roads raster — SAME method as the v0/original export
// (reduceToImage all-touched rasterisation), but split into longitude
// bands so progress is banked per task instead of one month-long global
// task that loops on internal attempt restarts (observed: two runs both
// stuck at 10.7%, stage 2/18, attempt 3, ~4M EECU-s burned).
//
// PART 1 (this run): one export task per band -> roadsAllImageOSM_v2_b0..b8.
//   Press Run on every task in the Tasks tab; GEE runs 2-3 concurrently,
//   the rest queue. A finished band never has to be recomputed.
// PART 2 (after ALL bands succeed): uncomment and run the combine export
//   at the bottom -- raster-only mosaic, fast (~hours), same grid.
//
// Per-pixel output is identical to the original method: features are
// pre-filtered per band with a small buffer so lines crossing a band
// edge still rasterise correctly on both sides; overlapping band pixels
// carry identical values, so mosaic() is safe.

var outputBandName = "constant";
var scaleFactor = 1;
var FOLDER = "projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/";

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

var roadsOsmAll = ee.FeatureCollection(assetIds.map(function (id) {
  return ee.FeatureCollection(FOLDER + id);
})).flatten()
  //remove ones that dont exist yet
  .filter(ee.Filter.neq('highway', 'proposed'))
  .filter(ee.Filter.neq('highway', 'planned'));

// Function to reduce a FeatureCollection to an image with constant value 1
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

// Band edges: narrower over dense Eurasia, wider over ocean-heavy spans.
var edges = [-180, -100, -60, -30, 0, 30, 60, 90, 120, 180];
var LAT_MIN = -57, LAT_MAX = 80;   // same vertical extent as the original
var PAD = 0.01;                    // deg; features crossing a band edge
                                   // are included on both sides

for (var i = 0; i < edges.length - 1; i++) {
  var lonMin = edges[i], lonMax = edges[i + 1];
  var bandRegion = ee.Geometry.Rectangle([lonMin, LAT_MIN, lonMax, LAT_MAX], null, false);
  var filterRegion = ee.Geometry.Rectangle(
    [Math.max(lonMin - PAD, -180), LAT_MIN, Math.min(lonMax + PAD, 180), LAT_MAX], null, false);

  var bandRoads = roadsOsmAll.filterBounds(filterRegion);
  var bandImage = reduceToConstantImage(bandRoads)
      .rename(outputBandName)
      .toInt8()
      .reproject({crs: "EPSG:4326", scale: exportScale});

  Export.image.toAsset({
    image: bandImage,
    description: "roadsAllImageOSM_v2_b" + i,
    assetId: FOLDER + "roadsAllImageOSM_v2_b" + i,
    region: bandRegion,
    scale: exportScale,
    maxPixels: 10e11
  });
}

// Quick visual check area: Thailand, roads from the previously missing
// chunk (99.27E -> band b7, [90,120]).
Map.setCenter(99.2695, 16.6762, 14);

// ------------------------------------------------------------------
// PART 2 -- run AFTER all 9 band tasks have SUCCEEDED. Raster-only
// mosaic on the same grid; fast. Produces the final single asset.
// ------------------------------------------------------------------
// var bandImages = [];
// for (var j = 0; j < 9; j++) {
//   bandImages.push(ee.Image(FOLDER + "roadsAllImageOSM_v2_b" + j));
// }
// var combined = ee.ImageCollection(bandImages).mosaic()
//     .rename("constant").toInt8();
// Export.image.toAsset({
//   image: combined,
//   description: "roadsAllImageOSM_v2",
//   assetId: FOLDER + "roadsAllImageOSM_v2",
//   region: ee.Geometry.Rectangle([-179.9999999, -57, 180, 80], null, false),
//   scale: exportScale,
//   maxPixels: 10e11
// });
// // Optionally delete the roadsAllImageOSM_v2_b* band assets afterwards.

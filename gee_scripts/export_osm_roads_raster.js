// Global OSM roads raster export — original v0 script, tidied.
// Identical method to the run that produced roadsAllImageOSM
// (reduceToImage -> int8 -> reproject at Hansen nominal scale, export
// with scale + region). Changes vs the original only:
//   - table34: the previously missing asia_20000000_to_30000000 chunk
//   - outputBandName / scaleFactor defined (were undefined in the
//     recovered copy; values from the existing asset: "constant", x1)
//   - dead code and commented experiments removed
// Full original kept verbatim in old_export_osm_roads_raster_v0.js.
// Delete any existing roadsAllImageOSM_v2 asset before running.

var outputBandName = "constant";
var scaleFactor = 1;

var table = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/africa_0_to_10000000_of_20329501"),
    table2 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/africa_10000000_to_20000000_of_20329501"),
    table3 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/africa_20000000_to_20329501_of_20329501"),
    table4 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/antartica_0_to_1102_of_1102"),
    table5 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/asia_0_to_10000000_of_62409033"),
    table6 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/asia_10000000_to_20000000_of_62409033"),
    table7 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/asia_30000000_to_40000000_of_62409033"),
    table8 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/asia_40000000_to_50000000_of_62409033"),
    table9 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/asia_50000000_to_60000000_of_62409033"),
    table10 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/asia_60000000_to_62409033_of_62409033"),
    table11 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/australia_oceania_0_to_4176086_of_4176086"),
    table12 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/central_america_0_to_2174319_of_2174319"),
    table13 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/europe_0_to_9945776_of_96258629"),
    table14 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/europe_21974838_to_23598911_of_96258629"),
    table15 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/europe_33598911_to_42897747_of_96258629"),
    table16 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/europe_42897747_to_50932175_of_96258629"),
    table17 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/europe_50932175_to_55425784_of_96258629"),
    table18 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/europe_55425784_to_63749243_of_96258629"),
    table19 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/europe_73035626_to_81889699_of_96258629"),
    table20 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/europe_81889699_to_88610282_of_96258629"),
    table21 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/europe_88610282_to_96258629_of_96258629"),
    table22 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/europe_9945776_to_11974838_of_96258629"),
    table23 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/north_america_0_to_10000000_of_55568828"),
    table24 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/north_america_10000000_to_20000000_of_55568828"),
    table25 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/north_america_20000000_to_30000000_of_55568828"),
    table26 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/north_america_30000000_to_40000000_of_55568828"),
    table27 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/north_america_40000000_to_50000000_of_55568828"),
    table28 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/north_america_50000000_to_55568828_of_55568828"),
    table29 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/south_america_0_to_10000000_of_13549774"),
    table30 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/south_america_10000000_to_13549774_of_13549774"),
    table31 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/europe_63749243_to_73035626_of_96258629"),
    table32 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/europe_23598911_to_33598911_of_96258629"),
    table33 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/europe_11974838_to_21974838_of_96258629"),
    table34 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/asia_20000000_to_30000000_of_62409033"); // previously missing chunk


var roadsOsmAll = ee.FeatureCollection(
  [
    table,table2,table3,table4,table5,table6,table7,table8,table9,table10,table11,
    table12,table13,table14,table15,table16,table17,table18,table19,table20,table21,
    table22,table23,table24,table25,table26,table27,table28,table29,
    table30,table31,table32,table33,table34
  ]
  ).flatten()

//remove ones that dont exist yet
var roadsOsmAll = roadsOsmAll
  .filter(ee.Filter.neq('highway', 'proposed'))
  .filter(ee.Filter.neq('highway', 'planned'));


// Function to reduce a FeatureCollection to an image with constant value 1
function reduceToConstantImage(fc, value) {
  value = value || 1; // Default to 1 if no value provided

  // Add constant property to each feature
  var fc_with_value = fc.map(function(f) {
    return f.set('constant_value', value);
  });

  // Reduce to image using the constant property
  return fc_with_value.reduceToImage({
    properties: ['constant_value'],
    reducer: ee.Reducer.first()
  });
}


////////////////////////////

var templateImage = ee.Image("UMD/hansen/global_forest_change_2023_v1_11").select(0)


//rasterise
var roadsAllImage = reduceToConstantImage(roadsOsmAll).rename(outputBandName).toInt8().reproject({crs:"EPSG:4326",scale:templateImage.projection().nominalScale().multiply(scaleFactor).getInfo()})


Map.addLayer(roadsAllImage,{min:0,max:1},"roadsAllImage")
Map.setCenter(99.2695, 16.6762, 14); // Thailand — roads from the previously missing chunk

var bounds = ee.Geometry.Rectangle(
  [-179.9999999, -57, 180, 80],
  null,            // Use default projection (EPSG:4326)
  false,           // geodesic: false for planar edges
  true             // evenOdd
);

Export.image.toAsset(
  {
  image: roadsAllImage,
  description: "roadsAllImageOSM_v2",
  assetId: "projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/roadsAllImageOSM_v2",
  region: bounds,
  scale: templateImage.projection().nominalScale().multiply(scaleFactor).getInfo(),
  maxPixels: 10e11,
})

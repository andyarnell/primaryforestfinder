// ORIGINAL export script for roadsAllImageOSM — recovered verbatim from the
// GEE Code Editor, 2026-09-15. Kept for provenance only; use
// export_osm_roads_raster.js for the 34-chunk re-export.
//
// NB: `outputBandName` and `scaleFactor` are referenced but not defined in
// this recovered copy (defined elsewhere / in an earlier session). The
// existing roadsAllImageOSM asset shows the values used: band name
// "constant", 0.00025°/px (= Hansen nominal scale, i.e. scaleFactor 1).
// NB: the interactive Map.addLayer of the full merged vector (254M features)
// exceeds Earth Engine's interactive memory limit — the batch exports were
// what produced the asset.

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
    table33 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/europe_11974838_to_21974838_of_96258629");


var roadsOsmAll = ee.FeatureCollection(
  [
    table,table2,table3,table4,table5,table6,table7,table8,table9,table10,table11,
    table12,table13,table14,table15,table16,table17,table18,table19,table20,table21,
    table22,table23,table24,table25,table26,table27,table28,table29
    ,table30,table31,table32,table33
    ]
    ).flatten()

// //check properties

// Function to simulate getting property types from a Feature or FeatureCollection
function getPropertyTypes(feature) {
  feature.toDictionary().evaluate(function(dict) {
    print('Property Types:');
    for (var key in dict) {
      print(key + ':', typeof dict[key]);
    }
  });

}

getPropertyTypes(roadsOsmAll.first());

//list types
// print(roadsOsmAll.aggregate_array("highway").distinct())

// print(roadsOsmAll.size())

// print(roadsOsmAll.aggregate_array("highway").distinct())

//remove ones that dont exist yet
var roadsOsmAll = roadsOsmAll
  .filter(ee.Filter.neq('highway', 'proposed'))
  .filter(ee.Filter.neq('highway', 'planned'));

Export.table.toAsset({
  collection:roadsOsmAll, description:"roadsOsmAll", assetId:"roadsOsmAll"}
  )

// view vector
Map.addLayer(roadsOsmAll,"","roadsOsmAll")

//centre
var featureSel = 1000 //change to move about the feature subset
// Map.centerObject(ee.FeatureCollection((roadsMicrosoftAll).toList(100000,1000)).first(),14)


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
// print(ee.Geometry(templateImage.geometry()),"hansen bounds")


//rasterise
// var roadsAllImage = roadsOsmAll.reduceToImage([propertyToReduce], ee.Reducer.max()).rename(outputBandName).toInt8().reproject({crs:"EPSG:4326",scale:templateImage.projection().nominalScale().getInfo()})
var roadsAllImage = reduceToConstantImage(roadsOsmAll).rename(outputBandName).toInt8().reproject({crs:"EPSG:4326",scale:templateImage.projection().nominalScale().multiply(scaleFactor).getInfo()})

// print(roadsAllImage)//check it worked


Map.addLayer(roadsAllImage,{min:0,max:1},"roadsAllImage")

var bounds = ee.Geometry.Rectangle(
  [-179.9999999, -57, 180, 80],
  null,            // Use default projection (EPSG:4326)
  false,           // geodesic: false for planar edges
  true            // evenOdd: false for left-inside rule
);

Export.image.toAsset(
  {
  image: roadsAllImage,
  description: "roadsAllImageOSM_v0",
  assetId: "roadsAllImageOSM_v0",
  // pyramidingPolicy:,
  //dimensions,
  region:bounds,
  scale:templateImage.projection().nominalScale().multiply(scaleFactor).getInfo(),
  // crs,
  // crsTransform,
  maxPixels: 10e11,
  // shardSize,
  // priority
})




/// Step 1: Get distinct highway types
var highwayTypes = roadsOsmAll.aggregate_array("highway").distinct();

// Step 2: Convert list to a FeatureCollection
var highwayFeatures = ee.FeatureCollection(highwayTypes.map(function(type) {
  return ee.Feature(null, {highway: type});
}));

// Step 3: Export as an Earth Engine asset
Export.table.toAsset({
  collection: highwayFeatures,
  description: 'export_highway_types',
  assetId: 'osm_highway_types_list'  // Replace with your EE username/path
});

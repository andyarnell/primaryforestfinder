// var image = ee.Image('Tsinghua/DESS/ChinaTerraceMap/v1');
// var roadsBrazil1 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/brazil_outros-trechos_mapbiomas"),
//     roadsBrazil2 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/brazil_rodovia-estadual_mapbiomas"),
//     roadsBrazil3 = ee.FeatureCollection("projects/ee-andyarnellgee/assets/brazil_rodovia-federal_mapbiomas");
// Map.addLayer(roadsBrazil1.merge(roadsBrazil2).merge(roadsBrazil3),"","roadsBrazil")

var targetYears = [1990, 2000, 2010, 2015, 2020];

var analysisYear = targetYears[0]

// Module to preprocess GLC-FCS30D dataset
var preprocessGlc = function() {
  // Define target years for analysis
  var target_years = [1990, 2000, 2010, 2015, 2020];

  // Load annual and five-yearly mosaics
  var annualCol = ee.ImageCollection('projects/sat-io/open-datasets/GLC-FCS30D/annual');
  var fiveYearCol = ee.ImageCollection('projects/sat-io/open-datasets/GLC-FCS30D/five-years-map');

  // Get the projection from the first image in the annual collection
  var firstAnnualImage = ee.Image(annualCol.first());
  var targetProjection = firstAnnualImage.projection();

  // Mosaic the collections
  var annual = annualCol.mosaic();
  var fiveYear = fiveYearCol.mosaic();

  // Create a list of years for five-yearly and annual datasets
  var fiveYearsList = ee.List.sequence(1985, 1995, 5).map(function(year) {
    return ee.Number(year).format('%04d');
  });
  var yearsList = ee.List.sequence(2000, 2022).map(function(year) {
    return ee.Number(year).format('%04d');
  });

  // Rename bands for five-yearly and annual mosaics
  var fiveYearMosaicRenamed = fiveYear.rename(fiveYearsList);
  var annualMosaicRenamed = annual.rename(yearsList);

  // Convert five-yearly mosaic to a collection with the correct projection
  var fiveYearlyMosaics = fiveYearsList.map(function(year) {
    var date = ee.Date.fromYMD(ee.Number.parse(year), 1, 1);
    return fiveYearMosaicRenamed
      .select([year])
      .setDefaultProjection(targetProjection) // Set default projection
      .set({
        'system:time_start': date.millis(),
        'system:index': year,
        'year': ee.Number.parse(year)
      });
  });

  // Convert annual mosaic to a collection with the correct projection
  var yearlyMosaics = yearsList.map(function(year) {
    var date = ee.Date.fromYMD(ee.Number.parse(year), 1, 1);
    return annualMosaicRenamed
      .select([year])
      .setDefaultProjection(targetProjection) // Set default projection
      .set({
        'system:time_start': date.millis(),
        'system:index': year,
        'year': ee.Number.parse(year)
      });
  });

  // Combine the collections
  var mosaicsCol = ee.ImageCollection.fromImages(fiveYearlyMosaics.cat(yearlyMosaics));

  // Filter the collection to target years
  return mosaicsCol.filter(ee.Filter.inList('year', target_years));
};

// Export the function directly
exports.preprocessGlc = preprocessGlc;






// ---------------------------------------------------------------------
// Example usage of preprocessGlc 
// ---------------------------------------------------------------------
// (Uncomment and modify the following lines as needed)
// var glcFcs30d = require('users/your_username/your_script_folder:glc_fcs30d.js').glcFcs30d;

// var targetYears = [1990, 2000, 2010, 2015, 2020];
// var analysisYear = targetYears[4];

// // Define remap inputs
// var fromList = [
//   10, 11, 12, 20, 51, 52, 61, 62, 71, 72, 81, 82, 91, 92, 120, 121, 122, 
//   130, 140, 150, 152, 153, 181, 182, 183, 184, 185, 186, 187, 190, 200, 
//   201, 202, 210, 220, 0
// ];
// var toList = ee.List.sequence(1, fromList.length);
// print(toList)

// // Preprocess the dataset for the target years and apply remap
// var glcFcs30dCollection = preprocessGlc()
// print(glcFcs30dCollection)

// // Select a specific year and add the layer to the map
// var glcFcs30dSel = glcFcs30dCollection.filter(ee.Filter.eq("year", analysisYear));


// var glcFcs30dSel = glcFcs30dSel.mosaic().remap(fromList, toList,0);

// // (For debugging) Print the filtered and remapped collection
// print('Filtered and Remapped GLC-FCS30D Collection:', glcFcs30dSel);

// var palette = [
//   '#ffff64', '#ffff64', '#ffff00', '#aaf0f0', '#4c7300', '#006400', '#a8c800', '#00a000', 
//   '#005000', '#003c00', '#286400', '#285000', '#a0b432', '#788200', '#966400', '#964b00', 
//   '#966400', '#ffb432', '#ffdcd2', '#ffebaf', '#ffd278', '#ffebaf', '#00a884', '#73ffdf', 
//   '#9ebb3b', '#828282', '#f57ab6', '#66cdab', '#444f89', '#c31400', '#fff5d7', '#dcdcdc', 
//   '#fff5d7', '#0046c8', '#ffffff', '#ffffff'
// ];
// var classVisParams = {min: 1, max: 36, palette: palette};
// Map.addLayer(glcFcs30dSel, classVisParams, 'Landcover ' + analysisYear);









// ---------------------------------------------------------------------
// GHSL Built-up and Population Module
// ---------------------------------------------------------------------

// // Function to process built-up and population data for a given year
// var processYear = function(year) {
//   var ghslSmodRaw = ee.ImageCollection("JRC/GHSL/P2023A/GHS_SMOD"); // Built-up dataset
//   var ghslPopRaw = ee.ImageCollection("JRC/GHSL/P2023A/GHS_POP");   // Population dataset

//   // Select the built-up image for the given year
//   var ghslSmodRawSel = ghslSmodRaw.filter(
//     ee.Filter.eq("system:index", year.toString())
//   ).first();
  
//   // Define low-density built-up areas (rural cluster and above)
//   var ghslLowDensity = ghslSmodRawSel.gte(11).and(ghslSmodRawSel.lte(12));

//   // Select the population image for the given year
//   var ghslPopRawSel = ghslPopRaw.filter(
//     ee.Filter.eq("system:index", year.toString())
//   ).first();

//   // Mask the low-density built-up areas with population data
//   var ghslLowDensMaskedToPop = ghslPopRawSel.unmask().updateMask(ghslLowDensity);

//   // Define higher-density built-up areas by excluding low-density
//   var ghslHigherDensMaskedToPop = ghslPopRawSel.updateMask(ghslLowDensMaskedToPop.not());


//   // Combine the two into one image (1 for small, 2 for large)
//   var combinedBuiltUp = ghslLowDensMaskedToPop.gt(0)
//     .multiply(1).unmask() // Assign value 1 for small built-up
//     .add(ghslHigherDensMaskedToPop.gt(0).multiply(2)); // Add value 2 for large built-up

//   // Return the combined image with year metadata
//   return ee.Image(combinedBuiltUp).set('year', year).rename('combined_built_up_' + year);
// };

// // Define the years of interest for built-up processing
// var targetYears = [1990, 2000, 2010, 2015, 2020];

// // Function to generate the combined built-up image collection for given years
// function getGhslCollection() {
//   var combinedGhslCollection = ee.ImageCollection(targetYears.map(function(year) {
//     return processYear(year);
//   }));
//   return combinedGhslCollection;
// }

// exports.getGhslCollection = getGhslCollection;


// // checking it 
// var ghslCollection = getGhslCollection()

// // Visualize the combined data using forEach
// targetYears.forEach(function(year) {
//   var image = ghslCollection.filter(ee.Filter.eq('year', year)).first();
  
//   Map.addLayer(image.selfMask(), 
//     {min: 1, max: 2, palette: ["red", "darkred"]}, 
//     'Combined Built-up GHSL' + year, false);
// })

// Fix the masking operations in processYear function
var processYear = function(year) {
  var ghslSmodRaw = ee.ImageCollection("JRC/GHSL/P2023A/GHS_SMOD");
  var ghslPopRaw = ee.ImageCollection("JRC/GHSL/P2023A/GHS_POP");

  // Get images for this year
  var ghslSmodRawSel = ghslSmodRaw.filter(ee.Filter.eq("system:index", year.toString())).first();
  var ghslPopRawSel = ghslPopRaw.filter(ee.Filter.eq("system:index", year.toString())).first();

  // Define built-up areas more explicitly
  var ghslLowDensity = ghslSmodRawSel.gte(11).and(ghslSmodRawSel.lte(12));
  var ghslHighDensity = ghslSmodRawSel.gt(12); // Urban centers and dense urban areas
  
  // Create a combined built-up image (1=small/rural, 2=larger/urban)
  var combinedBuiltUp = ghslLowDensity.multiply(1)
    .add(ghslHighDensity.multiply(2))
    .updateMask(ghslPopRawSel.gt(0)); // Only keep areas with some population

  // Return the image with metadata
  return combinedBuiltUp.set('year', year).rename('combined_built_up_' + year);
};

// Define the years of interest for built-up processing
var targetYears = [1990, 2000, 2010, 2015, 2020];

// Function to generate the combined built-up image collection for given years
function getGhslCollection() {
  var combinedGhslCollection = ee.ImageCollection(targetYears.map(function(year) {
    return processYear(year);
  }));
  return combinedGhslCollection;
}

exports.getGhslCollection = getGhslCollection;
exports.getGhslForYear = processYear;

// // If you're using this file as a module AND want to visualize directly,
// // use this approach - otherwise remove this section:
// var ghslCollection = getGhslCollection();

// // Add visualization function that can be called either here or from importing script
// function visualizeGhslCollection(collection) {
//   targetYears.forEach(function(year) {
//     var image = collection.filter(ee.Filter.eq('year', year)).first();
    
//     Map.addLayer(image.selfMask(), 
//       {min: 1, max: 2, palette: ["red", "darkred"]}, 
//       'Combined Built-up GHSL ' + year, false);
//   });
// }

// // Export the visualization function
// exports.visualizeGhslCollection = visualizeGhslCollection;

// // Uncomment to visualize when running this file directly
// visualizeGhslCollection(ghslCollection);
// // ---------------------------------------------------------------------
// GISD30 Built-up Module (Zhang et al., 2020)
// ---------------------------------------------------------------------

var gisd30 = ee.Image("projects/sat-io/open-datasets/GISD30_1985_2020");

var processGISDYear = function(year) {
  return gisd30.lte(year-1985).selfMask().set('year', year).rename('GISD_' + year);
};

function getGISDCollection() {
  var targetYears = [1990, 2000, 2010, 2015, 2020];
  return ee.ImageCollection(targetYears.map(processGISDYear));
}

exports.getGISDCollection = getGISDCollection;
exports.getGISDForYear = processGISDYear;




// // Define years to visualize
// var targetYears = [1990, 2000, 2010, 2015, 2020];

// // Define visualization parameters
// var visParamsGISD = {min: 1, max: 8, palette: ["#808080", "#006400", "#228B22", "#32CD32", "#ADFF2F", "#FFFF00", "#FFA500", "#FF0000"]};

// var gisdCollection = getGISDCollection();

// // Add layers to the map for visualization
// targetYears.forEach(function(year) {
//   Map.addLayer(gisdCollection.filter(ee.Filter.eq('year', year)).first(), visParamsGISD, 'GISD ' + year);

// });

// // Display Full Image Collections
// print('GISD30 Collection:', gisdCollection);



// ---------------------------------------------------------------------
// GISA Built-up Module (Huang et al., 2021)
// ---------------------------------------------------------------------

var gisa = ee.ImageCollection("projects/sat-io/open-datasets/GISA_1972_2019");
var gisaMosaic = gisa.mosaic();

var processGISAYear = function(year) {
  return gisaMosaic.lte(year - 1972).selfMask().set('year', year).rename('GISA_' + year);
};

function getGISACollection() {
  var targetYears = [1990, 2000, 2010, 2015, 2020];
  return ee.ImageCollection(targetYears.map(processGISAYear));
}

exports.getGISACollection = getGISACollection;
exports.getGISAForYear = processGISAYear;


// // Define years to visualize
// var targetYears = [1990, 2000, 2010, 2015, 2020];


// var gisaCollection = getGISACollection();

// // Define visualization parameters
// var visParamsGISA = {min: 0, max: 1, palette: ['gray', 'red']};

// // Add layers to the map for visualization
// targetYears.forEach(function(year) {
//   Map.addLayer(gisaCollection.filter(ee.Filter.eq('year', year)).first(), visParamsGISA, 'GISA ' + year);
// });

// // // Display Full Image Collections
// print('GISA Collection:', gisaCollection);


// // ---------------------------------------------------------------------
// // WSF Built-up Module (WSF EVO, WSF2015, WSF2019)
// ---------------------------------------------------------------------

// var wsf2015 = ee.Image('DLR/WSF/WSF2015/v1'); // 10m, Built-up pixels = 255 (unused)
// var wsf2019 = ee.ImageCollection("projects/sat-io/open-datasets/WSF/WSF_2019").mosaic(); // (unused)
var wsfEvo = ee.ImageCollection("projects/sat-io/open-datasets/WSF/WSF_EVO");
var wsfEvoMosaic = wsfEvo.mosaic();

var processWSFYear = function(year) {
  return wsfEvoMosaic.lte(year).selfMask().set('year', year).rename('WSF_' + year);
};

// Define years to visualize
var targetYears = [1990, 2000, 2010, 2015, 2020];

function getWSFCollection() {
  var targetYears = [1990, 2000, 2010, 2015, 2020];
  return ee.ImageCollection(targetYears.map(processWSFYear));
}

exports.getWSFCollection = getWSFCollection;
exports.getWSFForYear = processWSFYear;




// var wsfCollection = getWSFCollection();

// // Define visualization parameters
// var visParamsWSF = {palette: ['red', 'orange', 'yellow', 'green', 'blue'], min: 0, max: 1};

// // Add layers to the map for visualization
// targetYears.forEach(function(year) {
//   Map.addLayer(wsfCollection.filter(ee.Filter.eq('year', year)).first(), visParamsWSF, 'WSF ' + year);
// });

// Display Full Image Collections
// print('WSF Collection:', wsfCollection);








// ---------------------------------------------------------------------
// Processing Function: processingCroplandsGlad
// ---------------------------------------------------------------------
// Cropland extent (GLAD)
// https://glad.umd.edu/dataset/croplands 
// Represents a globally consistent cropland extent time-series at 30-m spatial resolution. 
// Cropland defined as land used for annual and perennial herbaceous crops 
// (for human consumption, forage including hay, and biofuel).
// Excludes: Perennial woody crops, permanent pastures, and shifting cultivation.
// Note: The year is the final year in each period (2000-2003, 2004-2007, 2008-2011,
// 2012-2015, and 2016-2019). For 1990, we use the 2003 asset as a proxy.
var processingCroplandsGlad = function() {
  // Define the target years (consistent with GLC-FCS30D)
  var targetYears = [1990, 2000, 2010, 2015, 2020];

  // Define the cropland asset and assign each a representative year.
  // NB: 1990 is a special case using the 2003 asset (copy of 2000 data)
  var croplandYears = [
    { image: "users/potapovpeter/Global_cropland_2003", representativeYear: 1990 },
    { image: "users/potapovpeter/Global_cropland_2003", representativeYear: 2000 },
    { image: "users/potapovpeter/Global_cropland_2011", representativeYear: 2010 },   
    { image: "users/potapovpeter/Global_cropland_2015", representativeYear: 2015 },
    { image: "users/potapovpeter/Global_cropland_2019", representativeYear: 2020 }
  ];

  // Map over each cropland asset and create an image with the proper properties.
  var images = croplandYears.map(function(item) {
    var yr = item.representativeYear;
    // Create a date corresponding to January 1st of the representative year.
    var date = ee.Date.fromYMD(yr, 1, 1);
    
    // Mosaic the asset (in case it's an ImageCollection) to form a single image
    // and assign properties for year, system time, and index.
    var image = ee.ImageCollection(item.image).mosaic().set({
      'year': yr,
      'system:time_start': date.millis(),
      'system:index': ee.String(yr.toString())
    });
    return image;
  });

  // Return the images as an ImageCollection, filtered to only include the target years.
  return ee.ImageCollection.fromImages(images)
           .filter(ee.Filter.inList('year', targetYears));
};

exports.processingCroplandsGlad = processingCroplandsGlad;

// Per-year cropland lookup (avoids building full collection)
var croplandAssetsByYear = {
  1990: "users/potapovpeter/Global_cropland_2003",
  2000: "users/potapovpeter/Global_cropland_2003",
  2010: "users/potapovpeter/Global_cropland_2011",
  2015: "users/potapovpeter/Global_cropland_2015",
  2020: "users/potapovpeter/Global_cropland_2019"
};
var getCroplandsGladForYear = function(year) {
  var assetPath = croplandAssetsByYear[year] || croplandAssetsByYear[2020];
  return ee.ImageCollection(assetPath).mosaic().set('year', year);
};
exports.getCroplandsGladForYear = getCroplandsGladForYear;



// var croplandGladCollection = processingCroplandsGlad()
// //select by year
// var cropland = ee.Image(croplandGladCollection.filter(ee.Filter.eq("year",analysisYear)).first())

// Map.addLayer(cropland,{min:0,max:1,palette:["white","orange"]},"cropland "+analysisYear.toString(),0,1)


// // Print the ImageCollection to verify
// print("Cropland GLAD Collection with representative years:", croplandGladCollection);

// // Visualize the cropland for each representative year
// targetYears.forEach(function(year) {
//   var cropland = croplandGladCollection.filter(
//     ee.Filter.eq("year", year)
//   ).first();

//   Map.addLayer(cropland.selfMask(), 
//     {min: 0, max: 1, palette: ["white", "orange"]}, 
//     "Cropland " + year, false);
// });


// /////so cropland stays present over time and cant turn into forest
//   function forwardFillBinaryTimeSeries(imageCollection, targetYears) {
//   var sorted = imageCollection.sort('year');

//   var initial = {
//     cumulative: ee.Image(0),
//     list: ee.List([])
//   };

//   var result = ee.List(targetYears).iterate(function(year, prev) {
//     year = ee.Number(year);
//     prev = ee.Dictionary(prev);

//     var cumulative = ee.Image(prev.get('cumulative'));

//     var imageForYear = ee.Image(
//       sorted.filter(ee.Filter.eq('year', year)).first()
//     ).unmask(0).gt(0);

//     var updatedCumulative = cumulative.or(imageForYear);

//     var yearImage = updatedCumulative.rename('forwardfill').set({
//       'year': year,
//       'system:time_start': ee.Date.fromYMD(year, 1, 1).millis(),
//       'system:index': year.format()
//     });

//     var updatedList = ee.List(prev.get('list')).add(yearImage);

//     return ee.Dictionary({
//       cumulative: updatedCumulative,
//       list: updatedList
//     });
//   }, initial);

//   return ee.ImageCollection.fromImages(ee.Dictionary(result).get('list'));
// }

// function forwardFillBinaryTimeSeries(imageCollection, targetYears) {
//   var sorted = imageCollection.sort('year');

//   // Pre-index images by year
//   var yearToImg = ee.Dictionary(
//     sorted.iterate(function(img, d) {
//       img = ee.Image(img);
//       var y = ee.Number(img.get('year'));
//       return ee.Dictionary(d).set(y.format(), img);
//     }, ee.Dictionary({}))
//   );

//   var initial = {
//     cumulative: ee.Image(0),
//     list: ee.List([])
//   };

//   var result = ee.List(targetYears).iterate(function(year, prev) {
//     year = ee.Number(year);
//     prev = ee.Dictionary(prev);

//     var cumulative = ee.Image(prev.get('cumulative'));
//     var imageForYear = ee.Image(yearToImg.get(year.format()))
//       .unmask(0).gt(0);

//     var updatedCumulative = cumulative.or(imageForYear);

//     var yearImage = updatedCumulative.rename('forwardfill').set({
//       'year': year,
//       'system:time_start': ee.Date.fromYMD(year, 1, 1).millis(),
//       'system:index': year.format()
//     });

//     return ee.Dictionary({
//       cumulative: updatedCumulative,
//       list: ee.List(prev.get('list')).add(yearImage)
//     });
//   }, initial);

//   return ee.ImageCollection.fromImages(ee.Dictionary(result).get('list'));
// }

function forwardFillBinaryTimeSeries(imageCollection, targetYears) {
  var sorted = imageCollection.sort('year');

  // Pre-index images by year
  var yearToImg = ee.Dictionary(
    sorted.iterate(function(img, d) {
      img = ee.Image(img);
      var y = ee.Number(img.get('year'));
      return ee.Dictionary(d).set(y.format(), img);
    }, ee.Dictionary({}))
  );

  var initial = {
    cumulative: ee.Image(0),
    list: ee.List([])
  };

  var result = ee.List(targetYears).iterate(function(year, prev) {
    year = ee.Number(year);
    prev = ee.Dictionary(prev);

    var cumulative = ee.Image(prev.get('cumulative'));
    var imageForYear = ee.Image(yearToImg.get(year.format()))
      .unmask(0).gt(0);

    var updatedCumulative = cumulative.or(imageForYear);

    var yearImage = updatedCumulative.rename('forwardfill').set({
      'year': year,
      'system:time_start': ee.Date.fromYMD(year, 1, 1).millis(),
      'system:index': year.format()
    });

    return ee.Dictionary({
      cumulative: updatedCumulative,
      list: ee.List(prev.get('list')).add(yearImage)
    });
  }, initial);

  return ee.ImageCollection.fromImages(ee.Dictionary(result).get('list'));
}

exports.forwardFillBinaryTimeSeries = forwardFillBinaryTimeSeries;

// 1. Define the wrapper as a normal variable
var processingCroplandsGladFF = function() {
  return forwardFillBinaryTimeSeries(processingCroplandsGlad(), targetYears);
};

// 2. Export it for use from other scripts
exports.processingCroplandsGladFF = processingCroplandsGladFF;

// 3. Uncomment below for debugging/visualization
// var croplandsGladFF = processingCroplandsGladFF();
// targetYears.forEach(function(year) {
//   var img = croplandsGladFF.filter(ee.Filter.eq('year', year)).first();
//   Map.addLayer(
//     img.selfMask(),
//     {palette: ['orange']},
//     'Cropland FF ' + year,
//     false
//   );
// });




// ---------------------------------------------------------------------
// PROCESSING FUNCTION: processingOilPalmDescals
// ---------------------------------------------------------------------
// GlobalOilPalm_YoP_2021: Year of oil palm plantation establishment dataset
// (Descals, A. 2024)
// This function converts the dataset into an ImageCollection where each image 
// represents the oil palm plantation extent up to a given target year.
// Pixels with an establishment year (YoP) less than or equal to the target year 
// are masked as true (1).

// Oil palm year-of-planting (computed once at module level)
var _oilPalmYoP = ee.ImageCollection("projects/ee-globaloilpalm/assets/shared/GlobalOilPalm_YoP_2021")
    .mosaic().select(['minNBR_date']).rename(['minNBR'])
    .divide(365).add(1970).min(1989);

var processingOilPalmDescals = function() {
  var targetYears = [1990, 2000, 2010, 2015, 2020];

  var images = targetYears.map(function(year) {
    year = ee.Number(year);
    var date = ee.Date.fromYMD(year, 1, 1);
    var image = _oilPalmYoP.lte(year)//.selfMask()
      .set({
        'year': year,
        'system:time_start': date.millis(),
        'system:index': ee.String(year.format())
      });
    return image;
  });
  
  return ee.ImageCollection.fromImages(images);
};

// Export the processingOilPalmDescals function.
exports.processingOilPalmDescals = processingOilPalmDescals;

// Per-year oil palm lookup (uses cached _oilPalmYoP)
var getOilPalmDescalsForYear = function(year) {
  return _oilPalmYoP.lte(year).set('year', year);
};
exports.getOilPalmDescalsForYear = getOilPalmDescalsForYear;


// // ---------------------------------------------------------------------
// // Visualization Example
// // ---------------------------------------------------------------------
// var targetYears = [1990, 2000, 2010, 2015, 2020];
// var analysisYear = 2020;  // Change this value as needed

// // Generate the oil palm plantation collection for the target years.
// var oilPalmCollection = processingOilPalmDescals();

// // Loop through the target years and add each layer to the map (initially hidden)
// targetYears.forEach(function(year) {
//   var image = ee.Image(oilPalmCollection.filter(ee.Filter.eq('year', year)).first());
//   Map.addLayer(
//     image,
//     {min: 0, max: 1, palette: ['white', 'black']},
//     'Oil Palm Plantation ' + year,
//     false  // set to true to have the layer visible by default
//   );
// });

// // Alternatively, select and display a single target year.
// var selectedImage = ee.Image(oilPalmCollection.filter(ee.Filter.eq('year', analysisYear)).first());
// Map.addLayer(
//   selectedImage,
//   {min: 0, max: 1, palette: ['white', 'black']},
//   'Oil Palm Plantation ' + analysisYear,
//   true
// );


//////////////////////////////////////



// Step 2: Load FDAP Plantation Datasets
function processingPlantationsMosaic(){
    // Step 1: Load and Clean SDPT Planted Trees Dataset
    var sdpt = ee.Image("projects/sdpt-v2/assets/sdpt_v2_simpleType_v09032024_public").unmask();
    var plantedTreesSDPT = sdpt.eq(1);  // Planted Forests
 
    var plantationsSDPT = sdpt.eq(2);   // Tree Crops
    
    // FDAP modelled data parameters
    var smoothRadius = 30; // in meters
    var agriSmallPixelThreshold1 = 0.4;
    var agriSmallPixelThreshold2 = 0.4;

    var plantationYear = "2020"; // One year of data
    var startDate = plantationYear + '-01-01';
    var endDate = plantationYear + '-12-31';

    var fdapPalmProbThreshold = 0.95;  // Suggested: 0.83
    var fdapRubberProbThreshold = 0.95; // Suggested: 0.93
    var fdapCocoaProbThreshold = 0.9;  // Suggested: 0.5


    // Load Palm Dataset
    var fdapPalmCollection = ee.ImageCollection("projects/forestdatapartnership/assets/palm/model_2024a")
        .filterDate(startDate, endDate);
    // print("FDAP Palm Collection Size:", fdapPalmCollection.size()); // Debugging

    var fdapPalm = fdapPalmCollection.first().gt(fdapPalmProbThreshold);

    // Load Rubber Dataset
    var fdapRubberCollection = ee.ImageCollection("projects/forestdatapartnership/assets/rubber/model_2024a")
        .filterDate(startDate, endDate);
    // print("FDAP Rubber Collection Size:", fdapRubberCollection.size()); // Debugging

    var fdapRubber = fdapRubberCollection.first().gt(fdapRubberProbThreshold);
 
    // Load Cocoa Dataset
    var fdapCocoaCollection = ee.ImageCollection("projects/forestdatapartnership/assets/cocoa/model_2024a")
        .filterDate(startDate, endDate);
    // print("FDAP Cocoa Collection Size:", fdapCocoaCollection.size()); // Debugging

    var fdapCocoa = fdapCocoaCollection.first().gt(fdapCocoaProbThreshold);

    // Combine FDAP Commodity Plantations
    var fdapCommodities = fdapPalm.unmask()
        .or(fdapRubber.unmask())
        .or(fdapCocoa.unmask());

 
    // Define the low-pass filter
    var boxcar = ee.Kernel.square({
        radius: smoothRadius, units: 'meters', normalize: true
    });

    var smooth1 = fdapCommodities.convolve(boxcar)
        .gt(agriSmallPixelThreshold1)
        .convolve(boxcar)
        .gt(agriSmallPixelThreshold2);

    var smooth2 = smooth1.convolve(boxcar).gt(agriSmallPixelThreshold2);
    
    var fdapCommoditiesLargePatches = smooth2//.selfMask();


    // Combine All Static Plantations
    var plantationsMosaicStatic = plantationsSDPT.or(plantedTreesSDPT)
    //speed checks
        // .or(fdapCommoditiesLargePatches);


    // Step 5: Remove time-series areas (use per-year instead of building full collection)
    var oilPalmMask = getOilPalmDescalsForYear(2020).unmask();

    var plantationsMosaicStaticNoDescals = plantationsMosaicStatic.multiply(oilPalmMask.not());
    
    // Map.addLayer(plantedTreesSDPT,{palette: ["white","red"]},"plantedTreesSDPT")
    
    // Map.addLayer(plantationsSDPT,{palette: ["white","purple"]},"plantationsSDPT")
 
    // Map.addLayer(fdapPalm, {palette: ["white","orange"]}, "fdapPalm (Debug)");
    // Map.addLayer(fdapRubber, {palette: ["white","orange"]}, "fdapRubber (Debug)");
    
    // Map.addLayer(fdapCocoa, {palette: ["white","orange"]}, "fdapCocoa (Debug)");
    // Map.addLayer(fdapCommodities, {palette: ["white","orange"]}, "FDAP Commodities (Debug)");
    // // Debug: Check large patches layer
    // Map.addLayer(fdapCommoditiesLargePatches, {palette: ["white","red"]}, "FDAP Large Patches (Debug)");
    // // Debug: Check static plantations layer
    // Map.addLayer(plantationsMosaicStatic, {palette: ["white","green"]}, "Plantations Mosaic Static (Debug)");
    // // Debug: Check oil palm mask
    // Map.addLayer(oilPalmMask, {palette: ["white","blue"]}, "Oil Palm Mask - all (Debug)");
    // Map.addLayer(plantationsMosaicStaticNoDescals, {palette: ["white","green"]}, "Plantations Mosaic Static No Descals(Debug)");

    return plantationsMosaicStaticNoDescals;
}

// Step 2b: Tree Crops only (SDPT class 2). Per FRA, tree crops
// (rubber, fruit, agroforestry) are agricultural land regardless of
// tree biology -- they do NOT count as planted forest. P1.18 uses
// this to exclude tree-cover-meeting agricultural land from the
// Forest baseline (FRA-aligned Forest = tree cover - agriculture).
// P1.20 reroutes SDPT class 2 + Descals oil palm out of the
// plantations layer entirely, leaving 02c_plantations as FRA
// Planted Forest (SDPT class 1) only. This helper gives consumers
// a clean Tree Crops layer alongside the new processingPlantedForestSDPT.
function processingTreeCropsSDPT(){
    var sdpt = ee.Image("projects/sdpt-v2/assets/sdpt_v2_simpleType_v09032024_public").unmask();
    return sdpt.eq(2);
}
exports.processingTreeCropsSDPT = processingTreeCropsSDPT;

// Step 2c: FRA Planted Forest only (SDPT class 1). P1.20: this is
// the FRA-faithful "Plantations" layer -- timber / pulp / fibre
// plantations (eucalyptus, pine, teak). It IS forest per FRA
// (just planted, not naturally regenerating), so it's the correct
// subtractor for deriving Naturally Regenerating Forest:
//   02d_naturally_regenerating_forest = 02b_forest - 02c_plantations
// Compare with processingPlantationsMosaic() which historically
// also bundled SDPT class 2 (tree crops) + Descals oil palm --
// per FRA those are agriculture, not forest, and now route through
// the disturbance/agriculture aggregation instead.
function processingPlantedForestSDPT(){
    var sdpt = ee.Image("projects/sdpt-v2/assets/sdpt_v2_simpleType_v09032024_public").unmask();
    return sdpt.eq(1);
}
exports.processingPlantedForestSDPT = processingPlantedForestSDPT;

exports.processingPlantationsMosaic = processingPlantationsMosaic

// Map.addLayer(processingPlantationsMosaic(),"","processingPlantationsMosaic")





// ---------------------------------------------------------------------
//modelled roads GRIP4_ExSet_1990_AADTpred_20240312

// GRIP4 rasterized (lazy-init: only computed when first accessed)
var _gripCache = {};
function _getGripRoads(year) {
  if (!_gripCache[year]) {
    _gripCache[year] = ee.FeatureCollection(
      "projects/ee-andyarnellgee/assets/p0002_primary_forest_support/raw/GRIP4_ExSet_" + year + "_AADTpred_20240312"
    ).reduceToImage(["median"], ee.Reducer.max()).set("year", year);
  }
  return _gripCache[year];
}

var getRoadsCollection = function() {
  // Create an ImageCollection from the lazy-loaded input years
  var roadImages = ee.ImageCollection([_getGripRoads(1990), _getGripRoads(2000), _getGripRoads(2015)]);

  // Define the target years for interpolation (including 2020)
  var targetYearsList = ee.List([1990, 2000, 2010, 2015, 2020]);

  // Interpolation function with 2020 as a special case
  var interpolateRoads = function(year) {
    year = ee.Number(year);

    // Special case for 2020: directly copy the 2015 image
    var specialCase2020 = ee.Algorithms.If(
      year.eq(2020),
      _getGripRoads(2015).set("year", 2020), // Copy values from 2015 and set year to 2020
      null
    );

    // Add a band for the year in the collection
    var collectionWithTime = roadImages.map(function(image) {
      return image.addBands(ee.Image.constant(image.get("year")).rename("year"));
    });

    // Find the closest images before and after the target year
    var before = collectionWithTime.filter(ee.Filter.lte("year", year)).sort("year", false).first();
    var after = collectionWithTime.filter(ee.Filter.gte("year", year)).sort("year").first();

    // Cast the years to ee.Number for math operations
    var beforeYear = ee.Number(before.get("year"));
    var afterYear = ee.Number(after.get("year"));

    // Handle edge cases (e.g., no interpolation needed)
    var interpolated = ee.Algorithms.If(
      beforeYear.eq(afterYear),
      ee.Image(before).set("year", year).select(0), // No interpolation needed, just copy the image
      // Linear interpolation
      ee.Image(before).select(0).multiply(afterYear.subtract(year))
        .add(ee.Image(after).select(0).multiply(year.subtract(beforeYear)))
        .divide(afterYear.subtract(beforeYear)).select(0)
        .set("year", year)
    );

    // Return special case for 2020 or interpolated result
    return ee.Image(ee.Algorithms.If(
      year.eq(2020),
      specialCase2020, // Use 2015 values for 2020
      interpolated      // Regular interpolation for other years
    ));
  };

  // Map the interpolation function over the target years
  return ee.ImageCollection(targetYearsList.map(interpolateRoads));

};

exports.getRoadsCollection = getRoadsCollection;

// Per-year GRIP4 roads with interpolation (uses cached module-level images)
var getGripRoadsForYear = function(year) {
  year = ee.Number(year);
  var roadImages = ee.ImageCollection([_getGripRoads(1990), _getGripRoads(2000), _getGripRoads(2015)]);

  var collectionWithTime = roadImages.map(function(image) {
    return image.addBands(ee.Image.constant(image.get("year")).rename("year"));
  });

  var before = collectionWithTime.filter(ee.Filter.lte("year", year)).sort("year", false).first();
  var after = collectionWithTime.filter(ee.Filter.gte("year", year)).sort("year").first();

  var beforeYear = ee.Number(before.get("year"));
  var afterYear = ee.Number(after.get("year"));

  var interpolated = ee.Algorithms.If(
    beforeYear.eq(afterYear),
    ee.Image(before).set("year", year).select(0),
    ee.Image(before).select(0).multiply(afterYear.subtract(year))
      .add(ee.Image(after).select(0).multiply(year.subtract(beforeYear)))
      .divide(afterYear.subtract(beforeYear)).select(0)
      .set("year", year)
  );

  // Years beyond 2015: use 2015 data (latest available)
  return ee.Image(ee.Algorithms.If(
    year.gt(2015),
    _getGripRoads(2015).set("year", year),
    interpolated
  ));
};
exports.getGripRoadsForYear = getGripRoadsForYear;


// ------------------ ACCESS INPUT DATASETS ------------------

// ------------------ FUNCTION TO GET ROADS UP TO YEAR ------------------

function getCongoRoadsUpToYear(year) {
  year = ee.Number(year);

  var forestRoads = ee.FeatureCollection(
    'projects/wurnrt-loggingroads/assets/distribution/forestroads_afr_2019-01_2024-12'
  );
  
  var oldRoads = ee.FeatureCollection(
    'projects/wurnrt-loggingroads/assets/kleinschroth/kleinschroth_etal_2019_natsust_data'
  );
  
  var forestMask = ee.Image(
    'projects/wurnrt-loggingroads/assets/distribution/forestmask'
  );
  
  // ------------------ FILTER AND CONVERT ROADS ------------------
  
  var oldRoadsPre2003 = oldRoads.filter(ee.Filter.stringContains("class", "old"));
  var oldRoads2003to2018 = oldRoads.filter(ee.Filter.stringContains("class", "new"));
  
  var roadsPre2003Img = oldRoadsPre2003
    .reduceToImage(['concession'], ee.Reducer.first())
    .gt(0)
    .selfMask();
  
  var roads2003to2018Img = oldRoads2003to2018
    .reduceToImage(['concession'], ee.Reducer.first())
    .gt(0)
    .selfMask();
  
  var roadsImg = forestRoads.reduceToImage(['MonthNum'], ee.Reducer.first());
  
  var roads2019to2020Img = roadsImg.lte(24).selfMask(); // Jan 2019 – Dec 2020
  var roadsPost2020Img = roadsImg.gte(25).selfMask();   // Jan 2021 onward

  
  // Server-side conditional accumulation
  // Pre-2003 roads always present; newer roads appear from their build period
  var roads = roadsPre2003Img.unmask(0)
    .max(roads2003to2018Img.unmask(0).multiply(year.gte(2003)))
    .max(roads2019to2020Img.unmask(0).multiply(year.gte(2019)))
    .max(roadsPost2020Img.unmask(0).multiply(year.gte(2021)));

  return roads.selfMask();
}

exports.getCongoRoadsUpToYear = getCongoRoadsUpToYear;

// ------------------ VISUALIZATION ------------------

// // Example usage: view roads existing by year XXXX
// var yearOfInterest = 2000;
// var roadsByYear = getCongoRoadsUpToYear(yearOfInterest);

// // Map.addLayer(forestMask.selfMask(), {min: 0, max: 1, palette: ['black']}, 'Forest Mask').setOpacity(0.25);
// Map.addLayer(roadsByYear, {palette: ['#1f78b4'], min: 0, max: 1}, 'Roads present by ' + yearOfInterest);

// // // Optional: show all time group layers for reference
// // Map.addLayer(roadsPre2003Img, {palette: ['#5e3c99']}, 'Roads Pre-2003');
// // Map.addLayer(roads2003to2018Img, {palette: ['#b2abd2']}, 'Roads 2003–2018');
// // Map.addLayer(roads2019to2020Img, {palette: ['#fdb863']}, 'Roads 2019–2020');
// // Map.addLayer(roadsPost2020Img, {palette: ['#e66101']}, 'Roads Post-2020');

// Map.setOptions('Satellite');
// Map.setCenter(15, 1, 7);


// Original roadsMosaicStatic with multiple vector sources (replaced by speed version below)
// function roadsMosaicStatic() {
//   var congoBasinForestRoads = ee.FeatureCollection("projects/wurnrt-loggingroads/assets/distribution/forestroads_afr_2019-01_2023-12");
//   var usaRoads = ee.FeatureCollection("projects/sat-io/open-datasets/TIGER/2025/Roads");
//   var osmRoadsImage = ee.Image("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/roadsAllImageOSM");
//   var usaRoadsImage = ee.Image(0).paint(usaRoads, 1).int8();
//   var congoBasinForestRoadsImage = ee.Image(0).paint(congoBasinForestRoads, 1).int8();
//   var mosaicRoads = ee.ImageCollection([osmRoadsImage]).max();
//   return mosaicRoads;
// }

// Speed version: raster-only, no vector paint
function roadsMosaicStatic() {
  var osmRoadsImage = ee.Image("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_osm/roadsAllImageOSM");
  return osmRoadsImage;
}


// // Call the function and display results
exports.roadsMosaicStatic= roadsMosaicStatic;

// var usaRoads = ee.FeatureCollection('TIGER/2016/Roads');
// var usaRoadsImage = ee.Image(0).paint(usaRoads, 1).int8();
// Map.addLayer(usaRoadsImage.selfMask(),{min: 0, max: 1, palette: ["white", "red"]}, "usaRoadsImage", 1, 1);
  
// var congoBasinForestRoads = ee.FeatureCollection("projects/wurnrt-loggingroads/assets/distribution/forestroads_afr_2019-01_2023-12");
// var congoBasinForestRoadsImage = ee.Image(0).paint(congoBasinForestRoads, 1).int8();
// Map.addLayer(congoBasinForestRoadsImage.selfMask(),{min: 0, max: 1, palette: ["white", "red"]}, "congoBasinForestRoadsImage", 1, 1);

// var ghostRoadsAsia = ee.FeatureCollection("projects/ee-andyarnellgee/assets/newguinea_ghostrds");
// var ghostRoadsAsiaImage = ee.Image(0).paint(ghostRoadsAsia, 1).int8();

// Map.addLayer(ghostRoadsAsiaImage.selfMask(),{min: 0, max: 1, palette: ["white", "red"]}, "ghost roads", 1, 1);

// var msRoadsImage = ee.Image("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_microsoft/roadsAllImageGlobal");

// var msRoadsImageBinary = msRoadsImage.gt(0).rename("constant")//change any width values 1 and rename
// Map.addLayer(msRoadsImageBinary.selfMask(),{min: 0, max: 1, palette: ["white", "blue"]}, "msRoadsImageBinary", 1, 1);
 
// var roads = roadsMosaicStatic() // only needed for direct visualization

// Map.addLayer(roads.selfMask(), {min: 0, max: 1, palette: ["white", "brown"]}, "roads", 1, 1);
  

function forest_disturbances(analysisYear) {
  var startYear = 1990;
  
  function prep_disturbance(imageCollection, endYear) {
    return imageCollection.filter(ee.Filter.lte('year', endYear))
                          .mosaic()
                          .gte(startYear);
  }

  var tmf_def = prep_disturbance(ee.ImageCollection('projects/JRC/TMF/v1_2025/DeforestationYear'), analysisYear);

  var hansen = ee.Image('UMD/hansen/global_forest_change_2024_v1_12');
  var gfc_loss = analysisYear >= 2000 
      ? hansen.select('lossyear').lte(analysisYear % 100)
          .and(hansen.select('treecover2000').gt(10))
      : ee.Image(0);

  return tmf_def.or(gfc_loss);
}

exports.forest_disturbances = forest_disturbances;

// // Visualization parameters
// var visParams = { min: 0, max: 1, palette: ['white', 'red'] };


// var analysisYear = 2020
// // Add result to the map
// Map.addLayer(forest_disturbances(analysisYear), visParams, 'Forest Disturbances Before'+analysisYear);

//////////////////
// Function to get Landscan Global population count as a time series
// NB using 2000 image for anything before then, i.e, 1990

//https://code.earthengine.google.com/0f2e21e036eabfe3b2a867ba17450275 see here for example use

function processLandscanPop() {
  var targetYears = [1990, 2000, 2010, 2015, 2020];
  
  var landscanCollection = ee.ImageCollection('projects/sat-io/open-datasets/ORNL/LANDSCAN_GLOBAL')
    .sort('system:time_start', false)
    .map(function(image) {
      var year = ee.Date(image.get('system:time_start')).get('year');
      return image.set('year', year);
    });
  
  // Filter collection to include only target years, replacing missing 1990 with 2000
  var images = targetYears.map(function(year) {
    if (year >=2000) {
      var image_after_2000 = landscanCollection.filter(ee.Filter.eq('year', year)).first();
      return image_after_2000;
    }
    else {
      var image_before_2000 = landscanCollection.filter(ee.Filter.eq('year', 2000)).first().set('year', year);
      return image_before_2000;
    }
  })//.filter(function(img) { return img !== null && img !== undefined; });
  
  return ee.ImageCollection(images);
}

exports.processLandscanPop = processLandscanPop;

// Per-year LandScan lookup (avoids building full collection)
var getLandscanForYear = function(year) {
  var lookupYear = year < 2000 ? 2000 : year;
  var landscanCollection = ee.ImageCollection('projects/sat-io/open-datasets/ORNL/LANDSCAN_GLOBAL')
    .filter(ee.Filter.calendarRange(lookupYear, lookupYear, 'year'));
  return landscanCollection.first().set('year', year);
};
exports.getLandscanForYear = getLandscanForYear;

// // Retrieve the processed Landscan collection
// var landscanCollection = processLandscanPop();

// // Visualization parameters
// var popcountViz = {
//   min: 1,
//   max: 18500,
//   palette: ['#CCCCCC', '#FFFFBE', '#FEFF73', '#FEFF2C', '#FFAA27', '#FF6625', '#FF0023', '#CC001A', '#730009']
// };

// // Checking visualization for specific years
// var targetYears = [1990, 2000, 2010, 2015, 2020];
// targetYears.forEach(function(year) {
//   var image = landscanCollection.filter(ee.Filter.eq('year', year)).first();
//   if (image) {
//     Map.addLayer(image.selfMask(), popcountViz, 'Population Count ' + year, false);
//   }
// });

//for use in analysis
//// var  landscanCollection = timeseriesAnthroModule.processLandscanPop()

// var landscanCollectionSel = landscanCollection.filter(ee.Filter.eq('year', analysisYear)).first()

// // Visualization parameters
// var popcountViz = {
//   min: 1,
//   max: 18500,
//   palette: ['#CCCCCC', '#FFFFBE', '#FEFF73', '#FEFF2C', '#FFAA27', '#FF6625', '#FF0023', '#CC001A', '#730009']
// };

// Map.addLayer(landscanCollectionSel,popcountViz,"landscanPop" )
  



//nat lands???
// var dataset = ee.Image('WRI/SBTN/naturalLands/v1_1/2020').select('natural');

// var lon = 0;
// var lat = 0;

// Map.setCenter(lon, lat, 2);

// Map.addLayer(dataset.eq(0).selfMask(),{palette:["blue"]}, 'Natural Lands');

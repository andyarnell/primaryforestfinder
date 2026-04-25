// ======================== DATA & PARAMS ========================
var countries = ee.FeatureCollection('USDOS/LSIB_SIMPLE/2017');
var property_name = 'country_na';
var default_country = "Cote d'Ivoire";

// Hansen GFC v1.12 (2000–2024)
var gfc = ee.Image('UMD/hansen/global_forest_change_2024_v1_12');
var treecover_threshold = 10;   // % canopy in 2000
var loss_year_param     = 2020; // exclude losses up to & incl. this year

var analysisYear = loss_year_param
// ======================== BASE IMAGES ==========================
var tree2000 = gfc.select('treecover2000').gt(treecover_threshold);
var lossyear = gfc.select('lossyear').unmask(0); // 0=no loss

// Keep = forest in 2000 AND (no loss OR loss after target year)
var keep = tree2000.and( lossyear.eq(0).or(lossyear.gt(loss_year_param - 2000)) );

// Forest remaining (pre-boundary); keep transparent background
var forestRemainBase = tree2000.updateMask(keep).selfMask();
var baseProj = tree2000.projection();

// ======================== UI LAYERS ============================
var forestLayer  = ui.Map.Layer(null, {min:0, max:1, palette:['d9f0a3','006837']},
                                'Forest remaining after ' + loss_year_param);
var outlineLayer = ui.Map.Layer(null, {}, 'Selected country');
Map.layers().add(forestLayer);
Map.layers().add(outlineLayer);

// ======================== ZOOM→SCALE ===========================
function scaleForZoom(z, base_scale, pivot_z, r, min_scale, max_scale) {
  var s = base_scale * Math.pow(r, (pivot_z - z));
  s = Math.round(s);
  return Math.min(max_scale, Math.max(min_scale, s));
}

// ======================== RENDERING ============================
var boundaryGeom = null; // set by dropdown

function render() {
  if (!boundaryGeom) return; // wait until a country is selected
  var z = Map.getZoom();
  var s = scaleForZoom(z, 30, 10, 1.8, 30, 900); // tweak r/min/max as you like
  print(s)
  print(z)
 
  var img = forestRemainBase
              .updateMask(ee.Image().byte()
    .paint(boundaryGeom, 1))                 // ⬅️ mask by selected boundary
              .reproject({crs: baseProj, scale: s});
  forestLayer.setEeObject(img);
}

// ======================== DROPDOWN UI ==========================
var panel = ui.Panel({style: {position: 'top-left', padding: '8px', width: '300px'}});
panel.add(ui.Label('Country'));
Map.add(panel);

countries.aggregate_array(property_name).distinct().sort().evaluate(function(nameList) {
  var select = ui.Select({
    items: nameList,
    value: default_country,
    onChange: selectCountry
  });
  panel.add(select);
  selectCountry(default_country); // initial selection
});

function selectCountry(name) {
  var fc = countries.filter(ee.Filter.eq(property_name, name));
  fc.size().evaluate(function(n) {
    if (!n) return;
    var geom = (fc).geometry();
    boundaryGeom = geom;

    // Outline
    var styled = fc.style({color: 'ff6b6b', width: 2, fillColor: '00000000'});
    outlineLayer.setEeObject(styled);

    // Zoom & render
    Map.centerObject(geom, 6);
    render();
  });
}

// Re-render when zoom changes (to adjust scale)
Map.onChangeZoom(render);

// function gladLulcForestPrep(analysisYear, treeHeightThreshold) {
//   var gladLandcoverLand = ee.Image('projects/glad/GLCLU2020/v2/LCLUC_' + analysisYear)
//     .updateMask(ee.Image("projects/glad/OceanMask").lte(1));

//   // Define remapping values
//   var fromValues = [
//     25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48,
//     125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147
//   ];
//   var toValues = [
//     3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26,
//     3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25
//   ];

//   // Remap landcover classes to tree height values
//   var gladLandcoverRemapped = gladLandcoverLand.remap(fromValues, toValues);

//   // Apply tree height threshold (binary output)
//   var gladLulcForestSel = gladLandcoverRemapped.gte(treeHeightThreshold);

//   return gladLulcForestSel.rename("gladLulcForestSel_" + analysisYear);
// }
// var treecoverHeightThreshold = 5
// Map.addLayer(gladLulcForestPrep(analysisYear,treecoverHeightThreshold),{palette:["green"]})
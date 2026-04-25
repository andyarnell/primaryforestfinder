// ======================== HANSEN ZOOM TEST ========================
// Standalone test to verify zoom-dependent rendering works correctly
// This is a simplified version to test the core functionality

// ======================== DATA & PARAMS ========================
var countries = ee.FeatureCollection('USDOS/LSIB_SIMPLE/2017');
var property_name = 'country_na';
var default_country = "Cote d'Ivoire";

// Hansen GFC v1.12 (2000–2024)
var gfc = ee.Image('UMD/hansen/global_forest_change_2024_v1_12');
var treecover_threshold = 10;   // % canopy in 2000
var loss_year_param = 2020;     // exclude losses up to & incl. this year

// ======================== BASE IMAGES ==========================
var tree2000 = gfc.select('treecover2000').gt(treecover_threshold);
var lossyear = gfc.select('lossyear').unmask(0); // 0=no loss

// Keep = forest in 2000 AND (no loss OR loss after target year)
var keep = tree2000.and(lossyear.eq(0).or(lossyear.gt(loss_year_param - 2000)));

// Forest remaining (pre-boundary); keep transparent background
var forestRemainBase = tree2000.updateMask(keep).selfMask();
var baseProj = tree2000.projection();

// ======================== UI LAYERS ============================
var forestLayer = ui.Map.Layer(
  null, 
  {min:0, max:1, palette:['d9f0a3','006837']},
  'Forest (GFC Hansen @ zoom)'
);
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
var currentCountryName = null;

function render() {
  if (!boundaryGeom) {
    print("⚠️ No country selected yet");
    return;
  }
  
  var z = Map.getZoom();
  var s = scaleForZoom(z, 30, 10, 1.8, 30, 900);
  
  print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  print("🔍 Zoom:", z);
  print("📏 Scale:", s + "m");
  print("🌍 Country:", currentCountryName);
  print("📅 Year:", loss_year_param);
  
  // Apply country boundary mask and reproject with zoom-dependent scale
  var img = forestRemainBase
    .updateMask(ee.Image().byte().paint(boundaryGeom, 1))
    .reproject({crs: baseProj, scale: s});
  
  // Update the layer
  forestLayer.setEeObject(img);
  forestLayer.setName('Forest (GFC Hansen ' + loss_year_param + ' @ ' + s + 'm)');
  
  print("✅ Layer updated successfully");
}

// ======================== DROPDOWN UI ==========================
var panel = ui.Panel({
  style: {
    position: 'top-left', 
    padding: '8px', 
    width: '300px',
    backgroundColor: 'white'
  }
});

panel.add(ui.Label({
  value: '🧪 Hansen Zoom Test',
  style: {fontWeight: 'bold', fontSize: '16px', margin: '0 0 8px 0'}
}));

panel.add(ui.Label({
  value: 'Select a country and zoom in/out to see the scale change:',
  style: {fontSize: '12px', margin: '0 0 8px 0'}
}));

panel.add(ui.Label('Country:', {fontWeight: 'bold'}));

Map.add(panel);

// Load country list and create dropdown
countries.aggregate_array(property_name).distinct().sort().evaluate(function(nameList) {
  var select = ui.Select({
    items: nameList,
    value: default_country,
    onChange: selectCountry,
    style: {width: '280px'}
  });
  panel.add(select);
  
  // Add instructions
  panel.add(ui.Label({
    value: '\n📌 Instructions:',
    style: {fontWeight: 'bold', margin: '8px 0 4px 0'}
  }));
  
  panel.add(ui.Label({
    value: '1. Select a country from dropdown\n2. Use mouse wheel to zoom in/out\n3. Watch the console for zoom/scale updates\n4. Check the layer name for current scale',
    style: {fontSize: '11px', whiteSpace: 'pre'}
  }));
  
  // Initial selection
  selectCountry(default_country);
});

function selectCountry(name) {
  currentCountryName = name;
  var fc = countries.filter(ee.Filter.eq(property_name, name));
  
  fc.size().evaluate(function(n) {
    if (!n) {
      print("❌ Country not found:", name);
      return;
    }
    
    var geom = fc.geometry();
    boundaryGeom = geom;

    // Outline style
    var styled = fc.style({
      color: 'ff6b6b', 
      width: 2, 
      fillColor: '00000000'
    });
    outlineLayer.setEeObject(styled);

    // Center on country and render
    print("\n🌍 Selected country:", name);
    Map.centerObject(geom, 6);
    render();
  });
}

// ======================== ZOOM LISTENER ============================
// Re-render when zoom changes (to adjust scale dynamically)
Map.onChangeZoom(render);

// ======================== INITIAL MESSAGE ============================
print("═══════════════════════════════════════");
print("🧪 HANSEN ZOOM TEST - READY");
print("═══════════════════════════════════════");
print("This test verifies that:");
print("• Zoom changes are detected");
print("• Scale is recalculated correctly");
print("• Layer updates dynamically");
print("• Layer name shows current scale");
print("\nTry zooming in and out now!");
print("═══════════════════════════════════════\n");

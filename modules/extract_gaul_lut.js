// Run this in GEE Code Editor to extract the GAUL LUT.
// Copy the printed output into your codebase.

var GAUL_2024_L0 = ee.FeatureCollection("projects/sat-io/open-datasets/FAO/GAUL/GAUL_2024_L0");

print('Total countries:', GAUL_2024_L0.size());

// Format each feature as a sortable string: "code|name|iso3"
// Zero-pad code to 4 digits so string sort = numeric sort
var formatted = GAUL_2024_L0.map(function(f) {
  var code = ee.Number(f.get('gaul0_code')).int();
  var name = ee.String(f.get('gaul0_name'));
  var iso3 = ee.String(f.get('iso3_code'));
  var line = ee.String('  ')
    .cat(code.format('%d'))
    .cat(': {name: "')
    .cat(name)
    .cat('", iso3: "')
    .cat(iso3)
    .cat('"}');
  // sortable key: zero-padded code
  return f.set('_line', line, '_sortKey', code.format('%04d'));
});

// Sort by code, then extract the formatted lines
var sortedLines = formatted.sort('_sortKey').aggregate_array('_line');

var jsObject = ee.String('var GAUL_LUT = {\n')
  .cat(sortedLines.join(',\n'))
  .cat('\n};');

print('--- COPY BELOW ---');
print(jsObject);

// Sorted name list for dropdown (strings sort fine)
var nameList = GAUL_2024_L0.aggregate_array('gaul0_name').distinct().sort();
print('--- SORTED NAMES FOR DROPDOWN ---');
print(nameList);

var image = ee.Image("UMD/hansen/global_forest_change_2024_v1_12");

/**** SETTINGS ****/

var TREECOVER_BAND = 'treecover2000';
var TREECOVER_THRESHOLD = 10;
var DOWNLOAD_SCALE = 90;

// Grid controls
var MAX_GRID = 13;    // allow up to 12 × 12
var DEFAULT_GRID = 6; // default 6 × 6

// Limits to avoid browser / EE overload (tiles)
var MAX_TILES_PER_CLICK = 170;  // per-run tile limit
var HARD_URL_LIMIT = 170;       // hard safety limit on number of URLs

// Area-based soft limits (km2)
var SAFE_AREA_6x6_KM2  = 420346;   // empirical safe area for 6×6 at 30 m
var SAFE_AREA_12x12_KM2 = 1681384; // extrapolated safe area for 12×12 at same per-tile size

// If true: tiles are clipped to AOI -> irregular edges, no data outside.
// If false: tiles are rectangular grid cells -> cleaner grid, may include some area outside AOI.
var CLIP_TILES_TO_AOI = false;

// Global handle for preview layer so we can remove/replace it
var tilePreviewLayer = null;


/**** 1. SOURCE IMAGE (binary) ****/

var img = image
  .select(TREECOVER_BAND)
  .gte(TREECOVER_THRESHOLD)
  .toByte();  // keep file size small

var imgVis = {min: 0, max: 1};
Map.addLayer(img, imgVis, 'Binary treecover >= ' + TREECOVER_THRESHOLD);


/**** 2. DRAWING TOOLS ****/

var drawingTools = Map.drawingTools();
drawingTools.setShown(true);
drawingTools.setShape('rectangle');
drawingTools.layers().reset();


/**** 3. LEFT PANEL (controls + links) ****/

var leftPanel = ui.Panel({
  style: {
    position: 'top-left',
    padding: '8px',
    width: '380px'
  }
});

var titleLabel = ui.Label('Download drawn area (tiled)', {
  fontWeight: 'bold',
  margin: '0 0 4px 0'
});

var hintLabel = ui.Label(
  '1. Draw a rectangle.\n' +
  '2. Choose rows/cols.\n' +
  '3. Click "Check AOI size & grid".\n' +
  '4. If okay, click "Create download links".\n' +
  '5. Copy & run the PowerShell script.',
  {fontSize: '11px'}
);

var infoLabel = ui.Label('', {fontSize: '11px', margin: '4px 0'});

// Grid sliders (default 6, max 12)
var rowsSlider = ui.Slider({
  min: 1, max: MAX_GRID, value: DEFAULT_GRID, step: 1,
  style: {width: '100%'}
});
var colsSlider = ui.Slider({
  min: 1, max: MAX_GRID, value: DEFAULT_GRID, step: 1,
  style: {width: '100%'}
});

var rowsLabel = ui.Label('Rows: ' + DEFAULT_GRID, {fontSize: '11px'});
var colsLabel = ui.Label('Cols: ' + DEFAULT_GRID, {fontSize: '11px'});

rowsSlider.onChange(function(v){ rowsLabel.setValue('Rows: ' + v); });
colsSlider.onChange(function(v){ colsLabel.setValue('Cols: ' + v); });

// Download links panel (scrolls via maxHeight)
var urlPanel = ui.Panel({
  style: {
    maxHeight: '200px',
    border: '1px solid #ccc',
    padding: '4px',
    margin: '4px 0'
  }
});


/**** 4. RIGHT PANEL (PowerShell script) ****/

var scriptTitleLabel = ui.Label('PowerShell script:', {
  fontWeight: 'bold',
  margin: '0 0 4px 0'
});

var scriptLabel = ui.Label('', {
  fontSize: '10px',
  whiteSpace: 'pre',  // preserve line breaks
  margin: '0'
});

var scriptPanel = ui.Panel({
  widgets: [scriptTitleLabel, scriptLabel],
  style: {
    position: 'top-right',
    padding: '8px',
    width: '380px',
    maxHeight: '450px',
    border: '1px solid #ccc'
  }
});
Map.add(scriptPanel);


/**** 5. TILE BUILDER ****/

// Returns an array of { geom: ee.Geometry, name: 'tile_X' }
function makeTilesFromGeometry(geom, nRows, nCols) {
  var coords = geom.bounds().coordinates().getInfo()[0];
  var ll = coords[0];
  var ur = coords[2];

  var west = ll[0];
  var south = ll[1];
  var east = ur[0];
  var north = ur[1];

  var dx = (east - west) / nCols;
  var dy = (north - south) / nRows;

  var tiles = [];
  var idx = 1;

  for (var r = 0; r < nRows; r++) {
    for (var c = 0; c < nCols; c++) {
      var rect = ee.Geometry.Rectangle(
        [west + c * dx, south + r * dy,
         west + (c + 1) * dx, south + (r + 1) * dy],
        null, false
      );

      var tileGeom = CLIP_TILES_TO_AOI
        ? rect.intersection(geom, ee.ErrorMargin(1))
        : rect;

      tiles.push({
        geom: tileGeom,
        name: 'tile_' + idx
      });
      idx++;
    }
  }
  return tiles;
}


/**** 6. AOI + GRID ANALYSIS (used by both buttons) ****/

function analyzeAoiAndGrid(aoi, nRows, nCols) {
  // Area in km2 (small non-zero margin)
  var areaKm2 = aoi.area(1).divide(1e6).getInfo();
  var totalTiles = nRows * nCols;

  var infoText =
    'AOI area: ~' + areaKm2.toFixed(0) + ' km²\n' +
    'Grid: ' + nRows + ' × ' + nCols + ' = ' + totalTiles +
    ' tiles at ' + DOWNLOAD_SCALE + ' m';

  // Warn if AOI is bigger than empirical safe size for 6×6
  if (areaKm2 > SAFE_AREA_6x6_KM2 && nRows <= 6 && nCols <= 6) {
    infoText +=
      '\n\n⚠ AOI is larger than the empirical safe limit of ~' +
      SAFE_AREA_6x6_KM2.toLocaleString() + ' km² for a 6×6 grid at 30 m.\n' +
      'You can increase rows/cols to reduce per-tile size, but expect the browser to hang\n' +
      'and possibly need to click "Wait" multiple times for the process to run.';
  }

  // Warn if AOI is bigger than estimated safe size for 12×12
  if (areaKm2 > SAFE_AREA_12x12_KM2) {
    infoText +=
      '\n\n⚠ AOI is also larger than the estimated ~' +
      SAFE_AREA_12x12_KM2.toLocaleString() +
      ' km² upper limit for 12×12 tiles at 30 m.\n' +
      'Even with many tiles you may hit memory or download-size limits.\n' +
      'Consider splitting the AOI into smaller regions before downloading.';
  }

  return {
    areaKm2: areaKm2,
    totalTiles: totalTiles,
    infoText: infoText
  };
}


/**** 7. BUTTONS (top of left panel) ****/

// 7a. Check-size button: only analyze + draw grid, no downloads
var checkButton = ui.Button({
  label: 'Check AOI size & grid',
  onClick: function() {
    infoLabel.setValue('');
    urlPanel.clear();
    scriptLabel.setValue('');

    var layers = drawingTools.layers();
    if (layers.length() === 0) {
      infoLabel.setValue('Draw a rectangle first.');
      return;
    }

    var aoi = layers.get(0).getEeObject();
    var nRows = rowsSlider.getValue();
    var nCols = colsSlider.getValue();

    var analysis = analyzeAoiAndGrid(aoi, nRows, nCols);
    infoLabel.setValue(analysis.infoText);

    // Always show grid preview on check
    var tiles = makeTilesFromGeometry(aoi, nRows, nCols);

    if (tilePreviewLayer !== null) {
      Map.layers().remove(tilePreviewLayer);
      tilePreviewLayer = null;
    }

    var fc = ee.FeatureCollection(
      tiles.map(function(t) {
        return ee.Feature(t.geom, {name: t.name});
      })
    );

    tilePreviewLayer = Map.addLayer(
      fc,
      {color: 'red'},
      'Tile grid preview'
    );
  },
  style: {margin: '0 0 4px 0'}
});

// 7b. Download button: area feedback + limits + URLs
var downloadButton = ui.Button({
  label: 'Create download links',
  onClick: downloadDrawnGeometryTiled,
  style: {margin: '0 0 4px 0'}
});

// Clear button: clears AOI, links, script, and preview grid
var clearButton = ui.Button({
  label: 'Clear AOI, links & preview',
  onClick: function() {
    drawingTools.layers().reset();
    infoLabel.setValue('');
    urlPanel.clear();
    scriptLabel.setValue('');
    if (tilePreviewLayer !== null) {
      Map.layers().remove(tilePreviewLayer);
      tilePreviewLayer = null;
    }
  },
  style: {margin: '0 0 8px 0'}
});

// Assemble left panel
leftPanel.add(titleLabel);
leftPanel.add(checkButton);
leftPanel.add(downloadButton);
leftPanel.add(clearButton);
leftPanel.add(hintLabel);
leftPanel.add(rowsLabel);
leftPanel.add(rowsSlider);
leftPanel.add(colsLabel);
leftPanel.add(colsSlider);
leftPanel.add(infoLabel);
leftPanel.add(ui.Label('Download links:', {fontWeight: 'bold'}));
leftPanel.add(urlPanel);
Map.add(leftPanel);


/**** 8. MAIN DOWNLOAD + GRID + LIMIT CHECKS ****/

function downloadDrawnGeometryTiled() {

  urlPanel.clear();
  scriptLabel.setValue('');
  infoLabel.setValue('');

  var layers = drawingTools.layers();
  if (layers.length() === 0) {
    infoLabel.setValue('Draw a rectangle first.');
    return;
  }

  var aoi = layers.get(0).getEeObject();
  var nRows = rowsSlider.getValue();
  var nCols = colsSlider.getValue();
  var total = nRows * nCols;

  // First: analyze AOI + grid and show all area-related feedback
  var analysis = analyzeAoiAndGrid(aoi, nRows, nCols);
  infoLabel.setValue(analysis.infoText + '\n\n(Proceeding to generate download links if limits allow.)');

  // Then: tile-count based limits
  if (total > MAX_TILES_PER_CLICK) {
    infoLabel.setValue(
      analysis.infoText +
      '\n\n🚫 Requested ' + total + ' tiles, which exceeds the per-run limit of ' +
      MAX_TILES_PER_CLICK + ' tiles.\n' +
      'Reduce rows/cols (e.g. 6×6 or smaller), or tile the area in multiple runs.'
    );
    return;
  }

  if (total > HARD_URL_LIMIT) {
    infoLabel.setValue(
      analysis.infoText +
      '\n\n🚫 Requested ' + total + ' tiles, which exceeds the hard limit of ' +
      HARD_URL_LIMIT + ' download URLs.\n' +
      'Please reduce rows/cols, or split the AOI into multiple runs.'
    );
    return;
  }

  var tiles = makeTilesFromGeometry(aoi, nRows, nCols);

  /***** 8a. Tile grid preview on the map *****/
  if (tilePreviewLayer !== null) {
    Map.layers().remove(tilePreviewLayer);
    tilePreviewLayer = null;
  }

  var fc = ee.FeatureCollection(
    tiles.map(function(t) {
      return ee.Feature(t.geom, {name: t.name});
    })
  );

  tilePreviewLayer = Map.addLayer(
    fc,
    {color: 'red'},
    'Tile grid preview'
  );

  /***** 8b. Build PowerShell script + download links *****/

  var scriptLines = [];
  scriptLines.push('# PowerShell download script');
  scriptLines.push('# Save as download_tiles.ps1');
  scriptLines.push('# Run from PowerShell:');
  scriptLines.push('#   PowerShell -ExecutionPolicy Bypass -File .\\download_tiles.ps1');
  scriptLines.push('');
  scriptLines.push('New-Item -ItemType Directory -Force -Path "tiles"');
  scriptLines.push('Set-Location "tiles"');
  scriptLines.push('');

  tiles.forEach(function(t) {
    var args = {
      name: 'treecover_' + t.name,
      crs: 'EPSG:4326',
      scale: DOWNLOAD_SCALE,
      region: t.geom
    };

    var url = img.getDownloadURL(args);

    urlPanel.add(ui.Label({
      value: 'Download ' + t.name,
      targetUrl: url
    }));

    // EE returns zip bundles for these URLs; save them as .zip
    scriptLines.push(
      'Invoke-WebRequest -Uri "' + url + '" -OutFile "' + args.name + '.zip"'
    );
  });

  scriptLabel.setValue(scriptLines.join('\n'));
}

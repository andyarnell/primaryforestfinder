// ============================================================================
// downloadViaUrl module
// GEE path: users/andyarnellgee/apps:modules/downloadViaUrl.js
//
// Reusable download-via-URL helpers for GEE apps and scripts.
// Works in both published Apps and the Code Editor (no Export/Tasks needed).
//
// Usage:
//   var dl = require('users/andyarnellgee/apps:modules/downloadViaUrl.js');
//   dl.downloadDirect(image, region, 100, 'my_layer', callback);
//   dl.downloadTiled(image, region, 100, 'my_layer', 4, 4, false, callback);
// ============================================================================

/**
 * Build a grid of tile geometries over a bounding box.
 * Always skips tiles that don't overlap the actual geometry (not just
 * its bbox).  Tiles are kept as clean rectangles — no clipping — so
 * output files have uniform dimensions.
 *
 * @param {ee.Geometry} geom   - Area of interest (country boundary, drawn polygon, etc.)
 * @param {number}      nRows  - Number of rows
 * @param {number}      nCols  - Number of columns
 * @returns {{tiles: Array<{geom: ee.Geometry, name: string}>,
 *            totalGrid: number, skipped: number}}
 */
exports.makeTiles = function(geom, nRows, nCols) {
  var coords = geom.bounds().coordinates().getInfo()[0];
  var ll = coords[0];
  var ur = coords[2];

  var west  = ll[0], south = ll[1];
  var east  = ur[0], north = ur[1];
  var dx = (east - west)  / nCols;
  var dy = (north - south) / nRows;

  // Build all tile rectangles over the bounding box
  var allRects = [];
  for (var r = 0; r < nRows; r++) {
    for (var c = 0; c < nCols; c++) {
      allRects.push(ee.Geometry.Rectangle(
        [west + c * dx,       south + r * dy,
         west + (c + 1) * dx, south + (r + 1) * dy],
        null, false
      ));
    }
  }

  var totalGrid = allRects.length;

  // Batch-check which tiles overlap the actual geometry (single server call).
  // This skips empty tiles (ocean, void) whose bbox rectangles fall outside
  // the real boundary — important for island nations, irregular shapes, etc.
  var features = allRects.map(function(rect, i) {
    return ee.Feature(rect, {idx: i});
  });
  var fc = ee.FeatureCollection(features);
  var overlappingIdxs = fc
    .filter(ee.Filter.intersects('.geo', geom, null, null, ee.ErrorMargin(100)))
    .aggregate_array('idx').getInfo();
  var keepSet = {};
  overlappingIdxs.forEach(function(i) { keepSet[i] = true; });

  var tiles = [];
  var idx = 1;
  for (var i = 0; i < allRects.length; i++) {
    if (keepSet[i]) {
      tiles.push({geom: allRects[i], name: 'tile_' + idx});
      idx++;
    }
  }
  return {tiles: tiles, totalGrid: totalGrid, skipped: totalGrid - tiles.length};
};

/**
 * Estimate AOI area and report grid info.
 *
 * @param {ee.Geometry} aoi
 * @param {number}      nRows
 * @param {number}      nCols
 * @param {number}      scale  - download scale in metres
 * @returns {{areaKm2: number, totalTiles: number, infoText: string}}
 */
exports.analyzeGrid = function(aoi, nRows, nCols, scale) {
  var areaKm2 = aoi.area(1).divide(1e6).getInfo();
  var totalTiles = nRows * nCols;

  var text =
    'AOI area: ~' + areaKm2.toFixed(0) + ' km²\n' +
    'Grid: ' + nRows + ' × ' + nCols + ' = ' + totalTiles +
    ' tiles at ' + scale + ' m';

  // Empirical limits (from downlaods_by_url.js testing)
  var SAFE_6x6  = 420346;
  var SAFE_12x12 = 1681384;

  if (areaKm2 > SAFE_6x6 && totalTiles <= 36) {
    text += '\n⚠ AOI exceeds ~' + SAFE_6x6.toLocaleString() +
      ' km² safe limit for ≤6×6 grid. Increase rows/cols or coarsen scale.';
  }
  if (areaKm2 > SAFE_12x12) {
    text += '\n⚠ AOI exceeds ~' + SAFE_12x12.toLocaleString() +
      ' km² upper limit even for 12×12. Split the AOI.';
  }

  return {areaKm2: areaKm2, totalTiles: totalTiles, infoText: text};
};

/**
 * Single-file download via getDownloadURL.
 * ~32 MB limit. Best for small countries or coarse scale.
 *
 * @param {ee.Image}    image
 * @param {ee.Geometry}  region
 * @param {number}       scale    - metres
 * @param {string}       name     - filename (no extension)
 * @param {function}     callback - function(url, err)
 * @param {Object}       [opts]   - optional overrides {crs, maxPixels, format}
 */
exports.downloadDirect = function(image, region, scale, name, callback, opts) {
  opts = opts || {};
  image.getDownloadURL({
    name: name,
    region: region,
    scale: scale,
    crs: opts.crs || 'EPSG:4326',
    maxPixels: opts.maxPixels || 1e9,
    filePerBand: false,
    format: opts.format || 'GeoTIFF'
  }, callback);
};

/**
 * Tiled download via getDownloadURL — splits large region into a grid.
 * Each tile gets its own download URL.
 *
 * @param {ee.Image}    image
 * @param {ee.Geometry}  region
 * @param {number}       scale      - metres
 * @param {string}       namePrefix - base filename
 * @param {number}       nRows
 * @param {number}       nCols
 * @param {function}     tileCallback - called per tile: function(tileName, url, err)
 * @param {Object}       [opts]     - optional overrides {crs, maxPixels, format}
 */
exports.downloadTiled = function(image, region, scale, namePrefix, nRows, nCols, tileCallback, opts) {
  opts = opts || {};
  var result = exports.makeTiles(region, nRows, nCols);

  result.tiles.forEach(function(t) {
    image.getDownloadURL({
      name: namePrefix + '_' + t.name,
      region: t.geom,
      scale: scale,
      crs: opts.crs || 'EPSG:4326',
      maxPixels: opts.maxPixels || 1e9,
      filePerBand: false,
      format: opts.format || 'GeoTIFF'
    }, function(url, err) {
      tileCallback(t.name, url, err);
    });
  });
};

/**
 * Calculate the minimum grid dimensions to keep each tile under the
 * getDownloadURL size limit (~32 MB).
 *
 * @param {ee.Geometry}  region
 * @param {number}       scale       - download scale in metres
 * @param {number}       [bytesPerPx] - bytes per pixel (default 1 for toByte)
 * @param {number}       [maxBytes]   - per-tile byte budget (default 30 MB, conservative)
 * @returns {{rows: number, cols: number, totalTiles: number, areaKm2: number,
 *            tileAreaKm2: number, feasible: boolean, message: string}}
 */
exports.autoGrid = function(region, scale, bytesPerPx, maxBytes) {
  bytesPerPx = bytesPerPx || 2;   // GEE getDownloadURL typically encodes ~2 bytes/pixel
  maxBytes   = maxBytes   || 40e6; // 40 MB conservative (GEE limit is ~48 MB / 50331648 bytes)

  // Use bounding box area, not geodesic area — tiles are rectangular
  var bounds = region.bounds();
  var bboxAreaKm2 = bounds.area(1).divide(1e6).getInfo();
  var bboxAreaM2  = bboxAreaKm2 * 1e6;

  // Pixels per tile that fit in maxBytes
  var maxPixelsPerTile = maxBytes / bytesPerPx;
  // Area each tile can cover
  var tileAreaM2 = maxPixelsPerTile * (scale * scale);
  var tileAreaKm2 = tileAreaM2 / 1e6;

  // How many tiles needed
  var tilesNeeded = Math.ceil(bboxAreaM2 / tileAreaM2);
  // Square-ish grid
  var side = Math.ceil(Math.sqrt(tilesNeeded));
  // Cap at reasonable maximum
  var MAX_SIDE = 20;
  var rows = Math.min(side, MAX_SIDE);
  var cols = Math.min(side, MAX_SIDE);
  var totalTiles = rows * cols;

  var feasible = (rows * cols >= tilesNeeded);
  var message;
  if (feasible) {
    message = 'Auto grid: ' + rows + '×' + cols + ' = ' + totalTiles +
      ' tiles (~' + Math.round(tileAreaKm2) + ' km² each)' +
      ' [bbox ~' + Math.round(bboxAreaKm2) + ' km²].\n' +
      'Non-overlapping tiles will be skipped automatically.';
  } else {
    message = 'Too large for tiled download at ' + scale + 'm (' +
      Math.round(bboxAreaKm2) + ' km² bbox needs ~' + tilesNeeded + ' tiles). ' +
      'Use Export to Drive (script mode) or increase scale.';
  }

  return {
    rows: rows,
    cols: cols,
    totalTiles: totalTiles,
    areaKm2: bboxAreaKm2,
    tileAreaKm2: tileAreaKm2,
    feasible: feasible,
    message: message
  };
};

/**
 * Build a PowerShell download script from an array of {name, url} objects.
 * Uses parallel background jobs for faster downloads.
 *
 * @param {Array<{name: string, url: string}>} items
 * @param {string} [folder]    - subfolder name (default 'tiles')
 * @returns {string} PowerShell script text
 */
/**
 * Build a PowerShell download script from an array of {name, url} objects.
 * Optionally supports parallel downloads using Start-Job.
 *
 * @param {Array<{name: string, url: string}>} items
 * @param {string} [folder]    - subfolder name (default 'tiles')
 * @param {boolean} [parallel] - if true, use parallel jobs
 * @returns {string} PowerShell script text
 */
exports.buildPowerShellScript = function(items, folder, parallel) {
  function getDateStamp() {
    var d = new Date();
    var pad = function(n) { return n < 10 ? '0' + n : n; };
    var date = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    var time = pad(d.getHours()) + 'h' + pad(d.getMinutes()) + 'm';
    return date + '_' + time;
  }
  folder = folder || ('pff_tiles_' + getDateStamp());

  // Cross-platform Downloads folder logic
  // Windows: $env:USERPROFILE\Downloads
  // macOS/Linux: ~/Downloads
  var downloadsVar = 'if ($IsWindows) { $downloads = Join-Path $env:USERPROFILE "Downloads" } else { $downloads = "~/Downloads" }';
  var folderPathVar = '$folderPath = Join-Path $downloads "' + folder + '"';

  var lines = [
    '# PowerShell download script',
    '# Save as download_tiles.ps1, then either:',
    '#   1. Right-click the .ps1 file → Run with PowerShell (Windows)',
    '#   2. Run:  PowerShell -ExecutionPolicy Bypass -File .\\download_tiles.ps1',
    '#   3. Or paste this script directly into a PowerShell window',    '#',
    '# NOTE: Download URLs expire ~2 hours after generation.',
    '#   The script can be re-run within that window.',    '',
    '$IsWindows = $env:OS -eq "Windows_NT"',
    downloadsVar,
    folderPathVar,
    'New-Item -ItemType Directory -Force -Path $folderPath',
    'Push-Location $folderPath',
    '',
    '$startTime = Get-Date'
  ];
  var total = items.length;
  if (parallel) {
    lines.push('$jobs = @()');
    items.forEach(function(item, idx) {
      var tileName = 'tile_' + (idx + 1) + '_of_' + total;
      // Pass $folderPath into the job via -ArgumentList so OutFile resolves correctly
      lines.push('$jobs += Start-Job -ArgumentList $folderPath -ScriptBlock { param($dir); Invoke-WebRequest -Uri "' + item.url + '" -OutFile (Join-Path $dir "' + tileName + '.tif") -ErrorAction Stop }');
    });
    lines.push('');
    lines.push('Write-Host "Waiting for ' + total + ' parallel downloads to finish..."');
    lines.push('Wait-Job -Job $jobs | Out-Null');
    lines.push('$allErrors = @()');
    lines.push('foreach ($job in $jobs) {');
    lines.push('  try { Receive-Job -Job $job -ErrorAction Stop | Out-Null }');
    lines.push('  catch { $allErrors += $_.Exception.Message }');
    lines.push('}');
    lines.push('Remove-Job -Job $jobs');
    lines.push('if ($allErrors.Count -gt 0) { $allErrors | Out-File -FilePath "errors.txt" -Encoding UTF8 }');
  } else {
    items.forEach(function(item, idx) {
      var tileName = 'tile_' + (idx + 1) + '_of_' + total;
      lines.push('try {');
      lines.push('  Invoke-WebRequest -Uri "' + item.url + '" -OutFile "' + tileName + '.tif" -ErrorAction Stop');
      lines.push('} catch { $_ | Out-File -FilePath "errors.txt" -Append -Encoding UTF8 }');
    });
  }
  // Add a message and blank lines to ensure last download completes
  lines.push('');
  lines.push('$endTime = Get-Date');
  lines.push('$duration = $endTime - $startTime');
  lines.push('Write-Host "Download complete."');
  lines.push('Write-Host "Total processing time: $($duration.Minutes) min $($duration.Seconds) sec"');
  lines.push('');
  // If errors.txt exists and is not empty, copy to README.txt with a summary
  lines.push('if ((Test-Path "errors.txt") -and ((Get-Content "errors.txt" -ErrorAction SilentlyContinue).Length -gt 0)) {');
  lines.push('  "Some downloads failed. See errors.txt for details." | Out-File -FilePath "README.txt" -Encoding UTF8');
  lines.push('  Get-Content "errors.txt" | Add-Content "README.txt"');
  lines.push('}');
  lines.push('');
  lines.push('Pop-Location');
  lines.push('');
  return lines.join('\n');
};

/**
 * Build a Python download script from an array of {name, url} objects.
 * Uses only stdlib (urllib, os, pathlib) — no pip install needed.
 * Works on Windows, macOS, and Linux.
 *
 * @param {Array<{name: string, url: string}>} items
 * @param {string} [folder]    - subfolder name (default auto-dated)
 * @returns {string} Python script text
 */
exports.buildPythonScript = function(items, folder) {
  function getDateStamp() {
    var d = new Date();
    var pad = function(n) { return n < 10 ? '0' + n : n; };
    var date = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    var time = pad(d.getHours()) + 'h' + pad(d.getMinutes()) + 'm';
    return date + '_' + time;
  }
  folder = folder || ('pff_tiles_' + getDateStamp());
  var total = items.length;

  var lines = [
    '#!/usr/bin/env python3',
    '"""',
    'Download script — save as download_tiles.py then run:',
    '  python download_tiles.py',    '',
    'NOTE: Download URLs expire ~2 hours after generation.',
    '  The script can be re-run within that window.',    '"""',
    'import os, sys, time, urllib.request, pathlib',
    '',
    'downloads = str(pathlib.Path.home() / "Downloads")',
    'folder = os.path.join(downloads, "' + folder + '")',
    'os.makedirs(folder, exist_ok=True)',
    '',
    'tiles = ['
  ];
  items.forEach(function(item, idx) {
    var tileName = 'tile_' + (idx + 1) + '_of_' + total;
    lines.push('    ("' + tileName + '.tif", "' + item.url + '"),');
  });
  lines.push(']');
  lines.push('');
  lines.push('errors = []');
  lines.push('start = time.time()');
  lines.push('for i, (name, url) in enumerate(tiles, 1):');
  lines.push('    out = os.path.join(folder, name)');
  lines.push('    print(f"Downloading {i}/{len(tiles)}: {name}...")');
  lines.push('    try:');
  lines.push('        urllib.request.urlretrieve(url, out)');
  lines.push('    except Exception as e:');
  lines.push('        errors.append(f"{name}: {e}")');
  lines.push('        print(f"  ERROR: {e}")');
  lines.push('');
  lines.push('elapsed = time.time() - start');
  lines.push('mins, secs = int(elapsed // 60), int(elapsed % 60)');
  lines.push('print(f"Download complete. Total time: {mins} min {secs} sec")');
  lines.push('print(f"Files saved to: {folder}")');
  lines.push('');
  lines.push('if errors:');
  lines.push('    err_path = os.path.join(folder, "errors.txt")');
  lines.push('    with open(err_path, "w") as f:');
  lines.push('        f.write("\\n".join(errors))');
  lines.push('    print(f"Some downloads failed — see {err_path}")');
  lines.push('');
  return lines.join('\n');
};

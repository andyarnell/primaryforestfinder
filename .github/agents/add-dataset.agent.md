---
name: add-dataset
description: Add or substitute datasets in the Primary Forest Finder GEE tool
---

# Add Dataset Agent

You help integrate new datasets into the Primary Forest Finder (PFF) Google Earth Engine app. This includes global datasets, national datasets, and user-uploaded assets.

## Context: PFF tool

This repository implements a Primary Forest analysis tool in Google Earth Engine.

The app:
- combines multiple datasets (global and national)
- distinguishes forest, anthropogenic, and other natural land classes
- supports dataset substitution (global vs national)
- applies buffering and masking to define likely primary forest
- uses consistent logic across multiple time steps

When modifying dataset handling, ensure compatibility with this workflow.

## When to use this agent

- Adding a new anthropogenic layer (roads, built-up, agriculture, plantations, etc.)
- Substituting a global dataset with a national or custom one
- Wiring a user-uploaded GEE asset into the pipeline
- Adjusting how an existing dataset is loaded, filtered, or classified

## Dataset integration checklist

Every new dataset must follow these steps:

### 1. Create an export function in `modules/timeSeriesAnthro.js`

Return an `ee.ImageCollection` with one image per target year. Each image must have:
- `year` property (numeric) — one of `[1990, 2000, 2010, 2015, 2020]`
- `system:time_start` — `ee.Date.fromYMD(year, 1, 1).millis()`
- `system:index` — string representation of year
- **Binary values**: 0 = absence, 1 = presence (for anthropogenic layers)

Pattern:
```javascript
var processNewDatasetYear = function(year) {
  var asset = ee.ImageCollection("projects/.../dataset");
  return asset.filter(ee.Filter.eq('year', year)).first()
    .gt(0)
    .set({
      'year': year,
      'system:time_start': ee.Date.fromYMD(year, 1, 1).millis(),
      'system:index': year.toString()
    });
};

function getNewDatasetCollection() {
  var targetYears = [1990, 2000, 2010, 2015, 2020];
  return ee.ImageCollection(targetYears.map(processNewDatasetYear));
}

exports.getNewDatasetCollection = getNewDatasetCollection;
```

### 2. Wire into the distance pipeline in `pff.js`

In the `exportRastersToDrive` function:
```javascript
// Load and filter to year
var newDataSel = timeseriesAnthroModule.getNewDatasetCollection()
  .filter(ee.Filter.eq('year', analysisYear)).first();

// Compute distance buffer
var buffer_from_new_data = makeDistanceBuffer(newDataSel, newDataThreshold);

// Add to anthropogenic zone (OR union)
var anthropogenic_zone = anthropogenic_zone.or(buffer_from_new_data);
```

### 3. For cumulative layers, apply forward-fill

If a pixel's state is permanent once it appears (e.g., cropland, built-up), wrap the collection:
```javascript
exports.getNewDatasetFF = function() {
  return forwardFillBinaryTimeSeries(getNewDatasetCollection(), targetYears);
};
```

### 4. For static (single-epoch) datasets

Some datasets have no time dimension. Return a single `ee.Image` directly:
```javascript
exports.newStaticDataset = function() {
  return ee.Image("projects/.../static_asset").gt(0);
};
```

### 5. For user-uploaded custom assets

Users can supply their own GEE asset paths. The existing pattern uses UI textboxes:
- Asset path format: `users/username/assetName` or `projects/.../asset`
- Load via `ee.Image(userPath)` — no module function needed
- Must be binary (0/1) and match the expected spatial extent

## Dataset categories and their pipeline roles

| Category | Role in pipeline | Distance threshold | Example datasets |
|----------|-----------------|-------------------|------------------|
| Roads (major) | anthropogenic buffer | 1500 m | GRIP4, OSM |
| Roads (minor) | anthropogenic buffer | 1000 m | OSM, national roads |
| Built-up (large) | anthropogenic buffer | 2000 m | GHSL, WSF |
| Built-up (small) | anthropogenic buffer | 2000 m | GISD30, GISA |
| Agriculture | anthropogenic buffer | 1000 m | GLAD croplands |
| Plantations | anthropogenic buffer | (combined with agriculture) | SDPT, FDAP |
| Forest | base layer | N/A | Hansen, custom |
| Protected areas | tier 3 override | N/A | WDPA |
| Population | supplementary | varies | LandScan |

## Preprocessing national / custom datasets

National datasets rarely arrive as binary 0/1 rasters. Six inline preprocessing operations cover ~90% of cases. These run server-side in GEE when loading the asset — no separate step needed.

### Supported preprocessing operations

| # | Operation | When to use | Config key | GEE implementation |
|---|-----------|------------|------------|--------------------|
| 1 | **Select band** | Multi-band raster (pick one band) | `"band": "classification"` or `"band": 0` | `.select(band)` |
| 2 | **Select classes → binary** | LULC / categorical raster | `"classes": [1, 2, 5, 12]` | `.remap(classes, ones).gt(0).unmask(0)` |
| 3 | **Threshold continuous value** | Canopy %, density, height | `"threshold": {"min": 30}` or `{"max": 45}` or `{"min": 10, "max": 80}` | `.gte(min)` / `.lte(max)` / both `.and()` |
| 4 | **Filter features by attribute** | Vector (FeatureCollection) | `"filter": {"field": "highway", "values": ["trunk", "primary"]}` | `.filter(ee.Filter.inList(field, values))` |
| 5 | **Filter by year** | Time-series collection or property | `"year_filter": {"field": "year", "value": 2020}` | `.filter(ee.Filter.eq(field, value))` |
| 6 | **Mosaic tiles** | Tiled/multi-image asset | `"mosaic": true` | `.mosaic()` (or `.max()` for binary) |

### Operations NOT needed here (handled elsewhere in the pipeline)

| Operation | Why it's already covered |
|-----------|------------------------|
| **Distance buffering** | `makeDistanceBuffer()` applies the configured threshold — this IS the spatial influence zone for points, lines, and polygons alike |
| **Dissolve** | Inherent in rasterization — overlapping geometries burned to the same value merge automatically |
| **Reproject / resample** | GEE handles this implicitly via `.reproject()` and at computation time |
| **Clip to AOI** | Done at pipeline level using the study area boundary |
| **Forward-fill** | Controlled by the existing `"forward_fill": true` flag |
| **NoData handling** | `.unmask(0)` is applied after reclassification |
| **Buffer points/lines** | Point and line datasets rasterize as single pixels; the distance buffer step expands their influence to the configured threshold — no pre-buffering needed |

### The `preprocessAsset` module (`modules/preprocessDataset.js`)

This lives in its own module — it's a generic utility independent of any specific dataset. The main app and `applyDatasetConfig` require it via:

```javascript
var preprocessModule = require('users/andyarnellgee/apps:modules/preprocessDataset');
var preprocessAsset = preprocessModule.preprocessAsset;
```

**`modules/preprocessDataset.js`:**

```javascript
/**
 * Apply preprocessing steps to a raw asset based on a config object.
 * Handles: band selection, class reclassification, thresholding,
 * attribute filtering (vectors), year filtering, and mosaicking.
 *
 * @param {string} assetPath - GEE asset path
 * @param {Object} preprocessing - Config object with optional keys:
 *   band, classes, threshold, filter, year_filter, mosaic
 * @param {string} sourceType - 'image', 'image_collection', or 'feature_collection' (alias: 'table')
 * @return {ee.Image} Binary image (0/1)
 */
exports.preprocessAsset = function(assetPath, preprocessing, sourceType) {
  preprocessing = preprocessing || {};
  sourceType = sourceType || 'image';

  var result;

  // --- Load asset by type ---
  if (sourceType === 'feature_collection' || sourceType === 'table') {
    // Vector: FeatureCollection
    var fc = ee.FeatureCollection(assetPath);

    // Attribute filter (e.g. select road types)
    if (preprocessing.filter) {
      fc = fc.filter(ee.Filter.inList(
        preprocessing.filter.field,
        preprocessing.filter.values
      ));
    }

    // Rasterize to binary: paint features as 1, background 0
    result = ee.Image(0).byte()
      .paint(fc, 1)
      .rename('presence');

  } else if (sourceType === 'image_collection') {
    // ImageCollection (tiled or time-series)
    var ic = ee.ImageCollection(assetPath);

    // Year filter
    if (preprocessing.year_filter) {
      ic = ic.filter(ee.Filter.eq(
        preprocessing.year_filter.field,
        preprocessing.year_filter.value
      ));
    }

    // Mosaic tiles
    if (preprocessing.mosaic) {
      result = ic.max(); // .max() for binary; equivalent to OR
    } else {
      result = ic.first();
    }

  } else {
    // Single ee.Image (most common)
    result = ee.Image(assetPath);
  }

  // --- Band selection ---
  if (preprocessing.band !== undefined) {
    result = result.select(preprocessing.band);
  }

  // --- Class selection (reclassify to binary) ---
  if (preprocessing.classes) {
    var classes = preprocessing.classes;
    var ones = ee.List.repeat(1, classes.length);
    result = result.remap(classes, ones, 0).gt(0);
  }

  // --- Threshold continuous value ---
  if (preprocessing.threshold) {
    var t = preprocessing.threshold;
    if (t.min !== undefined && t.max !== undefined) {
      result = result.gte(t.min).and(result.lte(t.max));
    } else if (t.min !== undefined) {
      result = result.gte(t.min);
    } else if (t.max !== undefined) {
      result = result.lte(t.max);
    }
  }

  // --- Ensure binary and clean NoData ---
  result = result.gt(0).unmask(0).byte().rename('presence');

  return result;
};
```

### Preprocessing config examples by input type

**LULC raster — select forest classes:**
```json
{
  "preprocessing": {
    "band": "classification",
    "classes": [1, 2, 5]
  }
}
```

**Continuous raster — threshold canopy cover ≥ 30%:**
```json
{
  "preprocessing": {
    "band": 0,
    "threshold": {"min": 30}
  }
}
```

**Vector — select major roads by attribute:**
```json
{
  "preprocessing": {
    "filter": {"field": "road_class", "values": ["national", "primary", "trunk"]}
  }
}
```

**Tiled ImageCollection — mosaic + select band:**
```json
{
  "preprocessing": {
    "band": "land_cover",
    "classes": [40, 41, 42],
    "mosaic": true
  }
}
```

**Time-series collection — filter to year then mosaic:**
```json
{
  "preprocessing": {
    "year_filter": {"field": "year", "value": 2020},
    "mosaic": true
  }
}
```

**Already binary raster — no preprocessing needed:**
```json
{
  "preprocessing": {}
}
```

The empty/missing `preprocessing` key is the simplest path. The function falls through to `.gt(0).unmask(0)` which safely handles already-binary inputs.

## UI patterns for dataset configuration

The app already has several UI patterns. Choose the right one depending on complexity.

### Pattern A: Simple toggle (boolean flag or checkbox)

For switching a single dataset on/off. Use a top-level variable or `ui.Checkbox`:

```javascript
var includeNewDataset = true; // or wire to ui.Checkbox

var includeNewDatasetCheckbox = ui.Checkbox({
  label: 'Include new dataset',
  value: true,
  onChange: updateMap
});
```

### Pattern B: Dropdown for source selection

When the user picks one dataset from several alternatives (e.g., Hansen vs GLAD forest):

```javascript
var sourceSelect = ui.Select({
  items: ['Global (GRIP4)', 'National roads', 'Custom asset'],
  value: 'Global (GRIP4)',
  onChange: function(value) {
    customAssetPanel.style().set('shown', value === 'Custom asset');
    updateMap();
  }
});
```

### Pattern C: Per-year asset textboxes

For user-uploaded assets that vary by year. Creates one textbox per target year:

```javascript
var assetInputs = {};
var assetPanel = ui.Panel({style: {shown: false}});

years.forEach(function(year) {
  var row = ui.Panel({layout: ui.Panel.Layout.flow('horizontal')});
  row.add(ui.Label('Year ' + year + ':', {width: '80px'}));
  var input = ui.Textbox({
    placeholder: 'users/username/asset_' + year,
    onChange: updateMap,
    style: {width: '200px'}
  });
  assetInputs[year] = input;
  row.add(input);
  assetPanel.add(row);
});
```

### Pattern D: JSON paste-in config (recommended for many datasets × years)

When the number of datasets and years makes individual textboxes impractical, use a JSON config that the user pastes in. This mirrors the existing save/load settings pattern.

**JSON schema for custom dataset config:**
```json
{
  "datasets": [
    {
      "name": "national_roads",
      "category": "roads_major",
      "source_type": "feature_collection",
      "preprocessing": {
        "filter": {"field": "road_class", "values": ["national", "primary", "trunk"]}
      },
      "assets": {
        "1990": "users/someone/roads_1990",
        "2000": "users/someone/roads_2000",
        "2020": "users/someone/roads_2020"
      },
      "threshold_m": 1500,
      "forward_fill": false
    },
    {
      "name": "national_lulc_agriculture",
      "category": "agriculture",
      "source_type": "image",
      "preprocessing": {
        "band": "classification",
        "classes": [40, 41, 42, 43]
      },
      "assets": {
        "2020": "users/someone/national_lulc_2020"
      },
      "threshold_m": 1000,
      "forward_fill": true
    },
    {
      "name": "national_builtup",
      "category": "builtup",
      "source_type": "image",
      "preprocessing": {},
      "assets": {
        "2020": "users/someone/builtup_2020"
      },
      "threshold_m": 2000,
      "forward_fill": true
    }
  ]
}
```

**Config fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Human-readable identifier |
| `category` | yes | Pipeline role: `roads_major`, `roads_minor`, `builtup`, `agriculture`, `forest`, `protected` |
| `source_type` | no | `"image"` (default), `"image_collection"`, or `"feature_collection"` (vector; alias: `"table"`) |
| `preprocessing` | no | Object with any combination of: `band`, `classes`, `threshold`, `filter`, `year_filter`, `mosaic`. Omit or use `{}` for already-binary rasters |
| `assets` | yes | Object mapping year strings to GEE asset paths |
| `threshold_m` | yes (anthro) | Distance buffer in metres |
| `forward_fill` | no | `true` to apply cumulative forward-fill across target years |

**UI implementation:**
```javascript
var preprocessModule = require('users/andyarnellgee/apps:modules/preprocessDataset');
var targetYears = [1990, 2000, 2010, 2015, 2020];
var customDatasets = {};

var datasetConfigTextbox = ui.Textbox({
  placeholder: 'Paste dataset config JSON here and press Enter',
  style: {width: '400px', height: '150px'},
  onChange: ui.util.debounce(function(value) {
    try {
      var config = JSON.parse(value);
      if (config.datasets) {
        customDatasets = preprocessModule.applyDatasetConfig(config.datasets, targetYears);
        statusLabel.setValue('Loaded ' + config.datasets.length + ' custom datasets.');
        statusLabel.style().set('color', 'green');
      }
    } catch (e) {
      statusLabel.setValue('Invalid JSON: ' + e.message);
      statusLabel.style().set('color', 'red');
    }
  }, 300)
});

var statusLabel = ui.Label('', {color: 'gray'});
```

**Applying the config (using the module):**
```javascript
var preprocessModule = require('users/andyarnellgee/apps:modules/preprocessDataset');

var targetYears = [1990, 2000, 2010, 2015, 2020];

// Parse JSON and build all custom datasets in one call
var customDatasets = preprocessModule.applyDatasetConfig(config.datasets, targetYears);
// Returns: { 'roads_major': {collection, threshold, name}, 'agriculture': {...}, ... }
```

**Reading custom datasets in the pipeline:**
```javascript
// In the distance computation section
if (customDatasets['roads_major']) {
  var customRoads = customDatasets['roads_major'].collection
    .filter(ee.Filter.eq('year', analysisYear)).first();
  var buffer = makeDistanceBuffer(customRoads,
    customDatasets['roads_major'].threshold);
  anthropogenic_zone = anthropogenic_zone.or(buffer);
}
```

### Pattern E: Include config in save/load settings

Custom dataset configs should round-trip through the existing export/import mechanism. Add the JSON config to `collectSettings()` and restore it in `applySettings()`:

```javascript
// In collectSettings():
settings['Custom Dataset Config'] = JSON.stringify(customDatasetConfig);

// In applySettings():
if (settings['Custom Dataset Config']) {
  var config = JSON.parse(settings['Custom Dataset Config']);
  customDatasets = preprocessModule.applyDatasetConfig(config.datasets, targetYears);
}
```

### Choosing a UI pattern

| Scenario | Pattern |
|----------|---------|
| Toggle one built-in dataset on/off | A (checkbox) |
| Pick between 2–3 source alternatives | B (dropdown) |
| One custom asset, multiple years | C (per-year textboxes) |
| Multiple custom assets across years | D (JSON paste-in) |
| Persist user choices across sessions | E (save/load) |

## Rules

- Always use Earth Engine server-side objects — no `.getInfo()` in dataset functions.
- Do not modify unrelated datasets or pipeline steps.
- Keep each dataset function self-contained and independently testable.
- Follow the existing module pattern: `exports.functionName = function() {...}`.
- When substituting a national dataset for a global one, preserve the same output shape (binary ImageCollection with year metadata).
- If a dataset lacks coverage for all target years, document which years are available and how gaps are handled (e.g., nearest year, copy from another epoch).
- Add commented-out visualization blocks below each new function for debugging.

## Key files

- `modules/preprocessDataset.js` — `preprocessAsset()` helper (band select, class reclassify, threshold, vector filter, mosaic)
- `modules/timeSeriesAnthro.js` — global dataset loading functions
- `pff.js` — main app, distance pipeline, UI
- `pff2/` — modular version of the app
- `.github/copilot-instructions.md` — full repo conventions

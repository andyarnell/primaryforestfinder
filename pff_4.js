  // Primary Forest Finder App
  var PFF_SCRIPT_VERSION = "4.16.0-beta.10";

  // Changelog: see CHANGELOG_GEE.md

  // AIM: run decision tree for primary forest delineation
  print('Primary Forest Finder v' + PFF_SCRIPT_VERSION);

  // Set to true when publishing as a GEE App. Hides Drive-export UI
  // ("Export to Google Drive" raster panel + "Export Statistics to Drive"
  // button) which requires the Code Editor Tasks tab and Drive write
  // permissions that published-app users typically don't have. The
  // in-browser "Download to Computer" path remains available.
  var IS_PUBLISHED_APP = false;

  var latestMaskedForest = {};
  var latestMaskedPrimaryForest = {};
  // Tree cover (thresholded, pre-FRA-filter) -- the broadest forest
  // layer in the FRA hierarchy. Stats panel reports it as the top of
  // the Tree cover -> Forest -> Nat Reg -> Primary progression.
  // Distinct from latestMaskedForest only when P1.18 FRA-agri toggle
  // is on (forest_map_clip got narrowed); otherwise both are equal.
  var latestMaskedTreeCover = {};
  // P1.16: separate dict for Naturally regenerating forest (Forest
  // minus Plantations). Populated only when "Exclude plantations" is
  // on and a plantations layer is available. Stats panel reads this
  // in addition to (not instead of) latestMaskedForest -- gives a
  // parallel "Naturally regenerating forest" area row when the data
  // is available.
  var latestMaskedNaturallyRegenerating = {};
  var latestPreConnectivityForest = {};
  var latestTier1Undisturbed = {};
  var latestTier2Steep = {};
  var latestTier3Protected = {};
  var latestAnalysisYear = null;

  //distance buffer calculations, when need to only (faster refresh when only changing slider vals)
  var useCachingCheckbox = true

  // Static GAUL LUT — eliminates blocking .getInfo() at startup
  var gaulLut = require("users/andyarnellgee/apps:modules/gaulLut.js");
  var fraStats = require("users/andyarnellgee/apps:modules/fraStats.js");
  var country_names = gaulLut.country_names;     // pre-sorted, no server call

  // GAUL 2024 boundaries: vector for geometry ops, raster for fast masking
  var countries = ee.FeatureCollection("projects/sat-io/open-datasets/FAO/GAUL/GAUL_2024_L0");
  var property_name = "gaul0_name"
  // Simplified geometries (0.001° tolerance, diced to 10k vertices) for countries
  // whose original GAUL polygons exceed the GEE vertex limit on .geometry().
  // NOTE: tried switching to the un-diced
  // 'GAUL_2024_L0_simplify_0_001deg' asset to remove dice seams; that
  // asset's field names don't include 'iso3_code' so the filter
  // returned an empty collection. Reverted until the un-diced asset's
  // schema is verified.
  var countries_simple = ee.FeatureCollection(
      "projects/ee-andyarnellgee/assets/crosscutting/GAUL_2024_L0_simplify_0_001deg_dice10k");
  var gaul_raster = ee.Image("projects/ee-andyarnellgee/assets/gaul_2024_level_0_code_500m");
  var default_country_selection = null;
  var country_buffer_threshold = 2000

  // Fast raster country mask (avoids vector .clip() per tile)
  function getCountryClip(countryName) {
    var code = gaulLut.nameToCode(countryName);
    return gaul_raster.eq(code).selfMask();
  }

  /**
   * Get the country FeatureCollection, using the simplified asset for countries
   * with overly complex geometries that exceed GEE vertex limits.
   * @param {string} countryName - Country name (gaul0_name).
   * @return {ee.FeatureCollection} Filtered FC (one or more features).
   */
  function getCountryFeatures(countryName) {
    var info = gaulLut.GAUL_LUT[gaulLut.nameToCode(countryName)];
    if (!info) return countries.filter(ee.Filter.eq(property_name, countryName));
    var iso3 = info.iso3;
    // Use simplified geometries for countries known to hit vertex limits
    if (iso3 === 'IDN' || iso3 === 'THA' || iso3 === 'DZA' || iso3 === 'AUS' || iso3 === 'CHN') {
      return countries_simple.filter(ee.Filter.eq('iso3_code', iso3));
    }
    return countries.filter(ee.Filter.eq(property_name, countryName));
  }

  //distance thresholds
  var neighborhoodSize = 170 // 167 is about 5km at 30m resolution (30*167 = 5010)

  var maxForAllDistances = 5100 // don't run any distance calcs over this distance (m) 
  var roadSizeThreshold = 750 
  var years_protected = 30; 
  //slope_threshold_1_2 = 45, 
  var fastBuffer = true

  //built up data (currently code for checkboxes to include/exclude these are hidden for keeping interface simple)
  var includeGISD = false // rock formation false positives (leaving out for now)
  var includeGISA = false // rock formation false positives (leaving out for now)
  var includeWSF = true
  var includeGHSL = true

  // IUCN categories
  var categories = {
    strict: ['Ia', 'Ib','II'],
    no_filter: ["Not Assigned", "Not Reported", "IV", "II", "III", "V", "Ia", "VI", "Ib", "Not Applicable"]
  };
  var current_year = ee.Date(Date.now()).get('year').getInfo(); 
  var selected_iucn_categories = categories['strict'];

  // ============================================
  // PRE-COMPUTE WDPA CATEGORY MASKS (cached once)
  // ============================================
  var allWdpaCategories = ['Ia', 'Ib', 'II', 'III', 'IV', 'V', 'VI', 'Not Reported', 'Not Assigned', 'Not Applicable'];
  var wdpaCategoryMasks = {};

  // Pre-compute all category masks at startup
  var wdpaBase = ee.FeatureCollection("WCMC/WDPA/current/polygons")
    .filter(ee.Filter.and(
      ee.Filter.neq('STATUS', 'Proposed'), 
      ee.Filter.neq('STATUS', 'Not Reported'), 
      ee.Filter.neq('DESIG_ENG', 'UNESCO-MAB Biosphere Reserve')
    ));

  // Cache the STATUS_YR layer (all PAs with year values)
  var wdpaStatusYearGlobal = wdpaBase
    .reduceToImage({
      properties: ['STATUS_YR'],
      reducer: ee.Reducer.min()
    });

  // Pre-compute category masks for each IUCN category
  allWdpaCategories.forEach(function(cat) {
    wdpaCategoryMasks[cat] = wdpaBase.filter(ee.Filter.eq('IUCN_CAT', cat))
      .reduceToImage({properties: ['WDPAID'], reducer: ee.Reducer.first()})
      .unmask(0).gt(0);
  });

  // Visualization parameters
  // Forest-type ramp -- designed so Primary forest STANDS OUT (very
  // dark) and the other layers are notably lighter shades but still
  // distinguishable from each other. Plantations uses a distinct gold
  // (#d4a017) so planted forest reads as a different category.
  //   Tree cover (thresholded, pre-FRA)  binary_palegreen    #c8e6c9 (palest)
  //   Forest (FRA baseline)              binary_lightgreen   lightgreen (#90EE90)
  //   Naturally regenerating forest      binary_medgreen     #81c784 (Material 300)
  //   Forest outside buffers (pre-conn)  binary_green        #4caf50 (Material 500)
  //   Primary forest                     binary_darkgreen    #0b3d1f (very dark)
  var binary_palegreen_palette  = {min:0, max:1, palette:["white","#c8e6c9"]};
  var binary_lightgreen_palette = {min:0, max:1, palette:["white","lightgreen"]};
  var binary_medgreen_palette   = {min:0, max:1, palette:["white","#81c784"]};
  var binary_green_palette = {min:0, max:1, palette:["white","#4caf50"]};
  var binary_darkgreen_palette = {min:0, max:1, palette:["white","#0b3d1f"]};

  // Utility functions
  var makeDistanceBuffer = function(sourceImage, threshold, fastBuffer) {
    fastBuffer = (typeof fastBuffer !== 'undefined') ? fastBuffer : true;
    if (fastBuffer) {
      return sourceImage.fastDistanceTransform({neighborhood: neighborhoodSize}).sqrt()
        .multiply(ee.Image.pixelArea().sqrt()).lte(threshold).selfMask();
    } else {
      return ee.Image(1).cumulativeCost({source: sourceImage, maxDistance: threshold*1.2})
        .lte(threshold).selfMask();
    }
  };



  // =============================================================================
  // ASSET LOADING WITH PREPROCESSING
  // Supports GEE asset IDs (users/..., projects/...) and gs:// Cloud Storage
  // COG URIs.  Returns a binary 0/1 ee.Image named 'presence'.
  // =============================================================================
  var preprocessAsset = function(assetPath, preprocessing) {
    preprocessing = preprocessing || {};
    var sourceType = preprocessing.source_type || 'image';
    var result;

    if (sourceType === 'feature_collection' || sourceType === 'table') {
      var fc = ee.FeatureCollection(assetPath);
      if (preprocessing.filter) {
        fc = fc.filter(ee.Filter.inList(
          preprocessing.filter.field, preprocessing.filter.values));
      }
      result = ee.Image(0).byte().paint(fc, 1).rename('presence');

    } else if (sourceType === 'image_collection') {
      var ic = ee.ImageCollection(assetPath);
      if (preprocessing.year_filter) {
        ic = ic.filter(ee.Filter.eq(
          preprocessing.year_filter.field, preprocessing.year_filter.value));
      }
      result = preprocessing.mosaic ? ic.max() : ic.first();

    } else {
      // Single image — accept GEE asset IDs or gs:// Cloud-Optimised GeoTIFF URIs
      if (assetPath.indexOf('gs://') === 0) {
        result = ee.Image.loadGeoTIFF(assetPath);
      } else {
        result = ee.Image(assetPath);
      }
    }

    // Band selection
    if (preprocessing.band !== undefined && preprocessing.band !== '') {
      result = result.select(preprocessing.band);
    }
    // Class remapping
    if (preprocessing.classes && preprocessing.classes.length > 0) {
      var classes = preprocessing.classes;
      var ones = ee.List.repeat(1, classes.length);
      result = result.remap(classes, ones, 0).gt(0);
    }
    // Threshold (threshold_min / threshold_max come from textboxes as strings)
    var tMin = preprocessing.threshold_min;
    var tMax = preprocessing.threshold_max;
    if ((tMin !== undefined && tMin !== '') || (tMax !== undefined && tMax !== '')) {
      var hasMin = tMin !== undefined && tMin !== '';
      var hasMax = tMax !== undefined && tMax !== '';
      if (hasMin && hasMax) {
        result = result.gte(Number(tMin)).and(result.lte(Number(tMax)));
      } else if (hasMin) {
        result = result.gte(Number(tMin));
      } else {
        result = result.lte(Number(tMax));
      }
    }

    return result.gt(0).unmask(0).byte().rename('presence');
  };

  var GRAYMAP = [
    {   // Dial down the map saturation.
      stylers: [ { saturation: -100 } ]
    },{ // Dial down the label darkness.
      elementType: 'labels',
      stylers: [ { lightness: 20 } ]
    },{ // Simplify the road geometries.
      featureType: 'road',
      elementType: 'geometry',
      stylers: [ { visibility: 'simplified' } ]
    },{ // Turn off road labels.
      featureType: 'road',
      elementType: 'labels',
      stylers: [ { visibility: 'off' } ]
    },{ // Turn off all icons.
      elementType: 'labels.icon',
      stylers: [ { visibility: 'off' } ]
    },{ // Turn off all POIs.
      featureType: 'poi',
      elementType: 'all',
      stylers: [ { visibility: 'off' }]
    }
  ];



  // var property_name = "shapeName";
  var cachedState = {
    country: null,
    year1: null,
    year2: null,
    distanceImages: {},
    slopeImage: null
  };

  ////////////////////
  // distance function 
  var makeDistanceSurface = function(sourceImage, fastBuffer) {
    fastBuffer = (typeof fastBuffer !== 'undefined') ? fastBuffer : true;
    if (fastBuffer) {
      return sourceImage.fastDistanceTransform({neighborhood: neighborhoodSize}).sqrt()
        .multiply(ee.Image.pixelArea().sqrt());
    } else {
      // For cumulativeCost, we need a max distance - using a large value
      var MAX_BUFFER = maxForAllDistances; // Large enough for all your buffers
      return ee.Image(1).cumulativeCost({
        source: sourceImage, 
        maxDistance: MAX_BUFFER*1.2
      });
    }
  };

  // Distance-image thresholding function.
  //
  // P0.15 (zero-buffer rule, 2026-04-26): when threshold == 0, only the
  // source pixels themselves (distance = 0) survive the .lte() filter --
  // so applyDistanceThreshold(dist, 0) returns the input footprint
  // directly with no buffer expansion. This matches the QGIS plugin's
  // P0.15 semantics: enable-tickbox ON + buffer = 0 means "include the
  // input pixels as anthropogenic but don't expand". To skip the input
  // entirely instead, untick its enable* checkbox -- the buffer then
  // doesn't enter activeBuffers below.
  //
  // DO NOT change this to .lt(threshold) or add a special case for
  // threshold==0; the current .lte() correctly handles the zero-buffer
  // rule by returning the source-pixel footprint.
  var applyDistanceThreshold = function(distanceImage, threshold) {
    return distanceImage.lte(threshold).selfMask();
  };

  // Zoom-dependent scale calculation for Hansen GFC visualization
  // Adjusts rendering scale based on zoom level to prevent masking issues
  function scaleForZoom(z, base_scale, pivot_z, r, min_scale, max_scale) {
    var s = base_scale * Math.pow(r, (pivot_z - z));
    s = Math.round(s);
    return Math.min(max_scale, Math.max(min_scale, s));
  }

  ////////////
    function forwardFillBinaryTimeSeries(imageCollection, targetYears) {
        var sorted = imageCollection.sort('year');
      
        var initial = {
          cumulative: ee.Image(0),
          list: ee.List([])
        };
      
        var result = ee.List(targetYears).iterate(function(year, prev) {
          year = ee.Number(year);
          prev = ee.Dictionary(prev);
      
          var cumulative = ee.Image(prev.get('cumulative'));
      
          var imageForYear = ee.Image(
            sorted.filter(ee.Filter.eq('year', year)).first()
          ).unmask(0).gt(0);
      
          var updatedCumulative = cumulative.or(imageForYear);
      
          var yearImage = updatedCumulative.rename('forwardfill').set({
            'year': year,
            'system:time_start': ee.Date.fromYMD(year, 1, 1).millis(),
            'system:index': year.format()
          });
      
          var updatedList = ee.List(prev.get('list')).add(yearImage);
      
          return ee.Dictionary({
            cumulative: updatedCumulative,
            list: updatedList
          });
        }, initial);
      
        return ee.ImageCollection.fromImages(ee.Dictionary(result).get('list'));
      }
      



  ///////////


  function remapClassesToOne(image, classList) {
    return image.remap(classList, ee.List.repeat(1, classList.length)).selfMask();
  }

  function calculateSlope(elevation, aoi_mask) {
    var proj = elevation.first().select(0).projection();
    
    // Mosaic elevation dataset
    var processed_elevation = elevation.mosaic();
    
    // Apply mask only if aoi_mask is provided
    if (aoi_mask) {
      processed_elevation = processed_elevation.updateMask(aoi_mask);
    }

    return ee.Terrain.slope(processed_elevation.setDefaultProjection(proj));
  }

  function generateOutcomeMaps(input_layer, mask_layer) {
    return {
      yes: input_layer.updateMask(mask_layer).selfMask(),
      no: input_layer.updateMask(mask_layer.not())
    };
  }



  function cleanCountryName(name) {
    return name.replace(/[\u0300-\u036f]/g, "").replace(/[^a-zA-Z0-9 ]/g, "")
      .trim().replace(/\s+/g, "_");
  }

  // ---------------------------------------------------------------------------
  // Canonical PFF output filename builder (Option D, decided 2026-04-26)
  // JS mirror of pff_qgis_tools/utils.py generate_layer_name(). Same signature,
  // same constants. Foundation for P1.13 (full filename rename across both
  // tools) -- no consumers in pff_4.js yet; existing Export.image.toDrive
  // description / fileNamePrefix calls migrate later.
  // ---------------------------------------------------------------------------

  // Stable platform tags. Use these exact strings -- not 'app' / 'plugin'.
  var PLATFORM_GEE = "gee";
  var PLATFORM_QGIS = "qgis";

  // Stable step prefixes. Production stage of the file (where in the pipeline
  // it was made), not the action that saves it. Sortable alphabetically =
  // workflow order.
  var STEP_CONTEXT          = "00";  // supplies ISO3 prefix; no files of its own
  var STEP_TIME_PERIOD      = "01";  // supplies year; no files of its own
  var STEP_FOREST_INPUTS    = "02";  // raw forest layers
  var STEP_HUMAN_INFLUENCE  = "03";  // raw anthro layers
  var STEP_REFINE           = "04";  // final refined rasters, pre-conn, combined
  var STEP_STATISTICS       = "05";  // stats CSV / per-zone shapefile
  var STEP_VALIDATION       = "06";  // vectorised + dissolved CEO outputs

  /**
   * Build a canonical PFF output filename per the Option D schema.
   * Format: {iso3}_{platform}_{step}_{name}.{ext}  (ISO3 optional;
   * omitted when no country selected).
   *
   * @param {string|null|undefined} iso3
   *        ISO3 country code (e.g. 'KEN'). Pass null/undefined/'' to omit.
   *        Cased uppercase if supplied.
   * @param {string} platform
   *        'gee' or 'qgis'. Use the PLATFORM_* constants in this module.
   * @param {string} step
   *        '00'-'06' with optional substep letter ('04a', '05b').
   *        Use the STEP_* constants for the base.
   * @param {string} name
   *        Snake-case layer name without step prefix or extension
   *        (e.g. 'primary_forest', 'area_statistics',
   *        'primary_forest_vector'). The step number already encodes
   *        the production stage, so no need to repeat 'results_' /
   *        'refined_' / 'validation_' qualifiers.
   * @param {string} [ext='tif']
   *        Extension without leading dot. Use 'gpkg' for vectors,
   *        'csv' for stats, 'shp' for shapefile-zone outputs, 'json'
   *        for metadata sidecars.
   * @return {string} Constructed filename.
   *
   * Examples:
   *   generateLayerName('KEN', PLATFORM_GEE, '04a', 'primary_forest')
   *     -> 'KEN_gee_04a_primary_forest.tif'
   *   generateLayerName(null, PLATFORM_GEE, '06b',
   *                     'primary_forest_dissolved', 'gpkg')
   *     -> 'gee_06b_primary_forest_dissolved.gpkg'
   *   generateLayerName('KEN', PLATFORM_GEE, '05a',
   *                     'area_statistics', 'csv')
   *     -> 'KEN_gee_05a_area_statistics.csv'
   */
  function generateLayerName(iso3, platform, step, name, ext) {
    var parts = [];
    if (iso3) {
      parts.push(String(iso3).trim().toUpperCase());
    }
    if (platform !== PLATFORM_GEE && platform !== PLATFORM_QGIS) {
      throw new Error(
        "platform must be 'gee' or 'qgis' (got " + JSON.stringify(platform) +
        "). Use the PLATFORM_GEE / PLATFORM_QGIS constants.");
    }
    parts.push(platform);
    if (!step) {
      throw new Error("step is required (e.g. '04a').");
    }
    parts.push(String(step).trim());
    if (!name) {
      throw new Error("name is required (e.g. 'primary_forest').");
    }
    parts.push(String(name).trim());
    var base = parts.join("_");
    var extClean = (ext === undefined || ext === null) ? "tif" : String(ext).trim().replace(/^\./, "");
    return extClean ? base + "." + extClean : base;
  }

  // function tmfUndisturbedForestPrep(year) {
  //   var tmfAnnual = ee.ImageCollection("projects/JRC/TMF/v1_2024/AnnualChanges").mosaic();
    
  //   // Get binary undisturbed forest mask for given year (class 1 = undisturbed TMF)
  //   var bandName = 'Dec' + year;
  //   var undisturbed = tmfAnnual.select(bandName).eq(1);
    
  //   return undisturbed.rename("TMF_Undisturbed_" + year);
  // }

  // var driversOfLoss = ee.Image("projects/landandcarbon/assets/wri_gdm_drivers_forest_loss_1km/v1_2_2001_2024");
  // var driversOfLossNatural = drivers_1km.select("classification").remap([5,7],[1,1],0)

  // Map.addLayer(driversOfLossNatural,{min:0,max:1,palette:["blue","red"]})


  function gfcHansenTreecoverPrep(analysisYear, treecoverPercentThreshold) {
    // Use Hansen GFC v1.12 (2000–2024) for latest data
    var gfc = ee.Image('UMD/hansen/global_forest_change_2024_v1_12');
    
    var tree2000 = gfc.select('treecover2000').gt(treecoverPercentThreshold);
    var lossyear = gfc.select('lossyear').unmask(0); // 0=no loss
    
    // Keep = forest in 2000 AND (no loss OR loss after target year)
    // This properly handles the loss masking by year
    var keep = tree2000.and(lossyear.eq(0).or(lossyear.gt(analysisYear - 2000)));
    
    // Apply mask and keep transparent background
    var gfcHansenSel = tree2000.updateMask(keep).selfMask();
    
    return gfcHansenSel.rename("GFC_Hansen_" + analysisYear);
  }

  function gladLulcForestPrep(analysisYear, treeHeightThreshold) {
    var gladLandcoverLand = ee.Image('projects/glad/GLCLU2020/v2/LCLUC_' + analysisYear)
      .updateMask(ee.Image("projects/glad/OceanMask").lte(1));

    // Define remapping values
    var fromValues = [
      25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48,
      125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147
    ];
    var toValues = [
      3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26,
      3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25
    ];

    // Remap landcover classes to tree height values
    var gladLandcoverRemapped = gladLandcoverLand.remap(fromValues, toValues);

    // Apply tree height threshold (binary output)
    var gladLulcForestSel = gladLandcoverRemapped.gte(treeHeightThreshold);

    return gladLulcForestSel.rename("gladLulcForestSel_" + analysisYear);
  }

  function agreementForestPrep(analysisYear, treecoverPercentThreshold, treeHeightThreshold) {
    // Get both Hansen and GLAD forest layers
    var hansenForest = gfcHansenTreecoverPrep(analysisYear, treecoverPercentThreshold);
    var gladForest = gladLulcForestPrep(analysisYear, treeHeightThreshold);
    
    // Both datasets (AND) — conservative, highest confidence
    var agreementForest = hansenForest.and(gladForest);
    
    return agreementForest.rename("Agreement_" + analysisYear);
  }

  function unionForestPrep(analysisYear, treecoverPercentThreshold, treeHeightThreshold) {
    // Get both Hansen and GLAD forest layers
    var hansenForest = gfcHansenTreecoverPrep(analysisYear, treecoverPercentThreshold);
    var gladForest = gladLulcForestPrep(analysisYear, treeHeightThreshold);

    // Either dataset (OR) — inclusive, maximum coverage
    var unionForest = hansenForest.or(gladForest);

    return unionForest.rename("Union_" + analysisYear);
  }

  // P1.23: merge a custom forest layer (nationalForest) with the global
  // source forest_map according to the user-selected merge mode. Returns
  // the merged forest layer, or the original global forest_map unchanged
  // if Custom forest data is off / no asset for this year.
  //
  // Modes:
  //   - Replace global         : custom replaces global entirely
  //   - Add to global extent   : custom OR global (union)
  //   - Agreement with global  : custom AND global (intersection)
  function applyCustomForestMerge(globalForest, analysisYear) {
    // Mirrors the visibility gate in updateGlobalForestInputsVisibility:
    // custom forest only counts as active when BOTH the §2 master
    // ("Enable custom data inputs") AND the per-dataset nationalForest
    // checkbox are ticked. Master off → analysis falls back to the
    // global source even if nationalForest.checkbox is still ticked.
    if (!enableTreeCoverCustomCheckbox.getValue()) return globalForest;
    if (!nationalForest.checkbox.getValue()) return globalForest;
    var customAsset = nationalForest.getAsset(analysisYear);
    if (!customAsset) return globalForest;

    var customForest;
    try {
      customForest = preprocessAsset(customAsset, nationalForest.getPreprocessingConfig());
    } catch (e) {
      print('Error loading custom forest asset for ' + analysisYear + '; falling back to global source.');
      return globalForest;
    }

    var mode = nationalForest.modeSelect.getValue();
    if (!globalForest || mode === 'Replace global') return customForest;
    if (mode === 'Add to global extent') {
      return globalForest.unmask(0).or(customForest.unmask(0)).selfMask();
    }
    if (mode === 'Agreement with global') {
      return globalForest.unmask(0).and(customForest.unmask(0)).selfMask();
    }
    // Unknown mode -- keep global, log once for debug
    print('Unknown nationalForest merge mode: ' + mode + ' — using global source.');
    return globalForest;
  }

  ///to fix toggle shoukd work with

  function toggleTreecoverSlider(value) {
    treecoverThresholdSlider.style().set('shown', value);
  }

  ///to fix toggle shoukd work with
  function toggleTreecoverHeightThresholdSlider(value) {
    treecoverHeightThresholdSlider.style().set('shown', value);
  }


  // UI setup
  var years = [2000, 2010, 2015, 2020];

  // var onTheFlyStatsRes = 900; // now controlled via statsScaleSlider

  // =============================================================================
  // PREPROCESSING UI FACTORY
  // =============================================================================
  // Creates a collapsible panel of preprocessing options for a custom dataset.
  // Returns: { panel, getConfig(), collectSettings(), applySettings(s) }

  function createPreprocessingUi() {
    var sourceTypeSelect = ui.Select({
      items: ['image', 'image_collection', 'feature_collection'],
      value: 'image',
      style: {fontSize: '10px', stretch: 'horizontal'},
      onChange: function(v) {
        var isRaster = (v !== 'feature_collection');
        rasterPanel.style().set('shown', isRaster);
        icPanel.style().set('shown', v === 'image_collection');
        fcPanel.style().set('shown', v === 'feature_collection');
      }
    });

    // Raster-only controls (hidden for feature_collection)
    var bandInput = ui.Textbox({
      placeholder: 'band name (optional)',
      style: {fontSize: '10px', stretch: 'horizontal'}
    });
    var classesInput = ui.Textbox({
      placeholder: 'pixel classes, e.g. 1,2,3 (optional)',
      style: {fontSize: '10px', stretch: 'horizontal'}
    });
    var threshMinInput = ui.Textbox({
      placeholder: 'min', style: {fontSize: '10px', width: '72px'}
    });
    var threshMaxInput = ui.Textbox({
      placeholder: 'max', style: {fontSize: '10px', width: '72px'}
    });
    var rasterPanel = ui.Panel({
      widgets: [
        ui.Panel(
          [ui.Label('Band:', {fontSize: '10px', margin: '4px 4px 0 0', width: '36px'}), bandInput],
          ui.Panel.Layout.flow('horizontal'), {margin: '2px 0'}),
        ui.Panel(
          [ui.Label('Classes:', {fontSize: '10px', margin: '4px 4px 0 0', width: '46px'}), classesInput],
          ui.Panel.Layout.flow('horizontal'), {margin: '2px 0'}),
        ui.Panel(
          [ui.Label('Threshold:', {fontSize: '10px', margin: '4px 4px 0 0'}),
          threshMinInput, ui.Label('–', {fontSize: '10px', margin: '4px 2px 0 2px'}), threshMaxInput],
          ui.Panel.Layout.flow('horizontal'), {margin: '2px 0'})
      ],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {shown: true, margin: '0'}
    });

    // ImageCollection-only controls
    var mosaicCheckbox = ui.Checkbox({label: 'max mosaic', value: true, style: {fontSize: '10px'}});
    var yrFilterFieldInput = ui.Textbox({placeholder: 'field', style: {fontSize: '10px', width: '80px'}});
    var yrFilterValInput   = ui.Textbox({placeholder: 'value', style: {fontSize: '10px', width: '60px'}});
    var icPanel = ui.Panel({
      widgets: [
        mosaicCheckbox,
        ui.Panel(
          [ui.Label('Year filter:', {fontSize: '10px', margin: '4px 4px 0 0'}), yrFilterFieldInput, yrFilterValInput],
          ui.Panel.Layout.flow('horizontal'), {margin: '2px 0'})
      ],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {shown: false, margin: '2px 0 0 8px'}
    });

    // FeatureCollection-only controls
    var fcFilterFieldInput = ui.Textbox({placeholder: 'field', style: {fontSize: '10px', width: '80px'}});
    var fcFilterValsInput  = ui.Textbox({placeholder: 'values, e.g. 1,2 or Ia,Ib', style: {fontSize: '10px', stretch: 'horizontal'}});
    var fcPanel = ui.Panel({
      widgets: [
        ui.Panel(
          [ui.Label('Filter field:', {fontSize: '10px', margin: '4px 4px 0 0'}), fcFilterFieldInput],
          ui.Panel.Layout.flow('horizontal'), {margin: '2px 0'}),
        ui.Panel(
          [ui.Label('Values:', {fontSize: '10px', margin: '4px 4px 0 0'}), fcFilterValsInput],
          ui.Panel.Layout.flow('horizontal'), {margin: '2px 0'})
      ],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {shown: false, margin: '2px 0 0 8px'}
    });

    var content = ui.Panel({
      widgets: [
        ui.Panel(
          [ui.Label('Type:', {fontSize: '10px', margin: '4px 4px 0 0', width: '36px'}), sourceTypeSelect],
          ui.Panel.Layout.flow('horizontal'), {margin: '2px 0'}),
        rasterPanel,
        icPanel,
        fcPanel
      ],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {shown: false, margin: '0', padding: '4px',
              backgroundColor: '#f5f5f5', border: '1px solid #ddd'}
    });

    var toggleBtn = ui.Button({
      label: '⚙ Preprocessing',
      onClick: function() {
        var s = content.style().get('shown');
        content.style().set({shown: !s});
        toggleBtn.setLabel(s ? '⚙ Preprocessing' : '▾ Preprocessing');
      },
      style: {fontSize: '10px', padding: '1px 6px', margin: '2px 0 0 0',
              backgroundColor: '#ebebeb'}
    });

    var panel = ui.Panel({
      widgets: [toggleBtn, content],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {margin: '0'}
    });

    return {
      panel: panel,

      getConfig: function() {
        var cfg = {source_type: sourceTypeSelect.getValue()};

        // Band / classes / threshold are raster-only — skip for feature_collection
        if (cfg.source_type !== 'feature_collection') {
          var band = bandInput.getValue();
          if (band && band.trim() !== '') cfg.band = band.trim();

          var classesStr = classesInput.getValue();
          if (classesStr && classesStr.trim() !== '') {
            cfg.classes = classesStr.split(',')
              .map(function(s) { return parseInt(s.trim()); })
              .filter(function(n) { return !isNaN(n); });
          }

          var tMin = threshMinInput.getValue();
          var tMax = threshMaxInput.getValue();
          if ((tMin && tMin.trim() !== '') || (tMax && tMax.trim() !== '')) {
            if (tMin && tMin.trim() !== '') cfg.threshold_min = tMin.trim();
            if (tMax && tMax.trim() !== '') cfg.threshold_max = tMax.trim();
          }
        }

        if (cfg.source_type === 'image_collection') {
          cfg.mosaic = mosaicCheckbox.getValue();
          var yrField = yrFilterFieldInput.getValue();
          var yrVal   = yrFilterValInput.getValue();
          if (yrField && yrField.trim() !== '' && yrVal && yrVal.trim() !== '') {
            var parsed = parseInt(yrVal.trim());
            cfg.year_filter = {
              field: yrField.trim(),
              value: isNaN(parsed) ? yrVal.trim() : parsed
            };
          }
        }

        if (cfg.source_type === 'feature_collection') {
          var fcField = fcFilterFieldInput.getValue();
          var fcVals  = fcFilterValsInput.getValue();
          if (fcField && fcField.trim() !== '' && fcVals && fcVals.trim() !== '') {
            var parsedVals = fcVals.split(',').map(function(s) {
              var t = s.trim();
              var n = parseInt(t);
              return isNaN(n) ? t : n;
            });
            cfg.filter = {field: fcField.trim(), values: parsedVals};
          }
        }

        return cfg;
      },

      collectSettings: function() {
        return {
          source_type:     sourceTypeSelect.getValue(),
          band:            bandInput.getValue(),
          classes:         classesInput.getValue(),
          threshold_min:   threshMinInput.getValue(),
          threshold_max:   threshMaxInput.getValue(),
          mosaic:          mosaicCheckbox.getValue(),
          yr_filter_field: yrFilterFieldInput.getValue(),
          yr_filter_val:   yrFilterValInput.getValue(),
          fc_filter_field: fcFilterFieldInput.getValue(),
          fc_filter_vals:  fcFilterValsInput.getValue()
        };
      },

      applySettings: function(s) {
        if (!s) return;
        if (s.source_type)     sourceTypeSelect.setValue(s.source_type, true);
        if (s.band        !== undefined) bandInput.setValue(s.band);
        if (s.classes     !== undefined) classesInput.setValue(s.classes);
        if (s.threshold_min !== undefined) threshMinInput.setValue(s.threshold_min);
        if (s.threshold_max !== undefined) threshMaxInput.setValue(s.threshold_max);
        if (s.mosaic      !== undefined) mosaicCheckbox.setValue(s.mosaic);
        if (s.yr_filter_field !== undefined) yrFilterFieldInput.setValue(s.yr_filter_field);
        if (s.yr_filter_val   !== undefined) yrFilterValInput.setValue(s.yr_filter_val);
        if (s.fc_filter_field !== undefined) fcFilterFieldInput.setValue(s.fc_filter_field);
        if (s.fc_filter_vals  !== undefined) fcFilterValsInput.setValue(s.fc_filter_vals);
      }
    };
  }

  // =============================================================================
  // REUSABLE ASSET INPUT FACTORY
  // =============================================================================
  // Creates dynamic year-based asset input UI components for any dataset type.
  // Returns an object with: panel, getAsset(year), updateVisibility(), getPreprocessingConfig()

  function createYearAssetInputs(config) {
    var placeholder = config.placeholder || 'users/username/asset';

    var inputs = {};
    var panels = {};
    var containerPanel = ui.Panel({style: {shown: false, margin: '2px 0 0 12px'}});

    years.forEach(function(year) {
      var yearPanel = ui.Panel({
        layout: ui.Panel.Layout.flow('horizontal'),
        style: {margin: '2px 0', shown: false}
      });
      yearPanel.add(ui.Label(year + ':', {fontSize: '10px', margin: '5px 4px 0 0', width: '36px'}));
      var assetInput = ui.Textbox({
        placeholder: placeholder.replace('{year}', year),
        style: {fontSize: '10px', stretch: 'horizontal'}
      });
      inputs[year] = assetInput;
      panels[year] = yearPanel;
      yearPanel.add(assetInput);
      containerPanel.add(yearPanel);
    });

    // Preprocessing UI — one shared config for all years of this dataset
    var prepUi = createPreprocessingUi();
    containerPanel.add(prepUi.panel);

    return {
      panel: containerPanel,
      inputs: inputs,

      // Get asset ID for a specific year
      getAsset: function(year) {
        return inputs[year] ? inputs[year].getValue() : '';
      },

      // Get preprocessing config (shared across all years)
      getPreprocessingConfig: function() {
        return prepUi.getConfig();
      },

      // Update visibility based on selected years
      updateVisibility: function(splitScreenEnabled, year1, year2) {
        years.forEach(function(year) {
          var showYear = false;
          if (splitScreenEnabled) {
            showYear = (year === year1 || year === year2);
          } else {
            showYear = (year === year2);
          }
          panels[year].style().set('shown', showYear);
        });
      },

      // Show/hide entire panel
      setShown: function(shown) {
        containerPanel.style().set('shown', shown);
      }
    };
  }

  // =============================================================================
  // STATE MANAGEMENT
  // =============================================================================

  var appState = {
    ui: {
      datesCollapsed: true,
      treeCoverCollapsed: true,
      refineInputCollapsed: true,
      anthropogenicCollapsed: true,
      limitedAccessCollapsed: true,
      connectivityCollapsed: true,
      layersPanelCollapsed: true,
      leftPanelCollapsed: false,
      rightPanelCollapsed: false
    },
    map: {
      currentMode: 'single',
      lastCenter: null,
      lastZoom: null,
      previousCountry: null
    }
  };

  // Track year label widgets so we can remove them on update
  var yearLabel1Widget = null;
  var yearLabel2Widget = null;

  // Track which layers are currently visible (state persistence)
  var _legendRefreshFns = [];  // legend refresh callbacks

  var visibleLayers = {
    // Analysis outputs
    primaryForest: true,         // Headline output (default on)
    forestOutsideBuffers: true,  // Supporting output: pre-connectivity (default on)
    treeCover: true,             // Thresholded tree cover -- pre-FRA-filter baseline
    forest: true,                // Input forest -- FRA Forest baseline (default on)
    naturallyRegenerating: true, // P1.16: ≈ FRA Naturally regenerating forest (default on when produced)
    // Processed binary inputs (what feeds the distance transforms)
    inputRoads: false,
    inputBuiltupSmall: false,
    inputBuiltupLarge: false,
    inputAgriculture: false,
    // Buffer zones
    roadSmallBuffer: false,
    // roadLargeBuffer removed — single roads category only
    builtSmallBuffer: false,
    builtLargeBuffer: false,
    agriBuffer: false,
    // Other
    plantations: false,
    slope: false,
    protectedAreas: false,
    flii: false,
    fdap: false,
    refCustom1: false,
    refCustom2: false,
    countryOutline: true
  };

  // Reset layer visibility to defaults (primary forest + supporting outputs +
  // forest input on, anthro/buffer/exception inputs off).
  function resetVisibleLayers() {
    visibleLayers.primaryForest = true;
    visibleLayers.forestOutsideBuffers = true;
    visibleLayers.treeCover = true;
    visibleLayers.forest = true;
    visibleLayers.naturallyRegenerating = true;
    visibleLayers.inputRoads = false;
    visibleLayers.inputBuiltupSmall = false;
    visibleLayers.inputBuiltupLarge = false;
    visibleLayers.inputAgriculture = false;
    visibleLayers.roadSmallBuffer = false;
    visibleLayers.builtSmallBuffer = false;
    visibleLayers.builtLargeBuffer = false;
    visibleLayers.agriBuffer = false;
    visibleLayers.plantations = false;
    visibleLayers.slope = false;
    visibleLayers.protectedAreas = false;
    visibleLayers.flii = false;
    visibleLayers.countryOutline = true;
  }

  // toggleLayerByName uses prefix matching for Slope / Protected Areas
  // (their layer names include dynamic values like degrees or year).
  var LAYER_PREFIX_MAP = [
    {prefix: 'Input: Slope',       key: 'slope'},
    {prefix: 'Input: Protected',   key: 'protectedAreas'},
    {prefix: 'Input: Tree cover',  key: 'treeCover'}
    // Forest layer renamed from 'Input: Forest' to plain 'Forest' --
    // no longer needs a prefix entry because its name is now static
    // (no dynamic year/threshold suffix). Adding a 'Forest' prefix
    // here would over-match 'Forest outside buffers'. Exact match in
    // toggleLayerByName handles 'Forest' correctly.
  ];

  // Toggle a named layer on both maps without triggering a full recompute.
  // Used by the layer-panel checkboxes.
  function toggleLayerByName(name, shown) {
    [map1, map2].forEach(function(m) {
      if (!m) return;
      var layers = m.layers();
      for (var i = 0; i < layers.length(); i++) {
        var layer = layers.get(i);
        var lname = layer.getName();
        var match = (lname === name);
        if (!match) {
          // prefix match for dynamic names
          for (var j = 0; j < LAYER_PREFIX_MAP.length; j++) {
            if (LAYER_PREFIX_MAP[j].key === name && lname.indexOf(LAYER_PREFIX_MAP[j].prefix) === 0) {
              match = true; break;
            }
          }
        }
        if (match) layer.setShown(shown);
      }
    });
    // Refresh all legend panels to show only visible layers
    _legendRefreshFns.forEach(function(fn) { fn(); });
  }

  var updateLeftPanelWidth = function() {};
  var updateRightPanelWidth = function() {};

  // Accordion helper - collapses all panels except the specified one
  var collapseAllPanelsExcept = function(exceptPanel) {
    // This will be populated after panel definitions
  };

  // =============================================================================
  // UI COMPONENTS - TOP BAR
  // =============================================================================

  var countryWarningLabel = ui.Label('', {color: '#cc6666', fontSize: '11px', margin: '6px 0 0 0', shown: false});

  var countrySelector = ui.Select({
    items: country_names,
    placeholder: 'Choose country',
    onChange: function(value) {
      // Clear red highlight and warning when a country is selected
      countrySelector.style().set({border: '1px solid #ccc', color: 'black'});
      countryWarningLabel.style().set({shown: false});
      updateMap();
    },
    style: {width: '150px', margin: '4px 8px'}
  });

  // Helper: close Config and About header panels (called by accordion logic)
  function closeConfig() {
    settingsContent.style().set({shown: false});
    configButton.style().set({backgroundColor: '#f0f0f0'});
  }
  function closeAbout() {
    aboutContent.style().set({shown: false});
    aboutButton.style().set({backgroundColor: '#f0f0f0'});
  }
  function closeValidation() {
    if (typeof validationContent !== 'undefined') {
      validationContent.style().set({shown: false});
      validationToggle.setLabel('▶ Validation');
    }
  }

  // Recenter button - zooms to selected country on demand
  var recenterButton = ui.Button({
    label: '⊕',
    onClick: function() {
      var selectedCountry = countrySelector.getValue();
      if (!selectedCountry) return;
      var country_features = getCountryFeatures(selectedCountry);
      var centroid = country_features.geometry().centroid().coordinates().getInfo();
      var useSplitScreen = enableSplitScreenCheckbox.getValue();
      if (useSplitScreen && map1) {
        map1.setCenter(centroid[0], centroid[1], 6);
        if (map2) {
          map2.setCenter(centroid[0], centroid[1], 6);
        }
      } else if (map2) {
        map2.setCenter(centroid[0], centroid[1], 6);
      }
    },
    style: {margin: '4px 2px', padding: '0px 4px', fontSize: '24px'}
  });

  // Config button (top bar) — toggles Config panel in right panel
  var configButton = ui.Button({
    label: '⚙ Config',
    onClick: function() {
      var isShown = settingsContent.style().get('shown');
      if (!isShown) {
        statsContent.style().set({shown: false});
        statsToggle.setLabel('▶ Area Statistics');
        downloadsContent.style().set({shown: false});
        downloadsToggle.setLabel('▶ Outputs');
        closeValidation();
        closeAbout();
      }
      settingsContent.style().set({shown: !isShown});
      configButton.style().set({backgroundColor: isShown ? '#f0f0f0' : '#d0e0ff'});
      updateRightPanelWidth();
    },
    style: {margin: '4px 2px', padding: '2px 8px', fontSize: '12px', backgroundColor: '#f0f0f0'}
  });

  // About button (top bar) — toggles About panel in right panel
  var aboutButton = ui.Button({
    label: 'ⓘ About',
    onClick: function() {
      var isShown = aboutContent.style().get('shown');
      if (!isShown) {
        statsContent.style().set({shown: false});
        statsToggle.setLabel('▶ Area Statistics');
        settingsContent.style().set({shown: false});
        configButton.style().set({backgroundColor: '#f0f0f0'});
        downloadsContent.style().set({shown: false});
        downloadsToggle.setLabel('▶ Outputs');
        closeValidation();
      }
      aboutContent.style().set({shown: !isShown});
      aboutButton.style().set({backgroundColor: isShown ? '#f0f0f0' : '#d0e0ff'});
      updateRightPanelWidth();
    },
    style: {margin: '4px 2px', padding: '2px 8px', fontSize: '12px', backgroundColor: '#f0f0f0'}
  });

  var yearSelector1Label = ui.Label('Year 1:', {margin: '4px 0px'});

  var yearSelector1 = ui.Select({
    items: years.map(String), 
    value: '2000', 
    onChange: function(value) {
      updateVisibleAssetInputs();
      updateMap();
    },
    style: {width: '80px', margin: '4px 8px'}
  });
  yearSelector1.style().set({shown: false});
  yearSelector1Label.style().set({shown: false});

  var yearSelector2Label = ui.Label('Year:', {margin: '4px 0px'});

  var yearSelector2 = ui.Select({
    items: years.map(String), 
    value: '2020', 
    onChange: function(value) {
      updateVisibleAssetInputs();
      updateMap();
    },
    style: {width: '80px', margin: '4px 8px'}
  });

  var enableSplitScreenCheckbox = ui.Checkbox({
    label: 'Compare Years',
    value: false,
    onChange: function(checked) {
      yearSelector1Label.style().set({shown: checked});
      yearSelector1.style().set({shown: checked});
      yearSelector2Label.setValue(checked ? 'Year 2:' : 'Year:');
      updateVisibleAssetInputs();
      updateMap();
    },
    style: {margin: '4px 8px'}
  });

  var appTitleLabel = ui.Label('Primary Forest Finder', {
    fontWeight: 'bold', fontSize: '18px', margin: '4px 0 4px 8px'
  });
  var appVersionLabel = ui.Label('v' + PFF_SCRIPT_VERSION, {
    fontSize: '12px', color: '#666', margin: '7px 8px 4px 4px'
  });
  var appTitle = ui.Panel({
    widgets: [appTitleLabel, appVersionLabel],
    layout: ui.Panel.Layout.flow('horizontal'),
    style: {margin: '0', padding: '0'}
  });


  var titleSpacer = ui.Panel({style: {stretch: 'horizontal'}});

  // About content -- shown via the "▶ About" dropdown in the right panel.
  // Batch 27.1: re-added a small ✕ close button at the top-right of the
  // content panel as a redundant-but-helpful close shortcut for users
  // who've scrolled inside the panel.
  var aboutCloseButton = ui.Button({
    label: '✕',
    onClick: function() {
      closeAbout();
      updateRightPanelWidth();
    },
    style: {margin: '0', padding: '0 6px', fontSize: '11px',
            backgroundColor: '#e8e8e8'}
  });
  var aboutCloseRow = ui.Panel({
    widgets: [
      ui.Label('', {stretch: 'horizontal'}),
      aboutCloseButton
    ],
    layout: ui.Panel.Layout.flow('horizontal'),
    style: {stretch: 'horizontal', margin: '0 0 4px 0'}
  });

  var aboutContent = ui.Panel({
    widgets: [
      aboutCloseRow,
      ui.Label('About', {fontWeight: 'bold', fontSize: '13px', margin: '0 0 6px 0', color: '#333'}),
      ui.Label(
        'An open tool for delineating primary and intact forests using ' +
        'satellite-derived tree cover, anthropogenic disturbance buffers, ' +
        'protected area status, terrain analysis, and connectivity filtering. ' +
        'Designed to support national forest monitoring and reporting ' +
        '(e.g. FAO FRA) with transparent, reproducible methods.',
        {fontSize: '11px', margin: '0 0 8px 0'}),

      ui.Label('How to use', {fontWeight: 'bold', fontSize: '11px', margin: '8px 0 2px 0'}),
      ui.Label(
        '1. Select a country and view the map\n' +
        '2. Adjust parameters, then click Update Analysis\n' +
        '3. View outputs and statistics in the right panel\n' +
        '4. Save outputs via the Outputs section\n' +
        '5. Save/load your settings via the ⚙ Config button',
        {fontSize: '10px', margin: '0 0 4px 4px', whiteSpace: 'pre'}
      ),
      ui.Label(
        'Preprocessing: expand ⚙ Preprocessing on custom data inputs ' +
        'to filter bands, remap classes, or set thresholds before use.',
        {fontSize: '10px', color: '#666', fontStyle: 'italic', margin: '0 0 8px 4px'}
      ),

      ui.Label('Resources', {fontWeight: 'bold', fontSize: '11px', margin: '4px 0 2px 0'}),
      ui.Label({
        value: 'FAO FRA 2025 definitions',
        style: {fontSize: '11px', color: 'blue', textDecoration: 'underline', margin: '0 0 2px 4px'},
        targetUrl: 'https://fra-data.fao.org/definitions/fra/2025/en/tad#1b'
      }),
      ui.Label({
        value: 'Source code on GitHub',
        style: {fontSize: '11px', color: 'blue', textDecoration: 'underline', margin: '0 0 2px 4px'},
        targetUrl: 'https://github.com/andyarnell/primaryforestfinder'
      }),
      ui.Label({
        value: 'Data inputs (global datasets)',
        style: {fontSize: '11px', color: 'blue', textDecoration: 'underline', margin: '0 0 2px 4px'},
        targetUrl: 'https://github.com/andyarnell/primaryforestfinder/blob/main/docs/datasets_global.md'
      }),
      ui.Label({
        value: 'Report an issue / request a feature',
        style: {fontSize: '11px', color: 'blue', textDecoration: 'underline', margin: '0 0 2px 4px'},
        targetUrl: 'https://github.com/andyarnell/primaryforestfinder/issues'
      }),
      ui.Label('Contact — andrew.arnell@fao.org', {fontSize: '11px', margin: '0 0 0 4px'})
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, padding: '8px', backgroundColor: 'rgba(255,255,255,0.9)'}
  });

  // RUN BUTTON - triggers analysis (instead of auto-update on slider change)
  var runButton = ui.Button({
    label: '↻ Update Analysis',
    onClick: function() {
      // Clear stats when updating to prevent stale data
      if (typeof areaStatsPanel !== 'undefined') {
        areaStatsPanel.clear();
      }
      // P1.25: button-only flag triggers visibility reset inside updateMap
      // so any layer the user had toggled off in the legend comes back on.
      updateMap({fromUpdateAnalysisButton: true});
    },
    style: {
      fontWeight: 'bold',
      fontSize: '12px',
      padding: '2px 12px',
      margin: '2px 8px',
      backgroundColor: '#4CAF50',
      color: '#333333'
    }
  });

  // P1.26: "Disable map" mode for slow internet connections. When ticked,
  // addLayersToMap() skips every map.addLayer() / map.layers().add() call
  // -- no tile fetches at all -- but the analysis cache (latestMasked*)
  // still populates. So Update Analysis still runs the server-side
  // compute graph (lazily), and Export All Layers / Export Statistics to
  // Drive still queue tasks containing Primary Forest + Pre-connectivity.
  // On-the-fly Show Area Statistics is also disabled (it uses .evaluate()
  // roundtrips per layer/year); user is steered to Export Statistics to
  // Drive instead, which queues server-side without immediate roundtrips.
  // Save/Load Settings + Download Run Metadata stay enabled (single small
  // JSON downloads, fast even on slow connections).
  var disableMapCheckbox = ui.Checkbox({
    label: 'Disable map (low internet)',
    value: false,
    onChange: function(v) {
      disableMapHint.style().set('shown', v);
      if (v && countrySelector.getValue()) {
        updateMap();
      } else {
        markNeedsUpdate();
      }
    },
    style: {fontSize: '11px', margin: '4px 8px 0 8px'}
  });
  var disableMapHint = ui.Label(
    'Map preview off — Update Analysis + Export to Drive still work. ' +
    'On-the-fly Show Stats disabled; use Export Statistics to Drive instead.',
    {fontSize: '10px', color: '#666', fontStyle: 'italic',
    margin: '0 8px 4px 24px', shown: false}
  );

  // Track if parameters have changed since last update
  var needsUpdate = false;

  function markNeedsUpdate() {
    if (!needsUpdate) {
      needsUpdate = true;
      runButton.setLabel('↻ Update Analysis *');
    }
    showStatsButton.setLabel('↻ Show Area\nStatistics *');
  }

  function markUpToDate() {
    needsUpdate = false;
    runButton.setLabel('↻ Update Analysis');
  }

  var topBarRow = ui.Panel({
    widgets: [appTitle, countrySelector, countryWarningLabel, recenterButton, titleSpacer, configButton, aboutButton],
    layout: ui.Panel.Layout.flow('horizontal'),
    style: {stretch: 'horizontal', padding: '0'}
  });

  var topBar = ui.Panel({
    widgets: [topBarRow],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {
      stretch: 'horizontal',
      backgroundColor: 'rgba(255, 255, 255, 0.95)',
      padding: '4px',
      border: '1px solid #ccc'
    }
  });

  // =============================================================================
  // SLIDERS (using pff2 values)
  // =============================================================================

  var treecoverThresholdSlider = ui.Slider({min: 0, max: 100, value: 10, step: 5, onChange: function() { markNeedsUpdate(); updateRefineFraWarning(); }});
  var treecoverHeightThresholdSlider = ui.Slider({min: 3, max: 25, value: 5, step: 1, onChange: function() { markNeedsUpdate(); updateRefineFraWarning(); }});
  var roadSmallBufferSlider = ui.Slider({min: 0, max: 5000, value: 1000, step: 50, onChange: markNeedsUpdate});
  // roadLargeBufferSlider removed — single roads category only
  var builtUpSmallBufferSlider = ui.Slider({min: 0, max: 5000, value: 1000, step: 50, onChange: markNeedsUpdate});
  var builtUpLargeBufferSlider = ui.Slider({min: 0, max: 5000, value: 1000, step: 50, onChange: markNeedsUpdate});
  var agriBufferSlider = ui.Slider({min: 0, max: 5000, value: 1000, step: 50, onChange: markNeedsUpdate});

  // Master buffer slider — sets all influence buffer distances at once
  var masterBufferSlider = ui.Slider({
    min: 0, max: 5000, value: 1000, step: 50,
    onChange: function(value) {
      roadSmallBufferSlider.setValue(value, false);
      builtUpSmallBufferSlider.setValue(value, false);
      builtUpLargeBufferSlider.setValue(value, false);
      agriBufferSlider.setValue(value, false);
      markNeedsUpdate();
    }
  });

  // Panels that hold individual slider rows (created later, referenced here)
  var individualBufferRows = null; // set after anthropogenicContent is built
  var masterBufferRow = null;      // set after anthropogenicContent is built

  var masterBufferStatusLabel = ui.Label('', {fontSize: '10px', color: '#888', fontStyle: 'italic', margin: '0 0 4px 4px', shown: false, whiteSpace: 'pre'});

  function updateMasterBufferStatus() {
    if (!useMasterBufferCheckbox.getValue()) {
      masterBufferStatusLabel.style().set({shown: false});
      return;
    }
    var enabled = [];
    var notEnabled = [];
    if (enableRoadsBuffer && enableRoadsBuffer.getValue()) enabled.push('Roads'); else notEnabled.push('Roads');
    if (enableBuiltUpSmallBuffer && enableBuiltUpSmallBuffer.getValue()) enabled.push('Built-up small'); else notEnabled.push('Built-up small');
    if (enableBuiltUpLargeBuffer && enableBuiltUpLargeBuffer.getValue()) enabled.push('Built-up large'); else notEnabled.push('Built-up large');
    if (enableAgriBuffer && enableAgriBuffer.getValue()) enabled.push('Agriculture'); else notEnabled.push('Agriculture');
    var parts = [];
    if (enabled.length) parts.push('Enabled: ' + enabled.join(', '));
    if (notEnabled.length) parts.push('Not enabled: ' + notEnabled.join(', '));
    masterBufferStatusLabel.setValue(parts.join('\n'));
    masterBufferStatusLabel.style().set({shown: true});
  }

  var useMasterBufferCheckbox = ui.Checkbox({
    label: 'Use single distance for all:',
    value: false,
    onChange: function(checked) {
      if (individualBufferRows) {
        individualBufferRows.forEach(function(row) {
          row.style().set({shown: !checked});
        });
      }
      if (masterBufferRow) {
        masterBufferRow.style().set({shown: checked});
      }
      if (checked) {
        var val = masterBufferSlider.getValue();
        roadSmallBufferSlider.setValue(val, false);
        builtUpSmallBufferSlider.setValue(val, false);
        builtUpLargeBufferSlider.setValue(val, false);
        agriBufferSlider.setValue(val, false);
      }
      updateMasterBufferStatus();
      markNeedsUpdate();
    },
    style: {fontSize: '11px', margin: '4px 0 0 0'}
  });
  var slopeToKeepSlider = ui.Slider({min: 0, max: 90, value: 45, step: 5, onChange: markNeedsUpdate});

    
  // Cache for country hex grids
  var countryHexGridCache = {};

  // Format a number string with commas for thousands (e.g. "1234567.8" -> "1,234,567.8")
  function formatWithCommas(numStr) {
    var parts = numStr.split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return parts.join('.');
  }

  function processForestAreaStats(image, name, year, scale, exportToDrive, country, panel, onComplete) {
    var pixelArea = ee.Image.pixelArea();
    var forestArea = image.multiply(pixelArea);

    // Use the country from parameter or global
    var countryName = country || selectedCountry;
    // Use cache for country hex grid
    if (!countryHexGridCache[countryName]) {
      var country_features = getCountryFeatures(countryName);
      countryHexGridCache[countryName] = country_features.geometry().coveringGrid('EPSG:4326', 50000);
    }
    var country_hex_grid = countryHexGridCache[countryName];

    var stats = forestArea.reduceRegions({
      collection: country_hex_grid,
      reducer: ee.Reducer.sum(),
      scale: scale
    });

    var totalArea = stats.aggregate_sum('sum');

    if (!exportToDrive) {
      totalArea.evaluate(function(result) {
        var msg;
        if (result !== null && result !== undefined) {
          var formattedResultKha = formatWithCommas(Number(result / 1e7).toFixed(1));
          msg = "✓ " + name + ": " + formattedResultKha + " kha";
        } else {
          msg = "✗ " + name + " (" + year + "): No valid data / processing timeout";
        }
        if (panel) {
          panel.add(ui.Label(msg));
        } else {
          print(msg);
        }
        if (onComplete) {
          onComplete();
        }
      });
    } else {
      // Only include relevant thresholds for each dataset.
      // After 14b rename: forest stats rows are "Forest" / "Naturally
      // regenerating forest"; primary row stays "Primary Forest".
      var isPrimary = name.indexOf('Primary Forest') !== -1;
      var isForestRow = !isPrimary;
      var feature = ee.Feature(null, {
        'Country': countryName,
        'Year': year,
        'Forest Type': name,
        'Area (sq km)': totalArea.divide(1e6),
        'Resolution (m)': scale,
        "Treecover Threshold (%)": isForestRow ? treecoverThresholdSlider.getValue() : '',
        'GLAD Treecover Height (m)': isPrimary ? treecoverHeightThresholdSlider.getValue() : '',
        "Road Small Buffer (m)": roadSmallBufferSlider.getValue(),
        "Built-Up Small Buffer (m)": builtUpSmallBufferSlider.getValue(),
        "Built-Up Large Buffer (m)": builtUpLargeBufferSlider.getValue(),
        "Agriculture Buffer (m)": agriBufferSlider.getValue(),
        // "Other Natural Buffer (m)": otherNatBuffer,
        "Slope to Keep": slopeToKeepSlider.getValue(),
        // "Slope Threshold (%)": ,
        "Years Protected": years_protected,
        // "Fast Buffer Used": fastBuffer ? "Yes" : "No",
        "Strict IUCN Categories": selected_iucn_categories.join(", "),
        // P1.23: report what was *effectively* applied (exclusionActive)
        // so the metadata reflects the analysis run, not stale UI state.
        "Plantations Included": exclusionActive(includePlantationsCheckbox, includePlantationsPanel) ? "No" : "Yes",
        "FRA Agriculture Excluded from Forest": exclusionActive(excludeAgricultureFromForestCheckbox, excludeAgriPanel) ? "Yes" : "No",
        "Input Category (declared)": inputCategorySelect.getValue(),
        "FRA Aligned": fraAlignedCheckbox.getValue() ? "Yes" : "No",
        "Refine Input Applied": refineInputCheckbox.getValue() ? "Yes" : "No",
        "Custom Forest Asset Active": nationalForest.checkbox.getValue() ? "Yes" : "No",
        "Custom Forest Merge Mode": nationalForest.checkbox.getValue() ? nationalForest.modeSelect.getValue() : ""
      });
      
      Export.table.toDrive({
        collection: ee.FeatureCollection([feature]),
        description: "Area_" + name.replace(/[\s.()]+/g, "_").replace(/_+/g, "_").replace(/_$/, "") + "_" + year + "_" +
                    cleanCountryName(countryName) + "_" + scale + "m",
        fileFormat: "CSV"
      });
    }
  }


  var showStatsButton = ui.Button({
    label: '↻ Show Area Statistics',
    style: {margin: '8px 0 8px 8px', fontWeight: 'bold', fontSize: '11px'},
    onClick: function() {
      showStatsButton.setLabel('↻ Show Area\nStatistics');
      areaStatsPanel.clear();
      // P1.26: in "Disable map" mode, on-the-fly stats are disabled
      // because each layer/year does a server-side .evaluate() roundtrip
      // -- bad on slow connections. Steer the user to Export Statistics
      // to Drive instead, which queues a server-side task.
      if (disableMapCheckbox.getValue()) {
        areaStatsPanel.add(ui.Label(
          'On-the-fly Show Area Statistics is disabled in low-internet mode. ' +
          'Use "Export Statistics to Drive" below -- it queues a server-side ' +
          'task and the CSV waits in your Drive for later pickup.',
          {color: '#b58105', fontSize: '11px', fontStyle: 'italic',
          margin: '0 0 6px 0'}));
        return;
      }
      var selectedCountry = countrySelector.getValue();
      if (!selectedCountry) {
        areaStatsPanel.add(ui.Label('Please select a country first.'));
        return;
      }
      if (Object.keys(latestMaskedForest).length === 0) {
        areaStatsPanel.add(ui.Label('No forest data available. Please wait for the map to load first.'));
        return;
      }
      // P0.10 stale-stats warning: if a parameter was changed since the
      // last analysis run, the cached forest layers are out of date and
      // the stats below will reflect the OLD parameters, not what's
      // currently set in the UI. Prompt the user to re-run analysis.
      if (needsUpdate) {
        areaStatsPanel.add(ui.Label(
          '⚠ Analysis is OUT OF DATE (parameters changed since last run). ' +
          'Stats below reflect the previous run. Click "↻ Update Analysis" ' +
          'and re-run "↻ Show Area Statistics" for current numbers.',
          {color: '#b58105', fontSize: '11px', fontWeight: 'bold', margin: '0 0 6px 0'}));
      }
      var selectedCountry = countrySelector.getValue();
      areaStatsPanel.add(ui.Label(selectedCountry, {fontWeight: 'bold'}));
      var statsScale = statsScaleSlider.getValue();
      areaStatsPanel.add(ui.Label('(Estimated at ' + statsScale + 'm resolution)', {fontSize: '11px', color: '#666', margin: '0 0 8px 0'}));

      // Create a panel for each year so results appear in order
      Object.keys(latestMaskedForest).forEach(function(year) {
        var yearInt = parseInt(year);
        var yearPanel = ui.Panel({layout: ui.Panel.Layout.flow('vertical')});
        yearPanel.add(ui.Label('Year ' + year + ':', {fontWeight: 'bold', margin: '4px 0 2px 0'}));
        areaStatsPanel.add(yearPanel);

        // FRA comparison line (static, instant) — shown first
        var fraLabel = fraStats.formatFRA(selectedCountry, yearInt);
        yearPanel.add(ui.Label('  ' + fraLabel, {fontSize: '11px', color: '#555', margin: '0 0 2px 4px'}));
        // Separator between FRA and calculated values
        yearPanel.add(ui.Label('  ───────────', {color: '#ccc', fontSize: '10px', margin: '0 0 2px 4px'}));
        // Progress indicator — updates per step
        var calcLabel = ui.Label('  Calculating total forest area...', {color: '#888', fontStyle: 'italic'});
        yearPanel.add(calcLabel);

        // P1.23a: only show rows for distinct refinement steps. A row is
        // suppressed when its content would be identical to the row
        // above it (e.g. Forest == Tree cover when OLWTC toggle is off).
        // Resulting cascades:
        //   declared "All tree cover":  Tree, Forest (if OLWTC on), NRF (if planted on), Primary
        //   declared "Forest only":     Forest, NRF (if planted on), Primary
        //   declared "Naturally regen": NRF, Primary
        //   declared "Primary":         Primary
        var declCat = inputCategorySelect.getValue();
        var olwtcApplied = exclusionActive(excludeAgricultureFromForestCheckbox, excludeAgriPanel);
        var plantedApplied = exclusionActive(includePlantationsCheckbox, includePlantationsPanel);
        // Input row: always shown. Label depends on declaration.
        // - No FRA category alignment (default): "Input"
        // - Tree cover declared:                  "Tree cover" (handled by showTreeCoverRow branch)
        // - Forest / NRF / Primary declared:      input == declared category;
        //   suppress this row since the cascade already has a labelled row for it.
        var showInputRow = (declCat === INPUT_CATEGORY_NONE
                            || !declCat || declCat === '');
        var showTreeCoverRow = (declCat === INPUT_CATEGORY_ALL);
        // Forest is distinct only when OLWTC was applied (declared ALL)
        // or when input IS forest (declared Forest).
        var showForestRow = (declCat === INPUT_CATEGORY_ALL && olwtcApplied) ||
                            (declCat === INPUT_CATEGORY_FOREST);
        // NRF is distinct only when planted was applied (declared ALL or
        // Forest) or when input IS NRF (declared NRF).
        var showNrfRow = ((declCat === INPUT_CATEGORY_ALL ||
                          declCat === INPUT_CATEGORY_FOREST) && plantedApplied) ||
                        (declCat === INPUT_CATEGORY_NATREG);
        // Primary row always shown when produced.

        // Track pending calculations for this year.
        var hasInput     = showInputRow     && latestMaskedTreeCover[year] !== undefined;
        var hasTreeCover = showTreeCoverRow && latestMaskedTreeCover[year] !== undefined;
        var hasForest    = showForestRow    && latestMaskedForest[year] !== undefined;
        var hasNatreg    = showNrfRow       && latestMaskedNaturallyRegenerating[year] !== undefined;
        var pending = (hasInput ? 1 : 0)
          + (hasTreeCover ? 1 : 0)
          + (hasForest ? 1 : 0)
          + (hasNatreg ? 1 : 0)
          + (latestMaskedPrimaryForest[year] ? 1 : 0);
        if (pending === 0) {
          // Edge case: user declared Primary but primary not produced yet
          yearPanel.remove(calcLabel);
          yearPanel.add(ui.Label('  (no rows to display)', {fontSize: '11px', color: '#888'}));
          return;
        }
        // P1.30 Batch 27.1: sequential dispatch instead of parallel.
        // Previous parallel implementation fired all evaluate()'s at
        // once and updated calcLabel from each callback -- when one
        // resolved before the next was queued, the label could read
        // "Calculating naturally regenerating forest area..." while
        // the row actually computing was Primary (or vice versa).
        // Building a queue + processing one at a time guarantees the
        // label always matches the row in flight. Slightly slower
        // total (rows compute serially), but the panel is correct.
        var rowQueue = [];
        if (hasInput) {
          rowQueue.push({
            layer: latestMaskedTreeCover[year], name: 'Input',
            waitText: '  Calculating input area...'
          });
        }
        if (hasTreeCover) {
          rowQueue.push({
            layer: latestMaskedTreeCover[year], name: 'Tree cover',
            waitText: '  Calculating tree cover area...'
          });
        }
        var _fraTag = fraAlignedCheckbox.getValue() ? '' : ' (non-FRA-aligned)';
        if (hasForest) {
          rowQueue.push({
            layer: latestMaskedForest[year], name: 'Forest' + _fraTag,
            waitText: '  Calculating forest area...'
          });
        }
        if (hasNatreg) {
          rowQueue.push({
            layer: latestMaskedNaturallyRegenerating[year],
            name: 'Naturally regenerating forest' + _fraTag,
            waitText: '  Calculating naturally regenerating forest area...'
          });
        }
        if (latestMaskedPrimaryForest[year]) {
          rowQueue.push({
            layer: latestMaskedPrimaryForest[year], name: 'Primary Forest',
            waitText: '  Calculating primary forest area...'
          });
        }
        var processRow = function(idx) {
          if (idx >= rowQueue.length) {
            yearPanel.remove(calcLabel);
            return;
          }
          var item = rowQueue[idx];
          calcLabel.setValue(item.waitText);
          processForestAreaStats(
            item.layer, item.name, yearInt, statsScale, false,
            selectedCountry, yearPanel,
            function() { processRow(idx + 1); });
        };
        processRow(0);
      });
    }
  });



  // Helper to get native resolution string based on selected forest data source
  function getNativeResolutionText() {
    // P1.23: Custom Forest is no longer a Source-dropdown option; if the
    // user has supplied a custom forest layer it overrides/merges with
    // the global source (see nationalForest), so report the global-source
    // resolution + a note that the effective resolution depends on the
    // custom asset.
    if (nationalForest.checkbox.getValue()) return 'unknown (custom asset)';
    var src = treecoverSourceSelect.getValue();
    if (src === 'Hansen GFC') return '~30m (Hansen GFC)';
    if (src === 'GLAD LULC') return '~30m (GLAD LULC)';
    return '~30m (Hansen GFC & GLAD LULC)';
  }

  // Info popup for area statistics
  var statsInfoContent = ui.Panel({
    widgets: [
      ui.Label('Area Statistics', {fontWeight: 'bold', fontSize: '12px', margin: '0 0 4px 0'}),
      ui.Label('On-the-fly statistics may time out at high resolutions ' +
              'for large countries. If this happens, try increasing the ' +
              'Resolution slider or use "Export Statistics to Drive" which has ' +
              'larger time and memory allowances.',
              {fontSize: '11px', margin: '0 0 6px 0'}),
      ui.Label('Note: statistics computed at a resolution coarser than the ' +
              'native resolution of the forest data ' +
              'can differ significantly from native-resolution results.',
              {fontSize: '11px', margin: '0 0 6px 0'}),
      ui.Label('FRA values shown are reported national statistics from the ' +
              'FAO Forest Resources Assessment (FRA 2025).',
              {fontSize: '11px', margin: '0 0 6px 0'}),
      ui.Label('─── FRA 2025 definitions ───', {fontWeight: 'bold', fontSize: '10px', color: '#888', margin: '4px 0 2px 0'}),
      ui.Label('Forest', {fontWeight: 'bold', fontSize: '10px', margin: '0 0 0 4px'}),
      ui.Label('As tree cover, but land use is forest (excludes agricultural & urban tree stands)', {fontSize: '10px', margin: '0 0 2px 12px', color: '#555'}),
      ui.Label('Naturally regenerating forest', {fontWeight: 'bold', fontSize: '10px', margin: '0 0 0 4px'}),
      ui.Label('Forest established through natural regeneration', {fontSize: '10px', margin: '0 0 2px 12px', color: '#555'}),
      ui.Label('Primary forest', {fontWeight: 'bold', fontSize: '10px', margin: '0 0 0 4px'}),
      ui.Label('Naturally regenerating, native species, no visible human activity', {fontSize: '10px', margin: '0 0 2px 12px', color: '#555'}),
      ui.Label({
        value: 'FAO FRA 2025 full definitions →',
        style: {fontSize: '10px', color: '#1a73e8', margin: '2px 0 0 4px'},
        targetUrl: 'https://fra-data.fao.org/definitions/fra/2025/en/tad#1b'
      })
    ],
    style: {shown: false, padding: '6px', margin: '4px 0 4px 8px', backgroundColor: '#fff8e1', border: '1px solid #e0c050', width: '240px'}
  });

  var statsInfoButton = ui.Button({
    label: ' i ',
    onClick: function() {
      var isShown = statsInfoContent.style().get('shown');
      // Refresh native resolution text each time
      statsInfoContent.widgets().set(2,
        ui.Label('Note: statistics computed at a resolution coarser than the ' +
                'native resolution of the forest data (currently ' + getNativeResolutionText() + ') ' +
                'can differ significantly from native-resolution results.',
                {fontSize: '11px', margin: '0 0 6px 0'})
      );
      statsInfoContent.style().set({shown: !isShown});
    },
    style: {padding: '4px 8px', margin: '12px 0 0 4px', fontSize: '13px', fontWeight: 'bold', backgroundColor: '#e0e0e0'}
  });

  // Panel to display area statistics results (must be defined before showStatsButton)
  var areaStatsPanel = ui.Panel({
    layout: ui.Panel.Layout.flow('vertical'),
    style: {
      margin: '8px 0 8px 8px', 
      padding: '8px', 
      backgroundColor: '#f7f7f7', 
      border: '1px solid #ccc',
      width: '250px'
    }
  });

  // Button to clear the area statistics panel
  var clearStatsButton = ui.Button({
    label: 'Clear Statistics',
    style: {margin: '0 0 6px 8px', backgroundColor: '#eee', color: '#888', fontSize: '10px'},
    onClick: function() {
      areaStatsPanel.clear();
      exportStatusLabel.setValue('');
    }
  });




  // Shared scale slider for both on-the-fly and export statistics.
  // Marks Stats button stale on change; doesn't touch the analysis cache
  // (the scale only affects stats reduction, not the per-pixel analysis).
  var statsScaleSlider = ui.Slider({
    min: 30, max: 3000, value: 900, step: 30,
    style: {margin: '0 0 6px 0', stretch: 'horizontal'},
    onChange: function() {
      showStatsButton.setLabel('↻ Show Area\nStatistics *');
    }
  });
  var statsScaleLabel = ui.Label('Resolution (m):', {margin: '0 8px 0 0'});

  // Label for export status message
  var exportStatusLabel = ui.Label('', {margin: '4px 0 0 8px', width: '280px'});

  // Button to export statistics as CSV
  var exportStatsButton = ui.Button({
    label: 'Export Statistics to Drive',
    style: {margin: '0 0 6px 8px', backgroundColor: '#e0ffe0', fontSize: '11px'},
    onClick: function() {
      exportStatusLabel.setValue('');
      if (Object.keys(latestMaskedForest).length === 0) {
        exportStatusLabel.setValue('No forest data to export.');
        return;
      }
      var selectedCountry = countrySelector.getValue();
      if (!selectedCountry) {
        exportStatusLabel.setValue('Please select a country first.');
        return;
      }
      var exportScale = statsScaleSlider.getValue();
      // P1.23a: same redundant-row rules as the on-the-fly stats panel
      // so the exported CSV matches what's displayed.
      var exportDeclCat = inputCategorySelect.getValue();
      var exportOlwtcApplied = exclusionActive(excludeAgricultureFromForestCheckbox, excludeAgriPanel);
      var exportPlantedApplied = exclusionActive(includePlantationsCheckbox, includePlantationsPanel);
      // Input row: same logic as the on-the-fly stats panel — always
      // emitted when no FRA category declared. Avoids redundancy when
      // a category IS declared (Tree cover row already covers it).
      var exportShowInput = (exportDeclCat === INPUT_CATEGORY_NONE
                             || !exportDeclCat || exportDeclCat === '');
      var exportShowTreeCover = (exportDeclCat === INPUT_CATEGORY_ALL);
      var exportShowForest = (exportDeclCat === INPUT_CATEGORY_ALL && exportOlwtcApplied) ||
                            (exportDeclCat === INPUT_CATEGORY_FOREST);
      var exportShowNrf = ((exportDeclCat === INPUT_CATEGORY_ALL ||
                            exportDeclCat === INPUT_CATEGORY_FOREST) && exportPlantedApplied) ||
                          (exportDeclCat === INPUT_CATEGORY_NATREG);
      var _exportFraTag = fraAlignedCheckbox.getValue() ? '' : ' (non-FRA-aligned)';
      Object.keys(latestMaskedForest).forEach(function(year) {
        var yearInt = parseInt(year);
        if (exportShowInput && latestMaskedTreeCover[year]) {
          processForestAreaStats(latestMaskedTreeCover[year], 'Input', yearInt, exportScale, true, selectedCountry);
        }
        if (exportShowTreeCover && latestMaskedTreeCover[year]) {
          processForestAreaStats(latestMaskedTreeCover[year], 'Tree cover', yearInt, exportScale, true, selectedCountry);
        }
        if (exportShowForest) {
          processForestAreaStats(latestMaskedForest[year], 'Forest' + _exportFraTag, yearInt, exportScale, true, selectedCountry);
        }
        if (exportShowNrf && latestMaskedNaturallyRegenerating[year]) {
          processForestAreaStats(latestMaskedNaturallyRegenerating[year], 'Naturally regenerating forest' + _exportFraTag, yearInt, exportScale, true, selectedCountry);
        }
        if (latestMaskedPrimaryForest[year]) {
          processForestAreaStats(latestMaskedPrimaryForest[year], "Primary Forest", yearInt, exportScale, true, selectedCountry);
        }
      });
      exportStatusLabel.setValue('Export submitted. Check Tasks tab to start processing output table(s) to your Drive.');
    }
  });

  // Panel to hold export button on top, scale label and slider below
  var exportStatsPanel = ui.Panel({
    widgets: [
      exportStatsButton,
      // Scale slider moved to shared statsScaleSlider above
      // ui.Panel([statsScaleLabel, statsScaleSlider], ...)
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {margin: '6px 0 0 8px', width: '280px'}
  });

  // ──────────────────────────────────────────────
  // Export Rasters (for QGIS / offline use)
  // ──────────────────────────────────────────────
  var exportRasterScaleSlider = ui.Slider({
    min: 30, max: 1000, value: 30, step: 10,
    style: {margin: '0 0 6px 0', stretch: 'horizontal'}
  });
  var exportToCloudCheckbox = ui.Checkbox({
    label: 'Export as COGs to Cloud Storage',
    value: false
  });
  var gcsBucketInput = ui.Textbox({
    placeholder: 'my-gcs-bucket',
    style: {width: '160px', shown: false}
  });
  exportToCloudCheckbox.onChange(function(checked) {
    gcsBucketInput.style().set('shown', checked);
  });
  var exportRasterStatusLabel = ui.Label('', {margin: '4px 0 0 8px', width: '280px'});

  // ── Selective export controls ──
  // Labels include the step prefix for the EXPORT FILENAME so the
  // dropdown reads top-to-bottom in schema order (00 -> 01 -> 02 ->
  // 03 -> 04 -> sidecar). Step prefixes shown in parentheses match
  // the file-name segment used by mkExportName(step, ...).
  var exportChkStyle = {fontSize: '11px', margin: '1px 0'};
  // ── Main outputs (default ON) ──
  var exportChk_inputForest     = ui.Checkbox({label: 'Forest', value: true,  style: exportChkStyle});
  var exportChk_naturallyRegenerating = ui.Checkbox({label: 'Naturally regenerating forest', value: true,  style: exportChkStyle});
  var exportChk_final           = ui.Checkbox({label: 'Primary forest', value: true,  style: exportChkStyle});
  var exportChk_runMetadata     = ui.Checkbox({label: 'Run metadata (config snapshot)', value: true,  style: exportChkStyle});
  // ── Intermediates (default OFF) ──
  var exportChk_preConnectivity = ui.Checkbox({label: 'Pre-refinement primary forest', value: false, style: exportChkStyle});
  var exportChk_fraAgriculture  = ui.Checkbox({label: 'Other land with tree cover', value: false, style: exportChkStyle});
  var exportChk_plantations     = ui.Checkbox({label: 'Planted forest', value: false, style: exportChkStyle});
  // ── Inputs (default OFF) ──
  var exportChk_forestRaw       = ui.Checkbox({label: 'Tree cover (raw input)', value: false, style: exportChkStyle});
  var exportChk_hansenRaw       = ui.Checkbox({label: 'Hansen raw', value: false, style: exportChkStyle});
  var exportChk_gladHeight      = ui.Checkbox({label: 'GLAD tree height', value: false, style: exportChkStyle});
  var exportChk_roads           = ui.Checkbox({label: 'Roads', value: false, style: exportChkStyle});
  var exportChk_roadsOsmVector  = ui.Checkbox({label: 'Roads (vector)', value: false, style: exportChkStyle});
  var exportChk_builtupSmall    = ui.Checkbox({label: 'Built-up small', value: false, style: exportChkStyle});
  var exportChk_builtupLarge    = ui.Checkbox({label: 'Built-up large', value: false, style: exportChkStyle});
  var exportChk_agriculture     = ui.Checkbox({label: 'Agriculture', value: false, style: exportChkStyle});
  var exportChk_dem             = ui.Checkbox({label: 'DEM', value: false, style: exportChkStyle});
  var exportChk_slope           = ui.Checkbox({label: 'Slope', value: false, style: exportChkStyle});
  var exportChk_protLegal       = ui.Checkbox({label: 'Protected areas', value: false, style: exportChkStyle});
  var exportChk_protVector      = ui.Checkbox({label: 'Protected areas (vector)', value: false, style: exportChkStyle});
  var exportChk_aoi             = ui.Checkbox({label: 'AOI boundary', value: false, style: exportChkStyle});

  // Select all / none master tickbox -- one-click bulk on/off for every
  // per-layer checkbox below. Default unticked: per-layer defaults are
  // mixed (some on, some off) so the master can't honestly claim either
  // state at startup. Toggling it overwrites all children. Manual
  // per-layer edits afterwards don't auto-resync the master (kept simple).
  // All export checkboxes for bulk operations
  var allExportCheckboxes = [
    exportChk_inputForest, exportChk_naturallyRegenerating,
    exportChk_final, exportChk_runMetadata,
    exportChk_preConnectivity, exportChk_fraAgriculture, exportChk_plantations,
    exportChk_forestRaw, exportChk_hansenRaw, exportChk_gladHeight,
    exportChk_roads, exportChk_roadsOsmVector,
    exportChk_builtupSmall, exportChk_builtupLarge, exportChk_agriculture,
    exportChk_dem, exportChk_slope,
    exportChk_protLegal, exportChk_protVector, exportChk_aoi
  ];

  var exportChkAllToggle = ui.Checkbox({
    label: 'Select all / none',
    value: false,
    onChange: function (v) {
      allExportCheckboxes.forEach(function (cb) { cb.setValue(v); });
    },
    style: {fontSize: '11px', fontWeight: 'bold', margin: '4px 0 2px 0'}
  });

  function resetExportDefaults() {
    exportChk_inputForest.setValue(true);
    exportChk_naturallyRegenerating.setValue(true);
    exportChk_final.setValue(true);
    exportChk_runMetadata.setValue(true);
    [exportChk_preConnectivity, exportChk_fraAgriculture, exportChk_plantations,
     exportChk_forestRaw, exportChk_hansenRaw, exportChk_gladHeight,
     exportChk_roads, exportChk_roadsOsmVector,
     exportChk_builtupSmall, exportChk_builtupLarge, exportChk_agriculture,
     exportChk_dem, exportChk_slope,
     exportChk_protLegal, exportChk_protVector, exportChk_aoi
    ].forEach(function(cb) { cb.setValue(false); });
  }

  var exportDefaultsButton = ui.Button({
    label: 'Defaults',
    onClick: resetExportDefaults,
    style: {fontSize: '10px', padding: '2px 8px', margin: '2px 0', backgroundColor: '#f0f0f0'}
  });

  // Collapsible intermediates panel
  var intermediatesContent = ui.Panel({
    widgets: [exportChk_preConnectivity, exportChk_fraAgriculture, exportChk_plantations],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, margin: '0 0 0 8px'}
  });
  var intermediatesToggle = ui.Button({
    label: '▸ Intermediates',
    onClick: function() {
      var s = intermediatesContent.style().get('shown');
      intermediatesContent.style().set({shown: !s});
      intermediatesToggle.setLabel(s ? '▸ Intermediates' : '▾ Intermediates');
    },
    style: {fontSize: '10px', color: '#555', margin: '2px 0', padding: '1px 6px', backgroundColor: '#f8f8f8'}
  });

  // Collapsible inputs panel
  var inputsContent = ui.Panel({
    widgets: [
      exportChk_forestRaw, exportChk_hansenRaw, exportChk_gladHeight,
      exportChk_roads, exportChk_roadsOsmVector,
      exportChk_builtupSmall, exportChk_builtupLarge, exportChk_agriculture,
      exportChk_dem, exportChk_slope,
      exportChk_protLegal, exportChk_protVector, exportChk_aoi
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, margin: '0 0 0 8px'}
  });
  var inputsToggle = ui.Button({
    label: '▸ Inputs',
    onClick: function() {
      var s = inputsContent.style().get('shown');
      inputsContent.style().set({shown: !s});
      inputsToggle.setLabel(s ? '▸ Inputs' : '▾ Inputs');
    },
    style: {fontSize: '10px', color: '#555', margin: '2px 0', padding: '1px 6px', backgroundColor: '#f8f8f8'}
  });

  // Collapsible main outputs panel (closed by default — user opens to see layer choices)
  var mainOutputsContent = ui.Panel({
    widgets: [
      exportChkAllToggle,
      exportChk_inputForest,
      exportChk_naturallyRegenerating,
      exportChk_final,
      exportChk_runMetadata
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, margin: '0 0 0 8px'}
  });
  var mainOutputsToggle = ui.Button({
    label: '▸ Main',
    onClick: function() {
      var s = mainOutputsContent.style().get('shown');
      mainOutputsContent.style().set({shown: !s});
      mainOutputsToggle.setLabel(s ? '▸ Main' : '▾ Main');
    },
    style: {fontSize: '10px', color: '#555', margin: '2px 0', padding: '1px 6px', backgroundColor: '#f8f8f8'}
  });

  var exportSelectPanel = ui.Panel({
    widgets: [
      ui.Label('Layers to save:', {fontWeight: 'bold', fontSize: '11px', margin: '4px 0 2px 0'}),
      mainOutputsToggle,
      mainOutputsContent,
      intermediatesToggle,
      intermediatesContent,
      inputsToggle,
      inputsContent
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {margin: '0 0 4px 0'}
  });

  // Build a per-run metadata bundle for the JSON sidecar export and the
  // in-browser snapshot download. Combines the user's full config (mirrors
  // Save Settings) with run-specifics (timestamp, year exported, scale,
  // destination, version). Keys are flat and prefixed (config__* / run__*)
  // because Earth Engine's getDownloadURL serialises Feature properties
  // best as flat key-value pairs.
  function buildRunBundle(year, scale, iso3, exportFolder, useCloud) {
    var bundle = {};
    var settings = collectSettings();
    Object.keys(settings).forEach(function(k) {
      bundle['config__' + k] = settings[k];
    });
    bundle['run__pff_script_version'] = PFF_SCRIPT_VERSION;
    bundle['run__timestamp']          = new Date().toISOString();
    bundle['run__country']            = countrySelector.getValue();
    bundle['run__iso3']               = iso3;
    bundle['run__year_exported']      = year;
    bundle['run__scale_m']            = scale;
    bundle['run__export_destination'] = useCloud ? 'cloud_storage' : 'google_drive';
    bundle['run__export_folder']      = exportFolder;
    return bundle;
  }

  function exportRastersToDrive() {
    exportRasterStatusLabel.setValue('');

    var selectedCountry = countrySelector.getValue();
    if (!selectedCountry) {
      exportRasterStatusLabel.setValue('Please select a country first.');
      return;
    }
    var analysisYear1 = parseInt(yearSelector1.getValue());
    var analysisYear2 = parseInt(yearSelector2.getValue());
    var exportScale = exportRasterScaleSlider.getValue();
    // Unique run tag so GEE doesn't reject duplicate task descriptions
    var runNow = new Date();
    var runPad = function(n) { return n < 10 ? '0' + n : n; };
    // ISO-8601 basic UTC: _YYYYMMDDTHHMMZ. Sortable + unambiguous +
    // no FS-invalid characters. Replaces the legacy _HHhMMm which
    // collided across days and wasn't lex-sortable.
    var runTag = '_' + runNow.getUTCFullYear()
      + runPad(runNow.getUTCMonth() + 1)
      + runPad(runNow.getUTCDate())
      + 'T'
      + runPad(runNow.getUTCHours())
      + runPad(runNow.getUTCMinutes())
      + 'Z';
    var countryClean = cleanCountryName(selectedCountry);
    var countryInfo = gaulLut.GAUL_LUT[gaulLut.nameToCode(selectedCountry)];
    var iso3 = countryInfo ? countryInfo.iso3 : countryClean.substring(0, 3).toUpperCase();

    var country_sel = getCountryFeatures(selectedCountry);
    var country_geom = country_sel.geometry();

    // Export in native GEE CRS (EPSG:4326) — matches how analysis was computed
    var targetCRS = 'EPSG:4326';

    // Export region: bounding box of the buffered country boundary. GEE always
    // writes a rectangular GeoTIFF covering the region's bbox, so using .bounds()
    // makes the region match the actual output extent while keeping the geometry
    // to 5 vertices — avoids vertex-limit overflow for archipelago countries
    // (Indonesia, Philippines, etc.) whose coastlines re-densify under .buffer().
    var exportRegion = country_geom.buffer(country_buffer_threshold + 1000).bounds();

    // Export destination: Cloud Storage (COG) or Drive (GeoTIFF COG)
    var useCloud = exportToCloudCheckbox.getValue();
    var gcsBucket = gcsBucketInput.getValue();
    if (useCloud && (!gcsBucket || gcsBucket.trim() === '')) {
      exportRasterStatusLabel.setValue('Please enter a GCS bucket name.');
      return;
    }

    // P1.13 Option D filename helper. Wraps generateLayerName() with the
    // current run's iso3, the GEE platform tag, and appends runTag (a
    // unique HHhMMm suffix) for task-id uniqueness across same-day
    // re-runs. Returns extension-less since GEE appends .tif / .geojson
    // / etc. automatically based on fileFormat.
    function mkExportName(step, name) {
      return generateLayerName(iso3, PLATFORM_GEE, step, name, '') + runTag;
    }

    // Shared export helper (binary/byte images). Caller passes the full
    // already-formatted filename in `description` (use mkExportName()).
    function doExport(image, description, folder) {
      if (useCloud) {
        Export.image.toCloudStorage({
          image: image.toByte(),
          description: description,
          bucket: gcsBucket.trim(),
          fileNamePrefix: folder + '/' + description,
          region: exportRegion,
          scale: exportScale,
          crs: targetCRS,
          maxPixels: 1e13,
          fileFormat: 'GeoTIFF',
          formatOptions: {cloudOptimized: true}
        });
      } else {
        Export.image.toDrive({
          image: image.toByte(),
          description: description,
          folder: folder,
          region: exportRegion,
          scale: exportScale,
          crs: targetCRS,
          maxPixels: 1e13,
          fileFormat: 'GeoTIFF',
          formatOptions: {cloudOptimized: true}
        });
      }
    }

    // Int16 export helper (for DEM). Same caller contract as doExport.
    function doExportInt16(image, description, folder) {
      if (useCloud) {
        Export.image.toCloudStorage({
          image: image.toInt16(),
          description: description,
          bucket: gcsBucket.trim(),
          fileNamePrefix: folder + '/' + description,
          region: exportRegion,
          scale: exportScale,
          crs: targetCRS,
          maxPixels: 1e13,
          fileFormat: 'GeoTIFF',
          formatOptions: {cloudOptimized: true}
        });
      } else {
        Export.image.toDrive({
          image: image.toInt16(),
          description: description,
          folder: folder,
          region: exportRegion,
          scale: exportScale,
          crs: targetCRS,
          maxPixels: 1e13,
          fileFormat: 'GeoTIFF',
          formatOptions: {cloudOptimized: true}
        });
      }
    }

    // Vector export helper. Same caller contract as doExport.
    // Optional `geometryTypes` arg lets callers export non-polygon
    // collections (e.g. OSM roads as LineStrings); defaults to polygons
    // for backwards compatibility with existing callers (WDPA, AOI, etc.).
    function doExportTable(collection, description, folder, geometryTypes) {
      var desc = description;
      geometryTypes = geometryTypes || ['Polygon', 'MultiPolygon'];
      // SHP requires a single geometry type. Some source FCs (WDPA, the
      // simplified/diced GAUL asset used for IDN/THA/DZA/AUS/CHN) carry stray
      // LineString / Point features that trigger GEE Error 3 ("multiple
      // geometry types"). Filter to the requested type(s) before export.
      var filtered = collection.map(function(f) {
        return f.set('_pff_gt', f.geometry().type());
      }).filter(ee.Filter.inList('_pff_gt', geometryTypes))
        .map(function(f) { return f.set('_pff_gt', null); });
      if (useCloud) {
        Export.table.toCloudStorage({
          collection: filtered,
          description: desc,
          bucket: gcsBucket.trim(),
          fileNamePrefix: folder + '/' + description,
          fileFormat: 'SHP'
        });
      } else {
        Export.table.toDrive({
          collection: filtered,
          description: desc,
          folder: folder,
          fileFormat: 'SHP'
        });
      }
    }

    var useSplitScreen = enableSplitScreenCheckbox.getValue();
    var uniqueYears;
    if (useSplitScreen) {
      uniqueYears = (analysisYear1 === analysisYear2) ? [analysisYear1] : [analysisYear1, analysisYear2];
    } else {
      uniqueYears = [analysisYear2];
    }
    var folder = 'PFF_export_' + countryClean;
    var s = exportScale + 'm';  // scale suffix for filenames

    // Country mask + buffer (raster-based, no vector .clip())
    var country_clip = getCountryClip(selectedCountry);
    var country_buffer = makeDistanceBuffer(country_clip, country_buffer_threshold, fastBuffer);
    var country_and_buffer_mask = country_buffer.where(country_clip, 1).selfMask();

    // ═══ Canonical export order (matches QGIS plugin input order) ═══
    // 0 — AOI boundary (vector)
    // 1 — Forest (binary) + raw reference bands (Hansen, GLAD height)
    // 2 — Anthropogenic: roads, builtup_small, builtup_large, agriculture
    // 3 — Protection: legal (WDPA raster + vector), natural (DEM, slope)
    // 4 — Pre-connectivity forest (combined tiers before density filter)
    // 5 — Primary forest (final output)
    // ══════════════════════════════════════════════════════
    //  0 — AOI & reference layers
    // ══════════════════════════════════════════════════════
    if (exportChk_aoi.getValue()) {
      // Big countries (IDN, THA, CHN, AUS, DZA) come from the dice10k
      // simplified GAUL asset which splits each country into many
      // chunks. Exporting `country_sel` directly produces a shapefile
      // with one feature per chunk → visible dice seams. Wrap as a
      // single-feature collection whose geometry is the union of all
      // chunks (FeatureCollection.geometry() already returns that
      // union). Result: one clean multipolygon per country in the
      // exported AOI vector.
      var aoi_one_feature = ee.FeatureCollection([
        ee.Feature(country_sel.geometry(), {gaul0_name: selectedCountry})
      ]);
      doExportTable(aoi_one_feature, mkExportName('00a', 'aoi_' + countryClean + '_vector'), folder);
    }

    // ══════════════════════════════════════════════════════
    //  1 — Tree cover / forest (static raw + per-year thresholded)
    // ══════════════════════════════════════════════════════

    // Hansen raw bands (export once — for re-thresholding in QGIS)
    if (exportChk_hansenRaw.getValue()) {
      var gfc = ee.Image('UMD/hansen/global_forest_change_2024_v1_12');
      doExport(gfc.select('treecover2000').updateMask(country_and_buffer_mask).unmask(0),
        mkExportName('02a', 'hansen_treecover2000_raw_' + s), folder);
      doExport(gfc.select('lossyear').updateMask(country_and_buffer_mask).unmask(0),
        mkExportName('02a', 'hansen_lossyear_raw_' + s), folder);
    }

    // ══════════════════════════════════════════════════════
    //  3 — Protection: legal (WDPA) + natural (DEM for slope)
    // ══════════════════════════════════════════════════════

    // 3a — Legal protection (WDPA filtered raster + unfiltered vector)
    var wdpaYearCutoff = current_year - years_protected;
    var wdpa_filt_by_date_image = wdpaStatusYearGlobal.lte(wdpaYearCutoff);
    if (selected_iucn_categories.length > 0 && selected_iucn_categories.length < 10) {
      var combinedCategoryMask = ee.Image(0);
      for (var i = 0; i < selected_iucn_categories.length; i++) {
        combinedCategoryMask = combinedCategoryMask.or(wdpaCategoryMasks[selected_iucn_categories[i]]);
      }
      wdpa_filt_by_date_image = wdpa_filt_by_date_image.updateMask(combinedCategoryMask);
    }
    var wdpa_raster = wdpa_filt_by_date_image.selfMask()
      .updateMask(country_and_buffer_mask).unmask(0).toByte().rename('protected');
    if (exportChk_protLegal.getValue()) {
      doExport(wdpa_raster, mkExportName('03b', 'protection_legal_' + s), folder);
    }

    if (exportChk_protVector.getValue()) {
      var wdpa_raw = ee.FeatureCollection("WCMC/WDPA/current/polygons").filter(
        ee.Filter.and(ee.Filter.neq('STATUS', 'Proposed'),
                      ee.Filter.neq('STATUS', 'Not Reported'))
      ).filterBounds(exportRegion);
      doExportTable(wdpa_raw, mkExportName('03b', 'protection_legal_unfiltered_vector'), folder);
    }

    // 3b — Natural protection (DEM for slope computation in QGIS)
    var alos_30m_elev = ee.ImageCollection('JAXA/ALOS/AW3D30/V3_2').select('DSM').mosaic();
    if (exportChk_dem.getValue()) {
      doExportInt16(alos_30m_elev.updateMask(country_and_buffer_mask).unmask(0),
        mkExportName('03b', 'protection_natural_dem_' + s), folder);
    }

    // 3c — Slope (optional — computed from DEM)
    if (exportChk_slope.getValue()) {
      var slopeImage = ee.Terrain.slope(alos_30m_elev.setDefaultProjection('EPSG:4326', null, 30));
      doExport(slopeImage.updateMask(country_and_buffer_mask).unmask(0).toByte(),
        mkExportName('03b', 'protection_natural_slope_' + s), folder);
    }

    // ══════════════════════════════════════════════════════
    //  PER-YEAR layers
    // ══════════════════════════════════════════════════════

    var treecoverPercentThreshold = treecoverThresholdSlider.getValue();
    var treecoverHeightThreshold = treecoverHeightThresholdSlider.getValue();
    var useHansenTreecover = (treecoverSourceSelect.getValue() === 'Hansen GFC');
    var useGladLulcForest = (treecoverSourceSelect.getValue() === 'GLAD LULC');
    var useAgreementForest = (treecoverSourceSelect.getValue() === 'Agreement (Hansen & GLAD)');
    var useUnionForest = (treecoverSourceSelect.getValue() === 'Combined extent (Hansen | GLAD)');
    var timeseriesAnthroModule = require("users/andyarnellgee/apps:modules/timeseriesAnthro.js");

    uniqueYears.forEach(function(analysisYear) {

      // ── 1 — Forest (as configured in the app) ──
      // P1.23: forest_map is always derived from the Source dropdown;
      // a custom forest layer (nationalForest) is then merged in via
      // its mode (Replace global / Add to global extent / Agreement
      // with global). See applyCustomForestMerge() below.
      var forest_map;
      if (useAgreementForest) {
        forest_map = agreementForestPrep(analysisYear, treecoverPercentThreshold, treecoverHeightThreshold);
      } else if (useUnionForest) {
        forest_map = unionForestPrep(analysisYear, treecoverPercentThreshold, treecoverHeightThreshold);
      } else if (useGladLulcForest) {
        forest_map = gladLulcForestPrep(analysisYear, treecoverHeightThreshold);
      } else if (useHansenTreecover) {
        forest_map = gfcHansenTreecoverPrep(analysisYear, treecoverPercentThreshold);
      }
      forest_map = applyCustomForestMerge(forest_map, analysisYear);
      if (!forest_map) {
        exportRasterStatusLabel.setValue('No forest data selected.');
        return;
      }
      // 02a / 02c forest exports moved BELOW the OLTC computation so the
      // FRA-narrowed Forest baseline (02c) can subtract OLTC -- matches
      // the FRA-Forest definition (Tree cover - OLTC). The pre-OLTC raw
      // thresholded version is exposed separately as 02a_forest_raw for
      // users who want the broader tree cover layer (or want to apply
      // their own national OLTC narrowing locally). See the export block
      // after `var olwtc = ...` below.

      // GLAD raw tree height (so user can re-threshold at any height in QGIS)
      if (exportChk_gladHeight.getValue()) {
        var gladLandcoverLand = ee.Image('projects/glad/GLCLU2020/v2/LCLUC_' + analysisYear)
          .updateMask(ee.Image("projects/glad/OceanMask").lte(1));
        var fromValues = [
          25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48,
          125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147
        ];
        var toValues = [
          3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26,
          3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25
        ];
        var gladTreeHeight = gladLandcoverLand.remap(fromValues, toValues)
          .updateMask(country_and_buffer_mask).unmask(0).toByte()
          .rename('tree_height_m');
        doExport(gladTreeHeight, mkExportName('02a', 'glad_tree_height_m_' + analysisYear + '_' + s), folder);
      }

      // ── 2 — Anthropogenic: roads, built-up (small + large), agriculture ──
      var roadsMosaicStatic = timeseriesAnthroModule.roadsMosaicStatic().updateMask(country_and_buffer_mask);
      if (exportChk_roads.getValue()) {
        doExport(roadsMosaicStatic.unmask(0), mkExportName('03a', 'roads_' + analysisYear + '_' + s), folder);
      }

      // OSM roads vector (global merge of 33 regional uploads). Clipped
      // to country + buffer (the SAME polygon used for the raster
      // country_and_buffer_mask), not just exportRegion which is the
      // looser bounding box. LineString geometry — pass geometryTypes
      // to doExportTable so it doesn't filter to polygons by default.
      // P1.30 batch 24.1: pass the AOI INTO getOsmRoadsAll so it
      // applies filterBounds per-asset BEFORE the flatten (WDPA-style
      // fast-path). Was a chained .filterBounds() AFTER flatten which
      // defeated per-child spatial-index pushdown across 33 children.
      if (exportChk_roadsOsmVector.getValue()) {
        var country_and_buffer_geom = country_geom.buffer(
          country_buffer_threshold + 1000);
        var roadsOsmAoi = timeseriesAnthroModule.getOsmRoadsAll(
          country_and_buffer_geom);
        doExportTable(
          roadsOsmAoi,
          mkExportName('03a', 'roads_osm_vector'),
          folder,
          ['LineString', 'MultiLineString']);
      }

      // Built-up small
      var builtUpSmall = ee.Image(0);
      var builtUpLargeImg = ee.Image(0);
      if (includeWSF) {
        var wsfCollection = timeseriesAnthroModule.getWSFCollection();
        builtUpSmall = builtUpSmall.or(wsfCollection.filter(ee.Filter.eq('year', analysisYear)).first().eq(1)).updateMask(country_and_buffer_mask);
      }
      if (includeGHSL) {
        var ghslCollection = timeseriesAnthroModule.getGhslCollection();
        var ghslSel = ghslCollection.filter(ee.Filter.eq('year', analysisYear)).first().updateMask(country_and_buffer_mask);
        builtUpSmall = builtUpSmall.or(ghslSel.eq(1));
        builtUpLargeImg = ghslSel.eq(2);
      }
      if (includeGISD) {
        var gisdCollection = timeseriesAnthroModule.getGISDCollection();
        builtUpSmall = builtUpSmall.or(gisdCollection.filter(ee.Filter.eq('year', analysisYear)).first().eq(1)).updateMask(country_and_buffer_mask);
      }
      if (includeGISA) {
        var gisaCollection = timeseriesAnthroModule.getGISACollection();
        builtUpSmall = builtUpSmall.or(gisaCollection.filter(ee.Filter.eq('year', analysisYear)).first().eq(1)).updateMask(country_and_buffer_mask);
      }
      if (exportChk_builtupSmall.getValue()) {
        doExport(builtUpSmall.updateMask(country_and_buffer_mask).unmask(0),
          mkExportName('03a', 'builtup_small_' + analysisYear + '_' + s), folder);
      }
      if (exportChk_builtupLarge.getValue()) {
        doExport(builtUpLargeImg.updateMask(country_and_buffer_mask).unmask(0),
          mkExportName('03a', 'builtup_large_' + analysisYear + '_' + s), folder);
      }

      // Agriculture
      var glcFcs30dCollection = timeseriesAnthroModule.preprocessGlc();
      var landcover = glcFcs30dCollection.filter(ee.Filter.eq("year", analysisYear)).first().updateMask(country_and_buffer_mask);
      var pastureDataset = ee.ImageCollection("projects/global-pasture-watch/assets/ggc-30m/v1/grassland_c");
      var pastureDatasetCultivated = pastureDataset.map(function(image){return image.eq(1).set('year',ee.Number.parse(image.get("system:index")))});
      var pastureDatasetFF = forwardFillBinaryTimeSeries(pastureDatasetCultivated, years.filter(function(year) {return year >= 2000}));
      var pastureDatasetSel = pastureDatasetFF.filter(ee.Filter.eq("year", analysisYear)).first().updateMask(country_and_buffer_mask);
      var oilPalmDescalsCollection = timeseriesAnthroModule.processingOilPalmDescals();
      var oilPalmDescalsSel = ee.Image(oilPalmDescalsCollection.filter(ee.Filter.eq("year", analysisYear)).first()).updateMask(country_and_buffer_mask);
      // P1.20: Plantations layer = SDPT class 1 only (FRA Planted Forest --
      // timber/pulp/fibre plantations like eucalyptus, pine, teak). SDPT
      // class 2 (tree crops -- rubber, fruit, agroforestry) and Descals
      // oil palm now route through the agriculture aggregation instead,
      // per FRA: those are agricultural land regardless of tree biology.
      // Net 04a_primary_forest pixels unchanged (everything is still in
      // the disturbance bucket), but 02d_planted_forest export and the
      // 02e_naturally_regenerating_forest derivation are now FRA-faithful.
      var plantedForestSDPT = timeseriesAnthroModule.processingPlantedForestSDPT()
          .updateMask(country_and_buffer_mask);
      var treeCropsSDPT = timeseriesAnthroModule.processingTreeCropsSDPT()
          .updateMask(country_and_buffer_mask);
      var allPlantationsSel = plantedForestSDPT;

      // P1.30 batch 25 -- OLWTC bucket per FRA Note 10 = "non-Forest
      // land with tree cover". Includes: oil palm + SDPT class 2 tree
      // crops + URBAN TREE COVER (tree-covered pixels inside built-up,
      // small or large). The urban-tree-cover sub-bucket is the
      // intersection of built-up with the chosen tree-cover source --
      // so each pixel claimed as OLWTC genuinely has tree cover (no
      // bare-rooftop overshoot). Built-up takes precedence over
      // Forest: a tree inside a city is "urban tree", not Forest.
      // Used in: 02b_other_land_with_tree_cover export below.
      var _treeCoverForOlwtc = forest_map.updateMask(country_and_buffer_mask);
      var urbanTreeCover = builtUpSmall.unmask(0)
          .or(builtUpLargeImg.unmask(0))
          .and(_treeCoverForOlwtc.unmask(0));
      var olwtc = oilPalmDescalsSel.unmask(0)
          .or(treeCropsSDPT.unmask(0))
          .or(urbanTreeCover);

      // ── Forest-baseline exports (02a raw / 02c FRA-aligned) ──
      // 02c_forest = FRA-Forest = Tree cover MINUS OLTC. Honours the
      // existing "Refine to forest" toggle (excludeAgricultureFromForest
      // Checkbox) so the export semantics match the analysis pipeline.
      // When the toggle is off, 02c falls back to raw thresholded tree
      // cover (same as 02a_forest_raw) and the export-status label
      // surfaces the fallback so the user knows the file isn't
      // FRA-narrowed in this mode.
      var _refineToForestActive = exclusionActive(
        excludeAgricultureFromForestCheckbox, excludeAgriPanel);
      var forest_map_fra = _refineToForestActive
        ? forest_map.updateMask(olwtc.not())
        : forest_map;
      if (exportChk_inputForest.getValue()) {
        doExport(forest_map_fra.updateMask(country_and_buffer_mask).unmask(0),
          mkExportName('02c', 'forest_' + analysisYear + '_' + s), folder);
        if (!_refineToForestActive) {
          exportRasterStatusLabel.setValue(
            'Note: 02c_forest exported WITHOUT OLTC narrowing because ' +
            '"Refine to forest" toggle is off. Content equals raw ' +
            'thresholded tree cover (same as 02a_forest_raw).');
        }
      }
      if (exportChk_forestRaw.getValue()) {
        // 02a_forest_raw = thresholded tree cover BEFORE OLTC narrowing.
        // Always available; useful when user wants to apply their own
        // OLTC narrowing locally with a national OLTC dataset different
        // from the global one.
        doExport(forest_map.updateMask(country_and_buffer_mask).unmask(0),
          mkExportName('02a', 'forest_raw_' + analysisYear + '_' + s), folder);
      }

      if (exportChk_plantations.getValue()) {
        // 02d_planted_forest export = FRA Planted Forest only (SDPT class 1).
        // Plugin mirrors this when consumed -- "exclude planted forest" =
        // exclude FRA Planted Forest (timber, pulp, fibre).
        // RUBBER CAVEAT: SDPT v2 puts rubber in class 2 (tree crops), so
        // rubber is NOT in this layer. Per FRA Note 7, rubber-wood
        // plantations ARE forest -- supply national rubber via
        // nationalPlantations override to add it.
        doExport(allPlantationsSel.unmask(0).toByte(),
          mkExportName('02d', 'planted_forest_' + analysisYear + '_' + s), folder);
      }
      // 02e_naturally_regenerating_forest export.
      // P1.23a: respect the panel-level declaration. If the user has
      // declared the input is already at NRF or Primary level, the input
      // IS the NRF -- don't subtract plantations again (would be a no-op
      // at best, double-subtraction at worst). Otherwise (declaration =
      // Tree cover or Forest), derive NRF as Forest minus Planted Forest,
      // matching the analysis-side forest_natreg_image construction.
      if (exportChk_naturallyRegenerating.getValue()) {
        // Batch 28: chain NRF off the FRA-narrowed Forest baseline
        // (forest_map_fra) instead of raw forest_map. Matches the FRA
        // hierarchy: Tree cover -> Forest (-OLTC) -> NRF (-Planted).
        // When "Refine to forest" toggle is off, forest_map_fra ==
        // forest_map so behaviour is identical to pre-Batch-28.
        var declCat = inputCategorySelect.getValue();
        var inputIsAtOrPastNRF = (declCat === INPUT_CATEGORY_NATREG ||
                                  declCat === INPUT_CATEGORY_PRIMARY);
        var natRegBase = inputIsAtOrPastNRF
          ? forest_map_fra  // input already excludes planted forest per declaration
          : forest_map_fra.updateMask(allPlantationsSel.unmask().not());
        var natRegExport = natRegBase
          .updateMask(country_and_buffer_mask)
          .unmask(0);
        doExport(natRegExport,
          mkExportName('02e', 'naturally_regenerating_forest_' + analysisYear + '_' + s), folder);
      }
      // P1.22 (was P1.18 export): "Plantations" (agricultural tree crops)
      // = Descals oil palm + SDPT class 2. Per FRA Note 10 these are
      // agricultural land regardless of tree biology -- e.g. oil palm,
      // fruit orchards, olive orchards, agroforestry-with-crops. The
      // everyday word "plantation" actually fits these crops better than
      // forestry timber plantations (which we now call "Planted forest").
      // Distinct from the broader 03a_agriculture (cropland + pasture +
      // everything for primary-forest disturbance buffering). Plugin
      // users can consume this layer to apply the FRA-strict Forest
      // baseline derivation when running standalone. Default off -- only
      // export when explicitly requested.
      // RUBBER CAVEAT: SDPT v2 puts rubber in class 2 so it lands here,
      // but per FRA Note 7 rubber-wood is forest. Workshop users should
      // be aware. National rubber data via nationalPlantations override
      // can correct this in the analysis pipeline.
      if (exportChk_fraAgriculture.getValue()) {
        // Batch 25: OLWTC export now includes urban tree cover (tree-
        // covered pixels in built-up small + large) per FRA Note 10.
        var fraAgriExport = olwtc
          .updateMask(country_and_buffer_mask)
          .unmask(0)
          .toByte();
        doExport(fraAgriExport,
          mkExportName('02b', 'other_land_with_tree_cover_' + analysisYear + '_' + s), folder);
      }
      var croplandGladCollection = timeseriesAnthroModule.processingCroplandsGlad();
      var croplandGladCollectionFF = forwardFillBinaryTimeSeries(croplandGladCollection, years);
      var croplandGladSel = ee.Image(croplandGladCollectionFF.filter(ee.Filter.eq("year", analysisYear)).first()).updateMask(country_and_buffer_mask);
      // P1.20: agriculture aggregation now explicitly includes the
      // tree-cover-meeting agricultural sources (tree crops + oil palm)
      // since allPlantationsSel no longer carries them. Plus planted
      // forest stays in the buffering bucket -- for primary-forest
      // disturbance purposes large managed plantations DO disturb
      // adjacent natural forest (logging access, edge effects), even
      // though FRA classifies them as forest.
      var agriculture = pastureDatasetSel
                          .or(plantedForestSDPT.unmask())   // SDPT class 1 -- buffered for primary
                          .or(treeCropsSDPT.unmask())       // SDPT class 2 -- FRA agriculture
                          .or(oilPalmDescalsSel.unmask())   // Descals oil palm -- FRA agriculture
                          .or(croplandGladSel);             // GLAD croplands
      if (exportChk_agriculture.getValue()) {
        doExport(agriculture.unmask(0), mkExportName('03a', 'agriculture_' + analysisYear + '_' + s), folder);
      }

      // ── 4 — Pre-connectivity Forest & Primary Forest (from analysis cache) ──
      if (exportChk_preConnectivity.getValue() && latestPreConnectivityForest[analysisYear]) {
        doExport(latestPreConnectivityForest[analysisYear].unmask(0),
          mkExportName('03c', 'pre_refinement_primary_forest_' + analysisYear + '_' + s), folder);
      }
      if (exportChk_final.getValue() && latestMaskedPrimaryForest[analysisYear]) {
        doExport(latestMaskedPrimaryForest[analysisYear].unmask(0),
          mkExportName('04a', 'primary_forest_' + analysisYear + '_' + s), folder);
      }
    });

    // Per-run metadata sidecar (one bundle per analysis year so two-year
    // comparisons get distinct files reflecting the year_exported field).
    // Exported as GeoJSON because Export.table only emits geo formats and
    // CSV/SHP would lose the structure -- GeoJSON parses cleanly back to a
    // flat dict downstream. P1.13 filename:
    //   <ISO3>_gee_run_metadata_<year>_<scale>m.geojson
    // (No top-level step number -- contextual sidecar, not a per-stage layer.)
    if (exportChk_runMetadata.getValue()) {
      uniqueYears.forEach(function(metaYear) {
        var bundle = buildRunBundle(metaYear, exportScale, iso3, folder, useCloud);
        var bundleFC = ee.FeatureCollection([ee.Feature(null, bundle)]);
        var bundlePrefix = (iso3 ? iso3 + '_' : '') +
          'gee_run_metadata_' + metaYear + '_' + s + 'm';
        var bundleDesc = bundlePrefix + runTag;
        if (useCloud) {
          Export.table.toCloudStorage({
            collection: bundleFC,
            description: bundleDesc,
            bucket: gcsBucket.trim(),
            fileNamePrefix: folder + '/' + bundlePrefix,
            fileFormat: 'GeoJSON'
          });
        } else {
          Export.table.toDrive({
            collection: bundleFC,
            description: bundleDesc,
            folder: folder,
            fileNamePrefix: bundlePrefix,
            fileFormat: 'GeoJSON'
          });
        }
      });
    }

    var yearStr = uniqueYears.join(' & ');
    var destStr = useCloud ? 'gs://' + gcsBucket.trim() + '/' + folder : 'Google Drive → ' + folder;
    var missingAnalysis = uniqueYears.filter(function(y) {
      return !latestMaskedPrimaryForest[y];
    });
    var note = '';
    if (missingAnalysis.length > 0) {
      note = ' NOTE: Run analysis first for year(s) ' + missingAnalysis.join(', ') +
        ' to include Primary & Pre-connectivity Forest exports.';
    }
    exportRasterStatusLabel.setValue(
      'Export tasks queued for ' + countryClean + ' (' + yearStr + ') → ' + destStr +
      '. Check the Tasks tab to run them. [pff v' + PFF_SCRIPT_VERSION + ']' + note);
  }

  var exportRastersButton = ui.Button({
    label: 'Save to Drive',
    style: {margin: '4px 0 4px 0', fontWeight: 'bold', fontSize: '12px',
            backgroundColor: '#d4edda', border: '2px solid #82c785'},
    onClick: exportRastersToDrive
  });

  var driveResolutionRow = ui.Panel(
    [ui.Label('Resolution (m):', {margin: '0 8px 0 0', fontSize: '11px'}), exportRasterScaleSlider],
    ui.Panel.Layout.flow('horizontal'), {stretch: 'horizontal'});

  var driveOptionsContent = ui.Panel({
    widgets: [
      exportToCloudCheckbox,
      ui.Panel([ui.Label('GCS Bucket:', {margin: '0 8px 0 0', fontSize: '11px'}), gcsBucketInput],
        ui.Panel.Layout.flow('horizontal'))
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, margin: '0 0 0 4px'}
  });
  var driveOptionsToggle = ui.Button({
    label: '▸ Advanced',
    onClick: function() {
      var s = driveOptionsContent.style().get('shown');
      driveOptionsContent.style().set({shown: !s});
      driveOptionsToggle.setLabel(s ? '▸ Advanced' : '▾ Advanced');
    },
    style: {fontSize: '11px', color: '#555', margin: '2px 0', padding: '2px 6px', backgroundColor: '#ffffff'}
  });

  var exportRastersPanel = ui.Panel({
    widgets: [
      exportSelectPanel,
      driveResolutionRow,
      exportRastersButton,
      exportRasterStatusLabel,
      driveOptionsToggle,
      driveOptionsContent
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {margin: '0', stretch: 'horizontal'}
  });

  // ──────────────────────────────────────────────
  // Download Layer (via getDownloadURL — works in App & Script)
  // ──────────────────────────────────────────────
  var dlModule = require('users/andyarnellgee/apps:modules/downloadViaUrl.js');

  var downloadLayerSelect = ui.Select({
    items: [
      'Primary forest',
      'Forest',
      'Naturally regenerating forest',
      'Pre-refinement primary forest',
      'Tree cover (raw input)',
    ],
    placeholder: '— Select dataset to save —',
    style: {margin: '0 0 4px 0', stretch: 'horizontal'}
  });
  var downloadScaleSlider = ui.Slider({
    min: 30, max: 1000, value: 90, step: 10,
    style: {margin: '0 0 6px 0', stretch: 'horizontal'},
    onChange: function(val) { downloadScaleInput.setValue(val.toString(), false); }
  });
  var downloadScaleInput = ui.Textbox({
    value: '90',
    style: {width: '55px', fontSize: '11px', margin: '0 0 0 4px'},
    onChange: function(val) {
      var n = parseInt(val);
      if (!isNaN(n) && n >= 30 && n <= 1000) {
        downloadScaleSlider.setValue(n, false);
      }
    }
  });
  // Custom AOI for downloads (drawn polygon overrides country boundary)
  var userDrawnAoi = null;

  var drawAoiStatusLabel = ui.Label('', {fontSize: '10px', color: '#666', margin: '0 0 4px 0'});

  var useCustomAoiCheckbox = ui.Checkbox({
    label: 'Use custom AOI (draw on map)',
    value: false,
    style: {margin: '0 0 4px 0', fontSize: '12px'},
    onChange: function(checked) {
      var activeMap = map2 || map1;
      if (checked) {
        // Activate drawing
        if (!activeMap) {
          drawAoiStatusLabel.setValue('No map available yet.');
          useCustomAoiCheckbox.setValue(false, false);
          return;
        }
        var dt = activeMap.drawingTools();
        dt.layers().reset();
        dt.setShown(true);
        dt.setShape('polygon');
        dt.draw();
        drawAoiStatusLabel.setValue('Draw a polygon on the map. Double-click last vertex to finish.');
        dt.onDraw(function(geom) {
          if (geom) {
            userDrawnAoi = geom;
            drawAoiStatusLabel.setValue('\u2714 Custom AOI set. Grid & tiles will use this area.');
            drawAoiStatusLabel.style().set('color', '#2a7f2a');
          }
          dt.stop();
        });
      } else {
        // Clear everything
        userDrawnAoi = null;
        drawAoiStatusLabel.setValue('');
        drawAoiStatusLabel.style().set('color', '#666');
        if (activeMap) {
          var dt = activeMap.drawingTools();
          dt.stop();
          dt.layers().reset();
          dt.setShown(false);
        }
      }
    }
  });

  // Result of "Check tile count" -- shown directly under the button so the
  // estimate appears where the user clicked (not in the far-down status
  // label). Set by the button's onClick.
  var downloadTileEstimateLabel = ui.Label('', {fontSize: '11px', margin: '2px 0 4px 0', color: '#333'});

  var downloadAutoGridButton = ui.Button({
    label: 'Check tile count',
    style: {width: '120px', fontSize: '11px', margin: '0 0 2px 0'},
    onClick: function() {
      var selectedCountry = countrySelector.getValue();
      if (!selectedCountry) {
        downloadTileEstimateLabel.style().set('color', 'red');
        downloadTileEstimateLabel.setValue('Please select a country first.');
        return;
      }
      var country_sel = getCountryFeatures(selectedCountry);
      var dlRegion = userDrawnAoi || country_sel.geometry();
      var dlScale = downloadScaleSlider.getValue();
      downloadTileEstimateLabel.style().set('color', '#888');
      downloadTileEstimateLabel.setValue('Calculating…');
      downloadAutoGridButton.setLabel('Working…');

      // Defer the blocking bounds.getInfo() one tick so "Working…" /
      // "Calculating…" paints before the GUI thread blocks (same fix as
      // the Save-to-computer button).
      ui.util.setTimeout(function() {
        var grid = dlModule.autoGrid(dlRegion, dlScale);

        // Safety: ensure each tile fits within GEE's 32768px hard limit
        var MAX_PX = 30000;
        var bounds = dlRegion.bounds();
        var coords = bounds.coordinates().get(0).getInfo();
        if (coords) {
          var lons = coords.map(function(c) { return c[0]; });
          var lats = coords.map(function(c) { return c[1]; });
          var lonSpan = Math.max.apply(null, lons) - Math.min.apply(null, lons);
          var latSpan = Math.max.apply(null, lats) - Math.min.apply(null, lats);
          var metersPerDeg = 111320;
          var widthPx = (lonSpan * metersPerDeg / dlScale) / grid.cols;
          var heightPx = (latSpan * metersPerDeg / dlScale) / grid.rows;
          while (widthPx > MAX_PX) { grid.cols += 1; widthPx = (lonSpan * metersPerDeg / dlScale) / grid.cols; }
          while (heightPx > MAX_PX) { grid.rows += 1; heightPx = (latSpan * metersPerDeg / dlScale) / grid.rows; }
        }

        downloadAutoGridButton.setLabel('Check tile count');
        if (!grid.feasible) {
          downloadTileEstimateLabel.style().set('color', 'red');
          downloadTileEstimateLabel.setValue(grid.message);
        } else {
          downloadTileEstimateLabel.style().set('color', '#333');
          var result = dlModule.makeTiles(dlRegion, grid.rows, grid.cols);
          var msg = grid.rows + '×' + grid.cols;
          if (grid.rows === 1 && grid.cols === 1) {
            msg = 'Single file (area fits in one tile)';
          } else if (result.skipped > 0) {
            msg += ' → ' + result.tiles.length + ' tiles overlap boundary' +
              ' (skipped ' + result.skipped + ' empty)';
          } else {
            msg += ' = ' + result.tiles.length + ' tiles';
          }
          if (grid.rows > 1 || grid.cols > 1) {
            msg += ' [~' + Math.round(grid.tileAreaKm2) + ' km² each]';
          }
          downloadTileEstimateLabel.setValue(msg);
        }
      }, 0);
    }
  });
  var downloadTileGridPanel = ui.Panel({
    widgets: [
      downloadAutoGridButton,
      ui.Label(
        'Previews the number of download links/tiles that would be ' +
        'created for the AOI extent at the chosen resolution.',
        {fontSize: '10px', color: '#888', fontStyle: 'italic', margin: '0 0 2px 0'}),
      downloadTileEstimateLabel
    ],
    layout: ui.Panel.Layout.flow('vertical')
  });
  var downloadStatusLabel = ui.Label('', {margin: '4px 0 0 8px', width: '280px', fontSize: '11px'});
  var downloadLinksPanel = ui.Panel({
    layout: ui.Panel.Layout.flow('vertical'),
    style: {margin: '4px 0 0 8px', width: '280px'}
  });
  var downloadItems = [];  // collect {name, url} for script
  var downloadFolder = '';  // folder name for script (includes country)

  // Link threshold: if total download links exceed this, auto-generate
  // a Python script instead of showing individual links.
  var DOWNLOAD_LINK_THRESHOLD = 10;

  function downloadLayer() {
    downloadStatusLabel.setValue('');
    downloadLinksPanel.clear();
    psScriptPanel.clear();
    psScriptPanel.style().set('shown', false);

    // Show warning + tip now that user clicked
    downloadWarningLabel.style().set({shown: true});
    if (!IS_PUBLISHED_APP) driveTipLabel.style().set({shown: true});

    var selectedCountry = countrySelector.getValue();
    if (!selectedCountry) {
      downloadStatusLabel.setValue('Please select a country first.');
      downloadWarningLabel.style().set({shown: false});
      driveTipLabel.style().set({shown: false});
      return;
    }

    var layerChoice = downloadLayerSelect.getValue();
    if (!layerChoice) {
      downloadStatusLabel.setValue('Please select a dataset first.');
      downloadWarningLabel.style().set({shown: false});
      driveTipLabel.style().set({shown: false});
      return;
    }

    var sourceDict;
    var nameBase;
    if (layerChoice === 'Forest') {
      sourceDict = latestMaskedForest;
      nameBase = '02c_forest';
    } else if (layerChoice === 'Naturally regenerating forest') {
      sourceDict = latestMaskedForest;
      nameBase = '02e_naturally_regenerating_forest';
    } else if (layerChoice === 'Pre-refinement primary forest') {
      sourceDict = latestPreConnectivityForest;
      nameBase = '03c_pre_refinement_primary_forest';
    } else if (layerChoice === 'Tree cover (raw input)') {
      sourceDict = latestMaskedForest;
      nameBase = '02a_treecover';
    } else {
      sourceDict = latestMaskedPrimaryForest;
      nameBase = '04a_primary_forest';
    }

    var years = Object.keys(sourceDict);
    if (years.length === 0) {
      downloadStatusLabel.setValue('No data for ' + layerChoice + '. Run the analysis first.');
      return;
    }

    // Primary forest caveat
    if (layerChoice === 'Primary forest') {
      downloadLinksPanel.add(ui.Label(
        '⚠ Primary forest is computed on-the-fly and may fail for large ' +
        'areas due to processing limits.',
        {fontSize: '10px', color: '#856404', margin: '0 0 4px 0',
         backgroundColor: '#fff3cd', padding: '4px', border: '1px solid #ffc107'}));
    }

    var selectedCountry = countrySelector.getValue();
    var countryClean = cleanCountryName(selectedCountry);
    var country_sel = getCountryFeatures(selectedCountry);
    var region = country_sel.geometry();
    var dlScale = downloadScaleSlider.getValue();

    var now = new Date();
    var pad = function(n) { return n < 10 ? '0' + n : n; };
    // ISO-8601 basic UTC: pff_<country>_YYYYMMDDTHHMMZ. Sortable +
    // unambiguous + no FS-invalid characters.
    downloadFolder = 'pff_' + countryClean + '_' +
      now.getUTCFullYear() + pad(now.getUTCMonth()+1) + pad(now.getUTCDate()) +
      'T' + pad(now.getUTCHours()) + pad(now.getUTCMinutes()) + 'Z';

    downloadStatusLabel.setValue('Calculating tiles…');
    downloadStatusLabel.style().set('color', '#888');
    downloadButton.setLabel('Working…');

    // Defer the heavy/blocking work (autoGrid + bounds.getInfo() + tiling)
    // one tick so the "Calculating tiles…" message paints BEFORE the GUI
    // thread blocks -- otherwise the click looks like it just hangs.
    ui.util.setTimeout(function() {

    var dlRegion = userDrawnAoi || region;
    var yearsArr = Object.keys(sourceDict);

    var grid = dlModule.autoGrid(dlRegion, dlScale);

    var MAX_PX = 30000;
    var bounds = dlRegion.bounds();
    var coords = bounds.coordinates().get(0).getInfo();
    if (coords) {
      var lons = coords.map(function(c) { return c[0]; });
      var lats = coords.map(function(c) { return c[1]; });
      var lonSpan = Math.max.apply(null, lons) - Math.min.apply(null, lons);
      var latSpan = Math.max.apply(null, lats) - Math.min.apply(null, lats);
      var metersPerDeg = 111320;
      var widthPx = (lonSpan * metersPerDeg / dlScale) / grid.cols;
      var heightPx = (latSpan * metersPerDeg / dlScale) / grid.rows;
      while (widthPx > MAX_PX) { grid.cols += 1; widthPx = (lonSpan * metersPerDeg / dlScale) / grid.cols; }
      while (heightPx > MAX_PX) { grid.rows += 1; heightPx = (latSpan * metersPerDeg / dlScale) / grid.rows; }
    }
    var tileRows = grid.rows;
    var tileCols = grid.cols;

    if (!grid.feasible) {
      downloadButton.setLabel('Save to computer');
      downloadStatusLabel.setValue(grid.message);
      downloadStatusLabel.style().set('color', 'red');
      return;
    }

    var tileResult = dlModule.makeTiles(dlRegion, tileRows, tileCols);
    var useTiled = (tileRows > 1 || tileCols > 1);
    var expectedLinks = yearsArr.length * tileResult.tiles.length;

    // Decide: show links inline or auto-generate Python script
    var threshold = DOWNLOAD_LINK_THRESHOLD;
    var useScriptMode = (expectedLinks > threshold);

    if (useScriptMode) {
      downloadStatusLabel.setValue(
        expectedLinks + ' download links required. Generating Python script…');
    } else if (tileResult.skipped > 0) {
      downloadStatusLabel.setValue(
        tileRows + '×' + tileCols + ' grid → ' + tileResult.tiles.length +
        ' tiles overlap boundary (skipped ' + tileResult.skipped + ' empty)');
    } else if (useTiled) {
      downloadStatusLabel.setValue(
        tileRows + '×' + tileCols + ' = ' + tileResult.tiles.length + ' tiles');
    } else {
      downloadStatusLabel.setValue('Generating download link…');
    }

    var linksReady = 0;
    downloadItems = [];

    function onAllLinksReady() {
      downloadButton.setLabel('Save to computer');
      if (useScriptMode) {
        // Auto-generate Python script
        try {
          var script = dlModule.buildPythonScript(downloadItems, downloadFolder);
          var dataUri = 'data:application/octet-stream;charset=utf-8,' + encodeURIComponent(script);
          psScriptPanel.add(ui.Label({
            value: '⬇ Download Python Script',
            targetUrl: dataUri,
            style: {fontSize: '11px', color: '#1a73e8', fontWeight: 'bold', margin: '4px 0 2px 0'}
          }));
          psScriptPanel.add(ui.Label(
            'Save as .py file (rename extension from .txt to .py) and run:\n' +
            '  python download_tiles.py',
            {fontSize: '10px', margin: '2px 0', whiteSpace: 'pre'}));
          // Mosaic step comes AFTER the run instruction (logical order:
          // run script -> tiles downloaded -> mosaic them).
          if (useTiled) {
            psScriptPanel.add(ui.Label(
              'After downloading, mosaic the .tif tiles in QGIS ' +
              '(Raster > Miscellaneous > Merge) or with gdal_merge.py ' +
              'to produce a single file.',
              {fontSize: '10px', color: '#666', fontStyle: 'italic', margin: '4px 0 0 0'}));
          }
          psScriptPanel.add(ui.Label(
            '⚠ Links expire ~2 hours after generation.',
            {fontSize: '10px', margin: '4px 0 2px 0'}));
          // Optional code preview (Advanced -> Preview Python code).
          if (previewPythonCheckbox.getValue()) {
            psScriptPanel.add(ui.Label('Code preview:', {fontSize: '10px',
              fontWeight: 'bold', color: '#555', margin: '6px 0 2px 0'}));
            psScriptPanel.add(ui.Label(script, {
              fontSize: '10px', whiteSpace: 'pre', margin: '0 0 4px 0',
              border: '1px solid #ccc', padding: '4px'
            }));
          }
          psScriptPanel.style().set('shown', true);
        } catch (e) {
          psScriptPanel.add(ui.Label('Error generating script: ' + e.message,
            {color: 'red', fontSize: '11px'}));
          psScriptPanel.style().set('shown', true);
        }
        downloadStatusLabel.setValue(
          downloadItems.length + ' links collected → Python script ready.');
      } else {
        downloadStatusLabel.setValue(
          linksReady + ' link(s) ready. ⚠ Links expire in ~2 hours — download soon.');
      }

      // Mosaic suggestion for tiled NON-script downloads (script mode adds
      // it to psScriptPanel above, right after the run instruction).
      if (useTiled && !useScriptMode) {
        downloadLinksPanel.add(ui.Label(
          'After downloading, mosaic the .tif tiles in QGIS ' +
          '(Raster > Miscellaneous > Merge) or with gdal_merge.py ' +
          'to produce a single file.',
          {fontSize: '10px', color: '#666', fontStyle: 'italic',
           margin: '4px 0 0 0'}));
      }

      clearDownloadLinksButton.style().set({shown: true});
    }

    function addLink(label, url, fileName) {
      linksReady++;
      downloadItems.push({name: fileName || label.replace(/[^a-zA-Z0-9_\-]/g, '_'), url: url});
      if (!useScriptMode) {
        downloadLinksPanel.add(ui.Label({
          value: '⬇ ' + label,
          style: {color: 'blue', textDecoration: 'underline', fontSize: '12px'},
          targetUrl: url
        }));
      }
      if (linksReady < expectedLinks) {
        downloadStatusLabel.setValue('Generating links… ' + linksReady + '/' + expectedLinks);
      } else {
        onAllLinksReady();
      }
    }
    function addError(msg) {
      downloadLinksPanel.add(ui.Label(msg, {color: 'red', fontSize: '11px'}));
    }

    years.forEach(function(year) {
      var yearInt = parseInt(year);
      var layer = sourceDict[year];
      if (!layer) return;
      var image = layer.unmask(0).toByte();
      var dlName = nameBase + '_' + countryClean + '_' + yearInt + '_' + dlScale + 'm';

      tileResult.tiles.forEach(function(t) {
        image.getDownloadURL({
          name: dlName + (useTiled ? '_' + t.name : ''),
          region: t.geom,
          scale: dlScale,
          crs: 'EPSG:4326',
          maxPixels: 1e9,
          filePerBand: false,
          format: 'GeoTIFF'
        }, function(url, err) {
          if (err) { addError('Error ' + (useTiled ? t.name : yearInt) + ': ' + err); return; }
          var label = useTiled
            ? layerChoice + ' ' + yearInt + ' – ' + t.name + ' (' + dlScale + 'm)'
            : layerChoice + ' ' + yearInt + ' (' + dlScale + 'm)';
          addLink(label, url);
        });
      });
    });
    }, 0);
  }

  var downloadButton = ui.Button({
    label: 'Save to computer',
    style: {margin: '4px 0 4px 0', fontWeight: 'bold', fontSize: '12px',
            backgroundColor: '#d4edda', border: '2px solid #82c785'},
    onClick: downloadLayer
  });

  var psScriptPanel = ui.Panel({layout: ui.Panel.Layout.flow('vertical'), style: {shown: false}});
  // psScriptButton + scriptTypeSelect removed — script generation is
  // now automatic when tile count exceeds DOWNLOAD_LINK_THRESHOLD.

  /*  -- dead code removed (old psScriptButton + scriptTypeSelect) --
      var _x_unused = 'Then either:\n' +
          '  1. Right-click the .ps1 file \u2192 Run with PowerShell (Windows)\n' +
          '  2. Run:  PowerShell -ExecutionPolicy Bypass -File .\\download_tiles.ps1\n' +
          '  3. Or paste the script below directly into a PowerShell window\n\n' +
          '⚠ Links expire ~2 hours after generation. Re-run can reuse links within that window.';
      }
      } catch (e) {
        psScriptPanel.add(ui.Label('Error: update the downloadViaUrl module in GEE Code Editor.', {color: 'red', fontSize: '11px'}));
        psScriptPanel.style().set('shown', true);
        return;
      }
      psScriptPanel.add(ui.Label({
        value: '\u2b07  Download ' + (isPython ? 'Python' : 'PowerShell') + ' Script',
        targetUrl: dataUri,
        style: {fontSize: '11px', color: '#1a73e8', fontWeight: 'bold', margin: '4px 0 2px 0'}
      }));
      psScriptPanel.add(ui.Label(instructions,
        {fontSize: '10px', margin: '2px 0', whiteSpace: 'pre'}));
      psScriptPanel.add(ui.Label(script, {
        fontSize: '10px',
        whiteSpace: 'pre',
        margin: '4px 0',
        border: '1px solid #ccc',
        padding: '4px'
      }));
      psScriptPanel.style().set('shown', true);
    }
  -- end dead code */

  var clearDownloadLinksButton = ui.Button({
    label: 'Clear',
    style: {width: '80px', fontSize: '10px', margin: '2px 0', backgroundColor: '#eee', color: '#888', shown: false},
    onClick: function() {
      downloadStatusLabel.setValue('');
      downloadLinksPanel.clear();
      psScriptPanel.clear();
      psScriptPanel.style().set('shown', false);
      downloadWarningLabel.style().set({shown: false});
      driveTipLabel.style().set({shown: false});
      downloadItems = [];
      clearDownloadLinksButton.style().set({shown: false});
    }
  });

  // Link threshold slider (in Advanced): controls when auto-script kicks in
  var linkThresholdSlider = ui.Slider({
    min: 1, max: 100, value: DOWNLOAD_LINK_THRESHOLD, step: 1,
    style: {margin: '0', stretch: 'horizontal'},
    onChange: function(val) { DOWNLOAD_LINK_THRESHOLD = val; }
  });

  // When script mode triggers, optionally show the generated Python code
  // inline (under a "Code preview:" header) so a user can inspect it before
  // running. Off by default -- most users just want the download link.
  var previewPythonCheckbox = ui.Checkbox({
    label: 'Preview Python code',
    value: false,
    style: {fontSize: '11px', margin: '4px 0 0 0'}
  });

  var downloadResolutionRow = ui.Panel(
    [ui.Label('Resolution (m):', {margin: '0 8px 0 0', fontSize: '11px'}), downloadScaleSlider, downloadScaleInput],
    ui.Panel.Layout.flow('horizontal'), {stretch: 'horizontal'});

  var downloadAdvancedContent = ui.Panel({
    widgets: [
      useCustomAoiCheckbox,
      drawAoiStatusLabel,
      downloadTileGridPanel,
      ui.Panel([
        ui.Label('Script threshold:', {margin: '0 8px 0 0', fontSize: '11px'}),
        linkThresholdSlider
      ], ui.Panel.Layout.flow('horizontal'), {stretch: 'horizontal'}),
      ui.Label(
        'When download links exceed this number, a Python script is ' +
        'generated instead of individual links.',
        {fontSize: '10px', color: '#888', fontStyle: 'italic', margin: '0 0 4px 0'}),
      previewPythonCheckbox,
      clearDownloadLinksButton
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, margin: '0 0 0 4px'}
  });
  var downloadAdvancedToggle = ui.Button({
    label: '▸ Advanced',
    onClick: function() {
      var s = downloadAdvancedContent.style().get('shown');
      downloadAdvancedContent.style().set({shown: !s});
      downloadAdvancedToggle.setLabel(s ? '▸ Advanced' : '▾ Advanced');
    },
    style: {fontSize: '11px', color: '#555', margin: '2px 0', padding: '2px 6px', backgroundColor: '#ffffff'}
  });

  // Warning banner about GEE app download workaround
  var downloadWarningLabel = ui.Label(
    'Note: downloading from a GEE app requires a workaround. Download ' +
    'links are time-limited and may expire. For reliable batch saving of ' +
    'large areas, use Save to Drive (script mode).',
    {fontSize: '10px', color: '#856404', margin: '0 0 4px 0',
     backgroundColor: '#fff3cd', padding: '4px', border: '1px solid #ffc107'});

  // Tip: suggest Save to Drive when in script mode (not published app)
  var driveTipLabel = ui.Label(
    'Tip: Save to Drive has fewer limitations and is recommended for ' +
    'large or multiple exports.',
    {fontSize: '10px', color: '#0c5460', fontStyle: 'italic',
     margin: '0 0 4px 0', backgroundColor: '#d1ecf1', padding: '4px',
     border: '1px solid #bee5eb'});
  if (IS_PUBLISHED_APP) driveTipLabel.style().set({shown: false});

  // Warning + tip start hidden; shown after the user clicks Save to computer
  downloadWarningLabel.style().set({shown: false});
  driveTipLabel.style().set({shown: false});

  var downloadPanel = ui.Panel({
    widgets: [
      ui.Panel([ui.Label('Layer:', {margin: '0 8px 0 0', fontSize: '12px'}), downloadLayerSelect],
        ui.Panel.Layout.flow('horizontal'), {stretch: 'horizontal', margin: '0 0 4px 0'}),
      downloadResolutionRow,
      downloadButton,
      downloadWarningLabel,
      driveTipLabel,
      downloadStatusLabel,
      downloadLinksPanel,
      psScriptPanel,
      downloadAdvancedToggle,
      downloadAdvancedContent
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {margin: '0', stretch: 'horizontal'}
  });

  var smoothRadiusForestSlider = ui.Slider({min: 0, max: 5000, value: 2000, step: 500, onChange: markNeedsUpdate});
  var smallPixelThresholdForestSlider = ui.Slider({min: 0, max: 1, value: 0.5, step: 0.1, onChange: markNeedsUpdate});

  // ============================================
  // WDPA UI CONTROLS
  // ============================================

  // Year slider for WDPA (minimum years protected becomes direct year cutoff)
  var wdpaYearSlider = ui.Slider({
    min: 1900, max: 2025, value: current_year - years_protected, step: 5,
    onChange: function(value) {
      years_protected = current_year - value;
      markNeedsUpdate();
    }
  });

  // Individual WDPA category checkboxes
  var wdpaCategoryCheckboxes = {};
  var wdpaCategoryCheckboxPanel = ui.Panel({layout: ui.Panel.Layout.flow('horizontal', true)});

  allWdpaCategories.forEach(function(cat) {
    wdpaCategoryCheckboxes[cat] = ui.Checkbox({
      label: cat,
      value: selected_iucn_categories.indexOf(cat) >= 0,
      onChange: function() {
        if (wdpaCategoryLabel.style().get('shown') !== false) {
          wdpaPresetSelect.setValue('Manual Selection', false);
        }
        updateSelectedCategories();
        markNeedsUpdate();
      }
    });
    wdpaCategoryCheckboxPanel.add(wdpaCategoryCheckboxes[cat]);
  });

  var wdpaCategoryLabel = ui.Label('IUCN Categories:');

  function updateSelectedCategories() {
    selected_iucn_categories = allWdpaCategories.filter(function(cat) { 
      return wdpaCategoryCheckboxes[cat].getValue(); 
    });
  }

  function showHideWdpaCheckboxes(show) {
    wdpaCategoryLabel.style().set('shown', show);
    wdpaCategoryCheckboxPanel.style().set('shown', show);
  }

  // WDPA preset dropdown
  var wdpaPresetSelect = ui.Select({
    items: ['All Categories', 'Strict (Ia, Ib, II)', 'Manual Selection'],
    value: 'Strict (Ia, Ib, II)',
    onChange: function(value) {
      var strictCats = ['Ia', 'Ib', 'II'];
      allWdpaCategories.forEach(function(cat) {
        var shouldCheck = value === 'All Categories' || (value === 'Strict (Ia, Ib, II)' && strictCats.indexOf(cat) >= 0);
        wdpaCategoryCheckboxes[cat].setValue(shouldCheck, false);
      });
      showHideWdpaCheckboxes(value === 'Manual Selection');
      updateSelectedCategories();
      markNeedsUpdate();
    }
  });

  showHideWdpaCheckboxes(false);

  // Treecover threshold panels. Stacked vertically (label above
  // slider) because the inline layout caused horizontal scrollbars
  // on narrow left panels — workshop feedback (2026-05-12).
  // The slider stretches to the panel width; the label sits on its
  // own line above so it never gets cropped.
  treecoverThresholdSlider.style().set('stretch', 'horizontal');
  treecoverHeightThresholdSlider.style().set('stretch', 'horizontal');
  var treecoverPanel = ui.Panel({
    layout: ui.Panel.Layout.flow('vertical'),
    widgets: [
      ui.Label('Tree canopy threshold (%):',
               {fontSize: '11px', margin: '4px 0 0 0'}),
      treecoverThresholdSlider
    ],
    style: {margin: '0', shown: false}
  });

  var treecoverHeightPanel = ui.Panel({
    layout: ui.Panel.Layout.flow('vertical'),
    widgets: [
      ui.Label('Tree height threshold (m):',
               {fontSize: '11px', margin: '4px 0 0 0'}),
      treecoverHeightThresholdSlider
    ],
    style: {margin: '0', shown: true}
  });

  // Dropdown for treecover source. P1.23: "Custom Forest" was pulled out
  // of this dropdown into its own discoverable checkbox section (see
  // nationalForest below) -- echoes the other custom-data sections
  // (nationalAgri, nationalPlantations, etc.) and is far more findable
  // than being buried as a 5th dropdown option.
  var treecoverSourceSelect = ui.Select({
    items: ['Hansen GFC', 'GLAD LULC', 'Agreement (Hansen & GLAD)', 'Combined extent (Hansen | GLAD)'],
    value: 'GLAD LULC',
    onChange: function() {
      // P1.24: visibility branching (source -> threshold panels, plus
      // hide-on-Replace-global) is owned by updateGlobalForestInputsVisibility().
      updateGlobalForestInputsVisibility();
      updateRefineFraWarning();  // height vs canopy relevance changes with source
      markNeedsUpdate();
    }
  });

  // P1.23: Custom forest asset inputs are now created via the standard
  // createNationalAssetInputs factory below (see `nationalForest`),
  // echoing the discoverable checkbox-style pattern of every other
  // custom-data section. The old createYearAssetInputs-based forestAssets
  // has been retired.

  // P1.22: paired checkboxes follow the FRA forest-derivation flow:
  //   tree cover - plantations    = Forest (FRA baseline)
  //   Forest    - planted forest = Naturally regenerating forest
  // "Plantations" here means agricultural tree crops (oil palm, fruit,
  // agroforestry) per FRA Note 10. "Planted forest" means timber/pulp/
  // fibre plantations (eucalyptus, pine, teak) per FRA Note 7.
  // (Rubber is country-dependent in FRA reporting -- see About panel.)
  // P1.24: outcome-framed labels.
  // P1.25: examples now inline in the label (FRA-aligned "other land
  // with tree cover" wording), so the standalone italic hint that lived
  // here in P1.24 is redundant and removed. Wrapper panel kept (single
  // child) so updateRefineVisibility() still toggles via the
  // wrapper and exclusionActive(checkbox, wrapper) keeps working.
  var excludeAgricultureFromForestCheckbox = ui.Checkbox({
    label: 'Refine to forest',
    // Opt-in: ships UNTICKED so opening the "Refine input" sub-section
    // doesn't silently start refining. Selecting an FRA category
    // auto-ticks it via updateRefineVisibility() (a deliberate opt-in).
    value: false,
    onChange: function() { markNeedsUpdate(); updateRefineStatus(); },
    style: {fontSize: '11px'}
  });
  // Hint text removed (2026-05-12 workshop) — checkbox label now
  // reads "Exclude other land with tree cover" inline. Kept as a
  // hidden widget so updateRefineVisibility() still has the
  // reference to manage (no NPEs elsewhere in the code).
  var excludeAgriHint = ui.Label('', {shown: false});
  var excludeAgriPanel = ui.Panel({
    widgets: [excludeAgricultureFromForestCheckbox, excludeAgriHint],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {margin: '0'}
  });

  var includePlantationsCheckbox = ui.Checkbox({
    label: 'Refine to naturally regenerating forest',
    // Opt-in: ships UNTICKED (see excludeAgricultureFromForestCheckbox).
    value: false,
    onChange: function() { markNeedsUpdate(); updateRefineStatus(); },
    style: {fontSize: '11px'}
  });
  // Hint text removed (2026-05-12 workshop) — checkbox label now
  // says "Exclude planted forest" inline.
  var includePlantationsHint = ui.Label('', {shown: false});
  var includePlantationsPanel = ui.Panel({
    widgets: [includePlantationsCheckbox, includePlantationsHint],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {margin: '0'}
  });

  // Function to update which asset inputs are visible based on selected years
  function updateVisibleAssetInputs() {
    var useSplitScreen = enableSplitScreenCheckbox.getValue();
    var year1 = parseInt(yearSelector1.getValue());
    var year2 = parseInt(yearSelector2.getValue());

    nationalForest.updateVisibility(useSplitScreen, year1, year2);
    nationalRoads.updateVisibility(useSplitScreen, year1, year2);
    nationalBuiltupSmall.updateVisibility(useSplitScreen, year1, year2);
    nationalBuiltupLarge.updateVisibility(useSplitScreen, year1, year2);
    nationalAgri.updateVisibility(useSplitScreen, year1, year2);
    nationalOLWTC.updateVisibility(useSplitScreen, year1, year2);
    nationalPlantations.updateVisibility(useSplitScreen, year1, year2);
    nationalProtected.updateVisibility(useSplitScreen, year1, year2);
  }

  // =============================================================================
  // CUSTOM DATA OVERRIDES
  // Each pair: checkbox (enable toggle) + textbox (asset ID). Shown inline.
  // Convention: binary 0/1 image, clipped or unclipped — country mask is applied.
  // Roads / built-up / protected: merged (union) with global defaults.
  // Agriculture / plantations: replaces global defaults.
  // =============================================================================
  // Factory for per-year custom asset inputs (mirrors createYearAssetInputs).
  // Returns {checkbox, modeSelect, panel, getAsset(year), updateVisibility(split,y1,y2), setShown(bool), reset()}
  //
  // P1.23 changes:
  //  - Renamed mode label "Add to global" -> "Add to global extent"
  //    (clearer about what's being unioned).
  //  - New optional `allowAgreement` config flag adds a third merge mode
  //    "Agreement with global" (intersection -- pixel must be in BOTH
  //    custom AND global). Off by default; opt-in per dataset because
  //    pixel alignment is unreliable for vector-derived layers (roads,
  //    small built-up) without buffering.
  //
  // Backwards-compat for saved settings: if a saved setting still has the
  // old value 'Add to global', it is mapped to 'Add to global extent' on
  // load. See applySavedSettings handling at line ~4535.
  function createNationalAssetInputs(config) {
    var label          = config.label;
    var placeholder    = config.placeholder || 'users/me/asset  (binary 0/1)';
    var defaultMode    = config.defaultMode || 'Add to global extent';
    var allowAgreement = config.allowAgreement === true;

    // Forward-migrate the old mode string in case a caller still passes it.
    if (defaultMode === 'Add to global') defaultMode = 'Add to global extent';

    var modeItems = ['Add to global extent', 'Replace global'];
    if (allowAgreement) modeItems.push('Agreement with global');

    var modeSelect = ui.Select({
      items: modeItems, value: defaultMode,
      onChange: function() { markNeedsUpdate(); },
      style: {shown: false, fontSize: '10px', margin: '0 0 0 4px'}
    });

    var inputs = {};
    var yearPanels = {};
    var yearInputsContainer = ui.Panel({
      layout: ui.Panel.Layout.flow('vertical'),
      style: {shown: false, margin: '2px 0 0 12px'}
    });

    years.forEach(function(year) {
      var row = ui.Panel({
        layout: ui.Panel.Layout.flow('horizontal'),
        style: {margin: '2px 0', shown: false}
      });
      row.add(ui.Label(year + ':', {fontSize: '10px', margin: '5px 4px 0 0', width: '36px'}));
      var tb = ui.Textbox({
        placeholder: placeholder,
        style: {fontSize: '10px', stretch: 'horizontal'}
      });
      inputs[year] = tb;
      yearPanels[year] = row;
      row.add(tb);
      yearInputsContainer.add(row);
    });

    var checkbox = ui.Checkbox({
      label: label, value: false,
      onChange: function(v) {
        modeSelect.style().set('shown', v);
        yearInputsContainer.style().set('shown', v);
        if (v) updateVisibleAssetInputs(); // show correct year rows
        markNeedsUpdate();
      },
      style: {fontSize: '11px', color: '#2c5282'}
    });

    modeSelect.style().set({margin: '0 0 0 12px', stretch: 'horizontal'});
    var headerRow = ui.Panel({
      widgets: [checkbox, modeSelect],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {margin: '0'}
    });

    // Preprocessing UI — one shared config for all years of this dataset
    var prepUi = createPreprocessingUi();

    var outerPanel = ui.Panel({
      widgets: [headerRow, yearInputsContainer, prepUi.panel],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {margin: '2px 0 4px 0', padding: '4px',
              border: '1px solid #d0d0d0', backgroundColor: '#fafafa'}
    });

    // Only show preprocessing panel when checkbox is enabled
    prepUi.panel.style().set('shown', false);
    checkbox.onChange(function(v) {
      prepUi.panel.style().set('shown', v);
    });

    return {
      checkbox: checkbox,
      modeSelect: modeSelect,
      panel: outerPanel,

      getAsset: function(year) {
        return inputs[year] ? inputs[year].getValue() : '';
      },

      // Get preprocessing config (shared across all years)
      getPreprocessingConfig: function() {
        return prepUi.getConfig();
      },

      updateVisibility: function(splitScreenEnabled, year1, year2) {
        years.forEach(function(year) {
          var show = splitScreenEnabled ? (year === year1 || year === year2) : (year === year2);
          yearPanels[year].style().set('shown', show);
        });
      },

      setShown: function(shown) {
        outerPanel.style().set('shown', shown);
      },

      reset: function() {
        checkbox.setValue(false);
        modeSelect.setValue(defaultMode);
        modeSelect.style().set('shown', false);
        yearInputsContainer.style().set('shown', false);
        prepUi.panel.style().set('shown', false);
        years.forEach(function(year) { inputs[year].setValue(''); });
      },

      // For settings serialisation
      collectAssets: function(checkboxVal) {
        if (!checkboxVal) return {};
        var out = {};
        years.forEach(function(year) {
          var v = inputs[year].getValue();
          if (v) out[year] = v;
        });
        return out;
      },

      applyAssets: function(assetsByYear) {
        years.forEach(function(year) {
          if (assetsByYear[year]) inputs[year].setValue(assetsByYear[year]);
        });
      },

      collectPreprocessing: function() { return prepUi.collectSettings(); },
      applyPreprocessing:   function(s) { prepUi.applySettings(s); }
    };
  }

  // Each accepts GEE asset IDs (users/..., projects/...) or gs:// Cloud Storage COG URIs.
  // Use ⚙ Preprocessing to configure source type, band, classes, or threshold.
  //
  // P1.23: allowAgreement is opt-in per dataset. Enabled for area-based
  // raster datasets where pixel-for-pixel intersection is meaningful
  // (forest, plantations/exclusion, agri, large built-up, protected).
  // Disabled for vector-derived narrow features (roads, small built-up)
  // because rasterised vectors rarely align pixel-perfectly between
  // independent sources, so unbuffered Agreement would yield near-empty
  // results -- adding a ~100 m alignment buffer is deferred to a later batch.
  var nationalForest     = createNationalAssetInputs({label: 'Custom forest data',          defaultMode: 'Replace global', placeholder: 'asset path or gs:// URI', allowAgreement: true});
  var nationalRoads      = createNationalAssetInputs({label: 'Custom road data',            defaultMode: 'Add to global extent',  placeholder: 'asset path or gs:// URI'});
  var nationalBuiltupSmall = createNationalAssetInputs({label: 'Custom small built-up data',  defaultMode: 'Add to global extent',  placeholder: 'asset path or gs:// URI'});
  var nationalBuiltupLarge = createNationalAssetInputs({label: 'Custom large built-up data',  defaultMode: 'Add to global extent',  placeholder: 'asset path or gs:// URI', allowAgreement: true});
  var nationalAgri       = createNationalAssetInputs({label: 'Custom agriculture data',     defaultMode: 'Replace global', placeholder: 'asset path or gs:// URI', allowAgreement: true});
  // Custom data for each refinement exclusion toggle.
  // nationalOLWTC: shown when "Refine to forest" (OLWTC exclusion) is visible
  // nationalPlantations: shown when "Refine to NRF" (planted forest exclusion) is visible
  // Variable name nationalPlantations kept for backwards compat with saved settings.
  var nationalOLWTC      = createNationalAssetInputs({label: 'Custom OLWTC data',             defaultMode: 'Replace global', placeholder: 'asset path or gs:// URI', allowAgreement: true});
  var nationalPlantations= createNationalAssetInputs({label: 'Custom planted forest data',    defaultMode: 'Replace global', placeholder: 'asset path or gs:// URI', allowAgreement: true});
  var nationalProtected  = createNationalAssetInputs({label: 'Custom protected areas data', defaultMode: 'Add to global extent',  placeholder: 'asset path or gs:// URI', allowAgreement: true});

  // Slope is non-temporal — single textbox kept intentionally
  var useCustomSlopeCheckbox = ui.Checkbox({
    label: 'Custom slope data (0–90°)', value: false,
    onChange: function(v) { customSlopeInput.style().set('shown', v); markNeedsUpdate(); },
    style: {fontSize: '11px'}
  });
  var customSlopeInput = ui.Textbox({
    placeholder: 'users/me/custom_slope  (0–90 degrees)',
    style: {shown: false, fontSize: '10px', stretch: 'horizontal', margin: '2px 0 0 12px'}
  });

  // =============================================================================
  // P1.23: INPUT-CATEGORY DECLARATION (panel level)
  // Lets the user declare what their tree cover layer represents on the
  // FRA hierarchy. Plain-language labels in the main UI; FRA mapping in
  // the About panel via the ⓘ link. Drives visibility of the OLWTC and
  // planted-forest exclusion toggles uniformly for all sources (Hansen,
  // GLAD, Agreement, Combined, or Custom forest data). Default value
  // "All tree cover" preserves pre-P1.23 behaviour for users who don't
  // engage with the dropdown.
  // =============================================================================

  // Plain-language input category labels (kept short enough to fit panel)
  // P1.25: FRA-aligned phrasing. "Other land with tree cover" is the
  // FRA 2025 category name (Note 10 + section 1e of the FRA Terms doc)
  // for the non-Forest tree-cover bucket -- palms, orchards,
  // agroforestry, urban trees. Surfacing the FRA term in the dropdown
  // trains workshop users on the vocabulary they'll need when reporting.
  // Plain names — workshop feedback (2026-05-11): the previous
  // "Tree cover: includes oil palm..." / "Forest: excludes..." wording
  // read like the tool was choosing to include or exclude classes,
  // when really these labels just align the user's input with a FRA
  // category. Tooltips still explain each category in detail.
  var INPUT_CATEGORY_ALL    = 'Tree cover';
  var INPUT_CATEGORY_FOREST = 'Forest';
  var INPUT_CATEGORY_NATREG = 'Naturally regenerating forest';
  var INPUT_CATEGORY_PRIMARY= 'Primary forest';

  // Map of old long-form values seen in saved settings → new short
  // values. Used on load so old saved configs continue to work.
  var INPUT_CATEGORY_LEGACY_MAP = {
    'Tree cover: includes oil palm, orchards, agroforestry etc': INPUT_CATEGORY_ALL,
    'Forest: excludes other land with tree cover e.g. oil palm, orchards, agroforestry etc': INPUT_CATEGORY_FOREST,
    'Naturally regenerating forest: also excludes planted forest': INPUT_CATEGORY_NATREG,
    'Primary forest: for comparison / further analysis': INPUT_CATEGORY_PRIMARY
  };

  // Sentinel value for "no FRA category declared" — selectable inside
  // the dropdown so users can undo a previous category pick. Workshop
  // feedback (2026-05-12): the placeholder-only approach trapped users
  // on whatever category they first picked.
  var INPUT_CATEGORY_NONE = 'Non FRA aligned';

  var inputCategorySelect = ui.Select({
    items: [INPUT_CATEGORY_NONE,
            INPUT_CATEGORY_ALL, INPUT_CATEGORY_FOREST,
            INPUT_CATEGORY_NATREG, INPUT_CATEGORY_PRIMARY],
    value: INPUT_CATEGORY_NONE,
    onChange: function() {
      updateRefineVisibility();
      markNeedsUpdate();
    },
    style: {stretch: 'horizontal', fontSize: '11px'}
  });

  var fraAlignedCheckbox = ui.Checkbox({
    label: 'FRA-aligned',
    value: false,
    onChange: function() { updateRefineVisibility(); markNeedsUpdate(); },
    style: {fontSize: '11px', margin: '4px 0 0 0'}
  });

  // ⓘ link opens the existing About panel (which already contains the
  // FRA 2025 definitions block + "How PFF outputs map to FRA"). Using
  // a small Button rather than a Label because GEE ui.Label.onClick is
  // not exposed -- targetUrl-only -- so we need a Button for in-app
  // actions. Style is kept understated so it reads as a link, not a
  // chunky action button.
  var inputCategoryFraInfo = ui.Button({
    label: 'ⓘ',
    onClick: function() {
      var shown = fraDefsPanel.style().get('shown');
      fraDefsPanel.style().set('shown', !shown);
    },
    style: {fontSize: '10px', padding: '2px 6px', margin: '0 0 0 4px',
            backgroundColor: '#f4f8ff'}
  });

  var fraDefLabel = ui.Label('', {fontSize: '10px', color: '#666',
      fontStyle: 'italic', margin: '0 0 4px 4px'});

  function updateFraDefLabel() {
    var v = inputCategorySelect.getValue();
    var defs = {};
    defs[INPUT_CATEGORY_ALL]     = '* Not a FRA category — entry point for the FRA cascade. Forest + OLTC combined (≥5 m, ≥10% canopy, ≥0.5 ha) without land-use filter.';
    defs[INPUT_CATEGORY_FOREST]  = 'FRA category: land use is forest — excludes agricultural/urban tree stands.';
    defs[INPUT_CATEGORY_NATREG]  = 'FRA category: forest of trees established through natural regeneration.';
    defs[INPUT_CATEGORY_PRIMARY] = 'FRA category: naturally regenerating, native species, no visible human activity.';
    fraDefLabel.setValue(defs[v] || '');
  }
  updateFraDefLabel();

  // ── ⓘ FRA definitions popup: two tabs (Definitions / Hierarchy) ──
  // GEE has no native tab widget, so simulate it with two toggle buttons
  // that show/hide their content panel and highlight the active one.
  //
  // Definitions tab: flat one-line FRA-category defs. Tree cover is
  // deliberately omitted (universally understood) -- so every entry here
  // IS an FRA category (no group headers / "(not a FRA category)" needed).
  // Hierarchy tab: the real FRA taxonomy by indentation (Forest and Other
  // land are SEPARATE top-level categories); Tree cover appears only as a
  // muted footnote because it is not an FRA category.
  var defsTabContent = ui.Panel({
    widgets: [
      ui.Label('Forest', {fontWeight: 'bold', fontSize: '10px', margin: '0 0 0 8px'}),
      ui.Label('Land use is forest; ≥5 m, ≥10% canopy, ≥0.5 ha (excludes agricultural & urban tree stands)', {fontSize: '10px', margin: '0 0 2px 16px', color: '#555'}),
      ui.Label('Naturally regenerating forest', {fontWeight: 'bold', fontSize: '10px', margin: '0 0 0 8px'}),
      ui.Label('Forest established through natural regeneration', {fontSize: '10px', margin: '0 0 2px 16px', color: '#555'}),
      ui.Label('Primary forest', {fontWeight: 'bold', fontSize: '10px', margin: '0 0 0 8px'}),
      ui.Label('Naturally regenerating, native species, no visible human activity', {fontSize: '10px', margin: '0 0 2px 16px', color: '#555'}),
      ui.Label('Other land with tree cover (OLTC)', {fontWeight: 'bold', fontSize: '10px', margin: '0 0 0 8px'}),
      ui.Label('Tree cover on non-forest land use: oil palm, orchards, agroforestry', {fontSize: '10px', margin: '0 0 2px 16px', color: '#555'}),
      ui.Label('Planted forest', {fontWeight: 'bold', fontSize: '10px', margin: '0 0 0 8px'}),
      ui.Label('Trees established by planting/seeding: eucalyptus, pine, teak, rubber', {fontSize: '10px', margin: '0 0 2px 16px', color: '#555'}),
      ui.Label({
        value: 'FAO FRA 2025 full definitions →',
        style: {fontSize: '10px', color: '#1a73e8', margin: '4px 0 0 8px'},
        targetUrl: 'https://fra-data.fao.org/definitions/fra/2025/en/tad#1b'
      })
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: true, margin: '2px 0 0 0'}
  });

  var hierTabContent = ui.Panel({
    widgets: [
      ui.Label('Forest', {fontWeight: 'bold', fontSize: '10px', margin: '2px 0 0 8px'}),
      ui.Label('Naturally regenerating forest', {fontWeight: 'bold', fontSize: '10px', margin: '0 0 0 20px'}),
      ui.Label('Primary forest', {fontWeight: 'bold', fontSize: '10px', margin: '0 0 0 32px'}),
      ui.Label('Planted forest', {fontWeight: 'bold', fontSize: '10px', margin: '0 0 0 20px'}),
      ui.Label('Other land', {fontWeight: 'bold', fontSize: '10px', margin: '4px 0 0 8px'}),
      ui.Label('Other land with tree cover (OLTC)', {fontWeight: 'bold', fontSize: '10px', margin: '0 0 0 20px'}),
      ui.Label('Tree cover (tool input) = Forest + OLTC pixels — not a FRA category.',
        {fontSize: '10px', fontStyle: 'italic', color: '#999', margin: '6px 0 0 8px'})
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, margin: '2px 0 0 0'}
  });

  function setFraDefsTab(tab) {
    var isDefs = (tab === 'defs');
    defsTabContent.style().set('shown', isDefs);
    hierTabContent.style().set('shown', !isDefs);
    defsTabBtn.style().set('backgroundColor', isDefs ? '#d0e0ff' : '#f0f0f0');
    hierTabBtn.style().set('backgroundColor', isDefs ? '#f0f0f0' : '#d0e0ff');
  }
  var defsTabBtn = ui.Button({
    label: 'Definitions',
    onClick: function() { setFraDefsTab('defs'); },
    style: {fontSize: '10px', padding: '1px 6px', margin: '0 2px 0 0', backgroundColor: '#d0e0ff'}
  });
  var hierTabBtn = ui.Button({
    label: 'Hierarchy',
    onClick: function() { setFraDefsTab('hier'); },
    style: {fontSize: '10px', padding: '1px 6px', margin: '0', backgroundColor: '#f0f0f0'}
  });
  var fraDefsTabBar = ui.Panel({
    widgets: [defsTabBtn, hierTabBtn],
    layout: ui.Panel.Layout.flow('horizontal'),
    style: {margin: '0 0 2px 0'}
  });

  var fraDefsPanel = ui.Panel({
    widgets: [fraDefsTabBar, defsTabContent, hierTabContent],
    style: {shown: false, backgroundColor: '#f8f9fa', border: '1px solid #e0e0e0',
            margin: '4px 0 4px 4px', padding: '4px'}
  });
  setFraDefsTab('defs');  // initial tab state

  // fraInputSection now contains just the dropdown + the contextual
  // FRA-def label. The ⓘ FRA definitions button + the collapsible
  // defs panel are mounted at the TOP of the Refine subsection
  // (workshop feedback 2026-05-12).
  // Inline hints removed (fraInputHint + fraDefLabel) -- the ⓘ tabbed
  // definitions popup now carries the definitional detail, so the dropdown
  // just needs its label. fraDefLabel var + updateFraDefLabel() are kept
  // as harmless no-ops (label no longer mounted) to avoid touching their
  // callers in updateRefineVisibility / init.
  var fraInputSection = ui.Panel({
    widgets: [
      createCompactRow('Treat input as:', inputCategorySelect)
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {margin: '0 0 0 0'}
  });

  var refineInputCheckbox = ui.Checkbox({
    label: 'Refine input',
    value: false,
    onChange: function() { updateRefineVisibility(); markNeedsUpdate(); },
    style: {fontSize: '11px', margin: '4px 0 0 0'}
  });
  var refineInputHint = ui.Label(
    'Creates intermediate layer(s) (optional)',
    {fontSize: '10px', color: '#666', fontStyle: 'italic',
    margin: '0 0 0 22px'}
  );
  var noRefineNote = ui.Label('', {fontSize: '10px', color: '#888', fontStyle: 'italic', margin: '0 0 0 22px', shown: false});
  var refineSep = ui.Panel({style: {
    height: '1px', backgroundColor: '#ddd', margin: '6px 0', stretch: 'horizontal'
  }});

  var _updatingRefineVis = false;

  function updateRefineVisibility() {
    if (_updatingRefineVis) return;
    _updatingRefineVis = true;

    // New scheme: dropdown is the single gate. Empty (placeholder)
    // means no FRA declaration → no intermediate layers surface.
    // Declared category drives exclusion-toggle auto-tick + ↳ creates
    // hint visibility. fraAlignedCheckbox + refineInputCheckbox are
    // kept hidden + synced from the dropdown so existing runtime
    // callers (stats panel, export logic, exclusionActive) continue
    // to work without rewriting.
    var cat = inputCategorySelect.getValue();
    var declared = !!cat && cat !== '' && cat !== INPUT_CATEGORY_NONE;

    var intermediatesPossible = declared
        && cat !== INPUT_CATEGORY_NATREG
        && cat !== INPUT_CATEGORY_PRIMARY;
    fraAlignedCheckbox.setValue(declared, false);
    refineInputCheckbox.setValue(intermediatesPossible, false);

    updateFraDefLabel();

    // OLTC widgets visible unless input is past the OLTC step.
    // - Placeholder: visible (user may tick toggles freely; no
    //   intermediate surfaces because not declared)
    // - Tree cover: visible
    // - Forest / NRF / Primary: hidden (OLTC irrelevant)
    var showOlwtc = !declared || (cat === INPUT_CATEGORY_ALL);
    // Planted widgets visible unless input is past the planted step.
    var showPlanted = !declared
        || (cat === INPUT_CATEGORY_ALL)
        || (cat === INPUT_CATEGORY_FOREST);

    var customOn = enableTreeCoverCustomCheckbox.getValue();
    excludeAgriPanel.style().set('shown', showOlwtc);
    nationalOLWTC.setShown(customOn && showOlwtc);
    includePlantationsPanel.style().set('shown', showPlanted);
    nationalPlantations.setShown(customOn && showPlanted);

    // ↳ creates hints — visible only when the toggle would actually
    // produce a valid FRA intermediate layer given the declaration.
    olwtcCreatesHint.style().set('shown',
        cat === INPUT_CATEGORY_ALL);
    plantedCreatesHint.style().set('shown',
        cat === INPUT_CATEGORY_ALL || cat === INPUT_CATEGORY_FOREST);

    // Auto-tick exclusion checkboxes per category. Placeholder leaves
    // toggles alone — user has full control.
    if (cat === INPUT_CATEGORY_ALL) {
      excludeAgricultureFromForestCheckbox.setValue(true, false);
      includePlantationsCheckbox.setValue(true, false);
    } else if (cat === INPUT_CATEGORY_FOREST) {
      excludeAgricultureFromForestCheckbox.setValue(false, false);
      includePlantationsCheckbox.setValue(true, false);
    } else if (cat === INPUT_CATEGORY_NATREG
            || cat === INPUT_CATEGORY_PRIMARY) {
      excludeAgricultureFromForestCheckbox.setValue(false, false);
      includePlantationsCheckbox.setValue(false, false);
    }

    // Stable labels (no FRA / non-FRA branching). Workshop feedback
    // (2026-05-12): use plain "Exclude other land with tree cover"
    // rather than the OLTC acronym — clearer to first-time users.
    excludeAgricultureFromForestCheckbox.setLabel(
      'Exclude other land with tree cover');
    includePlantationsCheckbox.setLabel('Exclude planted forest');
    exportChk_inputForest.setLabel(
      declared ? 'Forest' : 'Forest (non-FRA)');
    exportChk_naturallyRegenerating.setLabel(
      declared ? 'Naturally regenerating forest' : 'NRF (non-FRA)');

    // Hidden / no-op legacy widgets — never visible in the new UI.
    fraInputSection.style().set('shown', true); // it's inside the
                                                // collapsible subsection
                                                // so collapse already
                                                // hides it
    refineInputHint.style().set('shown', false);
    noRefineNote.style().set('shown', false);
    refineSep.style().set('shown', false);

    updateRefineStatus();
    _updatingRefineVis = false;
  }

  // NOTE: initial call to updateRefineVisibility() deferred until after
  // the new §2 layout panels (inputDefinitionPanel,
  // refineSubsectionContent, olwtcCreatesHint, plantedCreatesHint) and
  // enableTreeCoverCustomCheckbox are defined further down. The function
  // now references those widgets unconditionally, so calling it here
  // (before they exist) throws "Cannot read property 'getValue' of
  // undefined". See the call at L3848-ish (next to
  // updateGlobalForestInputsVisibility() initial sync).

  // Helper: a hidden exclusion checkbox should never apply, even if its
  // underlying value is still `true`. Used at every analysis branch
  // that reads excludeAgricultureFromForestCheckbox / includePlantationsCheckbox.
  // P1.24: now accepts an optional wrapper panel -- visibility is toggled
  // on the wrapper (so checkbox + hint label hide together), so we must
  // read the wrapper's shown state, not the bare checkbox.
  function exclusionActive(checkbox, wrapper) {
    // Single source of truth = the checkbox value (gated only by its
    // wrapper's FRA-driven visibility). Collapsing the "Refine input"
    // sub-section no longer disables refinement -- the opt-in default
    // (checkboxes ship unticked) covers the safety concern, and the
    // status label can then reflect the checkbox state honestly whether
    // the panel is open or collapsed (matches Buffer Exceptions).
    var visTarget = wrapper || checkbox;
    return visTarget.style().get('shown') !== false && checkbox.getValue();
  }

  // =============================================================================
  // COLLAPSIBLE PANELS (pff_layout style)
  // =============================================================================

  // DATES & VIEW PANEL
  var datesContent = ui.Panel({
    widgets: [
      yearSelector1Label, yearSelector1,
      yearSelector2Label, yearSelector2,
      enableSplitScreenCheckbox
    ],
    style: {shown: false, padding: '8px'}
  });

  var datesToggle = ui.Button({
    label: '▶ 1. Time Period',
    onClick: function() {
      var wasCollapsed = appState.ui.datesCollapsed;
      if (wasCollapsed) {
        collapseAllPanelsExcept('dates');
      }
      appState.ui.datesCollapsed = !appState.ui.datesCollapsed;
      datesContent.style().set({shown: !appState.ui.datesCollapsed});
      datesToggle.setLabel(appState.ui.datesCollapsed ? '▶ 1. Time Period' : '▼ 1. Time Period');
      updateLeftPanelWidth();
    },
    style: {stretch: 'horizontal', textAlign: 'left', padding: '3px 6px', margin: '1px', backgroundColor: '#f0f0f0'}
  });

  var datesPanelCollapsible = ui.Panel({
    widgets: [datesToggle, datesContent],
    layout: ui.Panel.Layout.flow('vertical')
  });

  // TREE COVER PANEL
  // P1.23 layout:
  //   1. Source dropdown (global default: Hansen / GLAD / Agreement / Combined)
  //   2. Threshold sliders (canopy or height, depending on source)
  //   3. Custom forest data section (echoes other custom-data sections;
  //      tickbox-driven, with mode-select for Replace/Add extent/Agreement)
  //   4. Panel-level "My tree cover represents:" declaration dropdown +
  //      ⓘ FRA mapping link. Drives visibility of the toggles below.
  //   5. Divider
  //   6. Conditional exclusion toggles (OLWTC, planted forest) and the
  //      Custom exclusion data section.
  // P1.24: bound to a variable so updateGlobalForestInputsVisibility()
  // can hide the whole row (label + dropdown) when custom forest is in
  // 'Replace global' mode.
  var treecoverSourceRow = createCompactRow('Source:', treecoverSourceSelect);

  // P1.24: status note that appears in the gap left by the hidden global
  // controls when custom forest replaces them. Default hidden.
  // GEE ui.Label can't mix bold and non-bold inline, so split into a
  // 3-label horizontal panel: lead text + bold "Replace global" + tail.
  // All three share the warn-style red + italic; only the middle label
  // adds bold so the option name pops.
  var _warnStyleBase = {fontSize: '10px', color: '#a04040',
                        fontStyle: 'italic', margin: '4px 0 4px 0'};
  var _warnStyleBold = {fontSize: '10px', color: '#a04040',
                        fontStyle: 'italic', fontWeight: 'bold',
                        margin: '4px 0 4px 0'};
  var globalSourceHiddenNote = ui.Panel({
    widgets: [
      ui.Label('Global tree-cover source not in use — ', _warnStyleBase),
      ui.Label('Replace global', _warnStyleBold),
      ui.Label(' option selected.', _warnStyleBase)
    ],
    layout: ui.Panel.Layout.flow('horizontal'),
    style: {margin: '0 0 0 4px', shown: false}
  });

  var enableTreeCoverCustomCheckbox = ui.Checkbox({
    label: 'Enable custom data inputs',
    value: false,
    onChange: function(checked) {
      nationalForest.setShown(checked);
      if (!checked) {
        nationalOLWTC.setShown(false);
        nationalPlantations.setShown(false);
      } else {
        updateRefineVisibility();
      }
    },
    style: {fontSize: '11px', color: '#555', margin: '6px 0 2px 0'}
  });
  nationalForest.panel.style().set({shown: false});

  // ── §2 restructure (Change A + C, GEE port) ───────────────────────
  // Source + threshold + custom-forest widgets go inside a bordered
  // "Tree-cover input definition" panel. FRA dropdown + exclusion
  // toggles go inside a collapsible "Refine input (optional,
  // experimental)" subsection, closed by default. fraAlignedCheckbox
  // and refineInputCheckbox are removed from the visible UI but
  // remain in scope so existing runtime callers (stats / exports /
  // exclusionActive) keep working — synced from the dropdown by
  // updateRefineVisibility.
  // ───────────────────────────────────────────────────────────────────

  var inputDefinitionPanel = ui.Panel({
    widgets: [
      // (Removed redundant "Tree-cover input definition" header -- the
      // section's "Define Tree Cover:" title sits directly above this box.)
      treecoverSourceRow,
      treecoverPanel,
      treecoverHeightPanel,
      globalSourceHiddenNote,
      enableTreeCoverCustomCheckbox,
      nationalForest.panel
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {border: '1px solid #d0d0d0', backgroundColor: '#fafafa',
            margin: '0 0 6px 0', padding: '6px'}
  });

  // ↳ creates "Forest" intermediate layer — italic helper shown only
  // when Tree cover declared (and so a Forest intermediate becomes
  // valid). Mirrors the QGIS plugin's _olwtc_creates_hint.
  var olwtcCreatesHint = ui.Label(
    '↳ creates "Forest" intermediate layer',
    {fontSize: '10px', color: '#666', fontStyle: 'italic',
     margin: '0 0 2px 22px', shown: false});

  // ↳ creates "Naturally regenerating forest" intermediate layer —
  // shown when Tree cover or Forest declared.
  var plantedCreatesHint = ui.Label(
    '↳ creates "Naturally regenerating forest" intermediate layer',
    {fontSize: '10px', color: '#666', fontStyle: 'italic',
     margin: '0 0 2px 22px', shown: false});

  var refineSubsectionContent = ui.Panel({
    widgets: [
      // Experimental marker -- same style as the Validation panel's, moved
      // here from the toggle label so the toggle reads just "(optional)".
      ui.Label('⚠ Experimental', {fontWeight: 'bold', fontSize: '11px',
        color: '#b35900', margin: '0 0 4px 0'}),
      inputCategoryFraInfo,       // ⓘ FRA definitions button (top)
      fraDefsPanel,               // collapsible definitions panel
      fraInputSection,            // dropdown + contextual FRA-def label
      excludeAgriPanel,
      olwtcCreatesHint,
      nationalOLWTC.panel,
      includePlantationsPanel,
      plantedCreatesHint,
      nationalPlantations.panel
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, margin: '0 0 0 4px'}
  });

  // Styling mirrors the "Buffer Exceptions" sub-section toggle (▸/▾
  // arrows, grey #555 text, #f0f0f0 background) so the two optional
  // sub-sections read as the same kind of control.
  // Always-visible status line (mirrors the Buffer Exceptions status
  // label) so the user can see what refinement is active without opening
  // the sub-section. Kept in sync by the exclusion checkboxes' onChange
  // and by updateRefineVisibility (the FRA dropdown drives the boxes).
  var refineStatusLabel = ui.Label('', {fontSize: '10px', color: '#888',
    fontStyle: 'italic', margin: '0 0 4px 4px'});

  // FRA-threshold guardrail: when a category IS declared (FRA-aligned) but
  // the tree-cover thresholds are below the FRA minimums (height ≥5 m,
  // canopy ≥10%), warn the user to raise the threshold or pick Non FRA
  // aligned. Always hidden for "Non FRA aligned" (sub-FRA is fine there).
  var refineFraWarningLabel = ui.Label('', {fontSize: '10px', color: '#b35900',
    fontWeight: 'bold', margin: '0 0 4px 4px', shown: false});

  function updateRefineFraWarning() {
    var cat = inputCategorySelect.getValue();
    var declared = !!cat && cat !== '' && cat !== INPUT_CATEGORY_NONE;
    if (!declared) { refineFraWarningLabel.style().set('shown', false); return; }
    var src = treecoverSourceSelect.getValue();
    var usesHeight = (src !== 'Hansen GFC');   // GLAD / Agreement / Combined use height
    var usesCanopy = (src !== 'GLAD LULC');    // Hansen / Agreement / Combined use canopy
    var heightBelow = usesHeight && treecoverHeightThresholdSlider.getValue() < 5;
    var canopyBelow = usesCanopy && treecoverThresholdSlider.getValue() < 10;
    if (!heightBelow && !canopyBelow) {
      refineFraWarningLabel.style().set('shown', false);
      return;
    }
    var parts = [];
    if (heightBelow) parts.push('tree height ≥5 m');
    if (canopyBelow) parts.push('canopy cover ≥10%');
    refineFraWarningLabel.setValue(
      '⚠ For FRA alignment, ' + parts.join(' and ') + ' is required. ' +
      'Raise the threshold, or choose "Non FRA aligned".');
    refineFraWarningLabel.style().set('shown', true);
  }

  function updateRefineStatus() {
    var olwtc   = excludeAgricultureFromForestCheckbox.getValue();
    var planted = includePlantationsCheckbox.getValue();
    var cat = inputCategorySelect.getValue();
    var declared = !!cat && cat !== '' && cat !== INPUT_CATEGORY_NONE;
    var msg;
    if (!declared) {
      // Non FRA aligned -- describe the exclusions; don't name FRA categories.
      if (olwtc && planted) {
        msg = 'Excluding: other land with tree cover + planted forest';
      } else if (olwtc) {
        msg = 'Excluding: other land with tree cover';
      } else if (planted) {
        msg = 'Excluding: planted forest';
      } else {
        msg = 'Refinement: none (output = input)';
      }
    } else {
      // FRA-aligned -- output level = max(declared input level, exclusions).
      // Levels: 0 tree cover, 1 Forest, 2 NRF, 3 Primary.
      var inputLevel = (cat === INPUT_CATEGORY_FOREST)  ? 1
                     : (cat === INPUT_CATEGORY_NATREG)  ? 2
                     : (cat === INPUT_CATEGORY_PRIMARY) ? 3 : 0;
      var exclLevel  = planted ? 2 : (olwtc ? 1 : 0);
      var outLevel   = Math.max(inputLevel, exclLevel);
      var names = {1: 'Forest', 2: 'Naturally regenerating forest', 3: 'Primary forest'};
      if (outLevel === 0) {
        msg = 'Refinement: none (output = tree cover)';
      } else if (exclLevel > inputLevel) {
        msg = 'Refining to: ' + names[outLevel];
      } else {
        msg = 'Input declared: ' + names[outLevel];
      }
    }
    refineStatusLabel.setValue(msg);
    updateRefineFraWarning();
  }

  var refineSubsectionToggle = ui.Button({
    label: '▸ Refine input (optional)',
    onClick: function() {
      appState.ui.refineInputCollapsed = !appState.ui.refineInputCollapsed;
      refineSubsectionContent.style().set({
        shown: !appState.ui.refineInputCollapsed});
      refineSubsectionToggle.setLabel(
        (appState.ui.refineInputCollapsed ? '▸ ' : '▾ ')
        + 'Refine input (optional)');
      // Collapse no longer affects exclusionActive() (the checkbox is the
      // single source of truth now), so no stale-mark needed on toggle.
    },
    style: {fontSize: '11px', color: '#555', margin: '6px 0 2px 0',
            padding: '2px 4px', backgroundColor: '#f0f0f0'}
  });

  var treeCoverContent = ui.Panel({
    widgets: [
      ui.Label('Define Tree Cover:',
               {fontWeight: 'bold', fontSize: '12px', margin: '0 0 4px 0'}),
      inputDefinitionPanel,
      refineSubsectionToggle,
      refineSubsectionContent,
      refineStatusLabel,
      refineFraWarningLabel
    ],
    style: {shown: false, padding: '8px'}
  });

  // =============================================================================
  // P1.24: GLOBAL FOREST INPUTS VISIBILITY
  // When a user supplies a custom forest layer in 'Replace global' mode,
  // the global tree-cover Source dropdown + threshold panels are inert
  // (the global layer is fully bypassed). Hide them and show a small
  // status note in the gap so the user knows why -- and isn't tempted
  // to fiddle with knobs that have no effect.
  //
  // Single source of truth: the existing source-driven threshold-panel
  // toggle (formerly inline in treecoverSourceSelect.onChange) is folded
  // into this helper too, so both paths can't disagree.
  // =============================================================================
  function updateGlobalForestInputsVisibility() {
    // Custom forest only counts as "active" when BOTH the §2 master
    // checkbox ("Enable custom data inputs") AND the per-dataset
    // nationalForest checkbox are ticked. Master off → custom data
    // is dormant regardless of the inner checkbox state, so the
    // global source must reappear. Fixes a bug where the global
    // dropdown stayed hidden after the user unticked the master.
    var masterActive = enableTreeCoverCustomCheckbox.getValue();
    var customActive = masterActive && nationalForest.checkbox.getValue();
    var mode         = nationalForest.modeSelect.getValue();
    var hideGlobal   = customActive && mode === 'Replace global';

    treecoverSourceRow.style().set('shown', !hideGlobal);
    globalSourceHiddenNote.style().set('shown', hideGlobal);

    if (hideGlobal) {
      treecoverPanel.style().set('shown', false);
      treecoverHeightPanel.style().set('shown', false);
    } else {
      // Restore source-driven sub-visibility (was the original logic
      // inside treecoverSourceSelect.onChange).
      var src = treecoverSourceSelect.getValue();
      var isHansen = (src === 'Hansen GFC');
      var isGlad   = (src === 'GLAD LULC');
      treecoverPanel.style().set('shown',       isHansen || !isGlad);
      treecoverHeightPanel.style().set('shown', isGlad   || !isHansen);
    }
  }

  // Re-evaluate global-controls visibility whenever the custom-forest
  // section changes state. Multiple onChange handlers stack in GEE UI,
  // so this composes cleanly with the factory's internal handler at
  // L3470 (which toggles the mode-select and year inputs).
  // Plus the §2 master toggle: when the user toggles "Enable custom
  // data inputs", we must re-evaluate so the global source dropdown
  // appears/disappears in sync.
  nationalForest.checkbox.onChange(updateGlobalForestInputsVisibility);
  nationalForest.modeSelect.onChange(updateGlobalForestInputsVisibility);
  enableTreeCoverCustomCheckbox.onChange(updateGlobalForestInputsVisibility);

  // Initial sync at startup -- mirrors the pattern at line 3683 for
  // updateRefineVisibility(). Placed after treeCoverContent so
  // treecoverSourceRow / globalSourceHiddenNote are in scope.
  updateGlobalForestInputsVisibility();

  // Initial sync of the refine subsection state. Deferred to here
  // (rather than at the end of the function definition) because the
  // function body references enableTreeCoverCustomCheckbox,
  // olwtcCreatesHint, and plantedCreatesHint — all defined between
  // the function and this call site.
  updateRefineVisibility();

  var treeCoverToggle = ui.Button({
    label: '▶ 2. Tree Cover',
    onClick: function() {
      var wasCollapsed = appState.ui.treeCoverCollapsed;
      if (wasCollapsed) {
        // Opening - close all others first
        collapseAllPanelsExcept('treeCover');
      }
      appState.ui.treeCoverCollapsed = !appState.ui.treeCoverCollapsed;
      treeCoverContent.style().set({shown: !appState.ui.treeCoverCollapsed});
      treeCoverToggle.setLabel(appState.ui.treeCoverCollapsed ? '▶ 2. Tree Cover' : '▼ 2. Tree Cover');
      updateLeftPanelWidth();
    },
    style: {stretch: 'horizontal', textAlign: 'left', padding: '3px 6px', margin: '1px', backgroundColor: '#f0f0f0'}
  });

  var treeCoverPanelCollapsible = ui.Panel({
    widgets: [treeCoverToggle, treeCoverContent],
    layout: ui.Panel.Layout.flow('vertical')
  });

  // Helper to create compact label+slider rows
  function createBufferRow(label, slider) {
    return ui.Panel({
      layout: ui.Panel.Layout.flow('horizontal'),
      widgets: [
        ui.Label(label, {width: '100px', margin: '6px 0 0 0'}),
        slider
      ],
      style: {margin: '0px'}
    });
  }

  // Helper to create compact label+widget rows for selects/sliders
  function createCompactRow(label, widget) {
    return ui.Panel({
      layout: ui.Panel.Layout.flow('horizontal'),
      widgets: [
        ui.Label(label, {margin: '6px 4px 0 0'}),
        widget
      ],
      style: {margin: '0px'}
    });
  }

  var slopePanel = ui.Panel({
    layout: ui.Panel.Layout.flow('horizontal'),
    widgets: [
      ui.Label('Slope (degrees) >', {margin: '6px 2px 0 0'}),
      slopeToKeepSlider
    ],
    style: {margin: '0px'}
  });

  // ANTHROPOGENIC PANEL — slope and protected areas with enable toggles
  // Batch 27.1: shown:false matches the new enableSlope default (false).
  var slopeControls = ui.Panel({
    widgets: [
      slopePanel,
      ui.Panel({widgets: [useCustomSlopeCheckbox, customSlopeInput], layout: ui.Panel.Layout.flow('vertical'), style: {margin: '0 0 4px 0'}})
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {margin: '0', shown: false}
  });
  // Batch 27.1: Buffer Exceptions OFF by default. Steep-slope and
  // protected-area rescues are ecologically meaningful but not all
  // users want them on first run; explicit opt-in avoids surprising
  // "primary forest in cropland" pixels in countries with sparse
  // protected-area coverage.
  var enableSlope = ui.Checkbox({
    label: 'Steep slope:',
    value: false,
    onChange: function(checked) {
      slopeControls.style().set({shown: checked});
      updateBufferExceptionsStatus();
      markNeedsUpdate();
    }
  });

  // Master "add to map" toggle for all input + buffer + exception layers.
  // Off by default to keep the EE Layers dropdown tidy; tick + Update
  // Analysis to surface them. Independent of the per-layer enable* flags
  // (which control whether the layer is COMPUTED). This only controls
  // whether the layer is ADDED to the map.
  var addInputLayersToMap = ui.Checkbox({
    label: 'Add input + buffer layers to map',
    value: false,
    onChange: function(v) {
      markNeedsUpdate();
      if (v) {
        updateMap();
      } else {
        var prefixes = ['Input: ', 'Buffer: ', 'Planted forest'];
        [map1, map2].forEach(function(m) {
          if (!m) return;
          var layers = m.layers();
          for (var i = 0; i < layers.length(); i++) {
            var lyr = layers.get(i);
            var n = lyr.getName();
            for (var p = 0; p < prefixes.length; p++) {
              if (n.indexOf(prefixes[p]) === 0) lyr.setShown(false);
            }
          }
        });
      }
    }
  });

  // Batch 27.1: shown:false matches the new enableProtectedAreas default.
  var protectedControls = ui.Panel({
    widgets: [
      createCompactRow('IUCN Categories:', wdpaPresetSelect),
      wdpaCategoryLabel, wdpaCategoryCheckboxPanel,
      createCompactRow('Established before:', wdpaYearSlider),
      nationalProtected.panel
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {margin: '0', shown: false}
  });
  var enableProtectedAreas = ui.Checkbox({
    label: 'Protected areas:',
    value: false,
    onChange: function(checked) {
      protectedControls.style().set({shown: checked});
      updateBufferExceptionsStatus();
      markNeedsUpdate();
    }
  });

  var bufferExceptionsContent = ui.Panel({
    widgets: [
      enableSlope, slopeControls,
      enableProtectedAreas, protectedControls
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, margin: '0 0 0 4px'}
  });
  var bufferExceptionsStatusLabel = ui.Label('', {fontSize: '10px', color: '#888', fontStyle: 'italic', margin: '0 0 0 4px', shown: false});

  function updateBufferExceptionsStatus() {
    var enabled = [];
    var notEnabled = [];
    if (enableSlope.getValue()) enabled.push('Steep slope'); else notEnabled.push('Steep slope');
    if (enableProtectedAreas.getValue()) enabled.push('Protected areas'); else notEnabled.push('Protected areas');
    var parts = [];
    if (enabled.length) parts.push('Enabled: ' + enabled.join(', '));
    if (notEnabled.length) parts.push('Not enabled: ' + notEnabled.join(', '));
    bufferExceptionsStatusLabel.setValue(parts.join('\n'));
    bufferExceptionsStatusLabel.style().set({shown: true, whiteSpace: 'pre'});
  }

  updateBufferExceptionsStatus();

  var bufferExceptionsToggle = ui.Button({
    label: '▸ Buffer Exceptions',
    onClick: function() {
      var s = bufferExceptionsContent.style().get('shown');
      bufferExceptionsContent.style().set({shown: !s});
      bufferExceptionsToggle.setLabel(s ? '▸ Buffer Exceptions' : '▾ Buffer Exceptions');
      updateLeftPanelWidth();
    },
    style: {fontSize: '11px', color: '#555', margin: '6px 0 2px 0', padding: '2px 4px', backgroundColor: '#f0f0f0'}
  });

  // Helper: create a combined checkbox + slider row for a buffer type
  // Slider hides when checkbox is unticked
  function createToggleBufferRow(label, slider) {
    var sliderPanel = ui.Panel({widgets: [slider], style: {stretch: 'horizontal', margin: '0'}});
    var checkbox = ui.Checkbox({
      label: label, value: true,
      onChange: function(checked) {
        sliderPanel.style().set({shown: checked});
        updateMasterBufferStatus();
        markNeedsUpdate();
      }
    });
    var row = ui.Panel({
      layout: ui.Panel.Layout.flow('horizontal'),
      widgets: [checkbox, sliderPanel],
      style: {margin: '0px'}
    });
    return {checkbox: checkbox, row: row, sliderPanel: sliderPanel};
  }

  var roadsToggle = createToggleBufferRow('Roads:', roadSmallBufferSlider);
  var builtUpSmallToggle = createToggleBufferRow('Small Built-Up:', builtUpSmallBufferSlider);
  var builtUpLargeToggle = createToggleBufferRow('Large Built-Up:', builtUpLargeBufferSlider);
  var agriToggle = createToggleBufferRow('Agriculture:', agriBufferSlider);

  // Expose checkboxes for use in analysis and settings
  var enableRoadsBuffer = roadsToggle.checkbox;
  var enableBuiltUpSmallBuffer = builtUpSmallToggle.checkbox;
  var enableBuiltUpLargeBuffer = builtUpLargeToggle.checkbox;
  var enableAgriBuffer = agriToggle.checkbox;

  masterBufferRow = ui.Panel({
    layout: ui.Panel.Layout.flow('horizontal'),
    widgets: [ui.Label('All:', {margin: '6px 4px 0 0'}), masterBufferSlider],
    style: {margin: '0px', shown: false}
  });
  individualBufferRows = [roadsToggle.row, builtUpSmallToggle.row, builtUpLargeToggle.row, agriToggle.row];

  // Custom data inputs toggle
  var enableCustomDataCheckbox = ui.Checkbox({
    label: 'Enable custom data inputs',
    value: false,
    onChange: function(checked) {
      nationalRoads.panel.style().set({shown: checked});
      nationalBuiltupSmall.panel.style().set({shown: checked});
      nationalBuiltupLarge.panel.style().set({shown: checked});
      nationalAgri.panel.style().set({shown: checked});
      nationalProtected.panel.style().set({shown: checked});
      useCustomSlopeCheckbox.style().set({shown: checked});
      if (!checked) customSlopeInput.style().set({shown: false});
      updateLeftPanelWidth();
    },
    style: {fontSize: '11px', color: '#555', margin: '6px 0 2px 0'}
  });

  // Batch 27.1: addInputLayersToMap moved to the BOTTOM of the panel
  // (was right under the section title). Distracting at the top; rarely
  // used. Default value (false) unchanged.
  var anthropogenicContent = ui.Panel({
    widgets: [
      ui.Label('Define Human Influence (m):', {fontWeight: 'bold', margin: '0 0 4px 0'}),
      useMasterBufferCheckbox,
      masterBufferRow,
      masterBufferStatusLabel,
      // Custom data input panels sit ABOVE the corresponding slider so
      // the user reads top-to-bottom as "data source → buffer
      // distance". When the master "Enable custom data inputs" box is
      // off, each panel is hidden, so visually the section collapses
      // back to just the sliders.
      nationalRoads.panel,
      roadsToggle.row,
      nationalBuiltupSmall.panel,
      builtUpSmallToggle.row,
      nationalBuiltupLarge.panel,
      builtUpLargeToggle.row,
      nationalAgri.panel,
      agriToggle.row,
      bufferExceptionsToggle,
      bufferExceptionsContent,
      bufferExceptionsStatusLabel,
      enableCustomDataCheckbox,
      addInputLayersToMap
    ],
    style: {shown: false, padding: '8px'}
  });

  // Hide custom data panels by default (shown when "Enable custom data inputs" is ticked)
  nationalRoads.panel.style().set({shown: false});
  nationalBuiltupSmall.panel.style().set({shown: false});
  nationalBuiltupLarge.panel.style().set({shown: false});
  nationalAgri.panel.style().set({shown: false});
  nationalProtected.panel.style().set({shown: false});
  useCustomSlopeCheckbox.style().set({shown: false});

  var anthropogenicToggle = ui.Button({
    label: '▶ 3. Human Influence',
    onClick: function() {
      var wasCollapsed = appState.ui.anthropogenicCollapsed;
      if (wasCollapsed) {
        collapseAllPanelsExcept('anthropogenic');
      }
      appState.ui.anthropogenicCollapsed = !appState.ui.anthropogenicCollapsed;
      anthropogenicContent.style().set({shown: !appState.ui.anthropogenicCollapsed});
      anthropogenicToggle.setLabel(appState.ui.anthropogenicCollapsed ? '▶ 3. Human Influence' : '▼ 3. Human Influence');
      updateLeftPanelWidth();
    },
    style: {stretch: 'horizontal', textAlign: 'left', padding: '3px 6px', margin: '1px', backgroundColor: '#f0f0f0'}
  });

  var anthropogenicPanel = ui.Panel({
    widgets: [anthropogenicToggle, anthropogenicContent],
    layout: ui.Panel.Layout.flow('vertical')
  });

  // CONNECTIVITY PANEL
  var connectivityControls = ui.Panel({
    widgets: [
      ui.Label('Pixels with too few forest neighbours within this radius are removed.', {fontSize: '11px', color: '#555', margin: '0 0 6px 0'}),
      ui.Label('Neighbourhood Radius (m):'), smoothRadiusForestSlider,
      ui.Label('Min. Density to Keep:'), smallPixelThresholdForestSlider
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {margin: '0'}
  });
  var enableRefineOutput = ui.Checkbox({
    label: 'Refine output:',
    value: true,
    onChange: function(checked) {
      connectivityControls.style().set({shown: checked});
      markNeedsUpdate();
    }
  });
  var connectivityContent = ui.Panel({
    widgets: [enableRefineOutput, connectivityControls],
    style: {shown: false, padding: '8px'}
  });

  var connectivityToggle = ui.Button({
    label: '▶ 4. Refine Output',
    onClick: function() {
      var wasCollapsed = appState.ui.connectivityCollapsed;
      if (wasCollapsed) {
        collapseAllPanelsExcept('connectivity');
      }
      appState.ui.connectivityCollapsed = !appState.ui.connectivityCollapsed;
      connectivityContent.style().set({shown: !appState.ui.connectivityCollapsed});
      connectivityToggle.setLabel(appState.ui.connectivityCollapsed ? '▶ 4. Refine Output' : '▼ 4. Refine Output');
      updateLeftPanelWidth();
    },
    style: {stretch: 'horizontal', textAlign: 'left', padding: '3px 6px', margin: '1px', backgroundColor: '#f0f0f0'}
  });

  var connectivityPanel = ui.Panel({
    widgets: [connectivityToggle, connectivityContent],
    layout: ui.Panel.Layout.flow('vertical')
  });

  // Implement accordion behavior - now that all panels are defined
  collapseAllPanelsExcept = function(exceptPanel) {
    if (exceptPanel !== 'dates' && !appState.ui.datesCollapsed) {
      appState.ui.datesCollapsed = true;
      datesContent.style().set({shown: false});
      datesToggle.setLabel('▶ 1. Time Period');
    }
    if (exceptPanel !== 'treeCover' && !appState.ui.treeCoverCollapsed) {
      appState.ui.treeCoverCollapsed = true;
      treeCoverContent.style().set({shown: false});
      treeCoverToggle.setLabel('▶ 2. Tree Cover');
    }
    if (exceptPanel !== 'anthropogenic' && !appState.ui.anthropogenicCollapsed) {
      appState.ui.anthropogenicCollapsed = true;
      anthropogenicContent.style().set({shown: false});
      anthropogenicToggle.setLabel('▶ 3. Human Influence');
    }
    if (exceptPanel !== 'connectivity' && !appState.ui.connectivityCollapsed) {
      appState.ui.connectivityCollapsed = true;
      connectivityContent.style().set({shown: false});
      connectivityToggle.setLabel('▶ 4. Refine Output');
    }
  };

  // =============================================================================
  // FLOATING LAYER PANEL (on map) - created as function for reuse
  // =============================================================================

  function createFloatingLayerPanel() {
    var layerScrollPanel = ui.Panel({
      widgets: [
        ui.Label('Layer Visibility', {fontWeight: 'bold', fontSize: '14px'}),
        ui.Label('─────────────────', {color: 'gray'}),
        ui.Checkbox({label: 'Primary Forest',        value: visibleLayers.primaryForest,       onChange: function(v) { visibleLayers.primaryForest       = v; toggleLayerByName('Primary Forest', v); }}),
        ui.Checkbox({label: 'Pre-refinement primary', value: visibleLayers.forestOutsideBuffers, onChange: function(v) { visibleLayers.forestOutsideBuffers = v; toggleLayerByName('Pre-refinement primary', v); }}),
        ui.Checkbox({label: 'Input: Tree cover',      value: visibleLayers.treeCover,            onChange: function(v) { visibleLayers.treeCover            = v; toggleLayerByName('Input: Tree cover', v); }}),
        ui.Checkbox({label: 'Naturally regenerating forest', value: visibleLayers.naturallyRegenerating, onChange: function(v) { visibleLayers.naturallyRegenerating = v; toggleLayerByName('Naturally regenerating forest', v); }}),
        ui.Checkbox({label: 'Forest',            value: visibleLayers.forest,               onChange: function(v) { visibleLayers.forest               = v; toggleLayerByName('Forest', v); }}),
        ui.Checkbox({label: 'Planted forest',         value: visibleLayers.plantations,          onChange: function(v) { visibleLayers.plantations          = v; toggleLayerByName('Planted forest', v); }}),
        ui.Label(''),
        ui.Label('Disturbance inputs:', {fontWeight: 'bold'}),
        ui.Checkbox({label: 'Agriculture',  value: visibleLayers.inputAgriculture,  onChange: function(v) { visibleLayers.inputAgriculture  = v; toggleLayerByName('Input: Agriculture', v); }}),
        ui.Checkbox({label: 'Roads',        value: visibleLayers.inputRoads,        onChange: function(v) { visibleLayers.inputRoads        = v; toggleLayerByName('Input: Roads', v); }}),
        ui.Checkbox({label: 'Built-up',     value: visibleLayers.inputBuiltupSmall, onChange: function(v) { visibleLayers.inputBuiltupSmall = v; toggleLayerByName('Input: Small Built-up', v); }}),
        ui.Checkbox({label: 'Built-up Large', value: visibleLayers.inputBuiltupLarge, onChange: function(v) { visibleLayers.inputBuiltupLarge = v; toggleLayerByName('Input: Large Built-up', v); }}),
        ui.Label(''),
        ui.Label('Buffers:', {fontWeight: 'bold'}),
        ui.Checkbox({label: 'Agriculture',  value: visibleLayers.agriBuffer,       onChange: function(v) { visibleLayers.agriBuffer       = v; toggleLayerByName('Buffer: Agriculture', v); }}),
        ui.Checkbox({label: 'Roads',        value: visibleLayers.roadSmallBuffer, onChange: function(v) { visibleLayers.roadSmallBuffer = v; toggleLayerByName('Buffer: Roads', v); }}),
        ui.Checkbox({label: 'Built-up Large', value: visibleLayers.builtLargeBuffer, onChange: function(v) { visibleLayers.builtLargeBuffer = v; toggleLayerByName('Buffer: Large Built-up', v); }}),
        ui.Label(''),
        ui.Label('Other:', {fontWeight: 'bold'}),
        ui.Checkbox({label: 'Slope',           value: visibleLayers.slope,          onChange: function(v) { visibleLayers.slope          = v; toggleLayerByName('Input: Slope', v); }}),
        ui.Checkbox({label: 'Protected Areas', value: visibleLayers.protectedAreas, onChange: function(v) { visibleLayers.protectedAreas = v; toggleLayerByName('Input: Protected', v); }})
      ],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {padding: '8px'}
    });

    var layerControlContent = ui.Panel({
      widgets: [layerScrollPanel],
      style: {shown: !appState.ui.layersPanelCollapsed, width: '200px', maxHeight: '400px', border: '1px solid #ccc', backgroundColor: 'rgba(255, 255, 255, 0.95)'}
    });

    var layerToggleButton = ui.Button({
      label: appState.ui.layersPanelCollapsed ? '▶ Layers' : '▼ Layers',
      onClick: function() {
        appState.ui.layersPanelCollapsed = !appState.ui.layersPanelCollapsed;
        layerControlContent.style().set({shown: !appState.ui.layersPanelCollapsed});
        layerToggleButton.setLabel(appState.ui.layersPanelCollapsed ? '▶ Layers' : '▼ Layers');
      },
      style: {width: '90px', padding: '4px', margin: '4px'}
    });

    return ui.Panel({
      widgets: [layerToggleButton, layerControlContent],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {position: 'top-left', margin: '8px 0px 0px 8px', padding: '0px', backgroundColor: 'rgba(255, 255, 255, 0.95)', border: '2px solid #ccc'}
    });
  }

  // =============================================================================
  // LEGEND PANEL (floating on map, bottom-left)
  // =============================================================================

  function createLegendItem(color, label, indent) {
    var colorBox = ui.Label({
      style: {
        backgroundColor: color,
        padding: '8px',
        margin: '0 4px 0 0',
        border: '1px solid #666'
      }
    });
    var description = ui.Label({
      value: label,
      style: {margin: '0', fontSize: '11px'}
    });
    return ui.Panel({
      widgets: [colorBox, description],
      layout: ui.Panel.Layout.flow('horizontal'),
      style: {margin: indent ? '1px 0 1px 14px' : '2px 0'}
    });
  }

  // Canonical legend definition: visibleLayers key → [colour, label]
  // Batch 27.1: Forest group reordered with HEADLINE OUTPUT FIRST
  // (Primary forest), then walking back DOWN the refinement chain
  // (Pre-refinement primary -> Naturally regenerating -> Forest ->
  // Tree cover) so the user reads top-to-bottom as "what I made"
  // preceding "what it was made from". Planted forest last as a
  // sibling category (gold, not in the green ramp).
  var LEGEND_ENTRIES = [
    {key: 'primaryForest',         color: '#0b3d1f', label: 'Primary Forest',           group: 'Forest'},
    {key: 'forestOutsideBuffers',  color: '#4caf50', label: 'Pre-refinement primary',   group: 'Forest'},
    {key: 'naturallyRegenerating', color: '#81c784', label: 'Naturally regenerating forest', group: 'Forest'},
    {key: 'forest',                color: '#90EE90', label: 'Forest',                   group: 'Forest'},
    {key: 'treeCover',             color: '#c8e6c9', label: 'Input',                    group: 'Forest'},
    {key: 'plantations',           color: '#d4a017', label: 'Planted forest',           group: 'Forest'},
    {key: 'agriBuffer',          color: '#ffcc00', label: 'Buffer: Agriculture',    group: 'Human Influence'},
    {key: 'roadSmallBuffer',     color: '#ff6600', label: 'Buffer: Roads',          group: 'Human Influence'},
    {key: 'builtSmallBuffer',    color: '#cc00cc', label: 'Buffer: Small Built-up', group: 'Human Influence'},
    {key: 'builtLargeBuffer',    color: '#3333cc', label: 'Buffer: Large Built-up', group: 'Human Influence'},
    {key: 'inputRoads',          color: '#993d00', label: 'Input: Roads',           group: 'Human Influence'},
    {key: 'inputBuiltupSmall',   color: '#800080', label: 'Input: Small Built-up',  group: 'Human Influence'},
    {key: 'inputBuiltupLarge',   color: '#1a1a80', label: 'Input: Large Built-up',  group: 'Human Influence'},
    {key: 'inputAgriculture',    color: '#b38f00', label: 'Input: Agriculture',     group: 'Human Influence'},
    {key: 'protectedAreas',      color: '#00cccc', label: 'Input: Protected Areas', group: 'Buffer Exceptions'},
    {key: 'slope',               color: '#708090', label: 'Input: Slope',           group: 'Buffer Exceptions'},
    {key: 'flii', group: 'Reference', title: 'FLII (forest integrity)', classes: [
      {color: '#0000ff', label: 'high (≥ 9.6)'},
      {color: '#ffa500', label: 'medium (6.0–9.6)'}
    ]},
    {key: 'fdap',                color: '#0000ff', label: 'Forest Persistence (FDaP)  >0.90', group: 'Reference'},
    {key: 'refCustom1',          color: '#e377c2', label: 'Reference: Custom 1',                  group: 'Reference'},
    {key: 'refCustom2',          color: '#17becf', label: 'Reference: Custom 2',                  group: 'Reference'}
  ];

  function createLegendPanel() {
    var legendItemsPanel = ui.Panel({
      widgets: [ui.Label('Legend', {fontWeight: 'bold', fontSize: '12px', margin: '0 0 4px 0'})],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {padding: '6px'}
    });

    // Read actual layer visibility from the map (handles native layer control)
    function syncVisibleLayersFromMap() {
      // Check map2 (always exists), fall back to map1
      var m = map2 || map1;
      if (!m) return;
      var layers = m.layers();
      // Build a set of visible layer names from the map
      var visibleNames = {};
      for (var i = 0; i < layers.length(); i++) {
        var layer = layers.get(i);
        if (layer.getShown()) {
          visibleNames[layer.getName()] = true;
        }
      }
      // Update visibleLayers state from map reality
      // Map layer names back to visibleLayers keys
      var NAME_TO_KEY = {
        'Primary Forest': 'primaryForest',
        'Primary forest': 'primaryForest',
        'Pre-refinement primary': 'forestOutsideBuffers',
        'Input': 'treeCover',
        'Input: Tree cover': 'treeCover',
        'Forest': 'forest',
        'Naturally regenerating forest': 'naturallyRegenerating',
        'Planted forest': 'plantations',
        'Buffer: Agriculture': 'agriBuffer',
        'Buffer: Roads': 'roadSmallBuffer',
        'Buffer: Small Built-up': 'builtSmallBuffer',
        'Buffer: Large Built-up': 'builtLargeBuffer',
        'Input: Roads': 'inputRoads',
        'Input: Small Built-up': 'inputBuiltupSmall',
        'Input: Large Built-up': 'inputBuiltupLarge',
        'Input: Agriculture': 'inputAgriculture'
      };
      // Reset all to false, then set visible ones
      Object.keys(visibleLayers).forEach(function(k) { visibleLayers[k] = false; });
      Object.keys(visibleNames).forEach(function(name) {
        if (NAME_TO_KEY[name]) {
          visibleLayers[NAME_TO_KEY[name]] = true;
        }
        // Prefix match for slope / protected / forest (dynamic names)
        if (name.indexOf('Input: Slope') === 0) visibleLayers.slope = true;
        if (name.indexOf('Input: Protected') === 0) visibleLayers.protectedAreas = true;
        if (name.indexOf('Reference: FLII') === 0) visibleLayers.flii = true;
        if (name.indexOf('Reference: Forest Persistence') === 0) visibleLayers.fdap = true;
        if (name === 'Reference: Custom 1') visibleLayers.refCustom1 = true;
        if (name === 'Reference: Custom 2') visibleLayers.refCustom2 = true;
        if (name.indexOf('Input: Tree cover') === 0) visibleLayers.treeCover = true;
        // 'Forest' handled by exact match in NAME_TO_KEY above -- no
        // prefix here, would over-match 'Forest outside buffers'.
      });
    }

    var _initialBuild = true;

    // Rebuild legend from visibleLayers state
    function refreshLegend() {
      // Clear all except the title label
      while (legendItemsPanel.widgets().length() > 1) {
        legendItemsPanel.remove(legendItemsPanel.widgets().get(1));
      }
      // Starter state (e.g. before a country is picked): nothing is on the
      // map yet, so show an empty legend rather than the visibleLayers
      // defaults (which would list forest layers that aren't drawn). Don't
      // syncVisibleLayersFromMap() here -- it would clobber the
      // visibleLayers defaults updateMap relies on for initial visibility.
      if (_initialBuild) {
        _initialBuild = false;
        legendItemsPanel.add(ui.Label('(no layers visible)', {fontSize: '11px', color: '#888'}));
        return;
      }
      syncVisibleLayersFromMap();
      var lastGroup = '';
      var anyShown = false;
      LEGEND_ENTRIES.forEach(function(entry) {
        if (visibleLayers[entry.key]) {
          if (entry.group !== lastGroup) {
            legendItemsPanel.add(ui.Label(entry.group + ':', {fontWeight: 'bold', fontSize: '11px', margin: '4px 0 2px 0'}));
            lastGroup = entry.group;
          }
          if (entry.classes) {
            // Multi-class layer: title row, then indented class swatches
            // (GIS-style) so it reads as one layer with its categories.
            legendItemsPanel.add(ui.Label(entry.title, {fontSize: '11px', margin: '2px 0 0 4px'}));
            entry.classes.forEach(function(c) {
              legendItemsPanel.add(createLegendItem(c.color, c.label, true));
            });
          } else {
            legendItemsPanel.add(createLegendItem(entry.color, entry.label));
          }
          anyShown = true;
        }
      });
      if (!anyShown) {
        legendItemsPanel.add(ui.Label('(no layers visible)', {fontSize: '11px', color: '#888'}));
      }
    }

    // Initial build -- empty legend until the first analysis runs.
    refreshLegend();

    // Store refresh callback globally so toggleLayerByName can trigger it
    _legendRefreshFns.push(refreshLegend);

    var legendContent = ui.Panel({
      widgets: [legendItemsPanel],
      style: {shown: true, width: '180px', border: '1px solid #ccc', backgroundColor: 'rgba(255, 255, 255, 0.95)'}
    });

    var legendRefreshButton = ui.Button({
      label: '↻ Refresh',
      onClick: refreshLegend,
      // Bumped to 80x32 with text label "↻ Refresh" so the button is
      // visibly clickable and self-explanatory. Earlier versions used
      // a tiny 24x24 icon-only button that was hard to find/hit and
      // the ↻ glyph didn't always render.
      style: {fontSize: '11px', padding: '2px 6px', margin: '4px 0 4px 2px', width: '80px', height: '32px'}
    });

    var legendToggleButton = ui.Button({
      label: '▼ Legend',
      onClick: function() {
        var isShown = legendContent.style().get('shown');
        legendContent.style().set({shown: !isShown});
        legendToggleButton.setLabel(isShown ? '▶ Legend' : '▼ Legend');
      },
      style: {width: '80px', padding: '4px', margin: '4px', fontSize: '11px'}
    });

    return ui.Panel({
      widgets: [
        ui.Panel([legendToggleButton, legendRefreshButton], ui.Panel.Layout.flow('horizontal'), {margin: '0', padding: '0'}),
        legendContent
      ],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {position: 'bottom-left', margin: '0px 0px 8px 8px', padding: '0px', backgroundColor: 'rgba(255, 255, 255, 0.95)', border: '2px solid #ccc'}
    });
  }

  // =============================================================================
  // UN MAP DISCLAIMER (floating, bottom-right)
  // =============================================================================

  function createDisclaimerPanel() {
    var disclaimerText = 'The designations employed and the presentation of material on this map ' +
      'do not imply the expression of any opinion whatsoever on the part of the Secretariat of the ' +
      'United Nations concerning the legal status of any country, territory, city or area or of its ' +
      'authorities, or concerning the delimitation of its frontiers or boundaries. Dotted line represents ' +
      'approximately the Line of Control in Jammu and Kashmir agreed upon by India and Pakistan. The ' +
      'final status of Jammu and Kashmir has not yet been agreed upon by the parties. Final boundary ' +
      'between the Republic of Sudan and the Republic of South Sudan has not yet been determined. ' +
      'Final status of the Abyei area is not yet determined. A dispute exists between the Governments ' +
      'of Argentina and the United Kingdom of Great Britain and Northern Ireland concerning sovereignty ' +
      'over the Falkland Islands (Malvinas).';

    var disclaimerContent = ui.Panel({
      widgets: [ui.Label(disclaimerText, {fontSize: '10px', color: '#555', margin: '4px'})],
      style: {shown: false, width: '320px', backgroundColor: 'rgba(255,255,255,0.95)', border: '1px solid #ccc', padding: '4px'}
    });

    var disclaimerButton = ui.Button({
      label: 'ℹ Map disclaimer',
      onClick: function() {
        var s = disclaimerContent.style().get('shown');
        disclaimerContent.style().set({shown: !s});
      },
      style: {fontSize: '10px', color: '#555', padding: '2px 6px', margin: '0', backgroundColor: 'rgba(255,255,255,0.85)', border: '1px solid #ccc'}
    });

    return ui.Panel({
      widgets: [disclaimerButton, disclaimerContent],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {position: 'bottom-right', margin: '0 8px 8px 0', padding: '0'}
    });
  }

  // =============================================================================
  // STATS PANEL (collapsible, right side)
  // =============================================================================

  var statsWidgets = [
    ui.Panel([showStatsButton, statsInfoButton], ui.Panel.Layout.flow('horizontal'), {margin: '0'}),
    statsInfoContent,
    clearStatsButton,
    ui.Panel([statsScaleLabel, statsScaleSlider], ui.Panel.Layout.flow('horizontal'), {stretch: 'horizontal', margin: '0 0 0 8px'}),
    areaStatsPanel
  ];
  if (!IS_PUBLISHED_APP) {
    statsWidgets.push(exportStatsPanel);
  }
  statsWidgets.push(exportStatusLabel);

  var statsContent = ui.Panel({
    widgets: statsWidgets,
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, padding: '8px', backgroundColor: 'rgba(255,255,255,0.9)'}
  });

  var statsToggle = ui.Button({
    label: '▶ Area Statistics',
    onClick: function() {
      var isShown = statsContent.style().get('shown');
      if (!isShown) {
        closeConfig();
        downloadsContent.style().set({shown: false});
        downloadsToggle.setLabel('▶ Outputs');
        closeValidation();
        closeAbout();
      }
      statsContent.style().set({shown: !isShown});
      statsToggle.setLabel(isShown ? '▶ Area Statistics' : '▼ Area Statistics');
      updateRightPanelWidth();
    },
    style: {stretch: 'horizontal', textAlign: 'left', padding: '3px 6px', margin: '1px', backgroundColor: '#f0f0f0'}
  });

  var statsPanel = ui.Panel({
    widgets: [statsToggle, statsContent],
    layout: ui.Panel.Layout.flow('vertical')
  });

  // =============================================================================
  // SETTINGS PANEL (collapsible, right side)
  // =============================================================================

  var exportSettingsButton = ui.Button({label: 'Save Settings', onClick: exportSettings, style: {margin: '4px 0px', fontSize: '11px'}});
  var importSettingsButton = ui.Button({label: 'Load Settings', onClick: showTextInput, style: {margin: '4px 0px', fontSize: '11px'}});

  // In-browser counterpart of the run metadata sidecar -- downloads the
  // current config + run snapshot without queueing a Drive export. Useful
  // when the user wants the run record before (or instead of) launching
  // the export-all batch. Year reported is yearSelector1 (the primary).
  function downloadRunBundle() {
    var selectedCountry = countrySelector.getValue();
    var countryInfo = selectedCountry ? gaulLut.GAUL_LUT[gaulLut.nameToCode(selectedCountry)] : null;
    var iso3 = countryInfo ? countryInfo.iso3 :
      (selectedCountry ? cleanCountryName(selectedCountry).substring(0, 3).toUpperCase() : 'XXX');
    var year = parseInt(yearSelector1.getValue());
    var scale = exportRasterScaleSlider.getValue();
    var bundle = buildRunBundle(year, scale, iso3, '<not-yet-exported>', false);
    var bundleFC = ee.FeatureCollection([ee.Feature(null, bundle)]);
    var url = bundleFC.getDownloadURL({
      format: 'json',
      filename: (iso3 ? iso3 + '_' : '') + 'gee_run_metadata_' + year + '_' + scale + 'm.json'
    });

    if (downloadLinkPanel) {
      ui.root.widgets().remove(downloadLinkPanel);
    }
    var downloadLink = ui.Label({
      value: 'Download Run Metadata (' + iso3 + ' ' + year + ' ' + scale + 'm)',
      style: {color: 'blue', textDecoration: 'underline'},
      targetUrl: url
    });
    var closeButton = ui.Button({
      label: '✖',
      style: {margin: '0 0 0 10px'},
      onClick: function() {
        ui.root.widgets().remove(downloadLinkPanel);
        downloadLinkPanel = null;
      }
    });
    downloadLinkPanel = ui.Panel({
      widgets: [downloadLink, closeButton],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {margin: '10px 0'}
    });
    ui.root.widgets().add(downloadLinkPanel);
  }

  var downloadRunBundleButton = ui.Button({
    label: 'Download Run Metadata',
    onClick: downloadRunBundle,
    style: {margin: '4px 0px', fontSize: '11px'}
  });

  // Reset function to restore all parameters to defaults
  function resetToDefaults() {
    // Tree Cover
    treecoverThresholdSlider.setValue(10);
    treecoverHeightThresholdSlider.setValue(5);
    treecoverSourceSelect.setValue('GLAD LULC');
    
    // Anthropogenic buffers
    useMasterBufferCheckbox.setValue(false);
    masterBufferSlider.setValue(1000);
    enableRoadsBuffer.setValue(true);
    enableBuiltUpSmallBuffer.setValue(true);
    enableBuiltUpLargeBuffer.setValue(true);
    enableAgriBuffer.setValue(true);
    roadSmallBufferSlider.setValue(1000);
    builtUpSmallBufferSlider.setValue(1000);
    builtUpLargeBufferSlider.setValue(1000);
    agriBufferSlider.setValue(1000);
    
    // Protection
    enableSlope.setValue(false);
    enableProtectedAreas.setValue(false);
    enableRefineOutput.setValue(true);
    slopeToKeepSlider.setValue(45);
    wdpaYearSlider.setValue(current_year - 30);
    wdpaPresetSelect.setValue('Strict (Ia, Ib, II)');
    
    // Connectivity
    smoothRadiusForestSlider.setValue(2000);
    smallPixelThresholdForestSlider.setValue(0.5);
    
    // Reset plantations and custom assets
    includePlantationsCheckbox.setValue(false);
    excludeAgricultureFromForestCheckbox.setValue(false);
    inputCategorySelect.setValue(null);
    fraAlignedCheckbox.setValue(false);
    refineInputCheckbox.setValue(false);
    updateRefineVisibility();

    // Reset national data overrides
    nationalForest.reset();
    nationalRoads.reset();
    nationalBuiltupSmall.reset();
    nationalBuiltupLarge.reset();
    nationalAgri.reset();
    nationalOLWTC.reset();
    nationalPlantations.reset();
    nationalProtected.reset();
    useCustomSlopeCheckbox.setValue(false);
    customSlopeInput.setValue('');
    customSlopeInput.style().set('shown', false);

    // Reset layer visibility to defaults
    resetVisibleLayers();
  }

  var resetSettingsButton = ui.Button({label: 'Reset Defaults', onClick: resetToDefaults, style: {width: '90px', margin: '2px 0px', fontSize: '10px', color: '#888'}});

  // Batch 27.1: tiny grey hint labels clarify that Save/Load Settings
  // and Download Run Metadata serve different purposes:
  //   - Save / Load Settings = portable config (manual, shareable with
  //     colleagues; excludes run-specific fields like timestamp).
  //   - Run Metadata = per-run snapshot (auto-emitted with Drive exports;
  //     records exactly what produced a given output).
  var settingsHintSettings = ui.Label(
    'Portable config — share with colleagues. Excludes run-specific ' +
    'fields like timestamp.',
    {fontSize: '10px', color: '#888', fontStyle: 'italic',
    margin: '0 0 6px 0'}
  );
  var settingsHintMetadata = ui.Label(
    'Run snapshot — records exactly what produced this run (auto-emitted ' +
    'alongside Drive exports). Use to trace what produced an output.',
    {fontSize: '10px', color: '#888', fontStyle: 'italic',
    margin: '6px 0 0 0'}
  );

  var settingsContent = ui.Panel({
    widgets: [
      ui.Label('Config', {fontWeight: 'bold', fontSize: '13px', margin: '0 0 6px 0', color: '#333'}),
      exportSettingsButton, importSettingsButton, settingsHintSettings,
      downloadRunBundleButton, settingsHintMetadata,
      resetSettingsButton
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, padding: '8px', backgroundColor: 'rgba(255,255,255,0.9)'}
  });

  // settingsToggle and settingsPanel removed — Config is now controlled
  // exclusively from the top-bar configButton (⚙).

  // =============================================================================
  // OUTPUTS PANEL (collapsible, right side)
  // =============================================================================

  var saveDataWidgets = [
    ui.Label('Save to computer (experimental)', {fontWeight: 'bold', fontSize: '13px', margin: '6px 0 4px 0', color: '#222'}),
    downloadPanel
  ];
  if (!IS_PUBLISHED_APP) {
    saveDataWidgets.push(ui.Panel({
      widgets: [],
      style: {
        height: '1px',
        margin: '8px 0 6px 0',
        backgroundColor: '#cccccc',
        stretch: 'horizontal'
      }
    }));
    saveDataWidgets.push(ui.Label('Save to Drive', {fontWeight: 'bold', fontSize: '13px', margin: '6px 0 4px 0', color: '#222'}));
    saveDataWidgets.push(exportRastersPanel);
  } else {
    saveDataWidgets.push(ui.Panel({
      widgets: [],
      style: {height: '1px', margin: '8px 0 6px 0', backgroundColor: '#cccccc', stretch: 'horizontal'}
    }));
    saveDataWidgets.push(ui.Label('Save to Drive', {fontWeight: 'bold', fontSize: '13px', margin: '6px 0 2px 0', color: '#999'}));
    saveDataWidgets.push(ui.Label(
      'Not available in published app — requires Google Drive access for the user. ' +
      'Published apps run under a single shared account. Use Save to computer instead, ' +
      'or run the script in the GEE Code Editor for Drive exports.',
      {fontSize: '10px', color: '#888', fontStyle: 'italic', margin: '0 0 4px 0'}));
  }

  var downloadsContent = ui.Panel({
    widgets: saveDataWidgets,
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, padding: '8px', backgroundColor: 'rgba(255,255,255,0.9)'}
  });

  var downloadsToggle = ui.Button({
    label: '▶ Outputs',
    onClick: function() {
      var isShown = downloadsContent.style().get('shown');
      if (!isShown) {
        statsContent.style().set({shown: false});
        statsToggle.setLabel('▶ Area Statistics');
        closeConfig();
        closeValidation();
        closeAbout();
      }
      downloadsContent.style().set({shown: !isShown});
      downloadsToggle.setLabel(isShown ? '▶ Outputs' : '▼ Outputs');
      updateRightPanelWidth();
    },
    style: {stretch: 'horizontal', textAlign: 'left', padding: '3px 6px', margin: '1px', backgroundColor: '#d4edda'}
  });

  var downloadsPanel = ui.Panel({
    widgets: [downloadsToggle, downloadsContent],
    layout: ui.Panel.Layout.flow('vertical')
  });

  // aboutToggle and aboutPanel removed — About is now controlled
  // exclusively from the top-bar aboutButton (ⓘ).

  // =============================================================================
  // VALIDATION PANEL (collapsible, right side)
  // =============================================================================

  // Validation reference layers (FLII / FDaP / Custom) are comparison
  // overlays INDEPENDENT of the primary-forest analysis. Toggling one
  // should add/remove just that overlay -- NOT re-run the whole analysis.
  // buildReferenceLayers() returns the enabled overlays (shared by the
  // full run in addLayersToMap and the targeted toggle below).
  var REFERENCE_LAYER_NAMES = [
    'Reference: FLII (high/med)',
    'Reference: Forest Persistence (FDaP)',
    'Reference: Custom 1',
    'Reference: Custom 2'
  ];

  function buildReferenceLayers(country_and_buffer_mask) {
    var refs = [];
    if (validationFliiCheckbox.getValue()) {
      var flii = ee.Image("users/openforisearthmap/World_EarthMap/flii_earth_20190824");
      var low = 6.0, high = 9.6;
      var flii_class = flii.expression(
        "(b1 > low) ? ((b1 < high) ? 2 : 3) : 0", {b1: flii, low: low, high: high}
      ).updateMask(country_and_buffer_mask).selfMask();
      refs.push({img: flii_class, vis: {min: 2, max: 3, palette: ["orange", "blue"]},
                 name: "Reference: FLII (high/med)", opacity: 1});
    }
    if (validationFdapCheckbox.getValue()) {
      var forestPersistence = ee.Image("projects/forestdatapartnership/assets/community_forests/ForestPersistence_2020")
          .updateMask(country_and_buffer_mask).selfMask();
      refs.push({img: forestPersistence.gt(.90), vis: {min: 0, max: 1, palette: ["white", "blue"]},
                 name: "Reference: Forest Persistence (FDaP)", opacity: 1});
    }
    if (customRef1.enableCheckbox.getValue()) {
      var ref1Path = customRef1.assetInput.getValue();
      if (ref1Path && ref1Path.trim() !== '') {
        var ref1Img = preprocessAsset(ref1Path.trim(), customRef1.prepUi.getConfig())
            .updateMask(country_and_buffer_mask).selfMask();
        refs.push({img: ref1Img, vis: {min: 0, max: 1, palette: ['white', '#e377c2']},
                   name: 'Reference: Custom 1', opacity: 0.7});
      }
    }
    if (customRef2.enableCheckbox.getValue()) {
      var ref2Path = customRef2.assetInput.getValue();
      if (ref2Path && ref2Path.trim() !== '') {
        var ref2Img = preprocessAsset(ref2Path.trim(), customRef2.prepUi.getConfig())
            .updateMask(country_and_buffer_mask).selfMask();
        refs.push({img: ref2Img, vis: {min: 0, max: 1, palette: ['white', '#17becf']},
                   name: 'Reference: Custom 2', opacity: 0.7});
      }
    }
    return refs;
  }

  // Targeted toggle: swap only the Reference overlays on the map(s) --
  // no full re-run. Country mask is cheap to rebuild (lazy EE). Falls
  // back to markNeedsUpdate when no country / disabled-map mode.
  function refreshReferenceLayers() {
    var selectedCountry = countrySelector.getValue();
    if (!selectedCountry) { markNeedsUpdate(); return; }
    if (disableMapCheckbox.getValue()) { return; }
    var country_clip = getCountryClip(selectedCountry);
    var country_buffer = makeDistanceBuffer(country_clip, country_buffer_threshold, fastBuffer);
    var country_and_buffer_mask = country_buffer.where(country_clip, 1).selfMask();
    var refs = buildReferenceLayers(country_and_buffer_mask);
    [map1, map2].forEach(function(m) {
      if (!m) return;
      var layers = m.layers();
      for (var i = layers.length() - 1; i >= 0; i--) {
        if (REFERENCE_LAYER_NAMES.indexOf(layers.get(i).getName()) !== -1) {
          layers.remove(layers.get(i));
        }
      }
      refs.forEach(function(r) { m.addLayer(r.img, r.vis, r.name, true, r.opacity); });
    });
    // Keep the legend in sync (reference layers appear in it).
    _legendRefreshFns.forEach(function(fn) { fn(); });
  }

  var validationFliiCheckbox = ui.Checkbox({
    label: 'FLII (high/medium integrity)',
    value: false,
    onChange: refreshReferenceLayers
  });

  var validationFdapCheckbox = ui.Checkbox({
    label: 'Forest Persistence (FDaP)',
    value: false,
    onChange: refreshReferenceLayers
  });

  // -- Custom reference layer input factory --
  function createValidationInput(label, index) {
    var layerName = 'Reference: Custom ' + index;
    var enableCheckbox = ui.Checkbox({
      label: label,
      value: false,
      onChange: refreshReferenceLayers,
      style: {fontWeight: 'bold', fontSize: '10px', margin: '6px 0 2px 0'}
    });
    var assetInput = ui.Textbox({
      placeholder: 'asset path or gs:// URI',
      style: {fontSize: '10px', stretch: 'horizontal'}
    });
    var prepUi = createPreprocessingUi();
    prepUi.panel.style().set('shown', false);

    var panel = ui.Panel({
      widgets: [
        enableCheckbox,
        assetInput,
        prepUi.panel
      ],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {margin: '0 0 4px 0', padding: '4px', backgroundColor: '#f8f8f8',
              border: '1px solid #e0e0e0'}
    });

    return {panel: panel, enableCheckbox: enableCheckbox, assetInput: assetInput, prepUi: prepUi};
  }

  var customRef1 = createValidationInput('Custom reference layer 1', 1);
  var customRef2 = createValidationInput('Custom reference layer 2', 2);
  customRef1.panel.style().set({shown: false});
  customRef2.panel.style().set({shown: false});

  var enableCustomValidationCheckbox = ui.Checkbox({
    label: 'Enable custom inputs',
    value: false,
    onChange: function(checked) {
      customRef1.panel.style().set({shown: checked});
      customRef2.panel.style().set({shown: checked});
    },
    style: {fontSize: '11px', color: '#555', margin: '6px 0 2px 0'}
  });

  var validationContent = ui.Panel({
    widgets: [
      ui.Label('⚠ Experimental', {fontWeight: 'bold', fontSize: '11px',
        color: '#b35900', margin: '0 0 4px 0'}),
      ui.Label(
        'Compare outputs to existing maps. ' +
        'For validation and sampling see the QGIS plugin ' +
        'and Collect Earth Online (CEO) workflows.',
        {fontSize: '10px', color: '#666', fontStyle: 'italic',
         margin: '4px 0 8px 0'}),
      ui.Label('Reference layers:', {fontWeight: 'bold', fontSize: '11px', margin: '4px 0 2px 0'}),
      validationFliiCheckbox,
      validationFdapCheckbox,
      enableCustomValidationCheckbox,
      customRef1.panel,
      customRef2.panel
    ],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {shown: false, padding: '8px', backgroundColor: 'rgba(255,255,255,0.9)'}
  });

  var validationToggle = ui.Button({
    label: '▶ Validation',
    onClick: function() {
      var isShown = validationContent.style().get('shown');
      if (!isShown) {
        statsContent.style().set({shown: false});
        statsToggle.setLabel('▶ Area Statistics');
        downloadsContent.style().set({shown: false});
        downloadsToggle.setLabel('▶ Outputs');
        closeConfig();
        closeAbout();
      }
      validationContent.style().set({shown: !isShown});
      validationToggle.setLabel(isShown ? '▶ Validation' : '▼ Validation');
      updateRightPanelWidth();
    },
    style: {stretch: 'horizontal', textAlign: 'left', padding: '3px 6px', margin: '1px', backgroundColor: '#e8f4f8'}
  });

  var validationPanel = ui.Panel({
    widgets: [validationToggle, validationContent],
    layout: ui.Panel.Layout.flow('vertical')
  });

  // =============================================================================
  // LAYOUT PANELS
  // =============================================================================

  // Left panel with collapsible sections and scroll
  var leftPanel = ui.Panel({
    widgets: [runButton, disableMapCheckbox, disableMapHint, datesPanelCollapsible, treeCoverPanelCollapsible, anthropogenicPanel, connectivityPanel],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {width: '310px', backgroundColor: 'rgba(255, 255, 255, 0.95)', padding: '2px', maxHeight: '600px'}
  });

  // Right panel: Stats, Outputs, Validation have toggle buttons;
  // Config + About are headless (controlled from the top-bar ⚙ and ⓘ buttons).
  var rightPanel = ui.Panel({
    widgets: [aboutContent, settingsContent, statsPanel, downloadsPanel, validationPanel],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {width: '310px', backgroundColor: 'rgba(255, 255, 255, 0.95)', padding: '2px', maxHeight: '600px'}
  });

  // Variable to keep track of the download link panel
  var downloadLinkPanel;

  // Add a loading label
  var loadingLabel = ui.Label({
    value: 'Loading...',
    style: {color: 'red', fontWeight: 'bold', shown: false}
  });

  // Function to collect current settings
  function collectSettings() {
    var settings = {
      'Country': countrySelector.getValue(),
      'Year 1': yearSelector1.getValue(),
      'Year 2': yearSelector2.getValue(),
      'Treecover Threshold (%)': treecoverThresholdSlider.getValue(),
      'GLAD Treecover Height (m)': treecoverHeightThresholdSlider.getValue(),
      'Road Small Buffer (m)': roadSmallBufferSlider.getValue(),
      'Built-Up Small Buffer (m)': builtUpSmallBufferSlider.getValue(),
      'Built-Up Large Buffer (m)': builtUpLargeBufferSlider.getValue(),
      'Slope to keep (degrees)': slopeToKeepSlider.getValue(),
      'Agriculture Buffer (m)': agriBufferSlider.getValue(),
      // 'Other Natural Buffer (m)': otherNatBufferSlider.getValue(),
      'Forest Smoothing Radius (m)': smoothRadiusForestSlider.getValue(),
      'Forest Smoothing Threshold': smallPixelThresholdForestSlider.getValue(),
      // 'Use Accurate Distance Buffers': fastBufferCheckbox.getValue(),
      // 'Include GISD': includeGISDCheckbox.getValue(),
      // 'Include GISA': includeGISACheckbox.getValue(),
      // 'Include WSF': includeWSFCheckbox.getValue(),
      // 'Include BuiltUp': includeGHSLCheckbox.getValue(),
    'Use Hansen (GFC) Tree Cover': (treecoverSourceSelect.getValue() === 'Hansen GFC'),
    'Use GLAD LULC Forest': (treecoverSourceSelect.getValue() === 'GLAD LULC'),
    'Use Agreement Forest': (treecoverSourceSelect.getValue() === 'Agreement (Hansen & GLAD)'),
    'Use Combined Extent Forest': (treecoverSourceSelect.getValue() === 'Combined extent (Hansen | GLAD)'),
      'Exclude Plantations': includePlantationsCheckbox.getValue(),
      'Exclude Agriculture from Forest (FRA)': excludeAgricultureFromForestCheckbox.getValue(),
      'WDPA Preset': wdpaPresetSelect.getValue(),
      'WDPA Established Before': wdpaYearSlider.getValue(),
      'WDPA Selected Categories': selected_iucn_categories.join(', '),
      'Custom Forest Mode': nationalForest.modeSelect.getValue(),  // P1.23
      'Custom Roads Mode': nationalRoads.modeSelect.getValue(),
      'Custom BuiltUp Small Mode': nationalBuiltupSmall.modeSelect.getValue(),
      'Custom BuiltUp Large Mode': nationalBuiltupLarge.modeSelect.getValue(),
      'Custom Agri Mode': nationalAgri.modeSelect.getValue(),
      'Custom OLWTC Mode': nationalOLWTC.modeSelect.getValue(),
      'Custom Plantations Mode': nationalPlantations.modeSelect.getValue(),
      'Custom Protected Mode': nationalProtected.modeSelect.getValue(),
      'Input Category': inputCategorySelect.getValue(),
      'FRA Aligned': fraAlignedCheckbox.getValue(),
      'Refine Input': refineInputCheckbox.getValue(),
      'Custom Slope Asset': useCustomSlopeCheckbox.getValue() ? customSlopeInput.getValue() : '',
      'Use Master Buffer': useMasterBufferCheckbox.getValue(),
      'Master Buffer (m)': masterBufferSlider.getValue(),
      'Enable Roads Buffer': enableRoadsBuffer.getValue(),
      'Enable Small BuiltUp Buffer': enableBuiltUpSmallBuffer.getValue(),
      'Enable Large BuiltUp Buffer': enableBuiltUpLargeBuffer.getValue(),
      'Enable Agriculture Buffer': enableAgriBuffer.getValue(),
      'Enable Slope': enableSlope.getValue(),
      'Enable Protected Areas': enableProtectedAreas.getValue(),
      'Enable Refine Output': enableRefineOutput.getValue(),
      'Add Input Layers To Map': addInputLayersToMap.getValue(),
      'Export Run Metadata JSON': exportChk_runMetadata.getValue()
    };

    // P1.23: Custom forest asset is now serialised via the standard
    // nationalDatasets map below (key 'Custom Forest'). The legacy
    // 'Custom Forest Asset YEAR' top-level keys are still emitted by
    // the loop above for backwards compatibility with earlier saved
    // settings via the same generic per-year asset path.

    // Add custom asset inputs per year
    var nationalDatasets = {
      'Custom Forest': nationalForest,                // P1.23
      'Custom Roads': nationalRoads,
      'Custom BuiltUp Small': nationalBuiltupSmall,
      'Custom BuiltUp Large': nationalBuiltupLarge,
      'Custom Agri': nationalAgri,
      'Custom OLWTC': nationalOLWTC,
      'Custom Plantations': nationalPlantations,
      'Custom Protected': nationalProtected
    };
    Object.keys(nationalDatasets).forEach(function(key) {
      var obj = nationalDatasets[key];
      if (obj.checkbox.getValue()) {
        years.forEach(function(year) {
          var v = obj.getAsset(year);
          if (v) settings[key + ' Asset ' + year] = v;
        });
      }
    });

    return settings;
  }

  // Function to export settings
  function exportSettings() {
    var settings = collectSettings();
    var settingsFeature = ee.Feature(null, settings);
    var settingsCollection = ee.FeatureCollection([settingsFeature]);

    var url = settingsCollection.getDownloadURL({
      format: 'json',
      filename: 'settings_primary_forest_app.json'
    });

    // Remove the previous download link panel if it exists
    if (downloadLinkPanel) {
      ui.root.widgets().remove(downloadLinkPanel);
    }

    // Create a new download link
    var downloadLink = ui.Label({
      value: 'Download Settings',
      style: {color: 'blue', textDecoration: 'underline'},
      targetUrl: url
    });

    // Create a close button
    var closeButton = ui.Button({
      label: '✖',
      style: {margin: '0 0 0 10px'},
      onClick: function() {
        ui.root.widgets().remove(downloadLinkPanel);
        downloadLinkPanel = null;
      }
    });

    // Create a panel to hold the download link and close button
    downloadLinkPanel = ui.Panel({
      widgets: [downloadLink, closeButton],
      layout: ui.Panel.Layout.flow('vertical'),
      style: {margin: '10px 0'}
    });

    ui.root.widgets().add(downloadLinkPanel);
  }


  // Function to show text input for importing settings
  function showTextInput() {
    var textInputPanel = ui.Panel({
      widgets: [
        ui.Label('Paste Settings from JSON (and press enter):'),
        ui.Textbox({
          placeholder: 'Paste settings JSON here',
          onChange: ui.util.debounce(function(value) {
            // Show loading label
            loadingLabel.style().set('shown', true);
            var success = false;
            
            try {
              var settings = JSON.parse(value);
              if (settings.type === 'FeatureCollection' && settings.features.length > 0) {
                settings = settings.features[0].properties;
              }
              applySettings(settings);
              success = true;
            } catch (e) {
              print('Invalid JSON format: ' + e.message);
              // Add more detailed error message to help users
              print('Check that you copied the entire file content, including { and } characters');
            } finally {
              // Hide loading label
              loadingLabel.style().set('shown', false);
              
              // Only remove the panel if successful
              if (success) {
                ui.root.widgets().remove(textInputPanel);
              }
            }
          },300),
          style: {width: '400px', height: '200px'}
        }),
        
        // Add a close button
        ui.Button({
          label: 'Cancel',
          onClick: function() {
            ui.root.widgets().remove(textInputPanel);
          },
          style: {margin: '5px 0'}
        })
      ],
      style: {margin: '10px 0', padding: '10px'}
    });

    ui.root.widgets().add(textInputPanel);
  }
  
  // Function to apply settings
  function applySettings(settings) {
    
    countrySelector.setValue(settings['Country']);
    yearSelector1.setValue(settings['Year 1']);
    yearSelector2.setValue(settings['Year 2']);
    treecoverThresholdSlider.setValue(settings['Treecover Threshold (%)']);
    treecoverHeightThresholdSlider.setValue(settings['GLAD Treecover Height (m)']);
    roadSmallBufferSlider.setValue(settings['Road Small Buffer (m)']);
    builtUpSmallBufferSlider.setValue(settings['Built-Up Small Buffer (m)']);
    builtUpLargeBufferSlider.setValue(settings['Built-Up Large Buffer (m)']);
    agriBufferSlider.setValue(settings['Agriculture Buffer (m)']);
    // Master buffer
    if (settings['Use Master Buffer'] !== undefined) {
      useMasterBufferCheckbox.setValue(settings['Use Master Buffer']);
    }
    if (settings['Master Buffer (m)'] !== undefined) {
      masterBufferSlider.setValue(settings['Master Buffer (m)']);
    }
    if (settings['Enable Roads Buffer'] !== undefined) enableRoadsBuffer.setValue(settings['Enable Roads Buffer']);
    if (settings['Enable Small BuiltUp Buffer'] !== undefined) enableBuiltUpSmallBuffer.setValue(settings['Enable Small BuiltUp Buffer']);
    if (settings['Enable Large BuiltUp Buffer'] !== undefined) enableBuiltUpLargeBuffer.setValue(settings['Enable Large BuiltUp Buffer']);
    if (settings['Enable Agriculture Buffer'] !== undefined) enableAgriBuffer.setValue(settings['Enable Agriculture Buffer']);
    if (settings['Enable Slope'] !== undefined) enableSlope.setValue(settings['Enable Slope']);
    if (settings['Enable Protected Areas'] !== undefined) enableProtectedAreas.setValue(settings['Enable Protected Areas']);
    if (settings['Enable Refine Output'] !== undefined) enableRefineOutput.setValue(settings['Enable Refine Output']);
    if (settings['Add Input Layers To Map'] !== undefined) addInputLayersToMap.setValue(settings['Add Input Layers To Map']);
    if (settings['Export Run Metadata JSON'] !== undefined) exportChk_runMetadata.setValue(settings['Export Run Metadata JSON']);
    slopeToKeepSlider.setValue(settings['Slope to keep (degrees)']);
    // otherNatBufferSlider.setValue(settings['Other Natural Buffer (m)']);
    smoothRadiusForestSlider.setValue(settings['Forest Smoothing Radius (m)']);
    smallPixelThresholdForestSlider.setValue(settings['Forest Smoothing Threshold']);
    // fastBufferCheckbox.setValue(settings['Use Accurate Distance Buffers']);
    // includeGISDCheckbox.setValue(settings['Include GISD']);
    // includeGISACheckbox.setValue(settings['Include GISA']);
    // includeWSFCheckbox.setValue(settings['Include WSF']);
    // includeGHSLCheckbox.setValue(settings['Include BuiltUp']);
    if (settings['Use Hansen (GFC) Tree Cover']) {
      treecoverSourceSelect.setValue('Hansen GFC');
    } else if (settings['Use GLAD LULC Forest']) {
      treecoverSourceSelect.setValue('GLAD LULC');
    } else if (settings['Use Agreement Forest']) {
      treecoverSourceSelect.setValue('Agreement (Hansen & GLAD)');
    } else if (settings['Use Combined Extent Forest']) {
      treecoverSourceSelect.setValue('Combined extent (Hansen | GLAD)');
    } else if (settings['Use Both Datasets Forest']) { // backward compat (pre-v4.1.6 key)
      treecoverSourceSelect.setValue('Agreement (Hansen & GLAD)');
    } else if (settings['Use Either Dataset Forest']) { // backward compat (pre-v4.1.6 key)
      treecoverSourceSelect.setValue('Combined extent (Hansen | GLAD)');
    }
    
    // Restore custom forest selection: handled by treecoverSourceSelect restore above
    if (settings['Exclude Plantations'] !== undefined) {
      includePlantationsCheckbox.setValue(settings['Exclude Plantations']);
    } else if (settings['Include Plantations'] !== undefined) {
      // Backward compatibility: invert old "Include" to new "Exclude" semantic
      includePlantationsCheckbox.setValue(!settings['Include Plantations']);
    }

    // P1.18: FRA-aligned Forest baseline toggle
    if (settings['Exclude Agriculture from Forest (FRA)'] !== undefined) {
      excludeAgricultureFromForestCheckbox.setValue(
        settings['Exclude Agriculture from Forest (FRA)']);
    }

    if (settings['FRA Aligned'] !== undefined)
      fraAlignedCheckbox.setValue(settings['FRA Aligned']);
    if (settings['Refine Input'] !== undefined)
      refineInputCheckbox.setValue(settings['Refine Input']);

    if (settings['Input Category']) {
      var savedCat = settings['Input Category'];
      // Backward compat: map old long-form values to new short ones.
      if (INPUT_CATEGORY_LEGACY_MAP[savedCat]) {
        savedCat = INPUT_CATEGORY_LEGACY_MAP[savedCat];
      }
      if ([INPUT_CATEGORY_ALL, INPUT_CATEGORY_FOREST,
          INPUT_CATEGORY_NATREG, INPUT_CATEGORY_PRIMARY].indexOf(savedCat) >= 0) {
        inputCategorySelect.setValue(savedCat);
      }
    }

    // Restore custom asset overrides (per-year)
    // P1.23: nationalForest joined this map, replacing the legacy
    // 'Custom Forest Asset YEAR' top-level keys path. Backwards compat
    // for old saved settings handled below.
    var nationalRestoreMap = {
      'Custom Forest': nationalForest,
      'Custom Roads': nationalRoads,
      'Custom BuiltUp Small': nationalBuiltupSmall,
      'Custom BuiltUp Large': nationalBuiltupLarge,
      'Custom Agri': nationalAgri,
      'Custom OLWTC': nationalOLWTC,
      'Custom Plantations': nationalPlantations,
      'Custom Protected': nationalProtected
    };
    Object.keys(nationalRestoreMap).forEach(function(key) {
      var obj = nationalRestoreMap[key];
      var modeKey = key + ' Mode';
      var hasAny = false;
      years.forEach(function(year) {
        if (settings[key + ' Asset ' + year]) hasAny = true;
      });
      if (hasAny) {
        obj.checkbox.setValue(true);
        obj.modeSelect.style().set('shown', true);
        if (settings[modeKey]) {
          var savedMode = settings[modeKey];
          // P1.23: forward-migrate the old mode label
          if (savedMode === 'Add to global') savedMode = 'Add to global extent';
          obj.modeSelect.setValue(savedMode);
        }
        var assetsByYear = {};
        years.forEach(function(year) {
          if (settings[key + ' Asset ' + year]) assetsByYear[year] = settings[key + ' Asset ' + year];
        });
        obj.applyAssets(assetsByYear);
        // trigger visibility so year rows appear
        var useSplitScreen = enableSplitScreenCheckbox.getValue();
        var y1 = parseInt(yearSelector1.getValue());
        var y2 = parseInt(yearSelector2.getValue());
        obj.updateVisibility(useSplitScreen, y1, y2);
        obj.setShown(true);
      }
    });
    updateRefineVisibility();
    if (settings['Custom Slope Asset']) {
      useCustomSlopeCheckbox.setValue(true);
      customSlopeInput.setValue(settings['Custom Slope Asset']);
      customSlopeInput.style().set('shown', true);
    }

    updateMap();
  }

  // Create maps (will be recreated on mode changes to avoid parent conflicts)
  var map1 = null;
  var map2 = null; // initialized below with globe view

  // Explicitly tracked centers/zooms (avoid relying on ui.Map.getCenter())
  var map1Center = null; // [lon, lat]
  var map1Zoom = null;   // number
  var map2Center = null; // [lon, lat]
  var map2Zoom = null;   // number

  // Main container with left panel, map, and right panel
  var mainContainer = ui.Panel({
    layout: ui.Panel.Layout.flow('horizontal'),
    style: {stretch: 'both', backgroundColor: 'white'}
  });

  // Root container with top bar and main content
  var rootContainer = ui.Panel({
    widgets: [topBar, mainContainer],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {stretch: 'both'}
  });

  // Initialize the UI
  ui.root.widgets().reset([rootContainer]);

  // Set initial globe view
  map2 = ui.Map();
  map2.setCenter(0, 20, 2);
  map2.setControlVisibility({all: true, zoomControl: true});
  map2.add(createLegendPanel());
  map2.add(createDisclaimerPanel());
  map2.setOptions('Gray', {Gray: GRAYMAP});
  mainContainer.add(leftPanel);
  mainContainer.add(map2);
  mainContainer.add(rightPanel);

  // splitPanel will be created on-demand when needed
  var splitPanel = null;

  // Create ui.Map.Layer objects for Hansen GFC that can be dynamically updated
  var hansenLayer1 = ui.Map.Layer(null, {min:0, max:1, palette:['white','lightgreen']}, 'Forest (GFC Hansen)', false);
  var hansenLayer2 = ui.Map.Layer(null, {min:0, max:1, palette:['white','lightgreen']}, 'Forest (GFC Hansen)', false);

  // Store reference to the current forest data for each map
  var currentForestData = {
    map1: {forest_map_clip: null, analysisYear: null, country_sel: null},
    map2: {forest_map_clip: null, analysisYear: null, country_sel: null}
  };

  // Function to update Hansen layer with new zoom-dependent scale
  // This prevents masking issues at different zoom levels
  function updateHansenLayer(map, mapName, hansenLayer) {
    // Check if Hansen is enabled and has data
    if (treecoverSourceSelect.getValue() !== 'Hansen GFC') {
      // Hansen is not enabled - zoom rendering only works with Hansen GFC
      return;
    }
    
    var data = currentForestData[mapName];
    if (!data.forest_map_clip) {
      // Data not loaded yet - this is normal on initial setup
      return;
    }
    
    var z = map.getZoom();
    var s = scaleForZoom(z, 30, 10, 1.8, 30, 900)
    // var s = scaleForZoom({z:z, base_scale:30, pivot_z:10, r:1.8, min_scale:30, max_scale:900}) ;
    
    // Get base projection
    var baseProj = data.forest_map_clip.projection();
    
    // Reproject with zoom-dependent scale
    var forest_rendered = data.forest_map_clip.reproject({
      crs: baseProj, 
      scale: s
    });
    
    // Update the layer with new rendering (same pattern as test file)
    hansenLayer.setEeObject(forest_rendered);
    hansenLayer.setName('Forest (GFC Hansen ' + data.analysisYear + ' @ ' + s + 'm)');
    hansenLayer.setShown(false);
  }

  // Note: Zoom listeners will be attached when maps are created in updateMap

  // Linker will be created only when split screen is enabled
  var linker = null;

  // Track current display mode
  var currentMode = 'single';

  // Track previous state to detect actual changes vs mode switches
  var previousState = {
    country: null,
    splitScreen: false,
    mapCenter: null,
    mapZoom: null
  };

  // Preserve view for manual recentering
  var lastCenter = null; // ee.Geometry.Point
  var lastZoom = null;   // number
  var previousCountry = null; // Track last selected country name

  // (visibleLayers defined above layerPanel)

  // Helper to log current map center and zoom
  function logCenterExplicit(label, centerArr, zoomVal) {
    if (centerArr && centerArr.length === 2 && typeof zoomVal === 'number') {
      print(label + ' center lon/lat: ' + centerArr[0] + ', ' + centerArr[1] + ' | zoom: ' + zoomVal);
    } else {
      print(label + ' center unavailable');
    }
  }

  // WORKAROUND: Linked maps may not fire zoom change events reliably
  // Poll for zoom changes as backup
  var lastZoomPoll = {map1: null, map2: null};
  ui.util.setInterval(function() {
    if (treecoverSourceSelect.getValue() !== 'Hansen GFC') return;
    
    // Guard against null maps (not yet initialized)
    if (!map1 || !map2) return;
    
    var z1 = map1.getZoom();
    var z2 = map2.getZoom();
    
    if (z1 !== lastZoomPoll.map1 && currentForestData.map1.forest_map_clip) {
      lastZoomPoll.map1 = z1;
      updateHansenLayer(map1, 'map1', hansenLayer1);
    }
    
    if (z2 !== lastZoomPoll.map2 && currentForestData.map2.forest_map_clip) {
      lastZoomPoll.map2 = z2;
      updateHansenLayer(map2, 'map2', hansenLayer2);
    }
  }, 500); // Check every 500ms

  // updateMap() // removed to see if needed


  // Main update function

  function updateMap(opts)  {
    // P1.25: opts.fromUpdateAnalysisButton flag toggles two button-only
    // behaviours (visibility reset, see below). All other callers
    // (country/year change, applySettings, initial load) call updateMap()
    // with no args -- they keep current behaviour and preserve the user's
    // per-layer toggles.
    opts = opts || {};
    markUpToDate();
    // Clear stale on-the-fly stats whenever parameters change
    areaStatsPanel.clear();
    exportStatusLabel.setValue('');
    var useSplitScreen = enableSplitScreenCheckbox.getValue();
    var analysisYear1 = parseInt(yearSelector1.getValue());
    var analysisYear2 = parseInt(yearSelector2.getValue());
    // Multi-year baseline-forest constraint (closure-scoped so
    // addLayersToMap can read these). When split-screen is active and the
    // two years differ, the later year's forest_map is intersected with
    // the earliest year's forest mask so dynamic forest layers (e.g.
    // GLAD) can't inflate later-year primary forest with newly-detected
    // forest pixels. Built later in this function once the forest source
    // toggles are resolved.
    var baselineForestMask = null;
    var baselineForestYear = null;

    // Reset stored forest data so only currently-active years appear in stats
    latestMaskedTreeCover = {};
    latestMaskedForest = {};
    latestMaskedPrimaryForest = {};
    latestMaskedNaturallyRegenerating = {};
    latestPreConnectivityForest = {};
    latestTier1Undisturbed = {};
    latestTier2Steep = {};
    latestTier3Protected = {};
    var selectedCountry = countrySelector.getValue();
    
    if (!selectedCountry || selectedCountry === '') {
      countrySelector.style().set({border: '2px solid #cc6666', color: '#cc6666'});
      countryWarningLabel.setValue('Please choose a country');
      countryWarningLabel.style().set({shown: true});
      return;
    }

    if (fraAlignedCheckbox.getValue() && !inputCategorySelect.getValue()) {
      inputCategorySelect.style().set({border: '2px solid #cc6666'});
      countryWarningLabel.setValue('Please select an input type (FRA-aligned is ticked)');
      countryWarningLabel.style().set({shown: true});
      return;
    }
    inputCategorySelect.style().set({border: ''});

    ////////////////////////////////
    // Check if country or years changed (requires clearing cache)
    if (selectedCountry !== cachedState.country || 
        analysisYear1 !== cachedState.year1 || 
        analysisYear2 !== cachedState.year2) {
      // Clear cache when fundamental parameters change
      cachedState.distanceImages = {};
      cachedState.country = selectedCountry;
      cachedState.year1 = analysisYear1;
      cachedState.year2 = analysisYear2;
    }
    /////////////////////////////

    var treecoverPercentThreshold = treecoverThresholdSlider.getValue();
    var treecoverHeightThreshold = treecoverHeightThresholdSlider.getValue();
    var roadSmallBuffer = roadSmallBufferSlider.getValue();
    var builtUpSmallBuffer = builtUpSmallBufferSlider.getValue();
    var builtUpLargeBuffer = builtUpLargeBufferSlider.getValue();
    var agriBuffer = agriBufferSlider.getValue();
    var slopeToKeepValue = slopeToKeepSlider.getValue();
    // var otherNatBuffer = otherNatBufferSlider.getValue();
    // var includeGISD = includeGISDCheckbox.getValue();
    // var includeGISA = includeGISACheckbox.getValue();
    // var includeWSF = includeWSFCheckbox.getValue();
    // var includeGHSL = includeGHSLCheckbox.getValue();
    var useHansenTreecover = (treecoverSourceSelect.getValue() === 'Hansen GFC');
    var useGladLulcForest = (treecoverSourceSelect.getValue() === 'GLAD LULC');
    var useAgreementForest = (treecoverSourceSelect.getValue() === 'Agreement (Hansen & GLAD)');
    var useUnionForest = (treecoverSourceSelect.getValue() === 'Combined extent (Hansen | GLAD)');
    // var fastBuffer = fastBufferCheckbox.getValue();
    var smoothRadiusForest = smoothRadiusForestSlider.getValue();
    var smallPixelThresholdForest = smallPixelThresholdForestSlider.getValue();

    print('=== updateMap START ===');
    print('updateMap: country=' + selectedCountry + ' | split=' + useSplitScreen);
    print('Visible layers: Primary=' + visibleLayers.primaryForest +
          ' | ForestOutside=' + visibleLayers.forestOutsideBuffers +
          ' | Forest=' + visibleLayers.forest +
          ' | RoadSmall=' + visibleLayers.roadSmallBuffer);
    
    var country_sel = getCountryFeatures(selectedCountry);
    
    var requestedMode = useSplitScreen ? 'split' : 'single';
    var modeChanged = (currentMode !== requestedMode);
    var countryChanged = (previousCountry !== selectedCountry);

    // Reset layer visibility when country changes so primary forest shows by default
    if (countryChanged && previousCountry !== null) {
      resetVisibleLayers();
    }

    // Force initialization on first run
    var needsInit = (requestedMode === 'single' && !map2) || (requestedMode === 'split' && (!map1 || !map2));
    if (needsInit) {
      modeChanged = true;
      print('First run - forcing initialization');
    }
    
    print('Mode check: current=' + currentMode + ' | requested=' + requestedMode + ' | changed=' + modeChanged);
    
    // Capture current view before potential rebuild (always capture to preserve view across mode changes)
    // Prefer map2 in single mode, map1 in split mode
    var activeMapPre = (currentMode === 'split' && map1) ? map1 : map2;
    if (activeMapPre) {
      try {
        lastZoom = activeMapPre.getZoom();
        var cPre = activeMapPre.getCenter(); // returns {lon, lat}
        if (cPre && typeof cPre.lon === 'number' && typeof cPre.lat === 'number') {
          lastCenter = ee.Geometry.Point([cPre.lon, cPre.lat]);
          print('Captured view: ' + cPre.lon + ', ' + cPre.lat + ' @ zoom ' + lastZoom);
        }
      } catch (e) {
        print('Error capturing view: ' + e);
      }
    }

    // Only rebuild UI if mode changed
    if (modeChanged) {
      print('Mode change: ' + currentMode + ' -> ' + requestedMode);

      // Clear main container and previous structures
      mainContainer.clear();
      linker = null;
      splitPanel = null;

      // P1.26: clear legend-refresh closures from previous maps. Each
      // createLegendPanel() call below pushes a new closure to
      // _legendRefreshFns; without this cleanup, every mode rebuild
      // leaks one fn referencing a now-orphaned panel. Cheap to keep
      // around individually, but accumulates across many mode toggles.
      _legendRefreshFns.length = 0;

      if (requestedMode === 'split') {
        // Recreate maps fresh
        map1 = ui.Map();
        map2 = ui.Map();
        map1.setControlVisibility({all: true, zoomControl: true});
        map2.setControlVisibility({all: true, zoomControl: true});
        
        // Add legend to first map
        map1.add(createLegendPanel());
        map1.add(createDisclaimerPanel());
        
        // Reset tracked centers/zooms when maps are recreated
        map1Center = null;
        map1Zoom = null;
        map2Center = null;
        map2Zoom = null;

        // Build split mode
        splitPanel = ui.SplitPanel({
          firstPanel: map1,
          secondPanel: map2,
          orientation: 'horizontal',
          wipe: true
        });
        
        // Assemble main container: left panel + split maps + right panel
        mainContainer.add(leftPanel);
        mainContainer.add(splitPanel);
        mainContainer.add(rightPanel);
        
        linker = ui.Map.Linker([map1, map2]);
        
        // Re-attach zoom listeners for Hansen
        map1.onChangeZoom(function() {
          updateHansenLayer(map1, 'map1', hansenLayer1);
        });
        map2.onChangeZoom(function() {
          updateHansenLayer(map2, 'map2', hansenLayer2);
        });
        
        print('Split mode initialized');
      } else {
        // Recreate single map fresh
        map2 = ui.Map();
        map2.setControlVisibility({all: true, zoomControl: true});
        
        // Add legend to map
        map2.add(createLegendPanel());
  map2.add(createDisclaimerPanel());
        
        // Reset tracked center/zoom for single map
        map2Center = null;
        map2Zoom = null;

        // Assemble main container: left panel + map + right panel
        mainContainer.add(leftPanel);
        mainContainer.add(map2);
        mainContainer.add(rightPanel);
        
        // Re-attach zoom listener for Hansen
        map2.onChangeZoom(function() {
          updateHansenLayer(map2, 'map2', hansenLayer2);
        });
        
        print('Single mode initialized');
      }

      currentMode = requestedMode;
    } else {
      // Same mode — remove only PFF-managed layers; preserve user-added layers
      var pffLayerNames = [
        'Buffer: Roads', 'Buffer: Small Built-up', 'Buffer: Large Built-up',
        'Buffer: Agriculture', 'Input: Roads', 'Input: Small Built-up',
        'Input: Large Built-up', 'Input: Agriculture', 'Planted forest',
        'Input', 'Input: Tree cover', 'Forest',
        'Naturally regenerating forest',
        'Pre-refinement primary',
        // legacy name kept so users with stale projects can still see
        // the old layer get cleaned up on update.
        'Forest outside buffers',
        'Primary Forest', 'Primary forest',
        'Reference: FLII (high/med)', 'Reference: Forest Persistence (FDaP)',
        'Reference: Custom 1', 'Reference: Custom 2'
      ];
      // Also match dynamic names like "Slope > 45°", "WDPA ..."
      // 'Forest' NOT in prefixes -- would over-match 'Pre-refinement primary'
      // (no longer relevant) but also other prefix-shaped names.
      // Exact match via pffLayerNames handles it.
      var pffPrefixes = ['Input: Slope', 'Input: Protected', 'Hansen ', 'Input: Tree cover'];
      function isPffLayer(name) {
        if (pffLayerNames.indexOf(name) !== -1) return true;
        for (var p = 0; p < pffPrefixes.length; p++) {
          if (name.indexOf(pffPrefixes[p]) === 0) return true;
        }
        return false;
      }
      // Map layer names to visibleLayers keys so we can capture user toggles
      var nameToKey = {
        'Primary Forest': 'primaryForest',
        'Primary forest': 'primaryForest',
        'Pre-refinement primary': 'forestOutsideBuffers',
        'Input': 'treeCover',
        'Input: Tree cover': 'treeCover',
        'Forest': 'forest',
        'Naturally regenerating forest': 'naturallyRegenerating',
        // 'Forest' handled via prefix matching below
        'Input: Roads': 'inputRoads',
        'Input: Small Built-up': 'inputBuiltupSmall',
        'Input: Large Built-up': 'inputBuiltupLarge',
        'Input: Agriculture': 'inputAgriculture',
        'Buffer: Roads': 'roadSmallBuffer',
        'Buffer: Small Built-up': 'builtSmallBuffer',
        'Buffer: Large Built-up': 'builtLargeBuffer',
        'Buffer: Agriculture': 'agriBuffer',
        'Planted forest': 'plantations',
        'Reference: FLII (high/med)': 'flii'
      };
      function syncAndRemovePffLayers(m) {
        if (!m) return;
        var layers = m.layers();
        // First pass: capture current shown state from the map
        for (var i = 0; i < layers.length(); i++) {
          var layer = layers.get(i);
          var key = nameToKey[layer.getName()];
          if (key) visibleLayers[key] = layer.getShown();
          // Handle dynamic prefix names
          var lname = layer.getName();
          if (lname.indexOf('Input: Slope') === 0) visibleLayers.slope = layer.getShown();
          if (lname.indexOf('Input: Protected') === 0) visibleLayers.protectedAreas = layer.getShown();
          if (lname === 'Forest') visibleLayers.forest = layer.getShown();
        }
        // Second pass: remove PFF layers
        for (var j = layers.length() - 1; j >= 0; j--) {
          if (isPffLayer(layers.get(j).getName())) layers.remove(layers.get(j));
        }
      }
      syncAndRemovePffLayers(map1);
      syncAndRemovePffLayers(map2);
    }

    // P1.25: when triggered by the Update Analysis button, restore default
    // layer visibility so freshly-added layers show on the map. Layers the
    // user had toggled off in the legend come back -- "fresh analysis =
    // fresh view." Placed AFTER syncAndRemovePffLayers so its writeback
    // to visibleLayers (from the soon-to-be-removed layers' shown-state)
    // doesn't overwrite the reset.
    if (opts.fromUpdateAnalysisButton) {
      resetVisibleLayers();
    }

    // After rebuild or clear, ensure maps are centered to avoid default USA view
    // Priority: restore last view if available; otherwise center on selected country
    var centroid = country_sel.geometry().centroid().coordinates().getInfo();
    if (useSplitScreen) {
      if (map1 && (!map1Center || !map1Zoom)) {
        if (lastCenter && lastZoom) {
          var lc1 = lastCenter.coordinates().getInfo();
          map1.setCenter(lc1[0], lc1[1], lastZoom);
          map1Center = [lc1[0], lc1[1]];
          map1Zoom = lastZoom;
          print('map1 restored to: ' + lc1[0] + ', ' + lc1[1] + ' @ ' + lastZoom);
        } else {
          map1.setCenter(centroid[0], centroid[1], 6);
          map1Center = [centroid[0], centroid[1]];
          map1Zoom = 6;
          print('map1 centered to country centroid');
        }
      }
      if (map2 && (!map2Center || !map2Zoom)) {
        if (lastCenter && lastZoom) {
          var lc2 = lastCenter.coordinates().getInfo();
          map2.setCenter(lc2[0], lc2[1], lastZoom);
          map2Center = [lc2[0], lc2[1]];
          map2Zoom = lastZoom;
          print('map2 restored to: ' + lc2[0] + ', ' + lc2[1] + ' @ ' + lastZoom);
        } else {
          map2.setCenter(centroid[0], centroid[1], 6);
          map2Center = [centroid[0], centroid[1]];
          map2Zoom = 6;
          print('map2 centered to country centroid');
        }
      }
    } else {
      if (map2 && (!map2Center || !map2Zoom)) {
        if (lastCenter && lastZoom) {
          var lc = lastCenter.coordinates().getInfo();
          map2.setCenter(lc[0], lc[1], lastZoom);
          map2Center = [lc[0], lc[1]];
          map2Zoom = lastZoom;
          print('map2 restored to: ' + lc[0] + ', ' + lc[1] + ' @ ' + lastZoom);
        } else {
          map2.setCenter(centroid[0], centroid[1], 6);
          map2Center = [centroid[0], centroid[1]];
          map2Zoom = 6;
          print('map2 centered to country centroid');
        }
      }
    }
    
    // Configure map layout based on split screen setting
    if (useSplitScreen) {
      // Split screen mode - remove old year labels if they exist
      if (yearLabel1Widget && map1) {
        try { map1.remove(yearLabel1Widget); } catch(e) {}
      }
      if (yearLabel2Widget && map2) {
        try { map2.remove(yearLabel2Widget); } catch(e) {}
      }
      
      // Create new year labels
      yearLabel1Widget = ui.Label({
        value: 'Year: ' + yearSelector1.getValue(),
        style: {
          position: 'top-left',
          backgroundColor: 'rgba(255, 255, 255, 0.8)',
          padding: '8px',
          margin: '3px',
          fontSize: '20px',
          fontWeight: 'bold'
        }
      });
      
      yearLabel2Widget = ui.Label({
        value: 'Year: ' + yearSelector2.getValue(),
        style: {
          position: 'top-right',
          backgroundColor: 'rgba(255, 255, 255, 0.8)',
          padding: '8px',
          margin: '3px',
          fontSize: '20px',
          fontWeight: 'bold'
        }
      });
      
      map1.add(yearLabel1Widget);
      map2.add(yearLabel2Widget);
      
      // Apply gray map style to both maps
      map1.setOptions('Gray', {Gray: GRAYMAP});
      map2.setOptions('Gray', {Gray: GRAYMAP});
      
      // Auto-zoom on first load or country change
      if (countryChanged) {
        print('Zooming to: ' + selectedCountry);
        map1.setCenter(centroid[0], centroid[1], 6);
        map1Center = [centroid[0], centroid[1]];
        map1Zoom = 6;
        logCenterExplicit('map1 after zoom', map1Center, map1Zoom);
      }
    } else {
      // Single map mode - remove old year labels if they exist
      if (yearLabel1Widget && map1) {
        try { map1.remove(yearLabel1Widget); } catch(e) {}
      }
      if (yearLabel2Widget && map2) {
        try { map2.remove(yearLabel2Widget); } catch(e) {}
      }
      
      // Create new year label
      yearLabel2Widget = ui.Label({
        value: 'Year: ' + yearSelector2.getValue(),
        style: {
          position: 'top-center',
          backgroundColor: 'rgba(255, 255, 255, 0.8)',
          padding: '8px',
          margin: '3px',
          fontSize: '20px',
          fontWeight: 'bold'
        }
      });
      yearLabel1Widget = null;  // Clear split-mode label reference
      
      map2.add(yearLabel2Widget);
      map2.setOptions('Gray', {Gray: GRAYMAP});
      
      // Auto-zoom on first load or country change
      if (countryChanged) {
        print('Zooming to: ' + selectedCountry);
        map2.setCenter(centroid[0], centroid[1], 6);
        map2Center = [centroid[0], centroid[1]];
        map2Zoom = 6;
        logCenterExplicit('map2 after zoom', map2Center, map2Zoom);
      }
    }
    //old
    // // Function to add layers to a map for a given year
    // function addLayersToMap(map, analysisYear) {
    //   // Forest cover processing
    //   var gfc_hansen = ee.Image("UMD/hansen/global_forest_change_2023_v1_11");
    //   var gfc_hansen_2000 = gfc_hansen.select("treecover2000").gt(treecoverPercentThreshold);
    //   var gfc_hansen_sel = gfc_hansen_2000.where(gfc_hansen.select("lossyear").lte(analysisYear - 2000), 0);
    //   var forest_map = gfc_hansen_sel;
    
    // Function to add layers to a map for a given year
    function addLayersToMap(map, analysisYear) {
      // P1.26: "Disable map" mode -- when on, skip every pffAddLayer()
      // call. The lazy ee.Image graph still gets built (cheap, no
      // roundtrip) and the latestMasked* caches still populate, so
      // Export All Layers / Export Statistics to Drive can still queue
      // tasks containing Primary Forest + Pre-connectivity. Only the
      // visual preview is skipped.
      var skipMap = disableMapCheckbox.getValue();
      function pffAddLayer() {
        if (skipMap) return;
        // .apply lets us forward whatever args the call site passed
        // (varies in arity across the addLayersToMap call sites).
        map.addLayer.apply(map, arguments);
      }

      // P1.23: forest_map is always derived from the Source dropdown
      // first; if Custom forest data is on, applyCustomForestMerge then
      // combines it with the global source according to the user-chosen
      // merge mode (Replace global / Add to global extent / Agreement
      // with global). Replaces the pre-P1.23 'Custom Forest' source-dropdown
      // branch.
      var forest_map;
      if (useAgreementForest) {
        forest_map = agreementForestPrep(analysisYear, treecoverPercentThreshold, treecoverHeightThreshold);
      } else if (useUnionForest) {
        forest_map = unionForestPrep(analysisYear, treecoverPercentThreshold, treecoverHeightThreshold);
      } else if (useGladLulcForest) {
        forest_map = gladLulcForestPrep(analysisYear,treecoverHeightThreshold);
      }
      // Uncomment when needed
      // else if (useGlcFlsd30Forest) {
      //   forest_map = glc_flsd30_forest;
      //   print('Using GLC FLSD30 forest data for ' + analysisYear);
      // }
      // else if (useEsaCciForest) {
      //   forest_map = esa_cci_forest;
      //   print('Using ESA CCI forest data for ' + analysisYear);
      // }
      else if (useHansenTreecover) {
        // var treecoverPercentThreshold = 10
        forest_map = gfcHansenTreecoverPrep(analysisYear,treecoverPercentThreshold);
        //debug print('Using Hansen Treecover data for ' + analysisYear);
      }

      forest_map = applyCustomForestMerge(forest_map, analysisYear);

      // Multi-year baseline-forest constraint: when split-screen is on
      // and this is the later year, intersect the year-N forest with the
      // baseline-year forest mask so newly-detected forest pixels (e.g.
      // GLAD year-on-year additions) can't be classified as primary.
      if (baselineForestMask !== null &&
          analysisYear !== baselineForestYear && forest_map) {
        forest_map = forest_map.and(baselineForestMask).rename('forest');
      }

      // Final check: If no forest dataset was selected, print a warning
      if (!forest_map) {
        print("No forest data selected — skipping layer build for " + analysisYear);
        return; // Prevent downstream errors
      }

      // Country mask preparation (raster-based, no vector .clip())
      var country_clip = getCountryClip(selectedCountry);
      // var country_buffer = ee.Image(1).cumulativeCost({
      //   source: country_clip, maxDistance: country_buffer_threshold, geodeticDistance: false
      // });
      
      var country_buffer = makeDistanceBuffer(country_clip, country_buffer_threshold, fastBuffer)
      var country_and_buffer_mask = country_buffer.where(country_clip, 1).selfMask();
      var forest_map_clip = forest_map.updateMask(country_and_buffer_mask);
      
      // var country_buffer = country_sel.geometry().buffer(country_buffer_threshold);
      
      // var country_buffer = (country_sel instanceof ee.FeatureCollection) ? 
      // country_sel.map(function(feat) {
      //     return feat.buffer(country_buffer_threshold);
      // }).union() :
      // country_sel.buffer(country_buffer_threshold);
      
      // pffAddLayer(country_buffer)
      
      
      // var country_and_buffer_mask = ee.Image(1).clip(country_buffer);
      // var forest_map_clip = forest_map.clip(country_buffer);
      
      // pffAddLayer(forest_map_clip, binary_lightgreen_palette, "Forest", 0, 1);
      
      /////////
      // Anthropogenic features
      var timeseriesAnthroModule = require("users/andyarnellgee/apps:modules/timeseriesAnthro.js");
      var glcFcs30dCollection = timeseriesAnthroModule.preprocessGlc();
      var landcover = glcFcs30dCollection.filter(ee.Filter.eq("year", analysisYear)).first().updateMask(country_and_buffer_mask);
      
      // Agricultural data
      var pastureDataset = ee.ImageCollection("projects/global-pasture-watch/assets/ggc-30m/v1/grassland_c");
      
      // var pastureDatasetSel = pastureDataset.filter(ee.Filter.eq("system:index", analysisYear.toString())).first().eq(1).unmask().updateMask(country_and_buffer_mask);
      var pastureDatasetCultivated = pastureDataset.map(function(image){return image.eq(1).set('year',ee.Number.parse(image.get("system:index")))})
      var pastureDatasetFF = forwardFillBinaryTimeSeries(pastureDatasetCultivated, years.filter(function(year) {return year >= 2000}));//forward filled version  i.e., anthropogenic LU remains anthropogenic 
      var pastureDatasetSel = pastureDatasetFF.filter(ee.Filter.eq("year", analysisYear)).first().updateMask(country_and_buffer_mask)
      var oilPalmDescalsCollection = timeseriesAnthroModule.processingOilPalmDescals();
      var oilPalmDescalsSel = ee.Image(oilPalmDescalsCollection.filter(ee.Filter.eq("year", analysisYear)).first()).updateMask(country_and_buffer_mask)
      // P1.20: Plantations layer = SDPT class 1 only (FRA Planted Forest --
      // timber/pulp/fibre). SDPT class 2 + Descals oil palm route through
      // agriculture instead per FRA. See export-context comment for full
      // rationale.
      var plantedForestSDPT = timeseriesAnthroModule.processingPlantedForestSDPT()
          .updateMask(country_and_buffer_mask);
      var treeCropsSDPT = timeseriesAnthroModule.processingTreeCropsSDPT()
          .updateMask(country_and_buffer_mask);
      var allPlantationsSel = plantedForestSDPT;

      // Override plantations with national data if provided. National
      // plantations layer should also be FRA Planted Forest -- if the
      // user supplies a national "plantations" raster that includes tree
      // crops or oil palm, those pixels will be mis-classified as planted
      // forest by the natreg derivation. Document this in workshop notes.
      // Master-gate: same fix as applyCustomForestMerge — §2 master off
      // makes the per-dataset checkbox dormant so analysis falls back
      // to the global source.
      if (enableTreeCoverCustomCheckbox.getValue() &&
          nationalPlantations.checkbox.getValue()) {
        var natPlantationsAsset = nationalPlantations.getAsset(analysisYear);
        if (natPlantationsAsset) {
          var natPlantations = preprocessAsset(natPlantationsAsset, nationalPlantations.getPreprocessingConfig()).updateMask(country_and_buffer_mask);
          var npMode = nationalPlantations.modeSelect.getValue();
          if (npMode === 'Add to global extent') {
            allPlantationsSel = allPlantationsSel.unmask(0).or(natPlantations).selfMask();
          } else if (npMode === 'Agreement with global') {  // P1.23
            allPlantationsSel = allPlantationsSel.unmask(0).and(natPlantations.unmask(0)).selfMask();
          } else { // 'Replace global'
            allPlantationsSel = natPlantations;
          }
        }
      }

      // Save the pre-FRA-filter thresholded tree cover layer BEFORE the
      // P1.18 exclusion overwrites forest_map_clip. Lets the map show
      // the broader "Input: Tree cover" layer alongside the FRA-strict
      // Forest baseline -- workshop users see the full FRA hierarchy
      // progression on the map: Tree cover -> Forest -> Naturally
      // regenerating -> Forest outside buffers -> Primary.
      var tree_cover_clip = forest_map_clip;

      // ── Built-up areas (relocated to here in batch 25 so that the
      //    OLWTC exclusion below can reference urban tree cover. The
      //    distance buffers further down still use these same vars.) ──
      var builtUpSmall = ee.Image(0);
      if (includeGISD) {
        var gisdCollection = timeseriesAnthroModule.getGISDCollection();
        builtUpSmall = builtUpSmall.or(gisdCollection.filter(ee.Filter.eq('year', analysisYear)).first().eq(1)).updateMask(country_and_buffer_mask);
      }
      if (includeGISA) {
        var gisaCollection = timeseriesAnthroModule.getGISACollection();
        builtUpSmall = builtUpSmall.or(gisaCollection.filter(ee.Filter.eq('year', analysisYear)).first().eq(1)).updateMask(country_and_buffer_mask);
      }
      if (includeWSF) {
        var wsfCollection = timeseriesAnthroModule.getWSFCollection();
        builtUpSmall = builtUpSmall.or(wsfCollection.filter(ee.Filter.eq('year', analysisYear)).first().eq(1)).updateMask(country_and_buffer_mask);
      }
      if (includeGHSL) {
        var ghslCollection = timeseriesAnthroModule.getGhslCollection();
        var ghslSel = ghslCollection.filter(ee.Filter.eq('year', analysisYear)).first().updateMask(country_and_buffer_mask);
        builtUpSmall = builtUpSmall.or(ghslSel.eq(1));
        var builtUpLarge = ghslSel.eq(2);
      }

      // Merge national small built-up with global
      if (nationalBuiltupSmall.checkbox.getValue()) {
        var natBuiltupSmallAsset = nationalBuiltupSmall.getAsset(analysisYear);
        if (natBuiltupSmallAsset) {
          var natBuiltupSmallData = preprocessAsset(natBuiltupSmallAsset, nationalBuiltupSmall.getPreprocessingConfig()).updateMask(country_and_buffer_mask);
          if (nationalBuiltupSmall.modeSelect.getValue() === 'Replace global') {
            builtUpSmall = natBuiltupSmallData;
          } else {
            builtUpSmall = builtUpSmall.unmask(0).or(natBuiltupSmallData).selfMask();
          }
        }
      }

      // Merge national large built-up with global
      if (nationalBuiltupLarge.checkbox.getValue()) {
        var natBuiltupLargeAsset = nationalBuiltupLarge.getAsset(analysisYear);
        if (natBuiltupLargeAsset) {
          var natBuiltupLargeData = preprocessAsset(natBuiltupLargeAsset, nationalBuiltupLarge.getPreprocessingConfig()).updateMask(country_and_buffer_mask);
          var nbLargeMode = nationalBuiltupLarge.modeSelect.getValue();
          if (nbLargeMode === 'Replace global') {
            builtUpLarge = natBuiltupLargeData;
          } else if (nbLargeMode === 'Agreement with global') {  // P1.23
            builtUpLarge = builtUpLarge.unmask(0).and(natBuiltupLargeData.unmask(0)).selfMask();
          } else { // 'Add to global extent'
            builtUpLarge = builtUpLarge.unmask(0).or(natBuiltupLargeData).selfMask();
          }
        }
      }

      // Batch 25: OLWTC bucket per FRA Note 10 = "non-Forest land with
      // tree cover". Includes: oil palm + SDPT class 2 tree crops +
      // URBAN TREE COVER (tree-covered pixels inside built-up, small
      // or large). Each urban-tree-cover pixel must genuinely have
      // tree cover (intersection with the chosen source) -- so no
      // bare-rooftop overshoot. Used in the FRA-strict Forest-baseline
      // exclusion below. End-of-pipeline 04a_primary_forest unchanged
      // (built-up was always in the disturbance buffer); 02c_forest
      // shrinks slightly in cities -- FRA-correct.
      var _builtUpLargeOrEmpty = (typeof builtUpLarge !== 'undefined' && builtUpLarge)
        ? builtUpLarge : ee.Image(0);
      var urbanTreeCover = builtUpSmall.unmask(0)
          .or(_builtUpLargeOrEmpty.unmask(0))
          .and(tree_cover_clip.unmask(0));
      var olwtc = oilPalmDescalsSel.unmask(0)
          .or(treeCropsSDPT.unmask(0))
          .or(urbanTreeCover);

      // Master-gate: same as nationalPlantations / applyCustomForestMerge.
      if (enableTreeCoverCustomCheckbox.getValue() &&
          nationalOLWTC.checkbox.getValue()) {
        var natOLWTCAsset = nationalOLWTC.getAsset(analysisYear);
        if (natOLWTCAsset) {
          var natOLWTCData = preprocessAsset(natOLWTCAsset, nationalOLWTC.getPreprocessingConfig()).updateMask(country_and_buffer_mask);
          var nOlwtcMode = nationalOLWTC.modeSelect.getValue();
          if (nOlwtcMode === 'Add to global extent') {
            olwtc = olwtc.unmask(0).or(natOLWTCData).selfMask();
          } else if (nOlwtcMode === 'Agreement with global') {
            olwtc = olwtc.unmask(0).and(natOLWTCData.unmask(0)).selfMask();
          } else {
            olwtc = natOLWTCData;
          }
        }
      }

      // P1.18: FRA-aligned Forest baseline. When ticked, exclude OLWTC
      // (non-Forest tree cover -- oil palm + SDPT class 2 + urban tree
      // cover) from forest_map_clip BEFORE the natreg derivation. This
      // narrows the Forest baseline (02c) to the FRA-strict definition:
      // tree cover meeting biophysical thresholds AND not in OLWTC.
      // Default ON (FRA-correct); when on, 02c_forest area shrinks but
      // 04a_primary_forest is essentially unchanged.
      // P1.23: exclusionActive() guards against a hidden checkbox with
      // a stale `true` value being applied -- e.g. user ticked exclude
      // plantations under "All tree cover", then switched declaration
      // to "Naturally regenerating forest" which hides the toggle.
      if (exclusionActive(excludeAgricultureFromForestCheckbox, excludeAgriPanel)) {
        forest_map_clip = forest_map_clip.updateMask(olwtc.not());
      }

      // P1.16: don't overwrite forest_map_clip in-place; compute a
      // parallel forest_natreg_image so both the FRA Forest baseline
      // (forest_map_clip) and the Naturally Regenerating Forest
      // derivation (forest_natreg_image) survive for export, map
      // display, and stats. Downstream tier analysis switches to
      // forest_baseline (= natreg if available, else forest) so primary
      // forest is computed from the most-refined available baseline.
      var forest_natreg_image = null;
      if (exclusionActive(includePlantationsCheckbox, includePlantationsPanel)) {  // P1.23: hidden-toggle guard
        forest_natreg_image = forest_map_clip.updateMask(
          allPlantationsSel.unmask().not());
      } else if (inputCategorySelect.getValue() === INPUT_CATEGORY_NATREG ||
                inputCategorySelect.getValue() === INPUT_CATEGORY_PRIMARY) {
        // P1.23a: declaration says input is already at NRF level (or beyond).
        // Treat forest_map_clip directly as NRF for downstream layer/stats/
        // export linkage so the user sees an "NRF" layer/row and the
        // 02e_naturally_regenerating_forest export reflects the input.
        forest_natreg_image = forest_map_clip;
      }
      var forest_baseline = forest_natreg_image !== null
        ? forest_natreg_image
        : forest_map_clip;

      var croplandGladCollection = timeseriesAnthroModule.processingCroplandsGlad() 
  
    
      var croplandGladCollectionFF = forwardFillBinaryTimeSeries(croplandGladCollection, years);//forward filled version of processingCroplandsGlad i.e., cropland remains cropland 
      
      var croplandGladSel = ee.Image(croplandGladCollectionFF.filter(ee.Filter.eq("year",analysisYear)).first()).updateMask(country_and_buffer_mask)
      
      // var croplandGladSel = ee.Image(croplandGladCollection.filter(ee.Filter.eq("year",analysisYear)).first()).updateMask(country_and_buffer_mask)
      
      
      
      // Land cover classes
      var croplandClasses = [11, 12, 10];
      // var otherNatClasses = [120, 121, 122, 130, 140, 181, 182, 150, 152, 153];
      var croplandSel = remapClassesToOne(landcover, croplandClasses,0).unmask().updateMask(country_and_buffer_mask);
  
      // Processing parameters
      //many small cropland patches in forest - some are artefacts/noise. Smoothing can limit this effect
      var agriSmoothRadius = 30, agriSmallPixelThreshold = 0.5;
      
      
      var boxcar = ee.Kernel.circle({radius: agriSmoothRadius, units: 'meters', normalize: true});
      
      // Process cropland and agriculture
      // var croplandSelLessNoise = croplandSel.convolve(boxcar).gt(agriSmallPixelThreshold).convolve(boxcar).gt(agriSmallPixelThreshold);
      var croplandComb = croplandGladSel //.or(croplandSelLessNoise)// the removing small patches is slow for tihs

      // P1.20: agriculture aggregation now explicitly includes the
      // tree-cover-meeting agricultural sources (tree crops + oil palm)
      // since allPlantationsSel no longer carries them. Plus planted
      // forest stays in the buffering bucket -- for primary-forest
      // disturbance purposes large managed plantations DO disturb
      // adjacent natural forest (logging access, edge effects), even
      // though FRA classifies them as forest. Net pixel content
      // unchanged from pre-P1.20: cropland + pasture + tree crops +
      // oil palm + planted forest.
      var agriculture = pastureDatasetSel
                          .or(allPlantationsSel.unmask())   // SDPT class 1 -- planted forest, buffered for primary
                          .or(treeCropsSDPT.unmask())       // SDPT class 2 -- FRA agriculture
                          .or(oilPalmDescalsSel.unmask())   // Descals oil palm -- FRA agriculture
                          .or(croplandComb);                // GLAD croplands

      // Override agriculture with national data if provided
      if (nationalAgri.checkbox.getValue()) {
        var natAgriAsset = nationalAgri.getAsset(analysisYear);
        if (natAgriAsset) {
          var natAgri = preprocessAsset(natAgriAsset, nationalAgri.getPreprocessingConfig()).updateMask(country_and_buffer_mask);
          var naMode = nationalAgri.modeSelect.getValue();
          if (naMode === 'Add to global extent') {
            agriculture = agriculture.unmask(0).or(natAgri).selfMask();
          } else if (naMode === 'Agreement with global') {  // P1.23
            agriculture = agriculture.unmask(0).and(natAgri.unmask(0)).selfMask();
          } else { // 'Replace global'
            agriculture = natAgri;
          }
        }
      }

      // pffAddLayer(plantationsMosaicStatic,"","plantationsMosaicStatic")

      // pffAddLayer(country_and_buffer_mask,'',"country_and_buffer_mask")

      if (addInputLayersToMap.getValue())
        pffAddLayer(allPlantationsSel.selfMask(), {palette: '#d4a017'}, 'Planted forest', visibleLayers.plantations, 0.7);
      // pffAddLayer(pastureDatasetSel,"","pastureDatasetSel")
      // pffAddLayer(croplandComb,"","croplandComb")

      // Road data
      var roadsMosaicStatic = timeseriesAnthroModule.roadsMosaicStatic().updateMask(country_and_buffer_mask);
    
      // var msRoadsImage = ee.Image("projects/ee-andyarnellgee/assets/crosscutting/infrastructure/roads_microsoft/roadsAllImageGlobal");
      // var msRoadsImageBinary = msRoadsImage.gt(0).rename("constant")//change any width values 1 and rename
      // var roadsMosaicStatic = msRoadsImageBinary.updateMask(country_and_buffer_mask);
    
      var roadsCollection = timeseriesAnthroModule.getRoadsCollection();//has traffic inlcuded
      var roadsSel = roadsCollection.filter(ee.Filter.eq('year', analysisYear)).first().updateMask(country_and_buffer_mask);
      
      //test speed without vector roads
      // var roadsSmall = roadsSel.lte(roadSizeThreshold).unmask().or(roadsMosaicStatic);
      // var roadsLarge = roadsSel.gt(roadSizeThreshold);
      
      var roadsSmall = roadsMosaicStatic;

      // Merge national roads with global
      if (nationalRoads.checkbox.getValue()) {
        var natRoadsAsset = nationalRoads.getAsset(analysisYear);
        if (natRoadsAsset) {
          var natRoads = preprocessAsset(natRoadsAsset, nationalRoads.getPreprocessingConfig()).updateMask(country_and_buffer_mask);
          if (nationalRoads.modeSelect.getValue() === 'Replace global') {
            roadsSmall = natRoads;
          } else {
            roadsSmall = roadsSmall.unmask(0).or(natRoads).selfMask();
          }
        }
      }

      //waterways
      var wdb_nav_rivers = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/wdb_navigable_rivers")
      var nav_rivers = ee.Image().paint(wdb_nav_rivers, 1).updateMask(country_and_buffer_mask);
      
      var nav_wways_usa = ee.FeatureCollection("projects/ee-andyarnellgee/assets/crosscutting/nav_wways_usa");
      var osm_water = ee.ImageCollection("projects/sat-io/open-datasets/OSM_waterLayer");
      var osmCanals = osm_water.median().eq(4)
      
      // Map.addLayer(osmCanals,{min:0,max:1,palette:["blue"]},'OSM Water Global -canals')
      
      // Map.addLayer(nav_wways_usa,{min:0,max:1,palette:["red"]},"nav_wways_usa" )
      
      // Built-up areas: defined earlier in batch 25 (above the OLWTC
      // exclusion) so urbanTreeCover could reference them. The vars
      // builtUpSmall + builtUpLarge are in scope here from that block.

      // Check cache first before calculating distance transforms
      var dist_road_small, dist_built_up_small, dist_built_up_large, dist_agriculture;
      
      
          
          
      // caching check box in addLayersToMap function
      if (useCachingCheckbox/*.getValue()*/ && cachedState.distanceImages[analysisYear + '_road_small']) {
        // Use cached distance images
        dist_road_small = cachedState.distanceImages[analysisYear + '_road_small'];
        dist_built_up_small = cachedState.distanceImages[analysisYear + '_built_up_small'];
        dist_built_up_large = cachedState.distanceImages[analysisYear + '_built_up_large'];
        dist_agriculture = cachedState.distanceImages[analysisYear + '_agriculture'];
        //debug print('Using cached distance images for year: ' + analysisYear);
      } else {
        // Calculate distance transforms
          dist_road_small = makeDistanceSurface(roadsSmall, fastBuffer);
          dist_built_up_small = makeDistanceSurface(builtUpSmall, fastBuffer);
          dist_built_up_large = makeDistanceSurface(ghslSel.eq(2), fastBuffer);
          dist_agriculture = makeDistanceSurface(agriculture, fastBuffer);
        
        // Only cache if caching is enabled
        if (useCachingCheckbox/*.getValue()*/) {
          cachedState.distanceImages[analysisYear + '_road_small'] = dist_road_small;
          cachedState.distanceImages[analysisYear + '_built_up_small'] = dist_built_up_small;
          cachedState.distanceImages[analysisYear + '_built_up_large'] = dist_built_up_large;
          cachedState.distanceImages[analysisYear + '_agriculture'] = dist_agriculture;
          //debug print('Calculated and cached distance images for year: ' + analysisYear);
        } else {
          //debug print('Calculated distance images without caching for year: ' + analysisYear);
        }
      }
      
      
      // ///////////////// testing caching
      // var distImageTest = cachedState.distanceImages[analysisYear + '_road_small'];

      // if (distImageTest) {
      //   pffAddLayer(
      //     distImageTest, 
      //     {min: 0, max: 5000, palette: ['white', 'blue', 'darkblue']}, 
      //     'Distance to small roads (' + analysisYear + ')'
      //   );
      // } else {
      //   print('No cached distance image found for:', analysisYear + '_road_small');
      // }
      
      // if (cachedState.distanceImages[analysisYear + '_road_small']) {
      //   // Use cached distance images
      //   dist_road_small = cachedState.distanceImages[analysisYear + '_road_small'];
      //   dist_road_large = cachedState.distanceImages[analysisYear + '_road_large'];
      //   dist_built_up_small = cachedState.distanceImages[analysisYear + '_built_up_small'];
      //   dist_built_up_large = cachedState.distanceImages[analysisYear + '_built_up_large'];
      //   dist_agriculture = cachedState.distanceImages[analysisYear + '_agriculture'];
      //   print('Using cached distance images for year: ' + analysisYear);
      // } else {
      //   // Calculate distance transforms ONCE and cache them
      //   dist_road_small = makeDistanceSurface(roadsSmall, fastBuffer);
      //   dist_road_large = makeDistanceSurface(roadsLarge, fastBuffer);
      //   dist_built_up_small = makeDistanceSurface(builtUpSmall, fastBuffer);
      //   dist_built_up_large = makeDistanceSurface(ghslSel.eq(2), fastBuffer);
      //   dist_agriculture = makeDistanceSurface(agriculture, fastBuffer);
        
      //   // Cache distance images
      //   cachedState.distanceImages[analysisYear + '_road_small'] = dist_road_small;
      //   cachedState.distanceImages[analysisYear + '_road_large'] = dist_road_large;
      //   cachedState.distanceImages[analysisYear + '_built_up_small'] = dist_built_up_small;
      //   cachedState.distanceImages[analysisYear + '_built_up_large'] = dist_built_up_large;
      //   cachedState.distanceImages[analysisYear + '_agriculture'] = dist_agriculture;
      //   print('Calculated and cached distance images for year: ' + analysisYear);
      // }
    
      
      // 3. Apply thresholds 
      var buffer_from_road_small = applyDistanceThreshold(dist_road_small, roadSmallBuffer);
      // large roads removed — single roads category only
      var buffer_from_built_up_small = applyDistanceThreshold(dist_built_up_small, builtUpSmallBuffer);
      var buffer_from_built_up_large = applyDistanceThreshold(dist_built_up_large, builtUpLargeBuffer);
      var buffer_from_agriculture = applyDistanceThreshold(dist_agriculture, agriBuffer);
      
      
      ///////////////
      // // Buffer calculations
      // var buffer_from_road_small = makeDistanceBuffer(roadsSmall, roadSmallBuffer, fastBuffer);
      // var buffer_from_road_large = makeDistanceBuffer(roadsLarge, roadLargeBuffer, fastBuffer);
      // var buffer_from_built_up_small = makeDistanceBuffer(builtUpSmall, builtUpSmallBuffer, fastBuffer);
      // var buffer_from_built_up_large = makeDistanceBuffer(ghslSel.eq(2), builtUpLargeBuffer, fastBuffer);
      // var buffer_from_agriculture = makeDistanceBuffer(agriculture, agriBuffer, fastBuffer);
      // // var buffer_from_otherNatural = makeDistanceBuffer(otherNaturalDataset, otherNatBuffer, fastBuffer);
      
      
    ////////////// 
          // Define visualization parameters for each binary buffer
      var visParams = [
          {image: buffer_from_road_small,   color: 'red',         name: 'Buffer: Roads'},
          // large roads removed
          {image: buffer_from_built_up_small, color: 'brown',    name: 'Buffer: Small Built-up'},
          {image: buffer_from_built_up_large, color: 'orange',    name: 'Buffer: Large Built-up'},
          {image: buffer_from_agriculture,  color: 'pink',       name: 'Buffer: Agriculture'},
          // {image: buffer_from_otherNatural, color: 'purple',      name: 'Buffer: Other Natural'}
      ];
      
      // Function to generate visualization parameters for binary masks
      function getVisParams(color) {
          return {
              min: 0,
              max: 1,
              palette: [color]
          };
      }
      
      // Add buffer layers — only when master toggle on AND per-buffer enabled.
      // Order: agriculture (bottom), roads, small built-up, large built-up (top)
      if (addInputLayersToMap.getValue()) {
        if (enableAgriBuffer.getValue())
          pffAddLayer(buffer_from_agriculture, getVisParams('#ffcc00'), 'Buffer: Agriculture', visibleLayers.agriBuffer, 0.5);
        if (enableRoadsBuffer.getValue())
          pffAddLayer(buffer_from_road_small, getVisParams('#ff6600'), 'Buffer: Roads', visibleLayers.roadSmallBuffer, 0.5);
        if (enableBuiltUpSmallBuffer.getValue())
          pffAddLayer(buffer_from_built_up_small, getVisParams('#cc00cc'), 'Buffer: Small Built-up', visibleLayers.builtSmallBuffer, 0.5);
        if (enableBuiltUpLargeBuffer.getValue())
          pffAddLayer(buffer_from_built_up_large, getVisParams('#3333cc'), 'Buffer: Large Built-up', visibleLayers.builtLargeBuffer, 0.5);
      }

      // Processed binary inputs — what actually feeds the distance transforms.
      // Gated on master toggle (computation still happens regardless).
      // Order: agriculture (bottom), roads, small built-up, large built-up (top)
      if (addInputLayersToMap.getValue()) {
        pffAddLayer(agriculture.selfMask(), getVisParams('#b38f00'), 'Input: Agriculture',   visibleLayers.inputAgriculture, 0.9);
        pffAddLayer(roadsSmall.selfMask(),   getVisParams('#993d00'), 'Input: Roads',         visibleLayers.inputRoads,       0.9);
        pffAddLayer(builtUpSmall.selfMask(), getVisParams('#800080'), 'Input: Small Built-up',visibleLayers.inputBuiltupSmall,0.9);
        if (builtUpLarge) {
          pffAddLayer(builtUpLarge.selfMask(), getVisParams('#1a1a80'), 'Input: Large Built-up',visibleLayers.inputBuiltupLarge, 0.9);
        }
      }

    ///////////////
      
      
      
      // Combine buffers (only include enabled ones)
      var activeBuffers = [];
      if (enableRoadsBuffer.getValue()) activeBuffers.push(buffer_from_road_small);
      if (enableBuiltUpSmallBuffer.getValue()) activeBuffers.push(buffer_from_built_up_small);
      if (enableBuiltUpLargeBuffer.getValue()) activeBuffers.push(buffer_from_built_up_large);
      if (enableAgriBuffer.getValue()) activeBuffers.push(buffer_from_agriculture);
      // Fallback: if nothing enabled, use an empty (all-zero) buffer
      var buffer_from_anthro = activeBuffers.length > 0
          ? ee.ImageCollection(activeBuffers).reduce(ee.Reducer.anyNonZero())
          : ee.Image(0);


      var all_edge_effects = buffer_from_anthro.unmask()//.or(buffer_from_otherNatural.unmask());
      // var all_edge_effects = buffer_from_anthro.unmask().or(buffer_from_otherNatural.unmask());
      
      // Slope analysis (with caching)
      // Calculate slope only once per country, then reuse with different thresholds
      var slopeAreasToKeep;
      if (useCustomSlopeCheckbox.getValue() && customSlopeInput.getValue()) {
        // National slope raster (0-90°): apply threshold directly
        slopeAreasToKeep = ee.Image(customSlopeInput.getValue()).updateMask(country_and_buffer_mask).gt(slopeToKeepValue);
      } else {
        if (!cachedState.slopeImage || cachedState.country !== selectedCountry) {
          var alos_30m_elev = ee.ImageCollection('JAXA/ALOS/AW3D30/V3_2').select('DSM');
          cachedState.slopeImage = calculateSlope(alos_30m_elev, country_and_buffer_mask);
        }
        slopeAreasToKeep = cachedState.slopeImage.gt(slopeToKeepValue);
      }
      
      if (addInputLayersToMap.getValue() && enableSlope.getValue())
        pffAddLayer(slopeAreasToKeep.selfMask(), {palette: '#708090'}, 'Input: Slope > ' + slopeToKeepValue + '°', visibleLayers.slope, 0.5);
      
      // Protected areas analysis (using cached category masks)
      var wdpaYearCutoff = current_year - years_protected;
      var wdpa_filt_by_date_image = wdpaStatusYearGlobal.lte(wdpaYearCutoff);
      
      // Apply category mask if not using all categories
      if (selected_iucn_categories.length > 0 && selected_iucn_categories.length < 10) {
        var combinedCategoryMask = ee.Image(0);
        for (var i = 0; i < selected_iucn_categories.length; i++) {
          combinedCategoryMask = combinedCategoryMask.or(wdpaCategoryMasks[selected_iucn_categories[i]]);
        }
        wdpa_filt_by_date_image = wdpa_filt_by_date_image.updateMask(combinedCategoryMask);
      }
      
      wdpa_filt_by_date_image = wdpa_filt_by_date_image.selfMask().updateMask(country_and_buffer_mask);

      // Merge national protected areas with WDPA
      if (nationalProtected.checkbox.getValue()) {
        var natProtectedAsset = nationalProtected.getAsset(analysisYear);
        if (natProtectedAsset) {
          var natProtected = preprocessAsset(natProtectedAsset, nationalProtected.getPreprocessingConfig()).updateMask(country_and_buffer_mask);
          var npMode2 = nationalProtected.modeSelect.getValue();
          if (npMode2 === 'Replace global') {
            wdpa_filt_by_date_image = natProtected;
          } else if (npMode2 === 'Agreement with global') {  // P1.23
            wdpa_filt_by_date_image = wdpa_filt_by_date_image.unmask(0).and(natProtected.unmask(0)).selfMask();
          } else { // 'Add to global extent'
            wdpa_filt_by_date_image = wdpa_filt_by_date_image.unmask(0).or(natProtected).selfMask();
          }
        }
      }
      
      var wdpaLabel = 'Input: Protected Areas (≤' + wdpaYearCutoff + ', ' +
        (selected_iucn_categories.length === 10 ? 'All' : selected_iucn_categories.join(', ')) + ')';
      if (addInputLayersToMap.getValue() && enableProtectedAreas.getValue())
        pffAddLayer(wdpa_filt_by_date_image, {palette: '#00cccc'}, wdpaLabel, visibleLayers.protectedAreas, 0.5);
      
      // Add forest layer AFTER slope and WDPA so it appears above them
      if (useHansenTreecover) {
        // Determine which map this is
        var mapName = (map === map1) ? 'map1' : 'map2';
        var hansenLayer = (map === map1) ? hansenLayer1 : hansenLayer2;
        
        // Store forest data for later zoom updates
        currentForestData[mapName] = {
          forest_map_clip: forest_map_clip,
          analysisYear: analysisYear,
          country_sel: country_sel
        };
        
        // P1.26: gate Hansen tile-rendering path with skipMap. The
        // map.layers().add() and updateHansenLayer() (which calls
        // setEeObject) both trigger tile fetches.
        if (!skipMap) {
          // Add the Hansen layer to the map if not already added
          var layers = map.layers();
          var layerExists = false;
          for (var i = 0; i < layers.length(); i++) {
            if (layers.get(i) === hansenLayer) {
              layerExists = true;
              break;
            }
          }
          if (!layerExists) {
            map.layers().add(hansenLayer);
          }

          // Initial render with current zoom
          updateHansenLayer(map, mapName, hansenLayer);
        }
        
      } else {
        // P1.23a: skip layers that would visually duplicate the row
        // above. A layer is meaningful only when it represents a
        // distinct refinement step from the prior layer.
        // - Tree cover: shown when declared ALL (it's the input).
        // - Forest: shown when distinct from Tree cover -- i.e. OLWTC
        //   was applied (declared ALL) or input IS Forest (declared FOREST).
        // - NRF: shown when forest_natreg_image differs from Forest --
        //   i.e. planted toggle on (declared ALL or FOREST) or input IS
        //   NRF (declared NATREG).
        // Without these guards, e.g. declared ALL with both toggles off
        // produces 3 visually-identical green layers (Tree cover ==
        // Forest, NRF skipped), which clutters the EE Layers dropdown.
        var mapDeclCat = inputCategorySelect.getValue();
        var mapOlwtcApplied = exclusionActive(excludeAgricultureFromForestCheckbox, excludeAgriPanel);
        var mapPlantedApplied = exclusionActive(includePlantationsCheckbox, includePlantationsPanel);
        // Input layer: always added. When no FRA category declared the
        // map shows just `Input` + `Primary forest`. When a category is
        // declared, the input layer carries the declared name (Tree cover,
        // Forest, etc.).
        var mapShowInput = (mapDeclCat === INPUT_CATEGORY_NONE
                            || !mapDeclCat || mapDeclCat === '');
        var mapShowTreeCover = (mapDeclCat === INPUT_CATEGORY_ALL);
        var mapShowForest = (mapDeclCat === INPUT_CATEGORY_ALL && mapOlwtcApplied) ||
                            (mapDeclCat === INPUT_CATEGORY_FOREST);
        var mapShowNrf = ((mapDeclCat === INPUT_CATEGORY_ALL ||
                          mapDeclCat === INPUT_CATEGORY_FOREST) && mapPlantedApplied) ||
                        (mapDeclCat === INPUT_CATEGORY_NATREG);

        if (mapShowInput) {
          pffAddLayer(tree_cover_clip.selfMask(), binary_palegreen_palette,
            "Input", visibleLayers.treeCover, 1);
        }
        if (mapShowTreeCover) {
          pffAddLayer(tree_cover_clip.selfMask(), binary_palegreen_palette,
            "Input: Tree cover", visibleLayers.treeCover, 1);
        }
        if (mapShowForest) {
          pffAddLayer(forest_map_clip.selfMask(), binary_lightgreen_palette,
            "Forest", visibleLayers.forest, 1);
        }
        if (mapShowNrf && forest_natreg_image !== null) {
          pffAddLayer(forest_natreg_image.selfMask(), binary_medgreen_palette,
            'Naturally regenerating forest', visibleLayers.naturallyRegenerating, 1);
        }
      }

      // Decision tree -- use the most-refined baseline available
      // (P1.16: forest_baseline = natreg when produced, else forest)
      var step_1_1 = generateOutcomeMaps(forest_baseline, all_edge_effects);
      var forest_map_1_1_y = step_1_1.yes;  // inside buffers
      var forest_map_1_1_n = step_1_1.no;   // outside buffers

      // Step 1.2: slope rescue (optional)
      var forest_map_1_2_y, forest_map_1_2_n;
      if (enableSlope.getValue()) {
        var step_1_2 = generateOutcomeMaps(forest_map_1_1_y, slopeAreasToKeep);
        forest_map_1_2_y = step_1_2.yes;  // steep slope rescue
        forest_map_1_2_n = step_1_2.no;   // not rescued by slope
      } else {
        forest_map_1_2_y = forest_map_1_1_y.updateMask(ee.Image(0)); // empty — no rescue
        forest_map_1_2_n = forest_map_1_1_y; // all go to next step
      }

      // Step 1.3: protected area rescue (optional)
      var forest_map_1_3_y, forest_map_1_3_n;
      if (enableProtectedAreas.getValue()) {
        var step_1_3 = generateOutcomeMaps(forest_map_1_2_n, wdpa_filt_by_date_image);
        forest_map_1_3_y = step_1_3.yes;  // protected rescue
        forest_map_1_3_n = step_1_3.no;   // not rescued
      } else {
        forest_map_1_3_y = forest_map_1_2_n.updateMask(ee.Image(0)); // empty — no rescue
        forest_map_1_3_n = forest_map_1_2_n;
      }

      // Combine outcomes
      var combined_map = forest_map
        .where(forest_map_1_1_y.mask(), 1)
        .where(forest_map_1_1_n.mask(), 2)
        .where(forest_map_1_2_y.mask(), 3)
        .where(forest_map_1_2_n.mask(), 4)
        .where(forest_map_1_3_y.mask(), 5)
        .where(forest_map_1_3_n.mask(), 6)
        .where(forest_map.eq(0), 0);

      // Primary forest identification
      var all_forest_1_1_to_1_3 = combined_map.eq(2).or(combined_map.eq(3)).or(combined_map.eq(5));
        pffAddLayer(all_forest_1_1_to_1_3.selfMask(), binary_green_palette, "Pre-refinement primary", visibleLayers.forestOutsideBuffers, 1);

      // Large forest patches (connectivity filtering)
      var largeForestPatches;
      if (enableRefineOutput.getValue()) {
        var density = all_forest_1_1_to_1_3.reduceNeighborhood({
          reducer: ee.Reducer.sum(),
          kernel: ee.Kernel.circle({radius: smoothRadiusForest, units: 'meters'}),
          skipMasked: false,
        });
        largeForestPatches = density.gt(smallPixelThresholdForest).updateMask(all_forest_1_1_to_1_3);
      } else {
        // Skip refinement — all pre-connectivity forest becomes primary
        largeForestPatches = all_forest_1_1_to_1_3;
      }
        pffAddLayer(largeForestPatches.selfMask(), binary_darkgreen_palette, 'Primary Forest', visibleLayers.primaryForest, 1);

      // Additional datasets 
      
      //for comparison / verification
      
      // Reference / comparison overlays (FLII / FDaP / Custom). Built via
      // the shared buildReferenceLayers() so the Validation toggles can
      // add/remove them standalone (refreshReferenceLayers) without a full
      // re-run. pffAddLayer respects the disable-map mode.
      buildReferenceLayers(country_and_buffer_mask).forEach(function(r) {
        pffAddLayer(r.img, r.vis, r.name, true, r.opacity);
      });

      //european primary forests database    
      // var epfd_2018_polys = ee.FeatureCollection("HU_BERLIN/EPFD/V2/polygons");
      // var epfd_2018_image = ee.Image(0).paint(epfd_2018_polys, 1).int8().selfMask();
      // pffAddLayer(epfd_2018_image.updateMask(country_and_buffer_mask),{min:0, max:1, palette:["brown"]}, "EPFD 2018", 0, 1);

      // Area calculations - store for later stats button
      var masked_tree_cover = tree_cover_clip.updateMask(country_clip);
      var masked_forest = forest_map_clip.updateMask(country_clip);
      var masked_primary_forest = largeForestPatches.updateMask(country_clip);

      // Store forest data for statistics (accessed by "Show Area Statistics" button)
      latestMaskedTreeCover[analysisYear] = masked_tree_cover;
      latestMaskedForest[analysisYear] = masked_forest;
      latestMaskedPrimaryForest[analysisYear] = masked_primary_forest;
      // P1.16: store Naturally regenerating forest separately when
      // produced. Stats panel reads this in addition to (not instead
      // of) Forest, so both rows appear when plantations refinement
      // ran. Primary forest is reported under nat reg in the hierarchy
      // (subset, not sibling category).
      if (forest_natreg_image !== null) {
        latestMaskedNaturallyRegenerating[analysisYear] =
          forest_natreg_image.updateMask(country_clip);
      } else {
        delete latestMaskedNaturallyRegenerating[analysisYear];
      }
      latestPreConnectivityForest[analysisYear] = all_forest_1_1_to_1_3.updateMask(country_clip);
      latestTier1Undisturbed[analysisYear] = forest_map_1_1_n.updateMask(country_clip);
      latestTier2Steep[analysisYear] = forest_map_1_2_y.updateMask(country_clip);
      latestTier3Protected[analysisYear] = forest_map_1_3_y.updateMask(country_clip);
    }
    
    // print('Cached distance keys:', Object.keys(cachedState.distanceImages));
    
    // Baseline forest construction for the multi-year constraint:
    // mirror the per-year forest derivation but force it to the earliest
    // year. addLayersToMap will AND each non-baseline year's forest_map
    // with this mask so primary forest can't expand into pixels that were
    // not forest at baseline.
    if (useSplitScreen && analysisYear1 !== analysisYear2) {
      baselineForestYear = Math.min(analysisYear1, analysisYear2);
      var _bf = null;
      if (useAgreementForest) {
        _bf = agreementForestPrep(baselineForestYear, treecoverPercentThreshold, treecoverHeightThreshold);
      } else if (useUnionForest) {
        _bf = unionForestPrep(baselineForestYear, treecoverPercentThreshold, treecoverHeightThreshold);
      } else if (useGladLulcForest) {
        _bf = gladLulcForestPrep(baselineForestYear, treecoverHeightThreshold);
      } else if (useHansenTreecover) {
        _bf = gfcHansenTreecoverPrep(baselineForestYear, treecoverPercentThreshold);
      }
      if (_bf !== null) {
        _bf = applyCustomForestMerge(_bf, baselineForestYear);
        baselineForestMask = _bf;
        print('Baseline forest constraint active: year ' + baselineForestYear +
              ' mask will be intersected with the other year\'s forest.');
      }
    }

    // Add layers to maps
    if (useSplitScreen) {
      addLayersToMap(map1, analysisYear1);
      addLayersToMap(map2, analysisYear2);
    } else {
      // Single map mode - only render map2
      addLayersToMap(map2, analysisYear2);
    }
    
    // Always print current centers at end for debugging
    if (map1) logCenterExplicit('map1 final', map1Center, map1Zoom);
    if (map2) logCenterExplicit('map2 final', map2Center, map2Zoom);
    
    // Update previous state
    previousState.country = selectedCountry;
    previousState.splitScreen = useSplitScreen;
    previousCountry = selectedCountry;

    // P1.25: keep the floating legend in sync with the layer set we just
    // added. Cheap UI-only op (no GEE compute) -- safe to run on every
    // updateMap call. _legendRefreshFns is populated by createLegendPanel
    // (each call pushes the legend's refreshLegend closure).
    _legendRefreshFns.forEach(function(fn) { fn(); });
  }

  // Initial map update
  updateMap();
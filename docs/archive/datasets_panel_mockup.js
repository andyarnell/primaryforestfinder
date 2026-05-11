// =============================================================================
// PFF Datasets Info — GEE UI mockup
// =============================================================================
// Two patterns shown:
//   (A) Full Datasets panel — scrollable list, all datasets, grouped.
//       Accessed via a "Datasets" button in the top bar (mirrors the About panel).
//   (B) Per-section (i) popup — tiny info button next to e.g. the forest source
//       dropdown or the buffer sliders, opens a small floating card for that
//       single dataset.
//
// Both are data-driven from docs/datasets_global.json (loaded once at startup
// — in production, host the JSON as a GEE asset or inline it as a module).
// Below the JSON is inlined as DATASETS_INDEX for the mockup.
//
// Drop-in: copy into pff_4.js or import as a module. Wire up two buttons:
//   datasetsButton.onClick(showDatasetsPanel);
//   forestSourceInfoBtn.onClick(function(){ showInfoPopup('hansen_gfc_v1_12'); });
// =============================================================================

// ── INLINED INDEX (subset for the mockup; full version = docs/datasets_global.json) ──
var DATASETS_INDEX = {
  groups: {
    forest_cover: 'Forest cover',
    forest_reference: 'Reference layers',
    administrative: 'Administrative',
    protected_areas: 'Protected areas',
    terrain: 'Terrain',
    built_up: 'Built-up',
    population: 'Population',
    land_cover_agriculture: 'Land cover / agriculture',
    plantations_treecrops: 'Plantations & tree crops',
    roads_infrastructure: 'Roads',
    disturbance_history: 'Disturbance history',
    water_waterways: 'Water / waterways',
    ancillary_unused: 'Queued (workshop / swap-in)'
  },
  datasets: [
    // shortened — production version reads docs/datasets_global.json
    {
      id: 'hansen_gfc_v1_12',
      name: 'Hansen Global Forest Change v1.12',
      group: 'forest_cover',
      status: 'active',
      role_in_pff: "Tree-cover-2000 + lossyear; 'Hansen GFC' / 'Agreement' / 'Combined' modes.",
      preprocessing_in_pff: 'tree2000 > threshold AND (no loss OR loss after analysisYear); selfMask. UI threshold default 10%.',
      citation: {
        text: 'Hansen, M.C. et al. (2013). High-Resolution Global Maps of 21st-Century Forest Cover Change. Science 342, 850–853.',
        doi_url: 'https://doi.org/10.1126/science.1244693',
        documentation: 'https://glad.umd.edu/dataset/global-forest-change'
      }
    },
    {
      id: 'glad_glclu2020_v2',
      name: 'GLAD GLCLU 2000–2020 v2',
      group: 'forest_cover',
      status: 'active',
      role_in_pff: "Default forest source ('GLAD LULC'). Tree-height threshold (default ≥ 5 m).",
      preprocessing_in_pff: 'Remap classes 25–48 / 125–148 to height (m); height ≥ user threshold.',
      citation: {
        text: 'Potapov, P. et al. (2022). Front. Remote Sens. 3, 856903.',
        doi_url: 'https://doi.org/10.3389/frsen.2022.856903',
        documentation: 'https://glad.umd.edu/dataset/GLCLUC2020'
      }
    },
    {
      id: 'wdpa_wcmc_current',
      name: 'WDPA — World Database on Protected Areas',
      group: 'protected_areas',
      status: 'active',
      role_in_pff: 'Tier 1.3 protected-area rescue. Default IUCN strict (Ia, Ib, II); ≥30 yr designation.',
      preprocessing_in_pff: 'Drop STATUS Proposed/Not Reported + UNESCO-MAB. Per-IUCN-cat masks cached at startup; min(STATUS_YR) for year filter.',
      citation: {
        text: 'UNEP-WCMC and IUCN (2026). Protected Planet: WDPA.',
        doi_url: 'https://doi.org/10.34892/6fwd-af11',
        documentation: 'https://www.protectedplanet.net/'
      }
    },
    {
      id: 'alos_aw3d30_v3_2',
      name: 'JAXA ALOS World 3D-30m v3.2',
      group: 'terrain',
      status: 'active',
      role_in_pff: 'DEM for Tier 1.2 steep-slope rescue + 03b sidecar.',
      preprocessing_in_pff: 'select(DSM).mosaic(); slope via ee.Terrain.slope at 30 m.',
      citation: {
        text: 'Tadono, T. et al. (2016). ISPRS Archives XLI-B4, 157–162.',
        doi_url: 'https://doi.org/10.5194/isprs-archives-XLI-B4-157-2016',
        documentation: 'https://www.eorc.jaxa.jp/ALOS/en/dataset/aw3d30/'
      }
    },
    {
      id: 'ghsl_smod_p2023a',
      name: 'JRC GHSL — SMOD + POP P2023A',
      group: 'built_up',
      status: 'active',
      role_in_pff: 'Built-up small (SMOD 11–12) + large (>12), masked by GHS_POP > 0.',
      preprocessing_in_pff: '1990/2000/2010/2015/2020 epochs. Combined with WSF EVO via OR for the small bucket.',
      citation: {
        text: 'Pesaresi, M. et al. (2024). Int. J. Digital Earth 17(1).',
        doi_url: 'https://doi.org/10.1080/17538947.2024.2390454',
        documentation: 'https://human-settlement.emergency.copernicus.eu/'
      }
    },
    {
      id: 'fdap_palm_2024a',
      name: 'FDAP Palm Probability — model 2024a',
      group: 'plantations_treecrops',
      status: 'optional_default_off',
      role_in_pff: 'Loaded but DISABLED — commits primary forest as palm. Workshop: discuss whether to re-enable.',
      preprocessing_in_pff: '.first().gt(0.95) + boxcar smoothing. NOT OR\'d into plantations mosaic.',
      citation: {
        text: 'Forest Data Partnership / Google (2024). FDAP Palm model 2024a.',
        documentation: 'https://www.forestdatapartnership.org/'
      }
    },
    {
      id: 'wri_sbtn_natural_lands_v1_1',
      name: 'WRI SBTN Natural Lands Map v1.1',
      group: 'ancillary_unused',
      status: 'queued',
      role_in_pff: 'Not used. Commented-out reference in timeSeriesAnthro.js — workshop swap-in candidate.',
      citation: {
        text: 'Mazur, E. et al. (2025). SBTN Natural Lands Map v1.1 Tech Doc.',
        documentation: 'https://landcarbonlab.org/data/natural-lands-map/'
      }
    }
    // ... 25+ more in production (read from datasets_global.json)
  ]
};

// ── STATUS CHIP STYLE ──
function statusChip(status) {
  var colour = ({
    active: '#2e7d32',
    optional_default_off: '#f57c00',
    queued: '#757575',
    deprecated: '#c62828'
  })[status] || '#555';
  var label = ({
    active: 'ACTIVE',
    optional_default_off: 'OPT (off)',
    queued: 'QUEUED',
    deprecated: 'DEPRECATED'
  })[status] || status.toUpperCase();
  return ui.Label(label, {
    color: 'white', backgroundColor: colour,
    fontSize: '9px', fontWeight: 'bold',
    margin: '0 0 0 6px', padding: '1px 4px'
  });
}

// ── PATTERN A: full Datasets panel ──
// Scrollable, grouped, one card per dataset. Mirrors the About panel layout.
function buildDatasetCard(d) {
  var titleRow = ui.Panel({
    widgets: [
      ui.Label(d.name, {fontWeight: 'bold', fontSize: '12px', margin: '0', stretch: 'horizontal'}),
      statusChip(d.status)
    ],
    layout: ui.Panel.Layout.flow('horizontal'),
    style: {margin: '0 0 2px 0'}
  });

  var widgets = [titleRow];
  if (d.role_in_pff) {
    widgets.push(ui.Label('Role: ' + d.role_in_pff,
      {fontSize: '11px', margin: '0 0 2px 0', color: '#333'}));
  }
  if (d.preprocessing_in_pff) {
    widgets.push(ui.Label('Preprocessing: ' + d.preprocessing_in_pff,
      {fontSize: '10px', margin: '0 0 2px 0', color: '#666', fontStyle: 'italic'}));
  }
  if (d.citation && d.citation.text) {
    widgets.push(ui.Label(d.citation.text,
      {fontSize: '10px', margin: '2px 0 0 0', color: '#444'}));
  }
  // Links row
  var linkWidgets = [];
  if (d.citation && d.citation.doi_url) {
    linkWidgets.push(ui.Label({
      value: 'DOI', targetUrl: d.citation.doi_url,
      style: {fontSize: '10px', color: 'blue', textDecoration: 'underline', margin: '0 8px 0 0'}
    }));
  }
  if (d.citation && d.citation.documentation) {
    linkWidgets.push(ui.Label({
      value: 'Docs', targetUrl: d.citation.documentation,
      style: {fontSize: '10px', color: 'blue', textDecoration: 'underline', margin: '0 8px 0 0'}
    }));
  }
  if (linkWidgets.length) {
    widgets.push(ui.Panel({
      widgets: linkWidgets, layout: ui.Panel.Layout.flow('horizontal'),
      style: {margin: '2px 0 0 0'}
    }));
  }

  return ui.Panel({
    widgets: widgets,
    layout: ui.Panel.Layout.flow('vertical'),
    style: {
      margin: '0 0 6px 0', padding: '6px',
      backgroundColor: 'rgba(255,255,255,0.6)',
      border: '1px solid #ddd'
    }
  });
}

function buildDatasetsPanel() {
  var groups = DATASETS_INDEX.groups;
  var datasets = DATASETS_INDEX.datasets;

  var closeBtn = ui.Button({
    label: '×',
    onClick: function() { datasetsContent.style().set('shown', false); },
    style: {padding: '0 6px', fontWeight: 'bold'}
  });
  var titleRow = ui.Panel({
    widgets: [
      ui.Label('Datasets used by Primary Forest Finder',
        {fontWeight: 'bold', fontSize: '13px', margin: '4px 0', stretch: 'horizontal'}),
      closeBtn
    ],
    layout: ui.Panel.Layout.flow('horizontal')
  });

  var legendRow = ui.Panel({
    widgets: [
      ui.Label('Legend:', {fontSize: '10px', margin: '0 4px 0 0'}),
      statusChip('active'),
      ui.Label('= used in every run.', {fontSize: '10px', margin: '0 8px 0 0'}),
      statusChip('optional_default_off'),
      ui.Label('= flag-flippable, off by default.', {fontSize: '10px', margin: '0 8px 0 0'}),
      statusChip('queued'),
      ui.Label('= referenced but not loaded.', {fontSize: '10px'})
    ],
    layout: ui.Panel.Layout.flow('horizontal'),
    style: {margin: '0 0 6px 0'}
  });

  var sections = [titleRow, legendRow];
  Object.keys(groups).forEach(function(groupKey) {
    var groupDatasets = datasets.filter(function(d) { return d.group === groupKey; });
    if (groupDatasets.length === 0) return;
    sections.push(ui.Label(groups[groupKey],
      {fontWeight: 'bold', fontSize: '11px', margin: '8px 0 2px 0', color: '#1565c0'}));
    groupDatasets.forEach(function(d) { sections.push(buildDatasetCard(d)); });
  });

  return ui.Panel({
    widgets: sections,
    layout: ui.Panel.Layout.flow('vertical'),
    style: {
      shown: false, padding: '8px',
      width: '420px', maxHeight: '90%',
      backgroundColor: 'rgba(255,255,255,0.95)'
    }
  });
}
var datasetsContent = buildDatasetsPanel();

// Top-bar button (place next to About / Recenter):
var datasetsButton = ui.Button({
  label: '📊 Datasets',
  onClick: function() {
    datasetsContent.style().set('shown',
      !datasetsContent.style().get('shown'));
  },
  style: {fontSize: '11px', margin: '2px 4px'}
});

// ── PATTERN B: per-section (i) popup ──
// Tiny floating card for one dataset. Tied to a specific UI element.
var infoPopupContent = ui.Panel({
  widgets: [],
  style: {
    shown: false, padding: '6px',
    width: '300px',
    backgroundColor: 'rgba(255,255,255,0.97)',
    border: '1px solid #888'
  }
});

function showInfoPopup(datasetId) {
  var d = DATASETS_INDEX.datasets.filter(
    function(x) { return x.id === datasetId; })[0];
  if (!d) {
    infoPopupContent.clear();
    infoPopupContent.add(ui.Label('No info found for: ' + datasetId,
      {fontSize: '10px', color: '#c00'}));
    infoPopupContent.style().set('shown', true);
    return;
  }

  infoPopupContent.clear();
  var closeBtn = ui.Button({label: '×',
    onClick: function() { infoPopupContent.style().set('shown', false); },
    style: {padding: '0 4px', fontSize: '11px'}});
  infoPopupContent.add(ui.Panel({
    widgets: [
      ui.Label(d.name, {fontWeight: 'bold', fontSize: '11px',
        margin: '0', stretch: 'horizontal'}),
      statusChip(d.status),
      closeBtn
    ],
    layout: ui.Panel.Layout.flow('horizontal')
  }));
  if (d.role_in_pff) {
    infoPopupContent.add(ui.Label(d.role_in_pff,
      {fontSize: '10px', margin: '2px 0', color: '#333'}));
  }
  if (d.citation) {
    if (d.citation.text) {
      infoPopupContent.add(ui.Label(d.citation.text,
        {fontSize: '10px', margin: '2px 0', color: '#555'}));
    }
    var links = [];
    if (d.citation.doi_url) links.push(ui.Label({
      value: 'DOI', targetUrl: d.citation.doi_url,
      style: {fontSize: '10px', color: 'blue',
        textDecoration: 'underline', margin: '0 8px 0 0'}}));
    if (d.citation.documentation) links.push(ui.Label({
      value: 'Docs', targetUrl: d.citation.documentation,
      style: {fontSize: '10px', color: 'blue',
        textDecoration: 'underline'}}));
    if (links.length) infoPopupContent.add(ui.Panel({
      widgets: links, layout: ui.Panel.Layout.flow('horizontal')
    }));
  }
  infoPopupContent.style().set('shown', true);
}

// Tiny info button you can place next to any slider/dropdown
function makeInfoButton(datasetId) {
  return ui.Button({
    label: 'ⓘ',
    onClick: function() { showInfoPopup(datasetId); },
    style: {padding: '0 4px', fontSize: '11px',
      margin: '0 0 0 2px', backgroundColor: 'transparent'}
  });
}

// Example wiring (in the real app, place in the existing slider rows):
//   forestSourceRow.add(makeInfoButton('hansen_gfc_v1_12'));   // next to Hansen
//   forestSourceRow.add(makeInfoButton('glad_glclu2020_v2'));  // next to GLAD
//   roadBufferRow.add(makeInfoButton('grip4_aadt_pred'));      // next to road slider
//   protectedAreaRow.add(makeInfoButton('wdpa_wcmc_current')); // next to IUCN cat
//   slopeRow.add(makeInfoButton('alos_aw3d30_v3_2'));          // next to slope thresh

// ── exports for the host script ──
exports.datasetsButton = datasetsButton;
exports.datasetsContent = datasetsContent;
exports.infoPopupContent = infoPopupContent;
exports.makeInfoButton = makeInfoButton;
exports.showInfoPopup = showInfoPopup;

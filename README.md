# Primary Forest Finder

Tools for identifying potential primary forest at national scale. Both tools are in **beta** — actively being tested and updated.

## What's here

- **GEE app** ([`pff_4.js`](pff_4.js)) — global-scale analysis in Google Earth Engine: tree cover → forest → naturally regenerating → primary forest, with human-influence buffers, protected-area and steep-slope rescues, and a connectivity refinement. Exports rasters/vectors + run metadata.
- **QGIS plugin** ([`pff_qgis_tools/`](pff_qgis_tools/)) — the same workflow on the desktop, for mixing national + global data and offline use. See the [plugin README](pff_qgis_tools/README.md).

## Run the GEE app

- **Browser app** — no account needed, fastest way to explore:
  https://fao-fra-493913.projects.earthengine.app/view/primary-forest-finder

  > **The app has moved to the address above.** The old link (`https://ee-andyarnellgee.projects.earthengine.app/view/primary-forest-finder`) will eventually be deprecated — please update bookmarks and any links you have shared.

- **Code Editor** — free Google Earth Engine account; lets you save settings, export to Drive, and edit. Opens the live script (always the latest version):
  https://code.earthengine.google.com/?scriptPath=users%2Fandyarnellgee%2Fapps%3Aprimary_forest_finder_v4

## Install the QGIS plugin

Download the latest zip from [`dist/`](dist/) and install via QGIS **Plugins → Manage and Install Plugins → Install from ZIP**. Open it from **Plugins → Primary Forest Finder → Show PFF Panel** (or the plugin's toolbar button); the panel docks on the right.

Current build: [`pff_qgis_tools_0.16.0-beta.17.zip`](dist/pff_qgis_tools_0.16.0-beta.17.zip). Version history: the `changelog=` field in [`pff_qgis_tools/metadata.txt`](pff_qgis_tools/metadata.txt).

## Datasets

Global datasets the GEE app loads, with sources and citations: [`docs/datasets_global.md`](docs/datasets_global.md). To use the same prepared layers in your own Earth Engine script, see [Using these datasets in your own GEE script](docs/datasets_global.md#using-these-datasets-in-your-own-gee-script).

**Known data issue:** the global OSM roads raster is missing one chunk of Asian roads (heavy in Southeast Asia), so roads are under-buffered there and primary forest may be over-estimated. The roads vector export is complete. Status: [issue #98](https://github.com/andyarnell/primaryforestfinder/issues/98) — if it is closed, this has been fixed.

## Issues & feedback

Report bugs or request features on the [GitHub issues page](https://github.com/andyarnell/primaryforestfinder/issues). Filter by label to focus — e.g. [`GEE App`](https://github.com/andyarnell/primaryforestfinder/issues?q=is%3Aissue+label%3A%22GEE+App%22) or [`QGIS Plugin`](https://github.com/andyarnell/primaryforestfinder/issues?q=is%3Aissue+label%3A%22QGIS+Plugin%22).

## License

CC BY 4.0 (workflow and documentation).

---

_Input preprocessing (OSM, Microsoft Roads, WDB and similar extractors) lives in [`preprocessing/`](preprocessing/) — mostly of interest to maintainers preparing GEE-ready data._

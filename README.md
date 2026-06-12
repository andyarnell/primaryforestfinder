# Primary Forest Finder

Tools and data pipelines for identifying potential primary forest at national scale. Three complementary components:

1. **Google Earth Engine app** - [`pff_4.js`](pff_4.js) - global-scale analysis with built-in data catalogue access and consistent preprocessed exports. Older versions (`old_pff.js`, `pff_3.js`, etc.) are kept for reference in [`gee_scripts/`](gee_scripts/).
2. **QGIS Processing plugin** - [`pff_qgis_tools/`](pff_qgis_tools/) - desktop workflow for mixing national and global data, bespoke analysis, and offline use. See the [plugin README](pff_qgis_tools/README.md). Built zip in [`pff_qgis_tools/dist/`](pff_qgis_tools/dist/).
3. **Data preprocessing notebooks** - OSM, Microsoft Roads, WDB and related extractors in [`preprocessing/`](preprocessing/).

## Try the GEE app

Two ways to access Primary Forest Finder in Google Earth Engine:

1. **Browser app** — no account needed. Fastest way to explore.
   → https://ee-andyarnellgee.projects.earthengine.app/view/primary-forest-finder
2. **Code Editor script** — requires a (free) Google Earth Engine account.
   Same tool plus you can save settings, export to Drive, and edit the script.
   → https://code.earthengine.google.com/66503aadedcb379433227212fa3e29a6

## Install the QGIS plugin

Download the latest zip from [`dist/`](dist/) and install in QGIS via
**Plugins → Manage and Install Plugins → Install from ZIP**.

**Current build:** [`pff_qgis_tools_0.16.0-beta.17.zip`](dist/pff_qgis_tools_0.16.0-beta.17.zip) — FRA input-section alignment + the `02a` tree-cover input rename (`forest_raw` → `tree_cover_binary`). See the `changelog=` in [`pff_qgis_tools/metadata.txt`](pff_qgis_tools/metadata.txt) for the full history.

Older versions are reachable through git history but generally shouldn't be used — most pre-`beta.11` builds carry a latent NoData bug on some GDAL builds. See [`docs/known_issues.md`](docs/known_issues.md).

## Documentation

### Workshop materials → [`docs/workshop/`](docs/workshop/)

- **[GEE_App_Walkthrough.md](docs/workshop/GEE_App_Walkthrough.md)** - step-by-step GEE follow-along (+ .docx)
- **[GEE_App_Workshop_Onepager.md](docs/workshop/GEE_App_Workshop_Onepager.md)** - compact GEE reference handout (+ .docx)
- **[QGIS_Plugin_Walkthrough.md](docs/workshop/QGIS_Plugin_Walkthrough.md)** - step-by-step QGIS plugin follow-along
- **[QGIS_Plugin_Workshop_Onepager.md](docs/workshop/QGIS_Plugin_Workshop_Onepager.md)** - compact QGIS reference handout (+ .docx)
- **[datasets_workshop_reference.md](docs/workshop/datasets_workshop_reference.md)** - full dataset info + citations (+ .docx)

### Other reference docs

- **[docs/pff4_vs_qgis_plugin_comparison.md](docs/pff4_vs_qgis_plugin_comparison.md)** - side-by-side workflow comparison between GEE and QGIS
- **[docs/connectivity_methods.md](docs/connectivity_methods.md)** - review of connectivity / fragmentation filtering methods
- **[docs/known_issues.md](docs/known_issues.md)** - known bugs + workarounds
- **[docs/input_labels_review.md](docs/input_labels_review.md)** - design doc for the FRA category labelling scheme (v0.16 UX restructure)
- **[docs/specs/](docs/specs/)** - plugin technical specs (tool spec, pseudocode, AI reference, automation notes, known doc issues)

## For contributors and AI coding tools

- [CLAUDE.md](CLAUDE.md) - project context entry point for Claude Code sessions
- [.github/copilot-instructions.md](.github/copilot-instructions.md) - canonical technical conventions (CRS, binary, compression, thresholds, naming)
- [planning/tasks_260417_organised.md](planning/tasks_260417_organised.md) - active task backlog and open design questions

## License

Licensed under CC BY 4.0 (workflow and documentation).

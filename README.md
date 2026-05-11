# Primary Forest Finder

Tools and data pipelines for identifying potential primary forest at national scale. Three complementary components:

1. **Google Earth Engine app** - [`pff_4.js`](pff_4.js) - global-scale analysis with built-in data catalogue access and consistent preprocessed exports. Older versions (`old_pff.js`, `pff_3.js`, etc.) are kept for reference in [`gee_scripts/`](gee_scripts/).
2. **QGIS Processing plugin** - [`pff_qgis_tools/`](pff_qgis_tools/) - desktop workflow for mixing national and global data, bespoke analysis, and offline use. See the [plugin README](pff_qgis_tools/README.md). Built zip in [`pff_qgis_tools/dist/`](pff_qgis_tools/dist/).
3. **Data preprocessing notebooks** - OSM, Microsoft Roads, WDB and related extractors in [`preprocessing/`](preprocessing/).

## Documentation

- **[docs/PFF_QGIS_Workshop_Guide_DRAFT.md](docs/PFF_QGIS_Workshop_Guide_DRAFT.md)** - end-user workshop guide (main doc + appendices)
- **[docs/QGIS_Walkthrough_Ann_Rotich_V0.md](docs/QGIS_Walkthrough_Ann_Rotich_V0.md)** - Ann Rotich canonical technical QGIS workflow (fallback for manual users)
- **[docs/pff4_vs_qgis_plugin_comparison.md](docs/pff4_vs_qgis_plugin_comparison.md)** - side-by-side workflow comparison between GEE and QGIS
- **[docs/connectivity_methods.md](docs/connectivity_methods.md)** - review of connectivity / fragmentation filtering methods
- **[docs/specs/](docs/specs/)** - plugin technical specs (tool spec, pseudocode, AI reference, automation notes, known doc issues)

## For contributors and AI coding tools

- [CLAUDE.md](CLAUDE.md) - project context entry point for Claude Code sessions
- [.github/copilot-instructions.md](.github/copilot-instructions.md) - canonical technical conventions (CRS, binary, compression, thresholds, naming)
- [planning/tasks_260417_organised.md](planning/tasks_260417_organised.md) - active task backlog and open design questions

## License

Licensed under CC BY 4.0 (workflow and documentation).

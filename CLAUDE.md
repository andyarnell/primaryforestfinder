# CLAUDE.md — Primary Forest Finder

Entry-point context for Claude Code sessions. Keep short — this is auto-loaded every session. For detailed rules, read [.github/copilot-instructions.md](.github/copilot-instructions.md) (canonical).

---

## What this repo is

Three complementary components for national primary forest mapping:

1. **GEE JavaScript app** — [pff_4.js](pff_4.js) — global-scale analysis via Google Earth Engine. Current production script; older versions (`pff.js`, `pff_3.js`, `old_pff*`) kept for reference only.
2. **QGIS Processing plugin** — [pff_qgis_tools/](pff_qgis_tools/) — desktop workflow for mixing national + global data and bespoke analysis.
3. **Preprocessing notebooks** — [preprocessing/](preprocessing/) — extract OSM/Microsoft Roads/WDB/etc. into GEE-ready formats. See [preprocessing/osm_local/README.md](preprocessing/osm_local/README.md) for the Conda/pyosmium caveat.

The two tools are complementary: GEE provides consistent preprocessed exports (handy as global defaults); QGIS provides flexibility and offline use. GEE exports can drop straight into the plugin as inputs.

---

## Current versions

- **pff_4.js** — see top-of-file `PFF_SCRIPT_VERSION` (add if missing per task 10 in backlog)
- **QGIS plugin** — v0.8.0 (see `pff_qgis_tools/metadata.txt` and `full_workflow.py` `PFF_VERSION`)

---

## Always check before editing

1. **`planning/` folder** (local only — gitignored) — current task backlog (`tasks_260417_organised.md`) and open design questions. **Read the "Session prep notes" block at the top** for execution order, versioning rules, GEE edit cadence, parked tasks, and known gotchas. Then check if the work is already scoped before starting anything.
2. **[.github/copilot-instructions.md](.github/copilot-instructions.md)** — canonical technical conventions (CRS, binary, LZW, thresholds, naming). Read this for anything non-trivial.
3. **Auto-memory** (`MEMORY.md` in your local Claude Code projects dir) — cross-session lessons (e.g. never use `-tap` / `gdal:cliprasterbymasklayer`).

---

## Key shared conventions

- **CRS:** always projected, metres. Never geographic (EPSG:4326) for distance/area. Plugin supports auto-UTM detection.
- **Binary rasters:** 1 = presence, 0 = absence. Use GeoTIFF + `COMPRESS=LZW|TILED=YES`.
- **Data types:** `Byte` for binary masks, `Float32` only for continuous (slope, distance surfaces).
- **Reference grid:** forest raster defines extent / resolution / pixel origin. All other rasters align to it.
- **Never use `-tap`** in gdalwarp — shifts pixel grid origin. Use `gdal:warpreproject` with `CUTLINE` + explicit `TARGET_RESOLUTION`.

---

## Documentation layout

| File | Purpose |
|------|---------|
| [docs/PFF_QGIS_Workshop_Guide_DRAFT.md](docs/PFF_QGIS_Workshop_Guide_DRAFT.md) | End-user workshop guide (short main doc + appendices) |
| [docs/QGIS_Workflow_Ann_Rotich_V0.md](docs/QGIS_Workflow_Ann_Rotich_V0.md) | Ann Rotich's canonical technical workflow — fallback when plugin has bugs or users prefer manual steps |
| [pff_qgis_tools/README.md](pff_qgis_tools/README.md) | Plugin user docs (install, tools, outputs) |
| [docs/specs/PFF_QGIS_PROCESSING_TOOL_SPEC.md](docs/specs/PFF_QGIS_PROCESSING_TOOL_SPEC.md) | Plugin input/output definitions |
| [docs/specs/PFF_QGIS_WORKFLOW_AI_REFERENCE.md](docs/specs/PFF_QGIS_WORKFLOW_AI_REFERENCE.md) | Conceptual workflow description |
| [docs/specs/PFF_QGIS_PYTHON_PSEUDOCODE.md](docs/specs/PFF_QGIS_PYTHON_PSEUDOCODE.md) | Pseudocode for PyQGIS automation |
| [docs/specs/PFF_QGIS_AUTOMATION_RECOMMENDATIONS.md](docs/specs/PFF_QGIS_AUTOMATION_RECOMMENDATIONS.md) | Architecture recommendations |
| [docs/specs/PFF_QGIS_WORKFLOW_DOC_UPDATES.md](docs/specs/PFF_QGIS_WORKFLOW_DOC_UPDATES.md) | Known ambiguities in earlier specs |
| [docs/pff4_vs_qgis_plugin_comparison.md](docs/pff4_vs_qgis_plugin_comparison.md) | GEE vs QGIS side-by-side |
| [docs/connectivity_methods.md](docs/connectivity_methods.md) | Connectivity / fragmentation methods review |
| [preprocessing/osm_local/README.md](preprocessing/osm_local/README.md) | OSM extraction notes (incl. Conda/pyosmium caveat) |
| [planning/](planning/) | Active task backlog |
| [.github/copilot-instructions.md](.github/copilot-instructions.md) | Canonical detailed technical rules (shared with GitHub Copilot) |
| [.github/agents/](.github/agents/) | Task-specific agent briefs (e.g. add-dataset) |
| [docs/archive/](docs/archive/) | Historical/superseded docs |

---

## Quick lookup — where is X?

- **Plugin entry point:** [pff_qgis_tools/pff_plugin.py](pff_qgis_tools/pff_plugin.py)
- **Plugin algorithms:** [pff_qgis_tools/algorithms/](pff_qgis_tools/algorithms/) (one file per tool)
- **Plugin shared utilities:** [pff_qgis_tools/utils.py](pff_qgis_tools/utils.py)
- **GEE anthropogenic datasets module:** [modules/timeseriesAnthro.js](modules/timeseriesAnthro.js)
- **GEE connectivity methods:** [modules/pff_connectivity.js](modules/pff_connectivity.js), [pff_connectivity_simple.js](pff_connectivity_simple.js)

---

## Notes for future sessions

- When a concept has two names across GEE vs QGIS (e.g. GEE "Refine Output" = plugin file `connectivity_filter.py`), the pff_4.js terminology is canonical — align QGIS to match.
- Plugin minimum QGIS version: 3.38 per `metadata.txt`, but a version check in `pff_plugin.py` warns under 3.28 (set there for wider workshop compatibility — see discussion in session memory).
- When adding user-facing text to the plugin, avoid mentioning "matches GEE tool" — irrelevant to the QGIS user. Keep those notes in the workshop guide Appendix D.

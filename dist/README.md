# Plugin distribution

Only the **current** plugin zip lives here. Older versions are reachable
through git history if you really need them, but generally **don't**:
several pre-`beta.11` versions carry a latent NoData=0 bug that can
silently zero out the primary-forest output on some GDAL builds (see
[../docs/known_issues.md](../docs/known_issues.md)).

## Current

- [`pff_qgis_tools_0.16.0-beta.13.zip`](pff_qgis_tools_0.16.0-beta.13.zip)
  — all bug fixes through 2026-05-12 workshop, plus scroll-wheel trap fix
  and multi-year baseline-forest constraint (see
  [../docs/known_issues.md](../docs/known_issues.md)).

## Install

QGIS → **Plugins → Manage and Install Plugins → Install from ZIP** → pick
the zip above.

## Going forward

New builds will be published as **GitHub Releases**, not committed here.
This folder will hold only the latest current zip (or be empty once the
Releases workflow is set up).

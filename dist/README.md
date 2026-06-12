# Plugin distribution

Only the **current** plugin zip lives here. Older versions are reachable
through git history if you really need them, but generally **don't**:
several pre-`beta.11` versions carry a latent NoData=0 bug that can
silently zero out the primary-forest output on some GDAL builds (see
[../docs/known_issues.md](../docs/known_issues.md)).

## Current

- [`pff_qgis_tools_0.16.0-beta.17.zip`](pff_qgis_tools_0.16.0-beta.17.zip)
  — version per `pff_qgis_tools/metadata.txt`; see
  [../CHANGELOG_GEE.md](../CHANGELOG_GEE.md) and the plugin `changelog=` in
  metadata.txt for what's in it.

## Install

QGIS → **Plugins → Manage and Install Plugins → Install from ZIP** → pick
the zip above.

## Build (regenerate the zip)

Run the build script — it reads the version from `metadata.txt`, names the
zip accordingly, drops any stale `pff_qgis_tools_*.zip`, and keeps only the
current one:

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_plugin_zip.ps1
```

**Do NOT build with `Compress-Archive`.** Windows PowerShell 5.1 writes zip
entries with backslash separators (`pff_qgis_tools\metadata.txt`), which the
QGIS installer can reject or unpack wrongly. The script builds via .NET
`ZipArchive` with **forward-slash** entry names, excludes `__pycache__`/`*.pyc`,
and puts `pff_qgis_tools/` at the zip root. Run a quick Bhutan self-test of
the plugin **before** shipping a new zip.

## Going forward

New builds will be published as **GitHub Releases**, not committed here.
This folder will hold only the latest current zip (or be empty once the
Releases workflow is set up).

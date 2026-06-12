<#
.SYNOPSIS
  Build the distributable QGIS plugin zip for Primary Forest Finder.

.DESCRIPTION
  Packages the `pff_qgis_tools/` folder into `dist/pff_qgis_tools_<version>.zip`,
  where <version> is read from `pff_qgis_tools/metadata.txt`.

  WHY THIS SCRIPT EXISTS (do not "just use Compress-Archive"):
  Windows PowerShell 5.1's `Compress-Archive` writes zip entries with
  BACKSLASH separators (`pff_qgis_tools\metadata.txt`). The QGIS plugin
  installer expects forward slashes (`pff_qgis_tools/metadata.txt`); a
  backslash zip can fail to install or unpack into a wrongly-named folder.
  This script builds entries explicitly via .NET ZipArchive with
  forward-slash names, so the result matches a Linux/Info-ZIP build.

  It also:
   - excludes `__pycache__/` and `*.pyc`,
   - puts `pff_qgis_tools/` at the zip root (the plugin folder name),
   - removes any older `pff_qgis_tools_*.zip` from dist/ (we keep only the
     current build here; see dist/README.md).

.NOTES
  Run a quick Bhutan self-test of the plugin BEFORE shipping a new zip
  (catch regressions before users do). Then have the user reinstall via
  Plugins -> Install from ZIP (or Plugin Reloader -> Reload for a dev copy).

.EXAMPLE
  pwsh tools/build_plugin_zip.ps1
  # or from Windows PowerShell:
  powershell -ExecutionPolicy Bypass -File tools\build_plugin_zip.ps1
#>

$ErrorActionPreference = 'Stop'

# Resolve repo root = parent of this script's folder (tools/).
$repo = Split-Path -Parent $PSScriptRoot
$plugin = Join-Path $repo 'pff_qgis_tools'
$distDir = Join-Path $repo 'dist'

if (-not (Test-Path (Join-Path $plugin 'metadata.txt'))) {
  throw "metadata.txt not found under $plugin"
}

# Read version= from metadata.txt.
$version = (Select-String -Path (Join-Path $plugin 'metadata.txt') -Pattern '^version=(.+)$').Matches[0].Groups[1].Value.Trim()
if (-not $version) { throw 'Could not read version= from metadata.txt' }
Write-Host "Plugin version: $version"

if (-not (Test-Path $distDir)) { New-Item -ItemType Directory -Force -Path $distDir | Out-Null }

# Stage a clean copy (no __pycache__ / *.pyc).
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("pff_pkg_" + [System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Force -Path $stage | Out-Null
try {
  Copy-Item -Recurse $plugin (Join-Path $stage 'pff_qgis_tools')
  Get-ChildItem -Recurse -Force (Join-Path $stage 'pff_qgis_tools') -Directory |
    Where-Object { $_.Name -eq '__pycache__' } | Remove-Item -Recurse -Force
  Get-ChildItem -Recurse -Force (Join-Path $stage 'pff_qgis_tools') -Include *.pyc | Remove-Item -Force

  $out = Join-Path $distDir "pff_qgis_tools_$version.zip"
  if (Test-Path $out) { Remove-Item -Force $out }

  Add-Type -AssemblyName System.IO.Compression
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zip = [System.IO.Compression.ZipFile]::Open($out, [System.IO.Compression.ZipArchiveMode]::Create)
  try {
    $base = (Resolve-Path $stage).Path
    Get-ChildItem -Recurse -File (Join-Path $stage 'pff_qgis_tools') | ForEach-Object {
      # Entry name relative to the stage root, forward slashes.
      $rel = $_.FullName.Substring($base.Length + 1) -replace '\\', '/'
      [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $rel) | Out-Null
    }
  } finally {
    $zip.Dispose()
  }

  # Keep only the current zip in dist/.
  Get-ChildItem $distDir -Filter 'pff_qgis_tools_*.zip' |
    Where-Object { $_.Name -ne "pff_qgis_tools_$version.zip" } |
    ForEach-Object { Write-Host "Removing stale: $($_.Name)"; Remove-Item -Force $_.FullName }

  $count = ([System.IO.Compression.ZipFile]::OpenRead($out).Entries).Count
  Write-Host "Built: dist/pff_qgis_tools_$version.zip ($count entries, forward-slash paths)"
} finally {
  Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
}

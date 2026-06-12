<#
.SYNOPSIS
  Sync the repo's pff_qgis_tools/ into the QGIS installed-plugins folder.

.DESCRIPTION
  The repo and the QGIS *installed* plugin are SEPARATE copies. Editing files
  in the repo does NOT change what QGIS runs — you must copy them across and
  reload. This script mirrors `pff_qgis_tools/` into the QGIS profile's plugin
  folder, clears `__pycache__` (so stale .pyc don't shadow your edits), and
  prints the resulting version.

  After running it: in QGIS, Plugins -> Plugin Reloader -> Reload
  "Primary Forest Finder" (no QGIS restart needed). The dock header reads its
  version from FullWorkflowAlgorithm.PFF_VERSION, so it should then match
  metadata.txt.

  Destination defaults to the *default* profile under %APPDATA%. Override with
  -Profile (another profile name) or -Dest (an explicit plugin folder path).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\sync_plugin_to_qgis.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\sync_plugin_to_qgis.ps1 -Profile myprofile
#>

param(
  [string]$Profile = 'default',
  [string]$Dest
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$src = Join-Path $repo 'pff_qgis_tools'
if (-not (Test-Path (Join-Path $src 'metadata.txt'))) { throw "Source plugin not found: $src" }

if (-not $Dest) {
  $Dest = Join-Path $env:APPDATA "QGIS\QGIS3\profiles\$Profile\python\plugins\pff_qgis_tools"
}

Write-Host "Source: $src"
Write-Host "Dest:   $Dest"
if (-not (Test-Path (Split-Path -Parent $Dest))) {
  throw "QGIS plugins folder not found: $(Split-Path -Parent $Dest). Is QGIS installed / is the profile name right? Use -Profile or -Dest."
}

# /MIR makes Dest identical to Source (copies new, removes stale). Exclude
# __pycache__ from the mirror, then delete any in Dest to force a recompile.
robocopy $src $Dest /MIR /XD __pycache__ /NFL /NDL /NJH /NJS /NC /NS | Out-Null
$rc = $LASTEXITCODE
if ($rc -ge 8) { throw "robocopy failed (exit $rc)" }   # 0-7 are success codes

Get-ChildItem -Recurse -Force $Dest -Directory |
  Where-Object { $_.Name -eq '__pycache__' } | Remove-Item -Recurse -Force

$ver = (Select-String -Path (Join-Path $Dest 'metadata.txt') -Pattern '^version=(.+)$').Matches[0].Groups[1].Value.Trim()
Write-Host "Synced. Installed version now: $ver"
Write-Host "Next: QGIS -> Plugins -> Plugin Reloader -> Reload 'Primary Forest Finder'."

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
  [string]$Dest,
  [switch]$NoZip
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$src = Join-Path $repo 'pff_qgis_tools'
if (-not (Test-Path (Join-Path $src 'metadata.txt'))) { throw "Source plugin not found: $src" }

# Pull latest from GitHub first: the local repo can be behind if a change was
# merged remotely (e.g. another agent), and syncing a stale local would push old
# code to QGIS. Fast-forward only + clean-tree guard, so this never clobbers
# local work. Skip with -NoPull (or when not a git checkout).
if (-not $NoPull -and (Test-Path (Join-Path $repo '.git'))) {
  Push-Location $repo
  try {
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    git fetch --quiet 2>$null
    $counts = git rev-list --left-right --count "HEAD...@{u}" 2>$null
    if ($LASTEXITCODE -eq 0 -and $counts) {
      $parts  = ($counts -replace '\s+', ' ').Trim() -split ' '
      $ahead  = [int]$parts[0]
      $behind = [int]$parts[1]
      if ($behind -gt 0) {
        $dirty = git status --porcelain --untracked-files=no
        if ($ahead -eq 0 -and -not $dirty) {
          git pull --ff-only --quiet
          Write-Host "Pulled $behind commit(s) from origin/$branch (fast-forward)."
        } else {
          $why = if ($ahead -gt 0) { "$ahead ahead" } else { 'uncommitted changes' }
          Write-Host "NOTE: local $branch is $behind behind origin but has $why -- NOT pulling. Resolve manually (git pull), then re-run."
        }
      }
    }
  } finally { Pop-Location }
}

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

# Timestamp companion: copy the version-matched dist zip next to the extracted
# folder as `pff_qgis_tools.zip`. QGIS loads the extracted folder, not this zip,
# but its file timestamp is an at-a-glance "is the install fresh?" check. Skip
# with -NoZip.
if (-not $NoZip) {
  $pluginsDir = Split-Path -Parent $Dest
  $distZip = Join-Path $repo "dist\pff_qgis_tools_$ver.zip"
  $companion = Join-Path $pluginsDir 'pff_qgis_tools.zip'
  if (Test-Path $distZip) {
    Copy-Item -Force $distZip $companion
    Write-Host "Zip companion refreshed: $companion"
  } else {
    Write-Host "NOTE: dist\pff_qgis_tools_$ver.zip not found -- zip companion NOT updated (build it with tools\build_plugin_zip.ps1)."
  }
}

Write-Host "Next: QGIS -> Plugins -> Plugin Reloader -> Reload 'Primary Forest Finder'."

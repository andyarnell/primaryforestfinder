"""
Primary Forest Finder — QGIS Processing Tools
================================================

A set of QGIS Processing algorithms (compatible with QGIS ≥ 3.38) that
replicate the Primary Forest Finder (PFF) Google Earth Engine app
workflow using local raster/vector data and GDAL / native QGIS
algorithms.

Tools (Processing Toolbox → Primary Forest Finder):
  1. Validate Inputs
  2. Prepare Datasets
  3a. Distance Surfaces (cache)
  3b. Build Anthropogenic Mask
  4. Run Primary Forest Finder
  5. Refine Output
  •  Run Full Workflow  (chains all steps)

Install
-------
Copy the ``pff_qgis_tools`` folder into your QGIS Processing scripts
directory, or add the parent folder to your QGIS Python path and load
the provider via the Plugin Manager.
"""


def classFactory(iface):
    """QGIS plugin entry‑point."""
    from .pff_plugin import PffPlugin
    return PffPlugin(iface)

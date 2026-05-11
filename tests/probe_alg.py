"""Probe what fails on createInstance / initAlgorithm of the CEO export."""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from qgis.core import QgsApplication

prefix = r"C:\Program Files\QGIS 3.38.0\apps\qgis"
QgsApplication.setPrefixPath(prefix, True)
app = QgsApplication([], False)
app.initQgis()
sys.path.append(os.path.join(prefix, "python", "plugins"))

from processing.core.Processing import Processing
Processing.initialize()

try:
    from pff_qgis_tools.algorithms.ceo_validation_export import (
        CeoValidationExportAlgorithm,
    )
    inst = CeoValidationExportAlgorithm()
    print("Instantiation OK")
    inst.initAlgorithm(None)
    print("initAlgorithm OK")
    inst2 = inst.createInstance()
    print("createInstance OK:", inst2)
    inst2.initAlgorithm(None)
    print("nested initAlgorithm OK")
except Exception as e:
    print("FAILED:", type(e).__name__, e)
    import traceback
    traceback.print_exc()

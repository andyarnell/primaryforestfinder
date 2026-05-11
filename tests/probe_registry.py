"""Probe which algorithms are registered after PffProvider load."""
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

from pff_qgis_tools.pff_provider import PffProvider
prov = PffProvider()
QgsApplication.processingRegistry().addProvider(prov)

reg = QgsApplication.processingRegistry()
print("Provider count:", len(reg.providers()))
for p in reg.providers():
    if p.id() == "pff":
        print("pff provider:", p, "with algorithms:")
        for a in p.algorithms():
            print(" ", a.id(), "=>", a.displayName())

alg = reg.createAlgorithmById("pff:ceo_validation_export")
print("createAlgorithmById:", alg)
if alg is None:
    print("NULL alg returned")
else:
    print("alg.parameterDefinitions:", len(alg.parameterDefinitions()))

"""Reproduce processing.run() failure on the new algorithm in isolation."""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from qgis.core import QgsApplication, QgsProcessingException

prefix = r"C:\Program Files\QGIS 3.38.0\apps\qgis"
QgsApplication.setPrefixPath(prefix, True)
app = QgsApplication([], False)
app.initQgis()
sys.path.append(os.path.join(prefix, "python", "plugins"))

import processing
from processing.core.Processing import Processing
Processing.initialize()

from pff_qgis_tools.pff_provider import PffProvider
QgsApplication.processingRegistry().addProvider(PffProvider())

# Confirm registry knows about us
reg = QgsApplication.processingRegistry()
alg = reg.createAlgorithmById("pff:ceo_validation_export")
print("registry createAlgorithmById:", alg)

# Now try processing.run with a Bhutan input (rule 1 condensed).
from pff_qgis_tools.algorithms.ceo_validation_export import (
    CeoValidationExportAlgorithm as A,
)
BHUTAN = (
    r"C:\Users\Arnell\Downloads\qgis_pff_testing\BTN\full_workflow_260504"
    r"\BTN_2020_qgis_06c_naturally_regenerating_forest_with_primary"
    r"_nested_vector.shp"
)
with tempfile.TemporaryDirectory() as out_dir:
    params = {
        A.INPUT: BHUTAN,
        A.CLASS_FIELD: "level",
        A.PRIMARY_CLASS_VALUE: 2,
        A.OTHER_CLASS_VALUE: 1,
        A.SAMPLING_DOMAIN: A.DOMAIN_ALL,
        A.STRATIFIED: False,
        A.N_SAMPLES: 5,
        A.N_PRIMARY: 0,
        A.N_OTHER: 0,
        A.MIN_DISTANCE: 0,
        A.RANDOM_SEED: "42",
        A.EXPORT_METHOD: A.METHOD_SIMPLE_POINTS,
        A.PLOT_RADIUS_M: 2000,
        A.RING_WIDTH_M: 1,
        A.SAMPLE_GEOM_POINT: True,
        A.SAMPLE_GEOM_SQUARE: False,
        A.SQUARE_SIZE_M: 100,
        A.OUTPUT_FOLDER: out_dir,
        A.OUTPUT_GEOPACKAGE: True,
        A.OUTPUT_ZIPPED_SHAPEFILE: False,
        A.ADD_PROVENANCE_FIELDS: True,
        A.ALLOW_EMPTY_STRATUM: False,
    }
    try:
        result = processing.run("pff:ceo_validation_export", params)
        print("RUN OK:", result)
    except Exception as e:
        print("RUN FAILED:", type(e).__name__, e)
        import traceback
        traceback.print_exc()

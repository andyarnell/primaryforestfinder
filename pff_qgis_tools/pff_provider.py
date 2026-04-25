"""PFF Processing provider — registers all algorithms under one toolbox group."""

from qgis.core import QgsProcessingProvider

from .algorithms.validate_inputs import ValidateInputsAlgorithm
from .algorithms.prepare_inputs import PrepareInputsAlgorithm
from .algorithms.distance_surfaces import DistanceSurfacesAlgorithm
from .algorithms.anthropogenic_mask import AnthropogenicMaskAlgorithm
from .algorithms.primary_forest import PrimaryForestAlgorithm
from .algorithms.connectivity_filter import ConnectivityFilterAlgorithm
from .algorithms.full_workflow import FullWorkflowAlgorithm
from .algorithms.zonal_statistics import ZonalStatisticsAlgorithm
# from .algorithms.generate_ceo_plots import GenerateCeoPlotsAlgorithm  # draft, not shipped yet


class PffProvider(QgsProcessingProvider):
    """Exposes PFF tools inside the QGIS Processing toolbox."""

    def id(self):
        return "pff"

    def name(self):
        return "Primary Forest Finder"

    def longName(self):
        return "Primary Forest Finder (PFF) Tools"

    def icon(self):
        return QgsProcessingProvider.icon(self)

    def loadAlgorithms(self):
        self.addAlgorithm(ValidateInputsAlgorithm())
        self.addAlgorithm(PrepareInputsAlgorithm())
        self.addAlgorithm(DistanceSurfacesAlgorithm())
        self.addAlgorithm(AnthropogenicMaskAlgorithm())
        self.addAlgorithm(PrimaryForestAlgorithm())
        self.addAlgorithm(ConnectivityFilterAlgorithm())
        self.addAlgorithm(FullWorkflowAlgorithm())
        self.addAlgorithm(ZonalStatisticsAlgorithm())
        # self.addAlgorithm(GenerateCeoPlotsAlgorithm())  # draft, not shipped yet

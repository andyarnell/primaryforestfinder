"""Thin QGIS plugin wrapper that registers the PFF Processing provider."""

from qgis.core import QgsApplication, Qgis
from .pff_provider import PffProvider

MIN_QGIS_VERSION = 32800  # 3.28.0


class PffPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initProcessing(self):
        self.provider = PffProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        version = Qgis.QGIS_VERSION_INT
        if version < MIN_QGIS_VERSION:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.warning(
                None, "PFF Plugin",
                f"The Primary Forest Finder plugin requires QGIS 3.28 or "
                f"later.\n\nYour version: {Qgis.QGIS_VERSION}\n\n"
                f"The plugin will load but some tools may not work correctly."
            )
        self.initProcessing()

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)

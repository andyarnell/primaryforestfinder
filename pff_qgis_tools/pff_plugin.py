"""QGIS plugin entry point.

Registers the PFF Processing provider and wires the custom dock widget
(P1.30, batch 20a) into a toolbar action + Plugins menu item. Dock is
lazy-constructed on first show so the plugin loads fast even when the
panel isn't used.
"""

from qgis.core import QgsApplication, Qgis
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .pff_provider import PffProvider

MIN_QGIS_VERSION = 32800  # 3.28.0


class PffPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self._dock = None
        self._dock_action = None

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

        # Toolbar action + Plugins-menu item that toggle the dock.
        self._dock_action = QAction(
            QIcon(), "Show PFF Panel", self.iface.mainWindow())
        self._dock_action.setCheckable(True)
        self._dock_action.setStatusTip(
            "Open the Primary Forest Finder workflow panel")
        self._dock_action.triggered.connect(self._toggle_dock)
        self.iface.addPluginToMenu("&Primary Forest Finder", self._dock_action)
        self.iface.addToolBarIcon(self._dock_action)

    def _toggle_dock(self, checked: bool):
        # Lazy-construct on first show.
        if self._dock is None:
            from .ui.pff_dock import PffDockWidget
            self._dock = PffDockWidget(self.iface, self.iface.mainWindow())
            # Right side by default -- the QGIS Layers + Browser panels
            # already live on the left, so docking PFF on the right keeps
            # those visible while users drive the workflow.
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self._dock)
            # Keep the toolbar action's checkbox in sync when the dock
            # is closed via its own X button.
            self._dock.visibilityChanged.connect(
                self._dock_action.setChecked)
        self._dock.setVisible(checked)
        if checked:
            self._dock.raise_()

    def unload(self):
        if self._dock_action is not None:
            self.iface.removePluginMenu(
                "&Primary Forest Finder", self._dock_action)
            self.iface.removeToolBarIcon(self._dock_action)
            self._dock_action = None
        if self._dock is not None:
            self.iface.removeDockWidget(self._dock)
            self._dock.deleteLater()
            self._dock = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

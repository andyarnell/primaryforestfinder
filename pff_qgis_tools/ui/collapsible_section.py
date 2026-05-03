"""Reusable collapsible section widget for the PFF dock.

A small QWidget that mimics the GEE app's left-panel collapsibles:
clickable header (▶/▼ + title) + a content frame whose visibility
toggles. Used for every section + nested sub-section in the dock.
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QFrame, QToolButton, QVBoxLayout, QWidget
)


class CollapsibleSection(QWidget):
    """Header button + collapsible content frame.

    Use ``set_content_layout(layout)`` to install the body. The header
    title shows ``▶`` when collapsed and ``▼`` when expanded.
    """

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, *, expanded: bool = False,
                 indent_px: int = 0, header_bold: bool = True,
                 parent: QWidget = None):
        super().__init__(parent)
        self._title = title

        outer = QVBoxLayout(self)
        outer.setContentsMargins(indent_px, 0, 0, 0)
        outer.setSpacing(2)

        self._header = QToolButton(self)
        self._header.setStyleSheet(
            "QToolButton { border: none; text-align: left; padding: 4px 2px; "
            + ("font-weight: bold; " if header_bold else "")
            + "}"
        )
        self._header.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._header.setCheckable(True)
        self._header.setChecked(expanded)
        self._header.toggled.connect(self._on_toggled)
        outer.addWidget(self._header)

        self._content = QFrame(self)
        self._content.setFrameShape(QFrame.NoFrame)
        self._content_outer_layout = QVBoxLayout(self._content)
        self._content_outer_layout.setContentsMargins(12, 0, 0, 4)
        self._content_outer_layout.setSpacing(4)
        outer.addWidget(self._content)

        self._content.setVisible(expanded)
        self._refresh_header_text()

    def set_content_layout(self, layout):
        """Install ``layout`` as the section body."""
        # Clear any existing inner layout the caller previously set.
        while self._content_outer_layout.count():
            item = self._content_outer_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        # Wrap the caller's layout in a host widget so we can drop it in.
        host = QWidget(self._content)
        host.setLayout(layout)
        self._content_outer_layout.addWidget(host)

    def is_expanded(self) -> bool:
        return self._header.isChecked()

    def set_expanded(self, expanded: bool):
        self._header.setChecked(expanded)

    def _on_toggled(self, checked: bool):
        self._content.setVisible(checked)
        self._refresh_header_text()
        self.toggled.emit(checked)

    def _refresh_header_text(self):
        arrow = "▼" if self._header.isChecked() else "▶"
        self._header.setText(f"{arrow}  {self._title}")

from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from desktop.state import WorkspaceSnapshot
from desktop.widgets import clear_layout


class ScrollPage(QScrollArea):
    title = ""
    subtitle = ""

    def __init__(self, snapshot: WorkspaceSnapshot) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setObjectName("Page")

        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(26, 22, 26, 26)
        self.layout.setSpacing(13)
        self.setWidget(self.container)

        self.update_snapshot(snapshot)

    def update_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        clear_layout(self.layout)
        self.build(snapshot)
        self.layout.addStretch(1)

    def build(self, snapshot: WorkspaceSnapshot) -> None:
        raise NotImplementedError

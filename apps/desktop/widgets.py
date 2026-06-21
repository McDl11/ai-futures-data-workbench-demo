from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop.actions import ActionResult, open_parent, open_path
from desktop.state import FileItem, FileStatus, format_size


def clear_layout(layout: QVBoxLayout | QHBoxLayout | QGridLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            clear_layout(child_layout)


def make_title(text: str, subtitle: str = "") -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 12)
    layout.setSpacing(4)

    title = QLabel(text)
    title.setObjectName("PageTitle")
    layout.addWidget(title)

    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("MutedText")
        sub.setWordWrap(True)
        layout.addWidget(sub)

    return container


class StatusCard(QFrame):
    def __init__(self, title: str, value: str, detail: str = "", state: str = "neutral") -> None:
        super().__init__()
        self.setObjectName("StatusCard")
        self.setProperty("state", state)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(104)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        layout.addWidget(title_label)

        value_label = QLabel(value)
        value_label.setObjectName("CardValue")
        value_label.setWordWrap(True)
        layout.addWidget(value_label)

        if detail:
            detail_label = QLabel(detail)
            detail_label.setObjectName("MutedText")
            detail_label.setWordWrap(True)
            layout.addWidget(detail_label)


class DashboardCard(QFrame):
    def __init__(self, title: str, value: str, detail: str = "", state: str = "neutral") -> None:
        super().__init__()
        self.setObjectName("DashboardCard")
        self.setProperty("state", state)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(118)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(7)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        indicator = QLabel("")
        indicator.setObjectName("StatusDot")
        indicator.setProperty("state", state)
        indicator.setFixedSize(9, 9)
        top.addWidget(indicator)

        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        top.addWidget(title_label, 1)
        layout.addLayout(top)

        value_label = QLabel(value)
        value_label.setObjectName("DashboardValue")
        value_label.setWordWrap(True)
        layout.addWidget(value_label)

        if detail:
            detail_label = QLabel(detail)
            detail_label.setObjectName("MutedText")
            detail_label.setWordWrap(True)
            layout.addWidget(detail_label)


class Section(QFrame):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.setObjectName("Section")
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(9)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 16, 18, 16)
        root_layout.setSpacing(11)

        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        root_layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("MutedText")
            subtitle_label.setWordWrap(True)
            root_layout.addWidget(subtitle_label)

        root_layout.addLayout(self.content_layout)

    def add(self, widget: QWidget) -> None:
        self.content_layout.addWidget(widget)


def status_row(label: str, status: FileStatus) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    name = QLabel(label)
    name.setObjectName("RowLabel")
    name.setMinimumWidth(120)
    layout.addWidget(name)

    state = QLabel(status.label)
    state.setObjectName("Pill")
    state.setProperty("state", "ok" if status.exists else "warning")
    layout.addWidget(state)

    detail = QLabel(status.detail or str(status.path))
    detail.setObjectName("MutedText")
    detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
    layout.addWidget(detail, 1)

    return row


class FileListWidget(QListWidget):
    def selected_path(self) -> Path | None:
        selected = self.currentItem()
        if selected is None:
            return None
        value = selected.data(Qt.UserRole)
        if value is None:
            return None
        return Path(value)


def file_list(items: list[FileItem], empty_text: str = "暂无文件") -> FileListWidget:
    listing = FileListWidget()
    listing.setObjectName("FileList")
    listing.setAlternatingRowColors(True)
    listing.setMinimumHeight(150)

    if not items:
        item = QListWidgetItem(empty_text)
        item.setFlags(Qt.NoItemFlags)
        listing.addItem(item)
        return listing

    for file_item in items:
        modified = format_datetime(file_item.modified_at)
        text = f"{file_item.path.name}  ·  {format_size(file_item.size_bytes)}  ·  {modified}"
        item = QListWidgetItem(text)
        item.setToolTip(str(file_item.path))
        item.setData(Qt.UserRole, str(file_item.path))
        listing.addItem(item)

    return listing


def action_buttons(labels: list[str]) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    for label in labels:
        button = QPushButton(f"{label} · 待接入")
        button.setObjectName("GhostButton")
        button.setEnabled(False)
        button.setToolTip("功能入口已预留，后续接入执行逻辑")
        layout.addWidget(button)

    layout.addStretch(1)
    return row


class FileActions(QWidget):
    def __init__(self, listing: FileListWidget, status_label: QLabel | None = None) -> None:
        super().__init__()
        self.listing = listing
        self.status_label = status_label

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        open_button = QPushButton("打开选中文件")
        open_button.clicked.connect(self.open_selected)
        layout.addWidget(open_button)

        folder_button = QPushButton("打开所在目录")
        folder_button.clicked.connect(self.open_selected_parent)
        layout.addWidget(folder_button)

        layout.addStretch(1)

    def open_selected(self) -> None:
        path = self.listing.selected_path()
        result = open_path(path) if path is not None else ActionResult(False, "请先选中一个文件")
        self._show_result(result)

    def open_selected_parent(self) -> None:
        path = self.listing.selected_path()
        result = open_parent(path) if path is not None else ActionResult(False, "请先选中一个文件")
        self._show_result(result)

    def _show_result(self, result: ActionResult) -> None:
        if self.status_label is not None:
            self.status_label.setText(result.message)


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "时间未知"
    return value.strftime("%Y-%m-%d %H:%M")


def short_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from desktop.actions import ActionResult, open_parent, open_path
from desktop.logs import LogErrorItem, LogFileItem, discover_log_files, read_log_file, scan_error_logs
from desktop.pages.base import ScrollPage
from desktop.state import WorkspaceSnapshot, format_size
from desktop.widgets import Section, make_title


class LogCenterPage(ScrollPage):
    def __init__(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        self.logs: list[LogFileItem] = []
        self.errors: list[LogErrorItem] = []
        self.log_table: QTableWidget | None = None
        self.error_table: QTableWidget | None = None
        self.keyword_input: QLineEdit | None = None
        self.preview_box: QTextEdit | None = None
        self.status_label: QLabel | None = None
        super().__init__(snapshot)

    def update_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        super().update_snapshot(snapshot)

    def build(self, snapshot: WorkspaceSnapshot) -> None:
        self.logs = discover_log_files(snapshot.project_root)
        self.errors = scan_error_logs(snapshot.project_root)

        self.layout.addWidget(
            make_title(
                "日志中心",
                "集中查看任务、报告、邮件和数据下载日志；可筛选关键词并快速定位错误。",
            )
        )

        splitter = QSplitter(Qt.Vertical)
        splitter.setObjectName("LogCenterSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(13)

        logs = Section("最近日志")
        logs.add(self._build_tools())
        self.log_table = self._build_log_table(self.logs)
        logs.add(self.log_table)
        logs.add(self._build_log_actions())
        top_layout.addWidget(logs)

        errors = Section("错误日志", "扫描 ERROR / Traceback / [FAIL] / 失败 等关键行。")
        self.error_table = self._build_error_table(self.errors)
        errors.add(self.error_table)
        top_layout.addWidget(errors)
        top_layout.addStretch(1)

        preview = Section("日志内容")
        self.preview_box = QTextEdit()
        self.preview_box.setReadOnly(True)
        self.preview_box.setMinimumHeight(180)
        self.preview_box.setPlaceholderText("选中日志后点击“查看日志内容”。")
        preview.add(self.preview_box)
        self.status_label = QLabel("选中一个日志文件后可以查看内容、打开文件或打开目录。")
        self.status_label.setObjectName("MutedText")
        preview.add(self.status_label)

        splitter.addWidget(top)
        splitter.addWidget(preview)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([560, 300])
        self.layout.addWidget(splitter)

    def _build_tools(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("输入关键词过滤日志内容")
        layout.addWidget(self.keyword_input, 1)
        return row

    def _build_log_table(self, logs: list[LogFileItem]) -> QTableWidget:
        table = QTableWidget()
        table.setObjectName("ReportTable")
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["时间", "系统", "分类", "文件", "大小"])
        table.setRowCount(len(logs))
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setMinimumHeight(260)

        for row, item in enumerate(logs):
            values = [
                item.modified_at.strftime("%Y-%m-%d %H:%M") if item.modified_at else "未知",
                item.category,
                item.subcategory or "-",
                item.path.name,
                format_size(item.size_bytes),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, row)
                table.setItem(row, col, cell)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        if logs:
            table.selectRow(0)
        return table

    def _build_error_table(self, errors: list[LogErrorItem]) -> QTableWidget:
        table = QTableWidget()
        table.setObjectName("ReportTable")
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["时间", "系统", "文件", "错误内容"])
        table.setRowCount(len(errors))
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(True)
        table.verticalHeader().setVisible(False)
        table.setMinimumHeight(180)

        for row, item in enumerate(errors):
            values = [
                item.modified_at.strftime("%Y-%m-%d %H:%M") if item.modified_at else "未知",
                item.category,
                item.path.name,
                item.line,
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, row)
                table.setItem(row, col, cell)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        table.resizeRowsToContents()
        return table

    def _build_log_actions(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        view_button = QPushButton("查看日志内容")
        view_button.setObjectName("PrimaryButton")
        view_button.clicked.connect(self.view_selected_log)
        layout.addWidget(view_button)

        open_button = QPushButton("打开日志文件")
        open_button.clicked.connect(self.open_selected_log)
        layout.addWidget(open_button)

        folder_button = QPushButton("打开目录")
        folder_button.clicked.connect(self.open_selected_log_folder)
        layout.addWidget(folder_button)

        refresh_button = QPushButton("刷新日志")
        refresh_button.clicked.connect(lambda: self.update_snapshot(self.snapshot))
        layout.addWidget(refresh_button)
        layout.addStretch(1)
        return row

    def selected_log(self) -> LogFileItem | None:
        if self.log_table is None:
            return None
        row = self.log_table.currentRow()
        if row < 0 or row >= len(self.logs):
            return None
        return self.logs[row]

    def selected_error(self) -> LogErrorItem | None:
        if self.error_table is None:
            return None
        row = self.error_table.currentRow()
        if row < 0 or row >= len(self.errors):
            return None
        return self.errors[row]

    def view_selected_log(self) -> None:
        log = self.selected_log()
        if log is None:
            self.show_status(ActionResult(False, "请先选中一个日志。"))
            return
        keyword = self.keyword_input.text() if self.keyword_input is not None else ""
        content = read_log_file(log.path, keyword=keyword)
        if self.preview_box is not None:
            self.preview_box.setPlainText(content)
        self.show_status(ActionResult(True, f"已读取：{log.path}"))

    def open_selected_log(self) -> None:
        log = self.selected_log()
        self.show_status(open_path(log.path) if log is not None else ActionResult(False, "请先选中一个日志。"))

    def open_selected_log_folder(self) -> None:
        log = self.selected_log()
        self.show_status(open_parent(log.path) if log is not None else ActionResult(False, "请先选中一个日志。"))

    def show_status(self, result: ActionResult) -> None:
        if self.status_label is not None:
            self.status_label.setText(result.message)

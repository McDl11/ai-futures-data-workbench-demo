from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
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
from desktop.pages.base import ScrollPage
from desktop.reports import (
    ReportItem,
    ReportSelection,
    delete_report,
    discover_reports,
    missing_report_attachments,
    regenerate_report,
    send_current_report,
)
from desktop.state import WorkspaceSnapshot, collect_workspace_snapshot
from desktop.widgets import Section, make_title
from desktop.workers import BackgroundTask


class ReportCenterPage(ScrollPage):
    def __init__(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        self.report_items: list[ReportItem] = []
        self.active_task: BackgroundTask | None = None
        self.table: QTableWidget | None = None
        self.date_input: QLineEdit | None = None
        self.output_box: QTextEdit | None = None
        self.last_output = ""
        super().__init__(snapshot)

    def update_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        super().update_snapshot(snapshot)

    def build(self, snapshot: WorkspaceSnapshot) -> None:
        self.report_items = discover_reports(snapshot.project_root)

        self.layout.addWidget(
            make_title(
                "报告中心",
                "列出白盘和日报，支持打开 HTML/PDF、重新生成报告，以及确认后发送当前报告。",
            )
        )

        splitter = QSplitter(Qt.Vertical)
        splitter.setObjectName("ReportCenterSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(13)

        reports = Section("报告")
        self.table = self._build_report_table(self.report_items)
        reports.add(self.table)
        reports.add(self._build_open_actions())
        top_layout.addWidget(reports)

        generate = Section("重新生成", "默认跳过数据更新，只用已有数据库重新生成报告；不会发送邮件。")
        generate.add(self._build_generate_controls(snapshot))
        top_layout.addWidget(generate)

        send = Section("发送当前报告", "会真实发送邮件。点击后会再次弹窗确认，避免误发。")
        send.add(self._build_send_controls())
        top_layout.addWidget(send)
        top_layout.addStretch(1)

        output = Section("执行输出")
        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setMinimumHeight(120)
        self.output_box.setPlaceholderText("重新生成或发送报告的输出会显示在这里。")
        if self.last_output:
            self.output_box.setPlainText(self.last_output)
        output.add(self.output_box)
        output.setMinimumHeight(170)

        splitter.addWidget(top)
        splitter.addWidget(output)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([560, 260])
        self.layout.addWidget(splitter)

    def _build_report_table(self, items: list[ReportItem]) -> QTableWidget:
        table = QTableWidget()
        table.setObjectName("ReportTable")
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["日期", "HTML", "PDF", "Markdown", "更新时间"])
        table.setRowCount(len(items))
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setMinimumHeight(240)

        for row, item in enumerate(items):
            values = [
                item.trade_date,
                "有" if item.has_html else "缺",
                "有" if item.has_pdf else "缺",
                "有" if item.has_md else "缺",
                item.modified_at.strftime("%Y-%m-%d %H:%M") if item.modified_at else "未知",
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, row)
                table.setItem(row, col, cell)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        if items:
            table.selectRow(0)
        return table

    def _build_open_actions(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        html_button = QPushButton("打开 HTML")
        html_button.clicked.connect(lambda: self.open_selected_report_file("html"))
        layout.addWidget(html_button)

        pdf_button = QPushButton("打开 PDF")
        pdf_button.clicked.connect(lambda: self.open_selected_report_file("pdf"))
        layout.addWidget(pdf_button)

        folder_button = QPushButton("打开目录")
        folder_button.clicked.connect(self.open_selected_report_folder)
        layout.addWidget(folder_button)

        delete_button = QPushButton("删除选中报告")
        delete_button.setObjectName("DangerButton")
        delete_button.clicked.connect(self.confirm_and_delete_selected_report)
        layout.addWidget(delete_button)

        layout.addStretch(1)
        return row

    def _build_generate_controls(self, snapshot: WorkspaceSnapshot) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.date_input = QLineEdit()
        self.date_input.setPlaceholderText("YYYYMMDD")
        self.date_input.setText(snapshot.latest_trade_date or "")
        self.date_input.setMaximumWidth(140)
        layout.addWidget(QLabel("日期"))
        layout.addWidget(self.date_input)

        generate_button = QPushButton("重新生成")
        generate_button.setObjectName("PrimaryButton")
        generate_button.clicked.connect(self.regenerate_selected_report)
        layout.addWidget(generate_button)

        layout.addStretch(1)
        return row

    def _build_send_controls(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        send_button = QPushButton("发送选中报告")
        send_button.setObjectName("PrimaryButton")
        send_button.clicked.connect(self.confirm_and_send_selected_report)
        layout.addWidget(send_button)

        layout.addStretch(1)
        return row

    def selected_report(self) -> ReportItem | None:
        if self.table is None:
            return None
        row = self.table.currentRow()
        if row < 0 or row >= len(self.report_items):
            return None
        return self.report_items[row]

    def open_selected_report_file(self, file_type: str) -> None:
        report = self.selected_report()
        if report is None:
            self.show_result(ActionResult(False, "请先选中一份报告。"))
            return

        path = report.html_path if file_type == "html" else report.pdf_path
        self.show_result(open_path(path))

    def open_selected_report_folder(self) -> None:
        report = self.selected_report()
        if report is None:
            self.show_result(ActionResult(False, "请先选中一份报告。"))
            return
        self.show_result(open_parent(report.directory))

    def confirm_and_delete_selected_report(self) -> None:
        report = self.selected_report()
        if report is None:
            self.show_result(ActionResult(False, "请先选中一份报告。"))
            return

        answer = QMessageBox.question(
            self,
            "确认删除",
            f"确认删除 {report.trade_date} {report.label}？\n\n会删除这份报告对应的 HTML、PDF、Markdown 文件。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.show_result(ActionResult(False, "已取消删除。"))
            return

        result = delete_report(report)
        self.show_result(result)
        self.update_snapshot(collect_workspace_snapshot(self.snapshot.project_root))

    def regenerate_selected_report(self) -> None:
        selection = self.selection_from_controls()
        if selection is None:
            return

        self.run_background(
            "正在重新生成白盘报告，请稍候...",
            lambda: regenerate_report(self.snapshot.project_root, selection.trade_date),
        )

    def confirm_and_send_selected_report(self) -> None:
        report = self.selected_report()
        if report is None:
            self.show_result(ActionResult(False, "请先选中一份报告。"))
            return
        missing = missing_report_attachments(report)
        if missing:
            labels = "、".join(label for label, _path in missing)
            self.show_result(ActionResult(False, f"当前报告缺少 {labels} 文件，不能发送。"))
            return

        answer = QMessageBox.question(
            self,
            "确认发送",
            f"确认发送 {report.trade_date} {report.label}？\n\n这会真实发送邮件；系统会自动允许重发当前报告。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.show_result(ActionResult(False, "已取消发送。"))
            return

        self.run_background(
            "正在发送报告，请稍候...",
            lambda: send_current_report(self.snapshot.project_root, report, resend=True),
        )

    def selection_from_controls(self) -> ReportSelection | None:
        if self.date_input is None:
            self.show_result(ActionResult(False, "页面控件尚未就绪。"))
            return None
        trade_date = self.date_input.text().strip()
        if len(trade_date) != 8 or not trade_date.isdigit():
            self.show_result(ActionResult(False, "请输入 8 位日期，例如 20260616。"))
            return None
        return ReportSelection(trade_date, "white")

    def run_background(self, start_message: str, fn) -> None:
        if self.active_task is not None:
            self.show_result(ActionResult(False, "已有任务正在运行，请稍候。"))
            return
        self.show_result(ActionResult(True, start_message))
        self.active_task = BackgroundTask(fn, self.on_background_finished)
        self.active_task.done.connect(self.clear_active_task)
        self.active_task.start()

    def on_background_finished(self, result: ActionResult) -> None:
        self.show_result(result)
        self.update_snapshot(collect_workspace_snapshot(self.snapshot.project_root))

    def clear_active_task(self) -> None:
        self.active_task = None

    def show_result(self, result: ActionResult) -> None:
        output = result.output.strip()
        self.last_output = result.message if not output else f"{result.message}\n\n{output}"
        if self.output_box is not None:
            self.output_box.setPlainText(self.last_output)

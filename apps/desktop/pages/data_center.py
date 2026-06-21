from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from desktop.actions import ActionResult
from desktop.data_center import (
    CoreTableStatus,
    collect_core_table_statuses,
    database_detail,
    find_recent_gap_range,
    plan_data_update_range,
    run_data_gap_repair,
    run_data_quick_update,
    run_data_update,
)
from desktop.pages.base import ScrollPage
from desktop.state import WorkspaceSnapshot, collect_workspace_snapshot, format_trade_date
from desktop.widgets import Section, make_title
from desktop.workers import BackgroundTask


class DataCenterPage(ScrollPage):
    def __init__(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        self.active_task: BackgroundTask | None = None
        self.table: QTableWidget | None = None
        self.output_box: QTextEdit | None = None
        self.last_output = ""
        super().__init__(snapshot)

    def update_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        super().update_snapshot(snapshot)

    def build(self, snapshot: WorkspaceSnapshot) -> None:
        self.layout.addWidget(
            make_title(
                "数据中心",
                "查看核心数据表的最新日期、行数和缺口检查，并可一键更新或补最近缺口。",
            )
        )

        splitter = QSplitter(Qt.Vertical)
        splitter.setObjectName("DataCenterSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(13)

        core = Section("核心表", database_detail(snapshot.database.path))
        self.table = self._build_table(collect_core_table_statuses(snapshot.database.path))
        core.add(self.table)
        top_layout.addWidget(core)

        actions = Section("数据更新", "一键更新会自动避开休市日；缺口检查提示异常时，可补最近 60 个交易日内发现的缺口。")
        actions.add(self._build_actions())
        top_layout.addWidget(actions)
        top_layout.addStretch(1)

        output = Section("执行输出")
        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setMinimumHeight(120)
        self.output_box.setPlaceholderText("更新或补缺口的输出会显示在这里。")
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

    def _build_table(self, statuses: list[CoreTableStatus]) -> QTableWidget:
        table = QTableWidget()
        table.setObjectName("ReportTable")
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels(["名称", "表名", "最新日期", "行数", "日期范围", "缺口检查", "状态"])
        table.setRowCount(len(statuses))
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(True)
        table.verticalHeader().setVisible(False)
        table.setMinimumHeight(360)

        for row, status in enumerate(statuses):
            values = [
                status.label,
                status.table,
                format_trade_date(status.latest_date),
                f"{status.row_count:,}",
                self._date_range_text(status.earliest_date, status.latest_date),
                self._gap_text(status),
                self._state_text(status.state),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, status.table)
                table.setItem(row, col, cell)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        table.setColumnWidth(0, 120)
        table.resizeRowsToContents()
        if statuses:
            table.selectRow(0)
        return table

    def _build_actions(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        quick_button = QPushButton("快速更新")
        quick_button.setObjectName("PrimaryButton")
        quick_button.clicked.connect(self.quick_update_data)
        layout.addWidget(quick_button)

        update_button = QPushButton("稳妥更新")
        update_button.setObjectName("PrimaryButton")
        update_button.clicked.connect(self.update_data)
        layout.addWidget(update_button)

        repair_button = QPushButton("补最近缺口")
        repair_button.clicked.connect(self.repair_recent_gaps)
        layout.addWidget(repair_button)

        refresh_button = QPushButton("刷新状态")
        refresh_button.clicked.connect(self.refresh_data_status)
        layout.addWidget(refresh_button)

        layout.addStretch(1)
        return row

    def quick_update_data(self) -> None:
        _start_date, end_date = plan_data_update_range(self.snapshot.database.path)
        range_text = self._range_text(end_date, end_date)
        self.run_background(
            f"正在快速更新：{range_text}，请稍候...",
            lambda: run_data_quick_update(self.snapshot.project_root),
        )

    def update_data(self) -> None:
        start_date, end_date = plan_data_update_range(self.snapshot.database.path)
        range_text = self._range_text(start_date, end_date)
        self.run_background(
            f"正在更新数据：{range_text}，请稍候...",
            lambda: run_data_update(self.snapshot.project_root),
        )

    def repair_recent_gaps(self) -> None:
        gap_range = find_recent_gap_range(self.snapshot.database.path)
        if gap_range is None:
            self.show_result(ActionResult(True, "最近缺口为空，无需补数据。"))
            return

        start_date, end_date = gap_range
        self.run_background(
            f"正在补最近缺口：{self._range_text(start_date, end_date)}，请稍候...",
            lambda: run_data_gap_repair(self.snapshot.project_root, gap_range=gap_range),
        )

    def refresh_data_status(self) -> None:
        self.show_result(ActionResult(True, "已刷新数据状态。"))
        self.update_snapshot(collect_workspace_snapshot(self.snapshot.project_root))

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

    def _date_range_text(self, earliest: str | None, latest: str | None) -> str:
        if not earliest and not latest:
            return "未知"
        return f"{format_trade_date(earliest)} ~ {format_trade_date(latest)}"

    def _range_text(self, start_date: str | None, end_date: str | None) -> str:
        if not start_date or not end_date:
            return "由脚本自动判断"
        return f"{format_trade_date(start_date)} ~ {format_trade_date(end_date)}"

    def _gap_text(self, status: CoreTableStatus) -> str:
        if status.gap_count and status.gap_count > 0:
            return f"{status.gap_summary}\n处理：点击“补最近缺口”"
        if status.state == "warning":
            return f"{status.gap_summary}\n处理：检查表结构或脚本配置"
        return status.gap_summary

    def _state_text(self, state: str) -> str:
        return {
            "ok": "正常",
            "warning": "需检查",
            "danger": "异常",
        }.get(state, state)

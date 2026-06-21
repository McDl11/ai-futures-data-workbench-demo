from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
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

from desktop.actions import ActionResult
from desktop.pages.base import ScrollPage
from desktop.state import WorkspaceSnapshot, collect_workspace_snapshot
from desktop.tasks import (
    TaskDefinition,
    TaskHistoryItem,
    TaskProcessItem,
    get_task_processes,
    load_task_history,
    run_task,
    start_background_task,
    stop_background_task,
    task_catalog,
)
from desktop.widgets import Section, make_title, short_path
from desktop.workers import BackgroundTask


class TaskCenterPage(ScrollPage):
    def __init__(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        self.tasks: list[TaskDefinition] = []
        self.history: list[TaskHistoryItem] = []
        self.processes: list[TaskProcessItem] = []
        self.active_task: BackgroundTask | None = None
        self.task_table: QTableWidget | None = None
        self.process_table: QTableWidget | None = None
        self.output_box: QTextEdit | None = None
        self.last_output = ""
        super().__init__(snapshot)

    def update_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        super().update_snapshot(snapshot)

    def build(self, snapshot: WorkspaceSnapshot) -> None:
        self.tasks = [task for task in task_catalog(snapshot.project_root) if not task.background]
        self.history = load_task_history(snapshot.project_root)
        self.processes = get_task_processes(snapshot.project_root)

        self.layout.addWidget(
            make_title(
                "任务中心",
                "运行临时脚本、管理 24 小时守护演练进程，并查看执行输出。",
            )
        )

        splitter = QSplitter(Qt.Vertical)
        splitter.setObjectName("TaskCenterSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(13)

        tasks = Section("临时任务", "这些任务只运行一次，执行完成后会自动结束。")
        self.task_table = self._build_task_table(self.tasks)
        tasks.add(self.task_table)
        tasks.add(self._build_task_actions())
        top_layout.addWidget(tasks)

        processes = Section("任务进程", "24 小时守护演练启动后会独立运行，关闭桌面 UI 后仍会继续工作。")
        self.process_table = self._build_process_table(self.processes)
        processes.add(self.process_table)
        processes.add(self._build_process_actions())
        top_layout.addWidget(processes)
        top_layout.addStretch(1)

        output = Section("执行输出")
        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setMinimumHeight(140)
        self.output_box.setPlaceholderText("运行一次、启动守护演练、停止守护演练的结果会显示在这里。")
        if self.last_output:
            self.output_box.setPlainText(self.last_output)
        output.add(self.output_box)
        output.setMinimumHeight(190)

        splitter.addWidget(top)
        splitter.addWidget(output)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([640, 260])
        self.layout.addWidget(splitter)

    def _build_task_table(self, tasks: list[TaskDefinition]) -> QTableWidget:
        table = QTableWidget()
        table.setObjectName("ReportTable")
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["任务", "分组", "脚本", "参数", "说明"])
        table.setRowCount(len(tasks))
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(True)
        table.verticalHeader().setVisible(False)
        table.setMinimumHeight(260)

        for row, task in enumerate(tasks):
            values = [
                task.name,
                task.group,
                task.script_name,
                " ".join(task.args) or "-",
                task.description,
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, task.id)
                table.setItem(row, col, cell)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        table.resizeRowsToContents()
        if tasks:
            table.selectRow(0)
        return table

    def _build_process_table(self, processes: list[TaskProcessItem]) -> QTableWidget:
        table = QTableWidget()
        table.setObjectName("ReportTable")
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels(["任务", "状态", "PID", "启动时间", "脚本", "日志", "说明"])
        table.setRowCount(len(processes))
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setMinimumHeight(180)

        for row, item in enumerate(processes):
            values = [
                item.name,
                item.status,
                str(item.pid) if item.pid is not None else "-",
                item.started_at or "-",
                item.script_name,
                short_path(item.log_path, self.snapshot.project_root) if item.log_path is not None else "-",
                item.description,
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, item.task_id)
                table.setItem(row, col, cell)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        table.resizeRowsToContents()
        if processes:
            table.selectRow(0)
        return table

    def _build_task_actions(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        run_button = QPushButton("运行一次")
        run_button.setObjectName("PrimaryButton")
        run_button.clicked.connect(self.run_selected_task)
        layout.addWidget(run_button)

        refresh_button = QPushButton("刷新状态")
        refresh_button.clicked.connect(self.refresh_task_status)
        layout.addWidget(refresh_button)
        layout.addStretch(1)
        return row

    def _build_process_actions(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        start_button = QPushButton("启动守护演练")
        start_button.setObjectName("PrimaryButton")
        start_button.clicked.connect(self.start_daemon_send)
        layout.addWidget(start_button)

        stop_button = QPushButton("停止守护演练")
        stop_button.setObjectName("DangerButton")
        stop_button.clicked.connect(self.stop_daemon_send)
        layout.addWidget(stop_button)

        refresh_button = QPushButton("刷新进程")
        refresh_button.clicked.connect(self.refresh_task_status)
        layout.addWidget(refresh_button)
        layout.addStretch(1)
        return row

    def selected_task(self) -> TaskDefinition | None:
        if self.task_table is None:
            return None
        row = self.task_table.currentRow()
        if row < 0 or row >= len(self.tasks):
            return None
        return self.tasks[row]

    def daemon_send_task(self) -> TaskDefinition | None:
        return next((task for task in task_catalog(self.snapshot.project_root) if task.id == "auto_report_daemon_send"), None)

    def run_selected_task(self) -> None:
        task = self.selected_task()
        if task is None:
            self.show_result(ActionResult(False, "请先选中一个任务。"))
            return
        self.run_background(
            f"正在运行：{task.name}，请稍候...",
            lambda: run_task(self.snapshot.project_root, task.id),
        )

    def start_daemon_send(self) -> None:
        task = self.daemon_send_task()
        if task is None:
            self.show_result(ActionResult(False, "未找到 24 小时守护演练任务。"))
            return
        answer = QMessageBox.question(
            self,
            "确认启动",
            "这是 24 小时 dry-run 守护演练脚本，到点只写入发送记录，不会真实发送邮件。关闭桌面 UI 后它也会继续运行。确认启动？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.show_result(ActionResult(False, "已取消启动。"))
            return
        result = start_background_task(self.snapshot.project_root, task.id)
        self.show_result(result)
        self.update_snapshot(collect_workspace_snapshot(self.snapshot.project_root))

    def stop_daemon_send(self) -> None:
        task = self.daemon_send_task()
        if task is None:
            self.show_result(ActionResult(False, "未找到 24 小时守护演练任务。"))
            return
        answer = QMessageBox.question(
            self,
            "确认停止",
            "确认停止 24 小时守护演练？停止后不会再自动执行定时演练。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.show_result(ActionResult(False, "已取消停止。"))
            return
        result = stop_background_task(self.snapshot.project_root, task.id)
        self.show_result(result)
        self.update_snapshot(collect_workspace_snapshot(self.snapshot.project_root))

    def refresh_task_status(self) -> None:
        self.show_result(ActionResult(True, "已刷新任务进程。"))
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

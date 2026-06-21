from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QWidget

from desktop.actions import run_python_script
from desktop.pages.base import ScrollPage
from desktop.project_paths import report_system_dir
from desktop.state import WorkspaceSnapshot, format_size, format_trade_date
from desktop.widgets import DashboardCard, Section, file_list, format_datetime, make_title


class HomePage(ScrollPage):
    def __init__(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        self.health_output: QTextEdit | None = None
        super().__init__(snapshot)

    def update_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        super().update_snapshot(snapshot)

    def build(self, snapshot: WorkspaceSnapshot) -> None:
        self.layout.addWidget(
            make_title(
                "首页仪表盘",
                "打开软件先看这里：数据、报告、邮件、错误和体检入口都集中在第一屏。",
            )
        )

        cards = QWidget()
        grid = QGridLayout(cards)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)

        trade_date = snapshot.latest_trade_date
        grid.addWidget(
            DashboardCard(
                "最新交易日",
                format_trade_date(trade_date) if trade_date else "未读到",
                "来自 fut_daily 最新 trade_date" if trade_date else "请先检查数据库是否已更新",
                "ok" if trade_date else "warning",
            ),
            0,
            0,
        )
        grid.addWidget(
            DashboardCard(
                "数据状态",
                snapshot.data_status.value,
                f"{snapshot.data_status.detail} · {format_size(snapshot.database.size_bytes)}",
                snapshot.data_status.state,
            ),
            0,
            1,
        )
        grid.addWidget(
            DashboardCard(
                "报告状态",
                snapshot.report_status.value,
                snapshot.report_status.detail,
                snapshot.report_status.state,
            ),
            0,
            2,
        )
        grid.addWidget(
            DashboardCard(
                "邮件状态",
                snapshot.mail_status.value,
                snapshot.mail_status.detail,
                snapshot.mail_status.state,
            ),
            1,
            0,
        )
        grid.addWidget(
            DashboardCard(
                "最近错误",
                snapshot.recent_error.value,
                snapshot.recent_error.detail,
                snapshot.recent_error.state,
            ),
            1,
            1,
        )
        grid.addWidget(
            DashboardCard(
                "一键体检",
                "可立即运行",
                f"只读检查，不会发送邮件或改数据 · 刷新于 {format_datetime(snapshot.collected_at)}",
                "neutral",
            ),
            1,
            2,
        )

        self.layout.addWidget(cards)

        health = Section("一键体检", "运行 health_check.py，结果会直接显示在这里。")
        action_row = QWidget()
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        health_button = QPushButton("运行体检")
        health_button.setObjectName("PrimaryButton")
        health_button.clicked.connect(self.run_health_check)
        action_layout.addWidget(health_button)

        hint = QLabel("体检只读取状态并写入体检日志，不会补数据或真实发送邮件。")
        hint.setObjectName("MutedText")
        action_layout.addWidget(hint, 1)
        health.add(action_row)

        self.health_output = QTextEdit()
        self.health_output.setReadOnly(True)
        self.health_output.setMinimumHeight(180)
        self.health_output.setPlaceholderText("点击“运行体检”后，体检输出会显示在这里。")
        health.add(self.health_output)
        self.layout.addWidget(health)

        activity = Section("最近文件", "保留最近报告和日志，方便继续追查。")
        activity.add(file_list((snapshot.recent_reports + snapshot.recent_logs)[:8], "未发现最近文件"))
        self.layout.addWidget(activity)

    def run_health_check(self) -> None:
        if self.health_output is None:
            return

        report_dir = report_system_dir(self.snapshot.project_root)
        script = report_dir / "health_check.py"
        self.health_output.setPlainText("正在运行体检，请稍候...")

        result = run_python_script(report_dir, script, timeout_seconds=180)
        output = result.output.strip() or "没有输出。"
        self.health_output.setPlainText(f"{result.message}\n\n{output}")

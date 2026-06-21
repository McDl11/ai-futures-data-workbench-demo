from __future__ import annotations

from desktop.pages.base import ScrollPage
from desktop.state import WorkspaceSnapshot
from desktop.status_labels import config_status_label
from desktop.widgets import Section, make_title, status_row


class SystemCenterPage(ScrollPage):
    def build(self, snapshot: WorkspaceSnapshot) -> None:
        self.layout.addWidget(
            make_title(
                "系统中心",
                "集中查看数据库、目录、脚本、日志和配置依赖文件是否正常。",
            )
        )

        data = Section("数据状态")
        data.add(status_row("主数据库", snapshot.database))
        data.add(status_row("下载日志目录", snapshot.downloader_logs_dir))
        self.layout.addWidget(data)

        reports = Section("报告目录")
        reports.add(status_row("报告输出", snapshot.reports_dir))
        self.layout.addWidget(reports)

        logs = Section("日志目录")
        logs.add(status_row("报告系统日志", snapshot.report_logs_dir))
        logs.add(status_row("下载系统日志", snapshot.downloader_logs_dir))
        self.layout.addWidget(logs)

        scripts = Section("关键脚本")
        for script in snapshot.script_files:
            scripts.add(status_row(script.path.name, script))
        self.layout.addWidget(scripts)

        configs = Section("配置与依赖文件状态")
        for config in snapshot.config_files:
            configs.add(status_row(config_status_label(config.path, snapshot.project_root), config))
        self.layout.addWidget(configs)

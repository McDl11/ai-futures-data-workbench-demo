import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from desktop.main_window import MainWindow
from desktop.pages.config_center import ConfigCenterPage
from desktop.pages.data_center import DataCenterPage
from desktop.pages.log_center import LogCenterPage
from desktop.pages.report_center import ReportCenterPage
from desktop.pages.system_center import SystemCenterPage
from desktop.pages.task_center import TaskCenterPage
from desktop.state import collect_workspace_snapshot


class DesktopSystemCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_contains_system_center_after_home(self):
        window = MainWindow()

        labels = [button.text() for button in window.nav_buttons]

        self.assertEqual(labels[:3], ["首页", "系统中心", "数据中心"])
        self.assertIsInstance(window.pages[1], SystemCenterPage)

    def test_system_center_collects_shared_status_sections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "data").mkdir()
            (root / "data" / "futures.db").write_bytes(b"db")
            report_dir = root / "futures_report_system"
            report_dir.mkdir()
            downloader_dir = root / "tushare down"
            downloader_dir.mkdir()
            (report_dir / "reports").mkdir()
            (report_dir / "logs").mkdir()
            (downloader_dir / "logs").mkdir()
            for script in ("auto_report_daemon.py", "auto_report_once.py", "health_check.py", "maintenance.py"):
                (report_dir / script).write_text("print('ok')", encoding="utf-8")
            for script in ("daily_update.py", "auto_futures_downloader.py"):
                (downloader_dir / script).write_text("print('ok')", encoding="utf-8")
            (report_dir / ".env").write_text("EMAIL_SENDER=a@example.com", encoding="utf-8")
            (downloader_dir / ".env").write_text("TUSHARE_TOKEN=test", encoding="utf-8")

            page = SystemCenterPage(collect_workspace_snapshot(root))
            labels = [label.text() for label in page.findChildren(QLabel)]

            self.assertIn("数据状态", labels)
            self.assertIn("报告目录", labels)
            self.assertIn("日志目录", labels)
            self.assertIn("关键脚本", labels)
            self.assertIn("配置与依赖文件状态", labels)
            self.assertIn("报告系统 .env", labels)
            self.assertIn("下载器 .env", labels)
            self.assertIn(str(Path("data") / "futures.db") + " · 2 B", labels)
            self.assertNotIn(str(root / "data" / "futures.db"), labels)

    def test_other_centers_no_longer_show_shared_status_sections(self):
        snapshot = collect_workspace_snapshot(Path("D:/AI期货数据工作台"))

        pages_and_removed_labels = [
            (DataCenterPage(snapshot), "数据状态"),
            (ReportCenterPage(snapshot), "报告目录"),
            (TaskCenterPage(snapshot), "关键脚本"),
            (LogCenterPage(snapshot), "日志目录"),
            (ConfigCenterPage(snapshot), "配置与依赖文件状态"),
        ]

        for page, removed_label in pages_and_removed_labels:
            labels = [label.text() for label in page.findChildren(QLabel)]
            self.assertNotIn(removed_label, labels)


if __name__ == "__main__":
    unittest.main()

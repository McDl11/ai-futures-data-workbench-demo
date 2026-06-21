import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from desktop.pages.task_center import TaskCenterPage
from desktop.state import collect_workspace_snapshot


class DesktopTaskCenterPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_task_center_uses_clear_process_actions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            report_dir.mkdir()
            for script_name in ("auto_report_daemon.py", "auto_report_once.py", "health_check.py", "maintenance.py"):
                (report_dir / script_name).write_text("print('ok')", encoding="utf-8")

            snapshot = collect_workspace_snapshot(root)
            page = TaskCenterPage(snapshot)
            buttons = [button.text() for button in page.findChildren(QPushButton)]

            self.assertIn("运行一次", buttons)
            self.assertIn("启动守护演练", buttons)
            self.assertIn("停止守护演练", buttons)
            self.assertNotIn("运行选中任务", buttons)
            self.assertNotIn("启动后台任务", buttons)

    def test_task_center_marks_daemon_running_from_pid_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            report_dir.mkdir()
            for script_name in ("auto_report_daemon.py", "auto_report_once.py", "health_check.py", "maintenance.py"):
                (report_dir / script_name).write_text("print('ok')", encoding="utf-8")
            runtime = root / ".desktop_runtime"
            runtime.mkdir()
            (runtime / "auto_report_daemon_send.pid").write_text(str(os.getpid()), encoding="utf-8")

            snapshot = collect_workspace_snapshot(root)
            page = TaskCenterPage(snapshot)

            statuses = [
                page.process_table.item(row, 1).text()
                for row in range(page.process_table.rowCount())
            ]
            pids = [
                page.process_table.item(row, 2).text()
                for row in range(page.process_table.rowCount())
            ]

            self.assertIn("运行中", statuses)
            self.assertIn(str(os.getpid()), pids)


if __name__ == "__main__":
    unittest.main()

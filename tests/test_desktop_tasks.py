import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop.actions import ActionResult
from desktop.tasks import (
    TaskProcessItem,
    TaskStartResult,
    get_task_processes,
    is_process_running,
    load_task_history,
    record_task_result,
    run_task,
    start_background_task,
    stop_background_task,
    task_catalog,
)


class DesktopTaskTests(unittest.TestCase):
    def test_task_catalog_includes_24_hour_daemon(self):
        tasks = task_catalog(Path("D:/AI期货数据工作台"))
        daemon = next(task for task in tasks if task.id == "auto_report_daemon_send")

        self.assertEqual(daemon.script_name, "auto_report_daemon.py")
        self.assertTrue(daemon.background)
        self.assertTrue(daemon.can_stop)
        self.assertEqual(daemon.name, "24小时守护演练")
        self.assertNotIn("--send", daemon.args)

    def test_task_catalog_hides_report_send_and_data_update(self):
        tasks = task_catalog(Path("D:/AI期货数据工作台"))
        task_ids = {task.id for task in tasks}

        self.assertNotIn("auto_report_once_white_send", task_ids)
        self.assertNotIn("daily_update", task_ids)

    def test_get_task_processes_marks_running_daemon_from_pid_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / ".desktop_runtime"
            runtime.mkdir()
            (runtime / "auto_report_daemon_send.pid").write_text("23456", encoding="utf-8")

            processes = get_task_processes(root, process_checker=lambda pid: pid == 23456)
            daemon = next(item for item in processes if item.task_id == "auto_report_daemon_send")

            self.assertIsInstance(daemon, TaskProcessItem)
            self.assertEqual(daemon.status, "运行中")
            self.assertEqual(daemon.pid, 23456)

    def test_get_task_processes_only_lists_background_processes(self):
        processes = get_task_processes(Path("D:/AI期货数据工作台"), process_checker=lambda pid: False)

        self.assertEqual([item.task_id for item in processes], ["auto_report_daemon_send"])

    def test_get_task_processes_marks_stale_pid_as_exited(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / ".desktop_runtime"
            runtime.mkdir()
            (runtime / "auto_report_daemon_send.pid").write_text("23456", encoding="utf-8")

            processes = get_task_processes(root, process_checker=lambda pid: False)
            daemon = next(item for item in processes if item.task_id == "auto_report_daemon_send")

            self.assertEqual(daemon.status, "异常退出")
            self.assertEqual(daemon.pid, 23456)

    def test_windows_process_check_does_not_send_os_kill_signal(self):
        with patch("desktop.tasks.os.name", "nt"):
            with patch("desktop.tasks.os.kill", side_effect=AssertionError("must not signal on Windows")):
                with patch("desktop.tasks._windows_process_running", return_value=True) as checker:
                    self.assertTrue(is_process_running(34567))

        checker.assert_called_once_with(34567)

    def test_run_task_invokes_script_and_records_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            report_dir.mkdir()
            (report_dir / "health_check.py").write_text("print('ok')", encoding="utf-8")
            captured = {}

            def fake_runner(working_dir, script_path, args=None, timeout_seconds=0, env=None):
                captured["working_dir"] = working_dir
                captured["script"] = script_path.name
                captured["args"] = args
                captured["env"] = env
                return ActionResult(True, "done", "health ok")

            result = run_task(root, "health_check", runner=fake_runner)

            self.assertTrue(result.ok)
            self.assertEqual(captured["working_dir"], report_dir)
            self.assertEqual(captured["script"], "health_check.py")
            self.assertEqual(captured["env"]["PYTHONIOENCODING"], "utf-8")
            history = load_task_history(root)
            self.assertEqual(history[0].task_id, "health_check")
            self.assertEqual(history[0].status, "成功")

    def test_start_background_task_writes_pid_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            report_dir.mkdir()
            (report_dir / "auto_report_daemon.py").write_text("print('daemon')", encoding="utf-8")

            def fake_starter(task, project_root):
                return TaskStartResult(pid=12345, log_path=project_root / "daemon.log")

            result = start_background_task(root, "auto_report_daemon_send", starter=fake_starter)

            self.assertTrue(result.ok)
            self.assertIn("12345", result.output)
            self.assertIn("daemon.log", result.output)
            self.assertNotIn(str(root), result.output)
            history = load_task_history(root)
            self.assertEqual(history[0].status, "已启动")

    def test_start_background_task_does_not_start_duplicate_running_daemon(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / ".desktop_runtime"
            runtime.mkdir()
            (runtime / "auto_report_daemon_send.pid").write_text("12345", encoding="utf-8")
            called = False

            def fake_starter(task, project_root):
                nonlocal called
                called = True
                return TaskStartResult(pid=99999, log_path=project_root / "daemon.log")

            result = start_background_task(
                root,
                "auto_report_daemon_send",
                starter=fake_starter,
                process_checker=lambda pid: pid == 12345,
            )

            self.assertTrue(result.ok)
            self.assertFalse(called)
            self.assertIn("正在运行", result.message)
            self.assertIn(str(Path(".desktop_runtime") / "auto_report_daemon_send.log"), result.output)
            self.assertNotIn(str(root), result.output)

    def test_stop_background_task_uses_pid_file_and_records_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / ".desktop_runtime"
            runtime.mkdir()
            (runtime / "auto_report_daemon_send.pid").write_text("12345", encoding="utf-8")
            stopped = {}

            def fake_terminator(pid):
                stopped["pid"] = pid
                return ActionResult(True, "stopped", "")

            result = stop_background_task(root, "auto_report_daemon_send", terminator=fake_terminator)

            self.assertTrue(result.ok)
            self.assertEqual(stopped["pid"], 12345)
            self.assertFalse((runtime / "auto_report_daemon_send.pid").exists())
            history = load_task_history(root)
            self.assertEqual(history[0].status, "已停止")

    def test_record_task_result_keeps_recent_history_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record_task_result(root, "a", "任务A", "成功", "first")
            record_task_result(root, "b", "任务B", "失败", "second")

            history = load_task_history(root)

            self.assertEqual([item.task_id for item in history], ["b", "a"])


if __name__ == "__main__":
    unittest.main()

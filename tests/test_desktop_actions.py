import tempfile
import unittest
from pathlib import Path

from desktop.actions import (
    ActionResult,
    build_open_command,
    open_path,
    run_python_script,
)


class DesktopActionTests(unittest.TestCase):
    def test_build_open_command_uses_windows_startfile_mode(self):
        command = build_open_command(Path("C:/temp/report.pdf"))

        self.assertEqual(command, ("startfile", Path("C:/temp/report.pdf")))

    def test_open_path_reports_missing_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.txt"

            result = open_path(missing, opener=lambda _path: None)

            self.assertFalse(result.ok)
            self.assertIn("不存在", result.message)

    def test_open_path_calls_opener_for_existing_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "file.txt"
            target.write_text("hello", encoding="utf-8")
            opened = []

            result = open_path(target, opener=lambda path: opened.append(path))

            self.assertTrue(result.ok)
            self.assertEqual(opened, [target])

    def test_run_python_script_captures_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script = Path(temp_dir) / "check.py"
            script.write_text("print('health ok')", encoding="utf-8")

            result = run_python_script(Path(temp_dir), script, timeout_seconds=10)

            self.assertTrue(result.ok)
            self.assertIn("health ok", result.output)

    def test_run_python_script_handles_missing_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_python_script(Path(temp_dir), Path(temp_dir) / "missing.py")

            self.assertIsInstance(result, ActionResult)
            self.assertFalse(result.ok)
            self.assertIn("不存在", result.message)


if __name__ == "__main__":
    unittest.main()

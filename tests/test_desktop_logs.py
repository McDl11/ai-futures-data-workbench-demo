import tempfile
import unittest
from pathlib import Path

from desktop.logs import discover_log_files, read_log_file, scan_error_logs


class DesktopLogTests(unittest.TestCase):
    def test_discover_log_files_groups_report_and_downloader_logs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_log = root / "futures_report_system" / "logs" / "邮件发送"
            down_log = root / "tushare down" / "logs" / "增量更新"
            report_log.mkdir(parents=True)
            down_log.mkdir(parents=True)
            (report_log / "email.log").write_text("ok", encoding="utf-8")
            (down_log / "update.log").write_text("ok", encoding="utf-8")

            logs = discover_log_files(root)

            categories = {item.category for item in logs}
            self.assertIn("报告系统", categories)
            self.assertIn("数据下载", categories)

    def test_scan_error_logs_extracts_recent_error_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            log_dir = root / "futures_report_system" / "logs" / "自动任务"
            log_dir.mkdir(parents=True)
            log_file = log_dir / "auto.log"
            log_file.write_text("INFO ok\nERROR failed thing\nTraceback detail\n", encoding="utf-8")

            errors = scan_error_logs(root)

            self.assertEqual(errors[0].path, log_file)
            self.assertIn("Traceback detail", errors[0].line)

    def test_read_log_file_filters_keyword_and_tails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "app.log"
            log_file.write_text("\n".join(f"line {index}" for index in range(20)), encoding="utf-8")

            text = read_log_file(log_file, keyword="line 1", max_lines=5)

            self.assertIn("line 19", text)
            self.assertNotIn("line 0", text)


if __name__ == "__main__":
    unittest.main()

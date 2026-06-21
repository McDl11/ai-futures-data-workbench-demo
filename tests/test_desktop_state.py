import csv
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from desktop.state import (
    collect_workspace_snapshot,
    count_recipients,
    database_status,
    detect_recent_error,
    latest_email_status,
    latest_files,
    latest_report_status,
    latest_trade_date,
)


class DesktopStateTests(unittest.TestCase):
    def test_database_status_reports_existing_file_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "futures.db"
            db_path.write_bytes(b"abc")

            status = database_status(db_path)

            self.assertTrue(status.exists)
            self.assertEqual(status.size_bytes, 3)
            self.assertEqual(status.label, "正常")

    def test_database_status_handles_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status = database_status(Path(temp_dir) / "missing.db")

            self.assertFalse(status.exists)
            self.assertEqual(status.size_bytes, 0)
            self.assertEqual(status.label, "未找到")

    def test_count_recipients_counts_non_empty_csv_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "recipients.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["name", "email"])
                writer.writerow(["A", "a@example.com"])
                writer.writerow(["", ""])
                writer.writerow(["B", "b@example.com"])

            self.assertEqual(count_recipients(csv_path), 2)

    def test_latest_files_returns_newest_files_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older = root / "older.log"
            newer = root / "newer.log"
            older.write_text("old", encoding="utf-8")
            newer.write_text("new", encoding="utf-8")

            files = latest_files(root, patterns=("*.log",), limit=2)

            self.assertEqual([item.path.name for item in files], ["newer.log", "older.log"])

    def test_latest_trade_date_reads_fut_daily_max_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "futures.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("create table fut_daily (trade_date text)")
                conn.executemany(
                    "insert into fut_daily (trade_date) values (?)",
                    [("20260618",), ("20260619",)],
                )
                conn.commit()
            finally:
                conn.close()

            self.assertEqual(latest_trade_date(db_path), "20260619")

    def test_latest_report_status_marks_complete_trade_date_bundle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir) / "reports"
            report_dir = reports_dir / "20260619" / "daily"
            report_dir.mkdir(parents=True)
            (report_dir / "report_20260619.pdf").write_bytes(b"%PDF")
            (report_dir / "report_20260619.html").write_text("<html></html>", encoding="utf-8")
            (report_dir / "report_20260619.md").write_text("# report", encoding="utf-8")

            status = latest_report_status(reports_dir, "20260619")

            self.assertEqual(status.state, "ok")
            self.assertEqual(status.value, "已生成")
            self.assertIn("PDF/HTML/MD", status.detail)

    def test_latest_email_status_reads_send_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "futures.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    create table report_send_history (
                        id integer primary key autoincrement,
                        trade_date text,
                        report_type text,
                        status text,
                        sent_at text,
                        error text
                    )
                    """
                )
                conn.execute(
                    """
                    insert into report_send_history
                    (trade_date, report_type, status, sent_at, error)
                    values (?, ?, ?, ?, ?)
                    """,
                    ("20260619", "daily", "dry_run", "2026-06-19 08:31:00", ""),
                )
                conn.commit()
            finally:
                conn.close()

            status = latest_email_status(db_path)

            self.assertEqual(status.state, "ok")
            self.assertEqual(status.value, "演练发送")
            self.assertIn("20260619", status.detail)

    def test_detect_recent_error_returns_newest_error_line(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_dir = Path(temp_dir)
            older = logs_dir / "older.log"
            newer = logs_dir / "newer.log"
            older.write_text("ERROR old failure\n", encoding="utf-8")
            newer.write_text("all good\nTraceback new failure\n", encoding="utf-8")
            old_time = (datetime.now() - timedelta(days=1)).timestamp()
            os.utime(older, (old_time, old_time))

            status = detect_recent_error([logs_dir])

            self.assertEqual(status.state, "danger")
            self.assertEqual(status.value, "发现异常")
            self.assertIn("Traceback new failure", status.detail)

    def test_detect_recent_error_ignores_ok_lines_that_mention_error_keywords(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_dir = Path(temp_dir)
            health_log = logs_dir / "health.txt"
            health_log.write_text(
                "[OK] 最新日志快速检查 - 未发现 ERROR/Traceback\n"
                "[INFO] 体检完成 - 未发现阻断性问题\n",
                encoding="utf-8",
            )

            status = detect_recent_error([logs_dir])

            self.assertEqual(status.state, "ok")
            self.assertEqual(status.value, "未发现")

    def test_detect_recent_error_marks_old_error_as_recovered_after_new_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_dir = Path(temp_dir)
            old_error = logs_dir / "update_20260620.log"
            new_success = logs_dir / "update_20260621.log"
            old_error.write_text("2026-06-20 14:35:15 | ERROR | old failed\n", encoding="utf-8")
            new_success.write_text("2026-06-21 09:50:00 | OK | 更新完成\n", encoding="utf-8")
            old_time = (datetime.now() - timedelta(days=1)).timestamp()
            os.utime(old_error, (old_time, old_time))

            status = detect_recent_error([logs_dir])

            self.assertEqual(status.state, "ok")
            self.assertEqual(status.value, "已恢复")
            self.assertIn("旧异常", status.detail)

    def test_collect_workspace_snapshot_handles_empty_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = collect_workspace_snapshot(Path(temp_dir))

            self.assertEqual(snapshot.project_root, Path(temp_dir))
            self.assertFalse(snapshot.database.exists)
            self.assertEqual(snapshot.recipients_count, 0)
            self.assertEqual(snapshot.recent_reports, [])
            self.assertEqual(snapshot.recent_logs, [])
            self.assertEqual(snapshot.latest_trade_date, None)
            self.assertEqual(snapshot.report_status.value, "未发现")
            self.assertEqual(snapshot.mail_status.value, "无记录")

    def test_collect_workspace_snapshot_reads_current_workspace(self):
        project_root = Path(__file__).resolve().parents[1]

        snapshot = collect_workspace_snapshot(project_root)

        self.assertEqual(snapshot.project_root, project_root)
        self.assertTrue(snapshot.database.path.name.endswith("futures.db"))
        self.assertIsInstance(snapshot.recent_reports, list)
        self.assertIsInstance(snapshot.recent_logs, list)
        self.assertGreaterEqual(snapshot.recipients_count, 0)
        self.assertTrue(hasattr(snapshot, "data_status"))
        self.assertTrue(hasattr(snapshot, "report_status"))
        self.assertTrue(hasattr(snapshot, "mail_status"))
        self.assertTrue(hasattr(snapshot, "recent_error"))


if __name__ == "__main__":
    unittest.main()

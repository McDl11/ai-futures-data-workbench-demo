import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from desktop.actions import ActionResult
from desktop.report_records import load_report_generation_history, record_report_generation
from desktop.reports import regenerate_report


class DesktopReportRecordTests(unittest.TestCase):
    def test_record_report_generation_writes_paths_quality_and_status_to_sqlite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system" / "reports" / "20260618" / "white"
            report_dir.mkdir(parents=True)
            html_path = report_dir / "report.html"
            pdf_path = report_dir / "report.pdf"
            md_path = report_dir / "report.md"
            html_path.write_text("html", encoding="utf-8")
            pdf_path.write_bytes(b"pdf")
            md_path.write_text("md", encoding="utf-8")

            result = record_report_generation(
                root,
                trade_date="20260618",
                report_type="white",
                generation_status="success",
                html_path=html_path,
                pdf_path=pdf_path,
                md_path=md_path,
            )

            self.assertTrue(result.ok)
            rows = load_report_generation_history(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["trade_date"], "20260618")
            self.assertEqual(rows[0]["report_type"], "white")
            self.assertEqual(rows[0]["generation_status"], "success")
            self.assertEqual(rows[0]["quality_status"], "passed")
            self.assertEqual(Path(rows[0]["html_path"]), html_path)
            self.assertEqual(Path(rows[0]["pdf_path"]), pdf_path)
            self.assertEqual(Path(rows[0]["md_path"]), md_path)

    def test_record_report_generation_marks_missing_file_quality_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system" / "reports" / "20260618" / "white"
            report_dir.mkdir(parents=True)
            html_path = report_dir / "report.html"
            pdf_path = report_dir / "report.pdf"
            md_path = report_dir / "report.md"
            html_path.write_text("html", encoding="utf-8")
            md_path.write_text("md", encoding="utf-8")

            record_report_generation(
                root,
                trade_date="20260618",
                report_type="white",
                generation_status="success",
                html_path=html_path,
                pdf_path=pdf_path,
                md_path=md_path,
            )

            rows = load_report_generation_history(root)
            self.assertEqual(rows[0]["quality_status"], "failed")
            self.assertIn("PDF", rows[0]["quality_detail"])

    def test_regenerate_report_records_report_generation_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_system = root / "futures_report_system"
            report_system.mkdir()

            def fake_runner(working_dir, script_path, args=None, timeout_seconds=0):
                report_dir = working_dir / "reports" / "20260618" / "white"
                report_dir.mkdir(parents=True)
                (report_dir / "report.html").write_text("html", encoding="utf-8")
                (report_dir / "report.pdf").write_bytes(b"pdf")
                (report_dir / "report.md").write_text("md", encoding="utf-8")
                return ActionResult(True, "generated", "report ok")

            result = regenerate_report(root, "20260618", runner=fake_runner)

            self.assertTrue(result.ok)
            rows = load_report_generation_history(root)
            self.assertEqual(rows[0]["trade_date"], "20260618")
            self.assertEqual(rows[0]["report_type"], "white")
            self.assertEqual(rows[0]["generation_status"], "success")
            self.assertEqual(rows[0]["quality_status"], "passed")

    def test_report_generation_history_is_queryable_with_raw_sqlite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record_report_generation(
                root,
                trade_date="20260618",
                report_type="white",
                generation_status="failed",
                error="boom",
            )

            db_path = root / "data" / "futures.db"
            with closing(sqlite3.connect(db_path)) as conn:
                row = conn.execute(
                    """
                    select trade_date, report_type, generation_status, error
                    from report_generation_history
                    """
                ).fetchone()

            self.assertEqual(row, ("20260618", "white", "failed", "boom"))


if __name__ == "__main__":
    unittest.main()

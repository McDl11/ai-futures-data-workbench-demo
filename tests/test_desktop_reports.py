import tempfile
import unittest
from pathlib import Path

from desktop.actions import ActionResult
from desktop.reports import (
    ReportItem,
    ReportSelection,
    build_generate_args,
    build_send_args,
    delete_report,
    discover_reports,
    regenerate_report,
    send_current_report,
)
from desktop.task_records import load_task_run_history


class DesktopReportTests(unittest.TestCase):
    def test_discover_reports_lists_white_and_daily_bundles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reports_dir = root / "futures_report_system" / "reports"
            white_dir = reports_dir / "20260616" / "white"
            daily_dir = reports_dir / "20260615" / "daily"
            white_dir.mkdir(parents=True)
            daily_dir.mkdir(parents=True)
            (white_dir / "white.html").write_text("html", encoding="utf-8")
            (white_dir / "white.pdf").write_bytes(b"pdf")
            (daily_dir / "daily.html").write_text("html", encoding="utf-8")
            (daily_dir / "daily.pdf").write_bytes(b"pdf")

            reports = discover_reports(root)

            self.assertEqual([(item.trade_date, item.report_type) for item in reports], [
                ("20260616", "white"),
                ("20260615", "daily"),
            ])
            self.assertEqual(reports[0].label, "白盘")
            self.assertTrue(reports[0].html_path.exists())
            self.assertTrue(reports[0].pdf_path.exists())

    def test_build_generate_args_skips_data_update_and_uses_white_report(self):
        args = build_generate_args("20260616")

        self.assertEqual(args, [
            "auto_report_once.py",
            "--report-type",
            "white",
            "--date",
            "20260616",
            "--no-update",
            "--force",
        ])
        self.assertNotIn("--send", args)

    def test_discover_reports_lists_legacy_daily_files_in_date_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_dir = root / "futures_report_system" / "reports" / "20260612"
            legacy_dir.mkdir(parents=True)
            (legacy_dir / "daily.html").write_text("html", encoding="utf-8")
            (legacy_dir / "daily.pdf").write_bytes(b"pdf")

            reports = discover_reports(root)

            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0].trade_date, "20260612")
            self.assertEqual(reports[0].report_type, "daily")
            self.assertEqual(reports[0].directory, legacy_dir)

    def test_build_send_args_resends_existing_current_report_by_default(self):
        args = build_send_args(ReportSelection("20260616", "white"))

        self.assertEqual(args, [
            "send_report_email.py",
            "--report-type",
            "white",
            "--date",
            "20260616",
            "--force",
            "--resend",
        ])
        self.assertNotIn("--send", args)

    def test_build_send_args_includes_explicit_report_paths(self):
        selection = ReportSelection(
            "20260616",
            "white",
            html_path=Path("reports/20260616/white/report.html"),
            pdf_path=Path("reports/20260616/white/report.pdf"),
            md_path=Path("reports/20260616/white/report.md"),
        )

        args = build_send_args(selection)

        self.assertEqual(Path(args[args.index("--html-path") + 1]), selection.html_path)
        self.assertEqual(Path(args[args.index("--pdf-path") + 1]), selection.pdf_path)
        self.assertEqual(Path(args[args.index("--md-path") + 1]), selection.md_path)

    def test_send_current_report_uses_selected_report_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_dir = root / "futures_report_system" / "reports" / "20260611"
            legacy_dir.mkdir(parents=True)
            html_path = legacy_dir / "期货市场日报_20260611.html"
            pdf_path = legacy_dir / "期货市场日报_20260611.pdf"
            md_path = legacy_dir / "期货市场日报_20260611.md"
            html_path.write_text("html", encoding="utf-8")
            pdf_path.write_bytes(b"pdf")
            md_path.write_text("md", encoding="utf-8")

            report = discover_reports(root)[0]
            captured = {}

            def fake_runner(working_dir, script_path, args=None, timeout_seconds=0):
                captured["script"] = script_path.name
                captured["args"] = args
                return ActionResult(True, "sent", "runner output")

            result = send_current_report(root, report, runner=fake_runner)

            self.assertTrue(result.ok)
            self.assertEqual(captured["script"], "send_report_email.py")
            self.assertIn("--resend", captured["args"])
            self.assertEqual(Path(captured["args"][captured["args"].index("--html-path") + 1]), html_path)
            self.assertEqual(Path(captured["args"][captured["args"].index("--pdf-path") + 1]), pdf_path)
            self.assertEqual(Path(captured["args"][captured["args"].index("--md-path") + 1]), md_path)
            self.assertIn(str(html_path), result.output)
            self.assertIn(str(pdf_path), result.output)
            self.assertIn(str(md_path), result.output)

    def test_regenerate_report_records_structured_task_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            report_dir.mkdir()

            def fake_runner(working_dir, script_path, args=None, timeout_seconds=0):
                return ActionResult(True, "generated", "report ok")

            result = regenerate_report(root, "20260618", runner=fake_runner)

            self.assertTrue(result.ok)
            rows = load_task_run_history(root)
            self.assertEqual(rows[0]["task_type"], "report_generate")
            self.assertEqual(rows[0]["target_date"], "20260618")

    def test_send_current_report_records_structured_task_result(self):
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
            report = ReportSelection("20260618", "white", html_path, pdf_path, md_path)

            def fake_runner(working_dir, script_path, args=None, timeout_seconds=0):
                return ActionResult(True, "sent", "mail ok")

            result = send_current_report(root, report, runner=fake_runner)

            self.assertTrue(result.ok)
            rows = load_task_run_history(root)
            self.assertEqual(rows[0]["task_type"], "mail_send")
            self.assertEqual(rows[0]["detail"], "white")

    def test_send_current_report_blocks_missing_selected_attachments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system" / "reports" / "20260611"
            report_dir.mkdir(parents=True)
            html_path = report_dir / "期货市场日报_20260611.html"
            pdf_path = report_dir / "期货市场日报_20260611.pdf"
            md_path = report_dir / "期货市场日报_20260611.md"
            html_path.write_text("html", encoding="utf-8")
            pdf_path.write_bytes(b"pdf")
            report = ReportItem(
                trade_date="20260611",
                report_type="daily",
                label="日报",
                directory=report_dir,
                html_path=html_path,
                pdf_path=pdf_path,
                md_path=md_path,
                modified_at=None,
            )
            called = False

            def fake_runner(working_dir, script_path, args=None, timeout_seconds=0):
                nonlocal called
                called = True
                return ActionResult(True, "sent")

            result = send_current_report(root, report, runner=fake_runner)

            self.assertFalse(result.ok)
            self.assertFalse(called)
            self.assertIn("缺少 Markdown", result.message)

    def test_send_current_report_defaults_to_resend(self):
        captured = {}

        def fake_runner(working_dir, script_path, args=None, timeout_seconds=0):
            captured["script"] = script_path.name
            captured["args"] = args
            return ActionResult(True, "sent")

        send_current_report(
            Path("D:/AI期货数据工作台"),
            ReportSelection("20260616", "white"),
            runner=fake_runner,
        )

        self.assertEqual(captured["script"], "send_report_email.py")
        self.assertIn("--resend", captured["args"])

    def test_delete_report_removes_selected_attachments_and_keeps_other_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_dir = Path(temp_dir) / "futures_report_system" / "reports" / "20260616" / "white"
            report_dir.mkdir(parents=True)
            html_path = report_dir / "期货白盘_数据20260616.html"
            pdf_path = report_dir / "期货白盘_数据20260616.pdf"
            md_path = report_dir / "期货白盘_数据20260616.md"
            keep_path = report_dir / "notes.txt"
            html_path.write_text("html", encoding="utf-8")
            pdf_path.write_bytes(b"pdf")
            md_path.write_text("md", encoding="utf-8")
            keep_path.write_text("keep", encoding="utf-8")
            report = ReportItem(
                trade_date="20260616",
                report_type="white",
                label="白盘",
                directory=report_dir,
                html_path=html_path,
                pdf_path=pdf_path,
                md_path=md_path,
                modified_at=None,
            )

            result = delete_report(report)

            self.assertTrue(result.ok)
            self.assertFalse(html_path.exists())
            self.assertFalse(pdf_path.exists())
            self.assertFalse(md_path.exists())
            self.assertTrue(keep_path.exists())
            self.assertTrue(report_dir.exists())

    def test_delete_report_removes_empty_report_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_dir = Path(temp_dir) / "futures_report_system" / "reports" / "20260616" / "white"
            report_dir.mkdir(parents=True)
            html_path = report_dir / "期货白盘_数据20260616.html"
            pdf_path = report_dir / "期货白盘_数据20260616.pdf"
            md_path = report_dir / "期货白盘_数据20260616.md"
            html_path.write_text("html", encoding="utf-8")
            pdf_path.write_bytes(b"pdf")
            md_path.write_text("md", encoding="utf-8")
            report = ReportItem(
                trade_date="20260616",
                report_type="white",
                label="白盘",
                directory=report_dir,
                html_path=html_path,
                pdf_path=pdf_path,
                md_path=md_path,
                modified_at=None,
            )

            result = delete_report(report)

            self.assertTrue(result.ok)
            self.assertFalse(report_dir.exists())


if __name__ == "__main__":
    unittest.main()

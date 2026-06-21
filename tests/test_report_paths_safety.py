import tempfile
import unittest
from pathlib import Path

import sys

SYSTEM_DIR = Path(__file__).resolve().parents[1] / "services" / "report_system"
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from report_paths import latest_report_bundle, report_paths


class ReportPathSafetyTests(unittest.TestCase):
    def test_report_paths_use_date_and_type_specific_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)

            html_path, md_path, pdf_path = report_paths("20260618", "white", reports_dir=reports_dir)

            self.assertEqual(html_path.parent, reports_dir / "20260618" / "white")
            self.assertEqual(md_path.parent, reports_dir / "20260618" / "white")
            self.assertEqual(pdf_path.parent, reports_dir / "20260618" / "white")
            self.assertIn("20260618", html_path.name)
            self.assertIn("white", html_path.name)

    def test_latest_report_bundle_prefers_requested_type_over_newer_other_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            white_dir = reports_dir / "20260618" / "white"
            daily_dir = reports_dir / "20260618" / "daily"
            white_dir.mkdir(parents=True)
            daily_dir.mkdir(parents=True)
            for path in report_paths("20260618", "white", reports_dir=reports_dir):
                path.write_text("white", encoding="utf-8")
            for path in report_paths("20260618", "daily", reports_dir=reports_dir):
                path.write_text("daily", encoding="utf-8")

            bundle = latest_report_bundle("20260618", preferred_type="white", reports_dir=reports_dir)

            self.assertIsNotNone(bundle)
            self.assertEqual(bundle.report_type, "white")
            self.assertEqual(bundle.directory, white_dir)

    def test_latest_report_bundle_returns_none_when_date_has_no_reports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            (reports_dir / "20260617" / "white").mkdir(parents=True)
            (reports_dir / "20260617" / "white" / "white.html").write_text("old", encoding="utf-8")

            bundle = latest_report_bundle("20260618", preferred_type="white", reports_dir=reports_dir)

            self.assertIsNone(bundle)


if __name__ == "__main__":
    unittest.main()

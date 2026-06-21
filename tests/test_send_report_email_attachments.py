import tempfile
import unittest
from pathlib import Path

import sys

SYSTEM_DIR = Path(__file__).resolve().parents[1] / "services" / "report_system"
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from send_report_email import check_attachments, existing_selected_attachments, parse_attachment_types


class SendReportEmailAttachmentTests(unittest.TestCase):
    def test_parse_attachment_types_normalizes_values(self):
        self.assertEqual(parse_attachment_types("pdf, html, markdown"), ["pdf", "html", "md"])
        self.assertEqual(parse_attachment_types(""), ["pdf", "html", "md"])

    def test_check_attachments_allows_pdf_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf = root / "report_20260618.pdf"
            html = root / "report_20260618.html"
            md = root / "report_20260618.md"
            pdf.write_bytes(b"%PDF-1.4\nbody")

            size = check_attachments("20260618", pdf, html, md, 1024, attachment_types=["pdf"])

            self.assertEqual(size, pdf.stat().st_size)

    def test_existing_selected_attachments_returns_selected_existing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf = root / "report_20260618.pdf"
            html = root / "report_20260618.html"
            md = root / "report_20260618.md"
            pdf.write_bytes(b"pdf")
            html.write_text("<html></html>", encoding="utf-8")

            attachments = existing_selected_attachments(pdf, html, md, ["html"])

            self.assertEqual(attachments, [html])

    def test_check_attachments_blocks_missing_required_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf = root / "report_20260618.pdf"
            html = root / "report_20260618.html"
            md = root / "report_20260618.md"
            pdf.write_bytes(b"%PDF-1.4\nbody")
            html.write_text("<html></html>", encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                check_attachments("20260618", pdf, html, md, 1024)

    def test_check_attachments_blocks_wrong_report_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf = root / "report_20260617.pdf"
            html = root / "report_20260617.html"
            md = root / "report_20260617.md"
            pdf.write_bytes(b"%PDF-1.4\nbody")
            html.write_text("<html></html>", encoding="utf-8")
            md.write_text("markdown", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "expected 20260618"):
                check_attachments("20260618", pdf, html, md, 1024)

    def test_check_attachments_blocks_total_size_over_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf = root / "report_20260618.pdf"
            html = root / "report_20260618.html"
            md = root / "report_20260618.md"
            pdf.write_bytes(b"%PDF-1.4\nbody")
            html.write_text("<html>long</html>", encoding="utf-8")
            md.write_text("markdown", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Attachments too large"):
                check_attachments("20260618", pdf, html, md, 5)


if __name__ == "__main__":
    unittest.main()

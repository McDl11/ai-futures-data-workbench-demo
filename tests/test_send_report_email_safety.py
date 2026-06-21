import importlib
import logging
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import sys

SYSTEM_DIR = Path(__file__).resolve().parents[1] / "services" / "report_system"
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))


class SendReportEmailSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.report_dir = self.root / "futures_report_system"
        self.data_dir = self.root / "data"
        self.report_dir.mkdir()
        self.data_dir.mkdir()
        self.db_path = self.data_dir / "futures.db"
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("create table trade_cal (exchange text, cal_date text, is_open text)")
            conn.execute("insert into trade_cal values ('SHFE', '20260618', '1')")
            conn.execute("insert into trade_cal values ('SHFE', '20260619', '0')")
            conn.commit()
        self.env_path = self.report_dir / ".env"
        self.env_path.write_text(
            "\n".join(
                [
                    "EMAIL_SENDER=sender@example.com",
                    "EMAIL_PASSWORD=secret",
                    "SMTP_HOST=smtp.example.com",
                    "SMTP_PORT=465",
                    "SMTP_USE_SSL=true",
                    "REPORT_EMAIL_DRY_RUN=false",
                    "REPORT_EMAIL_BATCH_INTERVAL_SECONDS=0",
                    "REPORT_MAX_ATTACHMENT_SIZE=1048576",
                ]
            ),
            encoding="utf-8",
        )
        self.send_report_email, self.config = self._load_modules()

    def tearDown(self):
        self.temp.cleanup()

    def test_send_report_skips_non_trading_day_without_smtp(self):
        html, md, pdf = self._write_report_files("20260619")

        with patch.object(self.send_report_email, "send_message") as send_message:
            result = self.send_report_email.send_report(
                "20260619",
                recipients=["alice@example.com"],
                dry_run=False,
                html_path=html,
                md_path=md,
                pdf_path=pdf,
            )

        self.assertEqual(result["status"], "skipped_non_trading_day")
        send_message.assert_not_called()

    def test_dry_run_records_result_without_smtp(self):
        html, md, pdf = self._write_report_files("20260618")

        with patch.object(self.send_report_email, "send_message") as send_message:
            result = self.send_report_email.send_report(
                "20260618",
                recipients=["alice@example.com"],
                dry_run=True,
                force=False,
                report_type="white",
                html_path=html,
                md_path=md,
                pdf_path=pdf,
            )

        self.assertEqual(result["status"], "dry_run")
        send_message.assert_not_called()
        with closing(sqlite3.connect(self.db_path)) as conn:
            status = conn.execute("select status from report_send_history").fetchone()[0]
        self.assertEqual(status, "dry_run")

    def test_duplicate_real_send_is_skipped_without_smtp(self):
        html, md, pdf = self._write_report_files("20260618")
        recipients = ["alice@example.com"]
        self.send_report_email.record_send_history(
            "20260618",
            "white",
            recipients,
            [],
            self.send_report_email.SEND_STATUS_SENT,
            html_path=html,
            md_path=md,
            pdf_path=pdf,
        )

        with patch.object(self.send_report_email, "send_message") as send_message:
            result = self.send_report_email.send_report(
                "20260618",
                recipients=recipients,
                dry_run=False,
                force=False,
                report_type="white",
                html_path=html,
                md_path=md,
                pdf_path=pdf,
            )

        self.assertEqual(result["status"], "skipped_duplicate")
        send_message.assert_not_called()

    def test_resend_bypasses_duplicate_guard_and_calls_smtp_once(self):
        html, md, pdf = self._write_report_files("20260618")
        recipients = ["alice@example.com"]
        self.send_report_email.record_send_history(
            "20260618",
            "white",
            recipients,
            [],
            self.send_report_email.SEND_STATUS_SENT,
            html_path=html,
            md_path=md,
            pdf_path=pdf,
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                create unique index idx_report_send_history_success
                on report_send_history (trade_date, report_type, recipients_key, status)
                where status = 'sent'
                """
            )
            conn.execute(
                """
                create unique index idx_report_recipient_send_success
                on report_recipient_send_history (trade_date, report_type, recipient, status)
                where status = 'sent'
                """
            )
            conn.commit()

        with patch.object(self.send_report_email, "send_message", return_value=True) as send_message:
            result = self.send_report_email.send_report(
                "20260618",
                recipients=recipients,
                dry_run=False,
                force=False,
                report_type="white",
                resend=True,
                html_path=html,
                md_path=md,
                pdf_path=pdf,
            )

        self.assertEqual(result["status"], "sent")
        send_message.assert_called_once()

    def _write_report_files(self, trade_date: str):
        out_dir = self.report_dir / "reports" / trade_date / "white"
        out_dir.mkdir(parents=True, exist_ok=True)
        html = out_dir / f"report_{trade_date}.html"
        md = out_dir / f"report_{trade_date}.md"
        pdf = out_dir / f"report_{trade_date}.pdf"
        html.write_text("<html></html>", encoding="utf-8")
        md.write_text("markdown", encoding="utf-8")
        pdf.write_bytes(b"%PDF-1.4\nbody")
        return html, md, pdf

    def _load_modules(self):
        import config
        import send_report_email

        config.BASE_DIR = self.report_dir
        config.PROJECT_ROOT = self.root
        config.DATA_DIR = self.data_dir
        config.DB_PATH = self.db_path
        config.REPORTS_DIR = self.report_dir / "reports"
        config.LOGS_DIR = self.report_dir / "logs"
        config.BACKUP_DIR = self.root / "backup"

        import data_loader

        importlib.reload(data_loader)
        module = importlib.reload(send_report_email)
        module.DB_PATH = self.db_path
        module.BASE_DIR = self.report_dir
        logging.getLogger("report_email").handlers.clear()
        return module, config


if __name__ == "__main__":
    unittest.main()

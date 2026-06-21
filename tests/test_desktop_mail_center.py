import csv
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from desktop.actions import ActionResult
from desktop.mail_center import (
    MailAccountConfig,
    MailRecipient,
    MailSendRecord,
    add_mail_recipient,
    build_resend_args,
    build_send_selected_args,
    delete_mail_recipient,
    load_mail_account_config,
    load_mail_recipients,
    load_mail_send_records,
    resend_mail_record,
    save_mail_account_config,
    send_selected_report,
    update_mail_recipient,
)
from desktop.pages.mail_center import MailCenterPage
from desktop.state import collect_workspace_snapshot
from desktop.task_records import load_task_run_history


class DesktopMailCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_load_and_save_mail_account_config_masks_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            report_dir.mkdir()
            env_path = report_dir / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "EMAIL_SENDER=old@example.com",
                        "EMAIL_PASSWORD=old-secret",
                        "SMTP_HOST=smtp.old.com",
                        "SMTP_PORT=465",
                        "SMTP_USE_SSL=true",
                        "REPORT_CC=copy@example.com",
                        "REPORT_EMAIL_DRY_RUN=false",
                        "REPORT_EMAIL_BATCH_INTERVAL_SECONDS=20",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_mail_account_config(root)
            self.assertEqual(config.sender, "old@example.com")
            self.assertTrue(config.has_password)
            self.assertEqual(config.password, "")

            save_mail_account_config(
                root,
                MailAccountConfig(
                    sender="new@example.com",
                    password="new-secret",
                    host="smtp.qq.com",
                    port=465,
                    use_ssl=True,
                    cc="new-copy@example.com",
                    dry_run=False,
                    batch_interval_seconds=5,
                ),
            )
            saved = env_path.read_text(encoding="utf-8")
            self.assertIn("EMAIL_SENDER=new@example.com", saved)
            self.assertIn("EMAIL_PASSWORD=new-secret", saved)
            self.assertIn("SMTP_HOST=smtp.qq.com", saved)
            self.assertIn("REPORT_CC=new-copy@example.com", saved)
            self.assertIn("REPORT_EMAIL_BATCH_INTERVAL_SECONDS=5", saved)

    def test_save_mail_account_config_keeps_existing_password_when_blank(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            report_dir.mkdir()
            env_path = report_dir / ".env"
            env_path.write_text("EMAIL_PASSWORD=old-secret\n", encoding="utf-8")

            save_mail_account_config(
                root,
                MailAccountConfig(
                    sender="new@example.com",
                    password="",
                    host="smtp.qq.com",
                    port=465,
                    use_ssl=True,
                    cc="",
                    dry_run=False,
                    batch_interval_seconds=5,
                    has_password=True,
                ),
            )

            self.assertIn("EMAIL_PASSWORD=old-secret", env_path.read_text(encoding="utf-8"))

    def test_load_mail_recipients_reads_enabled_state_and_details(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            report_dir.mkdir()
            csv_path = report_dir / "recipients.csv"
            with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["email", "name", "enabled", "remark"])
                writer.writerow(["alice@example.com", "Alice", "true", "主收件人"])
                writer.writerow(["bob@example.com", "Bob", "false", "停用"])

            recipients = load_mail_recipients(root)

            self.assertEqual([item.email for item in recipients], ["alice@example.com", "bob@example.com"])
            self.assertTrue(recipients[0].enabled)
            self.assertFalse(recipients[1].enabled)
            self.assertEqual(recipients[0].name, "Alice")
            self.assertEqual(recipients[1].remark, "停用")

    def test_add_update_delete_mail_recipients_writes_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            add_mail_recipient(root, MailRecipient("alice@example.com", "Alice", True, "主收件人"))
            add_mail_recipient(root, MailRecipient("bob@example.com", "Bob", False, "停用"))
            update_mail_recipient(root, "bob@example.com", MailRecipient("bob@example.com", "Bobby", True, "恢复"))
            delete_mail_recipient(root, "alice@example.com")

            recipients = load_mail_recipients(root)
            self.assertEqual(len(recipients), 1)
            self.assertEqual(recipients[0].email, "bob@example.com")
            self.assertEqual(recipients[0].name, "Bobby")
            self.assertTrue(recipients[0].enabled)
            self.assertEqual(recipients[0].remark, "恢复")

    def test_load_mail_send_records_reads_recipient_records_and_failure_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            db_path = data_dir / "futures.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    create table report_send_history (
                        id integer primary key autoincrement,
                        trade_date text,
                        report_type text,
                        recipients text,
                        cc text,
                        status text,
                        sent_at text,
                        error text,
                        html_path text,
                        md_path text,
                        pdf_path text
                    )
                    """
                )
                conn.execute(
                    """
                    create table report_recipient_send_history (
                        id integer primary key autoincrement,
                        trade_date text,
                        report_type text,
                        recipient text,
                        cc text,
                        status text,
                        sent_at text,
                        error text,
                        html_path text,
                        md_path text,
                        pdf_path text
                    )
                    """
                )
                conn.execute(
                    """
                    insert into report_send_history
                    (trade_date, report_type, recipients, cc, status, sent_at, error, html_path, md_path, pdf_path)
                    values ('20260618', 'white', 'alice@example.com,bob@example.com', '', 'failed',
                            '2026-06-18 16:31:00', 'SMTP authentication failed', 'r.html', 'r.md', 'r.pdf')
                    """
                )
                conn.execute(
                    """
                    insert into report_recipient_send_history
                    (trade_date, report_type, recipient, cc, status, sent_at, error, html_path, md_path, pdf_path)
                    values ('20260618', 'white', 'alice@example.com', '', 'failed',
                            '2026-06-18 16:31:01', '', 'r.html', 'r.md', 'r.pdf')
                    """
                )
                conn.execute(
                    """
                    insert into report_recipient_send_history
                    (trade_date, report_type, recipient, cc, status, sent_at, error, html_path, md_path, pdf_path)
                    values ('20260618', 'white', 'bob@example.com', '', 'sent',
                            '2026-06-18 16:31:02', '', 'r.html', 'r.md', 'r.pdf')
                    """
                )
                conn.commit()
            finally:
                conn.close()

            records = load_mail_send_records(root)

            self.assertEqual(len(records), 2)
            failed = next(record for record in records if record.recipient == "alice@example.com")
            self.assertEqual(failed.status, "failed")
            self.assertEqual(failed.failure_reason, "SMTP authentication failed")
            self.assertEqual(records[0].scope, "recipient")

    def test_load_mail_send_records_fills_failure_reason_from_later_batch_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            db_path = data_dir / "futures.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    create table report_send_history (
                        id integer primary key autoincrement,
                        trade_date text,
                        report_type text,
                        recipients text,
                        cc text,
                        status text,
                        sent_at text,
                        error text,
                        html_path text,
                        md_path text,
                        pdf_path text
                    )
                    """
                )
                conn.execute(
                    """
                    create table report_recipient_send_history (
                        id integer primary key autoincrement,
                        trade_date text,
                        report_type text,
                        recipient text,
                        cc text,
                        status text,
                        sent_at text,
                        error text,
                        html_path text,
                        md_path text,
                        pdf_path text
                    )
                    """
                )
                conn.execute(
                    """
                    insert into report_recipient_send_history
                    (trade_date, report_type, recipient, cc, status, sent_at, error, html_path, md_path, pdf_path)
                    values ('20260618', 'white', 'alice@example.com', '', 'failed',
                            '2026-06-18 16:31:01', '', 'r.html', 'r.md', 'r.pdf')
                    """
                )
                conn.execute(
                    """
                    insert into report_send_history
                    (trade_date, report_type, recipients, cc, status, sent_at, error, html_path, md_path, pdf_path)
                    values ('20260618', 'white', 'alice@example.com', '', 'failed',
                            '2026-06-18 16:31:03', 'SMTP timeout', 'r.html', 'r.md', 'r.pdf')
                    """
                )
                conn.commit()
            finally:
                conn.close()

            records = load_mail_send_records(root)

            self.assertEqual(records[0].failure_reason, "SMTP timeout")

    def test_build_resend_args_targets_selected_recipient(self):
        record = MailSendRecord(
            id=7,
            scope="recipient",
            trade_date="20260618",
            report_type="white",
            recipient="alice@example.com",
            recipients="",
            cc="copy@example.com",
            status="failed",
            sent_at="2026-06-18 16:31:01",
            error="SMTP authentication failed",
            html_path=Path("r.html"),
            md_path=Path("r.md"),
            pdf_path=Path("r.pdf"),
        )

        args = build_resend_args(record)

        self.assertEqual(args[:5], ["send_report_email.py", "--report-type", "white", "--date", "20260618"])
        self.assertIn("--send", args)
        self.assertIn("--force", args)
        self.assertIn("--resend", args)
        self.assertIn("--to", args)
        self.assertIn("alice@example.com", args)
        self.assertIn("--cc", args)
        self.assertIn("copy@example.com", args)

    def test_build_send_selected_args_targets_recipients_and_attachment_types(self):
        args = build_send_selected_args(
            trade_date="20260618",
            report_type="white",
            recipients=["alice@example.com", "bob@example.com"],
            cc="copy@example.com",
            attachments=["pdf", "html"],
            resend=True,
        )

        self.assertEqual(args[:5], ["send_report_email.py", "--report-type", "white", "--date", "20260618"])
        self.assertIn("--to", args)
        self.assertIn("alice@example.com,bob@example.com", args)
        self.assertIn("--attachments", args)
        self.assertIn("pdf,html", args)
        self.assertIn("--resend", args)

    def test_send_selected_report_runs_send_script(self):
        captured = {}

        def fake_runner(working_dir, script_path, args=None, timeout_seconds=0, env=None):
            captured["working_dir"] = working_dir
            captured["script"] = script_path.name
            captured["args"] = args
            captured["env"] = env
            return ActionResult(True, "sent", "ok")

        result = send_selected_report(
            Path("D:/AI期货数据工作台"),
            trade_date="20260618",
            report_type="white",
            recipients=["alice@example.com"],
            attachments=["pdf"],
            cc="",
            confirmed=True,
            runner=fake_runner,
        )

        self.assertTrue(result.ok)
        self.assertEqual(captured["script"], "send_report_email.py")
        self.assertIn("--attachments", captured["args"])
        self.assertIn("pdf", captured["args"])
        self.assertEqual(captured["env"]["PYTHONIOENCODING"], "utf-8")

    def test_send_selected_report_records_structured_task_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "futures_report_system").mkdir()

            def fake_runner(working_dir, script_path, args=None, timeout_seconds=0, env=None):
                return ActionResult(True, "sent", "ok")

            result = send_selected_report(
                root,
                trade_date="20260618",
                report_type="white",
                recipients=["alice@example.com"],
                attachments=["pdf"],
                cc="",
                confirmed=True,
                runner=fake_runner,
            )

            self.assertTrue(result.ok)
            rows = load_task_run_history(root)
        self.assertEqual(rows[0]["task_type"], "mail_send")
        self.assertEqual(rows[0]["target_date"], "20260618")

    def test_send_selected_report_requires_explicit_confirmation(self):
        called = False

        def fake_runner(working_dir, script_path, args=None, timeout_seconds=0, env=None):
            nonlocal called
            called = True
            return ActionResult(True, "sent", "ok")

        result = send_selected_report(
            Path("D:/AI期货数据工作台"),
            trade_date="20260618",
            report_type="white",
            recipients=["alice@example.com"],
            attachments=["pdf"],
            cc="",
            confirmed=False,
            runner=fake_runner,
        )

        self.assertFalse(result.ok)
        self.assertFalse(called)
        self.assertIn("确认", result.message)

    def test_resend_mail_record_runs_send_script_with_utf8_environment(self):
        captured = {}
        record = MailSendRecord(
            id=7,
            scope="recipient",
            trade_date="20260618",
            report_type="white",
            recipient="alice@example.com",
            recipients="",
            cc="",
            status="failed",
            sent_at="2026-06-18 16:31:01",
            error="",
            html_path=None,
            md_path=None,
            pdf_path=None,
        )

        def fake_runner(working_dir, script_path, args=None, timeout_seconds=0, env=None):
            captured["working_dir"] = working_dir
            captured["script"] = script_path.name
            captured["args"] = args
            captured["env"] = env
            return ActionResult(True, "resent", "ok")

        result = resend_mail_record(Path("D:/AI期货数据工作台"), record, runner=fake_runner)

        self.assertTrue(result.ok)
        self.assertEqual(captured["working_dir"], Path("D:/AI期货数据工作台") / "services" / "report_system")
        self.assertEqual(captured["script"], "send_report_email.py")
        self.assertIn("--resend", captured["args"])
        self.assertEqual(captured["env"]["PYTHONIOENCODING"], "utf-8")

    def test_resend_mail_record_records_structured_task_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "futures_report_system").mkdir()
            record = MailSendRecord(
                id=7,
                scope="recipient",
                trade_date="20260618",
                report_type="white",
                recipient="alice@example.com",
                recipients="",
                cc="",
                status="failed",
                sent_at="2026-06-18 16:31:01",
                error="",
                html_path=None,
                md_path=None,
                pdf_path=None,
            )

            def fake_runner(working_dir, script_path, args=None, timeout_seconds=0, env=None):
                return ActionResult(True, "resent", "ok")

            result = resend_mail_record(root, record, runner=fake_runner)

            self.assertTrue(result.ok)
            rows = load_task_run_history(root)
            self.assertEqual(rows[0]["task_type"], "mail_send")
            self.assertIn("重发", rows[0]["task_name"])

    def test_mail_center_send_controls_only_offer_white_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "futures_report_system").mkdir()

            page = MailCenterPage(collect_workspace_snapshot(root))
            labels = [label.text() for label in page.findChildren(QLabel)]

            self.assertIn("报告", labels)
            self.assertIn("白盘", labels)
            self.assertNotIn("日报", labels)


if __name__ == "__main__":
    unittest.main()

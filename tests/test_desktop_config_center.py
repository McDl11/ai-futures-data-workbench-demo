import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from desktop.config_center import (
    CommonConfig,
    load_common_config,
    save_common_config,
)
from desktop.pages.config_center import ManualSpinBox
from desktop.pages.config_center import ConfigCenterPage
from desktop.pages.mail_center import MailCenterPage
from desktop.state import collect_workspace_snapshot


class DesktopConfigCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_load_common_config_reads_mail_retention_path_and_ai_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            downloader_dir = root / "tushare down"
            report_dir.mkdir()
            downloader_dir.mkdir()
            (report_dir / ".env").write_text(
                "\n".join(
                    [
                        "EMAIL_SENDER=sender@example.com",
                        "EMAIL_PASSWORD=secret",
                        "SMTP_HOST=smtp.example.com",
                        "SMTP_PORT=587",
                        "SMTP_USE_SSL=false",
                        "REPORT_CC=cc@example.com",
                        "REPORT_EMAIL_DRY_RUN=false",
                        "REPORT_EMAIL_BATCH_INTERVAL_SECONDS=8",
                        "REPORT_MAX_ATTACHMENT_SIZE=123456",
                        "FUTURES_DATA_DIR=my-data",
                        "BACKUP_DIR=my-backup",
                        "DB_BACKUP_KEEP_DAYS=9",
                        "LOG_KEEP_DAYS=10",
                        "REPORT_KEEP_DAYS=11",
                        "AI_ANALYSIS_ENABLED=true",
                        "AI_ASSISTANT_USE_COMMERCIAL_AI=true",
                        "DEEPSEEK_API_KEY=deep-secret",
                        "DEEPSEEK_API_BASE=https://api.example.com",
                        "DEEPSEEK_MODEL=deepseek-test",
                        "AI_ANALYSIS_TIMEOUT_SECONDS=12",
                        "AI_ANALYSIS_MAX_TOKENS=345",
                    ]
                ),
                encoding="utf-8",
            )
            (downloader_dir / ".env").write_text(
                "TUSHARE_TOKEN=tushare-secret\nTUSHARE_HTTP_URL=http://proxy.example.com\n",
                encoding="utf-8",
            )

            config = load_common_config(root)

            self.assertEqual(config.sender, "sender@example.com")
            self.assertTrue(config.has_email_password)
            self.assertEqual(config.email_password, "")
            self.assertEqual(config.smtp_host, "smtp.example.com")
            self.assertEqual(config.smtp_port, 587)
            self.assertFalse(config.smtp_use_ssl)
            self.assertFalse(config.report_email_dry_run)
            self.assertEqual(config.report_max_attachment_size, 123456)
            self.assertEqual(config.futures_data_dir, "my-data")
            self.assertEqual(config.backup_dir, "my-backup")
            self.assertEqual(config.report_keep_days, 11)
            self.assertTrue(config.ai_analysis_enabled)
            self.assertTrue(config.ai_assistant_use_commercial_ai)
            self.assertTrue(config.has_deepseek_api_key)
            self.assertEqual(config.deepseek_api_key, "")
            self.assertEqual(config.deepseek_model, "deepseek-test")
            self.assertTrue(config.has_tushare_token)
            self.assertEqual(config.tushare_token, "")
            self.assertEqual(config.tushare_http_url, "http://proxy.example.com")

    def test_save_common_config_keeps_existing_secrets_when_blank_and_omits_empty_tushare_http_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            downloader_dir = root / "tushare down"
            report_dir.mkdir()
            downloader_dir.mkdir()
            env_path = report_dir / ".env"
            downloader_env_path = downloader_dir / ".env"
            env_path.write_text(
                "EMAIL_PASSWORD=old-mail-secret\nDEEPSEEK_API_KEY=old-ai-secret\n",
                encoding="utf-8",
            )
            downloader_env_path.write_text(
                "TUSHARE_TOKEN=old-tushare-secret\nTUSHARE_HTTP_URL=http://old-proxy.example.com\n",
                encoding="utf-8",
            )

            result = save_common_config(
                root,
                CommonConfig(
                    sender="new@example.com",
                    email_password="",
                    smtp_host="smtp.qq.com",
                    smtp_port=465,
                    smtp_use_ssl=True,
                    report_cc="",
                    report_email_dry_run=True,
                    report_email_batch_interval_seconds=3,
                    report_max_attachment_size=20971520,
                    futures_data_dir="data",
                    backup_dir="backup",
                    db_backup_keep_days=30,
                    log_keep_days=60,
                    report_keep_days=180,
                    ai_analysis_enabled=False,
                    ai_assistant_use_commercial_ai=True,
                    deepseek_api_key="",
                    deepseek_api_base="https://api.deepseek.com",
                    deepseek_model="deepseek-v4-flash",
                    ai_analysis_timeout_seconds=60,
                    ai_analysis_max_tokens=900,
                    tushare_token="",
                    tushare_http_url="",
                    has_email_password=True,
                    has_deepseek_api_key=True,
                    has_tushare_token=True,
                ),
            )

            self.assertTrue(result.ok)
            saved = env_path.read_text(encoding="utf-8")
            self.assertIn("EMAIL_SENDER=new@example.com", saved)
            self.assertIn("EMAIL_PASSWORD=old-mail-secret", saved)
            self.assertIn("DEEPSEEK_API_KEY=old-ai-secret", saved)
            self.assertIn("AI_ASSISTANT_USE_COMMERCIAL_AI=true", saved)
            self.assertIn("REPORT_EMAIL_BATCH_INTERVAL_SECONDS=3", saved)
            downloader_saved = downloader_env_path.read_text(encoding="utf-8")
            self.assertIn("TUSHARE_TOKEN=old-tushare-secret", downloader_saved)
            self.assertNotIn("TUSHARE_HTTP_URL=", downloader_saved)

    def test_config_center_contains_common_config_sections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "futures_report_system").mkdir()

            page = ConfigCenterPage(collect_workspace_snapshot(root))
            labels = [label.text() for label in page.findChildren(QLabel)]

            self.assertIn("邮件发送", labels)
            self.assertIn("数据源接入", labels)
            self.assertIn("保留策略", labels)
            self.assertIn("路径配置", labels)
            self.assertIn("AI 分析", labels)

    def test_config_center_no_longer_contains_file_status_block(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            downloader_dir = root / "tushare down"
            report_dir.mkdir()
            downloader_dir.mkdir()
            (report_dir / ".env").write_text("EMAIL_SENDER=a@example.com\n", encoding="utf-8")
            (downloader_dir / ".env").write_text("TUSHARE_TOKEN=test\n", encoding="utf-8")

            page = ConfigCenterPage(collect_workspace_snapshot(root))
            labels = [label.text() for label in page.findChildren(QLabel)]

            self.assertNotIn("配置与依赖文件状态", labels)
            self.assertNotIn("报告系统 .env", labels)
            self.assertNotIn("下载器 .env", labels)

    def test_mail_center_no_longer_contains_sender_account_section(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "futures_report_system").mkdir()

            page = MailCenterPage(collect_workspace_snapshot(root))
            labels = [label.text() for label in page.findChildren(QLabel)]

            self.assertNotIn("发件账号", labels)

    def test_manual_spin_box_ignores_mouse_wheel(self):
        box = ManualSpinBox()
        box.setRange(0, 100)
        box.setValue(20)
        event = type(
            "WheelEvent",
            (),
            {
                "ignore": lambda self: setattr(self, "ignored", True),
            },
        )()

        box.wheelEvent(event)

        self.assertEqual(box.value(), 20)
        self.assertTrue(event.ignored)


if __name__ == "__main__":
    unittest.main()

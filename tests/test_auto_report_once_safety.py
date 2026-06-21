import importlib
import logging
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import sys

SYSTEM_DIR = Path(__file__).resolve().parents[1] / "services" / "report_system"
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))


class AutoReportOnceSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.report_dir = self.root / "futures_report_system"
        self.data_dir = self.root / "data"
        self.tushare_dir = self.root / "tushare down"
        self.report_dir.mkdir()
        self.data_dir.mkdir()
        self.tushare_dir.mkdir()
        self.db_path = self.data_dir / "futures.db"
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("create table trade_cal (exchange text, cal_date text, is_open text)")
            conn.execute("create table fut_daily (trade_date text)")
            conn.execute("insert into trade_cal values ('SHFE', '20260618', '1')")
            conn.execute("insert into trade_cal values ('SHFE', '20260619', '0')")
            conn.execute("insert into fut_daily values ('20260618')")
            conn.commit()
        self.auto_report_once = self._load_module()

    def tearDown(self):
        self.temp.cleanup()

    def test_run_once_skips_non_trading_day_before_generating_or_sending(self):
        args = self._args(date="20260619", force=False)

        with patch.object(self.auto_report_once, "build_report") as build_report, patch.object(self.auto_report_once, "send_report") as send_report:
            result = self.auto_report_once.run_once(args)

        self.assertEqual(result["status"], "skipped_non_trading_day")
        build_report.assert_not_called()
        send_report.assert_not_called()

    def test_run_once_passes_dry_run_when_send_flag_is_false(self):
        args = self._args(date="20260618", send=False, force=False)
        html = self.report_dir / "reports" / "20260618" / "white" / "report_20260618.html"
        md = self.report_dir / "reports" / "20260618" / "white" / "report_20260618.md"
        pdf = self.report_dir / "reports" / "20260618" / "white" / "report_20260618.pdf"

        with patch.object(self.auto_report_once, "build_report", return_value={"trade_date": "20260618"}) as build_report, patch.object(
            self.auto_report_once,
            "write_report",
            return_value=(html, md, pdf),
        ), patch.object(self.auto_report_once, "send_report", return_value={"status": "dry_run"}) as send_report:
            result = self.auto_report_once.run_once(args)

        self.assertEqual(result["status"], "dry_run")
        build_report.assert_called_once_with("20260618", "white")
        self.assertTrue(send_report.call_args.kwargs["dry_run"])

    def test_run_once_passes_real_send_when_send_flag_is_true(self):
        args = self._args(date="20260618", send=True, force=False)
        html = self.report_dir / "reports" / "20260618" / "white" / "report_20260618.html"
        md = self.report_dir / "reports" / "20260618" / "white" / "report_20260618.md"
        pdf = self.report_dir / "reports" / "20260618" / "white" / "report_20260618.pdf"

        with patch.object(self.auto_report_once, "build_report", return_value={"trade_date": "20260618"}), patch.object(
            self.auto_report_once,
            "write_report",
            return_value=(html, md, pdf),
        ), patch.object(self.auto_report_once, "send_report", return_value={"status": "sent"}) as send_report:
            result = self.auto_report_once.run_once(args)

        self.assertEqual(result["status"], "sent")
        self.assertFalse(send_report.call_args.kwargs["dry_run"])

    def _args(self, **overrides):
        values = {
            "report_type": "white",
            "date": "20260618",
            "to": "",
            "cc": "",
            "send": False,
            "force": False,
            "no_update": True,
            "allow_latest": False,
            "retries": 1,
            "retry_interval": 0,
            "resend": False,
        }
        values.update(overrides)
        return Namespace(**values)

    def _load_module(self):
        import config
        import auto_report_once

        config.BASE_DIR = self.report_dir
        config.PROJECT_ROOT = self.root
        config.DATA_DIR = self.data_dir
        config.DB_PATH = self.db_path
        config.REPORTS_DIR = self.report_dir / "reports"
        config.LOGS_DIR = self.report_dir / "logs"
        config.BACKUP_DIR = self.root / "backup"

        import data_loader

        importlib.reload(data_loader)
        module = importlib.reload(auto_report_once)
        module.DB_PATH = self.db_path
        module.PROJECT_ROOT = self.root
        module.TUSHARE_DIR = self.tushare_dir
        module.DAILY_UPDATE = self.tushare_dir / "daily_update.py"
        logging.getLogger("auto_report").handlers.clear()
        return module


if __name__ == "__main__":
    unittest.main()

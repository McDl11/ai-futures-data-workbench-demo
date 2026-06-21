import sqlite3
import tempfile
import unittest
from pathlib import Path

from desktop.actions import ActionResult
from desktop.data_center import (
    CoreTableSpec,
    CoreTableStatus,
    collect_core_table_statuses,
    find_recent_gap_range,
    plan_data_update_range,
    run_data_gap_repair,
    run_data_quick_update,
    run_data_update,
)
from desktop.task_records import load_task_run_history


class DesktopDataCenterTests(unittest.TestCase):
    def test_collect_core_table_status_reads_rows_latest_date_and_gaps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "futures.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("create table trade_cal (exchange text, cal_date text, is_open text)")
                conn.execute("create table fut_daily (ts_code text, trade_date text)")
                conn.executemany(
                    "insert into trade_cal values ('SHFE', ?, '1')",
                    [("20260611",), ("20260612",), ("20260615",)],
                )
                conn.executemany(
                    "insert into fut_daily values (?, ?)",
                    [("A.SHF", "20260611"), ("A.SHF", "20260615")],
                )
                conn.commit()
            finally:
                conn.close()

            statuses = collect_core_table_statuses(
                db_path,
                specs=[CoreTableSpec("fut_daily", "日线行情", "trade_date", True)],
            )

            self.assertEqual(len(statuses), 1)
            self.assertEqual(statuses[0].row_count, 2)
            self.assertEqual(statuses[0].latest_date, "20260615")
            self.assertEqual(statuses[0].gap_count, 1)
            self.assertIn("2026-06-12", statuses[0].gap_summary)

    def test_collect_core_table_status_ignores_future_trade_calendar_dates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "futures.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("create table trade_cal (exchange text, cal_date text, is_open text)")
                conn.execute("create table fut_daily (ts_code text, trade_date text)")
                conn.executemany(
                    "insert into trade_cal values ('SHFE', ?, '1')",
                    [("20260618",), ("20260701",)],
                )
                conn.execute("insert into fut_daily values ('A.SHF', '20260618')")
                conn.commit()
            finally:
                conn.close()

            statuses = collect_core_table_statuses(
                db_path,
                specs=[CoreTableSpec("fut_daily", "日线行情", "trade_date", True)],
                today="20260620",
            )

            self.assertEqual(statuses[0].gap_count, 0)
            self.assertEqual(statuses[0].gap_summary, "无缺口")

    def test_collect_core_table_status_reports_missing_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "futures.db"
            conn = sqlite3.connect(db_path)
            conn.close()

            statuses = collect_core_table_statuses(
                db_path,
                specs=[CoreTableSpec("fut_daily", "日线行情", "trade_date", True)],
            )

            self.assertFalse(statuses[0].exists)
            self.assertEqual(statuses[0].row_count, 0)
            self.assertEqual(statuses[0].gap_summary, "表不存在")

    def test_collect_core_table_status_checks_recent_gaps_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "futures.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("create table trade_cal (exchange text, cal_date text, is_open text)")
                conn.execute("create table fut_daily (ts_code text, trade_date text)")
                dates = [f"202601{day:02d}" for day in range(1, 32)] + [f"202602{day:02d}" for day in range(1, 32)]
                conn.executemany("insert into trade_cal values ('SHFE', ?, '1')", [(date,) for date in dates])
                actual = [date for date in dates if date not in {"20260102"}]
                conn.executemany("insert into fut_daily values ('A.SHF', ?)", [(date,) for date in actual])
                conn.commit()
            finally:
                conn.close()

            statuses = collect_core_table_statuses(
                db_path,
                specs=[CoreTableSpec("fut_daily", "日线行情", "trade_date", True)],
            )

            self.assertEqual(statuses[0].gap_count, 0)
            self.assertEqual(statuses[0].gap_summary, "无缺口")

    def test_run_data_update_invokes_daily_update_now(self):
        captured = {}

        def fake_runner(working_dir, script_path, args=None, timeout_seconds=0, env=None):
            captured["working_dir"] = working_dir
            captured["script"] = script_path.name
            captured["args"] = args
            captured["timeout_seconds"] = timeout_seconds
            captured["env"] = env
            return ActionResult(True, "ok", "updated")

        result = run_data_update(Path("D:/AI期货数据工作台"), runner=fake_runner)

        self.assertTrue(result.ok)
        self.assertEqual(captured["working_dir"], Path("D:/AI期货数据工作台") / "services" / "data_downloader")
        self.assertEqual(captured["script"], "daily_update.py")
        self.assertEqual(captured["args"][0], "--now")
        self.assertEqual(captured["env"]["PYTHONIOENCODING"], "utf-8")
        self.assertGreaterEqual(captured["timeout_seconds"], 1200)

    def test_run_data_update_records_structured_task_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "tushare down").mkdir()

            def fake_runner(working_dir, script_path, args=None, timeout_seconds=0, env=None):
                return ActionResult(True, "updated", "rows=10")

            result = run_data_update(root, runner=fake_runner, today="20260620")

            self.assertTrue(result.ok)
            rows = load_task_run_history(root)
            self.assertEqual(rows[0]["task_type"], "data_update")
            self.assertEqual(rows[0]["status"], "success")

    def test_plan_data_update_range_uses_latest_open_day_when_yesterday_is_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "futures.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("create table trade_cal (exchange text, cal_date text, is_open text)")
                conn.executemany(
                    "insert into trade_cal values ('SHFE', ?, ?)",
                    [
                        ("20260616", "1"),
                        ("20260617", "1"),
                        ("20260618", "1"),
                        ("20260619", "0"),
                    ],
                )
                conn.commit()
            finally:
                conn.close()

            start_date, end_date = plan_data_update_range(db_path, today="20260620")

            self.assertEqual(start_date, "20260611")
            self.assertEqual(end_date, "20260618")

    def test_run_data_update_uses_planned_open_day_range_and_utf8_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "tushare down").mkdir()
            data_dir = root / "data"
            data_dir.mkdir()
            db_path = data_dir / "futures.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("create table trade_cal (exchange text, cal_date text, is_open text)")
                conn.executemany(
                    "insert into trade_cal values ('SHFE', ?, ?)",
                    [("20260618", "1"), ("20260619", "0")],
                )
                conn.commit()
            finally:
                conn.close()
            captured = {}

            def fake_runner(working_dir, script_path, args=None, timeout_seconds=0, env=None):
                captured["args"] = args
                captured["env"] = env
                return ActionResult(True, "ok", "中文输出")

            result = run_data_update(root, runner=fake_runner, today="20260620")

            self.assertTrue(result.ok)
            self.assertEqual(captured["args"], ["--now", "--start-date", "20260611", "--end-date", "20260618"])
            self.assertEqual(captured["env"]["PYTHONIOENCODING"], "utf-8")
            self.assertEqual(captured["env"]["PYTHONUTF8"], "1")

    def test_run_data_quick_update_uses_latest_open_day_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "tushare down").mkdir()
            data_dir = root / "data"
            data_dir.mkdir()
            db_path = data_dir / "futures.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("create table trade_cal (exchange text, cal_date text, is_open text)")
                conn.executemany(
                    "insert into trade_cal values ('SHFE', ?, ?)",
                    [("20260618", "1"), ("20260619", "0")],
                )
                conn.commit()
            finally:
                conn.close()
            captured = {}

            def fake_runner(working_dir, script_path, args=None, timeout_seconds=0, env=None):
                captured["args"] = args
                captured["env"] = env
                return ActionResult(True, "ok", "quick updated")

            result = run_data_quick_update(root, runner=fake_runner, today="20260620")

            self.assertTrue(result.ok)
            self.assertEqual(captured["args"], ["--now", "--start-date", "20260618", "--end-date", "20260618"])
            self.assertEqual(captured["env"]["PYTHONIOENCODING"], "utf-8")

    def test_find_recent_gap_range_returns_min_and_max_missing_dates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "futures.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("create table trade_cal (exchange text, cal_date text, is_open text)")
                conn.execute("create table fut_daily (ts_code text, trade_date text)")
                conn.execute("create table fut_holding (ts_code text, trade_date text)")
                conn.executemany(
                    "insert into trade_cal values ('SHFE', ?, '1')",
                    [("20260616",), ("20260617",), ("20260618",)],
                )
                conn.executemany("insert into fut_daily values ('A.SHF', ?)", [("20260616",)])
                conn.executemany("insert into fut_holding values ('A.SHF', ?)", [("20260616",), ("20260618",)])
                conn.commit()
            finally:
                conn.close()

            gap_range = find_recent_gap_range(
                db_path,
                specs=[
                    CoreTableSpec("fut_daily", "日线行情", "trade_date", True),
                    CoreTableSpec("fut_holding", "持仓排名", "trade_date", True),
                ],
            )

            self.assertEqual(gap_range, ("20260617", "20260618"))

    def test_run_data_gap_repair_uses_gap_range(self):
        captured = {}

        def fake_runner(working_dir, script_path, args=None, timeout_seconds=0, env=None):
            captured["args"] = args
            captured["env"] = env
            return ActionResult(True, "ok", "repaired")

        result = run_data_gap_repair(
            Path("D:/AI期货数据工作台"),
            ("20260617", "20260618"),
            runner=fake_runner,
        )

        self.assertTrue(result.ok)
        self.assertEqual(captured["args"], ["--now", "--start-date", "20260617", "--end-date", "20260618"])
        self.assertEqual(captured["env"]["PYTHONIOENCODING"], "utf-8")


if __name__ == "__main__":
    unittest.main()

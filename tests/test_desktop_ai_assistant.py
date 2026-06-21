import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from desktop.ai_assistant import answer_question


class DesktopAiAssistantTests(unittest.TestCase):
    def test_answer_question_answers_trading_day_directly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "futures.db"
            db_path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("create table trade_cal (exchange text, cal_date text, is_open text)")
                conn.executemany(
                    "insert into trade_cal values ('SHFE', ?, ?)",
                    [("20260620", "0"), ("20260619", "1")],
                )
                conn.commit()

            with patch("desktop.ai_assistant.datetime") as mocked_datetime:
                mocked_datetime.now.return_value.strftime.return_value = "20260620"
                answer = answer_question(root, "今天是不是交易日？")

            self.assertIn("2026-06-20", answer.text)
            self.assertIn("不是交易日", answer.text)
            self.assertNotIn("任务记录", answer.text)
            self.assertNotIn("报告记录", answer.text)
            self.assertNotIn("邮件记录", answer.text)

    def test_answer_question_answers_next_trading_day_from_calendar(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            report_dir.mkdir()
            (report_dir / ".env").write_text(
                "AI_ASSISTANT_USE_COMMERCIAL_AI=true\nDEEPSEEK_API_KEY=secret\n",
                encoding="utf-8",
            )
            db_path = root / "data" / "futures.db"
            db_path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("create table trade_cal (exchange text, cal_date text, is_open text)")
                conn.executemany(
                    "insert into trade_cal values ('SHFE', ?, ?)",
                    [("20260620", "0"), ("20260621", "0"), ("20260622", "1")],
                )
                conn.commit()

            with patch("desktop.ai_assistant.call_deepseek_assistant") as call, patch("desktop.ai_assistant.datetime") as mocked_datetime:
                mocked_datetime.now.return_value.strftime.return_value = "20260620"
                answer = answer_question(root, "下一个交易日是哪天")

            call.assert_not_called()
            self.assertIn("下一个交易日", answer.text)
            self.assertIn("2026-06-22", answer.text)
            self.assertNotIn("未提供", answer.text)

    def test_answer_question_answers_product_history_table_from_dictionary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            report_dir.mkdir()
            (report_dir / ".env").write_text(
                "AI_ASSISTANT_USE_COMMERCIAL_AI=true\nDEEPSEEK_API_KEY=secret\n",
                encoding="utf-8",
            )

            with patch("desktop.ai_assistant.call_deepseek_assistant") as call:
                answer = answer_question(root, "鸡蛋历史行情在哪个表查？")

            call.assert_not_called()
            self.assertIn("鸡蛋", answer.text)
            self.assertIn("JD", answer.text)
            self.assertIn("fut_daily", answer.text)
            self.assertIn("trade_date", answer.text)
            self.assertIn("ts_code", answer.text)

    def test_answer_question_answers_known_table_from_dictionary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            report_dir.mkdir()
            (report_dir / ".env").write_text(
                "AI_ASSISTANT_USE_COMMERCIAL_AI=true\nDEEPSEEK_API_KEY=secret\n",
                encoding="utf-8",
            )

            with patch("desktop.ai_assistant.call_deepseek_assistant") as call:
                answer = answer_question(root, "fut_daily 是干什么的？")

            call.assert_not_called()
            self.assertIn("fut_daily", answer.text)
            self.assertIn("期货日线行情", answer.text)
            self.assertIn("查某个品种历史行情时", answer.text)

    def test_answer_question_does_not_create_database_when_reading_empty_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            answer = answer_question(root, "帮我发送当前报告")

            self.assertFalse((root / "data" / "futures.db").exists())
            self.assertIn("只读", answer.text)
            self.assertIn("不会发送", answer.text)

    def test_answer_question_summarizes_recent_task_failures(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "futures.db"
            db_path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """
                    create table task_run_history (
                        id integer primary key autoincrement,
                        task_type text,
                        task_name text,
                        status text,
                        target_date text,
                        detail text,
                        started_at text,
                        finished_at text,
                        duration_seconds real,
                        output text,
                        error text
                    )
                    """
                )
                conn.execute(
                    """
                    insert into task_run_history (
                        task_type, task_name, status, target_date,
                        detail, finished_at, output, error
                    )
                    values ('data_update', '数据更新', 'failed', '20260618',
                            '20260611~20260618', '2026-06-20 12:30:00', '', 'token expired')
                    """
                )
                conn.commit()

            answer = answer_question(root, "最近为什么失败？")

            self.assertIn("数据更新", answer.text)
            self.assertIn("20260618", answer.text)
            self.assertIn("token expired", answer.text)

    def test_answer_question_summarizes_report_quality_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "futures.db"
            db_path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """
                    create table report_generation_history (
                        id integer primary key autoincrement,
                        trade_date text,
                        report_type text,
                        generation_status text,
                        html_path text,
                        pdf_path text,
                        md_path text,
                        report_dir text,
                        quality_status text,
                        quality_detail text,
                        generated_at text,
                        recorded_at text,
                        output text,
                        error text
                    )
                    """
                )
                conn.execute(
                    """
                    insert into report_generation_history (
                        trade_date, report_type, generation_status,
                        html_path, pdf_path, md_path, report_dir,
                        quality_status, quality_detail, generated_at, recorded_at, output, error
                    )
                    values ('20260618', 'white', 'success',
                            'a.html', 'a.pdf', 'a.md', 'reports/20260618/white',
                            'failed', '缺少文件：PDF', '2026-06-20 12:40:00',
                            '2026-06-20 12:40:01', '', '')
                    """
                )
                conn.commit()

            answer = answer_question(root, "报告质检怎么样？")

            self.assertIn("20260618", answer.text)
            self.assertIn("white", answer.text)
            self.assertIn("质检", answer.text)
            self.assertIn("缺少文件：PDF", answer.text)

    def test_answer_question_summarizes_mail_failure_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "futures.db"
            db_path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """
                    create table report_send_history (
                        id integer primary key autoincrement,
                        trade_date text,
                        report_type text,
                        recipients_key text,
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
                    insert into report_send_history (
                        trade_date, report_type, recipients, status, sent_at, error
                    )
                    values ('20260618', 'white', 'a@example.com',
                            'failed', '2026-06-20 12:50:00', 'SMTP auth failed')
                    """
                )
                conn.commit()

            answer = answer_question(root, "邮件发送失败原因是什么？")

            self.assertIn("邮件", answer.text)
            self.assertIn("20260618", answer.text)
            self.assertIn("SMTP auth failed", answer.text)

    def test_answer_question_only_answers_matching_mail_failure_topic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "futures.db"
            db_path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """
                    create table task_run_history (
                        id integer primary key autoincrement,
                        task_type text,
                        task_name text,
                        status text,
                        target_date text,
                        detail text,
                        started_at text,
                        finished_at text,
                        duration_seconds real,
                        output text,
                        error text
                    )
                    """
                )
                conn.execute(
                    """
                    create table report_send_history (
                        id integer primary key autoincrement,
                        trade_date text,
                        report_type text,
                        recipients_key text,
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
                    insert into task_run_history (
                        task_type, task_name, status, target_date, finished_at, error
                    )
                    values ('data_update', '数据更新', 'failed', '20260618',
                            '2026-06-20 12:00:00', 'token expired')
                    """
                )
                conn.execute(
                    """
                    insert into report_send_history (
                        trade_date, report_type, recipients, status, sent_at, error
                    )
                    values ('20260618', 'white', 'a@example.com',
                            'failed', '2026-06-20 12:50:00', 'SMTP auth failed')
                    """
                )
                conn.commit()

            answer = answer_question(root, "邮件发送失败原因是什么？")

            self.assertIn("SMTP auth failed", answer.text)
            self.assertNotIn("token expired", answer.text)
            self.assertNotIn("任务记录", answer.text)

    def test_diagnoses_report_not_generated_with_fixed_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "futures.db"
            db_path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """
                    create table report_generation_history (
                        id integer primary key autoincrement,
                        trade_date text,
                        report_type text,
                        generation_status text,
                        html_path text,
                        pdf_path text,
                        md_path text,
                        report_dir text,
                        quality_status text,
                        quality_detail text,
                        generated_at text,
                        recorded_at text,
                        output text,
                        error text
                    )
                    """
                )
                conn.execute(
                    """
                    insert into report_generation_history (
                        trade_date, report_type, generation_status, quality_status,
                        quality_detail, generated_at, recorded_at, error
                    )
                    values ('20260618', 'white', 'failed', 'not_checked',
                            '生成未成功，未执行文件质检。', '2026-06-20 16:30:00',
                            '2026-06-20 16:30:01', 'missing fut_daily data')
                    """
                )
                conn.commit()

            with patch("desktop.ai_assistant.call_deepseek_assistant") as call:
                answer = answer_question(root, "为什么报告没生成？")

            call.assert_not_called()
            self.assertIn("诊断：报告生成失败", answer.text)
            self.assertIn("原因：missing fut_daily data", answer.text)
            self.assertIn("证据：20260618 white generation_status=failed", answer.text)
            self.assertIn("建议：先检查数据中心是否有缺口，再重新生成报告。", answer.text)

    def test_diagnoses_mail_not_sent_with_fixed_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "futures.db"
            db_path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db_path)) as conn:
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
                    insert into report_recipient_send_history (
                        trade_date, report_type, recipient, status, sent_at, error
                    )
                    values ('20260618', 'white', 'a@example.com',
                            'failed', '2026-06-20 16:31:00', 'SMTP auth failed')
                    """
                )
                conn.commit()

            with patch("desktop.ai_assistant.call_deepseek_assistant") as call:
                answer = answer_question(root, "为什么邮件没发送？")

            call.assert_not_called()
            self.assertIn("诊断：邮件发送失败", answer.text)
            self.assertIn("原因：SMTP auth failed", answer.text)
            self.assertIn("证据：20260618 white a@example.com status=failed", answer.text)
            self.assertIn("建议：检查配置中心里的发件邮箱、SMTP 授权码和演练发送开关。", answer.text)

    def test_diagnoses_data_update_failure_with_fixed_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "futures.db"
            db_path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """
                    create table task_run_history (
                        id integer primary key autoincrement,
                        task_type text,
                        task_name text,
                        status text,
                        target_date text,
                        detail text,
                        started_at text,
                        finished_at text,
                        duration_seconds real,
                        output text,
                        error text
                    )
                    """
                )
                conn.execute(
                    """
                    insert into task_run_history (
                        task_type, task_name, status, target_date, detail,
                        finished_at, output, error
                    )
                    values ('data_update', '数据更新', 'failed', '20260618',
                            '20260611~20260618', '2026-06-20 12:30:00',
                            '', 'Tushare token expired')
                    """
                )
                conn.commit()

            with patch("desktop.ai_assistant.call_deepseek_assistant") as call:
                answer = answer_question(root, "为什么数据没更新？")

            call.assert_not_called()
            self.assertIn("诊断：数据更新失败", answer.text)
            self.assertIn("原因：Tushare token expired", answer.text)
            self.assertIn("证据：数据更新 20260618 status=failed", answer.text)
            self.assertIn("建议：检查 Tushare 配置和下载日志，再执行快速更新或一键更新。", answer.text)

    def test_diagnoses_data_gap_with_fixed_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "futures.db"
            db_path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("create table trade_cal (exchange text, cal_date text, is_open text)")
                conn.execute("create table fut_daily (ts_code text, trade_date text)")
                conn.executemany(
                    "insert into trade_cal values ('SHFE', ?, '1')",
                    [("20260616",), ("20260617",), ("20260618",)],
                )
                conn.executemany(
                    "insert into fut_daily values ('JD2609.DCE', ?)",
                    [("20260616",), ("20260618",)],
                )
                conn.commit()

            with patch("desktop.ai_assistant.call_deepseek_assistant") as call, patch("desktop.ai_diagnostics._today_text", return_value="20260619"):
                answer = answer_question(root, "数据缺口还存在吗？")

            call.assert_not_called()
            self.assertIn("诊断：数据缺口仍存在", answer.text)
            self.assertIn("原因：核心表存在交易日缺口。", answer.text)
            self.assertIn("证据：日线行情 fut_daily 缺口 1 个", answer.text)
            self.assertIn("建议：在数据中心执行补最近缺口，完成后刷新状态。", answer.text)

    def test_diagnoses_deepseek_configuration_failure_with_fixed_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with patch("desktop.ai_assistant.call_deepseek_assistant") as call:
                answer = answer_question(root, "DeepSeek 为什么调用失败？")

            call.assert_not_called()
            self.assertIn("诊断：DeepSeek 未启用或 Key 缺失", answer.text)
            self.assertIn("原因：配置中心没有开启商业 AI，或没有保存 DeepSeek API Key。", answer.text)
            self.assertIn("建议：到配置中心开启商业 AI，并保存有效的 DeepSeek API Key。", answer.text)

    def test_diagnoses_daemon_not_running_with_fixed_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with patch("desktop.ai_assistant.call_deepseek_assistant") as call:
                answer = answer_question(root, "24小时守护为什么没运行？")

            call.assert_not_called()
            self.assertIn("诊断：24小时守护未启动", answer.text)
            self.assertIn("原因：没有找到守护进程 PID 记录。", answer.text)
            self.assertIn("建议：在任务中心启动 24 小时守护发送。", answer.text)


if __name__ == "__main__":
    unittest.main()

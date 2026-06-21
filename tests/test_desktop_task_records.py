import sqlite3
import tempfile
import unittest
from pathlib import Path

from desktop.actions import ActionResult
from desktop.task_records import load_task_run_history, record_task_run, run_and_record


class DesktopTaskRecordTests(unittest.TestCase):
    def test_record_task_run_writes_structured_row_to_sqlite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            result = record_task_run(
                root,
                task_type="data_update",
                task_name="数据更新",
                status="success",
                target_date="20260618",
                detail="20260611~20260618",
                output="updated",
            )

            self.assertTrue(result.ok)
            rows = load_task_run_history(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["task_type"], "data_update")
            self.assertEqual(rows[0]["task_name"], "数据更新")
            self.assertEqual(rows[0]["status"], "success")
            self.assertEqual(rows[0]["target_date"], "20260618")

    def test_run_and_record_records_success_and_failure_without_changing_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            success = run_and_record(
                root,
                task_type="report_generate",
                task_name="报告生成",
                target_date="20260618",
                detail="white",
                fn=lambda: ActionResult(True, "ok", "generated"),
            )
            failure = run_and_record(
                root,
                task_type="mail_send",
                task_name="邮件发送",
                target_date="20260618",
                detail="white",
                fn=lambda: ActionResult(False, "bad", "smtp failed"),
            )

            self.assertTrue(success.ok)
            self.assertFalse(failure.ok)
            rows = load_task_run_history(root)
            self.assertEqual([row["task_type"] for row in rows], ["mail_send", "report_generate"])
            self.assertEqual([row["status"] for row in rows], ["failed", "success"])
            self.assertEqual(rows[0]["error"], "bad")

    def test_task_run_history_schema_is_queryable_by_sqlite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record_task_run(root, "mail_send", "邮件发送", "success", "20260618", "white")

            conn = sqlite3.connect(root / "data" / "futures.db")
            try:
                row = conn.execute(
                    """
                    select task_type, task_name, status, target_date
                    from task_run_history
                    where task_type = 'mail_send'
                    """
                ).fetchone()
            finally:
                conn.close()

            self.assertEqual(row, ("mail_send", "邮件发送", "success", "20260618"))


if __name__ == "__main__":
    unittest.main()

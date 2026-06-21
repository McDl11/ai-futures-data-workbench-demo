import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SYSTEM_DIR = Path(__file__).resolve().parents[1]
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))


class ReportPathTests(unittest.TestCase):
    def test_report_paths_are_typed_for_white_and_daily(self):
        from report_paths import report_paths

        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp)

            white_html, white_md, white_pdf = report_paths('20260616', 'white', reports_dir=reports_dir)
            self.assertEqual(white_html, reports_dir / '20260616' / 'white' / '期货白盘_数据20260616.html')
            self.assertEqual(white_md, reports_dir / '20260616' / 'white' / '期货白盘_数据20260616.md')
            self.assertEqual(white_pdf, reports_dir / '20260616' / 'white' / '期货白盘_数据20260616.pdf')

            daily_html, daily_md, daily_pdf = report_paths('20260616', 'daily', reports_dir=reports_dir)
            self.assertEqual(daily_html, reports_dir / '20260616' / 'daily' / '期货日报_数据20260616.html')
            self.assertEqual(daily_md, reports_dir / '20260616' / 'daily' / '期货日报_数据20260616.md')
            self.assertEqual(daily_pdf, reports_dir / '20260616' / 'daily' / '期货日报_数据20260616.pdf')

    def test_backup_dir_uses_project_root_for_relative_values(self):
        from config import PROJECT_ROOT, resolve_backup_dir

        self.assertEqual(resolve_backup_dir('backup'), PROJECT_ROOT / 'backups')
        self.assertEqual(resolve_backup_dir(''), PROJECT_ROOT / 'backups')
        self.assertEqual(resolve_backup_dir(None), PROJECT_ROOT / 'backups')


class HealthCheckTests(unittest.TestCase):
    def test_check_reports_accepts_white_report_in_type_subdirectory(self):
        from health_check import HealthReport, check_reports

        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp)
            white_dir = reports_dir / '20260616' / 'white'
            white_dir.mkdir(parents=True)
            (white_dir / '期货白盘_数据20260616.html').write_text('<html></html>', encoding='utf-8')
            (white_dir / '期货白盘_数据20260616.md').write_text('# report\n', encoding='utf-8')
            (white_dir / '期货白盘_数据20260616.pdf').write_bytes(b'%PDF-1.4\n')

            report = HealthReport()
            with patch('health_check.REPORTS_DIR', reports_dir), patch(
                'health_check.scan_pdf_header_footer',
                return_value=[],
            ):
                check_reports(report, '20260616')

        self.assertTrue(any('[OK] 最新报告目录' in line and 'white' in line for line in report.lines))
        self.assertFalse(any('报告缺失' in line for line in report.lines))

    def test_daemon_process_ids_deduplicates_py_launcher(self):
        from health_check import daemon_process_ids

        rows = [
            {
                'ProcessId': 6904,
                'Name': 'py.exe',
                'CommandLine': r'"C:\WINDOWS\py.exe" .\auto_report_daemon.py --send',
            },
            {
                'ProcessId': 19984,
                'Name': 'python.exe',
                'CommandLine': r'C:\Python313\python.exe .\auto_report_daemon.py --send',
            },
        ]

        self.assertEqual(daemon_process_ids(rows), ['19984'])

    def test_daemon_process_ids_deduplicates_venv_python_parent(self):
        from health_check import daemon_process_ids

        rows = [
            {
                'ProcessId': 35200,
                'ParentProcessId': 7540,
                'Name': 'python.exe',
                'CommandLine': (
                    r'"D:\AI期货数据工作台\.venv\Scripts\python.exe" '
                    r'"D:\AI期货数据工作台\futures_report_system\auto_report_daemon.py" --send'
                ),
            },
            {
                'ProcessId': 6900,
                'ParentProcessId': 35200,
                'Name': 'python.exe',
                'CommandLine': (
                    r'"C:\Python310\python.exe" '
                    r'"D:\AI期货数据工作台\futures_report_system\auto_report_daemon.py" --send'
                ),
            },
        ]

        self.assertEqual(daemon_process_ids(rows), ['6900'])

    def test_load_process_rows_accepts_unescaped_dot_venv_path(self):
        from health_check import load_process_rows

        raw_json = (
            r'[{"ProcessId":16492,"Name":"python.exe",'
            r'"CommandLine":"\"D:\\repo\.venv\\Scripts\\python.exe\" -"}]'
        )

        rows = load_process_rows(raw_json)

        self.assertEqual(rows[0]['ProcessId'], 16492)
        self.assertEqual(rows[0]['CommandLine'], r'"D:\repo\.venv\Scripts\python.exe" -')


if __name__ == '__main__':
    unittest.main()

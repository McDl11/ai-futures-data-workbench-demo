import sys
import logging
import unittest
from pathlib import Path
from unittest.mock import patch


SYSTEM_DIR = Path(__file__).resolve().parents[1]
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))


class AutoReportDaemonTests(unittest.TestCase):
    def test_ctrl_c_exits_cleanly_without_traceback(self):
        import auto_report_daemon

        logger = logging.getLogger('auto_report_test')
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False

        with patch.object(sys, 'argv', ['auto_report_daemon.py']), patch(
            'auto_report_daemon.setup_logging',
            return_value=logger,
        ), patch(
            'auto_report_daemon.logging.getLogger',
            return_value=logger,
        ), patch(
            'auto_report_daemon.time.sleep',
            side_effect=KeyboardInterrupt,
        ):
            self.assertEqual(auto_report_daemon.main(), 0)


if __name__ == '__main__':
    unittest.main()

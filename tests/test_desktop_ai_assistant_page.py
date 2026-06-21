import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QTextEdit

from desktop.main_window import MainWindow
from desktop.pages.ai_assistant import AiAssistantPage
from desktop.state import collect_workspace_snapshot


class DesktopAiAssistantPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ai_assistant_page_answers_without_running_actions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = collect_workspace_snapshot(root)
            page = AiAssistantPage(snapshot)

            page.ask("帮我发送当前报告")

            answer_boxes = page.findChildren(QTextEdit)
            self.assertTrue(any("只读" in box.toPlainText() for box in answer_boxes))
            self.assertFalse((root / "data" / "futures.db").exists())

    def test_main_window_registers_ai_assistant_navigation(self):
        window = MainWindow()
        try:
            labels = [button.text() for button in window.findChildren(QPushButton)]
            self.assertIn("AI 助手", labels)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()

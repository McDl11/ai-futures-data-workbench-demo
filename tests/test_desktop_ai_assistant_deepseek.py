import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop.ai_assistant import answer_question


class DesktopAiAssistantDeepSeekTests(unittest.TestCase):
    def test_commercial_ai_disabled_does_not_call_deepseek(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            report_dir.mkdir()
            (report_dir / ".env").write_text(
                "AI_ASSISTANT_USE_COMMERCIAL_AI=false\nDEEPSEEK_API_KEY=secret\n",
                encoding="utf-8",
            )

            with patch("desktop.ai_assistant.call_deepseek_assistant") as call:
                answer = answer_question(root, "最近任务运行情况？")

            call.assert_not_called()
            self.assertIn("还没有读到相关任务记录", answer.text)

    def test_commercial_ai_enabled_calls_deepseek_when_key_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            report_dir.mkdir()
            (report_dir / ".env").write_text(
                "\n".join(
                    [
                        "AI_ASSISTANT_USE_COMMERCIAL_AI=true",
                        "DEEPSEEK_API_KEY=secret",
                        "DEEPSEEK_API_BASE=https://api.deepseek.com",
                        "DEEPSEEK_MODEL=deepseek-test",
                        "AI_ANALYSIS_TIMEOUT_SECONDS=12",
                        "AI_ANALYSIS_MAX_TOKENS=345",
                    ]
                ),
                encoding="utf-8",
            )

            with patch("desktop.ai_assistant.call_deepseek_assistant", return_value="商业 AI 回答") as call:
                answer = answer_question(root, "为什么行情突然波动？")

            call.assert_called_once()
            config_arg = call.call_args.args[0]
            self.assertEqual(config_arg.deepseek_api_key, "secret")
            self.assertEqual(answer.text, "商业 AI 回答")

    def test_commercial_ai_failure_falls_back_to_local_answer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "futures_report_system"
            report_dir.mkdir()
            (report_dir / ".env").write_text(
                "AI_ASSISTANT_USE_COMMERCIAL_AI=true\nDEEPSEEK_API_KEY=secret\n",
                encoding="utf-8",
            )

            with patch("desktop.ai_assistant.call_deepseek_assistant", side_effect=RuntimeError("network bad")):
                answer = answer_question(root, "报告质检怎么样？")

            self.assertIn("商业 AI 调用失败，已改用本地只读回答", answer.text)
            self.assertIn("还没有读到结构化报告生成记录", answer.text)


if __name__ == "__main__":
    unittest.main()

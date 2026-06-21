import unittest

from desktop.ai_router import route_question


class DesktopAiRouterTests(unittest.TestCase):
    def test_routes_data_dictionary_questions_to_local_answer(self):
        route = route_question("鸡蛋历史行情在哪个表查？")

        self.assertEqual(route.intent, "data_dictionary")
        self.assertFalse(route.allow_commercial_ai)

    def test_routes_known_table_name_questions_to_local_answer(self):
        route = route_question("fut_daily 是干什么的？")

        self.assertEqual(route.intent, "data_dictionary")
        self.assertFalse(route.allow_commercial_ai)

    def test_routes_trading_day_questions_to_local_answer(self):
        route = route_question("下一个交易日是哪天？")

        self.assertEqual(route.intent, "trading_day")
        self.assertFalse(route.allow_commercial_ai)

    def test_allows_commercial_ai_for_explanation_questions(self):
        route = route_question("为什么行情突然波动？")

        self.assertEqual(route.intent, "explain")
        self.assertTrue(route.allow_commercial_ai)

    def test_routes_common_failure_questions_to_local_diagnostics(self):
        route = route_question("为什么今天没发报告？")

        self.assertEqual(route.intent, "diagnostic")
        self.assertFalse(route.allow_commercial_ai)


if __name__ == "__main__":
    unittest.main()

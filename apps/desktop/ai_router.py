from __future__ import annotations

from dataclasses import dataclass

from desktop.ai_diagnostics import is_diagnostic_question
from desktop.data_dictionary import answer_data_dictionary_question


@dataclass(frozen=True)
class QuestionRoute:
    intent: str
    allow_commercial_ai: bool


def route_question(question: str) -> QuestionRoute:
    normalized = str(question or "").strip().lower()
    if _wants_trading_day(normalized):
        return QuestionRoute("trading_day", False)
    if _wants_data_dictionary(normalized):
        return QuestionRoute("data_dictionary", False)
    if is_diagnostic_question(normalized):
        return QuestionRoute("diagnostic", False)
    if _wants_local_status(normalized):
        return QuestionRoute("local_status", False)
    if _wants_explanation(normalized):
        return QuestionRoute("explain", True)
    return QuestionRoute("general", True)


def _wants_trading_day(question: str) -> bool:
    return "交易日" in question or "休市" in question or "开市" in question


def _wants_data_dictionary(question: str) -> bool:
    if answer_data_dictionary_question(question):
        return True
    table_words = ("哪个表", "哪张表", "什么表", "表查", "字段", "数据字典")
    domain_words = ("历史行情", "日线", "行情", "鸡蛋", "黄金", "白银", "螺纹", "豆粕", "主力", "合约")
    return any(word in question for word in table_words) or (
        any(word in question for word in domain_words) and any(word in question for word in ("哪里", "怎么查", "在哪", "表"))
    )


def _wants_local_status(question: str) -> bool:
    return any(
        word in question
        for word in (
            "有没有生成",
            "有没有发送",
            "是否生成",
            "是否发送",
            "最新数据",
            "多少行",
            "守护",
            "运行中",
            "配置",
        )
    )


def _wants_explanation(question: str) -> bool:
    return any(word in question for word in ("为什么", "原因", "怎么处理", "怎么办", "失败", "异常"))

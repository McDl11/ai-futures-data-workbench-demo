from __future__ import annotations

import sqlite3
import json
import re
import urllib.request
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from desktop.ai_diagnostics import answer_diagnostic_question
from desktop.ai_router import route_question
from desktop.config_center import CommonConfig, load_common_config_with_secrets
from desktop.data_dictionary import answer_data_dictionary_question
from desktop.logs import scan_error_logs
from desktop.project_paths import report_system_dir
from desktop.report_records import load_report_generation_history
from desktop.task_records import load_task_run_history


@dataclass(frozen=True)
class AssistantAnswer:
    text: str
    sources: list[str]


READ_ONLY_ACTION_NOTICE = "当前是只读模式，我不会发送邮件、不会更新数据、不会生成报告、不会删除文件。"


def answer_question(project_root: Path, question: str) -> AssistantAnswer:
    root = Path(project_root)
    route = route_question(question)
    local_answer = _answer_question_local(root, question)
    if not route.allow_commercial_ai:
        return local_answer
    config = load_common_config_with_secrets(root)
    if not _commercial_ai_ready(config):
        return local_answer
    try:
        text = call_deepseek_assistant(config, question, _build_ai_context(root, local_answer))
    except Exception as exc:
        return AssistantAnswer(
            f"商业 AI 调用失败，已改用本地只读回答。\n原因：{exc}\n\n{local_answer.text}",
            local_answer.sources,
        )
    return AssistantAnswer(text.strip() or local_answer.text, local_answer.sources + ["DeepSeek"])


def _answer_question_local(project_root: Path, question: str) -> AssistantAnswer:
    root = Path(project_root)
    normalized = _normalize(question)
    sources: list[str] = []

    if _wants_trading_day(normalized):
        text, used_sources = _trading_day_summary(root, normalized)
        return AssistantAnswer(text, used_sources)

    if _wants_data_dictionary(normalized):
        text = answer_data_dictionary_question(question)
        if text:
            return AssistantAnswer(text, ["本地数据字典"])

    diagnostic = answer_diagnostic_question(root, question)
    if diagnostic:
        return _answer_from(diagnostic)

    if _is_action_request(normalized):
        text = READ_ONLY_ACTION_NOTICE
        if _wants_mail(normalized):
            mail_text, used_sources = _mail_summary(root)
            return AssistantAnswer(f"{text}\n\n{mail_text}", used_sources)
        if _wants_report(normalized):
            report_text, used_sources = _report_summary(root)
            return AssistantAnswer(f"{text}\n\n{report_text}", used_sources)
        if _wants_data(normalized):
            task_text, used_sources = _task_summary(root, preferred_types={"data_update"})
            return AssistantAnswer(f"{text}\n\n{task_text}", used_sources)
        return AssistantAnswer(text, [])

    if _wants_mail(normalized):
        return _answer_from(_mail_summary(root))

    if _wants_report(normalized):
        return _answer_from(_report_summary(root))

    if _wants_task(normalized):
        return _answer_from(_task_summary(root))

    if _wants_log(normalized):
        return _answer_from(_log_summary(root))

    if _wants_failure(normalized):
        task_text, task_sources = _task_summary(root)
        if "还没有" not in task_text and "没有失败" not in task_text:
            return AssistantAnswer(task_text, task_sources)
        return _answer_from(_log_summary(root))

    overview = _brief_overview(root)
    sources.extend(overview.sources)
    return AssistantAnswer(overview.text, sources)


def call_deepseek_assistant(config: CommonConfig, question: str, context: str) -> str:
    url = config.deepseek_api_base.rstrip("/") + "/chat/completions"
    payload = {
        "model": config.deepseek_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是本地期货数据工作台的只读 AI 助手。"
                    "只能根据用户问题和提供的本地状态摘要回答；"
                    "不要编造未提供的数据；不要要求用户去看无关页面；"
                    "不要执行或承诺执行发送、更新、生成、删除、停止任务等操作。"
                    "回答要简洁，只回答用户问的内容。"
                ),
            },
            {
                "role": "user",
                "content": f"用户问题：{question}\n\n本地只读状态摘要：\n{context}",
            },
        ],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": max(1, config.ai_analysis_max_tokens),
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.deepseek_api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=max(1, config.ai_analysis_timeout_seconds)) as response:
        body = json.loads(response.read().decode("utf-8"))
    return str(body["choices"][0]["message"]["content"]).strip()


def _commercial_ai_ready(config: CommonConfig) -> bool:
    return bool(config.ai_assistant_use_commercial_ai and config.deepseek_api_key.strip())


def _build_ai_context(project_root: Path, local_answer: AssistantAnswer) -> str:
    parts = [
        "本地规则回答：",
        _sanitize_context(local_answer.text),
        "",
        "最近任务：",
        _sanitize_context(_task_summary(project_root)[0]),
        "",
        "最近报告：",
        _sanitize_context(_report_summary(project_root)[0]),
        "",
        "最近邮件：",
        _sanitize_context(_mail_summary(project_root)[0]),
        "",
        "最近日志：",
        _sanitize_context(_log_summary(project_root)[0]),
    ]
    return "\n".join(parts)[:6000]


def _sanitize_context(text: str) -> str:
    sanitized = re.sub(r"([A-Za-z0-9._%+-]{2})[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+)", r"\1***\2", text)
    sanitized = re.sub(r"(?i)(password|api[_-]?key|token|secret)[=:：]\s*\S+", r"\1=***", sanitized)
    return sanitized


def _answer_from(result: tuple[str, list[str]]) -> AssistantAnswer:
    return AssistantAnswer(result[0], result[1])


def _trading_day_summary(project_root: Path, question: str = "") -> tuple[str, list[str]]:
    db_path = _db_path(project_root)
    source = _db_source(project_root, "trade_cal")
    target_date = _extract_date_from_question(datetime.now().strftime("%Y%m%d"))
    if not db_path.exists():
        return f"{_format_date(target_date)}：无法判断，数据库不存在。", [source]

    with closing(sqlite3.connect(db_path)) as conn:
        if not _table_exists(conn, "trade_cal"):
            return f"{_format_date(target_date)}：无法判断，trade_cal 交易日历表不存在。", [source]
        row = conn.execute(
            """
            select cal_date, max(cast(is_open as text))
            from trade_cal
            where cal_date = ?
            group by cal_date
            """,
            (target_date,),
        ).fetchone()
        previous = conn.execute(
            """
            select max(cal_date)
            from trade_cal
            where cal_date < ? and cast(is_open as text) = '1'
            """,
            (target_date,),
        ).fetchone()
        next_day = conn.execute(
            """
            select min(cal_date)
            from trade_cal
            where cal_date > ? and cast(is_open as text) = '1'
            """,
            (target_date,),
        ).fetchone()

    next_text = _format_date(next_day[0]) if next_day and next_day[0] else "未查到"
    if _wants_next_trading_day(question):
        return f"下一个交易日是 {next_text}。", [source]

    if not row:
        return f"{_format_date(target_date)}：交易日历里没有这一天，无法判断。", [source]

    is_open = str(row[1]) == "1"
    if is_open:
        return f"{_format_date(target_date)} 是交易日。", [source]
    previous_text = _format_date(previous[0]) if previous and previous[0] else "未查到"
    return f"{_format_date(target_date)} 不是交易日。上一交易日：{previous_text}。", [source]


def _task_summary(
    project_root: Path,
    preferred_types: set[str] | None = None,
) -> tuple[str, list[str]]:
    rows = load_task_run_history(project_root, limit=12)
    source = _db_source(project_root, "task_run_history")
    if preferred_types:
        rows = [row for row in rows if str(row.get("task_type") or "") in preferred_types]
    if not rows:
        return "还没有读到相关任务记录。", [source]

    failed = [row for row in rows if str(row.get("status") or "").lower() == "failed"]
    if failed:
        row = failed[0]
        return (
            "最近失败任务："
            f"\n- 任务：{row.get('task_name') or row.get('task_type')}"
            f"\n- 日期：{row.get('target_date') or '-'}"
            f"\n- 时间：{row.get('finished_at') or '-'}"
            f"\n- 原因：{row.get('error') or row.get('output') or '未记录具体原因'}",
            [source],
        )

    row = rows[0]
    return (
        "最近没有失败任务。"
        f"\n- 最近任务：{row.get('task_name') or row.get('task_type')}"
        f"\n- 状态：{row.get('status') or '-'}"
        f"\n- 日期：{row.get('target_date') or '-'}"
        f"\n- 时间：{row.get('finished_at') or '-'}",
        [source],
    )


def _report_summary(project_root: Path) -> tuple[str, list[str]]:
    rows = load_report_generation_history(project_root, limit=8)
    source = _db_source(project_root, "report_generation_history")
    if not rows:
        return "还没有读到结构化报告生成记录。", [source]

    failed_quality = [row for row in rows if str(row.get("quality_status") or "").lower() == "failed"]
    failed_generation = [row for row in rows if str(row.get("generation_status") or "").lower() == "failed"]
    row = (failed_quality or failed_generation or rows)[0]
    quality = row.get("quality_status") or "-"
    generation = row.get("generation_status") or "-"
    detail = row.get("quality_detail") or row.get("error") or "未记录异常详情"
    return (
        "报告质检结果："
        f"\n- 日期：{row.get('trade_date') or '-'}"
        f"\n- 类型：{row.get('report_type') or '-'}"
        f"\n- 生成状态：{generation}"
        f"\n- 质检结果：{quality}"
        f"\n- 说明：{detail}",
        [source],
    )


def _mail_summary(project_root: Path) -> tuple[str, list[str]]:
    db_path = _db_path(project_root)
    source = _db_source(project_root, "report_send_history")
    if not db_path.exists():
        return "还没有可读的邮件发送记录。", [source]

    with closing(sqlite3.connect(db_path)) as conn:
        rows = _select_mail_rows(conn)

    if not rows:
        return "还没有读到邮件发送记录。", [source]

    failed = [row for row in rows if str(row["status"]).lower() in {"failed", "partial_failed"}]
    row = (failed or rows)[0]
    prefix = "邮件发送失败原因：" if failed else "最近邮件发送记录："
    return (
        prefix +
        f"\n- 日期：{row['trade_date'] or '-'}"
        f"\n- 类型：{row['report_type'] or '-'}"
        f"\n- 收件人：{row['target'] or '-'}"
        f"\n- 状态：{row['status'] or '-'}"
        f"\n- 时间：{row['sent_at'] or '-'}"
        f"\n- 原因：{row['error'] or '未记录错误原因'}",
        [source],
    )


def _log_summary(project_root: Path) -> tuple[str, list[str]]:
    errors = scan_error_logs(project_root, limit=20)
    source = str(report_system_dir(Path(project_root)) / "logs")
    if not errors:
        return "最近日志里没有扫到 ERROR / Traceback / [FAIL]。", [source]
    error = errors[0]
    return (
        "最近日志异常："
        f"\n- 系统：{error.category}"
        f"\n- 文件：{error.path.name}"
        f"\n- 内容：{error.line}",
        [str(error.path)],
    )


def _brief_overview(project_root: Path) -> AssistantAnswer:
    task_text, task_sources = _task_summary(project_root)
    return AssistantAnswer(task_text, task_sources)


def _select_mail_rows(conn: sqlite3.Connection) -> list[dict[str, str]]:
    if _table_exists(conn, "report_recipient_send_history"):
        rows = conn.execute(
            """
            select trade_date, report_type, recipient as target, status, sent_at, coalesce(error, '') as error
            from report_recipient_send_history
            order by id desc
            limit 10
            """
        ).fetchall()
        if rows:
            return [_mail_row_dict(row) for row in rows]

    if _table_exists(conn, "report_send_history"):
        rows = conn.execute(
            """
            select trade_date, report_type, recipients as target, status, sent_at, coalesce(error, '') as error
            from report_send_history
            order by id desc
            limit 10
            """
        ).fetchall()
        return [_mail_row_dict(row) for row in rows]
    return []


def _mail_row_dict(row: tuple[object, ...]) -> dict[str, str]:
    return {
        "trade_date": str(row[0] or ""),
        "report_type": str(row[1] or ""),
        "target": str(row[2] or ""),
        "status": str(row[3] or ""),
        "sent_at": str(row[4] or ""),
        "error": str(row[5] or ""),
    }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type='table' and name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _is_action_request(question: str) -> bool:
    if any(word in question for word in ("原因", "为什么", "是否", "是不是", "怎么样", "什么", "吗", "?","？")):
        return False
    return any(word in question for word in ("帮我发送", "发送当前", "更新数据", "生成报告", "删除", "停止", "启动", "重发", "补齐"))


def _wants_trading_day(question: str) -> bool:
    return "交易日" in question or "休市" in question or "开市" in question


def _wants_data_dictionary(question: str) -> bool:
    return answer_data_dictionary_question(question) is not None


def _wants_next_trading_day(question: str) -> bool:
    return _wants_trading_day(question) and any(word in question for word in ("下一个", "下一", "下次", "最近一个", "最近的"))


def _wants_data(question: str) -> bool:
    return "数据" in question or "缺口" in question


def _wants_mail(question: str) -> bool:
    return any(word in question for word in ("邮件", "发送", "收件", "smtp", "重发"))


def _wants_report(question: str) -> bool:
    return any(word in question for word in ("报告", "质检", "pdf", "html", "markdown", "生成"))


def _wants_task(question: str) -> bool:
    return any(word in question for word in ("任务", "进程", "运行"))


def _wants_log(question: str) -> bool:
    return any(word in question for word in ("日志", "错误", "traceback", "error"))


def _wants_failure(question: str) -> bool:
    return any(word in question for word in ("失败", "异常", "原因"))


def _normalize(question: str) -> str:
    return str(question or "").strip().lower()


def _extract_date_from_question(default_date: str) -> str:
    return default_date


def _format_date(value: object) -> str:
    text = str(value or "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text or "-"


def _db_source(project_root: Path, table: str) -> str:
    return f"{_db_path(project_root)}::{table}"


def _db_path(project_root: Path) -> Path:
    return Path(project_root) / "data" / "futures.db"

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from desktop.config_center import load_common_config
from desktop.data_center import collect_core_table_statuses
from desktop.project_paths import desktop_runtime_dir, report_system_dir
from desktop.report_records import load_report_generation_history
from desktop.task_records import load_task_run_history
from desktop.tasks import get_task_processes


def answer_diagnostic_question(project_root: Path, question: str) -> tuple[str, list[str]] | None:
    normalized = str(question or "").strip().lower()
    root = Path(project_root)
    if _wants_deepseek_diagnostic(normalized):
        return _deepseek_diagnostic(root)
    if _wants_daemon_diagnostic(normalized):
        return _daemon_diagnostic(root)
    if _wants_report_diagnostic(normalized):
        return _report_diagnostic(root)
    if _wants_mail_diagnostic(normalized):
        return _mail_diagnostic(root)
    if _wants_data_diagnostic(normalized):
        return _data_diagnostic(root, normalized)
    return None


def is_diagnostic_question(question: str) -> bool:
    return _looks_like_known_diagnostic(question)


def format_diagnostic(title: str, reason: str, evidence: str, advice: str) -> str:
    return f"诊断：{title}\n原因：{reason}\n证据：{evidence}\n建议：{advice}"


def _report_diagnostic(project_root: Path) -> tuple[str, list[str]]:
    rows = load_report_generation_history(project_root, limit=10)
    source = _db_source(project_root, "report_generation_history")
    if not rows:
        return (
            format_diagnostic(
                "没有读到报告生成记录",
                "结构化报告记录为空，系统无法确认是否执行过生成。",
                "report_generation_history 无记录",
                "先到报告中心重新生成一次报告，再查看执行输出和报告记录。",
            ),
            [source],
        )
    failed = [row for row in rows if str(row.get("generation_status") or "").lower() == "failed"]
    row = (failed or rows)[0]
    status = str(row.get("generation_status") or "-")
    quality = str(row.get("quality_status") or "-")
    reason = str(row.get("error") or row.get("quality_detail") or "没有记录具体原因")
    title = "报告生成失败" if status.lower() == "failed" else "最近报告生成记录正常"
    advice = "先检查数据中心是否有缺口，再重新生成报告。" if status.lower() == "failed" else "如果界面仍显示异常，刷新报告中心后再检查文件路径。"
    return (
        format_diagnostic(
            title,
            reason,
            f"{row.get('trade_date') or '-'} {row.get('report_type') or '-'} generation_status={status}, quality_status={quality}",
            advice,
        ),
        [source],
    )


def _mail_diagnostic(project_root: Path) -> tuple[str, list[str]]:
    rows = _load_mail_rows(project_root)
    source = _db_source(project_root, "report_recipient_send_history")
    if not rows:
        return (
            format_diagnostic(
                "没有读到邮件发送记录",
                "结构化邮件发送记录为空，系统无法确认是否执行过发送。",
                "report_recipient_send_history / report_send_history 无记录",
                "先到邮件中心或报告中心执行一次发送，再查看发送记录。",
            ),
            [source],
        )
    failed = [row for row in rows if str(row["status"]).lower() in {"failed", "partial_failed"}]
    row = (failed or rows)[0]
    failed_now = str(row["status"]).lower() in {"failed", "partial_failed"}
    return (
        format_diagnostic(
            "邮件发送失败" if failed_now else "最近邮件发送记录正常",
            row["error"] or "没有记录具体原因",
            f"{row['trade_date'] or '-'} {row['report_type'] or '-'} {row['target'] or '-'} status={row['status'] or '-'}",
            "检查配置中心里的发件邮箱、SMTP 授权码和演练发送开关。" if failed_now else "如果收件箱没收到，检查垃圾箱、收件人列表和 SMTP 服务商退信。",
        ),
        [source],
    )


def _data_diagnostic(project_root: Path, question: str) -> tuple[str, list[str]]:
    if "缺口" in question:
        gap = _data_gap_diagnostic(project_root)
        if gap:
            return gap

    rows = [row for row in load_task_run_history(project_root, limit=20) if str(row.get("task_type") or "") == "data_update"]
    source = _db_source(project_root, "task_run_history")
    if not rows:
        return (
            format_diagnostic(
                "没有读到数据更新记录",
                "结构化任务记录里没有数据更新任务。",
                "task_run_history 中 task_type=data_update 无记录",
                "先在数据中心执行快速更新或一键更新，再查看执行输出。",
            ),
            [source],
        )
    failed = [row for row in rows if str(row.get("status") or "").lower() == "failed"]
    row = (failed or rows)[0]
    failed_now = str(row.get("status") or "").lower() == "failed"
    return (
        format_diagnostic(
            "数据更新失败" if failed_now else "最近数据更新记录正常",
            str(row.get("error") or row.get("output") or "没有记录具体原因"),
            f"{row.get('task_name') or row.get('task_type')} {row.get('target_date') or '-'} status={row.get('status') or '-'}",
            "检查 Tushare 配置和下载日志，再执行快速更新或一键更新。" if failed_now else "如果核心表日期没变化，刷新数据中心并查看下载日志。",
        ),
        [source],
    )


def _data_gap_diagnostic(project_root: Path) -> tuple[str, list[str]] | None:
    statuses = collect_core_table_statuses(Path(project_root) / "data" / "futures.db", today=_today_text())
    warnings = [status for status in statuses if status.gap_count and status.gap_count > 0]
    source = _db_source(project_root, "core_tables")
    if not warnings:
        if any(status.exists for status in statuses):
            return (
                format_diagnostic(
                    "未发现核心表交易日缺口",
                    "核心表缺口检查没有发现缺失交易日。",
                    "核心表 gap_count 均为 0 或不按交易日检查",
                    "无需补缺口；如果数据仍异常，再检查下载日志和具体品种数据。",
                ),
                [source],
            )
        return None
    first = warnings[0]
    return (
        format_diagnostic(
            "数据缺口仍存在",
            "核心表存在交易日缺口。",
            f"{first.label} {first.table} 缺口 {first.gap_count} 个：{first.gap_summary}",
            "在数据中心执行补最近缺口，完成后刷新状态。",
        ),
        [source],
    )


def _deepseek_diagnostic(project_root: Path) -> tuple[str, list[str]]:
    config = load_common_config(project_root)
    source = str(report_system_dir(Path(project_root)) / ".env")
    if not config.ai_assistant_use_commercial_ai or not config.has_deepseek_api_key:
        return (
            format_diagnostic(
                "DeepSeek 未启用或 Key 缺失",
                "配置中心没有开启商业 AI，或没有保存 DeepSeek API Key。",
                f"商业 AI 开关={config.ai_assistant_use_commercial_ai}, Key 已保存={config.has_deepseek_api_key}",
                "到配置中心开启商业 AI，并保存有效的 DeepSeek API Key。",
            ),
            [source],
        )
    return (
        format_diagnostic(
            "DeepSeek 配置已填写",
            "如果仍调用失败，通常是网络、额度、Key 权限或 API 地址问题。",
            f"base={config.deepseek_api_base}, model={config.deepseek_model}, Key 已保存=True",
            "确认网络可访问 DeepSeek，检查 API Key 权限、余额和模型名称。",
        ),
        [source],
    )


def _daemon_diagnostic(project_root: Path) -> tuple[str, list[str]]:
    processes = [item for item in get_task_processes(project_root) if item.task_id == "auto_report_daemon_send"]
    source = str(desktop_runtime_dir(Path(project_root)))
    if not processes or processes[0].pid is None:
        return (
            format_diagnostic(
                "24小时守护未启动",
                "没有找到守护进程 PID 记录。",
                "auto_report_daemon_send.pid 不存在",
                "在任务中心启动 24 小时守护演练。",
            ),
            [source],
        )
    item = processes[0]
    if item.status != "运行中":
        return (
            format_diagnostic(
                "24小时守护异常退出",
                "找到 PID 记录，但进程已经不在运行。",
                f"PID={item.pid}, status={item.status}",
                "先停止守护演练，再重新启动 24 小时守护演练，并查看守护日志。",
            ),
            [source],
        )
    return (
        format_diagnostic(
            "24小时守护正在运行",
            "守护进程 PID 存在且进程仍在运行。",
            f"PID={item.pid}, status={item.status}",
            "无需处理；如未按时发送，再查看守护日志和邮件发送记录。",
        ),
        [source],
    )


def _load_mail_rows(project_root: Path) -> list[dict[str, str]]:
    import sqlite3
    from contextlib import closing

    db_path = Path(project_root) / "data" / "futures.db"
    if not db_path.exists():
        return []
    try:
        with closing(sqlite3.connect(db_path)) as conn:
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
    except sqlite3.Error:
        return []
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


def _table_exists(conn, table: str) -> bool:
    row = conn.execute("select 1 from sqlite_master where type='table' and name=?", (table,)).fetchone()
    return bool(row)


def _looks_like_known_diagnostic(question: str) -> bool:
    normalized = str(question or "").strip().lower()
    return any(
        checker(normalized)
        for checker in (
            _wants_report_diagnostic,
            _wants_mail_diagnostic,
            _wants_data_diagnostic,
            _wants_deepseek_diagnostic,
            _wants_daemon_diagnostic,
        )
    )


def _wants_report_diagnostic(question: str) -> bool:
    return "报告" in question and any(word in question for word in ("没生成", "未生成", "生成失败", "为什么", "原因"))


def _wants_mail_diagnostic(question: str) -> bool:
    return any(word in question for word in ("邮件", "发送")) and any(word in question for word in ("没发送", "未发送", "发送失败", "为什么", "原因"))


def _wants_data_diagnostic(question: str) -> bool:
    return "数据" in question and any(word in question for word in ("没更新", "未更新", "更新失败", "为什么", "原因", "缺口"))


def _wants_deepseek_diagnostic(question: str) -> bool:
    return any(word in question for word in ("deepseek", "商业 ai", "商业ai")) and any(word in question for word in ("失败", "调用", "配置", "为什么", "原因"))


def _wants_daemon_diagnostic(question: str) -> bool:
    return any(word in question for word in ("24小时", "24 小时", "守护", "后台")) and any(word in question for word in ("没运行", "未运行", "异常", "为什么", "状态"))


def _db_source(project_root: Path, table: str) -> str:
    return f"{Path(project_root) / 'data' / 'futures.db'}::{table}"


def _today_text() -> str:
    return datetime.now().strftime("%Y%m%d")

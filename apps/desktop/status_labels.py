from __future__ import annotations

from pathlib import Path


def config_status_label(path: Path, project_root: Path) -> str:
    path = Path(path)
    try:
        relative = path.relative_to(project_root)
    except ValueError:
        return path.name
    parts = relative.parts
    if parts in (("services", "report_system", ".env"), ("futures_report_system", ".env")):
        return "报告系统 .env"
    if parts in (("services", "data_downloader", ".env"), ("tushare down", ".env")):
        return "下载器 .env"
    if parts in (("services", "report_system", ".env.example"), ("futures_report_system", ".env.example")):
        return "报告系统 .env.example"
    if parts in (("services", "report_system", "recipients.csv"), ("futures_report_system", "recipients.csv")):
        return "收件人 recipients.csv"
    if parts in (("services", "report_system", "night_sessions.csv"), ("futures_report_system", "night_sessions.csv")):
        return "夜盘 night_sessions.csv"
    if parts in (("services", "data_downloader", "requirements.txt"), ("tushare down", "requirements.txt")):
        return "下载器 requirements.txt"
    return path.name

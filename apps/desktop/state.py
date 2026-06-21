from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from desktop.project_paths import data_downloader_dir, desktop_runtime_dir, report_system_dir


def find_project_root(start: Path) -> Path:
    for path in (Path(start).resolve(), *Path(start).resolve().parents):
        if (path / "AI金融数据工作台进化规划.md").exists():
            return path
        if (path / "apps").exists() and (path / "services").exists() and (path / "data").exists():
            return path
    return Path(start).resolve().parents[1]


PROJECT_ROOT = find_project_root(Path(__file__).resolve().parent)


@dataclass(frozen=True)
class FileStatus:
    path: Path
    exists: bool
    label: str
    size_bytes: int = 0
    detail: str = ""


@dataclass(frozen=True)
class FileItem:
    path: Path
    modified_at: datetime | None
    size_bytes: int


@dataclass(frozen=True)
class DashboardStatus:
    value: str
    detail: str
    state: str = "neutral"


@dataclass(frozen=True)
class WorkspaceSnapshot:
    project_root: Path
    database: FileStatus
    reports_dir: FileStatus
    report_logs_dir: FileStatus
    downloader_logs_dir: FileStatus
    recent_reports: list[FileItem]
    recent_logs: list[FileItem]
    config_files: list[FileStatus]
    script_files: list[FileStatus]
    recipients_count: int
    latest_trade_date: str | None
    data_status: DashboardStatus
    report_status: DashboardStatus
    mail_status: DashboardStatus
    recent_error: DashboardStatus
    collected_at: datetime


def format_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 B"

    units = ("B", "KB", "MB", "GB")
    value = float(size_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024

    return f"{size_bytes} B"


def file_status(path: Path, exists_label: str = "正常") -> FileStatus:
    path = Path(path)
    try:
        if not path.exists():
            return FileStatus(path=path, exists=False, label="未找到", detail=str(path))

        size = path.stat().st_size if path.is_file() else 0
        detail = format_size(size) if path.is_file() else str(path)
        return FileStatus(path=path, exists=True, label=exists_label, size_bytes=size, detail=detail)
    except OSError as exc:
        return FileStatus(path=path, exists=False, label="不可用", detail=str(exc))


def database_status(path: Path) -> FileStatus:
    return file_status(path, exists_label="正常")


def directory_status(path: Path, exists_label: str = "可用") -> FileStatus:
    return file_status(path, exists_label=exists_label)


def latest_files(
    root: Path,
    patterns: Iterable[str] = ("*",),
    limit: int = 8,
) -> list[FileItem]:
    root = Path(root)
    if limit <= 0 or not root.exists():
        return []

    found: dict[Path, FileItem] = {}
    try:
        for pattern in patterns:
            for path in root.rglob(pattern):
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                found[path] = FileItem(
                    path=path,
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                    size_bytes=stat.st_size,
                )
    except OSError:
        return []

    return sorted(
        found.values(),
        key=lambda item: item.modified_at or datetime.min,
        reverse=True,
    )[:limit]


def count_recipients(path: Path) -> int:
    path = Path(path)
    if not path.exists():
        return 0

    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
    except (OSError, csv.Error, UnicodeDecodeError):
        return 0

    if not rows:
        return 0

    count = 0
    for index, row in enumerate(rows):
        if index == 0 and _looks_like_header(row):
            continue
        if any(cell.strip() for cell in row):
            count += 1
    return count


def latest_trade_date(db_path: Path) -> str | None:
    db_path = Path(db_path)
    if not db_path.exists():
        return None

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        table = conn.execute(
            "select 1 from sqlite_master where type='table' and name='fut_daily'"
        ).fetchone()
        if not table:
            return None
        row = conn.execute(
            "select max(trade_date) from fut_daily where trade_date is not null"
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        if conn is not None:
            conn.close()

    value = row[0] if row else None
    return str(value) if value else None


def data_status(database: FileStatus, trade_date: str | None) -> DashboardStatus:
    if not database.exists:
        return DashboardStatus("未就绪", "未找到 data/futures.db", "warning")
    if not trade_date:
        return DashboardStatus("需检查", "数据库存在，但没有读到 fut_daily 最新交易日", "warning")
    return DashboardStatus("正常", f"最新交易日 {format_trade_date(trade_date)}", "ok")


def latest_report_status(reports_dir: Path, trade_date: str | None) -> DashboardStatus:
    reports_dir = Path(reports_dir)
    if not reports_dir.exists():
        return DashboardStatus("未发现", "报告目录不存在", "warning")

    if not trade_date:
        files = latest_files(reports_dir, patterns=("*.pdf", "*.html", "*.md"), limit=1)
        if not files:
            return DashboardStatus("未发现", "暂无报告文件", "neutral")
        latest = files[0]
        return DashboardStatus("有历史报告", latest.path.name, "neutral")

    trade_dir = reports_dir / trade_date
    if not trade_dir.exists():
        return DashboardStatus("未生成", f"{trade_date} 还没有报告目录", "warning")

    suffixes = {path.suffix.lower() for path in trade_dir.rglob("*") if path.is_file()}
    required = {".pdf", ".html", ".md"}
    missing = sorted(required - suffixes)
    if not missing:
        return DashboardStatus("已生成", f"{format_trade_date(trade_date)} PDF/HTML/MD 齐全", "ok")

    missing_text = ", ".join(suffix.upper().lstrip(".") for suffix in missing)
    return DashboardStatus("不完整", f"{format_trade_date(trade_date)} 缺少 {missing_text}", "warning")


def latest_email_status(db_path: Path) -> DashboardStatus:
    db_path = Path(db_path)
    if not db_path.exists():
        return DashboardStatus("无记录", "数据库不存在，无法读取发送记录", "neutral")

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        table = conn.execute(
            "select 1 from sqlite_master where type='table' and name='report_send_history'"
        ).fetchone()
        if not table:
            return DashboardStatus("无记录", "report_send_history 表不存在", "neutral")
        row = conn.execute(
            """
            select trade_date, report_type, status, sent_at, coalesce(error, '')
            from report_send_history
            order by id desc
            limit 1
            """
        ).fetchone()
    except sqlite3.Error as exc:
        return DashboardStatus("需检查", f"发送记录读取失败：{exc}", "warning")
    finally:
        if conn is not None:
            conn.close()

    if not row:
        return DashboardStatus("无记录", "还没有邮件发送记录", "neutral")

    trade_date, report_type, status, sent_at, error = row
    value_map = {
        "sent": ("已发送", "ok"),
        "dry_run": ("演练发送", "ok"),
        "skipped_duplicate": ("已跳过重复", "neutral"),
        "failed": ("发送失败", "danger"),
        "partial_failed": ("部分失败", "danger"),
    }
    value, state = value_map.get(str(status), (str(status), "warning"))
    detail = f"{trade_date} {report_type} @ {sent_at}"
    if error:
        detail = f"{detail}：{error}"
    return DashboardStatus(value, detail, state)


def detect_recent_error(log_dirs: Iterable[Path], limit: int = 24) -> DashboardStatus:
    log_files: list[FileItem] = []
    for log_dir in log_dirs:
        log_files.extend(latest_files(Path(log_dir), patterns=("*.log", "*.txt"), limit=limit))

    danger_words = ("ERROR", "Traceback", "[FAIL]", "failed with code", "Exception")
    newest_success: FileItem | None = None
    oldest_recovered_error_detail = ""
    for item in sorted(log_files, key=lambda file: file.modified_at or datetime.min, reverse=True)[:limit]:
        try:
            lines = item.path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        if newest_success is None and _has_success_log_line(lines):
            newest_success = item
            continue
        for line in reversed(lines):
            stripped = line.strip()
            if stripped and _is_error_log_line(stripped, danger_words):
                if newest_success is not None:
                    oldest_recovered_error_detail = f"旧异常：{item.path.name}: {stripped[:120]}"
                    break
                return DashboardStatus("发现异常", f"{item.path.name}: {stripped[:180]}", "danger")
        if oldest_recovered_error_detail:
            break

    if newest_success is not None and oldest_recovered_error_detail:
        return DashboardStatus("已恢复", oldest_recovered_error_detail, "ok")

    if log_files:
        return DashboardStatus("未发现", "最近日志未发现 ERROR/Traceback/[FAIL]", "ok")
    return DashboardStatus("无日志", "未发现可扫描的日志文件", "neutral")


def _is_error_log_line(line: str, danger_words: tuple[str, ...]) -> bool:
    normalized = line.strip()
    if not normalized:
        return False
    if normalized.startswith("[OK]") or normalized.startswith("[INFO]"):
        return False
    if "未发现" in normalized and any(word in normalized for word in danger_words):
        return False
    return any(word in normalized for word in danger_words)


def _has_success_log_line(lines: list[str]) -> bool:
    success_words = ("更新完成", "完成", "[OK]", "Result: sent", "Result: dry_run", "success")
    for line in reversed(lines[-80:]):
        stripped = line.strip()
        if not stripped:
            continue
        if _is_error_log_line(stripped, ("ERROR", "Traceback", "[FAIL]", "failed with code", "Exception")):
            return False
        if any(word in stripped for word in success_words):
            return True
    return False


def format_trade_date(value: str | None) -> str:
    if value and len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value or "未知"


def collect_workspace_snapshot(project_root: Path | None = None) -> WorkspaceSnapshot:
    root = Path(project_root) if project_root is not None else PROJECT_ROOT

    futures_report_dir = report_system_dir(root)
    downloader_dir = data_downloader_dir(root)
    runtime_dir = desktop_runtime_dir(root)
    reports_dir = futures_report_dir / "reports"
    report_logs_dir = futures_report_dir / "logs"
    downloader_logs_dir = downloader_dir / "logs"

    config_paths = [
        futures_report_dir / ".env",
        futures_report_dir / ".env.example",
        futures_report_dir / "recipients.csv",
        futures_report_dir / "night_sessions.csv",
        downloader_dir / ".env",
        downloader_dir / "requirements.txt",
    ]
    script_paths = [
        futures_report_dir / "auto_report_daemon.py",
        futures_report_dir / "auto_report_once.py",
        futures_report_dir / "health_check.py",
        futures_report_dir / "maintenance.py",
        downloader_dir / "daily_update.py",
        downloader_dir / "auto_futures_downloader.py",
    ]

    database = database_status(root / "data" / "futures.db")
    trade_date = latest_trade_date(database.path)
    recent_reports = latest_files(reports_dir, patterns=("*.pdf", "*.html", "*.md"), limit=10)
    report_logs = latest_files(report_logs_dir, patterns=("*.log", "*.txt"), limit=8)
    downloader_logs = latest_files(downloader_logs_dir, patterns=("*.log", "*.txt"), limit=8)

    return WorkspaceSnapshot(
        project_root=root,
        database=database,
        reports_dir=directory_status(reports_dir),
        report_logs_dir=directory_status(report_logs_dir),
        downloader_logs_dir=directory_status(downloader_logs_dir),
        recent_reports=recent_reports,
        recent_logs=report_logs + downloader_logs,
        config_files=[file_status(path) for path in config_paths],
        script_files=[file_status(path) for path in script_paths],
        recipients_count=count_recipients(futures_report_dir / "recipients.csv"),
        latest_trade_date=trade_date,
        data_status=data_status(database, trade_date),
        report_status=latest_report_status(reports_dir, trade_date),
        mail_status=latest_email_status(database.path),
        recent_error=detect_recent_error([report_logs_dir, downloader_logs_dir, runtime_dir]),
        collected_at=datetime.now(),
    )


def _looks_like_header(row: list[str]) -> bool:
    normalized = {cell.strip().lower() for cell in row}
    return bool(normalized & {"email", "邮箱", "recipient", "name", "收件人"})

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from desktop.project_paths import data_downloader_dir, desktop_runtime_dir, report_system_dir


@dataclass(frozen=True)
class LogFileItem:
    path: Path
    category: str
    subcategory: str
    modified_at: datetime | None
    size_bytes: int


@dataclass(frozen=True)
class LogErrorItem:
    path: Path
    category: str
    line: str
    modified_at: datetime | None


ERROR_WORDS = ("ERROR", "Traceback", "[FAIL]", "Exception", "failed with code", "失败")


def discover_log_files(project_root: Path, limit: int = 200) -> list[LogFileItem]:
    root = Path(project_root)
    targets = [
        ("报告系统", report_system_dir(root) / "logs"),
        ("数据下载", data_downloader_dir(root) / "logs"),
        ("桌面任务", desktop_runtime_dir(root)),
    ]
    items: list[LogFileItem] = []
    for category, log_root in targets:
        if not log_root.exists():
            continue
        for path in log_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in (".log", ".txt", ".json"):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            subcategory = _subcategory(path, log_root)
            items.append(
                LogFileItem(
                    path=path,
                    category=category,
                    subcategory=subcategory,
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                    size_bytes=stat.st_size,
                )
            )
    return sorted(items, key=lambda item: item.modified_at or datetime.min, reverse=True)[:limit]


def scan_error_logs(project_root: Path, limit: int = 100) -> list[LogErrorItem]:
    errors: list[LogErrorItem] = []
    for item in discover_log_files(project_root, limit=limit):
        try:
            lines = item.path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in reversed(lines[-500:]):
            stripped = line.strip()
            if _is_error_line(stripped):
                errors.append(LogErrorItem(item.path, item.category, stripped, item.modified_at))
                break
    return errors


def read_log_file(path: Path, keyword: str = "", max_lines: int = 300) -> str:
    path = Path(path)
    if not path.exists():
        return "日志文件不存在。"
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as exc:
        return f"读取失败：{exc}"
    if keyword.strip():
        key = keyword.strip().lower()
        lines = [line for line in lines if key in line.lower()]
    lines = lines[-max_lines:]
    return "\n".join(lines) if lines else "没有匹配的日志内容。"


def _subcategory(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return ""
    return relative.parts[0] if len(relative.parts) > 1 else ""


def _is_error_line(line: str) -> bool:
    if not line:
        return False
    if line.startswith("[OK]") or line.startswith("[INFO]"):
        return False
    return any(word in line for word in ERROR_WORDS)

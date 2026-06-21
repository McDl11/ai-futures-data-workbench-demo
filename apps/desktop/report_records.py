from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from desktop.actions import ActionResult


GENERATION_STATUS_SUCCESS = "success"
GENERATION_STATUS_FAILED = "failed"
QUALITY_STATUS_PASSED = "passed"
QUALITY_STATUS_FAILED = "failed"
QUALITY_STATUS_NOT_CHECKED = "not_checked"


def record_report_generation(
    project_root: Path,
    trade_date: str,
    report_type: str,
    generation_status: str,
    html_path: Path | str | None = None,
    pdf_path: Path | str | None = None,
    md_path: Path | str | None = None,
    quality_status: str | None = None,
    quality_detail: str = "",
    output: str = "",
    error: str = "",
) -> ActionResult:
    checked_quality_status, checked_quality_detail = _quality_result(
        generation_status=generation_status,
        html_path=_optional_path(html_path),
        pdf_path=_optional_path(pdf_path),
        md_path=_optional_path(md_path),
        quality_status=quality_status,
        quality_detail=quality_detail,
    )
    db_path = _db_path(project_root)
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(db_path)) as conn:
            _ensure_schema(conn)
            conn.execute(
                """
                insert into report_generation_history (
                    trade_date, report_type, generation_status,
                    html_path, pdf_path, md_path, report_dir,
                    quality_status, quality_detail,
                    generated_at, recorded_at, output, error
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(trade_date or ""),
                    _normalize_report_type(report_type),
                    str(generation_status or GENERATION_STATUS_FAILED),
                    _path_text(html_path),
                    _path_text(pdf_path),
                    _path_text(md_path),
                    _report_dir_text(html_path, pdf_path, md_path),
                    checked_quality_status,
                    checked_quality_detail,
                    _now_text(),
                    _now_text(),
                    _trim_output(output),
                    _trim_output(error),
                ),
            )
            conn.commit()
    except sqlite3.Error as exc:
        return ActionResult(False, f"报告记录写入失败：{exc}")
    return ActionResult(True, "报告记录已写入。")


def load_report_generation_history(project_root: Path, limit: int = 100) -> list[dict[str, object]]:
    db_path = _db_path(project_root)
    if not db_path.exists():
        return []
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            _ensure_schema(conn)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                select id, trade_date, report_type, generation_status,
                       html_path, pdf_path, md_path, report_dir,
                       quality_status, quality_detail,
                       generated_at, recorded_at, output, error
                from report_generation_history
                order by id desc
                limit ?
                """,
                (limit,),
            ).fetchall()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists report_generation_history (
            id integer primary key autoincrement,
            trade_date text not null,
            report_type text not null,
            generation_status text not null,
            html_path text,
            pdf_path text,
            md_path text,
            report_dir text,
            quality_status text not null,
            quality_detail text,
            generated_at text not null,
            recorded_at text not null,
            output text,
            error text
        )
        """
    )
    conn.execute(
        """
        create index if not exists idx_report_generation_history_date_type
        on report_generation_history (trade_date, report_type, recorded_at)
        """
    )


def _quality_result(
    generation_status: str,
    html_path: Path | None,
    pdf_path: Path | None,
    md_path: Path | None,
    quality_status: str | None,
    quality_detail: str,
) -> tuple[str, str]:
    if quality_status:
        return quality_status, quality_detail
    if generation_status != GENERATION_STATUS_SUCCESS:
        return QUALITY_STATUS_NOT_CHECKED, quality_detail or "生成未成功，未执行文件质检。"

    missing: list[str] = []
    empty: list[str] = []
    for label, path in (("HTML", html_path), ("PDF", pdf_path), ("Markdown", md_path)):
        if path is None or not path.exists():
            missing.append(label)
            continue
        if path.stat().st_size <= 0:
            empty.append(label)

    if missing or empty:
        parts: list[str] = []
        if missing:
            parts.append("缺少文件：" + "、".join(missing))
        if empty:
            parts.append("空文件：" + "、".join(empty))
        return QUALITY_STATUS_FAILED, "；".join(parts)
    return QUALITY_STATUS_PASSED, quality_detail or "HTML、PDF、Markdown 文件齐全。"


def _optional_path(value: Path | str | None) -> Path | None:
    if value in (None, ""):
        return None
    return Path(value)


def _path_text(value: Path | str | None) -> str:
    path = _optional_path(value)
    return "" if path is None else str(path)


def _report_dir_text(*paths: Path | str | None) -> str:
    for value in paths:
        path = _optional_path(value)
        if path is not None:
            return str(path.parent)
    return ""


def _db_path(project_root: Path) -> Path:
    return Path(project_root) / "data" / "futures.db"


def _normalize_report_type(report_type: str) -> str:
    value = str(report_type or "").strip().lower()
    return value if value in {"white", "daily", "morning"} else "daily"


def _trim_output(value: str, limit: int = 4000) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

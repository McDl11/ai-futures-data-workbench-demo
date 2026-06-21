from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path

from desktop.actions import ActionResult


TASK_STATUS_SUCCESS = "success"
TASK_STATUS_FAILED = "failed"


def record_task_run(
    project_root: Path,
    task_type: str,
    task_name: str,
    status: str,
    target_date: str = "",
    detail: str = "",
    output: str = "",
    error: str = "",
) -> ActionResult:
    db_path = _db_path(project_root)
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(db_path)) as conn:
            _ensure_schema(conn)
            conn.execute(
                """
                insert into task_run_history (
                    task_type, task_name, status, target_date, detail,
                    started_at, finished_at, duration_seconds, output, error
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_type,
                    task_name,
                    status,
                    target_date,
                    detail,
                    "",
                    _now_text(),
                    None,
                    _trim_output(output),
                    _trim_output(error),
                ),
            )
            conn.commit()
    except sqlite3.Error as exc:
        return ActionResult(False, f"任务记录写入失败：{exc}")
    return ActionResult(True, "任务记录已写入。")


def run_and_record(
    project_root: Path,
    task_type: str,
    task_name: str,
    target_date: str,
    detail: str,
    fn: Callable[[], ActionResult],
) -> ActionResult:
    started_at = _now_text()
    started_time = datetime.now()
    try:
        result = fn()
    except Exception as exc:
        result = ActionResult(False, f"执行失败：{exc}")
    duration_seconds = (datetime.now() - started_time).total_seconds()
    _record_task_result(
        project_root=project_root,
        task_type=task_type,
        task_name=task_name,
        status=TASK_STATUS_SUCCESS if result.ok else TASK_STATUS_FAILED,
        target_date=target_date,
        detail=detail,
        started_at=started_at,
        duration_seconds=duration_seconds,
        output=result.output,
        error="" if result.ok else result.message,
    )
    return result


def load_task_run_history(project_root: Path, limit: int = 100) -> list[dict[str, object]]:
    db_path = _db_path(project_root)
    if not db_path.exists():
        return []
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            _ensure_schema(conn)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                select id, task_type, task_name, status, target_date, detail,
                       started_at, finished_at, duration_seconds, output, error
                from task_run_history
                order by id desc
                limit ?
                """,
                (limit,),
            ).fetchall()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def _record_task_result(
    project_root: Path,
    task_type: str,
    task_name: str,
    status: str,
    target_date: str,
    detail: str,
    started_at: str,
    duration_seconds: float,
    output: str,
    error: str,
) -> ActionResult:
    db_path = _db_path(project_root)
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(db_path)) as conn:
            _ensure_schema(conn)
            conn.execute(
                """
                insert into task_run_history (
                    task_type, task_name, status, target_date, detail,
                    started_at, finished_at, duration_seconds, output, error
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_type,
                    task_name,
                    status,
                    target_date,
                    detail,
                    started_at,
                    _now_text(),
                    round(duration_seconds, 3),
                    _trim_output(output),
                    _trim_output(error),
                ),
            )
            conn.commit()
    except sqlite3.Error as exc:
        return ActionResult(False, f"任务记录写入失败：{exc}")
    return ActionResult(True, "任务记录已写入。")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists task_run_history (
            id integer primary key autoincrement,
            task_type text not null,
            task_name text not null,
            status text not null,
            target_date text,
            detail text,
            started_at text,
            finished_at text not null,
            duration_seconds real,
            output text,
            error text
        )
        """
    )
    conn.execute(
        """
        create index if not exists idx_task_run_history_type_time
        on task_run_history (task_type, finished_at)
        """
    )


def _db_path(project_root: Path) -> Path:
    return Path(project_root) / "data" / "futures.db"


def _trim_output(value: str, limit: int = 4000) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

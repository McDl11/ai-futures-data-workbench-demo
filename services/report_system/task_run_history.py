from __future__ import annotations

import sqlite3
from datetime import datetime

from config import DB_PATH


def record_task_run(
    task_type,
    task_name,
    status,
    target_date='',
    detail='',
    output='',
    error='',
    started_at='',
):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        ensure_schema(conn)
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
                target_date or '',
                detail or '',
                started_at or '',
                now_text(),
                None,
                trim(output),
                trim(error),
            ),
        )
        conn.commit()


def ensure_schema(conn):
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


def trim(value, limit=4000):
    return str(value or '').strip()[:limit]


def now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

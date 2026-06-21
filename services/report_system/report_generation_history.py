from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from config import DB_PATH


GENERATION_STATUS_SUCCESS = 'success'
GENERATION_STATUS_FAILED = 'failed'
QUALITY_STATUS_PASSED = 'passed'
QUALITY_STATUS_FAILED = 'failed'
QUALITY_STATUS_NOT_CHECKED = 'not_checked'


def record_report_generation(
    trade_date,
    report_type,
    generation_status,
    html_path=None,
    pdf_path=None,
    md_path=None,
    quality_status=None,
    quality_detail='',
    output='',
    error='',
):
    checked_quality_status, checked_quality_detail = quality_result(
        generation_status,
        optional_path(html_path),
        optional_path(pdf_path),
        optional_path(md_path),
        quality_status,
        quality_detail,
    )
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        ensure_schema(conn)
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
                str(trade_date or ''),
                normalize_report_type(report_type),
                str(generation_status or GENERATION_STATUS_FAILED),
                path_text(html_path),
                path_text(pdf_path),
                path_text(md_path),
                report_dir_text(html_path, pdf_path, md_path),
                checked_quality_status,
                checked_quality_detail,
                now_text(),
                now_text(),
                trim(output),
                trim(error),
            ),
        )
        conn.commit()


def ensure_schema(conn):
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


def quality_result(generation_status, html_path, pdf_path, md_path, quality_status, quality_detail):
    if quality_status:
        return quality_status, quality_detail
    if generation_status != GENERATION_STATUS_SUCCESS:
        return QUALITY_STATUS_NOT_CHECKED, quality_detail or '生成未成功，未执行文件质检。'

    missing = []
    empty = []
    for label, path in (('HTML', html_path), ('PDF', pdf_path), ('Markdown', md_path)):
        if path is None or not path.exists():
            missing.append(label)
            continue
        if path.stat().st_size <= 0:
            empty.append(label)

    if missing or empty:
        parts = []
        if missing:
            parts.append('缺少文件：' + '、'.join(missing))
        if empty:
            parts.append('空文件：' + '、'.join(empty))
        return QUALITY_STATUS_FAILED, '；'.join(parts)
    return QUALITY_STATUS_PASSED, quality_detail or 'HTML、PDF、Markdown 文件齐全。'


def optional_path(value):
    if value in (None, ''):
        return None
    return Path(value)


def path_text(value):
    path = optional_path(value)
    return '' if path is None else str(path)


def report_dir_text(*paths):
    for value in paths:
        path = optional_path(value)
        if path is not None:
            return str(path.parent)
    return ''


def normalize_report_type(report_type):
    value = str(report_type or '').strip().lower()
    return value if value in {'white', 'daily', 'morning'} else 'daily'


def trim(value, limit=4000):
    return str(value or '').strip()[:limit]


def now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

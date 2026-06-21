from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from desktop.actions import ActionResult, run_python_script
from desktop.project_paths import data_downloader_dir
from desktop.state import format_size, format_trade_date
from desktop.task_records import run_and_record


@dataclass(frozen=True)
class CoreTableSpec:
    table: str
    label: str
    date_column: str
    check_gaps: bool = True


@dataclass(frozen=True)
class CoreTableStatus:
    table: str
    label: str
    exists: bool
    row_count: int
    earliest_date: str | None
    latest_date: str | None
    gap_count: int | None
    gap_summary: str
    state: str


CORE_TABLES = [
    CoreTableSpec("trade_cal", "交易日历", "cal_date", False),
    CoreTableSpec("fut_daily", "日线行情", "trade_date", True),
    CoreTableSpec("fut_mapping", "主力映射", "trade_date", True),
    CoreTableSpec("fut_holding", "持仓排名", "trade_date", True),
    CoreTableSpec("fut_wsr", "仓单日报", "trade_date", True),
    CoreTableSpec("fut_settle", "结算参数", "trade_date", True),
    CoreTableSpec("ft_limit", "涨跌停板", "trade_date", True),
    CoreTableSpec("index_daily", "期货指数", "trade_date", True),
    CoreTableSpec("shibor", "SHIBOR", "date", False),
    CoreTableSpec("fx_daily", "汇率日线", "trade_date", False),
    CoreTableSpec("sge_daily", "黄金日线", "trade_date", False),
    CoreTableSpec("cn_cpi", "CPI", "month", False),
    CoreTableSpec("cn_ppi", "PPI", "month", False),
    CoreTableSpec("cn_pmi", "PMI", "month", False),
]
GAP_CHECK_TRADE_DAYS = 60
UPDATE_LOOKBACK_DAYS = 7
SCRIPT_ENV = {
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
}


def collect_core_table_statuses(
    db_path: Path,
    specs: list[CoreTableSpec] | None = None,
    today: str | None = None,
) -> list[CoreTableStatus]:
    db_path = Path(db_path)
    specs = specs or CORE_TABLES
    if not db_path.exists():
        return [_missing_database_status(spec) for spec in specs]

    conn = sqlite3.connect(db_path)
    try:
        calendar_dates = _open_trade_dates(conn)
        expected_latest = _latest_expected_trade_date(calendar_dates, today=today)
        return [_table_status(conn, spec, calendar_dates, expected_latest) for spec in specs]
    finally:
        conn.close()


def run_data_update(project_root: Path, runner=run_python_script, today: str | None = None) -> ActionResult:
    project_root = Path(project_root)
    start_date, end_date = plan_data_update_range(project_root / "data" / "futures.db", today=today)
    return _run_data_update_range(project_root, start_date, end_date, runner=runner)


def run_data_quick_update(project_root: Path, runner=run_python_script, today: str | None = None) -> ActionResult:
    project_root = Path(project_root)
    _start_date, end_date = plan_data_update_range(project_root / "data" / "futures.db", today=today)
    return _run_data_update_range(project_root, end_date, end_date, runner=runner)


def _run_data_update_range(
    project_root: Path,
    start_date: str | None,
    end_date: str | None,
    runner=run_python_script,
) -> ActionResult:
    args = ["--now"]
    if start_date and end_date:
        args.extend(["--start-date", start_date, "--end-date", end_date])

    downloader_dir = data_downloader_dir(Path(project_root))
    return run_and_record(
        project_root,
        task_type="data_update",
        task_name="数据更新",
        target_date=end_date or "",
        detail=_date_range_detail(start_date, end_date),
        fn=lambda: runner(
            downloader_dir,
            downloader_dir / "daily_update.py",
            args=args,
            timeout_seconds=1800,
            env=SCRIPT_ENV,
        ),
    )


def run_data_gap_repair(
    project_root: Path,
    gap_range: tuple[str, str] | None = None,
    runner=run_python_script,
) -> ActionResult:
    project_root = Path(project_root)
    selected_range = gap_range or find_recent_gap_range(project_root / "data" / "futures.db")
    if selected_range is None:
        return ActionResult(False, "最近缺口为空，无需补数据。")

    start_date, end_date = selected_range
    downloader_dir = data_downloader_dir(project_root)
    return run_and_record(
        project_root,
        task_type="data_update",
        task_name="补最近缺口",
        target_date=end_date,
        detail=_date_range_detail(start_date, end_date),
        fn=lambda: runner(
            downloader_dir,
            downloader_dir / "daily_update.py",
            args=["--now", "--start-date", start_date, "--end-date", end_date],
            timeout_seconds=1800,
            env=SCRIPT_ENV,
        ),
    )


def plan_data_update_range(db_path: Path, today: str | None = None) -> tuple[str | None, str | None]:
    today = today or datetime.now().strftime("%Y%m%d")
    yesterday = (datetime.strptime(today, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    latest_open = latest_open_trade_date(db_path, up_to=yesterday)
    if latest_open is None:
        return None, None
    start_date = (datetime.strptime(latest_open, "%Y%m%d") - timedelta(days=UPDATE_LOOKBACK_DAYS)).strftime("%Y%m%d")
    return start_date, latest_open


def latest_open_trade_date(db_path: Path, up_to: str | None = None) -> str | None:
    db_path = Path(db_path)
    if not db_path.exists():
        return up_to

    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "trade_cal") or not _column_exists(conn, "trade_cal", "cal_date"):
            return up_to
        where = "where cal_date <= ?" if up_to else ""
        params = (up_to,) if up_to else ()
        open_filter = ""
        if _column_exists(conn, "trade_cal", "is_open"):
            open_filter = " and cast(is_open as text) = '1'" if where else "where cast(is_open as text) = '1'"
        row = conn.execute(
            f"select max(cal_date) from trade_cal {where}{open_filter}",
            params,
        ).fetchone()
        return str(row[0]) if row and row[0] else up_to
    finally:
        conn.close()


def find_recent_gap_range(
    db_path: Path,
    specs: list[CoreTableSpec] | None = None,
    today: str | None = None,
) -> tuple[str, str] | None:
    db_path = Path(db_path)
    specs = specs or CORE_TABLES
    if not db_path.exists():
        return None

    conn = sqlite3.connect(db_path)
    try:
        calendar_dates = _open_trade_dates(conn)
        expected_latest = _latest_expected_trade_date(calendar_dates, today=today)
        missing_dates: set[str] = set()
        for spec in specs:
            if not spec.check_gaps or not _table_exists(conn, spec.table) or not _column_exists(conn, spec.table, spec.date_column):
                continue
            earliest, latest = _date_range(conn, spec.table, spec.date_column)
            missing_dates.update(
                _missing_trade_dates(
                    conn,
                    spec.table,
                    spec.date_column,
                    calendar_dates,
                    earliest,
                    latest,
                    expected_latest,
                )
            )
    finally:
        conn.close()

    if not missing_dates:
        return None
    ordered = sorted(missing_dates)
    return ordered[0], ordered[-1]


def database_detail(db_path: Path, project_root: Path | None = None) -> str:
    db_path = Path(db_path)
    if project_root is not None:
        display_path = _display_path(db_path, project_root)
        if not db_path.exists():
            return display_path
        try:
            return f"{display_path} · {format_size(db_path.stat().st_size)}"
        except OSError:
            return display_path
    if not db_path.exists():
        return str(db_path)
    try:
        return f"{db_path} · {format_size(db_path.stat().st_size)}"
    except OSError:
        return str(db_path)


def _missing_database_status(spec: CoreTableSpec) -> CoreTableStatus:
    return CoreTableStatus(
        table=spec.table,
        label=spec.label,
        exists=False,
        row_count=0,
        earliest_date=None,
        latest_date=None,
        gap_count=None,
        gap_summary="数据库不存在",
        state="warning",
    )


def _table_status(
    conn: sqlite3.Connection,
    spec: CoreTableSpec,
    calendar_dates: list[str],
    expected_latest: str | None,
) -> CoreTableStatus:
    if not _table_exists(conn, spec.table):
        return CoreTableStatus(
            table=spec.table,
            label=spec.label,
            exists=False,
            row_count=0,
            earliest_date=None,
            latest_date=None,
            gap_count=None,
            gap_summary="表不存在",
            state="warning",
        )

    if not _column_exists(conn, spec.table, spec.date_column):
        row_count = _count_rows(conn, spec.table)
        return CoreTableStatus(
            table=spec.table,
            label=spec.label,
            exists=True,
            row_count=row_count,
            earliest_date=None,
            latest_date=None,
            gap_count=None,
            gap_summary=f"缺少日期字段 {spec.date_column}",
            state="warning",
        )

    row_count = _count_rows(conn, spec.table)
    earliest, latest = _date_range(conn, spec.table, spec.date_column)
    if row_count <= 0:
        return CoreTableStatus(
            table=spec.table,
            label=spec.label,
            exists=True,
            row_count=0,
            earliest_date=earliest,
            latest_date=latest,
            gap_count=None,
            gap_summary="空表",
            state="warning",
        )

    if not spec.check_gaps:
        return CoreTableStatus(
            table=spec.table,
            label=spec.label,
            exists=True,
            row_count=row_count,
            earliest_date=earliest,
            latest_date=latest,
            gap_count=None,
            gap_summary="不按交易日检查",
            state="ok",
        )

    missing = _missing_trade_dates(
        conn,
        spec.table,
        spec.date_column,
        calendar_dates,
        earliest,
        latest,
        expected_latest,
    )
    return CoreTableStatus(
        table=spec.table,
        label=spec.label,
        exists=True,
        row_count=row_count,
        earliest_date=earliest,
        latest_date=latest,
        gap_count=len(missing),
        gap_summary=_gap_summary(missing),
        state="ok" if not missing else "warning",
    )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type='table' and name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return column in {row[1] for row in conn.execute(f"pragma table_info({_quote_name(table)})")}


def _count_rows(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"select count(*) from {_quote_name(table)}").fetchone()[0])


def _date_range(conn: sqlite3.Connection, table: str, date_column: str) -> tuple[str | None, str | None]:
    row = conn.execute(
        f"select min({_quote_name(date_column)}), max({_quote_name(date_column)}) from {_quote_name(table)}"
    ).fetchone()
    if not row:
        return None, None
    return (str(row[0]) if row[0] else None, str(row[1]) if row[1] else None)


def _open_trade_dates(conn: sqlite3.Connection) -> list[str]:
    if not _table_exists(conn, "trade_cal") or not _column_exists(conn, "trade_cal", "cal_date"):
        return []
    where = ""
    if _column_exists(conn, "trade_cal", "is_open"):
        where = " where cast(is_open as text) = '1'"
    rows = conn.execute(
        f"select distinct cal_date from trade_cal{where} order by cal_date"
    ).fetchall()
    return [str(row[0]) for row in rows if row[0]]


def _latest_expected_trade_date(calendar_dates: list[str], today: str | None = None) -> str | None:
    if not calendar_dates:
        return None
    today = today or datetime.now().strftime("%Y%m%d")
    yesterday = (datetime.strptime(today, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    past_dates = [date for date in calendar_dates if date <= yesterday]
    return past_dates[-1] if past_dates else None


def _missing_trade_dates(
    conn: sqlite3.Connection,
    table: str,
    date_column: str,
    calendar_dates: list[str],
    earliest: str | None,
    latest: str | None,
    expected_latest: str | None = None,
) -> list[str]:
    if not calendar_dates or not earliest:
        return []

    check_until = expected_latest or latest
    if not check_until:
        return []

    expected = [date for date in calendar_dates if earliest <= date <= check_until]
    expected = expected[-GAP_CHECK_TRADE_DAYS:]
    if not expected:
        return []

    rows = conn.execute(
        f"""
        select distinct {_quote_name(date_column)}
        from {_quote_name(table)}
        where {_quote_name(date_column)} between ? and ?
        """,
        (expected[0], expected[-1]),
    ).fetchall()
    actual = {str(row[0]) for row in rows if row[0]}
    return [date for date in expected if date not in actual]


def _gap_summary(missing: list[str]) -> str:
    if not missing:
        return "无缺口"
    preview = "、".join(format_trade_date(date) for date in missing[:5])
    if len(missing) > 5:
        preview += f" 等 {len(missing)} 天"
    return preview


def _date_range_detail(start_date: str | None, end_date: str | None) -> str:
    if start_date and end_date:
        return f"{start_date}~{end_date}"
    return ""


def _quote_name(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return str(Path(path).relative_to(Path(project_root)))
    except ValueError:
        return str(path)

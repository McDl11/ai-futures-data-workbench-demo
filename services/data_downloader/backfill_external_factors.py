"""
Backfill external explanatory factors for the futures daily report.

Data written:
  - futures_data/12_外部因子/shibor_all.csv       -> SQLite table shibor
  - futures_data/12_外部因子/fx_daily_all.csv     -> SQLite table fx_daily
  - futures_data/12_外部因子/sge_daily_all.csv    -> SQLite table sge_daily
  - futures_data/13_宏观数据/cn_cpi_all.csv       -> SQLite table cn_cpi
  - futures_data/13_宏观数据/cn_ppi_all.csv       -> SQLite table cn_ppi
  - futures_data/13_宏观数据/cn_pmi_all.csv       -> SQLite table cn_pmi

Usage:
  python backfill_external_factors.py --start 20100101 --end 20260612
  python backfill_external_factors.py --start 20260601 --end 20260612 --only shibor fx_daily
  python backfill_external_factors.py --start-m 202001 --end-m 202606 --only cn_cpi cn_ppi cn_pmi
"""

import argparse
import os
import sqlite3
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from import_csv_to_sqlite import upsert_dataframe


BASE_DIR = Path(__file__).resolve().parent


def find_project_root(start):
    for path in (Path(start).resolve(), *Path(start).resolve().parents):
        if (path / 'AI金融数据工作台进化规划.md').exists():
            return path
        if (path / 'apps').exists() and (path / 'services').exists() and (path / 'data').exists():
            return path
    return Path(start).resolve().parent


PROJECT_ROOT = find_project_root(BASE_DIR)
OUTPUT = BASE_DIR / 'futures_data'


def resolve_project_path(value, default):
    path = Path(value) if value else default
    return path if path.is_absolute() else PROJECT_ROOT / path


DB_DIR = resolve_project_path(os.getenv('FUTURES_DATA_DIR'), PROJECT_ROOT / 'data')
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / 'futures.db'
EXTERNAL_DIR = OUTPUT / '12_外部因子'
MACRO_DIR = OUTPUT / '13_宏观数据'

load_dotenv(BASE_DIR / '.env')
TOKEN = os.getenv('TUSHARE_TOKEN')
HTTP_URL = os.getenv('TUSHARE_HTTP_URL', 'http://jiaoch.site')

import tushare as ts

pro = ts.pro_api(TOKEN)
pro._DataApi__token = TOKEN
pro._DataApi__http_url = HTTP_URL


class RateLimiter:
    def __init__(self, max_calls=200):
        self.max_calls = max_calls
        self._timestamps = deque()

    def wait(self):
        now = time.time()
        cutoff = now - 60
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        if len(self._timestamps) >= self.max_calls:
            time.sleep(self._timestamps[0] - cutoff + 0.1)
            now = time.time()
            cutoff = now - 60
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
        self._timestamps.append(time.time())


limiter = RateLimiter(200)


DATASETS = {
    'shibor': {
        'file': EXTERNAL_DIR / 'shibor_all.csv',
        'table': 'shibor',
        'dedup': ['date'],
        'call': lambda start, end: pro.shibor(start_date=start, end_date=end),
    },
    'fx_daily': {
        'file': EXTERNAL_DIR / 'fx_daily_all.csv',
        'table': 'fx_daily',
        'dedup': ['ts_code', 'trade_date'],
        'call': lambda start, end: pro.fx_daily(
            ts_code='USDCNH.FXCM',
            start_date=start,
            end_date=end,
        ),
    },
    'sge_daily': {
        'file': EXTERNAL_DIR / 'sge_daily_all.csv',
        'table': 'sge_daily',
        'dedup': ['ts_code', 'trade_date'],
        'call': lambda start, end: pro.sge_daily(start_date=start, end_date=end),
    },
    'cn_cpi': {
        'file': MACRO_DIR / 'cn_cpi_all.csv',
        'table': 'cn_cpi',
        'dedup': ['month'],
        'call': lambda start_m, end_m: pro.cn_cpi(start_m=start_m, end_m=end_m),
        'date_type': 'month',
    },
    'cn_ppi': {
        'file': MACRO_DIR / 'cn_ppi_all.csv',
        'table': 'cn_ppi',
        'dedup': ['month'],
        'call': lambda start_m, end_m: pro.cn_ppi(start_m=start_m, end_m=end_m),
        'date_type': 'month',
    },
    'cn_pmi': {
        'file': MACRO_DIR / 'cn_pmi_all.csv',
        'table': 'cn_pmi',
        'dedup': ['month'],
        'call': lambda start_m, end_m: pro.cn_pmi(start_m=start_m, end_m=end_m),
        'date_type': 'month',
    },
}


def log(message):
    print(f'[{datetime.now().strftime("%H:%M:%S")}] {message}', flush=True)


def iter_years(start, end):
    fmt = '%Y%m%d'
    cur = datetime.strptime(start, fmt)
    last = datetime.strptime(end, fmt)
    while cur <= last:
        year_end = min(cur.replace(month=12, day=31), last)
        yield cur.strftime(fmt), year_end.strftime(fmt)
        cur = year_end + timedelta(days=1)


def iter_months(start, end):
    fmt = '%Y%m%d'
    cur = datetime.strptime(start, fmt)
    last = datetime.strptime(end, fmt)
    while cur <= last:
        if cur.month == 12:
            next_month = cur.replace(year=cur.year + 1, month=1, day=1)
        else:
            next_month = cur.replace(month=cur.month + 1, day=1)
        month_end = min(next_month - timedelta(days=1), last)
        yield cur.strftime(fmt), month_end.strftime(fmt)
        cur = month_end + timedelta(days=1)


def iter_month_codes(start_m, end_m):
    cur_year = int(start_m[:4])
    cur_month = int(start_m[4:6])
    end_year = int(end_m[:4])
    end_month = int(end_m[4:6])
    while (cur_year, cur_month) <= (end_year, end_month):
        yield f'{cur_year:04d}{cur_month:02d}', f'{cur_year:04d}{cur_month:02d}'
        cur_month += 1
        if cur_month == 13:
            cur_year += 1
            cur_month = 1


def iter_year_month_ranges(start_m, end_m):
    cur_year = int(start_m[:4])
    end_year = int(end_m[:4])
    while cur_year <= end_year:
        chunk_start = start_m if cur_year == int(start_m[:4]) else f'{cur_year:04d}01'
        chunk_end = end_m if cur_year == end_year else f'{cur_year:04d}12'
        yield chunk_start, chunk_end
        cur_year += 1


def normalize_case_columns(df):
    if df is None or df.empty:
        return df
    normalized = df.copy()
    normalized.columns = [str(col).strip().lower() for col in normalized.columns]
    if not normalized.columns.duplicated().any():
        return normalized

    result = pd.DataFrame(index=normalized.index)
    seen = []
    for col in normalized.columns:
        if col in seen:
            continue
        seen.append(col)
        same_cols = normalized.loc[:, normalized.columns == col]
        result[col] = same_cols.bfill(axis=1).iloc[:, 0]
    return result


def safe_call(name, start, end):
    cfg = DATASETS[name]
    for attempt in range(3):
        try:
            limiter.wait()
            df = cfg['call'](start, end)
            return df if df is not None and not df.empty else pd.DataFrame()
        except Exception as exc:
            if attempt == 2:
                log(f'[FAIL] {name} {start}~{end}: {exc}')
                return pd.DataFrame()
            time.sleep(5 * (attempt + 1))
    return pd.DataFrame()


def merge_save(df_new, csv_path, dedup_cols):
    if df_new is None or df_new.empty:
        return 0, 0

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df_new = df_new.astype(object).where(pd.notna(df_new), None)

    if csv_path.exists():
        df_old = pd.read_csv(csv_path, dtype=str)
        common_cols = [c for c in df_new.columns if c in df_old.columns]
        if common_cols:
            combined = pd.concat([df_old[common_cols], df_new[common_cols]], ignore_index=True)
        else:
            combined = pd.concat([df_old, df_new], ignore_index=True)
    else:
        combined = df_new

    existing_dedup = [c for c in dedup_cols if c in combined.columns]
    if existing_dedup:
        for col in existing_dedup:
            combined[col] = combined[col].astype(str)
        combined = combined.drop_duplicates(subset=existing_dedup, keep='last')

    combined.to_csv(csv_path, index=False, encoding='utf-8-sig')
    return len(df_new), len(combined)


def upsert_sqlite(table, df):
    if df is None or df.empty:
        return 0
    if not DB_PATH.exists():
        log(f'[SQL] skip, database not found: {DB_PATH}')
        return 0
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        return upsert_dataframe(conn, table, df)


def backfill_dataset(name, start, end):
    cfg = DATASETS[name]
    frames = []
    total_downloaded = 0

    if cfg.get('date_type') == 'month':
        chunks = iter_year_month_ranges(start, end)
    elif name == 'sge_daily':
        chunks = iter_months(start, end)
    else:
        chunks = iter_years(start, end)

    for chunk_start, chunk_end in chunks:
        df = safe_call(name, chunk_start, chunk_end)
        if name == 'cn_pmi':
            df = normalize_case_columns(df)
        rows = len(df)
        total_downloaded += rows
        log(f'{name} {chunk_start}~{chunk_end}: {rows} rows')
        if not df.empty:
            frames.append(df)

    if not frames:
        log(f'{name}: no data')
        return 0, 0, 0

    result = pd.concat(frames, ignore_index=True)
    new_rows, file_rows = merge_save(result, cfg['file'], cfg['dedup'])
    sql_rows = upsert_sqlite(cfg['table'], result)
    log(f'{name}: downloaded={total_downloaded}, csv_rows={file_rows}, sql_upsert={sql_rows}')
    return total_downloaded, file_rows, sql_rows


def main():
    parser = argparse.ArgumentParser(description='Backfill futures external factors')
    parser.add_argument('--start', default=None, help='YYYYMMDD for daily datasets')
    parser.add_argument('--end', default=None, help='YYYYMMDD for daily datasets')
    parser.add_argument('--start-m', default=None, help='YYYYMM for monthly macro datasets')
    parser.add_argument('--end-m', default=None, help='YYYYMM for monthly macro datasets')
    parser.add_argument(
        '--only',
        nargs='+',
        choices=sorted(DATASETS),
        default=sorted(DATASETS),
        help='datasets to backfill',
    )
    args = parser.parse_args()

    daily_names = [name for name in args.only if DATASETS[name].get('date_type') != 'month']
    monthly_names = [name for name in args.only if DATASETS[name].get('date_type') == 'month']
    if daily_names and (not args.start or not args.end):
        parser.error('--start and --end are required for daily datasets')
    if monthly_names and (not args.start_m or not args.end_m):
        if args.start and args.end:
            args.start_m = args.start[:6]
            args.end_m = args.end[:6]
        else:
            parser.error('--start-m and --end-m are required for monthly macro datasets')

    log(f'external factors backfill datasets={",".join(args.only)}')
    results = {}
    for name in args.only:
        if DATASETS[name].get('date_type') == 'month':
            results[name] = backfill_dataset(name, args.start_m, args.end_m)
        else:
            results[name] = backfill_dataset(name, args.start, args.end)

    log('done')
    for name, (downloaded, file_rows, sql_rows) in results.items():
        log(f'  {name}: downloaded={downloaded}, csv_rows={file_rows}, sql_upsert={sql_rows}')


if __name__ == '__main__':
    main()

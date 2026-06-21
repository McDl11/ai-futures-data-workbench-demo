"""
Import futures CSV files into SQLite.

The CSV files remain as backups/exports. The SQLite database is the faster
query layer for daily reports and future incremental updates.

Usage:
  python import_csv_to_sqlite.py
"""

from pathlib import Path
import os
import sqlite3

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent


def find_project_root(start):
    for path in (Path(start).resolve(), *Path(start).resolve().parents):
        if (path / 'AI金融数据工作台进化规划.md').exists():
            return path
        if (path / 'apps').exists() and (path / 'services').exists() and (path / 'data').exists():
            return path
    return Path(start).resolve().parent


PROJECT_ROOT = find_project_root(BASE_DIR)
DATA_DIR = BASE_DIR / 'futures_data'


def resolve_project_path(value, default):
    path = Path(value) if value else default
    return path if path.is_absolute() else PROJECT_ROOT / path


DB_DIR = resolve_project_path(os.getenv('FUTURES_DATA_DIR'), PROJECT_ROOT / 'data')
DB_PATH = DB_DIR / 'futures.db'


TABLES = [
    {
        'table': 'fut_basic',
        'csv': DATA_DIR / '01_合约列表' / 'fut_basic_all.csv',
        'unique': ['ts_code', 'exchange'],
        'indexes': [['fut_code'], ['symbol'], ['exchange']],
    },
    {
        'table': 'trade_cal',
        'csv': DATA_DIR / '02_交易日历' / 'trade_cal_futures.csv',
        'unique': ['exchange', 'cal_date'],
        'indexes': [['cal_date'], ['exchange', 'is_open']],
    },
    {
        'table': 'fut_daily',
        'csv': DATA_DIR / '03_日线行情' / 'fut_daily_all.csv',
        'unique': ['ts_code', 'trade_date'],
        'indexes': [['trade_date'], ['ts_code'], ['ts_code', 'trade_date']],
    },
    {
        'table': 'fut_weekly_monthly',
        'csv': DATA_DIR / '04_周月线' / 'fut_weekly_monthly_all.csv',
        'unique': ['ts_code', 'trade_date', 'freq'],
        'indexes': [['trade_date'], ['ts_code'], ['freq']],
    },
    {
        'table': 'fut_holding',
        'csv': DATA_DIR / '05_持仓排名' / 'fut_holding_all.csv',
        'unique': ['trade_date', 'symbol', 'broker'],
        'indexes': [['trade_date'], ['symbol'], ['broker'], ['symbol', 'trade_date']],
    },
    {
        'table': 'fut_wsr',
        'csv': DATA_DIR / '06_仓单日报' / 'fut_wsr_all.csv',
        'unique': ['trade_date', 'symbol', 'warehouse'],
        'indexes': [['trade_date'], ['symbol'], ['symbol', 'trade_date']],
    },
    {
        'table': 'fut_settle',
        'csv': DATA_DIR / '07_结算参数' / 'fut_settle_all.csv',
        'unique': ['ts_code', 'trade_date'],
        'indexes': [['trade_date'], ['ts_code'], ['ts_code', 'trade_date']],
    },
    {
        'table': 'ft_limit',
        'csv': DATA_DIR / '08_涨跌停板' / 'ft_limit_all.csv',
        'unique': ['ts_code', 'trade_date'],
        'indexes': [['trade_date'], ['ts_code'], ['exchange']],
    },
    {
        'table': 'fut_weekly_detail',
        'csv': DATA_DIR / '09_周度明细' / 'fut_weekly_detail_all.csv',
        'unique': ['exchange', 'prd', 'week_date'],
        'indexes': [['week_date'], ['exchange'], ['prd']],
    },
    {
        'table': 'fut_mapping',
        'csv': DATA_DIR / '10_主力映射' / 'fut_mapping_all.csv',
        'unique': ['ts_code', 'trade_date'],
        'indexes': [['trade_date'], ['ts_code'], ['mapping_ts_code']],
    },
    {
        'table': 'index_daily',
        'csv': DATA_DIR / '11_期货指数' / 'index_daily_all.csv',
        'unique': ['ts_code', 'trade_date'],
        'indexes': [['trade_date'], ['ts_code']],
    },
    {
        'table': 'shibor',
        'csv': DATA_DIR / '12_外部因子' / 'shibor_all.csv',
        'unique': ['date'],
        'indexes': [['date']],
    },
    {
        'table': 'fx_daily',
        'csv': DATA_DIR / '12_外部因子' / 'fx_daily_all.csv',
        'unique': ['ts_code', 'trade_date'],
        'indexes': [['trade_date'], ['ts_code'], ['ts_code', 'trade_date']],
    },
    {
        'table': 'sge_daily',
        'csv': DATA_DIR / '12_外部因子' / 'sge_daily_all.csv',
        'unique': ['ts_code', 'trade_date'],
        'indexes': [['trade_date'], ['ts_code'], ['ts_code', 'trade_date']],
    },
    {
        'table': 'cn_cpi',
        'csv': DATA_DIR / '13_宏观数据' / 'cn_cpi_all.csv',
        'unique': ['month'],
        'indexes': [['month']],
    },
    {
        'table': 'cn_ppi',
        'csv': DATA_DIR / '13_宏观数据' / 'cn_ppi_all.csv',
        'unique': ['month'],
        'indexes': [['month']],
    },
    {
        'table': 'cn_pmi',
        'csv': DATA_DIR / '13_宏观数据' / 'cn_pmi_all.csv',
        'unique': ['month'],
        'indexes': [['month']],
    },
]


def quote_name(name):
    return '"' + name.replace('"', '""') + '"'


def load_columns(csv_path):
    return pd.read_csv(csv_path, nrows=0).columns.tolist()


def create_table(conn, table, columns, unique_cols):
    col_defs = ', '.join(f'{quote_name(c)} TEXT' for c in columns)
    existing_unique = [c for c in unique_cols if c in columns]
    if existing_unique:
        unique_def = ', UNIQUE (' + ', '.join(quote_name(c) for c in existing_unique) + ')'
    else:
        unique_def = ''
    conn.execute(f'DROP TABLE IF EXISTS {quote_name(table)}')
    conn.execute(f'CREATE TABLE {quote_name(table)} ({col_defs}{unique_def})')


def create_indexes(conn, table, columns, indexes):
    available = set(columns)
    for idx_cols in indexes:
        existing = [c for c in idx_cols if c in available]
        if not existing:
            continue
        idx_name = f'idx_{table}_' + '_'.join(existing)
        sql = (
            f'CREATE INDEX IF NOT EXISTS {quote_name(idx_name)} '
            f'ON {quote_name(table)} ({", ".join(quote_name(c) for c in existing)})'
        )
        conn.execute(sql)


def insert_chunk(conn, table, columns, df):
    placeholders = ', '.join('?' for _ in columns)
    col_list = ', '.join(quote_name(c) for c in columns)
    sql = f'INSERT OR REPLACE INTO {quote_name(table)} ({col_list}) VALUES ({placeholders})'
    df = df.where(pd.notna(df), None)
    rows = [tuple(row) for row in df[columns].itertuples(index=False, name=None)]
    conn.executemany(sql, rows)


def get_table_config(table):
    for cfg in TABLES:
        if cfg['table'] == table:
            return cfg
    raise KeyError(f'unknown table: {table}')


def ensure_table(conn, cfg, columns):
    table = cfg['table']
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if not exists:
        create_table(conn, table, columns, cfg['unique'])
        create_indexes(conn, table, columns, cfg['indexes'])


def upsert_dataframe(conn, table, df):
    if df is None or df.empty:
        return 0
    cfg = get_table_config(table)
    columns = list(df.columns)
    ensure_table(conn, cfg, columns)
    insert_chunk(conn, table, columns, df.astype(object))
    return len(df)


def import_table(conn, cfg, chunksize=100_000):
    csv_path = cfg['csv']
    table = cfg['table']
    if not csv_path.exists():
        print(f'[SKIP] {table}: missing {csv_path}')
        return 0

    columns = load_columns(csv_path)
    create_table(conn, table, columns, cfg['unique'])

    imported = 0
    for chunk in pd.read_csv(csv_path, dtype=str, chunksize=chunksize):
        insert_chunk(conn, table, columns, chunk)
        imported += len(chunk)
        print(f'  {table}: imported {imported} rows', flush=True)

    create_indexes(conn, table, columns, cfg['indexes'])
    final_count = conn.execute(f'SELECT COUNT(*) FROM {quote_name(table)}').fetchone()[0]
    print(f'[OK] {table}: csv_rows={imported}, table_rows={final_count}')
    return final_count


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA temp_store=MEMORY')
        conn.execute('PRAGMA cache_size=-200000')

        results = {}
        for cfg in TABLES:
            with conn:
                results[cfg['table']] = import_table(conn, cfg)

        print()
        print(f'Database: {DB_PATH}')
        for table, count in results.items():
            print(f'  {table}: {count}')
    finally:
        conn.close()


if __name__ == '__main__':
    main()

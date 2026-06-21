"""
Backfill Tushare fut_holding by trade_date with incremental flushes.

Usage:
  python backfill_fut_holding.py --start 20250601 --end 20260611
  python backfill_fut_holding.py --start 20250601 --end 20260611 --batch-size 20
"""

import argparse
import os
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
OUTPUT = BASE_DIR / 'futures_data'
TARGET = OUTPUT / '05_持仓排名' / 'fut_holding_all.csv'
LOG_DIR = BASE_DIR / 'logs' / '历史补数据'
LOG_DIR.mkdir(parents=True, exist_ok=True)

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


def log(message):
    print(f'[{datetime.now().strftime("%H:%M:%S")}] {message}', flush=True)


def iter_trade_dates(start, end, exchanges=None):
    exchanges = exchanges or ['CFFEX', 'SHFE', 'DCE', 'CZCE', 'INE']
    cal_file = OUTPUT / '02_交易日历' / 'trade_cal_futures.csv'
    if cal_file.exists():
        try:
            cal = pd.read_csv(cal_file, dtype={'cal_date': str})
            if {'exchange', 'cal_date', 'is_open'}.issubset(cal.columns):
                mask = (
                    cal['exchange'].isin(exchanges)
                    & (cal['cal_date'] >= start)
                    & (cal['cal_date'] <= end)
                    & (cal['is_open'].astype(str) == '1')
                )
                dates = sorted(cal.loc[mask, 'cal_date'].dropna().unique().tolist())
                if dates:
                    return dates
        except Exception as exc:
            log(f'[WARN] trade calendar read failed, fallback to weekdays: {exc}')

    fmt = '%Y%m%d'
    s = datetime.strptime(start, fmt)
    e = datetime.strptime(end, fmt)
    dates = []
    while s <= e:
        if s.weekday() < 5:
            dates.append(s.strftime(fmt))
        s += timedelta(days=1)
    return dates


def safe_fut_holding(trade_date):
    for attempt in range(3):
        try:
            limiter.wait()
            df = pro.fut_holding(trade_date=trade_date)
            return df if df is not None and not df.empty else pd.DataFrame()
        except Exception as exc:
            if attempt == 2:
                log(f'[FAIL] {trade_date}: {exc}')
                return pd.DataFrame()
            time.sleep(5 * (attempt + 1))
    return pd.DataFrame()


def merge_save(frames):
    if not frames:
        return 0, 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    df_new = pd.concat(frames, ignore_index=True)
    if TARGET.exists():
        df_old = pd.read_csv(TARGET, dtype=str)
        common_cols = [c for c in df_new.columns if c in df_old.columns]
        if common_cols:
            combined = pd.concat([df_old[common_cols], df_new[common_cols]], ignore_index=True)
        else:
            combined = pd.concat([df_old, df_new], ignore_index=True)
    else:
        combined = df_new

    dedup_cols = [c for c in ['symbol', 'trade_date', 'broker'] if c in combined.columns]
    if dedup_cols:
        combined = combined.drop_duplicates(subset=dedup_cols, keep='last')

    combined.to_csv(TARGET, index=False, encoding='utf-8-sig')
    return len(df_new), len(combined)


def main():
    parser = argparse.ArgumentParser(description='Backfill fut_holding by trade_date')
    parser.add_argument('--start', required=True, help='YYYYMMDD')
    parser.add_argument('--end', required=True, help='YYYYMMDD')
    parser.add_argument('--batch-size', type=int, default=20, help='flush every N trading days')
    args = parser.parse_args()

    dates = iter_trade_dates(args.start, args.end)
    log(f'fut_holding backfill {args.start}~{args.end}, trading days={len(dates)}, batch={args.batch_size}')

    buffer = []
    processed = 0
    total_new = 0
    for idx, trade_date in enumerate(dates, start=1):
        df = safe_fut_holding(trade_date)
        processed += 1
        if not df.empty:
            buffer.append(df)
            total_new += len(df)
        log(f'{idx}/{len(dates)} {trade_date}: {len(df)} rows')

        if buffer and (processed % args.batch_size == 0):
            new_rows, total_rows = merge_save(buffer)
            log(f'[SAVE] batch_new={new_rows}, file_rows={total_rows}')
            buffer.clear()

    if buffer:
        new_rows, total_rows = merge_save(buffer)
        log(f'[SAVE] batch_new={new_rows}, file_rows={total_rows}')

    log(f'done, downloaded_rows={total_new}, file={TARGET}')


if __name__ == '__main__':
    main()

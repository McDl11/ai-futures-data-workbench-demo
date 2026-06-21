"""
Tushare 期货数据下载器（通过中转 http://jiaoch.site）
覆盖 11 个期货接口，排除实时分钟线和历史分钟线
账号积分：10,000，所有接口均可调用

使用方式：
  python futures_downloader.py                        # 默认：下载近 3 个月数据
  python futures_downloader.py --start 20240101       # 从指定日期下载至今
  python futures_downloader.py --start 20220101 --end 20221231  # 指定日期范围
  python futures_downloader.py --all                  # 下载全部历史数据
"""

import os
import sys
import time
import threading
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from collections import deque

# ============================ 配置 ============================
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')
TOKEN = os.getenv('TUSHARE_TOKEN')
HTTP_URL = os.getenv('TUSHARE_HTTP_URL', 'http://jiaoch.site')

import tushare as ts

# 初始化 pro（关键！必须设置中转地址）
pro = ts.pro_api(TOKEN)
pro._DataApi__token = TOKEN
pro._DataApi__http_url = HTTP_URL

# 输出根目录
OUTPUT = BASE_DIR / 'futures_data'

# 速率限制：每分钟最多 200 次
MAX_CALLS_PER_MINUTE = 200
MIN_INTERVAL = 60.0 / MAX_CALLS_PER_MINUTE  # 0.3 秒


# ============================ 速率限制器 ============================
class RateLimiter:
    """单线程速率控制：滑动窗口，保证每分钟不超过 max_calls 次"""

    def __init__(self, max_calls=200):
        self.max_calls = max_calls
        self.window_seconds = 60.0
        self._timestamps = deque()
        self._lock = threading.Lock()  # 保证线程安全（虽然是单线程，防患于未然）

    def wait(self):
        """阻塞直到可以发起下一次调用"""
        with self._lock:
            now = time.time()
            # 清理 60 秒前的记录
            cutoff = now - self.window_seconds
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()

            # 如果一分钟内已达上限，等待
            if len(self._timestamps) >= self.max_calls:
                sleep_time = self._timestamps[0] - cutoff + 0.1
                log_detail(f'[RATE] 等待 {sleep_time:.1f}s 以遵守 {self.max_calls}次/分钟 限制')
                time.sleep(sleep_time)
                now = time.time()
                cutoff = now - self.window_seconds
                while self._timestamps and self._timestamps[0] < cutoff:
                    self._timestamps.popleft()

            self._timestamps.append(now)

    def stats(self):
        """返回当前窗口内调用次数"""
        with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            return len(self._timestamps)


# 全局限速器实例
limiter = RateLimiter(MAX_CALLS_PER_MINUTE)


# ============================ 工具函数 ============================
def log(msg):
    print(f'[{datetime.now().strftime("%H:%M:%S")}] {msg}'.encode(
        'utf-8', errors='replace').decode('utf-8', errors='replace'))


def log_detail(msg):
    """详细日志，仅在需要时显示"""
    # 不输出限速等待日志，保持简洁
    pass


def safe_dedup(df, subset=None):
    """安全去重：只对存在的列去重"""
    if df is None or df.empty:
        return df
    if subset:
        existing = [c for c in subset if c in df.columns]
        if existing:
            return df.drop_duplicates(subset=existing)
    return df.drop_duplicates()


def save(df, folder, filename):
    """保存 DataFrame 到 CSV"""
    if df is None or df.empty:
        log(f'  [SKIP] {filename}')
        return
    d = OUTPUT / folder
    d.mkdir(parents=True, exist_ok=True)
    fp = d / filename
    df.to_csv(fp, index=False, encoding='utf-8-sig')
    log(f'  [OK] {filename}  |  {len(df)} rows')


def iter_dates(start, end, step_days=365):
    """按年分段，避免单次请求超过 2000 条"""
    fmt = '%Y%m%d'
    s = datetime.strptime(start, fmt)
    e = datetime.strptime(end, fmt)
    while s < e:
        n = min(s + timedelta(days=step_days), e)
        yield s.strftime(fmt), n.strftime(fmt)
        s = n + timedelta(days=1)


def iter_trade_dates(start, end, exchanges=None):
    """从本地交易日历取交易日；交易日历不可用时按自然日兜底。"""
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
        except Exception as e:
            log(f'  [WARN] 读取交易日历失败，改用自然日: {e}')

    fmt = '%Y%m%d'
    s = datetime.strptime(start, fmt)
    e = datetime.strptime(end, fmt)
    dates = []
    while s <= e:
        if s.weekday() < 5:
            dates.append(s.strftime(fmt))
        s += timedelta(days=1)
    return dates


def safe_call(func, api_name, **kwargs):
    """安全调用 API（单线程，含速率限制和失败重试）"""
    for attempt in range(3):  # 最多重试 3 次
        try:
            limiter.wait()  # 遵守速率限制
            df = func(**kwargs)
            if df is not None and not df.empty:
                return df
            return pd.DataFrame()
        except Exception as e:
            if attempt == 2:
                log(f'  [ERR] [{api_name}]: {e}')
                return pd.DataFrame()
            wait_sec = 5 * (attempt + 1)  # 5s, 10s 递增等待
            log(f'  [RETRY] [{api_name}] attempt {attempt+1}/3, wait {wait_sec}s...')
            time.sleep(wait_sec)
    return pd.DataFrame()


# ============================ 各接口下载函数 ============================
def download_fut_basic():
    """期货合约基本信息"""
    log('\n[1/11] fut_basic -- 期货合约列表')
    exchanges = ['CFFEX', 'SHFE', 'DCE', 'CZCE', 'INE', 'GFEX']
    fut_types = {'1': '普通合约', '2': '主力连续', '3': '指数'}
    all_dfs = []
    for ex in exchanges:
        for ft, ft_name in fut_types.items():
            df = safe_call(pro.fut_basic, 'fut_basic', exchange=ex, fut_type=ft)
            if not df.empty:
                df['fut_type'] = ft_name
                all_dfs.append(df)
                log(f'  {ex} {ft_name}: {len(df)} rows')
    if all_dfs:
        save(pd.concat(all_dfs, ignore_index=True), '01_合约列表', 'fut_basic_all.csv')


def download_trade_cal():
    """期货交易日历"""
    log('\n[2/11] trade_cal -- 交易日历')
    exchanges = ['CFFEX', 'SHFE', 'DCE', 'CZCE', 'INE']
    all_dfs = []
    for ex in exchanges:
        df = safe_call(pro.trade_cal, 'trade_cal', exchange=ex,
                       start_date=START_DATE, end_date=END_DATE)
        if not df.empty:
            all_dfs.append(df)
            log(f'  {ex}: {len(df)} rows')
    if all_dfs:
        save(pd.concat(all_dfs, ignore_index=True), '02_交易日历', 'trade_cal_futures.csv')


def download_fut_daily():
    """期货日线行情（按年分段）"""
    log('\n[3/11] fut_daily -- 日线行情')
    all_dfs = []
    chunk_count = 0
    for s, e in iter_dates(START_DATE, END_DATE):
        chunk_count += 1
        df = safe_call(pro.fut_daily, 'fut_daily', start_date=s, end_date=e)
        if not df.empty:
            all_dfs.append(df)
            total = sum(len(d) for d in all_dfs)
            log(f'  [{chunk_count}] {s[:4]}~{e[:4]}: {len(df)} rows, 累计 {total}')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['ts_code', 'trade_date'])
        save(result, '03_日线行情', 'fut_daily_all.csv')


def download_fut_weekly_monthly():
    """期货周线/月线行情"""
    log('\n[4/11] fut_weekly_monthly -- 周/月线行情')
    all_dfs = []
    chunk_count = 0
    for freq in ('week', 'month'):
        for s, e in iter_dates(START_DATE, END_DATE):
            chunk_count += 1
            df = safe_call(pro.fut_weekly_monthly, 'fut_weekly_monthly',
                           start_date=s, end_date=e, freq=freq)
            if not df.empty:
                all_dfs.append(df)
                total = sum(len(d) for d in all_dfs)
                log(f'  [{chunk_count}] {freq} {s[:4]}~{e[:4]}: {len(df)} rows, 累计 {total}')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['ts_code', 'trade_date', 'freq'])
        save(result, '04_周月线', 'fut_weekly_monthly_all.csv')


def download_fut_holding():
    """期货持仓排名（按交易日逐日下载）"""
    log('\n[5/11] fut_holding -- 持仓排名')
    hold_start = max(START_DATE, '20020101')
    all_dfs = []
    trade_dates = iter_trade_dates(hold_start, END_DATE)
    for idx, trade_date in enumerate(trade_dates, start=1):
        df = safe_call(pro.fut_holding, 'fut_holding', trade_date=trade_date)
        if not df.empty:
            all_dfs.append(df)
            total = sum(len(d) for d in all_dfs)
            log(f'  [{idx}/{len(trade_dates)}] {trade_date}: {len(df)} rows, 累计 {total}')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['symbol', 'trade_date', 'broker'])
        save(result, '05_持仓排名', 'fut_holding_all.csv')


def download_fut_wsr():
    """期货仓单日报（按交易日逐日下载）"""
    log('\n[6/11] fut_wsr -- 仓单日报')
    wsr_start = max(START_DATE, '20060101')
    all_dfs = []
    trade_dates = iter_trade_dates(wsr_start, END_DATE)
    for idx, trade_date in enumerate(trade_dates, start=1):
        df = safe_call(pro.fut_wsr, 'fut_wsr', trade_date=trade_date)
        if not df.empty:
            all_dfs.append(df)
            total = sum(len(d) for d in all_dfs)
            log(f'  [{idx}/{len(trade_dates)}] {trade_date}: {len(df)} rows, 累计 {total}')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['symbol', 'trade_date', 'warehouse'])
        save(result, '06_仓单日报', 'fut_wsr_all.csv')


def download_fut_settle():
    """期货结算参数（按年分段）"""
    log('\n[7/11] fut_settle -- 结算参数')
    settle_start = max(START_DATE, '20120101')
    all_dfs = []
    chunk_count = 0
    for s, e in iter_dates(settle_start, END_DATE):
        chunk_count += 1
        df = safe_call(pro.fut_settle, 'fut_settle', start_date=s, end_date=e)
        if not df.empty:
            all_dfs.append(df)
            total = sum(len(d) for d in all_dfs)
            log(f'  [{chunk_count}] {s[:4]}~{e[:4]}: {len(df)} rows, 累计 {total}')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['ts_code', 'trade_date'])
        save(result, '07_结算参数', 'fut_settle_all.csv')


def download_ft_limit():
    """期货涨跌停板（按年分段）"""
    log('\n[8/11] ft_limit -- 涨跌停板')
    limit_start = max(START_DATE, '20050101')
    all_dfs = []
    chunk_count = 0
    for s, e in iter_dates(limit_start, END_DATE):
        chunk_count += 1
        df = safe_call(pro.ft_limit, 'ft_limit', start_date=s, end_date=e)
        if not df.empty:
            all_dfs.append(df)
            total = sum(len(d) for d in all_dfs)
            log(f'  [{chunk_count}] {s[:4]}~{e[:4]}: {len(df)} rows, 累计 {total}')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['ts_code', 'trade_date'])
        save(result, '08_涨跌停板', 'ft_limit_all.csv')


def download_fut_weekly_detail():
    """期货周度明细（按年分段）"""
    log('\n[9/11] fut_weekly_detail -- 周度明细')
    wd_start = max(START_DATE, '20100301')
    all_dfs = []
    chunk_count = 0
    for s, e in iter_dates(wd_start, END_DATE):
        chunk_count += 1
        df = safe_call(pro.fut_weekly_detail, 'fut_weekly_detail',
                       start_date=s, end_date=e)
        if not df.empty:
            all_dfs.append(df)
            total = sum(len(d) for d in all_dfs)
            log(f'  [{chunk_count}] {s[:4]}~{e[:4]}: {len(df)} rows, 累计 {total}')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['exchange', 'symbol', 'week_date'])
        save(result, '09_周度明细', 'fut_weekly_detail_all.csv')






def download_fut_mapping():
    """期货主力/连续合约映射"""
    log('\n[10/11] fut_mapping -- 主力/连续合约映射')
    all_dfs = []
    chunk_count = 0
    for s, e in iter_dates(START_DATE, END_DATE):
        chunk_count += 1
        df = safe_call(pro.fut_mapping, 'fut_mapping', start_date=s, end_date=e)
        if not df.empty:
            all_dfs.append(df)
            total = sum(len(d) for d in all_dfs)
            log(f'  [{chunk_count}] {s[:4]}~{e[:4]}: {len(df)} rows, 累计 {total}')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['ts_code', 'trade_date'])
        save(result, '10_主力映射', 'fut_mapping_all.csv')


def download_index_daily():
    """南华期货指数日线"""
    log('\n[11/11] index_daily -- 南华期货指数')
    idx_start = max(START_DATE, '20100101')
    all_dfs = []
    chunk_count = 0
    for s, e in iter_dates(idx_start, END_DATE):
        chunk_count += 1
        df = safe_call(pro.index_daily, 'index_daily', start_date=s, end_date=e)
        if not df.empty:
            all_dfs.append(df)
            total = sum(len(d) for d in all_dfs)
            log(f'  [{chunk_count}] {s[:4]}~{e[:4]}: {len(df)} rows, 累计 {total}')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['ts_code', 'trade_date'])
        save(result, '11_期货指数', 'index_daily_all.csv')


# ============================ 主流程 ============================
def parse_args():
    """解析命令行参数，返回 (start_date, end_date)"""
    args = sys.argv[1:]

    if '--all' in args:
        return '19960101', datetime.now().strftime('%Y%m%d')

    start = None
    end = None
    i = 0
    while i < len(args):
        if args[i] == '--start' and i + 1 < len(args):
            start = args[i + 1]
            i += 2
        elif args[i] == '--end' and i + 1 < len(args):
            end = args[i + 1]
            i += 2
        else:
            i += 1

    # 默认：近 3 个月（测试用）
    if start is None:
        start = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')
    if end is None:
        end = datetime.now().strftime('%Y%m%d')

    return start, end


def main():
    global START_DATE, END_DATE

    START_DATE, END_DATE = parse_args()

    log('=' * 60)
    log('Tushare Futures Data Downloader')
    log(f'   URL:        {HTTP_URL}')
    log(f'   Output:     {OUTPUT.resolve()}')
    log(f'   Range:      {START_DATE} ~ {END_DATE}')
    log(f'   Rate Limit: {MAX_CALLS_PER_MINUTE} calls/min ({MIN_INTERVAL:.1f}s interval)')
    log(f'   Mode:       SEQUENTIAL (single-thread, no concurrent)')
    log('=' * 60)

    # 如果日期跨度大，提示预估次数
    fmt = '%Y%m%d'
    days = (datetime.strptime(END_DATE, fmt) - datetime.strptime(START_DATE, fmt)).days
    years = days / 365
    est_calls_per_interface = max(1, int(years)) + 3  # 按年分段 + 一些额外
    total_est = est_calls_per_interface * 11
    log(f'   Estimated total API calls: ~{total_est} (will take ~{total_est * MIN_INTERVAL:.0f}s+)')

    start_time = time.time()

    # 逐个串行下载（绝不并发）
    download_funcs = [
        download_fut_basic,           # 1. 合约列表
        download_trade_cal,           # 2. 交易日历
        download_fut_daily,           # 3. 日线行情
        download_fut_weekly_monthly,  # 4. 周/月线
        download_fut_holding,         # 5. 持仓排名
        download_fut_wsr,             # 6. 仓单日报
        download_fut_settle,          # 7. 结算参数
        download_ft_limit,            # 8. 涨跌停板
        download_fut_weekly_detail,   # 9. 周度明细
        download_fut_mapping,         # 10. 主力映射
        download_index_daily,         # 11. 南华期货指数
    ]

    for func in download_funcs:
        try:
            func()
        except Exception as e:
            log(f'  [ERR] skip: {e}')

    elapsed = time.time() - start_time
    total_calls = limiter.stats()
    log(f'\n{"=" * 60}')
    log(f'ALL DONE! Time: {elapsed:.0f}s  |  Total calls: {total_calls}')
    log(f'DATA: {OUTPUT.resolve()}')
    log(f'{"=" * 60}')


if __name__ == '__main__':
    main()

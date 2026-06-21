"""
自动化期货数据下载引擎
========================
功能：
  - 下载全部 11 个期货接口
  - 文件日志 + 控制台双输出
  - 下载完成后逐接口做数据完整性校验
  - 生成下载摘要报告

使用方式：
  python auto_futures_downloader.py           # 打开后自动等到凌晨 4:00 下载
  python auto_futures_downloader.py --now     # 立即执行一次
  python auto_futures_downloader.py --now --start 20240101  # 指定日期范围
"""

import os
import sys
import time
import logging
import traceback
import schedule
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque, OrderedDict
from dotenv import load_dotenv

from split_by_product import run_split

# ============================ 路径 & 环境 ============================
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

TOKEN = os.getenv('TUSHARE_TOKEN')
HTTP_URL = os.getenv('TUSHARE_HTTP_URL', 'http://jiaoch.site')

# 初始化 tushare pro（模块级，方便跨模块调用）
import tushare as ts
pro = ts.pro_api(TOKEN)
pro._DataApi__token = TOKEN
pro._DataApi__http_url = HTTP_URL

# 输出根目录 & 日志目录
OUTPUT = BASE_DIR / 'futures_data'
LOG_DIR = BASE_DIR / 'logs' / '全量下载'
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 今天日期（日志 & 报告文件名用）
TODAY_STR = datetime.now().strftime('%Y%m%d')

# 速率限制
MAX_CALLS_PER_MINUTE = 200
MIN_INTERVAL = 60.0 / MAX_CALLS_PER_MINUTE

# 全局下载状态收集
DOWNLOAD_RESULTS = OrderedDict()
INTEGRITY_RESULTS = OrderedDict()

# ============================ 日志配置 ============================
LOG_FILE = LOG_DIR / f'download_{TODAY_STR}.log'

def setup_logging():
    """双输出日志：控制台 + 文件"""
    logger = logging.getLogger('auto_downloader')
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # 文件 handler（详细）
    fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)-7s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))

    # 控制台 handler（简洁）
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        '[%(asctime)s] %(message)s', datefmt='%H:%M:%S'
    ))

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


log = setup_logging()


# ============================ 速率限制器 ============================
class RateLimiter:
    """滑动窗口速率控制"""

    def __init__(self, max_calls=200):
        self.max_calls = max_calls
        self.window_seconds = 60.0
        self._timestamps = deque()
        self._total_calls = 0

    def wait(self):
        now = time.time()
        cutoff = now - self.window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

        if len(self._timestamps) >= self.max_calls:
            sleep_time = self._timestamps[0] - cutoff + 0.1
            log.debug(f'[RATE] 等待 {sleep_time:.1f}s')
            time.sleep(sleep_time)
            now = time.time()
            cutoff = now - self.window_seconds
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()

        self._timestamps.append(now)
        self._total_calls += 1


limiter = RateLimiter(MAX_CALLS_PER_MINUTE)


# ============================ 工具函数 ============================
def safe_dedup(df, subset=None):
    """安全去重"""
    if df is None or df.empty:
        return df
    if subset:
        existing = [c for c in subset if c in df.columns]
        if existing:
            return df.drop_duplicates(subset=existing)
    return df.drop_duplicates()


def save_csv(df, folder, filename):
    """保存到 CSV"""
    d = OUTPUT / folder
    d.mkdir(parents=True, exist_ok=True)
    fp = d / filename
    df.to_csv(fp, index=False, encoding='utf-8-sig')
    return str(fp), len(df)


def iter_dates(start, end, step_days=365):
    """按年分段迭代"""
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
            log.warning(f'  [WARN] 读取交易日历失败，改用自然日: {e}')

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
    """安全 API 调用（含速率限制 + 3 次重试 + 指数退避）"""
    for attempt in range(3):
        try:
            limiter.wait()
            df = func(**kwargs)
            if df is not None and not df.empty:
                return df
            return pd.DataFrame()
        except Exception as e:
            if attempt == 2:
                log.error(f'  [FAIL] {api_name}: {e}')
                return pd.DataFrame()
            wait_sec = 5 * (attempt + 1)
            log.warning(f'  [RETRY] {api_name} #{attempt+1}/3, wait {wait_sec}s: {e}')
            time.sleep(wait_sec)
    return pd.DataFrame()


# ============================ 数据完整性校验 ============================
def check_integrity(folder, filename, expected_cols, start_date, end_date,
                    min_rows=100, date_col='trade_date'):
    """
    校验下载数据完整性
    返回: (passed: bool, details: list)
    """
    fp = OUTPUT / folder / filename
    checks = []

    # 1. 文件存在
    if not fp.exists():
        checks.append(('文件不存在', False, str(fp)))
        return False, checks
    checks.append(('文件存在', True, str(fp.name)))

    # 2. 文件可读且非空
    try:
        df = pd.read_csv(fp)
    except Exception as e:
        checks.append(('文件读取', False, str(e)))
        return False, checks

    row_count = len(df)
    checks.append(('行数', row_count >= min_rows,
                   f'{row_count} rows (阈值: {min_rows})'))
    if row_count == 0:
        return False, checks

    # 3. 列校验
    missing_cols = [c for c in expected_cols if c not in df.columns]
    if missing_cols:
        checks.append(('必备列缺失', False, ', '.join(missing_cols)))
    else:
        checks.append(('必备列完整', True, f'{len(expected_cols)} 列均存在'))

    # 4. 日期列校验（如果有）
    if date_col and date_col in df.columns:
        df[date_col] = df[date_col].astype(str)
        dates_in_df = pd.to_datetime(df[date_col], format='%Y%m%d', errors='coerce')
        valid_dates = dates_in_df.dropna()
        if len(valid_dates) > 0:
            min_d = valid_dates.min().strftime('%Y%m%d')
            max_d = valid_dates.max().strftime('%Y%m%d')
            cover_start = min_d <= start_date
            cover_end = max_d >= end_date or max_d >= (datetime.now() - timedelta(days=3)).strftime('%Y%m%d')
            checks.append(('日期覆盖范围', cover_start and cover_end,
                           f'{min_d} ~ {max_d} (期望 >= {start_date} ~ {end_date})'))
        else:
            checks.append(('日期覆盖范围', False, '无有效日期'))
    else:
        checks.append(('日期覆盖范围', True, '无日期列，跳过'))

    # 5. 关键列空值率
    key_cols = [c for c in expected_cols[:5] if c in df.columns]
    for c in key_cols:
        null_rate = df[c].isna().mean()
        checks.append((f'空值率({c})', null_rate < 0.3,
                       f'{null_rate:.2%}'))

    all_pass = all(p for _, p, _ in checks)
    return all_pass, checks


def run_integrity_checks():
    """对所有已下载数据做完整性校验"""
    log.info('\n' + '=' * 60)
    log.info('[CHECK] 数据完整性校验开始')
    log.info('=' * 60)

    end_date = datetime.now().strftime('%Y%m%d')

    # 定义各接口校验规则
    checks_config = [
        {'folder': '01_合约列表',    'file': 'fut_basic_all.csv',
         'cols': ['ts_code', 'symbol', 'name', 'exchange', 'fut_type'],
         'start': '19960101', 'end': end_date, 'min_rows': 50, 'date_col': None},
        {'folder': '02_交易日历',   'file': 'trade_cal_futures.csv',
         'cols': ['exchange', 'cal_date', 'is_open'],
         'start': '20000101', 'end': end_date, 'min_rows': 1000, 'date_col': 'cal_date'},
        {'folder': '03_日线行情',   'file': 'fut_daily_all.csv',
         'cols': ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol'],
         'start': '20100101', 'end': end_date, 'min_rows': 5000, 'date_col': 'trade_date'},
        {'folder': '04_周月线',     'file': 'fut_weekly_monthly_all.csv',
         'cols': ['ts_code', 'trade_date', 'open', 'close', 'freq'],
         'start': '20100101', 'end': end_date, 'min_rows': 500, 'date_col': 'trade_date'},
        {'folder': '05_持仓排名',   'file': 'fut_holding_all.csv',
         'cols': ['trade_date', 'symbol', 'broker', 'vol', 'long_hld', 'short_hld'],
         'start': '20020101', 'end': end_date, 'min_rows': 500, 'date_col': 'trade_date'},
        {'folder': '06_仓单日报',   'file': 'fut_wsr_all.csv',
         'cols': ['trade_date', 'symbol', 'warehouse', 'vol', 'unit'],
         'start': '20060101', 'end': end_date, 'min_rows': 500, 'date_col': 'trade_date'},
        {'folder': '07_结算参数',   'file': 'fut_settle_all.csv',
         'cols': ['ts_code', 'trade_date', 'settle', 'long_margin_rate', 'short_margin_rate'],
         'start': '20120101', 'end': end_date, 'min_rows': 500, 'date_col': 'trade_date'},
        {'folder': '08_涨跌停板',   'file': 'ft_limit_all.csv',
         'cols': ['ts_code', 'trade_date', 'up_limit', 'down_limit'],
         'start': '20050101', 'end': end_date, 'min_rows': 500, 'date_col': 'trade_date'},
        {'folder': '09_周度明细',   'file': 'fut_weekly_detail_all.csv',
         'cols': ['exchange', 'symbol', 'week_date', 'vol', 'amount'],
         'start': '20100301', 'end': end_date, 'min_rows': 100, 'date_col': 'week_date'},
        {'folder': '10_主力映射',   'file': 'fut_mapping_all.csv',
         'cols': ['ts_code', 'trade_date', 'mapping_ts_code'],
         'start': '20100101', 'end': end_date, 'min_rows': 500, 'date_col': 'trade_date'},
        {'folder': '11_期货指数',   'file': 'index_daily_all.csv',
         'cols': ['ts_code', 'trade_date', 'open', 'close', 'vol'],
         'start': '20100101', 'end': end_date, 'min_rows': 500, 'date_col': 'trade_date'},
    ]

    all_passed = True
    for cfg in checks_config:
        folder = cfg['folder']
        fname = cfg['file']
        log.info(f'\n--- 校验 {folder}/{fname} ---')
        passed, details = check_integrity(
            folder, fname, cfg['cols'], cfg['start'], cfg['end'],
            min_rows=cfg['min_rows'], date_col=cfg['date_col']
        )
        INTEGRITY_RESULTS[f'{folder}/{fname}'] = {
            'passed': passed,
            'details': details
        }
        for name, ok, info in details:
            icon = '[OK]' if ok else '[!!]'
            log.info(f'  {icon} {name}: {info}')
        status = 'PASS' if passed else 'FAIL'
        if not passed:
            all_passed = False
        log.info(f'  综合: {status}')

    log.info(f'\n[CHECK] 完整性校验完成：{"全部通过" if all_passed else "存在未通过项"}')
    return all_passed


# ============================ 各接口下载函数 ============================
def download_fut_basic():
    """期货合约基本信息"""
    log.info('\n[1/11] fut_basic -- 期货合约列表')
    exchanges = ['CFFEX', 'SHFE', 'DCE', 'CZCE', 'INE', 'GFEX']
    fut_types = {'1': '普通合约', '2': '主力连续', '3': '指数'}
    all_dfs = []
    for ex in exchanges:
        for ft, ft_name in fut_types.items():
            df = safe_call(pro.fut_basic, 'fut_basic', exchange=ex, fut_type=ft)
            if not df.empty:
                df['fut_type'] = ft_name
                all_dfs.append(df)
                log.debug(f'    {ex}/{ft_name}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        fp, cnt = save_csv(result, '01_合约列表', 'fut_basic_all.csv')
        DOWNLOAD_RESULTS['fut_basic'] = {'file': fp, 'rows': cnt, 'status': 'OK'}
        log.info(f'  [OK] 合约列表: {cnt} rows → {fp}')
    else:
        DOWNLOAD_RESULTS['fut_basic'] = {'file': '', 'rows': 0, 'status': 'EMPTY'}
        log.warning('  [WARN] fut_basic 无数据')


def download_trade_cal(start, end):
    """期货交易日历"""
    log.info('\n[2/11] trade_cal -- 交易日历')
    exchanges = ['CFFEX', 'SHFE', 'DCE', 'CZCE', 'INE']
    all_dfs = []
    for ex in exchanges:
        df = safe_call(pro.trade_cal, 'trade_cal', exchange=ex,
                       start_date=start, end_date=end)
        if not df.empty:
            all_dfs.append(df)
            log.debug(f'    {ex}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        fp, cnt = save_csv(result, '02_交易日历', 'trade_cal_futures.csv')
        DOWNLOAD_RESULTS['trade_cal'] = {'file': fp, 'rows': cnt, 'status': 'OK'}
        log.info(f'  [OK] 交易日历: {cnt} rows → {fp}')
    else:
        DOWNLOAD_RESULTS['trade_cal'] = {'file': '', 'rows': 0, 'status': 'EMPTY'}
        log.warning('  [WARN] trade_cal 无数据')


def download_fut_daily(start, end):
    """期货日线行情（按年分段）"""
    log.info('\n[3/11] fut_daily -- 日线行情')
    all_dfs = []
    chunk = 0
    for s, e in iter_dates(start, end):
        chunk += 1
        df = safe_call(pro.fut_daily, 'fut_daily', start_date=s, end_date=e)
        if not df.empty:
            all_dfs.append(df)
            total = sum(len(d) for d in all_dfs)
            log.info(f'  chunk {chunk} [{s[:4]}~{e[:4]}]: {len(df)} rows, 累计 {total}')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['ts_code', 'trade_date'])
        fp, cnt = save_csv(result, '03_日线行情', 'fut_daily_all.csv')
        DOWNLOAD_RESULTS['fut_daily'] = {'file': fp, 'rows': cnt, 'status': 'OK'}
        log.info(f'  [OK] 日线行情: {cnt} rows → {fp}')
    else:
        DOWNLOAD_RESULTS['fut_daily'] = {'file': '', 'rows': 0, 'status': 'EMPTY'}
        log.warning('  [WARN] fut_daily 无数据')


def download_fut_weekly_monthly(start, end):
    """期货周线/月线行情"""
    log.info('\n[4/11] fut_weekly_monthly -- 周/月线')
    all_dfs = []
    chunk = 0
    for freq in ('week', 'month'):
        for s, e in iter_dates(start, end):
            chunk += 1
            df = safe_call(pro.fut_weekly_monthly, 'fut_weekly_monthly',
                           start_date=s, end_date=e, freq=freq)
            if not df.empty:
                all_dfs.append(df)
                log.debug(f'    {freq} chunk {chunk}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['ts_code', 'trade_date', 'freq'])
        fp, cnt = save_csv(result, '04_周月线', 'fut_weekly_monthly_all.csv')
        DOWNLOAD_RESULTS['fut_weekly_monthly'] = {'file': fp, 'rows': cnt, 'status': 'OK'}
        log.info(f'  [OK] 周月线: {cnt} rows → {fp}')
    else:
        DOWNLOAD_RESULTS['fut_weekly_monthly'] = {'file': '', 'rows': 0, 'status': 'EMPTY'}
        log.warning('  [WARN] fut_weekly_monthly 无数据')


def download_fut_holding(start, end):
    """期货持仓排名（按交易日逐日下载）"""
    log.info('\n[5/11] fut_holding -- 持仓排名')
    hold_start = max(start, '20020101')
    all_dfs = []
    trade_dates = iter_trade_dates(hold_start, end)
    for idx, trade_date in enumerate(trade_dates, start=1):
        df = safe_call(pro.fut_holding, 'fut_holding', trade_date=trade_date)
        if not df.empty:
            all_dfs.append(df)
            log.debug(f'    {idx}/{len(trade_dates)} {trade_date}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['symbol', 'trade_date', 'broker'])
        fp, cnt = save_csv(result, '05_持仓排名', 'fut_holding_all.csv')
        DOWNLOAD_RESULTS['fut_holding'] = {'file': fp, 'rows': cnt, 'status': 'OK'}
        log.info(f'  [OK] 持仓排名: {cnt} rows → {fp}')
    else:
        DOWNLOAD_RESULTS['fut_holding'] = {'file': '', 'rows': 0, 'status': 'EMPTY'}
        log.warning('  [WARN] fut_holding 无数据')


def download_fut_wsr(start, end):
    """期货仓单日报（按交易日逐日下载）"""
    log.info('\n[6/11] fut_wsr -- 仓单日报')
    wsr_start = max(start, '20060101')
    all_dfs = []
    trade_dates = iter_trade_dates(wsr_start, end)
    for idx, trade_date in enumerate(trade_dates, start=1):
        df = safe_call(pro.fut_wsr, 'fut_wsr', trade_date=trade_date)
        if not df.empty:
            all_dfs.append(df)
            log.debug(f'    {idx}/{len(trade_dates)} {trade_date}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['symbol', 'trade_date', 'warehouse'])
        fp, cnt = save_csv(result, '06_仓单日报', 'fut_wsr_all.csv')
        DOWNLOAD_RESULTS['fut_wsr'] = {'file': fp, 'rows': cnt, 'status': 'OK'}
        log.info(f'  [OK] 仓单日报: {cnt} rows → {fp}')
    else:
        DOWNLOAD_RESULTS['fut_wsr'] = {'file': '', 'rows': 0, 'status': 'EMPTY'}
        log.warning('  [WARN] fut_wsr 无数据')


def download_fut_settle(start, end):
    """期货结算参数"""
    log.info('\n[7/11] fut_settle -- 结算参数')
    settle_start = max(start, '20120101')
    all_dfs = []
    chunk = 0
    for s, e in iter_dates(settle_start, end):
        chunk += 1
        df = safe_call(pro.fut_settle, 'fut_settle', start_date=s, end_date=e)
        if not df.empty:
            all_dfs.append(df)
            log.debug(f'    chunk {chunk}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['ts_code', 'trade_date'])
        fp, cnt = save_csv(result, '07_结算参数', 'fut_settle_all.csv')
        DOWNLOAD_RESULTS['fut_settle'] = {'file': fp, 'rows': cnt, 'status': 'OK'}
        log.info(f'  [OK] 结算参数: {cnt} rows → {fp}')
    else:
        DOWNLOAD_RESULTS['fut_settle'] = {'file': '', 'rows': 0, 'status': 'EMPTY'}
        log.warning('  [WARN] fut_settle 无数据')


def download_ft_limit(start, end):
    """期货涨跌停板"""
    log.info('\n[8/11] ft_limit -- 涨跌停板')
    limit_start = max(start, '20050101')
    all_dfs = []
    chunk = 0
    for s, e in iter_dates(limit_start, end):
        chunk += 1
        df = safe_call(pro.ft_limit, 'ft_limit', start_date=s, end_date=e)
        if not df.empty:
            all_dfs.append(df)
            log.debug(f'    chunk {chunk}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['ts_code', 'trade_date'])
        fp, cnt = save_csv(result, '08_涨跌停板', 'ft_limit_all.csv')
        DOWNLOAD_RESULTS['ft_limit'] = {'file': fp, 'rows': cnt, 'status': 'OK'}
        log.info(f'  [OK] 涨跌停板: {cnt} rows → {fp}')
    else:
        DOWNLOAD_RESULTS['ft_limit'] = {'file': '', 'rows': 0, 'status': 'EMPTY'}
        log.warning('  [WARN] ft_limit 无数据')


def download_fut_weekly_detail(start, end):
    """期货周度明细"""
    log.info('\n[9/11] fut_weekly_detail -- 周度明细')
    wd_start = max(start, '20100301')
    all_dfs = []
    chunk = 0
    for s, e in iter_dates(wd_start, end):
        chunk += 1
        df = safe_call(pro.fut_weekly_detail, 'fut_weekly_detail',
                       start_date=s, end_date=e)
        if not df.empty:
            all_dfs.append(df)
            log.debug(f'    chunk {chunk}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['exchange', 'symbol', 'week_date'])
        fp, cnt = save_csv(result, '09_周度明细', 'fut_weekly_detail_all.csv')
        DOWNLOAD_RESULTS['fut_weekly_detail'] = {'file': fp, 'rows': cnt, 'status': 'OK'}
        log.info(f'  [OK] 周度明细: {cnt} rows → {fp}')
    else:
        DOWNLOAD_RESULTS['fut_weekly_detail'] = {'file': '', 'rows': 0, 'status': 'EMPTY'}
        log.warning('  [WARN] fut_weekly_detail 无数据')


def download_fut_mapping(start, end):
    """期货主力/连续合约映射"""
    log.info('\n[10/11] fut_mapping -- 主力/连续合约映射')
    all_dfs = []
    chunk = 0
    for s, e in iter_dates(start, end):
        chunk += 1
        df = safe_call(pro.fut_mapping, 'fut_mapping', start_date=s, end_date=e)
        if not df.empty:
            all_dfs.append(df)
            log.debug(f'    chunk {chunk}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['ts_code', 'trade_date'])
        fp, cnt = save_csv(result, '10_主力映射', 'fut_mapping_all.csv')
        DOWNLOAD_RESULTS['fut_mapping'] = {'file': fp, 'rows': cnt, 'status': 'OK'}
        log.info(f'  [OK] 主力映射: {cnt} rows → {fp}')
    else:
        DOWNLOAD_RESULTS['fut_mapping'] = {'file': '', 'rows': 0, 'status': 'EMPTY'}
        log.warning('  [WARN] fut_mapping 无数据')


def download_index_daily(start, end):
    """南华期货指数日线"""
    log.info('\n[11/11] index_daily -- 南华期货指数')
    idx_start = max(start, '20100101')
    all_dfs = []
    chunk = 0
    for s, e in iter_dates(idx_start, end):
        chunk += 1
        df = safe_call(pro.index_daily, 'index_daily', start_date=s, end_date=e)
        if not df.empty:
            all_dfs.append(df)
            log.debug(f'    chunk {chunk}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = safe_dedup(result, ['ts_code', 'trade_date'])
        fp, cnt = save_csv(result, '11_期货指数', 'index_daily_all.csv')
        DOWNLOAD_RESULTS['index_daily'] = {'file': fp, 'rows': cnt, 'status': 'OK'}
        log.info(f'  [OK] 期货指数: {cnt} rows → {fp}')
    else:
        DOWNLOAD_RESULTS['index_daily'] = {'file': '', 'rows': 0, 'status': 'EMPTY'}
        log.warning('  [WARN] index_daily 无数据')


# ============================ 主流程 ============================
def generate_summary(elapsed_sec, start_date, end_date):
    """生成下载摘要报告"""
    summary_file = LOG_DIR / f'summary_{TODAY_STR}.txt'
    lines = []
    lines.append('=' * 60)
    lines.append(f'  期货数据下载摘要报告')
    lines.append(f'  日期: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    lines.append(f'  数据范围: {start_date} ~ {end_date}')
    lines.append(f'  总耗时: {elapsed_sec:.0f} 秒 ({elapsed_sec/60:.1f} 分钟)')
    lines.append('=' * 60)
    lines.append('')

    lines.append(f'{"接口":<25s} {"行数":>10s} {"状态":>8s}')
    lines.append('-' * 45)
    total_rows = 0
    ok_count = 0
    for name, info in DOWNLOAD_RESULTS.items():
        lines.append(f'  {name:<23s} {info["rows"]:>10d} {info["status"]:>8s}')
        total_rows += info['rows']
        if info['status'] == 'OK':
            ok_count += 1
    lines.append('-' * 45)
    lines.append(f'  {"合计":<23s} {total_rows:>10d}')
    lines.append('')
    lines.append(f'  接口成功: {ok_count}/11')

    lines.append('')
    lines.append('=' * 60)
    lines.append('  数据完整性校验')
    lines.append('=' * 60)
    all_ok = True
    for name, result in INTEGRITY_RESULTS.items():
        icon = 'PASS' if result['passed'] else 'FAIL'
        lines.append(f'  [{icon}] {name}')
        if not result['passed']:
            all_ok = False
    lines.append(f'  综合: {"全部通过" if all_ok else "存在未通过项"}')

    lines.append('')
    lines.append(f'  详细日志: {LOG_FILE}')
    lines.append('=' * 60)

    report = '\n'.join(lines)
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write(report)

    log.info(report)
    log.info(f'\n[REPORT] 报告已保存: {summary_file}')
    return report


# 全局日期变量
START_DATE = None
END_DATE = None


def run_download(start_date=None, end_date=None):
    """
    执行一次完整下载。
    如果未传参，默认下载全量历史数据（从最早可用日期到昨天）。
    """
    global START_DATE, END_DATE, DOWNLOAD_RESULTS, INTEGRITY_RESULTS

    # 重置状态
    DOWNLOAD_RESULTS.clear()
    INTEGRITY_RESULTS.clear()

    if start_date is None:
        START_DATE = '19960101'
    else:
        START_DATE = start_date
    if end_date is None:
        END_DATE = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    else:
        END_DATE = end_date

    log.info('=' * 60)
    log.info('  Tushare 期货数据自动下载引擎')
    log.info(f'  中转地址:   {HTTP_URL}')
    log.info(f'  数据范围:   {START_DATE} ~ {END_DATE}')
    log.info(f'  速率限制:   {MAX_CALLS_PER_MINUTE} 次/分钟')
    log.info(f'  输出目录:   {OUTPUT.resolve()}')
    log.info(f'  日志文件:   {LOG_FILE.resolve()}')
    log.info('=' * 60)

    start_ts = time.time()

    # ---- 按顺序下载 11 个接口 ----
    download_tasks = [
        ('fut_basic',             download_fut_basic),
        ('trade_cal',             lambda: download_trade_cal(START_DATE, END_DATE)),
        ('fut_daily',             lambda: download_fut_daily(START_DATE, END_DATE)),
        ('fut_weekly_monthly',    lambda: download_fut_weekly_monthly(START_DATE, END_DATE)),
        ('fut_holding',           lambda: download_fut_holding(START_DATE, END_DATE)),
        ('fut_wsr',               lambda: download_fut_wsr(START_DATE, END_DATE)),
        ('fut_settle',            lambda: download_fut_settle(START_DATE, END_DATE)),
        ('ft_limit',              lambda: download_ft_limit(START_DATE, END_DATE)),
        ('fut_weekly_detail',     lambda: download_fut_weekly_detail(START_DATE, END_DATE)),
        ('fut_mapping',           lambda: download_fut_mapping(START_DATE, END_DATE)),
        ('index_daily',           lambda: download_index_daily(START_DATE, END_DATE)),
    ]

    for name, func in download_tasks:
        try:
            func()
        except Exception as e:
            log.error(f'  [PANIC] {name}: {e}')
            log.error(traceback.format_exc())
            DOWNLOAD_RESULTS[name] = {'file': '', 'rows': 0, 'status': 'ERROR'}

    elapsed = time.time() - start_ts
    log.info(f'\n[DONE] 下载阶段完成，耗时 {elapsed:.0f}s')

    # ---- 完整性校验 ----
    run_integrity_checks()

    # ---- 生成报告 ----
    generate_summary(elapsed, START_DATE, END_DATE)

    # ---- 按品种拆分 ----
    log.info('\n[SPLIT] 开始按品种拆分数据...')
    try:
        split_result = run_split(quiet=True)
        log.info(f'[SPLIT] 完成: {split_result["products"]} 个品种')
    except Exception as e:
        log.error(f'[SPLIT] 拆分失败: {e}')

    return DOWNLOAD_RESULTS, INTEGRITY_RESULTS


# ============================ 入口 ============================
def show_countdown(target_hour=4, target_minute=0):
    """在控制台显示倒计时，让用户知道脚本正在等待"""
    while True:
        now = datetime.now()
        target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        remaining = target - now
        hours, rem = divmod(int(remaining.total_seconds()), 3600)
        mins, secs = divmod(rem, 60)
        sys.stdout.write(
            f'\r  等待凌晨 {target_hour:02d}:{target_minute:02d} 触发下载...  '
            f'剩余 {hours:02d}:{mins:02d}:{secs:02d}  '
        )
        sys.stdout.flush()
        if remaining.total_seconds() <= 1:
            print()
            break
        time.sleep(1)


if __name__ == '__main__':
    import argparse
    import traceback as _tb

    # ---- 全局异常兜底（防止双击闪退） ----
    try:
        parser = argparse.ArgumentParser(description='自动期货数据下载引擎')
        parser.add_argument('--now', action='store_true',
                            help='立即执行一次下载')
        parser.add_argument('--start', type=str, default=None,
                            help='起始日期 YYYYMMDD（默认：全量最早日期）')
        parser.add_argument('--end', type=str, default=None,
                            help='结束日期 YYYYMMDD（默认：昨天）')
        parser.add_argument('--all', action='store_true',
                            help='下载全量历史数据')
        args = parser.parse_args()

        if args.now:
            # -------- 立即执行模式 --------
            run_download(start_date=args.start, end_date=args.end)
            print()
            print('下载完成。窗口将在 10 秒后关闭，或按 Enter 立即关闭...')
            # 防止双击运行后窗口一闪而过
            try:
                import msvcrt
                for _ in range(100):  # 最多等 10 秒
                    if msvcrt.kbhit() and msvcrt.getch() in (b'\r', b'\n', b' '):
                        break
                    time.sleep(0.1)
            except ImportError:
                time.sleep(5)

        else:
            # -------- 定时等待模式（默认） --------
            print()
            print('=' * 60)
            print('  期货数据自动下载 — 定时等待模式')
            print('=' * 60)
            print(f'  当前时间:   {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
            print(f'  触发时间:   每天凌晨 04:00')
            print(f'  日志目录:   {LOG_DIR.resolve()}')
            print(f'  关闭窗口即可停止等待')
            print(f'  提示: 如果想立即下载，请用: python auto_futures_downloader.py --now')
            print('=' * 60)
            print()

            # 注册每日 4:00 任务
            schedule.every().day.at('04:00').do(run_download)

            while True:
                try:
                    schedule.run_pending()
                    sys.stdout.write(f'\r  当前时间: {datetime.now().strftime("%H:%M:%S")}  |  等待 04:00 触发...  ')
                    sys.stdout.flush()
                    time.sleep(30)
                except KeyboardInterrupt:
                    print('\n\n  已手动停止。')
                    break
                except Exception as e:
                    log.error(f'调度异常: {e}', exc_info=True)
                    time.sleep(60)

    except SystemExit:
        pass
    except Exception:
        print()
        print('=' * 60)
        print('  发生错误，脚本异常退出：')
        print('=' * 60)
        _tb.print_exc()
        print()
        print('  日志文件: logs/download_*.log')
        print()
        input('按 Enter 关闭窗口...')

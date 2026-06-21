"""
期货数据每日增量更新
======================
每天凌晨 4:00 自动下载最新数据，与已有 CSV 合并去重。

用法：
  python daily_update.py           # 等到 4:00，下载最近数据
  python daily_update.py --now     # 立即执行一次
"""

import os
import sys
import time
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque
from dotenv import load_dotenv
import pandas as pd

from split_by_product import run_split
from import_csv_to_sqlite import upsert_dataframe
from task_run_history import record_task_run

# ============================ 环境 & 初始化 ============================
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

TOKEN = os.getenv('TUSHARE_TOKEN')
HTTP_URL = os.getenv('TUSHARE_HTTP_URL', 'http://jiaoch.site')

import tushare as ts
pro = ts.pro_api(TOKEN)
pro._DataApi__token = TOKEN
pro._DataApi__http_url = HTTP_URL

OUTPUT = BASE_DIR / 'futures_data'


def find_project_root(start):
    for path in (Path(start).resolve(), *Path(start).resolve().parents):
        if (path / 'AI金融数据工作台进化规划.md').exists():
            return path
        if (path / 'apps').exists() and (path / 'services').exists() and (path / 'data').exists():
            return path
    return Path(start).resolve().parent


PROJECT_ROOT = find_project_root(BASE_DIR)


def resolve_project_path(value, default):
    path = Path(value) if value else default
    return path if path.is_absolute() else PROJECT_ROOT / path


DB_DIR = resolve_project_path(os.getenv('FUTURES_DATA_DIR'), PROJECT_ROOT / 'data')
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / 'futures.db'
LOG_DIR = BASE_DIR / 'logs' / '增量更新'
LOG_DIR.mkdir(parents=True, exist_ok=True)

TODAY_STR = datetime.now().strftime('%Y%m%d')
LOG_FILE = LOG_DIR / f'update_{TODAY_STR}.log'

# ============================ 日志 ============================
logger = logging.getLogger('daily_update')
logger.setLevel(logging.INFO)
logger.handlers.clear()
fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
fh.setLevel(logging.DEBUG)
fh.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-7s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(fh)
logger.addHandler(ch)

# ============================ 速率限制 ============================
class RateLimiter:
    def __init__(self, max_calls=200):
        self.max_calls = max_calls
        self._ts = deque()
    def wait(self):
        now = time.time()
        cutoff = now - 60
        while self._ts and self._ts[0] < cutoff:
            self._ts.popleft()
        if len(self._ts) >= self.max_calls:
            time.sleep(self._ts[0] - cutoff + 0.1)
            now = time.time()
            cutoff = now - 60
            while self._ts and self._ts[0] < cutoff:
                self._ts.popleft()
        self._ts.append(now)
limiter = RateLimiter(200)
FUTURES_EXCHANGES = ['CFFEX', 'SHFE', 'DCE', 'CZCE', 'INE', 'GFEX']
NH_INDEX_CODES = [
    'NHCI.NH',   # 南华商品指数
    'NHAI.NH',   # 南华农产品指数
    'NHECI.NH',  # 南华能化指数
    'NHFI.NH',   # 南华金融指数
    'NHII.NH',   # 南华工业品指数
    'NHMI.NH',   # 南华金属指数
]

# ============================ API 调用 ============================
def safe_call(func, name, **kwargs):
    for attempt in range(3):
        try:
            limiter.wait()
            df = func(**kwargs)
            return df if (df is not None and not df.empty) else pd.DataFrame()
        except Exception as e:
            if attempt == 2:
                logger.error(f'  [FAIL] {name}: {e}')
                return pd.DataFrame()
            time.sleep(5 * (attempt + 1))
    return pd.DataFrame()


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
            logger.warning(f'  [WARN] 读取交易日历失败，改用自然日: {e}')

    fmt = '%Y%m%d'
    s = datetime.strptime(start, fmt)
    e = datetime.strptime(end, fmt)
    dates = []
    while s <= e:
        if s.weekday() < 5:
            dates.append(s.strftime(fmt))
        s += timedelta(days=1)
    return dates


def month_window(months=4):
    """返回最近 N 个月的 YYYYMM 范围，用于发布有滞后的月度宏观数据。"""
    today = datetime.now()
    end_month = today.strftime('%Y%m')
    month_index = today.year * 12 + today.month - months + 1
    start_year = (month_index - 1) // 12
    start_month = (month_index - 1) % 12 + 1
    start_month_str = f'{start_year:04d}{start_month:02d}'
    return start_month_str, end_month


def normalize_case_columns(df):
    """统一列名大小写，并合并大小写不同但语义相同的重复列。"""
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

# ============================ 合并保存 ============================
def upsert_sqlite(table, df):
    """同步增量数据到 SQLite。"""
    if df is None or df.empty:
        return 0
    if not DB_PATH.exists():
        logger.warning(f'  [SQL] 数据库不存在，跳过: {DB_PATH}')
        return 0
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            rows = upsert_dataframe(conn, table, df)
            logger.info(f'  [SQL] {table}: upsert {rows} rows')
            return rows
    except Exception as e:
        logger.error(f'  [SQL] {table} 写入失败: {e}', exc_info=True)
        return 0


def merge_save(df_new, folder, filename, dedup_cols, table=None):
    """将新数据与已有 CSV 合并去重保存，并可同步写入 SQLite。"""
    d = OUTPUT / folder
    d.mkdir(parents=True, exist_ok=True)
    fp = d / filename

    existing_cols = set(df_new.columns)
    if fp.exists():
        try:
            df_old = pd.read_csv(fp, dtype=str)
            df_new = df_new.astype(object).where(pd.notna(df_new), None)
            common_cols = [c for c in df_new.columns if c in df_old.columns]
            if common_cols:
                combined = pd.concat([df_old[common_cols], df_new[common_cols]], ignore_index=True)
            else:
                combined = pd.concat([df_old, df_new], ignore_index=True)
        except Exception:
            logger.warning(f'  读取旧文件失败，将覆盖: {filename}')
            combined = df_new
    else:
        combined = df_new

    # 去重
    existing = [c for c in dedup_cols if c in combined.columns]
    if existing:
        before = len(combined)
        for c in existing:
            combined[c] = combined[c].astype(str)
        combined = combined.drop_duplicates(subset=existing, keep='last')
        logger.debug(f'  去重: {before} -> {len(combined)} rows')

    combined.to_csv(fp, index=False, encoding='utf-8-sig')
    if table:
        upsert_sqlite(table, df_new)
    return str(fp), len(combined), len(df_new)


# ============================ 各接口增量下载 ============================
def update_fut_basic():
    """期货合约列表（全量，数据量小直接覆盖）"""
    logger.info('[1/10] fut_basic -- 合约列表')
    exchanges = ['CFFEX', 'SHFE', 'DCE', 'CZCE', 'INE', 'GFEX']
    fut_types = {'1': '普通合约', '2': '主力连续', '3': '指数'}
    all_dfs = []
    for ex in exchanges:
        for ft, ft_name in fut_types.items():
            df = safe_call(pro.fut_basic, 'fut_basic', exchange=ex, fut_type=ft)
            if not df.empty:
                df['fut_type'] = ft_name
                all_dfs.append(df)
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        fp, total, new = merge_save(result, '01_合约列表', 'fut_basic_all.csv',
                                     ['ts_code', 'exchange'], table='fut_basic')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def update_trade_cal(start, end):
    """交易日历"""
    logger.info('[2/10] trade_cal -- 交易日历')
    exchanges = ['CFFEX', 'SHFE', 'DCE', 'CZCE', 'INE']
    all_dfs = []
    for ex in exchanges:
        df = safe_call(pro.trade_cal, 'trade_cal', exchange=ex, start_date=start, end_date=end)
        if not df.empty:
            all_dfs.append(df)
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        fp, total, new = merge_save(result, '02_交易日历', 'trade_cal_futures.csv',
                                     ['exchange', 'cal_date'], table='trade_cal')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def update_fut_daily(start, end):
    """日线行情"""
    logger.info(f'[3/10] fut_daily -- {start}~{end}')
    trade_dates = iter_trade_dates(start, end)
    all_dfs = []
    for trade_date in trade_dates:
        df = safe_call(pro.fut_daily, 'fut_daily', trade_date=trade_date)
        if not df.empty:
            logger.info(f'  {trade_date}: {len(df)} rows')
            if len(df) >= 2000:
                logger.warning(f'  [WARN] {trade_date} fut_daily rows reached 2000; retry by exchange.')
                fallback = download_fut_daily_by_exchange(trade_date)
                if not fallback.empty:
                    before = len(df)
                    df = pd.concat([df, fallback], ignore_index=True)
                    if {'ts_code', 'trade_date'}.issubset(df.columns):
                        df = df.drop_duplicates(subset=['ts_code', 'trade_date'], keep='last')
                    logger.info(f'  {trade_date}: merged fallback {before} + {len(fallback)} -> {len(df)} rows')
            all_dfs.append(df)
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        fp, total, new = merge_save(result, '03_日线行情', 'fut_daily_all.csv',
                                     ['ts_code', 'trade_date'], table='fut_daily')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def download_fut_daily_by_exchange(trade_date):
    """单日结果疑似达到接口上限时，按交易所兜底重拉。"""
    parts = []
    for exchange in FUTURES_EXCHANGES:
        df = safe_call(pro.fut_daily, 'fut_daily', trade_date=trade_date, exchange=exchange)
        if df.empty:
            logger.info(f'    fallback {trade_date} {exchange}: 0 rows')
            continue
        parts.append(df)
        logger.info(f'    fallback {trade_date} {exchange}: {len(df)} rows')
        if len(df) >= 2000:
            logger.warning(f'    [WARN] {trade_date} {exchange} fut_daily rows reached 2000; still may be truncated.')
    if not parts:
        logger.warning(f'    [WARN] {trade_date} fut_daily fallback returned no rows.')
        return pd.DataFrame()
    result = pd.concat(parts, ignore_index=True)
    if {'ts_code', 'trade_date'}.issubset(result.columns):
        result = result.drop_duplicates(subset=['ts_code', 'trade_date'], keep='last')
    return result


def update_weekly_monthly(start, end):
    """周线/月线"""
    logger.info(f'[4/10] fut_weekly_monthly -- {start}~{end}')
    all_dfs = []
    for freq in ('week', 'month'):
        df = safe_call(pro.fut_weekly_monthly, 'fut_weekly_monthly',
                       start_date=start, end_date=end, freq=freq)
        if not df.empty:
            all_dfs.append(df)
            logger.info(f'  {freq}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        fp, total, new = merge_save(result, '04_周月线', 'fut_weekly_monthly_all.csv',
                                     ['ts_code', 'trade_date', 'freq'], table='fut_weekly_monthly')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def update_fut_holding(start, end):
    """持仓排名"""
    logger.info(f'[5/10] fut_holding -- {start}~{end}')
    trade_dates = iter_trade_dates(start, end)
    all_dfs = []
    for trade_date in trade_dates:
        df = safe_call(pro.fut_holding, 'fut_holding', trade_date=trade_date)
        if not df.empty:
            all_dfs.append(df)
            logger.info(f'  {trade_date}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        fp, total, new = merge_save(result, '05_持仓排名', 'fut_holding_all.csv',
                                     ['symbol', 'trade_date', 'broker'], table='fut_holding')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def update_fut_wsr(start, end):
    """仓单日报"""
    logger.info(f'[6/10] fut_wsr -- {start}~{end}')
    trade_dates = iter_trade_dates(start, end)
    all_dfs = []
    for trade_date in trade_dates:
        df = safe_call(pro.fut_wsr, 'fut_wsr', trade_date=trade_date)
        if not df.empty:
            all_dfs.append(df)
            logger.info(f'  {trade_date}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        fp, total, new = merge_save(result, '06_仓单日报', 'fut_wsr_all.csv',
                                     ['symbol', 'trade_date', 'warehouse'], table='fut_wsr')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def update_fut_settle(start, end):
    """结算参数"""
    logger.info(f'[7/10] fut_settle -- {start}~{end}')
    trade_dates = iter_trade_dates(start, end)
    all_dfs = []
    for trade_date in trade_dates:
        df = safe_call(pro.fut_settle, 'fut_settle', trade_date=trade_date)
        if not df.empty:
            all_dfs.append(df)
            logger.info(f'  {trade_date}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        fp, total, new = merge_save(result, '07_结算参数', 'fut_settle_all.csv',
                                     ['ts_code', 'trade_date'], table='fut_settle')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def update_ft_limit(start, end):
    """涨跌停板"""
    logger.info(f'[8/10] ft_limit -- {start}~{end}')
    df = safe_call(pro.ft_limit, 'ft_limit', start_date=start, end_date=end)
    if not df.empty:
        fp, total, new = merge_save(df, '08_涨跌停板', 'ft_limit_all.csv',
                                     ['ts_code', 'trade_date'], table='ft_limit')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def update_fut_mapping(start, end):
    """主力/连续合约映射"""
    logger.info(f'[9/10] fut_mapping -- {start}~{end}')
    df = safe_call(pro.fut_mapping, 'fut_mapping', start_date=start, end_date=end)
    if not df.empty:
        fp, total, new = merge_save(df, '10_主力映射', 'fut_mapping_all.csv',
                                     ['ts_code', 'trade_date'], table='fut_mapping')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def update_index_daily(start, end):
    """南华期货指数"""
    logger.info(f'[10/10] index_daily -- {start}~{end}')
    all_dfs = []
    for ts_code in NH_INDEX_CODES:
        df = safe_call(pro.index_daily, 'index_daily', ts_code=ts_code, start_date=start, end_date=end)
        if not df.empty:
            all_dfs.append(df)
            logger.info(f'  {ts_code}: {len(df)} rows')
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        fp, total, new = merge_save(result, '11_期货指数', 'index_daily_all.csv',
                                     ['ts_code', 'trade_date'], table='index_daily')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def update_shibor(start, end):
    """SHIBOR 利率。"""
    logger.info(f'[11/16] shibor -- {start}~{end}')
    df = safe_call(pro.shibor, 'shibor', start_date=start, end_date=end)
    if not df.empty:
        fp, total, new = merge_save(df, '12_外部因子', 'shibor_all.csv',
                                     ['date'], table='shibor')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def update_fx_daily(start, end):
    """离岸人民币汇率日线。"""
    logger.info(f'[12/16] fx_daily USDCNH.FXCM -- {start}~{end}')
    df = safe_call(pro.fx_daily, 'fx_daily', ts_code='USDCNH.FXCM',
                   start_date=start, end_date=end)
    if not df.empty:
        fp, total, new = merge_save(df, '12_外部因子', 'fx_daily_all.csv',
                                     ['ts_code', 'trade_date'], table='fx_daily')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def update_sge_daily(start, end):
    """上海黄金交易所日线。"""
    logger.info(f'[13/16] sge_daily -- {start}~{end}')
    df = safe_call(pro.sge_daily, 'sge_daily', start_date=start, end_date=end)
    if not df.empty:
        fp, total, new = merge_save(df, '12_外部因子', 'sge_daily_all.csv',
                                     ['ts_code', 'trade_date'], table='sge_daily')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def update_cn_cpi(start_m, end_m):
    """中国 CPI 月度数据。"""
    logger.info(f'[14/16] cn_cpi -- {start_m}~{end_m}')
    df = safe_call(pro.cn_cpi, 'cn_cpi', start_m=start_m, end_m=end_m)
    if not df.empty:
        fp, total, new = merge_save(df, '13_宏观数据', 'cn_cpi_all.csv',
                                     ['month'], table='cn_cpi')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def update_cn_ppi(start_m, end_m):
    """中国 PPI 月度数据。"""
    logger.info(f'[15/16] cn_ppi -- {start_m}~{end_m}')
    df = safe_call(pro.cn_ppi, 'cn_ppi', start_m=start_m, end_m=end_m)
    if not df.empty:
        fp, total, new = merge_save(df, '13_宏观数据', 'cn_ppi_all.csv',
                                     ['month'], table='cn_ppi')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


def update_cn_pmi(start_m, end_m):
    """中国 PMI 月度数据。"""
    logger.info(f'[16/16] cn_pmi -- {start_m}~{end_m}')
    df = safe_call(pro.cn_pmi, 'cn_pmi', start_m=start_m, end_m=end_m)
    if not df.empty:
        df = normalize_case_columns(df)
        fp, total, new = merge_save(df, '13_宏观数据', 'cn_pmi_all.csv',
                                     ['month'], table='cn_pmi')
        logger.info(f'  [OK] {total} rows (新增 {new}) -> {fp}')
        return total
    logger.warning('  [WARN] 无数据')
    return 0


# ============================ 主流程 ============================
def is_trading_day(date_str):
    """
    通过已下载的交易日历 CSV 判断是否为交易日。
    如果 CSV 不存在，仅按周末判断。
    """
    cal_file = OUTPUT / '02_交易日历' / 'trade_cal_futures.csv'
    if cal_file.exists():
        try:
            cal = pd.read_csv(cal_file, dtype={'cal_date': str})
            if 'cal_date' in cal.columns and 'is_open' in cal.columns:
                row = cal[(cal['cal_date'] == date_str) & (cal['is_open'] == 1)]
                return len(row) > 0
        except Exception:
            pass
    # 回退：仅判断周末
    dt = datetime.strptime(date_str, '%Y%m%d')
    return dt.weekday() < 5  # 周一到周五


def should_skip_today(target_date=None):
    """
    判断是否应该跳过本次下载。
    返回 (skip: bool, reason: str)
    """
    target_date = target_date or (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')

    # 1. 检查目标日是周六/周日
    target_dt = datetime.strptime(target_date, '%Y%m%d')
    if target_dt.weekday() >= 5:
        return True, f'{target_date} 是周末（{target_dt.strftime("%A")}），预期无数据'

    # 2. 如果交易日历已存在，精准校验目标日是否为交易日
    if not is_trading_day(target_date):
        return True, f'{target_date} 非交易日（节假日休市），预期无数据'

    return False, ''


def run_incremental_update(start_date=None, end_date=None):
    """
    增量更新：下载最近 7 天的数据并合并到已有 CSV。
    宽裕的窗口（7天）确保不会因节假日等原因漏数据。
    周末/节假日自动跳过，避免无效 API 调用。
    """
    end_date = end_date or (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    start_date = start_date or (datetime.strptime(end_date, '%Y%m%d') - timedelta(days=7)).strftime('%Y%m%d')

    logger.info('=' * 60)
    logger.info('  期货数据每日增量更新')
    logger.info(f'  当前时间:   {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    logger.info(f'  数据范围:   {start_date} ~ {end_date}')
    logger.info(f'  模式:       合并到已有 CSV（仅新增行）')
    logger.info(f'  日志文件:   {LOG_FILE}')
    logger.info('=' * 60)

    # 先更新交易日历，再判断是否跳过。这样节假日判断不依赖过期的本地日历。
    r2 = update_trade_cal(start_date, end_date)

    # -------- 周末/节假日检查 --------
    skip, reason = should_skip_today(end_date)
    if skip:
        logger.info(f'  [SKIP] {reason}，跳过本次下载')
        # 写入简要报告（表明脚本正常运行）
        report_file = LOG_DIR / f'update_report_{TODAY_STR}.txt'
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.write(f'结果: 跳过（{reason}）\n')
        logger.info('')
        return {'status': 'skipped', 'reason': reason}

    t0 = time.time()

    # fut_basic 不需要日期范围
    r1 = update_fut_basic()
    r3 = update_fut_daily(start_date, end_date)
    r4 = update_weekly_monthly(start_date, end_date)
    r5 = update_fut_holding(start_date, end_date)
    r6 = update_fut_wsr(start_date, end_date)
    r7 = update_fut_settle(start_date, end_date)
    r8 = update_ft_limit(start_date, end_date)
    r9 = update_fut_mapping(start_date, end_date)
    r10 = update_index_daily(start_date, end_date)
    r11 = update_shibor(start_date, end_date)
    r12 = update_fx_daily(start_date, end_date)
    r13 = update_sge_daily(start_date, end_date)
    start_m, end_m = month_window(4)
    r14 = update_cn_cpi(start_m, end_m)
    r15 = update_cn_ppi(start_m, end_m)
    r16 = update_cn_pmi(start_m, end_m)

    elapsed = time.time() - t0

    # 简易摘要
    results = {
        'fut_basic': r1, 'trade_cal': r2, 'fut_daily': r3,
        'weekly_monthly': r4, 'fut_holding': r5, 'fut_wsr': r6,
        'fut_settle': r7, 'ft_limit': r8, 'fut_mapping': r9,
        'index_daily': r10, 'shibor': r11, 'fx_daily': r12,
        'sge_daily': r13, 'cn_cpi': r14, 'cn_ppi': r15,
        'cn_pmi': r16,
    }
    ok_count = sum(1 for v in results.values() if v > 0)
    total_rows = sum(results.values())
    total_interfaces = len(results)

    summary = [
        '',
        '=' * 50,
        f'  更新完成! 耗时 {elapsed:.0f}s  |  {ok_count}/{total_interfaces} 接口有数据',
        f'  新增行数合计: {total_rows}',
        f'  日志: {LOG_FILE}',
        '=' * 50,
    ]
    for line in summary:
        logger.info(line)

    # 写入简要报告
    report_file = LOG_DIR / f'update_report_{TODAY_STR}.txt'
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f'更新时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
        f.write(f'数据范围: {start_date} ~ {end_date}\n')
        f.write(f'耗时: {elapsed:.0f}s\n')
        f.write(f'成功接口: {ok_count}/{total_interfaces}\n')
        f.write(f'新增行数: {total_rows}\n')
        f.write('\n各接口详情:\n')
        for name, rows in results.items():
            f.write(f'  {name}: {rows} rows\n')

    # ---- 按品种拆分 ----
    logger.info('')
    logger.info('[SPLIT] 开始按品种拆分数据...')
    try:
        split_result = run_split(quiet=True)
        logger.info(f'[SPLIT] 完成: {split_result["products"]} 个品种')
    except Exception as e:
        logger.error(f'[SPLIT] 拆分失败: {e}')

    return results


# ============================ 入口 ============================
if __name__ == '__main__':
    import argparse
    import traceback as _tb

    # ---- 全局异常兜底（防止双击闪退） ----
    try:
        parser = argparse.ArgumentParser(description='期货数据每日增量更新')
        parser.add_argument('--now', action='store_true', help='立即执行一次')
        parser.add_argument('--start-date', help='开始日期 YYYYMMDD，默认按结束日期向前 7 天')
        parser.add_argument('--end-date', help='结束日期 YYYYMMDD，默认昨天')
        args = parser.parse_args()

        if args.now:
            started_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            result = run_incremental_update(start_date=args.start_date, end_date=args.end_date)
            status = 'skipped' if isinstance(result, dict) and result.get('status') == 'skipped' else 'success'
            record_task_run(
                DB_PATH,
                task_type='data_update',
                task_name='数据更新',
                status=status,
                target_date=args.end_date or '',
                detail=f'{args.start_date or ""}~{args.end_date or ""}',
                output=str(result),
                started_at=started_at,
            )
            print()
            print('更新完成。窗口将在 10 秒后关闭，或按 Enter 立即关闭...')
            try:
                import msvcrt
                for _ in range(100):
                    if msvcrt.kbhit() and msvcrt.getch() in (b'\r', b'\n', b' '):
                        break
                    time.sleep(0.1)
            except ImportError:
                time.sleep(5)
        else:
            import schedule

            print()
            print('=' * 60)
            print('  期货数据每日增量更新')
            print('=' * 60)
            print(f'  当前时间:   {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
            print(f'  触发时间:   每天凌晨 04:00')
            print(f'  数据范围:   最近 7 天')
            print(f'  模式:       合并到已有 CSV')
            print(f'  日志目录:   {LOG_DIR.resolve()}')
            print(f'  关闭窗口即可停止')
            print(f'  提示: 如果想立即更新，请用: python daily_update.py --now')
            print('=' * 60)
            print()

            schedule.every().day.at('04:00').do(run_incremental_update)

            while True:
                try:
                    schedule.run_pending()
                    sys.stdout.write(
                        f'\r  当前时间: {datetime.now().strftime("%H:%M:%S")}  '
                        f'|  等待 04:00 触发...  '
                    )
                    sys.stdout.flush()
                    time.sleep(30)
                except KeyboardInterrupt:
                    print('\n\n  已手动停止。')
                    break
                except Exception as e:
                    logger.error(f'调度异常: {e}', exc_info=True)
                    time.sleep(60)

    except SystemExit:
        pass
    except Exception:
        try:
            record_task_run(
                DB_PATH,
                task_type='data_update',
                task_name='数据更新',
                status='failed',
                target_date='',
                detail='',
                error=_tb.format_exc(),
            )
        except Exception:
            pass
        print()
        print('=' * 60)
        print('  发生错误，脚本异常退出：')
        print('=' * 60)
        _tb.print_exc()
        print()
        print('  日志文件: logs/update_*.log')
        print()
        input('按 Enter 关闭窗口...')

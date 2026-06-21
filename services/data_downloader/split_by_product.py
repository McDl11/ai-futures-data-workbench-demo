"""
按品种拆分期货数据 → by_product/ 目录
=========================================
从全量 CSV 中提取每个品种的数据，存入独立目录，
方便 AI / RAG 按品种加载上下文。

用法：
  python split_by_product.py           # 拆分全部接口
  python split_by_product.py --quiet   # 静默模式（被 daily_update 调用时使用）

输出结构：
  futures_data/by_product/
    A/           ← 豆一
      basic.csv      ← 该品种全部合约
      daily.csv      ← 日线行情
      holding.csv    ← 持仓排名
      wsr.csv        ← 仓单日报
      settle.csv     ← 结算参数
      limit.csv      ← 涨跌停板
      weekly_monthly.csv ← 周/月线行情
      mapping.csv    ← 主力/连续合约映射
    RB/           ← 螺纹钢
    ...
    calendar/     ← 交易日历（共享）
      trade_cal.csv
    index/        ← 南华期货指数
      index_daily.csv
"""

import os
import re
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd

# ============================ 路径 ============================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'futures_data'
BY_PRODUCT_DIR = DATA_DIR / 'by_product'
LOG_DIR = BASE_DIR / 'logs' / '品种拆分'
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ============================ 日志 ============================
logger = logging.getLogger('splitter')
logger.setLevel(logging.INFO)
logger.handlers.clear()

LOG_FILE = LOG_DIR / f'split_{datetime.now().strftime("%Y%m%d")}.log'
fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
fh.setLevel(logging.DEBUG)
fh.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(fh)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(ch)


# ============================ 品种代码提取 ============================
def extract_product(ts_code_or_symbol: str) -> str:
    """
    从 ts_code 或 symbol 中提取品种代码。
    - "A.DCE"       → "A"
    - "A2401.DCE"   → "A"
    - "RB2401.SHF"  → "RB"
    - "NI2402"      → "NI"
    - "000001.SH"   → "000001"  (指数类，不进品种目录)
    - "SM2402"      → "SM"
    """
    code = str(ts_code_or_symbol).strip()
    # 去掉后缀 .DCE / .SHF / .CZC / .CFX / .INE / .GFX
    code = code.split('.')[0]
    # 提取前导字母
    m = re.match(r'^([A-Za-z]+)', code)
    if m:
        return m.group(1).upper()
    # 纯数字（指数类）
    return code


def is_futures_product(code: str) -> bool:
    """判断是否为期货品种代码（排除纯数字指数类）"""
    return bool(re.match(r'^[A-Za-z]+$', code))


# ============================ 接口→文件名映射 ============================
# (源目录, 源文件, by_product下的文件名, 品种识别列, 是否需要拆分)
# 需要拆分的用 ts_code 或 symbol 列提取品种
# 不需要拆分的直接拷贝到 calendar/ 或 index/
SOURCE_CONFIG = [
    # ---- 按品种拆分 ----
    {
        'folder': '01_合约列表',
        'file': 'fut_basic_all.csv',
        'out_name': 'basic.csv',
        'product_col': 'ts_code',
        'split': True,
    },
    {
        'folder': '03_日线行情',
        'file': 'fut_daily_all.csv',
        'out_name': 'daily.csv',
        'product_col': 'ts_code',
        'split': True,
    },
    {
        'folder': '04_周月线',
        'file': 'fut_weekly_monthly_all.csv',
        'out_name': 'weekly_monthly.csv',
        'product_col': 'ts_code',
        'split': True,
    },
    {
        'folder': '05_持仓排名',
        'file': 'fut_holding_all.csv',
        'out_name': 'holding.csv',
        'product_col': 'symbol',
        'split': True,
    },
    {
        'folder': '06_仓单日报',
        'file': 'fut_wsr_all.csv',
        'out_name': 'wsr.csv',
        'product_col': 'symbol',
        'split': True,
    },
    {
        'folder': '07_结算参数',
        'file': 'fut_settle_all.csv',
        'out_name': 'settle.csv',
        'product_col': 'ts_code',
        'split': True,
    },
    {
        'folder': '08_涨跌停板',
        'file': 'ft_limit_all.csv',
        'out_name': 'limit.csv',
        'product_col': 'ts_code',
        'split': True,
    },
    {
        'folder': '10_主力映射',
        'file': 'fut_mapping_all.csv',
        'out_name': 'mapping.csv',
        'product_col': 'ts_code',
        'split': True,
    },
    # ---- 共享/全局 ----
    {
        'folder': '02_交易日历',
        'file': 'trade_cal_futures.csv',
        'out_name': 'calendar/trade_cal.csv',
        'product_col': None,
        'split': False,
    },
    {
        'folder': '11_期货指数',
        'file': 'index_daily_all.csv',
        'out_name': 'index/index_daily.csv',
        'product_col': None,
        'split': False,
    },
]


def split_single_source(cfg: dict) -> dict:
    """拆分/拷贝单个数据源，返回统计信息"""
    src_path = DATA_DIR / cfg['folder'] / cfg['file']

    if not src_path.exists():
        logger.warning(f'  [SKIP] 文件不存在: {src_path}')
        return {'source': cfg['file'], 'exists': False, 'products': 0, 'rows': 0}

    try:
        df = pd.read_csv(src_path, dtype=str)
    except Exception as e:
        logger.error(f'  [ERROR] 读取失败: {src_path} → {e}')
        return {'source': cfg['file'], 'exists': True, 'error': str(e), 'products': 0, 'rows': 0}

    if df.empty:
        logger.warning(f'  [SKIP] 文件为空: {cfg["file"]}')
        return {'source': cfg['file'], 'exists': True, 'empty': True, 'products': 0, 'rows': 0}

    if not cfg['split']:
        # ---- 不拆分，直接拷贝 ----
        out_path = BY_PRODUCT_DIR / cfg['out_name']
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False, encoding='utf-8-sig')
        logger.info(f'  [OK] {cfg["file"]} → {out_path} ({len(df)} rows)')
        return {'source': cfg['file'], 'exists': True, 'products': 1, 'rows': len(df)}

    # ---- 按品种拆分 ----
    col = cfg['product_col']
    if col not in df.columns:
        logger.error(f'  [ERROR] 列缺失: {cfg["file"]} 无 "{col}" 列')
        return {'source': cfg['file'], 'exists': True, 'error': f'列 "{col}" 缺失', 'products': 0, 'rows': 0}

    # 提取品种代码
    df['_product'] = df[col].apply(extract_product)

    # 只保留真正的期货品种（过滤指数类）
    df_futures = df[df['_product'].apply(is_futures_product)].copy()
    df_other = df[~df['_product'].apply(is_futures_product)].copy()

    product_count = 0
    total_rows = 0

    # 按品种分组写出
    for prod, group in df_futures.groupby('_product'):
        group = group.drop(columns=['_product'])
        out_dir = BY_PRODUCT_DIR / prod
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / cfg['out_name']

        # 合并已有文件（增量模式）
        if out_file.exists():
            try:
                existing = pd.read_csv(out_file, dtype=str)
                combined = pd.concat([existing, group], ignore_index=True)
                # 根据源类型去重
                dedup_cols = get_dedup_cols(cfg['out_name'])
                existing_dedup = [c for c in dedup_cols if c in combined.columns]
                if existing_dedup:
                    before = len(combined)
                    combined = combined.drop_duplicates(subset=existing_dedup, keep='last')
                    logger.debug(f'    {prod}: 去重 {before}→{len(combined)}')
                combined.to_csv(out_file, index=False, encoding='utf-8-sig')
            except Exception:
                group.to_csv(out_file, index=False, encoding='utf-8-sig')
        else:
            group.to_csv(out_file, index=False, encoding='utf-8-sig')

        product_count += 1
        total_rows += len(group)

    # 非期货品种的条目（如指数类 ts_code）计入 index 目录
    if not df_other.empty:
        df_other = df_other.drop(columns=['_product'])
        if cfg['out_name'] in ('basic.csv', 'daily.csv'):
            # 指数类合约也归入 index/ 目录
            idx_dir = BY_PRODUCT_DIR / 'index'
            idx_dir.mkdir(parents=True, exist_ok=True)
            idx_file = idx_dir / cfg['out_name']
            if idx_file.exists():
                try:
                    existing = pd.read_csv(idx_file, dtype=str)
                    combined = pd.concat([existing, df_other], ignore_index=True)
                    dedup_cols = get_dedup_cols(cfg['out_name'])
                    existing_dedup = [c for c in dedup_cols if c in combined.columns]
                    if existing_dedup:
                        combined = combined.drop_duplicates(subset=existing_dedup, keep='last')
                    combined.to_csv(idx_file, index=False, encoding='utf-8-sig')
                except Exception:
                    df_other.to_csv(idx_file, index=False, encoding='utf-8-sig')
            else:
                df_other.to_csv(idx_file, index=False, encoding='utf-8-sig')

    logger.info(f'  [OK] {cfg["file"]} → {product_count} 个品种, {total_rows} rows')
    return {'source': cfg['file'], 'exists': True, 'products': product_count, 'rows': total_rows}


def get_dedup_cols(out_name: str) -> list:
    """根据文件名返回去重列"""
    mapping = {
        'basic.csv':      ['ts_code', 'exchange'],
        'daily.csv':      ['ts_code', 'trade_date'],
        'weekly_monthly.csv': ['ts_code', 'trade_date', 'freq'],
        'holding.csv':    ['symbol', 'trade_date', 'broker'],
        'wsr.csv':        ['symbol', 'trade_date', 'warehouse'],
        'settle.csv':     ['ts_code', 'trade_date'],
        'limit.csv':      ['ts_code', 'trade_date'],
        'mapping.csv':    ['ts_code', 'trade_date'],
    }
    return mapping.get(out_name, [])


def generate_product_index():
    """
    生成 by_product 下的 README.md 和品种清单，
    方便 AI 快速了解有哪些品种。
    """
    products = []
    for item in sorted(BY_PRODUCT_DIR.iterdir()):
        if item.is_dir() and item.name not in ('calendar', 'index'):
            files = sorted([f.name for f in item.iterdir() if f.suffix == '.csv'])
            products.append((item.name, files))

    lines = [
        '# 期货品种数据目录',
        '',
        f'> 更新时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        '',
        '## 品种列表',
        '',
        '| 品种 | 代码 | 数据文件 |',
        '|------|------|----------|',
    ]

    for prod, files in products:
        file_list = ', '.join(files)
        lines.append(f'| {prod} | {prod} | {file_list} |')

    lines.extend([
        '',
        '## 共享数据',
        '',
        '- `calendar/` — 交易日历（所有品种共用）',
        '- `index/` — 南华期货指数日线',
        '',
        '## AI 使用建议',
        '',
        '1. **按需加载**：只需要某个品种时，只读取该品种目录下的 CSV 文件',
        '2. **多维度关联**：同一品种的 basic.csv + daily.csv + mapping.csv + holding.csv 天然关联',
        '3. **数据量友好**：单个品种数据通常在几百 KB ~ 几十 MB，适合直接投喂 AI',
    ])

    readme_path = BY_PRODUCT_DIR / 'README.md'
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    logger.info(f'  [OK] 品种索引: {readme_path}')
    return len(products)


# ============================ 主入口 ============================
def run_split(quiet: bool = False):
    """执行完整拆分"""
    if quiet:
        logger.setLevel(logging.WARNING)
        ch.setLevel(logging.WARNING)

    t0 = time.time()
    logger.info('=' * 60)
    logger.info('  期货数据按品种拆分')
    logger.info(f'  时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    logger.info(f'  输出: {BY_PRODUCT_DIR}')
    logger.info('=' * 60)

    BY_PRODUCT_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for cfg in SOURCE_CONFIG:
        r = split_single_source(cfg)
        results.append(r)

    # 生成品种索引
    n_products = generate_product_index()

    # 汇总
    elapsed = time.time() - t0
    ok = sum(1 for r in results if r.get('products', 0) > 0 or r.get('exists') and not r.get('error'))
    failed = sum(1 for r in results if r.get('error'))

    logger.info('')
    logger.info('=' * 50)
    logger.info(f'  拆分完成! 耗时 {elapsed:.1f}s')
    logger.info(f'  数据源: {ok}/{len(results)} 成功')
    logger.info(f'  品种数: {n_products} 个')
    logger.info(f'  日志:   {LOG_FILE}')
    logger.info('=' * 50)

    return {'ok': ok, 'failed': failed, 'products': n_products, 'elapsed': elapsed, 'results': results}


# ============================ 命令行入口 ============================
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='按品种拆分期货数据')
    parser.add_argument('--quiet', action='store_true', help='静默模式')
    args = parser.parse_args()
    run_split(quiet=args.quiet)

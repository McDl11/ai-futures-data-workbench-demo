import re
from datetime import datetime, timedelta

import pandas as pd


MAIN_CODE_RE = re.compile(r'^[A-Z_]+[.][A-Z]+$')

SECTOR_BY_FUT_CODE = {
    # 黑色建材
    'RB': '黑色建材', 'HC': '黑色建材', 'I': '黑色建材', 'J': '黑色建材',
    'JM': '黑色建材', 'SM': '黑色建材', 'SF': '黑色建材', 'SS': '黑色建材',
    'FG': '黑色建材',
    # 能源化工
    'SC': '能源化工', 'FU': '能源化工', 'LU': '能源化工', 'BU': '能源化工',
    'PG': '能源化工', 'RU': '能源化工', 'NR': '能源化工', 'L': '能源化工',
    'V': '能源化工', 'PP': '能源化工', 'TA': '能源化工', 'EG': '能源化工',
    'MA': '能源化工', 'UR': '能源化工', 'SA': '能源化工', 'PF': '能源化工',
    'PX': '能源化工', 'BR': '能源化工',
    # 有色金属
    'CU': '有色金属', 'AL': '有色金属', 'AD': '有色金属', 'ZN': '有色金属', 'PB': '有色金属',
    'NI': '有色金属', 'SN': '有色金属', 'AO': '有色金属', 'SI': '有色金属',
    'BC': '有色金属',
    # 新能源材料
    'LC': '新能源材料', 'PS': '新能源材料',
    # 贵金属
    'AU': '贵金属', 'AG': '贵金属', 'PD': '贵金属', 'PT': '贵金属',
    # 农产品
    'A': '农产品', 'B': '农产品', 'M': '农产品', 'Y': '农产品',
    'P': '农产品', 'OI': '农产品', 'RM': '农产品', 'C': '农产品',
    'CS': '农产品', 'JD': '农产品', 'LH': '农产品', 'AP': '农产品',
    'CJ': '农产品', 'SR': '农产品', 'CF': '农产品', 'CY': '农产品',
    'PK': '农产品', 'RR': '农产品', 'RS': '农产品',
    # 金融期货
    'IF': '金融期货', 'IH': '金融期货', 'IC': '金融期货', 'IM': '金融期货',
    'T': '金融期货', 'TF': '金融期货', 'TS': '金融期货', 'TL': '金融期货',
    # 航运
    'EC': '航运指数',
    # 林纸商品
    'BB': '林纸商品', 'FB': '林纸商品', 'LG': '林纸商品',
    'OP': '林纸商品', 'SP': '林纸商品',
    # 其他已上市化工/建材细分
    'BZ': '能源化工', 'EB': '能源化工', 'PL': '能源化工',
    'PR': '能源化工', 'SH': '能源化工', 'L_F': '能源化工',
    'PP_F': '能源化工', 'V_F': '能源化工',
    'WR': '黑色建材',
}


def to_num(series):
    return pd.to_numeric(series, errors='coerce')


def product_code(row):
    code = row.get('fut_code') if hasattr(row, 'get') else None
    if code is None or pd.isna(code) or str(code).strip() == '':
        ts_code = str(row.get('ts_code', '')) if hasattr(row, 'get') else ''
        code = re.sub(r'[^A-Za-z_]', '', ts_code.split('.')[0])
    return str(code).upper().strip()


def classify_sector(code):
    return SECTOR_BY_FUT_CODE.get(str(code).upper().strip(), '其他')


def fmt_pct_value(value):
    if value is None or pd.isna(value):
        return '-'
    try:
        return f'{float(value):+.2f}%'
    except (TypeError, ValueError):
        return str(value)


def fmt_num_value(value):
    if value is None or pd.isna(value):
        return '-'
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(value) >= 100000000:
        return f'{value / 100000000:.2f}亿'
    if abs(value) >= 10000:
        return f'{value / 10000:.2f}万'
    return f'{value:.0f}'


def pct_change(close, pre_settle):
    close = to_num(close)
    pre_settle = to_num(pre_settle)
    return ((close - pre_settle) / pre_settle * 100).where(pre_settle != 0)


def clean_daily(daily, basic):
    if daily.empty:
        return daily

    df = daily.copy()
    for col in ['pre_close', 'pre_settle', 'open', 'high', 'low', 'close', 'settle',
                'change1', 'change2', 'vol', 'amount', 'oi', 'oi_chg']:
        if col in df.columns:
            df[col] = to_num(df[col])
    df['pct_chg'] = pct_change(df['close'], df['pre_settle'])
    df['is_main_series'] = df['ts_code'].astype(str).map(lambda x: bool(MAIN_CODE_RE.match(x)))

    basic_cols = ['ts_code', 'symbol', 'name', 'fut_code', 'exchange', 'fut_type']
    df = df.merge(basic[basic_cols], on='ts_code', how='left')
    df['display_name'] = df['name'].fillna(df['ts_code'])
    return df


def main_series(daily):
    if daily.empty or 'is_main_series' not in daily.columns:
        return pd.DataFrame()
    df = daily[daily['is_main_series']].copy()
    df = df[~df['ts_code'].str.contains('L1|L2|L3', regex=True, na=False)]
    if 'display_name' in df.columns:
        df = df[~df['display_name'].astype(str).str.contains('连续', na=False)]
    df = df[df['vol'].fillna(0) > 0]
    if not df.empty:
        return df

    fallback = daily[~daily['is_main_series']].copy()
    fallback = fallback[fallback['vol'].fillna(0) > 0]
    if fallback.empty:
        return fallback
    fallback['product_code'] = fallback.apply(product_code, axis=1)
    fallback = fallback.sort_values(['product_code', 'vol', 'oi'], ascending=[True, False, False])
    fallback = fallback.drop_duplicates('product_code', keep='first')
    fallback['display_name'] = fallback.apply(
        lambda row: f'{row.get("name") or row["product_code"]}主力',
        axis=1,
    )
    return fallback


def market_overview(main_df):
    if main_df.empty:
        return {
            'contracts': 0,
            'up_count': 0,
            'down_count': 0,
            'flat_count': 0,
            'avg_pct_chg': None,
            'total_vol': None,
            'total_oi': None,
        }

    pct = main_df['pct_chg']
    return {
        'contracts': int(len(main_df)),
        'up_count': int((pct > 0).sum()),
        'down_count': int((pct < 0).sum()),
        'flat_count': int((pct == 0).sum()),
        'avg_pct_chg': pct.mean(),
        'total_vol': main_df['vol'].sum(),
        'total_oi': main_df['oi'].sum(),
    }


def top_table(df, sort_col, n=10, ascending=False, columns=None):
    if df.empty or sort_col not in df.columns:
        return pd.DataFrame()
    result = df.sort_values(sort_col, ascending=ascending).head(n).copy()
    if columns:
        keep = [c for c in columns if c in result.columns]
        result = result[keep]
    return result


def volume_anomaly(daily, loader, trade_date, n=10):
    if daily.empty:
        return pd.DataFrame()

    start_date = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=30)).strftime('%Y%m%d')
    dates = loader.read_sql(
        """
        select distinct trade_date
        from fut_daily
        where trade_date between :start_date and :trade_date
        order by trade_date desc
        limit 6
        """,
        {'start_date': start_date, 'trade_date': trade_date},
    )
    if len(dates) < 2:
        return pd.DataFrame()
    selected_dates = dates['trade_date'].astype(str).tolist()
    placeholders = ','.join(f"'{d}'" for d in selected_dates)
    hist = loader.read_sql(
        f"""
        select ts_code, trade_date, vol
        from fut_daily
        where trade_date in ({placeholders})
        """,
    )
    if hist.empty:
        return pd.DataFrame()
    hist['vol'] = to_num(hist['vol'])
    prev = hist[hist['trade_date'] < trade_date]
    avg = prev.groupby('ts_code', as_index=False)['vol'].mean().rename(columns={'vol': 'vol_5d_avg'})
    current = daily[['ts_code', 'display_name', 'close', 'pct_chg', 'vol', 'oi']].copy()
    result = current.merge(avg, on='ts_code', how='left')
    result['vol_ratio'] = result['vol'] / result['vol_5d_avg']
    result = result[(result['vol_5d_avg'] > 0) & (result['vol_ratio'] >= 1.5)]
    return result.sort_values('vol_ratio', ascending=False).head(n)


def limit_events(main_df, ft_limit):
    if main_df.empty or ft_limit.empty:
        return pd.DataFrame()
    lim = ft_limit.copy()
    for col in ['up_limit', 'down_limit']:
        lim[col] = to_num(lim[col])
    df = main_df.merge(lim[['ts_code', 'up_limit', 'down_limit']], on='ts_code', how='left')
    df['dist_up_pct'] = (df['up_limit'] - df['close']) / df['close'] * 100
    df['dist_down_pct'] = (df['close'] - df['down_limit']) / df['close'] * 100
    df['limit_status'] = ''
    df.loc[df['close'] >= df['up_limit'], 'limit_status'] = '涨停'
    df.loc[df['close'] <= df['down_limit'], 'limit_status'] = '跌停'
    near = df[
        (df['limit_status'] != '')
        | (df['dist_up_pct'].between(0, 1.0))
        | (df['dist_down_pct'].between(0, 1.0))
    ].copy()
    return near.sort_values(['limit_status', 'dist_up_pct', 'dist_down_pct']).head(20)


def wsr_summary(wsr, n=10):
    if wsr.empty:
        return pd.DataFrame(), pd.DataFrame()
    df = wsr.copy()
    df['vol'] = to_num(df['vol'])
    df['vol_chg'] = to_num(df['vol_chg'])
    name_map = (
        df.dropna(subset=['fut_name'])
        .drop_duplicates('symbol')
        .set_index('symbol')['fut_name']
        .to_dict()
    )
    grouped = df.groupby('symbol', dropna=False, as_index=False).agg(
        vol=('vol', 'sum'),
        vol_chg=('vol_chg', 'sum'),
    )
    grouped['fut_name'] = grouped['symbol'].map(name_map).fillna(grouped['symbol'])
    up = grouped.sort_values('vol_chg', ascending=False).head(n)
    down = grouped.sort_values('vol_chg', ascending=True).head(n)
    return up, down


def holding_summary(holding, n=10):
    if holding.empty:
        return pd.DataFrame()
    df = holding.copy()
    for col in ['vol', 'vol_chg', 'long_hld', 'long_chg', 'short_hld', 'short_chg']:
        df[col] = to_num(df[col])
    grouped = df.groupby('symbol', as_index=False).agg(
        vol=('vol', 'sum'),
        vol_chg=('vol_chg', 'sum'),
        long_hld=('long_hld', 'sum'),
        long_chg=('long_chg', 'sum'),
        short_hld=('short_hld', 'sum'),
        short_chg=('short_chg', 'sum'),
    )
    grouped['net_long'] = grouped['long_hld'] - grouped['short_hld']
    grouped['net_long_chg'] = grouped['long_chg'] - grouped['short_chg']
    return grouped.reindex(grouped['net_long_chg'].abs().sort_values(ascending=False).index).head(n)


def index_summary(index_daily, n=10):
    if index_daily.empty:
        return pd.DataFrame()
    df = index_daily.copy()
    for col in ['close', 'change', 'pct_chg', 'vol', 'amount']:
        df[col] = to_num(df[col])
    return df.sort_values('pct_chg', ascending=False).head(n)


def external_summary(shibor, fx, sge, macro):
    items = []
    if not shibor.empty:
        latest = shibor.iloc[0]
        prev = shibor.iloc[1] if len(shibor) > 1 else None
        on_chg = None
        if prev is not None:
            on_chg = to_num(pd.Series([latest.get('on')])).iloc[0] - to_num(pd.Series([prev.get('on')])).iloc[0]
        items.append({
            'name': 'SHIBOR O/N',
            'date': latest.get('date'),
            'value': latest.get('on'),
            'change': on_chg,
        })
    if not fx.empty:
        latest = fx.iloc[0]
        prev = fx.iloc[1] if len(fx) > 1 else None
        close = to_num(pd.Series([latest.get('bid_close')])).iloc[0]
        chg = None
        if prev is not None:
            chg = close - to_num(pd.Series([prev.get('bid_close')])).iloc[0]
        items.append({
            'name': 'USDCNH',
            'date': latest.get('trade_date'),
            'value': close,
            'change': chg,
        })
    if not sge.empty:
        au = sge[sge['ts_code'].astype(str).str.contains('Au|AU|iAu', regex=True, na=False)].copy()
        if not au.empty:
            au['amount'] = to_num(au['amount'])
            row = au.sort_values('amount', ascending=False).iloc[0]
            items.append({
                'name': f'SGE {row.get("ts_code")}',
                'date': row.get('trade_date'),
                'value': row.get('close'),
                'change': row.get('pct_change'),
            })
    for key, label, field in [
        ('cpi', 'CPI 同比', 'nt_yoy'),
        ('ppi', 'PPI 同比', 'ppi_yoy'),
        ('pmi', '制造业 PMI', 'pmi010000'),
    ]:
        df = macro.get(key)
        if df is not None and not df.empty:
            row = df.iloc[0]
            items.append({
                'name': label,
                'date': row.get('month'),
                'value': row.get(field),
                'change': None,
            })
    return pd.DataFrame(items)


def sector_strength(main_df):
    if main_df.empty:
        return pd.DataFrame(columns=[
            'sector', 'contracts', 'avg_pct_chg', 'up_count', 'down_count',
            'up_ratio', 'total_vol', 'total_oi', 'total_oi_chg'
        ])

    df = main_df.copy()
    df['sector'] = df.apply(lambda row: classify_sector(product_code(row)), axis=1)
    grouped = df.groupby('sector', as_index=False).agg(
        contracts=('ts_code', 'count'),
        avg_pct_chg=('pct_chg', 'mean'),
        up_count=('pct_chg', lambda s: int((s > 0).sum())),
        down_count=('pct_chg', lambda s: int((s < 0).sum())),
        total_vol=('vol', 'sum'),
        total_oi=('oi', 'sum'),
        total_oi_chg=('oi_chg', 'sum'),
    )
    grouped['up_ratio'] = grouped['up_count'] / grouped['contracts'] * 100
    return grouped.sort_values('avg_pct_chg', ascending=False)


def _first_row(df):
    if df is None or df.empty:
        return None
    return df.iloc[0]


def _display_name(row):
    if row is None:
        return ''
    value = row.get('display_name') if hasattr(row, 'get') else None
    if value is None or pd.isna(value) or str(value).strip() == '':
        value = row.get('ts_code', '') if hasattr(row, 'get') else ''
    return str(value)


def focus_highlights(overview, sectors, gainers, losers, vol_anom, oi_chg_top, limits, ext):
    highlights = []
    up_count = overview.get('up_count', 0)
    down_count = overview.get('down_count', 0)
    avg_pct = overview.get('avg_pct_chg')
    if up_count > down_count:
        highlights.append(f'市场上涨品种多于下跌品种，平均涨跌幅 {fmt_pct_value(avg_pct)}，整体情绪偏强。')
    elif down_count > up_count:
        highlights.append(f'市场下跌品种多于上涨品种，平均涨跌幅 {fmt_pct_value(avg_pct)}，整体情绪偏弱。')
    else:
        highlights.append(f'市场涨跌数量接近，平均涨跌幅 {fmt_pct_value(avg_pct)}，整体分歧较大。')

    if sectors is not None and not sectors.empty:
        strong = sectors.iloc[0]
        weak = sectors.iloc[-1]
        highlights.append(
            f'板块上，{strong["sector"]}表现靠前，平均涨跌幅 {fmt_pct_value(strong["avg_pct_chg"])}；'
            f'{weak["sector"]}相对偏弱，平均涨跌幅 {fmt_pct_value(weak["avg_pct_chg"])}。'
        )

    top_gainer = _first_row(gainers)
    top_loser = _first_row(losers)
    if top_gainer is not None:
        highlights.append(f'强势合约表现：{_display_name(top_gainer)}，涨跌幅 {fmt_pct_value(top_gainer.get("pct_chg"))}。')
    if top_loser is not None:
        highlights.append(f'弱势合约表现：{_display_name(top_loser)}，涨跌幅 {fmt_pct_value(top_loser.get("pct_chg"))}。')

    vol_row = _first_row(vol_anom)
    if vol_row is not None:
        highlights.append(
            f'成交异动方面，{_display_name(vol_row)}成交量约为近 5 日均量的 '
            f'{fmt_num_value(vol_row.get("vol_ratio"))} 倍。'
        )

    oi_row = _first_row(oi_chg_top)
    if oi_row is not None:
        highlights.append(
            f'持仓变化方面，{_display_name(oi_row)}持仓变化 {fmt_num_value(oi_row.get("oi_chg"))}，'
            f'需结合价格方向观察资金态度。'
        )

    if limits is not None and not limits.empty:
        first_limit = limits.iloc[0]
        highlights.append(f'涨跌停风险方面，发现 {len(limits)} 个涨跌停或临近涨跌停事件，代表合约为 {_display_name(first_limit)}。')

    if ext is not None and not ext.empty:
        fx = ext[ext['name'].astype(str).str.contains('USDCNH', na=False)]
        if not fx.empty:
            row = fx.iloc[0]
            highlights.append(f'外部因子方面，USDCNH 最新值 {row.get("value")}，日变化 {fmt_num_value(row.get("change"))}。')

    return highlights[:7]

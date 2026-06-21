import argparse
import csv
import html
import json
import os
import sqlite3
import sys
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent


def find_project_root(start):
    for path in (Path(start).resolve(), *Path(start).resolve().parents):
        if (path / 'AI金融数据工作台进化规划.md').exists():
            return path
        if (path / 'apps').exists() and (path / 'services').exists() and (path / 'data').exists():
            return path
    return Path(start).resolve().parent


PROJECT_ROOT = find_project_root(APP_DIR)
DB_PATH = PROJECT_ROOT / 'data' / 'futures.db'
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8765
PAGE_SIZE_OPTIONS = (50, 100, 200, 500)
MAX_EXPORT_ROWS = 20000

TABLE_LABELS = {
    'trade_cal': '交易日历',
    'fut_basic': '合约列表',
    'fut_daily': '期货日线',
    'fut_mapping': '主力映射',
    'fut_holding': '持仓排名',
    'fut_wsr': '仓单日报',
    'fut_settle': '结算参数',
    'ft_limit': '涨跌停板',
    'fut_weekly_monthly': '周月线',
    'fut_weekly_detail': '周度明细',
    'index_daily': '南华期货指数',
    'fx_daily': '汇率日线',
    'sge_daily': '上金所日线',
    'shibor': 'SHIBOR',
    'cn_cpi': 'CPI',
    'cn_ppi': 'PPI',
    'cn_pmi': 'PMI',
    'report_send_history': '报告发送记录',
    'report_recipient_send_history': '收件人发送记录',
}

DATE_COLUMNS = ('trade_date', 'cal_date', 'date', 'month', 'week_date', 'sent_at')
CODE_COLUMNS = ('ts_code', 'symbol', 'mapping_ts_code', 'prd')
STATUS_COLUMNS = ('status', 'is_open', 'exchange', 'report_type')
CORE_TABLES = (
    'fut_daily',
    'fut_mapping',
    'fut_holding',
    'fut_wsr',
    'fut_settle',
    'ft_limit',
    'index_daily',
    'trade_cal',
)


def e(value):
    return html.escape('' if value is None else str(value), quote=True)


def display_date(value):
    value = str(value or '')
    if len(value) == 8 and value.isdigit():
        return f'{value[:4]}-{value[4:6]}-{value[6:]}'
    return value


def display_cell(value):
    text = '' if value is None else str(value)
    if not text:
        return ''
    path = Path(text)
    if path.is_absolute():
        try:
            return path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return path.name
    return text


def parse_qs(query):
    return {k: v[-1] if v else '' for k, v in urllib.parse.parse_qs(query).items()}


def build_url(path, **params):
    cleaned = {k: str(v) for k, v in params.items() if v is not None and str(v) != ''}
    return path + ('?' + urllib.parse.urlencode(cleaned) if cleaned else '')


class Db:
    def __init__(self, path=DB_PATH):
        self.path = Path(path)

    def connect(self):
        conn = sqlite3.connect(f'file:{self.path}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def tables(self):
        with self.connect() as conn:
            rows = conn.execute(
                """
                select name
                from sqlite_master
                where type='table'
                order by name
                """
            ).fetchall()
        return [row['name'] for row in rows if row['name'] != 'sqlite_sequence']

    def columns(self, table):
        self.ensure_table(table)
        with self.connect() as conn:
            rows = conn.execute(f'pragma table_info("{table}")').fetchall()
        return [row['name'] for row in rows]

    def ensure_table(self, table):
        if table not in self.tables():
            raise ValueError(f'未知数据表：{table}')

    def scalar(self, sql, params=()):
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return row[0] if row else None

    def query(self, sql, params=()):
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def table_summary(self):
        rows = []
        for table in self.tables():
            cols = self.columns(table)
            date_col = next((c for c in DATE_COLUMNS if c in cols), None)
            min_date = max_date = ''
            if date_col:
                row = self.query(
                    f'select count(*) as count, min("{date_col}") as min_date, max("{date_col}") as max_date from "{table}"'
                )[0]
                count = row['count']
                min_date = row['min_date']
                max_date = row['max_date']
            else:
                count = self.scalar(f'select count(*) from "{table}"')
            rows.append({
                'table': table,
                'label': TABLE_LABELS.get(table, table),
                'count': count,
                'date_col': date_col or '',
                'min_date': min_date or '',
                'max_date': max_date or '',
            })
        return rows


def page(title, active, body):
    nav = [
        ('/', '总览'),
        ('/table', '数据表'),
        ('/product', '品种视图'),
        ('/send', '发送记录'),
        ('/quality', '数据质量'),
    ]
    nav_html = ''.join(
        f'<a class="nav-item {"active" if href == active else ""}" href="{href}">{label}</a>'
        for href, label in nav
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} - 期货数据库查看系统</title>
<style>
:root {{
  --bg: #f5f7fb;
  --panel: #ffffff;
  --line: #d9e2ec;
  --text: #172033;
  --muted: #667085;
  --brand: #0f7ca8;
  --brand-dark: #075b7d;
  --red: #b42318;
  --green: #067647;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text); font-family: "Microsoft YaHei", Arial, sans-serif; }}
a {{ color: var(--brand-dark); text-decoration: none; }}
.top {{ height: 58px; display: flex; align-items: center; justify-content: space-between; padding: 0 22px; background: #fff; border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 5; }}
.brand {{ font-weight: 800; font-size: 18px; }}
.sub {{ color: var(--muted); font-size: 12px; margin-top: 3px; }}
.layout {{ display: grid; grid-template-columns: 190px minmax(0, 1fr); min-height: calc(100vh - 58px); }}
.side {{ padding: 18px 12px; border-right: 1px solid var(--line); background: #fff; }}
.nav-item {{ display: block; padding: 10px 12px; border-radius: 6px; color: #344054; margin-bottom: 4px; font-weight: 700; }}
.nav-item.active, .nav-item:hover {{ background: #e6f4f8; color: var(--brand-dark); }}
.main {{ padding: 20px 22px 34px; min-width: 0; }}
h1 {{ font-size: 22px; margin: 0 0 14px; }}
h2 {{ font-size: 16px; margin: 20px 0 10px; }}
.grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
.card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
.metric-label {{ color: var(--muted); font-size: 12px; margin-bottom: 8px; }}
.metric-value {{ font-size: 22px; font-weight: 800; }}
.toolbar {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; margin-bottom: 14px; }}
.form-grid {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; align-items: end; }}
label {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 5px; }}
input, select {{ width: 100%; height: 34px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 0 8px; background: #fff; color: var(--text); }}
button, .button {{ display: inline-flex; align-items: center; justify-content: center; height: 34px; border: 1px solid var(--brand); background: var(--brand); color: #fff; border-radius: 6px; padding: 0 12px; font-weight: 700; cursor: pointer; }}
.button.secondary {{ background: #fff; color: var(--brand-dark); }}
.table-wrap {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
th, td {{ padding: 7px 9px; border-bottom: 1px solid #edf1f6; white-space: nowrap; text-align: left; }}
th {{ background: #f0f4f8; color: #344054; position: sticky; top: 0; z-index: 1; }}
tr:nth-child(even) td {{ background: #fbfcfe; }}
.muted {{ color: var(--muted); }}
.ok {{ color: var(--green); font-weight: 800; }}
.bad {{ color: var(--red); font-weight: 800; }}
.pager {{ display: flex; gap: 8px; align-items: center; margin: 12px 0; }}
.notice {{ padding: 10px 12px; background: #fff8eb; border: 1px solid #f7d394; color: #8a4b0f; border-radius: 8px; margin-bottom: 14px; }}
.chart {{ width: 100%; height: 260px; }}
.small {{ font-size: 12px; }}
@media (max-width: 1100px) {{
  .layout {{ grid-template-columns: 1fr; }}
  .side {{ display: flex; gap: 6px; overflow-x: auto; border-right: 0; border-bottom: 1px solid var(--line); }}
  .nav-item {{ white-space: nowrap; margin-bottom: 0; }}
  .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .form-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
}}
</style>
</head>
<body>
<header class="top">
  <div>
    <div class="brand">期货数据库查看系统</div>
    <div class="sub">只读查看 data/futures.db</div>
  </div>
  <div class="sub">{e(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}</div>
</header>
<div class="layout">
  <aside class="side">{nav_html}</aside>
  <main class="main">{body}</main>
</div>
</body>
</html>"""


def table_html(rows, columns=None, empty='暂无数据'):
    if not rows:
        return f'<div class="notice">{e(empty)}</div>'
    if columns is None:
        columns = rows[0].keys()
    head = ''.join(f'<th>{e(col)}</th>' for col in columns)
    body_rows = []
    for row in rows:
        body_rows.append('<tr>' + ''.join(f'<td>{e(display_cell(row[col]))}</td>' for col in columns) + '</tr>')
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'


def option_html(values, selected=''):
    return ''.join(
        f'<option value="{e(value)}" {"selected" if str(value) == str(selected) else ""}>{e(value)}</option>'
        for value in values
    )


def table_select(db, selected=''):
    items = []
    for table in db.tables():
        label = TABLE_LABELS.get(table, table)
        items.append((table, f'{label} ({table})'))
    return ''.join(
        f'<option value="{e(value)}" {"selected" if value == selected else ""}>{e(label)}</option>'
        for value, label in items
    )


def render_home(db):
    summaries = db.table_summary()
    latest_trade = db.scalar('select max(trade_date) from fut_daily') or ''
    latest_report = db.scalar('select max(trade_date) from report_send_history') or ''
    send_count = db.scalar('select count(*) from report_send_history') or 0
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    cards = [
        ('数据库大小', f'{db_size / 1024 / 1024:.1f} MB'),
        ('数据表数量', len(summaries)),
        ('最新日线日期', display_date(latest_trade)),
        ('发送记录数', send_count),
    ]
    card_html = ''.join(
        f'<div class="card"><div class="metric-label">{e(label)}</div><div class="metric-value">{e(value)}</div></div>'
        for label, value in cards
    )
    summary_rows = [
        {
            '数据表': f'{row["label"]} ({row["table"]})',
            '行数': row['count'],
            '日期字段': row['date_col'],
            '最早': display_date(row['min_date']),
            '最新': display_date(row['max_date']),
        }
        for row in summaries
    ]
    recent_send = db.query(
        """
        select trade_date as 日期, report_type as 类型, status as 状态, sent_at as 时间, recipients as 收件人, error as 错误
        from report_send_history
        order by sent_at desc
        limit 8
        """
    ) if 'report_send_history' in db.tables() else []
    body = f"""
    <h1>总览</h1>
    <div class="grid">{card_html}</div>
    <h2>数据表概况</h2>
    {table_html(summary_rows)}
    <h2>最近发送记录</h2>
    {table_html(recent_send)}
    """
    return page('总览', '/', body)


def build_table_where(cols, params):
    where = []
    values = []
    date_col = next((c for c in DATE_COLUMNS if c in cols), None)
    code_col = next((c for c in CODE_COLUMNS if c in cols), None)
    product_col = 'fut_code' if 'fut_code' in cols else 'cont' if 'cont' in cols else None
    status_col = next((c for c in STATUS_COLUMNS if c in cols), None)

    if date_col:
        start = params.get('start', '').strip()
        end = params.get('end', '').strip()
        if start:
            where.append(f'"{date_col}" >= ?')
            values.append(start.replace('-', ''))
        if end:
            where.append(f'"{date_col}" <= ?')
            values.append(end.replace('-', ''))
    keyword = params.get('keyword', '').strip()
    if keyword:
        like_cols = [c for c in (code_col, product_col, 'name', 'broker', 'warehouse', 'recipient', 'recipients') if c and c in cols]
        if like_cols:
            where.append('(' + ' or '.join(f'"{c}" like ?' for c in like_cols) + ')')
            values.extend([f'%{keyword}%'] * len(like_cols))
    status = params.get('status', '').strip()
    if status and status_col:
        where.append(f'"{status_col}" = ?')
        values.append(status)
    return where, values, {'date_col': date_col, 'status_col': status_col}


def render_table(db, params):
    tables = db.tables()
    table = params.get('table') or ('fut_daily' if 'fut_daily' in tables else tables[0])
    db.ensure_table(table)
    cols = db.columns(table)
    where, values, meta = build_table_where(cols, params)
    page_no = max(1, int(params.get('page') or 1))
    page_size = int(params.get('page_size') or 100)
    page_size = page_size if page_size in PAGE_SIZE_OPTIONS else 100
    offset = (page_no - 1) * page_size
    where_sql = ' where ' + ' and '.join(where) if where else ''
    order_col = meta['date_col'] or cols[0]
    total = db.scalar(f'select count(*) from "{table}"{where_sql}', values)
    rows = db.query(
        f'select * from "{table}"{where_sql} order by "{order_col}" desc limit ? offset ?',
        values + [page_size, offset],
    )
    status_options = []
    if meta['status_col']:
        status_rows = db.query(
            f'select distinct "{meta["status_col"]}" as value from "{table}" order by "{meta["status_col"]}" limit 200'
        )
        status_options = [row['value'] for row in status_rows if row['value'] is not None]
    prev_url = build_url('/table', **{**params, 'table': table, 'page': page_no - 1}) if page_no > 1 else ''
    next_url = build_url('/table', **{**params, 'table': table, 'page': page_no + 1}) if offset + page_size < total else ''
    pager = '<div class="pager">'
    if prev_url:
        pager += f'<a class="button secondary" href="{prev_url}">上一页</a>'
    pager += f'<span class="muted">第 {page_no} 页，共 {total} 行</span>'
    if next_url:
        pager += f'<a class="button secondary" href="{next_url}">下一页</a>'
    pager += '</div>'
    status_select = ''
    if status_options:
        status_select = f"""
        <div><label>状态/类型</label><select name="status"><option value="">全部</option>{option_html(status_options, params.get('status', ''))}</select></div>
        """
    export_url = build_url('/export', **{**params, 'table': table})
    body = f"""
    <h1>数据表浏览</h1>
    <form class="toolbar" method="get" action="/table">
      <div class="form-grid">
        <div><label>数据表</label><select name="table">{table_select(db, table)}</select></div>
        <div><label>开始日期</label><input name="start" value="{e(params.get('start', ''))}" placeholder="20260601"></div>
        <div><label>结束日期</label><input name="end" value="{e(params.get('end', ''))}" placeholder="20260615"></div>
        <div><label>关键词</label><input name="keyword" value="{e(params.get('keyword', ''))}" placeholder="CU / 合约 / 经纪商"></div>
        {status_select}
        <div><label>每页行数</label><select name="page_size">{option_html(PAGE_SIZE_OPTIONS, page_size)}</select></div>
        <div><label>&nbsp;</label><button type="submit">查询</button></div>
        <div><label>&nbsp;</label><a class="button secondary" href="{e(export_url)}">导出当前筛选</a></div>
      </div>
    </form>
    {pager}
    {table_html(rows, cols)}
    {pager}
    """
    return page('数据表浏览', '/table', body)


def export_table_csv(db, params):
    table = params.get('table') or 'fut_daily'
    db.ensure_table(table)
    cols = db.columns(table)
    where, values, meta = build_table_where(cols, params)
    where_sql = ' where ' + ' and '.join(where) if where else ''
    order_col = meta['date_col'] or cols[0]
    rows = db.query(
        f'select * from "{table}"{where_sql} order by "{order_col}" desc limit ?',
        values + [MAX_EXPORT_ROWS],
    )
    from io import StringIO
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(cols)
    for row in rows:
        writer.writerow([row[col] for col in cols])
    data = buffer.getvalue()
    filename = f'{table}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    return filename, data.encode('utf-8-sig')


def get_products(db):
    rows = db.query(
        """
        select fut_code, max(name) as name, count(*) as contracts
        from fut_basic
        where fut_code is not null and fut_code != ''
        group by fut_code
        order by fut_code
        """
    )
    return rows


def render_line_svg(rows, value_col, title):
    points = []
    labels = []
    for row in rows:
        try:
            value = float(row[value_col])
            date = row['trade_date']
        except (TypeError, ValueError, KeyError):
            continue
        points.append(value)
        labels.append(date)
    if len(points) < 2:
        return '<div class="notice">数据点不足，无法绘图。</div>'
    width, height = 760, 260
    pad_l, pad_r, pad_t, pad_b = 46, 14, 24, 34
    min_v, max_v = min(points), max(points)
    if min_v == max_v:
        min_v -= 1
        max_v += 1
    span = max_v - min_v
    coords = []
    for idx, value in enumerate(points):
        x = pad_l + idx * (width - pad_l - pad_r) / (len(points) - 1)
        y = pad_t + (max_v - value) * (height - pad_t - pad_b) / span
        coords.append((x, y))
    poly = ' '.join(f'{x:.1f},{y:.1f}' for x, y in coords)
    x0, y0 = coords[0]
    x1, y1 = coords[-1]
    return f"""
    <div class="card">
      <div class="metric-label">{e(title)}</div>
      <svg class="chart" viewBox="0 0 {width} {height}" preserveAspectRatio="none">
        <rect x="0" y="0" width="{width}" height="{height}" fill="#fff"/>
        <line x1="{pad_l}" y1="{height-pad_b}" x2="{width-pad_r}" y2="{height-pad_b}" stroke="#cbd5e1"/>
        <line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{height-pad_b}" stroke="#cbd5e1"/>
        <text x="4" y="{pad_t+4}" font-size="12" fill="#667085">{max_v:.2f}</text>
        <text x="4" y="{height-pad_b}" font-size="12" fill="#667085">{min_v:.2f}</text>
        <polyline points="{poly}" fill="none" stroke="#0f7ca8" stroke-width="2.2"/>
        <circle cx="{x0:.1f}" cy="{y0:.1f}" r="3" fill="#0f7ca8"/>
        <circle cx="{x1:.1f}" cy="{y1:.1f}" r="3" fill="#b42318"/>
        <text x="{pad_l}" y="{height-10}" font-size="12" fill="#667085">{e(display_date(labels[0]))}</text>
        <text x="{width-96}" y="{height-10}" font-size="12" fill="#667085">{e(display_date(labels[-1]))}</text>
      </svg>
    </div>
    """


def render_product(db, params):
    product = (params.get('product') or 'CU').upper().strip()
    end = params.get('end', '').strip().replace('-', '')
    days = int(params.get('days') or 120)
    products = get_products(db)
    product_options = ''.join(
        f'<option value="{e(row["fut_code"])}" {"selected" if row["fut_code"] == product else ""}>{e(row["fut_code"])} - {e(row["name"] or "")}</option>'
        for row in products
    )
    end_clause = 'and d.trade_date <= ?' if end else ''
    values = [f'{product}%', product]
    if end:
        values.append(end)
    daily = db.query(
        f"""
        select d.trade_date, d.ts_code, b.name, d.open, d.high, d.low, d.close, d.vol, d.oi, d.oi_chg
        from fut_daily d
        left join fut_basic b on d.ts_code = b.ts_code
        where (d.ts_code like ? or b.fut_code = ?)
        {end_clause}
        order by d.trade_date desc
        limit ?
        """,
        values + [days],
    )
    daily_asc = list(reversed(daily))
    latest_date = daily[0]['trade_date'] if daily else ''
    mapping = db.query(
        """
        select trade_date, ts_code, mapping_ts_code
        from fut_mapping
        where ts_code = ? or ts_code = ?
        order by trade_date desc
        limit 20
        """,
        [product, product + 'L'],
    )
    wsr = db.query(
        """
        select trade_date, symbol, fut_name, warehouse, vol, vol_chg, unit
        from fut_wsr
        where symbol = ?
        order by trade_date desc
        limit 80
        """,
        [product],
    )
    holding = db.query(
        """
        select trade_date, symbol, broker, vol, vol_chg, long_hld, long_chg, short_hld, short_chg
        from fut_holding
        where symbol like ?
        order by trade_date desc
        limit 80
        """,
        [product + '%'],
    )
    limits = db.query(
        """
        select trade_date, ts_code, name, up_limit, down_limit, m_ratio, cont, exchange
        from ft_limit
        where cont = ? or ts_code like ?
        order by trade_date desc
        limit 50
        """,
        [product, product + '%'],
    )
    body = f"""
    <h1>品种视图</h1>
    <form class="toolbar" method="get" action="/product">
      <div class="form-grid">
        <div><label>品种</label><select name="product">{product_options}</select></div>
        <div><label>截至日期</label><input name="end" value="{e(params.get('end', ''))}" placeholder="默认最新"></div>
        <div><label>日线条数</label><input name="days" value="{e(days)}"></div>
        <div><label>&nbsp;</label><button type="submit">查询</button></div>
      </div>
    </form>
    <div class="grid">
      <div class="card"><div class="metric-label">当前品种</div><div class="metric-value">{e(product)}</div></div>
      <div class="card"><div class="metric-label">最新日线日期</div><div class="metric-value">{e(display_date(latest_date))}</div></div>
      <div class="card"><div class="metric-label">日线记录</div><div class="metric-value">{len(daily)}</div></div>
      <div class="card"><div class="metric-label">仓单记录</div><div class="metric-value">{len(wsr)}</div></div>
    </div>
    <h2>收盘价走势</h2>
    {render_line_svg(daily_asc, 'close', f'{product} 收盘价')}
    <h2>最近日线</h2>
    {table_html(daily[:30])}
    <h2>主力映射</h2>
    {table_html(mapping)}
    <h2>仓单日报</h2>
    {table_html(wsr)}
    <h2>持仓排名</h2>
    {table_html(holding)}
    <h2>涨跌停板</h2>
    {table_html(limits)}
    """
    return page('品种视图', '/product', body)


def render_send(db, params):
    report_type = params.get('report_type', '')
    status = params.get('status', '')
    start = params.get('start', '').replace('-', '')
    end = params.get('end', '').replace('-', '')
    where = []
    values = []
    if report_type:
        where.append('report_type = ?')
        values.append(report_type)
    if status:
        where.append('status = ?')
        values.append(status)
    if start:
        where.append('trade_date >= ?')
        values.append(start)
    if end:
        where.append('trade_date <= ?')
        values.append(end)
    where_sql = ' where ' + ' and '.join(where) if where else ''
    report_rows = db.query(
        f"""
        select trade_date as 日期, report_type as 类型, status as 状态, sent_at as 时间,
               recipients as 收件人, cc as 抄送, error as 错误, pdf_path as PDF
        from report_send_history
        {where_sql}
        order by sent_at desc
        limit 100
        """,
        values,
    )
    recipient_rows = db.query(
        f"""
        select trade_date as 日期, report_type as 类型, recipient as 收件人, status as 状态,
               sent_at as 时间, error as 错误
        from report_recipient_send_history
        {where_sql}
        order by sent_at desc
        limit 100
        """,
        values,
    )
    body = f"""
    <h1>发送记录</h1>
    <form class="toolbar" method="get" action="/send">
      <div class="form-grid">
        <div><label>报告类型</label><select name="report_type"><option value="">全部</option>{option_html(['morning', 'white', 'daily'], report_type)}</select></div>
        <div><label>状态</label><select name="status"><option value="">全部</option>{option_html(['sent', 'dry_run', 'failed', 'partial_failed', 'skipped_duplicate'], status)}</select></div>
        <div><label>开始日期</label><input name="start" value="{e(params.get('start', ''))}"></div>
        <div><label>结束日期</label><input name="end" value="{e(params.get('end', ''))}"></div>
        <div><label>&nbsp;</label><button type="submit">查询</button></div>
      </div>
    </form>
    <h2>报告级记录</h2>
    {table_html(report_rows)}
    <h2>收件人级记录</h2>
    {table_html(recipient_rows)}
    """
    return page('发送记录', '/send', body)


def render_quality(db, params):
    target = (params.get('date') or db.scalar('select max(trade_date) from fut_daily') or '').replace('-', '')
    checks = []
    for table in CORE_TABLES:
        if table not in db.tables():
            continue
        cols = db.columns(table)
        date_col = 'trade_date' if 'trade_date' in cols else 'cal_date' if 'cal_date' in cols else None
        if not date_col:
            continue
        latest = db.scalar(f'select max("{date_col}") from "{table}"')
        count_on_target = db.scalar(f'select count(*) from "{table}" where "{date_col}" = ?', [target])
        ok = bool(count_on_target)
        checks.append({
            '数据表': TABLE_LABELS.get(table, table),
            '表名': table,
            '最新日期': display_date(latest),
            '目标日期': display_date(target),
            '目标日行数': count_on_target,
            '状态': '有数据' if ok else '缺数据',
        })
    latest_rows = db.query(
        """
        select cal_date as 日期, exchange as 交易所, is_open as 是否开市, pretrade_date as 上一交易日
        from trade_cal
        where cal_date >= ?
        order by cal_date, exchange
        limit 40
        """,
        [target],
    )
    body = f"""
    <h1>数据质量</h1>
    <form class="toolbar" method="get" action="/quality">
      <div class="form-grid">
        <div><label>检查日期</label><input name="date" value="{e(target)}"></div>
        <div><label>&nbsp;</label><button type="submit">检查</button></div>
      </div>
    </form>
    <h2>核心表缺口</h2>
    {table_html(checks)}
    <h2>交易日历片段</h2>
    {table_html(latest_rows)}
    """
    return page('数据质量', '/quality', body)


class Handler(BaseHTTPRequestHandler):
    db = Db()

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = parse_qs(parsed.query)
            if parsed.path == '/':
                content = render_home(self.db)
            elif parsed.path == '/table':
                content = render_table(self.db, params)
            elif parsed.path == '/product':
                content = render_product(self.db, params)
            elif parsed.path == '/send':
                content = render_send(self.db, params)
            elif parsed.path == '/quality':
                content = render_quality(self.db, params)
            elif parsed.path == '/favicon.ico':
                self.send_response(204)
                self.end_headers()
                return
            elif parsed.path == '/export':
                filename, data = export_table_csv(self.db, params)
                quoted = urllib.parse.quote(filename)
                self.send_response(200)
                self.send_header('Content-Type', 'text/csv; charset=utf-8')
                self.send_header('Content-Disposition', f"attachment; filename*=UTF-8''{quoted}")
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            else:
                self.send_error(404, 'Not Found')
                return
            data = content.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            self.send_response(500)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            body = page('错误', '', f'<h1>发生错误</h1><div class="notice">{e(exc)}</div>')
            self.wfile.write(body.encode('utf-8'))

    def log_message(self, fmt, *args):
        sys.stdout.write('%s - %s\n' % (self.address_string(), fmt % args))


def main():
    parser = argparse.ArgumentParser(description='期货数据库查看系统')
    parser.add_argument('--host', default=DEFAULT_HOST)
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--db', default=str(DB_PATH))
    args = parser.parse_args()

    Handler.db = Db(Path(args.db))
    if not Handler.db.path.exists():
        raise FileNotFoundError(f'数据库不存在：{Handler.db.path}')

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f'http://{args.host}:{args.port}'
    print(f'期货数据库查看系统已启动：{url}')
    print(f'数据库：{Handler.db.path}')
    print('按 Ctrl+C 停止。')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止。')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

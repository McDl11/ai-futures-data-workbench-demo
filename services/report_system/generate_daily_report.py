import argparse
import logging
from datetime import datetime
from html import escape

from ai_analysis import build_ai_payload, generate_ai_analysis
from config import get_log_dir
from data_loader import FuturesDataLoader
from indicators import (
    clean_daily,
    external_summary,
    focus_highlights,
    holding_summary,
    index_summary,
    limit_events,
    main_series,
    market_overview,
    sector_strength,
    top_table,
    volume_anomaly,
    wsr_summary,
)
from report_generator import (
    dataframe_to_html,
    dataframe_to_markdown,
    write_report,
)
from report_generation_history import record_report_generation
from report_paths import report_file_prefix, report_output_dir


def setup_logging():
    log_file = get_log_dir('报告生成') / f'report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger('futures_report')


def section_html(title, html):
    return f'<h2>{title}</h2>\n{html}\n'


def section_md(title, markdown):
    return f'## {title}\n\n{markdown}\n'


def bullet_list_html(items):
    if not items:
        return '<p class="empty">暂无重点提示</p>'
    return '<ul class="bullets">' + ''.join(f'<li>{escape(str(item))}</li>' for item in items) + '</ul>'


def bullet_list_md(items):
    if not items:
        return '暂无重点提示\n'
    return '\n'.join(f'- {item}' for item in items) + '\n'


def analysis_html(text):
    if not text:
        return ''
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    cleaned = []
    for line in lines:
        if len(line) > 3 and line[0].isdigit() and line[1] in ('.', '、'):
            line = line[2:].strip()
        cleaned.append(line)
    body = ''.join(f'<p class="analysis-item">{escape(line)}</p>' for line in cleaned)
    return section_html('AI市场摘要', f'<div class="analysis">{body}</div>')


def analysis_md(text):
    if not text:
        return ''
    return section_md('AI市场摘要', str(text).strip())


def build_report(trade_date, report_type='daily'):
    loader = FuturesDataLoader()
    basic = loader.get_fut_basic()
    daily = clean_daily(loader.get_daily(trade_date), basic)
    main_df = main_series(daily)

    overview = market_overview(main_df)
    ft_limit = loader.get_ft_limit(trade_date)
    holding = loader.get_holding(trade_date)
    wsr = loader.get_wsr(trade_date)
    index_daily = loader.get_index_daily(trade_date)

    shibor = loader.get_latest_shibor(trade_date)
    fx = loader.get_latest_fx(trade_date)
    sge = loader.get_latest_sge(trade_date)
    macro = loader.get_latest_macro()

    columns_main = ['ts_code', 'display_name', 'close', 'pct_chg', 'vol', 'oi', 'oi_chg']
    headers_main = ['代码', '名称', '收盘', '涨跌幅', '成交量', '持仓量', '持仓变化']

    gainers = top_table(main_df, 'pct_chg', 10, ascending=False, columns=columns_main)
    losers = top_table(main_df, 'pct_chg', 10, ascending=True, columns=columns_main)
    vol_top = top_table(main_df, 'vol', 10, ascending=False, columns=columns_main)
    oi_chg_top = main_df.reindex(main_df['oi_chg'].abs().sort_values(ascending=False).index).head(10)
    oi_chg_top = oi_chg_top[[c for c in columns_main if c in oi_chg_top.columns]]
    vol_anom = volume_anomaly(main_df, loader, trade_date, 10)
    limits = limit_events(main_df, ft_limit)
    wsr_up, wsr_down = wsr_summary(wsr, 10)
    holding_top = holding_summary(holding, 10)
    idx = index_summary(index_daily, 10)
    ext = external_summary(shibor, fx, sge, macro)
    sectors = sector_strength(main_df)
    highlights = focus_highlights(overview, sectors, gainers, losers, vol_anom, oi_chg_top, limits, ext)
    ai_payload = build_ai_payload(
        trade_date=trade_date,
        report_type=report_type,
        overview=overview,
        highlights=highlights,
        sectors=sectors,
        gainers=gainers,
        losers=losers,
        vol_anom=vol_anom,
        oi_chg_top=oi_chg_top,
        limits=limits,
        ext=ext,
    )
    ai_text = generate_ai_analysis(ai_payload)

    html_sections = []
    md_sections = []

    html_sections.append(section_html('今日重点', bullet_list_html(highlights)))
    md_sections.append(section_md('今日重点', bullet_list_md(highlights)))

    if ai_text:
        html_sections.append(analysis_html(ai_text))
        md_sections.append(analysis_md(ai_text))

    sector_cols = ['sector', 'contracts', 'avg_pct_chg', 'up_count', 'down_count', 'up_ratio', 'total_vol', 'total_oi_chg']
    sector_headers = ['板块', '合约数', '平均涨跌幅', '上涨数', '下跌数', '上涨占比', '成交量', '持仓变化']
    html_sections.append(section_html(
        '板块强弱',
        dataframe_to_html(
            sectors,
            sector_cols,
            sector_headers,
            pct_cols={'avg_pct_chg', 'up_ratio'},
            num_cols={'contracts', 'up_count', 'down_count', 'total_vol', 'total_oi_chg'},
        )
    ))
    md_sections.append(section_md(
        '板块强弱',
        dataframe_to_markdown(
            sectors,
            sector_cols,
            sector_headers,
            pct_cols={'avg_pct_chg', 'up_ratio'},
            num_cols={'contracts', 'up_count', 'down_count', 'total_vol', 'total_oi_chg'},
        )
    ))

    html_sections.append(section_html(
        '涨跌幅排行',
        '<div class="grid"><div class="panel">'
        + '<h3>涨幅 Top 10</h3>'
        + dataframe_to_html(gainers, columns_main, headers_main, pct_cols={'pct_chg'}, num_cols={'close', 'vol', 'oi', 'oi_chg'})
        + '</div><div class="panel">'
        + '<h3>跌幅 Top 10</h3>'
        + dataframe_to_html(losers, columns_main, headers_main, pct_cols={'pct_chg'}, num_cols={'close', 'vol', 'oi', 'oi_chg'})
        + '</div></div>'
    ))
    md_sections.append(section_md(
        '涨幅 Top 10',
        dataframe_to_markdown(gainers, columns_main, headers_main, pct_cols={'pct_chg'}, num_cols={'close', 'vol', 'oi', 'oi_chg'})
    ))
    md_sections.append(section_md(
        '跌幅 Top 10',
        dataframe_to_markdown(losers, columns_main, headers_main, pct_cols={'pct_chg'}, num_cols={'close', 'vol', 'oi', 'oi_chg'})
    ))

    html_sections.append(section_html(
        '成交与持仓异动',
        '<div class="grid"><div class="panel">'
        + '<h3>成交量 Top 10</h3>'
        + dataframe_to_html(vol_top, columns_main, headers_main, pct_cols={'pct_chg'}, num_cols={'close', 'vol', 'oi', 'oi_chg'})
        + '</div><div class="panel">'
        + '<h3>持仓变化 Top 10</h3>'
        + dataframe_to_html(oi_chg_top, columns_main, headers_main, pct_cols={'pct_chg'}, num_cols={'close', 'vol', 'oi', 'oi_chg'})
        + '</div></div>'
    ))
    md_sections.append(section_md(
        '成交量 Top 10',
        dataframe_to_markdown(vol_top, columns_main, headers_main, pct_cols={'pct_chg'}, num_cols={'close', 'vol', 'oi', 'oi_chg'})
    ))
    md_sections.append(section_md(
        '持仓变化 Top 10',
        dataframe_to_markdown(oi_chg_top, columns_main, headers_main, pct_cols={'pct_chg'}, num_cols={'close', 'vol', 'oi', 'oi_chg'})
    ))

    vol_cols = ['ts_code', 'display_name', 'close', 'pct_chg', 'vol', 'vol_5d_avg', 'vol_ratio']
    vol_headers = ['代码', '名称', '收盘', '涨跌幅', '成交量', '近5日均量', '放大倍数']
    html_sections.append(section_html(
        '成交量异常放大',
        dataframe_to_html(vol_anom, vol_cols, vol_headers, pct_cols={'pct_chg'}, num_cols={'close', 'vol', 'vol_5d_avg', 'vol_ratio'})
    ))
    md_sections.append(section_md(
        '成交量异常放大',
        dataframe_to_markdown(vol_anom, vol_cols, vol_headers, pct_cols={'pct_chg'}, num_cols={'close', 'vol', 'vol_5d_avg', 'vol_ratio'})
    ))

    limit_cols = ['ts_code', 'display_name', 'close', 'up_limit', 'down_limit', 'dist_up_pct', 'dist_down_pct', 'limit_status']
    limit_headers = ['代码', '名称', '收盘', '涨停价', '跌停价', '距涨停', '距跌停', '状态']
    html_sections.append(section_html(
        '涨跌停与临近事件',
        dataframe_to_html(
            limits,
            limit_cols,
            limit_headers,
            pct_cols={'dist_up_pct', 'dist_down_pct'},
            num_cols={'close', 'up_limit', 'down_limit'},
            empty_text='主力合约暂无涨跌停或 1% 以内临近涨跌停事件',
        )
    ))
    md_sections.append(section_md(
        '涨跌停与临近事件',
        dataframe_to_markdown(
            limits,
            limit_cols,
            limit_headers,
            pct_cols={'dist_up_pct', 'dist_down_pct'},
            num_cols={'close', 'up_limit', 'down_limit'},
            empty_text='主力合约暂无涨跌停或 1% 以内临近涨跌停事件',
        )
    ))

    wsr_cols = ['symbol', 'fut_name', 'vol', 'vol_chg']
    wsr_headers = ['品种', '名称', '仓单量', '仓单变化']
    html_sections.append(section_html(
        '仓单变化',
        '<div class="grid"><div class="panel">'
        + '<h3>仓单增加 Top 10</h3>'
        + dataframe_to_html(wsr_up, wsr_cols, wsr_headers, num_cols={'vol', 'vol_chg'})
        + '</div><div class="panel">'
        + '<h3>仓单减少 Top 10</h3>'
        + dataframe_to_html(wsr_down, wsr_cols, wsr_headers, num_cols={'vol', 'vol_chg'})
        + '</div></div>'
    ))
    md_sections.append(section_md(
        '仓单增加 Top 10',
        dataframe_to_markdown(wsr_up, wsr_cols, wsr_headers, num_cols={'vol', 'vol_chg'})
    ))
    md_sections.append(section_md(
        '仓单减少 Top 10',
        dataframe_to_markdown(wsr_down, wsr_cols, wsr_headers, num_cols={'vol', 'vol_chg'})
    ))

    holding_cols = ['symbol', 'long_hld', 'long_chg', 'short_hld', 'short_chg', 'net_long', 'net_long_chg']
    holding_headers = ['合约', '多头持仓', '多头变化', '空头持仓', '空头变化', '净多', '净多变化']
    html_sections.append(section_html(
        '持仓席位汇总',
        dataframe_to_html(holding_top, holding_cols, holding_headers, num_cols=set(holding_cols) - {'symbol'})
    ))
    md_sections.append(section_md(
        '持仓席位汇总',
        dataframe_to_markdown(holding_top, holding_cols, holding_headers, num_cols=set(holding_cols) - {'symbol'})
    ))

    idx_cols = ['ts_code', 'close', 'pct_chg', 'vol', 'amount']
    idx_headers = ['指数代码', '收盘', '涨跌幅', '成交量', '成交额']
    html_sections.append(section_html(
        '南华期货指数',
        dataframe_to_html(idx, idx_cols, idx_headers, pct_cols={'pct_chg'}, num_cols={'close', 'vol', 'amount'})
    ))
    md_sections.append(section_md(
        '南华期货指数',
        dataframe_to_markdown(idx, idx_cols, idx_headers, pct_cols={'pct_chg'}, num_cols={'close', 'vol', 'amount'})
    ))

    ext_cols = ['name', 'date', 'value', 'change']
    ext_headers = ['指标', '日期', '数值', '变化']
    html_sections.append(section_html(
        '外部因子与宏观背景',
        '<p class="meta">CPI/PPI/PMI 为月度数据，日期显示最新已发布月份。</p>'
        + dataframe_to_html(ext, ext_cols, ext_headers, num_cols={'value', 'change'})
    ))
    md_sections.append(section_md(
        '外部因子与宏观背景',
        'CPI/PPI/PMI 为月度数据，日期显示最新已发布月份。\n\n'
        + dataframe_to_markdown(ext, ext_cols, ext_headers, num_cols={'value', 'change'})
    ))

    return {
        'trade_date': trade_date,
        'report_type': report_type,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'data_status': f'使用 futures.db 最新可得交易日 {trade_date}',
        'overview': overview,
        'sections': '\n'.join(html_sections),
        'markdown_sections': '\n'.join(md_sections),
    }


def parse_args():
    parser = argparse.ArgumentParser(description='Generate futures daily report')
    parser.add_argument('--date', help='YYYYMMDD. If omitted, use today and skip silently when today is not trading day.')
    parser.add_argument('--report-type', choices=['daily', 'white', 'morning'], default='daily')
    parser.add_argument('--force', action='store_true', help='Generate for latest available date even if target date is not trading day.')
    return parser.parse_args()


def main():
    logger = setup_logging()
    args = parse_args()
    loader = FuturesDataLoader()

    today = datetime.now().strftime('%Y%m%d')
    target_date = args.date or today

    if not args.force and not loader.is_trading_day(target_date):
        logger.info(f'{target_date} is not a trading day. Skip report generation silently.')
        return 0

    trade_date = loader.latest_trade_date(target_date)
    if not trade_date:
        logger.warning(f'No futures daily data found up to {target_date}.')
        return 1

    if not args.force and args.date and trade_date != target_date:
        logger.warning(f'No data for {target_date}; latest available is {trade_date}.')
        return 1

    try:
        context = build_report(trade_date, args.report_type)
        html_path, md_path, pdf_path = write_report(
            context,
            report_output_dir(trade_date, args.report_type),
            file_prefix=report_file_prefix(args.report_type, trade_date),
        )
    except Exception as exc:
        record_report_generation(
            trade_date=trade_date,
            report_type=args.report_type,
            generation_status='failed',
            error=str(exc),
        )
        raise
    logger.info(f'HTML report: {html_path}')
    logger.info(f'Markdown report: {md_path}')
    logger.info(f'PDF report: {pdf_path}' if pdf_path.exists() else 'PDF report: not generated')
    record_report_generation(
        trade_date=trade_date,
        report_type=args.report_type,
        generation_status='success',
        html_path=html_path,
        pdf_path=pdf_path,
        md_path=md_path,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

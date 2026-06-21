import json
import logging
import os
import re
import urllib.error
import urllib.request

import pandas as pd
from dotenv import load_dotenv

from config import BASE_DIR


def ai_config():
    load_dotenv(BASE_DIR / '.env')
    return {
        'enabled': os.getenv('AI_ANALYSIS_ENABLED', 'false').lower() in ('1', 'true', 'yes', 'y'),
        'api_key': os.getenv('DEEPSEEK_API_KEY', ''),
        'api_base': os.getenv('DEEPSEEK_API_BASE', 'https://api.deepseek.com').rstrip('/'),
        'model': os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-flash'),
        'timeout': int(os.getenv('AI_ANALYSIS_TIMEOUT_SECONDS', '60')),
        'max_tokens': int(os.getenv('AI_ANALYSIS_MAX_TOKENS', '900')),
    }


def df_records(df, columns=None, limit=8):
    if df is None or df.empty:
        return []
    view = df.copy()
    if columns:
        view = view[[c for c in columns if c in view.columns]]
    view = view.head(limit)
    view = view.where(pd.notna(view), None)
    return view.to_dict('records')


def build_ai_payload(
    trade_date,
    report_type,
    overview,
    highlights,
    sectors,
    gainers,
    losers,
    vol_anom,
    oi_chg_top,
    limits,
    ext,
):
    main_cols = ['ts_code', 'display_name', 'pct_chg', 'vol', 'oi', 'oi_chg']
    return {
        'trade_date': trade_date,
        'report_type': report_type,
        'overview': overview,
        'highlights': highlights,
        'sector_strength': df_records(
            sectors,
            ['sector', 'contracts', 'avg_pct_chg', 'up_count', 'down_count', 'up_ratio', 'total_vol', 'total_oi_chg'],
            8,
        ),
        'top_gainers': df_records(gainers, main_cols, 5),
        'top_losers': df_records(losers, main_cols, 5),
        'volume_anomalies': df_records(
            vol_anom,
            ['ts_code', 'display_name', 'pct_chg', 'vol', 'vol_5d_avg', 'vol_ratio'],
            5,
        ),
        'oi_changes': df_records(oi_chg_top, main_cols, 5),
        'limit_events': df_records(
            limits,
            ['ts_code', 'display_name', 'close', 'dist_up_pct', 'dist_down_pct', 'limit_status'],
            5,
        ),
        'external_factors': df_records(ext, ['name', 'date', 'value', 'change'], 8),
    }


def build_prompt(payload):
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return (
        '请根据下面的期货市场日报摘要，生成可直接放进日报的中文市场解读成稿。\n'
        '要求：\n'
        '1. 只做数据解读、复盘和风险提示，不提供买入、卖出、持仓、止盈止损等交易建议。\n'
        '2. 不预测必然涨跌，不使用“保证、必然、确定、稳赚”等词。\n'
        '3. 输出 4 到 6 条要点，每条 1 到 2 句话。\n'
        '4. 重点覆盖：整体情绪、板块强弱、成交/持仓异动、风险点、后续关注。\n'
        '5. 语言要像投研日报，清楚、克制、可读。\n'
        '6. 不要写“好的”“以下是”“基于您提供的数据”等开场白。\n'
        '7. 不要使用 Markdown 加粗符号、标题符号或表格。\n'
        '8. 每条格式固定为“1. 小标题：正文”，小标题不超过 10 个字。\n\n'
        f'数据摘要：\n{data}'
    )


def polish_ai_text(text):
    if not text:
        return ''
    cleaned = str(text).strip()
    cleaned = cleaned.replace('**', '')
    cleaned = cleaned.replace('###', '').replace('##', '').replace('#', '')
    cleaned = cleaned.replace('：：', '：')
    cleaned = re.sub(r'^\s*(好的|好|以下是|下面是)[，,：:\s].*?(?=\n|\d+[\.、])', '', cleaned, flags=re.S)
    cleaned = re.sub(r'基于您?提供的[^，。,：:\n]*[，。,：:\n]*', '', cleaned)
    cleaned = re.sub(r'中文市场解读[：:\n]*', '', cleaned)

    items = []
    current = ''
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r'^[-*]\s*', '', line)
        line = re.sub(r'^(\d+)[、)]', r'\1.', line)
        if re.match(r'^\d+\.\s*', line):
            if current:
                items.append(current.strip())
            current = line
        else:
            current = f'{current} {line}'.strip() if current else line
    if current:
        items.append(current.strip())

    polished = []
    for idx, item in enumerate(items, 1):
        item = re.sub(r'^\d+\.\s*', f'{idx}. ', item)
        item = re.sub(r'\s+', ' ', item).strip()
        item = item.replace('后续建议关注', '后续关注')
        item = item.replace('建议关注', '后续关注')
        item = item.replace('后续后续关注', '后续关注')
        item = item.replace('可关注', '可跟踪')
        item = item.replace('后续关注要点：关注', '后续关注：')
        item = item.replace('后续关注：关注', '后续关注：')
        polished.append(item)
    return '\n'.join(polished[:6])


def call_deepseek(prompt, cfg):
    url = cfg['api_base'] + '/chat/completions'
    payload = {
        'model': cfg['model'],
        'messages': [
            {
                'role': 'system',
                'content': '你是期货市场日报助理，只能做客观数据解读和风险提示，不提供交易建议。',
            },
            {'role': 'user', 'content': prompt},
        ],
        'stream': False,
        'temperature': 0.2,
        'max_tokens': cfg['max_tokens'],
        'thinking': {'type': 'disabled'},
    }
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {cfg["api_key"]}',
        },
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=cfg['timeout']) as response:
        body = json.loads(response.read().decode('utf-8'))
    return body['choices'][0]['message']['content'].strip()


def generate_ai_analysis(payload):
    logger = logging.getLogger('futures_report')
    cfg = ai_config()
    if not cfg['enabled']:
        return ''
    if not cfg['api_key']:
        logger.warning('AI analysis enabled but DEEPSEEK_API_KEY is empty. Skip AI section.')
        return ''

    try:
        return polish_ai_text(call_deepseek(build_prompt(payload), cfg))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')
        logger.warning(f'DeepSeek API failed: HTTP {exc.code} {detail[:300]}')
    except Exception as exc:
        logger.warning(f'DeepSeek API failed: {exc}')
    return ''

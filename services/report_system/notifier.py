import json
import os
import urllib.error
import urllib.request
from datetime import datetime

from dotenv import load_dotenv

from config import BASE_DIR


PUSHPLUS_API = 'https://www.pushplus.plus/send'


def load_notify_config():
    load_dotenv(BASE_DIR / '.env')
    return {
        'enabled': os.getenv('PUSHPLUS_ENABLED', 'true').lower() in ('1', 'true', 'yes', 'y'),
        'token': os.getenv('PUSHPLUS_TOKEN', '').strip(),
    }


def send_pushplus(title, content, template='markdown', logger=None):
    cfg = load_notify_config()
    if not cfg['enabled']:
        return {'ok': False, 'reason': 'disabled'}
    if not cfg['token']:
        return {'ok': False, 'reason': 'missing_token'}

    payload = {
        'token': cfg['token'],
        'title': title,
        'content': content,
        'template': template,
    }
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        PUSHPLUS_API,
        data=data,
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode('utf-8', errors='ignore')
        result = json.loads(body) if body else {}
        ok = str(result.get('code')) == '200'
        if logger:
            level = logger.info if ok else logger.warning
            level(f'PushPlus notify result: code={result.get("code")}, msg={result.get("msg")}')
        return {'ok': ok, 'response': result}
    except urllib.error.URLError as exc:
        if logger:
            logger.warning(f'PushPlus notify failed: {exc}')
        return {'ok': False, 'reason': str(exc)}
    except Exception as exc:
        if logger:
            logger.warning(f'PushPlus notify failed: {exc}')
        return {'ok': False, 'reason': str(exc)}


def notify_failure(title, detail, logger=None):
    content = (
        f'## {title}\n\n'
        f'- 时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n'
        f'- 系统：期货自动日报\n\n'
        f'```text\n{detail}\n```'
    )
    return send_pushplus(title=f'期货日报告警：{title}', content=content, logger=logger)

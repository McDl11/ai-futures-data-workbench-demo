import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from config import BASE_DIR, DB_PATH, LOGS_DIR, PROJECT_ROOT, REPORTS_DIR, get_log_dir, resolve_backup_dir
from data_loader import FuturesDataLoader
from report_paths import latest_report_bundle, report_type_label
from send_report_email import load_recipients_csv


KEY_TABLES = [
    ('trade_cal', 'cal_date', True),
    ('fut_daily', 'trade_date', True),
    ('fut_mapping', 'trade_date', True),
    ('fut_holding', 'trade_date', True),
    ('fut_wsr', 'trade_date', True),
    ('fut_settle', 'trade_date', True),
    ('ft_limit', 'trade_date', True),
    ('index_daily', 'trade_date', True),
    ('shibor', 'date', False),
    ('fx_daily', 'trade_date', False),
    ('sge_daily', 'trade_date', False),
    ('cn_cpi', 'month', False),
    ('cn_ppi', 'month', False),
    ('cn_pmi', 'month', False),
]


DATA_DOWNLOADER_DIR = PROJECT_ROOT / 'services' / 'data_downloader'
if not DATA_DOWNLOADER_DIR.exists():
    DATA_DOWNLOADER_DIR = PROJECT_ROOT / 'tushare down'


def setup_console():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def today_str():
    return datetime.now().strftime('%Y%m%d')


def human_size(size):
    if size is None:
        return '-'
    size = float(size)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024 or unit == 'GB':
            return f'{size:.1f}{unit}' if unit != 'B' else f'{int(size)}B'
        size /= 1024


def mask_email(value):
    if not value or '@' not in value:
        return '未配置'
    name, domain = value.split('@', 1)
    if len(name) <= 3:
        masked = name[:1] + '*'
    else:
        masked = name[:3] + '***' + name[-1:]
    return f'{masked}@{domain}'


def parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ('1', 'true', 'yes', 'y')


def split_addresses(value):
    if not value:
        return []
    return [p.strip() for p in value.replace(';', ',').split(',') if p.strip()]


class HealthReport:
    def __init__(self):
        self.lines = []
        self.has_failure = False

    def add(self, level, title, detail=''):
        if level == 'FAIL':
            self.has_failure = True
        line = f'[{level}] {title}'
        if detail:
            line += f' - {detail}'
        self.lines.append(line)
        print(line)

    def ok(self, title, detail=''):
        self.add('OK', title, detail)

    def warn(self, title, detail=''):
        self.add('WARN', title, detail)

    def fail(self, title, detail=''):
        self.add('FAIL', title, detail)

    def info(self, title, detail=''):
        self.add('INFO', title, detail)

    def save(self):
        path = get_log_dir('体检') / f'health_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
        content = '\n'.join(self.lines) + '\n'
        path.write_text(content, encoding='utf-8')
        print(f'[INFO] 体检结果已保存 - {path}')
        return path


def table_exists(conn, table):
    row = conn.execute(
        "select 1 from sqlite_master where type='table' and name=?",
        (table,),
    ).fetchone()
    return bool(row)


def count_rows(conn, table):
    return conn.execute(f'select count(*) from {table}').fetchone()[0]


def date_range(conn, table, date_col):
    return conn.execute(f'select min({date_col}), max({date_col}) from {table}').fetchone()


def check_files(report):
    report.info('项目目录', str(BASE_DIR))
    required = [
        BASE_DIR / 'auto_report_once.py',
        BASE_DIR / 'auto_report_daemon.py',
        BASE_DIR / 'maintenance.py',
        BASE_DIR / 'health_check.py',
        BASE_DIR / 'report_generator.py',
        DATA_DOWNLOADER_DIR / 'daily_update.py',
    ]
    for path in required:
        if path.exists():
            report.ok('关键文件存在', path.name)
        else:
            report.fail('关键文件缺失', str(path))


def check_env(report):
    env_path = BASE_DIR / '.env'
    if not env_path.exists():
        report.fail('.env 不存在', str(env_path))
        return

    load_dotenv(env_path, override=True)
    sender = os.getenv('EMAIL_SENDER', '')
    password = os.getenv('EMAIL_PASSWORD', '')
    host = os.getenv('SMTP_HOST', 'smtp.163.com')
    port = os.getenv('SMTP_PORT', '465')
    recipients = split_addresses(os.getenv('REPORT_RECIPIENTS', ''))
    dry_run = parse_bool(os.getenv('REPORT_EMAIL_DRY_RUN', 'true'), True)
    batch_size = os.getenv('REPORT_EMAIL_BATCH_SIZE', '1')
    interval = os.getenv('REPORT_EMAIL_BATCH_INTERVAL_SECONDS', '20')
    pushplus_enabled = parse_bool(os.getenv('PUSHPLUS_ENABLED', 'true'), True)
    pushplus_token = os.getenv('PUSHPLUS_TOKEN', '').strip()
    csv_recipients = load_recipients_csv()

    report.ok('.env 已加载', str(env_path))
    if sender:
        report.ok('发件邮箱', mask_email(sender))
    else:
        report.fail('发件邮箱未配置', 'EMAIL_SENDER 为空')

    if password:
        report.ok('邮箱授权码', '已配置')
    elif dry_run:
        report.warn('邮箱授权码未配置', '当前是 dry-run，不会真实发送')
    else:
        report.fail('邮箱授权码未配置', '真实发送需要 EMAIL_PASSWORD')

    if csv_recipients:
        report.ok('客户名单', f'recipients.csv 启用 {len(csv_recipients)} 个收件人')
    elif recipients:
        report.ok('收件人数量', f'.env 配置 {len(recipients)} 个收件人')
    else:
        report.fail('收件人未配置', 'REPORT_RECIPIENTS 为空')

    report.ok('SMTP 设置', f'{host}:{port}')
    report.warn('邮件仍是 dry-run', 'REPORT_EMAIL_DRY_RUN=true，不会真实发送') if dry_run else report.ok('邮件真实发送', 'REPORT_EMAIL_DRY_RUN=false')
    report.ok('分批发送设置', f'每批 {batch_size} 人，间隔 {interval} 秒')

    ai_enabled = parse_bool(os.getenv('AI_ANALYSIS_ENABLED', 'false'), False)
    ai_key = os.getenv('DEEPSEEK_API_KEY', '')
    if ai_enabled and ai_key:
        report.ok('AI 分析', '已开启，DeepSeek Key 已配置')
    elif ai_enabled:
        report.warn('AI 分析已开启但缺 Key', 'DEEPSEEK_API_KEY 为空，日报会跳过 AI 章节')
    else:
        report.info('AI 分析', '当前关闭')

    if pushplus_enabled and pushplus_token:
        report.ok('PushPlus 告警', '已开启，token 已配置')
    elif pushplus_enabled:
        report.warn('PushPlus 告警已开启但缺 token', 'PUSHPLUS_TOKEN 为空')
    else:
        report.info('PushPlus 告警', '当前关闭')


def check_database(report):
    if not DB_PATH.exists():
        report.fail('数据库不存在', str(DB_PATH))
        return None

    report.ok('数据库存在', f'{DB_PATH} ({human_size(DB_PATH.stat().st_size)})')
    conn = sqlite3.connect(DB_PATH)
    try:
        for table, date_col, required in KEY_TABLES:
            if not table_exists(conn, table):
                message = '关键数据表缺失' if required else '可选数据表缺失'
                (report.fail if required else report.warn)(message, table)
                continue
            count = count_rows(conn, table)
            min_date, max_date = date_range(conn, table, date_col)
            if count <= 0:
                (report.fail if required else report.warn)('数据表为空', table)
            else:
                report.ok('数据表', f'{table}: {count} 行，{min_date}~{max_date}')

        loader = FuturesDataLoader()
        today = today_str()
        is_open = loader.is_trading_day(today)
        latest = loader.latest_trade_date(today)
        previous = loader.previous_trade_date(today) if latest else None
        if is_open:
            report.ok('今天是交易日', today)
            if latest == today:
                report.ok('今日行情已入库', latest)
            else:
                report.warn('今日行情尚未入库', f'当前最新交易日 {latest or "无"}')
        else:
            report.info('今天不是交易日', f'{today}，自动任务应静默跳过')
        if latest:
            report.ok('最新可用交易日', latest)
        if previous:
            report.info('上一交易日', previous)
        return latest
    finally:
        conn.close()


def latest_report_dir():
    if not REPORTS_DIR.exists():
        return None
    dirs = [p for p in REPORTS_DIR.iterdir() if p.is_dir() and p.name.isdigit()]
    return sorted(dirs, key=lambda p: p.name, reverse=True)[0] if dirs else None


def scan_pdf_header_footer(pdf_path):
    data = pdf_path.read_bytes()
    bad_terms = [b'file:///', b'C:/Users/', b'C:\\Users\\']
    return [term.decode('latin1') for term in bad_terms if term in data]


def check_reports(report, latest_trade_date):
    if not REPORTS_DIR.exists():
        report.warn('报告目录不存在', str(REPORTS_DIR))
        return

    report_dir = REPORTS_DIR / latest_trade_date if latest_trade_date else latest_report_dir()
    if not report_dir or not report_dir.exists():
        report.warn('最新交易日还没有报告目录', latest_trade_date or str(REPORTS_DIR))
        return

    trade_date = latest_trade_date or report_dir.name
    bundle = latest_report_bundle(trade_date, reports_dir=REPORTS_DIR)
    if not bundle:
        report.warn('最新交易日还没有报告文件', str(report_dir))
        return

    report.ok('最新报告目录', str(bundle.directory))
    report.ok('报告类型', report_type_label(bundle.report_type))
    files = {
        'PDF': bundle.pdf_path,
        'HTML': bundle.html_path,
        'Markdown': bundle.md_path,
    }
    total_size = 0
    for label, path in files.items():
        if not path.exists():
            report.warn(f'{label} 报告缺失', str(bundle.directory))
            continue
        size = path.stat().st_size
        total_size += size
        report.ok(f'{label} 报告存在', f'{path.name} ({human_size(size)})')
        if label == 'PDF':
            bad_terms = scan_pdf_header_footer(path)
            if bad_terms:
                report.warn('PDF 可能仍有浏览器页眉', ', '.join(bad_terms))
            else:
                report.ok('PDF 页眉页脚检查', '未发现本地路径残留')

    max_size = int(os.getenv('REPORT_MAX_ATTACHMENT_SIZE', str(20 * 1024 * 1024)))
    if total_size > max_size:
        report.warn('附件总大小超过配置上限', f'{human_size(total_size)} > {human_size(max_size)}')
    else:
        report.ok('附件总大小', f'{human_size(total_size)} / 上限 {human_size(max_size)}')


def check_backups(report):
    backup_dir = resolve_backup_dir()
    if not backup_dir.exists():
        report.warn('数据库备份目录不存在', str(backup_dir))
        return
    backups = sorted(backup_dir.glob('futures_*.zip'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        report.warn('暂无数据库备份', str(backup_dir))
        return
    newest = backups[0]
    age = datetime.now() - datetime.fromtimestamp(newest.stat().st_mtime)
    detail = f'{newest.name} ({human_size(newest.stat().st_size)})'
    if age > timedelta(days=2):
        report.warn('数据库备份超过 2 天未更新', detail)
    else:
        report.ok('最新数据库备份', detail)
    report.info('数据库备份数量', f'{len(backups)} 个，目录 {backup_dir}')


def check_send_history(report):
    if not DB_PATH.exists():
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        if not table_exists(conn, 'report_send_history'):
            report.warn('发送记录表不存在', 'report_send_history')
            return
        rows = conn.execute(
            """
            select trade_date, report_type, status, sent_at, coalesce(error, '')
            from report_send_history
            order by id desc
            limit 5
            """
        ).fetchall()
        if not rows:
            report.warn('暂无发送记录', 'report_send_history 为空')
            return
        latest = rows[0]
        status = latest[2]
        detail = f'{latest[0]} {latest[1]} {status} @ {latest[3]}'
        if status in ('sent', 'dry_run', 'skipped_duplicate'):
            report.ok('最近一次发送记录', detail)
        else:
            report.warn('最近一次发送记录异常', detail)
        failed = [r for r in rows if r[2] in ('failed', 'partial_failed')]
        if failed:
            report.warn('最近 5 次有失败发送', f'{len(failed)} 次')
        else:
            report.ok('最近 5 次发送记录', '未发现 failed/partial_failed')
    finally:
        conn.close()


def check_recent_logs(report):
    if not LOGS_DIR.exists():
        report.warn('日志目录不存在', str(LOGS_DIR))
        return
    logs = sorted(LOGS_DIR.rglob('*.log'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        report.warn('暂无运行日志', str(LOGS_DIR))
        return
    newest = logs[0]
    text = newest.read_text(encoding='utf-8', errors='ignore')
    try:
        display_name = str(newest.relative_to(LOGS_DIR))
    except ValueError:
        display_name = str(newest)
    report.ok('最新日志文件', display_name)
    danger_words = ['ERROR', 'Traceback', 'failed with code']
    hits = [word for word in danger_words if word in text]
    if hits:
        report.warn('最新日志存在异常关键词', ', '.join(hits))
    else:
        report.ok('最新日志快速检查', '未发现 ERROR/Traceback')


def daemon_process_ids(rows):
    daemon_rows = []
    for item in rows:
        cmd = item.get('CommandLine') or ''
        if 'auto_report_daemon.py' in cmd:
            daemon_rows.append(item)

    real_python_rows = [
        item for item in daemon_rows
        if str(item.get('Name') or '').lower() != 'py.exe'
    ]
    selected = real_python_rows or daemon_rows
    parent_ids = {str(item.get('ParentProcessId')) for item in selected}
    child_rows = [item for item in selected if str(item.get('ProcessId')) not in parent_ids]
    selected = child_rows or selected
    return [str(item.get('ProcessId')) for item in selected]


def load_process_rows(raw_json):
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        data = json.loads(raw_json.replace('\\.', '\\\\.'))
    if isinstance(data, dict):
        return [data]
    return data


def check_daemon(report):
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match 'python|py|cmd' } | "
        "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', command],
            text=True,
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            report.warn('24小时守护进程检查失败', result.stderr.strip()[:200])
            return
        data = load_process_rows(result.stdout)
        matches = daemon_process_ids(data)
        if matches:
            report.ok('24小时守护进程正在运行', 'PID ' + ', '.join(matches))
        else:
            report.warn('24小时守护进程未发现', '需要运行 python auto_report_daemon.py --send，或由任务计划程序拉起')
    except Exception as exc:
        report.warn('24小时守护进程检查失败', str(exc))


def main():
    setup_console()
    report = HealthReport()
    report.info('期货日报系统体检开始', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    check_files(report)
    check_env(report)
    latest_trade_date = check_database(report)
    check_reports(report, latest_trade_date)
    check_backups(report)
    check_send_history(report)
    check_recent_logs(report)
    check_daemon(report)
    report.info('体检完成', '存在 FAIL 需要优先处理' if report.has_failure else '未发现阻断性问题')
    report.save()
    return 1 if report.has_failure else 0


if __name__ == '__main__':
    raise SystemExit(main())

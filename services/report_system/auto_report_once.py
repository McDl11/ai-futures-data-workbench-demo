import argparse
import logging
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from config import DB_PATH, DEFAULT_EXCHANGES, PROJECT_ROOT, get_log_dir
from data_loader import FuturesDataLoader
from generate_daily_report import build_report
from notifier import notify_failure
from report_generation_history import record_report_generation
from report_paths import report_file_prefix, report_output_dir
from report_generator import write_report
from send_report_email import send_report, split_addresses
from task_run_history import record_task_run


TUSHARE_DIR = PROJECT_ROOT / 'services' / 'data_downloader'
if not TUSHARE_DIR.exists():
    TUSHARE_DIR = PROJECT_ROOT / 'tushare down'
DAILY_UPDATE = TUSHARE_DIR / 'daily_update.py'


def setup_logging():
    log_file = get_log_dir('自动任务') / f'auto_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger('auto_report')


def today_str():
    return datetime.now().strftime('%Y%m%d')


def previous_calendar_day():
    return (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')


def refresh_trade_calendar(logger, start_date, end_date):
    env_path = TUSHARE_DIR / '.env'
    try:
        from dotenv import load_dotenv
        import tushare as ts
    except Exception as exc:
        logger.warning(f'Skip trade calendar refresh: {exc}')
        return 0

    load_dotenv(env_path)
    token = os.getenv('TUSHARE_TOKEN')
    if not token:
        logger.warning(f'Skip trade calendar refresh: missing TUSHARE_TOKEN in {env_path}')
        return 0

    pro = ts.pro_api(token)
    http_url = os.getenv('TUSHARE_HTTP_URL')
    if http_url:
        pro._DataApi__token = token
        pro._DataApi__http_url = http_url

    rows = []
    for exchange in DEFAULT_EXCHANGES:
        df = pro.trade_cal(exchange=exchange, start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            for row in df.to_dict('records'):
                rows.append(
                    (
                        str(row.get('exchange', exchange)),
                        str(row.get('cal_date', '')),
                        str(row.get('is_open', '')),
                        str(row.get('pretrade_date', '')),
                    )
                )
        time.sleep(0.35)

    if not rows:
        logger.warning(f'Trade calendar refresh returned no rows: {start_date}~{end_date}')
        return 0

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            create table if not exists trade_cal (
                exchange text,
                cal_date text,
                is_open text,
                pretrade_date text,
                unique (exchange, cal_date)
            )
            """
        )
        conn.executemany(
            """
            insert or replace into trade_cal (exchange, cal_date, is_open, pretrade_date)
            values (?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()

    logger.info(f'Trade calendar refreshed: {start_date}~{end_date}, rows={len(rows)}')
    return len(rows)


def run_daily_update(logger, end_date=None):
    if not DAILY_UPDATE.exists():
        raise FileNotFoundError(f'daily_update.py not found: {DAILY_UPDATE}')
    cmd = [sys.executable, str(DAILY_UPDATE), '--now']
    if end_date:
        cmd.extend(['--end-date', end_date])
    logger.info(f'Run data update: {" ".join(cmd)}')
    result = subprocess.run(
        cmd,
        cwd=str(TUSHARE_DIR),
        text=True,
        capture_output=True,
        timeout=60 * 60,
    )
    if result.stdout:
        logger.info(result.stdout.strip())
    if result.stderr:
        logger.warning(result.stderr.strip())
    if result.returncode != 0:
        raise RuntimeError(f'daily_update.py failed with code {result.returncode}')


def resolve_target_date(loader, report_type, explicit_date=None):
    if explicit_date:
        return explicit_date
    if report_type in ('morning', 'white'):
        return today_str()
    return loader.latest_trade_date(today_str()) or previous_calendar_day()


def wait_for_data(
    loader,
    target_date,
    require_exact_date,
    retries,
    interval_minutes,
    logger,
    update_between_retries=False,
):
    for attempt in range(1, retries + 1):
        latest = loader.latest_trade_date(target_date)
        logger.info(f'Data check {attempt}/{retries}: target={target_date}, latest={latest}')
        if latest and (not require_exact_date or latest == target_date):
            return latest
        if attempt < retries:
            sleep_seconds = interval_minutes * 60
            logger.info(f'Wait {interval_minutes} minutes before retry.')
            time.sleep(sleep_seconds)
            if update_between_retries:
                run_daily_update(logger, end_date=target_date)
    return None


def run_once(args):
    logger = logging.getLogger('auto_report')
    scheduled_date = args.date or today_str()
    if not args.no_update:
        today = today_str()
        refresh_trade_calendar(
            logger=logger,
            start_date=(datetime.now() - timedelta(days=7)).strftime('%Y%m%d'),
            end_date=(datetime.now() + timedelta(days=14)).strftime('%Y%m%d'),
        )

    loader = FuturesDataLoader()

    if not args.force and not loader.is_trading_day(scheduled_date):
        logger.info(f'{scheduled_date} is not a trading day. Skip silently.')
        return {'status': 'skipped_non_trading_day'}

    target_date = resolve_target_date(loader, args.report_type, args.date)

    if not args.force and args.date and not loader.is_trading_day(target_date):
        logger.info(f'{target_date} is not a trading day. Skip silently.')
        return {'status': 'skipped_non_trading_day'}

    if not args.no_update:
        run_daily_update(logger, end_date=target_date)

    # 早报与白盘都以当前交易日为数据日：有 target_date 数据才发送。
    require_exact_date = args.report_type in ('morning', 'white') and not args.allow_latest
    latest_trade_date = wait_for_data(
        loader=loader,
        target_date=target_date,
        require_exact_date=require_exact_date,
        retries=args.retries,
        interval_minutes=args.retry_interval,
        logger=logger,
        update_between_retries=not args.no_update,
    )
    if not latest_trade_date:
        logger.info('Data not ready. Skip report/email.')
        return {'status': 'skipped_data_not_ready'}

    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    context = build_report(latest_trade_date, args.report_type)
    context['scheduled_date'] = scheduled_date
    context['generated_at'] = generated_at
    html_path, md_path, pdf_path = write_report(
        context,
        report_output_dir(latest_trade_date, args.report_type),
        file_prefix=report_file_prefix(args.report_type, latest_trade_date),
    )
    logger.info(f'HTML report: {html_path}')
    logger.info(f'Markdown report: {md_path}')
    logger.info(f'PDF report: {pdf_path}' if pdf_path.exists() else 'PDF report: not generated')
    record_report_generation(
        trade_date=latest_trade_date,
        report_type=args.report_type,
        generation_status='success',
        html_path=html_path,
        pdf_path=pdf_path,
        md_path=md_path,
    )

    recipients = split_addresses(args.to) if args.to else None
    cc = split_addresses(args.cc) if args.cc else None
    email_result = send_report(
        trade_date=latest_trade_date,
        recipients=recipients,
        cc=cc,
        dry_run=not args.send,
        force=True,
        report_type=args.report_type,
        resend=args.resend,
        html_path=html_path,
        md_path=md_path,
        pdf_path=pdf_path,
        scheduled_date=scheduled_date,
        generated_at=generated_at,
    )
    logger.info(f'Email result: {email_result["status"]}')
    return {
        'status': email_result['status'],
        'trade_date': latest_trade_date,
        'html': str(html_path),
        'markdown': str(md_path),
        'pdf': str(pdf_path) if pdf_path.exists() else '',
    }


def parse_args():
    parser = argparse.ArgumentParser(description='One-shot futures report automation')
    parser.add_argument('--report-type', choices=['morning', 'white', 'daily'], default='daily')
    parser.add_argument('--date', help='YYYYMMDD. Defaults: white=today, morning/daily=latest available.')
    parser.add_argument('--to', default='', help='Recipients separated by comma or semicolon')
    parser.add_argument('--cc', default='', help='CC recipients separated by comma or semicolon')
    parser.add_argument('--send', action='store_true', help='Actually send email. Default is dry-run.')
    parser.add_argument('--force', action='store_true', help='Run even if target date is not a trading day.')
    parser.add_argument('--no-update', action='store_true', help='Skip daily_update.py and use existing database.')
    parser.add_argument('--allow-latest', action='store_true', help='For white report, allow latest available date if target date data is not ready.')
    parser.add_argument('--retries', type=int, default=1, help='Data readiness retries. Use 6 for scheduled white report.')
    parser.add_argument('--retry-interval', type=int, default=10, help='Minutes between retries.')
    parser.add_argument('--resend', action='store_true', help='Send again even if this report was already sent.')
    return parser.parse_args()


def main():
    setup_logging()
    args = parse_args()
    started_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        result = run_once(args)
    except Exception as exc:
        logging.getLogger('auto_report').exception(f'Auto report failed: {exc}')
        notify_failure('自动日报运行失败', str(exc), logger=logging.getLogger('auto_report'))
        record_task_run(
            task_type='report_generate',
            task_name='自动报告',
            status='failed',
            target_date=args.date or today_str(),
            detail=args.report_type,
            error=str(exc),
            started_at=started_at,
        )
        record_report_generation(
            trade_date=args.date or today_str(),
            report_type=args.report_type,
            generation_status='failed',
            error=str(exc),
        )
        raise
    logging.getLogger('auto_report').info(f'Result: {result["status"]}')
    status = 'success' if result['status'] in (
        'sent',
        'dry_run',
        'skipped_duplicate',
        'partial_failed',
    ) else 'skipped'
    record_task_run(
        task_type='report_generate',
        task_name='自动报告',
        status=status,
        target_date=result.get('trade_date') or args.date or today_str(),
        detail=args.report_type,
        output=str(result),
        started_at=started_at,
    )
    return 0 if result['status'] in (
        'sent',
        'dry_run',
        'skipped_duplicate',
        'partial_failed',
        'skipped_non_trading_day',
        'skipped_data_not_ready',
    ) else 1


if __name__ == '__main__':
    raise SystemExit(main())

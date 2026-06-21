import argparse
import csv
import hashlib
import logging
import os
import sqlite3
import smtplib
import time
from contextlib import closing
from datetime import datetime
from email.message import EmailMessage
from html import escape
from pathlib import Path

from dotenv import load_dotenv

from config import BASE_DIR, DB_PATH, get_log_dir
from data_loader import FuturesDataLoader
from notifier import notify_failure
from report_paths import report_paths, report_type_label
from task_run_history import record_task_run


SEND_STATUS_SENT = 'sent'
SEND_STATUS_FAILED = 'failed'
SEND_STATUS_DRY_RUN = 'dry_run'
SEND_STATUS_SKIPPED_DUPLICATE = 'skipped_duplicate'
SEND_STATUS_PARTIAL_FAILED = 'partial_failed'


def setup_logging():
    log_file = get_log_dir('邮件发送') / f'email_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger('report_email')


def load_email_env():
    load_dotenv(BASE_DIR / '.env', override=True)


def split_addresses(value):
    if not value:
        return []
    parts = value.replace(';', ',').split(',')
    return [p.strip() for p in parts if p.strip()]


def normalize_addresses(addresses):
    return sorted({addr.strip().lower() for addr in addresses if addr and addr.strip()})


def load_recipients_csv(path=None):
    path = path or (BASE_DIR / 'recipients.csv')
    if not path.exists():
        return []
    recipients = []
    last_error = None
    for encoding in ('utf-8-sig', 'utf-8', 'gbk', 'gb18030'):
        try:
            with path.open('r', encoding=encoding, newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    email = (row.get('email') or '').strip()
                    enabled = (row.get('enabled') or 'true').strip().lower()
                    if email and enabled in ('1', 'true', 'yes', 'y', '是'):
                        recipients.append(email)
            return normalize_addresses(recipients)
        except UnicodeDecodeError as exc:
            last_error = exc
            recipients = []
            continue
    if last_error:
        raise last_error
    return normalize_addresses(recipients)


def recipients_key(recipients, cc):
    joined = '|'.join(normalize_addresses((recipients or []) + (cc or [])))
    return hashlib.sha256(joined.encode('utf-8')).hexdigest()


def init_send_history():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            create table if not exists report_send_history (
                id integer primary key autoincrement,
                trade_date text not null,
                report_type text not null,
                recipients_key text not null,
                recipients text not null,
                cc text not null,
                status text not null,
                sent_at text not null,
                error text,
                html_path text,
                md_path text,
                pdf_path text
            )
            """
        )
        try:
            conn.execute('alter table report_send_history add column pdf_path text')
        except sqlite3.OperationalError:
            pass
        conn.execute('drop index if exists idx_report_send_history_success')
        conn.execute(
            """
            create index if not exists idx_report_send_history_success_lookup
            on report_send_history (trade_date, report_type, recipients_key, status, sent_at)
            """
        )
        conn.execute(
            """
            create table if not exists report_recipient_send_history (
                id integer primary key autoincrement,
                trade_date text not null,
                report_type text not null,
                recipient text not null,
                cc text not null,
                status text not null,
                sent_at text not null,
                error text,
                html_path text,
                md_path text,
                pdf_path text
            )
            """
        )
        try:
            conn.execute('alter table report_recipient_send_history add column pdf_path text')
        except sqlite3.OperationalError:
            pass
        conn.execute('drop index if exists idx_report_recipient_send_success')
        conn.execute(
            """
            create index if not exists idx_report_recipient_send_lookup
            on report_recipient_send_history (trade_date, report_type, recipient, status, sent_at)
            """
        )
        conn.commit()


def has_successful_send(trade_date, report_type, key):
    init_send_history()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            """
            select sent_at
            from report_send_history
            where trade_date = ?
              and report_type = ?
              and recipients_key = ?
              and status = ?
            order by sent_at desc
            limit 1
            """,
            (trade_date, report_type, key, SEND_STATUS_SENT),
        ).fetchone()
    return row[0] if row else None


def has_successful_recipient_send(trade_date, report_type, recipient):
    init_send_history()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            """
            select sent_at
            from report_recipient_send_history
            where trade_date = ?
              and report_type = ?
              and recipient = ?
              and status = ?
            order by sent_at desc
            limit 1
            """,
            (trade_date, report_type, recipient.lower(), SEND_STATUS_SENT),
        ).fetchone()
    return row[0] if row else None


def record_send_history(
    trade_date,
    report_type,
    recipients,
    cc,
    status,
    html_path=None,
    md_path=None,
    pdf_path=None,
    error='',
):
    init_send_history()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            insert into report_send_history (
                trade_date, report_type, recipients_key, recipients, cc,
                status, sent_at, error, html_path, md_path, pdf_path
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_date,
                report_type,
                recipients_key(recipients, cc),
                ','.join(normalize_addresses(recipients or [])),
                ','.join(normalize_addresses(cc or [])),
                status,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                error or '',
                str(html_path) if html_path else '',
                str(md_path) if md_path else '',
                str(pdf_path) if pdf_path else '',
            ),
        )
        conn.commit()


def record_recipient_send_history(
    trade_date,
    report_type,
    recipient,
    cc,
    status,
    html_path=None,
    md_path=None,
    pdf_path=None,
    error='',
):
    init_send_history()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            insert into report_recipient_send_history (
                trade_date, report_type, recipient, cc, status,
                sent_at, error, html_path, md_path, pdf_path
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_date,
                report_type,
                recipient.strip().lower(),
                ','.join(normalize_addresses(cc or [])),
                status,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                error or '',
                str(html_path) if html_path else '',
                str(md_path) if md_path else '',
                str(pdf_path) if pdf_path else '',
            ),
        )
        conn.commit()


def email_config():
    load_email_env()
    csv_recipients = load_recipients_csv()
    return {
        'sender': os.getenv('EMAIL_SENDER', ''),
        'password': os.getenv('EMAIL_PASSWORD', ''),
        'host': os.getenv('SMTP_HOST', 'smtp.163.com'),
        'port': int(os.getenv('SMTP_PORT', '465')),
        'use_ssl': os.getenv('SMTP_USE_SSL', 'true').lower() in ('1', 'true', 'yes', 'y'),
        'recipients': csv_recipients or split_addresses(os.getenv('REPORT_RECIPIENTS', '')),
        'cc': split_addresses(os.getenv('REPORT_CC', '')),
        'dry_run': os.getenv('REPORT_EMAIL_DRY_RUN', 'true').lower() in ('1', 'true', 'yes', 'y'),
        'max_attachment_size': int(os.getenv('REPORT_MAX_ATTACHMENT_SIZE', str(20 * 1024 * 1024))),
        'batch_size': int(os.getenv('REPORT_EMAIL_BATCH_SIZE', '1')),
        'batch_interval_seconds': int(os.getenv('REPORT_EMAIL_BATCH_INTERVAL_SECONDS', '20')),
    }


def existing_attachments(*paths):
    return [path for path in paths if path and path.exists()]


def parse_attachment_types(value=None):
    if not value:
        return ['pdf', 'html', 'md']
    aliases = {'markdown': 'md'}
    allowed = {'pdf', 'html', 'md'}
    parsed = []
    for part in str(value).replace(';', ',').split(','):
        item = aliases.get(part.strip().lower(), part.strip().lower())
        if item in allowed and item not in parsed:
            parsed.append(item)
    return parsed or ['pdf', 'html', 'md']


def selected_attachment_paths(pdf_path, html_path, md_path, attachment_types=None):
    selected = parse_attachment_types(','.join(attachment_types) if isinstance(attachment_types, list) else attachment_types)
    mapping = {
        'pdf': pdf_path,
        'html': html_path,
        'md': md_path,
    }
    return [mapping[item] for item in selected if mapping.get(item)]


def existing_selected_attachments(pdf_path, html_path, md_path, attachment_types=None):
    return existing_attachments(*selected_attachment_paths(pdf_path, html_path, md_path, attachment_types))


def scan_pdf_header_footer(pdf_path):
    data = pdf_path.read_bytes()
    bad_terms = [b'file:///', b'C:/Users/', b'C:\\Users\\']
    return [term.decode('latin1') for term in bad_terms if term in data]


def extract_markdown_section(md_path, title, max_lines=5):
    if not md_path.exists():
        return []
    lines = md_path.read_text(encoding='utf-8', errors='ignore').splitlines()
    header = f'## {title}'
    in_section = False
    items = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('## ') and stripped != header and in_section:
            break
        if stripped == header:
            in_section = True
            continue
        if in_section and stripped.startswith('- '):
            items.append(stripped)
            if len(items) >= max_lines:
                break
    return items


def display_trade_date(trade_date):
    trade_date = str(trade_date)
    if len(trade_date) == 8 and trade_date.isdigit():
        return f'{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}'
    return trade_date


def clean_markdown_item(value):
    value = str(value).strip()
    return value[2:].strip() if value.startswith('- ') else value


def attachment_mime(path):
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        return 'application', 'pdf'
    if suffix in ('.html', '.htm'):
        return 'text', 'html'
    if suffix == '.md':
        return 'text', 'markdown'
    return 'application', 'octet-stream'


def build_message(
    cfg,
    trade_date,
    html_path,
    md_path,
    pdf_path,
    recipients,
    cc,
    report_type='daily',
    scheduled_date=None,
    generated_at=None,
    attachment_types=None,
):
    date_text = display_trade_date(trade_date)
    report_label = report_type_label(report_type)
    scheduled_text = display_trade_date(scheduled_date) if scheduled_date else ''
    subject = f'期货{report_label} | 数据日 {date_text}'
    highlights = extract_markdown_section(md_path, '今日重点', 5)
    if not highlights:
        highlights = extract_markdown_section(md_path, '今日重点关注', 5)
    clean_highlights = [clean_markdown_item(item) for item in highlights]
    attachments = existing_selected_attachments(pdf_path, html_path, md_path, attachment_types)
    attachment_text = '\n'.join(f'- {path.name}' for path in attachments) or '- 暂无附件'

    if clean_highlights:
        highlight_text = '今日重点：\n' + '\n'.join(f'{idx}. {item}' for idx, item in enumerate(clean_highlights, 1)) + '\n\n'
        highlight_html = ''.join(f'<li>{escape(item)}</li>' for item in clean_highlights)
    else:
        highlight_text = '今日重点：暂无重点提示。\n\n'
        highlight_html = '<li>暂无重点提示。</li>'

    trigger_line = f'触发日期：{scheduled_text}\n' if scheduled_text else ''
    generated_line = f'生成时间：{generated_at}\n\n' if generated_at else '\n'
    body = (
        f'您好：\n\n'
        f'报告类型：期货市场{report_label}\n'
        f'数据日期：{date_text}\n'
        f'{trigger_line}'
        f'{generated_line}'
        f'{highlight_text}'
        f'附件清单：\n{attachment_text}\n\n'
        f'说明：本报告仅用于数据整理和复盘辅助，不构成任何投资建议。\n'
    )
    html_meta = f'数据日 {escape(date_text)}'
    if scheduled_text:
        html_meta += f' | 触发日 {escape(scheduled_text)}'
    html_body = (
        '<!doctype html><html><body style="margin:0;padding:0;background:#f6f8fb;'
        'font-family:Microsoft YaHei,Arial,sans-serif;color:#1f2933;">'
        '<div style="max-width:680px;margin:0 auto;padding:24px;">'
        '<div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:22px;">'
        f'<div style="font-size:13px;color:#64748b;margin-bottom:8px;">{html_meta}</div>'
        f'<h1 style="font-size:22px;line-height:1.35;margin:0 0 12px;color:#111827;">期货市场{escape(report_label)}</h1>'
        '<p style="font-size:13px;line-height:1.7;margin:0 0 12px;color:#667085;">统计口径：以主力合约/连续合约为主要观察对象，不等同于交易所全部挂牌合约统计。</p>'
        '<h2 style="font-size:16px;margin:18px 0 10px;color:#111827;">今日重点</h2>'
        f'<ol style="margin:0 0 18px 20px;padding:0;line-height:1.8;font-size:14px;">{highlight_html}</ol>'
        '<p style="font-size:13px;line-height:1.7;color:#64748b;margin:18px 0 0;">'
        '本报告仅用于数据整理和复盘辅助，不构成任何投资建议。'
        '</p>'
        '</div>'
        '</div>'
        '</body></html>'
    )

    msg = EmailMessage()
    msg['From'] = cfg['sender']
    msg['To'] = ', '.join(recipients)
    if cc:
        msg['Cc'] = ', '.join(cc)
    msg['Subject'] = subject
    msg.set_content(body)
    msg.add_alternative(html_body, subtype='html')

    for path in attachments:
        data = path.read_bytes()
        maintype, subtype = attachment_mime(path)
        msg.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )
    return msg


def check_attachments(trade_date, pdf_path, html_path, md_path, max_size, attachment_types=None):
    required = selected_attachment_paths(pdf_path, html_path, md_path, attachment_types)
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError('Missing report files: ' + ', '.join(missing))
    if any(trade_date not in path.name for path in required):
        raise ValueError(f'Report filename date mismatch: expected {trade_date}')
    if pdf_path in required and html_path.exists() and md_path.exists():
        latest_source_mtime = max(html_path.stat().st_mtime, md_path.stat().st_mtime)
    else:
        latest_source_mtime = 0
    if pdf_path in required and pdf_path.stat().st_mtime + 2 < latest_source_mtime:
        raise ValueError('PDF is older than HTML/Markdown report. Close opened PDF and regenerate report.')
    if pdf_path in required:
        bad_terms = scan_pdf_header_footer(pdf_path)
        if bad_terms:
            raise ValueError('PDF contains browser header/footer residue: ' + ', '.join(bad_terms))
    total_size = sum(p.stat().st_size for p in required)
    if total_size > max_size:
        raise ValueError(f'Attachments too large: {total_size} > {max_size}')
    return total_size


def send_message(cfg, msg, all_recipients, logger, retries=3):
    for attempt in range(1, retries + 1):
        try:
            if cfg['use_ssl']:
                server = smtplib.SMTP_SSL(cfg['host'], cfg['port'], timeout=30)
            else:
                server = smtplib.SMTP(cfg['host'], cfg['port'], timeout=30)
                server.starttls()
            try:
                server.login(cfg['sender'], cfg['password'])
                server.send_message(msg, from_addr=cfg['sender'], to_addrs=all_recipients)
            finally:
                server.quit()
            logger.info(f'Email sent to {len(all_recipients)} recipients.')
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error('SMTP authentication failed. Check EMAIL_SENDER and EMAIL_PASSWORD.')
            return False
        except Exception as exc:
            logger.warning(f'Send failed attempt {attempt}/{retries}: {exc}')
            if attempt < retries:
                time.sleep(5 * attempt)
    return False


def send_report_batches(
    cfg,
    trade_date,
    report_type,
    recipients,
    cc,
    html_path,
    md_path,
    pdf_path,
    resend,
    logger,
    scheduled_date=None,
    generated_at=None,
    attachment_types=None,
):
    results = []
    sent_count = 0
    failed_count = 0
    skipped_count = 0
    batch_size = max(1, cfg['batch_size'])
    interval = max(0, cfg['batch_interval_seconds'])

    for start in range(0, len(recipients), batch_size):
        batch = recipients[start:start + batch_size]
        pending = []
        for recipient in batch:
            previous_sent_at = None if resend else has_successful_recipient_send(
                trade_date,
                report_type,
                recipient,
            )
            if previous_sent_at:
                logger.info(
                    f'Recipient already sent: date={trade_date}, type={report_type}, '
                    f'recipient={recipient}, sent_at={previous_sent_at}. Skip.'
                )
                skipped_count += 1
                results.append({
                    'recipient': recipient,
                    'status': SEND_STATUS_SKIPPED_DUPLICATE,
                    'sent_at': previous_sent_at,
                })
            else:
                pending.append(recipient)

        if pending:
            msg = build_message(
                cfg,
                trade_date,
                html_path,
                md_path,
                pdf_path,
                pending,
                cc,
                report_type=report_type,
                scheduled_date=scheduled_date,
                generated_at=generated_at,
                attachment_types=attachment_types,
            )
            ok = send_message(cfg, msg, pending + cc, logger)
            status = SEND_STATUS_SENT if ok else SEND_STATUS_FAILED
            for recipient in pending:
                record_recipient_send_history(
                    trade_date=trade_date,
                    report_type=report_type,
                    recipient=recipient,
                    cc=cc,
                    status=status,
                    html_path=html_path,
                    md_path=md_path,
                    pdf_path=pdf_path,
                )
                results.append({'recipient': recipient, 'status': status})
            if ok:
                sent_count += len(pending)
            else:
                failed_count += len(pending)

        if start + batch_size < len(recipients) and interval:
            logger.info(f'Wait {interval} seconds before next email batch.')
            time.sleep(interval)

    return {
        'results': results,
        'sent_count': sent_count,
        'failed_count': failed_count,
        'skipped_count': skipped_count,
    }


def send_report(
    trade_date,
    recipients=None,
    cc=None,
    dry_run=None,
    force=False,
    report_type='daily',
    resend=False,
    html_path=None,
    md_path=None,
    pdf_path=None,
    scheduled_date=None,
    generated_at=None,
    attachment_types=None,
):
    logger = logging.getLogger('report_email')
    loader = FuturesDataLoader()

    if not force and not loader.is_trading_day(trade_date):
        logger.info(f'{trade_date} is not a trading day. Skip email silently.')
        return {'status': 'skipped_non_trading_day'}

    cfg = email_config()
    if dry_run is not None:
        cfg['dry_run'] = dry_run

    recipients = recipients or cfg['recipients']
    cc = cc if cc is not None else cfg['cc']
    if not recipients:
        raise ValueError('No recipients configured. Set REPORT_RECIPIENTS or pass --to.')

    if html_path is None or md_path is None or pdf_path is None:
        html_path, md_path, pdf_path = report_paths(trade_date, report_type)
    else:
        html_path = Path(html_path)
        md_path = Path(md_path)
        pdf_path = Path(pdf_path)
    try:
        total_size = check_attachments(
            trade_date,
            pdf_path,
            html_path,
            md_path,
            cfg['max_attachment_size'],
            attachment_types=attachment_types,
        )
    except Exception as exc:
        error = str(exc)
        record_send_history(
            trade_date=trade_date,
            report_type=report_type,
            recipients=recipients,
            cc=cc,
            status=SEND_STATUS_FAILED,
            html_path=html_path if html_path.exists() else None,
            md_path=md_path if md_path.exists() else None,
            pdf_path=pdf_path if pdf_path.exists() else None,
            error=error,
        )
        notify_failure('邮件附件检查失败', f'{trade_date} {report_type}\n{error}', logger=logger)
        raise
    attachments = existing_selected_attachments(pdf_path, html_path, md_path, attachment_types)

    key = recipients_key(recipients, cc)
    if not cfg['dry_run'] and not resend:
        previous_sent_at = has_successful_send(trade_date, report_type, key)
        if previous_sent_at:
            logger.info(
                f'Report already sent: date={trade_date}, type={report_type}, '
                f'sent_at={previous_sent_at}. Skip email.'
            )
            return {
                'status': SEND_STATUS_SKIPPED_DUPLICATE,
                'trade_date': trade_date,
                'report_type': report_type,
                'sent_at': previous_sent_at,
            }

    if cfg['dry_run']:
        logger.info('[DRY-RUN] Email not sent.')
        logger.info(f'[DRY-RUN] To: {", ".join(recipients)}')
        if cc:
            logger.info(f'[DRY-RUN] Cc: {", ".join(cc)}')
        logger.info(f'[DRY-RUN] Attachments: {", ".join(path.name for path in attachments)}; total={total_size} bytes')
        record_send_history(
            trade_date=trade_date,
            report_type=report_type,
            recipients=recipients,
            cc=cc,
            status=SEND_STATUS_DRY_RUN,
            html_path=html_path,
            md_path=md_path,
            pdf_path=pdf_path if pdf_path.exists() else None,
        )
        for recipient in recipients:
            record_recipient_send_history(
                trade_date=trade_date,
                report_type=report_type,
                recipient=recipient,
                cc=cc,
                status=SEND_STATUS_DRY_RUN,
                html_path=html_path,
                md_path=md_path,
                pdf_path=pdf_path if pdf_path.exists() else None,
            )
        return {
            'status': SEND_STATUS_DRY_RUN,
            'trade_date': trade_date,
            'report_type': report_type,
            'recipients': recipients + cc,
            'attachments': [str(path) for path in attachments],
        }

    if not cfg['sender'] or not cfg['password']:
        raise ValueError('EMAIL_SENDER and EMAIL_PASSWORD are required for real sending.')

    batch_result = send_report_batches(
        cfg=cfg,
        trade_date=trade_date,
        report_type=report_type,
        recipients=recipients,
        cc=cc,
        html_path=html_path,
        md_path=md_path,
        pdf_path=pdf_path if pdf_path.exists() else None,
        resend=resend,
        logger=logger,
        scheduled_date=scheduled_date,
        generated_at=generated_at,
        attachment_types=attachment_types,
    )
    if batch_result['failed_count']:
        status = SEND_STATUS_PARTIAL_FAILED if batch_result['sent_count'] else SEND_STATUS_FAILED
    elif batch_result['sent_count']:
        status = SEND_STATUS_SENT
    else:
        status = SEND_STATUS_SKIPPED_DUPLICATE
    record_send_history(
        trade_date=trade_date,
        report_type=report_type,
        recipients=recipients,
        cc=cc,
        status=status,
        html_path=html_path,
        md_path=md_path,
        pdf_path=pdf_path if pdf_path.exists() else None,
    )
    if status in (SEND_STATUS_FAILED, SEND_STATUS_PARTIAL_FAILED):
        notify_failure(
            '邮件发送失败',
            (
                f'日期：{trade_date}\n'
                f'类型：{report_type}\n'
                f'状态：{status}\n'
                f'成功：{batch_result["sent_count"]}\n'
                f'失败：{batch_result["failed_count"]}\n'
                f'跳过：{batch_result["skipped_count"]}'
            ),
            logger=logger,
        )
    return {
        'status': status,
        'trade_date': trade_date,
        'report_type': report_type,
        'sent_count': batch_result['sent_count'],
        'failed_count': batch_result['failed_count'],
        'skipped_count': batch_result['skipped_count'],
        'recipient_results': batch_result['results'],
    }


def parse_args():
    parser = argparse.ArgumentParser(description='Send futures daily report email')
    parser.add_argument('--date', default=datetime.now().strftime('%Y%m%d'), help='YYYYMMDD')
    parser.add_argument('--to', default='', help='Recipients separated by comma or semicolon')
    parser.add_argument('--cc', default='', help='CC recipients separated by comma or semicolon')
    parser.add_argument('--send', action='store_true', help='Actually send email. Default is dry-run.')
    parser.add_argument('--force', action='store_true', help='Allow sending on non-trading days.')
    parser.add_argument('--report-type', choices=['morning', 'white', 'daily'], default='daily')
    parser.add_argument('--resend', action='store_true', help='Send again even if this report was already sent.')
    parser.add_argument('--html-path', default='', help='Explicit HTML report path')
    parser.add_argument('--md-path', default='', help='Explicit Markdown report path')
    parser.add_argument('--pdf-path', default='', help='Explicit PDF report path')
    parser.add_argument('--attachments', default='', help='Attachment types: pdf,html,md')
    return parser.parse_args()


def main():
    setup_logging()
    args = parse_args()
    recipients = split_addresses(args.to) if args.to else None
    cc = split_addresses(args.cc) if args.cc else None
    started_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        result = send_report(
            trade_date=args.date,
            recipients=recipients,
            cc=cc,
            dry_run=not args.send,
            force=args.force,
            report_type=args.report_type,
            resend=args.resend,
            html_path=args.html_path or None,
            md_path=args.md_path or None,
            pdf_path=args.pdf_path or None,
            attachment_types=parse_attachment_types(args.attachments),
        )
    except Exception as exc:
        record_task_run(
            task_type='mail_send',
            task_name='邮件发送',
            status='failed',
            target_date=args.date,
            detail=args.report_type,
            error=str(exc),
            started_at=started_at,
        )
        raise
    logging.getLogger('report_email').info(f'Result: {result["status"]}')
    record_task_run(
        task_type='mail_send',
        task_name='邮件发送',
        status='success' if result['status'] in (
            SEND_STATUS_SENT,
            SEND_STATUS_DRY_RUN,
            SEND_STATUS_SKIPPED_DUPLICATE,
            SEND_STATUS_PARTIAL_FAILED,
            'skipped_non_trading_day',
        ) else 'failed',
        target_date=args.date,
        detail=args.report_type,
        output=str(result),
        started_at=started_at,
    )
    return 0 if result['status'] in (
        SEND_STATUS_SENT,
        SEND_STATUS_DRY_RUN,
        SEND_STATUS_SKIPPED_DUPLICATE,
        SEND_STATUS_PARTIAL_FAILED,
        'skipped_non_trading_day',
    ) else 1


if __name__ == '__main__':
    raise SystemExit(main())

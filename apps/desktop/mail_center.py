from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from desktop.actions import ActionResult, run_python_script
from desktop.config_center import (
    CommonConfig,
    common_env_path,
    env_bool,
    load_common_config,
    read_env_file,
    safe_int,
    save_common_config,
    write_env_file,
)
from desktop.project_paths import report_system_dir
from desktop.task_records import run_and_record


SCRIPT_ENV = {
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
}


@dataclass(frozen=True)
class MailRecipient:
    email: str
    name: str = ""
    enabled: bool = True
    remark: str = ""


@dataclass(frozen=True)
class MailAccountConfig:
    sender: str = ""
    password: str = ""
    host: str = "smtp.163.com"
    port: int = 465
    use_ssl: bool = True
    cc: str = ""
    dry_run: bool = True
    batch_interval_seconds: int = 20
    has_password: bool = False


@dataclass(frozen=True)
class MailSendRecord:
    id: int
    scope: str
    trade_date: str
    report_type: str
    recipient: str
    recipients: str
    cc: str
    status: str
    sent_at: str
    error: str
    html_path: Path | None = None
    md_path: Path | None = None
    pdf_path: Path | None = None

    @property
    def target(self) -> str:
        return self.recipient or self.recipients

    @property
    def failure_reason(self) -> str:
        return self.error or "同批次发送失败，具体原因见总发送记录或执行输出。"


Runner = Callable[..., ActionResult]


def load_mail_account_config(project_root: Path) -> MailAccountConfig:
    config = load_common_config(project_root)
    return MailAccountConfig(
        sender=config.sender,
        password="",
        host=config.smtp_host,
        port=config.smtp_port,
        use_ssl=config.smtp_use_ssl,
        cc=config.report_cc,
        dry_run=config.report_email_dry_run,
        batch_interval_seconds=config.report_email_batch_interval_seconds,
        has_password=config.has_email_password,
    )


def save_mail_account_config(project_root: Path, config: MailAccountConfig) -> ActionResult:
    current = load_common_config(project_root)
    return save_common_config(
        project_root,
        CommonConfig(
            sender=config.sender,
            email_password=config.password,
            smtp_host=config.host,
            smtp_port=config.port,
            smtp_use_ssl=config.use_ssl,
            report_cc=config.cc,
            report_email_dry_run=config.dry_run,
            report_email_batch_interval_seconds=config.batch_interval_seconds,
            report_max_attachment_size=current.report_max_attachment_size,
            futures_data_dir=current.futures_data_dir,
            backup_dir=current.backup_dir,
            db_backup_keep_days=current.db_backup_keep_days,
            log_keep_days=current.log_keep_days,
            report_keep_days=current.report_keep_days,
            ai_analysis_enabled=current.ai_analysis_enabled,
            ai_assistant_use_commercial_ai=current.ai_assistant_use_commercial_ai,
            deepseek_api_key=current.deepseek_api_key,
            deepseek_api_base=current.deepseek_api_base,
            deepseek_model=current.deepseek_model,
            ai_analysis_timeout_seconds=current.ai_analysis_timeout_seconds,
            ai_analysis_max_tokens=current.ai_analysis_max_tokens,
            tushare_token=current.tushare_token,
            tushare_http_url=current.tushare_http_url,
            has_email_password=config.has_password,
            has_deepseek_api_key=current.has_deepseek_api_key,
            has_tushare_token=current.has_tushare_token,
        ),
    )


def load_mail_recipients(project_root: Path) -> list[MailRecipient]:
    path = _recipients_path(project_root)
    if not path.exists():
        return []

    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                return [_recipient_from_row(row) for row in reader if _row_has_value(row)]
        except UnicodeDecodeError:
            continue
        except (OSError, csv.Error):
            return []
    return []


def save_mail_recipients(project_root: Path, recipients: list[MailRecipient]) -> ActionResult:
    path = _recipients_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["email", "name", "enabled", "remark"])
            writer.writeheader()
            for recipient in recipients:
                writer.writerow(
                    {
                        "email": recipient.email.strip(),
                        "name": recipient.name.strip(),
                        "enabled": "TRUE" if recipient.enabled else "FALSE",
                        "remark": recipient.remark.strip(),
                    }
                )
    except (OSError, csv.Error) as exc:
        return ActionResult(False, f"收件人保存失败：{exc}")
    return ActionResult(True, "收件人列表已保存。")


def add_mail_recipient(project_root: Path, recipient: MailRecipient) -> ActionResult:
    recipients = load_mail_recipients(project_root)
    email = recipient.email.strip().lower()
    if not email:
        return ActionResult(False, "邮箱不能为空。")
    if any(item.email.lower() == email for item in recipients):
        return ActionResult(False, f"收件人已存在：{recipient.email}")
    return save_mail_recipients(project_root, recipients + [recipient])


def update_mail_recipient(project_root: Path, old_email: str, recipient: MailRecipient) -> ActionResult:
    recipients = load_mail_recipients(project_root)
    old_email = old_email.strip().lower()
    new_email = recipient.email.strip().lower()
    updated: list[MailRecipient] = []
    found = False
    for item in recipients:
        if item.email.lower() == old_email:
            updated.append(recipient)
            found = True
        else:
            if item.email.lower() == new_email and old_email != new_email:
                return ActionResult(False, f"收件人已存在：{recipient.email}")
            updated.append(item)
    if not found:
        return ActionResult(False, "未找到要修改的收件人。")
    return save_mail_recipients(project_root, updated)


def delete_mail_recipient(project_root: Path, email: str) -> ActionResult:
    recipients = load_mail_recipients(project_root)
    email = email.strip().lower()
    kept = [item for item in recipients if item.email.lower() != email]
    if len(kept) == len(recipients):
        return ActionResult(False, "未找到要删除的收件人。")
    return save_mail_recipients(project_root, kept)


def build_send_selected_args(
    trade_date: str,
    report_type: str,
    recipients: list[str],
    attachments: list[str],
    cc: str = "",
    resend: bool = True,
) -> list[str]:
    args = [
        "send_report_email.py",
        "--report-type",
        report_type,
        "--date",
        trade_date,
        "--send",
        "--force",
        "--to",
        ",".join(address.strip() for address in recipients if address.strip()),
        "--attachments",
        ",".join(_normalize_attachment_types(attachments)),
    ]
    if cc.strip():
        args.extend(["--cc", cc.strip()])
    if resend:
        args.append("--resend")
    return args


def send_selected_report(
    project_root: Path,
    trade_date: str,
    report_type: str,
    recipients: list[str],
    attachments: list[str],
    cc: str = "",
    confirmed: bool = False,
    runner: Runner = run_python_script,
) -> ActionResult:
    if not confirmed:
        return ActionResult(False, "发送前需要确认，未确认不会启动发送脚本。")
    if not recipients:
        return ActionResult(False, "请先选择至少一个收件人。")
    if not _normalize_attachment_types(attachments):
        return ActionResult(False, "请至少选择一种发送内容。")
    report_dir = report_system_dir(Path(project_root))
    args = build_send_selected_args(trade_date, report_type, recipients, attachments, cc=cc)
    return run_and_record(
        project_root,
        task_type="mail_send",
        task_name="发送给选中收件人",
        target_date=trade_date,
        detail=f"{report_type} -> {len(recipients)} 人",
        fn=lambda: runner(
            report_dir,
            report_dir / args[0],
            args=args[1:],
            timeout_seconds=300,
            env=SCRIPT_ENV,
        ),
    )


def load_mail_send_records(project_root: Path, limit: int = 80) -> list[MailSendRecord]:
    db_path = Path(project_root) / "data" / "futures.db"
    if not db_path.exists():
        return []

    conn = sqlite3.connect(db_path)
    try:
        if _table_exists(conn, "report_recipient_send_history"):
            records = _load_recipient_records(conn, limit)
            if records:
                return _fill_missing_failure_reasons(conn, records)
        if _table_exists(conn, "report_send_history"):
            return _load_batch_records(conn, limit)
        return []
    finally:
        conn.close()


def build_resend_args(record: MailSendRecord) -> list[str]:
    args = [
        "send_report_email.py",
        "--report-type",
        record.report_type,
        "--date",
        record.trade_date,
        "--send",
        "--force",
        "--resend",
    ]
    recipients = record.recipient or record.recipients
    if recipients:
        args.extend(["--to", recipients])
    if record.cc:
        args.extend(["--cc", record.cc])
    if record.html_path is not None:
        args.extend(["--html-path", str(record.html_path)])
    if record.md_path is not None:
        args.extend(["--md-path", str(record.md_path)])
    if record.pdf_path is not None:
        args.extend(["--pdf-path", str(record.pdf_path)])
    return args


def resend_mail_record(project_root: Path, record: MailSendRecord, runner: Runner = run_python_script) -> ActionResult:
    report_dir = report_system_dir(Path(project_root))
    args = build_resend_args(record)
    return run_and_record(
        project_root,
        task_type="mail_send",
        task_name="重发邮件",
        target_date=record.trade_date,
        detail=f"{record.report_type} -> {record.target}",
        fn=lambda: runner(
            report_dir,
            report_dir / args[0],
            args=args[1:],
            timeout_seconds=300,
            env=SCRIPT_ENV,
        ),
    )


def _recipient_from_row(row: dict[str, str]) -> MailRecipient:
    enabled_text = (row.get("enabled") or "true").strip().lower()
    return MailRecipient(
        email=(row.get("email") or "").strip(),
        name=(row.get("name") or row.get("收件人") or "").strip(),
        enabled=enabled_text in ("1", "true", "yes", "y", "是", "启用", ""),
        remark=(row.get("remark") or row.get("备注") or "").strip(),
    )


def _mail_env_path(project_root: Path) -> Path:
    return common_env_path(project_root)


def _recipients_path(project_root: Path) -> Path:
    return report_system_dir(Path(project_root)) / "recipients.csv"


def _read_env_file(path: Path) -> dict[str, str]:
    return read_env_file(path)


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    write_env_file(path, values)


def _env_bool(value: str | None, default: bool) -> bool:
    return env_bool(value, default)


def _safe_int(value: str | None, default: int) -> int:
    return safe_int(value, default)


def _normalize_attachment_types(attachments: list[str]) -> list[str]:
    allowed = {"pdf", "html", "md"}
    normalized = []
    for item in attachments:
        value = item.strip().lower()
        if value == "markdown":
            value = "md"
        if value in allowed and value not in normalized:
            normalized.append(value)
    return normalized


def _row_has_value(row: dict[str, str]) -> bool:
    return any(str(value or "").strip() for value in row.values())


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type='table' and name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _load_recipient_records(conn: sqlite3.Connection, limit: int) -> list[MailSendRecord]:
    rows = conn.execute(
        """
        select id, trade_date, report_type, recipient, cc, status, sent_at,
               coalesce(error, ''), html_path, md_path, pdf_path
        from report_recipient_send_history
        order by id desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [
        MailSendRecord(
            id=int(row[0]),
            scope="recipient",
            trade_date=str(row[1] or ""),
            report_type=str(row[2] or "daily"),
            recipient=str(row[3] or ""),
            recipients="",
            cc=str(row[4] or ""),
            status=str(row[5] or ""),
            sent_at=str(row[6] or ""),
            error=str(row[7] or ""),
            html_path=_optional_path(row[8]),
            md_path=_optional_path(row[9]),
            pdf_path=_optional_path(row[10]),
        )
        for row in rows
    ]


def _load_batch_records(conn: sqlite3.Connection, limit: int) -> list[MailSendRecord]:
    rows = conn.execute(
        """
        select id, trade_date, report_type, recipients, cc, status, sent_at,
               coalesce(error, ''), html_path, md_path, pdf_path
        from report_send_history
        order by id desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [
        MailSendRecord(
            id=int(row[0]),
            scope="batch",
            trade_date=str(row[1] or ""),
            report_type=str(row[2] or "daily"),
            recipient="",
            recipients=str(row[3] or ""),
            cc=str(row[4] or ""),
            status=str(row[5] or ""),
            sent_at=str(row[6] or ""),
            error=str(row[7] or ""),
            html_path=_optional_path(row[8]),
            md_path=_optional_path(row[9]),
            pdf_path=_optional_path(row[10]),
        )
        for row in rows
    ]


def _fill_missing_failure_reasons(
    conn: sqlite3.Connection,
    records: list[MailSendRecord],
) -> list[MailSendRecord]:
    if not _table_exists(conn, "report_send_history"):
        return records

    filled = []
    for record in records:
        if record.error or record.status not in ("failed", "partial_failed"):
            filled.append(record)
            continue
        row = conn.execute(
            """
            select coalesce(error, '')
            from report_send_history
            where trade_date = ?
              and report_type = ?
              and status in ('failed', 'partial_failed')
              and coalesce(error, '') <> ''
            order by sent_at desc, id desc
            limit 1
            """,
            (record.trade_date, record.report_type),
        ).fetchone()
        if row and row[0]:
            record = MailSendRecord(
                id=record.id,
                scope=record.scope,
                trade_date=record.trade_date,
                report_type=record.report_type,
                recipient=record.recipient,
                recipients=record.recipients,
                cc=record.cc,
                status=record.status,
                sent_at=record.sent_at,
                error=str(row[0]),
                html_path=record.html_path,
                md_path=record.md_path,
                pdf_path=record.pdf_path,
            )
        filled.append(record)
    return filled


def _optional_path(value: object) -> Path | None:
    text = str(value or "").strip()
    return Path(text) if text else None

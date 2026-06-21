from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from desktop.actions import ActionResult
from desktop.project_paths import data_downloader_dir, report_system_dir


@dataclass(frozen=True)
class CommonConfig:
    sender: str = ""
    email_password: str = ""
    smtp_host: str = "smtp.163.com"
    smtp_port: int = 465
    smtp_use_ssl: bool = True
    report_cc: str = ""
    report_email_dry_run: bool = True
    report_email_batch_interval_seconds: int = 20
    report_max_attachment_size: int = 20_971_520
    futures_data_dir: str = "data"
    backup_dir: str = "backups"
    db_backup_keep_days: int = 30
    log_keep_days: int = 60
    report_keep_days: int = 180
    ai_analysis_enabled: bool = False
    ai_assistant_use_commercial_ai: bool = False
    deepseek_api_key: str = ""
    deepseek_api_base: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    ai_analysis_timeout_seconds: int = 60
    ai_analysis_max_tokens: int = 900
    tushare_token: str = ""
    tushare_http_url: str = ""
    has_email_password: bool = False
    has_deepseek_api_key: bool = False
    has_tushare_token: bool = False


def load_common_config(project_root: Path) -> CommonConfig:
    return _load_common_config(project_root, include_secrets=False)


def load_common_config_with_secrets(project_root: Path) -> CommonConfig:
    return _load_common_config(project_root, include_secrets=True)


def _load_common_config(project_root: Path, include_secrets: bool) -> CommonConfig:
    values = read_env_file(common_env_path(project_root))
    tushare_values = read_env_file(tushare_env_path(project_root))
    email_password = values.get("EMAIL_PASSWORD", "")
    deepseek_api_key = values.get("DEEPSEEK_API_KEY", "")
    tushare_token = tushare_values.get("TUSHARE_TOKEN", "")
    return CommonConfig(
        sender=values.get("EMAIL_SENDER", ""),
        email_password=email_password if include_secrets else "",
        smtp_host=values.get("SMTP_HOST", "smtp.163.com"),
        smtp_port=safe_int(values.get("SMTP_PORT"), 465),
        smtp_use_ssl=env_bool(values.get("SMTP_USE_SSL"), True),
        report_cc=values.get("REPORT_CC", ""),
        report_email_dry_run=env_bool(values.get("REPORT_EMAIL_DRY_RUN"), True),
        report_email_batch_interval_seconds=safe_int(values.get("REPORT_EMAIL_BATCH_INTERVAL_SECONDS"), 20),
        report_max_attachment_size=safe_int(values.get("REPORT_MAX_ATTACHMENT_SIZE"), 20_971_520),
        futures_data_dir=values.get("FUTURES_DATA_DIR", "data"),
        backup_dir=values.get("BACKUP_DIR", "backups"),
        db_backup_keep_days=safe_int(values.get("DB_BACKUP_KEEP_DAYS"), 30),
        log_keep_days=safe_int(values.get("LOG_KEEP_DAYS"), 60),
        report_keep_days=safe_int(values.get("REPORT_KEEP_DAYS"), 180),
        ai_analysis_enabled=env_bool(values.get("AI_ANALYSIS_ENABLED"), False),
        ai_assistant_use_commercial_ai=env_bool(values.get("AI_ASSISTANT_USE_COMMERCIAL_AI"), False),
        deepseek_api_key=deepseek_api_key if include_secrets else "",
        deepseek_api_base=values.get("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
        deepseek_model=values.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        ai_analysis_timeout_seconds=safe_int(values.get("AI_ANALYSIS_TIMEOUT_SECONDS"), 60),
        ai_analysis_max_tokens=safe_int(values.get("AI_ANALYSIS_MAX_TOKENS"), 900),
        tushare_token=tushare_token if include_secrets else "",
        tushare_http_url=tushare_values.get("TUSHARE_HTTP_URL", ""),
        has_email_password=bool(email_password),
        has_deepseek_api_key=bool(deepseek_api_key),
        has_tushare_token=bool(tushare_token),
    )


def save_common_config(project_root: Path, config: CommonConfig) -> ActionResult:
    env_path = common_env_path(project_root)
    values = read_env_file(env_path)
    values["EMAIL_SENDER"] = config.sender.strip()
    if config.email_password:
        values["EMAIL_PASSWORD"] = config.email_password
    elif not config.has_email_password:
        values["EMAIL_PASSWORD"] = ""
    values["SMTP_HOST"] = config.smtp_host.strip() or "smtp.163.com"
    values["SMTP_PORT"] = str(config.smtp_port or 465)
    values["SMTP_USE_SSL"] = bool_text(config.smtp_use_ssl)
    values["REPORT_CC"] = config.report_cc.strip()
    values["REPORT_EMAIL_DRY_RUN"] = bool_text(config.report_email_dry_run)
    values["REPORT_EMAIL_BATCH_INTERVAL_SECONDS"] = str(max(0, config.report_email_batch_interval_seconds))
    values["REPORT_MAX_ATTACHMENT_SIZE"] = str(max(0, config.report_max_attachment_size))
    values["FUTURES_DATA_DIR"] = config.futures_data_dir.strip() or "data"
    values["BACKUP_DIR"] = config.backup_dir.strip() or "backups"
    values["DB_BACKUP_KEEP_DAYS"] = str(max(0, config.db_backup_keep_days))
    values["LOG_KEEP_DAYS"] = str(max(0, config.log_keep_days))
    values["REPORT_KEEP_DAYS"] = str(max(0, config.report_keep_days))
    values["AI_ANALYSIS_ENABLED"] = bool_text(config.ai_analysis_enabled)
    values["AI_ASSISTANT_USE_COMMERCIAL_AI"] = bool_text(config.ai_assistant_use_commercial_ai)
    if config.deepseek_api_key:
        values["DEEPSEEK_API_KEY"] = config.deepseek_api_key
    elif not config.has_deepseek_api_key:
        values["DEEPSEEK_API_KEY"] = ""
    values["DEEPSEEK_API_BASE"] = config.deepseek_api_base.strip() or "https://api.deepseek.com"
    values["DEEPSEEK_MODEL"] = config.deepseek_model.strip() or "deepseek-v4-flash"
    values["AI_ANALYSIS_TIMEOUT_SECONDS"] = str(max(1, config.ai_analysis_timeout_seconds))
    values["AI_ANALYSIS_MAX_TOKENS"] = str(max(1, config.ai_analysis_max_tokens))
    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        write_env_file(env_path, values)
        save_tushare_config(project_root, config)
    except OSError as exc:
        return ActionResult(False, f"配置保存失败：{exc}")
    return ActionResult(True, "配置已保存。")


def common_env_path(project_root: Path) -> Path:
    return report_system_dir(Path(project_root)) / ".env"


def tushare_env_path(project_root: Path) -> Path:
    return data_downloader_dir(Path(project_root)) / ".env"


def save_tushare_config(project_root: Path, config: CommonConfig) -> None:
    env_path = tushare_env_path(project_root)
    values = read_env_file(env_path)
    if config.tushare_token:
        values["TUSHARE_TOKEN"] = config.tushare_token
    elif not config.has_tushare_token:
        values["TUSHARE_TOKEN"] = ""
    http_url = config.tushare_http_url.strip()
    if http_url:
        values["TUSHARE_HTTP_URL"] = http_url
    else:
        values.pop("TUSHARE_HTTP_URL", None)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    write_env_file(env_path, values, order=TUSHARE_ENV_WRITE_ORDER)


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()
    except OSError:
        return {}
    return values


def write_env_file(path: Path, values: dict[str, str], order: list[str] | None = None) -> None:
    write_order = order or ENV_WRITE_ORDER
    keys = [key for key in write_order if key in values] + [key for key in values if key not in write_order]
    path.write_text("\n".join(f"{key}={values.get(key, '')}" for key in keys) + "\n", encoding="utf-8")


def env_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "是")


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def safe_int(value: str | None, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


ENV_WRITE_ORDER = [
    "FUTURES_DATA_DIR",
    "BACKUP_DIR",
    "DB_BACKUP_KEEP_DAYS",
    "LOG_KEEP_DAYS",
    "REPORT_KEEP_DAYS",
    "EMAIL_SENDER",
    "EMAIL_PASSWORD",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USE_SSL",
    "REPORT_CC",
    "REPORT_EMAIL_DRY_RUN",
    "REPORT_MAX_ATTACHMENT_SIZE",
    "REPORT_EMAIL_BATCH_INTERVAL_SECONDS",
    "AI_ANALYSIS_ENABLED",
    "AI_ASSISTANT_USE_COMMERCIAL_AI",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_BASE",
    "DEEPSEEK_MODEL",
    "AI_ANALYSIS_TIMEOUT_SECONDS",
    "AI_ANALYSIS_MAX_TOKENS",
]

TUSHARE_ENV_WRITE_ORDER = [
    "TUSHARE_TOKEN",
    "TUSHARE_HTTP_URL",
]

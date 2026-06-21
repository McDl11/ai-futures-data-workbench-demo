import argparse
import os
import sqlite3
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from config import BACKUP_DIR, BASE_DIR, DB_PATH, LOGS_DIR, REPORTS_DIR


load_dotenv(BASE_DIR / '.env')

DB_BACKUP_KEEP_DAYS = int(os.getenv('DB_BACKUP_KEEP_DAYS', '30'))
LOG_KEEP_DAYS = int(os.getenv('LOG_KEEP_DAYS', '60'))
REPORT_KEEP_DAYS = int(os.getenv('REPORT_KEEP_DAYS', '180'))


def setup_console():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def human_size(size):
    size = float(size)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024 or unit == 'GB':
            return f'{size:.1f}{unit}' if unit != 'B' else f'{int(size)}B'
        size /= 1024


def log(message):
    print(f'[{datetime.now().strftime("%H:%M:%S")}] {message}', flush=True)


def ensure_dirs():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def backup_database():
    if not DB_PATH.exists():
        raise FileNotFoundError(f'数据库不存在: {DB_PATH}')

    ensure_dirs()
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_db = BACKUP_DIR / f'futures_{stamp}.db'
    zip_path = BACKUP_DIR / f'futures_{stamp}.zip'

    log(f'开始备份数据库: {DB_PATH}')
    source = sqlite3.connect(DB_PATH)
    try:
        target = sqlite3.connect(temp_db)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(temp_db, arcname=temp_db.name)
    temp_db.unlink()

    log(f'数据库备份完成: {zip_path.name} ({human_size(zip_path.stat().st_size)})')
    return zip_path


def cutoff_time(days):
    return datetime.now() - timedelta(days=days)


def delete_old_files(folder, pattern, keep_days, dry_run=False):
    if keep_days <= 0 or not folder.exists():
        return []
    cutoff = cutoff_time(keep_days)
    deleted = []
    for path in folder.glob(pattern):
        if not path.is_file():
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if mtime >= cutoff:
            continue
        deleted.append(path)
        if not dry_run:
            path.unlink()
    return deleted


def delete_old_files_recursive(folder, pattern, keep_days, dry_run=False):
    if keep_days <= 0 or not folder.exists():
        return []
    cutoff = cutoff_time(keep_days)
    deleted = []
    for path in folder.rglob(pattern):
        if not path.is_file():
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if mtime >= cutoff:
            continue
        deleted.append(path)
        if not dry_run:
            path.unlink()
    return deleted


def delete_old_report_dirs(keep_days, dry_run=False):
    if keep_days <= 0 or not REPORTS_DIR.exists():
        return []
    cutoff = cutoff_time(keep_days)
    deleted = []
    for path in REPORTS_DIR.iterdir():
        if not path.is_dir():
            continue
        if not path.name.isdigit():
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if mtime >= cutoff:
            continue
        deleted.append(path)
        if not dry_run:
            remove_tree(path)
    return deleted


def remove_tree(path):
    for child in path.iterdir():
        if child.is_dir():
            remove_tree(child)
        else:
            child.unlink()
    path.rmdir()


def cleanup_old_files(dry_run=False):
    ensure_dirs()
    results = {
        'backup_zip': delete_old_files(BACKUP_DIR, 'futures_*.zip', DB_BACKUP_KEEP_DAYS, dry_run),
        'backup_temp_db': delete_old_files(BACKUP_DIR, 'futures_*.db', 1, dry_run),
        'logs': delete_old_files_recursive(LOGS_DIR, '*.*', LOG_KEEP_DAYS, dry_run),
        'reports': delete_old_report_dirs(REPORT_KEEP_DAYS, dry_run),
    }
    for label, paths in results.items():
        action = '将清理' if dry_run else '已清理'
        log(f'{label}: {action} {len(paths)} 项')
    return results


def latest_backup():
    if not BACKUP_DIR.exists():
        return None
    backups = sorted(BACKUP_DIR.glob('futures_*.zip'), key=lambda p: p.stat().st_mtime, reverse=True)
    return backups[0] if backups else None


def main():
    setup_console()
    parser = argparse.ArgumentParser(description='Futures report maintenance')
    parser.add_argument('--no-backup', action='store_true', help='只清理，不备份数据库')
    parser.add_argument('--no-cleanup', action='store_true', help='只备份，不清理旧文件')
    parser.add_argument('--dry-run', action='store_true', help='只预览清理项，不删除')
    args = parser.parse_args()

    log('维护任务开始')
    log(f'数据库: {DB_PATH}')
    log(f'备份目录: {BACKUP_DIR}')
    log(f'保留策略: 备份 {DB_BACKUP_KEEP_DAYS} 天，日志 {LOG_KEEP_DAYS} 天，报告 {REPORT_KEEP_DAYS} 天')

    backup_path = None
    if not args.no_backup:
        backup_path = backup_database()

    if not args.no_cleanup:
        cleanup_old_files(dry_run=args.dry_run)

    newest = latest_backup()
    if newest:
        log(f'最新备份: {newest.name} ({human_size(newest.stat().st_size)})')
    if backup_path:
        log('维护任务完成')
    else:
        log('维护任务完成：本次未生成新备份')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

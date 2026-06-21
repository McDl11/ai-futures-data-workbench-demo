import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent


def find_project_root(start):
    for path in (Path(start).resolve(), *Path(start).resolve().parents):
        if (path / 'AI金融数据工作台进化规划.md').exists():
            return path
        if (path / 'apps').exists() and (path / 'services').exists() and (path / 'data').exists():
            return path
    return Path(start).resolve().parent


PROJECT_ROOT = find_project_root(BASE_DIR)

load_dotenv(BASE_DIR / '.env')


def resolve_project_path(value, default):
    path = Path(value) if value else default
    if not path.is_absolute() and path == Path('backup'):
        path = Path('backups')
    return path if path.is_absolute() else PROJECT_ROOT / path


DATA_DIR = resolve_project_path(os.getenv('FUTURES_DATA_DIR'), PROJECT_ROOT / 'data')
DB_PATH = DATA_DIR / 'futures.db'
REPORTS_DIR = BASE_DIR / 'reports'
LOGS_DIR = BASE_DIR / 'logs'
BACKUP_DIR = resolve_project_path(os.getenv('BACKUP_DIR'), PROJECT_ROOT / 'backups')

DEFAULT_EXCHANGES = ('CFFEX', 'SHFE', 'DCE', 'CZCE', 'INE')


def resolve_backup_dir(value=None):
    return resolve_project_path(value if value else os.getenv('BACKUP_DIR'), PROJECT_ROOT / 'backups')


def get_log_dir(category=None):
    path = LOGS_DIR / category if category else LOGS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path

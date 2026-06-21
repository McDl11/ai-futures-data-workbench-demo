from pathlib import Path

from config import LOGS_DIR, PROJECT_ROOT, get_log_dir


SYSTEM_RULES = [
    ('auto_', '自动任务'),
    ('report_', '报告生成'),
    ('email_', '邮件发送'),
    ('health_', '体检'),
]

TUSHARE_LOGS_DIR = PROJECT_ROOT / 'services' / 'data_downloader' / 'logs'
if not TUSHARE_LOGS_DIR.exists():
    TUSHARE_LOGS_DIR = PROJECT_ROOT / 'tushare down' / 'logs'
TUSHARE_RULES = [
    ('scheduler.', '调度'),
    ('update_', '增量更新'),
    ('update_report_', '增量更新'),
    ('download_', '全量下载'),
    ('summary_', '全量下载'),
    ('split_', '品种拆分'),
    ('backfill_', '历史补数据'),
]


def target_name(path, target_dir):
    candidate = target_dir / path.name
    if not candidate.exists():
        return candidate

    stem = path.stem
    suffix = path.suffix
    index = 1
    while True:
        candidate = target_dir / f'{stem}_{index}{suffix}'
        if not candidate.exists():
            return candidate
        index += 1


def move_by_rules(logs_dir, rules, target_dir_factory):
    if not logs_dir.exists():
        return []

    moved = []
    for path in logs_dir.iterdir():
        if not path.is_file():
            continue
        category = None
        for prefix, rule_category in rules:
            if path.name.startswith(prefix):
                category = rule_category
                break
        if not category:
            continue

        target_dir = target_dir_factory(category)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_name(path, target_dir)
        path.replace(target)
        moved.append((path, target))
    return moved


def main():
    moved = []
    moved.extend(move_by_rules(LOGS_DIR, SYSTEM_RULES, get_log_dir))
    moved.extend(move_by_rules(TUSHARE_LOGS_DIR, TUSHARE_RULES, lambda category: TUSHARE_LOGS_DIR / category))

    for source, target in moved:
        print(f'{source} -> {target}')
    print(f'moved={len(moved)}')


if __name__ == '__main__':
    main()

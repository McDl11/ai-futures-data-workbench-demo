from pathlib import Path

from config import REPORTS_DIR


RULES = [
    ('morning', '期货早报_数据{date}', '期货市场早报_数据'),
    ('white', '期货白盘_数据{date}', '期货市场白盘日报_数据'),
]


def extract_data_date(name, marker):
    idx = name.find(marker)
    if idx < 0:
        return ''
    start = idx + len(marker)
    value = name[start:start + 8]
    return value if len(value) == 8 and value.isdigit() else ''


def archive_path(path):
    archive_dir = path.parent / 'archive_long_names'
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / path.name
    if not target.exists():
        return target
    stem = path.stem
    suffix = path.suffix
    index = 1
    while True:
        candidate = archive_dir / f'{stem}_{index}{suffix}'
        if not candidate.exists():
            return candidate
        index += 1


def migrate():
    moved = []
    archived = []
    if not REPORTS_DIR.exists():
        return moved, archived

    for report_type, new_pattern, marker in RULES:
        for path in REPORTS_DIR.glob(f'*/{report_type}/*'):
            if not path.is_file():
                continue
            if not path.name.startswith(marker):
                continue
            data_date = extract_data_date(path.name, marker)
            if not data_date:
                continue
            target = path.parent / f'{new_pattern.format(date=data_date)}{path.suffix}'
            if target.exists():
                archive = archive_path(path)
                path.replace(archive)
                archived.append((path, archive))
            else:
                path.replace(target)
                moved.append((path, target))
    return moved, archived


def main():
    moved, archived = migrate()
    for source, target in moved:
        print(f'move {source} -> {target}')
    for source, target in archived:
        print(f'archive {source} -> {target}')
    print(f'moved={len(moved)}, archived={len(archived)}')


if __name__ == '__main__':
    main()

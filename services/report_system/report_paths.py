from dataclasses import dataclass
from pathlib import Path

from config import REPORTS_DIR


DEMO_ENGLISH_FILENAMES = True


REPORT_TYPES = ('white', 'daily', 'morning')


def normalize_report_type(report_type):
    value = str(report_type or 'daily').strip().lower()
    return value if value in REPORT_TYPES else 'daily'


def report_type_label(report_type):
    return {
        'morning': '早报',
        'white': '白盘',
        'daily': '日报',
    }.get(normalize_report_type(report_type), '日报')


def safe_filename(value):
    text = str(value or '').strip()
    for char in '<>:"/\\|?*':
        text = text.replace(char, '_')
    return text or 'report'


def report_file_prefix(report_type, trade_date):
    if DEMO_ENGLISH_FILENAMES:
        return safe_filename(f'futures_{report_type}_{trade_date}')
    return safe_filename(f'期货{report_type_label(report_type)}_数据{trade_date}')


def report_output_dir(trade_date, report_type='daily', reports_dir=None):
    return Path(reports_dir or REPORTS_DIR) / str(trade_date) / normalize_report_type(report_type)


def report_paths(trade_date, report_type='daily', reports_dir=None):
    out_dir = report_output_dir(trade_date, report_type, reports_dir=reports_dir)
    prefix = report_file_prefix(report_type, trade_date)
    return (
        out_dir / f'{prefix}.html',
        out_dir / f'{prefix}.md',
        out_dir / f'{prefix}.pdf',
    )


@dataclass(frozen=True)
class ReportBundle:
    report_type: str
    directory: Path
    html_path: Path
    md_path: Path
    pdf_path: Path

    @property
    def paths(self):
        return (self.html_path, self.md_path, self.pdf_path)

    @property
    def existing_paths(self):
        return [path for path in self.paths if path.exists()]

    @property
    def is_complete(self):
        return all(path.exists() for path in self.paths)

    @property
    def latest_mtime(self):
        existing = self.existing_paths
        return max((path.stat().st_mtime for path in existing), default=0)


def expected_report_bundle(trade_date, report_type='daily', reports_dir=None):
    html_path, md_path, pdf_path = report_paths(trade_date, report_type, reports_dir=reports_dir)
    return ReportBundle(
        report_type=normalize_report_type(report_type),
        directory=html_path.parent,
        html_path=html_path,
        md_path=md_path,
        pdf_path=pdf_path,
    )


def _bundle_from_files(report_type, files):
    by_suffix = {path.suffix.lower(): path for path in files}
    sample = next(iter(files), None)
    directory = sample.parent if sample else Path()
    return ReportBundle(
        report_type=normalize_report_type(report_type),
        directory=directory,
        html_path=by_suffix.get('.html', directory / 'missing.html'),
        md_path=by_suffix.get('.md', directory / 'missing.md'),
        pdf_path=by_suffix.get('.pdf', directory / 'missing.pdf'),
    )


def discover_report_bundles(trade_date, reports_dir=None):
    base_dir = Path(reports_dir or REPORTS_DIR) / str(trade_date)
    if not base_dir.exists():
        return []

    bundles = []
    for report_type in REPORT_TYPES:
        expected = expected_report_bundle(trade_date, report_type, reports_dir=reports_dir)
        if expected.directory.exists() and expected.existing_paths:
            bundles.append(expected)

    legacy_files = [
        path for path in base_dir.iterdir()
        if path.is_file() and path.suffix.lower() in ('.html', '.md', '.pdf')
    ]
    if legacy_files:
        bundles.append(_bundle_from_files('daily', legacy_files))

    return sorted(bundles, key=lambda bundle: bundle.latest_mtime, reverse=True)


def latest_report_bundle(trade_date, preferred_type=None, reports_dir=None):
    bundles = discover_report_bundles(trade_date, reports_dir=reports_dir)
    if preferred_type:
        normalized = normalize_report_type(preferred_type)
        matching = [bundle for bundle in bundles if bundle.report_type == normalized]
        if matching:
            return matching[0]
    complete = [bundle for bundle in bundles if bundle.is_complete]
    if complete:
        return complete[0]
    return bundles[0] if bundles else None

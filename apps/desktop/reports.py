from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from collections.abc import Callable

from desktop.actions import ActionResult, run_python_script
from desktop.project_paths import report_system_dir
from desktop.report_records import GENERATION_STATUS_FAILED, GENERATION_STATUS_SUCCESS, record_report_generation
from desktop.task_records import run_and_record


REPORT_LABELS = {
    "white": "白盘",
    "daily": "日报",
}
SUPPORTED_REPORT_TYPES = ("white", "daily")


@dataclass(frozen=True)
class ReportSelection:
    trade_date: str
    report_type: str
    html_path: Path | None = None
    pdf_path: Path | None = None
    md_path: Path | None = None


@dataclass(frozen=True)
class ReportItem:
    trade_date: str
    report_type: str
    label: str
    directory: Path
    html_path: Path
    pdf_path: Path
    md_path: Path
    modified_at: datetime | None

    @property
    def display_name(self) -> str:
        return f"{self.trade_date} {self.label}"

    @property
    def has_html(self) -> bool:
        return self.html_path.exists()

    @property
    def has_pdf(self) -> bool:
        return self.pdf_path.exists()

    @property
    def has_md(self) -> bool:
        return self.md_path.exists()


def discover_reports(project_root: Path, limit: int = 30) -> list[ReportItem]:
    reports_dir = report_system_dir(Path(project_root)) / "reports"
    if not reports_dir.exists():
        return []

    items: list[ReportItem] = []
    for date_dir in reports_dir.iterdir():
        if not date_dir.is_dir() or not date_dir.name.isdigit():
            continue
        for report_type in SUPPORTED_REPORT_TYPES:
            report_dir = date_dir / report_type
            if not report_dir.exists():
                continue
            item = _report_item_from_dir(date_dir.name, report_type, report_dir)
            if item is not None:
                items.append(item)
        legacy_daily = _report_item_from_dir(date_dir.name, "daily", date_dir)
        if legacy_daily is not None:
            items.append(legacy_daily)

    return sorted(items, key=_report_sort_key, reverse=True)[:limit]


def build_generate_args(trade_date: str) -> list[str]:
    return [
        "auto_report_once.py",
        "--report-type",
        "white",
        "--date",
        trade_date,
        "--no-update",
        "--force",
    ]


def build_send_args(selection: ReportSelection, resend: bool = True) -> list[str]:
    args = [
        "send_report_email.py",
        "--report-type",
        _normalize_report_type(selection.report_type),
        "--date",
        selection.trade_date,
        "--send",
        "--force",
    ]
    if selection.html_path is not None:
        args.extend(["--html-path", str(selection.html_path)])
    if selection.md_path is not None:
        args.extend(["--md-path", str(selection.md_path)])
    if selection.pdf_path is not None:
        args.extend(["--pdf-path", str(selection.pdf_path)])
    if resend:
        args.append("--resend")
    return args


Runner = Callable[..., ActionResult]


def regenerate_report(project_root: Path, trade_date: str, runner: Runner = run_python_script) -> ActionResult:
    report_dir = report_system_dir(Path(project_root))
    args = build_generate_args(trade_date)
    result = run_and_record(
        project_root,
        task_type="report_generate",
        task_name="报告生成",
        target_date=trade_date,
        detail="white",
        fn=lambda: runner(report_dir, report_dir / args[0], args=args[1:], timeout_seconds=600),
    )
    _record_regenerated_report(project_root, trade_date, "white", result)
    return result


def send_current_report(
    project_root: Path,
    selection: ReportSelection | ReportItem,
    resend: bool = True,
    runner: Runner = run_python_script,
) -> ActionResult:
    selection = _selection_from_report(selection)
    missing = missing_report_attachments(selection)
    if missing:
        labels = "、".join(label for label, _path in missing)
        return ActionResult(False, f"当前报告缺少 {labels} 文件，不能发送。", format_report_attachments(selection))

    report_dir = report_system_dir(Path(project_root))
    args = build_send_args(selection, resend=resend)
    result = run_and_record(
        project_root,
        task_type="mail_send",
        task_name="发送当前报告",
        target_date=selection.trade_date,
        detail=selection.report_type,
        fn=lambda: runner(report_dir, report_dir / args[0], args=args[1:], timeout_seconds=300),
    )
    return _with_attachment_output(result, selection)


def delete_report(report: ReportItem) -> ActionResult:
    targets = _unique_existing_or_expected_paths([report.html_path, report.pdf_path, report.md_path])
    deleted: list[Path] = []
    missing: list[Path] = []

    try:
        for path in targets:
            if path.exists():
                path.unlink()
                deleted.append(path)
            else:
                missing.append(path)
        if report.directory.exists() and report.directory.is_dir() and not any(report.directory.iterdir()):
            report.directory.rmdir()
    except OSError as exc:
        output = _format_delete_output(deleted, missing)
        return ActionResult(False, f"删除失败：{exc}", output)

    return ActionResult(True, f"已删除报告：{report.display_name}", _format_delete_output(deleted, missing))


def missing_report_attachments(selection: ReportSelection | ReportItem) -> list[tuple[str, Path]]:
    selection = _selection_from_report(selection)
    attachments = [
        ("HTML", selection.html_path),
        ("PDF", selection.pdf_path),
        ("Markdown", selection.md_path),
    ]
    return [(label, path) for label, path in attachments if path is not None and not path.exists()]


def format_report_attachments(selection: ReportSelection | ReportItem) -> str:
    selection = _selection_from_report(selection)
    lines = ["本次发送使用的附件路径："]
    for label, path in [
        ("HTML", selection.html_path),
        ("PDF", selection.pdf_path),
        ("Markdown", selection.md_path),
    ]:
        if path is None:
            lines.append(f"- {label}: 未指定，由发送脚本自动查找")
        else:
            status = "存在" if path.exists() else "缺失"
            lines.append(f"- {label}: {path}（{status}）")
    return "\n".join(lines)


def _record_regenerated_report(
    project_root: Path,
    trade_date: str,
    report_type: str,
    result: ActionResult,
) -> ActionResult:
    generation_status = GENERATION_STATUS_SUCCESS if result.ok else GENERATION_STATUS_FAILED
    item = _find_report_item(project_root, trade_date, report_type) if result.ok else None
    return record_report_generation(
        project_root,
        trade_date=trade_date,
        report_type=report_type,
        generation_status=generation_status,
        html_path=item.html_path if item else None,
        pdf_path=item.pdf_path if item else None,
        md_path=item.md_path if item else None,
        output=result.output,
        error="" if result.ok else result.message,
    )


def _find_report_item(project_root: Path, trade_date: str, report_type: str) -> ReportItem | None:
    normalized_type = _normalize_report_type(report_type)
    for item in discover_reports(project_root, limit=100):
        if item.trade_date == trade_date and item.report_type == normalized_type:
            return item
    return None


def _report_item_from_dir(trade_date: str, report_type: str, report_dir: Path) -> ReportItem | None:
    files = [path for path in report_dir.iterdir() if path.is_file()]
    html_path = _first_by_suffix(files, ".html")
    pdf_path = _first_by_suffix(files, ".pdf")
    md_path = _first_by_suffix(files, ".md")
    if html_path is None and pdf_path is None and md_path is None:
        return None

    existing = [path for path in (html_path, pdf_path, md_path) if path is not None]
    modified_at = None
    if existing:
        modified_at = datetime.fromtimestamp(max(path.stat().st_mtime for path in existing))

    return ReportItem(
        trade_date=trade_date,
        report_type=_normalize_report_type(report_type),
        label=REPORT_LABELS[_normalize_report_type(report_type)],
        directory=report_dir,
        html_path=html_path or report_dir / "missing.html",
        pdf_path=pdf_path or report_dir / "missing.pdf",
        md_path=md_path or report_dir / "missing.md",
        modified_at=modified_at,
    )


def _first_by_suffix(files: list[Path], suffix: str) -> Path | None:
    matches = sorted((path for path in files if path.suffix.lower() == suffix), key=lambda path: path.name)
    return matches[0] if matches else None


def _report_sort_key(item: ReportItem) -> tuple[str, int, datetime]:
    type_rank = {"white": 2, "daily": 1}.get(item.report_type, 0)
    return (item.trade_date, type_rank, item.modified_at or datetime.min)


def _normalize_report_type(report_type: str) -> str:
    value = str(report_type or "").strip().lower()
    return value if value in SUPPORTED_REPORT_TYPES else "daily"


def _selection_from_report(selection: ReportSelection | ReportItem) -> ReportSelection:
    if isinstance(selection, ReportSelection):
        return selection
    return ReportSelection(
        selection.trade_date,
        selection.report_type,
        html_path=selection.html_path,
        pdf_path=selection.pdf_path,
        md_path=selection.md_path,
    )


def _with_attachment_output(result: ActionResult, selection: ReportSelection) -> ActionResult:
    attachment_output = format_report_attachments(selection)
    output = attachment_output if not result.output else f"{attachment_output}\n\n{result.output}"
    return ActionResult(result.ok, result.message, output)


def _unique_existing_or_expected_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        normalized = Path(path)
        if normalized not in seen:
            unique.append(normalized)
            seen.add(normalized)
    return unique


def _format_delete_output(deleted: list[Path], missing: list[Path]) -> str:
    lines: list[str] = []
    if deleted:
        lines.append("已删除文件：")
        lines.extend(f"- {path}" for path in deleted)
    if missing:
        if lines:
            lines.append("")
        lines.append("原本已不存在：")
        lines.extend(f"- {path}" for path in missing)
    return "\n".join(lines)

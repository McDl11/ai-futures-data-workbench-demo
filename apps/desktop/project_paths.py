from __future__ import annotations

from pathlib import Path


def find_project_root(start: Path) -> Path:
    for path in (Path(start).resolve(), *Path(start).resolve().parents):
        if (path / "AI金融数据工作台进化规划.md").exists():
            return path
        if (path / "apps").exists() and (path / "services").exists() and (path / "data").exists():
            return path
    return Path(start).resolve().parents[1]


def report_system_dir(project_root: Path) -> Path:
    root = Path(project_root)
    preferred = root / "services" / "report_system"
    return preferred if preferred.exists() else root / "futures_report_system"


def data_downloader_dir(project_root: Path) -> Path:
    root = Path(project_root)
    preferred = root / "services" / "data_downloader"
    return preferred if preferred.exists() else root / "tushare down"


def desktop_runtime_dir(project_root: Path) -> Path:
    root = Path(project_root)
    preferred = root / "runtime" / "desktop"
    return preferred if preferred.exists() else root / ".desktop_runtime"

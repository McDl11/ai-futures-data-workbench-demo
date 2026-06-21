from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: str
    output: str = ""


def build_open_command(path: Path) -> tuple[str, Path]:
    return ("startfile", Path(path))


def open_path(path: Path, opener: Callable[[Path], None] | None = None) -> ActionResult:
    target = Path(path)
    if not target.exists():
        return ActionResult(False, f"路径不存在：{target}")

    try:
        if opener is not None:
            opener(target)
        else:
            os.startfile(str(target))  # type: ignore[attr-defined]
    except OSError as exc:
        return ActionResult(False, f"打开失败：{exc}")

    return ActionResult(True, f"已打开：{target}")


def open_parent(path: Path, opener: Callable[[Path], None] | None = None) -> ActionResult:
    target = Path(path)
    parent = target if target.is_dir() else target.parent
    return open_path(parent, opener=opener)


def run_python_script(
    working_dir: Path,
    script_path: Path,
    args: list[str] | None = None,
    timeout_seconds: int = 120,
    env: dict[str, str] | None = None,
) -> ActionResult:
    script = Path(script_path)
    if not script.exists():
        return ActionResult(False, f"脚本不存在：{script}")

    command = [sys.executable, str(script)]
    if args:
        command.extend(args)

    try:
        process_env = None
        if env is not None:
            process_env = os.environ.copy()
            process_env.update(env)
        completed = subprocess.run(
            command,
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=process_env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        return ActionResult(False, f"执行超时：{script.name}", output)
    except OSError as exc:
        return ActionResult(False, f"执行失败：{exc}")

    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    if completed.returncode == 0:
        return ActionResult(True, f"执行完成：{script.name}", output)
    return ActionResult(False, f"执行失败，退出码 {completed.returncode}：{script.name}", output)

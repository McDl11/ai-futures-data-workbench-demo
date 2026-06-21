from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import ctypes
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from desktop.actions import ActionResult, run_python_script
from desktop.project_paths import data_downloader_dir, desktop_runtime_dir, report_system_dir


SCRIPT_ENV = {
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
}


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    name: str
    group: str
    working_dir: Path
    script_name: str
    args: list[str]
    description: str
    timeout_seconds: int = 600
    background: bool = False
    can_stop: bool = False


@dataclass(frozen=True)
class TaskHistoryItem:
    task_id: str
    name: str
    status: str
    message: str
    output: str
    started_at: str
    finished_at: str


@dataclass(frozen=True)
class TaskProcessItem:
    task_id: str
    name: str
    group: str
    script_name: str
    status: str
    pid: int | None
    started_at: str
    log_path: Path | None
    description: str
    background: bool
    can_stop: bool


@dataclass(frozen=True)
class TaskStartResult:
    pid: int
    log_path: Path


Runner = Callable[..., ActionResult]


def task_catalog(project_root: Path) -> list[TaskDefinition]:
    root = Path(project_root)
    report_dir = report_system_dir(root)
    downloader_dir = data_downloader_dir(root)
    return [
        TaskDefinition(
            id="health_check",
            name="运行体检",
            group="检查",
            working_dir=report_dir,
            script_name="health_check.py",
            args=[],
            description="只读取状态并输出体检结果。",
            timeout_seconds=180,
        ),
        TaskDefinition(
            id="auto_report_once_white_dry_run",
            name="白盘报告演练",
            group="报告",
            working_dir=report_dir,
            script_name="auto_report_once.py",
            args=["--report-type", "white", "--no-update", "--allow-latest"],
            description="生成/发送流程演练，不真实发送邮件。",
            timeout_seconds=900,
        ),
        TaskDefinition(
            id="maintenance",
            name="运行维护",
            group="维护",
            working_dir=report_dir,
            script_name="maintenance.py",
            args=[],
            description="运行报告系统维护脚本。",
            timeout_seconds=1200,
        ),
        TaskDefinition(
            id="auto_report_daemon_send",
            name="24小时守护演练",
            group="守护进程",
            working_dir=report_dir,
            script_name="auto_report_daemon.py",
            args=[],
            description="启动 24 小时守护脚本，到点写入 dry-run 记录，不真实发送邮件。",
            background=True,
            can_stop=True,
        ),
    ]


def run_task(project_root: Path, task_id: str, runner: Runner = run_python_script) -> ActionResult:
    task = _find_task(project_root, task_id)
    if task is None:
        return ActionResult(False, f"未知任务：{task_id}")
    if task.background:
        return start_background_task(project_root, task_id)

    started = _now_text()
    result = runner(
        task.working_dir,
        task.working_dir / task.script_name,
        args=task.args,
        timeout_seconds=task.timeout_seconds,
        env=SCRIPT_ENV,
    )
    record_task_result(
        project_root,
        task.id,
        task.name,
        "成功" if result.ok else "失败",
        result.message,
        result.output,
        started_at=started,
    )
    return result


def start_background_task(
    project_root: Path,
    task_id: str,
    starter: Callable[[TaskDefinition, Path], TaskStartResult] | None = None,
    process_checker: Callable[[int], bool] | None = None,
) -> ActionResult:
    task = _find_task(project_root, task_id)
    if task is None:
        return ActionResult(False, f"未知任务：{task_id}")
    if not task.background:
        return ActionResult(False, "该任务不是后台任务。")
    process_checker = process_checker or is_process_running
    pid, _started_at = _read_pid_record(project_root, task_id)
    if pid is not None and process_checker(pid):
        log_path = _task_log_path(project_root, task_id)
        return ActionResult(True, f"{task.name} 正在运行。", f"PID: {pid}\n日志: {_display_path(log_path, project_root)}")

    started = _now_text()
    try:
        result = starter(task, Path(project_root)) if starter else _start_process(task, Path(project_root))
        _pid_path(project_root, task_id).parent.mkdir(parents=True, exist_ok=True)
        _pid_path(project_root, task_id).write_text(str(result.pid), encoding="utf-8")
    except OSError as exc:
        record_task_result(project_root, task.id, task.name, "启动失败", str(exc), "", started_at=started)
        return ActionResult(False, f"启动失败：{exc}")

    output = f"PID: {result.pid}\n日志: {_display_path(result.log_path, project_root)}"
    record_task_result(project_root, task.id, task.name, "已启动", "后台任务已启动。", output, started_at=started)
    return ActionResult(True, "后台任务已启动。", output)


def stop_background_task(
    project_root: Path,
    task_id: str,
    terminator: Callable[[int], ActionResult] | None = None,
) -> ActionResult:
    task = _find_task(project_root, task_id)
    if task is None:
        return ActionResult(False, f"未知任务：{task_id}")
    path = _pid_path(project_root, task_id)
    if not path.exists():
        return ActionResult(False, "未找到该任务的 PID 记录。")
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return ActionResult(False, "PID 记录无效。")

    terminator = terminator or _terminate_process
    result = terminator(pid)
    if result.ok:
        path.unlink(missing_ok=True)
        record_task_result(project_root, task.id, task.name, "已停止", result.message, result.output)
    else:
        record_task_result(project_root, task.id, task.name, "停止失败", result.message, result.output)
    return result


def get_task_processes(
    project_root: Path,
    process_checker: Callable[[int], bool] | None = None,
) -> list[TaskProcessItem]:
    process_checker = process_checker or is_process_running
    items: list[TaskProcessItem] = []
    for task in task_catalog(project_root):
        if not task.background:
            continue
        pid, started_at = _read_pid_record(project_root, task.id)
        log_path = _task_log_path(project_root, task.id) if task.background else None
        if pid is None:
            status = "未启动"
        elif process_checker(pid):
            status = "运行中"
        else:
            status = "异常退出"
        items.append(
            TaskProcessItem(
                task_id=task.id,
                name=task.name,
                group=task.group,
                script_name=task.script_name,
                status=status,
                pid=pid,
                started_at=started_at,
                log_path=log_path,
                description=task.description,
                background=task.background,
                can_stop=task.can_stop,
            )
        )
    return items


def record_task_result(
    project_root: Path,
    task_id: str,
    name: str,
    status: str,
    message: str,
    output: str = "",
    started_at: str | None = None,
) -> None:
    item = TaskHistoryItem(
        task_id=task_id,
        name=name,
        status=status,
        message=message,
        output=output,
        started_at=started_at or _now_text(),
        finished_at=_now_text(),
    )
    history = [item] + load_task_history(project_root)
    history = history[:100]
    path = _history_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(entry) for entry in history], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_task_history(project_root: Path) -> list[TaskHistoryItem]:
    path = _history_path(project_root)
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [TaskHistoryItem(**row) for row in rows if isinstance(row, dict)]


def _find_task(project_root: Path, task_id: str) -> TaskDefinition | None:
    return next((task for task in task_catalog(project_root) if task.id == task_id), None)


def _start_process(task: TaskDefinition, project_root: Path) -> TaskStartResult:
    runtime_dir = _runtime_dir(project_root)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = _task_log_path(project_root, task.id)
    out = log_path.open("a", encoding="utf-8")
    command = [sys.executable, str(task.working_dir / task.script_name), *task.args]
    env = os.environ.copy()
    env.update(SCRIPT_ENV)
    process = subprocess.Popen(
        command,
        cwd=str(task.working_dir),
        stdout=out,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    return TaskStartResult(pid=process.pid, log_path=log_path)


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_running(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _windows_process_running(pid: int) -> bool:
    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _terminate_process(pid: int) -> ActionResult:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        return ActionResult(False, f"停止失败：{exc}")
    return ActionResult(True, f"已发送停止信号：PID {pid}")


def _runtime_dir(project_root: Path) -> Path:
    return desktop_runtime_dir(Path(project_root))


def _history_path(project_root: Path) -> Path:
    return _runtime_dir(project_root) / "task_history.json"


def _pid_path(project_root: Path, task_id: str) -> Path:
    return _runtime_dir(project_root) / f"{task_id}.pid"


def _task_log_path(project_root: Path, task_id: str) -> Path:
    return _runtime_dir(project_root) / f"{task_id}.log"


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return str(Path(path).relative_to(Path(project_root)))
    except ValueError:
        return str(path)


def _read_pid_record(project_root: Path, task_id: str) -> tuple[int | None, str]:
    path = _pid_path(project_root, task_id)
    if not path.exists():
        return None, ""
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None, ""
    modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return pid, modified


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

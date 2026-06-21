from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from desktop.actions import ActionResult


class Worker(QObject):
    finished = Signal(object)

    def __init__(self, fn: Callable[[], ActionResult]) -> None:
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:
            result = ActionResult(False, f"执行失败：{exc}")
        self.finished.emit(result)


class BackgroundTask(QObject):
    done = Signal()

    def __init__(self, fn: Callable[[], ActionResult], on_finished: Callable[[ActionResult], Any]) -> None:
        super().__init__()
        self.thread = QThread()
        self.worker = Worker(fn)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.done.emit)

    def start(self) -> None:
        self.thread.start()

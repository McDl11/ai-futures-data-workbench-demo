from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from desktop.ai_assistant import answer_question
from desktop.pages.base import ScrollPage
from desktop.state import WorkspaceSnapshot
from desktop.widgets import Section, make_title


class AiAssistantPage(ScrollPage):
    def __init__(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        self.question_input: QLineEdit | None = None
        self.answer_box: QTextEdit | None = None
        self.sources_box: QTextEdit | None = None
        super().__init__(snapshot)

    def update_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        super().update_snapshot(snapshot)

    def build(self, snapshot: WorkspaceSnapshot) -> None:
        self.layout.addWidget(
            make_title(
                "AI 助手",
                "只读模式：读取结构化记录、报告记录、邮件记录和日志，帮你解释当前工作台状态。",
            )
        )

        ask_section = Section("问工作台", "它不会执行发送、更新、删除、停止等操作；需要操作时会提示你去对应中心确认。")
        ask_section.add(self._build_question_row())
        ask_section.add(self._build_quick_questions())
        self.layout.addWidget(ask_section)

        answer_section = Section("回答")
        self.answer_box = QTextEdit()
        self.answer_box.setReadOnly(True)
        self.answer_box.setMinimumHeight(260)
        self.answer_box.setPlaceholderText("输入问题后点击“询问”。")
        answer_section.add(self.answer_box)
        self.layout.addWidget(answer_section)

        sources_section = Section("读取来源")
        self.sources_box = QTextEdit()
        self.sources_box.setReadOnly(True)
        self.sources_box.setMinimumHeight(90)
        self.sources_box.setPlaceholderText("回答使用到的 SQLite 表或日志路径会显示在这里。")
        sources_section.add(self.sources_box)
        self.layout.addWidget(sources_section)

    def _build_question_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.question_input = QLineEdit()
        self.question_input.setPlaceholderText("例如：最近为什么失败？邮件发送成功了吗？报告质检怎么样？")
        self.question_input.returnPressed.connect(self.ask)
        layout.addWidget(self.question_input, 1)

        ask_button = QPushButton("询问")
        ask_button.setObjectName("PrimaryButton")
        ask_button.clicked.connect(self.ask)
        layout.addWidget(ask_button)
        return row

    def _build_quick_questions(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        label = QLabel("快捷问题")
        label.setObjectName("MutedText")
        layout.addWidget(label)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        for text in [
            "最近为什么失败？",
            "报告质检怎么样？",
            "邮件发送失败原因是什么？",
            "最近任务运行情况？",
        ]:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, value=text: self.ask(value))
            row_layout.addWidget(button)
        row_layout.addStretch(1)
        layout.addWidget(row)
        return container

    def ask(self, question: str | None = None) -> None:
        text = question if isinstance(question, str) else ""
        if not text and self.question_input is not None:
            text = self.question_input.text()
        text = text.strip()
        if not text:
            text = "最近工作台状态怎么样？"
        if self.question_input is not None:
            self.question_input.setText(text)

        answer = answer_question(self.snapshot.project_root, text)
        if self.answer_box is not None:
            self.answer_box.setPlainText(answer.text)
        if self.sources_box is not None:
            self.sources_box.setPlainText("\n".join(answer.sources) if answer.sources else "未读取外部来源。")

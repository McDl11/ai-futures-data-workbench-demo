from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from desktop.actions import ActionResult
from desktop.mail_center import (
    MailAccountConfig,
    MailRecipient,
    MailSendRecord,
    add_mail_recipient,
    delete_mail_recipient,
    load_mail_account_config,
    load_mail_recipients,
    load_mail_send_records,
    resend_mail_record,
    send_selected_report,
    update_mail_recipient,
)
from desktop.pages.base import ScrollPage
from desktop.state import WorkspaceSnapshot, collect_workspace_snapshot
from desktop.widgets import Section, make_title
from desktop.workers import BackgroundTask


class MailCenterPage(ScrollPage):
    def __init__(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        self.account = MailAccountConfig()
        self.recipients: list[MailRecipient] = []
        self.visible_recipients: list[MailRecipient] = []
        self.records: list[MailSendRecord] = []
        self.active_task: BackgroundTask | None = None
        self.search_input: QLineEdit | None = None
        self.recipients_table: QTableWidget | None = None
        self.records_table: QTableWidget | None = None
        self.date_input: QLineEdit | None = None
        self.pdf_checkbox: QCheckBox | None = None
        self.html_checkbox: QCheckBox | None = None
        self.md_checkbox: QCheckBox | None = None
        self.output_box: QTextEdit | None = None
        self.last_output = ""
        super().__init__(snapshot)

    def update_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        super().update_snapshot(snapshot)

    def build(self, snapshot: WorkspaceSnapshot) -> None:
        self.account = load_mail_account_config(snapshot.project_root)
        self.recipients = load_mail_recipients(snapshot.project_root)
        self.visible_recipients = list(self.recipients)
        self.records = load_mail_send_records(snapshot.project_root)

        self.layout.addWidget(
            make_title(
                "邮件中心",
                "管理收件人、报告附件和发送记录；发件账号请在配置中心维护。",
            )
        )

        splitter = QSplitter(Qt.Vertical)
        splitter.setObjectName("MailCenterSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(13)

        recipients_section = Section("收件人管理")
        recipients_section.add(self._build_recipient_tools())
        self.recipients_table = self._build_recipients_table(self.visible_recipients)
        recipients_section.add(self.recipients_table)
        top_layout.addWidget(recipients_section)

        send_section = Section("发送邮件", "先选中一个或多个收件人，再选择报告日期和附件内容。")
        send_section.add(self._build_send_controls(snapshot))
        top_layout.addWidget(send_section)

        records = Section("发送记录", "查看成功/失败和失败原因；历史失败记录可选中后重发。")
        self.records_table = self._build_records_table(self.records)
        records.add(self.records_table)
        records.add(self._build_record_actions())
        top_layout.addWidget(records)
        top_layout.addStretch(1)

        output = Section("执行输出")
        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setMinimumHeight(120)
        self.output_box.setPlaceholderText("保存配置、发送或重发的输出会显示在这里。")
        if self.last_output:
            self.output_box.setPlainText(self.last_output)
        output.add(self.output_box)
        output.setMinimumHeight(170)

        splitter.addWidget(top)
        splitter.addWidget(output)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([760, 240])
        self.layout.addWidget(splitter)

    def _build_recipient_tools(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索邮箱、姓名、备注")
        self.search_input.textChanged.connect(self.apply_recipient_filter)
        layout.addWidget(self.search_input, 1)

        add_button = QPushButton("新增收件人")
        add_button.setObjectName("PrimaryButton")
        add_button.clicked.connect(self.add_recipient)
        layout.addWidget(add_button)

        edit_button = QPushButton("修改选中")
        edit_button.clicked.connect(self.edit_selected_recipient)
        layout.addWidget(edit_button)

        toggle_button = QPushButton("启用/停用")
        toggle_button.clicked.connect(self.toggle_selected_recipient)
        layout.addWidget(toggle_button)

        delete_button = QPushButton("删除选中")
        delete_button.setObjectName("DangerButton")
        delete_button.clicked.connect(self.delete_selected_recipient)
        layout.addWidget(delete_button)
        return row

    def _build_recipients_table(self, recipients: list[MailRecipient]) -> QTableWidget:
        table = QTableWidget()
        table.setObjectName("ReportTable")
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["邮箱", "姓名", "状态", "备注"])
        table.setRowCount(len(recipients))
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.ExtendedSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setMinimumHeight(180)

        for row, recipient in enumerate(recipients):
            values = [
                recipient.email,
                recipient.name or "-",
                "启用" if recipient.enabled else "停用",
                recipient.remark or "-",
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, recipient.email)
                table.setItem(row, col, cell)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        if recipients:
            table.selectRow(0)
        return table

    def _build_send_controls(self, snapshot: WorkspaceSnapshot) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.date_input = QLineEdit(snapshot.latest_trade_date or "")
        self.date_input.setPlaceholderText("YYYYMMDD")
        self.date_input.setMaximumWidth(120)
        layout.addWidget(QLabel("日期"))
        layout.addWidget(self.date_input)

        layout.addWidget(QLabel("报告"))
        report_label = QLabel("白盘")
        report_label.setObjectName("MutedText")
        layout.addWidget(report_label)

        self.pdf_checkbox = QCheckBox("PDF")
        self.pdf_checkbox.setChecked(True)
        self.html_checkbox = QCheckBox("HTML")
        self.html_checkbox.setChecked(True)
        self.md_checkbox = QCheckBox("Markdown")
        self.md_checkbox.setChecked(True)
        layout.addWidget(self.pdf_checkbox)
        layout.addWidget(self.html_checkbox)
        layout.addWidget(self.md_checkbox)

        send_button = QPushButton("发送给选中收件人")
        send_button.setObjectName("PrimaryButton")
        send_button.clicked.connect(self.confirm_and_send_selected_recipients)
        layout.addWidget(send_button)

        layout.addStretch(1)
        return row

    def _build_records_table(self, records: list[MailSendRecord]) -> QTableWidget:
        table = QTableWidget()
        table.setObjectName("ReportTable")
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels(["时间", "日期", "报告", "收件人", "状态", "失败原因", "范围"])
        table.setRowCount(len(records))
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(True)
        table.verticalHeader().setVisible(False)
        table.setMinimumHeight(240)

        for row, record in enumerate(records):
            values = [
                record.sent_at,
                record.trade_date,
                self._report_type_text(record.report_type),
                record.target,
                self._status_text(record.status),
                record.failure_reason if record.status in ("failed", "partial_failed") else "-",
                "单个收件人" if record.scope == "recipient" else "整批",
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, row)
                table.setItem(row, col, cell)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        table.resizeRowsToContents()
        if records:
            table.selectRow(0)
        return table

    def _build_record_actions(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        resend_button = QPushButton("重发选中记录")
        resend_button.clicked.connect(self.confirm_and_resend_selected_record)
        layout.addWidget(resend_button)

        refresh_button = QPushButton("刷新记录")
        refresh_button.clicked.connect(self.refresh_mail_status)
        layout.addWidget(refresh_button)

        layout.addStretch(1)
        return row

    def add_recipient(self) -> None:
        dialog = RecipientDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        result = add_mail_recipient(self.snapshot.project_root, dialog.recipient())
        self.show_result(result)
        self.update_snapshot(collect_workspace_snapshot(self.snapshot.project_root))

    def edit_selected_recipient(self) -> None:
        recipient = self.selected_recipient()
        if recipient is None:
            self.show_result(ActionResult(False, "请先选中一个收件人。"))
            return
        dialog = RecipientDialog(self, recipient)
        if dialog.exec() != QDialog.Accepted:
            return
        result = update_mail_recipient(self.snapshot.project_root, recipient.email, dialog.recipient())
        self.show_result(result)
        self.update_snapshot(collect_workspace_snapshot(self.snapshot.project_root))

    def toggle_selected_recipient(self) -> None:
        recipient = self.selected_recipient()
        if recipient is None:
            self.show_result(ActionResult(False, "请先选中一个收件人。"))
            return
        updated = MailRecipient(recipient.email, recipient.name, not recipient.enabled, recipient.remark)
        result = update_mail_recipient(self.snapshot.project_root, recipient.email, updated)
        self.show_result(result)
        self.update_snapshot(collect_workspace_snapshot(self.snapshot.project_root))

    def delete_selected_recipient(self) -> None:
        recipient = self.selected_recipient()
        if recipient is None:
            self.show_result(ActionResult(False, "请先选中一个收件人。"))
            return
        answer = QMessageBox.question(
            self,
            "确认删除",
            f"确认删除收件人 {recipient.email}？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.show_result(ActionResult(False, "已取消删除。"))
            return
        result = delete_mail_recipient(self.snapshot.project_root, recipient.email)
        self.show_result(result)
        self.update_snapshot(collect_workspace_snapshot(self.snapshot.project_root))

    def apply_recipient_filter(self) -> None:
        if self.search_input is None:
            return
        keyword = self.search_input.text().strip().lower()
        if not keyword:
            self.visible_recipients = list(self.recipients)
        else:
            self.visible_recipients = [
                item
                for item in self.recipients
                if keyword in item.email.lower()
                or keyword in item.name.lower()
                or keyword in item.remark.lower()
            ]
        if self.recipients_table is not None:
            replacement = self._build_recipients_table(self.visible_recipients)
            parent = self.recipients_table.parentWidget()
            layout = parent.layout() if parent is not None else None
            if layout is not None:
                index = layout.indexOf(self.recipients_table)
                layout.removeWidget(self.recipients_table)
                self.recipients_table.deleteLater()
                layout.insertWidget(index, replacement)
                self.recipients_table = replacement

    def selected_recipient(self) -> MailRecipient | None:
        selected = self.selected_recipients()
        return selected[0] if selected else None

    def selected_recipients(self) -> list[MailRecipient]:
        if self.recipients_table is None:
            return []
        rows = sorted({item.row() for item in self.recipients_table.selectedItems()})
        return [
            self.visible_recipients[row]
            for row in rows
            if 0 <= row < len(self.visible_recipients)
        ]

    def selected_record(self) -> MailSendRecord | None:
        if self.records_table is None:
            return None
        row = self.records_table.currentRow()
        if row < 0 or row >= len(self.records):
            return None
        return self.records[row]

    def selected_attachment_types(self) -> list[str]:
        selected = []
        if self.pdf_checkbox is not None and self.pdf_checkbox.isChecked():
            selected.append("pdf")
        if self.html_checkbox is not None and self.html_checkbox.isChecked():
            selected.append("html")
        if self.md_checkbox is not None and self.md_checkbox.isChecked():
            selected.append("md")
        return selected

    def confirm_and_send_selected_recipients(self) -> None:
        recipients = [item for item in self.selected_recipients() if item.enabled]
        if not recipients:
            self.show_result(ActionResult(False, "请先选中至少一个启用收件人。"))
            return
        if self.date_input is None:
            return
        attachments = self.selected_attachment_types()
        if not attachments:
            self.show_result(ActionResult(False, "请至少选择一种发送内容。"))
            return
        trade_date = self.date_input.text().strip()
        report_type = "white"
        addresses = [item.email for item in recipients]
        cc = self.account.cc.strip()

        answer = QMessageBox.question(
            self,
            "确认发送",
            (
                f"发件邮箱：{self.account.sender or '未配置'}\n"
                f"收件人：{', '.join(addresses)}\n"
                f"报告日期：{trade_date}\n"
                f"报告类型：{self._report_type_text(report_type)}\n"
                f"附件内容：{', '.join(attachments)}\n\n"
                "确认后会真实发送邮件。"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.show_result(ActionResult(False, "已取消发送。"))
            return
        self.run_background(
            f"正在发送邮件：{trade_date} -> {len(addresses)} 个收件人，请稍候...",
            lambda: send_selected_report(
                self.snapshot.project_root,
                trade_date=trade_date,
                report_type=report_type,
                recipients=addresses,
                attachments=attachments,
                cc=cc,
                confirmed=True,
            ),
        )

    def confirm_and_resend_selected_record(self) -> None:
        record = self.selected_record()
        if record is None:
            self.show_result(ActionResult(False, "请先选中一条发送记录。"))
            return
        answer = QMessageBox.question(
            self,
            "确认重发",
            (
                f"确认重发 {record.trade_date} {self._report_type_text(record.report_type)}？\n\n"
                f"收件人：{record.target}\n\n"
                "这会真实发送邮件。"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.show_result(ActionResult(False, "已取消重发。"))
            return
        self.run_background(
            f"正在重发邮件：{record.trade_date} {record.target}，请稍候...",
            lambda: resend_mail_record(self.snapshot.project_root, record),
        )

    def refresh_mail_status(self) -> None:
        self.show_result(ActionResult(True, "已刷新邮件记录。"))
        self.update_snapshot(collect_workspace_snapshot(self.snapshot.project_root))

    def run_background(self, start_message: str, fn) -> None:
        if self.active_task is not None:
            self.show_result(ActionResult(False, "已有任务正在运行，请稍候。"))
            return
        self.show_result(ActionResult(True, start_message))
        self.active_task = BackgroundTask(fn, self.on_background_finished)
        self.active_task.done.connect(self.clear_active_task)
        self.active_task.start()

    def on_background_finished(self, result: ActionResult) -> None:
        self.show_result(result)
        self.update_snapshot(collect_workspace_snapshot(self.snapshot.project_root))

    def clear_active_task(self) -> None:
        self.active_task = None

    def show_result(self, result: ActionResult) -> None:
        output = result.output.strip()
        self.last_output = result.message if not output else f"{result.message}\n\n{output}"
        if self.output_box is not None:
            self.output_box.setPlainText(self.last_output)

    def _report_type_text(self, report_type: str) -> str:
        return {
            "white": "白盘",
            "daily": "日报",
            "morning": "早报",
        }.get(report_type, report_type)

    def _status_text(self, status: str) -> str:
        return {
            "sent": "已发送",
            "dry_run": "演练",
            "skipped_duplicate": "已跳过重复",
            "failed": "失败",
            "partial_failed": "部分失败",
        }.get(status, status)


class RecipientDialog(QDialog):
    def __init__(self, parent: QWidget, recipient: MailRecipient | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("收件人")
        self.email_input = QLineEdit(recipient.email if recipient else "")
        self.name_input = QLineEdit(recipient.name if recipient else "")
        self.enabled_checkbox = QCheckBox("启用")
        self.enabled_checkbox.setChecked(True if recipient is None else recipient.enabled)
        self.remark_input = QLineEdit(recipient.remark if recipient else "")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("邮箱", self.email_input)
        form.addRow("姓名", self.name_input)
        form.addRow("", self.enabled_checkbox)
        form.addRow("备注", self.remark_input)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok_button = QPushButton("确定")
        ok_button.setObjectName("PrimaryButton")
        ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(ok_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

    def recipient(self) -> MailRecipient:
        return MailRecipient(
            email=self.email_input.text().strip(),
            name=self.name_input.text().strip(),
            enabled=self.enabled_checkbox.isChecked(),
            remark=self.remark_input.text().strip(),
        )

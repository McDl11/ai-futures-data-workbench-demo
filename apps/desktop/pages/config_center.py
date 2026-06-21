from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from desktop.actions import ActionResult
from desktop.config_center import CommonConfig, load_common_config, save_common_config
from desktop.pages.base import ScrollPage
from desktop.state import FileItem, WorkspaceSnapshot, collect_workspace_snapshot
from desktop.widgets import FileActions, Section, file_list, make_title


class ManualSpinBox(QSpinBox):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


class ConfigCenterPage(ScrollPage):
    def __init__(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        self.config = CommonConfig()
        self.sender_input: QLineEdit | None = None
        self.email_password_input: QLineEdit | None = None
        self.smtp_host_input: QLineEdit | None = None
        self.smtp_port_input: QSpinBox | None = None
        self.smtp_ssl_checkbox: QCheckBox | None = None
        self.report_cc_input: QLineEdit | None = None
        self.dry_run_checkbox: QCheckBox | None = None
        self.batch_interval_input: QSpinBox | None = None
        self.attachment_size_input: QSpinBox | None = None
        self.tushare_token_input: QLineEdit | None = None
        self.tushare_http_url_input: QLineEdit | None = None
        self.futures_data_dir_input: QLineEdit | None = None
        self.backup_dir_input: QLineEdit | None = None
        self.db_backup_keep_input: QSpinBox | None = None
        self.log_keep_input: QSpinBox | None = None
        self.report_keep_input: QSpinBox | None = None
        self.ai_enabled_checkbox: QCheckBox | None = None
        self.ai_assistant_commercial_checkbox: QCheckBox | None = None
        self.deepseek_key_input: QLineEdit | None = None
        self.deepseek_base_input: QLineEdit | None = None
        self.deepseek_model_input: QLineEdit | None = None
        self.ai_timeout_input: QSpinBox | None = None
        self.ai_tokens_input: QSpinBox | None = None
        self.output_box: QTextEdit | None = None
        self.last_output = ""
        super().__init__(snapshot)

    def update_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        super().update_snapshot(snapshot)

    def build(self, snapshot: WorkspaceSnapshot) -> None:
        self.config = load_common_config(snapshot.project_root)

        self.layout.addWidget(
            make_title(
                "配置中心",
                "管理常用 .env 配置；SMTP 授权码和 API Key 留空保存时会保留原值。",
            )
        )

        form_area = QWidget()
        form_layout = QVBoxLayout(form_area)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(13)
        form_layout.addWidget(self._build_mail_section())
        form_layout.addWidget(self._build_data_source_section())
        form_layout.addWidget(self._build_retention_section())
        form_layout.addWidget(self._build_path_section())
        form_layout.addWidget(self._build_ai_section())
        form_layout.addWidget(self._build_save_actions())
        self.layout.addWidget(form_area)

        existing_items = [
            FileItem(path=config.path, modified_at=None, size_bytes=config.size_bytes)
            for config in snapshot.config_files
            if config.exists
        ]
        config_list = Section("打开配置文件")
        listing = file_list(existing_items, "未发现可打开的配置文件")
        action_status = QLabel("选中一个配置文件后可以打开文件或所在目录。")
        action_status.setObjectName("MutedText")
        config_list.add(listing)
        config_list.add(FileActions(listing, action_status))
        config_list.add(action_status)
        self.layout.addWidget(config_list)

        output = Section("执行输出")
        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setMinimumHeight(110)
        self.output_box.setPlaceholderText("保存配置的结果会显示在这里。")
        if self.last_output:
            self.output_box.setPlainText(self.last_output)
        output.add(self.output_box)
        self.layout.addWidget(output)

    def _build_mail_section(self) -> Section:
        section = Section("邮件发送", "管理发件账号和发送安全开关；收件人仍在邮件中心管理。")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.sender_input = QLineEdit(self.config.sender)
        self.sender_input.setPlaceholderText("your-email@example.com")
        form.addRow("发件邮箱", self.sender_input)

        self.email_password_input = QLineEdit()
        self.email_password_input.setEchoMode(QLineEdit.Password)
        self.email_password_input.setPlaceholderText(
            "已配置，留空则不修改" if self.config.has_email_password else "请输入 SMTP 授权码"
        )
        form.addRow("SMTP 授权码", self.email_password_input)

        self.smtp_host_input = QLineEdit(self.config.smtp_host)
        form.addRow("SMTP 服务器", self.smtp_host_input)

        self.smtp_port_input = self._spin(1, 65535, self.config.smtp_port)
        form.addRow("端口", self.smtp_port_input)

        self.smtp_ssl_checkbox = QCheckBox("使用 SSL")
        self.smtp_ssl_checkbox.setChecked(self.config.smtp_use_ssl)
        form.addRow("", self.smtp_ssl_checkbox)

        self.dry_run_checkbox = QCheckBox("只演练，不真实发送")
        self.dry_run_checkbox.setChecked(self.config.report_email_dry_run)
        form.addRow("", self.dry_run_checkbox)

        self.report_cc_input = QLineEdit(self.config.report_cc)
        form.addRow("默认抄送", self.report_cc_input)

        self.batch_interval_input = self._spin(0, 3600, self.config.report_email_batch_interval_seconds)
        form.addRow("批量间隔秒", self.batch_interval_input)

        self.attachment_size_input = self._spin(0, 200 * 1024 * 1024, self.config.report_max_attachment_size)
        form.addRow("附件上限字节", self.attachment_size_input)

        section.add(self._wrap_form(form))
        return section

    def _build_data_source_section(self) -> Section:
        section = Section("数据源接入", "管理 Tushare 下载器配置；Token 留空保存时会保留原值，HTTP 地址可留空。")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.tushare_token_input = QLineEdit()
        self.tushare_token_input.setEchoMode(QLineEdit.Password)
        self.tushare_token_input.setPlaceholderText(
            "已配置，留空则不修改" if self.config.has_tushare_token else "请输入 Tushare Token"
        )
        form.addRow("Tushare Token", self.tushare_token_input)

        self.tushare_http_url_input = QLineEdit(self.config.tushare_http_url)
        self.tushare_http_url_input.setPlaceholderText("可留空；使用自定义 Tushare 接口时填写")
        form.addRow("Tushare HTTP 地址", self.tushare_http_url_input)

        section.add(self._wrap_form(form))
        return section

    def _build_retention_section(self) -> Section:
        section = Section("保留策略", "控制报告、日志和数据库备份保留多久。")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.db_backup_keep_input = self._spin(0, 3650, self.config.db_backup_keep_days)
        form.addRow("数据库备份保留天数", self.db_backup_keep_input)

        self.log_keep_input = self._spin(0, 3650, self.config.log_keep_days)
        form.addRow("日志保留天数", self.log_keep_input)

        self.report_keep_input = self._spin(0, 3650, self.config.report_keep_days)
        form.addRow("报告保留天数", self.report_keep_input)

        section.add(self._wrap_form(form))
        return section

    def _build_path_section(self) -> Section:
        section = Section("路径配置", "常用路径可在这里调整；数据库实际文件仍会在数据中心展示。")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.futures_data_dir_input = QLineEdit(self.config.futures_data_dir)
        form.addRow("数据目录", self.futures_data_dir_input)

        self.backup_dir_input = QLineEdit(self.config.backup_dir)
        form.addRow("备份目录", self.backup_dir_input)

        section.add(self._wrap_form(form))
        return section

    def _build_ai_section(self) -> Section:
        section = Section("AI 分析", "高级配置；未启用时不会调用 AI 接口。")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.ai_enabled_checkbox = QCheckBox("启用 AI 分析")
        self.ai_enabled_checkbox.setChecked(self.config.ai_analysis_enabled)
        form.addRow("", self.ai_enabled_checkbox)

        self.ai_assistant_commercial_checkbox = QCheckBox("AI 助手使用商业 AI")
        self.ai_assistant_commercial_checkbox.setChecked(self.config.ai_assistant_use_commercial_ai)
        form.addRow("", self.ai_assistant_commercial_checkbox)

        self.deepseek_key_input = QLineEdit()
        self.deepseek_key_input.setEchoMode(QLineEdit.Password)
        self.deepseek_key_input.setPlaceholderText(
            "已配置，留空则不修改" if self.config.has_deepseek_api_key else "请输入 DeepSeek API Key"
        )
        form.addRow("DeepSeek API Key", self.deepseek_key_input)

        self.deepseek_base_input = QLineEdit(self.config.deepseek_api_base)
        form.addRow("API 地址", self.deepseek_base_input)

        self.deepseek_model_input = QLineEdit(self.config.deepseek_model)
        form.addRow("模型名", self.deepseek_model_input)

        self.ai_timeout_input = self._spin(1, 3600, self.config.ai_analysis_timeout_seconds)
        form.addRow("超时秒数", self.ai_timeout_input)

        self.ai_tokens_input = self._spin(1, 200_000, self.config.ai_analysis_max_tokens)
        form.addRow("最大 Tokens", self.ai_tokens_input)

        section.add(self._wrap_form(form))
        return section

    def _build_save_actions(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        save_button = QPushButton("保存配置")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self.save_config)
        layout.addWidget(save_button)

        refresh_button = QPushButton("重新读取")
        refresh_button.clicked.connect(lambda: self.update_snapshot(collect_workspace_snapshot(self.snapshot.project_root)))
        layout.addWidget(refresh_button)
        layout.addStretch(1)
        return row

    def save_config(self) -> None:
        if not self._form_ready():
            return
        config = CommonConfig(
            sender=self.sender_input.text(),
            email_password=self.email_password_input.text(),
            smtp_host=self.smtp_host_input.text(),
            smtp_port=self.smtp_port_input.value(),
            smtp_use_ssl=self.smtp_ssl_checkbox.isChecked(),
            report_cc=self.report_cc_input.text(),
            report_email_dry_run=self.dry_run_checkbox.isChecked(),
            report_email_batch_interval_seconds=self.batch_interval_input.value(),
            report_max_attachment_size=self.attachment_size_input.value(),
            tushare_token=self.tushare_token_input.text(),
            tushare_http_url=self.tushare_http_url_input.text(),
            futures_data_dir=self.futures_data_dir_input.text(),
            backup_dir=self.backup_dir_input.text(),
            db_backup_keep_days=self.db_backup_keep_input.value(),
            log_keep_days=self.log_keep_input.value(),
            report_keep_days=self.report_keep_input.value(),
            ai_analysis_enabled=self.ai_enabled_checkbox.isChecked(),
            ai_assistant_use_commercial_ai=self.ai_assistant_commercial_checkbox.isChecked(),
            deepseek_api_key=self.deepseek_key_input.text(),
            deepseek_api_base=self.deepseek_base_input.text(),
            deepseek_model=self.deepseek_model_input.text(),
            ai_analysis_timeout_seconds=self.ai_timeout_input.value(),
            ai_analysis_max_tokens=self.ai_tokens_input.value(),
            has_email_password=self.config.has_email_password,
            has_deepseek_api_key=self.config.has_deepseek_api_key,
            has_tushare_token=self.config.has_tushare_token,
        )
        self.show_result(save_common_config(self.snapshot.project_root, config))
        self.update_snapshot(collect_workspace_snapshot(self.snapshot.project_root))

    def show_result(self, result: ActionResult) -> None:
        output = result.output.strip()
        self.last_output = result.message if not output else f"{result.message}\n\n{output}"
        if self.output_box is not None:
            self.output_box.setPlainText(self.last_output)

    def _form_ready(self) -> bool:
        required = [
            self.sender_input,
            self.email_password_input,
            self.smtp_host_input,
            self.smtp_port_input,
            self.smtp_ssl_checkbox,
            self.report_cc_input,
            self.dry_run_checkbox,
            self.batch_interval_input,
            self.attachment_size_input,
            self.tushare_token_input,
            self.tushare_http_url_input,
            self.futures_data_dir_input,
            self.backup_dir_input,
            self.db_backup_keep_input,
            self.log_keep_input,
            self.report_keep_input,
            self.ai_enabled_checkbox,
            self.ai_assistant_commercial_checkbox,
            self.deepseek_key_input,
            self.deepseek_base_input,
            self.deepseek_model_input,
            self.ai_timeout_input,
            self.ai_tokens_input,
        ]
        return all(item is not None for item in required)

    def _spin(self, minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = ManualSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def _wrap_form(self, form: QFormLayout) -> QWidget:
        box = QWidget()
        box.setLayout(form)
        return box

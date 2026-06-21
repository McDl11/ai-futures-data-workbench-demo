from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop.pages.ai_assistant import AiAssistantPage
from desktop.pages.config_center import ConfigCenterPage
from desktop.pages.data_center import DataCenterPage
from desktop.pages.home import HomePage
from desktop.pages.log_center import LogCenterPage
from desktop.pages.mail_center import MailCenterPage
from desktop.pages.report_center import ReportCenterPage
from desktop.pages.system_center import SystemCenterPage
from desktop.pages.task_center import TaskCenterPage
from desktop.state import collect_workspace_snapshot
from desktop.theme import build_stylesheet, detect_theme_mode, theme_tokens
from desktop.widgets import format_datetime


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.theme_mode = detect_theme_mode()
        self.tokens = theme_tokens(self.theme_mode)
        self.setWindowTitle("AI 期货数据工作台")
        self.resize(1220, 780)

        self.snapshot = collect_workspace_snapshot()
        self.nav_buttons: list[QPushButton] = []
        self.pages: list[QWidget] = []

        self._build_ui()
        self._apply_styles()
        self._update_header()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        root_layout.addWidget(self._build_sidebar())
        root_layout.addWidget(self._build_content(), 1)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(204)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 18, 16, 18)
        layout.setSpacing(8)

        layout.addWidget(self._build_brand())

        nav_items = [
            ("首页", HomePage),
            ("系统中心", SystemCenterPage),
            ("数据中心", DataCenterPage),
            ("报告中心", ReportCenterPage),
            ("邮件中心", MailCenterPage),
            ("任务中心", TaskCenterPage),
            ("AI 助手", AiAssistantPage),
            ("日志中心", LogCenterPage),
            ("配置中心", ConfigCenterPage),
        ]

        layout.addSpacing(18)
        for index, (label, page_cls) in enumerate(nav_items):
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, page_index=index: self.set_page(page_index))
            self.nav_buttons.append(button)
            layout.addWidget(button)

            page = page_cls(self.snapshot)
            self.pages.append(page)

        layout.addStretch(1)

        footer = QLabel("AI Futures Data Workbench · Demo")
        footer.setObjectName("SidebarFooter")
        layout.addWidget(footer)

        self.nav_buttons[0].setChecked(True)
        return sidebar

    def _build_brand(self) -> QWidget:
        brand_row = QWidget()
        brand_layout = QHBoxLayout(brand_row)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(10)

        brand_mark = QLabel("AI")
        brand_mark.setObjectName("BrandMark")
        brand_mark.setFixedSize(38, 38)
        brand_mark.setAlignment(Qt.AlignCenter)
        brand_layout.addWidget(brand_mark)

        brand_text = QWidget()
        brand_text_layout = QVBoxLayout(brand_text)
        brand_text_layout.setContentsMargins(0, 0, 0, 0)
        brand_text_layout.setSpacing(1)

        brand_title = QLabel("期货工作台")
        brand_title.setObjectName("BrandTitle")
        brand_text_layout.addWidget(brand_title)

        brand_subtitle = QLabel("本地数据中枢")
        brand_subtitle.setObjectName("BrandSubtitle")
        brand_text_layout.addWidget(brand_subtitle)

        brand_layout.addWidget(brand_text, 1)
        return brand_row

    def _build_content(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("Header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(26, 16, 26, 16)
        header_layout.setSpacing(12)

        title_group = QWidget()
        title_layout = QVBoxLayout(title_group)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)

        title = QLabel("本地金融数据自动化工作台")
        title.setObjectName("HeaderTitle")
        title_layout.addWidget(title)

        self.header_status = QLabel("")
        self.header_status.setObjectName("HeaderStatus")
        title_layout.addWidget(self.header_status)
        header_layout.addWidget(title_group, 1)

        self.theme_label = QLabel(f"跟随 Windows · {self.theme_mode.value}")
        self.theme_label.setObjectName("ThemePill")
        header_layout.addWidget(self.theme_label)

        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setObjectName("PrimaryButton")
        self.refresh_button.clicked.connect(self.refresh_snapshot)
        header_layout.addWidget(self.refresh_button)

        layout.addWidget(header)

        self.stack = QStackedWidget()
        for page in self.pages:
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)

        return content

    def set_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)

    def refresh_snapshot(self) -> None:
        self.theme_mode = detect_theme_mode()
        self.tokens = theme_tokens(self.theme_mode)
        self._apply_styles()
        self.theme_label.setText(f"跟随 Windows · {self.theme_mode.value}")

        self.snapshot = collect_workspace_snapshot()
        for page in self.pages:
            if hasattr(page, "update_snapshot"):
                page.update_snapshot(self.snapshot)  # type: ignore[attr-defined]
        self._update_header()

    def _update_header(self) -> None:
        db_text = "数据库正常" if self.snapshot.database.exists else "数据库未找到"
        self.header_status.setText(
            f"{db_text} · 最近报告 {len(self.snapshot.recent_reports)} 个 · "
            f"收件人 {self.snapshot.recipients_count} 人 · "
            f"刷新于 {format_datetime(self.snapshot.collected_at)}"
        )

    def _apply_styles(self) -> None:
        self.setStyleSheet(build_stylesheet(self.tokens))

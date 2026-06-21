from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True)
class ThemeTokens:
    mode: ThemeMode
    background: str
    surface: str
    surface_alt: str
    sidebar: str
    sidebar_hover: str
    sidebar_active: str
    text: str
    muted: str
    subtle: str
    border: str
    accent: str
    accent_soft: str
    success: str
    warning: str
    danger: str
    shadow: str
    disabled_bg: str
    disabled_text: str
    input_bg: str


def read_windows_light_setting() -> int | None:
    try:
        import winreg
    except ImportError:
        return None

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _value_type = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value)
    except OSError:
        return None


def choose_theme_mode(preference: str = "system", windows_light_setting: int | None = None) -> ThemeMode:
    normalized = preference.strip().lower()
    if normalized == ThemeMode.LIGHT.value:
        return ThemeMode.LIGHT
    if normalized == ThemeMode.DARK.value:
        return ThemeMode.DARK
    if normalized != "system":
        return ThemeMode.LIGHT
    if windows_light_setting == 0:
        return ThemeMode.DARK
    return ThemeMode.LIGHT


def detect_theme_mode(preference: str = "system") -> ThemeMode:
    return choose_theme_mode(preference, read_windows_light_setting())


def theme_tokens(mode: ThemeMode) -> ThemeTokens:
    if mode == ThemeMode.DARK:
        return ThemeTokens(
            mode=mode,
            background="#0f1419",
            surface="#171d23",
            surface_alt="#1d252d",
            sidebar="#111820",
            sidebar_hover="#1d2833",
            sidebar_active="#1f6f78",
            text="#e8eef5",
            muted="#a7b3c1",
            subtle="#748294",
            border="#2a3541",
            accent="#24a6a0",
            accent_soft="#163d42",
            success="#34c88a",
            warning="#e0a33a",
            danger="#e36b6b",
            shadow="rgba(0, 0, 0, 0.24)",
            disabled_bg="#202832",
            disabled_text="#748294",
            input_bg="#121920",
        )

    return ThemeTokens(
        mode=mode,
        background="#f6f8fb",
        surface="#ffffff",
        surface_alt="#f1f5f8",
        sidebar="#f8fafc",
        sidebar_hover="#edf3f7",
        sidebar_active="#dff3f2",
        text="#18222d",
        muted="#617080",
        subtle="#8a97a6",
        border="#dde5ec",
        accent="#0d8f89",
        accent_soft="#e4f5f3",
        success="#168464",
        warning="#b7791f",
        danger="#c94b4b",
        shadow="rgba(31, 44, 58, 0.08)",
        disabled_bg="#eef2f5",
        disabled_text="#8b98a6",
        input_bg="#ffffff",
    )


def build_stylesheet(tokens: ThemeTokens) -> str:
    return f"""
    QMainWindow {{
        background: {tokens.background};
        color: {tokens.text};
        font-family: "Microsoft YaHei UI", "Segoe UI", Arial, sans-serif;
        font-size: 13px;
    }}
    #Sidebar {{
        background: {tokens.sidebar};
        border-right: 1px solid {tokens.border};
    }}
    #BrandMark {{
        background: {tokens.accent};
        color: #ffffff;
        border-radius: 8px;
        font-weight: 800;
        font-size: 16px;
    }}
    #BrandTitle {{
        color: {tokens.text};
        font-size: 16px;
        font-weight: 800;
    }}
    #BrandSubtitle, #SidebarFooter {{
        color: {tokens.muted};
        font-size: 12px;
    }}
    QPushButton#NavButton {{
        background: transparent;
        border: none;
        border-radius: 8px;
        color: {tokens.muted};
        min-height: 40px;
        padding: 0 12px;
        text-align: left;
        font-weight: 600;
    }}
    QPushButton#NavButton:hover {{
        background: {tokens.sidebar_hover};
        color: {tokens.text};
    }}
    QPushButton#NavButton:checked {{
        background: {tokens.sidebar_active};
        color: {tokens.text};
    }}
    #Header {{
        background: {tokens.surface};
        border-bottom: 1px solid {tokens.border};
    }}
    #HeaderTitle {{
        font-size: 18px;
        font-weight: 800;
        color: {tokens.text};
    }}
    #HeaderStatus {{
        color: {tokens.muted};
    }}
    #ThemePill {{
        border: 1px solid {tokens.border};
        border-radius: 8px;
        background: {tokens.surface_alt};
        color: {tokens.muted};
        padding: 6px 10px;
        font-weight: 600;
    }}
    #Page {{
        background: {tokens.background};
        border: none;
    }}
    #PageTitle {{
        font-size: 24px;
        font-weight: 800;
        color: {tokens.text};
    }}
    #MutedText {{
        color: {tokens.muted};
    }}
    #StatusCard {{
        background: {tokens.surface};
        border: 1px solid {tokens.border};
        border-radius: 8px;
    }}
    #StatusCard[state="ok"] {{
        border-left: 4px solid {tokens.success};
    }}
    #StatusCard[state="warning"] {{
        border-left: 4px solid {tokens.warning};
    }}
    #StatusCard[state="neutral"] {{
        border-left: 4px solid {tokens.accent};
    }}
    #StatusCard[state="danger"] {{
        border-left: 4px solid {tokens.danger};
    }}
    #DashboardCard {{
        background: {tokens.surface};
        border: 1px solid {tokens.border};
        border-radius: 8px;
    }}
    #DashboardCard[state="ok"] {{
        border-color: {tokens.success};
    }}
    #DashboardCard[state="warning"] {{
        border-color: {tokens.warning};
    }}
    #DashboardCard[state="danger"] {{
        border-color: {tokens.danger};
    }}
    #DashboardCard[state="neutral"] {{
        border-color: {tokens.border};
    }}
    #DashboardValue {{
        color: {tokens.text};
        font-size: 20px;
        font-weight: 800;
    }}
    #StatusDot {{
        border-radius: 4px;
        background: {tokens.subtle};
    }}
    #StatusDot[state="ok"] {{
        background: {tokens.success};
    }}
    #StatusDot[state="warning"] {{
        background: {tokens.warning};
    }}
    #StatusDot[state="danger"] {{
        background: {tokens.danger};
    }}
    #StatusDot[state="neutral"] {{
        background: {tokens.accent};
    }}
    #Section {{
        background: {tokens.surface};
        border: 1px solid {tokens.border};
        border-radius: 8px;
    }}
    #CardTitle {{
        color: {tokens.muted};
        font-size: 12px;
        font-weight: 700;
    }}
    #CardValue {{
        color: {tokens.text};
        font-size: 19px;
        font-weight: 800;
    }}
    #SectionTitle {{
        color: {tokens.text};
        font-size: 15px;
        font-weight: 800;
    }}
    #RowLabel {{
        color: {tokens.text};
        font-weight: 700;
    }}
    #Pill {{
        border-radius: 8px;
        padding: 4px 9px;
        min-width: 50px;
        color: #ffffff;
        background: {tokens.subtle};
        font-size: 12px;
        font-weight: 700;
    }}
    #Pill[state="ok"] {{
        background: {tokens.success};
    }}
    #Pill[state="warning"] {{
        background: {tokens.warning};
    }}
    #Pill[state="danger"] {{
        background: {tokens.danger};
    }}
    QPushButton {{
        border: 1px solid {tokens.border};
        border-radius: 8px;
        padding: 8px 12px;
        background: {tokens.surface};
        color: {tokens.text};
        font-weight: 600;
    }}
    QPushButton:hover {{
        border-color: {tokens.accent};
        background: {tokens.accent_soft};
    }}
    QPushButton:disabled {{
        color: {tokens.disabled_text};
        background: {tokens.disabled_bg};
        border-color: {tokens.border};
    }}
    QPushButton#PrimaryButton {{
        background: {tokens.accent};
        border-color: {tokens.accent};
        color: #ffffff;
        font-weight: 800;
    }}
    QPushButton#GhostButton {{
        background: {tokens.accent_soft};
        border-color: {tokens.accent_soft};
        color: {tokens.accent};
    }}
    QPushButton#DangerButton {{
        background: {tokens.surface};
        border-color: {tokens.danger};
        color: {tokens.danger};
        font-weight: 800;
    }}
    QPushButton#DangerButton:hover {{
        background: {tokens.danger};
        border-color: {tokens.danger};
        color: #ffffff;
    }}
    QListWidget#FileList {{
        border: 1px solid {tokens.border};
        border-radius: 8px;
        background: {tokens.input_bg};
        padding: 4px;
        color: {tokens.text};
        alternate-background-color: {tokens.surface_alt};
    }}
    QTableWidget#ReportTable {{
        border: 1px solid {tokens.border};
        border-radius: 8px;
        background: {tokens.input_bg};
        color: {tokens.text};
        gridline-color: {tokens.border};
        alternate-background-color: {tokens.surface_alt};
        selection-background-color: {tokens.accent_soft};
        selection-color: {tokens.text};
    }}
    QTableWidget#ReportTable::item {{
        padding: 7px;
    }}
    QHeaderView::section {{
        background: {tokens.surface_alt};
        color: {tokens.muted};
        border: none;
        border-right: 1px solid {tokens.border};
        border-bottom: 1px solid {tokens.border};
        padding: 7px 8px;
        font-weight: 700;
    }}
    QLineEdit {{
        border: 1px solid {tokens.border};
        border-radius: 8px;
        padding: 8px 10px;
        background: {tokens.input_bg};
        color: {tokens.text};
    }}
    QTextEdit {{
        border: 1px solid {tokens.border};
        border-radius: 8px;
        padding: 10px;
        background: {tokens.input_bg};
        color: {tokens.text};
        selection-background-color: {tokens.accent};
        selection-color: #ffffff;
    }}
    QSplitter#ReportCenterSplitter::handle:vertical,
    QSplitter#DataCenterSplitter::handle:vertical,
    QSplitter#MailCenterSplitter::handle:vertical,
    QSplitter#TaskCenterSplitter::handle:vertical,
    QSplitter#LogCenterSplitter::handle:vertical {{
        background: {tokens.border};
        height: 10px;
        margin: 2px 0;
        border-radius: 4px;
    }}
    QSplitter#ReportCenterSplitter::handle:vertical:hover,
    QSplitter#DataCenterSplitter::handle:vertical:hover,
    QSplitter#MailCenterSplitter::handle:vertical:hover,
    QSplitter#TaskCenterSplitter::handle:vertical:hover,
    QSplitter#LogCenterSplitter::handle:vertical:hover {{
        background: {tokens.accent};
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {tokens.border};
        border-radius: 5px;
        min-height: 28px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    """

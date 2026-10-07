"""Светлая и тёмная тема: один набор правил, две палитры."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PyQt6.QtWidgets import QApplication


@dataclass(frozen=True, slots=True)
class Palette:
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_soft: str
    on_accent: str
    good: str
    good_soft: str
    bad: str
    bad_soft: str
    warn: str
    warn_soft: str
    violet: str
    violet_soft: str
    group_bg: str
    selection: str


LIGHT = Palette(
    bg="#F3F4F6",
    surface="#FFFFFF",
    surface_alt="#F8F9FB",
    border="#E1E4E9",
    text="#1F2630",
    muted="#6A7382",
    accent="#2F6AD9",
    accent_hover="#2559BD",
    accent_soft="#E7EFFC",
    on_accent="#FFFFFF",
    good="#1D8A57",
    good_soft="#E2F3EA",
    bad="#C4453C",
    bad_soft="#FAE8E6",
    warn="#9A6A12",
    warn_soft="#FBF2DD",
    violet="#6553C8",
    violet_soft="#ECE9FA",
    group_bg="#F2F5FA",
    selection="#DAE6FA",
)

DARK = Palette(
    bg="#14171C",
    surface="#1B1F26",
    surface_alt="#20252D",
    border="#2B313B",
    text="#E3E6EA",
    muted="#8F98A5",
    accent="#6A99EE",
    accent_hover="#82AAF2",
    accent_soft="#22324C",
    on_accent="#0F1318",
    good="#5BC490",
    good_soft="#1C382C",
    bad="#EC7C73",
    bad_soft="#42262A",
    warn="#DDB35F",
    warn_soft="#3A311F",
    violet="#A99DF0",
    violet_soft="#2C2946",
    group_bg="#212731",
    selection="#293A56",
)

PALETTES = {"light": LIGHT, "dark": DARK}

_QSS = """
QWidget {{ color: {text}; font-size: 13px; }}
QMainWindow, QDialog {{ background: {bg}; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 4px 6px; }}

#sidebar {{ background: {surface}; border-right: 1px solid {border}; }}
#appTitle {{ font-size: 18px; font-weight: 600; }}
#appSubtitle, #muted, #stepHint, #statCaption, #statNote, #statusLine {{ color: {muted}; }}
#appSubtitle, #statNote, #stepHint, #statusLine {{ font-size: 12px; }}

#stepCard, #statCard, #panel {{
    background: {surface}; border: 1px solid {border}; border-radius: 10px;
}}
#stepCard {{ background: {surface_alt}; }}
#stepCard[dropTarget="true"] {{ border: 1px dashed {accent}; background: {accent_soft}; }}
#stepBadge {{
    background: {accent_soft}; color: {accent}; border-radius: 11px;
    font-weight: 600; font-size: 12px;
}}
#stepBadge[done="true"] {{ background: {good_soft}; color: {good}; }}
#stepTitle {{ font-weight: 600; font-size: 14px; }}
#stepFile {{ font-weight: 600; }}

#statCaption {{ font-size: 12px; }}
#statValue {{ font-size: 22px; font-weight: 600; }}
#statValue[tone="good"] {{ color: {good}; }}
#statValue[tone="bad"] {{ color: {bad}; }}

QPushButton {{
    background: {surface}; border: 1px solid {border}; border-radius: 8px;
    padding: 7px 14px; min-height: 18px;
}}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton:pressed {{ background: {accent_soft}; }}
QPushButton:disabled {{ color: {muted}; background: {surface_alt}; border-color: {border}; }}
QPushButton#primary {{
    background: {accent}; color: {on_accent}; border: 1px solid {accent};
    font-weight: 600; font-size: 14px; padding: 10px 14px;
}}
QPushButton#primary:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
QPushButton#primary:disabled {{ background: {border}; border-color: {border}; color: {muted}; }}
QPushButton#link {{
    background: transparent; border: none; color: {accent}; padding: 2px 0; text-align: left;
}}
QPushButton#link:hover {{ color: {accent_hover}; text-decoration: underline; }}
QPushButton#link:disabled {{ color: {muted}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {surface}; border: 1px solid {border}; border-radius: 8px;
    padding: 6px 10px; min-height: 18px; selection-background-color: {selection};
    selection-color: {text};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {surface}; border: 1px solid {border}; outline: 0;
    selection-background-color: {selection}; selection-color: {text};
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border: 1px solid {muted}; border-radius: 4px;
    background: {surface};
}}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
QCheckBox::indicator:disabled {{ border-color: {border}; }}
QPlainTextEdit {{
    background: {surface}; border: 1px solid {border}; border-radius: 10px; padding: 8px;
}}

QProgressBar {{
    background: {border}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px;
}}
QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}

QTreeView, QTableWidget {{
    background: {surface}; alternate-background-color: {surface_alt};
    border: 1px solid {border}; border-radius: 10px; outline: 0;
    selection-background-color: {selection}; selection-color: {text};
    gridline-color: {border};
}}
QTreeView::item, QTableWidget::item {{ padding: 5px 8px; border: none; }}
QTreeView::item:selected, QTableWidget::item:selected {{ background: {selection}; color: {text}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {surface}; color: {muted}; border: none; border-bottom: 1px solid {border};
    padding: 8px; font-size: 12px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {surface}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{
    background: {border}; border-radius: 3px; min-height: 28px; min-width: 28px;
}}
QScrollBar::handle:hover {{ background: {muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

#banner {{ background: {warn_soft}; border: 1px solid {warn_soft}; border-radius: 8px; }}
#banner QLabel {{ color: {warn}; }}
#emptyTitle {{ font-size: 16px; font-weight: 600; }}
#dialogTitle {{ font-size: 16px; font-weight: 600; }}
QGroupBox {{
    border: 1px solid {border}; border-radius: 10px; margin-top: 10px; padding: 12px 10px 8px 10px;
    background: {surface}; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {muted}; }}
QMenu {{ background: {surface}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {selection}; }}
"""


def system_theme() -> str:
    scheme = QGuiApplication.styleHints().colorScheme()
    return "dark" if scheme == Qt.ColorScheme.Dark else "light"


def apply_theme(app: QApplication, name: str) -> Palette:
    """Красит приложение целиком. Возвращает палитру, чтобы виджеты брали из неё цвета."""
    colors = PALETTES.get(name, LIGHT)
    app.setStyle("Fusion")
    font = QFont("Segoe UI")
    font.setPixelSize(13)
    app.setFont(font)

    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: colors.bg,
        QPalette.ColorRole.WindowText: colors.text,
        QPalette.ColorRole.Base: colors.surface,
        QPalette.ColorRole.AlternateBase: colors.surface_alt,
        QPalette.ColorRole.Text: colors.text,
        QPalette.ColorRole.Button: colors.surface,
        QPalette.ColorRole.ButtonText: colors.text,
        QPalette.ColorRole.Highlight: colors.selection,
        QPalette.ColorRole.HighlightedText: colors.text,
        QPalette.ColorRole.ToolTipBase: colors.surface,
        QPalette.ColorRole.ToolTipText: colors.text,
        QPalette.ColorRole.PlaceholderText: colors.muted,
        QPalette.ColorRole.Link: colors.accent,
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(colors.muted))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(colors.muted)
    )
    app.setPalette(palette)
    app.setStyleSheet(_QSS.format(**asdict(colors)))
    return colors

"""A small QSS stylesheet applied once at the QApplication level for a
cleaner, more modern look than Qt's bare default widget styling. Light
theme only -- no attempt at full dark-mode theming in this pass.
"""

from __future__ import annotations

ACCENT = "#3B6FE0"
ACCENT_HOVER = "#2F5BC4"
ACCENT_PRESSED = "#25489C"
BACKGROUND = "#F5F6F8"
SURFACE = "#FFFFFF"
BORDER = "#DADEE5"
TEXT = "#1E2126"
TEXT_MUTED = "#5B6270"

STYLESHEET = f"""
QWidget {{
    background: {BACKGROUND};
    color: {TEXT};
    font-family: "Segoe UI", sans-serif;
    font-size: 10pt;
}}

QMainWindow {{
    background: {BACKGROUND};
}}

QLabel {{
    background: transparent;
}}

QLabel[muted="true"] {{
    color: {TEXT_MUTED};
}}

QGroupBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}}

QPushButton {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 8px 16px;
    color: {TEXT};
}}

QPushButton:hover {{
    border-color: {ACCENT};
    color: {ACCENT};
}}

QPushButton:pressed {{
    background: {BORDER};
}}

QPushButton:disabled {{
    color: {TEXT_MUTED};
    border-color: {BORDER};
}}

QPushButton[accent="true"] {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: white;
    font-weight: 600;
}}

QPushButton[accent="true"]:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
    color: white;
}}

QPushButton[accent="true"]:pressed {{
    background: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
}}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {ACCENT};
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT};
}}

QProgressBar {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    text-align: center;
    height: 20px;
}}

QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 5px;
}}

QScrollArea {{
    border: none;
}}

QFrame[matchRow="true"] {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background: {SURFACE};
}}

QTabBar::tab {{
    background: transparent;
    padding: 8px 14px;
    color: {TEXT_MUTED};
}}

QTabBar::tab:selected {{
    color: {ACCENT};
    font-weight: 600;
}}

QTableWidget {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: {BORDER};
}}

QHeaderView::section {{
    background: {BACKGROUND};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
    font-weight: 600;
}}
"""

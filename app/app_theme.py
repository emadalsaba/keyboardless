"""مظهر البرنامج: الوضع الفاتح/الداكن، وألوان المشروع من دليل التصميم.

The user chooses how the window looks: follow Windows, always dark, or always
light. The palette is the one from the icon design notes (dark green, mint,
amber), so the window and the artwork belong to the same design.

Kept free of Qt: the choice, the resolution and the colour table are testable on
a machine with no display, and the window only turns the result into a stylesheet.
"""

from __future__ import annotations

from pathlib import Path

#: the values that may be stored in config.json under "appearance"
APPEARANCES = ("system", "dark", "light")

#: ألوان من دليل تصميم الأيقونات، مع قيم مقابلة لكل وضع
PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#1B241F",        # داكن (من الدليل)
        "field": "#141916",
        "fg": "#E4F0E9",        # خلفية نعناعية فاتحة تُقرأ كنص
        "muted": "#B3B6B3",     # رمادي فاتح (من الدليل)
        "border": "#2F3B34",
        "button": "#26322C",
        "accent": "#6E9484",    # أخضر فاتح (من الدليل)
        "dedication": "#E4F0E9",
        "ok": "#6E9484",
        "warn": "#D79A1F",      # عنبري (من الدليل)
    },
    "light": {
        "bg": "#F7F9F8",        # ألوان ويندوز المعتادة مع لمسة نعناعية خفيفة
        "field": "#FFFFFF",
        "fg": "#1B241F",
        "muted": "#5B6472",
        "border": "#D6DCD8",
        "button": "#EFEFEF",
        "accent": "#234C3B",    # أخضر داكن (من الدليل)
        "dedication": "#234C3B",
        "ok": "#0F9D58",
        "warn": "#B87C10",      # عنبري داكن (من الدليل)
    },
}


def resolve(appearance: str, system_dark: bool) -> str:
    """الوضع الفعلي: اختيار المستخدم، أو ما يفضّله ويندوز عند «اتبع النظام»."""
    if appearance not in APPEARANCES:
        appearance = "system"
    if appearance == "system":
        return "dark" if system_dark else "light"
    return appearance


def colors(appearance: str, system_dark: bool = False) -> dict[str, str]:
    """جدول الألوان للوضع الفعلي."""
    return PALETTES[resolve(appearance, system_dark)]


def labels() -> tuple[tuple[str, str], ...]:
    """خيارات القائمة في النافذة: (التسمية، القيمة في الإعداد)."""
    return (("اتّبع وضع ويندوز", "system"), ("داكن دائمًا", "dark"),
            ("فاتح دائمًا (ألوان ويندوز)", "light"))


def stylesheet(appearance: str, system_dark: bool = False) -> str:
    """ورقة أنماط Qt للمظهر المختار (تُطبَّق على التطبيق كله)."""
    c = colors(appearance, system_dark)
    return f"""
    QWidget {{ background-color: {c['bg']}; color: {c['fg']}; }}
    QMainWindow, QDialog {{ background-color: {c['bg']}; }}
    QLabel {{ background: transparent; }}
    QGroupBox {{ border: 1px solid {c['border']}; border-radius: 8px;
                 margin-top: 14px; padding-top: 10px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px;
                        color: {c['muted']}; }}
    QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QPlainTextEdit, QProgressBar {{
        background-color: {c['field']}; color: {c['fg']};
        border: 1px solid {c['border']}; border-radius: 6px; padding: 4px; }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 6px; }}
    QTabBar::tab {{ padding: 7px 14px; color: {c['fg']}; background: transparent; }}
    QTabBar::tab:selected {{ color: {c['accent']}; font-weight: 600; }}
    QPushButton {{ background-color: {c['button']}; color: {c['fg']};
                   border: 1px solid {c['border']}; border-radius: 6px; padding: 5px 12px; }}
    QPushButton:hover {{ border-color: {c['accent']}; }}
    QPushButton:disabled {{ color: {c['muted']}; }}
    QCheckBox, QRadioButton {{ color: {c['fg']}; }}
    QMenu {{ background-color: {c['bg']}; color: {c['fg']};
             border: 1px solid {c['border']}; }}
    QMenu::item:selected {{ background-color: {c['accent']}; color: {c['bg']}; }}
    QToolTip {{ background-color: {c['bg']}; color: {c['fg']};
                border: 1px solid {c['border']}; }}
    """


def path_exists(path: Path) -> bool:  # pragma: no cover - helper used by the UI
    return path.exists()

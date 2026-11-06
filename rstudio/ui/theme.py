"""Design system: one palette + one stylesheet for the whole application (dark by default, light available)."""
DARK = dict(bg="#101216", panel="#171a20", panel2="#1e222a", panel3="#262b35", border="#2c323d", text="#e7e9ee", muted="#9aa3b2",
            accent="#3b82f6", accent_hi="#5b9bff", accent2="#f59e0b", ok="#34c38f", warn="#f5a524", err="#ef5b5b", canvas="#0c0e11", hover="#2a303b")
LIGHT = dict(bg="#eef0f4", panel="#ffffff", panel2="#f4f6f9", panel3="#e6e9ef", border="#d3d8e0", text="#1b1f27", muted="#5d6675",
             accent="#2563eb", accent_hi="#3b82f6", accent2="#d97706", ok="#15935f", warn="#b7791f", err="#d03a3a", canvas="#dfe3ea", hover="#e0e5ee")
THEMES = {"dark": DARK, "light": LIGHT}
FONT_FAMILY = "Segoe UI"

def palette(name="dark"): return THEMES.get(name, DARK)

def stylesheet(name="dark"):
    c = palette(name)
    return f"""
* {{ font-family: "{FONT_FAMILY}", "Noto Sans", "Nirmala UI", sans-serif; font-size: 13px; outline: 0; }}
QWidget {{ background: {c['panel']}; color: {c['text']}; }}
QMainWindow, QStackedWidget, QSplitter {{ background: {c['bg']}; }}
QSplitter::handle {{ background: {c['bg']}; width: 3px; height: 3px; }}
QLabel {{ background: transparent; }}
QLabel#h1 {{ font-size: 30px; font-weight: 700; }}
QLabel#h2 {{ font-size: 17px; font-weight: 600; }}
QLabel#muted, QLabel[muted="true"] {{ color: {c['muted']}; }}
QLabel#section {{ color: {c['muted']}; font-size: 11px; font-weight: 700; letter-spacing: 1px; padding: 10px 0 2px 0; }}
QToolTip {{ background: {c['panel3']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 5px 8px; }}
QMenuBar {{ background: {c['panel']}; border-bottom: 1px solid {c['border']}; }}
QMenuBar::item {{ padding: 6px 11px; background: transparent; }} QMenuBar::item:selected {{ background: {c['hover']}; border-radius: 4px; }}
QMenu {{ background: {c['panel2']}; border: 1px solid {c['border']}; padding: 5px; }}
QMenu::item {{ padding: 6px 28px 6px 14px; border-radius: 4px; }} QMenu::item:selected {{ background: {c['accent']}; color: white; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 4px; }}
QToolBar {{ background: {c['panel']}; border: none; spacing: 4px; padding: 4px; }}
QToolBar#header {{ border-bottom: 1px solid {c['border']}; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 5px; color: {c['text']}; }}
QToolButton:hover {{ background: {c['hover']}; }}
QToolButton:checked {{ background: {c['accent']}; color: white; }}
QToolButton:disabled {{ color: {c['muted']}; }}
QToolButton#nav {{ padding: 9px 6px; border-radius: 8px; font-size: 11px; min-width: 66px; }}
QToolButton#nav:checked {{ background: {c['panel3']}; border-left: 3px solid {c['accent']}; border-radius: 4px; color: {c['text']}; }}
QPushButton {{ background: {c['panel3']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 7px 14px; }}
QPushButton:hover {{ background: {c['hover']}; border-color: {c['accent']}; }}
QPushButton:pressed {{ background: {c['accent']}; }}
QPushButton:disabled {{ color: {c['muted']}; background: {c['panel2']}; border-color: {c['panel2']}; }}
QPushButton#primary {{ background: {c['accent']}; border-color: {c['accent']}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {c['accent_hi']}; }}
QPushButton#primary:disabled {{ background: {c['panel3']}; color: {c['muted']}; }}
QPushButton#card {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 12px; padding: 16px; text-align: left; font-size: 14px; }}
QPushButton#card:hover {{ border-color: {c['accent']}; background: {c['panel3']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 5px; padding: 5px 7px; selection-background-color: {c['accent']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {c['panel2']}; border: 1px solid {c['border']}; selection-background-color: {c['accent']}; }}
QCheckBox, QRadioButton {{ spacing: 7px; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {c['border']}; border-radius: 4px; background: {c['panel2']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['panel3']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {c['text']}; width: 14px; height: 14px; margin: -6px 0; border-radius: 7px; }}
QListWidget, QTableWidget, QTreeWidget {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 6px; }}
QListWidget::item {{ padding: 6px; border-radius: 4px; }} QListWidget::item:selected {{ background: {c['accent']}; color: white; }}
QListWidget::item:hover:!selected {{ background: {c['hover']}; }}
QHeaderView::section {{ background: {c['panel3']}; border: none; padding: 6px; color: {c['muted']}; }}
QTabWidget::pane {{ border: none; background: {c['canvas']}; }}
QTabBar {{ background: {c['bg']}; }}
QTabBar::tab {{ background: {c['panel']}; padding: 7px 16px; border: 1px solid {c['border']}; border-bottom: none; border-top-left-radius: 7px; border-top-right-radius: 7px; margin-right: 2px; color: {c['muted']}; }}
QTabBar::tab:selected {{ background: {c['panel3']}; color: {c['text']}; border-top: 2px solid {c['accent']}; }}
QScrollBar:vertical {{ background: transparent; width: 11px; }} QScrollBar:horizontal {{ background: transparent; height: 11px; }}
QScrollBar::handle {{ background: {c['panel3']}; border-radius: 5px; min-height: 28px; min-width: 28px; }} QScrollBar::handle:hover {{ background: {c['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollArea {{ border: none; background: transparent; }}
QStatusBar {{ background: {c['panel']}; border-top: 1px solid {c['border']}; }} QStatusBar QLabel {{ padding: 0 8px; color: {c['muted']}; }}
QProgressBar {{ background: {c['panel3']}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}
QGroupBox {{ border: 1px solid {c['border']}; border-radius: 8px; margin-top: 12px; padding: 12px 8px 8px 8px; background: {c['panel']}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; color: {c['muted']}; }}
QFrame#panel {{ background: {c['panel']}; border-left: 1px solid {c['border']}; }}
QFrame#optbar {{ background: {c['panel2']}; border-bottom: 1px solid {c['border']}; }}
QFrame#toolcol {{ background: {c['panel']}; border-right: 1px solid {c['border']}; }}
QFrame#navcol {{ background: {c['panel2']}; border-right: 1px solid {c['border']}; }}
QFrame#hero {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {c['panel2']}, stop:1 {c['bg']}); border-radius: 16px; }}
QDialog {{ background: {c['panel']}; }}
"""

def apply_theme(app, name="dark"):
    app.setStyleSheet(stylesheet(name))

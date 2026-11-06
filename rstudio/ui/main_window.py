"""The one and only main window. Home, Photo Editor, Adjustments, AI Studio, Document Studio, Passport & ID, Layout Studio and Settings are
all views of this window working on the same open documents (same canvas, layers, undo history, task manager and file operations)."""
import os
import numpy as np
from PIL import Image, ImageOps
from PySide6.QtCore import Qt, QTimer, QSizeF, QMarginsF, QRectF, QSize, QPoint
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QPageSize, QPageLayout, QPainter, QImage
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QTabWidget, QToolBar, QToolButton, QButtonGroup, QFrame, QLabel,
                               QPushButton, QProgressBar, QSplitter, QScrollArea, QFileDialog, QMessageBox, QInputDialog, QLineEdit, QSpinBox, QSlider,
                               QCheckBox, QComboBox, QApplication, QSizePolicy)
from .. import APP_NAME, VERSION
from ..engine.settings import Settings
from ..engine.ai import AIManager
from ..engine.document import Document, Layer, to_rgba, text_support
from ..engine.recovery import Recovery
from ..engine import docstudio
from .qtbridge import TaskBridge
from .canvas import CanvasView
from .home import HomeScreen
from .settings_page import SettingsPage
from .widgets import NewDocDialog, ExportDialog, ColorChip, SliderRow, label, row
from .sheets import PrintSheetDialog, LayerSizeDialog
from . import clip
from ..engine import perspective as persp_engine, passport as passport_engine, cards as cards_engine
from .panels import ImagePanel, AdjustPanel, RetouchPanel, AIPanel, DocPanel, PassportPanel, LayoutPanel, LayersPanel
from .icons import icon
from . import theme
from ..engine import core

NAV = [("home", "Home", "home"), ("photo", "Photo Editor", "crop"), ("adjust", "Adjustments", "adjust"), ("retouch", "Retouch", "face"), ("ai", "AI Studio", "ai"), ("doc", "Document Studio", "doc"),
       ("passport", "Passport & ID", "passport"), ("layout", "Layout Studio", "layout"), ("settings", "Settings", "settings")]
TOOLS = [("move", "Move / resize  (V)", "move", "V"), ("select", "Marquee: rectangle or ellipse  (M)", "select", "M"), ("lasso", "Lasso: draw freehand  (L)", "lasso", "L"), ("poly", "Polygon lasso: click points, double-click to close  (Q)", "poly", "Q"),
         ("wand", "Magic wand  (W)", "wand", "W"), ("crop", "Crop  (C)", "crop", "C"), ("perspective", "Perspective crop - straighten a card / paper photo  (P)", "transform", "P"),
         ("brush", "Brush  (B)   Alt+click picks a colour", "brush", "B"), ("eraser", "Eraser  (E)", "eraser", "E"), ("clone", "Clone stamp  (S)   Alt+click sets the source", "stamp", "S"),
         ("bucket", "Paint bucket  (K)", "bucket", "K"), ("gradient", "Gradient  (G)", "gradient", "G"), ("text", "Text  (T)", "text", "T"), ("shape", "Shapes  (U)", "shape", "U"),
         ("picker", "Colour picker  (I)", "picker", "I"), ("zoom", "Zoom  (Z)   click = in, Alt+click = out", "zoomin", "Z"), ("pan", "Hand  (H)", "hand", "H")]
OPEN_FILTER = "Images, projects and PDFs (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp *.rai *.pdf);;Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;Ripon project (*.rai);;PDF (*.pdf)"

class MainWindow(QMainWindow):
    def __init__(self, settings=None, recovery=None):
        super().__init__()
        self.settings = settings or Settings(); self.recovery = recovery or Recovery(); self._auto_ver = {}; self.ai = AIManager(self.settings); self.bridge = TaskBridge(self); self._theme = self.settings.get("theme"); self._tool = "move"
        self._cur_task = None; self._nav = "home"; self._icon_widgets = []
        self.opts = dict(brush_size=24, brush_opacity=1.0, brush_hardness=1.0, brush_color=(0, 0, 0, 255), bg_color=(255, 255, 255, 255), erase_transparent=False, sel_mode="new", marquee="rect", wand_tol=32, wand_contig=True, wand_all=True, bucket_tol=32, bucket_contig=True, grad_kind="linear", wheel_zooms=bool(self.settings.get("wheel_zooms")), text="Text", text_size=64, text_bold=False, text_color=(0, 0, 0, 255),
                         shape="rect", shape_fill=(59, 130, 246, 255), shape_stroke=None, shape_stroke_w=0, autoselect=True)
        self.setWindowTitle(APP_NAME); self.resize(1480, 900); self.setAcceptDrops(True)
        from .. import paths
        from PySide6.QtGui import QIcon
        self.setWindowIcon(QIcon(paths.asset("logo.ico")) if os.path.isfile(paths.asset("logo.ico")) else QIcon())
        self.panels = {}; self._build_actions(); self._build_ui(); self._build_menus(); self._build_status()
        self.bridge.started.connect(self._task_started); self.bridge.progress.connect(self._task_progress); self.bridge.finished.connect(self._task_finished)
        self.goto("home"); self.set_tool("move"); self._update_actions()
        self._auto_timer = QTimer(self); self._auto_timer.setInterval(60000); self._auto_timer.timeout.connect(self._autosave); self._auto_timer.start()
        QTimer.singleShot(700, self._offer_recovery)

    # ======================================================================= panel API (used by every panel)
    def canvas(self):
        w = self.tabs.currentWidget(); return w if isinstance(w, CanvasView) else None
    def doc(self): c = self.canvas(); return c.doc if c else None
    def docs(self): return [self.tabs.widget(i).doc for i in range(self.tabs.count())]
    def icon_color(self): return theme.palette(self._theme)["text"]
    def require_doc(self):
        d = self.doc()
        if d is None: self.notify("Open or create an image first.", "warn")
        return d
    def run_task(self, title, fn, done=None, fail=None, quiet=False):
        def _fail(e):
            if fail: fail(e)
            else: self.notify(f"{title} failed: {type(e).__name__}: {e}", "error")
        return self.bridge.run(title, fn, done, _fail, quiet)
    def notify(self, msg, kind="info"):
        col = {"info": "#9aa3b2", "ok": "#34c38f", "warn": "#f5a524", "error": "#ef5b5b"}[kind]
        self.msg.setStyleSheet(f"color:{col}; font-weight:600;"); self.msg.setText(msg); self._msg_timer.start(9000)
        if kind == "error": QMessageBox.critical(self, APP_NAME, msg)
    def set_compare(self, mode):
        c = self.canvas()
        if c: c.set_compare(mode)
    def layer_selected(self):
        if self._nav == "adjust": self.panels["adjust"].preview()
        self._refresh_panels()
    def after_edit(self, label_=""):
        c = self.canvas()
        if c is None: return
        c.update(); self.layers.refresh(); self._refresh_panels(); self._update_tab_title(self.tabs.currentIndex()); self._update_actions(); self._status_info()
        if self._nav == "adjust" and label_: self.panels["adjust"].preview()
        if label_ in ("Add text", "Edit text"): self._check_text(c.doc.active)

    def _check_text(self, L):
        if L is None or L.kind != "text": return
        s = text_support(L.params.get("text", ""))
        if s["bengali"] and not (s["font_found"] and s["shaped"]):
            self.notify("Bengali text may not look right: " + ("no Bengali font was found (install Nirmala UI / Noto Sans Bengali). " if not s["font_found"] else "") + ("Complex-script shaping is unavailable." if not s["shaped"] else ""), "warn")

    # ======================================================================= crash protection
    def _autosave(self):
        for d in self.docs():
            if d.dirty and self._auto_ver.get(d.uid) != d.version:
                snap = d.snapshot(); self._auto_ver[d.uid] = d.version
                self.run_task("Autosave", lambda ctx, u=d.uid, n=d.name, s=snap: self.recovery.write(u, n, s), fail=lambda e: None, quiet=True)
    def _offer_recovery(self):
        items = self.recovery.pending()
        if not items: return
        r = QMessageBox.question(self, APP_NAME, f"{len(items)} unsaved document(s) from the last session were found (the app closed unexpectedly). Open them now?")
        for it in items:
            if r == QMessageBox.StandardButton.Yes:
                try: self.open_document(self.recovery.open(it))
                except Exception as e: self.notify(f"Could not recover '{it['name']}': {type(e).__name__}", "error")
            self.recovery.clear(it["uid"])

    # ======================================================================= construction
    def _act(self, text, slot, shortcut=None, ic=None, tip=""):
        a = QAction(text, self)
        if shortcut: a.setShortcut(QKeySequence(shortcut))
        if ic: a.setIcon(icon(ic, self.icon_color())); self._icon_widgets.append((a, ic))
        if tip: a.setToolTip(tip)
        a.triggered.connect(lambda _=False: slot()); return a

    def _build_actions(self):
        A = self._act; self.a = {}
        self.a["new"] = A("New project...", self.new_project, "Ctrl+N", "new", "New project"); self.a["open"] = A("Open...", self.open_files, "Ctrl+O", "open", "Open image / project / PDF")
        self.a["save"] = A("Save", self.save, "Ctrl+S", "save", "Save project (.rai, keeps layers)"); self.a["saveas"] = A("Save as...", self.save_as, "Ctrl+Shift+S")
        self.a["export"] = A("Export...", self.export, "Ctrl+E", "export", "Export PNG / JPG / PDF ..."); self.a["print"] = A("Print preview...", self.print_preview, "Ctrl+P", "print")
        self.a["close"] = A("Close tab", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W"); self.a["quit"] = A("Quit", self.close, "Ctrl+Q")
        self.a["undo"] = A("Undo", self.undo, "Ctrl+Z", "undo", "Undo"); self.a["redo"] = A("Redo", self.redo, "Ctrl+Y", "redo", "Redo")
        self.a["copy"] = A("Copy layer / selection", self.copy_clipboard, "Ctrl+C"); self.a["paste"] = A("Paste picture as new layer", self.paste_clipboard, "Ctrl+V")
        self.a["invsel"] = A("Inverse selection", self.invert_selection, "Ctrl+Shift+I"); self.a["clearpx"] = A("Clear selected pixels", self.clear_pixels, "Delete"); self.a["fillfg"] = A("Fill with foreground colour", lambda: self.fill_selection(False), "Alt+Backspace")
        self.a["fillbg"] = A("Fill with background colour", lambda: self.fill_selection(True), "Ctrl+Backspace"); self.a["viacopy"] = A("Layer via copy", self.layer_via_copy, "Ctrl+J"); self.a["viacut"] = A("Layer via cut", lambda: self.layer_via_copy(True), "Ctrl+Shift+J")
        self.a["swapc"] = A("Swap foreground / background colours", self.swap_colors, "X"); self.a["defc"] = A("Default colours (black / white)", self.default_colors, "D")
        self.a["sizeup"] = A("Brush bigger", lambda: self.brush_step(1.12), "]"); self.a["sizedn"] = A("Brush smaller", lambda: self.brush_step(1 / 1.12), "[")
        self.a["hardup"] = A("Brush harder", lambda: self.brush_hard(0.1), "Shift+]"); self.a["harddn"] = A("Brush softer", lambda: self.brush_hard(-0.1), "Shift+[")
        self.a["selall"] = A("Select all", self.select_all, "Ctrl+A"); self.a["desel"] = A("Deselect", self.deselect, "Ctrl+D")
        self.a["fit"] = A("Fit to screen", lambda: self._cv(lambda c: c.fit()), "Ctrl+0", "fit", "Fit to screen"); self.a["z100"] = A("Actual pixels (100%)", lambda: self._cv(lambda c: c.actual()), "Ctrl+1")
        self.a["zprint"] = A("Actual print size", lambda: self._cv(lambda c: c.zoom_physical()), "Ctrl+2"); self.a["zin"] = A("Zoom in", lambda: self._cv(lambda c: c.zoom_by(1.25)), "Ctrl+=", "zoomin", "Zoom in")
        self.a["zout"] = A("Zoom out", lambda: self._cv(lambda c: c.zoom_by(0.8)), "Ctrl+-", "zoomout", "Zoom out"); self.a["compare"] = A("Before / After", self.cycle_compare, "\\", "compare", "Compare with the original: split, then before-only, then off")
        self.a["panel"] = A("Show / hide side panel", self.toggle_side, "Tab"); self.a["theme"] = A("Switch dark / light theme", self.toggle_theme)
        self.a["about"] = A("About", self.about)

    def _cv(self, f):
        c = self.canvas()
        if c: f(c)

    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root); h = QHBoxLayout(root); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)
        # --- left navigation
        nav = QFrame(); nav.setObjectName("navcol"); nv = QVBoxLayout(nav); nv.setContentsMargins(6, 8, 6, 8); nv.setSpacing(3); self.navgrp = QButtonGroup(self); self.navbtn = {}
        logo = QLabel(); from PySide6.QtGui import QPixmap; from .. import paths
        pm = QPixmap(paths.asset("logo_512.png"))
        if not pm.isNull(): logo.setPixmap(pm.scaled(54, 54, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)); logo.setAlignment(Qt.AlignmentFlag.AlignCenter); nv.addWidget(logo); nv.addSpacing(6)
        for key, text, ic in NAV:
            b = QToolButton(); b.setObjectName("nav"); b.setText(text.replace(" ", "\n", 1)); b.setCheckable(True); b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon); b.setIcon(icon(ic, self.icon_color(), 24)); b.setIconSize(QSize(24, 24))
            b.setToolTip(text); b.clicked.connect(lambda _=False, k=key: self.goto(k)); self.navgrp.addButton(b); nv.addWidget(b); self.navbtn[key] = b; self._icon_widgets.append((b, ic))
            if key in ("home", "layout"): nv.addSpacing(4)
        nv.addStretch(1); h.addWidget(nav)
        # --- pages
        self.stack = QStackedWidget(); h.addWidget(self.stack, 1)
        self.home = HomeScreen(self.icon_color()); self.home.action.connect(self._home_action); self.home.openRecent.connect(lambda p: self.open_files([p])); self.home.removeRecent.connect(self._remove_recent); self.home.clearRecent.connect(self.clear_recent); self.stack.addWidget(self.home)
        self.work = QWidget(); self.stack.addWidget(self.work); self._build_workspace()
        self.settings_page = SettingsPage(self); self.settings_page.themeChanged.connect(self.apply_theme); self.stack.addWidget(self.settings_page)
        # --- header toolbar
        tb = QToolBar("Header"); tb.setObjectName("header"); tb.setMovable(False); tb.setIconSize(QSize(20, 20)); self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        brand = QLabel(f"  {APP_NAME}  "); brand.setObjectName("h2"); tb.addWidget(brand); tb.addSeparator()
        for k in ("new", "open", "save", "export"): tb.addAction(self.a[k])
        tb.addSeparator(); tb.addAction(self.a["undo"]); tb.addAction(self.a["redo"]); tb.addSeparator(); tb.addAction(self.a["compare"])
        sp = QWidget(); sp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred); tb.addWidget(sp)
        for k in ("zout", "fit", "zin"): tb.addAction(self.a[k])
        self.zoom_lbl = QLabel("100%"); self.zoom_lbl.setMinimumWidth(52); self.zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter); tb.addWidget(self.zoom_lbl)

    def _build_workspace(self):
        lay = QHBoxLayout(self.work); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        # tool column
        tc = QFrame(); tc.setObjectName("toolcol"); tv = QVBoxLayout(tc); tv.setContentsMargins(5, 8, 5, 8); tv.setSpacing(3); self.toolgrp = QButtonGroup(self); self.toolbtn = {}
        for key, tip, ic, sc in TOOLS:
            b = QToolButton(); b.setCheckable(True); b.setIcon(icon(ic, self.icon_color(), 22)); b.setToolTip(tip); b.clicked.connect(lambda _=False, k=key: self.set_tool(k)); self.toolgrp.addButton(b); tv.addWidget(b); self.toolbtn[key] = b; self._icon_widgets.append((b, ic))
            a = QAction(self); a.setShortcut(QKeySequence(sc)); a.triggered.connect(lambda _=False, k=key: self.set_tool(k)); self.addAction(a)
        tv.addStretch(1); lay.addWidget(tc)
        # centre: options bar + tabs / empty state
        centre = QWidget(); cv = QVBoxLayout(centre); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(0)
        self.optbar = QFrame(); self.optbar.setObjectName("optbar"); self.optbar.setFixedHeight(46); self.optstack = QStackedWidget(); ol = QHBoxLayout(self.optbar); ol.setContentsMargins(10, 4, 10, 4); ol.addWidget(self.optstack); self._build_options(); cv.addWidget(self.optbar)
        self.cstack = QStackedWidget(); cv.addWidget(self.cstack, 1)
        empty = QWidget(); ev = QVBoxLayout(empty); ev.addStretch(1); t = QLabel("No image open"); t.setObjectName("h2"); t.setAlignment(Qt.AlignmentFlag.AlignCenter); ev.addWidget(t)
        s = QLabel("Create a project, open an image, or drop files here."); s.setObjectName("muted"); s.setAlignment(Qt.AlignmentFlag.AlignCenter); ev.addWidget(s)
        bl = QHBoxLayout(); bl.addStretch(1); n = QPushButton("New project"); n.clicked.connect(self.new_project); o = QPushButton("Open image"); o.setObjectName("primary"); o.clicked.connect(lambda: self.open_files()); bl.addWidget(n); bl.addWidget(o); bl.addStretch(1); ev.addLayout(bl); ev.addStretch(2)
        self.cstack.addWidget(empty)
        self.tabs = QTabWidget(); self.tabs.setDocumentMode(True); self.tabs.setTabsClosable(True); self.tabs.setMovable(True); self.tabs.tabCloseRequested.connect(self.close_tab); self.tabs.currentChanged.connect(self._tab_changed); self.cstack.addWidget(self.tabs)
        # right side: properties + layers
        self.side = QFrame(); self.side.setObjectName("panel"); sv = QVBoxLayout(self.side); sv.setContentsMargins(0, 0, 0, 0); sv.setSpacing(0)
        split = QSplitter(Qt.Orientation.Vertical); sv.addWidget(split)
        self.ptitle = QLabel(""); self.ptitle.setObjectName("h2"); self.pstack = QStackedWidget(); top = QWidget(); tl = QVBoxLayout(top); tl.setContentsMargins(12, 10, 0, 0); tl.addWidget(self.ptitle); tl.addWidget(self.pstack, 1)
        for key, cls in (("photo", ImagePanel), ("adjust", AdjustPanel), ("retouch", RetouchPanel), ("ai", AIPanel), ("doc", DocPanel), ("passport", PassportPanel), ("layout", LayoutPanel)):
            p = cls(self); self.panels[key] = p; sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(p); sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.pstack.addWidget(sc)
        self.layers = LayersPanel(self); split.addWidget(top); split.addWidget(self.layers); split.setStretchFactor(0, 3); split.setStretchFactor(1, 2)
        self.hsplit = QSplitter(Qt.Orientation.Horizontal); self.hsplit.addWidget(centre); self.hsplit.addWidget(self.side); self.hsplit.setStretchFactor(0, 1); self.hsplit.setSizes([1000, 340]); self.side.setMinimumWidth(290)
        lay.addWidget(self.hsplit, 1)

    def _build_options(self):
        o = self.opts; pages = {}
        def page(key, *widgets):
            w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(10)
            for x in widgets: h.addWidget(x)
            h.addStretch(1); self.optstack.addWidget(w); pages[key] = w
        def spin(lo, hi, val, key, suffix="", scale=1.0):
            s = QSpinBox(); s.setRange(lo, hi); s.setValue(int(val)); s.setSuffix(suffix); s.valueChanged.connect(lambda v: o.__setitem__(key, v * scale)); return s
        self.brush_chip = ColorChip(o["brush_color"]); self.brush_chip.colorChanged.connect(lambda c: o.__setitem__("brush_color", c)); self.bg_chip = ColorChip(o["bg_color"]); self.bg_chip.colorChanged.connect(lambda c: o.__setitem__("bg_color", c))
        self._size_spins, self._hard_spins = [], []
        def paint_controls():
            sz = spin(1, 1500, o["brush_size"], "brush_size", " px"); hd = spin(0, 100, 100, "brush_hardness", " %", 0.01); self._size_spins.append(sz); self._hard_spins.append(hd); return [QLabel("Size"), sz, QLabel("Hardness"), hd, QLabel("Opacity"), spin(1, 100, 100, "brush_opacity", " %", 0.01)]
        swap = QPushButton("Swap  (X)"); swap.clicked.connect(self.swap_colors); dflt = QPushButton("Black / white  (D)"); dflt.clicked.connect(self.default_colors)
        page("brush", *paint_controls(), QLabel("Foreground"), self.brush_chip, QLabel("Background"), self.bg_chip, swap, dflt, QLabel("[ ] = size, Shift+[ ] = hardness, Shift+click = straight line"))
        et = QCheckBox("Erase to transparent even on the Background layer"); et.toggled.connect(lambda v: o.__setitem__("erase_transparent", v))
        page("eraser", *paint_controls(), et)
        page("clone", *paint_controls(), QLabel("Alt+click sets the source, then paint to copy from it."))
        bt = spin(0, 255, o["bucket_tol"], "bucket_tol", ""); bc = QCheckBox("Contiguous"); bc.setChecked(True); bc.toggled.connect(lambda v: o.__setitem__("bucket_contig", v))
        page("bucket", QLabel("Tolerance"), bt, bc, QLabel("Opacity"), spin(1, 100, 100, "brush_opacity", " %", 0.01), QLabel("Foreground"), self.brush_chip, QLabel("Fills the area of similar colour (only inside a selection, if there is one)."))
        gk = QComboBox(); gk.addItem("Linear", "linear"); gk.addItem("Radial", "radial"); gk.currentIndexChanged.connect(lambda _: o.__setitem__("grad_kind", gk.currentData()))
        page("gradient", QLabel("Type"), gk, QLabel("Foreground"), self.brush_chip, QLabel("Background"), self.bg_chip, QLabel("Drag across the picture from the start colour to the end colour."))
        t = QLineEdit(o["text"]); t.setMinimumWidth(200); t.textChanged.connect(lambda v: o.__setitem__("text", v)); bold = QCheckBox("Bold"); bold.toggled.connect(lambda v: o.__setitem__("text_bold", v))
        self.text_chip = ColorChip(o["text_color"], True); self.text_chip.colorChanged.connect(lambda c: o.__setitem__("text_color", c))
        page("text", QLabel("Size"), spin(6, 1000, o["text_size"], "text_size", " px"), bold, self.text_chip, QLabel("Click the page and type. Click existing text to edit it."))
        sh = QComboBox(); [sh.addItem(n, k) for n, k in (("Rectangle", "rect"), ("Ellipse", "ellipse"), ("Line", "line"))]; sh.currentIndexChanged.connect(lambda _: o.__setitem__("shape", sh.currentData()))
        fc = ColorChip(o["shape_fill"], True); fc.colorChanged.connect(lambda c: o.__setitem__("shape_fill", c)); sc = ColorChip((0, 0, 0, 255), True)
        sw = spin(0, 100, 0, "shape_stroke_w", " px"); sc.colorChanged.connect(lambda c: o.__setitem__("shape_stroke", c if o["shape_stroke_w"] else None))
        sw.valueChanged.connect(lambda v: o.__setitem__("shape_stroke", sc.color() if v else None))
        page("shape", QLabel("Shape"), sh, QLabel("Fill"), fc, QLabel("Outline"), sc, sw, QLabel("Drag on the page."))
        asp = QComboBox(); self.asp = asp
        for n, w_, h_ in (("Free", 0, 0), ("1 : 1", 1, 1), ("35 x 45 mm", 35, 45), ("40 x 50 mm", 40, 50), ("45 x 55 mm", 45, 55), ("3 : 4", 3, 4), ("4 : 5", 4, 5), ("3 : 2", 3, 2), ("16 : 9", 16, 9)): asp.addItem(n, (w_, h_))
        asp.currentIndexChanged.connect(self._crop_ratio_changed)
        ok = QPushButton("Apply crop  (Enter)"); ok.setObjectName("primary"); ok.clicked.connect(lambda: self._cv(lambda c: c.apply_crop())); cn = QPushButton("Cancel  (Esc)"); cn.clicked.connect(lambda: self._cv(lambda c: c.cancel_crop()))
        page("crop", QLabel("Ratio"), asp, ok, cn, QLabel("Drag to draw, drag inside to move, drag edges to resize."))
        sa = QPushButton("Select all"); sa.clicked.connect(self.select_all); ds = QPushButton("Deselect"); ds.clicked.connect(self.deselect); iv = QPushButton("Inverse"); iv.clicked.connect(self.invert_selection)
        shp = QComboBox(); shp.addItem("Rectangle", "rect"); shp.addItem("Ellipse", "ellipse"); shp.currentIndexChanged.connect(lambda _: o.__setitem__("marquee", shp.currentData()))
        def mode_combo():
            c = QComboBox(); [c.addItem(n, k) for n, k in (("New selection", "new"), ("Add  (Shift)", "add"), ("Subtract  (Alt)", "sub"), ("Intersect  (Shift+Alt)", "inter"))]; c.currentIndexChanged.connect(lambda _: o.__setitem__("sel_mode", c.currentData())); self._mode_combos.append(c); return c
        self._mode_combos = []
        page("select", QLabel("Shape"), shp, mode_combo(), sa, ds, iv, QLabel("Drag. Delete clears, Ctrl+J copies to a new layer, brush / adjustments only touch the selection."))
        page("lasso", mode_combo(), ds, iv, QLabel("Hold the button and draw around what you want."))
        page("poly", mode_combo(), ds, iv, QLabel("Click the corners one by one; double-click, Enter or the first point closes the shape. Esc cancels."))
        wt = spin(0, 255, o["wand_tol"], "wand_tol", ""); wc = QCheckBox("Contiguous"); wc.setChecked(True); wc.toggled.connect(lambda v: o.__setitem__("wand_contig", v)); wa = QCheckBox("Sample all layers"); wa.setChecked(True); wa.toggled.connect(lambda v: o.__setitem__("wand_all", v))
        page("wand", QLabel("Tolerance"), wt, wc, wa, mode_combo(), ds, iv)
        po = QComboBox(); self.persp_out = po
        for n, spec in (("Automatic size", None), ("ID card 85.6 x 54 mm (NID)", (85.6, 54.0)), ("A4 page 210 x 297 mm", (210.0, 297.0)), ("Passport photo 35 x 45 mm", (35.0, 45.0)), ("Photo 4 x 6 in", (101.6, 152.4)), ("A5 148 x 210 mm", (148.0, 210.0))): po.addItem(n, spec)
        po.currentIndexChanged.connect(lambda _: o.__setitem__("persp_aspect", (po.currentData()[0] / po.currentData()[1]) if po.currentData() else None))
        rot = QPushButton("Turn 90"); rot.setToolTip("Turn the result a quarter turn (fixes an upside-down or sideways card)"); self.persp_rot_lbl = QLabel("0 deg")
        def turn(): o["persp_rot"] = (int(o.get("persp_rot", 0)) + 90) % 360; self.persp_rot_lbl.setText(f"{o['persp_rot']} deg")
        rot.clicked.connect(turn); det = QPushButton("Find corners"); det.clicked.connect(self.persp_detect); acard = QPushButton("Auto-crop ID card"); acard.setToolTip("One click: finds the card edges, straightens it and crops it to exact ID-1 size (85.6 x 54 mm)"); acard.clicked.connect(self.auto_crop_cards); pok = QPushButton("Apply  (Enter)"); pok.setObjectName("primary"); pok.clicked.connect(self.apply_perspective)
        page("perspective", QLabel("Output"), po, rot, self.persp_rot_lbl, det, acard, pok, QLabel("Drag the 4 white corners onto the corners of the card / paper."))
        auto = QCheckBox("Auto-select layer under cursor"); auto.setChecked(True); auto.toggled.connect(lambda v: o.__setitem__("autoselect", v)); page("move", auto, QLabel("Drag a layer to move it (it snaps to the page edges, centre and other layers; hold Alt to turn snapping off). Drag the white squares to resize (Shift = free). Layer menu: exact size in mm."))
        page("picker", QLabel("Click the image to pick a colour - it becomes the brush and text colour."))
        page("pan", QLabel("Drag to pan. Wheel scrolls, Ctrl+wheel zooms (Settings can change this). Holding Space pans with any tool."))
        page("zoom", QLabel("Click to zoom in, Alt+click to zoom out. Ctrl+0 fits the page, Ctrl+1 shows real pixels."))
        self._optpages = pages

    def _crop_ratio_changed(self, _):
        w, h = self.asp.currentData(); c = self.canvas()
        if c: c.set_crop_ratio(w, h); (c.set_crop_to_ratio_default() if w else None)

    def _build_menus(self):
        mb = self.menuBar(); A = self.a
        m = mb.addMenu("&File"); [m.addAction(A[k]) for k in ("new", "open")]; self.recent_menu = m.addMenu("Open recent"); self.recent_menu.aboutToShow.connect(self._fill_recent); m.addSeparator()
        [m.addAction(A[k]) for k in ("save", "saveas", "export")]; m.addAction("Export open documents as PDF...", self.export_open_as_pdf); m.addAction(A["print"]); m.addSeparator(); [m.addAction(A[k]) for k in ("close", "quit")]
        m = mb.addMenu("&Edit"); [m.addAction(A[k]) for k in ("undo", "redo")]; m.addSeparator(); [m.addAction(A[k]) for k in ("copy", "paste")]; m.addSeparator(); [m.addAction(A[k]) for k in ("selall", "desel")]
        m = mb.addMenu("&Select"); [m.addAction(A[k]) for k in ("selall", "desel", "invsel")]; m.addSeparator(); m.addAction("Feather...", lambda: self.selection_op("feather")); m.addAction("Expand...", lambda: self.selection_op("grow")); m.addAction("Contract...", lambda: self.selection_op("shrink")); m.addSeparator(); [m.addAction(A[k]) for k in ("viacopy", "viacut", "clearpx", "fillfg", "fillbg")]
        m = mb.addMenu("&Image"); P = self.panels["photo"]
        for t, f in (("Resize...", P.resize), ("Set DPI...", P.set_dpi), ("Rotate left", lambda: P._do("rotate90", False)), ("Rotate right", lambda: P._do("rotate90", True)), ("Flip horizontal", lambda: P._do("flip", True)), ("Flip vertical", lambda: P._do("flip", False)), ("Crop to selection", P.crop_sel), ("Rotate by angle...", self.rotate_angle), ("Auto-crop ID card (find edges)", self.auto_crop_cards)): m.addAction(t, f)
        m = mb.addMenu("&Layer"); L = self.panels["layout"]; LP = self.layers
        m.addAction("New empty layer", self.new_layer); m.addAction("Place image...", L.place); m.addAction("Add text...", L.add_text); m.addAction("Edit text / shape...", self.edit_layer_params); m.addSeparator()
        for t, f in (("Duplicate", LP._dup), ("Delete", LP._del), ("Merge down", LP._merge), ("Flatten image", LP._flat), ("Transform...", P.transform)): m.addAction(t, f)
        m.addSeparator(); m.addAction("Size and position (mm)...", self.layer_size_dialog); m.addAction("Fit layer to page", lambda: self._layer_fit("contain")); m.addAction("Fill page with layer", lambda: self._layer_fit("cover"))
        m.addAction("Rotate layer right", lambda: self._layer_op("rotate_layer90", True)); m.addAction("Rotate layer left", lambda: self._layer_op("rotate_layer90", False)); m.addAction("Flip layer horizontally", lambda: self._layer_op("flip_layer", True)); m.addSeparator()
        self.copyto_menu = m.addMenu("Copy layer to document"); self.copyto_menu.aboutToShow.connect(self._fill_copyto); m.addAction("Send picture to a new A4 page...", self.send_to_a4)
        m = mb.addMenu("&Print"); m.addAction("Passport / photo sheet...", lambda: self.print_sheet("passport")); m.addAction("Bank photo duet...", lambda: self.print_sheet("duet")); m.addAction("NID / ID card on A4...", lambda: self.print_sheet("nid")); m.addSeparator(); m.addAction(A["print"])
        m = mb.addMenu("&View"); [m.addAction(A[k]) for k in ("fit", "z100", "zprint", "zin", "zout", "compare", "panel", "theme")]
        m = mb.addMenu("&Workspace")
        for key, text, _ in NAV: m.addAction(text, lambda k=key: self.goto(k))
        m = mb.addMenu("&Help"); m.addAction("AI model setup", lambda: self.goto("settings")); m.addAction(A["about"])

    def _build_status(self):
        sb = self.statusBar(); self.info_lbl = QLabel("No image"); self.cur_lbl = QLabel(""); self.msg = QLabel(""); self.msg.setStyleSheet("color:#9aa3b2")
        self.task_lbl = QLabel(""); self.prog = QProgressBar(); self.prog.setFixedWidth(150); self.prog.setRange(0, 100); self.cancel_btn = QPushButton("Cancel"); self.cancel_btn.setFixedHeight(22)
        self.cancel_btn.clicked.connect(lambda: self._cur_task and self._cur_task.cancel()); [w.setVisible(False) for w in (self.task_lbl, self.prog, self.cancel_btn)]
        sb.addWidget(self.info_lbl); sb.addWidget(self.cur_lbl, 1); sb.addPermanentWidget(self.msg); sb.addPermanentWidget(self.task_lbl); sb.addPermanentWidget(self.prog); sb.addPermanentWidget(self.cancel_btn)
        self._msg_timer = QTimer(self); self._msg_timer.setSingleShot(True); self._msg_timer.timeout.connect(lambda: self.msg.setText(""))

    # ======================================================================= navigation / tools
    def goto(self, key):
        if key not in self.navbtn: return
        if self._nav in self.panels and key != self._nav: self.panels[self._nav].deactivate()
        self._nav = key; self.navbtn[key].setChecked(True)
        if key == "home": self.home.set_recent(self.settings.recent_existing()); self.stack.setCurrentIndex(0)
        elif key == "settings": self.settings_page.refresh(); self.stack.setCurrentIndex(2)
        else:
            self.stack.setCurrentIndex(1); idx = list(self.panels).index(key); self.pstack.setCurrentIndex(idx); self.ptitle.setText(self.panels[key].title); self._refresh_panels()
            if key == "adjust": self.panels["adjust"].preview()
        self._update_actions()

    def _home_action(self, key):
        if key == "new": self.new_project()
        elif key == "open": self.open_files()
        elif key in ("nid", "duet"): self.print_sheet(key)
        elif key == "retouch": self.goto("retouch")
        else: self.goto(key)

    def set_tool(self, tool):
        self._tool = tool; self.toolbtn[tool].setChecked(True)
        if tool in self._optpages: self.optstack.setCurrentWidget(self._optpages[tool])
        c = self.canvas()
        if c: c.set_tool(tool)
        if self._nav in ("home", "settings") and self.tabs.count(): self.goto("photo")

    def toggle_side(self): self.side.setVisible(not self.side.isVisible())
    def cycle_compare(self):
        c = self.canvas()
        if c: c.set_compare({"off": "split", "split": "before", "before": "off"}[c.compare])
    def _refresh_panels(self):
        p = self.panels.get(self._nav)
        if p: p.refresh()

    def apply_theme(self, name):
        self._theme = name; theme.apply_theme(QApplication.instance(), name); col = self.icon_color()
        for w, ic in self._icon_widgets: w.setIcon(icon(ic, col, 24 if w in self.navbtn.values() else 22))
        for i in range(self.tabs.count()): self.tabs.widget(i).set_theme_bg(theme.palette(name)["canvas"])
    def toggle_theme(self):
        n = "light" if self._theme == "dark" else "dark"; self.settings.set("theme", n); self.settings.save(); self.apply_theme(n)

    # ======================================================================= documents / tabs
    def open_document(self, doc, path=None):
        c = CanvasView(doc, self.opts, theme.palette(self._theme)["canvas"]); c.set_tool(self._tool)
        c.edited.connect(lambda lbl: self.after_edit(lbl)); c.activeChanged.connect(lambda: (self.layers.refresh(), self._refresh_panels())); c.zoomChanged.connect(lambda z: self.zoom_lbl.setText(f"{z * 100:.0f}%"))
        c.cursorInfo.connect(self._cursor_info); c.colorPicked.connect(self._color_picked); c.perspApply.connect(self.apply_perspective); c.filesDropped.connect(self.place_files); c.textRequested.connect(self.text_prompt); c.crossDrop.connect(lambda info, c=c: self._cross_drop(c, info))
        i = self.tabs.addTab(c, doc.name); self.tabs.setCurrentIndex(i); self.cstack.setCurrentWidget(self.tabs)
        if self._nav in ("home", "settings"): self.goto("photo")
        QTimer.singleShot(0, c.fit); self._update_tab_title(i); return c

    def _tab_changed(self, i):
        self.cstack.setCurrentWidget(self.tabs if self.tabs.count() else self.cstack.widget(0)); c = self.canvas()
        if c: c.set_tool(self._tool); self.zoom_lbl.setText(f"{c.zoom * 100:.0f}%"); self.layers.refresh(); self.panels["adjust"].deactivate() if self._nav != "adjust" else self.panels["adjust"].preview()
        else: self.layers.refresh(); self.zoom_lbl.setText("")
        self._refresh_panels(); self._status_info(); self._update_actions(); self._set_title()

    def _update_tab_title(self, i):
        if i < 0 or i >= self.tabs.count(): return
        d = self.tabs.widget(i).doc; self.tabs.setTabText(i, d.name + (" *" if d.dirty else "")); self._set_title()
    def _set_title(self):
        d = self.doc(); self.setWindowTitle(f"{d.name}{' *' if d.dirty else ''}  -  {APP_NAME}" if d else APP_NAME)
    def _status_info(self):
        d = self.doc()
        if d is None: self.info_lbl.setText("No image"); self.cur_lbl.setText(""); return
        wm, hm = d.size_mm(); self.info_lbl.setText(f"{d.w} x {d.h} px   |   {wm:.0f} x {hm:.0f} mm @ {d.dpi} DPI   |   {len(d.layers)} layer(s)")
    def _cursor_info(self, x, y, rgba):
        self.cur_lbl.setText(f"x {x}  y {y}" + (f"    RGBA {rgba[0]}, {rgba[1]}, {rgba[2]}, {rgba[3]}" if rgba else ""))
    def _color_picked(self, c):
        self.opts["brush_color"] = tuple(c); self.opts["text_color"] = tuple(c); self.brush_chip.set_color(c); self.text_chip.set_color(c); self.notify(f"Picked colour {c[0]}, {c[1]}, {c[2]}", "info")
    def _update_actions(self):
        d = self.doc(); has = d is not None; self.a["undo"].setEnabled(bool(has and d.can_undo())); self.a["redo"].setEnabled(bool(has and d.can_redo()))
        for k in ("save", "saveas", "export", "print", "close", "selall", "desel", "fit", "z100", "zprint", "zin", "zout", "compare"): self.a[k].setEnabled(has)

    def close_tab(self, i):
        if i < 0 or i >= self.tabs.count(): return True
        d = self.tabs.widget(i).doc
        if d.dirty:
            r = QMessageBox.question(self, APP_NAME, f"Save changes to '{d.name}'?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel: return False
            if r == QMessageBox.StandardButton.Save:
                self.tabs.setCurrentIndex(i)
                if not self.save(): return False
        self.recovery.clear(d.uid); self._auto_ver.pop(d.uid, None); w = self.tabs.widget(i); self.tabs.removeTab(i); w.deleteLater(); return True
    def closeEvent(self, e):
        while self.tabs.count():
            if not self.close_tab(self.tabs.count() - 1): e.ignore(); return
        self.settings.save(); e.accept()

    # ======================================================================= file operations
    def new_project(self):
        dlg = NewDocDialog(self)
        if dlg.exec():
            r = dlg.result_data(); self.open_document(Document.new(r["w"], r["h"], r["dpi"], r["bg"], r["name"], max_undo=self.settings.get("max_undo")))
    def edit_layer_params(self):
        """Re-edit a text layer's wording / size or a shape layer's size (they stay editable until painted on)."""
        d = self.require_doc(); L = d.active if d else None
        if L is None: return
        if L.kind == "text":
            t, ok = QInputDialog.getMultiLineText(self, "Edit text", "Text:", L.params.get("text", ""))
            if not ok or not t.strip(): return
            sz, ok2 = QInputDialog.getInt(self, "Edit text", "Size (px):", int(L.params.get("size", 64)), 6, 1000)
            if ok2: d.update_params(L.id, "Edit text", text=t, size=sz); self.after_edit("Edit text")
        elif L.kind == "shape":
            w, ok = QInputDialog.getInt(self, "Edit shape", "Width (px):", int(L.params.get("w", 200)), 2, 20000)
            if not ok: return
            h, ok = QInputDialog.getInt(self, "Edit shape", "Height (px):", int(L.params.get("h", 120)), 2, 20000)
            if ok: d.update_params(L.id, "Edit shape", w=w, h=h); self.after_edit()
        else: self.notify("Select a text or shape layer first (raster layers are plain pixels).", "warn")
    def new_layer(self):
        d = self.require_doc()
        if d: d.add_layer(Layer(to_rgba(np.zeros((d.h, d.w, 4), np.uint8)), f"Layer {len(d.layers) + 1}"), label="New layer"); self.after_edit()
    def open_files(self, files=None):
        if not files:
            files, _ = QFileDialog.getOpenFileNames(self, "Open", self.settings.get("export_dir") or "", OPEN_FILTER)
        for f in files or []:
            try:
                ext = os.path.splitext(f)[1].lower()
                if ext == ".rai": d = Document.load(f, max_undo=self.settings.get("max_undo"))
                elif ext == ".pdf": self._import_pdf(f); continue
                else: d = Document.open_image(f, max_undo=self.settings.get("max_undo"))
            except Exception as e: self.notify(f"Could not open {os.path.basename(f)}: {type(e).__name__}: {e}", "error"); continue
            self.settings.add_recent(f); self.open_document(d)
        self.settings.save()
    def _import_pdf(self, f):
        def done(pages):
            for i, im in enumerate(pages, 1): self.open_document(Document.from_image(im, f"{os.path.splitext(os.path.basename(f))[0]} p{i}", 200))
        self.run_task("Reading PDF", lambda ctx: docstudio.pdf_to_images(f, 200, ctx), done=done, fail=lambda e: self.notify(str(e), "warn" if isinstance(e, docstudio.Unavailable) else "error"))
    def _fill_recent(self):
        self.recent_menu.clear(); files = self.settings.recent_existing()
        for p in files: self.recent_menu.addAction(os.path.basename(p), lambda p=p: self.open_files([p]))
        if not files: self.recent_menu.addAction("(empty)").setEnabled(False)
        self.recent_menu.addSeparator(); self.recent_menu.addAction("Clear recent list", self.clear_recent).setEnabled(bool(files))
    def save(self):
        d = self.require_doc()
        if not d: return False
        if not d.path.lower().endswith(".rai"): return self.save_as()
        try: d.save(); self.recovery.clear(d.uid); self._update_tab_title(self.tabs.currentIndex()); self.notify("Saved.", "ok"); return True
        except Exception as e: self.notify(f"Save failed: {e}", "error"); return False
    def save_as(self):
        d = self.require_doc()
        if not d: return False
        p, _ = QFileDialog.getSaveFileName(self, "Save project", os.path.join(self.settings.get("export_dir") or "", d.name + ".rai"), "Ripon project (*.rai)")
        if not p: return False
        if not p.lower().endswith(".rai"): p += ".rai"
        try: d.save(p); d.name = os.path.splitext(os.path.basename(p))[0]; self.recovery.clear(d.uid); self.settings.add_recent(p); self.settings.save(); self._update_tab_title(self.tabs.currentIndex()); self.notify("Saved.", "ok"); return True
        except Exception as e: self.notify(f"Save failed: {e}", "error"); return False
    def export(self):
        d = self.require_doc()
        if not d: return
        dlg = ExportDialog(d, self)
        if not dlg.exec(): return
        ext, q, dpi = dlg.values(); p, _ = QFileDialog.getSaveFileName(self, "Export", os.path.join(self.settings.get("export_dir") or "", d.name + ext), f"*{ext}")
        if not p: return
        if not p.lower().endswith(ext): p += ext
        try: d.export(p, q, dpi); self.notify(f"Exported {os.path.basename(p)}", "ok")
        except Exception as e: self.notify(f"Export failed: {e}", "error")
    def export_open_as_pdf(self):
        ds = self.docs()
        if not ds: self.notify("Nothing is open.", "warn"); return
        p, _ = QFileDialog.getSaveFileName(self, "Export all open documents as one PDF", os.path.join(self.settings.get("export_dir") or "", "document.pdf"), "PDF (*.pdf)")
        if not p: return
        try: core.save_pdf([d.to_pil(background=(255, 255, 255)).convert("RGB") for d in ds], p, ds[0].dpi); self.notify(f"PDF with {len(ds)} page(s) saved.", "ok")
        except Exception as e: self.notify(f"PDF export failed: {e}", "error")
    def print_preview(self):
        d = self.require_doc()
        if not d: return
        from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
        pr = QPrinter(QPrinter.PrinterMode.HighResolution); wm, hm = d.size_mm()
        pr.setPageSize(QPageSize(QSizeF(wm, hm), QPageSize.Unit.Millimeter)); pr.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
        arr = np.ascontiguousarray(np.array(d.to_pil(background=(255, 255, 255)).convert("RGBA"))); qi = QImage(arr.data, d.w, d.h, d.w * 4, QImage.Format.Format_RGBA8888).copy()
        def paint(printer):
            p = QPainter(printer); r = printer.pageRect(QPrinter.Unit.DevicePixel); p.drawImage(QRectF(0, 0, r.width(), r.height()), qi); p.end()
        dlg = QPrintPreviewDialog(pr, self); dlg.setWindowTitle(f"Print preview - {wm:.0f} x {hm:.0f} mm @ {d.dpi} DPI"); dlg.paintRequested.connect(paint); dlg.resize(1100, 820); dlg.exec()

    # ======================================================================= edit
    def undo(self):
        d = self.doc()
        if d and d.can_undo():
            c = self.canvas(); c.clear_preview(); lbl = d.undo(); self.notify(f"Undid: {lbl}", "info"); self.after_edit()
    def redo(self):
        d = self.doc()
        if d and d.can_redo(): lbl = d.redo(); self.notify(f"Redid: {lbl}", "info"); self.after_edit()
    def select_all(self):
        d = self.require_doc()
        if d: d.select_all(); d.commit("Select all", dirty=False); self.after_edit()
    def invert_selection(self):
        d = self.require_doc()
        if d: d.invert_selection(); d.commit("Inverse selection", dirty=False); self.after_edit()
    def selection_op(self, kind):
        d = self.require_doc()
        if not d: return
        if not d.selection: self.notify("Make a selection first.", "warn"); return
        v, ok = QInputDialog.getInt(self, {"feather": "Feather", "grow": "Expand selection", "shrink": "Contract selection"}[kind], "Pixels:", 8, 1, 500)
        if not ok: return
        {"feather": lambda: d.feather_selection(v), "grow": lambda: d.grow_selection(v), "shrink": lambda: d.grow_selection(-v)}[kind](); d.commit("Selection", dirty=False); self.after_edit()
    def _remove_recent(self, p):
        self.settings.remove_recent(p); self.settings.save(); self.home.set_recent(self.settings.recent_existing())
    def clear_recent(self):
        self.settings.clear_recent(); self.settings.save(); self.home.set_recent([]); self.notify("Recent history cleared. Your files were not touched.", "ok")
    def clear_pixels(self):
        if self.stack.currentIndex() != 1: return                                                       # Delete on Home / Settings belongs to those pages
        d = self.doc(); L = d.active if d else None
        if L is None or not d.selection: self.notify("Make a selection first (Delete clears the selected pixels).", "warn"); return
        d.clear_selected(L.id, tuple(self.opts["bg_color"])); self.after_edit("Clear")
    def fill_selection(self, background=False):
        d = self.doc(); L = d.active if d else None
        if L is None: return
        d.fill_selected(L.id, tuple(self.opts["bg_color" if background else "brush_color"]), 1.0, "Fill with background colour" if background else "Fill with foreground colour"); self.after_edit("Fill")
    def layer_via_copy(self, cut=False):
        d = self.doc(); L = d.active if d else None
        if L is None: return
        if d.selection: d.layer_from_selection(L.id, cut, background=tuple(self.opts["bg_color"]))
        elif not cut: d.duplicate_layer(L.id)                                                         # Ctrl+J without a selection duplicates the layer, as in Photoshop
        else: return
        self.after_edit()
    def swap_colors(self):
        o = self.opts; o["brush_color"], o["bg_color"] = o["bg_color"], o["brush_color"]; self.brush_chip.set_color(o["brush_color"]); self.bg_chip.set_color(o["bg_color"])
    def default_colors(self):
        o = self.opts; o["brush_color"], o["bg_color"] = (0, 0, 0, 255), (255, 255, 255, 255); self.brush_chip.set_color(o["brush_color"]); self.bg_chip.set_color(o["bg_color"])
    def brush_step(self, f):
        o = self.opts; o["brush_size"] = int(max(1, min(1500, round(o["brush_size"] * f if abs(f - 1) > 0.01 else o["brush_size"]) + (1 if f > 1 and round(o["brush_size"] * f) == o["brush_size"] else 0) - (1 if f < 1 and round(o["brush_size"] * f) == o["brush_size"] else 0))))
        for sp in self._size_spins: sp.setValue(o["brush_size"])
        c = self.canvas()
        if c: c.update()
    def brush_hard(self, d):
        o = self.opts; o["brush_hardness"] = float(min(1.0, max(0.0, round(o["brush_hardness"] + d, 2))))
        for sp in self._hard_spins: sp.setValue(int(round(o["brush_hardness"] * 100)))
    def text_prompt(self, x, y, layer_id):
        """Text tool click: type the text in a dialog (new text at the click, or edit the text layer that was clicked)."""
        d = self.doc()
        if d is None: return
        L = d.layer(layer_id) if layer_id else None
        t, ok = QInputDialog.getMultiLineText(self, "Text", "Type the text:", L.params.get("text", "") if L is not None else "")
        if not ok or not t.strip(): return
        if L is not None: d.update_params(L.id, "Edit text", text=t); d.active_id = L.id; self.after_edit("Edit text")
        else:
            c = tuple(self.opts.get("text_color", (0, 0, 0, 255))); d.add_text(t, int(x), int(y), int(self.opts.get("text_size", 64)), c, bool(self.opts.get("text_bold", False))); self.after_edit("Add text")
    def deselect(self):
        d = self.doc()
        if d: d.clear_selection(); d.commit("Deselect", dirty=False); self.after_edit()
    def apply_wheel_setting(self, on):
        self.opts["wheel_zooms"] = bool(on); self.settings.set("wheel_zooms", bool(on)); self.settings.save()

    # ======================================================================= pages, perspective crop, placing pictures
    def print_sheet(self, kind):
        dlg = PrintSheetDialog(self, kind)
        if dlg.exec():
            for d in dlg.result_docs: self.open_document(d)
            self.notify(dlg.result_msg, "ok")
    def persp_detect(self):
        c = self.canvas()
        if c is None: self.notify("Open a picture first.", "warn"); return
        found, conf = c.auto_perspective()
        self.notify("Card / paper corners found - check them and press Enter." if found else "Could not find clear edges - drag the four corners by hand.", "ok" if found else "warn")
    def auto_crop_cards(self):
        """One click: find the card(s) in the picture, straighten each one and crop it to exact ID-1 size. One card -> the picture is replaced (Ctrl+Z undoes);
        two cards on one scan -> front and back open as two new documents."""
        d = self.require_doc()
        if not d: return
        rgb = np.array(d.to_pil(background=(255, 255, 255)).convert("RGB")); W, H = core.mm2px(85.6, 300), core.mm2px(54.0, 300); name = d.name
        def done(found):
            if not found: self.notify("No card found. Check that the whole card is visible, or use the Perspective crop tool (P) and drag the 4 corners.", "warn"); return
            crops = [persp_engine.perspective_crop(rgb, f["quad"], (W, H)) for f in found]
            if len(crops) == 1:
                d.replace_with_image(crops[0], "Auto-crop ID card"); d.dpi = 300; c = self.canvas(); c.fit(); self.after_edit("Auto-crop ID card"); self.notify(f"Card found (confidence {found[0]['confidence']:.0%}) and cropped to {W} x {H} px. Ctrl+Z restores the original.", "ok")
            else:
                for i, im in enumerate(crops): nd = Document.from_image(im, f"{name} - {'front' if i == 0 else 'back'}", 300); self.open_document(nd)
                self.notify(f"{len(crops)} cards found: opened as 'front' (first / upper) and 'back'. If they are the wrong way round, swap them in the print wizard.", "ok")
        self.run_task("Finding the card", lambda ctx: cards_engine.detect_cards(rgb, cards_engine.ID1_ASPECT, 2), done=done)
    def _tab_under(self, c, lx, ly):
        bar = self.tabs.tabBar(); gp = c.mapToGlobal(QPoint(int(lx), int(ly))); return bar.tabAt(bar.mapFromGlobal(gp))
    def _cross_drop(self, c, info):
        """A dragged layer / selection was released outside the page. Released on another document's tab -> a COPY goes into that document."""
        d = c.doc; lid = info["lid"]; L = d.layer(lid)
        try: idx = self._tab_under(c, info["x"], info["y"])
        except Exception: idx = -1
        dst = self.tabs.widget(idx).doc if (idx is not None and 0 <= idx < self.tabs.count() and self.tabs.widget(idx) is not c) else None
        if L is not None and dst is not None: d.copy_layer_to(lid, dst, fit=True)
        if info["lift"]: d.undo()                                                                        # take the lifted copy back: the source picture stays exactly as it was
        elif L is not None: L.x, L.y = info["pos0"]; d.invalidate()
        if dst is None: self.after_edit(); self.notify("Drop on the TAB of another open document to copy it there.", "warn"); return
        self.tabs.setCurrentIndex(idx); self.after_edit(); self.notify(f"Copied into '{dst.name}'. Drag it into place with the Move tool.", "ok")
    def apply_perspective(self):
        c, d = self.canvas(), self.doc()
        if c is None or d is None or c.persp is None: self.notify("Choose the Perspective crop tool and place the 4 corners first.", "warn"); return
        quad = np.array(c.persp, np.float32); spec = self.persp_out.currentData(); rot = int(self.opts.get("persp_rot", 0)); rgb = np.array(d.to_pil(background=(255, 255, 255)).convert("RGB"))
        def work(ctx):
            if spec: return persp_engine.perspective_crop(rgb, quad, (core.mm2px(spec[0], 300), core.mm2px(spec[1], 300)), extra_rotation=rot)
            return persp_engine.perspective_crop(rgb, quad, extra_rotation=rot)
        def done(out):
            d.replace_with_image(out, "Perspective crop")
            if spec: d.dpi = 300
            self.opts["persp_rot"] = 0; self.persp_rot_lbl.setText("0 deg"); c.persp = None; self.set_tool("move"); c.fit(); self.after_edit("Perspective crop"); self.notify(f"Straightened: {d.w} x {d.h} px ({d.size_mm()[0]:.1f} x {d.size_mm()[1]:.1f} mm). Undo (Ctrl+Z) brings the original back.", "ok")
        self.run_task("Perspective crop", work, done=done)
    def place_files(self, files, x, y):
        """Pictures dropped onto the page become layers at the drop point (bigger ones are scaled to fit the page)."""
        d = self.doc(); exts = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"); imgs = [f for f in files if f.lower().endswith(exts)]; rest = [f for f in files if f not in imgs]
        if rest: self.open_files(rest)
        if d is None or not imgs: return
        n = 0
        for i, f in enumerate(imgs):
            try: im = ImageOps.exif_transpose(Image.open(f)).convert("RGBA")
            except Exception as e: self.notify(f"Could not read {os.path.basename(f)}: {type(e).__name__}", "warn"); continue
            k = min(1.0, d.w * 0.9 / im.width, d.h * 0.9 / im.height)
            if k < 1.0: im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
            px = int(min(max(0, x - im.width / 2 + 30 * i), max(0, d.w - im.width))); py = int(min(max(0, y - im.height / 2 + 30 * i), max(0, d.h - im.height)))
            d.add_image_layer(im, os.path.splitext(os.path.basename(f))[0], px, py); n += 1
        if n: self.after_edit(); self.notify(f"Placed {n} picture(s). Drag to move, drag the white squares to resize, Layer > Size and position (mm) for exact size.", "ok")
    def copy_clipboard(self):
        d = self.doc(); L = d.active if d else None
        if L is None: return
        if d.selection:
            part = d.selection_layer(L.id)
            if part is not None: clip.set_image(np.array(part.pixels)); self.notify("Selection copied. Ctrl+V pastes it - here, in another document, or in another program.", "ok"); return
        try: clip.set_image(np.array(L.pixels)); self.notify("Layer copied. Paste it with Ctrl+V - here or in another document.", "ok")
        except Exception as e: self.notify(f"Could not copy: {type(e).__name__}", "warn")
    def paste_clipboard(self):
        try: a = clip.get_image()
        except Exception: a = None
        if a is None: self.notify("There is no picture on the clipboard.", "warn"); return
        d = self.doc()
        if d is None: self.open_document(Document.from_image(a, "Pasted picture", 300)); return
        if a.shape[1] > d.w or a.shape[0] > d.h: k = min(d.w * 0.9 / a.shape[1], d.h * 0.9 / a.shape[0]); a = np.array(Image.fromarray(a, "RGBA").resize((max(1, int(a.shape[1] * k)), max(1, int(a.shape[0] * k))), Image.LANCZOS))
        d.add_image_layer(a, "Pasted picture"); self.after_edit(); self.notify("Pasted as a new layer.", "ok")
    def layer_size_dialog(self):
        d = self.require_doc(); L = d.active if d else None
        if L is None: return
        dlg = LayerSizeDialog(d, L, self)
        if dlg.exec(): x, y, w, h = dlg.values(); d.set_layer_rect_mm(L.id, x, y, w, h); self.after_edit()
    def _layer_fit(self, mode):
        d = self.require_doc()
        if d and d.active: d.fit_layer(d.active_id, mode); self.after_edit()
    def _layer_op(self, name, arg):
        d = self.require_doc()
        if d and d.active: getattr(d, name)(d.active_id, arg); self.after_edit()
    def rotate_angle(self):
        d = self.require_doc()
        if not d: return
        a, ok = QInputDialog.getDouble(self, "Rotate by angle", "Degrees clockwise (use a negative number for anticlockwise):", 0.0, -180.0, 180.0, 1)
        if ok and abs(a) > 1e-6: d.rotate_image(a); self.canvas().fit(); self.after_edit()
    def _fill_copyto(self):
        self.copyto_menu.clear(); cur = self.doc(); others = [x for x in self.docs() if x is not cur]
        for x in others: self.copyto_menu.addAction(x.name, lambda x=x: self.copy_layer_to(x))
        if not others: self.copyto_menu.addAction("(no other document is open)").setEnabled(False)
    def copy_layer_to(self, dst):
        d = self.doc(); L = d.active if d else None
        if L is None or dst is None: return
        if d.selection:                                                                                  # only the selected part goes across
            part = d.selection_layer(L.id, L.name + " (part)")
            if part is not None: dst.add_layer(part, label="Paste selection"); part.x, part.y = (dst.w - part.w) // 2, (dst.h - part.h) // 2; dst.fit_layer(part.id, "contain", 0) if (part.w > dst.w or part.h > dst.h) else dst.commit("Paste selection")
        else: d.copy_layer_to(L.id, dst, fit=True, margin_px=0)
        for i in range(self.tabs.count()):
            if self.tabs.widget(i).doc is dst: self.tabs.setCurrentIndex(i); break
        self.after_edit(); self.notify(f"Copied to '{dst.name}'. Drag it into place.", "ok")
    def add_doc_as_layer(self, src, fit=True):
        """Put another open document (its whole picture) on the current page as a layer."""
        dst = self.doc()
        if dst is None or src is None or src is dst: self.notify("Open a page and another picture first.", "warn"); return
        dst.add_image_layer(src.to_pil(), src.name); L = dst.active
        if fit and (L.w > dst.w or L.h > dst.h): dst.fit_layer(L.id, "contain", 0)
        self.after_edit(); self.notify(f"Added '{src.name}' to the page.", "ok")
    def send_to_a4(self):
        d = self.require_doc()
        if not d: return
        mode, ok = QInputDialog.getItem(self, "Send to A4 page", "How big should the picture be on the page?", ["Fit to the page (recommended)", "Actual size (uses the picture's DPI)"], 0, False)
        if not ok: return
        wide = d.w > d.h; page = passport_engine.blank_page_document("A4", "Landscape" if wide else "Portrait", 300, None, f"A4 - {d.name}"); page.add_image_layer(d.to_pil(), d.name)
        L = page.active
        if mode.startswith("Actual"): k = 300.0 / max(1, d.dpi); page.resize_layer(L.id, L.w * k, L.h * k, (page.w - L.w * k) / 2, (page.h - L.h * k) / 2, "Actual size")
        else: page.fit_layer(L.id, "contain", core.mm2px(10, 300))
        self.open_document(page); self.notify("A4 page created. Drag the picture, drag the white squares to resize, or Layer > Size and position (mm).", "ok")

    # ======================================================================= tasks
    def _task_started(self, t):
        if (t.tag or {}).get("quiet"): return
        self._cur_task = t; self.task_lbl.setText(t.title); self.prog.setValue(0); self.prog.setRange(0, 0)
        [w.setVisible(True) for w in (self.task_lbl, self.prog, self.cancel_btn)]
    def _task_progress(self, t):
        if t is self._cur_task:
            self.prog.setRange(0, 100); self.prog.setValue(int(t.frac * 100)); self.task_lbl.setText(f"{t.title}  {t.msg}")
    def _task_finished(self, t):
        if t is self._cur_task:
            self._cur_task = None; [w.setVisible(False) for w in (self.task_lbl, self.prog, self.cancel_btn)]
            if t.state == "cancelled": self.notify("Cancelled.", "warn")

    # ======================================================================= drag & drop / about
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dropEvent(self, e): self.open_files([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
    def about(self):
        QMessageBox.about(self, f"About {APP_NAME}", f"<b>{APP_NAME}</b> {VERSION}<br>Photo editing, document cleanup, passport & ID sheets and print layout in one application.<br><br>Python, PySide6, OpenCV, NumPy, Pillow.")

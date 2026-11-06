"""Small reusable widgets and dialogs shared by every panel (one look, one behaviour)."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSlider, QPushButton, QColorDialog, QDialog, QFormLayout, QSpinBox,
                               QDoubleSpinBox, QComboBox, QCheckBox, QDialogButtonBox, QLineEdit, QFileDialog, QListWidget, QListWidgetItem)

def label(text, name=None, wrap=True):
    l = QLabel(text); l.setWordWrap(wrap)
    if name: l.setObjectName(name)
    return l

def row(*widgets, stretch_last=False):
    w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
    for x in widgets: h.addWidget(x)
    return w

class ColorChip(QPushButton):
    colorChanged = Signal(tuple)
    def __init__(self, color=(0, 0, 0, 255), alpha=False, parent=None):
        super().__init__(parent); self._c = tuple(color) + ((255,) if len(color) == 3 else ()); self._alpha = alpha
        self.setFixedSize(34, 24); self.setToolTip("Choose colour"); self.clicked.connect(self._pick); self._paint()
    def color(self): return self._c
    def set_color(self, c):
        self._c = tuple(int(v) for v in c) + ((255,) if len(c) == 3 else ()); self._paint()
    def _paint(self):
        r, g, b, a = self._c[:4]; self.setStyleSheet(f"QPushButton{{background: rgba({r},{g},{b},{a}); border: 1px solid #5a6270; border-radius: 4px;}}")
    def _pick(self):
        opt = QColorDialog.ColorDialogOption.ShowAlphaChannel if self._alpha else QColorDialog.ColorDialogOption(0)
        c = QColorDialog.getColor(QColor(*self._c[:4]), self, "Choose colour", opt)
        if c.isValid(): self.set_color((c.red(), c.green(), c.blue(), c.alpha())); self.colorChanged.emit(self._c)

class SliderRow(QWidget):
    """label + slider + live value. Works for int and float ranges (step defines the resolution)."""
    valueChanged = Signal(float)
    released = Signal()
    def __init__(self, text, lo, hi, default, step=1, kind="int", parent=None):
        super().__init__(parent); self.lo, self.step, self.kind = lo, step, kind
        v = QVBoxLayout(self); v.setContentsMargins(0, 2, 0, 2); v.setSpacing(2)
        top = QHBoxLayout(); self.name = QLabel(text); self.val = QLabel(); self.val.setObjectName("muted"); self.val.setAlignment(Qt.AlignmentFlag.AlignRight)
        top.addWidget(self.name); top.addStretch(1); top.addWidget(self.val); v.addLayout(top)
        self.s = QSlider(Qt.Orientation.Horizontal); self.s.setRange(0, max(1, int(round((hi - lo) / step)))); v.addWidget(self.s)
        self.default = default; self.setValue(default)
        self.s.valueChanged.connect(self._ch); self.s.sliderReleased.connect(self.released.emit)
        self.s.mouseDoubleClickEvent = lambda e: self.reset()          # double-click = back to default
    def value(self):
        v = self.lo + self.s.value() * self.step; return float(v) if self.kind == "float" else int(round(v))
    def setValue(self, v):
        self.s.blockSignals(True); self.s.setValue(int(round((v - self.lo) / self.step))); self.s.blockSignals(False); self._show()
    def reset(self): self.setValue(self.default); self.valueChanged.emit(self.value())
    def _show(self): v = self.value(); self.val.setText(f"{v:.2f}" if self.kind == "float" else str(v))
    def _ch(self, _): self._show(); self.valueChanged.emit(self.value())

def fmt_bytes(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB": return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024.0

class GroupPickDialog(QDialog):
    """A checklist of model groups (+ optional extra tick box and warning text) used by Backup and Restore."""
    def __init__(self, title, intro, groups, ok_text, warning="", extra=None, parent=None):
        super().__init__(parent); self.setWindowTitle(title); self.setMinimumWidth(560); v = QVBoxLayout(self); v.addWidget(label(intro))
        self.list = QListWidget(); v.addWidget(self.list)
        for g in groups:
            it = QListWidgetItem(f"{g['label']}   -   {g['files']} file(s), {fmt_bytes(g['bytes'])}"); it.setData(Qt.ItemDataRole.UserRole, g["key"]); it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable); it.setCheckState(Qt.CheckState.Checked); self.list.addItem(it)
        self.total = label(""); self.total.setObjectName("muted"); v.addWidget(self.total)
        if warning: w = label(warning); w.setStyleSheet("color:#f5a524;"); v.addWidget(w)
        self.extra = QCheckBox(extra) if extra else None
        if self.extra: v.addWidget(self.extra)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); bb.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); v.addWidget(bb)
        self._groups = groups; self.list.itemChanged.connect(lambda _: self._sum()); self._sum()
    def keys(self):
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked: out.append(it.data(Qt.ItemDataRole.UserRole))
        return out
    def _sum(self):
        ks = set(self.keys()); self.total.setText(f"Selected: {len(ks)} group(s), {fmt_bytes(sum(g['bytes'] for g in self._groups if g['key'] in ks))}")
    def extra_checked(self): return bool(self.extra and self.extra.isChecked())

PAPERS = ["A4", "A3", "A5", "A6", "Letter", "Legal", "Custom"]

class NewDocDialog(QDialog):
    PRESETS = [("A4 portrait  (2480 x 3508 @300)", 2480, 3508, 300), ("A4 landscape (3508 x 2480 @300)", 3508, 2480, 300), ("A5 portrait  (1748 x 2480 @300)", 1748, 2480, 300),
               ("Photo 4 x 6 in (1200 x 1800 @300)", 1200, 1800, 300), ("Passport 35 x 45 mm (413 x 531 @300)", 413, 531, 300), ("Square 1080", 1080, 1080, 72), ("Custom", 0, 0, 300)]
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("New project"); f = QFormLayout(self)
        self.preset = QComboBox(); [self.preset.addItem(p[0]) for p in self.PRESETS]
        self.w = QSpinBox(); self.w.setRange(1, 20000); self.h = QSpinBox(); self.h.setRange(1, 20000); self.dpi = QSpinBox(); self.dpi.setRange(36, 1200)
        self.bg = QComboBox(); self.bg.addItems(["White", "Transparent", "Black"]); self.name = QLineEdit("Untitled")
        for k, w in (("Name", self.name), ("Preset", self.preset), ("Width (px)", self.w), ("Height (px)", self.h), ("DPI", self.dpi), ("Background", self.bg)): f.addRow(k, w)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); f.addRow(bb)
        self.preset.currentIndexChanged.connect(self._p); self._p(0)
    def _p(self, i):
        n, w, h, d = self.PRESETS[i]
        if w: self.w.setValue(w); self.h.setValue(h); self.dpi.setValue(d)
        for x in (self.w, self.h): x.setEnabled(w == 0)
    def result_data(self):
        bg = {"White": (255, 255, 255, 255), "Transparent": None, "Black": (0, 0, 0, 255)}[self.bg.currentText()]
        return dict(w=self.w.value(), h=self.h.value(), dpi=self.dpi.value(), bg=bg, name=self.name.text() or "Untitled")

class ResizeDialog(QDialog):
    def __init__(self, w, h, dpi, parent=None):
        super().__init__(parent); self.setWindowTitle("Resize image"); f = QFormLayout(self); self.ar = w / float(h); self._lock = True
        self.w = QSpinBox(); self.w.setRange(1, 40000); self.w.setValue(w); self.h = QSpinBox(); self.h.setRange(1, 40000); self.h.setValue(h)
        self.keep = QCheckBox("Keep proportions"); self.keep.setChecked(True); self.dpi = QSpinBox(); self.dpi.setRange(36, 1200); self.dpi.setValue(dpi)
        self.mm = QLabel(); self.mm.setObjectName("muted")
        f.addRow("Width (px)", self.w); f.addRow("Height (px)", self.h); f.addRow("", self.keep); f.addRow("DPI", self.dpi); f.addRow("Print size", self.mm)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); f.addRow(bb)
        self.w.valueChanged.connect(self._wc); self.h.valueChanged.connect(self._hc); self.dpi.valueChanged.connect(self._mm); self._mm()
    def _wc(self, v):
        if self.keep.isChecked() and self._lock: self._lock = False; self.h.setValue(max(1, round(v / self.ar))); self._lock = True
        self._mm()
    def _hc(self, v):
        if self.keep.isChecked() and self._lock: self._lock = False; self.w.setValue(max(1, round(v * self.ar))); self._lock = True
        self._mm()
    def _mm(self): d = self.dpi.value(); self.mm.setText(f"{self.w.value() / d * 25.4:.1f} x {self.h.value() / d * 25.4:.1f} mm")
    def values(self): return self.w.value(), self.h.value(), self.dpi.value()

class TransformDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("Transform layer"); f = QFormLayout(self)
        self.scale = QDoubleSpinBox(); self.scale.setRange(1, 2000); self.scale.setValue(100); self.scale.setSuffix(" %")
        self.angle = QDoubleSpinBox(); self.angle.setRange(-360, 360); self.angle.setDecimals(1); self.angle.setSuffix(" deg")
        f.addRow("Scale", self.scale); f.addRow("Rotate (clockwise)", self.angle)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); f.addRow(bb)
    def values(self): return self.scale.value() / 100.0, self.angle.value()

class ExportDialog(QDialog):
    FORMATS = [("PNG (lossless, keeps transparency)", ".png"), ("JPEG (photos)", ".jpg"), ("WebP", ".webp"), ("TIFF", ".tif"), ("BMP", ".bmp"), ("PDF (one page)", ".pdf")]
    def __init__(self, doc, parent=None):
        super().__init__(parent); self.setWindowTitle("Export"); f = QFormLayout(self); self.fmt = QComboBox(); [self.fmt.addItem(a) for a, _ in self.FORMATS]
        self.q = SliderRow("JPEG / WebP quality", 40, 100, 92); self.dpi = QSpinBox(); self.dpi.setRange(36, 1200); self.dpi.setValue(doc.dpi)
        info = QLabel(f"{doc.w} x {doc.h} px   -   {doc.w / doc.dpi * 25.4:.0f} x {doc.h / doc.dpi * 25.4:.0f} mm at {doc.dpi} DPI"); info.setObjectName("muted")
        f.addRow(info); f.addRow("Format", self.fmt); f.addRow(self.q); f.addRow("DPI metadata", self.dpi)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); bb.button(QDialogButtonBox.StandardButton.Ok).setText("Choose file..."); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); f.addRow(bb)
    def values(self): return self.FORMATS[self.fmt.currentIndex()][1], self.q.value(), self.dpi.value()

"""Print-sheet wizards (passport photos, Bank Photo Duet, NID / ID card on A4) and the exact size / position dialog for layers."""
import os
import numpy as np
from PIL import Image, ImageOps
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QWidget, QLabel, QComboBox, QPushButton, QDoubleSpinBox, QSpinBox, QCheckBox,
                               QDialogButtonBox, QFileDialog, QGroupBox)
from ..engine import passport, perspective, core, cards
from .widgets import label, row, PAPERS

IMG_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)"

class ImageSource(QWidget):
    """Pick a picture: one of the open documents, or a file from disk."""
    def __init__(self, main, title, placeholder="(choose a picture)", use_current=False):
        super().__init__(); self.main = main; self._file = ""; self._override = None; self.placeholder, self.use_current = placeholder, use_current; h = QHBoxLayout(self); h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel(title)); self.combo = QComboBox(); h.addWidget(self.combo, 1); self.btn = QPushButton("Browse..."); self.btn.clicked.connect(self._browse); h.addWidget(self.btn); self.reload()
    def reload(self):
        self.combo.clear(); self.combo.addItem(self.placeholder, None); cur = self.main.doc()
        for d in self.main.docs():
            self.combo.addItem(f"Open: {d.name}", d)
            if self.use_current and d is cur and not self._file: self.combo.setCurrentIndex(self.combo.count() - 1)
        if self._file: self.combo.addItem(f"File: {os.path.basename(self._file)}", self._file); self.combo.setCurrentIndex(self.combo.count() - 1)
    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose a picture", self.main.settings.get("export_dir") or "", IMG_FILTER)
        if p: self._file = p; self.reload()
    def set_rgb(self, arr): self._override = np.ascontiguousarray(arr[..., :3])             # used by tests
    def rgb(self):
        if self._override is not None: return self._override
        data = self.combo.currentData()
        if data is None: return None
        if isinstance(data, str): return np.array(ImageOps.exif_transpose(Image.open(data)).convert("RGB"))
        return np.array(data.to_pil(background=(255, 255, 255)).convert("RGB"))
    def name(self): return self.combo.currentText()

class PrintSheetDialog(QDialog):
    TITLES = {"passport": "Passport / photo sheet", "duet": "Bank photo duet", "nid": "NID / ID card - A4 print"}
    def __init__(self, main, kind):
        super().__init__(main); self.main, self.kind = main, kind; self.result_docs, self.result_msg = [], ""; self.setWindowTitle(self.TITLES[kind]); self.setMinimumWidth(520); v = QVBoxLayout(self)
        intro = {"passport": "Pick the photo, the size and the number of copies. The result is an A4 sheet (one layer per photo).",
                 "duet": "Two photos side by side in one duet (whole duet 1.9 x 1.5 inch by default), repeated to fill the A4 sheet.",
                 "nid": "Pick the FRONT and the BACK picture of the card (a photo of the card on a table is fine). The card is straightened and printed at exact size on A4."}[kind]
        v.addWidget(label(intro, "muted")); self.src = []
        for t, ph, cur in {"passport": [("Photo", "(choose a picture)", True)], "duet": [("Photo A", "(choose a picture)", True), ("Photo B", "(same as Photo A)", False)], "nid": [("Front", "(choose the front)", True), ("Back", "(choose the back)", False)]}[kind]:
            s = ImageSource(main, t, ph, cur); self.src.append(s); v.addWidget(s)
        g = QGroupBox("Size"); f = QFormLayout(g); v.addWidget(g)
        self.w = QDoubleSpinBox(); self.h = QDoubleSpinBox(); self.n = QSpinBox(); self.n.setRange(1, 500)
        for s_ in (self.w, self.h): s_.setRange(10, 400); s_.setDecimals(1); s_.setSuffix(" mm")
        if kind == "passport":
            self.preset = QComboBox(); [self.preset.addItem(n, (a, b)) for n, a, b in passport.PRESETS[:-1]]
            for n, a, b in main.settings.custom_presets(): self.preset.addItem(f"{n}  ({a:g} x {b:g} mm)", (a, b))
            self.preset.addItem("Custom", (0, 0)); self.preset.currentIndexChanged.connect(self._preset); f.addRow("Photo size", self.preset); self.n.setValue(8); f.addRow("Copies", self.n); self._preset()
        elif kind == "duet":
            self.w.setRange(0.5, 10); self.h.setRange(0.5, 10); self.w.setDecimals(2); self.h.setDecimals(2); self.w.setSuffix(" in"); self.h.setSuffix(" in"); self.w.setValue(1.9); self.h.setValue(1.5)
            self.arr = QComboBox(); [self.arr.addItem(a, b) for a, b in (("Side by side", "side"), ("Stacked", "stack"), ("Best fit", "auto"))]; self.between = QDoubleSpinBox(); self.between.setRange(0, 20); self.between.setSuffix(" mm")
            f.addRow("Whole duet W", self.w); f.addRow("Whole duet H", self.h); f.addRow("Layout", self.arr); f.addRow("Gap between the two photos", self.between); self.n.setValue(12); f.addRow("Number of duets", self.n)
        else:
            self.w.setValue(passport.ID1_MM[0]); self.h.setValue(passport.ID1_MM[1]); f.addRow("Card width", self.w); f.addRow("Card height", self.h)
            self.arr = QComboBox(); [self.arr.addItem(a, b) for a, b in (("Back below the front", "stack"), ("Back beside the front", "side"))]; f.addRow("Layout", self.arr); self.n.setValue(1); f.addRow("Number of front + back sets", self.n)
            self.auto = QCheckBox("Find the card edges and straighten each picture automatically"); self.auto.setChecked(True); f.addRow(self.auto)
            self.one = QCheckBox("Both sides are in the FRONT picture (upper / left card = front, the other = back)"); f.addRow(self.one); self.swap = QCheckBox("Swap front and back"); f.addRow(self.swap)
            self.turn = QCheckBox("Allow turning the cards 90 deg to fit more"); f.addRow(self.turn)
        g2 = QGroupBox("Page"); f2 = QFormLayout(g2); v.addWidget(g2)
        self.paper = QComboBox(); self.paper.addItems(PAPERS[:-1]); self.orient = QComboBox(); self.orient.addItems(["Portrait", "Landscape"])
        self.margin = QDoubleSpinBox(); self.gap = QDoubleSpinBox(); self.border = QDoubleSpinBox(); self.dpi = QSpinBox(); self.dpi.setRange(100, 1200); self.dpi.setValue(300)
        for s_, val in ((self.margin, 15.0 if kind == "nid" else 5.0), (self.gap, 10.0 if kind == "nid" else 2.0), (self.border, 0.2 if kind == "nid" else 0.0)): s_.setRange(0, 50); s_.setDecimals(1); s_.setSuffix(" mm"); s_.setValue(val)
        self.cut = QCheckBox("Cut marks"); f2.addRow("Paper", row(self.paper, self.orient)); f2.addRow("Margin", self.margin); f2.addRow("Gap", self.gap); f2.addRow("Thin border", self.border); f2.addRow("DPI", self.dpi); f2.addRow(self.cut)
        self.msg = label(""); self.msg.setStyleSheet("color:#f5a524;"); v.addWidget(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); bb.button(QDialogButtonBox.StandardButton.Ok).setText("Make the A4 sheet"); bb.accepted.connect(self._ok); bb.rejected.connect(self.reject); v.addWidget(bb)
    def _preset(self, *_):
        a, b = self.preset.currentData(); custom = (a == 0)
        if not custom: self.w.setValue(a); self.h.setValue(b)
        self.w.setEnabled(custom); self.h.setEnabled(custom)
    def _ok(self):
        try: self.result_docs, self.result_msg = self.build()
        except ValueError as e: self.msg.setText(str(e)); return
        except Exception as e: self.msg.setText(f"{type(e).__name__}: {e}"); return
        self.accept()
    def build(self):
        """-> (list of Documents, message). Raises ValueError with a readable text."""
        k = self.kind; common = dict(paper=self.paper.currentText(), orientation=self.orient.currentText(), margin=self.margin.value(), gap=self.gap.value(), dpi=self.dpi.value(), border_mm=self.border.value(), cut_marks=self.cut.isChecked())
        a = self.src[0].rgb()
        if a is None: raise ValueError("Choose a picture first.")
        if k == "passport":
            docs, info = passport.make_sheet_documents(a, self.w.value(), self.h.value(), self.n.value(), **common); return docs, f"Built {len(docs)} sheet(s), {info['capacity']} photos fit per page."
        if k == "duet":
            b = self.src[1].rgb(); docs, info = passport.make_duet_documents(a, b, self.w.value() * 25.4, self.h.value() * 25.4, self.n.value(), between=self.between.value(), arrangement=self.arr.currentData(), **common)
            return docs, f"Built {len(docs)} sheet(s), {info['capacity']} duets fit per page."
        cw, ch = self.w.value(), self.h.value(); dpi = self.dpi.value(); notes = []
        if self.one.isChecked():
            found = cards.detect_cards(a, cw / ch, 2, min_conf=0.4)
            if len(found) < 2: raise ValueError(f"Found {len(found)} card(s) in the picture - two are needed. Make sure both cards are fully visible with a little space between them.")
            a, b = (perspective.perspective_crop(a, f["quad"], (core.mm2px(cw, dpi), core.mm2px(ch, dpi))) for f in found); notes = ["front: detected", "back: detected"]
            if self.swap.isChecked(): a, b = b, a
            common.pop("gap"); docs, info = passport.make_id_card_documents(a, b, cw, ch, self.n.value(), gap=self.gap.value(), arrangement=self.arr.currentData(), allow_rotate=self.turn.isChecked(), **common)
            return docs, f"Built {len(docs)} A4 sheet(s) at {dpi} DPI  ({'; '.join(notes)}). Check the result, then File > Export or Print."
        b = self.src[1].rgb()
        if b is None: raise ValueError("Choose the BACK picture too.")
        if self.swap.isChecked(): a, b = b, a
        if self.auto.isChecked():
            fa, ia = perspective.card_from_photo(a, cw, ch, dpi); fb, ib = perspective.card_from_photo(b, cw, ch, dpi); a, b = fa, fb
            notes = [f"{n}: {ii['method'].replace('-', ' ')}" for n, ii in (("front", ia), ("back", ib))]
        common.pop("gap"); docs, info = passport.make_id_card_documents(a, b, cw, ch, self.n.value(), gap=self.gap.value(), arrangement=self.arr.currentData(), allow_rotate=self.turn.isChecked(), **common)
        return docs, f"Built {len(docs)} A4 sheet(s) at {dpi} DPI" + (f"  ({'; '.join(notes)})" if notes else "") + ". Check the result, then File > Export or Print."

class LayerSizeDialog(QDialog):
    """Exact size and position of the selected layer in millimetres (what a print shop needs)."""
    def __init__(self, doc, layer, parent=None):
        super().__init__(parent); self.doc, self.layer = doc, layer; self.setWindowTitle("Layer size and position"); f = QFormLayout(self); x, y, w, h = doc.layer_rect_mm(layer.id); self.ratio = (w / h) if h else 1.0; self._busy = False
        self.sp = {}
        for key, val in (("X", x), ("Y", y), ("Width", w), ("Height", h)):
            s = QDoubleSpinBox(); s.setRange(-5000, 5000); s.setDecimals(2); s.setSuffix(" mm"); s.setValue(val); self.sp[key] = s; f.addRow(key, s)
        self.keep = QCheckBox("Keep proportions"); self.keep.setChecked(True); f.addRow(self.keep); self.sp["Width"].valueChanged.connect(self._w); self.sp["Height"].valueChanged.connect(self._h)
        pw, ph = doc.size_mm(); f.addRow(QLabel(f"Page: {pw:.1f} x {ph:.1f} mm at {doc.dpi} DPI"))
        b = QHBoxLayout(); [b.addWidget(self._mk(t, fn)) for t, fn in (("Fit page", lambda: self._fit("contain")), ("Fill page", lambda: self._fit("cover")), ("Centre", self._centre), ("ID-1 card", lambda: self._set(85.6, 54.0)))]; f.addRow(b)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); f.addRow(bb)
    def _mk(self, t, fn): b = QPushButton(t); b.clicked.connect(lambda: fn()); return b
    def _w(self, v):
        if self.keep.isChecked() and not self._busy: self._busy = True; self.sp["Height"].setValue(v / self.ratio if self.ratio else v); self._busy = False
    def _h(self, v):
        if self.keep.isChecked() and not self._busy: self._busy = True; self.sp["Width"].setValue(v * self.ratio); self._busy = False
    def _set(self, w, h):
        self._busy = True; self.sp["Width"].setValue(w); self.sp["Height"].setValue(h); self._busy = False; self.ratio = w / h
    def _fit(self, mode):
        pw, ph = self.doc.size_mm()
        w = min(pw, ph * self.ratio) if mode == "contain" else max(pw, ph * self.ratio); h = w / self.ratio; self._set(w, h); self.sp["X"].setValue((pw - w) / 2); self.sp["Y"].setValue((ph - h) / 2)
    def _centre(self):
        pw, ph = self.doc.size_mm(); self.sp["X"].setValue((pw - self.sp["Width"].value()) / 2); self.sp["Y"].setValue((ph - self.sp["Height"].value()) / 2)
    def values(self): return tuple(self.sp[k].value() for k in ("X", "Y", "Width", "Height"))

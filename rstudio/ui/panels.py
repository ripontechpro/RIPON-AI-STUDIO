"""Right-hand panels. Each one is a thin UI over the engine: it collects options, runs the engine function through main.run_task() and
puts the result back into the shared Document. `main` is the MainWindow (see its 'panel API' section)."""
import os
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QListWidget,
                               QListWidgetItem, QFileDialog, QInputDialog, QMessageBox, QGroupBox, QGridLayout, QLineEdit)
from ..engine import adjust, docstudio, passport, ai as aimod
from ..engine.document import Layer, to_rgba, composite_layers
from ..engine import restore as restoremod, photofix, retouch as retouch_engine, export as export_engine
from ..engine.ai import AIUnavailable
from .widgets import label, row, SliderRow, ColorChip, ResizeDialog, TransformDialog, PAPERS
from ..engine import core

IMG_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)"

def _vbox(parent, margin=10):
    v = QVBoxLayout(parent); v.setContentsMargins(margin, margin, margin, margin); v.setSpacing(6); return v

def _btn(text, slot=None, primary=False, tip=""):
    b = QPushButton(text)
    if primary: b.setObjectName("primary")
    if tip: b.setToolTip(tip)
    if slot: b.clicked.connect(slot)
    return b

def _flat_rgb(doc):
    """Whole picture as RGB uint8, transparency flattened onto white (what a scanner / printer would see)."""
    return np.array(doc.to_pil(background=(255, 255, 255)).convert("RGB"))

class BasePanel(QWidget):
    title = ""
    def __init__(self, main): super().__init__(); self.main = main
    def refresh(self): pass
    def deactivate(self): pass

# ------------------------------------------------------------------------------------------------ Photo Editor: image
class ImagePanel(BasePanel):
    title = "Image"
    def __init__(self, main):
        super().__init__(main); v = _vbox(self)
        v.addWidget(label("IMAGE", "section")); self.info = label("", "muted"); v.addWidget(self.info)
        g = QGridLayout(); g.setSpacing(6)
        items = [("Resize...", self.resize), ("Set DPI...", self.set_dpi), ("Rotate left", lambda: self._do("rotate90", False)), ("Rotate right", lambda: self._do("rotate90", True)),
                 ("Flip horizontal", lambda: self._do("flip", True)), ("Flip vertical", lambda: self._do("flip", False)), ("Crop to selection", self.crop_sel), ("Transform layer...", self.transform)]
        for i, (t, f) in enumerate(items): g.addWidget(_btn(t, f), i // 2, i % 2)
        v.addLayout(g); v.addWidget(label("TOOLS", "section"))
        v.addWidget(label("Crop (C), Selection (M), Brush (B), Eraser (E), Text (T), Shapes (U), Colour picker (I), Move (V), Pan (H or hold Space). "
                          "Scroll to zoom, Enter applies a crop, Esc cancels.", "muted")); v.addStretch(1)
    def refresh(self):
        d = self.main.doc()
        if d is None: self.info.setText("No image open."); return
        wm, hm = d.size_mm(); self.info.setText(f"{d.w} x {d.h} px\n{wm:.1f} x {hm:.1f} mm at {d.dpi} DPI\n{len(d.layers)} layer(s)")
    def _do(self, what, arg):
        d = self.main.require_doc()
        if d: getattr(d, what)(arg); self.main.canvas().fit(); self.main.after_edit(); 
    def resize(self):
        d = self.main.require_doc()
        if not d: return
        dlg = ResizeDialog(d.w, d.h, d.dpi, self)
        if dlg.exec():
            w, h, dpi = dlg.values(); d.dpi = dpi; d.resize(w, h); self.main.canvas().fit(); self.main.after_edit()
    def set_dpi(self):
        d = self.main.require_doc()
        if not d: return
        v, ok = QInputDialog.getInt(self, "Set DPI", "Print resolution (pixels are not changed):", d.dpi, 36, 1200)
        if ok: d.dpi = v; d.commit("Set DPI"); self.main.after_edit()
    def crop_sel(self):
        d = self.main.require_doc()
        if not d: return
        if not d.selection: self.main.notify("Make a selection first (Selection tool, M).", "warn"); return
        d.crop(*d.selection); self.main.canvas().fit(); self.main.after_edit()
    def transform(self):
        d = self.main.require_doc()
        if not d or not d.active: return
        dlg = TransformDialog(self)
        if dlg.exec():
            s, a = dlg.values(); d.transform_layer(d.active_id, s, a); self.main.after_edit()

# ------------------------------------------------------------------------------------------------ Adjustments
SLOW = {"denoise"}      # not previewed live; has its own Preview button

class AdjustPanel(BasePanel):
    title = "Adjustments"
    def __init__(self, main):
        super().__init__(main); v = _vbox(self); self._gen = 0; self._rows = {}
        v.addWidget(label("ADJUSTMENT", "section")); self.combo = QComboBox(); [self.combo.addItem(a.label, a.key) for a in adjust.ADJUSTMENTS.values()]; v.addWidget(self.combo)
        self.tip = label("", "muted"); v.addWidget(self.tip)
        self.box = QWidget(); self.boxl = QVBoxLayout(self.box); self.boxl.setContentsMargins(0, 0, 0, 0); v.addWidget(self.box)
        self.live = QCheckBox("Live preview"); self.live.setChecked(True); v.addWidget(self.live)
        self.sel_note = label("", "muted"); v.addWidget(self.sel_note)
        v.addWidget(row(_btn("Reset", self.reset), _btn("Preview", lambda: self.preview(force=True)), _btn("Apply", self.apply, primary=True)))
        v.addWidget(label("Double-click a slider to reset it. Use the Before/After button in the top bar to compare. With a selection, only the selected area changes.", "muted")); v.addStretch(1)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(90); self.timer.timeout.connect(self.preview)
        self.combo.currentIndexChanged.connect(lambda _: self._select()); self.live.toggled.connect(lambda on: self.preview() if on else self._clear()); self._select()
    def key(self): return self.combo.currentData()
    def _select(self):
        while self.boxl.count():
            it = self.boxl.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        adj = adjust.ADJUSTMENTS[self.key()]; self._rows = {}; self.tip.setText(adj.tip)
        for p in adj.params:
            r = SliderRow(p.label, p.lo, p.hi, p.default, p.step, p.kind); r.valueChanged.connect(lambda _: self.timer.start()); self.boxl.addWidget(r); self._rows[p.key] = r
        if not adj.params: self.boxl.addWidget(label("No settings.", "muted"))
        self._clear(); self.timer.start()
    def params(self): return {k: r.value() for k, r in self._rows.items()}
    def reset(self):
        for r in self._rows.values(): r.setValue(r.default)
        self.preview()
    def _clear(self):
        cv = self.main.canvas()
        if cv: cv.clear_preview()
    def refresh(self):
        d = self.main.doc(); self.sel_note.setText("Selection active: adjustment affects the selected area only." if d and d.selection else "")
    def deactivate(self): self.timer.stop(); self._gen += 1; self._clear()
    def preview(self, force=False):
        cv, d = self.main.canvas(), self.main.doc()
        if cv is None or d is None or d.active is None: return
        key = self.key()
        if not force and (not self.live.isChecked() or key in SLOW): return
        L = d.active; adj = adjust.ADJUSTMENTS[key]; params = self.params(); arr = np.array(L.pixels); self._gen += 1; gen = self._gen; lid = L.id
        def done(res):
            if gen != self._gen or self.main.canvas() is not cv or cv.doc.layer(lid) is None: return
            cv.set_preview({lid: cv.doc.masked(lid, res)})
        self.main.run_task("Preview " + adj.label, lambda ctx: adj.apply(arr, **params), done=done, quiet=not force)
    def apply(self):
        d = self.main.require_doc()
        if not d or d.active is None: return
        L = d.active
        if L.locked: self.main.notify("This layer is locked.", "warn"); return
        adj = adjust.ADJUSTMENTS[self.key()]; params = self.params(); arr = np.array(L.pixels); lid = L.id; self._gen += 1
        def done(res):
            cv = self.main.canvas(); cv.clear_preview(); d.apply_to_layer(lid, lambda a: res, adj.label); self.main.after_edit(adj.label)
        self.main.run_task("Applying " + adj.label, lambda ctx: adj.apply(arr, **params), done=done)

# ------------------------------------------------------------------------------------------------ Retouch (Photo Doctor, skin, red eye, online export) - ported from the earlier Photostudio
class RetouchPanel(BasePanel):
    title = "Retouch"
    def __init__(self, main):
        super().__init__(main); v = _vbox(self)
        v.addWidget(label("PHOTO DOCTOR", "section")); self.strength = SliderRow("Strength", 0, 100, 100); v.addWidget(self.strength)
        v.addWidget(row(_btn("Analyze", self.analyze), _btn("Auto fix", self.auto_fix, True))); self.report = label("", "muted"); v.addWidget(self.report)
        v.addWidget(label("Fixes only what is wrong (colour cast, exposure, dark shadows, noise, softness, red eyes). A good picture is left alone. The result is a new layer; your original stays below.", "muted"))
        v.addWidget(label("SKIN", "section")); self.smooth = SliderRow("Smoothing", 0, 100, 50); self.tone = SliderRow("Tone-up", 0, 100, 20); self.shine = SliderRow("Shine fix", 0, 100, 50); self.sens = SliderRow("Spot sensitivity", 0, 100, 50)
        for r in (self.smooth, self.tone, self.shine, self.sens): v.addWidget(r)
        self.spots = QCheckBox("Remove small spots"); self.spots.setChecked(True); v.addWidget(self.spots); v.addWidget(_btn("Retouch skin", self.skin, True)); v.addWidget(_btn("Remove red eyes", self.red_eye))
        v.addWidget(label("Skin only: eyes, eyebrows and mouth are never smoothed. Needs a face looking at the camera.", "muted"))
        v.addWidget(label("SAVE FOR ONLINE FORMS", "section")); self.kb = QSpinBox(); self.kb.setRange(10, 5000); self.kb.setValue(100); self.kb.setSuffix(" KB"); v.addWidget(row(QLabel("Largest file size"), self.kb))
        v.addWidget(_btn("Save JPG under this size...", self.save_kb)); self.cap = QLineEdit(); self.cap.setPlaceholderText("Caption: name, date, ID number ..."); v.addWidget(self.cap); v.addWidget(_btn("Add caption bar under the picture", self.caption))
        self.wm = QLineEdit(); self.wm.setPlaceholderText("Watermark text"); v.addWidget(self.wm); v.addWidget(_btn("Add watermark layer", self.watermark)); v.addStretch(1)
    def _fail(self, e):
        if isinstance(e, restoremod.NoFace): self.main.notify("No face found. This tool needs a face looking at the camera.", "warn")
        elif isinstance(e, ValueError): self.main.notify(str(e), "warn")
        else: self.main.notify(f"{type(e).__name__}: {e}", "error")
    def _faces(self, rgb): return restoremod.detect_faces(rgb, self.main.ai.yunet_path())[0]
    def _add(self, d, out, name, msg):
        d.add_layer(Layer(to_rgba(out), name, x=0, y=0), label=name); self.main.after_edit(); self.main.notify(msg, "ok")
    def analyze(self):
        d = self.main.require_doc()
        if not d: return
        rgb = _flat_rgb(d)
        def done(m):
            s = photofix.suggest(m); self.report.setText(f"Brightness {m['median']:.0f}/255   colour cast {m['cast'] * 100:.0f}%   noise {m['noise']:.1f}   sharpness {m['sharp']:.0f}\n" + ("Would fix: " + ", ".join(s) if s else "Looks fine - nothing to fix."))
        self.main.run_task("Analyzing", lambda ctx: photofix.analyze(rgb), done=done, fail=self._fail)
    def auto_fix(self):
        d = self.main.require_doc()
        if not d: return
        rgb = _flat_rgb(d); k = self.strength.value() / 100.0
        def work(ctx): return photofix.photo_doctor(rgb, self._faces(rgb), k)
        def done(res):
            out, rep = res
            if not rep["steps"]: self.main.notify("The picture looks fine - nothing was changed.", "info"); return
            self._add(d, out, "Photo doctor", "Fixed: " + ", ".join(rep["steps"]) + ". The original is still in the layer below.")
        self.main.run_task("Photo doctor", work, done=done, fail=self._fail)
    def skin(self):
        d = self.main.require_doc()
        if not d: return
        rgb = _flat_rgb(d); a = (self.smooth.value() / 100.0, self.tone.value() / 100.0, self.shine.value() / 100.0, self.spots.isChecked(), self.sens.value() / 100.0)
        def work(ctx):
            f = self._faces(rgb)
            if not f: raise restoremod.NoFace("no face")
            return retouch_engine.skin_retouch(rgb, f, *a)
        self.main.run_task("Retouching skin", work, done=lambda res: self._add(d, res[0], "Skin retouch", f"Skin retouched ({res[1]['spots']} spot(s) removed). The original is still in the layer below."), fail=self._fail)
    def red_eye(self):
        d = self.main.require_doc()
        if not d: return
        rgb = _flat_rgb(d)
        def work(ctx):
            f = self._faces(rgb)
            if not f: raise restoremod.NoFace("no face")
            return photofix.fix_red_eye(rgb, f)
        def done(res):
            out, n = res
            if n == 0: self.main.notify("No red eyes found.", "info"); return
            self._add(d, out, "Red eyes fixed", f"{n} eye(s) fixed.")
        self.main.run_task("Red eyes", work, done=done, fail=self._fail)
    def save_kb(self):
        d = self.main.require_doc()
        if not d: return
        p, _ = QFileDialog.getSaveFileName(self, "Save JPG", os.path.join(self.main.settings.get("export_dir") or "", d.name + ".jpg"), "JPEG (*.jpg)")
        if not p: return
        p = p if p.lower().endswith((".jpg", ".jpeg")) else p + ".jpg"; rgb = _flat_rgb(d); kb = self.kb.value()
        def done(r): self.main.notify(f"Saved {os.path.basename(p)}: {r['bytes'] / 1024:.0f} KB, quality {r['quality']}, size {r['size'][0]} x {r['size'][1]} px" + (f" (reduced to {r['scale'] * 100:.0f}% to fit)" if r["scale"] < 0.999 else ""), "ok")
        self.main.run_task("Saving under size limit", lambda ctx: export_engine.save_under_kb(rgb, p, kb), done=done, fail=self._fail)
    def caption(self):
        d = self.main.require_doc()
        if not d: return
        t = self.cap.text().strip()
        if not t: self.main.notify("Type the caption text first.", "warn"); return
        d.replace_with_image(export_engine.add_caption(_flat_rgb(d), t), "Add caption"); self.main.canvas().fit(); self.main.after_edit()
    def watermark(self):
        d = self.main.require_doc()
        if not d: return
        t = self.wm.text().strip()
        if not t: self.main.notify("Type the watermark text first.", "warn"); return
        self._add(d, export_engine.watermark(np.zeros((d.h, d.w, 3), np.uint8), t), "Watermark", "Watermark added as its own layer - hide or delete it any time.")

# ------------------------------------------------------------------------------------------------ AI Studio
STATUS_COLOR = {"ready": "#34c38f", "needs_setup": "#f5a524", "planned": "#9aa3b2"}
STATUS_TEXT = {"ready": "Ready", "needs_setup": "Needs setup", "planned": "Planned"}

class AIPanel(BasePanel):
    title = "AI Studio"
    def __init__(self, main):
        super().__init__(main); v = _vbox(self); self._bg_img = ""
        v.addWidget(label("BACKGROUND", "section")); self._busy = False; self.bgmodel = QComboBox(); self.bgmodel.setToolTip("Background-removal model. Installed ones are used straight away."); v.addWidget(self.bgmodel)
        v.addWidget(row(_btn("Remove background", self.remove_bg, True), _btn("Prepare model", self.prepare, tip="One-time download of the background model (explicit action).")))
        self.bgchip = ColorChip((255, 255, 255, 255)); self.bgimg = _btn("Image...", self.pick_bg_img)
        v.addWidget(row(QLabel("New background"), self.bgchip, self.bgimg)); v.addWidget(_btn("Replace background", self.replace_bg))
        v.addWidget(label("UPSCALE", "section")); self.scale = QComboBox(); [self.scale.addItem(f"{s}x", s) for s in (2, 3, 4)]
        self.model = QComboBox()
        v.addWidget(row(self.scale, self.model)); v.addWidget(_btn("Upscale image", self.upscale, True))
        v.addWidget(label("REMOVE OBJECTS (LaMa)", "section"))
        v.addWidget(row(_btn("1. Mark objects", self.start_marking, tip="Adds a 'Remove mask' layer and selects the brush: paint over what must disappear."), _btn("2. Remove", self.remove_marked, True, "Removes what you painted red (or the rectangle selection).")))
        v.addWidget(label("Paint over dust, scratches, people or objects with the brush (any size), then press Remove. Your original stays in its own layer.", "muted"))
        v.addWidget(label("RESTORE FACES", "section")); self.faceeng = QComboBox(); v.addWidget(self.faceeng)
        self.fid = SliderRow("Fidelity (higher = closer to the real face)", 0, 100, 70); self.fstr = SliderRow("Strength", 0, 100, 100); v.addWidget(self.fid); v.addWidget(self.fstr)
        v.addWidget(_btn("Restore faces", self.restore_faces, True))
        v.addWidget(label("ENHANCE", "section")); v.addWidget(_btn("Auto enhance (classical)", self.enhance, tip="Auto-levels + gentle sharpen. Not AI.")); 
        v.addWidget(label("DOWNLOAD MODELS", "section")); self.dl = QComboBox(); v.addWidget(self.dl); v.addWidget(_btn("Download selected model (once)", self.download, tip="Explicit download. Models you already have are never downloaded again."))
        v.addWidget(label("STATUS", "section")); self.status = label(""); self.status.setTextFormat(Qt.TextFormat.RichText); v.addWidget(self.status)
        v.addWidget(label("Nothing is uploaded: every model here runs on this PC. Items marked Planned are not implemented yet.", "muted")); v.addStretch(1)
    def _fill_models(self):
        ai = self.main.ai; self._busy = True; inst = set(ai.installed_bg()); self.bgmodel.clear()
        for k, lab, size in aimod.BG_MODELS: self.bgmodel.addItem(f"{lab}  [{'installed' if k in inst else 'not installed, ' + size}]", k)
        for i in range(self.bgmodel.count()):
            if self.bgmodel.itemData(i) == ai.selected_bg(): self.bgmodel.setCurrentIndex(i)
        prev = self.model.currentData(); self.model.clear(); ms = ai.upscale_models() or aimod.UPSCALE_DEFAULTS
        for m in ms: self.model.addItem(m, m)
        for i in range(self.model.count()):
            if self.model.itemData(i) == (prev or "realesrgan-x4plus"): self.model.setCurrentIndex(i)
        prev = self.faceeng.currentData(); self.faceeng.clear()
        for k in ai.face_engines(): self.faceeng.addItem({"codeformer": "CodeFormer (best for old / blurry faces)", "gfpgan": "GFPGAN (fast)"}[k], k)
        if not self.faceeng.count(): self.faceeng.addItem("No face model installed - download one below", "")
        for i in range(self.faceeng.count()):
            if self.faceeng.itemData(i) == prev: self.faceeng.setCurrentIndex(i)
        prev = self.dl.currentData(); self.dl.clear()
        for k, (lab, rel, url, size) in aimod.DOWNLOADS.items(): self.dl.addItem(f"{lab}  [{'installed' if ai.has_model(k) else 'not installed, ' + size}]", k)
        for i in range(self.dl.count()):
            if self.dl.itemData(i) == prev: self.dl.setCurrentIndex(i)
        self._busy = False
        if not getattr(self, "_wired", False): self.bgmodel.currentIndexChanged.connect(self._bg_changed); self._wired = True
    def _bg_changed(self, _):
        if self._busy: return
        self.main.settings.set("bg_model", self.bgmodel.currentData()); self.main.settings.save(); self.refresh()
    def refresh(self):
        self._fill_models(); html = []
        for c in self.main.ai.capabilities():
            col = STATUS_COLOR[c["status"]]; tag = " (classical, not AI)" if c["kind"] == "classical" else ""
            html.append(f'<p style="margin:3px 0"><b>{c["label"]}</b>{tag} <span style="color:{col}">&#9679; {STATUS_TEXT[c["status"]]}</span><br><span style="color:#9aa3b2">{c["detail"]}</span></p>')
        self.status.setText("".join(html))
    def _fail(self, e):
        if isinstance(e, AIUnavailable): self.main.notify(f"{e}. {e.hint}", "warn"); self.refresh()
        elif isinstance(e, restoremod.NoFace): self.main.notify("No face found in this picture. The finder works best on front-facing faces; download the YuNet face finder below for better results.", "warn")
        else: self.main.notify(f"{type(e).__name__}: {e}", "error")
    def prepare(self):
        if QMessageBox.question(self, "Download model", "This downloads the background-removal model (about 170 MB) from the internet once. Continue?") != QMessageBox.StandardButton.Yes: return
        self.main.run_task("Preparing background model", lambda ctx: self.main.ai.prepare_bg_model(ctx), done=lambda ok: (self.main.notify("Background model is ready.", "ok"), self.refresh()), fail=self._fail)
    def pick_bg_img(self):
        p, _ = QFileDialog.getOpenFileName(self, "Background image", "", IMG_FILTER)
        if p: self._bg_img = p; self.bgimg.setText(os.path.basename(p)[:14])
    def remove_bg(self):
        d = self.main.require_doc()
        if not d or d.active is None: return
        L = d.active; arr = np.array(L.pixels); lid = L.id
        def done(cut):
            i = d.index(lid)
            if i < 0: return
            d.insert_layers(i + 1, [Layer(to_rgba(cut), "Cutout", x=L.x, y=L.y)], hide_id=lid, label="Remove background"); self.main.after_edit()
        self.main.run_task("Removing background", lambda ctx: self.main.ai.remove_background(arr, ctx), done=done, fail=self._fail)
    def replace_bg(self):
        d = self.main.require_doc()
        if not d or d.active is None: return
        L = d.active; arr = np.array(L.pixels); lid = L.id; col = self.bgchip.color(); img = self._bg_img
        def done(cut):
            i = d.index(lid)
            if i < 0: return
            if img:
                from PIL import Image
                bg = np.array(Image.open(img).convert("RGBA").resize((d.w, d.h), Image.LANCZOS))
            else: bg = np.zeros((d.h, d.w, 4), np.uint8); bg[:] = col
            d.insert_layers(i + 1, [Layer(to_rgba(bg), "New background"), Layer(to_rgba(cut), "Cutout", x=L.x, y=L.y)], hide_id=lid, label="Replace background"); self.main.after_edit()
        self.main.run_task("Replacing background", lambda ctx: self.main.ai.remove_background(arr, ctx), done=done, fail=self._fail)
    def upscale(self):
        d = self.main.require_doc()
        if not d: return
        rgb = _flat_rgb(d); s = self.scale.currentData(); model = self.model.currentData() or "realesrgan-x4plus"
        def done(out): d.replace_with_image(out, f"Upscale {s}x"); self.main.canvas().fit(); self.main.after_edit(); self.main.notify(f"Upscaled to {d.w} x {d.h} px.", "ok")
        self.main.run_task(f"Upscaling {s}x", lambda ctx: self.main.ai.upscale(rgb, s, model, ctx), done=done, fail=self._fail)
    MASK_NAME = "Remove mask"
    def start_marking(self):
        d = self.main.require_doc()
        if not d: return
        L = next((x for x in d.layers if x.name == self.MASK_NAME), None)
        if L is None: d.add_layer(Layer(to_rgba(np.zeros((d.h, d.w, 4), np.uint8)), self.MASK_NAME), label="Add removal mask")
        else: d.active_id = L.id
        self.main.opts.update(brush_color=(255, 0, 0, 255), brush_size=max(12, d.w // 60), brush_opacity=1.0); self.main.brush_chip.set_color((255, 0, 0, 255)); self.main.set_tool("brush"); self.main.after_edit()
        self.main.notify("Paint over the objects to remove, then press Remove.", "info")
    def remove_marked(self):
        d = self.main.require_doc()
        if not d: return
        L = next((x for x in d.layers if x.name == self.MASK_NAME), None); mask = np.zeros((d.h, d.w), np.uint8)
        if L is not None:
            x0, y0, x1, y1 = max(0, L.x), max(0, L.y), min(d.w, L.x + L.w), min(d.h, L.y + L.h)
            if x1 > x0 and y1 > y0: mask[y0:y1, x0:x1] = (L.pixels[y0 - L.y:y1 - L.y, x0 - L.x:x1 - L.x, 3] > 127).astype(np.uint8) * 255
        if not mask.any() and d.selection: sx0, sy0, sx1, sy1 = d.selection; mask[sy0:sy1, sx0:sx1] = 255
        if not mask.any(): self.main.notify("Nothing is marked. Press '1. Mark objects' and paint over what to remove (or make a rectangle selection).", "warn"); return
        flat = composite_layers([x for x in d.layers if x is not L], d.w, d.h); bg = np.full((d.h, d.w, 4), 255, np.uint8); from ..engine.document import blend_over; blend_over(bg, flat, 0, 0); rgb = np.ascontiguousarray(bg[..., :3]); mid = L.id if L is not None else None
        def done(res):
            out, n = res; d.insert_layers(len(d.layers), [Layer(to_rgba(out), "Objects removed")], hide_id=mid, label="Remove objects"); self.main.after_edit(); self.main.notify(f"Removed {n} area(s). The original is still in the layers below.", "ok")
        self.main.run_task("Removing objects", lambda ctx: self.main.ai.object_remove(rgb, mask, ctx), done=done, fail=self._fail)
    def restore_faces(self):
        d = self.main.require_doc()
        if not d: return
        eng = self.faceeng.currentData() or "auto"; fid = self.fid.value() / 100.0; st = self.fstr.value() / 100.0; rgb = _flat_rgb(d)
        def done(res):
            out, n, used = res; d.add_layer(Layer(to_rgba(out), "Faces restored", x=0, y=0), label="Restore faces"); self.main.after_edit(); self.main.notify(f"Restored {n} face(s) (finder: {used}). Original kept in the layer below.", "ok")
        self.main.run_task("Restoring faces", lambda ctx: self.main.ai.restore_faces(rgb, eng, fid, st, 0.8, ctx), done=done, fail=self._fail)
    def download(self):
        key = self.dl.currentData()
        if not key: return
        lab, rel, url, size = aimod.DOWNLOADS[key]
        if self.main.ai.has_model(key): self.main.notify(f"{lab} is already installed.", "info"); return
        if QMessageBox.question(self, "Download model", f"Download '{lab}' ({size}) from the internet once?\n\n{url}") != QMessageBox.StandardButton.Yes: return
        self.main.run_task(f"Downloading {lab}", lambda ctx: self.main.ai.download_model(key, ctx), done=lambda ok: (self.main.notify(f"{lab} is ready.", "ok"), self.refresh()), fail=self._fail)
    def enhance(self):
        d = self.main.require_doc()
        if d and d.active: d.apply_to_layer(d.active_id, aimod.auto_enhance, "Auto enhance"); self.main.after_edit()

# ------------------------------------------------------------------------------------------------ Document Studio
class DocPanel(BasePanel):
    title = "Document Studio"
    def __init__(self, main):
        super().__init__(main); v = _vbox(self); self._result = None
        v.addWidget(label("SCAN CLEANUP", "section")); self.mode = QComboBox(); self.mode.addItem("Colour", "color"); self.mode.addItem("Grayscale", "gray"); self.mode.addItem("Black & white", "bw"); v.addWidget(self.mode)
        self.inten = SliderRow("Strength", 0, 100, 70); v.addWidget(self.inten); self.sharp = SliderRow("Text sharpness", 0, 100, 40); v.addWidget(self.sharp)
        self.c = {}
        for k, t, on in [("shadow_removal", "Remove shadows / uneven light", True), ("whiten", "Remove paper background (whiten)", True), ("denoise", "Reduce noise", True), ("faint_text", "Improve text contrast (faded ink)", True),
                         ("preserve_black_text", "Preserve black text", True), ("preserve_marks", "Keep coloured signatures & stamps", True), ("deskew", "Straighten (deskew)", True), ("auto_crop", "Cut page out & trim borders", True)]:
            cb = QCheckBox(t); cb.setChecked(on); v.addWidget(cb); self.c[k] = cb
        v.addWidget(row(_btn("Preview", self.preview, True), _btn("Apply", self.apply), _btn("Cancel", self.cancel)))
        self.report = label("", "muted"); v.addWidget(self.report)
        v.addWidget(label("TOOLS", "section"))
        v.addWidget(_btn("Straighten photographed page", self.straighten, tip="Finds the sheet in a photo and flattens its perspective."))
        v.addWidget(_btn("Trim margins to content", self.trim)); 
        v.addWidget(label("SEVERAL DOCUMENTS ON ONE SCAN", "section")); v.addWidget(_btn("Split and straighten each document", self.split_docs, tip="Cards, receipts or sheets lying on one scan become separate, straight pictures (new tabs)."))
        v.addWidget(_btn("Extract signature (transparent)", self.signature, tip="Dark ink on paper becomes a transparent picture you can paste onto any document."))
        v.addWidget(label("BATCH & PDF", "section")); v.addWidget(_btn("Batch process files...", self.batch)); v.addWidget(_btn("Import PDF pages...", self.import_pdf)); v.addWidget(_btn("Export open documents as one PDF...", self.main.export_open_as_pdf))
        v.addWidget(label("Classical image processing - no AI, so no text is ever invented. 'Ink kept' shows how much of the original dark content survived.", "muted")); v.addStretch(1)
    def options(self):
        o = docstudio.CleanOptions(mode=self.mode.currentData(), intensity=self.inten.value(), sharpen=self.sharp.value())
        for k, cb in self.c.items(): setattr(o, k, cb.isChecked())
        return o
    def preview(self):
        d = self.main.require_doc()
        if not d: return
        rgb = _flat_rgb(d); opt = self.options()
        def done(res):
            out, rep = res; self._result = out; self.main.canvas().set_preview(image=np.dstack([out, np.full(out.shape[:2], 255, np.uint8)]))
            self.report.setText(f"Ink kept: {rep['ink_retention'] * 100:.1f}%   Skew corrected: {rep.get('skew_deg', 0.0):+.2f} deg   Page cut out: {'yes' if rep.get('page_cut') else 'no'}\nResult {out.shape[1]} x {out.shape[0]} px - Apply to keep it, Cancel to discard.")
        self.main.run_task("Cleaning scan", lambda ctx: docstudio.clean_scan(rgb, opt, ctx), done=done, fail=lambda e: self.main.notify(f"{type(e).__name__}: {e}", "error"))
    def apply(self):
        d = self.main.doc()
        if d is None or self._result is None: self.main.notify("Press Preview first.", "warn"); return
        d.replace_with_image(self._result, "Document cleanup"); self._result = None; self.main.canvas().clear_preview(); self.main.canvas().fit(); self.report.setText(""); self.main.after_edit()
    def cancel(self):
        self._result = None; cv = self.main.canvas()
        if cv: cv.clear_preview()
        self.report.setText("")
    def deactivate(self): self.cancel()
    def straighten(self):
        d = self.main.require_doc()
        if not d: return
        rgb = _flat_rgb(d)
        def done(res):
            out, conf = res
            if out is rgb or out.shape == rgb.shape and conf < 0.5: self.main.notify(f"No clear sheet of paper found (confidence {conf:.0%}). Use the Crop tool instead.", "warn"); return
            d.replace_with_image(out, "Straighten page"); self.main.canvas().fit(); self.main.after_edit(); self.main.notify(f"Page straightened (confidence {conf:.0%}).", "ok")
        self.main.run_task("Finding page", lambda ctx: docstudio.straighten_document(rgb), done=done, fail=lambda e: self.main.notify(str(e), "error"))
    def trim(self):
        d = self.main.require_doc()
        if not d: return
        bb = docstudio.content_bbox(_flat_rgb(d), 12)
        if not bb: self.main.notify("No content found to trim to.", "warn"); return
        d.crop(*bb); self.main.canvas().fit(); self.main.after_edit()
    def split_docs(self):
        d = self.main.require_doc()
        if not d: return
        rgb = _flat_rgb(d); name = d.name
        def done(crops):
            if not crops: self.main.notify("No separate documents found. They must lie apart from each other on a plain background.", "warn"); return
            from ..engine.document import Document
            for i, (im, conf) in enumerate(crops, 1): self.main.open_document(Document.from_image(im, f"{name} - {i}", d.dpi))
            self.main.notify(f"{len(crops)} document(s) found and opened as new tabs (reading order: top to bottom, left to right).", "ok")
        self.main.run_task("Finding documents", lambda ctx: docstudio.split_documents(rgb), done=done, fail=lambda e: self.main.notify(f"{type(e).__name__}: {e}", "error"))
    def signature(self):
        d = self.main.require_doc()
        if not d: return
        rgb = _flat_rgb(d); dpi = d.dpi
        def done(sig):
            if sig is None: self.main.notify("No ink found. The signature must be dark on lighter paper.", "warn"); return
            from ..engine.document import Document
            self.main.open_document(Document.from_image(sig, "signature", dpi)); self.main.notify("Signature extracted into a new tab with a transparent background. Copy it (Ctrl+C) and paste it onto a document (Ctrl+V).", "ok")
        self.main.run_task("Extracting signature", lambda ctx: docstudio.extract_signature(rgb), done=done, fail=lambda e: self.main.notify(f"{type(e).__name__}: {e}", "error"))
    def import_pdf(self):
        p, _ = QFileDialog.getOpenFileName(self, "Import PDF", "", "PDF (*.pdf)")
        if not p: return
        from ..engine.document import Document
        def done(pages):
            for i, im in enumerate(pages, 1): self.main.open_document(Document.from_image(im, f"{os.path.splitext(os.path.basename(p))[0]} p{i}", 200))
            self.main.notify(f"Imported {len(pages)} page(s).", "ok")
        self.main.run_task("Reading PDF", lambda ctx: docstudio.pdf_to_images(p, 200, ctx), done=done, fail=lambda e: self.main.notify(f"{e}", "warn" if isinstance(e, docstudio.Unavailable) else "error"))
    def batch(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choose scans / PDFs", "", "Scans (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp *.pdf)")
        if not files: return
        out = QFileDialog.getExistingDirectory(self, "Output folder", self.main.settings.get("export_dir") or os.path.dirname(files[0]))
        if not out: return
        choice, ok = QInputDialog.getItem(self, "Output", "Save results as:", ["PNG files", "JPG files", "One PDF file"], 0, False)
        if not ok: return
        opt = self.options(); fmt = "jpg" if choice.startswith("JPG") else "png"; pdf = os.path.join(out, "cleaned.pdf") if choice.startswith("One") else None
        def done(res):
            bad = [r for r in res if not r["ok"]]; self.main.notify(f"Batch finished: {len(res) - len(bad)} done, {len(bad)} failed.", "ok" if not bad else "warn")
            if bad: QMessageBox.warning(self, "Some files failed", "\n".join(f"{os.path.basename(r['src'])}: {r['error']}" for r in bad[:12]))
        self.main.run_task("Batch cleanup", lambda ctx: docstudio.batch_clean(files, out, opt, fmt, ctx, pdf), done=done, fail=lambda e: self.main.notify(f"{type(e).__name__}: {e}", "error"))

# ------------------------------------------------------------------------------------------------ Passport & ID
class PassportPanel(BasePanel):
    title = "Passport & ID"
    MODES = [("Passport / photo sheet", "sheet"), ("Bank photo duet (2 photos)", "duet"), ("ID card  front + back", "card")]
    def __init__(self, main):
        super().__init__(main); v = _vbox(self); self._busy = False
        v.addWidget(label("QUICK PRINT SHEETS", "section")); v.addWidget(row(_btn("Passport...", lambda: main.print_sheet("passport")), _btn("Bank duet...", lambda: main.print_sheet("duet")), _btn("NID A4...", lambda: main.print_sheet("nid"), True)))
        v.addWidget(label("Each wizard asks for the picture(s) and builds a print-ready A4 sheet. The settings below work on the picture that is open now.", "muted"))
        v.addWidget(label("PHOTO SIZE", "section")); self.preset = QComboBox(); v.addWidget(self.preset)
        self.w = QDoubleSpinBox(); self.h = QDoubleSpinBox()
        for s_ in (self.w, self.h): s_.setRange(10, 400); s_.setDecimals(1); s_.setSuffix(" mm")
        v.addWidget(row(QLabel("W"), self.w, QLabel("H"), self.h)); v.addWidget(row(_btn("Save size as preset", self.save_preset, tip="Keep your own sizes (NID, visa, ...)"), _btn("Delete preset", self.delete_preset)))
        v.addWidget(label("FACE & CROP", "section")); self.head = SliderRow("Face size in photo", 30, 70, 50); v.addWidget(self.head)
        v.addWidget(_btn("Auto-crop to face", self.face_crop, True, "Finds the face and places a crop box of this size. You can still move it, then press Enter."))
        v.addWidget(_btn("Crop manually to this ratio", self.crop_ratio, tip="Crop tool locked to this aspect ratio."))
        v.addWidget(_btn("Remove / replace background...", lambda: main.goto("ai")))
        v.addWidget(label("PRINT SHEET", "section")); self.kind = QComboBox(); [self.kind.addItem(n, k) for n, k in self.MODES]; v.addWidget(self.kind)
        self.copies_lbl = QLabel("Copies"); self.copies = QSpinBox(); self.copies.setRange(1, 500); self.copies.setValue(8); v.addWidget(row(self.copies_lbl, self.copies))
        # duet options
        self.duet_box = QWidget(); dv = QVBoxLayout(self.duet_box); dv.setContentsMargins(0, 0, 0, 0)
        self.dw = QDoubleSpinBox(); self.dh = QDoubleSpinBox()
        for s_, val in ((self.dw, 1.9), (self.dh, 1.5)): s_.setRange(0.5, 10); s_.setDecimals(2); s_.setSingleStep(0.05); s_.setValue(val); s_.setSuffix(" in")
        self.arr = QComboBox(); [self.arr.addItem(n, k) for n, k in (("Side by side", "side"), ("Stacked", "stack"), ("Best fit", "auto"))]; self.between = QDoubleSpinBox(); self.between.setRange(0, 20); self.between.setSuffix(" mm")
        dv.addWidget(label("Whole duet size (both photos together)", "muted")); dv.addWidget(row(QLabel("W"), self.dw, QLabel("H"), self.dh)); dv.addWidget(row(self.arr, QLabel("Gap between"), self.between)); v.addWidget(self.duet_box)
        # card options
        self.card_box = QWidget(); cv = QVBoxLayout(self.card_box); cv.setContentsMargins(0, 0, 0, 0)
        self.cw = QDoubleSpinBox(); self.ch = QDoubleSpinBox()
        for s_, val in ((self.cw, passport.ID1_MM[0]), (self.ch, passport.ID1_MM[1])): s_.setRange(20, 300); s_.setDecimals(1); s_.setValue(val); s_.setSuffix(" mm")
        self.back = QComboBox(); self.carr = QComboBox(); [self.carr.addItem(n, k) for n, k in (("Back below front", "stack"), ("Back beside front", "side"))]
        cv.addWidget(label("Card size (default ISO ID-1 bank-card size)", "muted")); cv.addWidget(row(QLabel("W"), self.cw, QLabel("H"), self.ch)); cv.addWidget(row(QLabel("Back side"), self.back)); cv.addWidget(self.carr)
        cv.addWidget(label("This document is the FRONT. Open the back as another document, then choose it above.", "muted")); v.addWidget(self.card_box)
        self.paper = QComboBox(); self.paper.addItems(PAPERS[:-1]); self.orient = QComboBox(); self.orient.addItems(["Portrait", "Landscape"]); v.addWidget(row(self.paper, self.orient))
        self.margin = QDoubleSpinBox(); self.gap = QDoubleSpinBox(); self.border = QDoubleSpinBox(); self.dpi = QSpinBox(); self.dpi.setRange(100, 1200); self.dpi.setValue(300)
        for s_, val in ((self.margin, 5.0), (self.gap, 2.0), (self.border, 0.0)): s_.setRange(0, 50); s_.setDecimals(1); s_.setValue(val); s_.setSuffix(" mm")
        v.addWidget(row(QLabel("Margin"), self.margin, QLabel("Gap"), self.gap)); v.addWidget(row(QLabel("Border"), self.border, QLabel("DPI"), self.dpi))
        self.cut = QCheckBox("Cut marks"); self.rot = QCheckBox("Allow 90 deg turn to fit more"); self.rot.setChecked(True); v.addWidget(self.cut); v.addWidget(self.rot)
        self.info = label("", "muted"); v.addWidget(self.info)
        v.addWidget(_btn("Build print sheet", self.build, True)); v.addWidget(label("The sheet opens as a normal document: every photo is its own layer, so you can still move it in Layout Studio, then Export / Print.", "muted")); v.addStretch(1)
        self._fill_presets(); self.preset.currentIndexChanged.connect(self._preset)
        for x in (self.w, self.h, self.copies, self.margin, self.gap, self.dw, self.dh, self.between, self.cw, self.ch): x.valueChanged.connect(self._info)
        for x in (self.paper, self.orient, self.arr, self.carr): x.currentIndexChanged.connect(self._info)
        self.rot.toggled.connect(self._info); self.kind.currentIndexChanged.connect(self._kind); self._kind(); self._preset(0)
    # ---- presets
    def _fill_presets(self, select=None):
        self._busy = True; self.preset.clear()
        for n, w, h in passport.PRESETS[:-1]: self.preset.addItem(n, (w, h))
        for n, w, h in self.main.settings.custom_presets(): self.preset.addItem(f"{n}  ({w:g} x {h:g} mm)", (w, h, n))
        self.preset.addItem("Custom", (0, 0)); self._busy = False
        if select is not None:
            for i in range(self.preset.count()):
                d = self.preset.itemData(i)
                if len(d) == 3 and d[2] == select: self.preset.setCurrentIndex(i)
    def _preset(self, _=None):
        if self._busy: return
        d = self.preset.currentData(); custom = (d[0] == 0)
        if not custom: self.w.setValue(d[0]); self.h.setValue(d[1])
        self.w.setEnabled(custom); self.h.setEnabled(custom); self._info()
    def save_preset(self):
        n, ok = QInputDialog.getText(self, "Save size", "Name for this size (e.g. NID 30x35):")
        if ok and n.strip():
            if self.main.settings.add_preset(n, self.w.value(), self.h.value()): self.main.settings.save(); self._fill_presets(select=n.strip()); self.main.notify(f"Saved size '{n.strip()}'.", "ok")
            else: self.main.notify("Enter a name and a size above zero.", "warn")
    def delete_preset(self):
        d = self.preset.currentData()
        if len(d) == 3: self.main.settings.remove_preset(d[2]); self.main.settings.save(); self._fill_presets(); self._preset(0); self.main.notify("Preset deleted.", "info")
        else: self.main.notify("Only your own saved sizes can be deleted.", "warn")
    # ---- mode
    def _kind(self, *_):
        k = self.kind.currentData(); self.duet_box.setVisible(k == "duet"); self.card_box.setVisible(k == "card")
        self.copies_lbl.setText({"sheet": "Copies", "duet": "Duets (2 photos each)", "card": "Front+back pairs"}[k])
        self.copies.setValue({"sheet": 8, "duet": 12, "card": 1}[k]); self.rot.setVisible(k != "duet")
        if k == "card": self.margin.setValue(15.0); self.gap.setValue(10.0); self.border.setValue(0.2)
        elif k == "duet": self.margin.setValue(5.0); self.gap.setValue(2.0); self.border.setValue(0.0)
        else: self.margin.setValue(5.0); self.gap.setValue(2.0); self.border.setValue(0.0)
        self._info()
    def refresh(self):
        cur = self.main.doc(); self.back.clear()
        for d in self.main.docs():
            if d is not cur: self.back.addItem(d.name, d)
    def _info(self, *_):
        k = self.kind.currentData(); pg = (self.paper.currentText(), self.orient.currentText())
        try:
            if k == "sheet":
                i = passport.sheet_info(self.w.value(), self.h.value(), self.copies.value(), *pg, self.margin.value(), self.gap.value(), self.rot.isChecked())
                self.info.setText(f"{i['capacity']} photos fit on one {pg[0]} sheet - {i['pages']} sheet(s) for {self.copies.value()} copies." if i["fits"] else "This size does not fit on the page.")
            elif k == "duet":
                i = passport.duet_info(self.dw.value() * 25.4, self.dh.value() * 25.4, *pg, self.margin.value(), self.gap.value(), self.between.value(), self.arr.currentData())
                cap = i["capacity"]; pw, ph = i["photo_mm"]; self.info.setText(f"Each photo {pw:.1f} x {ph:.1f} mm. {cap} duets fit on one {pg[0]} sheet." if cap else "This duet does not fit on the page.")
            else:
                i = passport.card_info(self.cw.value(), self.ch.value(), *pg, self.margin.value(), self.gap.value(), 8.0, self.carr.currentData(), self.rot.isChecked())
                self.info.setText(f"{i['capacity']} front+back pair(s) fit on one {pg[0]} sheet." if i["capacity"] else "This card does not fit on the page - try smaller margins or the other arrangement.")
        except Exception as e: self.info.setText(str(e))
    # ---- face / crop
    def crop_ratio(self):
        cv = self.main.canvas()
        if cv is None: self.main.notify("Open a photo first.", "warn"); return
        self.main.set_tool("crop"); cv.set_crop_ratio(self.w.value(), self.h.value()); cv.set_crop_to_ratio_default(); self.main.notify("Drag the crop box into place, then press Enter.", "info")
    def face_crop(self):
        d = self.main.require_doc()
        if not d: return
        rgb = _flat_rgb(d); w, h, head = self.w.value(), self.h.value(), self.head.value() / 100.0; W, H = d.w, d.h
        def done(faces):
            cv = self.main.canvas()
            if cv is None or cv.doc is not d: return
            if not faces: self.main.notify("No face found (it works best on a front-facing photo). Use 'Crop manually to this ratio'.", "warn"); return
            x0, y0, x1, y1, clamped = passport.face_crop_rect(W, H, faces[0], w / h, head)
            self.main.set_tool("crop"); cv.set_crop_ratio(w, h); cv.crop_rect = (x0, y0, x1, y1); cv.cropChanged.emit(cv.crop_rect); cv.update()
            extra = f" ({len(faces)} faces - using the largest)" if len(faces) > 1 else ""; small = " The photo is small, so the face is larger than requested." if clamped else ""
            self.main.notify("Face found" + extra + ". Adjust the box if needed, then press Enter." + small, "ok")
        yn = os.path.join(self.main.settings.models_dir(), "yunet", "face_detection_yunet_2023mar.onnx")
        self.main.run_task("Finding face", lambda ctx: passport.detect_faces(rgb, yunet_path=yn), done=done)
    # ---- build
    def build(self):
        d = self.main.require_doc()
        if not d: return
        photo = _flat_rgb(d); k = self.kind.currentData(); common = dict(paper=self.paper.currentText(), orientation=self.orient.currentText(), margin=self.margin.value(), gap=self.gap.value(), dpi=self.dpi.value(), border_mm=self.border.value(), cut_marks=self.cut.isChecked())
        try:
            if k == "sheet": docs, info = passport.make_sheet_documents(photo, self.w.value(), self.h.value(), self.copies.value(), allow_rotate=self.rot.isChecked(), **common)
            elif k == "duet": docs, info = passport.make_duet_documents(photo, None, self.dw.value() * 25.4, self.dh.value() * 25.4, self.copies.value(), between=self.between.value(), arrangement=self.arr.currentData(), **common)
            else:
                back = self.back.currentData()
                if back is None: self.main.notify("Open the back side as another document first, then choose it under 'Back side'.", "warn"); return
                common.pop("gap"); docs, info = passport.make_id_card_documents(photo, _flat_rgb(back), self.cw.value(), self.ch.value(), self.copies.value(), gap=self.gap.value(), arrangement=self.carr.currentData(), allow_rotate=self.rot.isChecked(), **common)
        except ValueError as e: self.main.notify(str(e), "warn"); return
        for doc in docs: self.main.open_document(doc)
        self.main.notify(f"Built {len(docs)} sheet(s), {self.paper.currentText()} at {self.dpi.value()} DPI.", "ok")

# ------------------------------------------------------------------------------------------------ Layout Studio
class LayoutPanel(BasePanel):
    title = "Layout Studio"
    def __init__(self, main):
        super().__init__(main); v = _vbox(self)
        v.addWidget(label("PAGE", "section")); self.paper = QComboBox(); self.paper.addItems(PAPERS); self.orient = QComboBox(); self.orient.addItems(["Portrait", "Landscape"])
        self.cw = QDoubleSpinBox(); self.ch = QDoubleSpinBox(); [(s.setRange(10, 2000), s.setDecimals(1), s.setSuffix(" mm"), s.setValue(v_)) for s, v_ in ((self.cw, 210.0), (self.ch, 297.0))]
        self.dpi = QSpinBox(); self.dpi.setRange(72, 1200); self.dpi.setValue(300)
        v.addWidget(row(self.paper, self.orient)); v.addWidget(row(QLabel("Custom"), self.cw, self.ch)); v.addWidget(row(QLabel("DPI"), self.dpi, _btn("New page", self.new_page, True)))
        self.margin = QDoubleSpinBox(); self.margin.setRange(0, 50); self.margin.setValue(5); self.margin.setSuffix(" mm"); self.show_m = QCheckBox("Show margin guide")
        v.addWidget(row(QLabel("Margin"), self.margin)); v.addWidget(self.show_m); self.show_m.toggled.connect(self._guide); self.margin.valueChanged.connect(lambda _: self._guide())
        self.info = label("", "muted"); v.addWidget(self.info)
        v.addWidget(label("PLACE", "section")); v.addWidget(_btn("Place images...", self.place)); v.addWidget(_btn("New A4 page from pictures...", self.new_page_from_pictures, tip="Choose pictures - they are placed on a fresh page"))
        self.docs_combo = QComboBox(); v.addWidget(row(self.docs_combo, _btn("Add as layer", self.add_doc, tip="Put another open picture on this page"))); v.addWidget(label("Tip: drag picture files from Explorer straight onto the page, paste with Ctrl+V, or use Layer > Copy layer to document.", "muted"))
        
        v.addWidget(row(_btn("Text", self.add_text), _btn("Rectangle", lambda: self.add_shape("rect")), _btn("Ellipse", lambda: self.add_shape("ellipse"))))
        v.addWidget(label("ALIGN SELECTED LAYER TO PAGE", "section")); g = QGridLayout(); g.setSpacing(4)
        for i, (t, k) in enumerate([("Left", "l"), ("Centre", "ch"), ("Right", "r"), ("Top", "t"), ("Middle", "cv"), ("Bottom", "b")]): g.addWidget(_btn(t, lambda _=False, k=k: self.align(k)), i // 3, i % 3)
        v.addLayout(g); v.addWidget(label("VIEW & PRINT", "section"))
        v.addWidget(row(_btn("Fit page", lambda: self.main.canvas() and self.main.canvas().fit()), _btn("Actual print size", lambda: self.main.canvas() and self.main.canvas().zoom_physical(), tip="100% = real millimetres on your screen")))
        v.addWidget(_btn("Print preview / Print...", self.main.print_preview, True)); v.addStretch(1)
    def refresh(self):
        d = self.main.doc(); self.docs_combo.clear()
        for o in self.main.docs():
            if o is not d: self.docs_combo.addItem(o.name, o)
        if d: wm, hm = d.size_mm(); self.info.setText(f"Current page: {wm:.1f} x {hm:.1f} mm  -  {d.w} x {d.h} px at {d.dpi} DPI")
        else: self.info.setText("")
    def new_page_from_pictures(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Pictures for the new page", self.main.settings.get("export_dir") or "", IMG_FILTER)
        if not files: return
        self.new_page(); d = self.main.doc()
        if d: self.main.place_files(files, d.w / 2.0, d.h / 2.0)
    def add_doc(self): self.main.add_doc_as_layer(self.docs_combo.currentData())
    def _guide(self):
        cv = self.main.canvas()
        if cv: cv.margin_guide_mm = self.margin.value() if self.show_m.isChecked() else None; cv.update()
    def new_page(self):
        d = passport.blank_page_document(self.paper.currentText(), self.orient.currentText(), self.dpi.value(), (self.cw.value(), self.ch.value()) if self.paper.currentText() == "Custom" else None, "Layout")
        self.main.open_document(d); self._guide()
    def place(self):
        d = self.main.require_doc()
        if not d: return
        files, _ = QFileDialog.getOpenFileNames(self, "Place images", "", IMG_FILTER)
        from PIL import Image, ImageOps
        for f in files:
            im = ImageOps.exif_transpose(Image.open(f)).convert("RGBA"); m = core.mm2px(self.margin.value(), d.dpi); k = min((d.w - 2 * m) / im.width, (d.h - 2 * m) / im.height, 1.0)
            if k < 1.0: im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
            d.add_image_layer(im, os.path.splitext(os.path.basename(f))[0])
        if files: self.main.after_edit()
    def add_text(self):
        d = self.main.require_doc()
        if not d: return
        t, ok = QInputDialog.getMultiLineText(self, "Add text", "Text:", "Text")
        if ok and t.strip(): d.add_text(t, d.w // 10, d.h // 10, size=max(24, d.h // 40)); self.main.after_edit("Add text")
    def add_shape(self, kind):
        d = self.main.require_doc()
        if d: d.add_shape(kind, d.w // 10, d.h // 10, d.w // 4, d.h // 8, fill=(59, 130, 246, 255)); self.main.after_edit()
    def align(self, k):
        d = self.main.require_doc()
        if not d or not d.active: return
        L = d.active; m = core.mm2px(self.margin.value(), d.dpi)
        x = {"l": m, "r": d.w - m - L.w, "ch": (d.w - L.w) // 2}.get(k, L.x); y = {"t": m, "b": d.h - m - L.h, "cv": (d.h - L.h) // 2}.get(k, L.y)
        d.set_layer_props(L.id, "Align", x=x, y=y); self.main.after_edit()

# ------------------------------------------------------------------------------------------------ Layers
class LayersPanel(QWidget):
    def __init__(self, main):
        super().__init__(); self.main = main; self._busy = False; v = _vbox(self, 8)
        v.addWidget(label("LAYERS", "section")); self.list = QListWidget(); self.list.setMinimumHeight(140); v.addWidget(self.list, 1)
        self.op = SliderRow("Opacity", 0, 100, 100); v.addWidget(self.op)
        g = QHBoxLayout(); g.setSpacing(4)
        for tip, ic, f in [("Move up", "up", lambda: self._order(+1)), ("Move down", "down", lambda: self._order(-1)), ("Duplicate", "copy", self._dup), ("Merge down", "merge", self._merge), ("Delete", "trash", self._del)]:
            from .icons import icon
            b = QPushButton(); b.setIcon(icon(ic, main.icon_color())); b.setToolTip(tip); b.clicked.connect(f); g.addWidget(b)
        v.addLayout(g); v.addWidget(row(_btn("Flatten image", self._flat), _btn("Rename", self._rename)))
        self.list.currentItemChanged.connect(self._sel); self.list.itemChanged.connect(self._item_changed); self.op.valueChanged.connect(self._opacity_live); self.op.released.connect(self._opacity_commit)
    def doc(self): return self.main.doc()
    def refresh(self):
        d = self.doc(); self._busy = True; self.list.clear()
        if d:
            for L in reversed(d.layers):
                it = QListWidgetItem(("T  " if L.kind == "text" else "S  " if L.kind == "shape" else "") + L.name); it.setData(Qt.ItemDataRole.UserRole, L.id)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable); it.setCheckState(Qt.CheckState.Checked if L.visible else Qt.CheckState.Unchecked); self.list.addItem(it)
                if L.id == d.active_id: self.list.setCurrentItem(it)
            a = d.active
            if a: self.op.setValue(int(round(a.opacity * 100)))
        self._busy = False
    def _lid(self):
        it = self.list.currentItem(); return it.data(Qt.ItemDataRole.UserRole) if it else None
    def _sel(self, cur, _prev):
        d = self.doc()
        if self._busy or d is None or cur is None: return
        d.active_id = cur.data(Qt.ItemDataRole.UserRole); L = d.active
        if L: self.op.setValue(int(round(L.opacity * 100)))
        self.main.canvas().update(); self.main.layer_selected()
    def _item_changed(self, it):
        d = self.doc()
        if self._busy or d is None: return
        L = d.layer(it.data(Qt.ItemDataRole.UserRole))
        if L is None: return
        vis = it.checkState() == Qt.CheckState.Checked
        if vis != L.visible: d.set_layer_props(L.id, "Show layer" if vis else "Hide layer", visible=vis); self.main.after_edit()
    def _opacity_live(self, v):
        d = self.doc(); L = d.active if d else None
        if L and not self._busy: L.opacity = v / 100.0; d.invalidate(); self.main.canvas().update()
    def _opacity_commit(self):
        d = self.doc()
        if d and d.active: d.commit("Layer opacity"); self.main.after_edit()
    def _order(self, delta):
        d = self.doc(); lid = self._lid()
        if d and lid and d.move_layer_order(lid, delta): self.main.after_edit()
    def _dup(self):
        d = self.doc(); lid = self._lid()
        if d and lid: d.duplicate_layer(lid); self.main.after_edit()
    def _merge(self):
        d = self.doc(); lid = self._lid()
        if d and lid and not d.merge_down(lid): self.main.notify("Nothing below to merge into.", "warn")
        self.main.after_edit()
    def _del(self):
        d = self.doc(); lid = self._lid()
        if d and lid and not d.remove_layer(lid): self.main.notify("A document must keep at least one layer.", "warn")
        self.main.after_edit()
    def _flat(self):
        d = self.doc()
        if d: d.flatten(); self.main.after_edit()
    def _rename(self):
        d = self.doc(); L = d.active if d else None
        if not L: return
        n, ok = QInputDialog.getText(self, "Rename layer", "Name:", text=L.name)
        if ok and n.strip(): d.set_layer_props(L.id, "Rename layer", name=n.strip()); self.main.after_edit()

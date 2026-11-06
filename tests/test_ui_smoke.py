"""Headless smoke test of the PySide6 UI code against a FAKE Qt (tests/qt_stub.py). Catches NameError / AttributeError / wrong arguments /
logic errors in our own code. It does NOT prove the real windows look or behave right - that needs a run on Windows."""
import os, sys, tempfile, unittest, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qt_stub; qt_stub.install()
import numpy as np
from PIL import Image
from rstudio.engine.settings import Settings
from rstudio.engine.recovery import Recovery
import onnx_tiny
from rstudio.engine import modelpack
from rstudio.engine.document import Document
from rstudio.ui import icons, theme
from rstudio.ui.main_window import MainWindow, NAV, TOOLS

def wait(pred, t=20):
    end = time.time() + t
    while time.time() < end:
        if pred(): return True
        time.sleep(0.02)
    return False

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory(); s = Settings(os.path.join(cls.td.name, "s.json")); s.set("models_dir", os.path.join(cls.td.name, "m"))
        cls.w = MainWindow(s, Recovery(os.path.join(cls.td.name, "rec")))
        a = np.zeros((300, 400, 3), np.uint8); a[..., 0] = np.linspace(0, 255, 400, dtype=np.uint8)[None]; a[..., 1] = 100; a[..., 2] = np.linspace(255, 0, 300, dtype=np.uint8)[:, None]
        cls.path = os.path.join(cls.td.name, "p.png"); Image.fromarray(a).save(cls.path)
    @classmethod
    def tearDownClass(cls): cls.td.cleanup()

    def test_01_construct_and_navigation(self):
        w = self.w; self.assertEqual(set(w.panels), {"photo", "adjust", "retouch", "ai", "doc", "passport", "layout"})
        for key, _, _ in NAV: w.goto(key)
        w.goto("home")
    def test_02_open_image_and_basic_ops(self):
        w = self.w; w.open_files([self.path]); self.assertEqual(w.tabs.count(), 1); d = w.doc(); self.assertEqual((d.w, d.h), (400, 300)); self.assertIsNotNone(w.canvas())
        w.panels["photo"]._do("rotate90", True); self.assertEqual((d.w, d.h), (300, 400)); w.undo(); self.assertEqual((d.w, d.h), (400, 300)); w.redo(); w.undo()
        w.select_all(); self.assertIsNotNone(d.selection); w.deselect(); self.assertIsNone(d.selection)
        w.new_layer(); self.assertEqual(len(d.layers), 2); w.layers._dup(); w.layers._merge(); w.layers._flat(); self.assertEqual(len(d.layers), 1)
    def test_03_every_tool_selectable(self):
        for k, *_ in TOOLS: self.w.set_tool(k)
        self.w.set_tool("move")
    def test_04_adjust_panel_every_adjustment_applies(self):
        w = self.w; w.goto("adjust"); P = w.panels["adjust"]; d = w.doc(); n0 = len(d.history_labels())
        for i in range(P.combo.count()):
            P.combo.setCurrentIndex(i); P.preview(force=True); wait(lambda: w.canvas().preview_overrides is not None, 20)
            P.apply(); self.assertTrue(wait(lambda: len(d.history_labels()) > n0, 60), P.key()); n0 = len(d.history_labels()); w.canvas().clear_preview()
        w.goto("photo")
    def test_05_document_panel_preview_apply(self):
        w = self.w; w.goto("doc"); P = w.panels["doc"]; P.preview(); self.assertTrue(wait(lambda: P._result is not None, 60)); d = w.doc(); P.apply(); self.assertEqual(len(d.layers), 1); w.undo()
        P.trim(); P.straighten(); time.sleep(1.0)
    def test_06_passport_and_layout(self):
        w = self.w; w.goto("passport"); P = w.panels["passport"]; n = w.tabs.count(); P.copies.setValue(8); P._info(); P.build(); self.assertEqual(w.tabs.count(), n + 1)
        d = w.doc(); self.assertEqual((d.w, d.h), (2480, 3508)); self.assertGreaterEqual(len(d.layers), 9)
        w.goto("layout"); L = w.panels["layout"]; L.refresh(); L.align("ch"); L.align("b"); L.add_shape("ellipse"); L.new_page(); self.assertEqual(w.tabs.count(), n + 2)
        w.tabs.setCurrentIndex(0)
    def test_07_ai_panel_reports_honestly_and_fails_cleanly(self):
        w = self.w; w.goto("ai"); P = w.panels["ai"]; P.refresh(); msgs = []; w.notify = lambda m, k="info": msgs.append((k, m))
        P.remove_bg(); self.assertTrue(wait(lambda: any(k == "warn" for k, _ in msgs), 20), msgs); self.assertIn("not set up", msgs[-1][1])
        msgs.clear(); P.upscale(); self.assertTrue(wait(lambda: any(k == "warn" for k, _ in msgs), 20), msgs)
        d = w.doc(); n = len(d.history_labels()); P.enhance(); self.assertEqual(len(d.history_labels()), n + 1)
    def test_07b_object_removal_and_face_restore_from_the_panel(self):
        import skimage.data as sd
        w = self.w; w.goto("ai"); P = w.panels["ai"]; msgs = []; w.notify = lambda m, k="info": msgs.append((k, m)); md = w.settings.models_dir()
        for key, builder in (("lama", onnx_tiny.build_lama_like), ("gfpgan", onnx_tiny.build_gfpgan_like), ("codeformer", onnx_tiny.build_codeformer_like)):
            p = w.ai.model_path(key); os.makedirs(os.path.dirname(p), exist_ok=True); builder(p)
        w.open_document(Document.from_image(sd.astronaut(), "astro", 300)); d = w.doc(); P.refresh(); self.assertEqual(w.ai.status("object_remove")["status"], "ready"); self.assertGreaterEqual(P.faceeng.count(), 2)
        msgs.clear(); P.remove_marked(); self.assertEqual(msgs[-1][0], "warn")                                               # nothing marked yet
        P.start_marking(); mask_layer = [l for l in d.layers if l.name == "Remove mask"][0]; self.assertEqual(w._tool, "brush"); self.assertEqual(w.opts["brush_color"], (255, 0, 0, 255))
        px = np.array(mask_layer.pixels); px[200:260, 100:180] = (255, 0, 0, 255); d.set_pixels(mask_layer.id, px, "paint"); n = len(d.layers)
        P.remove_marked(); self.assertTrue(wait(lambda: len(d.layers) == n + 1, 30), msgs); self.assertEqual(d.layers[-1].name, "Objects removed"); self.assertFalse(d.layer(mask_layer.id).visible)
        self.assertTrue(np.array_equal(np.array(d.layers[-1].pixels)[:60, :60, :3], sd.astronaut()[:60, :60]), "far from the mask nothing changed")
        n = len(d.layers); P.fid.setValue(70); P.faceeng.setCurrentIndex(0); P.restore_faces(); self.assertTrue(wait(lambda: len(d.layers) == n + 1, 30), msgs); self.assertEqual(d.layers[-1].name, "Faces restored")
        d.select_rect(300, 300, 340, 340); d.layers[-1].visible = True; n = len(d.layers); P.remove_marked()          # mask layer exists but is empty -> falls back to the rectangle selection
        self.assertTrue(wait(lambda: len(d.layers) == n + 1, 30), msgs)
        d.dirty = False
    def test_07c_download_button_asks_and_downloads(self):
        import rstudio.ui.panels as pn
        from rstudio.engine import ai as aimod
        w = self.w; w.goto("ai"); P = w.panels["ai"]; src = os.path.join(self.td.name, "y.onnx"); onnx_tiny.build_lama_like(src); orig = aimod.DOWNLOADS["yunet"]; aimod.DOWNLOADS["yunet"] = (orig[0], orig[1], "file://" + src, orig[3])
        class Q:
            StandardButton = pn.QMessageBox.StandardButton
            @staticmethod
            def question(*a, **k): return pn.QMessageBox.StandardButton.Yes
        old, pn.QMessageBox = pn.QMessageBox, Q
        try:
            P.refresh(); [P.dl.setCurrentIndex(i) for i in range(P.dl.count()) if P.dl.itemData(i) == "yunet"]; w.ai._onnx.clear(); P.download(); self.assertTrue(wait(lambda: w.ai.has_model("yunet"), 20))
        finally: pn.QMessageBox = old; aimod.DOWNLOADS["yunet"] = orig
    def test_07d_settings_backup_and_restore(self):
        w = self.w; w.goto("settings"); S = w.settings_page; pack = os.path.join(self.td.name, "backup.zip"); before = {g["key"] for g in modelpack.scan(w.settings.models_dir())}; self.assertIn("lama", before)
        S.start_backup(["lama", "gfpgan"], pack); self.assertTrue(wait(lambda: os.path.isfile(pack), 30)); info = modelpack.inspect_backup(pack); self.assertEqual({g["key"] for g in info["groups"]}, {"lama", "gfpgan"})
        os.remove(w.ai.model_path("lama")); self.assertFalse(w.ai.has_model("lama")); S.start_restore(pack, ["lama"], False); self.assertTrue(wait(lambda: w.ai.has_model("lama"), 30)); S.refresh()
    def test_07e_perspective_crop_resize_handles_drop_paste_send(self):
        import cv2, rstudio.ui.main_window as mw
        from test_layout_tools import card, photo_of, QUAD
        w = self.w; base = w.tabs.count(); msgs = []; w.notify = lambda m, k="info": msgs.append((k, m)); ph = photo_of(card(), QUAD); w.open_document(Document.from_image(ph, "cardphoto", 150)); d = w.doc(); c = w.canvas()
        w.set_tool("perspective"); self.assertIsNotNone(c.persp); self.assertEqual(np.array(c.persp).shape, (4, 2)); w.persp_detect(); self.assertIsNotNone(c.persp)
        c.persp = np.array(QUAD, np.float32); [w.persp_out.setCurrentIndex(i) for i in range(w.persp_out.count()) if w.persp_out.itemData(i) == (85.6, 54.0)]
        w.apply_perspective(); self.assertTrue(wait(lambda: (d.w, d.h) == (1011, 638), 30), (d.w, d.h)); self.assertEqual(d.dpi, 300); self.assertIsNone(c.persp); self.assertEqual(w._tool, "move"); d.undo(); self.assertEqual((d.w, d.h), (ph.shape[1], ph.shape[0]))
        w.set_tool("move"); page = Document.new(1000, 800, 300, name="page"); w.open_document(page); c = w.canvas(); L = page.add_image_layer(np.full((100, 200, 3), 90, np.uint8), "pic", 100, 100)
        dr = dict(kind="scale", h="br", layer=L, base=L.pixels, rect=(L.x, L.y, L.w, L.h)); c._scale_to(dr, L.x + 400, L.y + 110, False); self.assertEqual((L.w, L.h), (400, 200), "corner handle keeps the proportions"); self.assertEqual(dr["target"], (100, 100, 400, 200))
        c._drag = dr; n = len(page.history_labels()); c.mouseReleaseEvent(None); self.assertEqual(len(page.history_labels()), n + 1); self.assertEqual(page.layer(L.id).w, 400)
        L = page.layer(L.id); dr = dict(kind="scale", h="tl", layer=L, base=L.pixels, rect=(L.x, L.y, L.w, L.h)); c._scale_to(dr, L.x + 200, L.y + 100, False); self.assertEqual((L.w, L.h), (200, 100)); self.assertEqual((L.x + L.w, L.y + L.h), (500, 300), "the opposite corner stays put")
        dr = dict(kind="scale", h="r", layer=L, base=L.pixels, rect=(L.x, L.y, L.w, L.h)); c._scale_to(dr, L.x + 50, L.y, False); self.assertEqual((L.w, L.h), (50, 100), "edge handle stretches one side"); d2 = dict(kind="scale", h="br", layer=L, base=L.pixels, rect=(L.x, L.y, L.w, L.h)); c._scale_to(d2, 0, 0, False); self.assertGreaterEqual(L.w, 4)
        L2 = page.add_image_layer(np.full((100, 200, 3), 90, np.uint8), "snap", 395, 350); nx, ny, guides = c._snap(L2, 395, 350); self.assertAlmostEqual(nx + L2.w / 2, 500, delta=0.01); self.assertTrue(guides[0] or guides[1])
        self.assertEqual(c._snap(L2, 395.0, 350.0)[2][0], [500.0]); page.undo()
        a = Image.fromarray(np.random.RandomState(0).randint(0, 255, (3000, 2000, 3)).astype(np.uint8)); f = os.path.join(self.td.name, "big.png"); a.save(f); n = len(page.layers); w.place_files([f, os.path.join(self.td.name, "missing.png")], 500, 400)
        self.assertEqual(len(page.layers), n + 1); big = page.layers[-1]; self.assertLessEqual(big.w, 900); self.assertLessEqual(big.h, 720); self.assertTrue(any(k == "warn" for k, _ in msgs))
        mw.clip.get_image = lambda: np.dstack([np.full((50, 80, 3), 7, np.uint8), np.full((50, 80), 255, np.uint8)]); n = len(page.layers); w.paste_clipboard(); self.assertEqual(len(page.layers), n + 1); mw.clip.get_image = lambda: None; w.paste_clipboard(); self.assertEqual(msgs[-1][0], "warn")
        copied = []; mw.clip.set_image = lambda a: copied.append(a.shape); w.copy_clipboard(); self.assertEqual(len(copied), 1)
        class FakeSize:
            def __init__(self, *a, **k): pass
            def exec(self): return True
            def values(self): return (20.0, 30.0, 85.6, 54.0)
        old, mw.LayerSizeDialog = mw.LayerSizeDialog, FakeSize
        try: w.layer_size_dialog()
        finally: mw.LayerSizeDialog = old
        act = page.active; self.assertEqual((act.w, act.h), (1011, 638)); w._layer_fit("contain"); self.assertLessEqual(page.active.w, 1000); w._layer_op("rotate_layer90", True); w._layer_op("flip_layer", True)
        other = Document.new(500, 400, name="other"); w.open_document(other); w.tabs.setCurrentIndex(w.tabs.count() - 2); n = len(other.layers); w.copy_layer_to(other); self.assertEqual(len(other.layers), n + 1); self.assertIs(w.doc(), other)
        w.add_doc_as_layer(page); self.assertEqual(len(other.layers), n + 2)
        class FakeQ:
            @staticmethod
            def getItem(*a, **k): return ("Fit to the page (recommended)", True)
        old, mw.QInputDialog = mw.QInputDialog, FakeQ; t = w.tabs.count()
        try: w.send_to_a4()
        finally: mw.QInputDialog = old
        self.assertEqual(w.tabs.count(), t + 1); a4 = w.doc(); self.assertEqual((a4.w, a4.h), (3508, 2480), "the picture is wider than tall, so the page is landscape"); self.assertEqual(len(a4.layers), 2); self.assertLessEqual(a4.active.w, 3508)
        for dd in w.docs(): dd.dirty = False
        while w.tabs.count() > base: w.close_tab(w.tabs.count() - 1)
    def test_07f_print_sheet_wizards(self):
        from rstudio.ui.sheets import PrintSheetDialog
        import rstudio.ui.main_window as mw
        from test_layout_tools import card, photo_of, QUAD
        w = self.w; base = w.tabs.count(); front = photo_of(card(), QUAD); back = np.ascontiguousarray(np.rot90(photo_of(card(), QUAD)))
        dlg = PrintSheetDialog(w, "nid"); dlg.src[0].set_rgb(front); dlg.src[1].set_rgb(back); docs, msg = dlg.build(); d = docs[0]; self.assertEqual((d.w, d.h), (2480, 3508)); cards = [l for l in d.layers if l.name.startswith("Card")]
        self.assertEqual(len(cards), 2); self.assertEqual((cards[0].w, cards[0].h), (1011, 638)); self.assertIn("detected", msg); self.assertGreater(cards[1].y, cards[0].y + cards[0].h - 1)
        dlg.auto.setChecked(False); docs, msg = dlg.build(); self.assertNotIn("detected", msg)
        dd = PrintSheetDialog(w, "duet"); dd.src[0].set_rgb(front); dd.src[1].set_rgb(back); docs, msg = dd.build(); self.assertEqual(len([l for l in docs[0].layers if l.name.startswith("Duet")]), 24); self.assertEqual(docs[0].layers[1].w, 285)
        dp = PrintSheetDialog(w, "passport"); dp.src[0].set_rgb(front); dp.n.setValue(8); docs, msg = dp.build(); self.assertEqual(len(docs[0].layers), 9)
        dn = PrintSheetDialog(w, "nid"); dn.src[0].set_rgb(front)
        with self.assertRaises(ValueError): dn.build()                                                                              # back missing -> clear message, no crash
        dn.src[1].set_rgb(back); dn.w.setValue(300.0)
        with self.assertRaises(ValueError): dn.build()                                                                              # card bigger than the page
        class FakeDlg:
            def __init__(self, main, kind): self.kind = kind; self.result_docs = [Document.new(50, 50, name="sheet " + kind)]; self.result_msg = "built " + kind
            def exec(self): return True
        old, mw.PrintSheetDialog = mw.PrintSheetDialog, FakeDlg; t = w.tabs.count()
        try: w._home_action("nid"); w._home_action("duet"); w.print_sheet("passport")
        finally: mw.PrintSheetDialog = old
        self.assertEqual(w.tabs.count(), t + 3)
        for dd_ in w.docs(): dd_.dirty = False
        while w.tabs.count() > base: w.close_tab(w.tabs.count() - 1)
    def test_08_save_export_roundtrip(self):
        w = self.w; d = w.doc(); p = os.path.join(self.td.name, "x.rai"); d.save(p); e = Document.load(p); self.assertEqual((e.w, e.h), (d.w, d.h))
        for ext in (".png", ".jpg", ".pdf"): d.export(os.path.join(self.td.name, "e" + ext))
    def test_09_settings_page_and_theme(self):
        w = self.w; w.goto("settings"); w.settings_page.refresh(); w.settings_page.save(); w.toggle_theme(); w.toggle_theme(); self.assertEqual(w.settings.get("theme"), "dark")
    def test_10_close_tabs_without_prompt_when_clean(self):
        w = self.w
        for d in w.docs(): d.dirty = False
        while w.tabs.count(): self.assertTrue(w.close_tab(w.tabs.count() - 1))
        self.assertIsNone(w.canvas()); w.goto("home")
    def test_10b_edit_text_layer(self):
        import rstudio.ui.main_window as mw
        w = self.w; w.open_document(Document.new(400, 300)); d = w.doc(); L = d.add_text("Hi", 10, 10, size=30)
        class FakeDlg:
            @staticmethod
            def getMultiLineText(*a): return ("Hello there", True)
            @staticmethod
            def getInt(*a): return (50, True)
        old, mw.QInputDialog = mw.QInputDialog, FakeDlg
        try: w.edit_layer_params()
        finally: mw.QInputDialog = old
        self.assertEqual(d.layer(L.id).params["text"], "Hello there"); self.assertEqual(d.layer(L.id).params["size"], 50)
        w.tabs.setCurrentIndex(w.tabs.count() - 1); d.dirty = False; w.close_tab(w.tabs.count() - 1)
    def test_10c_duet_card_presets_and_face_crop(self):
        import skimage.data as sd
        w = self.w; w.goto("passport"); P = w.panels["passport"]; face = Document.from_image(sd.astronaut(), "face", 300); w.open_document(face); n = w.tabs.count()
        P.kind.setCurrentIndex(1); self.assertEqual(P.kind.currentData(), "duet"); P._info(); self.assertIn("duets fit", P.info.text()); P.build(); self.assertEqual(w.tabs.count(), n + 1); self.assertGreaterEqual(len(w.doc().layers), 5)
        w.tabs.setCurrentIndex(n - 1); P.kind.setCurrentIndex(2); P.refresh(); P._info(); self.assertIn("pair", P.info.text()); P.build(); self.assertEqual(w.tabs.count(), n + 2)          # back = the duet sheet doc (any other doc)
        w.tabs.setCurrentIndex(n - 1); P.kind.setCurrentIndex(0); msgs = []; w.notify = lambda m, k="info": msgs.append((k, m))
        P.face_crop(); self.assertTrue(wait(lambda: msgs, 20)); cv = w.canvas(); self.assertEqual(msgs[-1][0], "ok", msgs); self.assertIsNotNone(cv.crop_rect); x0, y0, x1, y1 = cv.crop_rect; self.assertAlmostEqual((x1 - x0) / (y1 - y0), 35 / 45.0, delta=0.02)
        cv.cancel_crop(); P.w.setValue(30.0); P.h.setValue(35.0); P.save_preset.__func__  # exists
        import rstudio.ui.panels as pn
        class Dlg:
            @staticmethod
            def getText(*a, **k): return ("NID 30x35", True)
        old, pn.QInputDialog = pn.QInputDialog, Dlg
        try: P.save_preset()
        finally: pn.QInputDialog = old
        self.assertEqual(w.settings.custom_presets()[0][0], "NID 30x35"); self.assertEqual((P.w.value(), P.h.value()), (30.0, 35.0)); P.delete_preset(); self.assertEqual(w.settings.custom_presets(), [])
        blank = Document.new(100, 100, name="blank"); w.open_document(blank); msgs.clear(); P.face_crop(); self.assertTrue(wait(lambda: msgs, 20)); self.assertEqual(msgs[-1][0], "warn")
        for i in range(w.tabs.count()): w.tabs.widget(i).doc.dirty = False
        while w.tabs.count(): w.close_tab(w.tabs.count() - 1)
        w.open_document(Document.new(50, 50, name="x")); w.goto("home")
    def test_10d_autosave_and_recovery_flow(self):
        import rstudio.ui.main_window as mw
        w = self.w; d = Document.new(60, 40, name="unsaved"); w.open_document(d); d.add_text("precious", 3, 3, size=14); d.dirty = True
        w._autosave(); self.assertTrue(wait(lambda: len(w.recovery.pending()) == 1, 20)); self.assertEqual(w.recovery.pending()[0]["name"], "unsaved"); v = d.version; w._autosave(); self.assertEqual(w._auto_ver[d.uid], v)
        class Q:
            StandardButton = mw.QMessageBox.StandardButton
            @staticmethod
            def question(*a, **k): return mw.QMessageBox.StandardButton.Yes
        old, mw.QMessageBox = mw.QMessageBox, Q
        try: n = w.tabs.count(); w._offer_recovery()
        finally: mw.QMessageBox = old
        self.assertEqual(w.tabs.count(), n + 1); r = w.doc(); self.assertEqual((r.w, r.h, len(r.layers)), (60, 40, 2)); self.assertTrue(r.dirty); self.assertEqual(w.recovery.pending(), [])
        w.recovery.write(d.uid, d.name, d.snapshot()); d.dirty = False; w.tabs.setCurrentIndex(w.tabs.count() - 2); r.dirty = False; w.close_tab(w.tabs.count() - 1); w.close_tab(w.tabs.count() - 1)
        self.assertEqual(w.recovery.pending(), [])                                                       # closing cleanly removes the recovery copy
    def test_10e_qt_text_backend_with_fake_qt_falls_back(self):
        from rstudio.engine import document as D
        from rstudio.ui import qttext
        D.set_text_backend(qttext.render)
        try: px = D.render_text(dict(text="Hello বাংলা", size=30, color=[0, 0, 0, 255])); self.assertGreater(px.shape[0], 5); self.assertGreater((px[..., 3] > 0).sum(), 10)
        finally: D.set_text_backend(None)
    def test_11_icons_and_theme_data(self):
        import xml.dom.minidom as m
        for n in icons.NAMES: m.parseString(icons.svg(n, "#fff"))
        for name in theme.THEMES: self.assertIn("QPushButton", theme.stylesheet(name)); self.assertEqual(set(theme.DARK), set(theme.LIGHT))

if __name__ == "__main__": unittest.main(verbosity=2)

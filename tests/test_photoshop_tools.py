"""UI-level tests of the Photoshop-style tools: real canvas code driven with fake mouse events (fake Qt - see qt_stub.py)."""
import os, sys, tempfile, unittest
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qt_stub; qt_stub.install()
from PySide6.QtCore import Qt
from rstudio.engine.settings import Settings
from rstudio.engine.recovery import Recovery
from rstudio.engine.document import Document
import rstudio.ui.canvas as cvmod
import rstudio.ui.main_window as mw
from rstudio.ui.main_window import MainWindow, TOOLS
from test_cards import scene, card_img, Q1

class Pt:
    def __init__(self, x=0.0, y=0.0): self._x, self._y = float(x), float(y)
    def x(self): return self._x
    def y(self): return self._y
class Rect:
    def __init__(self, x=0, y=0, w=0, h=0): self._x, self._y, self._w, self._h = float(x), float(y), float(w), float(h)
    def left(self): return self._x
    def top(self): return self._y
    def right(self): return self._x + self._w
    def bottom(self): return self._y + self._h
    def width(self): return self._w
    def height(self): return self._h
    def center(self): return Pt(self._x + self._w / 2, self._y + self._h / 2)
class Mods:
    def __init__(self, *f): self.f = set(f)
    def __and__(self, flag): return flag in self.f
SH, AL, CT = Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.AltModifier, Qt.KeyboardModifier.ControlModifier
class Ev:
    def __init__(self, x=0, y=0, mods=(), dy=0, key=None): self.p, self.m, self.dy, self.k = Pt(x, y), Mods(*mods), dy, key
    def position(self): return self.p
    def modifiers(self): return self.m
    def button(self): return Qt.MouseButton.LeftButton
    def angleDelta(self): return Pt(0, self.dy)
    def key(self): return self.k
    def isAutoRepeat(self): return False

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = cvmod.QPointF; cvmod.QPointF = Pt; cls._origr = cvmod.QRectF; cvmod.QRectF = Rect                                    # numeric stand-in so the view maths can run under the fake Qt
        cls.td = tempfile.TemporaryDirectory(); s = Settings(os.path.join(cls.td.name, "s.json")); s.set("models_dir", os.path.join(cls.td.name, "m"))
        cls.w = MainWindow(s, Recovery(os.path.join(cls.td.name, "rec"))); cls.w.goto("photo")
    @classmethod
    def tearDownClass(cls): cvmod.QPointF = cls._orig; cvmod.QRectF = cls._origr; cls.td.cleanup()
    def setUp(self):
        w = self.w; w.opts.update(brush_size=20, brush_hardness=1.0, brush_opacity=1.0, brush_color=(0, 0, 0, 255), bg_color=(255, 255, 255, 255), sel_mode="new", marquee="rect", erase_transparent=False, wheel_zooms=False)
        while w.tabs.count(): w.docs()[-1].dirty = False; w.close_tab(w.tabs.count() - 1)
    def page(self, w=400, h=300, bg=(255, 255, 255, 255)):
        d = Document.new(w, h, 300, bg=bg, name="t"); self.w.open_document(d); c = self.w.canvas(); c.off = Pt(0, 0); c.zoom = 1.0; c._fit_mode = False; return d, c
    def drag(self, c, pts, mods=()):
        c.mousePressEvent(Ev(*pts[0], mods)); [c.mouseMoveEvent(Ev(*p, mods)) for p in pts[1:]]; c.mouseReleaseEvent(Ev(*pts[-1], mods))
    def px(self, d, x, y): return tuple(int(v) for v in d.composite()[y, x])

    # ------------------------------------------------------------------ every tool exists and has an options page
    def test_all_tools_selectable_with_options(self):
        self.page()
        for k, *_ in TOOLS: self.w.set_tool(k); self.assertIn(k, self.w._optpages)
        self.w.set_tool("move"); self.assertGreaterEqual(len(TOOLS), 17)

    # ------------------------------------------------------------------ selections
    def test_marquee_rect_ellipse_and_modes(self):
        d, c = self.page(); self.w.set_tool("select"); self.w.opts["marquee"] = "ellipse"; self.drag(c, [(50, 50), (100, 80), (150, 120)]); m = d.selection_mask()
        self.assertGreater(m[85, 100], 200); self.assertEqual(m[52, 52], 0, "the corner of the box is outside the ellipse")
        self.w.opts["marquee"] = "rect"; self.drag(c, [(140, 100), (200, 160), (250, 200)], (SH,)); self.assertGreater(d.selection_mask()[85, 100], 200); self.assertEqual(d.selection_mask()[180, 220], 255, "Shift adds")
        self.drag(c, [(60, 60), (150, 100), (260, 210)], (AL,)); self.assertEqual(d.selection_mask()[150, 200], 0, "Alt subtracts"); self.drag(c, [(10, 10), (12, 11), (11, 12)]); self.assertIsNone(d.selection, "a plain click deselects")
        self.drag(c, [(10, 10), (150, 150)]); self.drag(c, [(100, 100), (300, 250)], (SH, AL)); m = d.selection_mask(); self.assertEqual(int((m > 0).sum()), 50 * 50, "Shift+Alt intersects")
    def test_lasso_and_polygon_lasso(self):
        d, c = self.page(); self.w.set_tool("lasso"); self.drag(c, [(20, 20), (120, 20), (70, 100), (20, 20)]); self.assertGreater(d.selection_mask()[40, 70], 200); self.assertEqual(d.selection_mask()[90, 25], 0)
        d.clear_selection(); self.w.set_tool("poly")
        for p in ((200, 20), (300, 20), (300, 120)): c.mousePressEvent(Ev(*p)); c.mouseReleaseEvent(Ev(*p))
        self.assertIsNone(d.selection); self.assertEqual(len(c._poly), 3); c.keyPressEvent(Ev(key=Qt.Key.Key_Return)); self.assertIsNotNone(d.selection); self.assertEqual(c._poly, []); self.assertGreater(d.selection_mask()[40, 280], 200)
        self.w.set_tool("poly"); c.mousePressEvent(Ev(10, 10)); c.mousePressEvent(Ev(20, 10)); c.keyPressEvent(Ev(key=Qt.Key.Key_Escape)); self.assertEqual(c._poly, [])
    def test_magic_wand(self):
        d, c = self.page(); d.fill_selected(d.active_id, (0, 0, 0)); d.select_rect(100, 100, 200, 180); d.fill_selected(d.active_id, (255, 255, 255)); d.clear_selection(); self.w.set_tool("wand"); self.w.opts["wand_tol"] = 20
        c.mousePressEvent(Ev(150, 140)); c.mouseReleaseEvent(Ev(150, 140)); m = d.selection_mask(); self.assertEqual(int((m > 127).sum()), 100 * 80); self.assertEqual(d.selection, (100, 100, 200, 180))
        c.mousePressEvent(Ev(10, 10, (SH,))); c.mouseReleaseEvent(Ev(10, 10, (SH,))); self.assertGreater(int((d.selection_mask() > 127).sum()), 100 * 80 + 1000, "Shift adds the black area")
        self.w.opts["wand_contig"] = False; self.w.opts["sel_mode"] = "new"; c.mousePressEvent(Ev(150, 140)); c.mouseReleaseEvent(Ev(150, 140)); self.assertEqual(int((d.selection_mask() > 127).sum()), 100 * 80)
    def test_inverse_delete_fill_and_layer_via_copy(self):
        d, c = self.page(); L = d.add_image_layer(np.full((100, 100, 3), (200, 0, 0), np.uint8), "pic", 50, 50); self.w.goto("photo"); d.select_rect(60, 60, 100, 100)
        self.w.clear_pixels(); self.assertEqual(self.px(d, 70, 70)[:3], (255, 255, 255)); self.assertEqual(d.layer(L.id).pixels[20, 20, 3], 0)
        self.w.fill_selection(False); self.assertEqual(self.px(d, 70, 70)[:3], (0, 0, 0)); self.w.opts["brush_color"] = (0, 255, 0, 255); self.w.fill_selection(False); self.assertEqual(self.px(d, 70, 70)[:3], (0, 255, 0))
        self.w.opts["bg_color"] = (0, 0, 255, 255); self.w.fill_selection(True); self.assertEqual(self.px(d, 70, 70)[:3], (0, 0, 255))
        n = len(d.layers); self.w.layer_via_copy(); self.assertEqual(len(d.layers), n + 1); self.assertEqual(d.layers[-1].name, "Layer via copy"); d.clear_selection(); self.w.layer_via_copy(); self.assertEqual(len(d.layers), n + 2, "Ctrl+J without a selection duplicates")
        d.select_rect(0, 0, 100, 100); self.w.invert_selection(); self.assertEqual(d.selection_mask()[50, 50], 0); self.assertEqual(d.selection_mask()[200, 300], 255)
        d.active_id = d.layers[0].id; d.select_rect(10, 10, 60, 60); self.w.clear_pixels(); self.assertEqual(self.px(d, 20, 20)[:3], (0, 0, 255), "Delete on the Background layer paints the background colour (blue here), it does not make a hole")
    def test_move_tool_drags_the_selected_pixels(self):
        d, c = self.page(); L = d.add_image_layer(np.full((100, 100, 3), (200, 0, 0), np.uint8), "pic", 50, 50); d.select_rect(60, 60, 110, 110); self.w.set_tool("move"); n = len(d.layers)
        self.drag(c, [(80, 80), (90, 80), (110, 80)]); self.assertEqual(len(d.layers), n + 1); moved = d.layers[-1]; self.assertEqual(moved.name, "Moved selection"); self.assertEqual((moved.x, moved.y), (60 + 30, 60)); self.assertIsNone(d.selection)
        self.assertEqual(d.layer(L.id).pixels[15, 15, 3], 0, "a hole stays where the pixels came from")
        d2, c2 = self.page(); L2 = d2.add_image_layer(np.full((100, 100, 3), 90, np.uint8), "pic", 50, 50); d2.select_rect(60, 60, 110, 110); self.w.opts["move_selection"] = False; self.drag(c2, [(80, 80), (110, 80)]); self.assertEqual(len(d2.layers), 2); self.w.opts["move_selection"] = True

    # ------------------------------------------------------------------ brush, eraser, clone, bucket, gradient
    def test_hard_and_soft_brush_strokes(self):
        d, c = self.page(); self.w.set_tool("brush"); self.drag(c, [(50, 50), (100, 50), (150, 50)]); self.assertEqual(self.px(d, 100, 50)[:3], (0, 0, 0)); self.assertEqual(self.px(d, 100, 70)[:3], (255, 255, 255)); n = len(d.history_labels()); self.assertEqual(d.history_labels()[-1], "Brush stroke")
        d.undo(); self.assertEqual(self.px(d, 100, 50)[:3], (255, 255, 255)); self.w.opts.update(brush_hardness=0.0, brush_size=60); self.drag(c, [(200, 150), (220, 150)]); row = [self.px(d, x, 150)[0] for x in range(172, 211)]
        self.assertLess(row[-1], 40); self.assertGreater(row[0], 225); self.assertGreater(len(set(row)), 8, "soft edge is gradual")
    def test_painting_outside_a_small_layer_works(self):
        d, c = self.page(); L = d.add_image_layer(np.full((50, 50, 3), 90, np.uint8), "small", 100, 100); self.w.set_tool("brush"); self.drag(c, [(10, 10), (30, 10)]); self.assertEqual(self.px(d, 20, 10)[:3], (0, 0, 0)); l = d.layer(L.id); self.assertGreaterEqual(l.w, 400); self.assertEqual((l.x, l.y), (0, 0))
        self.assertEqual(self.px(d, 120, 120)[:3], (90, 90, 90), "the picture itself is unchanged")
    def test_shift_click_straight_line_and_alt_picker(self):
        d, c = self.page(); self.w.set_tool("brush"); self.drag(c, [(20, 20), (21, 20)]); self.drag(c, [(220, 20)], (SH,)); self.assertEqual(self.px(d, 120, 20)[:3], (0, 0, 0), "Shift+click draws a straight line from the last point")
        d.fill_selected(d.active_id, (10, 200, 30)); n = len(d.history_labels()); c.mousePressEvent(Ev(50, 50, (AL,))); c.mouseReleaseEvent(Ev(50, 50, (AL,))); self.assertEqual(tuple(self.w.opts["brush_color"][:3]), (10, 200, 30)); self.assertEqual(len(d.history_labels()), n, "Alt+click picks, it does not paint")
    def test_eraser_background_vs_layer_and_transparent_option(self):
        d, c = self.page(); self.w.set_tool("brush"); self.drag(c, [(50, 50), (150, 50)]); self.w.set_tool("eraser"); self.drag(c, [(90, 50), (110, 50)]); self.assertEqual(self.px(d, 100, 50), (255, 255, 255, 255), "on the Background layer the eraser paints the background colour")
        self.w.opts["erase_transparent"] = True; self.drag(c, [(60, 50), (70, 50)]); self.assertEqual(self.px(d, 65, 50)[3], 0); self.w.opts["erase_transparent"] = False
        L = d.add_image_layer(np.full((100, 100, 3), 77, np.uint8), "pic", 200, 100); self.w.set_tool("eraser"); self.drag(c, [(230, 130), (240, 130)]); self.assertEqual(d.layer(L.id).pixels[30, 35, 3], 0, "on a normal layer the eraser makes it transparent")
    def test_painting_stays_inside_a_selection(self):
        d, c = self.page(); d.select_rect(100, 0, 400, 300); self.w.set_tool("brush"); self.drag(c, [(60, 50), (160, 50)]); self.assertEqual(self.px(d, 80, 50)[:3], (255, 255, 255)); self.assertEqual(self.px(d, 130, 50)[:3], (0, 0, 0))
    def test_paint_bucket_and_gradient(self):
        d, c = self.page(); d.select_rect(0, 0, 200, 300); d.fill_selected(d.active_id, (0, 0, 0)); d.clear_selection(); self.w.opts["brush_color"] = (255, 0, 0, 255); self.w.set_tool("bucket"); c.mousePressEvent(Ev(300, 100)); c.mouseReleaseEvent(Ev(300, 100))
        self.assertEqual(self.px(d, 350, 250)[:3], (255, 0, 0)); self.assertEqual(self.px(d, 50, 50)[:3], (0, 0, 0)); self.assertEqual(d.history_labels()[-1], "Paint bucket")
        self.w.opts.update(brush_color=(255, 0, 0, 255), bg_color=(0, 0, 255, 255)); self.w.set_tool("gradient"); self.drag(c, [(0, 150), (200, 150), (400, 150)]); self.assertLessEqual(abs(self.px(d, 1, 150)[0] - 255) + self.px(d, 1, 150)[2], 4); self.assertLessEqual(self.px(d, 398, 150)[0], 4); self.assertGreater(self.px(d, 398, 150)[2], 250); self.assertEqual(d.history_labels()[-1], "Gradient")
        self.w.opts["grad_kind"] = "radial"; self.drag(c, [(200, 150), (250, 150), (300, 150)]); self.assertEqual(self.px(d, 200, 150)[:3], (255, 0, 0))
    def test_clone_stamp(self):
        d, c = self.page(); d.select_rect(0, 0, 100, 300); d.fill_selected(d.active_id, (255, 0, 0)); d.clear_selection(); self.w.set_tool("clone"); self.drag(c, [(300, 100), (310, 100)])
        self.assertEqual(self.px(d, 305, 100)[:3], (255, 255, 255), "no source set yet: nothing is copied"); c.mousePressEvent(Ev(50, 100, (AL,))); c.mouseReleaseEvent(Ev(50, 100, (AL,))); self.drag(c, [(250, 100), (260, 100)])
        self.assertEqual(self.px(d, 255, 100)[:3], (255, 0, 0), "aligned clone: target x copies from x - 200, which is red"); self.assertEqual(d.history_labels()[-1], "Clone stamp"); self.assertEqual(self.px(d, 350, 100)[:3], (255, 255, 255))
    def test_keyboard_actions_for_brush_and_colours(self):
        self.page(); o = self.w.opts; s0 = o["brush_size"]; self.w.brush_step(1.12); self.assertGreater(o["brush_size"], s0); self.w.brush_step(1 / 1.12); self.assertLessEqual(o["brush_size"], s0 + 1); o["brush_size"] = 1; self.w.brush_step(1 / 1.12); self.assertEqual(o["brush_size"], 1)
        o["brush_size"] = 1500; self.w.brush_step(1.12); self.assertEqual(o["brush_size"], 1500); o["brush_hardness"] = 1.0; self.w.brush_hard(0.1); self.assertEqual(o["brush_hardness"], 1.0); self.w.brush_hard(-0.3); self.assertAlmostEqual(o["brush_hardness"], 0.7)
        o["brush_color"], o["bg_color"] = (1, 2, 3, 255), (4, 5, 6, 255); self.w.swap_colors(); self.assertEqual((o["brush_color"], o["bg_color"]), ((4, 5, 6, 255), (1, 2, 3, 255))); self.w.default_colors(); self.assertEqual((o["brush_color"], o["bg_color"]), ((0, 0, 0, 255), (255, 255, 255, 255)))

    # ------------------------------------------------------------------ ID cards and moving things between documents
    def wait(self, pred, secs=30):
        import time; end = time.time() + secs
        while time.time() < end:
            if pred(): return True
            time.sleep(0.02)
        return False
    def test_auto_crop_id_card_one_click(self):
        w = self.w; msgs = []; w.notify = lambda m, k="info": msgs.append((k, m)); d = Document.from_image(scene([Q1]), "scan", 200); w.open_document(d); w.goto("photo")
        w.auto_crop_cards(); self.assertTrue(self.wait(lambda: (d.w, d.h) == (1011, 638)), (d.w, d.h, msgs)); self.assertEqual(d.dpi, 300); self.assertEqual(msgs[-1][0], "ok"); d.undo(); self.assertEqual((d.w, d.h), (1400, 1000))
        q_top = [(250, 80), (850, 90), (840, 440), (240, 430)]; q_bot = [(250, 560), (850, 570), (840, 920), (240, 910)]; n = w.tabs.count(); both = Document.from_image(scene([q_top, q_bot]), "both", 200); w.open_document(both)
        w.auto_crop_cards(); self.assertTrue(self.wait(lambda: w.tabs.count() == n + 3)); names = [x.name for x in w.docs()[-2:]]; self.assertEqual(names, ["both - front", "both - back"]); self.assertEqual((w.docs()[-1].w, w.docs()[-1].h), (1011, 638))
        blank = Document.new(300, 300, name="blank"); w.open_document(blank); msgs.clear(); w.auto_crop_cards(); self.assertTrue(self.wait(lambda: msgs)); self.assertEqual(msgs[-1][0], "warn"); self.assertEqual((blank.w, blank.h), (300, 300))
    def test_perspective_tool_finds_a_card_with_the_card_preset(self):
        d, c = self.page(1400, 1000); d.replace_with_image(scene([Q1]), "scan"); w = self.w; w.set_tool("perspective"); idx = [i for i in range(w.persp_out.count()) if w.persp_out.itemData(i) == (85.6, 54.0)][0]
        w.persp_out.setCurrentIndex(idx); self.assertAlmostEqual(w.opts["persp_aspect"], 85.6 / 54.0, delta=0.001); found, conf = c.auto_perspective(); self.assertTrue(found); self.assertGreater(conf, 0.5)
        from test_cards import err
        self.assertLess(err(c.persp, Q1), 20)
    def test_drag_a_selection_onto_another_documents_tab_copies_it(self):
        w = self.w; a, ca = self.page(); L = a.add_image_layer(np.full((100, 100, 3), (200, 0, 0), np.uint8), "pic", 50, 50); a.select_rect(60, 60, 110, 110); a.commit("Selection", dirty=False); b = Document.new(300, 200, name="other"); w.open_document(b); w.tabs.setCurrentIndex(0)
        w.set_tool("move"); before = np.array(a.layer(L.id).pixels).copy(); nl = len(a.layers); w._tab_under = lambda c, x, y: 1
        try:
            ca.mousePressEvent(Ev(80, 80)); ca.mouseMoveEvent(Ev(90, 80)); self.assertEqual(len(a.layers), nl + 1); ca.mouseMoveEvent(Ev(-30, -20)); ca.mouseReleaseEvent(Ev(-30, -20))
        finally: del w._tab_under
        self.assertEqual(len(b.layers), 2); part = b.layers[-1]; self.assertEqual((part.w, part.h), (50, 50)); self.assertEqual(len(a.layers), nl, "the source document is back as it was"); self.assertTrue(np.array_equal(np.array(a.layer(L.id).pixels), before)); self.assertIsNotNone(a.selection)
        self.assertIs(w.doc(), b)
    def test_drag_a_whole_layer_outside_without_a_tab_snaps_back(self):
        w = self.w; msgs = []; w.notify = lambda m, k="info": msgs.append((k, m)); a, ca = self.page(); L = a.add_image_layer(np.full((100, 100, 3), 90, np.uint8), "pic", 50, 50); w.set_tool("move"); w._tab_under = lambda c, x, y: -1
        try: ca.mousePressEvent(Ev(80, 80)); ca.mouseMoveEvent(Ev(120, 90)); ca.mouseReleaseEvent(Ev(-10, -10))
        finally: del w._tab_under
        self.assertEqual((a.layer(L.id).x, a.layer(L.id).y), (50, 50)); self.assertEqual(msgs[-1][0], "warn")
        other = Document.new(200, 200, name="o2"); w.open_document(other); w.tabs.setCurrentIndex(w.tabs.count() - 2); w._tab_under = lambda c, x, y: w.tabs.count() - 1; n = len(a.layers)
        try: ca.mousePressEvent(Ev(80, 80)); ca.mouseMoveEvent(Ev(100, 80)); ca.mouseReleaseEvent(Ev(-10, -10))
        finally: del w._tab_under
        self.assertEqual(len(other.layers), 2); self.assertEqual((a.layer(L.id).x, a.layer(L.id).y), (50, 50)); self.assertEqual(len(a.layers), n)
    def test_copy_selection_to_document_and_clipboard_copy_only_the_part(self):
        import rstudio.ui.main_window as mwm
        w = self.w; a, ca = self.page(); L = a.add_image_layer(np.full((100, 100, 3), (0, 200, 0), np.uint8), "pic", 50, 50); a.select_rect(60, 60, 90, 80); b = Document.new(300, 200, name="dest"); w.open_document(b); w.tabs.setCurrentIndex(0); w.copy_layer_to(b)
        self.assertEqual((b.layers[-1].w, b.layers[-1].h), (30, 20)); shapes = []; mwm.clip.set_image = lambda arr: shapes.append(arr.shape); w.copy_clipboard(); self.assertEqual(shapes[-1][:2], (20, 30))
    def test_nid_wizard_with_both_cards_in_one_picture(self):
        from rstudio.ui.sheets import PrintSheetDialog
        w = self.w; q_top = [(250, 80), (850, 90), (840, 440), (240, 430)]; q_bot = [(250, 560), (850, 570), (840, 920), (240, 910)]
        imgs = [np.full((404, 640, 3), (200, 40, 40), np.uint8), np.full((404, 640, 3), (40, 40, 200), np.uint8)]; both = scene([q_top, q_bot], imgs=imgs)
        dlg = PrintSheetDialog(w, "nid"); dlg.src[0].set_rgb(both); dlg.one.setChecked(True); docs, msg = dlg.build(); cards_ = [l for l in docs[0].layers if l.name.startswith("Card")]; self.assertEqual(len(cards_), 2); self.assertEqual((cards_[0].w, cards_[0].h), (1011, 638))
        self.assertGreater(int(cards_[0].pixels[300, 500, 0]), 150, "front = the upper (red) card"); self.assertGreater(int(cards_[1].pixels[300, 500, 2]), 150, "back = the lower (blue) card")
        dlg.swap.setChecked(True); docs, _ = dlg.build(); c2 = [l for l in docs[0].layers if l.name.startswith("Card")]; self.assertGreater(int(c2[0].pixels[300, 500, 2]), 150)
        single = PrintSheetDialog(w, "nid"); single.src[0].set_rgb(scene([Q1])); single.one.setChecked(True)
        with self.assertRaises(ValueError) as e: single.build()
        self.assertIn("two are needed", str(e.exception))

    # ------------------------------------------------------------------ Retouch workspace and Document Studio extras (ported from the earlier Photostudio)
    def astro_doc(self):
        import skimage.data as sd; d = Document.from_image(np.ascontiguousarray(sd.astronaut()), "face", 300); self.w.open_document(d); return d
    def test_retouch_panel_doctor_skin_redeye_and_online_export(self):
        import rstudio.ui.panels as pn, cv2
        w = self.w; msgs = []; w.notify = lambda m, k="info": msgs.append((k, m)); d = self.astro_doc(); w.goto("retouch"); P = w.panels["retouch"]; self.assertEqual(P.title, "Retouch")
        P.analyze(); self.assertTrue(self.wait(lambda: "Brightness" in P.report.text())); n = len(d.layers); P.auto_fix(); self.assertTrue(self.wait(lambda: msgs and msgs[-1][1].startswith(("The picture looks fine", "Fixed"))))
        dark = Document.from_image((np.clip(np.array(d.to_pil().convert("RGB")).astype(np.float32) * 0.35, 0, 255)).astype(np.uint8), "dark", 300); w.open_document(dark); n = len(dark.layers); msgs.clear(); P.auto_fix()
        self.assertTrue(self.wait(lambda: len(dark.layers) == n + 1)); self.assertEqual(dark.layers[-1].name, "Photo doctor"); self.assertIn("exposure", msgs[-1][1]); self.assertGreater(float(dark.layers[-1].pixels[..., :3].mean()), float(dark.layers[0].pixels[..., :3].mean()) + 20)
        w.tabs.setCurrentIndex(w.tabs.count() - 2); d2 = w.doc(); n = len(d2.layers); P.skin(); self.assertTrue(self.wait(lambda: len(d2.layers) == n + 1)); self.assertEqual(d2.layers[-1].name, "Skin retouch")
        from rstudio.engine import restore; f, _ = restore.detect_faces(np.array(d2.to_pil().convert("RGB"))); top = d2.layers[-1]; img = np.array(top.pixels).copy()
        for key in ("le", "re"): cv2.circle(img, (int(f[0][key][0]), int(f[0][key][1])), max(4, int(0.05 * f[0]["bbox"][2])), (230, 20, 20, 255), -1)
        d2.set_pixels(top.id, img, "paint red eyes"); n = len(d2.layers); P.red_eye(); self.assertTrue(self.wait(lambda: len(d2.layers) == n + 1)); self.assertEqual(d2.layers[-1].name, "Red eyes fixed")
        blank = Document.new(200, 200, name="blank"); w.open_document(blank); msgs.clear(); P.skin(); self.assertTrue(self.wait(lambda: msgs)); self.assertEqual(msgs[-1][0], "warn"); self.assertEqual(len(blank.layers), 1)
        class FD:
            @staticmethod
            def getSaveFileName(*a, **k): return (os.path.join(self.td.name, "online"), "")
        old, pn.QFileDialog = pn.QFileDialog, FD
        try: w.tabs.setCurrentIndex(w.tabs.count() - 3); P.kb.setValue(40); P.save_kb()
        finally: pn.QFileDialog = old
        out = os.path.join(self.td.name, "online.jpg"); self.assertTrue(self.wait(lambda: os.path.exists(out))); self.assertLessEqual(os.path.getsize(out), 40 * 1024)
        dd = w.doc(); h0 = dd.h; P.cap.setText("Md. Rahim"); P.caption(); self.assertGreater(dd.h, h0); n = len(dd.layers); P.wm.setText("COPY"); P.watermark(); self.assertEqual(len(dd.layers), n + 1); self.assertEqual(dd.layers[-1].name, "Watermark")
        msgs.clear(); P.cap.setText(""); P.caption(); self.assertEqual(msgs[-1][0], "warn")
    def test_document_studio_split_and_signature(self):
        w = self.w; msgs = []; w.notify = lambda m, k="info": msgs.append((k, m)); import cv2
        q = [[(80, 60), (480, 60), (480, 320), (80, 320)], [(560, 60), (960, 60), (960, 320), (560, 320)]]; imgs = []
        for col in ((200, 40, 40), (40, 160, 40)): a = np.full((260, 400, 3), col, np.uint8); cv2.putText(a, "DOC", (40, 150), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 4); imgs.append(a)
        d = Document.from_image(scene(q, size=(1100, 420), imgs=imgs, shadow=False), "twodocs", 200); w.open_document(d); w.goto("doc"); P = w.panels["doc"]; n = w.tabs.count(); P.split_docs()
        self.assertTrue(self.wait(lambda: w.tabs.count() == n + 2)); self.assertEqual([x.name for x in w.docs()[-2:]], ["twodocs - 1", "twodocs - 2"])
        paper = np.full((200, 500, 3), 235, np.uint8); cv2.putText(paper, "Rahim", (60, 130), cv2.FONT_HERSHEY_SCRIPT_COMPLEX, 3, (30, 30, 120), 4, cv2.LINE_AA); s = Document.from_image(paper, "sig scan", 300); w.open_document(s); n = w.tabs.count(); P.signature()
        self.assertTrue(self.wait(lambda: w.tabs.count() == n + 1)); sig = w.doc(); self.assertEqual(sig.name, "signature"); self.assertEqual(int(sig.layers[0].pixels[0, 0, 3]), 0)
        blank = Document.new(300, 300, name="b"); w.open_document(blank); msgs.clear(); P.signature(); self.assertTrue(self.wait(lambda: msgs)); self.assertEqual(msgs[-1][0], "warn")
    def test_home_has_the_retouch_card_and_nav_entry(self):
        from rstudio.ui.main_window import NAV
        self.assertIn("retouch", [k for k, _, _ in NAV]); self.assertIn("retouch", [c[0] for c in self.w.home.CARDS]); self.w._home_action("retouch"); self.assertEqual(self.w._nav, "retouch"); self.w.goto("photo")

    # ------------------------------------------------------------------ view, text, history
    def test_photoshop_wheel_behaviour(self):
        d, c = self.page(); c.zoom, c.off = 1.0, Pt(0, 0); c.wheelEvent(Ev(100, 100, (), 120)); self.assertEqual(c.zoom, 1.0); self.assertGreater(c.off.y(), 0); y1 = c.off.y()
        c.wheelEvent(Ev(100, 100, (SH,), 120)); self.assertGreater(c.off.x(), 0); self.assertEqual(c.off.y(), y1)
        c.zoom, c.off = 1.0, Pt(0, 0); c.wheelEvent(Ev(100, 100, (CT,), 120)); self.assertGreater(c.zoom, 1.1); self.assertAlmostEqual(c.off.x() + 100 * c.zoom - 100 * c.zoom, c.off.x()); self.assertAlmostEqual((100 - c.off.x()) / c.zoom, 100, delta=0.5)
        c.zoom, c.off = 1.0, Pt(0, 0); c.wheelEvent(Ev(100, 100, (AL,), -120)); self.assertLess(c.zoom, 1.0); c.zoom = 1.0; self.w.apply_wheel_setting(True); c.wheelEvent(Ev(100, 100, (), 120)); self.assertGreater(c.zoom, 1.1); self.w.apply_wheel_setting(False)
        self.w.set_tool("zoom"); c.zoom = 1.0; c.mousePressEvent(Ev(50, 50)); c.mouseReleaseEvent(Ev(50, 50)); self.assertAlmostEqual(c.zoom, 1.5); c.mousePressEvent(Ev(50, 50, (AL,))); c.mouseReleaseEvent(Ev(50, 50, (AL,))); self.assertAlmostEqual(c.zoom, 1.0, delta=0.01)
    def test_text_tool_asks_for_the_text_and_edits_existing(self):
        d, c = self.page(); calls = []
        class Q:
            @staticmethod
            def getMultiLineText(*a, **k): calls.append(a); return ("Hello world", True)
        old, mw.QInputDialog = mw.QInputDialog, Q
        try:
            self.w.set_tool("text"); c.mousePressEvent(Ev(40, 60)); c.mouseReleaseEvent(Ev(40, 60)); self.assertEqual(len(d.layers), 2); t = d.layers[-1]; self.assertEqual(t.kind, "text"); self.assertEqual(t.params["text"], "Hello world")
            Q.getMultiLineText = staticmethod(lambda *a, **k: ("Changed", True)); px, py = t.x + 5, t.y + t.h // 2; c.mousePressEvent(Ev(px, py)); c.mouseReleaseEvent(Ev(px, py)); self.assertEqual(len(d.layers), 2); self.assertEqual(d.layers[-1].params["text"], "Changed")
            Q.getMultiLineText = staticmethod(lambda *a, **k: ("x", False)); n = len(d.history_labels()); c.mousePressEvent(Ev(300, 250)); c.mouseReleaseEvent(Ev(300, 250)); self.assertEqual(len(d.history_labels()), n, "cancel adds nothing")
        finally: mw.QInputDialog = old
    def test_recent_history_can_be_removed_and_cleared(self):
        w = self.w; files = []
        for n in ("a.png", "b.png", "c.png"):
            p = os.path.join(self.td.name, n); open(p, "w").close(); files.append(p); w.settings.add_recent(p)
        w.goto("home"); self.assertEqual(len(w.settings.recent_existing()), 3); w._remove_recent(files[1]); self.assertEqual([os.path.basename(x) for x in w.settings.recent_existing()], ["c.png", "a.png"])
        w.settings.save(); self.assertEqual(Settings(w.settings.path).recent_existing().__len__(), 2); msgs = []; w.notify = lambda m, k="info": msgs.append(m); w.clear_recent(); self.assertEqual(w.settings.recent_existing(), []); self.assertTrue(all(os.path.exists(f) for f in files), "files are never deleted")
        self.assertEqual(Settings(w.settings.path).recent_existing(), []); self.assertIn("cleared", msgs[-1]); w.settings_page.clear_recovery(); w.goto("photo")

if __name__ == "__main__": unittest.main(verbosity=1)

import os, sys, unittest
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rstudio.engine import select as S, brush as B
from rstudio.engine.document import Document, Layer, to_rgba

class TestSelectionMasks(unittest.TestCase):
    def test_shapes(self):
        r = S.rect_mask(50, 80, 10, 5, 30, 25); self.assertEqual(int((r > 0).sum()), 20 * 20); self.assertEqual(S.bbox(r), (10, 5, 30, 25))
        e = S.ellipse_mask(100, 100, 20, 20, 80, 60); self.assertGreater(e[40, 50], 200); self.assertEqual(e[20, 20], 0); a = (e > 127).sum(); self.assertAlmostEqual(a, np.pi * 30 * 20, delta=np.pi * 30 * 20 * 0.06)
        p = S.polygon_mask(50, 50, [(5, 5), (45, 5), (25, 45)]); self.assertGreater(p[15, 25], 200); self.assertEqual(p[45, 5], 0); self.assertEqual(S.polygon_mask(50, 50, [(1, 1), (2, 2)]).max(), 0)
        self.assertEqual(S.rect_mask(10, 10, -5, -5, 3, 3)[0, 0], 255); self.assertEqual(S.rect_mask(10, 10, 20, 20, 30, 30).max(), 0)
    def test_magic_wand_contiguous_and_global(self):
        img = np.full((60, 60, 3), 200, np.uint8); img[:, 30:] = (40, 40, 200); img[10:20, 5:15] = 200; img[40:50, 40:50] = 200      # a blue half with a grey island, plus a separate grey square
        m = S.wand_mask(img, 5, 5, 10, True); self.assertEqual(m[5, 5], 255); self.assertEqual(m[0, 59], 0); self.assertEqual(m[45, 45], 0, "the island inside the blue half is not connected"); self.assertGreater(int((m > 0).sum()), 30 * 60 - 10)
        g = S.wand_mask(img, 5, 5, 10, False); self.assertEqual(g[45, 45], 255, "non-contiguous also takes the grey square in the blue half"); b = S.wand_mask(img, 50, 5, 10, False); self.assertEqual(b[0, 59], 255); self.assertEqual(b[5, 5], 0)
        t = S.wand_mask(img, 5, 5, 255, True); self.assertTrue((t == 255).all(), "tolerance 255 selects everything"); self.assertEqual(S.wand_mask(img, -1, 5).max(), 0); self.assertEqual(S.wand_mask(img, 5, 999).max(), 0)
    def test_modes(self):
        a = S.rect_mask(40, 40, 0, 0, 20, 20); b = S.rect_mask(40, 40, 10, 10, 30, 30)
        self.assertEqual(int((S.combine(a, b, "add") > 0).sum()), 400 + 400 - 100); self.assertEqual(int((S.combine(a, b, "inter") > 0).sum()), 100); self.assertEqual(int((S.combine(a, b, "sub") > 0).sum()), 300)
        self.assertTrue(np.array_equal(S.combine(a, b, "new"), b)); self.assertTrue(np.array_equal(S.combine(None, b, "add"), b)); self.assertIsNone(S.combine(None, b, "sub")); self.assertIsNone(S.combine(None, b, "inter"))
        with self.assertRaises(ValueError): S.combine(a, b, "xor")
    def test_invert_feather_grow_outline(self):
        a = S.rect_mask(40, 40, 10, 10, 30, 30); inv = S.invert(a); self.assertEqual(int(a.astype(int).sum() + inv.astype(int).sum()), 255 * 1600); self.assertEqual(S.invert(None, 5, 5).min(), 255)
        f = S.feather(a, 8); self.assertTrue(((f > 0) & (f < 255)).any()); self.assertGreater(f[20, 20], 200); self.assertTrue(np.array_equal(S.feather(a, 0), a))
        g = S.grow(a, 3); self.assertEqual(S.bbox(g), (7, 7, 33, 33)); s = S.grow(a, -3); self.assertEqual(S.bbox(s), (13, 13, 27, 27)); self.assertTrue(np.array_equal(S.grow(a, 0), a))
        o = S.outline(a); self.assertEqual(len(o), 1); self.assertGreaterEqual(len(o[0]), 4); self.assertEqual(S.outline(np.zeros((20, 20), np.uint8)), [])

class TestDocumentSelection(unittest.TestCase):
    def doc(self): d = Document.new(100, 80, bg=(255, 255, 255, 255)); L = d.add_image_layer(np.full((60, 60, 3), (200, 0, 0), np.uint8), "pic", 20, 10); return d, L
    def test_mask_selection_undo_and_bbox(self):
        d, L = self.doc(); n0 = len(d.history_labels()); d.set_selection_mask(S.ellipse_mask(80, 100, 30, 20, 70, 60)); self.assertIsNotNone(d.selection); self.assertLessEqual(abs(d.selection[0] - 30) + abs(d.selection[1] - 20), 2, "box hugs the ellipse (anti-aliased edge may add 1 px)"); d.commit("Selection", dirty=False)
        d.clear_selection(); d.commit("Deselect", dirty=False); self.assertIsNone(d.selection); self.assertIsNone(d.sel_mask); d.undo(); self.assertIsNotNone(d.sel_mask); self.assertLessEqual(abs(d.selection[0] - 30), 1)
        d.set_selection_mask(np.zeros((80, 100), np.uint8)); self.assertIsNone(d.selection)
    def test_adjustment_follows_the_mask_not_just_the_box(self):
        d, L = self.doc(); d.set_selection_mask(S.ellipse_mask(80, 100, 20, 10, 80, 70)); d.apply_to_layer(L.id, lambda a: np.zeros_like(a) + np.array([0, 0, 255, 255], np.uint8), "blue"); c = d.composite()
        self.assertEqual(tuple(c[40, 50, :3]), (0, 0, 255)); self.assertEqual(tuple(c[11, 21, :3]), (200, 0, 0), "a corner of the box lies outside the ellipse and is untouched")
    def test_feathered_selection_blends_softly(self):
        d, L = self.doc(); d.set_selection_mask(S.feather(S.rect_mask(80, 100, 30, 20, 70, 60), 12)); d.apply_to_layer(L.id, lambda a: np.zeros_like(a) + np.array([0, 255, 0, 255], np.uint8), "green"); g = d.composite()[:, :, 1]
        self.assertGreater(g[40, 50], 230); self.assertLess(int(g[12, 22]), 10); self.assertTrue(((g[40, 28:40] > 5) & (g[40, 28:40] < 250)).any(), "values change gradually across the feathered edge")
    def test_invert_feather_grow_via_document(self):
        d, L = self.doc(); d.select_rect(20, 20, 40, 40); d.invert_selection(); m = d.selection_mask(); self.assertEqual(m[30, 30], 0); self.assertEqual(m[5, 5], 255); d.invert_selection(); d.grow_selection(5); self.assertEqual(d.selection, (15, 15, 45, 45))
        d.feather_selection(6); self.assertTrue(((d.selection_mask() > 0) & (d.selection_mask() < 255)).any()); d.select_all(); self.assertEqual(d.selection, (0, 0, 100, 80)); self.assertIsInstance(d.selection_outline(), list)
    def test_delete_makes_holes_but_background_gets_colour(self):
        d, L = self.doc(); d.select_rect(30, 20, 50, 40); self.assertTrue(d.clear_selected(L.id)); self.assertEqual(d.layer(L.id).pixels[20 - 10, 30 - 20, 3], 0); self.assertEqual(d.layer(L.id).pixels[0, 0, 3], 255)
        bg = d.layers[0]; self.assertTrue(bg.is_background); d.select_rect(0, 0, 10, 10); d.active_id = bg.id; d.clear_selected(bg.id, (10, 20, 30, 255)); self.assertEqual(tuple(d.layers[0].pixels[5, 5]), (10, 20, 30, 255))
        d.clear_selection(); self.assertFalse(d.clear_selected(L.id))
    def test_fill_selection_and_whole_layer(self):
        d, L = self.doc(); d.select_rect(20, 10, 40, 30); d.fill_selected(L.id, (0, 255, 0)); p = d.layer(L.id).pixels; self.assertEqual(tuple(p[0, 0, :3]), (0, 255, 0)); self.assertEqual(tuple(p[50, 50, :3]), (200, 0, 0))
        d.clear_selection(); d.fill_selected(L.id, (0, 0, 255), 0.5); q = d.layer(L.id).pixels[50, 50]; self.assertTrue(80 <= q[0] <= 120 and 120 <= q[2] <= 135)
    def test_layer_via_copy_and_cut(self):
        d, L = self.doc(); d.set_selection_mask(S.ellipse_mask(80, 100, 30, 20, 70, 60)); n = len(d.layers); new = d.layer_from_selection(L.id); self.assertEqual(len(d.layers), n + 1); self.assertEqual(d.active_id, new.id); self.assertLessEqual(abs(new.x - 30) + abs(new.y - 20), 2)
        self.assertEqual(new.pixels[20, 20, 3], 255); self.assertEqual(new.pixels[0, 0, 3], 0, "outside the ellipse: transparent"); self.assertEqual(d.layer(L.id).pixels[20, 20, 3], 255, "copy leaves the source alone")
        cut = d.layer_from_selection(L.id, cut=True); self.assertEqual(d.layer(L.id).pixels[40 - 10, 50 - 20, 3], 0, "cut removes the pixels from the source"); self.assertEqual(cut.pixels[20, 20, 3], 255); d.undo(); self.assertEqual(d.layer(L.id).pixels[30, 30, 3], 255)
        d.clear_selection(); self.assertIsNone(d.layer_from_selection(L.id))
    def test_crop_resets_selection_and_mask(self):
        d, L = self.doc(); d.set_selection_mask(S.ellipse_mask(80, 100, 30, 20, 70, 60)); d.crop(0, 0, 50, 50); self.assertIsNone(d.selection); self.assertIsNone(d.sel_mask)

class TestBrush(unittest.TestCase):
    def test_tip_shapes(self):
        hard = B.tip(20, 1.0); soft = B.tip(20, 0.0); self.assertEqual(hard.shape, (20, 20)); self.assertEqual(hard[10, 10], 255); self.assertEqual(hard[0, 0], 0)
        self.assertAlmostEqual(int((hard > 127).sum()), np.pi * 100, delta=np.pi * 100 * 0.08); self.assertEqual(soft[10, 10], 255 if soft[10, 10] == 255 else soft[10, 10]); self.assertLess(soft[10, 5], 200); self.assertGreater(soft[10, 10], soft[10, 3])
        mid = B.tip(40, 0.5); row = mid[20, 20:]; self.assertTrue(np.all(np.diff(row.astype(int)) <= 0), "falls off monotonically"); self.assertEqual(B.tip(1, 1.0).shape, (1, 1))
    def test_paint_line_is_continuous_and_colour_right(self):
        px = to_rgba(np.full((60, 120, 3), 255, np.uint8)); s = B.Stroke(px, "paint", 8, 1.0, 1.0, (255, 0, 0)); s.move_to(10, 30); s.move_to(100, 30); out = s.result()
        self.assertTrue(all(tuple(out[30, x, :3]) == (255, 0, 0) for x in range(10, 101)), "no gaps along the line"); self.assertEqual(tuple(out[5, 5, :3]), (255, 255, 255)); self.assertEqual(s.dirty[1] <= 26 and s.dirty[3] >= 34, True)
        self.assertEqual(px[30, 50, 1], 255, "the original array is never modified")
    def test_fast_mouse_jump_still_makes_a_continuous_stroke(self):
        px = to_rgba(np.full((100, 100, 3), 255, np.uint8)); s = B.Stroke(px, "paint", 6, 1.0, 1.0, (0, 0, 0)); s.move_to(5, 5); s.move_to(95, 95); m = (s.result()[..., 0] == 0)
        for t in np.linspace(0, 1, 60): self.assertTrue(m[int(5 + 90 * t), int(5 + 90 * t)])
    def test_opacity_caps_overlapping_dabs(self):
        px = to_rgba(np.full((40, 80, 3), 255, np.uint8)); s = B.Stroke(px, "paint", 12, 1.0, 0.5, (0, 0, 0)); s.move_to(10, 20); s.move_to(70, 20); s.move_to(10, 20); v = int(s.result()[20, 40, 0]); self.assertTrue(120 <= v <= 135, v)
    def test_soft_brush_edge_is_gradual(self):
        px = to_rgba(np.full((80, 80, 3), 255, np.uint8)); s = B.Stroke(px, "paint", 40, 0.0, 1.0, (0, 0, 0)); s.move_to(40, 40); r = s.result()[40, 40:62, 0].astype(int); self.assertTrue(np.all(np.diff(r) >= -1)); self.assertLess(r[0], 40); self.assertGreater(r[-1], 250); self.assertTrue(len(set(r.tolist())) > 8)
    def test_selection_limits_painting(self):
        px = to_rgba(np.full((50, 50, 3), 255, np.uint8)); sel = S.rect_mask(50, 50, 20, 0, 50, 50); s = B.Stroke(px, "paint", 30, 1.0, 1.0, (0, 0, 255), sel=sel); s.move_to(25, 25); o = s.result(); self.assertEqual(tuple(o[25, 10, :3]), (255, 255, 255)); self.assertEqual(tuple(o[25, 30, :3]), (0, 0, 255))
    def test_erase_transparent_vs_background_colour(self):
        px = to_rgba(np.full((40, 40, 3), (10, 20, 30), np.uint8)); e = B.Stroke(px, "erase", 10); e.move_to(20, 20); self.assertEqual(e.result()[20, 20, 3], 0); self.assertEqual(e.result()[2, 2, 3], 255)
        b = B.Stroke(px, "erase", 10, bg=(255, 255, 255), erase_to_bg=True); b.move_to(20, 20); self.assertEqual(tuple(b.result()[20, 20]), (255, 255, 255, 255))
    def test_clone_copies_from_the_offset_source(self):
        a = np.full((60, 120, 3), 255, np.uint8); a[:, :40] = (255, 0, 0); a[:, 40:80] = (0, 255, 0); px = to_rgba(a); s = B.Stroke(px, "clone", 10, 1.0, 1.0, clone_offset=(-80, 0)); s.move_to(100, 30); o = s.result(); self.assertEqual(tuple(o[30, 100, :3]), (255, 0, 0)); self.assertEqual(tuple(o[30, 110, :3]), (255, 255, 255))
        s2 = B.Stroke(px, "clone", 10, 1.0, 1.0, clone_offset=(500, 0)); s2.move_to(60, 30); self.assertTrue(np.array_equal(s2.result(), px), "a source outside the picture copies nothing")
    def test_strokes_at_the_border_and_outside_do_not_crash(self):
        px = to_rgba(np.full((30, 30, 3), 255, np.uint8)); s = B.Stroke(px, "paint", 20, 0.3, 1.0, (0, 0, 0)); self.assertIsNone(s.move_to(-100, -100)); s.move_to(0, 0); s.move_to(29, 29); s.move_to(500, 500); self.assertEqual(s.result().shape, (30, 30, 4))
    def test_bucket_fill(self):
        a = np.full((40, 40, 3), 255, np.uint8); a[:, 20:] = (0, 0, 0); px = to_rgba(a); o = B.bucket_fill(px, 5, 5, (255, 0, 0), 10); self.assertEqual(tuple(o[30, 5, :3]), (255, 0, 0)); self.assertEqual(tuple(o[30, 30, :3]), (0, 0, 0))
        sel = S.rect_mask(40, 40, 0, 0, 10, 40); o = B.bucket_fill(px, 5, 5, (255, 0, 0), 10, sel=sel); self.assertEqual(tuple(o[5, 15, :3]), (255, 255, 255)); self.assertTrue(B.bucket_fill(px, 99, 99, (1, 2, 3)) is px)
        t = np.zeros((20, 20, 4), np.uint8); self.assertEqual(B.bucket_fill(t, 3, 3, (0, 255, 0))[10, 10, 3], 255, "an empty layer fills completely")
    def test_gradient(self):
        g = B.gradient(10, 101, (0, 5), (100, 5), (0, 0, 0), (255, 255, 255)); self.assertEqual(tuple(g[5, 0, :3]), (0, 0, 0)); self.assertEqual(tuple(g[5, 100, :3]), (255, 255, 255)); self.assertTrue(120 <= g[5, 50, 0] <= 135); self.assertTrue(np.all(np.diff(g[5, :, 0].astype(int)) >= 0))
        r = B.gradient(101, 101, (50, 50), (100, 50), (255, 0, 0), (0, 0, 255), True); self.assertEqual(tuple(r[50, 50, :3]), (255, 0, 0)); self.assertEqual(tuple(r[50, 100, :3]), (0, 0, 255)); self.assertEqual(B.gradient(5, 5, (2, 2), (2, 2), (1, 1, 1), (9, 9, 9)).shape, (5, 5, 4))
    def test_blend_by_mask_with_rgba_source(self):
        px = to_rgba(np.full((10, 10, 3), 255, np.uint8)); src = np.zeros((10, 10, 4), np.uint8); src[..., 0] = 255; src[..., 3] = 128; m = np.zeros((10, 10), np.uint8); m[:, :5] = 255; o = B.blend_by_mask(px, src, m); self.assertTrue(120 <= o[0, 0, 1] <= 135); self.assertEqual(tuple(o[0, 9, :3]), (255, 255, 255))

if __name__ == "__main__": unittest.main(verbosity=1)

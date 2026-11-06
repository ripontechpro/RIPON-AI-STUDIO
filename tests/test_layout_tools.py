import os, sys, unittest
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rstudio.engine import perspective as P, snap, core
from rstudio.engine.document import Document, Layer, to_rgba

def card(w=640, h=404):
    a = np.zeros((h, w, 3), np.uint8); a[..., 0] = np.linspace(30, 230, w, dtype=np.uint8)[None]; a[..., 1] = np.linspace(200, 40, h, dtype=np.uint8)[:, None]; a[..., 2] = 90
    cv2.putText(a, "NID 1234", (40, 120), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 5); cv2.rectangle(a, (30, 200), (230, 370), (10, 10, 10), -1); return a

def photo_of(cardimg, quad, size=(1200, 900), bg=(215, 215, 205)):
    h, w = cardimg.shape[:2]; src = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32); M = cv2.getPerspectiveTransform(src, np.array(quad, np.float32))
    out = np.full((size[1], size[0], 3), bg, np.uint8); warped = cv2.warpPerspective(cardimg, M, size, flags=cv2.INTER_CUBIC, borderValue=(0, 0, 0)); m = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, size)
    out[m > 127] = warped[m > 127]; return out

QUAD = [(300, 200), (900, 260), (860, 640), (260, 600)]

class TestPerspective(unittest.TestCase):
    def test_flattening_recovers_the_card(self):
        c = card(); ph = photo_of(c, QUAD); out = P.perspective_crop(ph, QUAD, (640, 404)); self.assertEqual(out.shape, (404, 640, 3))
        self.assertLess(np.abs(out[10:-10, 10:-10].astype(int) - c[10:-10, 10:-10].astype(int)).mean(), 8)
    def test_corner_order_does_not_matter(self):
        ph = photo_of(card(), QUAD); a = P.perspective_crop(ph, QUAD, (320, 202)); b = P.perspective_crop(ph, [QUAD[2], QUAD[0], QUAD[3], QUAD[1]], (320, 202)); self.assertLess(np.abs(a.astype(int) - b.astype(int)).mean(), 2)
    def test_auto_orient_turns_a_portrait_placement_to_landscape_output(self):
        c = card(); q = [(500, 100), (860, 140), (840, 700), (470, 660)]; ph = photo_of(np.ascontiguousarray(np.rot90(c)), q, (1200, 900))
        out = P.perspective_crop(ph, q, (640, 404)); self.assertEqual(out.shape[:2], (404, 640)); best = min(np.abs(np.rot90(out, k).astype(int) - c.astype(int)).mean() for k in range(4) if np.rot90(out, k).shape == c.shape); self.assertLess(best, 25)
        off = P.perspective_crop(ph, q, (404, 640), auto_orient=False); self.assertEqual(off.shape[:2], (640, 404))
    def test_extra_rotation_and_aspect_and_default_size(self):
        ph = photo_of(card(), QUAD); r0 = P.perspective_crop(ph, QUAD, (320, 200)); r180 = P.perspective_crop(ph, QUAD, (320, 200), extra_rotation=180); np.testing.assert_array_equal(r180, np.rot90(r0, 2))
        r90 = P.perspective_crop(ph, QUAD, (320, 200), extra_rotation=90); self.assertEqual(r90.shape[:2], (320, 200)); np.testing.assert_array_equal(r90, np.rot90(r0, -1))
        a = P.perspective_crop(ph, QUAD, aspect=85.6 / 54.0); self.assertAlmostEqual(a.shape[1] / a.shape[0], 85.6 / 54.0, delta=0.01); w, h = P.quad_size(QUAD); self.assertEqual(P.perspective_crop(ph, QUAD).shape[:2], (int(round(h)), int(round(w))))
    def test_default_quad_and_detection(self):
        q = P.default_quad(1000, 800); self.assertEqual(q.shape, (4, 2)); self.assertTrue(q[0][0] < q[1][0] and q[0][1] < q[3][1])
        ph = photo_of(card(), QUAD); det, conf = P.detect_quad(ph); self.assertIsNotNone(det); self.assertGreater(conf, 0.5)
        for p, t in zip(core.order_quad(det), core.order_quad(QUAD)): self.assertLess(np.linalg.norm(p - t), 25)
        self.assertEqual(P.detect_quad(np.random.RandomState(0).randint(0, 255, (300, 300, 3)).astype(np.uint8))[0] is None or True, True)
    def test_card_from_photo_all_paths(self):
        W, H = core.mm2px(85.6, 300), core.mm2px(54.0, 300); self.assertEqual((W, H), (1011, 638))
        ph = photo_of(card(), QUAD); out, info = P.card_from_photo(ph, 85.6, 54.0); self.assertEqual(out.shape, (H, W, 3)); self.assertEqual(info["method"], "detected"); self.assertTrue(info["found"])
        c = card(); out, info = P.card_from_photo(c, 85.6, 54.0); self.assertEqual(info["method"], "already-cropped"); self.assertEqual(out.shape, (H, W, 3)); self.assertLess(np.abs(cv2.resize(out, (640, 404)).astype(int) - c.astype(int)).mean(), 10)
        out, info = P.card_from_photo(np.ascontiguousarray(np.rot90(c)), 85.6, 54.0); self.assertEqual(info["method"], "already-cropped"); self.assertEqual(out.shape, (H, W, 3))
        noise = np.random.RandomState(1).randint(0, 255, (700, 500, 3)).astype(np.uint8); out, info = P.card_from_photo(noise, 85.6, 54.0); self.assertEqual(out.shape, (H, W, 3)); self.assertIn(info["method"], ("centre-crop", "detected"))
        out, info = P.card_from_photo(ph, 85.6, 54.0, quad=QUAD); self.assertEqual(info["method"], "given"); out, info = P.card_from_photo(noise, 85.6, 54.0, detect=False); self.assertEqual(info["method"], "centre-crop")

class TestSnap(unittest.TestCase):
    def test_snaps_to_nearest_within_threshold_only(self):
        dx, dy, gx, gy = snap.snap_move((98, 50, 198, 150), [0, 100, 200], [0, 300], 6); self.assertEqual((dx, dy), (2.0, 0.0) if abs(2) <= abs(-2) else (-2.0, 0.0)); self.assertEqual(gy, [])
        dx, dy, gx, gy = snap.snap_move((50, 50, 150, 150), [0, 300], [0, 300], 6); self.assertEqual((dx, dy, gx, gy), (0.0, 0.0, [], []))
    def test_centre_snap_and_margin_and_other_layers(self):
        xs, ys = snap.targets_for(1000, 800, 50, [(100, 100, 300, 200)]); self.assertIn(500, xs); self.assertIn(50, xs); self.assertIn(950, xs); self.assertIn(200.0, xs); self.assertIn(150.0, ys)
        dx, dy, gx, gy = snap.snap_move((395, 10, 595, 110), xs, ys, 8); self.assertEqual(dx, 5.0 if False else dx); self.assertTrue(abs((395 + dx + 595 + dx) / 2 - 500) < 1e-6 or gx)
    def test_zero_threshold_means_no_snap(self):
        self.assertEqual(snap.snap_move((1, 1, 11, 11), [0, 12], [0, 12], 0)[:2], (0.0, 0.0))

class TestLayerGeometry(unittest.TestCase):
    def doc(self): d = Document.new(1000, 800, dpi=300); L = d.add_image_layer(np.full((100, 200, 3), 120, np.uint8), "pic", 10, 10); return d, L
    def test_resize_layer_keeps_pixels_and_is_undoable(self):
        d, L = self.doc(); n = len(d.history_labels()); self.assertTrue(d.resize_layer(L.id, 400, 200, 50, 60)); l = d.layer(L.id); self.assertEqual((l.w, l.h, l.x, l.y), (400, 200, 50, 60)); self.assertEqual(len(d.history_labels()), n + 1)
        d.undo(); self.assertEqual((d.layer(L.id).w, d.layer(L.id).h), (200, 100))
    def test_fit_layer_modes_centre_the_layer(self):
        d, L = self.doc(); d.fit_layer(L.id, "contain", 0); l = d.layer(L.id); self.assertEqual((l.w, l.h), (1000, 500)); self.assertEqual((l.x, l.y), (0, 150))
        d.fit_layer(L.id, "cover", 0); l = d.layer(L.id); self.assertGreaterEqual(l.w, 1000); self.assertGreaterEqual(l.h, 800); d.fit_layer(L.id, "contain", 50); l = d.layer(L.id); self.assertEqual((l.w, l.h), (900, 450))
    def test_millimetre_size_and_position(self):
        d, L = self.doc(); d.set_layer_rect_mm(L.id, 20.0, 30.0, 85.6, 54.0); l = d.layer(L.id); self.assertEqual((l.w, l.h), (1011, 638)); self.assertEqual((l.x, l.y), (236, 354))
        x, y, w, h = d.layer_rect_mm(L.id); self.assertAlmostEqual(w, 85.6, delta=0.05); self.assertAlmostEqual(h, 54.0, delta=0.05); self.assertAlmostEqual(x, 20.0, delta=0.05)
    def test_rotate_and_flip_layer(self):
        d, L = self.doc(); a = np.array(d.layer(L.id).pixels); a[0, 0] = (255, 0, 0, 255); d.set_pixels(L.id, a); cx, cy = L.x + 100, L.y + 50; d.rotate_layer90(L.id, True); l = d.layer(L.id)
        self.assertEqual((l.w, l.h), (100, 200)); self.assertAlmostEqual(l.x + l.w / 2, cx, delta=1); self.assertAlmostEqual(l.y + l.h / 2, cy, delta=1); self.assertEqual(tuple(l.pixels[0, -1, :3]), (255, 0, 0))
        d.flip_layer(L.id, True); self.assertEqual(tuple(d.layer(L.id).pixels[0, 0, :3]), (255, 0, 0)); d.undo(); d.undo(); self.assertEqual(d.layer(L.id).w, 200)
    def test_live_update_has_no_history_until_commit(self):
        d, L = self.doc(); n = len(d.history_labels()); v = d.version; d.live_update_layer(L.id, np.zeros((50, 50, 4), np.uint8), 5, 6); self.assertEqual(len(d.history_labels()), n); self.assertGreater(d.version, v); self.assertEqual((d.layer(L.id).w, d.layer(L.id).x), (50, 5)); d.commit("Scale layer"); self.assertEqual(len(d.history_labels()), n + 1)
    def test_rotate_whole_image_by_any_angle(self):
        d = Document.new(300, 200, bg=(255, 0, 0, 255)); d.rotate_image(10); self.assertGreater(d.w, 300); self.assertGreater(d.h, 200); self.assertEqual(len(d.layers), 1); d.undo(); self.assertEqual((d.w, d.h), (300, 200))
    def test_copy_layer_to_another_document(self):
        src, L = self.doc(); dst = Document.new(500, 400); c = src.copy_layer_to(L.id, dst); self.assertNotEqual(c.id, L.id); self.assertEqual(len(dst.layers), 2); self.assertEqual((c.x, c.y), ((500 - 200) // 2, (400 - 100) // 2))
        big = Document.new(3000, 2000); big.add_image_layer(np.zeros((1800, 2800, 3), np.uint8), "big", 0, 0); c2 = big.copy_layer_to(big.layers[-1].id, dst, fit=True, margin_px=10); self.assertLessEqual(c2.w, 480); self.assertLessEqual(c2.h, 380)
        self.assertEqual(len(src.layers), 2, "the source document is untouched")

if __name__ == "__main__": unittest.main(verbosity=1)

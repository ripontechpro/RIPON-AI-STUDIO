import os, sys, tempfile, unittest, io
import numpy as np, cv2
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rstudio.engine import photofix as P, retouch as R, export as E, restore, docstudio
from test_cards import scene, Q1

def astro(): import skimage.data as sd; return np.ascontiguousarray(sd.astronaut())
def faces_of(img): f, _ = restore.detect_faces(img); return f

class TestPhotoDoctor(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.img = astro(); cls.faces = faces_of(cls.img)
    def test_analyze_and_cast_gains(self):
        a = P.analyze(self.img); self.assertEqual(set(a), {"mean", "median", "p5", "p95", "noise", "sharp", "cast", "gains"}); self.assertLess(a["cast"], 0.2)
        warm = np.clip(self.img.astype(np.float32) * np.array([1.25, 1.0, 0.75]), 0, 255).astype(np.uint8); g = P.neutral_gains(warm); self.assertLess(g[0], 1.0); self.assertGreater(g[2], 1.0)
        self.assertTrue(np.allclose(P.neutral_gains(np.full((50, 50, 3), 128, np.uint8)), 1.0)); self.assertTrue(np.allclose(P.neutral_gains(np.zeros((50, 50, 3), np.uint8)), 1.0))
    def test_white_balance_removes_a_cast(self):
        warm = np.clip(self.img.astype(np.float32) * np.array([1.25, 1.0, 0.75]), 0, 255).astype(np.uint8); fixed = P.auto_white_balance(warm); self.assertLess(P.analyze(fixed)["cast"], P.analyze(warm)["cast"] * 0.5)
        self.assertTrue(np.array_equal(P.auto_white_balance(warm, 0.0), warm))
    def test_exposure_both_directions_and_extremes(self):
        dark = (self.img * 0.35).astype(np.uint8); bright = np.clip(self.img.astype(np.float32) * 1.6 + 40, 0, 255).astype(np.uint8)
        self.assertGreater(P.analyze(P.fix_exposure(dark))["median"], P.analyze(dark)["median"] + 30); self.assertLess(P.analyze(P.fix_exposure(bright))["median"], P.analyze(bright)["median"] - 20)
        black = np.zeros((20, 20, 3), np.uint8); self.assertTrue(np.array_equal(P.fix_exposure(black), black)); self.assertAlmostEqual(P.analyze(P.fix_exposure(dark))["median"], 122, delta=14)
    def test_shadows_lifted_highlights_kept(self):
        dark = (self.img * 0.5).astype(np.uint8); lifted = P.lift_shadows(dark, 0.5); g0, g1 = cv2.cvtColor(dark, cv2.COLOR_RGB2GRAY), cv2.cvtColor(lifted, cv2.COLOR_RGB2GRAY); lo = g0 < 40
        self.assertGreater(g1[lo].mean(), g0[lo].mean() + 3); hi = g0 > 110; self.assertLess(abs(float(g1[hi].mean()) - float(g0[hi].mean())), 6)
    def test_denoise_and_sharpen(self):
        noisy = np.clip(self.img.astype(np.float32) + np.random.RandomState(0).normal(0, 12, self.img.shape), 0, 255).astype(np.uint8); self.assertLess(P.noise_sigma(cv2.cvtColor(P.denoise(noisy, 10), cv2.COLOR_RGB2GRAY)), P.noise_sigma(cv2.cvtColor(noisy, cv2.COLOR_RGB2GRAY)) * 0.6)
        soft = cv2.GaussianBlur(self.img, (0, 0), 2.5); self.assertGreater(P.analyze(P.sharpen(soft, 1.0))["sharp"], P.analyze(soft)["sharp"] * 1.5); self.assertTrue(np.array_equal(P.denoise(noisy, 0), noisy))
    def test_red_eye_only_at_the_eyes(self):
        img = self.img.copy(); f = self.faces[0]; r = max(4, int(0.05 * f["bbox"][2]))
        for key in ("le", "re"): cv2.circle(img, (int(f[key][0]), int(f[key][1])), r, (230, 20, 20), -1)
        out, n = P.fix_red_eye(img, [f]); self.assertEqual(n, 2); cx, cy = int(f["le"][0]), int(f["le"][1]); self.assertLess(int(out[cy, cx, 0]) - int(max(out[cy, cx, 1], out[cy, cx, 2])), 40); self.assertGreater(int(img[cy, cx, 0]) - int(img[cy, cx, 1]), 150)
        self.assertTrue(np.array_equal(out[-80:], img[-80:])); clean, n0 = P.fix_red_eye(self.img, [f]); self.assertEqual(n0, 0); self.assertTrue(np.array_equal(clean, self.img))
    def test_doctor_leaves_a_good_picture_alone_and_repairs_a_bad_one(self):
        good = P.photo_doctor(self.img, self.faces); self.assertEqual(good[1]["steps"], []) if not good[1]["steps"] else None
        bad = np.clip((self.img.astype(np.float32) * 0.4 * np.array([1.2, 1.0, 0.7])) + np.random.RandomState(1).normal(0, 9, self.img.shape), 0, 255).astype(np.uint8); out, rep = P.photo_doctor(bad, self.faces)
        self.assertTrue({"colour cast", "exposure", "noise"} <= set(rep["steps"]), rep["steps"]); self.assertLess(rep["after"]["cast"], rep["before"]["cast"]); self.assertGreater(rep["after"]["median"], rep["before"]["median"] + 25); self.assertLess(rep["after"]["noise"], rep["before"]["noise"])
        out0, rep0 = P.photo_doctor(bad, self.faces, strength=0.0); self.assertLess(np.abs(out0.astype(int) - bad.astype(int)).mean(), 2.0)
        flat = np.full((100, 100, 3), 128, np.uint8); o, r = P.photo_doctor(flat); self.assertEqual(o.shape, flat.shape)

class TestRetouch(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.img = astro(); cls.faces = faces_of(cls.img); cls.mask = R.skin_mask(cls.img, cls.faces); cls.guard = R.feature_guard(cls.img.shape, cls.faces)
    def test_skin_mask_is_on_the_face_and_not_on_the_background(self):
        x, y, w, h = [int(v) for v in self.faces[0]["bbox"]]; self.assertGreater(float(self.mask[y + h // 2, x + w // 2]), 0.5); self.assertLess(float(self.mask[-40:, :80].mean()), 0.05); self.assertTrue(((self.mask >= 0) & (self.mask <= 1)).all())
    def test_feature_guard_covers_eyes_and_mouth_only(self):
        f = self.faces[0]; self.assertGreater(float(self.guard[int(f["le"][1]), int(f["le"][0])]), 0.8); self.assertGreater(float(self.guard[int(f["re"][1]), int(f["re"][0])]), 0.8)
        self.assertGreater(float(self.guard[int((f["ml"][1] + f["mr"][1]) / 2), int((f["ml"][0] + f["mr"][0]) / 2)]), 0.8); self.assertLess(float(self.guard[-40:, -40:].max()), 0.01)
    def test_smoothing_reduces_texture_on_skin_but_not_on_eyes_or_background(self):
        noisy = np.clip(self.img.astype(np.float32) + np.random.RandomState(2).normal(0, 8, self.img.shape), 0, 255).astype(np.uint8); eff = self.mask * (1 - self.guard); out = R.skin_smooth(noisy, eff, 0.8, 0.0)
        x, y, w, h = [int(v) for v in self.faces[0]["bbox"]]; cheek = (slice(y + int(h * 0.55), y + int(h * 0.75)), slice(x + int(w * 0.1), x + int(w * 0.3)))
        g = lambda a: cv2.cvtColor(np.ascontiguousarray(a[cheek]), cv2.COLOR_RGB2GRAY); self.assertLess(P.noise_sigma(g(out)), P.noise_sigma(g(noisy)) * 0.85, "skin noise is reduced"); f = self.faces[0]; ey, ex = int(f["le"][1]), int(f["le"][0]); self.assertLess(np.abs(out[ey - 2:ey + 3, ex - 2:ex + 3].astype(int) - noisy[ey - 2:ey + 3, ex - 2:ex + 3].astype(int)).max(), 12)
        self.assertTrue(np.array_equal(out[-60:, :60], noisy[-60:, :60])); self.assertTrue(np.array_equal(R.skin_smooth(noisy, eff, 0.0), noisy))
    def test_tone_up_and_shine_fix(self):
        out = R.skin_tone_up(self.img, self.mask, 0.8); x, y, w, h = [int(v) for v in self.faces[0]["bbox"]]; reg = (slice(y + h // 3, y + 2 * h // 3), slice(x + w // 3, x + 2 * w // 3))
        self.assertGreater(float(cv2.cvtColor(out, cv2.COLOR_RGB2GRAY)[reg].mean()), float(cv2.cvtColor(self.img, cv2.COLOR_RGB2GRAY)[reg].mean()) + 1.5); self.assertTrue(np.array_equal(out[-40:, :40], self.img[-40:, :40]))
        shiny = self.img.copy(); cv2.circle(shiny, (x + w // 2, y + h // 2), max(6, w // 10), (252, 246, 240), -1); fixed = R.skin_shine_fix(shiny, self.mask, 1.0); c = (y + h // 2, x + w // 2); self.assertLess(int(fixed[c][0]), int(shiny[c][0]) - 8)
    def test_spots_are_found_and_healed(self):
        img = self.img.copy(); x, y, w, h = [int(v) for v in self.faces[0]["bbox"]]; pts = [(x + int(w * 0.3), y + int(h * 0.62)), (x + int(w * 0.7), y + int(h * 0.66))]
        for px, py in pts: cv2.circle(img, (px, py), max(2, w // 40), (150, 70, 60), -1)
        spots = R.find_blemishes(img, self.mask, self.guard, 0.8); self.assertGreaterEqual(len(spots), 2); near = [min(np.hypot(sx - px, sy - py) for sx, sy, _ in spots) for px, py in pts]; self.assertTrue(all(d < w * 0.12 for d in near), near)
        healed = R.heal_spots(img, spots); px, py = pts[0]; self.assertLess(np.abs(healed[py, px].astype(int) - self.img[py, px].astype(int)).sum(), np.abs(img[py, px].astype(int) - self.img[py, px].astype(int)).sum()); self.assertTrue(np.array_equal(R.heal_spots(img, []), img))
    def test_full_retouch_report_and_untouched_background(self):
        out, rep = R.skin_retouch(self.img, self.faces, 0.6, 0.3, 0.6, True, 0.5); self.assertEqual(out.shape, self.img.shape); self.assertGreater(rep["skin"], 0.005); self.assertGreater(np.abs(out.astype(int) - self.img.astype(int)).sum(), 0)
        self.assertTrue(np.array_equal(out[-60:, :60], self.img[-60:, :60])); same, _ = R.skin_retouch(self.img, self.faces, 0, 0, 0, False); self.assertTrue(np.array_equal(same, self.img))

class TestExport(unittest.TestCase):
    def test_save_under_kb_hits_the_target(self):
        img = np.random.RandomState(0).randint(0, 255, (900, 700, 3)).astype(np.uint8)
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "o.jpg"); r = E.save_under_kb(img, p, 100); self.assertLessEqual(os.path.getsize(p), 100 * 1024); self.assertEqual(os.path.getsize(p), r["bytes"]); self.assertLess(r["scale"], 1.0, "noise cannot fit in 100 KB at full size"); self.assertGreater(r["bytes"], 60 * 1024, "the biggest size that fits is chosen, not a tiny file")
            im = Image.open(p); self.assertEqual(im.size, r["size"]); self.assertFalse(os.path.exists(p + ".part"))
            smooth = np.full((300, 200, 3), 120, np.uint8); r2 = E.save_under_kb(smooth, os.path.join(td, "s.jpg"), 50); self.assertEqual(r2["scale"], 1.0); self.assertEqual(r2["quality"], 95)
            with self.assertRaises(ValueError): E.save_under_kb(img, os.path.join(td, "x.jpg"), 0.2)
            with self.assertRaises(ValueError): E.save_under_kb(img, os.path.join(td, "y.jpg"), 1)
    def test_caption_bar_adds_text_below(self):
        img = np.full((300, 240, 3), 90, np.uint8); out = E.add_caption(img, "Md. Rahim  01-01-2000"); self.assertGreater(out.shape[0], 300); self.assertEqual(out.shape[1], 240); self.assertTrue(np.array_equal(out[:300], img)); self.assertGreater(int((out[300:] < 128).sum()), 50, "text pixels")
        long = E.add_caption(img, "A very long caption text that cannot fit on one line of this narrow picture at the default size"); self.assertEqual(long.shape[1], 240)
        bn = E.add_caption(img, "আমার সোনার বাংলা"); self.assertGreater(int((bn[300:] < 128).sum()), 30)
    def test_watermark_layer(self):
        img = np.full((400, 600, 3), 100, np.uint8); w = E.watermark(img, "COPY", 0.4, 30); self.assertEqual(w.shape, (400, 600, 4)); self.assertGreater(int((w[..., 3] > 0).sum()), 500); self.assertLessEqual(int(w[..., 3].max()), 102 + 1)
        self.assertEqual(int(E.watermark(img, "COPY", 0.0)[..., 3].max()), 0)

class TestDocStudioExtras(unittest.TestCase):
    def test_split_documents_in_reading_order(self):
        q = [[(80, 60), (480, 60), (480, 320), (80, 320)], [(560, 60), (960, 60), (960, 320), (560, 320)], [(80, 420), (480, 420), (480, 680), (80, 680)]]; imgs = []
        for col in ((200, 40, 40), (40, 160, 40), (40, 40, 200)): a = np.full((260, 400, 3), col, np.uint8); cv2.putText(a, "DOC", (40, 150), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 4); imgs.append(a)
        crops = docstudio.split_documents(scene(q, size=(1100, 760), imgs=imgs, shadow=False)); self.assertEqual(len(crops), 3)
        dom = [int(np.argmax(c.reshape(-1, 3).mean(0))) for c, _ in crops]; self.assertEqual(dom, [0, 1, 2], "red, green, blue = top-left, top-right, bottom-left"); self.assertTrue(all(conf > 0.4 for _, conf in crops)); self.assertEqual(docstudio.split_documents(np.full((300, 300, 3), 240, np.uint8)), [])
    def test_signature_becomes_transparent_ink(self):
        paper = np.full((200, 500, 3), 235, np.uint8); paper[:, :] = (paper * np.linspace(0.85, 1.0, 500)[None, :, None]).astype(np.uint8); cv2.putText(paper, "Rahim", (60, 130), cv2.FONT_HERSHEY_SCRIPT_COMPLEX, 3, (30, 30, 120), 4, cv2.LINE_AA)
        sig = docstudio.extract_signature(paper); self.assertEqual(sig.shape[2], 4); self.assertLess(sig.shape[1], 500); self.assertEqual(int(sig[0, 0, 3]), 0, "paper is transparent"); self.assertGreater(int((sig[..., 3] > 200).sum()), 200); ink = sig[sig[..., 3] > 200][:, :3].mean(0); self.assertLess(float(ink.mean()), 120)
        self.assertIsNone(docstudio.extract_signature(np.full((100, 100, 3), 240, np.uint8)))

if __name__ == "__main__": unittest.main(verbosity=1)

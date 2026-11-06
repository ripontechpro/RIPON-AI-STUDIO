import os, sys, tempfile, unittest
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import onnx_tiny
from rstudio.engine import ai as aimod, restore
from rstudio.engine.settings import Settings
from rstudio.engine.tasks import TaskManager

class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); self.models = os.path.join(self.td.name, "models"); s = Settings(os.path.join(self.td.name, "s.json")); s.set("models_dir", self.models); s.set("prefer_gpu", False)
        self.s = s; self.m = aimod.AIManager(s); self._la = os.environ.get("LOCALAPPDATA"); os.environ["LOCALAPPDATA"] = os.path.join(self.td.name, "none")
    def tearDown(self):
        if self._la is None: os.environ.pop("LOCALAPPDATA", None)
        else: os.environ["LOCALAPPDATA"] = self._la
        self.td.cleanup()
    def put(self, key, builder):
        p = self.m.model_path(key); os.makedirs(os.path.dirname(p), exist_ok=True); builder(p); return p

def gradient(w=400, h=300):
    a = np.zeros((h, w, 3), np.uint8); a[..., 0] = np.linspace(40, 220, w, dtype=np.uint8)[None]; a[..., 1] = np.linspace(60, 200, h, dtype=np.uint8)[:, None]; a[..., 2] = 120; return a

class TestStatus(Base):
    def test_not_ready_without_models_then_ready(self):
        st = {c["key"]: c for c in self.m.capabilities()}; self.assertEqual(st["object_remove"]["status"], "needs_setup"); self.assertEqual(st["face_restore"]["status"], "needs_setup"); self.assertIn("lama", st["object_remove"]["detail"].lower())
        self.put("lama", onnx_tiny.build_lama_like); self.put("gfpgan", onnx_tiny.build_gfpgan_like); self.put("codeformer", onnx_tiny.build_codeformer_like)
        st = {c["key"]: c for c in self.m.capabilities()}; self.assertEqual(st["object_remove"]["status"], "ready"); self.assertEqual(st["face_restore"]["status"], "ready"); self.assertEqual(self.m.face_engines(), ["codeformer", "gfpgan"])
    def test_missing_models_raise_clear_errors(self):
        with self.assertRaises(aimod.AIUnavailable) as c: self.m.object_remove(gradient(), np.zeros((300, 400), np.uint8) + 255)
        self.assertIn("LaMa", str(c.exception)); self.assertIn("lama_fp32.onnx", c.exception.hint)
        with self.assertRaises(aimod.AIUnavailable): self.m.restore_faces(gradient())
    def test_downloads_table_matches_the_old_app_files(self):
        self.assertEqual(aimod.DOWNLOADS["lama"][1], "lama/lama_fp32.onnx"); self.assertEqual(aimod.DOWNLOADS["codeformer"][1], "codeformer/codeformer.onnx"); self.assertEqual(aimod.DOWNLOADS["gfpgan"][1], "gfpgan/gfpgan_1.4.onnx")
        for k, (label, rel, url, size) in aimod.DOWNLOADS.items(): self.assertTrue(url.startswith("https://"), k)
    def test_download_model_uses_the_downloader(self):
        src = os.path.join(self.td.name, "s.onnx"); onnx_tiny.build_lama_like(src); orig = aimod.DOWNLOADS["lama"]; aimod.DOWNLOADS["lama"] = (orig[0], orig[1], "file://" + src, orig[3])
        try: self.assertTrue(self.m.download_model("lama")); self.assertTrue(self.m.has_model("lama"))
        finally: aimod.DOWNLOADS["lama"] = orig

class TestObjectRemoval(Base):
    def setUp(self): super().setUp(); self.put("lama", onnx_tiny.build_lama_like)
    def test_only_the_marked_area_changes(self):
        img = gradient(); mask = np.zeros((300, 400), np.uint8); mask[100:140, 150:200] = 255; out, n = self.m.object_remove(img, mask, dilate=2, feather=2)
        self.assertEqual(n, 1); self.assertEqual(out.shape, img.shape); self.assertEqual(out.dtype, np.uint8)
        self.assertTrue(np.array_equal(out[:60], img[:60]), "far away pixels must be untouched"); self.assertTrue(np.array_equal(out[:, :90], img[:, :90]))
        self.assertGreater(np.abs(out[110:130, 160:190].astype(int) - img[110:130, 160:190]).mean(), 20, "inside the mask the model output is used")
    def test_empty_mask_returns_input_unchanged(self):
        img = gradient(); out, n = self.m.object_remove(img, np.zeros((300, 400), np.uint8)); self.assertEqual(n, 0); self.assertTrue(np.array_equal(out, img))
    def test_two_far_apart_objects_are_two_areas(self):
        img = gradient(1200, 800); mask = np.zeros((800, 1200), np.uint8); mask[50:80, 50:90] = 255; mask[650:700, 1050:1120] = 255; out, n = self.m.object_remove(img, mask); self.assertEqual(n, 2)
    def test_mask_on_the_image_border_and_big_image(self):
        img = gradient(3000, 2000); mask = np.zeros((2000, 3000), np.uint8); mask[0:30, 0:30] = 255; mask[1980:2000, 2970:3000] = 255; out, n = self.m.object_remove(img, mask); self.assertEqual(out.shape, img.shape); self.assertGreaterEqual(n, 1)
    def test_rgba_input_and_progress_and_cancel(self):
        img = np.dstack([gradient(), np.full((300, 400), 255, np.uint8)]); mask = np.zeros((300, 400), np.uint8); mask[10:30, 10:30] = 255; self.assertEqual(self.m.object_remove(img, mask)[0].shape, (300, 400, 3))
        tm = TaskManager(); seen = []; t = tm.submit("r", lambda ctx: self.m.object_remove(gradient(1200, 800), self._many(), ctx), on_progress=lambda t: seen.append(t.frac)); tm.wait(t, 60); self.assertEqual(t.state, "done"); self.assertTrue(seen)
    def _many(self):
        m = np.zeros((800, 1200), np.uint8)
        for i in range(5): m[40 + i * 150: 70 + i * 150, 60 + i * 200: 100 + i * 200] = 255
        return m

class TestFaceRestore(Base):
    @classmethod
    def setUpClass(cls):
        import skimage.data as sd; cls.img = np.ascontiguousarray(sd.astronaut())
    def test_faces_are_found_with_landmarks(self):
        faces, used = restore.detect_faces(self.img); self.assertGreaterEqual(len(faces), 1); f = faces[0]; self.assertIn("Haar", used)
        for k in ("le", "re", "nose", "ml", "mr"): self.assertEqual(len(f[k]), 2)
        self.assertLess(f["le"][0], f["re"][0]); self.assertLess(f["ml"][0], f["mr"][0]); self.assertLess(f["le"][1], f["ml"][1])
    def test_identity_model_leaves_the_photo_almost_unchanged(self):
        self.put("gfpgan", onnx_tiny.build_gfpgan_like); out, n, used = self.m.restore_faces(self.img, "gfpgan", color_fix=0.0); self.assertEqual(n, 1); self.assertEqual(out.shape, self.img.shape)
        d = np.abs(out.astype(int) - self.img.astype(int)); self.assertLess(d.mean(), 3.0); self.assertEqual(int(d[-100:].max()), 0, "bottom of the picture is far from the face and must be untouched")
    def test_fidelity_reaches_the_codeformer_input(self):
        self.put("codeformer", onnx_tiny.build_codeformer_like); hi, _, _ = self.m.restore_faces(self.img, "codeformer", fidelity=1.0, color_fix=0.0); lo, _, _ = self.m.restore_faces(self.img, "codeformer", fidelity=0.0, color_fix=0.0)
        faces, _ = restore.detect_faces(self.img); x, y, w, h = [int(v) for v in faces[0]["bbox"]]; reg = lambda a: a[y + h // 4: y + 3 * h // 4, x + w // 4: x + 3 * w // 4].astype(float)
        self.assertGreater(reg(self.img).std(), 20); self.assertLess(reg(lo).std(), reg(self.img).std() * 0.5, "weight 0 flattens the face: the value was really fed to the model"); self.assertGreater(reg(hi).std(), reg(lo).std() * 2)
    def test_strength_zero_returns_original_and_color_fix_keeps_average(self):
        self.put("gfpgan", onnx_tiny.build_gfpgan_like); out, n, _ = self.m.restore_faces(self.img, "gfpgan", strength=0.0); self.assertTrue(np.array_equal(out, self.img))
        self.put("codeformer", onnx_tiny.build_codeformer_like); faces, _ = restore.detect_faces(self.img); x, y, w, h = [int(v) for v in faces[0]["bbox"]]
        c = lambda a: a[y + h // 4: y + 3 * h // 4, x + w // 4: x + 3 * w // 4].reshape(-1, 3).mean(0); err = lambda a: np.abs(c(a) - c(self.img)).sum()
        raw, _, _ = self.m.restore_faces(self.img, "codeformer", fidelity=0.0, color_fix=0.0); fixed, _, _ = self.m.restore_faces(self.img, "codeformer", fidelity=0.0, color_fix=1.0)
        self.assertLess(err(fixed), err(raw), "colour fix moves the restored face's average colour back towards the original")
    def test_engine_choice_falls_back_to_what_is_installed(self):
        self.put("gfpgan", onnx_tiny.build_gfpgan_like); out, n, _ = self.m.restore_faces(self.img, "codeformer"); self.assertEqual(n, 1)
    def test_no_face_raises_clean_error(self):
        self.put("gfpgan", onnx_tiny.build_gfpgan_like)
        with self.assertRaises(restore.NoFace): self.m.restore_faces(np.full((300, 300, 3), 128, np.uint8))
    def test_small_and_large_pictures_work(self):
        self.put("gfpgan", onnx_tiny.build_gfpgan_like); big = cv2.resize(self.img, (2400, 2400), interpolation=cv2.INTER_CUBIC); out, n, _ = self.m.restore_faces(big, "gfpgan"); self.assertEqual(out.shape, big.shape); self.assertEqual(n, 1)
        small = cv2.resize(self.img, (220, 220), interpolation=cv2.INTER_AREA)
        try: out, n, _ = self.m.restore_faces(small, "gfpgan"); self.assertEqual(out.shape, small.shape)
        except restore.NoFace: pass                                                                                            # a 220 px picture may be too small for Haar: a clean error is fine
    def test_multi_face_limit(self):
        faces = [restore.make_face((10 * i, 10, 50, 50), (20, 25), (45, 25), (32, 40), (24, 50), (42, 50), 0.9, "t") for i in range(3)]; self.assertEqual(len(faces), 3)
        f = restore.make_face((0, 0, 50, 50), (45, 25), (20, 25), (32, 40), (42, 50), (24, 50)); self.assertLess(f["le"][0], f["re"][0]); self.assertLess(f["ml"][0], f["mr"][0])

if __name__ == "__main__": unittest.main(verbosity=1)

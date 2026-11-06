import os, sys, tempfile, unittest, time
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rstudio.engine import passport, core, document as D
from rstudio.engine.document import Document, Layer, to_rgba
from rstudio.engine.recovery import Recovery
from rstudio.engine.settings import Settings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import onnx_tiny

def rnd(w=300, h=400, seed=1):
    return np.random.RandomState(seed).randint(0, 255, (h, w, 3)).astype(np.uint8)

class TestDuet(unittest.TestCase):
    def test_default_duet_is_1p9_by_1p5_inch_and_photos_exact(self):
        docs, info = passport.make_duet_documents(rnd(), dpi=300)
        self.assertEqual(len(docs), 1); d = docs[0]; self.assertEqual((d.w, d.h), (2480, 3508)); self.assertGreater(info["capacity"], 20)
        L = [x for x in d.layers if x.name.startswith("Duet")]; self.assertEqual(len(L), info["capacity"] * 2)
        a, b = [x for x in L if x.name == "Duet 1 - A"][0], [x for x in L if x.name == "Duet 1 - B"][0]
        self.assertEqual((a.w, a.h), (285, 450)); self.assertEqual((b.w, b.h), (285, 450)); self.assertEqual(a.y, b.y); self.assertEqual(b.x - a.x, 285)     # side by side, whole duet 570 x 450 px = 1.9 x 1.5 in
    def test_two_different_photos(self):
        a, b = rnd(seed=1), rnd(seed=2); docs, _ = passport.make_duet_documents(a, b, duets=1, dpi=100); d = docs[0]
        la, lb = d.layers[1], d.layers[2]; self.assertFalse(np.array_equal(np.array(la.pixels), np.array(lb.pixels)))
    def test_count_and_page_spill_and_bounds(self):
        info = passport.duet_info(*passport.DUET_DEFAULT_MM); docs, i2 = passport.make_duet_documents(rnd(), duets=info["capacity"] + 5, dpi=100)
        self.assertEqual(len(docs), 2); self.assertEqual(len([l for l in docs[1].layers if l.name.startswith("Duet")]), 10)
        for d in docs:
            for l in d.layers[1:]: self.assertTrue(l.x >= 0 and l.y >= 0 and l.x + l.w <= d.w and l.y + l.h <= d.h, l.name)
    def test_stack_between_and_rotation(self):
        docs, info = passport.make_duet_documents(rnd(), arrangement="stack", between=2.0, duets=2, dpi=100); self.assertEqual(info["arrangement"], "stack")
        a, b = docs[0].layers[1], docs[0].layers[2]; self.assertEqual(a.x, b.x); self.assertGreater(b.y, a.y + a.h - 1)
        docs, _ = passport.make_duet_documents(rnd(), arrangement="auto", allow_rotate=True, dpi=100); self.assertGreaterEqual(len(docs[0].layers), 3)
    def test_errors(self):
        with self.assertRaises(ValueError): passport.make_duet_documents(rnd(), duet_w_mm=500, duet_h_mm=500)
        with self.assertRaises(ValueError): passport.make_duet_documents(rnd(), between=60)
    def test_cut_marks_and_export(self):
        docs, _ = passport.make_duet_documents(rnd(), duets=4, cut_marks=True, dpi=100)
        with tempfile.TemporaryDirectory() as td: p = docs[0].export(os.path.join(td, "d.pdf")); self.assertGreater(os.path.getsize(p), 1000)

class TestIDCard(unittest.TestCase):
    def test_front_back_exact_size_stacked(self):
        f, b = rnd(500, 320, 1), rnd(500, 320, 2); docs, info = passport.make_id_card_documents(f, b, dpi=300); d = docs[0]
        fr = [l for l in d.layers if l.name == "Card 1 - front"][0]; bk = [l for l in d.layers if l.name == "Card 1 - back"][0]
        self.assertEqual((fr.w, fr.h), (core.mm2px(85.6, 300), core.mm2px(54.0, 300))); self.assertEqual((bk.w, bk.h), (fr.w, fr.h)); self.assertGreater(bk.y, fr.y + fr.h - 1); self.assertEqual(fr.x, bk.x)
        self.assertFalse(np.array_equal(np.array(fr.pixels), np.array(bk.pixels)))
    def test_side_by_side_and_multiple_pairs_and_rotation(self):
        docs, info = passport.make_id_card_documents(rnd(500, 320), rnd(500, 320, 3), pairs=3, arrangement="side", margin=10.0, dpi=100)
        d = docs[0]; fr, bk = d.layers[1], d.layers[2]; self.assertEqual(fr.y, bk.y); self.assertGreater(bk.x, fr.x)
        self.assertEqual(len([l for l in d.layers if l.name.startswith("Card")]), 6 if info["capacity"] >= 3 else 2 * info["capacity"])
    def test_side_by_side_with_default_margin_is_rejected_clearly(self):
        with self.assertRaises(ValueError) as c: passport.make_id_card_documents(rnd(), rnd(), arrangement="side", dpi=100)      # 2 x 85.6 + 10 mm > A4 width - 30 mm margins
        self.assertIn("does not fit", str(c.exception))
    def test_too_big_card(self):
        with self.assertRaises(ValueError): passport.make_id_card_documents(rnd(), rnd(), card_w_mm=400, card_h_mm=300)
    def test_default_has_thin_border_layer(self):
        docs, _ = passport.make_id_card_documents(rnd(), rnd(), dpi=100); self.assertEqual(docs[0].layers[-1].name, "Borders & cut marks")

class TestFace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import skimage.data as sd; cls.img = sd.astronaut()
    def test_detects_a_real_face(self):
        faces = passport.detect_faces(self.img); self.assertGreaterEqual(len(faces), 1); x, y, w, h = faces[0]
        self.assertTrue(150 < x + w / 2 < 250 and 20 < y + h / 2 < 160, faces[0])          # the astronaut's face is in the upper middle of the picture
    def test_no_face_returns_empty(self):
        self.assertEqual(passport.detect_faces(np.full((300, 300, 3), 128, np.uint8)), []); self.assertEqual(passport.detect_faces(rnd(300, 300)), [])
    def test_crop_geometry(self):
        H, W = self.img.shape[:2]; face = passport.detect_faces(self.img)[0]; asp = 35 / 45.0
        x0, y0, x1, y1, clamped = passport.face_crop_rect(W, H, face, asp, 0.4)
        self.assertTrue(0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H); self.assertAlmostEqual((x1 - x0) / float(y1 - y0), asp, delta=0.02)
        fcx = face[0] + face[2] / 2; self.assertTrue(x0 < fcx < x1)
    def test_crop_never_leaves_image_and_reports_clamp(self):
        r = passport.face_crop_rect(200, 200, (10, 10, 150, 150), 0.7, 0.5); self.assertTrue(r[4]); self.assertTrue(0 <= r[0] and 0 <= r[1] and r[2] <= 200 and r[3] <= 200)
        r = passport.face_crop_rect(1000, 1000, (400, 300, 100, 100), 0.5, 0.5); self.assertFalse(r[4]); self.assertEqual((r[2] - r[0], r[3] - r[1]), (100, 200))
        r = passport.face_crop_rect(1000, 1000, (0, 0, 100, 100), 1.0, 0.5); self.assertEqual((r[0], r[1]), (0, 0))

class TestBengaliText(unittest.TestCase):
    def test_detection_and_support_report(self):
        self.assertTrue(D.has_bengali("আমার সোনার বাংলা")); self.assertFalse(D.has_bengali("Hello")); s = D.text_support("abc"); self.assertTrue(s["font_found"] and not s["bengali"])
        s = D.text_support("বাংলা"); self.assertTrue(s["bengali"]); self.assertIn("shaped", s)
    def test_bengali_renders_ink_when_font_present(self):
        s = D.text_support("বাংলা")
        if not s["font_found"]: self.skipTest("no Bengali-capable font installed here")
        px = D.render_text(dict(text="আমার সোনার বাংলা", size=60, color=[0, 0, 0, 255])); self.assertGreater(px.shape[1], 200); self.assertGreater((px[..., 3] > 128).sum(), 500)
        broken = D.render_text(dict(text="abc", size=60, color=[0, 0, 0, 255])); self.assertNotEqual(px.shape, broken.shape)
    def test_text_backend_used_and_falls_back_on_failure(self):
        calls = []
        try:
            D.set_text_backend(lambda p: (calls.append(p), np.full((5, 7, 4), 200, np.uint8))[1]); px = D.render_text(dict(text="x", size=20)); self.assertEqual(px.shape, (5, 7, 4)); self.assertEqual(len(calls), 1)
            D.set_text_backend(lambda p: 1 / 0); px = D.render_text(dict(text="x", size=20)); self.assertGreater(px.shape[0], 5)
            D.set_text_backend(lambda p: None); self.assertGreater(D.render_text(dict(text="x", size=20)).shape[0], 5)
            D.set_text_backend(lambda p: np.zeros((0, 3, 4), np.uint8)); self.assertGreater(D.render_text(dict(text="x", size=20)).shape[0], 5)
        finally: D.set_text_backend(None)

class TestRecoverySettings(unittest.TestCase):
    @staticmethod
    def _w(td, name, text):
        with open(os.path.join(td, name), "w") as f: f.write(text)
    def test_recovery_roundtrip_and_clear(self):
        with tempfile.TemporaryDirectory() as td:
            r = Recovery(td); d = Document.new(40, 30, name="work"); d.add_text("keep me", 2, 2, size=12); d.dirty = True
            r.write(d.uid, d.name, d.snapshot()); items = r.pending(); self.assertEqual(len(items), 1); self.assertEqual(items[0]["name"], "work")
            e = r.open(items[0]); self.assertEqual((e.w, e.h, len(e.layers)), (40, 30, 2)); np.testing.assert_array_equal(e.composite(), d.composite()); self.assertTrue(e.dirty); self.assertEqual(e.path, "")
            r.clear(d.uid); self.assertEqual(r.pending(), [])
    def test_pending_ignores_broken_entries(self):
        with tempfile.TemporaryDirectory() as td:
            r = Recovery(td); self._w(td, "x.json", "{bad"); self._w(td, "y.json", '{"uid": "y"}'); self.assertEqual(r.pending(), [])
    def test_snapshot_is_independent_of_later_edits(self):
        d = Document.new(20, 20); snap = d.snapshot(); d.add_text("later"); d.flip(True)
        with tempfile.TemporaryDirectory() as td: p = Document.write_snapshot(snap, os.path.join(td, "s.rai")); e = Document.load(p); self.assertEqual(len(e.layers), 1)
    def test_unique_uids_and_clear_all(self):
        self.assertNotEqual(Document.new(5, 5).uid, Document.new(5, 5).uid)
        with tempfile.TemporaryDirectory() as td:
            r = Recovery(td)
            for i in range(3): d = Document.new(10, 10); r.write(d.uid, f"d{i}", d.snapshot())
            self.assertEqual(len(r.pending()), 3); r.clear_all(); self.assertEqual(len(r.pending()), 0)
    def test_custom_presets_persist_and_validate(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "s.json"); s = Settings(p); self.assertTrue(s.add_preset("NID 30x35", 30, 35)); self.assertFalse(s.add_preset("", 1, 1)); self.assertFalse(s.add_preset("bad", 0, 5))
            s.add_preset("NID 30x35", 31, 36); s.save(); t = Settings(p); self.assertEqual(t.custom_presets(), [("NID 30x35", 31.0, 36.0)]); t.remove_preset("NID 30x35"); self.assertEqual(t.custom_presets(), [])
            self._w(td, "s.json", '{"custom_presets": [["ok", 1, 2], "junk", [1], ["n", "x", 3]]}'); self.assertEqual(Settings(p).custom_presets(), [("ok", 1.0, 2.0)])

class TestBackgroundModelLocation(unittest.TestCase):
    """rembg decides where it stores models (our folder, ~/.u2net, ...). The app must find the file wherever it lands."""
    def setUp(self):
        import importlib.machinery, types
        from rstudio.engine import ai as aimod
        self.aimod = aimod; self.td = tempfile.TemporaryDirectory(); self.home = os.path.join(self.td.name, "home"); os.makedirs(self.home)
        self._env = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE", "U2NET_HOME", "XDG_DATA_HOME")}
        os.environ["HOME"] = self.home; os.environ["USERPROFILE"] = self.home; os.environ.pop("U2NET_HOME", None); os.environ.pop("XDG_DATA_HOME", None)
        s = Settings(os.path.join(self.td.name, "s.json")); s.set("models_dir", os.path.join(self.td.name, "models")); self.m = aimod.AIManager(s)
        self.store = {"mode": "ours"}
        def new_session(name, *a, **k):
            if self.store["mode"] == "none": return object()
            d = os.environ["U2NET_HOME"] if self.store["mode"] == "ours" else os.path.join(self.home, ".u2net"); os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, name + ".onnx"), "wb") as f: f.write(b"x")
            return object()
        fake = types.ModuleType("rembg"); fake.new_session = new_session; fake.remove = lambda *a, **k: None; fake.__spec__ = importlib.machinery.ModuleSpec("rembg", None); sys.modules["rembg"] = fake
    def tearDown(self):
        sys.modules.pop("rembg", None)
        for k, v in self._env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.td.cleanup()
    def test_not_ready_before_download(self): self.assertEqual(self.m.status("bg_remove")["status"], "needs_setup")
    def test_model_stored_in_our_folder(self):
        self.store["mode"] = "ours"; self.assertTrue(self.m.prepare_bg_model()); self.assertEqual(self.m.status("bg_remove")["status"], "ready"); self.assertTrue(os.path.isfile(self.m.bg_model_file()))
    def test_model_stored_in_rembg_default_folder_is_found_and_copied(self):
        self.store["mode"] = "default"; self.assertTrue(self.m.prepare_bg_model())            # this is the real-world case reported on Windows
        self.assertEqual(self.m.status("bg_remove")["status"], "ready"); self.assertTrue(os.path.isfile(self.m.bg_model_file()), "a copy is kept in our models folder")
    def test_default_folder_model_counts_even_without_prepare(self):
        os.makedirs(os.path.join(self.home, ".u2net")); open(os.path.join(self.home, ".u2net", "u2net.onnx"), "wb").close(); self.assertEqual(self.m.status("bg_remove")["status"], "ready")
    def test_download_that_leaves_no_file_gives_clear_error_with_paths(self):
        self.store["mode"] = "none"
        with self.assertRaises(self.aimod.AIUnavailable) as c: self.m.prepare_bg_model()
        self.assertIn("not found after the download", str(c.exception)); self.assertIn(".u2net", c.exception.hint); self.assertIn("rembg", c.exception.hint)

FAKE_EXE = ("#!/usr/bin/env python3\nimport sys\nfrom PIL import Image\na=sys.argv\nm=a[a.index('-n')+1];s=int(a[a.index('-s')+1])\n"
            "if m.startswith('realesrgan-x4plus') and s!=4: sys.stderr.write('x4plus only supports 4');sys.exit(1)\n"
            "open(sys.argv[0]+'.log','a').write(' '.join(a[1:])+'\\n')\n"
            "im=Image.open(a[a.index('-i')+1]);im.resize((im.width*s,im.height*s)).save(a[a.index('-o')+1])\n")

class TestOldRiponComputerFolder(unittest.TestCase):
    """The previous Ripon Computer app keeps its models in %LOCALAPPDATA%\\RiponComputer\\models - the new app must reuse them as they are."""
    def setUp(self):
        import importlib.machinery, types
        from rstudio.engine import ai as aimod
        self.aimod = aimod; self.td = tempfile.TemporaryDirectory(); self.la = os.path.join(self.td.name, "Local"); self.old = os.path.join(self.la, "RiponComputer", "models"); os.makedirs(self.old)
        self._env = {k: os.environ.get(k) for k in ("LOCALAPPDATA", "HOME", "USERPROFILE", "U2NET_HOME")}
        os.environ["LOCALAPPDATA"] = self.la; os.environ["HOME"] = os.environ["USERPROFILE"] = os.path.join(self.td.name, "home"); os.environ.pop("U2NET_HOME", None)
        fake = types.ModuleType("rembg"); fake.new_session = lambda n, *a, **k: ("session", n); fake.remove = lambda *a, **k: None; fake.__spec__ = importlib.machinery.ModuleSpec("rembg", None); sys.modules["rembg"] = fake
        self.s = Settings(os.path.join(self.td.name, "s.json")); self.m = aimod.AIManager(self.s)
    def tearDown(self):
        sys.modules.pop("rembg", None)
        for k, v in self._env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.td.cleanup()
    def _touch(self, *parts):
        p = os.path.join(self.old, *parts); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").close(); return p
    def test_old_folder_is_used_automatically(self):
        self.assertEqual(self.s.models_dir(), self.old); self.assertEqual(self.m.rembg_dir(), os.path.join(self.old, "rembg"))
    def test_explicit_choice_wins_but_unused_default_does_not(self):
        from rstudio import paths
        self.s.set("models_dir", os.path.join(self.td.name, "mine")); self.assertEqual(self.s.models_dir(), os.path.join(self.td.name, "mine"))
        self.s.set("models_dir", paths.default_models_dir()); self.assertEqual(self.s.models_dir(), self.old)          # pinned-by-accident default (folder does not exist) -> still the old folder
    def test_no_old_folder_falls_back_to_app_models(self):
        from rstudio import paths
        os.environ["LOCALAPPDATA"] = os.path.join(self.td.name, "nothing"); self.assertEqual(Settings(os.path.join(self.td.name, "x.json")).models_dir(), paths.default_models_dir())
    def test_old_rembg_model_makes_background_removal_ready(self):
        self._touch("rembg", "u2net_human_seg.onnx"); st = self.m.status("bg_remove"); self.assertEqual(st["status"], "ready"); self.assertIn("u2net_human_seg", st["detail"]); self.assertEqual(self.m.installed_bg(), ["u2net_human_seg"])
    def test_selected_but_missing_model_falls_back_to_an_installed_one(self):
        self._touch("rembg", "isnet-general-use.onnx"); self.s.set("bg_model", "birefnet-portrait")
        self.assertEqual(self.m.active_bg(), "isnet-general-use"); st = self.m.status("bg_remove"); self.assertEqual(st["status"], "ready"); self.assertIn("cannot run", st["detail"])
        self._touch("rembg", "birefnet-portrait.onnx"); self.assertEqual(self.m.active_bg(), "birefnet-portrait")
        self.s.set("bg_model", "nonsense"); self.assertEqual(self.m.selected_bg(), "u2net_human_seg")
    def _exe(self):
        p = self._touch("realesrgan-ncnn", "realesrgan-ncnn-vulkan.exe"); 
        with open(p, "w") as f: f.write(FAKE_EXE)
        os.chmod(p, 0o755); return p
    def test_old_ncnn_layout_found_and_models_listed(self):
        self.assertEqual(self.m.status("upscale")["status"], "needs_setup"); exe = self._exe(); self.assertEqual(self.m.realesrgan_exe(), exe); self.assertEqual(self.m.status("upscale")["status"], "needs_setup")      # exe but no weights yet
        self._touch("realesrgan-ncnn", "models", "realesrgan-x4plus.bin"); self._touch("realesrgan-ncnn", "models", "realesr-animevideov3.bin"); self._touch("realesrgan-ncnn", "models", "realesrgan-x4plus.param")
        self.assertEqual(self.m.upscale_models(), ["realesr-animevideov3", "realesrgan-x4plus"]); self.assertEqual(self.m.status("upscale")["status"], "ready")
    def test_x4plus_runs_at_4x_and_is_resized_to_requested_scale(self):
        self._exe(); self._touch("realesrgan-ncnn", "models", "realesrgan-x4plus.bin"); self._touch("realesrgan-ncnn", "models", "realesr-animevideov3.bin")
        a = rnd(30, 20)
        self.assertEqual(self.m.upscale(a, 2, "realesrgan-x4plus").shape, (40, 60, 3)); self.assertEqual(self.m.upscale(a, 4, "realesrgan-x4plus").shape, (80, 120, 3))
        self.assertEqual(self.m.upscale(a, 3, "realesr-animevideov3").shape, (60, 90, 3))
        log = open(self.m.realesrgan_exe() + ".log").read().splitlines(); self.assertTrue(any("-s 3" in l and "animevideov3" in l for l in log)); self.assertTrue(all("-g -1" not in l for l in log))
    def test_unknown_model_falls_back_to_x4plus_and_gpu_off_flag(self):
        self._exe(); self._touch("realesrgan-ncnn", "models", "realesrgan-x4plus.bin"); self.s.set("prefer_gpu", False)
        self.assertEqual(self.m.upscale(rnd(30, 20), 2, "does-not-exist").shape, (40, 60, 3)); self.assertIn("-g -1", open(self.m.realesrgan_exe() + ".log").read()); self.assertIn("realesrgan-x4plus", open(self.m.realesrgan_exe() + ".log").read())
    def test_no_weights_and_too_large_photo_give_clear_errors(self):
        self._exe()
        with self.assertRaises(self.aimod.AIUnavailable): self.m.upscale(rnd(30, 20), 2)
        self._touch("realesrgan-ncnn", "models", "realesrgan-x4plus.bin")
        with self.assertRaises(self.aimod.AIUnavailable) as c: self.m.upscale(np.zeros((10, 2500, 3), np.uint8), 2, "realesrgan-x4plus")
        self.assertIn("too large", str(c.exception))

class TestYuNetFallback(unittest.TestCase):
    def test_missing_or_broken_model_falls_back_to_haar(self):
        import skimage.data as sd; img = sd.astronaut(); base = passport.detect_faces(img); self.assertGreaterEqual(len(base), 1)
        self.assertEqual(passport.detect_faces(img, yunet_path="/no/such/model.onnx"), base)
        with tempfile.TemporaryDirectory() as td:
            bad = os.path.join(td, "yunet.onnx")
            with open(bad, "wb") as f: f.write(b"not a model")
            self.assertEqual(passport.detect_faces(img, yunet_path=bad), base)

class TestMODNetAndDiagnostics(unittest.TestCase):
    def setUp(self):
        import importlib.machinery, types
        from rstudio.engine import ai as aimod
        self.aimod = aimod; self.td = tempfile.TemporaryDirectory(); self.models = os.path.join(self.td.name, "models"); os.makedirs(os.path.join(self.models, "modnet")); os.makedirs(os.path.join(self.models, "rembg"))
        self._env = {k: os.environ.get(k) for k in ("LOCALAPPDATA", "HOME", "USERPROFILE", "U2NET_HOME")}; os.environ["HOME"] = os.environ["USERPROFILE"] = os.path.join(self.td.name, "home"); os.environ["LOCALAPPDATA"] = os.path.join(self.td.name, "none"); os.environ.pop("U2NET_HOME", None)
        self.s = Settings(os.path.join(self.td.name, "s.json")); self.s.set("models_dir", self.models); self.s.set("prefer_gpu", False); self.m = aimod.AIManager(self.s)
        self.model = os.path.join(self.models, "modnet", "modnet.onnx")
    def tearDown(self):
        sys.modules.pop("rembg", None)
        for k, v in self._env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.td.cleanup()
    def _fake_rembg(self, session_factory):
        import importlib.machinery, types
        fake = types.ModuleType("rembg"); fake.new_session = session_factory; fake.remove = lambda *a, **k: None; fake.__spec__ = importlib.machinery.ModuleSpec("rembg", None); sys.modules["rembg"] = fake
    def test_matte_shapes_and_range_for_many_sizes(self):
        from rstudio.engine.matting import MODNetMatter
        mm = MODNetMatter(onnx_tiny.build(self.model), False)
        for h, w in ((300, 200), (200, 300), (40, 30), (1000, 800), (700, 700), (33, 2000)):
            a = mm.matte(rnd(w, h, 3), 640); self.assertEqual(a.shape, (h, w)); self.assertEqual(a.dtype, np.float32); self.assertTrue(0.0 <= a.min() and a.max() <= 1.0)
    def test_modnet_alone_makes_background_removal_ready_and_returns_soft_alpha(self):
        onnx_tiny.build(self.model); st = self.m.status("bg_remove"); self.assertEqual(st["status"], "ready"); self.assertIn("MODNet", st["detail"]); self.assertEqual(self.m.active_bg(), "modnet")
        img = rnd(120, 160, 4); out = self.m.remove_background(img); self.assertEqual(out.shape, (160, 120, 4)); np.testing.assert_array_equal(out[..., :3], img)
        self.assertGreater(len(np.unique(out[..., 3])), 20, "alpha must be a soft matte, not a hard 0/255 mask"); self.assertEqual(self.m.remove_background(np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])).shape, (160, 120, 4))
    def test_selected_modnet_is_used_even_when_rembg_models_exist(self):
        import types
        onnx_tiny.build(self.model); self._fake_rembg(lambda *a, **k: None); open(os.path.join(self.models, "rembg", "u2net_human_seg.onnx"), "wb").close()
        self.assertEqual(self.m.active_bg(), "u2net_human_seg"); self.s.set("bg_model", "modnet"); self.assertEqual(self.m.active_bg(), "modnet")
    def test_auto_fallback_order_and_bria_never_automatic(self):
        self._fake_rembg(lambda *a, **k: None)
        for n in ("bria-rmbg", "silueta"): open(os.path.join(self.models, "rembg", n + ".onnx"), "wb").close()
        self.assertEqual(self.m.active_bg(), "silueta"); os.remove(os.path.join(self.models, "rembg", "silueta.onnx")); self.assertEqual(self.m.active_bg(), "u2net_human_seg")      # nothing usable: stays on the selection
        self.assertEqual(self.m.status("bg_remove")["status"], "needs_setup"); self.s.set("bg_model", "bria-rmbg"); self.assertEqual(self.m.active_bg(), "bria-rmbg")                # explicit choice is honoured
    def test_missing_onnxruntime_gives_install_hint(self):
        onnx_tiny.build(self.model); self.s.set("bg_model", "modnet"); orig = self.aimod._has
        self.aimod._has = lambda m: False if m in ("onnxruntime", "rembg") else orig(m)
        try:
            st = self.m.status("bg_remove"); self.assertEqual(st["status"], "needs_setup"); self.assertIn("pip install", st["detail"])
            with self.assertRaises(self.aimod.AIUnavailable): self.m.remove_background(rnd(20, 20))
        finally: self.aimod._has = orig
    def test_unrecognised_onnx_files_are_listed(self):
        self._fake_rembg(lambda *a, **k: None); open(os.path.join(self.models, "rembg", "my_custom.onnx"), "wb").close(); st = self.m.status("bg_remove"); self.assertEqual(st["status"], "needs_setup"); self.assertIn("my_custom.onnx", st["detail"])
    def test_rembg_file_located_through_the_loaded_session(self):
        elsewhere = os.path.join(self.td.name, "weird", "u2net_human_seg.onnx"); os.makedirs(os.path.dirname(elsewhere)); open(elsewhere, "wb").write(b"x" * 10)
        class Inner: _model_path = elsewhere
        class Sess: inner_session = Inner()
        self._fake_rembg(lambda *a, **k: Sess()); self.assertTrue(self.m.prepare_bg_model()); self.assertTrue(os.path.isfile(os.path.join(self.models, "rembg", "u2net_human_seg.onnx")))
    def test_failed_prepare_reports_version_session_path_and_folder_listing(self):
        class Sess: inner_session = None
        self._fake_rembg(lambda *a, **k: Sess()); open(os.path.join(self.models, "rembg", "other.onnx"), "wb").close()
        with self.assertRaises(self.aimod.AIUnavailable) as c: self.m.prepare_bg_model()
        h = c.exception.hint; self.assertIn("rembg", h); self.assertIn("other.onnx", h); self.assertIn("Folders checked", h); self.assertIn("u2net_human_seg.onnx", h)
    def test_modnet_download_from_url_and_rejects_empty(self):
        src = os.path.join(self.td.name, "src.onnx"); onnx_tiny.build(src); dest = os.path.join(self.td.name, "dl", "m.onnx")
        self.m._download("file://" + src.replace(os.sep, "/"), dest); self.assertTrue(os.path.isfile(dest)); self.assertFalse(os.path.exists(dest + ".part"))
        empty = os.path.join(self.td.name, "empty.onnx"); open(empty, "wb").close()
        with self.assertRaises(self.aimod.AIUnavailable): self.m._download("file://" + empty.replace(os.sep, "/"), os.path.join(self.td.name, "dl", "e.onnx"))
        self.assertFalse(os.path.exists(os.path.join(self.td.name, "dl", "e.onnx.part")))

if __name__ == "__main__": unittest.main(verbosity=1)

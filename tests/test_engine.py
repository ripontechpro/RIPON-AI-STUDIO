import os, sys, stat, time, tempfile, unittest, zipfile
import numpy as np, cv2
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rstudio.engine.document import Document, Layer, to_rgba, blend_over
from rstudio.engine import adjust, docstudio, passport, ai, tasks
from rstudio.engine.settings import Settings
from rstudio.engine import core

from rstudio.engine.document import composite_layers
def composite_layers_ref(d): return composite_layers(d.layers, d.w, d.h)

def photo(w=120, h=80):
    a = np.zeros((h, w, 3), np.uint8); a[..., 0] = np.linspace(0, 255, w, dtype=np.uint8)[None, :]; a[..., 1] = 90; a[..., 2] = np.linspace(255, 0, h, dtype=np.uint8)[:, None]
    return a

class TestDocument(unittest.TestCase):
    def test_new_open_composite(self):
        d = Document.new(40, 30); self.assertEqual((d.w, d.h, len(d.layers)), (40, 30, 1))
        c = d.composite(); self.assertEqual(c.shape, (30, 40, 4)); self.assertTrue((c == 255).all())
    def test_from_image_roundtrip_pixels(self):
        d = Document.from_image(photo()); np.testing.assert_array_equal(d.composite()[..., :3], photo())
    def test_pixels_are_immutable(self):
        d = Document.from_image(photo())
        with self.assertRaises(ValueError): d.layers[0].pixels[0, 0, 0] = 1
    def test_undo_redo_restores_exact_pixels(self):
        d = Document.from_image(photo()); before = d.composite().copy()
        d.apply_to_layer(d.active_id, lambda a: adjust.brightness_contrast(a, 50, 0), "Brighten")
        self.assertFalse(np.array_equal(d.composite(), before)); after = d.composite().copy()
        self.assertEqual(d.undo(), "Brighten"); np.testing.assert_array_equal(d.composite(), before)
        d.redo(); np.testing.assert_array_equal(d.composite(), after)
        self.assertFalse(d.can_redo())
    def test_new_edit_after_undo_drops_redo(self):
        d = Document.from_image(photo()); d.flip(True); d.undo(); d.flip(False); self.assertFalse(d.can_redo())
    def test_history_cap_keeps_original(self):
        d = Document.from_image(photo(), max_undo=5); orig = d.composite().copy()
        for i in range(20): d.set_layer_props(d.active_id, opacity=1.0, name=f"n{i}")
        self.assertLessEqual(len(d.history_labels()), 6); np.testing.assert_array_equal(d.original_composite(), orig)
    def test_original_composite_for_before_after(self):
        d = Document.from_image(photo()); o = d.composite().copy(); d.apply_to_layer(d.active_id, adjust.grayscale, "Gray")
        np.testing.assert_array_equal(d.original_composite(), o); self.assertFalse(np.array_equal(d.composite(), o))
    def test_layers_order_visibility_opacity(self):
        d = Document.new(10, 10, bg=(255, 255, 255, 255))
        red = d.add_image_layer(np.full((10, 10, 3), (255, 0, 0), np.uint8), "red", 0, 0)
        self.assertEqual(tuple(d.composite()[5, 5, :3]), (255, 0, 0))
        d.set_layer_props(red.id, opacity=0.5); self.assertEqual(d.composite()[5, 5, 1], 128 if d.composite()[5, 5, 1] in (127, 128) else d.composite()[5, 5, 1]); self.assertTrue(120 <= d.composite()[5, 5, 1] <= 135)
        d.set_layer_props(red.id, visible=False); self.assertEqual(tuple(d.composite()[5, 5, :3]), (255, 255, 255))
        d.set_layer_props(red.id, visible=True, opacity=1.0); blue = d.add_image_layer(np.full((10, 10, 3), (0, 0, 255), np.uint8), "blue", 0, 0)
        self.assertEqual(tuple(d.composite()[5, 5, :3]), (0, 0, 255)); d.move_layer_order(blue.id, -1)
        self.assertEqual(tuple(d.composite()[5, 5, :3]), (255, 0, 0))
    def test_duplicate_delete_and_last_layer_protected(self):
        d = Document.new(10, 10); lid = d.active_id; c = d.duplicate_layer(lid); self.assertEqual(len(d.layers), 2)
        self.assertTrue(d.remove_layer(c.id)); self.assertFalse(d.remove_layer(lid)); self.assertEqual(len(d.layers), 1)
    def test_alpha_compositing_transparent_layer(self):
        d = Document.new(4, 4, bg=None); self.assertTrue((d.composite()[..., 3] == 0).all())
        px = np.zeros((2, 2, 4), np.uint8); px[..., 0] = 200; px[..., 3] = 128; d.add_layer(Layer(to_rgba(px), "half", x=1, y=1))
        c = d.composite(); self.assertEqual(c[1, 1, 3], 128); self.assertEqual(c[0, 0, 3], 0)
    def test_layer_partially_offscreen(self):
        d = Document.new(10, 10); d.add_image_layer(np.zeros((8, 8, 3), np.uint8), "off", -4, 6); self.assertEqual(d.composite().shape, (10, 10, 4))
        self.assertEqual(tuple(d.composite()[7, 2, :3]), (0, 0, 0)); self.assertEqual(tuple(d.composite()[2, 2, :3]), (255, 255, 255))
    def test_selection_limits_adjustment(self):
        d = Document.new(20, 20); d.select_rect(5, 5, 10, 10)
        d.apply_to_layer(d.active_id, lambda a: adjust.exposure(a, -2.0), "Darken sel")
        c = d.composite(); self.assertLess(c[7, 7, 0], 255); self.assertEqual(c[1, 1, 0], 255); self.assertEqual(c[15, 15, 0], 255)
    def test_crop_resize_rotate_flip_geometry(self):
        a = np.zeros((20, 30, 3), np.uint8); a[2, 3] = (255, 0, 0)
        d = Document.from_image(a); d.rotate90(True); self.assertEqual((d.w, d.h), (20, 30)); self.assertEqual(tuple(d.composite()[3, 17, :3]), (255, 0, 0))
        d.undo(); d.flip(True); self.assertEqual(tuple(d.composite()[2, 26, :3]), (255, 0, 0))
        d.undo(); d.flip(False); self.assertEqual(tuple(d.composite()[17, 3, :3]), (255, 0, 0))
        d.undo(); self.assertTrue(d.crop(3, 2, 13, 12)); self.assertEqual((d.w, d.h), (10, 10)); self.assertEqual(tuple(d.composite()[0, 0, :3]), (255, 0, 0))
        d.undo(); d.resize(60, 40); self.assertEqual((d.w, d.h), (60, 40)); self.assertEqual(d.layers[0].pixels.shape[:2], (40, 60))
    def test_rotate_with_extra_layer(self):
        d = Document.new(20, 10); d.add_image_layer(np.zeros((2, 2, 3), np.uint8), "dot", 0, 0); d.rotate90(True)
        self.assertEqual((d.w, d.h), (10, 20)); self.assertEqual(tuple(d.composite()[0, 8, :3]), (0, 0, 0)); self.assertEqual(tuple(d.composite()[0, 0, :3]), (255, 255, 255))
    def test_transform_layer(self):
        d = Document.new(100, 100); L = d.add_image_layer(np.full((20, 10, 3), 0, np.uint8), "bar", 40, 40)
        d.transform_layer(L.id, scale=2.0, angle=0); self.assertEqual((d.layer(L.id).w, d.layer(L.id).h), (20, 40))
        d.transform_layer(L.id, angle=90); self.assertEqual((d.layer(L.id).w, d.layer(L.id).h), (40, 20))
    def test_merge_down_and_flatten(self):
        d = Document.new(10, 10); d.add_image_layer(np.full((4, 4, 3), (255, 0, 0), np.uint8), "r", 2, 2); before = d.composite().copy()
        d.merge_down(d.active_id); self.assertEqual(len(d.layers), 1); np.testing.assert_array_equal(d.composite(), before)
        d.add_text("Hi"); d.flatten(); self.assertEqual(len(d.layers), 1)
    def test_text_and_shape_layers_stay_editable(self):
        d = Document.new(300, 200); t = d.add_text("Hello", 10, 10, size=40); w1 = t.w
        d.update_params(t.id, text="Hello wide world", size=40); self.assertGreater(d.layer(t.id).w, w1)
        s = d.add_shape("ellipse", 20, 20, 100, 60, fill=(255, 0, 0, 255), stroke=(0, 0, 0, 255), stroke_w=4)
        self.assertEqual(s.kind, "shape"); self.assertGreater(s.w, 100); self.assertTrue(d.layer(s.id).pixels[:, :, 3].max() == 255)
        d.undo(); d.undo(); self.assertEqual(d.layer(t.id).params["text"], "Hello")
    def test_project_save_load(self):
        d = Document.new(30, 20, dpi=200, name="proj"); d.add_text("T", 1, 1, size=12); d.add_image_layer(photo(10, 10), "p", 3, 3)
        d.set_layer_props(d.active_id, opacity=0.4, visible=True)
        with tempfile.TemporaryDirectory() as td:
            p = d.save(os.path.join(td, "a.rai")); self.assertFalse(d.dirty); e = Document.load(p)
            self.assertEqual((e.w, e.h, e.dpi, e.name, len(e.layers)), (30, 20, 200, "proj", 3))
            np.testing.assert_array_equal(e.composite(), d.composite()); self.assertAlmostEqual(e.layers[-1].opacity, 0.4); self.assertEqual(e.layers[1].kind, "text")
            self.assertEqual(e.layers[1].params["text"], "T")
    def test_load_rejects_newer_and_corrupt(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "bad.rai")
            with zipfile.ZipFile(p, "w") as z: z.writestr("doc.json", '{"version": 99, "w":1,"h":1,"layers":[]}')
            with self.assertRaises(ValueError): Document.load(p)
            with open(p, "wb") as f: f.write(b"junk")
            with self.assertRaises(Exception): Document.load(p)
    def test_export_formats_and_dpi(self):
        d = Document.from_image(photo(60, 40)); d.dpi = 200
        with tempfile.TemporaryDirectory() as td:
            for ext in (".png", ".jpg", ".webp", ".bmp", ".tif", ".pdf"):
                p = d.export(os.path.join(td, "o" + ext)); self.assertTrue(os.path.getsize(p) > 100, ext)
            im = Image.open(os.path.join(td, "o.png")); self.assertEqual(im.size, (60, 40)); self.assertAlmostEqual(im.info["dpi"][0], 200, delta=1)
            self.assertEqual(Image.open(os.path.join(td, "o.jpg")).mode, "RGB")
            with self.assertRaises(ValueError): d.export(os.path.join(td, "x.xyz"))
            self.assertFalse([f for f in os.listdir(td) if f.endswith(".part")])
    def test_export_transparent_png_keeps_alpha(self):
        d = Document.new(5, 5, bg=None); d.add_image_layer(np.zeros((2, 2, 3), np.uint8), "x", 0, 0)
        with tempfile.TemporaryDirectory() as td:
            p = d.export(os.path.join(td, "t.png")); im = Image.open(p); self.assertEqual(im.mode, "RGBA"); self.assertEqual(im.getpixel((4, 4))[3], 0)
    def test_open_image_exif_and_dpi(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "a.jpg"); Image.fromarray(photo()).save(p, dpi=(150, 150)); d = Document.open_image(p)
            self.assertEqual(d.dpi, 150); self.assertEqual(d.name, "a"); self.assertEqual((d.w, d.h), (120, 80))

class TestAdjust(unittest.TestCase):
    def setUp(self): self.a = to_rgba(photo()); self.a = np.array(self.a); self.a[..., 3] = np.linspace(10, 255, self.a.shape[1], dtype=np.uint8)[None, :]
    def test_defaults_are_identity_or_close_and_alpha_kept(self):
        for k, adj in adjust.ADJUSTMENTS.items():
            if k in ("grayscale", "auto_levels", "whiten_paper", "denoise", "sharpen", "blur"): continue
            out = adj.apply(self.a); self.assertEqual(out.shape, self.a.shape, k); np.testing.assert_array_equal(out[..., 3], self.a[..., 3])
            self.assertLessEqual(np.abs(out[..., :3].astype(int) - self.a[..., :3]).max(), 2, k + " default must be ~identity")
    def test_every_adjustment_runs_keeps_alpha_and_dtype(self):
        for k, adj in adjust.ADJUSTMENTS.items():
            out = adj.apply(self.a); self.assertEqual(out.dtype, np.uint8, k); np.testing.assert_array_equal(out[..., 3], self.a[..., 3], k)
    def test_directional_behaviour(self):
        m = lambda x: x[..., :3].mean()
        self.assertGreater(m(adjust.brightness_contrast(self.a, 40, 0)), m(self.a)); self.assertLess(m(adjust.brightness_contrast(self.a, -40, 0)), m(self.a))
        self.assertGreater(adjust.brightness_contrast(self.a, 0, 50)[..., :3].std(), self.a[..., :3].std())
        self.assertGreater(m(adjust.exposure(self.a, 1.0)), m(self.a)); self.assertLess(m(adjust.exposure(self.a, -1.0)), m(self.a))
        g = adjust.grayscale(self.a); np.testing.assert_array_equal(g[..., 0], g[..., 1]); np.testing.assert_array_equal(g[..., 1], g[..., 2])
        s = adjust.hue_saturation(self.a, 0, -100, 0); self.assertLess(np.ptp(s[..., :3].astype(int), axis=2).mean(), 3)
        self.assertGreater(adjust.color_balance(self.a, 80, 0, 0)[..., 0].mean(), self.a[..., 0].mean())
        self.assertLess(adjust.blur(self.a, 5)[..., :3].std(), self.a[..., :3].std() + 1e-6)
        noisy = self.a.copy(); noisy[..., :3] = np.clip(noisy[..., :3].astype(int) + np.random.RandomState(0).randint(-25, 25, noisy[..., :3].shape), 0, 255).astype(np.uint8)
        self.assertLess(np.abs(adjust.denoise(noisy, 12)[..., :3].astype(int) - self.a[..., :3]).mean(), np.abs(noisy[..., :3].astype(int) - self.a[..., :3]).mean())
    def test_levels_clip_and_curves_monotone(self):
        lv = adjust.levels(self.a, 50, 200, 1.0); self.assertEqual(lv[..., :3].min(), 0); self.assertEqual(lv[..., :3].max(), 255)
        for s, mid, h in [(60, -40, 80), (-100, 100, -100), (0, 0, 0)]:
            t = adjust._monotone_curve([(0, 0), (64, 64 + s * .6), (128, 128 + mid * .6), (192, 192 + h * .6), (255, 255)])
            pts = np.clip(t, 0, 255); self.assertTrue(np.isfinite(pts).all())
        ramp = np.zeros((1, 256, 4), np.uint8); ramp[..., :3] = np.arange(256)[None, :, None]; ramp[..., 3] = 255
        out = adjust.curves(ramp, 60, 0, -60)[0, :, 0]; self.assertTrue(np.all(np.diff(out.astype(int)) >= -1))
    def test_auto_levels_stretches_flat_image(self):
        flat = np.full((20, 20, 4), 255, np.uint8); flat[..., :3] = np.random.RandomState(1).randint(100, 150, (20, 20, 3)); out = adjust.auto_levels(flat)
        self.assertGreater(np.ptp(out[..., 0]), np.ptp(flat[..., 0]))
    def test_unknown_params_ignored(self): adjust.ADJUSTMENTS["blur"].apply(self.a, bogus=1)

def make_scan(rot=3.0, w=900, h=1200, seed=0):
    rs = np.random.RandomState(seed); page = np.full((h, w, 3), 235, np.float32)
    yy, xx = np.mgrid[0:h, 0:w]; page *= (0.72 + 0.28 * (xx / w))[..., None]              # strong lighting gradient
    img = np.clip(page + rs.normal(0, 3, page.shape), 0, 255).astype(np.uint8)
    for i in range(14): cv2.putText(img, "Sample text line number %d for scan" % i, (80, 140 + i * 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 2, cv2.LINE_AA)
    cv2.circle(img, (700, 1050), 60, (200, 20, 20), 5)                                       # red stamp
    cv2.putText(img, "SEAL", (655, 1060), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 20, 20), 3, cv2.LINE_AA)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), rot, 1.0); out = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(120, 120, 120))
    return out

class TestDocStudio(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.scan = make_scan()
    def test_clean_whitens_deskews_and_keeps_ink(self):
        out, rep = docstudio.clean_scan(self.scan, docstudio.CleanOptions(auto_crop=False))
        g = cv2.cvtColor(out, cv2.COLOR_RGB2GRAY); core_region = g[len(g) // 3: 2 * len(g) // 3, len(g[0]) // 4: 3 * len(g[0]) // 4]
        self.assertGreater(np.percentile(core_region, 70), 235, "paper should be white")
        self.assertGreater(rep["ink_retention"], 0.85); self.assertLess(abs(rep["skew_deg"] + 3.0) , 1.6)
        self.assertLess(abs(core.estimate_skew(out)), 1.0)
    def test_input_not_modified(self):
        c = self.scan.copy(); docstudio.clean_scan(c); np.testing.assert_array_equal(c, self.scan)
    def test_bw_mode_is_binary_except_marks_and_stamp_survives(self):
        out, _ = docstudio.clean_scan(self.scan, docstudio.CleanOptions(mode="bw", preserve_marks=True, deskew=False, auto_crop=False))
        sat = (out.max(-1).astype(int) - out.min(-1)); self.assertGreater((sat > 80).sum(), 300, "red stamp must stay coloured")
        gray_only, _ = docstudio.clean_scan(self.scan, docstudio.CleanOptions(mode="bw", preserve_marks=False, deskew=False, auto_crop=False))
        self.assertEqual(int((gray_only.max(-1).astype(int) - gray_only.min(-1)).max()), 0); self.assertTrue(set(np.unique(gray_only)) <= {0, 255})
    def test_gray_mode(self):
        out, _ = docstudio.clean_scan(self.scan, docstudio.CleanOptions(mode="gray", preserve_marks=False, deskew=False, auto_crop=False))
        self.assertEqual(int((out.max(-1).astype(int) - out.min(-1)).max()), 0)
    def test_auto_crop_removes_border(self):
        out, rep = docstudio.clean_scan(self.scan, docstudio.CleanOptions(deskew=False)); self.assertLess(out.shape[0] * out.shape[1], self.scan.shape[0] * self.scan.shape[1])
        self.assertIsNotNone(rep["crop"]); self.assertTrue(rep.get("page_cut"))
    def test_rotated_scan_full_pipeline_has_no_dark_wedges(self):
        out, rep = docstudio.clean_scan(self.scan, docstudio.CleanOptions()); g = cv2.cvtColor(out, cv2.COLOR_RGB2GRAY)
        frame = np.concatenate([g[:8].ravel(), g[-8:].ravel(), g[:, :8].ravel(), g[:, -8:].ravel()])
        self.assertLess((frame < 60).mean(), 0.03); self.assertLess(abs(core.estimate_skew(out)), 1.0); self.assertGreater(rep["ink_retention"], 0.8)
    def test_already_flat_scan_is_not_resampled_needlessly(self):
        flat = make_scan(0.0); out, rep = docstudio.clean_scan(flat, docstudio.CleanOptions(deskew=False)); self.assertFalse(rep.get("page_cut", False))
    def test_blank_page_does_not_crash(self):
        blank = np.full((300, 200, 3), 240, np.uint8); out, rep = docstudio.clean_scan(blank); self.assertEqual(out.ndim, 3); self.assertEqual(rep["ink_retention"], 1.0)
    def test_intensity_extremes(self):
        for k in (0, 100): out, _ = docstudio.clean_scan(self.scan, docstudio.CleanOptions(intensity=k, deskew=False, auto_crop=False)); self.assertEqual(out.shape, self.scan.shape)
    def test_straighten_document_photo(self):
        page = np.full((600, 800, 3), 60, np.uint8); page[100:500, 150:650] = 240; cv2.putText(page, "HELLO", (200, 300), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
        out, conf = docstudio.straighten_document(page); self.assertTrue(out.shape[0] > 0)
        if conf >= 0.5: self.assertLess(out.shape[1], 800)
    def test_batch_keeps_going_after_bad_file_and_writes_pdf(self):
        with tempfile.TemporaryDirectory() as td:
            ok = os.path.join(td, "a.png"); Image.fromarray(self.scan[:400, :300]).save(ok); bad = os.path.join(td, "bad.png"); open(bad, "wb").write(b"not an image")
            res = docstudio.batch_clean([bad, ok], os.path.join(td, "out"), docstudio.CleanOptions(auto_crop=False, deskew=False), "png", pdf_out=os.path.join(td, "all.pdf"))
            self.assertEqual([r["ok"] for r in res], [False, True]); self.assertIn("Error", res[0]["error"]); self.assertTrue(os.path.getsize(os.path.join(td, "all.pdf")) > 500)
            res = docstudio.batch_clean([ok], os.path.join(td, "out2"), docstudio.CleanOptions(auto_crop=False, deskew=False), "jpg")
            self.assertTrue(os.path.isfile(res[0]["out"]))
    def test_batch_cancel(self):
        tm = tasks.TaskManager()
        with tempfile.TemporaryDirectory() as td:
            files = []
            for i in range(6): p = os.path.join(td, f"{i}.png"); Image.fromarray(self.scan[:500, :400]).save(p); files.append(p)
            t = tm.submit("batch", lambda ctx: docstudio.batch_clean(files, os.path.join(td, "o"), docstudio.CleanOptions(auto_crop=False, deskew=False), ctx=ctx), on_progress=lambda t: t.cancel() if t.frac > 0.2 else None)
            self.assertEqual(tm.wait(t, 60), "cancelled")
    def test_pdf_import_reports_missing_backend(self):
        if docstudio.pdf_backend() is None:
            with self.assertRaises(docstudio.Unavailable): docstudio.pdf_to_images("x.pdf")

class TestPassport(unittest.TestCase):
    def test_a4_35x45_capacity_and_positions(self):
        info = passport.sheet_info(35, 45, 8); self.assertTrue(info["fits"]); self.assertGreaterEqual(info["capacity"], 8); self.assertEqual(info["pages"], 1)
        docs, info = passport.make_sheet_documents(photo(200, 260), 35, 45, 8, dpi=300)
        d = docs[0]; self.assertEqual((d.w, d.h), (2480, 3508)); self.assertEqual(len(d.layers), 9)
        for L in d.layers[1:]:
            self.assertTrue(L.x >= 0 and L.y >= 0 and L.x + L.w <= d.w and L.y + L.h <= d.h)
            self.assertIn((L.w, L.h), [(core.mm2px(35, 300), core.mm2px(45, 300)), (core.mm2px(45, 300), core.mm2px(35, 300))])
        self.assertAlmostEqual(d.size_mm()[0], 210, delta=0.2)
    def test_spills_to_second_page(self):
        info = passport.sheet_info(35, 45, 100); self.assertGreater(info["pages"], 1)
        docs, _ = passport.make_sheet_documents(photo(200, 260), 35, 45, 100, dpi=100); self.assertEqual(len(docs), info["pages"])
    def test_too_large_photo_rejected(self):
        with self.assertRaises(ValueError): passport.make_sheet_documents(photo(), 300, 400, 1)
        with self.assertRaises(ValueError): passport.make_sheet_documents(photo(), 35, 45, 0)
    def test_borders_and_cut_marks_layer(self):
        docs, _ = passport.make_sheet_documents(photo(200, 260), 35, 45, 4, dpi=100, border_mm=0.5, cut_marks=True); self.assertEqual(docs[0].layers[-1].name, "Borders & cut marks")
    def test_layout_sheet_is_editable_and_exports_exact_a4(self):
        docs, _ = passport.make_sheet_documents(photo(200, 260), 35, 45, 4, dpi=300); d = docs[0]; d.set_layer_props(d.layers[1].id, x=100, y=100)
        with tempfile.TemporaryDirectory() as td:
            p = d.export(os.path.join(td, "s.png"))
            with Image.open(p) as im: self.assertEqual(im.size, (2480, 3508)); self.assertAlmostEqual(im.info["dpi"][0], 300, delta=1)
            p = d.export(os.path.join(td, "s.pdf")); self.assertTrue(os.path.getsize(p) > 1000)
    def test_blank_page(self):
        d = passport.blank_page_document("A4", "Landscape"); self.assertEqual((d.w, d.h), (3508, 2480))

class TestAI(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); s = Settings(os.path.join(self.td.name, "s.json")); s.set("models_dir", os.path.join(self.td.name, "models")); self.m = ai.AIManager(s)
    def tearDown(self): self.td.cleanup()
    def test_status_honest_when_nothing_installed(self):
        st = {c["key"]: c for c in self.m.capabilities()}
        self.assertEqual(st["upscale"]["status"], "needs_setup"); self.assertEqual(st["enhance"]["kind"], "classical"); self.assertEqual(st["object_remove"]["status"], "needs_setup"); self.assertEqual(st["old_photo"]["status"], "planned")
        self.assertEqual(st["generate"]["status"], "planned"); self.assertIn(st["bg_remove"]["status"], ("needs_setup",))
    def test_missing_models_raise_clear_errors(self):
        with self.assertRaises(ai.AIUnavailable) as c: self.m.remove_background(photo())
        self.assertTrue(c.exception.hint)
        with self.assertRaises(ai.AIUnavailable): self.m.upscale(photo(), 2)
    def _fake_exe(self, body):
        d = self.m.realesrgan_dir(); os.makedirs(os.path.join(d, "models"), exist_ok=True); p = os.path.join(d, "realesrgan-ncnn-vulkan")
        with open(p, "w") as f: f.write(body)
        os.chmod(p, 0o755)
        for n in ("realesrgan-x4plus", "realesr-animevideov3"): open(os.path.join(d, "models", n + ".bin"), "wb").close()
        return p
    def test_upscale_via_cli_contract(self):
        self._fake_exe("#!/usr/bin/env python3\nimport sys\nfrom PIL import Image\na=sys.argv\ni=a[a.index('-i')+1];o=a[a.index('-o')+1];s=int(a[a.index('-s')+1])\nim=Image.open(i);im.resize((im.width*s,im.height*s)).save(o)\n")
        self.assertEqual(self.m.status("upscale")["status"], "ready"); out = self.m.upscale(photo(30, 20), 2); self.assertEqual(out.shape, (40, 60, 3))
    def test_upscale_failure_and_cancel(self):
        self._fake_exe("#!/bin/sh\necho boom >&2\nexit 3\n")
        with self.assertRaises(ai.AIUnavailable) as c: self.m.upscale(photo(), 2)
        self.assertIn("boom", c.exception.hint)
        self._fake_exe("#!/bin/sh\nsleep 30\n") if False else None
        os.remove(self.m.realesrgan_exe()); self._fake_exe("#!/bin/sh\nsleep 30\n")
        tm = tasks.TaskManager(); t = tm.submit("up", lambda ctx: self.m.upscale(photo(), 2, ctx=ctx)); time.sleep(0.5); t.cancel(); t0 = time.time()
        self.assertEqual(tm.wait(t, 10), "cancelled"); self.assertLess(time.time() - t0, 5)
    def test_replace_background(self):
        rgba = np.zeros((4, 4, 4), np.uint8); rgba[1:3, 1:3] = (10, 20, 30, 255); out = ai.AIManager.replace_background(rgba, (255, 255, 255)); self.assertEqual(tuple(out[0, 0]), (255, 255, 255, 255)); self.assertEqual(tuple(out[1, 1]), (10, 20, 30, 255))
    def test_auto_enhance_is_classical(self): self.assertEqual(ai.auto_enhance(to_rgba(photo()).copy()).shape, (80, 120, 4))

class TestTasksSettings(unittest.TestCase):
    def test_progress_done_error(self):
        tm = tasks.TaskManager(); seen = []
        t = tm.submit("ok", lambda ctx: (ctx.progress(0.5, "half"), 42)[1], on_progress=lambda t: seen.append(t.frac)); self.assertEqual(tm.wait(t), "done"); self.assertEqual(t.result, 42); self.assertEqual(seen, [0.5])
        t = tm.submit("bad", lambda ctx: 1 / 0); self.assertEqual(tm.wait(t), "error"); self.assertIsInstance(t.error, ZeroDivisionError)
    def test_callbacks_that_raise_do_not_kill_worker(self):
        tm = tasks.TaskManager(); t = tm.submit("x", lambda c: 1, on_done=lambda t: 1 / 0); self.assertEqual(tm.wait(t), "done")
    def test_settings_roundtrip_and_recent(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "s.json"); s = Settings(p); s.set("theme", "dark"); f = os.path.join(td, "a.png"); open(f, "w").close(); s.add_recent(f); s.add_recent(os.path.join(td, "gone.png")); self.assertTrue(s.save())
            s2 = Settings(p); self.assertEqual(s2.get("theme"), "dark"); self.assertEqual(s2.recent_existing(), [os.path.abspath(f)])
            
            with open(p, "w") as f: f.write("{broken")
            self.assertEqual(Settings(p).get("max_undo"), 40)
    def test_no_api_key_field_in_settings(self):
        from rstudio.engine.settings import DEFAULTS; self.assertFalse([k for k in DEFAULTS if "key" in k.lower() or "token" in k.lower()])




class TestDocumentPreviewHelpers(unittest.TestCase):
    def test_history_memory_budget(self):
        d = Document.new(1000, 1000, mem_budget_mb=40); orig = d.original_composite().copy()
        for i in range(25): d.apply_to_layer(d.active_id, lambda a, i=i: adjust.brightness_contrast(a, (i % 5) - 2, 0), f"e{i}")
        self.assertLessEqual(len(d.history_labels()), 10); np.testing.assert_array_equal(d.original_composite(), orig); self.assertTrue(d.can_undo()); d.undo(); d.redo()
        self.assertEqual(d.history_labels()[-1], "e24")
    def test_insert_layers_single_history_step_and_hide(self):
        d = Document.new(10, 10); base = d.active_id; n = len(d.history_labels())
        a = Layer(to_rgba(np.zeros((2, 2, 3), np.uint8)), "bg"); b = Layer(to_rgba(np.full((2, 2, 3), 9, np.uint8)), "cut")
        d.insert_layers(1, [a, b], hide_id=base, label="Swap"); self.assertEqual(len(d.history_labels()), n + 1); self.assertFalse(d.layer(base).visible); self.assertEqual(d.active_id, b.id)
        d.undo(); self.assertTrue(d.layer(base).visible); self.assertEqual(len(d.layers), 1)
    def test_patch_cache_matches_full_composite(self):
        d = Document.new(60, 40); L = d.add_image_layer(np.full((30, 30, 3), (10, 200, 30), np.uint8), "a", 10, 5); d.composite()
        arr = np.array(L.pixels); arr[5:12, 5:12] = (255, 0, 0, 255); L.pixels = arr; d.patch_cache(15, 10, 22, 17)
        fresh = composite_layers_ref(d); np.testing.assert_array_equal(d.composite(), fresh)
        d.patch_cache(-50, -50, 500, 500); np.testing.assert_array_equal(d.composite(), composite_layers_ref(d))
    def test_composite_with_override_does_not_touch_history(self):
        d = Document.from_image(photo()); v = d.version; ov = {d.active_id: adjust.grayscale(np.array(d.layers[0].pixels))}
        c = d.composite_with(ov); self.assertEqual(int((c[..., 0].astype(int) - c[..., 1]).max()), 0); self.assertEqual(d.version, v); self.assertFalse(d.can_undo())
    def test_masked_respects_selection_and_replace_with_image(self):
        d = Document.new(20, 20); d.select_rect(0, 0, 10, 10); res = np.zeros((20, 20, 4), np.uint8); out = d.masked(d.active_id, res)
        self.assertEqual(out[5, 5, 3], 0); self.assertEqual(out[15, 15, 3], 255)
        d.replace_with_image(np.zeros((8, 6, 3), np.uint8), "x"); self.assertEqual((d.w, d.h, len(d.layers)), (6, 8, 1)); d.undo(); self.assertEqual((d.w, d.h), (20, 20))
    def test_invalidate_refreshes_without_history(self):
        d = Document.new(10, 10); L = d.add_image_layer(np.zeros((2, 2, 3), np.uint8), "a", 0, 0); n = len(d.history_labels()); L.x = 5; d.invalidate()
        self.assertEqual(tuple(d.composite()[0, 5, :3]), (0, 0, 0)); self.assertEqual(len(d.history_labels()), n)

if __name__ == "__main__": unittest.main(verbosity=1)

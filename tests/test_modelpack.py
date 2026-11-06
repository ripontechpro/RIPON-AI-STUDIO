import os, sys, json, zipfile, hashlib, tempfile, unittest, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rstudio.engine import modelpack as mp
from rstudio.engine.tasks import TaskManager, Cancelled

def sha(b): return hashlib.sha256(b).hexdigest()

def make_models(root):
    files = {"rembg/u2net_human_seg.onnx": b"A" * 5000, "modnet/modnet.onnx": b"B" * 3000, "lama/lama_fp32.onnx": os.urandom(40000), "gfpgan/gfpgan_1.4.onnx": b"G" * 1234,
             "realesrgan-ncnn/realesrgan-ncnn-vulkan.exe": b"MZ" + b"E" * 2000, "realesrgan-ncnn/models/realesrgan-x4plus.bin": b"X" * 777, "realesrgan-ncnn/models/realesrgan-x4plus.param": b"P" * 55,
             "codeformer/codeformer.onnx": b"C" * 9000, "yunet/face_detection_yunet_2023mar.onnx": b"Y" * 1500}
    for rel, data in files.items():
        p = os.path.join(root, *rel.split("/")); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f: f.write(data)
    os.makedirs(os.path.join(root, "torch")); open(os.path.join(root, "torch", "cache.bin"), "wb").write(b"t")     # unknown folder: never part of a pack
    open(os.path.join(root, "doc_models.json"), "w").write("{}")                                                    # loose file in the root: not part of a pack
    open(os.path.join(root, "lama", "half.onnx.part"), "wb").write(b"junk")                                         # unfinished download: skipped
    return files

def craft(path, entries, extra=None, fmt=mp.FORMAT):
    """Write a pack by hand so hostile manifests can be tested. entries: [(path_in_manifest, data, claimed_sha or None, name_in_zip or None)]"""
    with zipfile.ZipFile(path, "w") as z:
        man = []
        for rel, data, claimed, name in entries:
            z.writestr(name or rel, data); man.append(dict(path=rel, size=len(data), sha256=claimed or sha(data)))
        for n, d in (extra or {}).items(): z.writestr(n, d)
        z.writestr("manifest.json", json.dumps(dict(format=fmt, files=man)))

class TestSafeRelpath(unittest.TestCase):
    def test_good_paths(self):
        for p in ("rembg/a.onnx", "realesrgan-ncnn/models/x.bin", "realesrgan-ncnn/realesrgan-ncnn-vulkan.exe", "lama/lama_fp32.onnx"): self.assertEqual(mp.safe_relpath(p), p)
    def test_bad_paths(self):
        bad = ["../evil.txt", "rembg/../../evil", "/etc/passwd", "C:/Windows/x.onnx", "C:\\x", "rembg\\a.onnx", "rembg//a.onnx", "rembg/./a.onnx", "unknown/a.onnx", "a.onnx", "rembg/", "", None, "rembg/a.onnx\x00.bat",
               "rembg/run.bat", "lama/x.ps1", "gfpgan/setup.vbs", "modnet/tool.exe", "rembg/evil.dll", "lama/a.lnk", "rembg/CON:stream", "rembg/trailing.", "rembg/space ", "rembg/x.PY"]
        for p in bad:
            with self.assertRaises(mp.PackError, msg=repr(p)): mp.safe_relpath(p)
    def test_case_insensitive_blocking(self):
        with self.assertRaises(mp.PackError): mp.safe_relpath("rembg/RUN.BAT")
        with self.assertRaises(mp.PackError): mp.safe_relpath("lama/TOOL.EXE")

class TestBackupRestore(unittest.TestCase):
    def setUp(self): self.td = tempfile.TemporaryDirectory(); self.src = os.path.join(self.td.name, "models"); os.makedirs(self.src); self.files = make_models(self.src); self.pack = os.path.join(self.td.name, "pack.zip")
    def tearDown(self): self.td.cleanup()
    def test_scan_lists_only_known_folders_with_sizes(self):
        g = {x["key"]: x for x in mp.scan(self.src)}; self.assertEqual(set(g), {"rembg", "modnet", "lama", "gfpgan", "realesrgan-ncnn", "codeformer", "yunet"}); self.assertEqual(g["realesrgan-ncnn"]["files"], 3); self.assertEqual(g["rembg"]["bytes"], 5000)
        self.assertEqual(g["lama"]["files"], 1, ".part files are not counted")
    def test_full_roundtrip_is_bit_exact(self):
        r = mp.create_backup(self.src, self.pack); self.assertEqual(r["files"], len(self.files)); dst = os.path.join(self.td.name, "friend", "models")
        info = mp.inspect_backup(self.pack); self.assertEqual(info["problems"], []); self.assertEqual(info["total"], sum(len(v) for v in self.files.values())); self.assertIn("lama", [g["key"] for g in info["groups"]])
        out = mp.restore_backup(self.pack, dst); self.assertEqual(out["failed"], []); self.assertEqual(sorted(out["restored"]), sorted(self.files))
        for rel, data in self.files.items(): self.assertEqual(open(os.path.join(dst, *rel.split("/")), "rb").read(), data, rel)
        self.assertFalse(os.path.exists(os.path.join(dst, "torch"))); self.assertFalse(os.path.exists(os.path.join(dst, "doc_models.json")))
        self.assertFalse([f for dp, _, fs in os.walk(dst) for f in fs if f.endswith(".part")])
    def test_pack_contains_readme_and_manifest_with_hashes(self):
        mp.create_backup(self.src, self.pack)
        with zipfile.ZipFile(self.pack) as z:
            self.assertIn("README.txt", z.namelist()); m = json.loads(z.read("manifest.json")); self.assertEqual(m["format"], mp.FORMAT)
            e = [x for x in m["files"] if x["path"] == "modnet/modnet.onnx"][0]; self.assertEqual(e["sha256"], sha(b"B" * 3000)); self.assertEqual(e["size"], 3000)
            self.assertFalse(any(i.compress_type != zipfile.ZIP_STORED for i in z.infolist() if i.filename.endswith(".onnx")))
    def test_subset_backup_and_subset_restore(self):
        mp.create_backup(self.src, self.pack, keys=["lama", "modnet"]); self.assertEqual({g["key"] for g in mp.inspect_backup(self.pack)["groups"]}, {"lama", "modnet"})
        mp.create_backup(self.src, self.pack, keys=None); dst = os.path.join(self.td.name, "d"); out = mp.restore_backup(self.pack, dst, keys=["gfpgan"]); self.assertEqual(out["restored"], ["gfpgan/gfpgan_1.4.onnx"]); self.assertFalse(os.path.exists(os.path.join(dst, "lama")))
    def test_existing_same_size_files_are_kept_unless_overwrite(self):
        mp.create_backup(self.src, self.pack, keys=["modnet"]); dst = os.path.join(self.td.name, "d"); os.makedirs(os.path.join(dst, "modnet")); p = os.path.join(dst, "modnet", "modnet.onnx"); open(p, "wb").write(b"Z" * 3000)
        out = mp.restore_backup(self.pack, dst); self.assertEqual(out["skipped"], ["modnet/modnet.onnx"]); self.assertEqual(open(p, "rb").read(), b"Z" * 3000)
        out = mp.restore_backup(self.pack, dst, overwrite=True); self.assertEqual(out["restored"], ["modnet/modnet.onnx"]); self.assertEqual(open(p, "rb").read(), b"B" * 3000)
    def test_nothing_to_back_up(self):
        empty = os.path.join(self.td.name, "empty"); os.makedirs(empty)
        with self.assertRaises(mp.PackError): mp.create_backup(empty, self.pack)
        self.assertFalse(os.path.exists(self.pack))
    def test_cancel_during_backup_leaves_no_file(self):
        big = os.path.join(self.src, "gfpgan", "big.onnx"); open(big, "wb").write(os.urandom(6 << 20)); tm = TaskManager()
        t = tm.submit("b", lambda ctx: mp.create_backup(self.src, self.pack, ctx=ctx), on_progress=lambda t: t.cancel() if t.frac > 0.1 else None); self.assertEqual(tm.wait(t, 30), "cancelled")
        self.assertFalse(os.path.exists(self.pack)); self.assertFalse(os.path.exists(self.pack + ".part"))
    def test_progress_reaches_one(self):
        seen = []; tm = TaskManager(); t = tm.submit("b", lambda ctx: mp.create_backup(self.src, self.pack, ctx=ctx), on_progress=lambda t: seen.append(t.frac)); tm.wait(t, 30); self.assertEqual(t.state, "done"); self.assertAlmostEqual(seen[-1], 1.0); self.assertEqual(seen, sorted(seen))
    def test_disk_space_check(self):
        import shutil; mp.create_backup(self.src, self.pack); orig = shutil.disk_usage
        shutil.disk_usage = lambda p: type("U", (), dict(free=100, total=1000, used=900))()
        try:
            with self.assertRaises(mp.PackError) as c: mp.restore_backup(self.pack, os.path.join(self.td.name, "d"))
            self.assertIn("free disk space", str(c.exception))
        finally: shutil.disk_usage = orig

class TestHostilePacks(unittest.TestCase):
    def setUp(self): self.td = tempfile.TemporaryDirectory(); self.pack = os.path.join(self.td.name, "p.zip"); self.dst = os.path.join(self.td.name, "models"); self.outside = os.path.join(self.td.name, "evil.txt")
    def tearDown(self): self.td.cleanup()
    def test_path_traversal_and_absolute_paths_are_rejected_not_written(self):
        craft(self.pack, [("../evil.txt", b"x", None, "../evil.txt"), ("rembg/../../evil.txt", b"x", None, "x1"), ("/tmp/evil_abs", b"x", None, "x2"), ("C:/evil.onnx", b"x", None, "x3"), ("lama/ok.onnx", b"fine", None, None)])
        info = mp.inspect_backup(self.pack); self.assertEqual(len(info["problems"]), 4); self.assertEqual([e["path"] for e in info["files"]], ["lama/ok.onnx"])
        out = mp.restore_backup(self.pack, self.dst); self.assertEqual(out["restored"], ["lama/ok.onnx"]); self.assertFalse(os.path.exists(self.outside)); self.assertFalse(os.path.exists(os.path.join(self.td.name, "evil_abs")))
    def test_scripts_and_foreign_programs_are_refused(self):
        craft(self.pack, [("rembg/run.bat", b"calc", None, None), ("lama/x.ps1", b"calc", None, None), ("modnet/tool.exe", b"MZ", None, None), ("realesrgan-ncnn/realesrgan-ncnn-vulkan.exe", b"MZ ok", None, None), ("lama/m.onnx", b"m", None, None)])
        info = mp.inspect_backup(self.pack); self.assertEqual(len(info["problems"]), 3); out = mp.restore_backup(self.pack, self.dst); self.assertEqual(sorted(out["restored"]), ["lama/m.onnx", "realesrgan-ncnn/realesrgan-ncnn-vulkan.exe"])
        self.assertFalse(os.path.exists(os.path.join(self.dst, "rembg", "run.bat")))
    def test_files_not_in_manifest_are_never_extracted(self):
        craft(self.pack, [("lama/m.onnx", b"m", None, None)], extra={"lama/sneaky.bat": b"calc", "other/readme.txt": b"hi"}); out = mp.restore_backup(self.pack, self.dst); self.assertEqual(out["restored"], ["lama/m.onnx"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.dst, "lama"))), ["m.onnx"]); self.assertFalse(os.path.exists(os.path.join(self.dst, "other")))
    def test_tampered_content_fails_checksum_and_leaves_no_file(self):
        craft(self.pack, [("lama/m.onnx", b"tampered!", sha(b"original"), None), ("gfpgan/g.onnx", b"good", None, None)]); out = mp.restore_backup(self.pack, self.dst)
        self.assertEqual(out["restored"], ["gfpgan/g.onnx"]); self.assertEqual(out["failed"][0][0], "lama/m.onnx"); self.assertIn("checksum", out["failed"][0][1]); self.assertFalse(os.path.exists(os.path.join(self.dst, "lama", "m.onnx"))); self.assertFalse(os.path.exists(os.path.join(self.dst, "lama", "m.onnx.part")))
    def test_good_existing_file_survives_a_failed_overwrite(self):
        os.makedirs(os.path.join(self.dst, "lama")); keep = os.path.join(self.dst, "lama", "m.onnx"); open(keep, "wb").write(b"my good model"); craft(self.pack, [("lama/m.onnx", b"bad data", sha(b"other"), None)])
        out = mp.restore_backup(self.pack, self.dst, overwrite=True); self.assertEqual(len(out["failed"]), 1); self.assertEqual(open(keep, "rb").read(), b"my good model")
    def test_manifest_size_lie_is_caught(self):
        with zipfile.ZipFile(self.pack, "w") as z:
            z.writestr("lama/m.onnx", b"0123456789"); z.writestr("manifest.json", json.dumps(dict(format=mp.FORMAT, files=[dict(path="lama/m.onnx", size=4, sha256=sha(b"0123"))])))
        out = mp.restore_backup(self.pack, self.dst); self.assertEqual(len(out["failed"]), 1); self.assertFalse(os.path.exists(os.path.join(self.dst, "lama", "m.onnx")))
    def test_listed_but_missing_entry_is_a_problem(self):
        with zipfile.ZipFile(self.pack, "w") as z: z.writestr("manifest.json", json.dumps(dict(format=mp.FORMAT, files=[dict(path="lama/ghost.onnx", size=1, sha256=sha(b"x"))])))
        info = mp.inspect_backup(self.pack); self.assertEqual(info["files"], []); self.assertIn("missing", info["problems"][0])
        with self.assertRaises(mp.PackError): mp.restore_backup(self.pack, self.dst)
    def test_not_a_pack_at_all(self):
        open(self.pack, "wb").write(b"this is not a zip")
        with self.assertRaises(mp.PackError): mp.inspect_backup(self.pack)
        with zipfile.ZipFile(self.pack, "w") as z: z.writestr("hello.txt", "hi")
        with self.assertRaises(mp.PackError) as c: mp.inspect_backup(self.pack)
        self.assertIn("manifest", str(c.exception))
        craft(self.pack, [("lama/m.onnx", b"m", None, None)], fmt="something-else")
        with self.assertRaises(mp.PackError): mp.inspect_backup(self.pack)
    def test_garbage_manifest_entries(self):
        with zipfile.ZipFile(self.pack, "w") as z: z.writestr("manifest.json", json.dumps(dict(format=mp.FORMAT, files=[{"path": "lama/a.onnx"}, "junk", {"path": "lama/b.onnx", "size": "x", "sha256": "y"}, {"path": 5, "size": 1, "sha256": "a" * 64}])))
        info = mp.inspect_backup(self.pack); self.assertEqual(info["files"], []); self.assertEqual(len(info["problems"]), 4)

if __name__ == "__main__": unittest.main(verbosity=1)

"""AI capability registry. Honest by construction: every capability reports one of
     ready        - runs now
     needs_setup  - code is here but a package / model file is missing (message says exactly what)
     planned      - not wired into this application yet
and `classical` marks non-AI image processing, which is never presented as AI.
Nothing is uploaded anywhere: only local providers exist today; the cloud switch is off by default and needs an explicit user action.

Models folder layout (same as the earlier Ripon Computer app, so existing files are reused):
    <models>/rembg/<model>.onnx                          background removal (u2net_human_seg, isnet-general-use, birefnet-*, silueta, ...)
    <models>/realesrgan-ncnn/realesrgan-ncnn-vulkan.exe  + its models/ folder      (or <models>/realesrgan/...)"""
import os, subprocess, tempfile, time
import numpy as np
from PIL import Image
from .tasks import Cancelled

class AIUnavailable(Exception):
    def __init__(self, msg, hint=""): super().__init__(msg); self.hint = hint

def _has(mod):
    import importlib.util
    try: return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError): return False

BG_MODELS = [("modnet", "MODNet portrait matte (fast, small, no rembg needed)", "~26 MB"), ("u2net_human_seg", "Fast portrait (u2net human)", "~170 MB"), ("isnet-general-use", "Fast, sharp edges (ISNet)", "~170 MB"),
             ("birefnet-general-lite", "Good hair edges, lighter (BiRefNet lite)", "~200 MB"), ("birefnet-portrait", "Best hair (BiRefNet portrait)", "~970 MB"),
             ("silueta", "Tiny / very fast (Silueta)", "~43 MB"), ("u2net", "General (u2net)", "~170 MB"),
             ("bria-rmbg", "RMBG-2.0 (licence is NON-commercial - check before using in a shop)", "~1 GB")]
BG_KEYS = [k for k, _, _ in BG_MODELS]
DEFAULT_BG = "u2net_human_seg"
AUTO_PREFERENCE = ["birefnet-portrait", "birefnet-general-lite", "modnet", "u2net_human_seg", "isnet-general-use", "silueta", "u2net"]     # bria-rmbg is never picked automatically (non-commercial licence)
MODNET_URL = "https://huggingface.co/Xenova/modnet/resolve/main/onnx/model.onnx"
UPSCALE_DEFAULTS = ["realesrgan-x4plus", "realesrgan-x4plus-anime", "realesr-animevideov3"]
# models that can be fetched with an explicit click (same files / addresses the earlier Ripon Computer app used): key -> (label, path inside models folder, url, size)
DOWNLOADS = {
    "modnet": ("Portrait cut-out: MODNet", "modnet/modnet.onnx", "https://huggingface.co/Xenova/modnet/resolve/main/onnx/model.onnx", "~26 MB"),
    "lama": ("Object removal: LaMa big-lama", "lama/lama_fp32.onnx", "https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx", "~208 MB"),
    "codeformer": ("Face restore: CodeFormer", "codeformer/codeformer.onnx", "https://github.com/facefusion/facefusion-assets/releases/download/models/codeformer.onnx", "~375 MB"),
    "gfpgan": ("Face restore (fast): GFPGAN", "gfpgan/gfpgan_1.4.onnx", "https://github.com/facefusion/facefusion-assets/releases/download/models/gfpgan_1.4.onnx", "~340 MB"),
    "yunet": ("Face finder: YuNet (tiny)", "yunet/face_detection_yunet_2023mar.onnx", "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx", "~230 KB"),
}

class AIManager:
    def __init__(self, settings):
        self.settings = settings
        self._bg_sessions = {}; self._modnet_obj = None; self._onnx = {}

    # ------------------------------------------------------------ locations
    def models_dir(self): return self.settings.models_dir()
    def rembg_dir(self): return os.path.join(self.models_dir(), "rembg")
    def realesrgan_exe(self):
        for sub in ("realesrgan-ncnn", "realesrgan"):
            for n in ("realesrgan-ncnn-vulkan.exe", "realesrgan-ncnn-vulkan"):
                p = os.path.join(self.models_dir(), sub, n)
                if os.path.isfile(p): return p
        return ""
    def realesrgan_dir(self):
        e = self.realesrgan_exe(); return os.path.dirname(e) if e else os.path.join(self.models_dir(), "realesrgan-ncnn")
    def upscale_models(self):
        """Model names that really have weights next to the exe (a .bin file each)."""
        mdir = os.path.join(self.realesrgan_dir(), "models")
        try: return sorted({f[:-4] for f in os.listdir(mdir) if f.endswith(".bin")})
        except OSError: return []

    # ---- background-removal model files (rembg decides where it stores them, so search every plausible place)
    def _bg_search_dirs(self):
        dirs = [self.rembg_dir()]
        env = os.environ.get("U2NET_HOME")
        if env: dirs.append(os.path.expanduser(env))
        dirs.append(os.path.join(os.path.expanduser("~"), ".u2net"))
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg: dirs.append(os.path.join(os.path.expanduser(xdg), ".u2net"))
        seen, out = set(), []
        for d in dirs:
            k = os.path.normcase(os.path.abspath(d))
            if k not in seen: seen.add(k); out.append(d)
        return out
    def modnet_path(self): return os.path.join(self.models_dir(), "modnet", "modnet.onnx")
    def model_path(self, key): return os.path.join(self.models_dir(), *DOWNLOADS[key][1].split("/"))
    def has_model(self, key):
        p = self.model_path(key); return os.path.isfile(p) and os.path.getsize(p) > 1000 or (key == "yunet" and os.path.isfile(p))
    def yunet_path(self): return self.model_path("yunet") if self.has_model("yunet") else None
    def face_engines(self):
        """Installed face-restore engines, best first."""
        return [k for k in ("codeformer", "gfpgan") if self.has_model(k)]
    def _model(self, key):
        """Load an ONNX model once and keep it (two at most, so a big GPU model does not pile up)."""
        from .onnxutil import OnnxModel
        p = self.model_path(key)
        if p not in self._onnx:
            if len(self._onnx) >= 2: self._onnx.pop(next(iter(self._onnx)))
            self._onnx[p] = OnnxModel(p, bool(self.settings.get("prefer_gpu")))
        return self._onnx[p]
    def _bg_dir(self, key):
        if key == "modnet":
            p = self.modnet_path(); return os.path.dirname(p) if os.path.isfile(p) and os.path.getsize(p) > 1000 else ""
        for d in self._bg_search_dirs():
            if os.path.isfile(os.path.join(d, key + ".onnx")): return d
        return ""
    def _lib_ok(self, key): return _has("onnxruntime") if key == "modnet" else _has("rembg")
    def _ready(self, key): return bool(self._bg_dir(key)) and self._lib_ok(key)
    def stray_onnx(self):
        """.onnx files in the rembg folder that are not one of the models we know - shown to the user so a different file name is easy to spot."""
        try: return sorted(f for f in os.listdir(self.rembg_dir()) if f.lower().endswith(".onnx") and f[:-5] not in BG_KEYS)
        except OSError: return []
    def selected_bg(self):
        v = self.settings.get("bg_model"); return v if v in BG_KEYS else DEFAULT_BG
    def installed_bg(self): return [k for k in BG_KEYS if self._bg_dir(k)]
    def active_bg(self):
        """The selected engine if it can run, otherwise the best one that can (so a working model is never ignored)."""
        sel = self.selected_bg()
        if self._ready(sel): return sel
        for k in AUTO_PREFERENCE:
            if self._ready(k): return k
        return sel
    def bg_model_dir(self, key=None): return self._bg_dir(key or self.active_bg())
    def bg_model_file(self, key=None):
        key = key or self.active_bg(); return self.modnet_path() if key == "modnet" else os.path.join(self.rembg_dir(), key + ".onnx")

    # ------------------------------------------------------------ status
    def capabilities(self):
        C = []
        def add(key, label, status, detail, kind="local-ai"): C.append(dict(key=key, label=label, status=status, detail=detail, kind=kind))
        act = self.active_bg()
        if self._ready(act):
            note = "" if act == self.selected_bg() else f"  (selected '{self.selected_bg()}' cannot run - using this one)"
            bg = ("ready", (f"MODNet + onnxruntime  ({self.modnet_path()})" if act == "modnet" else f"rembg + {act}.onnx  ({self.bg_model_dir()})") + note)
        elif not self._lib_ok(act): bg = ("needs_setup", "Install the package:  " + ("pip install onnxruntime" if act == "modnet" else "pip install rembg"))
        else:
            stray = self.stray_onnx(); extra = f"  Other .onnx files found in the rembg folder (not recognised): {', '.join(stray)}." if stray else ""
            where = self.modnet_path() if act == "modnet" else self.rembg_dir()
            bg = ("needs_setup", f"Model file for '{act}' is missing. Use 'Prepare model' (one explicit download) or copy it into {where}.{extra}")
        add("bg_remove", "Background removal", *bg)
        add("bg_replace", "Background replacement", bg[0], "Uses the background-removal result; " + bg[1])
        exe = self.realesrgan_exe(); ms = self.upscale_models()
        if exe and ms: up = ("ready", f"{exe}  -  models: {', '.join(ms)}")
        elif exe: up = ("needs_setup", f"Found {exe} but no model files (*.bin) in {os.path.join(os.path.dirname(exe), 'models')}")
        else: up = ("needs_setup", f"Put realesrgan-ncnn-vulkan(.exe) and its models folder into {self.realesrgan_dir()}")
        add("upscale", "Image upscaling (Real-ESRGAN)", *up)
        add("enhance", "Auto enhance", "ready", "Classical auto-levels + sharpen - not AI", "classical")
        add("doc_enhance", "Document enhancement", "ready", "Classical shadow / whitening / text-contrast pipeline - not AI", "classical")
        ort = _has("onnxruntime")
        if not ort: add("object_remove", "Object removal (LaMa)", "needs_setup", "Install the package:  pip install onnxruntime")
        elif not self.has_model("lama"): add("object_remove", "Object removal (LaMa)", "needs_setup", f"Model missing: {self.model_path('lama')}  (AI Studio > Download models)")
        else: add("object_remove", "Object removal (LaMa)", "ready", self.model_path("lama"))
        eng = self.face_engines()
        if not ort: add("face_restore", "Face restoration (CodeFormer / GFPGAN)", "needs_setup", "Install the package:  pip install onnxruntime")
        elif not eng: add("face_restore", "Face restoration (CodeFormer / GFPGAN)", "needs_setup", f"Model missing: put codeformer.onnx in {os.path.dirname(self.model_path('codeformer'))} or gfpgan_1.4.onnx in {os.path.dirname(self.model_path('gfpgan'))}")
        else: add("face_restore", "Face restoration (CodeFormer / GFPGAN)", "ready", f"Engines: {', '.join(eng)}  -  face finder: {'YuNet' if self.has_model('yunet') else 'OpenCV Haar (one face)'}")
        for k, l, d in [("old_photo", "Old photo restoration", "Planned - not implemented yet"),
                        ("colorize", "Colorization", "Not implemented"), ("generate", "AI image generation", "Not implemented (needs a provider)"),
                        ("img2img", "AI image-to-image editing", "Not implemented (needs a provider)")]:
            add(k, l, "planned", d)
        return C
    def status(self, key): return next((c for c in self.capabilities() if c["key"] == key), None)

    # ------------------------------------------------------------ background removal
    def _download(self, url, dest, ctx=None):
        import urllib.request
        os.makedirs(os.path.dirname(dest), exist_ok=True); tmp = dest + ".part"
        req = urllib.request.Request(url, headers={"User-Agent": "RiponAIStudio/4"})
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as out:
            total = int(r.headers.get("Content-Length") or 0); got = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk: break
                out.write(chunk); got += len(chunk)
                if ctx: ctx.progress(0.9 * got / total if total else 0.5, f"Downloading {os.path.basename(dest)}")
        if os.path.getsize(tmp) < 1000: os.remove(tmp); raise AIUnavailable("The download is empty", "Check the internet connection / firewall.")
        os.replace(tmp, dest)

    def prepare_bg_model(self, ctx=None):
        """EXPLICIT user action: fetches the SELECTED engine's model. Never called automatically."""
        key = self.selected_bg()
        if key == "modnet":
            if not _has("onnxruntime"): raise AIUnavailable("onnxruntime is not installed", "pip install onnxruntime")
            self._download(MODNET_URL, self.modnet_path(), ctx); self._modnet_obj = None; return True
        if not _has("rembg"): raise AIUnavailable("rembg is not installed", "pip install rembg")
        os.makedirs(self.rembg_dir(), exist_ok=True); os.environ["U2NET_HOME"] = self.rembg_dir()
        if ctx: ctx.progress(0.1, f"Downloading background model '{key}' (one time)")
        from rembg import new_session
        sess = new_session(key); self._bg_sessions[key] = sess
        found = self._bg_dir(key)
        if not found:                                           # ask the loaded session where its file really is
            mp = getattr(getattr(sess, "inner_session", None), "_model_path", None)
            if mp and os.path.isfile(str(mp)):
                try:
                    import shutil; os.makedirs(self.rembg_dir(), exist_ok=True); shutil.copy2(str(mp), self.bg_model_file(key)); found = self._bg_dir(key)
                except OSError: pass
        if not found:
            try:
                import importlib.metadata as md; ver = md.version("rembg")
            except Exception: ver = "unknown"
            seen = []
            for d in self._bg_search_dirs():
                try: seen.append(f"{d}: {', '.join(sorted(os.listdir(d))[:8]) or '(empty)'}")
                except OSError: seen.append(f"{d}: (missing)")
            raise AIUnavailable("The background model was not found after the download", f"rembg {ver} loaded '{key}' from {getattr(getattr(sess, 'inner_session', None), '_model_path', 'an unknown place')}. Folders checked - " + " | ".join(seen) + f". You can also copy {key}.onnx into {self.rembg_dir()}")
        if os.path.normcase(os.path.abspath(found)) != os.path.normcase(os.path.abspath(self.rembg_dir())):      # rembg stored it elsewhere: keep a copy in OUR folder too
            try:
                import shutil; shutil.copy2(os.path.join(found, key + ".onnx"), self.bg_model_file(key))
            except OSError: pass
        return True

    def remove_background(self, rgb, ctx=None):
        """RGB/RGBA uint8 -> RGBA uint8 with a real alpha matte from the model. No edge blur / refinement is added."""
        st = self.status("bg_remove")
        if st["status"] != "ready": raise AIUnavailable("Background removal is not set up", st["detail"])
        key = self.active_bg()
        if key == "modnet":
            from .matting import MODNetMatter
            if ctx: ctx.progress(0.1, "Loading MODNet")
            if self._modnet_obj is None or self._modnet_obj.path != self.modnet_path(): self._modnet_obj = MODNetMatter(self.modnet_path(), bool(self.settings.get("prefer_gpu")))
            rgb3 = np.ascontiguousarray(np.asarray(rgb)[..., :3])
            if ctx: ctx.progress(0.4, "Cutting out the person")
            alpha = self._modnet_obj.matte(rgb3, 640)
            if ctx: ctx.progress(1.0, "Done")
            return np.dstack([rgb3, np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)])
        os.environ["U2NET_HOME"] = self.bg_model_dir(key)
        if ctx: ctx.progress(0.1, f"Loading model {key}")
        if key not in self._bg_sessions:
            from rembg import new_session
            self._bg_sessions[key] = new_session(key)
        from rembg import remove
        if ctx: ctx.progress(0.4, "Removing background")
        out = remove(Image.fromarray(np.ascontiguousarray(rgb[..., :3])), session=self._bg_sessions[key])
        if ctx: ctx.progress(1.0, "Done")
        return np.array(out.convert("RGBA"))

    @staticmethod
    def replace_background(rgba, bg_color=None, bg_image=None):
        """Composite the cut-out over a colour or an image (works on any RGBA with a real matte)."""
        h, w = rgba.shape[:2]
        if bg_image is not None: bg = Image.fromarray(bg_image).convert("RGBA").resize((w, h), Image.LANCZOS)
        else: bg = Image.new("RGBA", (w, h), tuple(bg_color or (255, 255, 255)) + (255,))
        bg.alpha_composite(Image.fromarray(rgba, "RGBA")); return np.array(bg)

    # ------------------------------------------------------------ upscaling
    def upscale(self, rgb, scale=2, model="realesrgan-x4plus", ctx=None):
        exe = self.realesrgan_exe()
        if not exe: raise AIUnavailable("Real-ESRGAN is not installed", f"Copy realesrgan-ncnn-vulkan and its 'models' folder into {self.realesrgan_dir()}")
        if scale not in (2, 3, 4): raise ValueError("scale must be 2, 3 or 4")
        mdir = os.path.join(os.path.dirname(exe), "models"); avail = self.upscale_models()
        if model not in avail:                                         # the old app did the same: fall back to x4plus, then to anything installed
            model = "realesrgan-x4plus" if "realesrgan-x4plus" in avail else (avail[0] if avail else "")
        if not model: raise AIUnavailable("No Real-ESRGAN model files found", f"Expected *.bin / *.param files in {mdir}")
        native = 4 if model.startswith("realesrgan-x4plus") else int(scale)       # the x4plus models exist at 4x only; the result is resized to the requested scale
        h0, w0 = rgb.shape[:2]
        if native == 4 and max(h0, w0) * 4 > 9000: raise AIUnavailable("This photo is too large for the 4x model", "Crop it first, or choose the fast realesr-animevideov3 model.")
        with tempfile.TemporaryDirectory() as td:
            src, dst = os.path.join(td, "in.png"), os.path.join(td, "out.png")
            Image.fromarray(np.ascontiguousarray(rgb[..., :3])).save(src, "PNG", compress_level=1)
            cmd = [exe, "-i", src, "-o", dst, "-n", model, "-s", str(native), "-f", "png", "-m", mdir]
            if not self.settings.get("prefer_gpu"): cmd += ["-g", "-1"]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags, cwd=os.path.dirname(exe))
            t0 = time.time()
            while p.poll() is None:
                if ctx and ctx.token.cancelled:
                    p.kill(); p.wait(); raise Cancelled()
                if ctx: ctx.progress(min(0.9, 0.05 + (time.time() - t0) / 120.0), f"Upscaling ({model})")
                time.sleep(0.1)
            log = (p.stdout.read() or b"").decode("utf-8", "replace")[-300:]
            if p.returncode != 0 or not os.path.isfile(dst): raise AIUnavailable("Real-ESRGAN failed", log.strip())
            im = Image.open(dst).convert("RGB")
            if native != scale: im = im.resize((w0 * scale, h0 * scale), Image.LANCZOS)
            return np.array(im)

    # ------------------------------------------------------------ downloads (explicit user action only)
    def download_model(self, key, ctx=None):
        if key not in DOWNLOADS: raise ValueError("unknown model")
        self._download(DOWNLOADS[key][2], self.model_path(key), ctx); self._onnx.pop(self.model_path(key), None); self._modnet_obj = None; return True

    # ------------------------------------------------------------ object removal / face restore
    def object_remove(self, rgb, mask, ctx=None, dilate=6, feather=3):
        """Remove the areas where mask > 127. Returns (rgb, number_of_areas)."""
        if not _has("onnxruntime"): raise AIUnavailable("onnxruntime is not installed", "pip install onnxruntime")
        if not self.has_model("lama"): raise AIUnavailable("The LaMa model is missing", f"Download it in AI Studio, or copy lama_fp32.onnx into {os.path.dirname(self.model_path('lama'))}")
        from . import restore
        if ctx: ctx.progress(0.02, "Loading LaMa")
        return restore.lama_inpaint(self._model("lama"), np.ascontiguousarray(rgb[..., :3]), mask, ctx, dilate=dilate, feather=feather)

    def restore_faces(self, rgb, engine="auto", fidelity=0.7, strength=1.0, color_fix=0.8, ctx=None):
        """-> (rgb, faces_restored, detector_name)."""
        if not _has("onnxruntime"): raise AIUnavailable("onnxruntime is not installed", "pip install onnxruntime")
        eng = self.face_engines()
        if not eng: raise AIUnavailable("No face-restore model found", f"Download CodeFormer or GFPGAN in AI Studio, or copy the .onnx file into {os.path.dirname(self.model_path('codeformer'))}")
        key = engine if engine in eng else eng[0]
        from . import restore
        rgb = np.ascontiguousarray(rgb[..., :3])
        if ctx: ctx.progress(0.02, "Finding faces")
        faces, used = restore.detect_faces(rgb, self.yunet_path())
        if not faces: raise restore.NoFace("No face found in this picture")
        if ctx: ctx.progress(0.1, f"Loading {key}")
        run = restore.make_face_runner(self._model(key), key, fidelity)
        out, n = restore.restore_faces(rgb, faces, run, strength, color_fix, ctx)
        return out, n, used

def auto_enhance(rgba):
    """Classical enhancement (named honestly): auto-levels then a gentle sharpen."""
    from . import adjust
    return adjust.sharpen(adjust.auto_levels(rgba, 0.4), 40, 1.2)

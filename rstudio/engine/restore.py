"""Object removal (LaMa) and face restoration (CodeFormer / GFPGAN), ported from the earlier Ripon Computer AI Studio.
All ONNX (onnxruntime) - no torch. Both work on small crops, so they are fast even on big photos."""
import math
import numpy as np, cv2
from .onnxutil import OnnxModel, dtype_of

FFHQ5 = np.array([[192.98138, 239.94708], [318.90277, 240.1936], [256.63416, 314.01935], [201.26117, 371.41043], [313.08905, 371.15118]], np.float32)

class NoFace(Exception): pass

# ------------------------------------------------------------------------------------------------ faces
def make_face(bbox, le, re_, nose, ml, mr, conf=1.0, src="", est=False):
    """Face description. Left/right as seen in the picture (le = eye on the left side of the image)."""
    if le[0] > re_[0]: le, re_ = re_, le
    if ml[0] > mr[0]: ml, mr = mr, ml
    f = lambda p: (float(p[0]), float(p[1]))
    return dict(bbox=tuple(float(v) for v in bbox), le=f(le), re=f(re_), nose=f(nose), ml=f(ml), mr=f(mr), conf=float(conf), src=src, est=est)

def _haar_face(rgb):
    """Haar box + eyes if two are found (else eye / mouth positions are estimated from the box)."""
    from . import passport
    out = []
    for (x, y, w, h) in passport.detect_faces(rgb)[:1]:
        le = re_ = None
        try:
            eye = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
            g = cv2.cvtColor(np.ascontiguousarray(rgb[y:y + int(h * 0.62), x:x + w]), cv2.COLOR_RGB2GRAY)
            eyes = eye.detectMultiScale(cv2.equalizeHist(g), 1.08, 4, minSize=(max(8, w // 10), max(8, w // 10)))
            cand = [(ex + ew / 2.0, ey + eh / 2.0, ew * eh) for ex, ey, ew, eh in eyes if ey + eh / 2.0 < h * 0.5]
            L = [c for c in cand if c[0] < w * 0.5]; R = [c for c in cand if c[0] >= w * 0.5]
            if L and R:
                a, b = max(L, key=lambda c: c[2]), max(R, key=lambda c: c[2])
                if abs(a[1] - b[1]) < w * 0.25: le, re_ = (x + a[0], y + a[1]), (x + b[0], y + b[1])
        except Exception: le = re_ = None
        est = le is None
        if est: le, re_ = (x + 0.30 * w, y + 0.40 * h), (x + 0.70 * w, y + 0.40 * h)
        out.append(make_face((x, y, w, h), le, re_, (x + 0.5 * w, y + 0.62 * h), (x + 0.35 * w, y + 0.78 * h), (x + 0.65 * w, y + 0.78 * h), 0.5, "haar", est))
    return out

def _yunet_faces(rgb, path):
    import os
    if not path or not os.path.isfile(path) or not hasattr(cv2, "FaceDetectorYN"): return None
    try:
        h, w = rgb.shape[:2]; d = cv2.FaceDetectorYN.create(path, "", (w, h), 0.6, 0.3, 50); d.setInputSize((w, h)); _, res = d.detect(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        out = []
        for r in (res if res is not None else []):
            x, y, bw, bh = [float(v) for v in r[:4]]
            out.append(make_face((x, y, bw, bh), (r[4], r[5]), (r[6], r[7]), (r[8], r[9]), (r[10], r[11]), (r[12], r[13]), r[14], "yunet"))
        return out
    except Exception: return None

def detect_faces(rgb, yunet_path=None, min_conf=0.5, max_faces=8):
    """Faces with landmarks, biggest first -> (faces, detector name). YuNet when its model exists, otherwise Haar (one face, landmarks partly estimated)."""
    rgb = np.ascontiguousarray(rgb[..., :3]); H, W = rgb.shape[:2]; s = min(1.0, 1600.0 / max(H, W))
    small = cv2.resize(rgb, (max(1, int(W * s)), max(1, int(H * s))), interpolation=cv2.INTER_AREA) if s < 1 else rgb
    faces = _yunet_faces(small, yunet_path); used = "YuNet"
    if not faces: faces = _haar_face(small); used = "OpenCV Haar (one face; eyes may be estimated)"
    faces = [f for f in faces if f["conf"] >= min_conf]; faces.sort(key=lambda f: -f["bbox"][2] * f["bbox"][3])
    if s < 1:
        k = 1.0 / s
        for f in faces:
            f["bbox"] = tuple(v * k for v in f["bbox"])
            for key in ("le", "re", "nose", "ml", "mr"): f[key] = (f[key][0] * k, f[key][1] * k)
    return faces[:max_faces], used

_MASK = None
def _face_mask512():
    global _MASK
    if _MASK is None:
        m = np.zeros((512, 512), np.float32); cv2.ellipse(m, (256, 262), (178, 214), 0, 0, 360, 1.0, -1); _MASK = cv2.GaussianBlur(m, (0, 0), 26)
    return _MASK

def _align_matrix(fi):
    src = np.array([fi["le"], fi["re"], fi["nose"], fi["ml"], fi["mr"]], np.float32)
    M, _ = cv2.estimateAffinePartial2D(src, FFHQ5, method=cv2.LMEDS); return M

def _match_mean(out, ref, mask, amount=0.8):
    """Move the colour average of the restored face back to the original face (restorers shift colour a little)."""
    if amount <= 0: return out
    a = cv2.cvtColor(out, cv2.COLOR_RGB2LAB).astype(np.float32); b = cv2.cvtColor(ref, cv2.COLOR_RGB2LAB).astype(np.float32); w = (mask > 0.5)
    if int(w.sum()) < 500: return out
    a += (b[w].mean(0) - a[w].mean(0)) * amount
    return cv2.cvtColor(np.clip(a, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)

def restore_faces(rgb, faces, run512, strength=1.0, color_fix=0.8, ctx=None):
    """run512(crop 512x512 RGB uint8) -> restored 512x512 RGB uint8. Each face is aligned, restored, then blended back through a soft oval mask."""
    out = rgb.copy(); H, W = rgb.shape[:2]; n = len(faces); mask512 = _face_mask512(); did = 0
    for i, fi in enumerate(faces):
        if ctx: ctx.progress(i / max(1, n), f"Restoring face {i + 1} / {n}")
        M = _align_matrix(fi)
        if M is None: continue
        Mi = cv2.invertAffineTransform(M); pts = np.array([[0, 0], [512, 0], [512, 512], [0, 512]], np.float32); q = pts @ Mi[:, :2].T + Mi[:, 2]
        x0, y0 = max(0, int(q[:, 0].min()) - 6), max(0, int(q[:, 1].min()) - 6); x1, y1 = min(W, int(q[:, 0].max()) + 7), min(H, int(q[:, 1].max()) + 7)
        if x1 - x0 < 16 or y1 - y0 < 16: continue
        roi = np.ascontiguousarray(rgb[y0:y1, x0:x1]); Mr = M.copy(); Mr[:, 2] += M[:, :2] @ np.array([x0, y0], np.float64); sc = float(math.hypot(Mr[0, 0], Mr[1, 0]))
        if sc < 0.7: roi = cv2.GaussianBlur(roi, (0, 0), max(0.3, 0.5 / sc))            # big face squeezed into 512: avoid aliasing
        crop = cv2.warpAffine(roi, Mr, (512, 512), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        fixed = run512(crop)
        if fixed.shape[:2] != (512, 512): fixed = cv2.resize(fixed, (512, 512), interpolation=cv2.INTER_CUBIC)
        fixed = _match_mean(fixed, crop, mask512, color_fix); Mir = cv2.invertAffineTransform(Mr); rw, rh = x1 - x0, y1 - y0
        back = cv2.warpAffine(fixed, Mir, (rw, rh), flags=cv2.INTER_LINEAR); m = cv2.warpAffine(mask512, Mir, (rw, rh), flags=cv2.INTER_LINEAR)[..., None] * float(np.clip(strength, 0, 1))
        cur = out[y0:y1, x0:x1].astype(np.float32); out[y0:y1, x0:x1] = np.clip(cur * (1 - m) + back.astype(np.float32) * m, 0, 255).astype(np.uint8); did += 1
    if did == 0: raise NoFace("Could not align any face for restoring")
    return out, did

def make_face_runner(model, kind, fidelity=0.7):
    """kind: 'codeformer' (fidelity: 0 = cleaner face ... 1 = more like the real face) or 'gfpgan'."""
    def feed(x, s):
        ins = s.get_inputs(); f = {ins[0].name: x.astype(dtype_of(ins[0]))}
        if len(ins) > 1 and kind == "codeformer":
            shp = getattr(ins[1], "shape", None); dt = dtype_of(ins[1])
            f[ins[1].name] = np.array(fidelity, dtype=dt) if (isinstance(shp, (list, tuple)) and len(shp) == 0) else np.array([fidelity], dtype=dt)
        return f
    def run(crop):
        x = ((crop.astype(np.float32) / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[None]
        o = model.run(lambda s: feed(x, s))[0]; o = np.clip(np.asarray(o, np.float32)[0].transpose(1, 2, 0), -1, 1)
        return ((o + 1.0) * 127.5).astype(np.uint8)
    return run

# ------------------------------------------------------------------------------------------------ object removal (LaMa)
def _lama512(model, img512, mask512):
    x = (img512.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]; m = (mask512 > 127).astype(np.float32)[None, None]
    def build(s):
        ins = s.get_inputs(); names = [i.name for i in ins]; ni = "image" if "image" in names else names[0]; nm = "mask" if "mask" in names else names[1]
        return {ni: x.astype(dtype_of(ins[names.index(ni)])), nm: m.astype(dtype_of(ins[names.index(nm)]))}
    o = np.asarray(model.run(build)[0], np.float32)[0].transpose(1, 2, 0)
    if float(o.max()) <= 1.5: o = o * 255.0                      # some exports return 0..1
    return np.clip(o, 0, 255).astype(np.uint8)

def _mask_groups(mb, max_groups=24):
    H, W = mb.shape; m8 = mb.astype(np.uint8); k = max(9, int(0.015 * max(H, W))); n = lab = st = None
    for _ in range(6):
        kk = int(k) | 1; closed = cv2.dilate(m8, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kk, kk))); n, lab, st, _c = cv2.connectedComponentsWithStats(closed, connectivity=8)
        if n - 1 <= max_groups: break
        k *= 2
    out = []
    for i in range(1, n):
        x, y, w, h = [int(v) for v in st[i, :4]]; ys, xs = np.where((lab[y:y + h, x:x + w] == i) & mb[y:y + h, x:x + w])
        if len(xs): out.append((x + int(xs.min()), y + int(ys.min()), x + int(xs.max()) + 1, y + int(ys.max()) + 1))
    return out

def _crop_box(bb, H, W, ctx_scale, min_side=320):
    x0, y0, x1, y1 = bb; bw, bh = x1 - x0, y1 - y0; side = min(max(max(bw, bh) * ctx_scale, min_side), max(H, W)); cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    if side <= min(H, W):
        s = int(round(side)); l = int(min(max(0, round(cx - s / 2.0)), W - s)); t = int(min(max(0, round(cy - s / 2.0)), H - s))
        if l <= x0 and t <= y0 and l + s >= x1 and t + s >= y1: return l, t, l + s, t + s
    mx, my = int(bw * (ctx_scale - 1) / 2.0) + 8, int(bh * (ctx_scale - 1) / 2.0) + 8
    return max(0, x0 - mx), max(0, y0 - my), min(W, x1 + mx), min(H, y1 + my)

def lama_inpaint(model, rgb, mask, ctx=None, ctx_scale=2.2, dilate=6, feather=3):
    """rgb HxWx3 uint8, mask HxW uint8 (>127 = remove). Returns (new_rgb, number_of_areas). Only the marked areas (plus a soft edge) change."""
    H, W = rgb.shape[:2]; mb = mask > 127
    if not mb.any(): return rgb, 0
    if dilate > 0: mb = cv2.dilate(mb.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(dilate) * 2 + 1,) * 2)) > 0
    groups = _mask_groups(mb); out = rgb.copy(); n = len(groups)
    for i, bb in enumerate(groups):
        if ctx: ctx.progress(i / max(1, n), f"Removing object {i + 1} / {n}")
        l, t, r, b = _crop_box(bb, H, W, ctx_scale); ci = np.ascontiguousarray(out[t:b, l:r]); cm = mb[t:b, l:r].astype(np.uint8) * 255; h0, w0 = ci.shape[:2]
        big = max(h0, w0) > 512
        i512 = cv2.resize(ci, (512, 512), interpolation=cv2.INTER_AREA if big else cv2.INTER_CUBIC); m512 = (cv2.resize(cm, (512, 512), interpolation=cv2.INTER_NEAREST) > 127).astype(np.uint8) * 255
        fill = cv2.resize(_lama512(model, i512, m512), (w0, h0), interpolation=cv2.INTER_AREA if big else cv2.INTER_CUBIC)
        a = cv2.GaussianBlur(cm.astype(np.float32) / 255.0, (0, 0), max(0.6, float(feather))); a = np.clip((a - 0.12) / 0.7, 0, 1)[..., None] * (cv2.dilate(cm, np.ones((3, 3), np.uint8)) > 0)[..., None]
        out[t:b, l:r] = np.clip(ci.astype(np.float32) * (1 - a) + fill.astype(np.float32) * a, 0, 255).astype(np.uint8)
    return out, n

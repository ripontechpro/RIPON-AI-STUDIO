"""Skin retouch (from the earlier Photostudio): smoothing that keeps texture, tone-up, shine fix and spot removal - always limited to skin and never over eyes, brows or mouth."""
import numpy as np, cv2

def _blur01(m, s): return np.clip(cv2.GaussianBlur(m.astype(np.float32), (0, 0), max(0.5, s)), 0, 1)

def skin_mask(rgb, faces=None):
    """Soft 0..1 mask of skin. With faces it is limited to the face and neck regions."""
    H, W = rgb.shape[:2]; ycc = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2YCrCb); y, cr, cb = ycc[..., 0], ycc[..., 1], ycc[..., 2]
    m = ((cr >= 133) & (cr <= 175) & (cb >= 75) & (cb <= 130) & (y >= 35) & (y <= 250)).astype(np.uint8)
    if faces:
        reg = np.zeros((H, W), np.uint8)
        for f in faces:
            x, y0, w, h = [int(v) for v in f["bbox"]]; cv2.ellipse(reg, (x + w // 2, y0 + int(h * 0.55)), (int(w * 0.75), int(h * 0.85)), 0, 0, 360, 1, -1); cv2.rectangle(reg, (x + int(w * 0.15), y0 + int(h * 0.9)), (x + int(w * 0.85), min(H - 1, y0 + int(h * 1.5))), 1, -1)
        m &= reg
    k = max(3, int(0.004 * max(H, W))) | 1; m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)); m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    return _blur01(m, max(1.5, 0.002 * max(H, W)))

def feature_guard(shape, faces):
    """1 where nothing may be smoothed: eyes, eyebrows and mouth of every face."""
    H, W = shape[:2]; g = np.zeros((H, W), np.uint8)
    for f in faces:
        w = f["bbox"][2]
        for key in ("le", "re"):
            cx, cy = int(f[key][0]), int(f[key][1]); cv2.ellipse(g, (cx, cy), (int(0.19 * w), int(0.10 * w)), 0, 0, 360, 1, -1); cv2.ellipse(g, (cx, cy - int(0.13 * w)), (int(0.21 * w), int(0.05 * w)), 0, 0, 360, 1, -1)
        mx, my = int((f["ml"][0] + f["mr"][0]) / 2), int((f["ml"][1] + f["mr"][1]) / 2); cv2.ellipse(g, (mx, my), (int(abs(f["mr"][0] - f["ml"][0]) / 2 + 0.06 * w), int(0.10 * w)), 0, 0, 360, 1, -1)
    return _blur01(g, max(1.5, 0.01 * W))

def skin_smooth(rgb, mask, strength=0.5, texture=0.35):
    H, W = rgb.shape[:2]; s = min(1.0, 1400.0 / max(H, W)); small = cv2.resize(rgb, (max(1, int(W * s)), max(1, int(H * s))), interpolation=cv2.INTER_AREA) if s < 1 else rgb
    sm = cv2.bilateralFilter(np.ascontiguousarray(small), 0, 22 + 38 * float(strength), max(3.0, 0.008 * max(small.shape[:2])) * 2.5)
    if s < 1: sm = cv2.resize(sm, (W, H), interpolation=cv2.INTER_CUBIC)
    f = rgb.astype(np.float32); hf = f - cv2.GaussianBlur(f, (0, 0), max(1.2, 0.003 * max(H, W))); base = sm.astype(np.float32) + hf * float(texture)
    a = (mask * float(np.clip(strength, 0, 1)))[..., None]; return np.clip(f * (1 - a) + base * a, 0, 255).astype(np.uint8)

def skin_tone_up(rgb, mask, amount=0.2):
    lab = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2LAB).astype(np.float32); a = mask * float(amount)
    lab[..., 0] = np.clip(lab[..., 0] + a * 28.0 * (1 - lab[..., 0] / 255.0), 0, 255); lab[..., 1] = np.clip(lab[..., 1] + a * 4.0, 0, 255); lab[..., 2] = np.clip(lab[..., 2] + a * 5.0, 0, 255)
    res = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB); return np.where((mask > 0)[..., None], res, rgb)        # pixels outside the mask are returned bit-for-bit (the LAB round trip alone would alter them)

def skin_shine_fix(rgb, mask, amount=0.5):
    hsv = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2HSV).astype(np.float32); v, s = hsv[..., 2] / 255.0, hsv[..., 1] / 255.0
    shine = _blur01(((v > 0.86) & (s < 0.28)).astype(np.float32), 2.0) * mask * float(amount); tone = cv2.GaussianBlur(rgb.astype(np.float32), (0, 0), max(6.0, 0.02 * max(rgb.shape[:2]))) * 0.92
    return np.clip(rgb.astype(np.float32) * (1 - shine[..., None]) + tone * shine[..., None], 0, 255).astype(np.uint8)

def find_blemishes(rgb, mask, guard=None, sens=0.5):
    """Small dark / red spots on skin -> list of (x, y, radius). Eyes, brows and mouth are never touched."""
    H, W = rgb.shape[:2]; lab = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2LAB).astype(np.float32); s = max(3.0, 0.004 * max(H, W))
    local = lab[..., 0] - cv2.GaussianBlur(lab[..., 0], (0, 0), s * 3); red = lab[..., 1] - cv2.GaussianBlur(lab[..., 1], (0, 0), s * 3); score = np.maximum(-local, red * 1.6)
    ok = (mask > 0.6) & (guard < 0.2 if guard is not None else True); thr = 26 - 16 * float(np.clip(sens, 0, 1)); cand = ((score > thr) & ok).astype(np.uint8); cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, lab_img, st, cen = cv2.connectedComponentsWithStats(cand, connectivity=8); out = []
    for i in range(1, n):
        a = st[i, cv2.CC_STAT_AREA]; w, h = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
        if 4 <= a <= 0.0025 * H * W and max(w, h) < 5 * min(w, h) + 2: out.append((float(cen[i][0]), float(cen[i][1]), float(max(2.0, max(w, h) / 2.0 + 1.5))))
    return out

def heal_spots(rgb, spots):
    if not spots: return rgb
    m = np.zeros(rgb.shape[:2], np.uint8)
    for x, y, r in spots: cv2.circle(m, (int(round(x)), int(round(y))), int(round(r)), 255, -1)
    return cv2.inpaint(np.ascontiguousarray(rgb), m, 3, cv2.INPAINT_TELEA)

def skin_retouch(rgb, faces, smooth=0.5, tone=0.2, shine=0.5, spots=True, sens=0.5):
    """-> (rgb, report). Order: spots -> shine -> smoothing -> tone."""
    img = np.ascontiguousarray(rgb[..., :3]); mask = skin_mask(img, faces); guard = feature_guard(img.shape, faces); eff = mask * (1 - guard); rep = dict(skin=float((mask > 0.5).mean()), spots=0)
    if spots:
        sp = find_blemishes(img, mask, guard, sens); rep["spots"] = len(sp); img = heal_spots(img, sp)
    if shine > 0: img = skin_shine_fix(img, eff, shine)
    if smooth > 0: img = skin_smooth(img, eff, smooth)
    if tone > 0: img = skin_tone_up(img, eff, tone)
    return img, rep

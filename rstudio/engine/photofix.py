"""Photo Doctor (from the earlier Photostudio): measure the picture, then fix only what is really wrong - colour cast, exposure, dark shadows, noise, softness, red eyes.
Classical image processing (no AI). A good picture is returned untouched."""
import numpy as np, cv2

def noise_sigma(gray):
    g = gray.astype(np.float32); d = g - cv2.GaussianBlur(g, (0, 0), 1.0); return float(1.4826 * np.median(np.abs(d - np.median(d))))

def neutral_gains(rgb, lo=40, hi=215):
    """Per-channel gains (R, G, B) that make the mid-tones neutral (gray-world on mid-tones only, limited to 0.75..1.33)."""
    f = rgb.astype(np.float32); lum = f.mean(-1); sat = (f.max(-1) - f.min(-1)) / np.maximum(1.0, f.max(-1)); m = (lum > lo) & (lum < hi) & (sat < 0.6)
    if int(m.sum()) < 200: return np.ones(3, np.float32)
    mean = f[m].mean(0); g = mean.mean() / np.maximum(mean, 1.0); return np.clip(g / g[1], 0.75, 1.33).astype(np.float32)

def analyze(rgb):
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY); p5, p50, p95 = np.percentile(g, [5, 50, 95]); gains = neutral_gains(rgb)
    return dict(mean=float(g.mean()), median=float(p50), p5=float(p5), p95=float(p95), noise=noise_sigma(g), sharp=float(cv2.Laplacian(g, cv2.CV_64F).var()), cast=float(np.abs(gains - 1).max()), gains=gains)

def auto_white_balance(rgb, strength=1.0):
    g = neutral_gains(rgb) ** float(np.clip(strength, 0, 1)); return np.clip(rgb.astype(np.float32) * g, 0, 255).astype(np.uint8)

def fix_exposure(rgb, target=122.0, strength=1.0):
    med = float(np.median(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)))
    if med < 8 or med > 247: return rgb
    gamma = float(np.clip(np.log(target / 255.0) / np.log(med / 255.0), 0.4, 1.8)) ** float(np.clip(strength, 0, 1)); lut = (255.0 * (np.arange(256) / 255.0) ** gamma).astype(np.uint8)
    return cv2.LUT(np.ascontiguousarray(rgb), lut)

def lift_shadows(rgb, amount=0.35):
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32); x = lab[..., 0] / 255.0; lab[..., 0] = np.clip((x + amount * 0.3 * np.exp(-((x - 0.12) ** 2) / (2 * 0.13 ** 2))) * 255.0, 0, 255)
    return cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB)

def denoise(rgb, strength=5.0):
    h = float(np.clip(strength, 0, 20)); return rgb if h <= 0.1 else cv2.fastNlMeansDenoisingColored(np.ascontiguousarray(rgb), None, h, h, 7, 21)

def sharpen(rgb, amount=0.5, radius=1.4):
    f = rgb.astype(np.float32); bl = cv2.GaussianBlur(f, (0, 0), max(0.3, radius)); return np.clip(f + (f - bl) * float(amount), 0, 255).astype(np.uint8)

def fix_red_eye(rgb, faces, strength=1.0):
    """Remove red from the pupils at the eye positions of each face. Returns (rgb, eyes_fixed)."""
    out = rgb.copy(); f = rgb.astype(np.float32); H, W = rgb.shape[:2]; n = 0
    for fc in faces:
        r = max(6, int(0.13 * fc["bbox"][2]))
        for key in ("le", "re"):
            cx, cy = int(fc[key][0]), int(fc[key][1]); x0, y0, x1, y1 = max(0, cx - r), max(0, cy - r), min(W, cx + r + 1), min(H, cy + r + 1)
            if x1 <= x0 or y1 <= y0: continue
            reg = f[y0:y1, x0:x1]; red = reg[..., 0] - np.maximum(reg[..., 1], reg[..., 2]); yy, xx = np.mgrid[y0:y1, x0:x1]; circ = ((xx - cx) ** 2 + (yy - cy) ** 2) <= r * r
            m = ((red > 0.45 * reg[..., 0]) & (reg[..., 0] > 90) & (reg[..., 0] > 1.7 * np.maximum(reg[..., 1], reg[..., 2]) + 15) & circ).astype(np.float32)
            m = m if float(m.sum()) >= 6 else m * 0
            if m.sum() < 4: continue
            m = cv2.GaussianBlur(m, (0, 0), 1.2) * float(np.clip(strength, 0, 1)); neutral = reg[..., 1:].mean(-1) * 0.85
            reg2 = reg.copy(); reg2[..., 0] = reg[..., 0] * (1 - m) + neutral * m; out[y0:y1, x0:x1] = np.clip(reg2, 0, 255).astype(np.uint8); n += 1
    return out, n

def suggest(m):
    """Which fixes the Photo Doctor would apply for these measurements (names only)."""
    s = []
    if m["cast"] > 0.04: s.append("colour cast")
    if m["median"] < 98 or m["median"] > 168: s.append("exposure")
    if m["p5"] < 22 and m["mean"] < 125: s.append("dark shadows")
    if m["noise"] > 3.5: s.append("noise")
    if m["sharp"] < 60: s.append("softness")
    return s

def photo_doctor(rgb, faces=None, strength=1.0):
    """-> (fixed rgb, report). report = dict(steps=[names], before=metrics, after=metrics). Only needed steps run."""
    img = np.ascontiguousarray(rgb[..., :3]); before = analyze(img); steps = []; k = float(np.clip(strength, 0, 1)); out = img
    if before["cast"] > 0.04: out = auto_white_balance(out, k); steps.append("colour cast")
    cur = analyze(out)
    if cur["median"] < 98 or cur["median"] > 168: out = fix_exposure(out, 122.0, k); steps.append("exposure")
    cur = analyze(out)
    if cur["p5"] < 22 and cur["mean"] < 125: out = lift_shadows(out, 0.35 * k); steps.append("dark shadows")
    if before["noise"] > 3.5: out = denoise(out, min(9.0, before["noise"] * 1.4) * k); steps.append("noise")
    if before["sharp"] < 60: out = sharpen(out, 0.55 * k); steps.append("softness")
    if faces:
        out, n = fix_red_eye(out, faces, k)
        if n: steps.append("red eyes")
    return out, dict(steps=steps, before=before, after=analyze(out))

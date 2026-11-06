"""Photo adjustments. Every function takes and returns an RGBA uint8 array (alpha is never touched), so they work on any layer.
`ADJUSTMENTS` describes each one (label + parameters) and the UI builds its controls from it - no per-tool UI code."""
import numpy as np, cv2

class Param:
    def __init__(self, key, label, lo, hi, default, step=1, kind="int", tip=""):
        self.key, self.label, self.lo, self.hi, self.default, self.step, self.kind, self.tip = key, label, lo, hi, default, step, kind, tip

class Adjustment:
    def __init__(self, key, label, params, fn, tip=""):
        self.key, self.label, self.params, self.fn, self.tip = key, label, params, fn, tip
    def defaults(self): return {p.key: p.default for p in self.params}
    def apply(self, rgba, **kw):
        args = self.defaults(); args.update({k: v for k, v in kw.items() if k in args}); return self.fn(rgba, **args)

def _split(a): return a[..., :3], a[..., 3:]
def _join(rgb, alpha): return np.concatenate([np.ascontiguousarray(rgb), alpha], -1)
def _lut(a, table):
    rgb, al = _split(a); return _join(cv2.LUT(np.ascontiguousarray(rgb), table.astype(np.uint8)), al)

def brightness_contrast(a, brightness=0, contrast=0):
    x = np.arange(256, dtype=np.float32); c = 1.0 + contrast / 100.0 if contrast <= 0 else 1.0 / max(1e-3, 1.0 - contrast / 100.0 * 0.99)
    return _lut(a, np.clip((x - 128) * c + 128 + brightness * 2.55, 0, 255) + 0.5)

def levels(a, black=0, white=255, gamma=1.0):
    black, white = int(black), max(int(white), int(black) + 1)
    x = np.clip((np.arange(256, dtype=np.float32) - black) / (white - black), 0, 1) ** (1.0 / max(0.05, gamma))
    return _lut(a, x * 255 + 0.5)

def _monotone_curve(pts):
    """Fritsch-Carlson monotone cubic through (x,y) points -> 256-entry table (no overshoot, so no halos)."""
    pts = sorted(pts); xs = np.array([p[0] for p in pts], np.float64); ys = np.array([p[1] for p in pts], np.float64)
    h = np.diff(xs); d = np.diff(ys) / h; m = np.empty_like(xs); m[0], m[-1] = d[0], d[-1]
    for i in range(1, len(xs) - 1): m[i] = 0.0 if d[i - 1] * d[i] <= 0 else (d[i - 1] + d[i]) / 2
    for i in range(len(d)):
        if d[i] == 0: m[i] = m[i + 1] = 0
        else:
            a, b = m[i] / d[i], m[i + 1] / d[i]; s = a * a + b * b
            if s > 9: t = 3 / np.sqrt(s); m[i], m[i + 1] = t * a * d[i], t * b * d[i]
    x = np.arange(256, dtype=np.float64); idx = np.clip(np.searchsorted(xs, x, side="right") - 1, 0, len(h) - 1)
    t = (x - xs[idx]) / h[idx]; h00 = 2 * t**3 - 3 * t**2 + 1; h10 = t**3 - 2 * t**2 + t; h01 = -2 * t**3 + 3 * t**2; h11 = t**3 - t**2
    return np.clip(h00 * ys[idx] + h10 * h[idx] * m[idx] + h01 * ys[idx + 1] + h11 * h[idx] * m[idx + 1], 0, 255)

def curves(a, shadows=0, midtones=0, highlights=0):
    pts = [(0, 0), (64, 64 + shadows * 0.6), (128, 128 + midtones * 0.6), (192, 192 + highlights * 0.6), (255, 255)]
    pts = [(x, float(np.clip(y, 0, 255))) for x, y in pts]
    return _lut(a, _monotone_curve(pts) + 0.5)

def exposure(a, ev=0.0):
    x = (np.arange(256, dtype=np.float32) / 255.0) ** 2.2 * (2.0 ** ev)
    return _lut(a, np.clip(x, 0, 1) ** (1 / 2.2) * 255 + 0.5)

def hue_saturation(a, hue=0, saturation=0, lightness=0):
    if not (hue or saturation or lightness): return a          # HSV round-trip is lossy; never touch pixels when nothing changes
    rgb, al = _split(a); hsv = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2HSV).astype(np.int32)
    hsv[..., 0] = (hsv[..., 0] + int(round(hue / 2.0))) % 180
    hsv[..., 1] = np.clip(hsv[..., 1] * (1 + saturation / 100.0), 0, 255)
    v = hsv[..., 2].astype(np.float32)
    v = v * (1 + lightness / 100.0) if lightness <= 0 else v + (255 - v) * (lightness / 100.0)
    hsv[..., 2] = np.clip(v, 0, 255)
    return _join(cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB), al)

def color_balance(a, cyan_red=0, magenta_green=0, yellow_blue=0):
    rgb, al = _split(a); f = rgb.astype(np.float32); lum = f.mean(-1, keepdims=True) / 255.0
    w = 4 * lum * (1 - lum)                                   # strongest in the midtones, fades to 0 in pure black / white
    shift = np.array([cyan_red, -magenta_green, -yellow_blue], np.float32) * 0.6
    return _join(np.clip(f + shift * w, 0, 255).astype(np.uint8), al)

def sharpen(a, amount=80, radius=1.5):
    rgb, al = _split(a); f = rgb.astype(np.float32); bl = cv2.GaussianBlur(f, (0, 0), max(0.1, radius)); k = amount / 100.0
    return _join(np.clip(f + (f - bl) * k, 0, 255).astype(np.uint8), al)

def blur(a, radius=3.0):
    if radius <= 0: return a
    rgb, al = _split(a); return _join(cv2.GaussianBlur(np.ascontiguousarray(rgb), (0, 0), radius), al)

def denoise(a, strength=6):
    rgb, al = _split(a); return _join(cv2.fastNlMeansDenoisingColored(np.ascontiguousarray(rgb), None, strength, strength, 7, 21), al)

def grayscale(a):
    rgb, al = _split(a); g = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2GRAY); return _join(np.stack([g, g, g], -1), al)

def auto_levels(a, clip=0.5):
    """Classical per-channel histogram stretch (NOT AI)."""
    rgb, al = _split(a); out = np.empty_like(rgb)
    for i in range(3):
        lo, hi = np.percentile(rgb[..., i], [clip, 100 - clip]); hi = max(hi, lo + 1)
        out[..., i] = np.clip((rgb[..., i].astype(np.float32) - lo) * 255.0 / (hi - lo), 0, 255)
    return _join(out, al)

def whiten_paper(a, strength=100, remove_shadow=True):
    from . import core
    rgb, al = _split(a); rgb = np.ascontiguousarray(rgb)
    if remove_shadow: rgb = core.remove_shadows(rgb, 0.8)
    return _join(core.whiten_background(rgb, strength / 100.0), al)

ADJUSTMENTS = {x.key: x for x in [
    Adjustment("brightness_contrast", "Brightness & Contrast", [Param("brightness", "Brightness", -100, 100, 0), Param("contrast", "Contrast", -100, 100, 0)], brightness_contrast),
    Adjustment("levels", "Levels", [Param("black", "Black point", 0, 254, 0), Param("white", "White point", 1, 255, 255), Param("gamma", "Midtones (gamma)", 0.2, 3.0, 1.0, 0.05, "float")], levels),
    Adjustment("curves", "Curves", [Param("shadows", "Shadows", -100, 100, 0), Param("midtones", "Midtones", -100, 100, 0), Param("highlights", "Highlights", -100, 100, 0)], curves),
    Adjustment("exposure", "Exposure", [Param("ev", "Exposure (EV)", -3.0, 3.0, 0.0, 0.1, "float")], exposure),
    Adjustment("hue_saturation", "Hue & Saturation", [Param("hue", "Hue", -180, 180, 0), Param("saturation", "Saturation", -100, 100, 0), Param("lightness", "Lightness", -100, 100, 0)], hue_saturation),
    Adjustment("color_balance", "Color Balance", [Param("cyan_red", "Cyan - Red", -100, 100, 0), Param("magenta_green", "Magenta - Green", -100, 100, 0), Param("yellow_blue", "Yellow - Blue", -100, 100, 0)], color_balance),
    Adjustment("sharpen", "Sharpen", [Param("amount", "Amount %", 0, 300, 80), Param("radius", "Radius", 0.5, 5.0, 1.5, 0.1, "float")], sharpen),
    Adjustment("blur", "Blur", [Param("radius", "Radius", 0.0, 30.0, 3.0, 0.5, "float")], blur),
    Adjustment("denoise", "Denoise", [Param("strength", "Strength", 1, 30, 6)], denoise, "Non-local-means denoise (classical, not AI). Can be slow on large images."),
    Adjustment("grayscale", "Grayscale", [], grayscale),
    Adjustment("auto_levels", "Auto Levels", [Param("clip", "Clip %", 0.0, 5.0, 0.5, 0.1, "float")], auto_levels, "Classical histogram stretch - not AI."),
    Adjustment("whiten_paper", "Background Whitening", [Param("strength", "Strength", 0, 100, 100)], whiten_paper, "Turns paper tone white and flattens uneven lighting."),
]}

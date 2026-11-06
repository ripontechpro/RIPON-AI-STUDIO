"""Painting engine: soft / hard brush stamps, eraser, clone stamp, paint bucket and gradients. Pure NumPy, no Qt.
A Stroke edits a private copy of a layer; the caller commits it as ONE history step when the mouse is released."""
import numpy as np, cv2
from . import select as sel_engine

def tip(size, hardness=1.0):
    """uint8 brush tip (size x size). hardness 1 = crisp edge, 0 = fully soft (like Photoshop's Hardness slider)."""
    d = max(1, int(round(size))); r = d / 2.0; yy, xx = np.mgrid[0:d, 0:d]; dist = np.hypot(xx + 0.5 - r, yy + 0.5 - r); h = float(np.clip(hardness, 0.0, 1.0))
    if h >= 0.995: a = np.clip(r + 0.5 - dist, 0, 1)
    else: inner = r * h; a = np.clip((r - dist) / max(1e-6, r - inner), 0, 1); a[dist <= inner] = 1.0
    return (a * 255.0 + 0.5).astype(np.uint8)

def _col(c): c = tuple(int(v) for v in c); return (c + (255,))[:4] if len(c) == 3 else c[:4]

class Stroke:
    """mode: 'paint' | 'erase' | 'clone'. All coordinates are in the LAYER's pixel grid.
    sel: layer-sized uint8 selection mask or None (painting only happens where selected). clone_offset=(dx, dy): copy from (x+dx, y+dy)."""
    def __init__(self, pixels, mode="paint", size=24, hardness=1.0, opacity=1.0, color=(0, 0, 0), bg=(255, 255, 255), erase_to_bg=False, sel=None, clone_offset=None, spacing=0.12):
        self.base = pixels; self.cur = np.array(pixels); self.H, self.W = self.cur.shape[:2]; self.mask = np.zeros((self.H, self.W), np.uint8)
        self.mode, self.size, self.opacity, self.spacing = mode, max(1, int(round(size))), float(np.clip(opacity, 0, 1)), max(0.02, float(spacing))
        self.color = np.array(_col(color)[:3], np.float32); self.bg = np.array(_col(bg)[:3], np.float32); self.erase_to_bg = bool(erase_to_bg); self.sel = sel; self.clone_offset = (int(round(clone_offset[0])), int(round(clone_offset[1]))) if clone_offset else None      # whole pixels only
        self.tip = tip(self.size, hardness); self.last = None; self.dirty = None
    def move_to(self, x, y):
        """Continue the stroke to (x, y). Returns the changed rectangle (x0, y0, x1, y1) in layer pixels, or None."""
        pts = [(x, y)]
        if self.last is not None:
            lx, ly = self.last; dist = float(np.hypot(x - lx, y - ly)); step = max(1.0, self.size * self.spacing); n = int(dist // step)
            pts = [(lx + (x - lx) * k * step / dist, ly + (y - ly) * k * step / dist) for k in range(1, n + 1)] + ([(x, y)] if dist - n * step > 0.01 or n == 0 else []) if dist > 0 else []
        rect = None
        for (px, py) in pts:
            r = self._stamp(px, py)
            if r is not None: rect = r if rect is None else (min(rect[0], r[0]), min(rect[1], r[1]), max(rect[2], r[2]), max(rect[3], r[3]))
        self.last = (x, y)
        if rect is not None: self._apply(rect); self.dirty = rect if self.dirty is None else (min(self.dirty[0], rect[0]), min(self.dirty[1], rect[1]), max(self.dirty[2], rect[2]), max(self.dirty[3], rect[3]))
        return rect
    def _stamp(self, cx, cy):
        d = self.tip.shape[0]; x0, y0 = int(round(cx - d / 2.0)), int(round(cy - d / 2.0)); gx0, gy0, gx1, gy1 = max(0, x0), max(0, y0), min(self.W, x0 + d), min(self.H, y0 + d)
        if gx1 <= gx0 or gy1 <= gy0: return None
        np.maximum(self.mask[gy0:gy1, gx0:gx1], self.tip[gy0 - y0:gy1 - y0, gx0 - x0:gx1 - x0], out=self.mask[gy0:gy1, gx0:gx1]); return (gx0, gy0, gx1, gy1)
    def _apply(self, rect):
        x0, y0, x1, y1 = rect; a = (self.mask[y0:y1, x0:x1].astype(np.float32) / 255.0) * self.opacity
        if self.sel is not None: a = a * (self.sel[y0:y1, x0:x1].astype(np.float32) / 255.0)
        a = a[..., None]; b = self.base[y0:y1, x0:x1].astype(np.float32); ba = b[..., 3:4] / 255.0
        if self.mode == "erase" and not self.erase_to_bg: oa = ba * (1 - a); rgb = b[..., :3]
        else:
            if self.mode == "clone":
                ox, oy = self.clone_offset or (0, 0); src = np.zeros_like(b); sx0, sy0, sx1, sy1 = x0 + ox, y0 + oy, x1 + ox, y1 + oy
                cx0, cy0, cx1, cy1 = max(0, sx0), max(0, sy0), min(self.W, sx1), min(self.H, sy1)
                if cx1 > cx0 and cy1 > cy0: src[cy0 - sy0:cy1 - sy0, cx0 - sx0:cx1 - sx0] = self.base[cy0:cy1, cx0:cx1].astype(np.float32)
                col = src[..., :3]; a = a * (src[..., 3:4] / 255.0)
            else: col = self.bg if self.mode == "erase" else self.color
            oa = a + ba * (1 - a); rgb = np.where(oa > 1e-6, (col * a + b[..., :3] * ba * (1 - a)) / np.maximum(oa, 1e-6), 0)
        self.cur[y0:y1, x0:x1, :3] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8); self.cur[y0:y1, x0:x1, 3:4] = np.clip(oa * 255.0 + 0.5, 0, 255).astype(np.uint8)
    def result(self): return self.cur

def blend_by_mask(pixels, color_or_rgba, mask, opacity=1.0):
    """Paint `color_or_rgba` (a colour, or an RGBA array the size of the layer) over `pixels` wherever mask > 0."""
    f = pixels.astype(np.float32); m = (mask.astype(np.float32) / 255.0 * float(opacity))[..., None]
    if isinstance(color_or_rgba, np.ndarray) and color_or_rgba.ndim == 3: src = color_or_rgba.astype(np.float32); sa = m * (src[..., 3:4] / 255.0); col = src[..., :3]
    else: col = np.array(_col(color_or_rgba)[:3], np.float32); sa = m * (_col(color_or_rgba)[3] / 255.0)
    ba = f[..., 3:4] / 255.0; oa = sa + ba * (1 - sa); rgb = np.where(oa > 1e-6, (col * sa + f[..., :3] * ba * (1 - sa)) / np.maximum(oa, 1e-6), 0)
    return np.clip(np.concatenate([rgb, oa * 255.0], -1) + 0.5, 0, 255).astype(np.uint8)

def bucket_fill(pixels, x, y, color, tolerance=32, contiguous=True, sel=None, opacity=1.0):
    """Paint bucket: fills the area of similar colour around (x, y). Returns the new pixels (or the same array when the click missed)."""
    rgba = np.asarray(pixels); h, w = rgba.shape[:2]; x, y = int(x), int(y)
    if not (0 <= x < w and 0 <= y < h): return pixels
    flat = rgba.copy(); a = flat[..., 3:4].astype(np.float32) / 255.0; flat[..., :3] = (flat[..., :3] * a + 255 * (1 - a)).astype(np.uint8)       # transparent areas count as white (like a flattened view)
    m = sel_engine.wand_mask(flat, x, y, tolerance, contiguous)
    if sel is not None: m = (m.astype(np.float32) * sel.astype(np.float32) / 255.0).astype(np.uint8)
    return blend_by_mask(rgba, color, m, opacity)

def gradient(h, w, p0, p1, c0, c1, radial=False):
    """RGBA gradient image (h, w, 4) from colour c0 at p0 to colour c1 at p1 (linear) or from the centre p0 out to radius |p1-p0| (radial)."""
    c0, c1 = np.array(_col(c0), np.float32), np.array(_col(c1), np.float32); yy, xx = np.mgrid[0:h, 0:w].astype(np.float32); dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    if radial: t = np.hypot(xx - p0[0], yy - p0[1]) / max(1e-6, np.hypot(dx, dy))
    else: L = dx * dx + dy * dy; t = ((xx - p0[0]) * dx + (yy - p0[1]) * dy) / L if L > 1e-9 else np.zeros_like(xx)
    t = np.clip(t, 0, 1)[..., None]; return np.clip(c0 * (1 - t) + c1 * t + 0.5, 0, 255).astype(np.uint8)

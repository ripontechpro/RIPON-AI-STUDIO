"""Output helpers from the earlier Photostudio: save under N kilobytes (online forms), caption bar, watermark."""
import io, os
import numpy as np
from PIL import Image
from .document import render_text

def _jpeg_bytes(im, q):
    b = io.BytesIO(); im.save(b, "JPEG", quality=int(q), optimize=True); return b.getvalue()

def save_under_kb(rgb, path, kb, min_quality=28, dpi=None):
    """Write a JPEG of at most `kb` kilobytes: the highest quality that fits; if even the lowest quality is too big the picture is shrunk in 10 % steps.
    Returns dict(bytes, quality, scale, size). Raises ValueError when the target cannot be reached."""
    target = int(kb * 1024); im0 = Image.fromarray(np.ascontiguousarray(rgb[..., :3])); scale = 1.0
    if target < 600: raise ValueError("The size limit is too small for a picture.")
    while scale >= 0.3:
        im = im0 if scale >= 0.999 else im0.resize((max(1, int(im0.width * scale)), max(1, int(im0.height * scale))), Image.LANCZOS)
        if len(_jpeg_bytes(im, min_quality)) <= target:
            lo, hi, best = min_quality, 95, min_quality
            while lo <= hi:
                mid = (lo + hi) // 2
                if len(_jpeg_bytes(im, mid)) <= target: best, lo = mid, mid + 1
                else: hi = mid - 1
            data = _jpeg_bytes(im, best); tmp = path + ".part"
            with open(tmp, "wb") as f: f.write(data)
            os.replace(tmp, path); return dict(bytes=len(data), quality=best, scale=scale, size=im.size)
        scale *= 0.9
    raise ValueError(f"Cannot reach {kb} KB even after shrinking the picture to 30%.")

def add_caption(rgb, text, bar_ratio=0.12, bg=(255, 255, 255), fg=(0, 0, 0)):
    """Adds a bar with text (name / date / ID number) under the picture. Bengali text works."""
    img = np.ascontiguousarray(rgb[..., :3]); H, W = img.shape[:2]; bar = max(24, int(H * bar_ratio)); canvas = np.zeros((H + bar, W, 3), np.uint8); canvas[:] = bg; canvas[:H] = img
    size = max(10, int(bar * 0.55)); t = render_text(dict(text=text or " ", size=size, color=list(fg) + [255]))
    while t.shape[1] > W - 8 and size > 8: size -= 2; t = render_text(dict(text=text, size=size, color=list(fg) + [255]))
    th, tw = t.shape[:2]; x0, y0 = max(0, (W - tw) // 2), H + max(0, (bar - th) // 2); x1, y1 = min(W, x0 + tw), min(H + bar, y0 + th); a = (t[:y1 - y0, :x1 - x0, 3:4].astype(np.float32) / 255.0)
    canvas[y0:y1, x0:x1] = np.clip(canvas[y0:y1, x0:x1] * (1 - a) + t[:y1 - y0, :x1 - x0, :3] * a, 0, 255).astype(np.uint8); return canvas

def watermark(rgba_or_rgb, text, opacity=0.25, angle=30.0, size_ratio=0.05, color=(255, 255, 255)):
    """RGBA overlay (same size) with the text repeated across the picture - used as its own layer, so it can be hidden or deleted later."""
    H, W = rgba_or_rgb.shape[:2]; size = max(10, int(min(H, W) * size_ratio)); t = render_text(dict(text=text or " ", size=size, color=list(color) + [255])); tile = Image.fromarray(t, "RGBA")
    big = max(H, W) * 2; layer = Image.new("RGBA", (big, big), (0, 0, 0, 0)); gx, gy = int(tile.width * 1.8), int(tile.height * 3.0)
    for row, yy in enumerate(range(0, big, gy)):
        off = (gx // 2) if row % 2 else 0
        for xx in range(0, big, gx):
            px = xx + off
            if px + tile.width < big and yy + tile.height < big: layer.alpha_composite(tile, (px, yy))
    layer = layer.rotate(angle, resample=Image.BICUBIC); l0 = (big - W) // 2; t0 = (big - H) // 2; out = np.array(layer.crop((l0, t0, l0 + W, t0 + H)))
    out[..., 3] = (out[..., 3].astype(np.float32) * float(np.clip(opacity, 0, 1))).astype(np.uint8); return out

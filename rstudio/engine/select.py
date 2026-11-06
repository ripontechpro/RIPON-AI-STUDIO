"""Pixel-mask selections (Photoshop-style). A mask is a uint8 array the size of the page: 0 = not selected, 255 = selected, values in between = feathered edge.
Pure NumPy / OpenCV, no Qt."""
import numpy as np, cv2

def rect_mask(h, w, x0, y0, x1, y1):
    m = np.zeros((h, w), np.uint8); x0, x1 = sorted((int(round(x0)), int(round(x1)))); y0, y1 = sorted((int(round(y0)), int(round(y1))))
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    if x1 > x0 and y1 > y0: m[y0:y1, x0:x1] = 255
    return m

def ellipse_mask(h, w, x0, y0, x1, y1):
    m = np.zeros((h, w), np.uint8); x0, x1 = sorted((float(x0), float(x1))); y0, y1 = sorted((float(y0), float(y1)))
    if x1 - x0 < 1 or y1 - y0 < 1: return m
    cv2.ellipse(m, (int(round((x0 + x1) / 2)), int(round((y0 + y1) / 2))), (max(1, int(round((x1 - x0) / 2))), max(1, int(round((y1 - y0) / 2)))), 0, 0, 360, 255, -1, cv2.LINE_AA); return m

def polygon_mask(h, w, pts):
    m = np.zeros((h, w), np.uint8)
    if len(pts) >= 3: cv2.fillPoly(m, [np.round(np.array(pts, np.float64)).astype(np.int32)], 255, cv2.LINE_AA)
    return m

def wand_mask(rgb, x, y, tol=32, contiguous=True):
    """Magic wand: pixels whose colour is within `tol` (0-255 per channel) of the clicked pixel; contiguous = only the connected area."""
    img = np.ascontiguousarray(np.asarray(rgb)[..., :3]); h, w = img.shape[:2]; x, y = int(x), int(y)
    if not (0 <= x < w and 0 <= y < h): return np.zeros((h, w), np.uint8)
    tol = int(max(0, min(255, tol)))
    if contiguous:
        mask = np.zeros((h + 2, w + 2), np.uint8); cv2.floodFill(img.copy(), mask, (x, y), 0, (tol,) * 3, (tol,) * 3, 4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE)
        return np.ascontiguousarray(mask[1:-1, 1:-1])
    seed = img[y, x].astype(np.int16); return ((np.abs(img.astype(np.int16) - seed).max(axis=2) <= tol).astype(np.uint8)) * 255

def combine(old, new, mode="new"):
    """mode: new | add | sub | inter (Photoshop: Shift = add, Alt = subtract, Shift+Alt = intersect)."""
    if mode == "new" or old is None: return new if mode in ("new", "add") else None
    if mode == "add": return np.maximum(old, new)
    if mode == "sub": return (old.astype(np.float32) * (1.0 - new.astype(np.float32) / 255.0)).astype(np.uint8)
    if mode == "inter": return np.minimum(old, new)
    raise ValueError("unknown mode")

def invert(m, h=None, w=None): return np.full((h, w), 255, np.uint8) if m is None else (255 - m).astype(np.uint8)

def feather(m, radius):
    return m if radius <= 0 else cv2.GaussianBlur(m, (0, 0), max(0.3, float(radius) / 2.0))

def grow(m, px):
    """px > 0 expands, px < 0 contracts the selection."""
    px = int(px)
    if px == 0: return m
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (abs(px) * 2 + 1,) * 2); return cv2.dilate(m, k) if px > 0 else cv2.erode(m, k)

def bbox(m, thresh=0):
    ys, xs = np.where(m > thresh)
    return None if len(xs) == 0 else (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)

def outline(m, thresh=127, max_side=1600):
    """Outline polylines [(N,2) float arrays, page pixels] for the marching ants."""
    h, w = m.shape; s = min(1.0, max_side / float(max(h, w))); b = (m > thresh).astype(np.uint8)
    if s < 1.0: b = cv2.resize(b, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_NEAREST)
    cs, _ = cv2.findContours(b, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    return [c.reshape(-1, 2).astype(np.float32) / s for c in cs if len(c) >= 2]

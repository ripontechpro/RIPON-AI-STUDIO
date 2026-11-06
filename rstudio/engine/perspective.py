"""Perspective crop: four corners picked on a skewed photo of a card / paper -> a flat, exact-size rectangle."""
import numpy as np, cv2
from . import core, cards

def default_quad(w, h, inset=0.1):
    """A rectangle inset from the image edges (TL, TR, BR, BL) to start dragging from."""
    x0, y0, x1, y1 = w * inset, h * inset, w * (1 - inset), h * (1 - inset)
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float32)

def detect_quad(rgb, min_frac=0.03):
    """Corners of the biggest card / sheet in the picture -> (quad TL,TR,BR,BL or None, confidence 0..1). Never guesses silently."""
    return core.detect_document_quad(np.ascontiguousarray(rgb[..., :3]), min_frac)

def quad_size(quad):
    q = core.order_quad(quad)
    return (float(max(np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[2] - q[3]))), float(max(np.linalg.norm(q[3] - q[0]), np.linalg.norm(q[2] - q[1]))))

def _warp(rgb, q, W, H):
    """Flatten the quad EXACTLY in the corner order given (core.warp_quad re-sorts the corners, which would undo a deliberate turn)."""
    M = cv2.getPerspectiveTransform(np.array(q, np.float32), np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], np.float32))
    return cv2.warpPerspective(rgb, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

def perspective_crop(rgb, quad, out_size=None, aspect=None, auto_orient=True, extra_rotation=0):
    """Flatten `quad`. out_size=(W, H) pixels exactly, or aspect=W/H (size from the quad's long side), else the quad's own size.
    auto_orient turns the result by 90 degrees when the card was photographed 'the other way' (portrait photo of a landscape card).
    extra_rotation (0/90/180/270 degrees clockwise) fixes an upside-down result."""
    q = core.order_quad(quad); w0, h0 = quad_size(q); rgb = np.ascontiguousarray(rgb[..., :3])
    if out_size is not None: W, H = int(out_size[0]), int(out_size[1])
    elif aspect: long_ = max(w0, h0); W, H = (int(round(long_)), int(round(long_ / aspect))) if aspect >= 1 else (int(round(long_ * aspect)), int(round(long_)))
    else: W, H = int(round(w0)), int(round(h0))
    W, H = max(8, W), max(8, H)
    if auto_orient and (w0 >= h0) != (W >= H): q = np.array([q[1], q[2], q[3], q[0]], np.float32)         # the quad is turned a quarter relative to the target
    out = _warp(rgb, q, W, H)
    k = (int(extra_rotation) // 90) % 4
    return np.ascontiguousarray(np.rot90(out, -k)) if k else out                                              # np.rot90 is counter-clockwise, so negative = clockwise

def card_from_photo(rgb, card_w_mm, card_h_mm, dpi=300, quad=None, min_frac=0.03, detect=True):
    """A photo of a card (or an already cropped scan) -> RGB of exactly card_w x card_h at `dpi`. Returns (rgb, info).
    info: dict(found=bool, confidence, method) with method in 'given', 'detected', 'already-cropped', 'centre-crop'."""
    rgb = np.ascontiguousarray(rgb[..., :3]); W, H = core.mm2px(card_w_mm, dpi), core.mm2px(card_h_mm, dpi); h, w = rgb.shape[:2]; ta = card_w_mm / card_h_mm
    if quad is not None: return perspective_crop(rgb, quad, (W, H)), dict(found=True, confidence=1.0, method="given")
    ia = w / float(h)
    if abs(ia / ta - 1) < 0.06 or abs(ia * ta - 1) < 0.06:                                                     # already a card-shaped picture (either way round)
        im = rgb if abs(ia / ta - 1) < 0.06 else np.ascontiguousarray(np.rot90(rgb)); return cv2.resize(im, (W, H), interpolation=cv2.INTER_AREA if im.shape[1] > W else cv2.INTER_CUBIC), dict(found=True, confidence=1.0, method="already-cropped")
    if detect:
        found = cards.detect_cards(rgb, ta, 1, min_conf=0.45)
        if found: return perspective_crop(rgb, found[0]["quad"], (W, H)), dict(found=True, confidence=found[0]["confidence"], method="detected")
        q, conf = detect_quad(rgb, min_frac)
        if q is not None and conf >= 0.5: return perspective_crop(rgb, q, (W, H)), dict(found=True, confidence=conf, method="detected")
    im = core.fit_image_to_box(__import__("PIL.Image", fromlist=["Image"]).fromarray(rgb), W, H, "cover")
    return np.array(im.convert("RGB")), dict(found=False, confidence=0.0, method="centre-crop")

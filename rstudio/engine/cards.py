"""Find ID cards / sheets of paper in a picture or scan WITHOUT any help: several independent detectors (difference from the background, colour saturation,
two edge detectors) each propose rectangles; every proposal is scored by how rectangular it is, how close its proportions are to the card (85.6 : 54 for an
ID-1 card) and how big it is. Overlaps are removed and the best ones come back in reading order (front = first, back = second when both are on one scan)."""
import numpy as np, cv2

ID1_ASPECT = 85.6 / 54.0

def order_quad(q):
    q = np.asarray(q, np.float32).reshape(4, 2); s = q.sum(1); d = np.diff(q, axis=1).ravel()
    return np.array([q[np.argmin(s)], q[np.argmin(d)], q[np.argmax(s)], q[np.argmax(d)]], np.float32)         # TL, TR, BR, BL

def quad_dims(q):
    q = order_quad(q); return (float(np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2, float(np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2)

def _poly_area(q): return float(abs(cv2.contourArea(np.asarray(q, np.float32).reshape(-1, 1, 2))))

def _masks(small):
    H, W = small.shape[:2]; gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY); lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB); hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV); out = []
    b = 6; border = np.concatenate([lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3), lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)]); bg = np.median(border, 0)
    diff = np.clip(np.linalg.norm(lab.astype(np.float32) - bg, axis=2) * 2.0, 0, 255).astype(np.uint8); t, _ = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    out.append(("background", diff > max(14, t))); out.append(("background-low", diff > max(8, t * 0.45)))
    s = hsv[..., 1]; ts, _ = cv2.threshold(s, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if ts >= 25: out.append(("colour", s > ts))
    blur = cv2.GaussianBlur(gray, (5, 5), 0); med = float(np.median(blur))
    for name, lo, hi in (("edges-auto", int(max(8, 0.66 * med)), int(min(255, 1.33 * med + 20))), ("edges-faint", 6, 20)):
        e = cv2.Canny(blur, lo, hi); e = cv2.dilate(e, np.ones((3, 3), np.uint8), iterations=2); out.append((name, e > 0))
    return out

def _candidates(small, aspect, tol):
    H, W = small.shape[:2]; k = max(5, W // 90) | 1; res = []
    for name, m in _masks(small):
        m8 = m.astype(np.uint8) * 255; m8 = cv2.morphologyEx(m8, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))); m8 = cv2.morphologyEx(m8, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        cs, _ = cv2.findContours(m8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cs:
            area = cv2.contourArea(c)
            if area < 0.012 * H * W or area > 0.93 * H * W: continue
            hull = cv2.convexHull(c); peri = cv2.arcLength(hull, True); ap = cv2.approxPolyDP(hull, 0.02 * peri, True); opts = []
            if len(ap) == 4: opts.append(order_quad(ap.reshape(4, 2)))
            opts.append(order_quad(cv2.boxPoints(cv2.minAreaRect(hull))))
            best = None
            for q in opts:
                w, h = quad_dims(q)
                if min(w, h) < 0.04 * min(H, W): continue
                fill = min(1.0, cv2.contourArea(hull) / max(_poly_area(q), 1.0)); asp = max(w, h) / max(1e-6, min(w, h))
                ascore = 1.0 if not aspect else max(0.0, 1.0 - abs(asp / max(aspect, 1.0 / aspect) - 1.0) / tol)
                edge = 0.92 if (q[:, 0].min() < 2 or q[:, 1].min() < 2 or q[:, 0].max() > W - 3 or q[:, 1].max() > H - 3) else 1.0
                sc = (fill ** 3) * ascore * edge
                if best is None or sc > best[0]: best = (sc, q, _poly_area(q) / float(H * W))
            if best and best[0] > 0.3: res.append(dict(score=best[0], quad=best[1], area=best[2], method=name))
    return res

def _bbox_overlap(a, b):
    ax0, ay0, ax1, ay1 = a[:, 0].min(), a[:, 1].min(), a[:, 0].max(), a[:, 1].max(); bx0, by0, bx1, by1 = b[:, 0].min(), b[:, 1].min(), b[:, 0].max(), b[:, 1].max()
    iw, ih = max(0.0, min(ax1, bx1) - max(ax0, bx0)), max(0.0, min(ay1, by1) - max(ay0, by0)); return iw * ih / max(1.0, min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0)))

def detect_cards(rgb, aspect=ID1_ASPECT, max_cards=2, tol=0.25, min_conf=0.35, max_side=1100):
    """-> list of dict(quad=4x2 float32 TL,TR,BR,BL in the ORIGINAL picture, confidence 0..1, method) in reading order. aspect=None finds any rectangle (sheets of paper)."""
    img = np.ascontiguousarray(np.asarray(rgb)[..., :3]); H, W = img.shape[:2]; s = min(1.0, max_side / float(max(H, W)))
    small = cv2.resize(img, (max(1, int(W * s)), max(1, int(H * s))), interpolation=cv2.INTER_AREA) if s < 1 else img
    cands = _candidates(small, aspect, tol); cands.sort(key=lambda c: -(c["score"] * (c["area"] ** 0.25))); chosen = []
    for c in cands:
        if all(_bbox_overlap(c["quad"], o["quad"]) < 0.5 for o in chosen): chosen.append(c)
        if len(chosen) >= max(1, int(max_cards)): break
    out = [dict(quad=(c["quad"] / s).astype(np.float32), confidence=float(min(1.0, c["score"])), method=c["method"]) for c in chosen if c["score"] >= min_conf]
    if len(out) > 1:
        cy = [float(o["quad"][:, 1].mean()) for o in out]; cx = [float(o["quad"][:, 0].mean()) for o in out]; hh = max(quad_dims(o["quad"])[1] for o in out)
        vertical = (max(cy) - min(cy)) > 0.6 * hh; out.sort(key=lambda o: o["quad"][:, 1].mean() if vertical else o["quad"][:, 0].mean())
    return out

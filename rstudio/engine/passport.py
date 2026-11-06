"""Passport & ID / print-sheet building. Geometry comes from core.passport_sheet (mm, exact print size); the result is a normal
shared Document (one movable layer per photo), so Layout Studio, undo/redo and export all work on it with no special code."""
import numpy as np
from PIL import Image
from . import core
from .document import Document, Layer, to_rgba

# Sizes only - the issuing authority's rules (background colour, head size, ...) are the operator's responsibility.
PRESETS = [("35 x 45 mm", 35.0, 45.0), ("40 x 50 mm", 40.0, 50.0), ("45 x 55 mm", 45.0, 55.0),
           ("2 x 2 inch (50.8 x 50.8 mm)", 50.8, 50.8), ("25 x 35 mm", 25.0, 35.0), ("Custom", 0.0, 0.0)]

def sheet_info(w_mm, h_mm, copies, paper="A4", orientation="Portrait", margin=5.0, gap=2.0, allow_rotate=True, custom_mm=None):
    pw, ph = core.page_size_mm(paper, orientation, custom_mm)
    r = core.passport_sheet(w_mm, h_mm, pw, ph, copies, gap, margin, allow_rotate)
    return dict(page_mm=(pw, ph), capacity=r["capacity"], fits=r["fits"], pages=len(r["pages"]), layout=r)

def make_sheet_documents(photo, w_mm, h_mm, copies, paper="A4", orientation="Portrait", margin=5.0, gap=2.0, dpi=300,
                         allow_rotate=True, border_mm=0.0, cut_marks=False, custom_mm=None, name="Passport sheet"):
    """photo: PIL image / ndarray. Returns (list[Document], info). Each photo copy is its own layer, already cropped to exact size."""
    if w_mm <= 0 or h_mm <= 0 or copies < 1: raise ValueError("photo size and copies must be positive")
    info = sheet_info(w_mm, h_mm, copies, paper, orientation, margin, gap, allow_rotate, custom_mm)
    if not info["fits"]: raise ValueError("This photo size does not fit on the page with these margins")
    pil = photo if isinstance(photo, Image.Image) else Image.fromarray(np.asarray(photo)[..., :3])
    pw, ph = info["page_mm"]; W, H = core.mm2px(pw, dpi), core.mm2px(ph, dpi); docs = []
    for n, rects in enumerate(info["layout"]["pages"], 1):
        d = Document.new(W, H, dpi, name=f"{name} {n}" if len(info["layout"]["pages"]) > 1 else name)
        for i, (x, y, w, h) in enumerate(rects, 1):
            rot = abs(w - w_mm) > 0.01 and abs(h - h_mm) > 0.01          # cell was turned 90 degrees to fit more
            tile = core.fit_image_to_box(pil.rotate(90, expand=True) if rot else pil, core.mm2px(w, dpi), core.mm2px(h, dpi), "cover")
            L = Layer(to_rgba(tile), f"Photo {i}", x=core.mm2px(x, dpi), y=core.mm2px(y, dpi)); d.layers.append(L)
        d.active_id = d.layers[-1].id; d.commit("Build sheet", reset=True)
        if border_mm > 0 or cut_marks: _decorate(d, rects, dpi, border_mm, cut_marks)
        docs.append(d)
    return docs, info

def _decorate(doc, rects, dpi, border_mm, cut_marks):
    from .document import render_shape
    ov = np.zeros((doc.h, doc.w, 4), np.uint8)
    for x, y, w, h in rects:
        x0, y0, x1, y1 = core.mm2px(x, dpi), core.mm2px(y, dpi), core.mm2px(x + w, dpi), core.mm2px(y + h, dpi)
        if border_mm > 0:
            t = max(1, core.mm2px(border_mm, dpi))
            ov[y0:y0 + t, x0:x1] = ov[y1 - t:y1, x0:x1] = ov[y0:y1, x0:x0 + t] = ov[y0:y1, x1 - t:x1] = (0, 0, 0, 255)
        if cut_marks:
            m = core.mm2px(2, dpi)
            for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                ov[max(0, cy):cy + 1, max(0, cx - m):cx + m] = (120, 120, 120, 255); ov[max(0, cy - m):cy + m, max(0, cx):cx + 1] = (120, 120, 120, 255)
    doc.add_layer(Layer(to_rgba(ov), "Borders & cut marks"), label="Borders & marks")

def blank_page_document(paper="A4", orientation="Portrait", dpi=300, custom_mm=None, name="Layout"):
    pw, ph = core.page_size_mm(paper, orientation, custom_mm)
    return Document.new(core.mm2px(pw, dpi), core.mm2px(ph, dpi), dpi, name=name)

def mm_to_px(mm, dpi): return core.mm2px(mm, dpi)
def px_to_mm(px, dpi): return core.px2mm(px, dpi)


# ---------------------------------------------------------------------------------------------- shared helpers
def _page_doc(pw, ph, dpi, name): return Document.new(core.mm2px(pw, dpi), core.mm2px(ph, dpi), dpi, name=name)

def _as_pil(img):
    if isinstance(img, Image.Image): return img.convert("RGB")
    return Image.fromarray(np.asarray(img)[..., :3])

def _place(doc, pil, rect, dpi, rot, name):
    """Cover-fit `pil` into rect (mm) - turned 90 deg first when the layout rotated the cell - and add it as a layer."""
    x, y, w, h = rect; tile = core.fit_image_to_box(pil.rotate(90, expand=True) if rot else pil, core.mm2px(w, dpi), core.mm2px(h, dpi), "cover")
    doc.layers.append(Layer(to_rgba(tile), name, x=core.mm2px(x, dpi), y=core.mm2px(y, dpi)))

def _finish(doc, rects, dpi, border_mm, cut_marks):
    doc.active_id = doc.layers[-1].id; doc.commit("Build sheet", reset=True)
    if border_mm > 0 or cut_marks: _decorate(doc, rects, dpi, border_mm, cut_marks)

# ---------------------------------------------------------------------------------------------- Bank Photo Duet
DUET_DEFAULT_MM = (1.9 * 25.4, 1.5 * 25.4)          # whole duet 1.9 x 1.5 inch (photo + photo)

def duet_info(duet_w_mm, duet_h_mm, paper="A4", orientation="Portrait", margin=5.0, gap=2.0, between=0.0, arrangement="side", allow_rotate=False, custom_mm=None):
    pw, ph = core.page_size_mm(paper, orientation, custom_mm)
    lay = core.duet_layout_total(duet_w_mm, duet_h_mm, pw, ph, gap, margin, between, None, arrangement, allow_rotate)
    return dict(page_mm=(pw, ph), capacity=lay["capacity"], photo_mm=lay["photo"], arrangement=lay["arrangement"])

def make_duet_documents(photo_a, photo_b=None, duet_w_mm=DUET_DEFAULT_MM[0], duet_h_mm=DUET_DEFAULT_MM[1], duets=None, paper="A4", orientation="Portrait",
                        margin=5.0, gap=2.0, between=0.0, arrangement="side", allow_rotate=False, dpi=300, border_mm=0.0, cut_marks=False, custom_mm=None, name="Bank photo duet"):
    """Two photos per duet (photo_b defaults to photo_a), as many duets as asked (default: fill one page). Returns (list[Document], info)."""
    info = duet_info(duet_w_mm, duet_h_mm, paper, orientation, margin, gap, between, arrangement, allow_rotate, custom_mm)
    cap = info["capacity"]
    if cap < 1: raise ValueError("This duet size does not fit on the page with these margins")
    total = int(duets) if duets else cap
    if total < 1: raise ValueError("duets must be at least 1")
    a = _as_pil(photo_a); b = _as_pil(photo_b) if photo_b is not None else a; pw, ph = info["page_mm"]; docs, left, n = [], total, 1
    while left > 0:
        k = min(cap, left); lay = core.duet_layout_total(duet_w_mm, duet_h_mm, pw, ph, gap, margin, between, k, arrangement, allow_rotate); d = _page_doc(pw, ph, dpi, name + (f" {n}" if total > cap else "")); rects = []
        for i, (ra, rb) in enumerate(lay["duets"], 1):
            _place(d, a, ra, dpi, lay["rot"], f"Duet {i} - A"); _place(d, b, rb, dpi, lay["rot"], f"Duet {i} - B"); rects += [ra, rb]
        _finish(d, rects, dpi, border_mm, cut_marks); docs.append(d); left -= k; n += 1
    info["pages"] = len(docs); info["duets"] = total; return docs, info

# ---------------------------------------------------------------------------------------------- ID card front + back
ID1_MM = (85.6, 54.0)                                 # ISO/IEC 7810 ID-1 (bank-card size)

def card_info(card_w_mm=ID1_MM[0], card_h_mm=ID1_MM[1], paper="A4", orientation="Portrait", margin=15.0, gap=10.0, card_gap=8.0, arrangement="stack", allow_rotate=False, custom_mm=None):
    pw, ph = core.page_size_mm(paper, orientation, custom_mm)
    lay = core.id_card_layout(card_w_mm, card_h_mm, pw, ph, gap, margin, arrangement, 1000, card_gap, allow_rotate)
    return dict(page_mm=(pw, ph), capacity=lay["capacity"])

def make_id_card_documents(front, back, card_w_mm=ID1_MM[0], card_h_mm=ID1_MM[1], pairs=1, paper="A4", orientation="Portrait", margin=15.0, gap=10.0, card_gap=8.0,
                           arrangement="stack", allow_rotate=False, dpi=300, border_mm=0.2, cut_marks=False, custom_mm=None, name="ID card"):
    """Front and back of a card printed together at exact size. Returns (list[Document], info)."""
    info = card_info(card_w_mm, card_h_mm, paper, orientation, margin, gap, card_gap, arrangement, allow_rotate, custom_mm); cap = info["capacity"]
    if cap < 1: raise ValueError("This card size does not fit on the page with these margins")
    total = max(1, int(pairs)); f, bk = _as_pil(front), _as_pil(back); pw, ph = info["page_mm"]; docs, left, n = [], total, 1
    while left > 0:
        k = min(cap, left); lay = core.id_card_layout(card_w_mm, card_h_mm, pw, ph, gap, margin, arrangement, k, card_gap, allow_rotate); d = _page_doc(pw, ph, dpi, name + (f" {n}" if total > cap else "")); rects = []
        for i, (rf, rb) in enumerate(lay["pairs"], 1):
            _place(d, f, rf, dpi, lay["rot"], f"Card {i} - front"); _place(d, bk, rb, dpi, lay["rot"], f"Card {i} - back"); rects += [rf, rb]
        _finish(d, rects, dpi, border_mm, cut_marks); docs.append(d); left -= k; n += 1
    info["pages"] = len(docs); info["pairs"] = total; return docs, info

# ---------------------------------------------------------------------------------------------- face-aware crop (suggestion only: the user can still move it)
def _yunet_faces(rgb, path):
    """OpenCV YuNet (small ONNX model, commercial-friendly). Returns boxes in full-image pixels, or None when unavailable / failed."""
    import cv2, os
    if not path or not os.path.isfile(path) or not hasattr(cv2, "FaceDetectorYN"): return None
    try:
        img = cv2.cvtColor(np.ascontiguousarray(np.asarray(rgb)[..., :3]), cv2.COLOR_RGB2BGR); H, W = img.shape[:2]; k = min(1.0, 1280.0 / max(H, W))
        small = cv2.resize(img, (max(1, int(W * k)), max(1, int(H * k)))) if k < 1 else img
        det = cv2.FaceDetectorYN.create(path, "", (small.shape[1], small.shape[0]), 0.7, 0.3, 5000); _, faces = det.detect(small)
        if faces is None: return []
        return sorted([tuple(int(round(v / k)) for v in f[:4]) for f in faces if f[2] > 8 and f[3] > 8], key=lambda f: -f[2] * f[3])
    except Exception:
        return None

def detect_faces(rgb, min_frac=0.08, yunet_path=None):
    """Face boxes (x, y, w, h), largest first. Uses the YuNet model when its file is given and present, otherwise OpenCV's built-in Haar cascade.
    Works for roughly frontal faces; returns [] when nothing is found."""
    import cv2, os
    yn = _yunet_faces(rgb, yunet_path)
    if yn: return yn
    g = cv2.cvtColor(np.ascontiguousarray(np.asarray(rgb)[..., :3]), cv2.COLOR_RGB2GRAY); g = cv2.equalizeHist(g); m = int(min(g.shape) * min_frac)
    for fn in ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml"):
        path = os.path.join(cv2.data.haarcascades, fn)
        if not os.path.isfile(path): continue
        found = cv2.CascadeClassifier(path).detectMultiScale(g, 1.1, 5, minSize=(max(24, m), max(24, m)))
        if len(found): return sorted([tuple(int(v) for v in f) for f in found], key=lambda f: -f[2] * f[3])
    return []

def face_crop_rect(img_w, img_h, face, aspect, head_ratio=0.5, eye_line=0.47):
    """Crop rectangle (x0, y0, x1, y1, clamped) with the given aspect (w/h) around `face`: the face box is `head_ratio` of the crop height and its
    centre sits `eye_line` of the way down. If the picture is too small for that, the crop is shrunk (clamped=True) so it never leaves the image."""
    fx, fy, fw, fh = face; ch = fh / float(head_ratio); cw = ch * aspect; clamped = False
    if cw > img_w or ch > img_h: k = min(img_w / cw, img_h / ch); cw, ch, clamped = cw * k, ch * k, True
    x0 = fx + fw / 2.0 - cw / 2.0; y0 = fy + fh / 2.0 - eye_line * ch
    x0 = min(max(0.0, x0), img_w - cw); y0 = min(max(0.0, y0), img_h - ch)
    return int(round(x0)), int(round(y0)), int(round(x0 + cw)), int(round(y0 + ch)), clamped

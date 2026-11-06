"""Document Studio: scan cleanup, deskew, border crop, batch + PDF. Built on the tested algorithms in rstudio.engine.core (no AI is claimed:
everything here is classical image processing and never invents text)."""
import os, numpy as np, cv2
from PIL import Image
from . import core

class Unavailable(Exception):
    """A feature needs an optional package / file that is not installed."""

class CleanOptions:
    def __init__(self, **kw):
        self.mode = "color"                 # color | gray | bw
        self.intensity = 70                 # 0..100
        self.shadow_removal = True; self.whiten = True; self.denoise = True; self.faint_text = True; self.sharpen = 40
        self.preserve_black_text = True     # dark ink is never allowed to become lighter than the scan
        self.preserve_marks = True          # coloured signatures / stamps stay coloured even in gray / bw mode
        self.deskew = True; self.auto_crop = True; self.crop_margin_px = 12
        self.__dict__.update(kw)
    def restore_options(self):
        return core.RestoreOptions(mode="color", intensity=self.intensity, shadow_removal=self.shadow_removal, whiten=self.whiten,
                                   denoise=self.denoise, faint_text=self.faint_text, sharpen=self.sharpen)

def _marks_mask(rgb):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    m = ((hsv[..., 1] > 70) & (hsv[..., 2] < 235)).astype(np.uint8)
    return cv2.dilate(m, np.ones((3, 3), np.uint8)) > 0

def content_bbox(rgb, margin=12, thresh=40):
    """Bounding box of the real content (text, stamps, signatures). Only pixels INSIDE the paper count, so the dark wedges around a
    rotated or skewed scan are ignored. Falls back to the whole frame when no clear sheet of paper is found."""
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY); H, W = g.shape
    paper = cv2.morphologyEx((g > 170).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    inside = np.ones((H, W), np.uint8)
    cnts, _ = cv2.findContours(paper, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        c = max(cnts, key=cv2.contourArea)
        if cv2.contourArea(c) > 0.2 * H * W:
            inside = np.zeros((H, W), np.uint8); cv2.fillPoly(inside, [cv2.convexHull(c)], 1)
            inside = cv2.erode(inside, np.ones((9, 9), np.uint8), iterations=1)          # drop the paper-edge transition itself
    m = (core.ink_mask(rgb, thresh) | (g < 90)) & (inside > 0)
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    ys, xs = np.where(m > 0)
    if len(xs) < 20: return None
    return max(0, xs.min() - margin), max(0, ys.min() - margin), min(W, xs.max() + margin + 1), min(H, ys.max() + margin + 1)

def clean_scan(rgb, opt=None, ctx=None):
    """RGB uint8 -> (cleaned RGB, report). The input is never modified.
    Order: restore (shadows, whiten, denoise, faint text) -> mode -> protect ink/marks -> deskew -> crop."""
    opt = opt or CleanOptions(); rgb = np.ascontiguousarray(rgb[..., :3]); rep = {}
    def step(f, m):
        if ctx: ctx.progress(f, m)
    if opt.auto_crop:                                       # cut the sheet out of its surroundings BEFORE cleaning (so no dark wedges survive)
        step(0.02, "Finding page edges")
        quad, conf = core.detect_document_quad(rgb); rep["page_confidence"] = conf
        if quad is not None and conf >= 0.6:
            q = core.order_quad(quad).astype(np.float32); cen = q.mean(0); d = cen - q; n = np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-6)
            q = q + d / n * 8.0                              # inset a few px so the page edge itself is not kept
            H0, W0 = rgb.shape[:2]
            if core._quad_area(q) < 0.97 * H0 * W0: rgb = core.warp_quad(rgb, q); rep["page_cut"] = True
    step(0.05, "Cleaning scan")
    base = core.restore_document(rgb, opt.restore_options())               # colour result
    out = base
    if opt.mode in ("gray", "bw"):
        out = core.restore_document(rgb, core.RestoreOptions(**{**opt.restore_options().__dict__, "mode": opt.mode}))
        if opt.preserve_marks:
            mm = _marks_mask(base)
            if mm.any(): out = out.copy(); out[mm] = base[mm]
    step(0.5, "Protecting text")
    if opt.preserve_black_text:
        g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        ink = core.ink_mask(rgb, 40) & (g < 130)
        if opt.mode != "bw" and ink.any():
            ref = rgb if opt.mode == "color" else np.repeat(g[..., None], 3, -1)       # gray mode must stay truly gray
            out = out.copy(); out[ink] = np.minimum(out[ink], ref[ink])
    rep["ink_retention"] = core.ink_retention(rgb, out)
    if opt.deskew:
        step(0.7, "Straightening")
        ang = core.estimate_skew(out); rep["skew_deg"] = ang
        if abs(ang) >= 0.2: out = core.straighten(out, ang)
    if opt.auto_crop:
        step(0.85, "Cropping borders")
        bb = content_bbox(out, int(opt.crop_margin_px)); rep["crop"] = bb
        if bb and (bb[2] - bb[0]) > 20 and (bb[3] - bb[1]) > 20: out = out[bb[1]:bb[3], bb[0]:bb[2]]
    step(1.0, "Done"); return np.ascontiguousarray(out), rep

def straighten_document(rgb):
    """Photo of a sheet on a table -> flat page (perspective). Returns (rgb, confidence); unchanged when no sheet is found."""
    quad, conf = core.detect_document_quad(rgb)
    if quad is None or conf < 0.5: return rgb, conf
    return core.warp_quad(rgb, quad), conf

# ---------------------------------------------------------------- PDF
def pdf_backend():
    for name in ("fitz", "pypdfium2"):
        try: __import__(name); return name
        except ImportError: continue
    return None

def pdf_to_images(path, dpi=200, ctx=None):
    be = pdf_backend()
    if be is None: raise Unavailable("PDF import needs PyMuPDF or pypdfium2:  pip install pymupdf")
    out = []
    if be == "fitz":
        import fitz
        with fitz.open(path) as doc:
            n = len(doc)
            for i, pg in enumerate(doc):
                if ctx: ctx.progress(i / max(1, n), f"Reading PDF page {i + 1}/{n}")
                pix = pg.get_pixmap(dpi=dpi, alpha=False); out.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    else:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(path); n = len(pdf)
        for i in range(n):
            if ctx: ctx.progress(i / max(1, n), f"Reading PDF page {i + 1}/{n}")
            out.append(pdf[i].render(scale=dpi / 72.0).to_pil().convert("RGB"))
    return out

def images_to_pdf(images, path, dpi=300): return core.save_pdf(images, path, dpi)

# ---------------------------------------------------------------- batch
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")

def batch_clean(files, out_dir, opt=None, fmt="png", ctx=None, pdf_out=None, dpi=300):
    """Clean many files. One bad file never stops the batch. Returns list of dict(src, out, ok, error, report). PDFs are expanded page by page."""
    os.makedirs(out_dir, exist_ok=True); results, pages = [], []; total = len(files)
    for i, f in enumerate(files):
        if ctx: ctx.progress(i / max(1, total), f"{os.path.basename(f)} ({i + 1}/{total})")
        try:
            items = pdf_to_images(f) if f.lower().endswith(".pdf") else [Image.open(f).convert("RGB")]
            base = os.path.splitext(os.path.basename(f))[0]
            for k, im in enumerate(items):
                cleaned, rep = clean_scan(np.array(im), opt); name = f"{base}_clean" + (f"_p{k + 1}" if len(items) > 1 else "")
                pim = Image.fromarray(cleaned); pages.append(pim)
                if pdf_out is None:
                    p = os.path.join(out_dir, name + "." + fmt); core.save_image(pim, p, dpi) if fmt in ("jpg", "jpeg", "png") else pim.save(p, dpi=(dpi, dpi))
                else: p = ""
                results.append(dict(src=f, out=p, ok=True, error="", report=rep))
        except Exception as e:
            from .tasks import Cancelled
            if isinstance(e, Cancelled): raise
            results.append(dict(src=f, out="", ok=False, error=f"{type(e).__name__}: {e}", report={}))
    if pdf_out and pages: images_to_pdf(pages, pdf_out, dpi)
    if ctx: ctx.progress(1.0, "Batch finished")
    return results


# ---------------------------------------------------------------- several documents on one scan / signatures
def split_documents(rgb, min_conf=0.4, max_docs=12):
    """Cards, receipts or sheets lying on one scan -> list of (straightened crop, confidence) in reading order (top to bottom, left to right)."""
    from . import cards, perspective
    found = cards.detect_cards(rgb, None, max_docs, tol=1.0, min_conf=min_conf)
    if not found: return []
    hs = [cards.quad_dims(f["quad"])[1] for f in found]; row_h = max(1.0, float(np.median(hs)) * 0.6)
    found.sort(key=lambda f: (round(float(f["quad"][:, 1].mean()) / row_h), float(f["quad"][:, 0].mean())))
    return [(perspective.perspective_crop(rgb, f["quad"]), f["confidence"]) for f in found]

def extract_signature(rgb, strength=0.6, margin=6):
    """Dark ink on light paper -> RGBA with a transparent background, cropped to the ink (use it as a layer on any document). Returns None when no ink is found."""
    g = cv2.cvtColor(np.ascontiguousarray(rgb[..., :3]), cv2.COLOR_RGB2GRAY).astype(np.float32); bg = cv2.GaussianBlur(cv2.dilate(g, np.ones((9, 9), np.uint8)), (0, 0), max(8, g.shape[1] // 40))
    norm = np.clip(g / np.maximum(bg, 1.0), 0, 1); alpha = np.clip((0.92 - norm) / (0.92 - (0.55 - 0.3 * float(np.clip(strength, 0, 1)))), 0, 1); a8 = (alpha * 255).astype(np.uint8)
    ys, xs = np.where(a8 > 40)
    if len(xs) < 30: return None
    ink = rgb[..., :3][a8 > 200]; col = np.percentile(ink, 15, axis=0).astype(np.uint8) if len(ink) else np.zeros(3, np.uint8); out = np.zeros(g.shape + (4,), np.uint8); out[..., :3] = col; out[..., 3] = a8
    x0, x1, y0, y1 = max(0, xs.min() - margin), min(g.shape[1], xs.max() + margin + 1), max(0, ys.min() - margin), min(g.shape[0], ys.max() + margin + 1); return out[y0:y1, x0:x1]

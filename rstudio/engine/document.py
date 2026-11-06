"""One shared document model for the whole application (photo editor, document studio, passport, layout all work on this).

Design rules
  * Layer pixels are RGBA uint8 arrays that are treated as IMMUTABLE (the array is flagged read-only). Every edit makes a new array,
    so undo/redo is just "swap the list of layers" and old states share memory (cheap history, original data never overwritten).
  * Text and shape layers keep their parameters and are re-rendered on change (still editable, not baked).
  * History stores the whole layer list + canvas size + selection. Undo/redo is therefore shared by every tool.
"""
import os, io, json, zipfile, uuid, copy
import numpy as np
from . import select as sel_engine
from PIL import Image, ImageDraw, ImageFont

VERSION = 1
BLEND_NORMAL = "normal"

def _uid(): return uuid.uuid4().hex[:10]

def _ro(a):
    a = np.ascontiguousarray(a, dtype=np.uint8); a.flags.writeable = False; return a

def to_rgba(img):
    """PIL image / ndarray (gray, RGB, RGBA) -> read-only RGBA uint8 array."""
    if isinstance(img, Image.Image):
        img = img.convert("RGBA"); return _ro(np.array(img))
    a = np.asarray(img)
    if a.dtype != np.uint8: a = np.clip(a, 0, 255).astype(np.uint8)
    if a.ndim == 2: a = np.stack([a, a, a, np.full_like(a, 255)], -1)
    elif a.shape[2] == 3: a = np.concatenate([a, np.full(a.shape[:2] + (1,), 255, np.uint8)], -1)
    return _ro(a)

# ------------------------------------------------------------------ fonts / vector layers
_FONT_CANDIDATES = ["arial.ttf", "segoeui.ttf", "calibri.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "LiberationSans-Regular.ttf"]
_BENGALI_FONTS = ["Nirmala.ttc", "Nirmala.ttf", "NirmalaUI.ttf", "vrinda.ttf", "Shonar.ttf", "Siyamrupali.ttf", "NotoSansBengali-Regular.ttf",
                  "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf", "/usr/share/fonts/truetype/freefont/FreeSerif.ttf", "FreeSerif.ttf", "Lohit-Bengali.ttf"]
_BENGALI_BOLD = ["NirmalaB.ttc", "NirmalaB.ttf"]

def has_bengali(text): return any(0x0980 <= ord(c) <= 0x09FF for c in str(text))

def _raqm():
    try:
        from PIL import features; return bool(features.check("raqm"))
    except Exception: return False

def _find_font(size, bold=False, text=""):
    """-> (font, bengali_capable). Bengali text prefers Bengali-capable fonts; the complex-script layout engine (Raqm) is used when this Pillow has it."""
    bn = has_bengali(text); names = (_BENGALI_BOLD if (bn and bold) else []) + (_BENGALI_FONTS if bn else []) + (["arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"] if bold else []) + _FONT_CANDIDATES
    eng = ImageFont.Layout.RAQM if _raqm() else ImageFont.Layout.BASIC
    for n in names:
        try: return ImageFont.truetype(n, size, layout_engine=eng), (bn and n in _BENGALI_FONTS + _BENGALI_BOLD)
        except (OSError, ValueError): continue
    try: return ImageFont.load_default(size), False
    except TypeError: return ImageFont.load_default(), False

def load_font(size, bold=False, text=""): return _find_font(size, bold, text)[0]

def text_support(text):
    """What the UI should warn about: Bengali text needs a Bengali font AND correct shaping (Qt backend or Raqm), otherwise conjunct letters look broken."""
    bn = has_bengali(text); font_ok = _find_font(24, False, text)[1] if bn else True
    return dict(bengali=bn, font_found=bool(font_ok), shaped=bool(_TEXT_BACKEND) or _raqm())

_TEXT_BACKEND = None
def set_text_backend(fn):
    """Optional: fn(params) -> RGBA ndarray (e.g. rendered by Qt, which always shapes Bengali correctly). Returning None / raising -> Pillow fallback."""
    global _TEXT_BACKEND; _TEXT_BACKEND = fn

def _color(c, default=(0, 0, 0, 255)):
    if c is None: return None
    c = tuple(int(v) for v in c)
    return (c + (255,))[:4] if len(c) == 3 else c[:4] if len(c) >= 4 else default

def render_text(p):
    """params: text,size,color,bold,align  ->  tight RGBA array."""
    if _TEXT_BACKEND is not None:
        try:
            a = _TEXT_BACKEND(p)
            if a is not None and getattr(a, "ndim", 0) == 3 and a.shape[2] == 4 and a.shape[0] > 0 and a.shape[1] > 0: return _ro(a)
        except Exception: pass
    text = str(p.get("text", "")) or " "; font = load_font(max(4, int(p.get("size", 48))), bool(p.get("bold")), text)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    l, t, r, b = probe.multiline_textbbox((0, 0), text, font=font, align=p.get("align", "left"))
    pad = 4
    im = Image.new("RGBA", (max(1, r - l + 2 * pad), max(1, b - t + 2 * pad)), (0, 0, 0, 0))
    ImageDraw.Draw(im).multiline_text((pad - l, pad - t), text, font=font, fill=_color(p.get("color"), (0, 0, 0, 255)), align=p.get("align", "left"))
    return _ro(np.array(im))

def render_shape(p):
    """params: shape(rect|ellipse|line),w,h,fill,stroke,stroke_w."""
    w, h = max(2, int(p.get("w", 200))), max(2, int(p.get("h", 120)))
    sw = max(0, int(p.get("stroke_w", 4))); pad = sw // 2 + 1
    im = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    fill, stroke = _color(p.get("fill")), _color(p.get("stroke"))
    box = [pad, pad, pad + w - 1, pad + h - 1]; kind = p.get("shape", "rect")
    if kind == "ellipse": d.ellipse(box, fill=fill, outline=stroke, width=sw if stroke else 0)
    elif kind == "line": d.line([(pad, pad), (pad + w - 1, pad + h - 1)], fill=stroke or fill or (0, 0, 0, 255), width=max(1, sw))
    else: d.rectangle(box, fill=fill, outline=stroke, width=sw if stroke else 0)
    return _ro(np.array(im))

# ------------------------------------------------------------------ layer
class Layer:
    KINDS = ("raster", "text", "shape")
    def __init__(self, pixels=None, name="Layer", kind="raster", x=0, y=0, params=None):
        self.id = _uid(); self.name = name; self.kind = kind
        self.x, self.y = int(x), int(y)
        self.opacity = 1.0; self.visible = True; self.locked = False; self.blend = BLEND_NORMAL
        self.params = dict(params or {})
        self.pixels = pixels if pixels is not None else _ro(np.zeros((1, 1, 4), np.uint8))
        if self.kind != "raster": self.rerender()
    @property
    def w(self): return self.pixels.shape[1]
    @property
    def h(self): return self.pixels.shape[0]
    def rerender(self):
        if self.kind == "text": self.pixels = render_text(self.params)
        elif self.kind == "shape": self.pixels = render_shape(self.params)
    def clone(self, new_id=False):
        c = copy.copy(self); c.params = copy.deepcopy(self.params)      # pixels are shared on purpose (immutable)
        if new_id: c.id = _uid()
        return c
    @property
    def is_background(self): return self.name == "Background"          # Photoshop rule: the eraser / Delete paint the background colour here instead of making holes
    def meta(self):
        return dict(id=self.id, name=self.name, kind=self.kind, x=self.x, y=self.y, opacity=self.opacity,
                    visible=self.visible, locked=self.locked, blend=self.blend, params=self.params)

# ------------------------------------------------------------------ compositing
def blend_over(dst, src, x, y, opacity=1.0):
    """Alpha-composite RGBA `src` onto RGBA `dst` (float math on the overlapping region only). dst is modified in place."""
    H, W = dst.shape[:2]; h, w = src.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0: return
    s = src[y0 - y: y1 - y, x0 - x: x1 - x].astype(np.float32); d = dst[y0:y1, x0:x1].astype(np.float32)
    sa = (s[..., 3:4] / 255.0) * float(opacity); da = d[..., 3:4] / 255.0
    oa = sa + da * (1 - sa)
    rgb = np.where(oa > 1e-6, (s[..., :3] * sa + d[..., :3] * da * (1 - sa)) / np.maximum(oa, 1e-6), 0)
    dst[y0:y1, x0:x1, :3] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8)
    dst[y0:y1, x0:x1, 3:4] = np.clip(oa * 255 + 0.5, 0, 255).astype(np.uint8)

def composite_layers(layers, w, h, upto=None):
    out = np.zeros((h, w, 4), np.uint8)
    for L in layers:
        if L.visible and L.opacity > 0: blend_over(out, L.pixels, L.x, L.y, L.opacity)
        if upto is not None and L.id == upto: break
    return out

# ------------------------------------------------------------------ document
class Document:
    def __init__(self, w=1000, h=1000, dpi=300, name="Untitled", max_undo=40, mem_budget_mb=1500):
        self.w, self.h, self.dpi, self.name = int(w), int(h), int(dpi), name
        self.layers = []; self.active_id = None; self._sel = None; self._sel_mask = None; self._outline = None      # selection: bounding box (x0,y0,x1,y1) + optional pixel mask
        self.uid = _uid() + _uid(); self.path = ""; self.dirty = False; self.max_undo = max_undo; self.mem_budget = int(mem_budget_mb) * 2 ** 20
        self._hist = []; self._pos = -1; self._cache = None; self._ver = 0
        self.commit("Open", dirty=False)

    @property
    def selection(self): return self._sel
    @selection.setter
    def selection(self, v):
        self._sel = v
        if v is None: self._sel_mask = None
    @property
    def sel_mask(self): return self._sel_mask

    # ---- construction
    @classmethod
    def new(cls, w, h, dpi=300, bg=(255, 255, 255, 255), name="Untitled", **kw):
        d = cls(w, h, dpi, name, **kw)
        if bg is not None:
            px = _ro(np.dstack([np.full((int(h), int(w)), c, np.uint8) for c in _color(bg)]))
            d.layers = [Layer(px, "Background")]; d.active_id = d.layers[0].id; d.commit("New", dirty=False, reset=True)
        return d
    @classmethod
    def from_image(cls, img, name="Image", dpi=300, path="", **kw):
        px = to_rgba(img); d = cls(px.shape[1], px.shape[0], dpi, name, **kw)
        L = Layer(px, "Background"); d.layers = [L]; d.active_id = L.id; d.path = path
        d.commit("Open", dirty=False, reset=True); return d
    @classmethod
    def open_image(cls, path, **kw):
        im = Image.open(path); dpi = 300
        try:
            v = im.info.get("dpi");  dpi = int(round(v[0])) if v and v[0] >= 36 else 300
        except Exception: dpi = 300
        from PIL import ImageOps
        im = ImageOps.exif_transpose(im)
        return cls.from_image(im, os.path.splitext(os.path.basename(path))[0], dpi, path, **kw)

    # ---- queries
    def layer(self, lid): return next((L for L in self.layers if L.id == lid), None)
    @property
    def active(self): return self.layer(self.active_id) or (self.layers[-1] if self.layers else None)
    def index(self, lid): return next((i for i, L in enumerate(self.layers) if L.id == lid), -1)
    def size_mm(self): return (self.w / self.dpi * 25.4, self.h / self.dpi * 25.4)

    # ---- history
    def _snap(self, label):
        return dict(label=label, w=self.w, h=self.h, layers=[L.clone() for L in self.layers], active=self.active_id, sel=(self._sel, self._sel_mask))
    def commit(self, label="Edit", dirty=True, reset=False):
        if reset: self._hist, self._pos = [], -1
        del self._hist[self._pos + 1:]
        self._hist.append(self._snap(label)); self._pos = len(self._hist) - 1
        extra = len(self._hist) - (self.max_undo + 1)
        if extra > 0:                       # keep state 0 (the original) forever, drop the oldest edits after it
            del self._hist[1:1 + extra]; self._pos = len(self._hist) - 1
        self._trim_memory()
        self._ver += 1; self._cache = None
        if dirty: self.dirty = True
    def _trim_memory(self):
        """Large pages x many brush strokes could eat gigabytes: drop the oldest edits (never state 0) until the history fits the budget."""
        while len(self._hist) > 2:
            sizes = {id(L.pixels): L.pixels.nbytes for st in self._hist for L in st["layers"]}
            if sum(sizes.values()) <= self.mem_budget: break
            del self._hist[1]; self._pos = len(self._hist) - 1
    def _restore(self, s):
        self.w, self.h = s["w"], s["h"]; self.layers = [L.clone() for L in s["layers"]]
        self.active_id = s["active"]; self._sel, self._sel_mask = s["sel"]; self._ver += 1; self._cache = None; self.dirty = True
    def can_undo(self): return self._pos > 0
    def can_redo(self): return self._pos < len(self._hist) - 1
    def undo(self):
        if not self.can_undo(): return None
        self._pos -= 1; self._restore(self._hist[self._pos]); return self._hist[self._pos + 1]["label"]
    def redo(self):
        if not self.can_redo(): return None
        self._pos += 1; self._restore(self._hist[self._pos]); return self._hist[self._pos]["label"]
    def history_labels(self): return [h["label"] for h in self._hist]
    @property
    def version(self): return self._ver

    # ---- render
    def composite(self):
        if self._cache is None or self._cache[0] != self._ver:
            self._cache = (self._ver, composite_layers(self.layers, self.w, self.h))
        return self._cache[1]
    def original_composite(self):
        """The untouched state-0 composite, for before/after comparison."""
        s = self._hist[0]; return composite_layers(s["layers"], s["w"], s["h"])
    def to_pil(self, background=None):
        a = self.composite()
        im = Image.fromarray(a, "RGBA")
        if background is not None:
            bg = Image.new("RGBA", im.size, _color(background)); bg.alpha_composite(im); im = bg
        return im

    # ---- layer operations (each commits one history step)
    def add_layer(self, layer, index=None, label="Add layer"):
        if index is None: self.layers.append(layer)
        else: self.layers.insert(max(0, min(len(self.layers), index)), layer)
        self.active_id = layer.id; self.commit(label); return layer
    def add_image_layer(self, img, name="Layer", x=None, y=None):
        px = to_rgba(img)
        x = (self.w - px.shape[1]) // 2 if x is None else x; y = (self.h - px.shape[0]) // 2 if y is None else y
        return self.add_layer(Layer(px, name, x=x, y=y), label="Add image")
    def add_text(self, text="Text", x=50, y=50, size=64, color=(0, 0, 0, 255), bold=False):
        return self.add_layer(Layer(name="Text", kind="text", x=x, y=y, params=dict(text=text, size=size, color=list(color), bold=bold)), label="Add text")
    def add_shape(self, shape="rect", x=50, y=50, w=300, h=200, fill=(30, 144, 255, 255), stroke=None, stroke_w=0):
        p = dict(shape=shape, w=w, h=h, fill=list(fill) if fill else None, stroke=list(stroke) if stroke else None, stroke_w=stroke_w)
        return self.add_layer(Layer(name=shape.title(), kind="shape", x=x, y=y, params=p), label="Add shape")
    def update_params(self, lid, label="Edit layer", **kw):
        L = self.layer(lid)
        if L is None or L.kind == "raster": return False
        L.params.update(kw); L.rerender(); self.commit(label); return True
    def insert_layers(self, index, layers, hide_id=None, label="Add layers"):
        """Insert several layers at once (ONE history step), optionally hiding another layer - used for cut-outs and background swaps."""
        index = max(0, min(len(self.layers), int(index)))
        for k, L in enumerate(layers): self.layers.insert(index + k, L)
        if hide_id and self.layer(hide_id): self.layer(hide_id).visible = False
        self.active_id = layers[-1].id; self.commit(label); return layers
    def remove_layer(self, lid):
        i = self.index(lid)
        if i < 0 or len(self.layers) <= 1: return False         # a document always keeps at least one layer
        del self.layers[i]; self.active_id = self.layers[max(0, i - 1)].id; self.commit("Delete layer"); return True
    def duplicate_layer(self, lid):
        i = self.index(lid)
        if i < 0: return None
        c = self.layers[i].clone(new_id=True); c.name += " copy"; c.x += 20; c.y += 20
        self.layers.insert(i + 1, c); self.active_id = c.id; self.commit("Duplicate layer"); return c
    def move_layer_order(self, lid, delta):
        i = self.index(lid); j = i + int(delta)
        if i < 0 or not 0 <= j < len(self.layers): return False
        self.layers.insert(j, self.layers.pop(i)); self.commit("Reorder layers"); return True
    def set_layer_props(self, lid, label="Layer properties", **kw):
        L = self.layer(lid)
        if L is None: return False
        for k, v in kw.items():
            if k in ("name", "visible", "locked", "opacity", "x", "y", "blend"): setattr(L, k, float(v) if k == "opacity" else v)
        L.opacity = max(0.0, min(1.0, L.opacity)); self.commit(label); return True
    def set_pixels(self, lid, arr, label="Edit", x=None, y=None):
        L = self.layer(lid)
        if L is None: return False
        L.pixels = to_rgba(arr)
        if x is not None: L.x = int(x)
        if y is not None: L.y = int(y)
        self.commit(label); return True
    def merge_down(self, lid):
        i = self.index(lid)
        if i <= 0: return False
        top, below = self.layers[i], self.layers[i - 1]
        x0, y0 = min(top.x, below.x), min(top.y, below.y); x1, y1 = max(top.x + top.w, below.x + below.w), max(top.y + top.h, below.y + below.h)
        buf = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
        for L in (below, top): blend_over(buf, L.pixels, L.x - x0, L.y - y0, L.opacity if L.visible else 0)
        m = Layer(_ro(buf), below.name, x=x0, y=y0); m.id = below.id
        self.layers[i - 1:i + 1] = [m]; self.active_id = m.id; self.commit("Merge down"); return True
    def flatten(self):
        px = _ro(self.composite().copy()); L = Layer(px, "Background"); self.layers = [L]; self.active_id = L.id; self.commit("Flatten image")

    # ---- selection
    def select_rect(self, x0, y0, x1, y1):
        x0, x1 = sorted((int(x0), int(x1))); y0, y1 = sorted((int(y0), int(y1)))
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(self.w, x1), min(self.h, y1)
        self._sel = (x0, y0, x1, y1) if x1 - x0 > 1 and y1 - y0 > 1 else None; self._sel_mask = None; self._outline = None
    def clear_selection(self): self.selection = None; self._outline = None
    def set_selection_mask(self, mask):
        """Selection from a page-sized mask (None / empty = deselect). The bounding box is kept in step."""
        if mask is None or not mask.any(): self.selection = None; self._outline = None; return
        m = np.ascontiguousarray(mask, dtype=np.uint8); m.flags.writeable = False; self._sel_mask = m; self._sel = sel_engine.bbox(m); self._outline = None
    def selection_mask(self):
        """Page-sized uint8 mask of the selection, or None when nothing is selected (a plain rectangle selection is turned into a mask)."""
        if self._sel is None: return None
        if self._sel_mask is not None: return self._sel_mask
        return sel_engine.rect_mask(self.h, self.w, *self._sel)
    def selection_outline(self):
        if self._sel is None: return []
        key = (id(self._sel_mask), self._sel)
        if self._outline is None or self._outline[0] != key: self._outline = (key, sel_engine.outline(self.selection_mask()))
        return self._outline[1]
    def select_all(self): self.set_selection_mask(np.full((self.h, self.w), 255, np.uint8))
    def invert_selection(self): self.set_selection_mask(sel_engine.invert(self.selection_mask(), self.h, self.w))
    def feather_selection(self, radius):
        m = self.selection_mask()
        if m is not None: self.set_selection_mask(sel_engine.feather(m, radius))
    def grow_selection(self, px):
        m = self.selection_mask()
        if m is not None: self.set_selection_mask(sel_engine.grow(m, px))

    def _layer_mask(self, L):
        """The selection expressed in a layer's own pixel grid (uint8, same size as the layer) or None."""
        m = self.selection_mask()
        if m is None: return None
        out = np.zeros((L.h, L.w), np.uint8); x0, y0, x1, y1 = max(0, L.x), max(0, L.y), min(self.w, L.x + L.w), min(self.h, L.y + L.h)
        if x1 > x0 and y1 > y0: out[y0 - L.y:y1 - L.y, x0 - L.x:x1 - L.x] = m[y0:y1, x0:x1]
        return out
    def masked(self, lid, res, use_selection=True):
        """Combine an adjusted copy of a layer with the original: only the selected pixels (soft at a feathered edge) take the new values."""
        L = self.layer(lid); src = np.asarray(L.pixels); res = np.asarray(res, dtype=np.uint8)
        if res.shape != src.shape: raise ValueError("adjustment must keep the layer size")
        if not (use_selection and self.selection): return res
        lm = self._layer_mask(L)
        if not lm.any(): return src
        ys, xs = np.where(lm > 0); y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1; out = src.copy(); a = (lm[y0:y1, x0:x1].astype(np.float32) / 255.0)[..., None]
        out[y0:y1, x0:x1] = np.clip(src[y0:y1, x0:x1].astype(np.float32) * (1 - a) + res[y0:y1, x0:x1].astype(np.float32) * a + 0.5, 0, 255).astype(np.uint8); return out

    # ---- selection-aware editing (Delete, fill, layer via copy / cut)
    def clear_selected(self, lid, background=(255, 255, 255, 255)):
        """Delete key: selected pixels become transparent - or the background colour on the 'Background' layer (as in Photoshop)."""
        L = self.layer(lid)
        if L is None or L.locked or not self.selection: return False
        res = np.array(L.pixels)
        if L.is_background: res[...] = _color(background)
        else: res[..., 3] = 0
        return self.apply_to_layer(lid, lambda a: res, "Clear selection")
    def fill_selected(self, lid, color, opacity=1.0, label="Fill selection"):
        """Fill the selection (or the whole layer when nothing is selected) with a colour."""
        L = self.layer(lid)
        if L is None or L.locked: return False
        c = np.array(_color(color), np.float32); k = float(opacity)
        def fill(a):
            f = a.astype(np.float32); al = f[..., 3:4] / 255.0; oa = k + al * (1 - k)
            rgb = np.where(oa > 1e-6, (c[:3] * k + f[..., :3] * al * (1 - k)) / np.maximum(oa, 1e-6), 0); return np.clip(np.concatenate([rgb, oa * 255.0], -1) + 0.5, 0, 255).astype(np.uint8)
        return self.apply_to_layer(lid, fill, label)
    def selection_layer(self, lid, name="Selection"):
        """The selected pixels of a layer as a NEW layer object (not added to this document, no history step) - for copying into another document."""
        L = self.layer(lid)
        if L is None or not self.selection: return None
        lm = self._layer_mask(L)
        if not lm.any(): return None
        ys, xs = np.where(lm > 0); y0, y1, x0, x1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
        px = np.array(L.pixels)[y0:y1, x0:x1].copy(); px[..., 3] = (px[..., 3].astype(np.float32) * lm[y0:y1, x0:x1].astype(np.float32) / 255.0 + 0.5).astype(np.uint8)
        return Layer(to_rgba(px), name, x=L.x + x0, y=L.y + y0)
    def layer_from_selection(self, lid, cut=False, name=None, background=(255, 255, 255, 255)):
        """Ctrl+J (copy) / Ctrl+Shift+J (cut): the selected pixels become a new layer in the same place."""
        L = self.layer(lid)
        if L is None or not self.selection: return None
        lm = self._layer_mask(L)
        if not lm.any(): return None
        ys, xs = np.where(lm > 0); y0, y1, x0, x1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
        px = np.array(L.pixels)[y0:y1, x0:x1].copy(); px[..., 3] = (px[..., 3].astype(np.float32) * lm[y0:y1, x0:x1].astype(np.float32) / 255.0 + 0.5).astype(np.uint8)
        new = Layer(to_rgba(px), name or ("Layer via cut" if cut else "Layer via copy"), x=L.x + x0, y=L.y + y0); i = self.index(lid)
        if cut:
            res = np.array(L.pixels)
            if L.is_background: res[...] = _color(background)
            else: res[..., 3] = 0
            L.pixels = to_rgba(self.masked(lid, res)); L.kind, L.params = "raster", {}
        self.layers.insert(i + 1, new); self.active_id = new.id; self.commit("Layer via cut" if cut else "Layer via copy"); return new

    def apply_to_layer(self, lid, fn, label="Adjust", use_selection=True):
        """fn(rgba uint8 HxWx4) -> rgba (same shape). With a selection only that region changes. Alpha is kept unless fn changes it."""
        L = self.layer(lid)
        if L is None or L.locked: return False
        res = self.masked(lid, fn(np.array(L.pixels)), use_selection)
        if L.kind != "raster":                  # editing pixels of a vector layer converts it to a plain raster layer
            L.kind = "raster"; L.params = {}
        L.pixels = _ro(res); self.commit(label); return True

    def composite_with(self, overrides):
        """Composite with some layers' pixels temporarily replaced ({layer_id: rgba}) - used for live adjustment previews. No history, no cache."""
        layers = []
        for L in self.layers:
            if L.id in overrides: c = L.clone(); c.pixels = overrides[L.id]; layers.append(c)
            else: layers.append(L)
        return composite_layers(layers, self.w, self.h)

    def invalidate(self):
        """Layer geometry changed live (e.g. while dragging): refresh the render cache without making a history step."""
        self._ver += 1; self._cache = None

    def patch_cache(self, x0, y0, x1, y1):
        """Re-composite ONLY a rectangle of the cached render (brush strokes on big pages must not recomposite 8 MP per mouse move)."""
        x0, y0, x1, y1 = max(0, int(x0)), max(0, int(y0)), min(self.w, int(x1)), min(self.h, int(y1))
        if x1 <= x0 or y1 <= y0: return
        if self._cache is None or self._cache[1].shape[:2] != (self.h, self.w): return self.invalidate()
        buf = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
        for L in self.layers:
            if L.visible and L.opacity > 0: blend_over(buf, L.pixels, L.x - x0, L.y - y0, L.opacity)
        arr = self._cache[1]; arr[y0:y1, x0:x1] = buf; self._ver += 1; self._cache = (self._ver, arr)

    def replace_with_image(self, img, label="Replace image"):
        """The whole picture becomes one new layer (size may change): used by cleanup / upscale results."""
        px = to_rgba(img); L = Layer(px, "Background"); self.w, self.h = px.shape[1], px.shape[0]
        self.layers = [L]; self.active_id = L.id; self.selection = None; self.commit(label)

    # ---- image-level transforms (affect every layer)
    def crop(self, x0, y0, x1, y1):
        x0, x1 = sorted((int(x0), int(x1))); y0, y1 = sorted((int(y0), int(y1)))
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(self.w, x1), min(self.h, y1)
        if x1 - x0 < 1 or y1 - y0 < 1: return False
        for L in self.layers: L.x -= x0; L.y -= y0
        self.w, self.h = x1 - x0, y1 - y0; self.selection = None; self.commit("Crop"); return True
    def resize(self, new_w, new_h, resample=Image.LANCZOS):
        new_w, new_h = max(1, int(new_w)), max(1, int(new_h))
        if (new_w, new_h) == (self.w, self.h): return False
        sx, sy = new_w / self.w, new_h / self.h
        for L in self.layers:
            tw, th = max(1, round(L.w * sx)), max(1, round(L.h * sy))
            L.pixels = _ro(np.array(Image.fromarray(np.array(L.pixels), "RGBA").resize((tw, th), resample)))
            L.x, L.y = round(L.x * sx), round(L.y * sy)
            if L.kind != "raster": L.kind, L.params = "raster", {}
        self.w, self.h = new_w, new_h; self.selection = None; self.commit("Resize image"); return True
    def rotate90(self, clockwise=True):
        k = -1 if clockwise else 1
        for L in self.layers:
            nx, ny = (self.h - (L.y + L.h), L.x) if clockwise else (L.y, self.w - (L.x + L.w))
            L.pixels = _ro(np.rot90(np.array(L.pixels), k)); L.x, L.y = nx, ny
            if L.kind != "raster": L.kind, L.params = "raster", {}
        self.w, self.h = self.h, self.w; self.selection = None; self.commit("Rotate 90"); return True
    def flip(self, horizontal=True):
        for L in self.layers:
            if horizontal: L.pixels = _ro(np.array(L.pixels)[:, ::-1]); L.x = self.w - (L.x + L.w)
            else: L.pixels = _ro(np.array(L.pixels)[::-1]); L.y = self.h - (L.y + L.h)
            if L.kind != "raster": L.kind, L.params = "raster", {}
        self.selection = None; self.commit("Flip horizontal" if horizontal else "Flip vertical"); return True
    # ---- layer geometry helpers (used by drag-to-resize, mm dialog, send-to-page)
    def live_update_layer(self, lid, pixels=None, x=None, y=None):
        """Change a layer while the mouse is down (no history step). Call commit() when the gesture ends."""
        L = self.layer(lid)
        if L is None: return False
        if pixels is not None:
            L.pixels = to_rgba(pixels)
            if L.kind != "raster": L.kind, L.params = "raster", {}
        if x is not None: L.x = int(x)
        if y is not None: L.y = int(y)
        self.invalidate(); return True
    def resize_layer(self, lid, new_w, new_h, x=None, y=None, label="Resize layer", resample=Image.LANCZOS):
        L = self.layer(lid)
        if L is None or L.locked: return False
        new_w, new_h = max(1, int(round(new_w))), max(1, int(round(new_h)))
        if (new_w, new_h) != (L.w, L.h): self.live_update_layer(lid, np.array(Image.fromarray(np.array(L.pixels), "RGBA").resize((new_w, new_h), resample)))
        if x is not None: L.x = int(round(x))
        if y is not None: L.y = int(round(y))
        self.commit(label); return True
    def fit_layer(self, lid, mode="contain", margin_px=0):
        """mode: contain (whole layer inside the page), cover (page completely covered), width (page width). The layer ends up centred."""
        L = self.layer(lid)
        if L is None: return False
        aw, ah = max(1, self.w - 2 * margin_px), max(1, self.h - 2 * margin_px)
        k = {"contain": min(aw / L.w, ah / L.h), "cover": max(aw / L.w, ah / L.h), "width": aw / L.w}[mode]; nw, nh = max(1, round(L.w * k)), max(1, round(L.h * k))
        return self.resize_layer(lid, nw, nh, (self.w - nw) / 2.0, (self.h - nh) / 2.0, "Fit layer to page")
    def layer_rect_mm(self, lid):
        L = self.layer(lid); f = 25.4 / self.dpi; return (L.x * f, L.y * f, L.w * f, L.h * f)
    def set_layer_rect_mm(self, lid, x_mm, y_mm, w_mm, h_mm):
        """Exact size and position in millimetres (print layouts)."""
        f = self.dpi / 25.4; return self.resize_layer(lid, w_mm * f, h_mm * f, x_mm * f, y_mm * f, "Set size / position (mm)")
    def rotate_layer90(self, lid, clockwise=True):
        L = self.layer(lid)
        if L is None or L.locked: return False
        cx, cy = L.x + L.w / 2.0, L.y + L.h / 2.0; L.pixels = to_rgba(np.rot90(np.array(L.pixels), -1 if clockwise else 1)); L.x, L.y = round(cx - L.w / 2.0), round(cy - L.h / 2.0)
        if L.kind != "raster": L.kind, L.params = "raster", {}
        self.commit("Rotate layer 90"); return True
    def flip_layer(self, lid, horizontal=True):
        L = self.layer(lid)
        if L is None or L.locked: return False
        L.pixels = to_rgba(np.array(L.pixels)[:, ::-1] if horizontal else np.array(L.pixels)[::-1])
        if L.kind != "raster": L.kind, L.params = "raster", {}
        self.commit("Flip layer"); return True
    def rotate_image(self, angle_deg, fill=(255, 255, 255, 255)):
        """Whole picture turned clockwise by any angle (canvas grows to hold it) - straightening a crooked scan."""
        im = self.to_pil(); im = im.rotate(-float(angle_deg), resample=Image.BICUBIC, expand=True, fillcolor=tuple(fill)); self.replace_with_image(np.array(im), f"Rotate {angle_deg:g} deg"); return True
    def copy_layer_to(self, lid, other, fit=False, margin_px=0):
        """Copy a layer into another open document (centred; fit=True also scales it to fit that page)."""
        L = self.layer(lid)
        if L is None: return None
        c = L.clone(new_id=True); other.add_layer(c, label="Paste layer"); c.x, c.y = (other.w - c.w) // 2, (other.h - c.h) // 2
        if fit and (c.w > other.w - 2 * margin_px or c.h > other.h - 2 * margin_px): other.fit_layer(c.id, "contain", margin_px)
        else: other.commit("Paste layer")
        return c
    def transform_layer(self, lid, scale=1.0, angle=0.0):
        """Scale and rotate ONE layer about its centre (bakes into its pixels)."""
        L = self.layer(lid)
        if L is None or L.locked: return False
        im = Image.fromarray(np.array(L.pixels), "RGBA"); cx, cy = L.x + L.w / 2, L.y + L.h / 2
        if abs(scale - 1.0) > 1e-6: im = im.resize((max(1, round(L.w * scale)), max(1, round(L.h * scale))), Image.LANCZOS)
        if abs(angle) > 1e-6: im = im.rotate(-angle, resample=Image.BICUBIC, expand=True)
        L.pixels = _ro(np.array(im)); L.x, L.y = round(cx - L.w / 2), round(cy - L.h / 2)
        if L.kind != "raster": L.kind, L.params = "raster", {}
        self.commit("Transform layer"); return True

    # ---- export
    def export(self, path, quality=92, dpi=None, background=(255, 255, 255)):
        ext = os.path.splitext(path)[1].lower(); dpi = int(dpi or self.dpi)
        im = self.to_pil()
        if ext in (".jpg", ".jpeg", ".bmp", ".pdf"): im = self.to_pil(background=background).convert("RGB")
        kw = {}
        if ext in (".jpg", ".jpeg"): kw = dict(quality=int(quality), optimize=True, dpi=(dpi, dpi))
        elif ext in (".png", ".tif", ".tiff"): kw = dict(dpi=(dpi, dpi))
        elif ext == ".webp": kw = dict(quality=int(quality))
        elif ext == ".pdf": kw = dict(resolution=float(dpi))
        elif ext not in (".bmp",): raise ValueError("Unsupported export format: " + (ext or "(none)"))
        tmp = path + ".part"
        with open(tmp, "wb") as f: im.save(f, format={".jpg": "JPEG", ".jpeg": "JPEG", ".tif": "TIFF", ".tiff": "TIFF", ".pdf": "PDF"}.get(ext, ext[1:].upper()), **kw)
        os.replace(tmp, path); return path

    # ---- project file (.rai = zip: doc.json + layers/<id>.png)
    def snapshot(self):
        """Everything needed to write the project, captured instantly (pixel arrays are immutable, so a worker thread can write it later)."""
        meta = dict(version=VERSION, name=self.name, w=self.w, h=self.h, dpi=self.dpi, active=self.active_id, layers=[L.meta() for L in self.layers])
        return dict(meta=meta, pixels=[(L.id, L.pixels) for L in self.layers])
    @staticmethod
    def write_snapshot(snap, path):
        tmp = path + ".part"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("doc.json", json.dumps(snap["meta"]))
            for lid, px in snap["pixels"]:
                b = io.BytesIO(); Image.fromarray(np.array(px), "RGBA").save(b, "PNG", compress_level=3); z.writestr(f"layers/{lid}.png", b.getvalue())
        os.replace(tmp, path); return path
    def save(self, path=None):
        path = path or self.path
        if not path: raise ValueError("no path")
        Document.write_snapshot(self.snapshot(), path); self.path = path; self.dirty = False; return path
    @classmethod
    def load(cls, path, **kw):
        with zipfile.ZipFile(path) as z:
            meta = json.loads(z.read("doc.json"))
            if meta.get("version", 0) > VERSION: raise ValueError("Project was saved by a newer version of Ripon AI Studio")
            d = cls(meta["w"], meta["h"], meta.get("dpi", 300), meta.get("name", "Untitled"), **kw); d.layers = []
            for m in meta["layers"]:
                lid = os.path.basename(str(m["id"]))
                with z.open(f"layers/{lid}.png") as f: px = to_rgba(Image.open(io.BytesIO(f.read())))
                L = Layer(px, m.get("name", "Layer"), "raster", m.get("x", 0), m.get("y", 0))
                L.kind, L.params = m.get("kind", "raster"), m.get("params", {})
                L.id = m["id"]; L.opacity = m.get("opacity", 1.0); L.visible = m.get("visible", True); L.locked = m.get("locked", False)
                d.layers.append(L)
            d.active_id = meta.get("active") or (d.layers[-1].id if d.layers else None)
        d.path = path; d.commit("Open", dirty=False, reset=True); return d

"""The editing canvas: zoom / pan, checkerboard, before-after, selection, crop, brush, eraser, text, shapes, picker, move.
All edits go through the shared Document (history, layers); this widget only draws it and translates the mouse into document operations."""
import numpy as np, cv2
from PySide6.QtCore import Qt, QPointF, QRectF, QRect, Signal
from PySide6.QtGui import QPainter, QImage, QColor, QPen, QBrush, QPixmap, QPainterPath, QPolygonF
from ..engine import perspective as persp_engine, snap as snap_engine, brush as brush_engine, select as sel_engine, cards as cards_engine
from PySide6.QtWidgets import QWidget

HANDLE = 8          # screen px grab distance for crop edges / split divider

def _qimage(arr):
    a = np.ascontiguousarray(arr); h, w = a.shape[:2]
    return QImage(a.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()

class CanvasView(QWidget):
    zoomChanged = Signal(float)
    cursorInfo = Signal(int, int, object)
    edited = Signal(str)                 # a history step was committed (layers panel / title must refresh)
    activeChanged = Signal()
    colorPicked = Signal(object)
    cropChanged = Signal(object)         # (x0,y0,x1,y1) or None
    textRequested = Signal(float, float, str)   # Text tool click: x, y, id of the text layer under the cursor ('' = new text)
    crossDrop = Signal(object)           # a dragged layer / selection was released OUTSIDE the page (e.g. on another document's tab): dict(lid, lift, x, y, pos0)
    perspApply = Signal()                # Enter pressed in the perspective-crop tool
    filesDropped = Signal(list, float, float)   # image files dropped on the page (paths, x, y in page pixels)

    def __init__(self, doc, opts, bg="#0c0e11", parent=None):
        super().__init__(parent)
        self.doc, self.opts = doc, opts
        self.tool = "move"; self.zoom = 1.0; self.off = QPointF(20, 20); self._fit_mode = True
        self.compare = "off"; self.split = 0.5
        self.preview_overrides = None; self.preview_image = None; self.preview_note = ""
        self.crop_rect = None; self.crop_aspect = None; self.margin_guide_mm = None
        self._drag = None; self._space = False; self._hover = None; self._stroke = None; self._qcache = {}
        self.persp = None; self._guides = ([], []); self.setAcceptDrops(True); self._poly = []; self._last_paint = None; self._clone_src = None; self._clone_off = None
        self.bg = QColor(bg)
        self._checker = self._make_checker()
        self.setMouseTracking(True); self.setFocusPolicy(Qt.FocusPolicy.StrongFocus); self.setMinimumSize(320, 240)
        self.set_tool("move")

    # ------------------------------------------------------------ view
    @staticmethod
    def _make_checker():
        pm = QPixmap(16, 16); pm.fill(QColor("#ffffff")); p = QPainter(pm); p.fillRect(0, 0, 8, 8, QColor("#cfd3da")); p.fillRect(8, 8, 8, 8, QColor("#cfd3da")); p.end(); return pm
    def set_theme_bg(self, color): self.bg = QColor(color); self.update()
    def _dims(self):
        a = self.preview_image if self.preview_image is not None else None
        return (a.shape[1], a.shape[0]) if a is not None else (self.doc.w, self.doc.h)
    def fit(self):
        w, h = self._dims(); vw, vh = max(50, self.width() - 40), max(50, self.height() - 40)
        self.zoom = max(0.02, min(vw / w, vh / h, 8.0)); self.off = QPointF((self.width() - w * self.zoom) / 2, (self.height() - h * self.zoom) / 2)
        self._fit_mode = True; self.zoomChanged.emit(self.zoom); self.update()
    def set_zoom(self, z, anchor=None):
        z = max(0.02, min(32.0, z)); anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
        ix, iy = (anchor.x() - self.off.x()) / self.zoom, (anchor.y() - self.off.y()) / self.zoom
        self.zoom = z; self.off = QPointF(anchor.x() - ix * z, anchor.y() - iy * z); self._fit_mode = False; self.zoomChanged.emit(z); self.update()
    def actual(self): self.set_zoom(1.0)
    def zoom_by(self, f, anchor=None): self.set_zoom(self.zoom * f, anchor)
    def zoom_physical(self):
        """100% print size: one document inch = one real inch on this screen."""
        self.set_zoom(self.logicalDpiX() / float(self.doc.dpi))
    def resizeEvent(self, e):
        if self._fit_mode: self.fit()
        super().resizeEvent(e)
    def set_document(self, doc):
        self.doc = doc; self.crop_rect = None; self.preview_overrides = None; self.preview_image = None; self.fit()
    def img_pt(self, pos): return ((pos.x() - self.off.x()) / self.zoom, (pos.y() - self.off.y()) / self.zoom)
    def _srect(self, x0, y0, x1, y1): return QRectF(self.off.x() + x0 * self.zoom, self.off.y() + y0 * self.zoom, (x1 - x0) * self.zoom, (y1 - y0) * self.zoom)

    # ------------------------------------------------------------ what is shown
    def display_array(self):
        if self.preview_image is not None: return self.preview_image
        if self.preview_overrides: return self.doc.composite_with(self.preview_overrides)
        return self.doc.composite()
    def before_array(self):
        return self.doc.composite() if (self.preview_image is not None or self.preview_overrides) else self.doc.original_composite()
    def set_preview(self, overrides=None, image=None, note=""):
        self.preview_overrides, self.preview_image, self.preview_note = overrides, image, note
        if image is not None: self.fit()
        self.update()
    def clear_preview(self):
        had = self.preview_image is not None; self.preview_overrides = self.preview_image = None; self.preview_note = ""
        if had: self.fit()
        self.update()
    def set_compare(self, mode): self.compare = mode; self.update()
    def refresh(self): self.update()

    def set_tool(self, tool):
        if tool != "crop": self.crop_rect = None; self.cropChanged.emit(None)
        if tool != "poly": self._poly = []
        if tool != "perspective": self.persp = None
        elif self.persp is None: self.auto_perspective(quiet=True)
        self.tool = tool
        self.setCursor({"pan": Qt.CursorShape.OpenHandCursor, "move": Qt.CursorShape.SizeAllCursor, "select": Qt.CursorShape.CrossCursor, "crop": Qt.CursorShape.CrossCursor,
                        "brush": Qt.CursorShape.CrossCursor, "eraser": Qt.CursorShape.CrossCursor, "text": Qt.CursorShape.IBeamCursor, "shape": Qt.CursorShape.CrossCursor,
                        "picker": Qt.CursorShape.PointingHandCursor, "perspective": Qt.CursorShape.CrossCursor, "lasso": Qt.CursorShape.CrossCursor, "poly": Qt.CursorShape.CrossCursor, "wand": Qt.CursorShape.CrossCursor, "bucket": Qt.CursorShape.CrossCursor, "gradient": Qt.CursorShape.CrossCursor, "clone": Qt.CursorShape.CrossCursor, "zoom": Qt.CursorShape.PointingHandCursor}.get(tool, Qt.CursorShape.ArrowCursor)); self.update()

    def _restore_cursor(self):
        if self._space: self.setCursor(Qt.CursorShape.OpenHandCursor)
        else: self.set_tool(self.tool)

    # ------------------------------------------------------------ painting
    def _cached(self, key, arr):
        q = self._qcache.get(key)
        if q is None:
            self._qcache = {k: v for k, v in self._qcache.items() if k[0] == key[0]} if len(self._qcache) > 3 else self._qcache; q = _qimage(arr); self._qcache[key] = q
        return q
    def paintEvent(self, e):
        p = QPainter(self); p.fillRect(self.rect(), self.bg)
        arr = self.display_array()
        if arr is None: return
        h, w = arr.shape[:2]; tgt = QRectF(self.off.x(), self.off.y(), w * self.zoom, h * self.zoom)
        vis = tgt.toAlignedRect().intersected(self.rect())
        if vis.isEmpty(): p.end(); return
        p.drawTiledPixmap(vis, self._checker)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.zoom < 1.0)
        kind = "prev" if (self.preview_image is not None or self.preview_overrides) else "doc"
        qi = _qimage(arr) if kind == "prev" else self._cached((self.doc.version, id(self.doc), "after"), arr)
        if self.compare == "split":
            before = _qimage(self.before_array()); sx = tgt.left() + tgt.width() * self.split
            p.save(); p.setClipRect(QRectF(tgt.left(), tgt.top(), max(0.0, sx - tgt.left()), tgt.height())); p.drawImage(tgt, before); p.restore()
            p.save(); p.setClipRect(QRectF(sx, tgt.top(), max(0.0, tgt.right() - sx), tgt.height())); p.drawImage(tgt, qi); p.restore()
            p.setPen(QPen(QColor("#ffffff"), 2)); p.drawLine(int(sx), int(max(0, tgt.top())), int(sx), int(min(self.height(), tgt.bottom())))
            self._badge(p, "BEFORE", QPointF(max(8, tgt.left() + 8), max(8, tgt.top() + 8))); self._badge(p, "AFTER", QPointF(min(self.width() - 70, sx + 8), max(8, tgt.top() + 8)))
        elif self.compare == "before":
            p.drawImage(tgt, _qimage(self.before_array())); self._badge(p, "BEFORE", QPointF(max(8, tgt.left() + 8), max(8, tgt.top() + 8)))
        else: p.drawImage(tgt, qi)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self.preview_image is not None:
            self._badge(p, "PREVIEW  -  Apply or Cancel in the side panel", QPointF(12, self.height() - 34), "#f59e0b"); p.end(); return
        self._overlays(p, tgt); p.end()

    def _badge(self, p, text, pos, color="#3b82f6"):
        fm = p.fontMetrics(); r = QRectF(pos.x(), pos.y(), fm.horizontalAdvance(text) + 16, fm.height() + 8)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(color)); p.drawRoundedRect(r, 5, 5); p.setPen(QColor("white")); p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def _overlays(self, p, tgt):
        d = self.doc
        if self.margin_guide_mm:
            m = self.margin_guide_mm / 25.4 * d.dpi; r = self._srect(m, m, d.w - m, d.h - m)
            p.setPen(QPen(QColor("#22d3ee"), 1, Qt.PenStyle.DashLine)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(r)
        for gx in self._guides[0]:
            sx = self.off.x() + gx * self.zoom; p.setPen(QPen(QColor("#22d3ee"), 1)); p.drawLine(int(sx), int(self.off.y()), int(sx), int(self.off.y() + d.h * self.zoom))
        for gy in self._guides[1]:
            sy = self.off.y() + gy * self.zoom; p.setPen(QPen(QColor("#22d3ee"), 1)); p.drawLine(int(self.off.x()), int(sy), int(self.off.x() + d.w * self.zoom), int(sy))
        if self.persp is not None and self.tool == "perspective":
            z = self.zoom; pts = [QPointF(self.off.x() + float(px) * z, self.off.y() + float(py) * z) for px, py in self.persp]; poly = QPolygonF(pts)
            dim = QPainterPath(); dim.addRect(tgt); dim.addPolygon(poly); dim.closeSubpath(); p.fillPath(dim, QColor(0, 0, 0, 130))
            p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(QColor("#22d3ee"), 2)); p.drawPolygon(poly)
            p.setBrush(QColor("#ffffff")); p.setPen(QPen(QColor("#0ea5e9"), 2))
            for i, pt in enumerate(pts): p.drawRect(QRectF(pt.x() - 7, pt.y() - 7, 14, 14))
        L = d.active
        if L is not None and self.tool == "move" and L.visible and not L.locked:
            p.setBrush(QColor("#ffffff")); p.setPen(QPen(QColor("#3b82f6"), 1.5))
            for hx, hy in self._layer_handles().values(): p.drawRect(QRectF(hx - 4.5, hy - 4.5, 9, 9))
        if L is not None and self.tool in ("move", "text", "shape") and L.visible:
            p.setPen(QPen(QColor("#3b82f6"), 1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(self._srect(L.x, L.y, L.x + L.w, L.y + L.h))
        if d.selection:
            p.setBrush(Qt.BrushStyle.NoBrush); z = self.zoom
            for c in d.selection_outline():
                poly = QPolygonF([QPointF(self.off.x() + float(px) * z, self.off.y() + float(py) * z) for px, py in c])
                p.setPen(QPen(QColor("white"), 1)); p.drawPolygon(poly); p.setPen(QPen(QColor("black"), 1, Qt.PenStyle.DashLine)); p.drawPolygon(poly)
        dr = self._drag
        if dr and dr.get("kind") == "rubber":
            r = self._srect(*dr["rect"]); p.setBrush(QColor(59, 130, 246, 40)); p.setPen(QPen(QColor("#3b82f6"), 1, Qt.PenStyle.DashLine))
            (p.drawEllipse(r) if dr.get("shape") == "ellipse" and dr.get("purpose") == "select" else p.drawRect(r))
        if dr and dr.get("kind") == "lasso" and len(dr["pts"]) > 1:
            p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(QColor("#3b82f6"), 1.5)); p.drawPolyline(QPolygonF([QPointF(self.off.x() + a * self.zoom, self.off.y() + b * self.zoom) for a, b in dr["pts"]]))
        if self._poly:
            pts = [QPointF(self.off.x() + a * self.zoom, self.off.y() + b * self.zoom) for a, b in self._poly]
            if self._hover is not None: pts.append(QPointF(self._hover))
            p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(QColor("#3b82f6"), 1.5)); p.drawPolyline(QPolygonF(pts)); p.setBrush(QColor("white"))
            for q in pts[:-1] if self._hover is not None else pts: p.drawRect(QRectF(q.x() - 3, q.y() - 3, 6, 6))
        if dr and dr.get("kind") == "grad":
            a, b = dr["p0"], dr["p1"]; p.setPen(QPen(QColor("#f59e0b"), 2)); p.drawLine(QPointF(self.off.x() + a[0] * self.zoom, self.off.y() + a[1] * self.zoom), QPointF(self.off.x() + b[0] * self.zoom, self.off.y() + b[1] * self.zoom))
        if self.tool == "clone" and self._clone_src is not None:
            cx, cy = self.off.x() + self._clone_src[0] * self.zoom, self.off.y() + self._clone_src[1] * self.zoom; p.setPen(QPen(QColor("#f59e0b"), 2)); p.drawLine(QPointF(cx - 8, cy), QPointF(cx + 8, cy)); p.drawLine(QPointF(cx, cy - 8), QPointF(cx, cy + 8))
        if self.crop_rect:
            cr = self._srect(*self.crop_rect); path = QPainterPath(); path.addRect(tgt); path.addRect(cr); p.fillPath(path, QColor(0, 0, 0, 150))
            p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(QColor("white"), 1.5)); p.drawRect(cr)
            p.setPen(QPen(QColor(255, 255, 255, 110), 1))
            for i in (1, 2):
                p.drawLine(int(cr.left() + cr.width() * i / 3), int(cr.top()), int(cr.left() + cr.width() * i / 3), int(cr.bottom()))
                p.drawLine(int(cr.left()), int(cr.top() + cr.height() * i / 3), int(cr.right()), int(cr.top() + cr.height() * i / 3))
            x0, y0, x1, y1 = self.crop_rect; self._badge(p, f"{int(abs(x1 - x0))} x {int(abs(y1 - y0))} px", QPointF(cr.left(), max(4, cr.top() - 28)))
        if self._hover and self.tool in ("brush", "eraser") and not self._space:
            r = max(1.0, float(self.opts.get("brush_size", 24)) / 2 * self.zoom); p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("white"), 1)); p.drawEllipse(self._hover, r, r); p.setPen(QPen(QColor("black"), 1, Qt.PenStyle.DotLine)); p.drawEllipse(self._hover, r, r)

    # ------------------------------------------------------------ mouse
    def wheelEvent(self, e):
        """Photoshop behaviour: wheel scrolls, Shift+wheel scrolls sideways, Ctrl / Alt + wheel zooms at the cursor (Settings can make the plain wheel zoom)."""
        m = e.modifiers(); dy = e.angleDelta().y(); ctrl = bool(m & Qt.KeyboardModifier.ControlModifier) or bool(m & Qt.KeyboardModifier.AltModifier)
        if ctrl or self.opts.get("wheel_zooms", False): self.zoom_by(1.15 ** (dy / 120.0), e.position()); return
        step = dy / 120.0 * 70.0
        if m & Qt.KeyboardModifier.ShiftModifier: self.off = QPointF(self.off.x() + step, self.off.y())
        else: self.off = QPointF(self.off.x(), self.off.y() + step)
        self._fit_mode = False; self.update()

    def _near_divider(self, pos):
        w, h = self._dims(); sx = self.off.x() + w * self.zoom * self.split
        return self.compare == "split" and abs(pos.x() - sx) <= HANDLE
    def _crop_handle(self, pos):
        if not self.crop_rect: return None
        x0, y0, x1, y1 = self.crop_rect; r = self._srect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)); m = HANDLE
        l, rt, t, b = abs(pos.x() - r.left()) <= m, abs(pos.x() - r.right()) <= m, abs(pos.y() - r.top()) <= m, abs(pos.y() - r.bottom()) <= m
        inx, iny = r.left() - m <= pos.x() <= r.right() + m, r.top() - m <= pos.y() <= r.bottom() + m
        if not (inx and iny): return None
        hx = "l" if l else "r" if rt else ""; hy = "t" if t else "b" if b else ""
        hd = (hx + hy) or None
        return hd if (hd is None or not self.crop_aspect or len(hd) == 2) else None            # with a fixed ratio only the corners resize

    def mousePressEvent(self, e):
        self.setFocus(); pos = e.position()
        if e.button() == Qt.MouseButton.MiddleButton or (e.button() == Qt.MouseButton.LeftButton and (self._space or self.tool == "pan")):
            self._drag = dict(kind="pan", start=pos, off=QPointF(self.off)); self.setCursor(Qt.CursorShape.ClosedHandCursor); return
        if e.button() != Qt.MouseButton.LeftButton: return
        if self._near_divider(pos): self._drag = dict(kind="split"); return
        if self.preview_image is not None or self.preview_overrides: return
        x, y = self.img_pt(pos); t = self.tool; d = self.doc
        if t == "move":
            hd = self._handle_at(pos)
            if hd and d.active is not None and not d.active.locked:
                L0 = d.active; self._drag = dict(kind="scale", h=hd, layer=L0, base=L0.pixels, rect=(L0.x, L0.y, L0.w, L0.h)); return
            if d.selection and self.opts.get("move_selection", True) and d.active is not None and not d.active.locked:
                m = d.selection_mask(); xi, yi = int(x), int(y)
                if 0 <= xi < d.w and 0 <= yi < d.h and m[yi, xi] > 127:                       # dragging INSIDE a selection moves the selected pixels (they become their own layer)
                    new = d.layer_from_selection(d.active_id, True, "Moved selection", tuple(self.opts.get("bg_color", (255, 255, 255, 255))))
                    if new is not None:
                        d.clear_selection(); self.activeChanged.emit(); self._drag = dict(kind="move", start=(x, y), pos=(new.x, new.y), layer=new, lift=True); self.update(); return
            if self.opts.get("autoselect", True):
                hit = self.pick_layer(x, y)
                if hit is not None and hit.id != d.active_id: d.active_id = hit.id; self.activeChanged.emit()
            L = d.active
            if L is not None and not L.locked: self._drag = dict(kind="move", start=(x, y), pos=(L.x, L.y), layer=L)
        elif t == "select": self._drag = dict(kind="rubber", start=(x, y), rect=(x, y, x, y), purpose="select", shape=self.opts.get("marquee", "rect"), mode=self._sel_mode(e))
        elif t == "lasso": self._drag = dict(kind="lasso", pts=[(x, y)], mode=self._sel_mode(e))
        elif t == "poly": self._press_poly(pos, x, y, e)
        elif t == "wand": self._wand(x, y, self._sel_mode(e))
        elif t == "bucket": self._bucket(x, y)
        elif t == "gradient":
            L0 = d.active
            if L0 is not None and not L0.locked and L0.visible: self._drag = dict(kind="grad", p0=(x, y), p1=(x, y))
        elif t == "zoom": self.zoom_by(1 / 1.5 if (e.modifiers() & Qt.KeyboardModifier.AltModifier) else 1.5, pos)
        elif t == "shape": self._drag = dict(kind="rubber", start=(x, y), rect=(x, y, x, y), purpose="shape")
        elif t == "crop": self._press_crop(pos, x, y)
        elif t == "perspective": self._press_persp(pos, x, y)
        elif t in ("brush", "eraser", "clone"):
            alt = bool(e.modifiers() & Qt.KeyboardModifier.AltModifier)
            if alt and t == "brush": self._pick(x, y); return                                   # Alt + click = temporary colour picker (as in Photoshop)
            if alt and t == "clone": self._clone_src = (x, y); self._clone_off = None; self.update(); return
            if t == "clone" and self._clone_src is None: return
            if self._stroke_begin(t, x, y):
                L0 = self._stroke["layer"]
                if (e.modifiers() & Qt.KeyboardModifier.ShiftModifier) and self._last_paint and self._last_paint[0] == L0.id and t != "clone": self._stroke_to(self._last_paint[1:])   # Shift + click = straight line from the last point
                self._stroke_to((x, y)); self._drag = dict(kind="stroke")
        elif t == "picker": self._pick(x, y)
        elif t == "text":
            hit = self.pick_layer(x, y); self.textRequested.emit(float(x), float(y), hit.id if (hit is not None and hit.kind == "text") else "")

    def _sel_mode(self, e):
        m = e.modifiers(); sh, al = bool(m & Qt.KeyboardModifier.ShiftModifier), bool(m & Qt.KeyboardModifier.AltModifier)
        return "inter" if (sh and al) else "add" if sh else "sub" if al else self.opts.get("sel_mode", "new")
    def _set_selection(self, new_mask, mode):
        d = self.doc
        if new_mask is None or not new_mask.any():
            if mode == "new": d.clear_selection()
        else: d.set_selection_mask(sel_engine.combine(d.selection_mask(), new_mask, mode))
        d.commit("Selection", dirty=False); self.edited.emit("Selection")
    def _press_poly(self, pos, x, y, e):
        if len(self._poly) >= 3:
            fx, fy = self._poly[0]
            if abs(self.off.x() + fx * self.zoom - pos.x()) <= 8 and abs(self.off.y() + fy * self.zoom - pos.y()) <= 8: self._close_poly(self._sel_mode(e)); return      # click on the first point closes it
        self._poly.append((x, y)); self.update()
    def _close_poly(self, mode=None):
        pts, self._poly = self._poly, []
        if len(pts) >= 3: self._set_selection(sel_engine.polygon_mask(self.doc.h, self.doc.w, pts), mode or self.opts.get("sel_mode", "new"))
        self.update()
    def mouseDoubleClickEvent(self, e):
        if self.tool == "poly" and len(self._poly) >= 3: self._close_poly()
        elif self.tool == "crop" and self.crop_rect: self.apply_crop()
        else: super().mouseDoubleClickEvent(e)
    def _wand(self, x, y, mode):
        d, o = self.doc, self.opts; L = d.active
        if o.get("wand_all", True) or L is None: src = d.composite()
        else:
            full = np.zeros((d.h, d.w, 4), np.uint8); x0, y0, x1, y1 = max(0, L.x), max(0, L.y), min(d.w, L.x + L.w), min(d.h, L.y + L.h)
            if x1 > x0 and y1 > y0: full[y0:y1, x0:x1] = L.pixels[y0 - L.y:y1 - L.y, x0 - L.x:x1 - L.x]
            src = full
        a = src[..., 3:4].astype(np.float32) / 255.0; flat = (src[..., :3] * a + 255 * (1 - a)).astype(np.uint8)
        self._set_selection(sel_engine.wand_mask(flat, x, y, int(o.get("wand_tol", 32)), bool(o.get("wand_contig", True))), mode)
    def _bucket(self, x, y):
        d, o = self.doc, self.opts; L = d.active
        if L is None or L.locked or not L.visible: return
        if L.kind != "raster": L.kind, L.params = "raster", {}
        sel = d._layer_mask(L); new = brush_engine.bucket_fill(L.pixels, x - L.x, y - L.y, o.get("brush_color", (0, 0, 0, 255)), int(o.get("bucket_tol", 32)), bool(o.get("bucket_contig", True)), sel, float(o.get("brush_opacity", 1.0)))
        if new is not L.pixels: d.set_pixels(L.id, new, "Paint bucket"); self.edited.emit("Paint bucket")
    def _apply_gradient(self, p0, p1):
        d, o = self.doc, self.opts; L = d.active
        if L is None or L.locked: return
        if L.kind != "raster": L.kind, L.params = "raster", {}
        g = brush_engine.gradient(L.h, L.w, (p0[0] - L.x, p0[1] - L.y), (p1[0] - L.x, p1[1] - L.y), o.get("brush_color", (0, 0, 0, 255)), o.get("bg_color", (255, 255, 255, 255)), o.get("grad_kind", "linear") == "radial")
        m = d._layer_mask(L); m = np.full((L.h, L.w), 255, np.uint8) if m is None else m
        d.set_pixels(L.id, brush_engine.blend_by_mask(L.pixels, g, m, float(o.get("brush_opacity", 1.0))), "Gradient"); self.edited.emit("Gradient")

    def _press_crop(self, pos, x, y):
        h = self._crop_handle(pos)
        if h: self._drag = dict(kind="crop_edge", h=h); return
        if self.crop_rect:
            x0, y0, x1, y1 = self.crop_rect
            if min(x0, x1) <= x <= max(x0, x1) and min(y0, y1) <= y <= max(y0, y1):
                self._drag = dict(kind="crop_move", start=(x, y), rect=self.crop_rect); return
        self._drag = dict(kind="crop_new", start=(x, y)); self.crop_rect = (x, y, x, y)

    def mouseMoveEvent(self, e):
        pos = e.position(); self._hover = pos; dr = self._drag
        if dr is None:
            if self._near_divider(pos): self.setCursor(Qt.CursorShape.SplitHCursor)
            elif self.tool == "crop" and self._crop_handle(pos): self.setCursor(Qt.CursorShape.SizeAllCursor)
            elif self.tool == "crop": self.setCursor(Qt.CursorShape.CrossCursor)
            elif self.tool == "move":
                hd = self._handle_at(pos); C = Qt.CursorShape
                self.setCursor({"tl": C.SizeFDiagCursor, "br": C.SizeFDiagCursor, "tr": C.SizeBDiagCursor, "bl": C.SizeBDiagCursor, "t": C.SizeVerCursor, "b": C.SizeVerCursor, "l": C.SizeHorCursor, "r": C.SizeHorCursor}.get(hd, C.SizeAllCursor))
        x, y = self.img_pt(pos); w, h = self._dims()
        if 0 <= x < w and 0 <= y < h and self.preview_image is None and not (dr and dr.get("kind") == "stroke"):
            a = self.doc.composite(); self.cursorInfo.emit(int(x), int(y), tuple(int(v) for v in a[int(y), int(x)]))
        else: self.cursorInfo.emit(int(x), int(y), None)
        if dr is None: self.update(); return
        k = dr["kind"]
        if k == "pan": self.off = QPointF(dr["off"].x() + pos.x() - dr["start"].x(), dr["off"].y() + pos.y() - dr["start"].y()); self._fit_mode = False
        elif k == "split": self.split = max(0.02, min(0.98, (pos.x() - self.off.x()) / max(1.0, w * self.zoom)))
        elif k == "move":
            L = dr["layer"]; nx, ny = dr["pos"][0] + x - dr["start"][0], dr["pos"][1] + y - dr["start"][1]
            if not (e.modifiers() & Qt.KeyboardModifier.AltModifier): nx, ny, self._guides = self._snap(L, nx, ny)
            else: self._guides = ([], [])
            L.x, L.y = int(round(nx)), int(round(ny)); self.doc.invalidate()
        elif k == "scale": self._scale_to(dr, x, y, bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier))
        elif k == "persp_pt": self.persp[dr["i"]] = (min(max(0.0, x), float(self.doc.w)), min(max(0.0, y), float(self.doc.h)))
        elif k == "persp_move": self.persp = np.array([(min(max(0.0, px + x - dr["start"][0]), float(self.doc.w)), min(max(0.0, py + y - dr["start"][1]), float(self.doc.h))) for px, py in dr["pts"]], np.float32)
        elif k == "rubber": dr["rect"] = (dr["start"][0], dr["start"][1], x, y)
        elif k == "stroke": self._stroke_to((x, y))
        elif k == "crop_new": self.crop_rect = self._aspect((dr["start"][0], dr["start"][1], x, y), e.modifiers())
        elif k == "crop_move":
            dx, dy = x - dr["start"][0], y - dr["start"][1]; x0, y0, x1, y1 = dr["rect"]; self.crop_rect = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
        elif k == "crop_edge":
            x0, y0, x1, y1 = self.crop_rect; hh = dr["h"]
            if self.crop_aspect and len(hh) == 2:                                   # corner with a fixed ratio: the opposite corner stays, the box keeps its shape
                ax, ay = (x1 if "l" in hh else x0), (y1 if "t" in hh else y0); w = max(4.0, abs(x - ax)); hgt = w / self.crop_aspect
                self.crop_rect = (ax, ay, ax + (w if "r" in hh else -w), ay + (hgt if "b" in hh else -hgt))
            else:
                if "l" in hh: x0 = x
                if "r" in hh: x1 = x
                if "t" in hh: y0 = y
                if "b" in hh: y1 = y
                self.crop_rect = (x0, y0, x1, y1)
        elif k == "lasso": dr["pts"].append((x, y))
        elif k == "grad": dr["p1"] = (x, y)
        self.update()

    def mouseReleaseEvent(self, e):
        dr, self._drag = self._drag, None
        self._restore_cursor()
        if dr is None: return
        k = dr["kind"]; d = self.doc; self._guides = ([], [])
        if k == "move":
            L = dr["layer"]; rp = e.position() if e is not None else None
            if rp is not None and (rp.x() < 0 or rp.y() < 0 or rp.x() > self.width() or rp.y() > self.height()):
                self.crossDrop.emit(dict(lid=L.id, lift=bool(dr.get("lift")), x=float(rp.x()), y=float(rp.y()), pos0=dr["pos"])); self.update(); return
            if (L.x, L.y) != dr["pos"]: d.commit("Move layer"); self.edited.emit("Move layer")
        elif k == "scale":
            t = dr.get("target"); L = dr["layer"]
            if t:
                d.live_update_layer(L.id, dr["base"], dr["rect"][0], dr["rect"][1]); d.resize_layer(L.id, t[2], t[3], t[0], t[1], "Scale layer"); self.edited.emit("Scale layer")
        elif k in ("persp_pt", "persp_move"): pass
        elif k == "stroke": self._stroke_end()
        elif k == "rubber":
            x0, y0, x1, y1 = dr["rect"]
            if dr["purpose"] == "select":
                if abs(x1 - x0) < 3 and abs(y1 - y0) < 3: self._set_selection(None, "new") if dr.get("mode", "new") == "new" else None
                else: self._set_selection((sel_engine.ellipse_mask if dr.get("shape") == "ellipse" else sel_engine.rect_mask)(d.h, d.w, x0, y0, x1, y1), dr.get("mode", "new"))
            else: self._make_shape(x0, y0, x1, y1)
        elif k == "lasso": self._set_selection(sel_engine.polygon_mask(d.h, d.w, dr["pts"]), dr["mode"]) if len(dr["pts"]) >= 3 else None
        elif k == "grad":
            if abs(dr["p1"][0] - dr["p0"][0]) + abs(dr["p1"][1] - dr["p0"][1]) > 3: self._apply_gradient(dr["p0"], dr["p1"])
        elif k in ("crop_new", "crop_move", "crop_edge"):
            if self.crop_rect and abs(self.crop_rect[2] - self.crop_rect[0]) < 4: self.crop_rect = None
            self.cropChanged.emit(self.crop_rect)
        self.update()

    def leaveEvent(self, e): self._hover = None; self.update()

    # ------------------------------------------------------------ resize handles / snapping / perspective / drop
    def _layer_handles(self):
        L = self.doc.active
        if L is None or not L.visible or L.locked: return {}
        r = self._srect(L.x, L.y, L.x + L.w, L.y + L.h); cx, cy = (r.left() + r.right()) / 2.0, (r.top() + r.bottom()) / 2.0
        return {"tl": (r.left(), r.top()), "tr": (r.right(), r.top()), "br": (r.right(), r.bottom()), "bl": (r.left(), r.bottom()), "t": (cx, r.top()), "b": (cx, r.bottom()), "l": (r.left(), cy), "r": (r.right(), cy)}
    def _handle_at(self, pos):
        if self.tool != "move" or self.preview_image is not None or self.preview_overrides: return None
        for k, (hx, hy) in self._layer_handles().items():
            if abs(pos.x() - hx) <= 9 and abs(pos.y() - hy) <= 9: return k
        return None
    def _scale_to(self, dr, x, y, free):
        L = dr["layer"]; x0, y0, w0, h0 = dr["rect"]; x1, y1 = x0 + w0, y0 + h0; hd = dr["h"]; MIN = 4
        nx0 = min(x, x1 - MIN) if "l" in hd else x0; nx1 = max(x, x0 + MIN) if "r" in hd else x1; ny0 = min(y, y1 - MIN) if "t" in hd else y0; ny1 = max(y, y0 + MIN) if "b" in hd else y1
        nw, nh = nx1 - nx0, ny1 - ny0
        if len(hd) == 2 and not free:                                    # corner handle: keep the proportions (hold Shift to stretch freely)
            k = max(nw / float(w0), nh / float(h0)); nw, nh = w0 * k, h0 * k; nx0 = x1 - nw if "l" in hd else x0; ny0 = y1 - nh if "t" in hd else y0
        nw, nh = max(MIN, int(round(nw))), max(MIN, int(round(nh))); nx0, ny0 = int(round(nx0)), int(round(ny0))
        interp = cv2.INTER_AREA if nw * nh < w0 * h0 else cv2.INTER_LINEAR
        self.doc.live_update_layer(L.id, cv2.resize(dr["base"], (nw, nh), interpolation=interp), nx0, ny0); dr["target"] = (nx0, ny0, nw, nh)
    def _snap(self, L, nx, ny):
        d = self.doc; m = (self.margin_guide_mm / 25.4 * d.dpi) if self.margin_guide_mm else 0
        others = [(o.x, o.y, o.x + o.w, o.y + o.h) for o in d.layers if o is not L and o.visible]; xs, ys = snap_engine.targets_for(d.w, d.h, m, others)
        dx, dy, gx, gy = snap_engine.snap_move((nx, ny, nx + L.w, ny + L.h), xs, ys, 8.0 / max(self.zoom, 0.01)); return nx + dx, ny + dy, (gx, gy)
    def auto_perspective(self, quiet=False):
        """Put the four corners on the biggest card / sheet found in the picture, or on a rectangle inset from the edges. Returns (found, confidence)."""
        rgb = np.ascontiguousarray(self.doc.composite()[..., :3]); found, conf = False, 0.0; q = None; asp = self.opts.get("persp_aspect")
        try:
            hits = cards_engine.detect_cards(rgb, asp, 1, min_conf=0.45) if asp else []
            if hits: q, conf, found = hits[0]["quad"], hits[0]["confidence"], True
            else: q, conf = persp_engine.detect_quad(rgb, 0.03); found = q is not None and conf >= 0.6
        except Exception: q = None
        self.persp = np.array(q, np.float32) if found else persp_engine.default_quad(self.doc.w, self.doc.h)
        self.update(); return found, conf
    def _press_persp(self, pos, x, y):
        if self.persp is None: return
        z = self.zoom
        for i, (px, py) in enumerate(self.persp):
            if abs(self.off.x() + px * z - pos.x()) <= 14 and abs(self.off.y() + py * z - pos.y()) <= 14: self._drag = dict(kind="persp_pt", i=i); return
        if cv2.pointPolygonTest(np.array(self.persp, np.float32).reshape(-1, 1, 2), (float(x), float(y)), False) >= 0: self._drag = dict(kind="persp_move", start=(x, y), pts=self.persp.copy())
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if files:
            x, y = self.img_pt(e.position()); self.filesDropped.emit(files, float(x), float(y)); e.acceptProposedAction()

    # ------------------------------------------------------------ tools
    def pick_layer(self, x, y):
        for L in reversed(self.doc.layers):
            if not L.visible or L.locked: continue
            if L.kind == "text" and L.x <= x < L.x + L.w and L.y <= y < L.y + L.h: return L          # text is grabbed anywhere inside its box, not only on the letter shapes
            lx, ly = int(x) - L.x, int(y) - L.y
            if 0 <= lx < L.w and 0 <= ly < L.h and L.pixels[ly, lx, 3] > 10: return L
        return None

    def _pick(self, x, y):
        a = self.doc.composite(); xi, yi = int(max(0, min(self.doc.w - 1, x))), int(max(0, min(self.doc.h - 1, y))); self.colorPicked.emit(tuple(int(v) for v in a[yi, xi]))

    def _aspect(self, r, mods):
        x0, y0, x1, y1 = r; asp = self.crop_aspect
        if (mods & Qt.KeyboardModifier.ShiftModifier) and not asp: asp = 1.0
        if asp:
            w = abs(x1 - x0); hgt = w / asp; y1 = y0 + (hgt if y1 >= y0 else -hgt)
        return (x0, y0, x1, y1)

    def apply_crop(self):
        rect = self.crop_rect or self.doc.selection
        if not rect: return False
        ok = self.doc.crop(*[int(round(v)) for v in rect]); self.crop_rect = None; self.cropChanged.emit(None)
        if ok: self.fit(); self.edited.emit("Crop")
        return ok
    def cancel_crop(self): self.crop_rect = None; self.cropChanged.emit(None); self.update()
    def set_crop_ratio(self, w, h):
        self.crop_aspect = (w / float(h)) if (w and h) else None
    def set_crop_to_ratio_default(self):
        """Pre-place a centred crop with the current aspect so the user only has to drag it into place."""
        if not self.crop_aspect: return
        W, H = self.doc.w, self.doc.h; cw = min(W, H * self.crop_aspect); ch = cw / self.crop_aspect
        self.crop_rect = ((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2); self.cropChanged.emit(self.crop_rect); self.update()

    def _make_shape(self, x0, y0, x1, y1):
        w, h = int(abs(x1 - x0)), int(abs(y1 - y0))
        if w < 4 or h < 4: return
        o = self.opts; fill = o.get("shape_fill"); stroke = o.get("shape_stroke")
        self.doc.add_shape(o.get("shape", "rect"), int(min(x0, x1)), int(min(y0, y1)), w, h, fill=tuple(fill) if fill else None, stroke=tuple(stroke) if stroke else None, stroke_w=int(o.get("shape_stroke_w", 0)))
        self.edited.emit("Add shape"); self.activeChanged.emit()

    # ---- brush / eraser / clone stamp (a private copy of the layer is painted and committed as ONE history step on release)
    def _expand_layer(self, L):
        """Photoshop layers cover the whole page, so painting outside a smaller picture works: grow the layer to cover the page."""
        d = self.doc; x0, y0, x1, y1 = min(0, L.x), min(0, L.y), max(d.w, L.x + L.w), max(d.h, L.y + L.h)
        if (x0, y0, x1, y1) == (L.x, L.y, L.x + L.w, L.y + L.h): return
        buf = np.zeros((y1 - y0, x1 - x0, 4), np.uint8); buf[L.y - y0:L.y - y0 + L.h, L.x - x0:L.x - x0 + L.w] = L.pixels; d.live_update_layer(L.id, buf, x0, y0)
    def _stroke_begin(self, tool, x=0.0, y=0.0):
        d, o = self.doc, self.opts; L = d.active
        if L is None or L.locked or not L.visible: return False
        if L.kind != "raster": L.kind, L.params = "raster", {}
        if tool != "eraser" or not L.is_background: self._expand_layer(L)
        sel = d._layer_mask(L); mode = {"brush": "paint", "eraser": "erase", "clone": "clone"}[tool]
        erase_bg = tool == "eraser" and L.is_background and not o.get("erase_transparent", False)
        if tool == "clone":
            if self._clone_off is None: self._clone_off = (self._clone_src[0] - x, self._clone_src[1] - y)           # aligned: the source keeps its distance for the whole session
            off = self._clone_off
        else: off = None
        st = brush_engine.Stroke(L.pixels, mode, float(o.get("brush_size", 24)), float(o.get("brush_hardness", 1.0)), float(o.get("brush_opacity", 1.0)), tuple(o.get("brush_color", (0, 0, 0, 255)))[:3],
                                 tuple(o.get("bg_color", (255, 255, 255, 255)))[:3], erase_bg, sel, off)
        self._stroke = dict(layer=L, tool=tool, st=st); L.pixels = st.cur; return True
    def _stroke_to(self, pt):
        s = self._stroke
        if s is None: return
        L = s["layer"]; rect = s["st"].move_to(pt[0] - L.x, pt[1] - L.y)
        if rect: self.doc.patch_cache(rect[0] + L.x, rect[1] + L.y, rect[2] + L.x, rect[3] + L.y)
    def _stroke_end(self):
        s, self._stroke = self._stroke, None
        if s is None: return
        L = s["layer"]; label = {"brush": "Brush stroke", "eraser": "Erase", "clone": "Clone stamp"}[s["tool"]]; last = s["st"].last
        if last: self._last_paint = (L.id, last[0] + L.x, last[1] + L.y)
        self.doc.set_pixels(L.id, s["st"].result(), label); self.edited.emit(label)

    # ------------------------------------------------------------ keys
    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Space and not e.isAutoRepeat(): self._space = True; self.setCursor(Qt.CursorShape.OpenHandCursor); return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.tool == "perspective" and self.persp is not None: self.perspApply.emit(); return
        if k == Qt.Key.Key_Escape and self.tool == "perspective": self.auto_perspective(quiet=True); return
        if self.tool == "poly" and k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and len(self._poly) >= 3: self._close_poly(); return
        if self.tool == "poly" and k == Qt.Key.Key_Escape and self._poly: self._poly = []; self.update(); return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (self.crop_rect or (self.tool == "crop" and self.doc.selection)): self.apply_crop(); return
        if k == Qt.Key.Key_Escape:
            if self.crop_rect: self.cancel_crop()
            elif self.doc.selection: self.doc.clear_selection(); self.doc.commit("Deselect", dirty=False); self.edited.emit("Deselect")
            return
        super().keyPressEvent(e)
    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat(): self._space = False; self.set_tool(self.tool); return
        super().keyReleaseEvent(e)

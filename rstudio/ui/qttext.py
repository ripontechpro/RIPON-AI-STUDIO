"""Text rendering through Qt (HarfBuzz / Uniscribe): always shapes Bengali conjunct letters correctly. Registered as the engine's text backend;
any problem here returns None / raises and the engine falls back to Pillow, so text layers can never break because of this file."""
import math
import numpy as np

BENGALI_FAMILIES = ["Nirmala UI", "Vrinda", "Shonar Bangla", "Siyam Rupali", "Noto Sans Bengali", "Lohit Bengali", "FreeSerif"]
LATIN_FAMILIES = ["Segoe UI", "Arial", "Helvetica", "DejaVu Sans"]

def render(p):
    from PySide6.QtCore import Qt, QRectF, QThread
    from PySide6.QtGui import QImage, QPainter, QFont, QColor, QFontMetricsF, QGuiApplication
    app = QGuiApplication.instance()
    if app is None or QThread.currentThread() != app.thread(): return None          # fonts are a GUI-thread resource
    from ..engine.document import has_bengali
    text = str(p.get("text", "")) or " "; size = max(4, int(p.get("size", 48)))
    font = QFont(); font.setFamilies((BENGALI_FAMILIES + LATIN_FAMILIES) if has_bengali(text) else LATIN_FAMILIES); font.setPixelSize(size); font.setBold(bool(p.get("bold")))
    align = {"center": Qt.AlignmentFlag.AlignHCenter, "right": Qt.AlignmentFlag.AlignRight}.get(p.get("align", "left"), Qt.AlignmentFlag.AlignLeft)
    flags = int(align.value) | int(Qt.AlignmentFlag.AlignTop.value)
    br = QFontMetricsF(font).boundingRect(QRectF(0, 0, 20000, 20000), flags, text)
    w, h = int(math.ceil(br.width())) + 10, int(math.ceil(br.height())) + 10
    if w < 2 or h < 2 or w > 20000 or h > 20000: return None
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied); img.fill(Qt.GlobalColor.transparent)
    qp = QPainter(img); qp.setRenderHint(QPainter.RenderHint.TextAntialiasing, True); qp.setFont(font)
    c = list(p.get("color") or (0, 0, 0, 255)) + [255]; qp.setPen(QColor(int(c[0]), int(c[1]), int(c[2]), int(c[3])))
    qp.drawText(QRectF(5, 5, br.width() + 1, br.height() + 1), flags, text); qp.end()
    img = img.convertToFormat(QImage.Format.Format_RGBA8888); bpl = img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)[:, :w * 4].reshape(h, w, 4)
    return np.array(buf)                                                              # copy: Qt owns the buffer

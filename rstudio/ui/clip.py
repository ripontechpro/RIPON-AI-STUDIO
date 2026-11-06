"""Clipboard <-> RGBA arrays (Ctrl+C / Ctrl+V of pictures). Kept tiny and separate so it can be replaced in tests."""
import numpy as np

def get_image():
    """Picture on the clipboard as RGBA uint8, or None."""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage
    qi = QApplication.clipboard().image()
    if qi is None or qi.isNull(): return None
    qi = qi.convertToFormat(QImage.Format.Format_RGBA8888); w, h, bpl = qi.width(), qi.height(), qi.bytesPerLine()
    return np.array(np.frombuffer(qi.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)[:, :w * 4].reshape(h, w, 4))

def set_image(rgba):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage
    a = np.ascontiguousarray(rgba); h, w = a.shape[:2]; QApplication.clipboard().setImage(QImage(a.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy())

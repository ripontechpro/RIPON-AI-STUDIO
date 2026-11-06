"""Home screen: logo, owner photo slot, welcome, quick actions and recent files."""
import os
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout, QListWidget, QListWidgetItem, QFrame
from .. import APP_NAME, paths
from .icons import icon

class HomeScreen(QWidget):
    action = Signal(str)               # new | open | photo | ai | doc | passport | layout
    openRecent = Signal(str)
    removeRecent = Signal(str)          # one entry removed from the list (the file itself is never touched)
    clearRecent = Signal()

    CARDS = [("new", "new", "New Project", "Blank page or canvas"), ("open", "open", "Open Image", "JPG, PNG, TIFF, WebP, PDF, project"),
             ("photo", "crop", "Photo Editing", "Crop, retouch, layers, text"), ("ai", "ai", "AI Tools", "Background, upscale, enhance"),
             ("retouch", "face", "Photo Doctor & Retouch", "Auto fix, skin, red eye, KB limit"), ("doc", "doc", "Document Cleanup", "Scans, deskew, batch, PDF"), ("passport", "passport", "Passport Photo Studio", "Sizes, sheets, A4 print"),
             ("nid", "passport", "NID / ID Print (A4)", "Front + back at exact size"), ("duet", "image", "Bank Photo Duet", "Two photos, many per A4"), ("layout", "layout", "Print Layout", "Pages, margins, print preview")]

    def __init__(self, icon_color="#e7e9ee"):
        super().__init__(); root = QHBoxLayout(self); root.setContentsMargins(36, 30, 36, 30); root.setSpacing(30)
        left = QVBoxLayout(); left.setSpacing(16); root.addLayout(left, 3)
        hero = QFrame(); hero.setObjectName("hero"); hl = QHBoxLayout(hero); hl.setContentsMargins(26, 22, 26, 22); hl.setSpacing(24)
        logo = QLabel(); pm = QPixmap(paths.asset("logo_512.png"))
        if not pm.isNull(): logo.setPixmap(pm.scaled(190, 190, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        hl.addWidget(logo)
        txt = QVBoxLayout(); txt.setSpacing(6)
        h1 = QLabel(APP_NAME); h1.setObjectName("h1"); txt.addWidget(h1)
        sub = QLabel("Welcome to Ripon - edit, enhance and create."); sub.setObjectName("h2"); txt.addWidget(sub)
        msg = QLabel("One workspace for photos, scanned documents, passport & ID sheets and print layouts. Pick a task below or open an image to start."); msg.setWordWrap(True); msg.setObjectName("muted"); txt.addWidget(msg)
        txt.addStretch(1); hl.addLayout(txt, 1); hl.addWidget(self._photo_slot())
        left.addWidget(hero)
        grid = QGridLayout(); grid.setSpacing(12)
        for i, (key, ic, title, sub_) in enumerate(self.CARDS):
            b = QPushButton(f"{title}\n{sub_}"); b.setObjectName("card"); b.setIcon(icon(ic, icon_color, 28)); b.setIconSize(QSize(28, 28)); b.setMinimumHeight(84)
            b.clicked.connect(lambda _=False, k=key: self.action.emit(k)); grid.addWidget(b, i // 3, i % 3)
        left.addLayout(grid); left.addStretch(1)
        right = QVBoxLayout(); root.addLayout(right, 1)
        t = QLabel("RECENT"); t.setObjectName("section"); right.addWidget(t)
        self.recent = QListWidget(); self.recent.itemActivated.connect(lambda it: self.openRecent.emit(it.data(Qt.ItemDataRole.UserRole))); right.addWidget(self.recent, 1)
        self.empty = QLabel("Nothing opened yet."); self.empty.setObjectName("muted"); right.addWidget(self.empty)
        btns = QHBoxLayout(); self.rm_btn = QPushButton("Remove from list"); self.rm_btn.setToolTip("Removes the selected entry from this list. The file itself is not deleted. (Delete key)"); self.rm_btn.clicked.connect(self._remove)
        self.clr_btn = QPushButton("Clear history"); self.clr_btn.setToolTip("Empties the recent list. Your files are not deleted."); self.clr_btn.clicked.connect(lambda: self.clearRecent.emit()); btns.addWidget(self.rm_btn); btns.addWidget(self.clr_btn); right.addLayout(btns)
        self.recent.keyPressEvent = self._recent_key

    def _photo_slot(self):
        """Owner photo: uses assets/ripon_photo.(png|jpg) when present, otherwise a replaceable placeholder (never an invented photo)."""
        lab = QLabel(); lab.setFixedSize(150, 150); size = 150
        pm = QPixmap()
        for n in ("ripon_photo.png", "ripon_photo.jpg", "ripon_photo.jpeg"):
            p = paths.asset(n)
            if os.path.isfile(p): pm = QPixmap(p); break
        out = QPixmap(size, size); out.fill(Qt.GlobalColor.transparent); qp = QPainter(out); qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath(); path.addEllipse(2, 2, size - 4, size - 4); qp.setClipPath(path)
        if pm.isNull():
            qp.fillRect(0, 0, size, size, QColor("#262b35")); qp.setPen(QColor("#9aa3b2")); f = QFont(); f.setPointSize(40); f.setBold(True); qp.setFont(f)
            qp.drawText(out.rect(), Qt.AlignmentFlag.AlignCenter, "R")
            lab.setToolTip("Placeholder. Put your photo at assets/ripon_photo.jpg (or .png) and restart to show it here.")
        else:
            pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation); qp.drawPixmap((size - pm.width()) // 2, (size - pm.height()) // 2, pm)
        qp.setClipping(False); qp.setPen(QColor("#3b82f6")); qp.setBrush(Qt.BrushStyle.NoBrush); qp.drawEllipse(2, 2, size - 4, size - 4); qp.end(); lab.setPixmap(out); return lab

    def _remove(self):
        it = self.recent.currentItem()
        if it is not None: self.removeRecent.emit(it.data(Qt.ItemDataRole.UserRole))
    def _recent_key(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace): self._remove()
        else: QListWidget.keyPressEvent(self.recent, e)
    def set_recent(self, files):
        self.recent.clear()
        for p in files:
            it = QListWidgetItem(os.path.basename(p)); it.setToolTip(p); it.setData(Qt.ItemDataRole.UserRole, p); self.recent.addItem(it)
        self.empty.setVisible(not files); self.rm_btn.setEnabled(bool(files)); self.clr_btn.setEnabled(bool(files))

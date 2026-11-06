"""Settings: theme, folders, AI model management, performance, about."""
import os
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QCheckBox, QSpinBox, QFileDialog, QGroupBox, QFormLayout,
                               QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea, QMessageBox)
from .. import APP_NAME, VERSION
from .panels import STATUS_TEXT, STATUS_COLOR
from .widgets import label, row, GroupPickDialog, fmt_bytes
from ..engine import modelpack
import time

class SettingsPage(QScrollArea):
    themeChanged = Signal(str)
    def __init__(self, main):
        super().__init__(); self.main = main; s = main.settings; self.setWidgetResizable(True)
        body = QWidget(); v = QVBoxLayout(body); v.setContentsMargins(40, 28, 40, 28); v.setSpacing(14); self.setWidget(body)
        t = QLabel("Settings"); t.setObjectName("h1"); v.addWidget(t)
        g = QGroupBox("Appearance"); f = QFormLayout(g); self.theme = QComboBox(); self.theme.addItems(["dark", "light"]); self.theme.setCurrentText(s.get("theme")); f.addRow("Theme", self.theme); v.addWidget(g)
        self.theme.currentTextChanged.connect(self._theme)
        g = QGroupBox("Folders"); f = QFormLayout(g); self.exp = QLineEdit(s.get("export_dir")); self.mod = QLineEdit(s.models_dir())
        f.addRow("Default export folder", row(self.exp, self._pick(self.exp)))
        f.addRow("AI models folder", row(self.mod, self._pick(self.mod), self._btn("Open", self.open_models)))
        legacy = s.legacy_models_dir(); same = bool(legacy) and os.path.normcase(os.path.abspath(legacy)) == os.path.normcase(os.path.abspath(s.models_dir()))
        f.addRow("", label(("Using the models folder of your earlier Ripon Computer app, so nothing has to be downloaded again.  " if same else "") + "Layout:  rembg/<model>.onnx   and   realesrgan-ncnn/realesrgan-ncnn-vulkan.exe + realesrgan-ncnn/models/", "muted")); v.addWidget(g)
        g = QGroupBox("AI models"); gl = QVBoxLayout(g); self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(["Capability", "Status", "Details"]); self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.setMinimumHeight(280); gl.addWidget(self.table)
        gl.addWidget(row(self._btn("Refresh", self.refresh), self._btn("Prepare background model (downloads once)", lambda: main.panels["ai"].prepare()))); v.addWidget(g)
        g = QGroupBox("Mouse, history and privacy"); gl = QVBoxLayout(g)
        self.wheel = QCheckBox("Mouse wheel zooms (default: the wheel scrolls and Ctrl / Alt + wheel zooms, as in Photoshop)"); self.wheel.setChecked(bool(s.get("wheel_zooms"))); self.wheel.toggled.connect(main.apply_wheel_setting); gl.addWidget(self.wheel)
        gl.addWidget(row(self._btn("Clear recent files list", main.clear_recent), self._btn("Delete autosave recovery copies", self.clear_recovery)))
        gl.addWidget(label("Clearing the list never deletes your pictures. Recovery copies are the automatic backups of unsaved work.", "muted")); v.addWidget(g)
        g = QGroupBox("Model backup & restore"); gl = QVBoxLayout(g)
        gl.addWidget(label("Pack the AI models you already downloaded into ONE zip file. A friend installs the app, presses Restore models and picks that zip - nothing has to be downloaded again.", "muted"))
        gl.addWidget(row(self._btn("Back up models...", self.backup_dialog, True), self._btn("Restore models...", self.restore_dialog)))
        gl.addWidget(label("Tip: a pack can be several GB. Use an NTFS / exFAT drive (a FAT32 USB stick cannot hold files over 4 GB), or back up one group at a time.", "muted")); v.addWidget(g)
        g = QGroupBox("AI providers"); f = QFormLayout(g); self.cloud = QCheckBox("Allow cloud providers (none are implemented yet)"); self.cloud.setChecked(bool(s.get("cloud_enabled"))); self.cloud.setEnabled(False)
        f.addRow(self.cloud); f.addRow("", label("Images are never uploaded without an explicit action. When cloud providers are added, API keys will be read from environment variables only - they are never stored in settings or in the code.", "muted")); v.addWidget(g)
        g = QGroupBox("Performance"); f = QFormLayout(g); self.undo = QSpinBox(); self.undo.setRange(5, 200); self.undo.setValue(int(s.get("max_undo"))); f.addRow("Undo steps per document", self.undo)
        self.gpu = QCheckBox("Prefer GPU when a model supports it"); self.gpu.setChecked(bool(s.get("prefer_gpu"))); f.addRow(self.gpu); v.addWidget(g)
        v.addWidget(row(self._btn("Save settings", self.save, True))); 
        g = QGroupBox("About"); gl = QVBoxLayout(g); gl.addWidget(label(f"{APP_NAME}  {VERSION}\nPhoto editing, document cleanup, passport & ID sheets and print layout in one application.\nBuilt with Python, PySide6, OpenCV, NumPy and Pillow.")); v.addWidget(g); v.addStretch(1)
        self.refresh()
    def _btn(self, text, slot, primary=False):
        b = QPushButton(text); b.clicked.connect(slot)
        if primary: b.setObjectName("primary")
        return b
    def _pick(self, edit):
        def go():
            p = QFileDialog.getExistingDirectory(self, "Choose folder", edit.text())
            if p: edit.setText(p)
        return self._btn("Browse...", go)
    def _theme(self, name): self.main.settings.set("theme", name); self.main.settings.save(); self.themeChanged.emit(name)
    def open_models(self):
        p = self.mod.text() or self.main.settings.models_dir(); os.makedirs(p, exist_ok=True); QDesktopServices.openUrl(QUrl.fromLocalFile(p))
    def save(self):
        s = self.main.settings; s.set("export_dir", self.exp.text().strip())
        txt = self.mod.text().strip()
        if s.get("models_dir") or os.path.normcase(os.path.abspath(txt or ".")) != os.path.normcase(os.path.abspath(s.models_dir())): s.set("models_dir", txt)       # untouched automatic folder stays automatic
        s.set("max_undo", self.undo.value()); s.set("prefer_gpu", self.gpu.isChecked())
        for d in self.main.docs(): d.max_undo = self.undo.value()
        ok = s.save(); self.main.notify("Settings saved." if ok else "Could not write the settings file.", "ok" if ok else "error"); self.refresh()
    def clear_recovery(self):
        n = len(self.main.recovery.pending()); self.main.recovery.clear_all(); self.main.notify(f"Deleted {n} recovery copy(ies).", "ok")
    # ---- backup / restore (dialogs call the start_* methods, which tests call directly)
    def backup_dialog(self):
        groups = modelpack.scan(self.main.settings.models_dir())
        if not groups: self.main.notify(f"No downloaded models found in {self.main.settings.models_dir()}.", "warn"); return
        dlg = GroupPickDialog("Back up models", f"Models found in:\n{self.main.settings.models_dir()}\n\nTick what goes into the backup file.", groups, "Choose file...", parent=self)
        if not dlg.exec() or not dlg.keys(): return
        p, _ = QFileDialog.getSaveFileName(self, "Save model backup", os.path.join(self.main.settings.get("export_dir") or "", f"RiponAIStudio-models-{time.strftime('%Y%m%d')}.zip"), "Model pack (*.zip)")
        if p: self.start_backup(dlg.keys(), p if p.lower().endswith(".zip") else p + ".zip")
    def start_backup(self, keys, path):
        md = self.main.settings.models_dir()
        def done(r): self.main.notify(f"Backup saved: {os.path.basename(r['path'])} ({r['files']} files, {fmt_bytes(r['bytes'])}).", "ok")
        self.main.run_task("Backing up models", lambda ctx: modelpack.create_backup(md, path, keys, ctx), done=done)
    def restore_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose a model backup", self.main.settings.get("export_dir") or "", "Model pack (*.zip)")
        if not p: return
        try: info = modelpack.inspect_backup(p)
        except modelpack.PackError as e: self.main.notify(str(e), "warn"); return
        if not info["groups"]: self.main.notify("This pack contains no usable model files.", "warn"); return
        warn = "Only restore packs from someone you trust. " + (f"This pack also contains a program the app will run for upscaling ({', '.join(info['programs'])}). " if info["programs"] else "") + (f"{len(info['problems'])} unsafe or damaged entr(y/ies) will be ignored." if info["problems"] else "")
        dlg = GroupPickDialog("Restore models", f"Pack created {info['created'] or '(unknown date)'}.\nFiles go into:\n{self.main.settings.models_dir()}", info["groups"], "Restore", warn, "Replace files that already exist", self)
        if dlg.exec() and dlg.keys(): self.start_restore(p, dlg.keys(), dlg.extra_checked())
    def start_restore(self, path, keys, overwrite=False):
        md = self.main.settings.models_dir()
        def done(r):
            msg = f"Restored {len(r['restored'])} file(s), kept {len(r['skipped'])} existing."
            if r["failed"]:
                QMessageBox.warning(self, "Some files were not restored", "\n".join(f"{p}: {why}" for p, why in r["failed"][:12])); msg += f" {len(r['failed'])} failed."
            self.main.notify(msg, "ok" if not r["failed"] else "warn"); self.refresh()
            if "ai" in self.main.panels: self.main.panels["ai"].refresh()
        self.main.run_task("Restoring models", lambda ctx: modelpack.restore_backup(path, md, keys, overwrite, ctx), done=done, fail=lambda e: self.main.notify(str(e), "warn" if isinstance(e, modelpack.PackError) else "error"))
    def refresh(self):
        caps = self.main.ai.capabilities(); self.table.setRowCount(len(caps))
        for i, c in enumerate(caps):
            self.table.setItem(i, 0, QTableWidgetItem(c["label"] + ("  (classical)" if c["kind"] == "classical" else ""))); st = QTableWidgetItem(STATUS_TEXT[c["status"]])
            from PySide6.QtGui import QColor
            st.setForeground(QColor(STATUS_COLOR[c["status"]])); self.table.setItem(i, 1, st); self.table.setItem(i, 2, QTableWidgetItem(c["detail"]))
        self.table.resizeColumnToContents(0); self.table.resizeColumnToContents(1)

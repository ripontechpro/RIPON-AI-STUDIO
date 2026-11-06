# -*- mode: python ; coding: utf-8 -*-
# Build with  build.bat  (or:  pyinstaller --noconfirm --clean ripon_ai_studio.spec)  ->  dist\RiponAIStudio\RiponAIStudio.exe
# Folder build on purpose (not --onefile) and UPX is OFF: both make antivirus false alarms much more likely.
import os, importlib.util
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

ROOT = SPECPATH
def have(m): return importlib.util.find_spec(m) is not None

hidden = collect_submodules("rstudio")
datas = [(os.path.join(ROOT, "assets"), "assets")]
binaries = []
for pkg in ("rembg", "onnxruntime", "pymupdf", "fitz", "pypdfium2"):       # optional extras: bundled only when installed in this environment
    if have(pkg):
        datas += collect_data_files(pkg); binaries += collect_dynamic_libs(pkg); hidden += collect_submodules(pkg)

a = Analysis([os.path.join(ROOT, "app.py")], pathex=[ROOT], binaries=binaries, datas=datas, hiddenimports=hidden, hookspath=[], runtime_hooks=[],
             excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide2", "IPython", "pytest"],
             noarchive=False)
pyz = PYZ(a.pure)
VERSION_FILE = os.path.join(ROOT, "build", "version_info.txt")                # written by tools\\make_version_file.py (build.bat does this)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="RiponAIStudio", debug=False, strip=False, upx=False, console=False, uac_admin=False,
          icon=os.path.join(ROOT, "assets", "logo.ico"), version=VERSION_FILE if os.path.isfile(VERSION_FILE) else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="RiponAIStudio")

"""Run this FIRST on a machine with PySide6 installed:   python tools\\qt_selfcheck.py
It builds the REAL main window off-screen, opens a generated image, visits every workspace page, runs a few edits and saves a screenshot of each
page into the 'selfcheck' folder. Exit code 0 = everything ran; 1 = a step failed (the traceback says which)."""
import os, sys, tempfile, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

def main():
    import numpy as np
    from PIL import Image
    from PySide6.QtWidgets import QApplication
    from rstudio.engine.settings import Settings
    from rstudio.engine.document import Document
    from rstudio.ui import theme
    from rstudio.ui.main_window import MainWindow, NAV
    out = os.path.join(ROOT, "selfcheck"); os.makedirs(out, exist_ok=True); td = tempfile.mkdtemp()
    app = QApplication([]); s = Settings(os.path.join(td, "s.json")); theme.apply_theme(app, "dark"); w = MainWindow(s); w.resize(1480, 900); w.show()
    step = "start"
    try:
        for key, _, _ in NAV:
            step = f"page {key}"; w.goto(key); app.processEvents(); w.grab().save(os.path.join(out, f"page_{key}.png"))
        a = np.zeros((600, 800, 3), np.uint8); a[..., 0] = np.linspace(0, 255, 800, dtype=np.uint8)[None]; a[..., 1] = 110; a[..., 2] = np.linspace(255, 0, 600, dtype=np.uint8)[:, None]
        p = os.path.join(td, "t.png"); Image.fromarray(a).save(p)
        step = "open image"; w.open_files([p]); app.processEvents()
        for key in ("photo", "adjust", "ai", "doc", "passport", "layout"):
            step = f"page {key} with image"; w.goto(key); app.processEvents(); w.grab().save(os.path.join(out, f"image_{key}.png"))
        step = "brush stroke"; w.set_tool("brush"); w.doc().add_text("Hello", 50, 50); w.after_edit(); app.processEvents()
        step = "undo/redo"; w.undo(); w.redo()
        step = "bengali text via Qt"; from rstudio.ui import qttext; px = qttext.render(dict(text="আমার সোনার বাংলা", size=60, color=[0, 0, 0, 255])); print("Bengali via Qt:", "no result (Pillow fallback will be used)" if px is None else f"{px.shape[1]}x{px.shape[0]} px, ink pixels {(px[..., 3] > 128).sum()}")
        step = "compare"; w.cycle_compare(); app.processEvents(); w.grab().save(os.path.join(out, "compare.png"))
        step = "theme"; w.apply_theme("light"); app.processEvents(); w.grab().save(os.path.join(out, "light.png")); w.apply_theme("dark")
    except Exception:
        print("FAILED at step:", step); traceback.print_exc(); return 1
    print("OK - screenshots in", out); return 0

if __name__ == "__main__": sys.exit(main())

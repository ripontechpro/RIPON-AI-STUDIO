"""`RiponAIStudio.exe --selftest`: starts the real window, runs a few real operations and writes a report to %TEMP%\\RiponAIStudio-selftest.txt.
build.bat runs it on the PACKAGED program, so a broken bundle (missing asset, missing DLL, bad import) is found before anyone else sees it."""
import os, sys, tempfile, traceback

def run():
    lines = []; ok = True
    def step(name, fn):
        nonlocal ok
        try: lines.append(f"OK    {name}" + (f"  {fn()}" if True else ""))
        except Exception: ok = False; lines.append(f"FAIL  {name}\n" + traceback.format_exc())
    try:
        import numpy as np
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QPixmap
        from rstudio import paths, APP_NAME, VERSION
        from rstudio.engine.settings import Settings
        from rstudio.engine.recovery import Recovery
        from rstudio.engine.document import Document
        from rstudio.engine import adjust, modelpack
        from rstudio.ui import theme
        from rstudio.ui.main_window import MainWindow
        td = tempfile.mkdtemp(); app = QApplication.instance() or QApplication([]); theme.apply_theme(app, "dark")
        step("version", lambda: f"{APP_NAME} {VERSION}")
        step("logo asset", lambda: (_ for _ in ()).throw(RuntimeError("logo missing: " + paths.asset("logo_512.png"))) if QPixmap(paths.asset("logo_512.png")).isNull() else "found")
        step("icon asset", lambda: (_ for _ in ()).throw(RuntimeError("icon missing")) if not os.path.isfile(paths.asset("logo.ico")) else "found")
        s = Settings(os.path.join(td, "s.json")); w = MainWindow(s, Recovery(os.path.join(td, "rec"))); w.show(); app.processEvents()
        step("main window", lambda: "shown")
        d = Document.from_image(np.random.RandomState(0).randint(0, 255, (300, 400, 3)).astype(np.uint8), "selftest"); w.open_document(d); app.processEvents()
        for key in ("photo", "adjust", "ai", "doc", "passport", "layout", "settings", "home"): step("page " + key, lambda k=key: (w.goto(k), app.processEvents(), "")[2])
        step("adjustment", lambda: (d.apply_to_layer(d.active_id, lambda a: adjust.ADJUSTMENTS["brightness_contrast"].apply(a, brightness=20), "t"), "")[1])
        step("export png", lambda: f"{os.path.getsize(d.export(os.path.join(td, 't.png')))} bytes")
        step("save project", lambda: f"{os.path.getsize(d.save(os.path.join(td, 't.rai')))} bytes")
        step("ai status", lambda: ", ".join(f"{c['key']}={c['status']}" for c in w.ai.capabilities()[:4]))
        step("model folder", lambda: f"{s.models_dir()} ({len(modelpack.scan(s.models_dir()))} groups)")
        w.close()
    except Exception:
        ok = False; lines.append("FAIL  startup\n" + traceback.format_exc())
    out = os.path.join(tempfile.gettempdir(), "RiponAIStudio-selftest.txt")
    try:
        with open(out, "w", encoding="utf-8") as f: f.write(("PASS" if ok else "FAIL") + "\n" + "\n".join(lines) + "\n")
    except OSError: pass
    return 0 if ok else 1

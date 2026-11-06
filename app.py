"""Ripon AI Studio - entry point.   python app.py [file ...]"""
import os, sys, traceback

def _excepthook(t, v, tb):
    msg = "".join(traceback.format_exception(t, v, tb)).replace(os.path.expanduser("~"), "~")        # keep user folder names out of the log
    try:
        from rstudio.paths import user_data_dir
        with open(os.path.join(user_data_dir(), "crash.log"), "a", encoding="utf-8") as f: f.write(msg + "\n")
    except Exception: pass
    sys.__excepthook__(t, v, tb)

def main(argv=None):
    sys.excepthook = _excepthook
    argv = list(sys.argv if argv is None else argv)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from rstudio import APP_NAME
    from rstudio.engine.settings import Settings
    from rstudio.ui import theme
    from rstudio.ui.main_window import MainWindow
    if sys.platform == "win32":
        try:
            import ctypes; ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Ripon.AIStudio")      # own taskbar icon
        except Exception: pass
    app = QApplication(argv); app.setApplicationName(APP_NAME); app.setOrganizationName("Ripon")
    s = Settings(); theme.apply_theme(app, s.get("theme"))
    from rstudio.engine import document as _doc; from rstudio.ui import qttext; _doc.set_text_backend(qttext.render)      # Bengali-correct text; engine falls back to Pillow on any problem
    if "--selftest" in argv: from rstudio import selftest; return selftest.run()
    w = MainWindow(s); w.show()
    files = [a for a in argv[1:] if os.path.isfile(a)]
    if files: w.open_files(files)
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())

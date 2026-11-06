"""Path helpers that work from source AND from a PyInstaller bundle (no hardcoded absolute paths)."""
import os, sys

def bundle_dir():
    """Folder that holds bundled read-only files (assets). PyInstaller sets sys._MEIPASS."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def asset(*parts):
    return os.path.join(bundle_dir(), "assets", *parts)

def app_dir():
    """Folder next to the EXE (frozen) or the project root (source). Used for the optional `models` folder."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def user_data_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    p = os.path.join(base, "RiponAIStudio")
    os.makedirs(p, exist_ok=True)
    return p

def default_models_dir():
    return os.path.join(app_dir(), "models")

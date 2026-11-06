"""Persistent user settings (JSON). API keys are NEVER stored here: providers read them from environment variables."""
import os, json
from .. import paths

DEFAULTS = {
    "theme": "dark",
    "export_dir": "",
    "models_dir": "",
    "bg_model": "u2net_human_seg",
    "wheel_zooms": False,         # False = Photoshop style: wheel scrolls, Ctrl/Alt + wheel zooms
    "max_undo": 40,
    "prefer_gpu": True,
    "recent": [],
    "cloud_enabled": False,       # cloud providers stay off until the user turns them on
    "cloud_endpoint": "",
    "custom_presets": [],         # [[name, width_mm, height_mm], ...] photo sizes saved by the user
}

class Settings:
    def __init__(self, path=None):
        self.path = path or os.path.join(paths.user_data_dir(), "settings.json")
        self.data = dict(DEFAULTS)
        self.load()
    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f: d = json.load(f)
            if isinstance(d, dict): self.data.update({k: v for k, v in d.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass
    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f: json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False
    def get(self, k): return self.data.get(k, DEFAULTS.get(k))
    def set(self, k, v): self.data[k] = v
    @staticmethod
    def legacy_models_dir():
        """Models folder of the earlier Ripon Computer app (%LOCALAPPDATA%\\RiponComputer\\models), if it exists."""
        la = os.environ.get("LOCALAPPDATA")
        if la:
            d = os.path.join(la, "RiponComputer", "models")
            if os.path.isdir(d): return d
        return ""
    def models_dir(self):
        """Explicit choice > the old Ripon Computer folder (already full of models) > <app>\\models.
        A saved path that is just the unused built-in default is treated as 'not chosen' so the old folder still wins."""
        d = self.data.get("models_dir"); dflt = paths.default_models_dir(); old = self.legacy_models_dir()
        if d and not (old and os.path.normcase(os.path.abspath(d)) == os.path.normcase(os.path.abspath(dflt)) and not os.path.isdir(d)): return d
        return old or dflt
    def custom_presets(self):
        out = []
        for it in self.data.get("custom_presets", []):
            try: out.append((str(it[0]), float(it[1]), float(it[2])))
            except (TypeError, ValueError, IndexError): continue
        return out
    def add_preset(self, name, w, h):
        name = str(name).strip()
        if not name or w <= 0 or h <= 0: return False
        self.data["custom_presets"] = [p for p in self.data.get("custom_presets", []) if p and p[0] != name] + [[name, float(w), float(h)]]; return True
    def remove_preset(self, name): self.data["custom_presets"] = [p for p in self.data.get("custom_presets", []) if p and p[0] != name]
    def clear_recent(self): self.data["recent"] = []
    def remove_recent(self, p):
        a = os.path.abspath(p); self.data["recent"] = [x for x in self.data["recent"] if x != a and x != p]
    def add_recent(self, p, limit=12):
        p = os.path.abspath(p); r = [x for x in self.data["recent"] if x != p]
        self.data["recent"] = ([p] + r)[:limit]
    def recent_existing(self):
        return [p for p in self.data["recent"] if os.path.exists(p)]

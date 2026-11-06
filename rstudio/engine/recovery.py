"""Crash / power-cut protection: unsaved documents are written to a recovery folder every minute and removed again on a clean close or save.
Files stay on this PC only (they are your images - they are deleted when the document is closed or saved)."""
import os, json, time
from .document import Document
from .. import paths

class Recovery:
    def __init__(self, folder=None):
        self.dir = folder or os.path.join(paths.user_data_dir(), "recovery"); os.makedirs(self.dir, exist_ok=True)
    def _p(self, uid, ext): return os.path.join(self.dir, f"{os.path.basename(uid)}{ext}")
    def write(self, uid, name, snapshot):
        """Safe to call from a worker thread (the snapshot is immutable data)."""
        Document.write_snapshot(snapshot, self._p(uid, ".rai"))
        with open(self._p(uid, ".json"), "w", encoding="utf-8") as f: json.dump(dict(uid=uid, name=name, time=time.time()), f)
    def clear(self, uid):
        for ext in (".rai", ".json", ".rai.part"):
            try: os.remove(self._p(uid, ext))
            except OSError: pass
    def pending(self):
        out = []
        for fn in os.listdir(self.dir):
            if not fn.endswith(".json"): continue
            try:
                with open(os.path.join(self.dir, fn), "r", encoding="utf-8") as f: m = json.load(f)
                rai = self._p(m["uid"], ".rai")
                if os.path.isfile(rai): out.append(dict(uid=m["uid"], name=m.get("name", "Recovered"), time=m.get("time", 0), path=rai))
            except (OSError, ValueError, KeyError): continue
        return sorted(out, key=lambda d: d["time"])
    def open(self, item):
        d = Document.load(item["path"]); d.name = item["name"]; d.path = ""; d.dirty = True; return d
    def clear_all(self):
        for it in self.pending(): self.clear(it["uid"])

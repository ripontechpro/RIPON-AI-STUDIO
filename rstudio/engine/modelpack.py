"""Backup / restore of the downloaded AI models (one .zip that a friend can restore on another PC).

Safety rules (a model pack is data from someone else, so restoring it must never be able to write outside the models folder or smuggle in programs):
  * only files listed in the pack's manifest are restored; everything else in the zip is ignored
  * every path must be relative, inside one of the known model folders, without '..' / drive letters / links
  * script-like file types are refused; .exe / .dll are accepted ONLY inside the Real-ESRGAN folders (that program is part of the upscaler)
  * every file is checked against its SHA-256 from the manifest before it replaces anything (corrupt / edited packs fail cleanly)
  * files are written as <name>.part and renamed at the end, so an interrupted restore never leaves half a model behind
The manifest hash protects against damage, NOT against a malicious author: only restore packs from someone you trust."""
import os, io, json, time, shutil, zipfile, hashlib, posixpath
from .. import APP_NAME, VERSION

FORMAT = "ripon-models-1"
GROUPS = [   # folder, label
    ("rembg", "Background removal (rembg models)"), ("modnet", "Portrait cut-out (MODNet)"), ("realesrgan-ncnn", "Upscaler (Real-ESRGAN ncnn)"),
    ("realesrgan", "Upscaler (Real-ESRGAN, other)"), ("lama", "Object removal (LaMa)"), ("gfpgan", "Face restore (GFPGAN)"), ("codeformer", "Face restore (CodeFormer)"),
    ("yunet", "Face finder (YuNet)"), ("insightface", "Face finder (InsightFace)"), ("document", "Document models"),
]
GROUP_KEYS = [k for k, _ in GROUPS]
PROGRAM_FOLDERS = ("realesrgan-ncnn", "realesrgan")
BLOCKED_EXT = {".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".msi", ".lnk", ".scr", ".com", ".hta", ".jar", ".reg", ".py", ".pyc", ".pyw", ".sh", ".dll_", ".cpl", ".url"}
PROGRAM_EXT = {".exe", ".dll"}
CHUNK = 1 << 20

class PackError(Exception): pass

def _sha_file(path, ctx=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b: break
            h.update(b)
            if ctx: ctx.check()
    return h.hexdigest()

def safe_relpath(rel):
    """Return the normalised 'folder/sub/file' path, or raise PackError. Pure string checks - nothing touches the disk."""
    if not isinstance(rel, str) or not rel or "\x00" in rel or "\\" in rel or rel.startswith("/") or (len(rel) > 1 and rel[1] == ":"): raise PackError(f"unsafe path: {rel!r}")
    parts = rel.split("/")
    if any(p in ("", ".", "..") or p.endswith((" ", ".")) or ":" in p for p in parts): raise PackError(f"unsafe path: {rel!r}")
    if len(parts) < 2 or parts[0] not in GROUP_KEYS: raise PackError(f"not inside a known model folder: {rel!r}")
    ext = posixpath.splitext(parts[-1])[1].lower()
    if ext in BLOCKED_EXT: raise PackError(f"file type {ext} is not allowed: {rel!r}")
    if ext in PROGRAM_EXT and parts[0] not in PROGRAM_FOLDERS: raise PackError(f"program file outside the upscaler folder: {rel!r}")
    return "/".join(parts)

def scan(models_dir):
    """[{key, label, files, bytes}] for every known model folder that contains files."""
    out = []
    for key, label in GROUPS:
        root = os.path.join(models_dir, key); n = size = 0
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                if f.endswith(".part"): continue
                try: size += os.path.getsize(os.path.join(dp, f)); n += 1
                except OSError: pass
        if n: out.append(dict(key=key, label=label, files=n, bytes=size))
    return out

def _list_files(models_dir, keys):
    items = []
    for key in keys:
        root = os.path.join(models_dir, key)
        for dp, dn, fn in os.walk(root):
            dn.sort()
            for f in sorted(fn):
                if f.endswith(".part") or os.path.islink(os.path.join(dp, f)): continue
                full = os.path.join(dp, f); rel = os.path.relpath(full, models_dir).replace(os.sep, "/")
                try: safe_relpath(rel)
                except PackError: continue                         # never put something into a pack that a restore would refuse
                items.append((full, rel, os.path.getsize(full)))
    return items

README = """Ripon AI Studio - model pack
============================
This zip holds AI model files exported from Ripon AI Studio.

To use it on another PC:
  1. Install Ripon AI Studio.
  2. Open  Settings > Model backup & restore > Restore models...
  3. Choose this zip file and confirm.
Nothing else is needed. Only restore packs from people you trust.
"""

def create_backup(models_dir, out_path, keys=None, ctx=None):
    """Write the selected model folders into one zip. Returns dict(files, bytes, path). Cancel-safe: the final file only appears when complete."""
    keys = [k for k in (keys or [g["key"] for g in scan(models_dir)]) if k in GROUP_KEYS]
    items = _list_files(models_dir, keys)
    if not items: raise PackError("There are no model files to back up.")
    total = sum(s for _, _, s in items) or 1; done = 0; manifest = []; tmp = out_path + ".part"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            z.writestr("README.txt", README)
            for full, rel, size in items:
                h = hashlib.sha256(); zi = zipfile.ZipInfo(rel, time.localtime(os.path.getmtime(full))[:6]); zi.compress_type = zipfile.ZIP_STORED
                with open(full, "rb") as src, z.open(zi, "w", force_zip64=True) as dst:
                    while True:
                        b = src.read(CHUNK)
                        if not b: break
                        dst.write(b); h.update(b); done += len(b)
                        if ctx: ctx.progress(0.98 * done / total, f"Backing up {rel}")
                manifest.append(dict(path=rel, size=size, sha256=h.hexdigest()))
            z.writestr("manifest.json", json.dumps(dict(format=FORMAT, app=APP_NAME, version=VERSION, created=time.strftime("%Y-%m-%d %H:%M:%S"), files=manifest), indent=1))
        os.replace(tmp, out_path)
    except BaseException:
        try: os.remove(tmp)
        except OSError: pass
        raise
    if ctx: ctx.progress(1.0, "Backup finished")
    return dict(files=len(manifest), bytes=sum(m["size"] for m in manifest), path=out_path)

def inspect_backup(path):
    """Read only the manifest. Returns dict(groups=[{key,label,files,bytes}], files=[...], total=bytes, problems=[...]); never extracts anything."""
    try:
        with zipfile.ZipFile(path) as z:
            if "manifest.json" not in z.namelist(): raise PackError("This zip is not a Ripon model pack (manifest.json is missing).")
            m = json.loads(z.read("manifest.json").decode("utf-8")); names = set(z.namelist())
    except (zipfile.BadZipFile, OSError, ValueError, UnicodeDecodeError) as e:
        raise PackError(f"Cannot read this file as a model pack ({type(e).__name__}).")
    if m.get("format") != FORMAT: raise PackError("This model pack has an unknown format version.")
    good, problems = [], []
    for e in m.get("files", []):
        try:
            rel = safe_relpath(e["path"]); size = int(e["size"]); sha = str(e["sha256"]).lower()
            if len(sha) != 64 or size < 0: raise PackError("bad manifest entry")
            if rel not in names: raise PackError(f"listed but missing from the zip: {rel}")
            good.append(dict(path=rel, size=size, sha256=sha))
        except (PackError, KeyError, ValueError, TypeError) as ex: problems.append(str(ex))
    groups = {}
    for e in good:
        k = e["path"].split("/")[0]; g = groups.setdefault(k, dict(key=k, label=dict(GROUPS)[k], files=0, bytes=0)); g["files"] += 1; g["bytes"] += e["size"]
    programs = [e["path"] for e in good if posixpath.splitext(e["path"])[1].lower() in PROGRAM_EXT]        # the app will RUN these (the upscaler), so the user is told
    return dict(groups=[groups[k] for k in GROUP_KEYS if k in groups], files=good, total=sum(e["size"] for e in good), problems=problems, programs=programs, created=m.get("created", ""), version=m.get("version", ""))

def restore_backup(path, models_dir, keys=None, overwrite=False, ctx=None):
    """Restore a pack. Returns dict(restored=[..], skipped=[..], failed=[(path, reason)..]). Existing files of the same size are kept unless overwrite=True."""
    info = inspect_backup(path); want = [e for e in info["files"] if keys is None or e["path"].split("/")[0] in keys]
    if not want: raise PackError("Nothing to restore from this pack.")
    os.makedirs(models_dir, exist_ok=True); need = 0
    for e in want:
        t = os.path.join(models_dir, *e["path"].split("/"))
        if overwrite or not (os.path.isfile(t) and os.path.getsize(t) == e["size"]): need += e["size"]
    free = shutil.disk_usage(models_dir).free
    if need > free: raise PackError(f"Not enough free disk space: {need / 1e9:.2f} GB needed, {free / 1e9:.2f} GB free.")
    total = sum(e["size"] for e in want) or 1; done = 0; restored, skipped, failed = [], [], []
    root = os.path.realpath(models_dir)
    with zipfile.ZipFile(path) as z:
        for e in want:
            rel = e["path"]; target = os.path.join(models_dir, *rel.split("/"))
            if os.path.commonpath([root, os.path.realpath(target)]) != root: failed.append((rel, "outside the models folder")); continue            # belt and braces
            if not overwrite and os.path.isfile(target) and os.path.getsize(target) == e["size"]: skipped.append(rel); done += e["size"]; continue
            os.makedirs(os.path.dirname(target), exist_ok=True); tmp = target + ".part"; h = hashlib.sha256(); got = 0
            try:
                with z.open(rel) as src, open(tmp, "wb") as dst:
                    while True:
                        b = src.read(CHUNK)
                        if not b: break
                        got += len(b)
                        if got > e["size"]: raise PackError("file is larger than the manifest says")
                        dst.write(b); h.update(b); done += len(b)
                        if ctx: ctx.progress(0.98 * done / total, f"Restoring {rel}")
                if got != e["size"] or h.hexdigest() != e["sha256"]: raise PackError("checksum mismatch - the pack is damaged or was edited")
                os.replace(tmp, target); restored.append(rel)
            except PackError as ex: failed.append((rel, str(ex)))
            except (OSError, zipfile.BadZipFile, RuntimeError) as ex: failed.append((rel, f"{type(ex).__name__}: {ex}"))
            finally:
                if os.path.exists(tmp):
                    try: os.remove(tmp)
                    except OSError: pass
    if ctx: ctx.progress(1.0, "Restore finished")
    return dict(restored=restored, skipped=skipped, failed=failed)

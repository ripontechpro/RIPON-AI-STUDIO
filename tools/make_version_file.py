"""Writes build/version_info.txt (Windows 'Details' tab: product, company, version, description) for PyInstaller.
An EXE that carries proper version information and an icon looks far less suspicious to Windows and to antivirus programs."""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
from rstudio import APP_NAME, VERSION

def main():
    nums = (re.findall(r"\d+", VERSION) + ["0", "0", "0", "0"])[:4]; tup = ", ".join(nums); dotted = ".".join(nums)
    text = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({tup}), prodvers=({tup}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Ripon'),
      StringStruct('FileDescription', '{APP_NAME} - photo editing, document cleanup, passport and ID sheets'),
      StringStruct('FileVersion', '{dotted}'),
      StringStruct('InternalName', 'RiponAIStudio'),
      StringStruct('LegalCopyright', 'Copyright (c) Ripon'),
      StringStruct('OriginalFilename', 'RiponAIStudio.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{dotted}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    out = os.path.join(ROOT, "build"); os.makedirs(out, exist_ok=True); p = os.path.join(out, "version_info.txt")
    with open(p, "w", encoding="utf-8") as f: f.write(text)
    print("wrote", p, "version", dotted)

if __name__ == "__main__": main()

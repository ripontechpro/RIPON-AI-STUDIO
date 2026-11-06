# Ripon AI Studio - Windows build guide (CMD)

## The short way: `build.bat`

```
cd /d "C:\Path\To\Ripon-AI-Studio"
build.bat /clean
```
It finds Python 3.10-3.13, creates a clean build environment (`.venv-build`), installs everything, runs the tests and a real-Qt check, writes the Windows
version information, builds the program (folder build, no UPX), **starts the packaged program once in `--selftest` mode** to prove the bundle works,
makes `dist\RiponAIStudio-<version>-win64.zip` and `dist\SHA256.txt`.
Options: `/notest` (quick rebuild), `/rembg` (bundle extra background models), `/directml` (GPU on any Windows GPU), `/installer` (Setup.exe via Inno Setup 6).
Code signing and antivirus advice: **SHARING.md**. Status of this guide: `build.bat` and the spec were written against the real project and linted, but could not be
executed on Windows by the author's tooling - the first run on your PC is the real test.

---

## The manual way (what `build.bat` does, step by step)

All commands are plain **CMD** (not PowerShell). Replace `C:\Path\To\Ripon-AI-Studio` with the real folder that contains `app.py`.
Python **3.12 (64-bit)** is the safest choice (3.10 - 3.13 work; the newest Python releases may not have `onnxruntime` / `rembg` wheels yet).

> Status of this guide: the commands were written against the real project files (entry point `app.py`, spec `ripon_ai_studio.spec`,
> tests in `tests\`). They could **not** be executed on Windows by the author's tooling, and **no EXE has been built yet** - step 11 is where you find out.

## 0. Once: check Python

```
py -3.12 --version
```
If that fails, install Python 3.12 from python.org and tick "Add to PATH" / "py launcher".

## 1. Go to the project, create and activate a virtual environment

```
cd /d "C:\Path\To\Ripon-AI-Studio"
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
```
(Prompt now starts with `(.venv)`. Run `.venv\Scripts\activate` again in every new CMD window.)

## 2. Install dependencies  *(needs internet)*

Required:
```
pip install -r requirements.txt
```
Optional features (the app starts without them; Settings > AI models shows what is missing):
```
rem background removal / replacement
pip install rembg onnxruntime
rem ...or, for any Windows GPU instead of onnxruntime:   pip install rembg onnxruntime-directml
rem import PDF pages in Document Studio
pip install pymupdf
```
Skip the two optional lines if you do not need them - `onnxruntime` (MODNet, object removal, face restore) is already part of `requirements.txt`.

## 3. Run from source

```
python app.py
```
Open a file straight away:  `python app.py "C:\Scans\page1.jpg"`

## 4. Self-check on the REAL Qt (do this before building)

```
python tools\qt_selfcheck.py
```
Builds the real window off-screen, visits every page, runs a few edits and writes screenshots to `selfcheck\`. Must print `OK`.
If it prints `FAILED at step: ...`, send me that traceback.

## 5. Run the automated tests

```
python -m unittest discover -s tests -v
```
`tests\test_engine.py` tests the processing engine (documents, layers, undo, adjustments, scan cleanup, passport sheets, AI status, tasks).
`tests\test_ui_smoke.py` runs the UI code against a *fake* Qt - it finds Python mistakes but does not prove the real windows look right (step 4 does).

## 6. Write / refresh the requirements files

```
pip freeze > requirements-lock.txt
```
`requirements.txt` stays the hand-written list; `requirements-lock.txt` records the exact versions you built with.

## 7. AI models  *(optional; separate offline and online steps)*

**If you used the earlier Ripon Computer app, nothing needs to be copied:** Ripon AI Studio automatically uses its folder
`%LOCALAPPDATA%\RiponComputer\models` (for example `C:\Users\<you>\AppData\Local\RiponComputer\models`) and the same file layout.
Check it with: `dir "%LOCALAPPDATA%\RiponComputer\models"` - Settings > Folders shows which folder is in use.
Otherwise the app uses `models\` next to `app.py` / next to `RiponAIStudio.exe`; you can choose any folder in **Settings > Folders**.

| Feature | What you need | Where it goes (inside the models folder) |
|---|---|---|
| Background removal / replacement (MODNet, no rembg needed) | `pip install onnxruntime` and the model file | `modnet\modnet.onnx` |
| Background removal / replacement (rembg models) | `pip install rembg onnxruntime`, plus one model file, e.g. `u2net_human_seg.onnx` (also `isnet-general-use`, `birefnet-general-lite`, `birefnet-portrait`, `silueta`) | `rembg\<model>.onnx` |
| Upscaling | Real-ESRGAN **ncnn-vulkan** Windows build | `realesrgan-ncnn\realesrgan-ncnn-vulkan.exe` and `realesrgan-ncnn\models\*.bin/*.param` |
| Better face finding for passport crop (optional) | OpenCV YuNet model | `yunet\face_detection_yunet_2023mar.onnx` (without it the built-in detector is used) |

Pick the background model in **AI Studio > Background**; models that are installed are used immediately, and the app falls back to an installed one if the selected one is missing.
The folders `lama`, `gfpgan`, `codeformer`, `modnet`, `insightface` and `document` of the old app are left untouched; they will be used once those tools are added to the new app.

* **Online:** AI Studio > *Prepare model* asks first, then downloads the selected model once.
* **Offline:** copy the files by hand. Nothing is ever downloaded or uploaded automatically.

## 8. Install the packaging tool  *(needs internet)*

```
pip install pyinstaller
```

## 9. Build the EXE (folder distribution - recommended)

```
cd /d "C:\Path\To\Ripon-AI-Studio"
.venv\Scripts\activate
pyinstaller --noconfirm --clean ripon_ai_studio.spec
```
The spec file already contains the entry point (`app.py`), the icon (`assets\logo.ico`), the `assets` data folder, all `rstudio` submodules,
and bundles `rembg` / `onnxruntime` / `pymupdf` automatically **if they are installed in this venv**.

## 10. Locate the result

```
dir dist\RiponAIStudio\RiponAIStudio.exe
```
Output folder: `dist\RiponAIStudio\` (copy that whole folder - not just the EXE).

## 11. Test the packaged app

```
dist\RiponAIStudio\RiponAIStudio.exe
```
Check: window opens with the logo on Home - open an image - crop / brush / undo - Adjustments preview - Document Studio preview - build a passport sheet - Export PNG/PDF - Print preview.
If it closes instantly, run it from CMD with a console build to see the error (see Troubleshooting).

Add models to the packaged app (optional):
```
xcopy /E /I /Y models dist\RiponAIStudio\models
```

## 12. Clean and rebuild

```
rmdir /s /q build
rmdir /s /q dist
pyinstaller --noconfirm --clean ripon_ai_studio.spec
```

## 13. Make a zip to hand out

```
tar -a -c -f RiponAIStudio-4.0.0.zip -C dist RiponAIStudio
```
(`tar` ships with Windows 10 1803+ and Windows 11.)

## 14. Single-file EXE (optional, slower start-up, bigger antivirus risk)

```
pyinstaller --noconfirm --clean --onefile --windowed --name RiponAIStudio --icon assets\logo.ico --add-data "assets;assets" --collect-submodules rstudio app.py
```
Result: `dist\RiponAIStudio.exe`. The `models` folder must then sit next to that EXE. Optional packages (rembg etc.) are **not** collected by this short command - use the spec file if you need them.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'rstudio...'` after building | Build from the project folder with the spec file (it sets `pathex`); the `rstudio` folder must be next to `app.py`. |
| `ModuleNotFoundError: PySide6` when running | venv not active: `.venv\Scripts\activate`, then `pip install -r requirements.txt`. |
| `Could not find the Qt platform plugin "windows"` | Delete `build` and `dist`, rebuild with `--clean`; make sure only PySide6 (not PyQt) is installed: `pip list`. |
| EXE starts then vanishes | Temporarily set `console=True` in `ripon_ai_studio.spec`, rebuild, run from CMD to read the error. Crashes are also logged to `%APPDATA%\RiponAIStudio\crash.log`. |
| `ImportError: DLL load failed` (opencv / onnxruntime) | Install the *Microsoft Visual C++ Redistributable 2015-2022 (x64)*. |
| Background removal says "Needs setup" | Settings > AI models lists exactly what is missing (package or model file and the folder it must be in). |
| Both `onnxruntime` and `onnxruntime-directml` installed | `pip uninstall onnxruntime onnxruntime-directml` then install only one. |
| Antivirus flags the EXE | Typical for PyInstaller. Prefer the folder build, and whitelist or sign the EXE. |
| Printed size is slightly off | In the printer dialog choose **100% / Actual size** (not "Fit to page"); some drivers add their own margins. |

## Release checklist

- [ ] `python -m unittest discover -s tests` passes
- [ ] `python tools\qt_selfcheck.py` prints OK
- [ ] Built with the spec file in a **fresh** venv (so no stray packages are bundled)
- [ ] Packaged app opens, shows the logo, opens/saves/exports an image, undo/redo works
- [ ] Document cleanup preview + apply + batch on 3 real scans (compare against the originals; check "Ink kept")
- [ ] Passport sheet: print one page at 100% and measure a photo with a ruler
- [ ] Missing optional models: app still starts and shows clear messages
- [ ] Put your own photo at `assets\ripon_photo.jpg` (optional) before building to show it on the Home screen
- [ ] Zip the `dist\RiponAIStudio` folder and test it on a PC that has no Python installed

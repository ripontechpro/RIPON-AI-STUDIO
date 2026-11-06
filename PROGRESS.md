# Ripon AI Studio - PROGRESS

Last update: 2026-11-02.  Version 4.0.0-dev.  Plain statements only: **built and tested** means a test ran here; **written, not run** means the code exists but could not be executed in this environment.

## Environment limits of this work session (honest blockers)
- Linux sandbox, no internet, **PySide6 not installable** -> the real GUI was never started here.
- **No Windows**, no PyInstaller -> **no EXE was built.**
- No `rembg` / Real-ESRGAN models available -> AI model paths were tested only through their *error/availability* behaviour and a fake Real-ESRGAN command-line stub.

## Architecture (one application)
```
app.py                      single entry point
rstudio/
  engine/   (Qt-free, unit tested)
    document.py             ONE shared document model: layers (raster / text / shape), selection, history (undo/redo), compositing, export, .rai project
    adjust.py               12 adjustments (brightness/contrast, levels, curves, exposure, hue/sat, colour balance, sharpen, blur, denoise, grayscale, auto levels, paper whitening)
    docstudio.py            scan cleanup, page cut-out, deskew, margin trim, batch, PDF import/export
    passport.py             passport sheets, Bank Photo Duet (1.9 x 1.5 in), ID card front+back (exact mm geometry), face detection + face-aware crop -> normal Documents
    recovery.py             autosave of unsaved work every minute, restore after a crash, deleted on save / close
    ai.py                   honest capability registry + background removal (rembg) + upscale (Real-ESRGAN ncnn CLI) + classical enhance
    core.py                 layout maths, scan restoration, deskew, PDF save (algorithms carried over from the old project, now inside the package)
    tasks.py / settings.py  shared task manager (progress, cancel) / settings (no API keys stored)
  ui/       (PySide6)
    main_window.py          the ONE window: nav, tool column, option bar, tabs, panels, menus, status bar, tasks, print preview
    canvas.py               zoom/pan, before-after, selection, crop, brush, eraser, text, shapes, picker, move
    panels.py               Image, Adjustments, AI Studio, Document Studio, Passport & ID, Layout Studio, Layers
    home.py, settings_page.py, widgets.py, theme.py, icons.py, qtbridge.py
assets/                     logo (png, ico)
tests/                      test_engine.py, test_ui_smoke.py (+ fake Qt), tools/qt_selfcheck.py (run on Windows)
```
The old project's separate apps and files are no longer part of this project (only the tested algorithms live on in `rstudio/engine/core.py`). The Layout Editor is now a workspace (Layout Studio) of the same window: same canvas, layers, undo, files.

## Milestones
| Phase | State |
|---|---|
| 1 Inspect project | done (entry point was `Photostudio.py`, Layout Editor was a separate window) |
| 2 Design + architecture | done |
| 3 Home screen + main window | written, **not run on real Qt** |
| 4 Layout Editor integrated | done as a workspace on the shared Document (page setup, place images, text, shapes, align, margins, print preview) - written, not run |
| 5 Shared document / canvas / layers / undo | engine **tested**; canvas written, not run |
| 6 Photo + document tools | engine **tested**; panels written, not run |
| 7 Real AI models | background removal + upscale wired (need models); others marked Planned |
| 8 Testing | 265 automated tests pass (engine + UI against fake Qt) |
| 9 Windows packaging | spec + guide written; **EXE not built** |
| 10 CMD guide | `BUILD_WINDOWS.md` |

## Test results (this environment)
- `python -m unittest discover -s tests` -> **265 tests, all pass**.
- Engine: document ops, immutability, undo/redo exactness, history cap + memory budget, alpha compositing, partial re-composite = full composite, selection-limited edits, crop/rotate/flip geometry, text/shape re-editing, `.rai` save/load, export (PNG/JPG/WebP/BMP/TIFF/PDF, DPI), every adjustment (alpha kept, direction correct), scan cleanup on a synthetic rotated + shadowed scan (paper whitened, skew corrected, ink retained >85%, no dark wedges, coloured stamp kept in B&W mode), batch with a corrupt file and with cancel, passport sheet capacity/positions/page spill/export size, AI availability reporting, Real-ESRGAN CLI contract (stub), task progress/cancel/error, settings.
- UI: 12 smoke tests drive MainWindow + every panel against a **fake Qt** (`tests/qt_stub.py`): navigation, open, undo/redo, all adjustments apply, document preview/apply, passport build, layout actions, AI failure messages, save/export, theme, tab close, text re-edit. This finds Python mistakes only.
- Bugs found by the tests and fixed: hue/saturation changed pixels at default settings; gray mode re-introduced colour noise via "preserve black text"; auto-crop kept dark wedges of a rotated scan (now cuts the page out first); infinite-history memory growth on large pages.

## Added after the first review (things a computer-service shop needs)
- **Bank Photo Duet** (whole duet 1.9 x 1.5 in = 570 x 450 px at 300 DPI, two photos side by side / stacked / best fit, optional second photo, page spill, cut marks).
- **ID card front + back** on one page at exact size (default ISO ID-1 85.6 x 54 mm, editable), front = open document, back = another open document.
- **Auto-crop to face** (OpenCV Haar cascade, frontal faces; places an adjustable crop box, never changes the photo until you press Enter). Tested on a real photograph.
- **Your own photo sizes** can be saved as presets (NID, visa, ...); the app does not guess official sizes.
- **Bengali text**: Bengali fonts are preferred, a Qt text backend shapes conjunct letters correctly (written, not run), Pillow+Raqm is the fallback, and the app warns when a Bengali font or shaping is missing.
- **Crash protection**: unsaved documents are autosaved every minute and offered back after an unexpected exit; recovery copies are deleted on save / close. The crash log hides your user-folder name.
- Memory budget for undo history on large pages, text/shape re-editing (Layer > Edit text / shape).

## First real Windows run (reported by the owner)
- The app starts and the Settings page renders correctly on Windows (screenshot received).
- Bug found there and fixed: after 'Prepare model' the app said the model file was missing because rembg stored it in `C:\Users\<user>\.u2net` instead of our `models\rembg`. The app now searches every place rembg may use, copies the file into `models\rembg`, and reports the folders it searched if nothing was downloaded. (5 tests)
- The owner's earlier models folder (`%LOCALAPPDATA%\\RiponComputer\\models`: rembg, realesrgan-ncnn, lama, gfpgan, codeformer, ...) is now found and reused automatically with the old layout; background model is selectable and falls back to an installed one; Real-ESRGAN x4plus runs at 4x and is resized to the requested scale (the old app's behaviour); optional YuNet face model. (13 tests)
- Second real-run finding: with the old folder Upscaling became Ready, but background removal still said the rembg file was missing. The earlier app also supported MODNet (`modnet\modnet.onnx`), which is in the owner's folder, so MODNet matting was ported (onnxruntime only, no rembg) and background engines now fall back automatically to whatever can run (bria-rmbg never automatically: non-commercial licence). 'Prepare model' now reports rembg's version, where the session loaded the file from, and what each searched folder contains; unrecognised `.onnx` names in the rembg folder are listed. (9 tests, MODNet tested end-to-end on a hand-built ONNX file, not on the real weights)
- Left-menu labels were cut ("Docu...udio"): now two-line labels.

## Next candidates
The owner already has LaMa, GFPGAN, CodeFormer and MODNet weights in the models folder, so porting those tools into AI Studio is now the quickest way to add object removal and face restore.

## Old models now used by the new tools, backup/restore, release build
- **Object removal (LaMa)**, **face restore (CodeFormer / GFPGAN, ONNX)** and **MODNet** were ported from the earlier app (same model files and folders). Object removal: 'Mark objects' paints a mask layer with the brush, 'Remove' fills only those areas; originals stay in their layers. Face restore aligns each face (YuNet landmarks, or Haar with estimated eyes), restores it at 512 px and blends it back through a soft oval. Both keep the original below as a layer. Tested end-to-end with hand-built stand-in ONNX files (tensor shapes of the real networks), NOT with the real weights.
- **Model backup / restore** (`engine/modelpack.py`, Settings page): one zip with a manifest of SHA-256 hashes; restore refuses unsafe paths, scripts, programs outside the upscaler folder, anything not in the manifest, and checks every file's hash before it replaces anything. 21 tests including hostile packs.
- **Release build**: `build.bat` (clean venv -> tests -> real-Qt check -> version info -> PyInstaller folder build without UPX -> `--selftest` of the packaged program -> optional signing -> zip + SHA-256), `installer.iss` (Inno Setup), `SHARING.md` (why antivirus / SmartScreen warn, signing, VirusTotal, false-positive reports), `docs/README-FIRST.txt` for users. The batch file was linted (labels, quoting, CRLF) but never executed on Windows.

## Owner's feedback round 3 (shop workflow gaps) - all added
- **Print wizards** (Print menu, Home cards, Passport panel): Passport sheet, **Bank Photo Duet**, **NID / ID card on A4**. Pick the picture(s) from open documents or files; the NID wizard finds the card edges in a photo of the card, straightens it and prints front + back at exact size (default 85.6 x 54 mm, editable) on A4 with optional thin border / cut marks.
- **Perspective crop tool** (P): four draggable corners, 'Find corners' auto-detect, output size presets (card, A4, passport, 4x6, automatic), turn-90 button, Enter applies; undo restores the original.
- **Pages and drag-and-drop**: drop picture files onto the page to place them as layers; Ctrl+V pastes a clipboard picture; Ctrl+C copies the layer; Layer > Copy layer to document; 'Add open document as layer'; 'New A4 page from pictures'; 'Send picture to a new A4 page'.
- **Move tool upgrades**: eight resize handles (corners keep proportions, Shift = free), magnetic snapping to page edges / centre / margins / other layers (hold Alt to switch off), exact size and position in millimetres, fit / fill page, rotate / flip layer, rotate the whole picture by any angle.
- 18 new tests (engine geometry, perspective maths on a synthetic photographed card, snapping, wizards, drop / paste / handles through the UI against fake Qt).

## Owner's feedback round 4 - 'recent history delete' and 'tools do not work like Photoshop'
- **Recent history**: 'Clear history' and 'Remove from list' (also the Delete key) on the Home screen, 'Clear recent list' in File > Open recent, and Settings > Mouse, history and privacy (also deletes autosave recovery copies). Only the list is cleared - pictures are never deleted.
- **Selections are now real pixel masks**: marquee (rectangle / ellipse), lasso, polygon lasso, magic wand (tolerance, contiguous, sample all layers); Shift = add, Alt = subtract, Shift+Alt = intersect; Select menu: all, deselect, inverse, feather, expand, contract; marching ants follow the real shape; feathered edges blend softly.
- **Edit with a selection** (Photoshop shortcuts): Delete clears (on the Background layer it paints the background colour), Alt+Backspace / Ctrl+Backspace fill with foreground / background, Ctrl+J layer via copy (duplicates the layer when nothing is selected), Ctrl+Shift+J layer via cut, dragging INSIDE a selection with the Move tool moves the selected pixels (they become their own layer). Adjustments, brush, eraser, bucket and gradient only touch the selection.
- **New brush engine**: hardness (soft / hard), size, opacity, smooth stamped strokes with no gaps, `[` `]` size, Shift+`[` `]` hardness, X swaps and D resets foreground / background colours, Shift+click = straight line, Alt+click = colour picker, painting outside a smaller picture works (the layer grows), eraser paints the background colour on the Background layer (option for transparent).
- **New tools**: clone stamp (Alt+click = source), paint bucket, gradient (linear / radial), zoom tool, polygon lasso, lasso, magic wand. Text tool: click and type (a dialog), click existing text anywhere in its box to edit.
- **View**: the mouse wheel scrolls, Shift+wheel scrolls sideways, Ctrl / Alt + wheel zooms (Settings can make the plain wheel zoom). Crop: corner handles keep the ratio, double-click applies.
- 41 new tests (selection / brush maths, and the real canvas code driven with fake mouse events).

## Owner's feedback round 5
- **ID card auto edge detection** (`engine/cards.py`): four independent detectors (difference from the background, colour, two edge detectors) propose rectangles, scored by rectangularity and the 85.6 : 54 card proportions; overlaps removed; best ones returned in reading order. One-click **Auto-crop ID card** (Perspective bar, Image menu): one card -> straightened and cropped to exact ID-1 size in place (Ctrl+Z undoes); two cards on one scan -> front and back open as two tabs. The NID wizard can take **both sides from one picture** (with a swap box). 13 tests on synthetic scans (white page + shadow, dark background, grey table with noise, strong perspective, two cards, faint white card on white, portrait card, big scans); real scans may differ - the tool always shows what it found and the manual 4-corner perspective crop remains.
- **Move tool across documents**: drag a layer, or selected pixels, out of the page and release on ANOTHER DOCUMENT'S TAB: a copy goes into that document (source untouched, Ctrl+Z not needed); released anywhere else it snaps back. Copy / Layer > Copy to document / Ctrl+C now copy only the selected part when there is a selection.
- **Ported from Photostudio.py** (re-implemented, tested): **Retouch workspace** - Photo Doctor (colour cast, exposure, dark shadows, noise, softness, red eyes; leaves a good picture alone), skin retouch (smoothing that keeps texture, tone-up, shine fix, small-spot removal, never over eyes / brows / mouth), red-eye fix, **save JPG under N KB** (online forms), caption bar (Bengali works), watermark layer; **Document Studio**: split several documents on one scan, extract a transparent signature.
- Still **not ported** from Photostudio.py: customer jobs / accounts database, passport quality report and head-size check, clothing (dress) overlay, hair colour, edge-repair brush for cut-outs, print-sheet naming / templates, external editor hand-off. Ask for the ones you use.

## Not tested (cannot be, here)
Real Qt rendering and layout, the Qt Bengali text renderer, face detection on photos other than the one test image, mouse/keyboard behaviour, real printing, GPU, real rembg / Real-ESRGAN runs, PDF import (needs pymupdf), Windows EXE start-up and packaged asset paths, light-theme appearance, performance on 12+ MP photos.

## Known limitations
- Customer job / accounts database from the old app is not included (not requested; say if you need it).
- Planned, not implemented: object removal / inpainting (LaMa), face restoration, old-photo restoration (they existed in the old AI Studio and were not carried over), colorization, AI generation, image-to-image. The Settings page and AI panel mark them "Planned".
- Old `.rproj` layout projects cannot be opened yet (new format is `.rai`).
- Curves are three sliders, not a draggable curve. No quick-selection brush, no healing brush, smudge, dodge / burn, blur / sharpen brushes or layer styles. The Move tool lifts selected pixels into a NEW layer (Photoshop moves them within the layer).
- Move tool re-composites the whole page while dragging; on very large pages it may feel slow (brush strokes are optimised).
- Print preview uses the document's physical size as the page size; some printer drivers add margins - print at 100%.

## Next steps
1. Run `python tools\qt_selfcheck.py` on Windows and fix whatever real Qt reports.
2. Build with the spec and test the packaged EXE (checklist in `BUILD_WINDOWS.md`).
3. Add LaMa / GFPGAN-CodeFormer / old-photo tools to AI Studio.

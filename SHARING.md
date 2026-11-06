# Sharing Ripon AI Studio safely (and why Windows may still complain)

You wrote this program and it contains no virus. A warning from Windows or an antivirus is still very common for a **new, unsigned program made
with PyInstaller**. This is the honest picture and what really helps. (Nobody can promise "zero detections" - but the steps below remove the
causes you control, and the one step that matters most is signing.)

## Why it happens
| What the user sees | What is really going on |
|---|---|
| **"Windows protected your PC"** (SmartScreen) | The file is not code-signed and has no download reputation yet. Not a virus finding. |
| An antivirus quarantines `RiponAIStudio.exe` | Heuristic / machine-learning engines get nervous about *unsigned programs that unpack themselves*. PyInstaller's standard launcher is also used by real malware, so its fingerprint is flagged by some engines - a "false positive". |
| 1-3 engines out of ~70 on VirusTotal flag it | Normal for fresh PyInstaller programs. A signed build and a few false-positive reports usually clear it. |

## What `build.bat` already does for you
- **Folder build, not `--onefile`** (a one-file EXE unpacks itself to a temp folder at start - the behaviour antivirus dislikes most).
- **UPX compression off** (packed files are flagged far more often).
- **Windows "Details" information** (company, product, version, description) and a real icon.
- **No administrator rights requested.**
- A clean virtual environment, pinned tools, tests, a self-test of the packaged program and **SHA-256 checksums** in `dist\SHA256.txt`.

## What you should do for a public release (in this order)
1. **Build on a clean PC** with `build.bat /clean` (not on a computer with other programs that may have infected files).
2. **Sign the program** - the single most effective step.
   - Buy a *code-signing certificate* from a certificate authority (OV or EV), or use a cloud signing service you qualify for (for example
     Microsoft's *Trusted Signing* - check whether it is available for individuals in your country).
   - Then, in the same CMD window, before building:
     ```
     set SIGN_PFX=C:\path\to\your-certificate.pfx
     set SIGN_PASS=your-certificate-password
     build.bat /clean
     ```
     (`signtool.exe` from the Windows SDK must be on PATH. `build.bat` signs the EXE - and the installer with `/installer` - and adds a timestamp.)
   - A *self-signed* certificate does **not** help for the public: Windows does not trust it.
3. **Scan it yourself**: upload `RiponAIStudio-<version>-win64.zip` to <https://www.virustotal.com>. If one or two engines flag it, open that vendor's
   *false-positive / file submission* page and report the file as clean (it takes a few minutes; the detection is usually removed within days).
   For Microsoft Defender use the submission portal: <https://www.microsoft.com/en-us/wdsi/filesubmission> (choose "Software developer").
4. **Publish the checksums** (`dist\SHA256.txt`) on the download page, and tell users how to check them (see `docs\README-FIRST.txt`).
5. **Publish the source code** (for example on GitHub) and put the download in the *Releases* section. Open code builds trust.
6. **Optional - an installer** (`build.bat /installer`, needs the free *Inno Setup 6*): users get a normal Setup.exe, Start-menu entry and uninstaller.
   Sign the installer as well.
7. **Optional, advanced - your own PyInstaller launcher.** The ready-made launcher shipped with PyInstaller is the thing many engines have seen in malware.
   Compiling it yourself produces a different file (needs Visual Studio Build Tools):
   ```
   git clone https://github.com/pyinstaller/pyinstaller.git
   cd pyinstaller\bootloader
   python ./waf all
   cd ..
   pip install .
   ```
   Then run `build.bat` again inside that same Python environment.

## What NOT to do
- Do not tell users to switch their antivirus off. Tell them to verify the checksum, and report the false positive to the vendor yourself.
- Do not use packers, obfuscators or "crypters" to hide the program - that is exactly what makes antivirus programs suspicious.
- Do not bundle downloaded programs you did not build (the upscaler `realesrgan-ncnn-vulkan.exe` is *not* inside the release; users add it with a model pack or download it themselves).

## Giving the program + models to a friend
1. Send the zip (or the Setup.exe) **and** `SHA256.txt`.
2. On *your* PC: **Settings > Model backup & restore > Back up models...**, tick what to include, save the zip. (Large: several GB. Use an NTFS/exFAT drive or a cloud link, and back up group by group if needed.)
3. Your friend installs the program, opens **Settings > Model backup & restore > Restore models...** and picks your zip. Files are checked against their checksums;
   unsafe paths, scripts and unknown programs inside a pack are refused.
4. Tell your friend to only restore packs from people they trust - a pack contains the upscaler program that the app will run.

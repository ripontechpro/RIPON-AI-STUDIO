@echo off
rem ======================================================================================================
rem  Ripon AI Studio - one-click Windows build
rem
rem  build.bat                 normal release build (tests -> real-Qt check -> EXE -> self-test -> zip + hashes)
rem  build.bat /clean          throw away the build environment first (do this for the FINAL release build)
rem  build.bat /notest         skip the tests and the real-Qt check (quick rebuild only)
rem  build.bat /rembg          also bundle rembg (extra background-removal models; big)
rem  build.bat /directml       use onnxruntime-directml (GPU on any Windows GPU) instead of CPU onnxruntime
rem  build.bat /installer      also build Setup.exe with Inno Setup (needs Inno Setup 6 installed)
rem
rem  Optional code signing (the single best way to avoid Windows / antivirus warnings): set these first
rem     set SIGN_PFX=C:\path\to\your-certificate.pfx
rem     set SIGN_PASS=your-certificate-password
rem  Needs signtool.exe from the Windows SDK on PATH. Nothing is signed when SIGN_PFX is not set.
rem ======================================================================================================
setlocal EnableExtensions
cd /d "%~dp0"
title Ripon AI Studio - build
set "APP=RiponAIStudio"
set "VENV=.venv-build"
set "NOTEST="
set "CLEAN="
set "REMBG="
set "DIRECTML="
set "INSTALLER="
:parse
if "%~1"=="" goto parsed
if /I "%~1"=="/notest" set "NOTEST=1"
if /I "%~1"=="/clean" set "CLEAN=1"
if /I "%~1"=="/rembg" set "REMBG=1"
if /I "%~1"=="/directml" set "DIRECTML=1"
if /I "%~1"=="/installer" set "INSTALLER=1"
shift
goto parse
:parsed

echo.
echo [1/9] Looking for Python 3.10 - 3.13 ...
set "PY="
for %%V in (3.12 3.11 3.13 3.10) do (
  if not defined PY (
    py -%%V --version >nul 2>&1
    if not errorlevel 1 set "PY=py -%%V"
  )
)
if not defined PY (
  python --version >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo ERROR: Python was not found. Install Python 3.12 64-bit from python.org and tick "Add python.exe to PATH".
  goto fail
)
echo Using: %PY%

echo.
echo [2/9] Preparing a clean build environment in %VENV% ...
if defined CLEAN if exist "%VENV%" rmdir /s /q "%VENV%"
if not exist "%VENV%\Scripts\python.exe" (
  %PY% -m venv "%VENV%"
  if errorlevel 1 goto fail
)
set "VPY=%VENV%\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 goto fail

echo.
echo [3/9] Installing packages (needs internet the first time) ...
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto fail
if defined DIRECTML (
  "%VPY%" -m pip uninstall -y onnxruntime
  "%VPY%" -m pip install onnxruntime-directml
)
if errorlevel 1 goto fail
"%VPY%" -m pip install pymupdf
if errorlevel 1 echo WARNING: pymupdf could not be installed - PDF import will be missing in this build.
if defined REMBG "%VPY%" -m pip install rembg
if errorlevel 1 goto fail
"%VPY%" -m pip install --upgrade pyinstaller
if errorlevel 1 goto fail

echo.
echo [4/9] Tests ...
if defined NOTEST (
  echo Skipped.
) else (
  "%VPY%" -m unittest discover -s tests
  if errorlevel 1 goto fail
  echo Real Qt check ...
  "%VPY%" tools\qt_selfcheck.py
  if errorlevel 1 goto fail
)

echo.
echo [5/9] Writing the Windows version information ...
"%VPY%" tools\make_version_file.py
if errorlevel 1 goto fail
"%VPY%" -c "from rstudio import VERSION; print(VERSION)" > "build\version.txt"
set /p VER=<"build\version.txt"
echo Version %VER%

echo.
echo [6/9] Building the program (folder build, no UPX) ...
if exist "dist\%APP%" rmdir /s /q "dist\%APP%"
"%VPY%" -m PyInstaller --noconfirm --clean ripon_ai_studio.spec
if errorlevel 1 goto fail
if not exist "dist\%APP%\%APP%.exe" (
  echo ERROR: dist\%APP%\%APP%.exe was not created.
  goto fail
)
copy /y "docs\README-FIRST.txt" "dist\%APP%\README-FIRST.txt" >nul

echo.
echo [7/9] Signing (optional) ...
if defined SIGN_PFX (
  call :sign "dist\%APP%\%APP%.exe"
  if errorlevel 1 goto fail
) else (
  echo SIGN_PFX is not set - the EXE stays UNSIGNED. Windows SmartScreen may warn users. See SHARING.md.
)

echo.
echo [8/9] Testing the PACKAGED program ...
del "%TEMP%\RiponAIStudio-selftest.txt" >nul 2>&1
start /wait "" "dist\%APP%\%APP%.exe" --selftest
if not exist "%TEMP%\RiponAIStudio-selftest.txt" (
  echo ERROR: the packaged program did not write a self-test report. It probably failed to start.
  goto fail
)
type "%TEMP%\RiponAIStudio-selftest.txt"
findstr /b /c:"PASS" "%TEMP%\RiponAIStudio-selftest.txt" >nul
if errorlevel 1 (
  echo ERROR: the packaged program failed its self-test.
  goto fail
)

echo.
echo [9/9] Making the zip file and the checksums ...
set "ZIP=dist\%APP%-%VER%-win64.zip"
if exist "%ZIP%" del "%ZIP%"
tar -a -c -f "%ZIP%" -C dist "%APP%"
if errorlevel 1 goto fail
if defined INSTALLER call :installer
(
  echo SHA-256 checksums for Ripon AI Studio %VER%
  echo.
  echo %APP%-%VER%-win64.zip
  certutil -hashfile "%ZIP%" SHA256 | findstr /v /c:"hash of" /c:"CertUtil"
  echo.
  echo %APP%.exe
  certutil -hashfile "dist\%APP%\%APP%.exe" SHA256 | findstr /v /c:"hash of" /c:"CertUtil"
) > "dist\SHA256.txt"
if exist "dist\%APP%-Setup-%VER%.exe" (
  echo. >> "dist\SHA256.txt"
  echo %APP%-Setup-%VER%.exe >> "dist\SHA256.txt"
  certutil -hashfile "dist\%APP%-Setup-%VER%.exe" SHA256 | findstr /v /c:"hash of" /c:"CertUtil" >> "dist\SHA256.txt"
)

echo.
echo ================================================================================
echo  BUILD FINISHED
echo   Program folder : dist\%APP%\%APP%.exe
echo   Zip to share   : %ZIP%
echo   Checksums      : dist\SHA256.txt   (publish these next to the download)
echo.
echo  Before you publish: read SHARING.md (antivirus / SmartScreen advice, VirusTotal, signing).
echo ================================================================================
endlocal
exit /b 0

:sign
signtool sign /fd SHA256 /f "%SIGN_PFX%" /p "%SIGN_PASS%" /tr http://timestamp.digicert.com /td SHA256 /d "Ripon AI Studio" %1
exit /b %errorlevel%

:installer
set "ISCC="
for %%P in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do if exist %%P set "ISCC=%%~P"
if not defined ISCC (
  echo Inno Setup 6 was not found - skipping Setup.exe. Install it from jrsoftware.org, then run build.bat /installer again.
  exit /b 0
)
"%ISCC%" /DMyAppVersion=%VER% installer.iss
if errorlevel 1 exit /b 1
if defined SIGN_PFX call :sign "dist\%APP%-Setup-%VER%.exe"
exit /b 0

:fail
echo.
echo ================================================================================
echo  BUILD FAILED - read the message above. Common fixes are listed in BUILD_WINDOWS.md.
echo ================================================================================
endlocal
exit /b 1

; Inno Setup 6 script - build.bat /installer runs it.   Needs the program folder from a finished build (dist\RiponAIStudio).
#ifndef MyAppVersion
  #define MyAppVersion "4.0.0"
#endif
#define MyAppName "Ripon AI Studio"
#define MyAppExe "RiponAIStudio.exe"

[Setup]
AppId={{B3F1C7A2-6E4D-4C58-9A1B-52D7E0A93C41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Ripon
DefaultDirName={autopf}\Ripon AI Studio
DefaultGroupName=Ripon AI Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=RiponAIStudio-Setup-{#MyAppVersion}
SetupIconFile=assets\logo.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\RiponAIStudio\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Ripon AI Studio"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\Ripon AI Studio"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Start Ripon AI Studio"; Flags: nowait postinstall skipifsilent

#define AppName "Liquid Memo Widget"
#define AppPublisher "CEQ151"
#define AppURL "https://github.com/CEQ151/liquid-memo-widget"
#define AppExeName "LiquidMemoWidget.exe"
#define AppVersion GetEnv("APP_VERSION")

#if AppVersion == ""
  #define AppVersion "0.0.1"
#endif

[Setup]
AppId={{7F5B01F1-8B1D-4EB1-9C90-37B1F6C4E0B8}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\THIRD_PARTY_NOTICES.md
OutputDir=..\dist\installer
OutputBaseFilename=LiquidMemoWidget-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Auto-update runs this installer silently while the app may still be closing:
; force-close anything holding our files instead of erroring, and never let the
; restart manager relaunch the app itself - the updater helper owns the relaunch.
CloseApplications=force
RestartApplications=no
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile=..\assets\logo.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[InstallDelete]
; Wipe the previous PyInstaller payload before copying the new one. The installer only
; overwrites same-named files, so without this an upgrade leaves orphaned DLLs from the old
; build (e.g. plugins/helpers from a different bundled PySide6 version, since PySide6 is
; unpinned) mixed in with the new ones - a mismatched Qt/GL DLL can break composition (black
; QOpenGLWidget) without crashing. _internal is entirely installer-owned and regenerated on
; every install; user data lives in %APPDATA%, so this is safe. Runs before [Files].
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\LiquidMemoWidget\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
; Auto-start is a user preference the app writes at runtime (startup.py), so the installer must
; NOT create or modify it at install time (ValueType: none = leave it alone). We only delete it
; on uninstall so the HKCU\...\Run "LiquidMemoWidget" value isn't left orphaned, pointing at a
; now-removed exe.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "LiquidMemoWidget"; Flags: uninsdeletevalue

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

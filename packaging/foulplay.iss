; Inno Setup script for FoulPlay.
; Wraps the PyInstaller onedir build (dist\FoulPlay) into a single
; FoulPlay-Setup.exe installer with a Start Menu shortcut and uninstaller.
;
; Build with (after running PyInstaller to produce dist\FoulPlay):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\foulplay.iss

; MyAppVersion must be kept in sync with core/version.py's APP_VERSION.
#define MyAppName "FoulPlay"
#define MyAppVersion "0.4.0"
#define MyAppPublisher "FoulPlay"
#define MyAppExeName "FoulPlay.exe"

[Setup]
AppId={{6C3F2B1E-6E60-4E36-9E6C-0F6B3B7A1E2A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
SetupIconFile=icon.ico
OutputDir=..\dist_installer
OutputBaseFilename=FoulPlay-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\FoulPlay\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; Inno Setup script for the SL2 Windows installer:  iscc /DVERSION=2.1.0 packaging\windows\sl2.iss
; Installs for the current user only (no admin password), into %LOCALAPPDATA%\Programs\SL2.
; Songs are saved in Documents\SL2 Songs and are never touched by an update or an uninstall.
#ifndef VERSION
  #define VERSION "0.0.0"
#endif

[Setup]
AppId={{6C1E2F4A-5B7D-4C3E-9A1F-2D8B7E6F5A41}
AppName=SL2
AppVersion={#VERSION}
AppPublisher=kefirman9000
AppPublisherURL=https://github.com/kefirman9000/SL2
DefaultDirName={localappdata}\Programs\SL2
DefaultGroupName=SL2
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=SL2-Setup-{#VERSION}
SetupIconFile=sl2.ico
UninstallDisplayIcon={app}\SL2.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\..\dist\SL2\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\SL2"; Filename: "{app}\SL2.exe"
Name: "{group}\SL2 songs folder"; Filename: "{userdocs}\SL2 Songs"
Name: "{group}\Uninstall SL2"; Filename: "{uninstallexe}"
Name: "{userdesktop}\SL2"; Filename: "{app}\SL2.exe"; Tasks: desktopicon

[Dirs]
Name: "{userdocs}\SL2 Songs"; Flags: uninsneveruninstall

[Run]
Filename: "{app}\SL2.exe"; Description: "Start SL2"; Flags: nowait postinstall skipifsilent

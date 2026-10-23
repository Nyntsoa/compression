#ifndef AppVersion
#define AppVersion "0.1.0"
#endif

#define AppName "Mihena"
#define ProjectRoot AddBackslash(SourcePath) + ".."
#define ApplicationBundle ProjectRoot + "\dist\Mihena"

[Setup]
AppId={{9141C04C-37F2-4B15-A69D-68B81C4BDAE7}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#ProjectRoot}\dist\installer
OutputBaseFilename=Mihena-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Mihena.exe

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis supplémentaires :"; Flags: unchecked

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Files]
Source: "{#ApplicationBundle}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Mihena.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Mihena.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Mihena.exe"; Description: "Lancer Mihena"; Flags: nowait postinstall skipifsilent

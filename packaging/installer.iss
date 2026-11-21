#define AppName "Odwolania2JSON"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C7B6D7E-2C1B-4A51-9C3E-0D2A0F7E2026}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Odwolania2JSON
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=..\dist\release
OutputBaseFilename=Odwolania2JSON-{#AppVersion}-windows-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\Odwolania2JSON.exe

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Odwolania2JSON\*"; DestDir: "{app}"; Excludes: "config\*,input\*,output\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\config\*"; DestDir: "{app}\config"; Flags: recursesubdirs createallsubdirs onlyifdoesntexist uninsneveruninstall

[Dirs]
Name: "{app}\input"
Name: "{app}\output"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Odwolania2JSON.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Odwolania2JSON.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Odwolania2JSON.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

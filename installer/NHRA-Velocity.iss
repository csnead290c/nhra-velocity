#define MyAppName "NHRA Velocity"
#define MyAppPublisher "NHRA"
#define MyAppExeName "NHRA-Velocity.exe"
#define MyAppVersion GetEnv("NHRA_VELOCITY_VERSION")
#if MyAppVersion == ""
  #define MyAppVersion "0.0.0-development"
#endif

[Setup]
AppId={{A44B1E6E-1D5A-4F04-80FD-6196B38654DE}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\NHRA Velocity
DefaultGroupName=NHRA Velocity
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=NHRA-Velocity-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes

[Files]
Source: "..\dist\NHRA-Velocity\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\NHRA Velocity"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\NHRA Velocity"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch NHRA Velocity"; Flags: nowait postinstall skipifsilent

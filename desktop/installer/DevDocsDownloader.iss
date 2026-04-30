#ifndef MyAppName
  #define MyAppName "DevDocsDownloader"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "1.2.5"
#endif
#ifndef MyAppPublisher
  #define MyAppPublisher "DevDocsDownloader"
#endif
#ifndef MyAppExeName
  #define MyAppExeName "DevDocsDownloader.Desktop.exe"
#endif
#ifndef MyOutputBaseFilename
  #define MyOutputBaseFilename "DevDocsDownloader-Setup-1.2.5"
#endif

[Setup]
AppId={{80A92745-DF95-47D4-BB4D-98E67DABAA1B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename={#MyOutputBaseFilename}
SetupIconFile=..\..\desktop\DevDocsDownloader.Desktop\Assets\DevDocsDownloader.ico
UninstallDisplayIcon={app}\DevDocsDownloader.ico
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\publish\desktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\DevDocsDownloader.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\DevDocsDownloader.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

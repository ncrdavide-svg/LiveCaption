; Inno Setup script for LiveCaption.
; Build with installer\build-installer.ps1 (builds the app with PyInstaller, then compiles this script).
; The speech, punctuation and translation models are not inside the setup (about 4 GB):
; LiveCaption downloads them on first start into %LOCALAPPDATA%\LiveCaption\models.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef PublishDir
  #define PublishDir "..\dist\LiveCaption"
#endif

[Setup]
; Keep this AppId fixed forever: new versions use it to upgrade an existing install, and
; LiveSuite uses it to find the installed version.
AppId={{BB4CDF44-BF66-4723-A67E-C48D9F7D34C6}
AppName=LiveCaption
AppVersion={#AppVersion}
AppVerName=LiveCaption {#AppVersion}
AppPublisher=LiveCaption
DefaultDirName={autopf}\LiveCaption
DefaultGroupName=LiveCaption
DisableProgramGroupPage=yes
SetupIconFile=..\assets\LiveCaption.ico
UninstallDisplayIcon={app}\LiveCaption.exe
OutputDir=..\artifacts\installer
OutputBaseFilename=LiveCaption-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Install for all users (asks for admin), or let the user pick "only for me" (no admin needed).
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#PublishDir}\*"; DestDir: "{app}"; Excludes: "LiveCaption.settings.json"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; PyInstaller file names change between builds: start each upgrade from a clean _internal folder.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\LiveCaption"; Filename: "{app}\LiveCaption.exe"
Name: "{autodesktop}\LiveCaption"; Filename: "{app}\LiveCaption.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LiveCaption.exe"; Description: "{cm:LaunchProgram,LiveCaption}"; Flags: nowait postinstall skipifsilent

[Messages]
italian.FinishedLabel=LiveCaption è installata.%n%nAl primo avvio scarica i modelli di trascrizione, punteggiatura e traduzione (circa 4 GB): serve internet solo quella volta.

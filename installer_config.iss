#define MyAppName "NetPrivacy Verification Tool"
#define MyAppExeName "NetPrivacyTool.exe"
#define MyAppVersion "2.0"
#define MyAppPublisher "TheFirSStYfOreVer"
#define MyAppURL ""
#define MyAppId "NPVT-NetPrivacyTool"
#define MyCoreExeName "npvt_core.exe"
#define MyCoreRelPath "core\\bin\\npvt_core.exe"
#define MyFwRuleBase "NPVT Core"
#define MyPathFlagKey "Software\\NPVT"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\\NetPrivacyTool
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=NetPrivacyTool_Setup
SetupIconFile=app\\assets\\icon.ico
WizardStyle=modern
#ifexist "app\\assets\\side_image.bmp"
WizardImageFile=app\\assets\\side_image.bmp
#endif
#ifexist "app\\assets\\top_logo.bmp"
WizardSmallImageFile=app\\assets\\top_logo.bmp
#endif
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\\assets\\icon.ico
ChangesAssociations=no
UsedUserAreasWarning=no

[Dirs]
Name: "{userappdata}\\{#MyAppName}"
Name: "{app}\\logs"

[Files]
Source: "dist\\NetPrivacyTool.exe"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
Source: "app\\assets\\*"; DestDir: "{app}\\assets"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "app\\data\\*"; DestDir: "{app}\\data"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "links_cache.json,verified_nodes.txt,temp_*.json,*.tmp"
Source: "app\\bin\\*"; DestDir: "{app}\\core\\bin"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "xray.exe"
Source: "app\\bin\\xray.exe"; DestDir: "{app}\\core\\bin"; DestName: "{#MyCoreExeName}"; Flags: ignoreversion

; Optional CLI helper (generated in [Code] when task selected)
; {app}\npvt.cmd

[Icons]
Name: "{autoprograms}\\{#MyAppName}"; Filename: "{app}\\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\\assets\\icon.ico"
Name: "{autodesktop}\\{#MyAppName}"; Filename: "{app}\\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\\assets\\icon.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{sys}\\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#MyFwRuleBase} (In)"" dir=in action=allow program=""{app}\\{#MyCoreRelPath}"" enable=yes profile=any"; Flags: runhidden
Filename: "{sys}\\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#MyFwRuleBase} (Out)"" dir=out action=allow program=""{app}\\{#MyCoreRelPath}"" enable=yes profile=any"; Flags: runhidden

[UninstallRun]
Filename: "{sys}\\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#MyFwRuleBase} (In)"""; Flags: runhidden; RunOnceId: "NPVT_FwIn"
Filename: "{sys}\\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#MyFwRuleBase} (Out)"""; Flags: runhidden; RunOnceId: "NPVT_FwOut"

[UninstallDelete]
Type: files; Name: "{%TEMP}\\npvt_run_*.exe"
Type: filesandordirs; Name: "{%TEMP}\\npvt_configs"
Type: filesandordirs; Name: "{app}\\logs"
Type: filesandordirs; Name: "{userappdata}\\{#MyAppName}"

[Code]
procedure CurPageChanged(CurPageID: Integer);
var
  ResultCode: Integer;
begin
  if CurPageID = wpInstalling then
  begin
    Exec(ExpandConstant('{sys}\\taskkill.exe'), '/f /im {#MyAppExeName} /t', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec(ExpandConstant('{sys}\\taskkill.exe'), '/f /im {#MyCoreExeName} /t', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;

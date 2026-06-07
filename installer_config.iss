;------------------------------------------------------------------------------
; NetPrivacy Verification Tool (NPVT)
; Inno Setup 6 script with isolated core process handling
;------------------------------------------------------------------------------
#define MyAppName "NetPrivacy Verification Tool"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "NPVT Team"
#define MyAppExeName "NetPrivacyTool.exe"
#define MyCoreExeName "nv_backend_core.exe"   ; уникальное имя вместо xray.exe
#define MyIconFile "app\\assets\\icon.ico"

[Setup]
AppId={{5E3E8F2F-6C0F-4E2A-9D4A-5DFBC5A8F1D2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://example.com/npvt
DefaultDirName={autopf}\NPVT
DefaultGroupName={#MyAppName}
DisableDirPage=no
OutputDir=dist
OutputBaseFilename=NetPrivacyTool_Setup
SetupIconFile={#MyIconFile}
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Устанавливаем всё содержимое собранной папки NPVT_Portable в {app}
Source: "dist\NPVT_Portable\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Очищаем временные файлы, если появятся
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\result"

;------------------------------------------------------------------------------
; Pascal Script: изоляция процессов. Проверяем только наши exe: NetPrivacyTool.exe
; и nv_backend_core.exe. НЕ трогаем generic xray.exe или чужие клиенты.
; Используем tasklist + temp file (надежный метод без type mismatch).
;------------------------------------------------------------------------------
[Code]

function IsProcessRunning(const ExeName: string): Boolean;
var
  ResultCode: Integer;
  TmpFile: string;
  Output: AnsiString;
begin
  Result := False;
  TmpFile := ExpandConstant('{tmp}\npvt_proc.tmp');
  Exec(ExpandConstant('{cmd}'),
    '/C tasklist /NH /FI "IMAGENAME eq ' + ExeName + '" > "' + TmpFile + '" 2>&1',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if LoadStringFromFile(TmpFile, Output) then
    Result := (Pos(Lowercase(ExeName), Lowercase(String(Output))) > 0);
  DeleteFile(TmpFile);
end;

function KillProcessByName(const ExeName: string): Boolean;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{cmd}'),
    '/C taskkill /F /IM "' + ExeName + '" >NUL 2>&1',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);
  Result := not IsProcessRunning(ExeName);
end;

function EnsureProcessClosed(const ExeName, FriendlyName: string): Boolean;
var
  R: Integer;
begin
  Result := True;
  if not IsProcessRunning(ExeName) then Exit;

  R := MsgBox(FriendlyName + ' (' + ExeName + ') запущен.' + #13#10 + #13#10 + 'Закрыть автоматически?', mbConfirmation, MB_YESNO or MB_DEFBUTTON1);

  if R = IDYES then
  begin
    if not KillProcessByName(ExeName) then
    begin
      MsgBox('Не удалось закрыть ' + FriendlyName + '. Закройте вручную.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end
  else
  begin
    Result := False;
    Exit;
  end;

  if IsProcessRunning(ExeName) then
  begin
    MsgBox(FriendlyName + ' все ещё работает. Закройте вручную.', mbError, MB_OK);
    Result := False;
  end;
end;

function EnsureAllClosed(): Boolean;
begin
  Result := True;
  if not EnsureProcessClosed('{#MyAppExeName}', 'NetPrivacyTool') then Result := False;
  if not EnsureProcessClosed('{#MyCoreExeName}', 'NPVT backend core') then Result := False;
end;

function InitializeSetup(): Boolean;
begin
  Result := EnsureAllClosed();
end;

function InitializeUninstall(): Boolean;
begin
  Result := EnsureAllClosed();
end;

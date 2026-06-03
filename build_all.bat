@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "RELEASE_DIR=%ROOT%release"

set "PS=powershell -NoProfile -ExecutionPolicy Bypass -Command"

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found in PATH. Install Python 3.8+ and check "Add Python to PATH".
    pause
    exit /b 1
)

echo =========================================
echo   NetPrivacy Tool - Full Build Pipeline
echo =========================================
echo.

:: === CLEAN: remove previous dist artifacts ===
echo [CLEAN] Removing old dist\ contents...
if exist "%ROOT%dist" rd /s /q "%ROOT%dist"
mkdir "%ROOT%dist"

echo [CLEAN] Removing old release\ contents...
if exist "%RELEASE_DIR%" rd /s /q "%RELEASE_DIR%"
mkdir "%RELEASE_DIR%"
echo.

:: === STEP 1: Build EXE with PyInstaller ===
echo [1/4] Building NetPrivacyTool.exe with PyInstaller (forced rebuild)...

if exist "dist\NetPrivacyTool.exe" del /q "dist\NetPrivacyTool.exe" >nul 2>&1

set "APPBIN=%ROOT%app\bin"
set "APPDATA_DIR=%ROOT%app\data"
set "APPASSETS=%ROOT%app\assets"
set "APPICON=%ROOT%app\assets\icon.ico"

set "STAGE_BIN=%ROOT%build\stage_bin"
if exist "%STAGE_BIN%" rd /s /q "%STAGE_BIN%"
mkdir "%STAGE_BIN%"
robocopy "%APPBIN%" "%STAGE_BIN%" /E /NFL /NDL /NJH /NJS >nul
if exist "%STAGE_BIN%\xray.exe" copy /y "%STAGE_BIN%\xray.exe" "%STAGE_BIN%\npvt_core.exe" >nul

python -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --noconsole ^
    --name NetPrivacyTool ^
    --icon "%APPICON%" ^
    --collect-data flet ^
    --collect-submodules flet ^
    --add-data "%STAGE_BIN%;core/bin" ^
    --add-data "%APPDATA_DIR%;app/data" ^
    --add-data "%APPASSETS%;app/assets" ^
    --distpath dist ^
    --workpath build\pywork ^
    --specpath build\pyspec ^
    app\main.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller build failed.
    pause
    exit /b 1
)

if not exist "dist\NetPrivacyTool.exe" (
    echo [ERROR] dist\NetPrivacyTool.exe still not found after build.
    pause
    exit /b 1
)

echo [OK] dist\NetPrivacyTool.exe ready.
echo.

:: === STEP 2: Create portable build ===
echo [2/4] Creating portable build in dist\portable\...

set "PORTABLE_DIR=%ROOT%dist\portable"

if exist "%PORTABLE_DIR%" rd /s /q "%PORTABLE_DIR%"
mkdir "%PORTABLE_DIR%"

:: Rename EXE to NetPrivacyTool.exe
copy /y "%ROOT%dist\NetPrivacyTool.exe" "%PORTABLE_DIR%\NetPrivacyTool.exe" >nul

:: core\bin\ (xray + geodata)
robocopy "%STAGE_BIN%"      "%PORTABLE_DIR%\core\bin"   /E /NFL /NDL /NJH /NJS >nul

:: data\ (sources.txt etc.)
robocopy "%ROOT%app\data"   "%PORTABLE_DIR%\data"       /E /NFL /NDL /NJH /NJS /XF "links_cache.json" "temp_*.json" "*.tmp" "verified_nodes.txt" >nul

:: assets\ (icon, optional wizard images)
robocopy "%ROOT%app\assets" "%PORTABLE_DIR%\assets"     /E /NFL /NDL /NJH /NJS >nul

:: Copy README if present
if exist "%ROOT%README.md" copy /y "%ROOT%README.md" "%PORTABLE_DIR%\README.md" >nul

:: Copy recommended VPN client folder if present (use PowerShell for Unicode folder name)
powershell -NoProfile -Command "$src='%ROOT%'; $dst='%PORTABLE_DIR%'; $fn=[char]0x0420+[char]0x0415+[char]0x041A+[char]0x041E+[char]0x041C+[char]0x0415+[char]0x041D+[char]0x0414+[char]0x041E+[char]0x0412+[char]0x0410+[char]0x041D+[char]0x041D+[char]0x0410+[char]0x042F+'_'+[char]0x041F+[char]0x0420+[char]0x041E+[char]0x041A+[char]0x0421+[char]0x0418+'_('+[char]0x0434+[char]0x043B+[char]0x044F+'_'+[char]0x043F+[char]0x043E+[char]0x043B+[char]0x0443+[char]0x0447+[char]0x0435+[char]0x043D+[char]0x043D+[char]0x043E+[char]0x0439+'_'+[char]0x0441+[char]0x0441+[char]0x044B+[char]0x043B+[char]0x043A+[char]0x0438+'_'+[char]0x043D+[char]0x0430+'_'+[char]0x043A+[char]0x043E+[char]0x043D+[char]0x0444+[char]0x0438+[char]0x0433+[char]0x0443+[char]0x0440+[char]0x0430+[char]0x0446+[char]0x0438+[char]0x044E+')'; $s=Join-Path $src $fn; $d=Join-Path $dst $fn; if(Test-Path $s){Copy-Item $s $d -Recurse -Force}" 2>nul

echo [OK] Portable build ready: dist\portable\

echo [2/4] Packing Portable ZIP...
%PS% "$ErrorActionPreference='Stop'; $zip=Join-Path '%RELEASE_DIR%' 'NPVT_Portable.zip'; if(Test-Path $zip){Remove-Item $zip -Force}; Compress-Archive -Path '%PORTABLE_DIR%\*' -DestinationPath $zip -Force; if(!(Test-Path $zip)){ throw 'Portable ZIP not created' }" >nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Portable ZIP build failed.
    pause
    exit /b 1
)
echo [OK] release\NPVT_Portable.zip ready.
echo.

:: === STEP 3: Build Inno Setup installer ===
echo [3/4] Building Inno Setup installer (installer_config.iss)...

set "INSTALLERS_DIR=%ROOT%dist\installers"
if not exist "%INSTALLERS_DIR%" mkdir "%INSTALLERS_DIR%"

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 5\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 5\ISCC.exe"
if not defined ISCC for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do (
    set "ISCC=%%I"
    goto :NPVT_ISCC_FOUND
)

if not defined ISCC for %%K in (
    "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1"
    "HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1"
    "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 5_is1"
    "HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 5_is1"
) do (
    for /f "tokens=2*" %%A in ('reg query %%~K /v InstallLocation 2^>nul ^| find /i "InstallLocation"') do (
        if exist "%%B\ISCC.exe" set "ISCC=%%B\ISCC.exe"
    )
)
:NPVT_ISCC_FOUND
if not defined ISCC (
    echo [WARN] Inno Setup compiler (ISCC.exe) not found. Skipping installer build.
    goto :NPVT_AFTER_INNO
)
if not exist "%ROOT%installer_config.iss" (
    echo [ERROR] installer_config.iss not found in project root.
    pause
    goto :NPVT_AFTER_INNO
)

"%ISCC%" /O"%INSTALLERS_DIR%" "%ROOT%installer_config.iss"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Inno Setup build failed.
    goto :NPVT_AFTER_INNO
)

echo [OK] Inno Setup installer built.

if exist "%INSTALLERS_DIR%\NetPrivacyTool_Setup.exe" copy /y "%INSTALLERS_DIR%\NetPrivacyTool_Setup.exe" "%RELEASE_DIR%\NetPrivacyTool_Setup.exe" >nul
if not exist "%RELEASE_DIR%\NetPrivacyTool_Setup.exe" (
    echo [WARN] release\NetPrivacyTool_Setup.exe not found after Inno build.
    goto :NPVT_AFTER_INNO
)
echo [OK] release\NetPrivacyTool_Setup.exe ready.
echo.

:NPVT_AFTER_INNO

:: === STEP 4: Create clean source ZIP ===
echo [4/4] Creating clean source ZIP...

set "SRC_STAGE=%ROOT%build\source_clean"
if exist "%SRC_STAGE%" rd /s /q "%SRC_STAGE%"
mkdir "%SRC_STAGE%"

robocopy "%ROOT%app" "%SRC_STAGE%\app" /E /NFL /NDL /NJH /NJS /XD "__pycache__" "logs" "result" "bin" >nul
robocopy "%ROOT%tools" "%SRC_STAGE%\tools" /E /NFL /NDL /NJH /NJS /XD "__pycache__" >nul
robocopy "%ROOT%docs" "%SRC_STAGE%\docs" /E /NFL /NDL /NJH /NJS >nul

copy /y "%ROOT%README.md" "%SRC_STAGE%\README.md" >nul
if exist "%ROOT%LICENSE" copy /y "%ROOT%LICENSE" "%SRC_STAGE%\LICENSE" >nul
copy /y "%ROOT%requirements.txt" "%SRC_STAGE%\requirements.txt" >nul
copy /y "%ROOT%start.bat" "%SRC_STAGE%\start.bat" >nul
copy /y "%ROOT%build_all.bat" "%SRC_STAGE%\build_all.bat" >nul
copy /y "%ROOT%installer_config.iss" "%SRC_STAGE%\installer_config.iss" >nul
copy /y "%ROOT%.gitignore" "%SRC_STAGE%\.gitignore" >nul

del /q "%SRC_STAGE%\app\data\links_cache.json" >nul 2>&1
del /q "%SRC_STAGE%\app\data\verified_nodes.txt" >nul 2>&1

%PS% "$ErrorActionPreference='Stop'; $zip=Join-Path '%RELEASE_DIR%' 'NPVT_Source.zip'; if(Test-Path $zip){Remove-Item $zip -Force}; Compress-Archive -Path '%SRC_STAGE%\*' -DestinationPath $zip -Force; if(!(Test-Path $zip)){ throw 'Source ZIP not created' }" >nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Clean source ZIP build failed.
    pause
    exit /b 1
)

if not exist "%RELEASE_DIR%\NPVT_Source.zip" (
    echo [ERROR] release\NPVT_Source.zip not found after build.
    pause
    exit /b 1
)

echo [OK] release\NPVT_Source.zip ready.

:: === Open output folders ===
echo Opening release folder...
explorer "%RELEASE_DIR%"

echo.
echo =========================================
echo   BUILD COMPLETE
echo   Portable folder : dist\portable\NetPrivacyTool.exe
echo   Portable ZIP    : release\NPVT_Portable.zip
if exist "%RELEASE_DIR%\NetPrivacyTool_Setup.exe" (
    echo   Installer (Inno): release\NetPrivacyTool_Setup.exe
) else (
    echo   Installer (Inno): (skipped or failed)
)
echo   Clean source ZIP: release\NPVT_Source.zip
echo =========================================

pause
endlocal
exit /b 0

@echo off
chcp 65001 >nul

if /i "%~1"=="--_logged" goto :NPVT_RUN

set "ROOT=%~dp0"
set "LOG_DIR=%ROOT%build"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\build_all.log"

echo [INFO] Full build log will be saved to: %LOG_FILE%
echo.

call "%~f0" --_logged > "%LOG_FILE%" 2>&1
set "RET=%ERRORLEVEL%"

type "%LOG_FILE%"
echo.
echo =========================================
echo [INFO] Build finished with exit code: %RET%
echo [INFO] Log file: %LOG_FILE%
echo =========================================
pause
exit /b %RET%

:NPVT_RUN
shift

setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "RELEASE_DIR=%ROOT%release"
set "LOG_MODE=1"

set "EXIT_CODE=0"
set "EXE_OK=0"
set "PORTABLE_OK=0"
set "INSTALLER_OK=0"
set "SOURCE_OK=0"

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
    set "EXIT_CODE=1"
    goto :NPVT_STEP4
)

if not exist "dist\NetPrivacyTool.exe" (
    echo [ERROR] dist\NetPrivacyTool.exe still not found after build.
    set "EXIT_CODE=1"
    goto :NPVT_STEP4
)

echo [OK] dist\NetPrivacyTool.exe ready.
set "EXE_OK=1"
echo.

:: === STEP 2: Create portable build ===
echo [2a/4] Creating portable build in release\NPVT_Portable\...

set "PORTABLE_DIR=%RELEASE_DIR%\NPVT_Portable"

if exist "%PORTABLE_DIR%" rd /s /q "%PORTABLE_DIR%"
mkdir "%PORTABLE_DIR%"

:: Rename EXE to NetPrivacyTool.exe
if "%EXE_OK%"=="1" (
    copy /y "%ROOT%dist\NetPrivacyTool.exe" "%PORTABLE_DIR%\NetPrivacyTool.exe" >nul
) else (
    echo [WARN] Skipping portable build: EXE not available.
    set "EXIT_CODE=1"
    goto :NPVT_STEP3
)

:: core\bin\ (xray + geodata)
robocopy "%STAGE_BIN%"      "%PORTABLE_DIR%\core\bin"   /E /NFL /NDL /NJH /NJS >nul

:: data\ (sources.txt etc.)
robocopy "%ROOT%app\data"   "%PORTABLE_DIR%\data"       /E /NFL /NDL /NJH /NJS /XF "links_cache.json" "temp_*.json" "*.tmp" "verified_nodes.txt" >nul

:: assets\ (icon, optional wizard images)
robocopy "%ROOT%app\assets" "%PORTABLE_DIR%\assets"     /E /NFL /NDL /NJH /NJS >nul

:: Copy README if present
if exist "%ROOT%README.md" copy /y "%ROOT%README.md" "%PORTABLE_DIR%\README.md" >nul

echo [OK] Portable build ready: release\NPVT_Portable\

echo [2b/4] Packing Portable ZIP...
python tools\make_zip.py "%PORTABLE_DIR%" "%RELEASE_DIR%\NPVT_Portable.zip" --compresslevel 3 --progress-every 200
echo [INFO] ZIP process returned with code %ERRORLEVEL%
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Portable ZIP build failed.
    set "EXIT_CODE=1"
    goto :NPVT_STEP3
)
if not exist "%RELEASE_DIR%\NPVT_Portable.zip" (
    echo [ERROR] release\NPVT_Portable.zip not found after build.
    set "EXIT_CODE=1"
    goto :NPVT_STEP3
)
echo [OK] release\NPVT_Portable.zip ready.
set "PORTABLE_OK=1"
echo.

:: === STEP 3: Build Inno Setup installer ===
:NPVT_STEP3
echo [3/4] Building Inno Setup installer (installer_config.iss)...

if "%EXE_OK%" NEQ "1" (
    echo [WARN] Skipping installer build: EXE not available.
    set "EXIT_CODE=1"
    goto :NPVT_STEP4
)

set "INSTALLERS_DIR=%RELEASE_DIR%"
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
    set "EXIT_CODE=1"
    goto :NPVT_AFTER_INNO
)

echo [OK] Inno Setup installer built.

if not exist "%INSTALLERS_DIR%\NetPrivacyTool_Setup.exe" (
    echo [WARN] release\NetPrivacyTool_Setup.exe not found after Inno build.
    set "EXIT_CODE=1"
    goto :NPVT_AFTER_INNO
)
echo [OK] release\NetPrivacyTool_Setup.exe ready.
set "INSTALLER_OK=1"
echo.

:NPVT_AFTER_INNO

:: === STEP 4: Create clean source ZIP ===
:NPVT_STEP4
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

python tools\make_zip.py "%SRC_STAGE%" "%RELEASE_DIR%\NPVT_Source.zip"
echo [INFO] ZIP process returned with code %ERRORLEVEL%
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Clean source ZIP build failed.
    set "EXIT_CODE=1"
    goto :NPVT_END
)

if not exist "%RELEASE_DIR%\NPVT_Source.zip" (
    echo [ERROR] release\NPVT_Source.zip not found after build.
    set "EXIT_CODE=1"
    goto :NPVT_END
)

echo [OK] release\NPVT_Source.zip ready.
set "SOURCE_OK=1"

:NPVT_END

:: === Open output folders ===
if not "%LOG_MODE%"=="1" (
    echo Opening release folder...
    explorer "%RELEASE_DIR%"
)

echo.
echo =========================================
echo   BUILD COMPLETE
echo   Portable folder : release\NPVT_Portable\NetPrivacyTool.exe
echo   Portable ZIP    : release\NPVT_Portable.zip
if exist "%RELEASE_DIR%\NetPrivacyTool_Setup.exe" (
    echo   Installer (Inno): release\NetPrivacyTool_Setup.exe
) else (
    echo   Installer (Inno): (skipped or failed)
)
echo   Clean source ZIP: release\NPVT_Source.zip
echo =========================================

if not "%LOG_MODE%"=="1" pause
endlocal & exit /b %EXIT_CODE%

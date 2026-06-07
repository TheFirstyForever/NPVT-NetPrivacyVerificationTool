@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

rem ---------------------------------------------------------------------------
rem  NetPrivacy Verification Tool (NPVT)
rem  Clean build + in-place upgrade, с изолированным ядром
rem ---------------------------------------------------------------------------
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "DIST_DIR=%ROOT%\dist"
set "RELEASE_DIR=%ROOT%\release"
set "BUILD_DIR=%ROOT%\build"
set "CORE_SRC=%ROOT%\app\bin"
set "EXIT_CODE=0"

echo =========================================
echo   NPVT - Clean Build / In-Place Upgrade
echo =========================================

echo [CHECK] Environment diagnostics...
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] Python not found in PATH.
  set "EXIT_CODE=1"
  goto :FINAL
)

python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] PyInstaller is not installed in this Python.
  echo         Fix: python -m pip install -U pyinstaller
  set "EXIT_CODE=1"
  goto :FINAL
)

if not exist "%ROOT%\app\main.py" (
  echo [ERROR] Missing entrypoint: app\main.py
  set "EXIT_CODE=1"
  goto :FINAL
)

if not exist "%ROOT%\app\assets\icon.ico" (
  echo [ERROR] Missing icon: app\assets\icon.ico
  set "EXIT_CODE=1"
  goto :FINAL
)

echo.
echo [CLEAN] Removing old build/dist/release...
for %%D in ("%BUILD_DIR%" "%DIST_DIR%" "%RELEASE_DIR%") do (
  if exist "%%~fD" rd /s /q "%%~fD"
  mkdir "%%~fD" >nul 2>&1
)

rem =========================
rem 1) PORTABLE (PyInstaller)
rem =========================
echo [1/3] Building portable (PyInstaller --onefile)...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --noconsole ^
  --name NetPrivacyTool ^
  --icon "%ROOT%\app\assets\icon.ico" ^
  --collect-data flet ^
  --collect-submodules flet ^
  --add-data "%ROOT%\app\data;app\data" ^
  --add-data "%ROOT%\app\assets;app\assets" ^
  --distpath "%DIST_DIR%" ^
  --workpath "%BUILD_DIR%\pywork" ^
  --specpath "%BUILD_DIR%\pyspec" ^
  "%ROOT%\app\main.py"

if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] PyInstaller build failed.
  set "EXIT_CODE=1"
  goto :BUILD_INSTALLER
)

if not exist "%DIST_DIR%\NetPrivacyTool.exe" (
  echo [ERROR] Built EXE not found: %DIST_DIR%\NetPrivacyTool.exe
  set "EXIT_CODE=1"
  goto :BUILD_INSTALLER
)

rem --- Собираем чистую портативную структуру ---
set "PORTABLE_DIR=%DIST_DIR%\NPVT_Portable"
if exist "%PORTABLE_DIR%" rd /s /q "%PORTABLE_DIR%"
mkdir "%PORTABLE_DIR%" >nul 2>&1

rem 1) EXE в корень
copy /y "%DIST_DIR%\NetPrivacyTool.exe" "%PORTABLE_DIR%\NetPrivacyTool.exe" >nul

rem 2) core/ — бинарники из app\bin (xray, geodata, wintun)
if not exist "%CORE_SRC%" (
  echo [WARN] app\bin not found; skipping core copy.
  set "EXIT_CODE=1"
  goto :SKIP_CORE
)
mkdir "%PORTABLE_DIR%\core" >nul 2>&1
robocopy "%CORE_SRC%" "%PORTABLE_DIR%\core" /E /NFL /NDL /NJH /NJS /XD "__pycache__" >nul
if %ERRORLEVEL% GEQ 8 (
  echo [ERROR] Robocopy failed during copy core.
  set "EXIT_CODE=1"
)
rem Переименовываем xray.exe для изоляции от чужих VPN-клиентов
if exist "%PORTABLE_DIR%\core\xray.exe" (
  ren "%PORTABLE_DIR%\core\xray.exe" "nv_backend_core.exe"
  echo [OK] xray.exe renamed to nv_backend_core.exe
)
:SKIP_CORE

rem 3) data/ — конфиги и источники из app\data
if exist "%ROOT%\app\data" (
  mkdir "%PORTABLE_DIR%\data" >nul 2>&1
  robocopy "%ROOT%\app\data" "%PORTABLE_DIR%\data" /E /NFL /NDL /NJH /NJS >nul
)

rem --- Сверка структуры с эталоном ---
echo.
echo [VERIFY] Checking portable structure...
set "STRUCT_OK=1"
if not exist "%PORTABLE_DIR%\NetPrivacyTool.exe" (
  echo   [FAIL] Missing: NetPrivacyTool.exe
  set "STRUCT_OK=0"
)
if not exist "%PORTABLE_DIR%\core\nv_backend_core.exe" (
  echo   [FAIL] Missing: core\nv_backend_core.exe
  set "STRUCT_OK=0"
)
if not exist "%PORTABLE_DIR%\core\geoip.dat" (
  echo   [FAIL] Missing: core\geoip.dat
  set "STRUCT_OK=0"
)
if not exist "%PORTABLE_DIR%\core\geosite.dat" (
  echo   [FAIL] Missing: core\geosite.dat
  set "STRUCT_OK=0"
)
if not exist "%PORTABLE_DIR%\data\sources.txt" (
  echo   [FAIL] Missing: data\sources.txt
  set "STRUCT_OK=0"
)
rem Проверяем что _internal НЕ существует (чистая сборка)
if exist "%PORTABLE_DIR%\_internal" (
  echo   [FAIL] Junk found: _internal\
  set "STRUCT_OK=0"
)

if "!STRUCT_OK!"=="0" (
  echo [ERROR] Portable structure verification FAILED.
  set "EXIT_CODE=1"
  goto :BUILD_INSTALLER
)
echo   [OK] Structure matches reference.
echo.
echo   dist\NPVT_Portable\
echo     NetPrivacyTool.exe
echo     core\
dir /b "%PORTABLE_DIR%\core" 2>nul
echo     data\
dir /b "%PORTABLE_DIR%\data" 2>nul

rem --- Пауза + упаковка ---
timeout /t 2 /nobreak >nul

echo.
echo [1/3] Packing portable ZIP ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; $src='%PORTABLE_DIR%'; $dst='%RELEASE_DIR%\NPVT_Portable.zip'; if (-not (Test-Path -LiteralPath $src)) { Write-Error ('Source folder not found: ' + $src); exit 1 }; if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Force }; [IO.Compression.ZipFile]::CreateFromDirectory($src, $dst, [IO.Compression.CompressionLevel]::Optimal, $false);" >nul
if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] Portable ZIP build failed.
  set "EXIT_CODE=1"
)
if not exist "%RELEASE_DIR%\NPVT_Portable.zip" (
  echo [ERROR] release\NPVT_Portable.zip not created.
  set "EXIT_CODE=1"
)

rem =========================
rem 2) INSTALLER (Inno Setup)
rem =========================
:BUILD_INSTALLER
echo.
echo [2/3] Building installer (Inno Setup)...
call :FIND_ISCC
if not defined ISCC (
  echo [WARN] ISCC.exe not found. Skipping installer build.
  set "EXIT_CODE=1"
  goto :BUILD_SOURCE
)

if not exist "%ROOT%\installer_config.iss" (
  echo [WARN] installer_config.iss not found. Skipping installer build.
  set "EXIT_CODE=1"
  goto :BUILD_SOURCE
)

"%ISCC%" "/O%DIST_DIR%" "%ROOT%\installer_config.iss"
if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] Inno Setup compile failed.
  set "EXIT_CODE=1"
  goto :BUILD_SOURCE
)

if not exist "%DIST_DIR%\NetPrivacyTool_Setup.exe" (
  echo [ERROR] Installer not found after build: %DIST_DIR%\NetPrivacyTool_Setup.exe
  set "EXIT_CODE=1"
  goto :BUILD_SOURCE
)

copy /y "%DIST_DIR%\NetPrivacyTool_Setup.exe" "%RELEASE_DIR%\NetPrivacyTool_Setup.exe" >nul

rem =========================
rem 3) CLEAN SOURCE ZIP
rem =========================
:BUILD_SOURCE
echo.
echo [3/3] Creating clean source ZIP -> release\NPVT_Source.zip ...

set "SRC_STAGE_ROOT=%BUILD_DIR%\src_stage"
set "SRC_STAGE=%SRC_STAGE_ROOT%\sources_code"
if exist "%SRC_STAGE_ROOT%" rd /s /q "%SRC_STAGE_ROOT%"
mkdir "%SRC_STAGE%" >nul 2>&1

robocopy "%ROOT%\app"   "%SRC_STAGE%\app"   /E /NFL /NDL /NJH /NJS /XD "__pycache__" ".git" "dist" "build" "release" >nul
if %ERRORLEVEL% GEQ 8 (
  echo [ERROR] Robocopy failed during copy app to src.
  set "EXIT_CODE=1"
)

rem app\core содержит Python-модули проекта (scanner, parser, sub_server)
rem app\bin содержит бинарники xray — в source zip не включаем бинарники

robocopy "%ROOT%\tools" "%SRC_STAGE%\tools" /E /NFL /NDL /NJH /NJS /XD "__pycache__" ".git" "dist" "build" "release" >nul
if %ERRORLEVEL% GEQ 8 (
  echo [ERROR] Robocopy failed during copy tools to src.
  set "EXIT_CODE=1"
)

if exist "%ROOT%\requirements.txt" copy /y "%ROOT%\requirements.txt" "%SRC_STAGE%\requirements.txt" >nul
if exist "%ROOT%\LICENSE"         copy /y "%ROOT%\LICENSE"         "%SRC_STAGE%\LICENSE" >nul
if exist "%ROOT%\README.md"       copy /y "%ROOT%\README.md"       "%SRC_STAGE%\README.md" >nul

rem пауза перед архивацией исходников
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 1" >nul

if not exist "%SRC_STAGE%" (
  echo [ERROR] Source staging folder missing: %SRC_STAGE%
  set "EXIT_CODE=1"
  goto :FINAL
)

echo [3/3] Packing source ZIP -> release\NPVT_Source.zip ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; $src='%SRC_STAGE%'; $dst='%RELEASE_DIR%\NPVT_Source.zip'; if (-not (Test-Path -LiteralPath $src)) { Write-Error ('Source folder not found: ' + $src); exit 1 }; if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Force }; [IO.Compression.ZipFile]::CreateFromDirectory($src, $dst, [IO.Compression.CompressionLevel]::Optimal, $true);" >nul
if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] Source ZIP build failed.
  set "EXIT_CODE=1"
)
if not exist "%RELEASE_DIR%\NPVT_Source.zip" (
  echo [ERROR] release\NPVT_Source.zip not created.
  set "EXIT_CODE=1"
)

:FINAL
echo.
echo =========================================
echo BUILD RESULT
echo - Portable folder : dist\NPVT_Portable\
echo - Portable ZIP    : release\NPVT_Portable.zip
echo - Installer       : release\NetPrivacyTool_Setup.exe
echo - Source ZIP      : release\NPVT_Source.zip
echo =========================================
echo Exit code: %EXIT_CODE%
echo.
pause
endlocal & exit /b %EXIT_CODE%

:FIND_ISCC
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 5\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 5\ISCC.exe"
if not defined ISCC for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do if not defined ISCC set "ISCC=%%I"
exit /b 0

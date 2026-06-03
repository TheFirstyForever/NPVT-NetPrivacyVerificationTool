@echo off
setlocal
chcp 65001 >nul
title NetPrivacy Verification Tool - GUI Mode [by @TheFirSStYfOreVer]

REM Go to this script directory
pushd "%~dp0"

echo =========================================
echo  NetPrivacy Verification Tool - GUI Mode
echo  made by @TheFirSStYfOreVer
echo =========================================
echo.

python --version >nul 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Python not found!
    echo Please install Python and add it to PATH.
    pause
    popd
    exit /b 1
)

echo Installing dependencies (if needed)...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Dependency installation failed.
    echo If you see SSL/permission errors, try running CMD as Administrator.
    pause
    popd
    exit /b 1
)

echo.
echo Starting GUI...
echo.

python app\main.py
if errorlevel 1 (
    echo.
    echo GUI exited with error. Check errors above.
    pause
    popd
    exit /b 1
)

popd
exit /b 0

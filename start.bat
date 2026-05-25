@echo off
chcp 65001 >nul
title NetPrivacy Verification Tool - GUI Mode [by @TheFirSStYfOreVer]

REM Переход в папку где находится этот batch файл
cd /d "%~dp0"

echo =========================================
echo  NetPrivacy Verification Tool - GUI Mode
echo  made by @TheFirSStYfOreVer
echo =========================================
echo.
echo Installing dependencies (if needed)...
pip install -q aiohttp aiohttp-socks pyperclip customtkinter Pillow 2>nul
echo.
echo Starting GUI...
echo.

where python >nul 2>nul
if %errorlevel% == 0 (
    python app\main.py
) else (
    echo.
    echo ERROR: Python not found!
    echo Please install Python and add it to PATH.
    pause
    exit /b 1
)

if errorlevel 1 (
    echo.
    echo GUI exited with error. Check errors above.
    pause
)

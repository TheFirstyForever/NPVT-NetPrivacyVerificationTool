@echo off
chcp 65001 >nul
title NetPrivacy Verification Tool - Uninstaller [by @TheFirSStYfOreVer]

echo =========================================
echo  NetPrivacy Verification Tool
echo  Uninstaller
echo  made by @TheFirSStYfOreVer
echo =========================================
echo.
echo This will remove the tool and its dependencies.
echo.
echo Press any key to continue or CTRL+C to cancel...
pause >nul

echo.
echo Removing dependencies...

pip uninstall -y aiohttp aiohttp-socks pyperclip customtkinter Pillow 2>nul

echo.
echo Removing desktop shortcut...
del "%USERPROFILE%\Desktop\NetPrivacy Tool.lnk" 2>nul

echo.
echo =========================================
echo  Uninstallation complete!
echo  made by @TheFirSStYfOreVer
echo =========================================
echo.
echo Note: Application files in this folder were NOT deleted.
echo To remove them, manually delete this folder:
echo %~dp0
echo.
pause

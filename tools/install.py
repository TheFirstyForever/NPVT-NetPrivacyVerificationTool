#!/usr/bin/env python3
"""
NetPrivacy Verification Tool - Windows Installer
Автономный установщик для Windows. Просто запусти на любом ПК!

Что делает этот установщик:
1. Проверяет установлен ли Python (если нет - предлагает скачать)
2. Устанавливает все необходимые библиотеки
3. Создает иконку приложения
4. Создает ярлык на рабочем столе
5. Создает portable-версию (опционально)

Для создания standalone .exe запусти:
   python install.py --build-exe
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
import zipfile

# Цвета для консоли
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_header(text):
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"  {text}")
    print(f"{BLUE}{'='*60}{RESET}\n")

def print_success(text):
    print(f"{GREEN}✓ {text}{RESET}")

def print_error(text):
    print(f"{RED}✗ {text}{RESET}")

def print_warning(text):
    print(f"{YELLOW}⚠ {text}{RESET}")

def check_python():
    """Проверяет установлен ли Python"""
    print_header("Checking Python Installation")
    
    version = sys.version_info
    print(f"Python version: {version.major}.{version.minor}.{version.micro}")
    
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print_error("Python 3.8+ required!")
        print("\nPlease download and install Python from:")
        print("  https://www.python.org/downloads/")
        print("\nIMPORTANT: Check 'Add Python to PATH' during installation!")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    print_success(f"Python {version.major}.{version.minor} is OK")
    return True

def install_dependencies():
    """Устанавливает необходимые библиотеки"""
    print_header("Installing Dependencies")

    project_root = get_project_root()
    req = project_root / "requirements.txt"
    if not req.exists():
        print_error("requirements.txt not found in project root")
        return False

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(req)],
        )
    except Exception as e:
        print_error(f"Dependency installation failed: {e}")
        return False

    print_success("All dependencies installed!")
    return True

def get_project_root():
    """Возвращает корневую папку проекта (родительская от tools)"""
    return Path(__file__).parent.parent

def create_icon():
    """Создает иконку приложения"""
    print_header("Creating Application Icon")

    project_root = get_project_root()
    ico_path = project_root / "app" / "assets" / "icon.ico"
    if ico_path.exists():
        print_success(f"Icon found: {ico_path}")
        return str(ico_path)

    print_warning("icon.ico not found. Trying to generate it via tools/create_icon.py...")
    try:
        subprocess.check_call([sys.executable, str(project_root / "tools" / "create_icon.py")])
    except Exception:
        print_warning("Failed to generate icon automatically. Shortcut will be created without custom icon.")
        return ""

    if ico_path.exists():
        print_success(f"Icon created: {ico_path}")
        return str(ico_path)

    return ""

def create_shortcut(icon_path):
    """Создает ярлык на рабочем столе"""
    print_header("Creating Desktop Shortcut")
    
    project_root = get_project_root()
    desktop = Path.home() / "Desktop"
    shortcut_path = desktop / "NetPrivacy Tool.lnk"
    target = project_root / "start.bat"
    
    # PowerShell скрипт
    ps_script = f'''
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{target}"
$Shortcut.WorkingDirectory = "{project_root}"
$Shortcut.IconLocation = "{icon_path}, 0"
$Shortcut.Description = "NetPrivacy Verification Tool"
$Shortcut.Save()
'''
    
    try:
        subprocess.run(
            ["powershell", "-Command", ps_script],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print_success(f"Desktop shortcut created: {shortcut_path}")
        return True
    except Exception as e:
        print_error(f"Failed to create shortcut: {e}")
        return False

def create_portable_package():
    """Создает portable zip-архив для переноса на другой ПК"""
    print_header("Creating Portable Package")
    
    project_root = get_project_root()
    parent_dir = project_root.parent
    zip_name = f"NetPrivacy_Portable_{project_root.name}.zip"
    zip_path = parent_dir / zip_name
    
    # Папки и файлы для включения
    include_items = [
        # Root files
        "requirements.txt", "start.bat", "README.md",
        # App folder
        "app/main.py", "app/core", "app/bin", "app/data", "app/assets",
        # Tools folder  
        "tools/uninstall.bat",
        "tools/install.py", "tools/create_icon.py",
    ]
    
    print(f"Creating: {zip_path}")
    
    skip_names = {
        "links_cache.json",
        "verified_nodes.txt",
    }
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in include_items:
            item_path = project_root / item
            if item_path.exists():
                if item_path.is_dir():
                    for file_path in item_path.rglob("*"):
                        if file_path.is_file():
                            try:
                                if "__pycache__" in file_path.parts:
                                    continue
                                if "logs" in file_path.parts:
                                    continue
                                if "result" in file_path.parts:
                                    continue
                                if file_path.name in skip_names:
                                    continue
                                if file_path.name.startswith("temp_") and file_path.suffix.lower() == ".json":
                                    continue
                                if file_path.suffix.lower() == ".tmp":
                                    continue
                            except Exception:
                                pass
                            arcname = str(file_path.relative_to(project_root))
                            zf.write(file_path, arcname)
                            print(f"  + {arcname}")
                else:
                    arcname = str(item_path.relative_to(project_root))
                    zf.write(item_path, arcname)
                    print(f"  + {arcname}")
    
    print_success(f"\nPortable package created: {zip_path}")
    print(f"\n{YELLOW}To use on another PC:{RESET}")
    print(f"1. Extract {zip_name} to any folder")
    print(f"2. Run tools/install.py (installs dependencies)")
    print(f"3. Run start.bat or desktop shortcut")
    
    return str(zip_path)

def create_standalone_exe():
    """Создает standalone .exe через PyInstaller"""
    print_header("Creating Standalone EXE (Optional)")
    
    print("This will create a single .exe file that runs without Python installed.")
    print("\nRequirements:")
    print("  - PyInstaller will be installed")
    print("  - Result: dist/NetPrivacyTool.exe")
    print("\nNote: This takes a few minutes and creates a larger file (~50MB)")
    
    response = input("\nCreate standalone .exe? (y/n): ").lower()
    if response != 'y':
        print("Skipping EXE creation.")
        return None
    
    # Устанавливаем pyinstaller
    print("\nInstalling PyInstaller...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "pyinstaller"],
            stdout=subprocess.DEVNULL
        )
    except Exception as e:
        print_error(f"Failed to install PyInstaller: {e}")
        return None
    
    # Создаем EXE
    print("Building EXE... (this may take a few minutes)")
    project_root = get_project_root()
    try:
        subprocess.check_call([
            sys.executable, "-m", "PyInstaller",
            "--onefile", "--windowed",
            "--name", "NetPrivacyTool",
            "--icon", str(project_root / "app" / "assets" / "icon.ico"),
            "--add-data", f"{project_root / 'app' / 'assets'};app/assets",
            "--add-data", f"{project_root / 'app' / 'data'};app/data",
            "--add-data", f"{project_root / 'app' / 'bin'};core/bin",
            str(project_root / "app" / "main.py")
        ], stdout=subprocess.DEVNULL, cwd=str(project_root))
        exe_path = project_root / "dist" / "NetPrivacyTool.exe"
        print_success(f"Standalone EXE created: {exe_path}")
        return str(exe_path)
    except Exception as e:
        print_error(f"Failed to build EXE: {e}")
        return None

def main():
    print_header("NetPrivacy Verification Tool - Windows Installer")
    print("Made by @TheFirSStYfOreVer")
    print("This installer will set up everything automatically.")
    print("No need to install anything manually!\n")
    
    # Проверка Python
    if not check_python():
        return
    
    # Установка зависимостей
    if not install_dependencies():
        print_error("\nInstallation failed!")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    # Создание иконки
    icon_path = create_icon()
    
    # Создание ярлыка
    create_shortcut(icon_path)
    
    # Создание portable пакета
    print("\n" + "="*60)
    print("  ADDITIONAL OPTIONS")
    print("="*60)
    
    zip_path = None
    exe_path = None
    
    response = input("\nCreate portable ZIP for other PCs? (y/n): ").lower()
    if response == 'y':
        zip_path = create_portable_package()
    
    # PyInstaller опционально
    exe_path = create_standalone_exe()
    
    # Итог
    print_header("Installation Complete!")
    print("Made by @TheFirSStYfOreVer")
    print_success("NetPrivacy Tool is ready to use!")
    print("\nHow to run:")
    print("  1. Double-click desktop shortcut 'NetPrivacy Tool'")
    print("  2. Or run: start.bat")
    print("\nFiles created:")
    print(f"  - Desktop shortcut")
    print(f"  - Assets/icon.ico")
    if zip_path:
        print(f"  - {zip_path}")
    if exe_path:
        print(f"  - {exe_path}")
    
    print("\n" + f"{GREEN}{'='*60}{RESET}")
    print("  To distribute to other PCs:")
    if zip_path:
        print(f"  Share: {zip_path}")
        print("  Other user: Extract → Run install.py → Use!")
    else:
        print("  Zip this folder and share")
    print(f"{GREEN}{'='*60}{RESET}")
    
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()

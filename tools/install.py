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
    
    deps = [
        ("aiohttp", "3.8.0"),
        ("aiohttp-socks", "0.7.0"),
        ("pyperclip", "1.8.0"),
        ("customtkinter", "5.0.0"),
        ("Pillow", "9.0.0"),
    ]
    
    failed = []
    for dep, min_ver in deps:
        print(f"Installing {dep}...")
        try:
            # Пробуем установить/обновить
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-q", "--upgrade", dep],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print_success(f"{dep} installed")
        except Exception as e:
            print_error(f"Failed to install {dep}: {e}")
            failed.append(dep)
    
    if failed:
        print_warning(f"\nSome packages failed: {', '.join(failed)}")
        print("Try running: pip install " + " ".join(failed))
        return False
    
    print_success("All dependencies installed!")
    return True

def get_project_root():
    """Возвращает корневую папку проекта (родительская от tools)"""
    return Path(__file__).parent.parent

def create_icon():
    """Создает иконку приложения"""
    print_header("Creating Application Icon")
    
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Installing Pillow for icon creation...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "Pillow"])
        from PIL import Image, ImageDraw, ImageFont
    
    # Создаем изображение
    size = 256
    img = Image.new('RGBA', (size, size), (15, 15, 26, 255))
    draw = ImageDraw.Draw(img)
    
    # Рисуем щит
    center = size // 2
    radius = size // 3
    draw.ellipse(
        [center - radius, center - radius, center + radius, center + radius],
        fill=(59, 142, 208, 255),
        outline=(255, 255, 255, 255),
        width=5
    )
    
    # Текст NP
    try:
        font = ImageFont.truetype("arial.ttf", size // 4)
    except:
        font = ImageFont.load_default()
    
    text = "NP"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (size - text_width) // 2
    y = (size - text_height) // 2
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
    
    # Сохраняем в app/assets
    project_root = get_project_root()
    assets_dir = project_root / "app" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    
    ico_path = assets_dir / "icon.ico"
    img.save(str(ico_path), format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    print_success(f"Icon created: {ico_path}")
    
    return str(ico_path)

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
        "requirements.txt", "start.bat",
        # App folder
        "app/main.py", "app/core", "app/bin", "app/data", "app/result",
        # Tools folder  
        "tools/uninstall.bat",
        "tools/install.py", "tools/create_icon.py",
        # Docs folder
        "docs/README.md",
    ]
    
    print(f"Creating: {zip_path}")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in include_items:
            item_path = project_root / item
            if item_path.exists():
                if item_path.is_dir():
                    for file_path in item_path.rglob("*"):
                        if file_path.is_file():
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
    print(f"3. Run tools/start.bat or desktop shortcut")
    
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
            "--add-data", f"{project_root / 'app' / 'assets'};assets",
            "--add-data", f"{project_root / 'app' / 'core'};core",
            "--add-data", f"{project_root / 'app' / 'bin'};bin",
            "--add-data", f"{project_root / 'app' / 'data'};data",
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

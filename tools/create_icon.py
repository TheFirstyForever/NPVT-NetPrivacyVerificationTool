#!/usr/bin/env python3
"""
Создает простую иконку для приложения
Требуется: pip install Pillow
Made by @TheFirSStYfOreVer
"""

from PIL import Image, ImageDraw, ImageFont
import os

def create_icon():
    """Создает ICO файл для Windows"""
    
    # Создаем изображение 256x256
    size = 256
    img = Image.new('RGBA', (size, size), (15, 15, 26, 255))  # Темно-синий фон
    draw = ImageDraw.Draw(img)
    
    # Рисуем круг (щит)
    shield_color = (59, 142, 208, 255)  # #3B8ED0
    center = size // 2
    radius = size // 3
    draw.ellipse([center - radius, center - radius, center + radius, center + radius], 
                 fill=shield_color, outline=(255, 255, 255, 255), width=5)
    
    # Добавляем текст "NP"
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
    
    # Создаем папку assets
    assets_dir = os.path.join(os.path.dirname(__file__), "assets")
    os.makedirs(assets_dir, exist_ok=True)
    
    # Сохраняем в разных размерах для ICO
    sizes = [256, 128, 64, 48, 32, 16]
    icons = []
    for s in sizes:
        resized = img.resize((s, s), Image.LANCZOS)
        icons.append(resized)
    
    # Сохраняем ICO
    ico_path = os.path.join(assets_dir, "icon.ico")
    icons[0].save(ico_path, format='ICO', sizes=[(s, s) for s in sizes])
    print(f"✓ Created: {ico_path}")
    
    # Сохраняем PNG для Linux/Mac
    png_path = os.path.join(assets_dir, "icon.png")
    img.save(png_path)
    print(f"✓ Created: {png_path}")
    
    return ico_path, png_path

if __name__ == "__main__":
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow not installed. Installing...")
        import subprocess
        import sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "Pillow"])
        from PIL import Image, ImageDraw, ImageFont
    
    print("Creating application icon...")
    print("Made by @TheFirSStYfOreVer")
    create_icon()
    print("\nIcon created successfully!")
    print("Made by @TheFirSStYfOreVer")
    print("Run install.py to create desktop shortcut with this icon.")

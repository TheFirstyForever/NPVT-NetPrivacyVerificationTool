# NetPrivacy Verification Tool

Research utility for encrypted node availability & security - **Windows Edition**

**Made by @TheFirSStYfOreVer**

## 🚀 Quick Start (First Time)

1. **Double-click `tools/install.py`** (или перетащи его на python.exe)
2. Жди пока установятся библиотеки
3. На рабочем столе появится ярлык **"NetPrivacy Tool"**
4. Запускай через ярлык или `tools/start.bat`

## 📤 Distribution - How to Share

### Method 1: Portable ZIP (Recommended)

После запуска `tools/install.py` он спросит:
```
Create portable ZIP for other PCs? (y/n):
```

Ответь **y** — создастся `NetPrivacy_Portable_V2_PROJECT.zip`

**На другом ПК:**
1. Распакуй ZIP в любую папку
2. Запусти `tools/install.py` (установит зависимости)
3. Готово! Ярлык появится на рабочем столе

### Method 2: Standalone EXE

В `tools/install.py` спросит:
```
Create standalone .exe? (y/n):
```

Ответь **y** — создастся `dist/NetPrivacyTool.exe`

**На другом ПК:**
1. Просто запусти EXE — работает без Python!
2. Размер ~50MB, но ничего ставить не нужно

## 📦 Files Explained

| File | Purpose |
|------|---------|
| `tools/install.py` | **Главный установщик** — ставит всё автоматически |
| `tools/start.bat` | Запуск программы |
| `tools/uninstall.bat` | Удаление библиотек и ярлыка |
| `tools/create_icon.py` | Создание иконки |
| `app/main.py` | Главное приложение |
| `docs/README.md` | Документация |

## 🔧 What tools/install.py Does

1. **Проверяет Python** — если нет, покажет ссылку для скачивания
2. **Устанавливает библиотеки:**
   - aiohttp — HTTP клиент
   - aiohttp-socks — SOCKS прокси
   - pyperclip — копирование в буфер
   - customtkinter — современный GUI
   - Pillow — работа с изображениями
3. **Создает иконку** — синий щит с NP
4. **Создает ярлык** на рабочем столе с иконкой
5. **(Опционально) Создает ZIP** для переноса на другой ПК
6. **(Опционально) Создает EXE** через PyInstaller

## 🎯 Requirements

- **Windows 10/11**
- **Python 3.8+** (если нет — установщик подскажет где скачать)

**No VS Code needed!** Просто запусти `install.py` на любом ПК с Python.

## 🛠️ Features

- **Modern Dark GUI** — CustomTkinter
- **Async Operations** — быстрая параллельная проверка
- **One-Click Copy** — копирование лучшего конфига
- **Resource Check** — YouTube, Telegram, Discord, Instagram
- **Clean STOP** — корректная остановка всех процессов

## 📁 Project Structure (Organized)

```
V2_PROJECT/
├── app/                      # Application files (runtime)
│   ├── main.py              # Главное приложение
│   ├── core/
│   │   └── scanner.py       # Логика проверки
│   ├── bin/
│   │   └── xray.exe         # Прокси
│   ├── data/
│   │   ├── sources.txt      # Источники прокси
│   │   └── verified_nodes.txt  # Результаты
│   ├── result/
│   │   └── optimal_config.txt  # Лучший конфиг
│   └── assets/
│       └── icon.ico         # Иконка приложения
├── tools/                    # Installers & utilities
│   ├── install.py           # Установщик (запускай первым!)
│   ├── start.bat            # Запуск
│   ├── uninstall.bat        # Удаление
│   └── create_icon.py       # Генератор иконки
├── docs/                     # Documentation
│   └── README.md            # Этот файл
└── requirements.txt         # Зависимости Python
```

## ⚙️ Configuration

Edit `app/data/sources.txt`:
```
# Прямые ссылки
vless://...
vmess://...

# Или URL со списками
https://example.com/proxies.txt
```

## 📝 License

MIT License

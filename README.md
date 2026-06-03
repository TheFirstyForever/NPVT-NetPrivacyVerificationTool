# NPVT — NetPrivacy Verification Tool

![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6)
![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB)
![UI](https://img.shields.io/badge/UI-Flet-4B8BBE)
![Engine](https://img.shields.io/badge/Engine-Xray--core-111827)
![License](https://img.shields.io/badge/License-GPL--3.0--or--later-green)

Research utility for **high‑volume streaming verification** of encrypted proxy nodes.

- **Streaming Engine**: непрерывная обработка через `asyncio.Queue` без batch‑гейтинга
- **Cyber‑Speedometer**: сглаженный CPS (rolling window / EMA)
- **ФОРСАЖ (MAX)**: динамический пул воркеров и защита UI от перегрузки
- **One‑click UX**: Copy Best Config / Copy Subscription / Import Subscription (deeplink)

---

## Скриншоты

![NPVT Screenshot 25](docs/screenshots/%D0%A1%D0%BD%D0%B8%D0%BC%D0%BE%D0%BA%20%D1%8D%D0%BA%D1%80%D0%B0%D0%BD%D0%B0%20%2825%29.png)

![NPVT Screenshot 26](docs/screenshots/%D0%A1%D0%BD%D0%B8%D0%BC%D0%BE%D0%BA%20%D1%8D%D0%BA%D1%80%D0%B0%D0%BD%D0%B0%20%2826%29.png)

![NPVT Screenshot 27](docs/screenshots/%D0%A1%D0%BD%D0%B8%D0%BC%D0%BE%D0%BA%20%D1%8D%D0%BA%D1%80%D0%B0%D0%BD%D0%B0%20%2827%29.png)

---

# RU

## Что это

NPVT — это инструмент для **быстрой и корректной** проверки больших массивов прокси‑конфигов (десятки тысяч) с реальным замером качества:

- доступность ключевых ресурсов (YouTube / Telegram / Discord / Instagram)
- надёжность (0/4 … 4/4)
- задержка (latency) и «лучший конфиг»

Проверка выполняется локально через Xray‑core (SOCKS5), а сетевые проверки — через `aiohttp`.

## Скачать (Release артефакты)

В релизах репозитория ожидаются 3 варианта:

- **Installer**: `NetPrivacyTool_Setup.exe`
- **Portable**: `NPVT_Portable.zip`
- **Source code**: `Source code.zip`

## Установка и запуск

### Вариант A — Installer (рекомендуется)

1) Скачай `NetPrivacyTool_Setup.exe`
2) Установи
3) Запускай через ярлык

### Вариант B — Portable ZIP

1) Скачай `NPVT_Portable.zip`
2) Распакуй
3) Запусти `NetPrivacyTool.exe`

### Вариант C — Запуск из исходников (Python)

1) Установи Python 3.8+
2) В корне проекта:

```bat
python -m pip install -r requirements.txt
start.bat
```

## Как это работает (коротко, по‑взрослому)

- **UI**: Flet (один поток отрисовки + асинхронные задачи)
- **Пайплайн**: ссылки → очередь → воркеры → результаты → Top‑N сортировка в UI
- **Производительность**: воркеры масштабируются под целевой CPS; метрика CPS сглаживается по окну
- **Без лагов**: UI сортирует и рендерит только Top‑N (15–20), не тысячи строк

## Конфигурация источников

Файл: `app/data/sources.txt`

```txt
vless://...
vmess://...
trojan://...

https://example.com/sub_or_list.txt
```

---

## Сборка (для разработчиков)

### Полный релиз‑пайплайн

`build_all.bat` собирает:

- Portable папку + `release/NPVT_Portable.zip`
- Inno Setup installer: `release/NetPrivacyTool_Setup.exe`
- Clean Source ZIP: `release/NPVT_Source.zip`

Требования:

- Python
- `pip install pyinstaller`
- Inno Setup 6 (`ISCC.exe`)

---

# EN

## What is NPVT

NPVT is a Windows research utility for **high‑volume streaming verification** of encrypted proxy nodes.

It combines:

- an `asyncio` streaming pipeline
- Xray‑core based local SOCKS5 execution
- a modern Flet UI with a real‑time CPS speedometer

## Downloads (Release artifacts)

- **Installer**: `NetPrivacyTool_Setup.exe`
- **Portable**: `NPVT_Portable.zip`
- **Clean Source**: `NPVT_Source.zip`

## Run from source

```bat
python -m pip install -r requirements.txt
start.bat
```

## Architecture highlights

- **Streaming verification** via `asyncio.Queue`
- **Dynamic worker pool** tuned to target CPS
- **Top‑N UI rendering** (keeps the interface fast even in MAX mode)


## 📝 License

This program is free software: you can redistribute it and/or modify it under the terms of the **GNU General Public License as published by the Free Software Foundation, version 3.0.**

Подробности в файле [LICENSE](./LICENSE).

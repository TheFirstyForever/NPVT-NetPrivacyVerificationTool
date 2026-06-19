# NPVT — NetPrivacy Verification Tool

![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![UI](https://img.shields.io/badge/UI-Flet-4B8BBE)
![Engine](https://img.shields.io/badge/Engine-Xray--core-111827)
![License](https://img.shields.io/badge/License-GPL--3.0--or--later-green)

<p align="center">
  <a href="https://www.tinkoff.ru/rm/r_hKMvqOMPWz.VIdWxEmgid/UW8Sr60397">
    <img src="https://img.shields.io/badge/Donate-Support_the_Project-ff69b4.svg?style=for-the-badge&logo=kofi&logoColor=white" alt="Donate">
  </a>
</p>

<details>
<summary><b>☕ Поддержать развитие проекта</b></summary>

<br>

<div align="center">
  <img src="docs/screenshots/IMG_20260609_035711.jpg" width="200" alt="Donate QR" style="border-radius: 12px;">

  <p><b>Поддержать разработку</b><br>
  Проект NetPrivacyTool был создан с идеей сделать инструменты для обеспечения приватности простыми и доступными для каждого. Я развиваю его в свободное время, потому что верю, что свобода и безопасность в сети должны быть базовыми вещами.</p>

  <p>Если этот инструмент оказался вам полезен и вы хотите сказать «спасибо», вы можете поддержать проект символическим донатом. Это лучший способ дать мне понять, что моя работа действительно делает вашу жизнь чуточку проще и безопаснее.</p>

  <p><i>Спасибо, что вы со мной!</i></p>
</div>

</details>


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

## Скачать (Release)

В релизах репозитория имеется
3 варианта:

- **Installer**: `NetPrivacyTool_Setup.exe`
- **Portable**: `Portable.zip`
- **Source code**: `Source code.zip`

## Установка и запуск

### Вариант A — Installer (рекомендуется)

1) Скачай `NetPrivacyTool_Setup.exe`
2) Установи
3) Запускай через ярлык

### Вариант B — Portable ZIP

1) Скачай `Portable.zip`
2) Распакуй
3) Запусти `NetPrivacyTool.exe`

### Вариант C — Запуск из исходников (Python)

1) Установи Python 3.10+
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

## Как это работает (подробно)

### 1) Где лежат данные при запуске (Runtime vs User)

В коде есть два «базовых» пути:

- `RUNTIME_BASE`
  - в PyInstaller (frozen) — это папка рядом с `NetPrivacyTool.exe` (или `_MEIPASS`, если доступен)
  - в dev-режиме — корень проекта (на уровень выше `app/main.py`)
- `USER_BASE`
  - Windows: `%LOCALAPPDATA%\NetPrivacyTool`

Из этого следует правило:

- `sources.txt` хранится рядом с программой (runtime)
- кэш и результаты хранятся в профиле пользователя (user)

### 2) Источники (`sources.txt`) и режимы Source mode

NPVT читает список источников из `sources.txt`:

- запуск из исходников: `app/data/sources.txt`
- portable/installer: `data/sources.txt` (рядом с `NetPrivacyTool.exe`)

В UI есть выпадающий список **Source mode**:

- **Auto** — онлайн, а при проблемах сети использует кэш
- **Online** — только онлайн-источники (HTTP/HTTPS)
- **Cache** — офлайн режим: используется только кэш ссылок
- **Parse** — парсинг через `app/core/goida_parser.py` (resilient fetch + фильтрация insecure)

Форматы строк в `sources.txt`:

- прямые конфиги: `vless://...`, `vmess://...`, `trojan://...`, `ss://...`
- URL источников: `https://...` (страницы/подписки)

### 3) Streaming пайплайн и динамические воркеры

1) Из источников извлекаются прокси-ссылки и дедуплицируются
2) Все ссылки кладутся в `asyncio.Queue`
3) Запускается динамический пул воркеров

Правило по воркерам:

- обычный режим: примерно `TargetCPS * 3` (с верхним лимитом)
- **ФОРСАЖ (MAX)**: воркеров существенно больше (агрессивный максимум)

### 4) Как проверяется одна нода (Xray-core -> SOCKS5 -> 4 проверки)

За проверку отвечает `LogicVerifier` (`app/core/scanner.py`). Для каждой ссылки:

1) Выбирается свободный локальный порт
2) Генерируется временный JSON-конфиг Xray в `%TEMP%\npvt_configs\temp_<port>.json`
3) Запускается локальный SOCKS5 на `127.0.0.1:<port>`
4) Через этот SOCKS5 выполняются параллельные HEAD-запросы к:

- `youtube.com`
- `t.me`
- `discord.com`
- `instagram.com`

Успешными считаются ответы: `200/204/301/302/307/308/403/404/405`.

Результат ноды включает:

- `accessible_count`: 0..4
- `accessibility`: строка вида `3/4`
- `is_high_reliability`: `True` если `4/4`
- `avg_resource_rtt`: средний RTT успешных доменов
- `ping`: базовая задержка (минимальный RTT из успешных)

### 5) Метрики CPS и UI без лагов

- CPS считается по окну ~1.5 секунды и сглаживается EMA
- UI получает результаты батчами и отображает только Top‑N (по качеству и RTT)

### 6) Локальная подписка `/sub` и импорт в VPN-клиенты

NPVT поднимает локальный HTTP сервер:

- `http://127.0.0.1:54321/sub`

Он отдаёт Top‑10 лучших нод (сортировка по ping). В UI доступно:

- **COPY SUBSCRIPTION** — копирует URL подписки
- **Импорт подписки** — открывает deeplink для выбранного клиента:
  - Happ: `happ://add/<url>`
  - Clash: `clash://install-config?url=<url>`
  - Hiddify: `hiddify://install-sub?url=<url>#NPVT`
  - v2rayN/NekoRay: копирует URL (импорт выполняется в самом клиенте)

### 7) Где лежат кэш и результаты

- кэш ссылок: `%LOCALAPPDATA%\NetPrivacyTool\links_cache.json`
- результаты: `%LOCALAPPDATA%\NetPrivacyTool\verified_nodes.txt`

### 8) Portable структура (чистая)

После распаковки `NPVT_Portable.zip` структура такая:

```
NPVT_Portable/
  NetPrivacyTool.exe
  core/
    nv_backend_core.exe
    geoip.dat
    geosite.dat
    wintun.dll
  data/
    sources.txt
```

Никаких `_internal/` рядом быть не должно — используется PyInstaller `--onefile`.

### 9) Сборка релиза

Основная сборка: `build_all.bat`.

На выходе:

- `release/NPVT_Portable.zip`
- `release/NPVT_Source.zip`
- `release/NetPrivacyTool_Setup.exe`

## Конфигурация источников

Файл:

- запуск из исходников: `app/data/sources.txt`
- portable/installer: `data/sources.txt`

```txt
vless://...
vmess://...
trojan://...

https://example.com/sub_or_list.txt
```

---

# EN

## What is NPVT

NPVT is a Windows research utility for **high‑volume streaming verification** of encrypted proxy nodes.

It combines:

- an `asyncio` streaming pipeline
- Xray‑core based local SOCKS5 execution
- a modern Flet UI with a real‑time CPS speedometer

## Downloads (Release)

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
---

<details>
<summary><b>Использованные технологии и источники данных</b></summary>

* <b>Ядро:</b> Проект реализован на базе [Xray-core](https://github.com/XTLS/Xray-core). Огромная благодарность команде [XTLS](https://github.com/XTLS) за разработку мощного ядра для сетевых протоколов.

* <b>Данные:</b> Проект использует автоматический парсинг публичных источников, а также использует технологии и публичные листы которые были составлены **Goida vpn**  [goida-vpn-configs](https://github.com/AvenCores/goida-vpn-configs).

</details>

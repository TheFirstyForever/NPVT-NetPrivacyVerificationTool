# NetPrivacy — Mobile Core

Мобильно-оптимизированное ядро сканера прокси.  
Полностью независимо от PC-версии (`app/`).

---

## Структура

```
mobile/
├── core/
│   ├── __init__.py
│   └── scanner.py          # MobileScanner, ScanConfig, NodeResult
├── data/
│   └── sources.txt         # ссылки / URL-подписки
├── results/                # создаётся автоматически
│   ├── results.json
│   └── results.txt
├── bin/                    # положи сюда xray (или xray.exe)
├── checker.py              # CLI-запуск
├── requirements_mobile.txt
└── README_MOBILE.md
```

---

## Быстрый старт

### Windows / Linux / macOS

```bash
pip install -r requirements_mobile.txt
python checker.py
```

### Android (Termux)

```bash
pkg update && pkg install python xray
pip install aiohttp aiohttp-socks
python checker.py --concurrency 5
```

---

## Параметры запуска

| Флаг | По умолчанию | Описание |
|---|---|---|
| `--sources` | `data/sources.txt` | Файл с ссылками / URL-подписками |
| `--out` | `results/results.json` | JSON-файл результатов |
| `--concurrency` | `10` | Параллельных проверок одновременно |
| `--no-gemini` | выкл. | Пропустить Gemini-проверку (быстрее) |

Примеры:

```bash
python checker.py --concurrency 5 --no-gemini
python checker.py --sources ~/my_nodes.txt --out /sdcard/out.json
```

---

## Ключевые оптимизации vs PC-версия

| | PC (`app/`) | Mobile (`mobile/`) |
|---|---|---|
| GUI | CustomTkinter | — |
| Threading bridge | `asyncio ↔ tkinter` | — |
| Параллельность | семафор 50 | воркер-пул 10 |
| База | timeout 10 с | 8 с |
| Ресурсы | session 15 с | 8 с / домен |
| xray конфиги | `app/data/temp_*` | `tempfile.mkstemp` |
| Поиск xray | `app/bin/xray.exe` | `bin/` → `app/bin/` → PATH |
| Kill (POSIX) | Windows-only | SIGTERM → SIGKILL |
| Результат | dict | `NodeResult` dataclass |
| API | callback + dict | async generator |
| Зависимости | ~7 пакетов | 2 пакета |

---

## Использование как библиотеки

```python
import asyncio
from mobile.core.scanner import MobileScanner, ScanConfig

async def main():
    cfg = ScanConfig(concurrency=8, check_gemini=True)
    scanner = MobileScanner(cfg, log_callback=print)

    links = ["vless://...", "vmess://..."]

    async for node in scanner.scan(links):
        if node.is_high_reliability:
            print(f"★ {node.name} | {node.accessibility}")

asyncio.run(main())
```

---

## xray binary

Положи бинарник в `mobile/bin/`:

- **Android/Termux**: `pkg install xray`  
- **Linux**: скачай с https://github.com/XTLS/Xray-core/releases  
- **Windows**: `xray.exe` в `mobile/bin/`  

Или укажи путь явно: `ScanConfig(xray_bin="/path/to/xray")`

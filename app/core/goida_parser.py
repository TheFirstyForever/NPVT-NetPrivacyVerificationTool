import asyncio
import json
import os
import re
import html
import urllib.parse
import base64
from typing import List, Tuple

import aiohttp

# -------------------- Константы и шаблоны --------------------
PROTOCOL_PREFIXES = (
    "vmess://", "vless://", "trojan://", "ss://", "ssr://",
    "tuic://", "hysteria://", "hysteria2://", "hy2://",
    "socks5://", "socks4://", "wireguard://", "ssh://",
    "snell://", "brook://", "juicity://",
)

INSECURE_PATTERN = re.compile(
    r'(?:[?&;]|3%[Bb])(allowinsecure|allow_insecure|insecure)=(?:1|true|yes)(?:[&;#]|$|(?=\s|$))',
    re.IGNORECASE,
)

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)

# -------------------- Утилиты разбора --------------------

def try_decode_base64(data: str) -> str:
    """Проверяет, является ли строка списком в Base64, и декодирует её."""
    if "://" not in data:
        try:
            clean_data = "".join(data.split())
            rem = len(clean_data) % 4
            if rem:
                clean_data += "=" * (4 - rem)
            decoded = base64.b64decode(clean_data).decode("utf-8", errors="ignore")
            if any(prefix in decoded.lower() for prefix in PROTOCOL_PREFIXES):
                return decoded
        except Exception:
            pass
    return data


def filter_insecure_configs(data: str) -> Tuple[str, int]:
    """Декодирует Base64, разделяет конфиги и фильтрует только валидные и безопасные."""
    data = try_decode_base64(data)

    pattern = "|".join(p.replace("://", "") for p in PROTOCOL_PREFIXES)
    data = re.sub(
        rf"({pattern})://",
        r"\n\1://",
        data,
        flags=re.IGNORECASE,
    )

    result: List[str] = []
    insecure_count = 0
    for line in data.splitlines():
        line_stripped = line.strip()
        if not line_stripped:
            continue
        if not line_stripped.lower().startswith(PROTOCOL_PREFIXES):
            continue
        processed = urllib.parse.unquote(html.unescape(line_stripped))
        if not INSECURE_PATTERN.search(processed):
            result.append(line_stripped)
        else:
            insecure_count += 1

    return "\n".join(result), insecure_count

# -------------------- Источники: передаются извне --------------------

# -------------------- Загрузка данных (aiohttp) --------------------

async def _fetch_once(session: aiohttp.ClientSession, url: str, timeout: int, ssl_opt) -> str:
    async with session.get(url, timeout=timeout, ssl=ssl_opt) as resp:
        resp.raise_for_status()
        return await resp.text()


async def fetch_data_resilient(session: aiohttp.ClientSession, url: str, timeout: int = 10, allow_http_downgrade: bool = True) -> str:
    """До 3 попыток: 1) https+verify; 2) https без валидации; 3) http без валидации (если возможно)."""
    last_exc: Exception | None = None
    parsed = urllib.parse.urlparse(url)
    for attempt in (1, 2, 3):
        try:
            if attempt == 1:
                return await _fetch_once(session, url, timeout, ssl_opt=True)
            elif attempt == 2:
                return await _fetch_once(session, url, timeout, ssl_opt=False)
            else:
                if parsed.scheme == "https" and allow_http_downgrade:
                    downgraded = parsed._replace(scheme="http").geturl()
                    return await _fetch_once(session, downgraded, timeout, ssl_opt=False)
        except Exception as exc:
            last_exc = exc
            continue
    raise last_exc or RuntimeError("fetch failed")

# -------------------- Главная функция парсера --------------------

async def fetch_and_parse(source_urls: List[str], concurrency: int = 16) -> List[str]:
    """Загружает указанные источники и возвращает список безопасных прокси-ссылок.

    source_urls — список HTTP(S) ссылок на страницы/подписки с конфигами.
    """
    urls = [u.strip() for u in source_urls if isinstance(u, str) and u.strip().lower().startswith(("http://", "https://"))]
    if not urls:
        return []

    connector = aiohttp.TCPConnector(limit=concurrency)
    headers = {"User-Agent": CHROME_UA}
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        sem = asyncio.BoundedSemaphore(concurrency)
        results: List[str] = []

        async def worker(src: str):
            async with sem:
                try:
                    text = await fetch_data_resilient(session, src, timeout=10)
                    cleaned, _ = filter_insecure_configs(text)
                    # Извлекаем прокси-ссылки (оставляем только строки начинающиеся с протоколов)
                    for line in cleaned.splitlines():
                        ls = line.strip()
                        if ls.lower().startswith(PROTOCOL_PREFIXES):
                            results.append(ls)
                except Exception:
                    return

        tasks = [asyncio.create_task(worker(u)) for u in urls]
        await asyncio.gather(*tasks)

    # Дедупликация
    return list(dict.fromkeys(results))

#!/usr/bin/env python3
"""
NetPrivacy Verification Tool — Mobile CLI
==========================================
Reads proxy links from sources.txt (local + remote URLs),
runs checks with the mobile-optimised scanner, writes results.

Output files (in results/):
  results.json  — full structured data
  results.txt   — human-readable proxy list with tags

Usage:
    python checker.py
    python checker.py --sources data/sources.txt --concurrency 10
    python checker.py --no-gemini --out results/custom.json
    python checker.py --help
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List

import aiohttp

sys.path.insert(0, str(Path(__file__).parent))
from core.scanner import MobileScanner, NodeResult, ScanConfig

PROXY_RE = re.compile(
    r'(vless|vmess|trojan|ss)://[^\s<>"\']+', re.IGNORECASE
)

_DEFAULT_SOURCES = Path(__file__).parent / "data" / "sources.txt"
_DEFAULT_OUT     = Path(__file__).parent / "results" / "results.json"
_CACHE_PATH      = Path(__file__).parent / "data" / "links_cache.json"


# ─────────────────────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────────────────────

def _save_cache(links: List[str]) -> None:
    """Сохраняет список ссылок в JSON-кэш (перезаписывает старый)."""
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cached_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(links),
            "links": links,
        }
        with open(_CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_cache() -> List[str]:
    """Загружает ссылки из кэша. Возвращает пустой список если кэша нет."""
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload.get("links", [])
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Link collection
# ─────────────────────────────────────────────────────────────────────────────

async def _collect_links(sources_path: str) -> List[str]:
    links: List[str] = []
    seen: set = set()

    with open(sources_path, encoding="utf-8") as fh:
        raw_lines = [l.strip() for l in fh if l.strip() and not l.startswith("#")]

    direct = [
        l for l in raw_lines
        if l.lower().startswith(("vless://", "vmess://", "trojan://", "ss://"))
    ]
    remote = [l for l in raw_lines if l.lower().startswith("http")]

    for lnk in direct:
        if lnk not in seen:
            seen.add(lnk)
            links.append(lnk)

    fetched_from_remote: List[str] = []

    if remote:
        _log(f"Загружаю ссылки с {len(remote)} удалённых источников…")
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        ) as sess:
            for url in remote:
                try:
                    async with sess.get(
                        url, timeout=aiohttp.ClientTimeout(total=12)
                    ) as r:
                        text = await r.text(errors="ignore")
                    for m in PROXY_RE.finditer(text):
                        lnk = m.group(0).rstrip(".,;)")
                        if lnk not in seen:
                            seen.add(lnk)
                            links.append(lnk)
                            fetched_from_remote.append(lnk)
                except Exception as exc:
                    _log(f"[WARN] {url[:60]} — {exc}")

    if fetched_from_remote:
        _save_cache(fetched_from_remote)
        _log(f"Кэш обновлён: сохранено {len(fetched_from_remote)} ссылок.")
    elif remote:
        cached = _load_cache()
        if cached:
            for lnk in cached:
                if lnk not in seen:
                    seen.add(lnk)
                    links.append(lnk)
            _log(f"Удалённые источники недоступны — загружено {len(cached)} ссылок из кэша.")
        else:
            _log("[WARN] Удалённые источники недоступны и кэш отсутствует.")

    return links


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# Result saving
# ─────────────────────────────────────────────────────────────────────────────

def _save(results: List[NodeResult], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump([r.to_dict() for r in results], fh, ensure_ascii=False, indent=2)

    txt_path = out_path.with_suffix(".txt")
    with open(txt_path, "w", encoding="utf-8") as fh:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        high = [r for r in results if r.is_high_reliability]
        fh.write(f"# NetPrivacy Mobile — {now}\n")
        fh.write(f"# Всего: {len(results)} живых  /  {len(high)} высокая надёжность\n\n")

        fh.write("# ── HIGH RELIABILITY ────────────────────────────────────\n\n")
        for r in results:
            if not r.is_high_reliability:
                continue
            tags = (" | " + " | ".join(r.tags)) if r.tags else ""
            fh.write(f"# {r.accessibility} | Avg:{r.avg_resource_rtt:.0f}ms | {r.name}{tags}\n")
            fh.write(f"{r.link}\n\n")

        fh.write("# ── остальные ────────────────────────────────────────────\n\n")
        for r in results:
            if r.is_high_reliability:
                continue
            tags = (" | " + " | ".join(r.tags)) if r.tags else ""
            fh.write(f"# {r.accessibility} | Avg:{r.avg_resource_rtt:.0f}ms | {r.name}{tags}\n")
            fh.write(f"{r.link}\n\n")

    _log(f"JSON → {out_path}")
    _log(f"TXT  → {txt_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main coroutine
# ─────────────────────────────────────────────────────────────────────────────

async def _run(args: argparse.Namespace) -> None:
    _log("NetPrivacy Mobile Scanner")
    _log(f"Источники : {args.sources}")
    _log(f"Параллельность: {args.concurrency}   Gemini: {not args.no_gemini}")

    links = await _collect_links(args.sources)
    _log(f"Загружено ссылок: {len(links)}")

    if not links:
        _log("Ссылки не найдены. Проверь sources.txt")
        return

    cfg = ScanConfig(
        concurrency=args.concurrency,
        check_gemini=not args.no_gemini,
    )
    scanner = MobileScanner(config=cfg, log_callback=_log)

    results: List[NodeResult] = []
    checked = 0

    try:
        async for node in scanner.scan(links):
            results.append(node)
            checked += 1
            star = "★" if node.is_high_reliability else " "
            gem  = " | Gemini_Ready" if node.gemini_ready else ""
            _log(
                f"  {star} {node.name[:40]} | {node.accessibility} | "
                f"Avg:{node.avg_resource_rtt:.0f}ms{gem}"
            )

    except KeyboardInterrupt:
        _log("Прервано — сохраняю частичные результаты…")
        scanner.stop()

    results.sort(key=lambda r: (-r.accessible_count, r.avg_resource_rtt))

    high = [r for r in results if r.is_high_reliability]
    _log(f"Готово: {len(results)} живых, {len(high)} высокая надёжность")

    if results:
        _save(results, Path(args.out))
    else:
        _log("Живых нод не найдено.")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="NetPrivacy Mobile Scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python checker.py
  python checker.py --concurrency 5
  python checker.py --sources my_links.txt --no-gemini
  python checker.py --out /sdcard/results.json
""",
    )
    ap.add_argument(
        "--sources",
        default=str(_DEFAULT_SOURCES),
        help="Путь к файлу с ссылками / URL-источниками",
    )
    ap.add_argument(
        "--out",
        default=str(_DEFAULT_OUT),
        help="Путь к JSON-файлу с результатами",
    )
    ap.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Кол-во параллельных проверок (по умолч. 10)",
    )
    ap.add_argument(
        "--no-gemini",
        action="store_true",
        help="Пропустить проверку Gemini (быстрее)",
    )
    args = ap.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()

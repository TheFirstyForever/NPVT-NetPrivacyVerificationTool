#  Copyright (C) 2026  @TheFirSStYfOreVer
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
NetPrivacy Verification Tool - Modern GUI Edition
Powered by Flet
Made by @TheFirSStYfOreVer
"""

import asyncio
import contextlib
import json
import os
import re
import sys
import time
import webbrowser
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote

import flet as ft

import aiohttp

# Core imports
from core.scanner import LogicVerifier
from core.sub_server import LocalSubscriptionServer
from core.goida_parser import fetch_and_parse

# Pyperclip для копирования
try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False

# Константы
CONCURRENT_LIMIT = 50
HARD_MAX_WORKERS_AT_100 = 200
SUBSCRIPTION_HOST = "127.0.0.1"
SUBSCRIPTION_PORT = 54321
SUBSCRIPTION_URL = f"http://{SUBSCRIPTION_HOST}:{SUBSCRIPTION_PORT}/sub"
PROXY_REGEX = re.compile(r'(vless|vmess|trojan|ss)://[^\s<>"\']+', re.IGNORECASE)

def _get_runtime_base() -> str:
    try:
        if getattr(sys, 'frozen', False):
            base = getattr(sys, '_MEIPASS', None)
            if base and os.path.isdir(base):
                return os.path.abspath(base)
            return os.path.abspath(os.path.dirname(sys.executable))
        # running from sources: this file is app/main.py
        return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    except Exception:
        return os.getcwd()

def _get_user_base() -> str:
    try:
        if sys.platform == 'win32':
            base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~\\AppData\\Local')
        else:
            base = os.path.expanduser('~/.local/share')
        path = os.path.join(base, 'NetPrivacyTool')
        os.makedirs(path, exist_ok=True)
        return path
    except Exception:
        return os.getcwd()

RUNTIME_BASE = _get_runtime_base()
USER_BASE = _get_user_base()
LINKS_CACHE_PATH = os.path.join(USER_BASE, "links_cache.json")
# Sources path: check embedded (app/data/) first, then portable layout (data/)
_sources_candidates = [
    os.path.join(RUNTIME_BASE, "app", "data", "sources.txt"),
    os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else RUNTIME_BASE, "data", "sources.txt"),
]
SOURCES_PATH = next((p for p in _sources_candidates if os.path.isfile(p)), _sources_candidates[0])
RESULTS_PATH = os.path.join(USER_BASE, "verified_nodes.txt")


def is_proxy_link(text):
    """Проверяет, является ли строка прокси-ссылкой."""
    return text.startswith(("vless://", "vmess://", "trojan://", "ss://"))


def _save_links_cache(links: List[str]) -> None:
    """Сохраняет список удалённо загруженных ссылок в кэш."""
    try:
        os.makedirs(os.path.dirname(LINKS_CACHE_PATH), exist_ok=True)
        payload = {
            "cached_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(links),
            "links": links,
        }
        with open(LINKS_CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_links_cache() -> List[str]:
    """Загружает ссылки из кэша. Возвращает пустой список если кэша нет."""
    try:
        with open(LINKS_CACHE_PATH, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload.get("links", [])
    except Exception:
        return []


@dataclass
class _UiStatsSnapshot:
    cps: float = 0.0
    active_workers: int = 0
    avg_latency_ms: float = 0.0
    current_task: str = ""
    completed: int = 0
    total: int = 0


class _TuiAdapter:
    """Минимальный адаптер, чтобы LogicVerifier мог сообщать текущий конфиг и читать stop-флаги."""

    def __init__(self, on_current_task) -> None:
        self._stop_requested = False
        self.is_running = False
        self._on_current_task = on_current_task

    async def log(self, message: str) -> None:
        return

    def set_current_config(self, config: dict, name: str = "") -> None:
        try:
            self._on_current_task(name or "")
        except Exception:
            pass


class VerificationController:
    def __init__(
        self,
        *,
        on_log,
        on_results_batch,
        on_stats,
    ) -> None:
        self._on_log = on_log
        self._on_results_batch = on_results_batch
        self._on_stats = on_stats

        self.scanner: Optional[LogicVerifier] = None
        self._tui = _TuiAdapter(self._set_current_task)
        self._stop_requested = False
        self._main_task: Optional[asyncio.Task] = None
        self._active_tasks: List[asyncio.Task] = []

        self._runtime_tune_event = asyncio.Event()

        self._stats_lock = asyncio.Lock()
        self._stats_done_times = deque()
        self._stats_latencies_ms = deque(maxlen=200)
        self._stats_cps_ema = 0.0
        self._stats_current_task = ""

        self._completed = 0
        self._total = 0

        self.current_results: List[dict] = []
        self.sub_server = LocalSubscriptionServer(
            data_provider=lambda: list(self.current_results),
            host=SUBSCRIPTION_HOST,
            port=SUBSCRIPTION_PORT,
        )
        self._sub_task: Optional[asyncio.Task] = None

        self.is_running = False
        self._forsage = False
        self._target_cps = 10
        self._source_mode = "auto"

    async def start(self, *, target_cps: int, forsage: bool, source_mode: str) -> None:
        if self.is_running:
            return

        self._stop_requested = False
        self.is_running = True
        self._tui._stop_requested = False
        self._tui.is_running = True
        self._forsage = bool(forsage)
        self._target_cps = int(target_cps or 0)
        self._source_mode = str(source_mode or "auto").lower()
        self._runtime_tune_event.clear()

        self.current_results = []
        self._completed = 0
        self._total = 0
        async with self._stats_lock:
            self._stats_done_times.clear()
            self._stats_latencies_ms.clear()
            self._stats_cps_ema = 0.0
            self._stats_current_task = ""

        if self._sub_task is None or self._sub_task.done():
            self._sub_task = asyncio.create_task(self._ensure_sub_server())

        self._emit_log(
            f"Starting verification | Target CPS: {'MAX (Forsage)' if self._forsage else self._target_cps}",
            "info",
        )

        self._main_task = asyncio.create_task(self._run())

    async def set_runtime_settings(self, *, target_cps: int, forsage: bool) -> None:
        if not self.is_running:
            self._forsage = bool(forsage)
            self._target_cps = int(target_cps or 0)
            return

        self._forsage = bool(forsage)
        self._target_cps = int(target_cps or 0)
        try:
            self._emit_log(
                f"Runtime update | Target CPS: {'MAX (Forsage)' if self._forsage else self._target_cps}",
                "info",
            )
        except Exception:
            pass
        try:
            self._runtime_tune_event.set()
        except Exception:
            pass

    async def stop(self) -> None:
        if not self.is_running:
            return

        self._emit_log("STOPPING: cancelling operations...", "warning")
        self._stop_requested = True
        self.is_running = False
        self._tui._stop_requested = True
        self._tui.is_running = False

        if self._main_task and (not self._main_task.done()):
            self._main_task.cancel()

        for task in list(self._active_tasks):
            try:
                if task and (not task.done()):
                    task.cancel()
            except Exception:
                pass

        if self._active_tasks:
            with contextlib.suppress(Exception):
                await asyncio.gather(*self._active_tasks, return_exceptions=True)
        self._active_tasks = []

        if self.scanner is not None:
            try:
                await asyncio.to_thread(self.scanner.kill_all_processes)
            except Exception:
                pass
            try:
                await asyncio.to_thread(self.scanner.kill_shadow_processes, "npvt_run_")
            except Exception:
                pass
            try:
                await asyncio.to_thread(self.scanner.cleanup_temp_now)
            except Exception:
                pass

        self._emit_log("Verification stopped", "success")

    async def shutdown(self) -> None:
        try:
            await self.stop()
        finally:
            try:
                await self.sub_server.stop()
            except Exception:
                pass

    def _emit_log(self, message: str, tag: str = "info") -> None:
        try:
            self._on_log(message, tag)
        except Exception:
            pass

    def _set_current_task(self, name: str) -> None:
        try:
            # Called from LogicVerifier synchronous context.
            self._stats_current_task = str(name or "")
        except Exception:
            pass

    def _fast_log_callback(self, message: str) -> None:
        try:
            if message.startswith("[DEBUG]") or message.startswith("[*]"):
                return
            if message.startswith("[XRAY]") or message.startswith("[CLEANUP]"):
                return
        except Exception:
            pass

        tag = "info"
        if "[ERROR]" in message or "[!]" in message:
            tag = "error"
        elif "[ACTIVE]" in message or "[+]" in message:
            tag = "success"
        elif "[WARN]" in message:
            tag = "warning"
        elif "[INACTIVE]" in message:
            tag = "warning"
        self._emit_log(message, tag)

    async def _ensure_sub_server(self) -> None:
        try:
            await self.sub_server.start()
            ok = await self.sub_server.wait_until_started(1.5)
            if ok:
                self._emit_log(f"[SUB] Local subscription server: {SUBSCRIPTION_URL}", "info")
        except Exception:
            pass

    async def _run(self) -> None:
        try:
            results = await self._do_verification()
            if results:
                self._emit_log(f"Verification complete. Total nodes: {len(results)}", "success")
                await asyncio.to_thread(self._save_results_to_file, results)
            else:
                self._emit_log("Verification finished with no results", "warning")
        except asyncio.CancelledError:
            self._emit_log("Verification cancelled", "warning")
        except Exception as e:
            self._emit_log(f"[FATAL] {str(e)[:200]}", "error")
        finally:
            self.is_running = False
            self._tui.is_running = False

    def _save_results_to_file(self, results: list) -> None:
        try:
            results.sort(
                key=lambda x: (-x.get("accessible_count", 0), x.get("avg_resource_rtt", 99999))
            )

            os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
            with open(RESULTS_PATH, "w", encoding="utf-8") as f:
                for r in results:
                    if r.get("is_high_reliability"):
                        f.write(
                            f"# HIGH RELIABILITY {r.get('accessibility')} | Avg: {r.get('avg_resource_rtt')}ms | {r['name']}\n"
                        )
                        f.write(f"{r['link']}\n\n")

                for r in results:
                    if not r.get("is_high_reliability"):
                        f.write(
                            f"# {r.get('accessibility')} | Avg: {r.get('avg_resource_rtt')}ms | {r['name']}\n"
                        )
                        f.write(f"{r['link']}\n\n")

            self._emit_log(f"Results saved to {RESULTS_PATH}", "success")
        except Exception as e:
            self._emit_log(f"Save error: {e}", "error")

    async def _do_verification(self) -> List[dict]:
        src_path = SOURCES_PATH

        if not os.path.exists(src_path):
            self._emit_log("ERROR: app/data/sources.txt not found!", "error")
            return []

        self.scanner = LogicVerifier(tui=self._tui, log_callback=self._fast_log_callback)

        _exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else RUNTIME_BASE
        _xray_candidates = [
            os.path.join(_exe_dir, "core", "nv_backend_core.exe"),
            os.path.join(_exe_dir, "core", "npvt_core.exe"),
            os.path.join(_exe_dir, "core", "xray.exe"),
            os.path.join(RUNTIME_BASE, "app", "bin", "npvt_core.exe"),
            os.path.join(RUNTIME_BASE, "app", "bin", "xray.exe"),
            os.path.join(_exe_dir, "core", "bin", "nv_backend_core.exe"),
            os.path.join(_exe_dir, "core", "bin", "npvt_core.exe"),
            os.path.join(_exe_dir, "core", "bin", "np_engine.exe"),
            os.path.join(_exe_dir, "core", "bin", "xray.exe"),
            os.path.join(_exe_dir, "app", "bin", "xray.exe"),
            os.path.join(os.path.dirname(_exe_dir), "app", "bin", "xray.exe"),
        ]
        for xr_bin in _xray_candidates:
            if os.path.isfile(xr_bin):
                self.scanner.bin_path = xr_bin
                break
        try:
            self.scanner._engine_path = self.scanner.bin_path
        except Exception:
            pass
        try:
            self.scanner.deep_checks = True
        except Exception:
            pass

        all_links: List[str] = []

        self._emit_log("Collecting proxy configurations...", "info")
        with open(src_path, "r", encoding="utf-8") as f:
            sources = [line.strip() for line in f if line.strip()]
        self._emit_log(f"Loaded {len(sources)} sources", "info")

        source_mode = self._source_mode
        remote_links_fetched: List[str] = []

        if source_mode == "cache":
            self._emit_log("Source mode: CACHE (offline)", "info")
            cached = _load_links_cache()
            if cached:
                all_links.extend(cached)
                self._emit_log(f"Loaded {len(cached)} links from cache.", "info")
            else:
                self._emit_log("Cache is empty! Run in Auto / Online mode first.", "error")
        elif source_mode == "parse":
            self._emit_log("Parse mode: parsing sources...", "info")
            parsed = await fetch_and_parse(sources, concurrency=min(max(1, self._target_cps), 32))
            if not parsed:
                self._emit_log("Parser returned no links", "error")
                return []
            all_links.extend(parsed)
            self._emit_log(f"Parser collected {len(parsed)} links", "success")
        else:
            async with aiohttp.ClientSession() as session:
                for source in sources:
                    if self._stop_requested or (not self.is_running):
                        break

                    if is_proxy_link(source):
                        all_links.append(source)
                        continue

                    if source.startswith(("http://", "https://")):
                        try:
                            self._emit_log(f"Loading: {source[:60]}...", "info")
                            async with session.get(source, timeout=15) as resp:
                                if resp.status != 200:
                                    self._emit_log(f"HTTP {resp.status}: {source[:50]}", "error")
                                    continue

                                text = await resp.text()
                                parse_text = text
                                if not PROXY_REGEX.search(text):
                                    try:
                                        import base64 as _b64

                                        clean = text.strip()
                                        pad = (4 - len(clean) % 4) % 4
                                        parse_text = _b64.b64decode(clean + "=" * pad).decode("utf-8")
                                    except Exception:
                                        parse_text = text

                                full_links = [m.group(0) for m in PROXY_REGEX.finditer(parse_text)]
                                unique_links = list(set(full_links))
                                all_links.extend(unique_links)
                                remote_links_fetched.extend(unique_links)
                                self._emit_log(
                                    f"Found {len(unique_links)} links from {source[:50]}...",
                                    "success",
                                )
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            self._emit_log(f"Error loading {source[:50]}: {e}", "error")

            if remote_links_fetched:
                _save_links_cache(remote_links_fetched)
                self._emit_log(
                    f"Cache updated: {len(remote_links_fetched)} remote links saved.",
                    "info",
                )
            elif source_mode == "auto":
                cached = _load_links_cache()
                if cached:
                    all_links.extend(cached)
                    self._emit_log(
                        f"GitHub unavailable — loaded {len(cached)} links from cache.",
                        "warning",
                    )
                else:
                    self._emit_log("No remote links fetched and no cache available.", "error")
            else:
                self._emit_log(
                    "Online mode: remote sources unavailable. Check your connection.",
                    "error",
                )

        all_links = list(dict.fromkeys(all_links))
        if not all_links:
            self._emit_log("No configurations found!", "error")
            return []

        if self._stop_requested or (not self.is_running):
            return []

        total = len(all_links)
        self._total = total
        self._emit_log(f"Total unique links: {total}", "info")

        results: List[dict] = []
        completed = 0

        q: asyncio.Queue[Optional[str]] = asyncio.Queue()
        for link in all_links:
            q.put_nowait(link)

        busy_workers = 0
        busy_lock = asyncio.Lock()

        worker_tasks: List[asyncio.Task] = []

        max_workers_non_forsage = min(HARD_MAX_WORKERS_AT_100, total)
        max_workers_forsage = min(max(HARD_MAX_WORKERS_AT_100, 400), total)

        def desired_workers() -> int:
            forsage_now = bool(self._forsage)
            target_cps_now = int(self._target_cps or 0)
            cap = max_workers_forsage if forsage_now else max_workers_non_forsage
            if forsage_now:
                return cap
            return min(cap, max(1, target_cps_now * 3))

        def spawn_workers(n: int) -> None:
            while len(worker_tasks) < n:
                wid = len(worker_tasks)
                t = asyncio.create_task(worker(wid))
                worker_tasks.append(t)
                self._active_tasks.append(t)

        if self._forsage:
            self._emit_log(
                f"Target CPS: MAX (Forsage) | Workers: {desired_workers()} | Max: {max_workers_forsage}",
                "info",
            )
        else:
            self._emit_log(
                f"Target CPS: {int(self._target_cps or 0)} | Workers: {desired_workers()} | Max: {max_workers_non_forsage}",
                "info",
            )

        def emit_stats(active_procs: int, cps_val: float, avg_lat: float) -> None:
            snap = _UiStatsSnapshot(
                cps=cps_val,
                active_workers=active_procs,
                avg_latency_ms=avg_lat,
                current_task=str(self._stats_current_task or ""),
                completed=completed,
                total=total,
            )
            try:
                self._on_stats(snap)
            except Exception:
                pass

        async def worker(worker_id: int) -> None:
            nonlocal completed
            nonlocal busy_workers
            while True:
                if self._stop_requested or (not self.is_running):
                    return
                try:
                    link = await q.get()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    return

                if link is None:
                    try:
                        q.task_done()
                    except Exception:
                        pass
                    return

                async with busy_lock:
                    busy_workers += 1

                try:
                    t0 = time.monotonic()
                    res = await self.scanner.check_connection(link, None)  # type: ignore[union-attr]
                    dt_ms = (time.monotonic() - t0) * 1000.0
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self._emit_log(f"[WORKER ERROR] {str(e)[:120]}", "error")
                    res = None
                    dt_ms = 0.0
                finally:
                    try:
                        q.task_done()
                    except Exception:
                        pass

                    async with busy_lock:
                        busy_workers = max(0, busy_workers - 1)

                completed += 1
                self._completed = completed

                now_ts = time.monotonic()
                async with self._stats_lock:
                    self._stats_done_times.append(now_ts)
                    if dt_ms > 0:
                        self._stats_latencies_ms.append(float(dt_ms))

                if res is not None:
                    results.append(res)
                    try:
                        self._on_results_batch([res])
                    except Exception:
                        pass
                    try:
                        self.current_results.append(res)
                    except Exception:
                        pass

                if (completed % 25 == 0) or (completed == total):
                    self._emit_log(
                        f"Progress: {completed}/{total} ({(completed * 100) // max(1, total)}%)",
                        "info",
                    )

                if completed >= total:
                    return

        async def controller_and_stats() -> None:
            window_s = 1.5
            alpha = 0.22
            while True:
                if self._stop_requested or (not self.is_running):
                    return

                try:
                    try:
                        await asyncio.wait_for(self._runtime_tune_event.wait(), timeout=0.25)
                    except asyncio.TimeoutError:
                        pass
                    self._runtime_tune_event.clear()
                except Exception:
                    await asyncio.sleep(0.25)

                try:
                    spawn_workers(desired_workers())
                except Exception:
                    pass

                async with busy_lock:
                    active_busy = int(busy_workers)

                now_ts = time.monotonic()
                async with self._stats_lock:
                    while self._stats_done_times and (now_ts - self._stats_done_times[0] > window_s):
                        self._stats_done_times.popleft()
                    inst_cps = (len(self._stats_done_times) / window_s) if window_s > 0 else 0.0
                    self._stats_cps_ema = (self._stats_cps_ema * (1.0 - alpha)) + (inst_cps * alpha)
                    cps_val = float(self._stats_cps_ema)
                    if self._stats_latencies_ms:
                        avg_lat = float(
                            sum(self._stats_latencies_ms) / max(1, len(self._stats_latencies_ms))
                        )
                    else:
                        avg_lat = 0.0

                emit_stats(active_busy, cps_val, avg_lat)

                if completed >= total:
                    return

        self._active_tasks = []
        spawn_workers(desired_workers())
        stats_task = asyncio.create_task(controller_and_stats())
        self._active_tasks.append(stats_task)

        try:
            await q.join()
        finally:
            for t in list(worker_tasks):
                try:
                    t.cancel()
                except Exception:
                    pass
            try:
                stats_task.cancel()
            except Exception:
                pass

            all_tasks = list(worker_tasks) + [stats_task]
            if all_tasks:
                with contextlib.suppress(Exception):
                    await asyncio.gather(*all_tasks, return_exceptions=True)

            self._active_tasks = []

        emit_stats(0, 0.0, 0.0)
        return results


class NPVTFletApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page

        self._log_buffer: deque = deque()
        self._result_buffer: deque = deque()
        self._best_results_by_link: dict = {}
        self._best_results_keep = 200
        self._best_results_topn = 20
        self._stats_snapshot = _UiStatsSnapshot()
        self._dirty = asyncio.Event()

        self.controller = VerificationController(
            on_log=self._on_log,
            on_results_batch=self._on_results_batch,
            on_stats=self._on_stats,
        )

        self._ui_task: Optional[asyncio.Task] = None

        self._snack = ft.SnackBar(ft.Text(""))
        try:
            self.page.overlay.append(self._snack)
        except Exception:
            pass

        self._build_ui()

    def _build_ui(self) -> None:
        self.page.title = "NetPrivacy Verification Tool | @TheFirSStYfOreVer"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#0B0F14"
        self.page.padding = 16

        self.page.dark_theme = ft.Theme(color_scheme_seed=ft.Colors.CYAN)

        self.target_cps_dd = ft.Dropdown(
            label="Target CPS",
            width=160,
            options=[
                ft.dropdown.Option("5"),
                ft.dropdown.Option("10"),
                ft.dropdown.Option("20"),
                ft.dropdown.Option("MAX"),
            ],
            value="10",
        )

        try:
            self.target_cps_dd.on_change = self._on_runtime_cps_change
        except Exception:
            pass

        self.source_mode_dd = ft.Dropdown(
            label="Source mode",
            width=160,
            options=[
                ft.dropdown.Option("Auto"),
                ft.dropdown.Option("Online"),
                ft.dropdown.Option("Cache"),
                ft.dropdown.Option("Parse"),
            ],
            value="Auto",
        )

        self.vpn_client_dd = ft.Dropdown(
            label="VPN client",
            width=316,
            options=[
                ft.dropdown.Option("Happ"),
                ft.dropdown.Option("Clash"),
                ft.dropdown.Option("Hiddify"),
                ft.dropdown.Option("v2rayN"),
                ft.dropdown.Option("NekoRay"),
                ft.dropdown.Option("Browser"),
            ],
            value="Happ",
        )

        self.start_btn = ft.ElevatedButton(
            "START",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._on_start_click,
            height=44,
        )
        self.stop_btn = ft.ElevatedButton(
            "STOP",
            icon=ft.Icons.STOP,
            on_click=self._on_stop_click,
            height=44,
            disabled=True,
        )

        self.progress_text = ft.Text("0/0", size=12, color="#94A3B8")
        self.progress_bar = ft.ProgressBar(value=0.0, height=8)

        self.cps_text = ft.Text(
            "0.0",
            size=74,
            weight=ft.FontWeight.W_900,
            color="#22D3EE",
            font_family="Consolas",
        )
        self.cps_label = ft.Text("CPS", size=14, color="#94A3B8")
        self.cps_ring = ft.ProgressRing(
            value=0.0,
            width=170,
            height=170,
            stroke_width=10,
            color="#22D3EE",
            bgcolor="#111827",
        )

        self.active_workers_text = ft.Text("0", size=28, weight=ft.FontWeight.BOLD)
        self.avg_latency_text = ft.Text("0 ms", size=28, weight=ft.FontWeight.BOLD)
        self.current_task_text = ft.Text(
            "",
            size=14,
            color="#E2E8F0",
            overflow=ft.TextOverflow.ELLIPSIS,
            max_lines=1,
        )

        self.logs_view = ft.ListView(expand=True, spacing=2, auto_scroll=True)
        self.results_view = ft.ListView(expand=True, spacing=6, auto_scroll=False)

        self.copy_logs_btn = ft.IconButton(
            icon=ft.Icons.CONTENT_COPY,
            tooltip="Copy logs",
            on_click=self._on_copy_logs_click,
        )

        self.copy_subscription_btn = ft.ElevatedButton(
            "COPY SUBSCRIPTION",
            icon=ft.Icons.COPY_ALL,
            on_click=self._on_copy_subscription_click,
            height=44,
        )

        self.copy_best_btn = ft.ElevatedButton(
            "Скопировать лучший конфиг",
            icon=ft.Icons.STAR,
            on_click=self._on_copy_best_click,
            height=44,
        )

        self.import_subscription_btn = ft.ElevatedButton(
            "Импорт подписки",
            icon=ft.Icons.LAUNCH,
            on_click=self._on_import_subscription_click,
            height=44,
        )

        left_panel = ft.Container(
            width=340,
            padding=12,
            bgcolor="#0B0F14",
            content=ft.Column(
                spacing=12,
                controls=[
                    self._card(
                        "CONTROL",
                        ft.Column(
                            spacing=12,
                            controls=[
                                ft.Row([self.start_btn, self.stop_btn], spacing=12),
                                ft.Row([self.target_cps_dd, self.source_mode_dd], spacing=12),
                            ],
                        ),
                    ),
                    self._card(
                        "SUBSCRIPTION",
                        ft.Column(
                            spacing=10,
                            controls=[
                                self.copy_best_btn,
                                self.vpn_client_dd,
                                self.import_subscription_btn,
                                ft.Text(
                                    SUBSCRIPTION_URL,
                                    size=12,
                                    color="#94A3B8",
                                    selectable=True,
                                ),
                                self.copy_subscription_btn,
                            ],
                        ),
                    ),
                    self._card(
                        "PROGRESS",
                        ft.Column(
                            spacing=10,
                            controls=[
                                self.progress_text,
                                self.progress_bar,
                            ],
                        ),
                    ),
                    self._card(
                        "LOGS",
                        ft.Column(
                            expand=True,
                            spacing=8,
                            controls=[
                                ft.Row(
                                    [ft.Text("Stream"), ft.Container(expand=True), self.copy_logs_btn],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                                ft.Container(
                                    expand=True,
                                    padding=8,
                                    bgcolor="#0F172A",
                                    border_radius=12,
                                    content=self.logs_view,
                                ),
                            ],
                        ),
                        expand=True,
                    ),
                ],
                expand=True,
            ),
        )

        self.speedometer_card = ft.Container(
            padding=18,
            border_radius=18,
            border=ft.Border.all(1, "#1F2937"),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.TOP_LEFT,
                end=ft.Alignment.BOTTOM_RIGHT,
                colors=["#060B10", "#0B1220"],
            ),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Stack(
                        width=240,
                        height=240,
                        controls=[
                            ft.Container(alignment=ft.Alignment.CENTER, content=self.cps_ring),
                            ft.Container(
                                alignment=ft.Alignment.CENTER,
                                content=ft.Column(
                                    spacing=0,
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        self.cps_text,
                                        self.cps_label,
                                    ],
                                ),
                            ),
                        ],
                    ),
                    ft.Column(
                        expand=True,
                        spacing=12,
                        controls=[
                            ft.Row(
                                spacing=12,
                                controls=[
                                    self._metric_tile("Active workers", self.active_workers_text),
                                    self._metric_tile("Avg latency", self.avg_latency_text),
                                ],
                            ),
                            self._card(
                                "CURRENT TASK",
                                ft.Container(
                                    padding=10,
                                    bgcolor="#0F172A",
                                    border_radius=12,
                                    content=self.current_task_text,
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        )

        right_panel = ft.Container(
            expand=True,
            padding=12,
            bgcolor="#0B0F14",
            content=ft.Column(
                spacing=12,
                controls=[
                    self._card(
                        "PERFORMANCE",
                        self.speedometer_card,
                    ),
                    self._card(
                        "RESULTS",
                        ft.Container(
                            expand=True,
                            padding=8,
                            bgcolor="#0F172A",
                            border_radius=12,
                            content=self.results_view,
                        ),
                        expand=True,
                    ),
                ],
                expand=True,
            ),
        )

        root = ft.Row([left_panel, right_panel], expand=True, spacing=12)
        self.page.add(root)

        def on_close(e) -> None:
            self.page.run_task(self.controller.shutdown)

        self.page.on_close = on_close

    def _card(self, title: str, content: ft.Control, *, expand: bool = False) -> ft.Container:
        header = ft.Text(title, size=12, color="#94A3B8", weight=ft.FontWeight.BOLD)
        col = ft.Column([header, content], spacing=10, expand=expand)
        return ft.Container(
            padding=14,
            border_radius=16,
            border=ft.Border.all(1, "#1F2937"),
            bgcolor="#111827",
            content=col,
            expand=expand,
        )

    def _metric_tile(self, title: str, value: ft.Text) -> ft.Container:
        return ft.Container(
            expand=True,
            padding=14,
            border_radius=16,
            bgcolor="#111827",
            border=ft.Border.all(1, "#1F2937"),
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Text(title, size=12, color="#94A3B8"),
                    value,
                ],
            ),
        )

    def _on_log(self, message: str, tag: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_buffer.append((f"[{ts}] {message}", tag))
        if len(self._log_buffer) > 3000:
            for _ in range(800):
                try:
                    self._log_buffer.popleft()
                except Exception:
                    break
        self._dirty.set()

    def _on_results_batch(self, batch: List[dict]) -> None:
        self._result_buffer.extend(batch)
        try:
            if len(self._result_buffer) > 6000:
                for _ in range(3500):
                    try:
                        self._result_buffer.popleft()
                    except Exception:
                        break
        except Exception:
            pass
        self._dirty.set()

    def _on_stats(self, snap: _UiStatsSnapshot) -> None:
        self._stats_snapshot = snap
        self._dirty.set()

    async def _on_start_click(self, e) -> None:
        raw = str(self.target_cps_dd.value or "10").strip()
        if raw.upper() == "MAX":
            forsage = True
            target_cps = 0
        else:
            forsage = False
            try:
                target_cps = max(1, int(raw))
            except Exception:
                target_cps = 10

        self._apply_forsage_style(forsage)
        self._clear_views()

        self.start_btn.disabled = True
        self.stop_btn.disabled = False
        self.page.update()

        if self._ui_task is None or self._ui_task.done():
            self._ui_task = asyncio.create_task(self._ui_flush_loop())

        await self.controller.start(
            target_cps=target_cps,
            forsage=forsage,
            source_mode=str(self.source_mode_dd.value or "Auto").lower(),
        )

    def _on_stop_click(self, e) -> None:
        self.stop_btn.disabled = True
        self.page.update()
        self.page.run_task(self._stop_async)

    async def _stop_async(self) -> None:
        await self.controller.stop()
        self.start_btn.disabled = False
        self.stop_btn.disabled = True
        self._apply_forsage_style(False)
        self.page.update()

    def _show_snack(self, message: str) -> None:
        try:
            self._snack.content = ft.Text(message)
            self._snack.open = True
            self.page.update()
        except Exception:
            pass

    def _pick_best_link(self) -> Optional[str]:
        results = list(getattr(self.controller, "current_results", []) or [])
        if not results:
            return None

        def get_accessible_count(r: dict) -> int:
            ac = r.get("accessible_count")
            try:
                if ac is not None:
                    return int(ac)
            except Exception:
                pass

            acc = str(r.get("accessibility") or "")
            m = re.match(r"\s*(\d+)\s*/", acc)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    return 0
            return 0

        def key(r: dict):
            hi = 1 if r.get("is_high_reliability") else 0
            ac = get_accessible_count(r)
            rtt = r.get("avg_resource_rtt", 99999)
            try:
                rtt = float(rtt)
            except Exception:
                rtt = 99999.0
            return (hi, ac, -rtt)

        try:
            best = max(results, key=key)
            link = best.get("link")
            return str(link) if link else None
        except Exception:
            return None

    def _on_copy_best_click(self, e) -> None:
        try:
            self.page.run_task(self._copy_best_async)
        except Exception:
            pass

    async def _copy_best_async(self) -> None:
        link = self._pick_best_link()
        if not link:
            self._show_snack("Лучший конфиг пока не найден")
            return

        copied = False
        try:
            if HAS_PYPERCLIP:
                pyperclip.copy(link)
                copied = True
        except Exception:
            copied = False

        if not copied:
            try:
                await ft.Clipboard().set(link)
                copied = True
            except Exception:
                copied = False

        if copied:
            self._show_snack("Лучший конфиг скопирован!")
        else:
            self._show_snack("Не удалось скопировать конфиг")

    def _on_import_subscription_click(self, e) -> None:
        try:
            self.page.run_task(self._import_subscription_async)
        except Exception:
            pass

    async def _import_subscription_async(self) -> None:
        try:
            await self.controller._ensure_sub_server()
        except Exception:
            pass

        client = str(getattr(self.vpn_client_dd, "value", "Happ") or "Happ").strip()
        import_url = await self._build_import_url(client)

        if client in {"v2rayN", "NekoRay"}:
            copied = False
            try:
                if HAS_PYPERCLIP:
                    pyperclip.copy(SUBSCRIPTION_URL)
                    copied = True
            except Exception:
                copied = False
            if not copied:
                try:
                    await ft.Clipboard().set(SUBSCRIPTION_URL)
                except Exception:
                    pass
            self._show_snack("Ссылка на подписку скопирована. Импортируй её в клиент.")

        opened = False
        try:
            if sys.platform == "win32":
                try:
                    os.startfile(import_url)  # type: ignore[attr-defined]
                    opened = True
                except Exception:
                    opened = False

            if not opened:
                try:
                    webbrowser.open(import_url, new=1)
                    opened = True
                except Exception:
                    opened = False
        except Exception:
            opened = False

        if not opened:
            try:
                if HAS_PYPERCLIP:
                    pyperclip.copy(import_url)
                else:
                    await ft.Clipboard().set(import_url)
            except Exception:
                pass
            self._show_snack("Не удалось открыть ссылку. Скопировал deeplink в буфер.")
        else:
            self._show_snack("Открываю подписку...")

    async def _build_import_url(self, client: str) -> str:
        c = (client or "").strip().lower()
        encoded = quote(SUBSCRIPTION_URL, safe="")

        if c == "browser":
            return SUBSCRIPTION_URL

        if c == "clash":
            return f"clash://install-config?url={encoded}"

        if c == "hiddify":
            return f"hiddify://install-sub?url={encoded}#NPVT"

        if c == "happ":
            return f"happ://add/{SUBSCRIPTION_URL}"

        return SUBSCRIPTION_URL

    def _on_runtime_cps_change(self, e) -> None:
        try:
            if not self.controller.is_running:
                return
            raw = str(self.target_cps_dd.value or "10").strip()
            forsage = raw.upper() == "MAX"
            target = 0 if forsage else int(raw)
            self._apply_forsage_style(forsage)
            self.page.run_task(self.controller.set_runtime_settings, target_cps=target, forsage=forsage)
        except Exception:
            pass

    def _on_copy_subscription_click(self, e) -> None:
        try:
            self.page.run_task(self._copy_subscription_async)
        except Exception:
            pass

    async def _copy_subscription_async(self) -> None:
        copied = False
        try:
            if HAS_PYPERCLIP:
                pyperclip.copy(SUBSCRIPTION_URL)
                copied = True
        except Exception:
            copied = False

        if not copied:
            try:
                await ft.Clipboard().set(SUBSCRIPTION_URL)
                copied = True
            except Exception:
                copied = False

        if copied:
            self._show_snack("Ссылка на подписку скопирована!")
        else:
            self._show_snack("Не удалось скопировать ссылку")

    def _on_copy_logs_click(self, e) -> None:
        try:
            self.page.run_task(self._copy_logs_async)
        except Exception:
            pass

    async def _copy_logs_async(self) -> None:
        text = "\n".join([m for (m, _t) in list(self._log_buffer)])
        try:
            await ft.Clipboard().set(text)
            self._show_snack("Logs copied to clipboard")
        except Exception:
            pass

    def _apply_forsage_style(self, enabled: bool) -> None:
        color = "#FF0000" if enabled else "#22D3EE"
        border = "#FF0000" if enabled else "#1F2937"
        self.cps_text.color = color
        self.cps_ring.color = color
        self.speedometer_card.border = ft.Border.all(2 if enabled else 1, border)

    def _clear_views(self) -> None:
        self.logs_view.controls.clear()
        self.results_view.controls.clear()
        self._log_buffer.clear()
        self._result_buffer.clear()
        self._best_results_by_link.clear()
        self._stats_snapshot = _UiStatsSnapshot()
        self.progress_bar.value = 0.0
        self.progress_text.value = "0/0"
        self.cps_text.value = "0.0"
        self.cps_ring.value = 0.0
        self.active_workers_text.value = "0"
        self.avg_latency_text.value = "0 ms"
        self.current_task_text.value = ""

    async def _ui_flush_loop(self) -> None:
        min_interval = 0.4
        last = 0.0
        while True:
            if not self.controller.is_running and self.stop_btn.disabled:
                return

            await self._dirty.wait()
            now = time.monotonic()
            dt = now - last
            if dt < min_interval:
                await asyncio.sleep(min_interval - dt)
            last = time.monotonic()
            self._dirty.clear()

            self._flush_logs(max_items=120)
            self._flush_results(max_items=40)
            self._flush_stats()

            self.page.update()

    def _flush_logs(self, *, max_items: int) -> None:
        if not self._log_buffer:
            return

        color_map = {
            "error": "#F87171",
            "warning": "#FBBF24",
            "success": "#34D399",
            "debug": "#94A3B8",
            "info": "#E2E8F0",
        }
        n = 0
        while self._log_buffer and n < max_items:
            msg, tag = self._log_buffer.popleft()
            self.logs_view.controls.append(
                ft.Text(msg, size=11, color=color_map.get(tag, "#E2E8F0"), font_family="Consolas")
            )
            n += 1

        if len(self.logs_view.controls) > 1200:
            self.logs_view.controls = self.logs_view.controls[-900:]

    def _flush_results(self, *, max_items: int) -> None:
        def to_float(v, default: float) -> float:
            try:
                if v is None:
                    return default
                return float(v)
            except Exception:
                return default

        def quality_key(r: dict):
            ac = 0
            try:
                ac = int(r.get("accessible_count") or 0)
            except Exception:
                ac = 0
            success_rank = 0 if ac > 0 else 1
            hi_rank = 0 if bool(r.get("is_high_reliability")) else 1
            latency = to_float(r.get("avg_resource_rtt"), 999999.0)
            return (success_rank, hi_rank, latency)

        ingested = 0
        while self._result_buffer and ingested < max_items:
            try:
                r = self._result_buffer.popleft()
            except Exception:
                break

            link = r.get("link")
            if link:
                self._best_results_by_link[str(link)] = r
            ingested += 1

        if not self._best_results_by_link:
            return

        try:
            ordered = sorted(self._best_results_by_link.values(), key=quality_key)
        except Exception:
            ordered = list(self._best_results_by_link.values())

        if len(ordered) > int(self._best_results_keep):
            ordered = ordered[: int(self._best_results_keep)]
            try:
                self._best_results_by_link = {str(r.get("link")): r for r in ordered if r.get("link")}
            except Exception:
                pass

        top_n = int(self._best_results_topn)
        view_items = ordered[:top_n]

        controls: List[ft.Control] = []
        for idx, r in enumerate(view_items, start=1):
            name = r.get("name", "Unknown")
            acc = r.get("accessibility", "")
            avg = r.get("avg_resource_rtt", 0)
            hi = bool(r.get("is_high_reliability"))
            color = "#34D399" if hi else "#60A5FA"

            title_controls: List[ft.Control] = []
            if idx == 1:
                title_controls.append(ft.Icon(ft.Icons.EMOJI_EVENTS, size=18, color="#FBBF24"))
            title_controls.append(
                ft.Text(
                    f"{idx}. {name}",
                    size=13,
                    weight=ft.FontWeight.W_900 if idx == 1 else ft.FontWeight.BOLD,
                    color="#E2E8F0",
                )
            )

            controls.append(
                ft.Container(
                    padding=12,
                    border_radius=14,
                    bgcolor="#111827" if idx != 1 else "#0B1220",
                    border=ft.Border.all(1, "#1F2937"),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(
                                spacing=2,
                                controls=[
                                    ft.Row(title_controls, spacing=6),
                                    ft.Text(f"Success | {acc} | Avg: {avg}ms", size=11, color="#94A3B8"),
                                ],
                            ),
                            ft.Container(
                                padding=8,
                                border_radius=12,
                                bgcolor="#0F172A",
                                content=ft.Text(
                                    "HIGH" if hi else "OK",
                                    size=12,
                                    weight=ft.FontWeight.BOLD,
                                    color=color,
                                ),
                            ),
                        ],
                    ),
                )
            )

        self.results_view.controls = controls

    def _flush_stats(self) -> None:
        snap = self._stats_snapshot
        self.cps_text.value = f"{snap.cps:.1f}"
        self.active_workers_text.value = str(int(snap.active_workers))
        self.avg_latency_text.value = f"{int(snap.avg_latency_ms)} ms"
        self.current_task_text.value = snap.current_task

        if snap.total > 0:
            self.progress_text.value = f"{snap.completed}/{snap.total}"
            self.progress_bar.value = min(1.0, max(0.0, snap.completed / max(1, snap.total)))

        # Simple visualization scale: 0..50 CPS == full ring (dynamic would be noisier)
        ring_scale = 50.0
        self.cps_ring.value = min(1.0, max(0.0, float(snap.cps) / ring_scale))


async def main(page: ft.Page) -> None:
    NPVTFletApp(page)


if __name__ == "__main__":
    print(
        """
╔══════════════════════════════════════════════════════════════╗
║     NetPrivacy Verification Tool - Flet Dashboard Edition    ║
║     Powered by Flet (Flutter)                                ║
║     Made by @TheFirSStYfOreVer                               ║
║                                                              ║
║     Supported protocols: VLESS, VMESS, Trojan, Shadowsocks   ║
╚══════════════════════════════════════════════════════════════╝
    """
    )
    ft.run(main)
    sys.exit(0)

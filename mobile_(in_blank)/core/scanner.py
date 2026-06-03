"""
NetPrivacy Verification Tool — Mobile Core
==========================================
Platform-agnostic, mobile-optimised proxy scanner.

Key differences vs PC version (app/core/scanner.py):
  - NO GUI dependencies (no customtkinter, Pillow, pyperclip)
  - NO threading bridge — pure asyncio throughout
  - Worker-pool pattern: fixed N coroutines, not N tasks per link
  - ScanConfig dataclass — all tunables in one place
  - NodeResult dataclass — typed, serialisable result
  - Async-generator API: results streamed as they arrive (memory safe)
  - Cross-platform process kill (SIGTERM on Linux/Android, CTRL_BREAK on Windows)
  - tempfile.mkstemp for xray configs (no hardcoded paths)
  - _find_xray() checks multiple locations including Termux PATH
  - Reduced defaults: concurrency=10, timeouts shorter for mobile radios
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import signal
import socket
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, unquote, urlparse

import aiohttp
import aiohttp_socks


# ─────────────────────────────────────────────────────────────────────────────
# Mobile-tuned defaults
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CONCURRENCY = 10      # PC uses 50; mobile radios saturate quickly
XRAY_WARMUP         = 0.3     # seconds after xray starts (PC: 0.5)
BASE_TIMEOUT        = 8.0     # basic connectivity check (PC: 10)
RESOURCE_TIMEOUT    = 8.0     # per-domain resource check (PC: 15 total)
GEMINI_TIMEOUT      = 5.0     # Gemini probe (same as PC)
READ_LIMIT          = 4096    # max response bytes read


# ─────────────────────────────────────────────────────────────────────────────
# Configuration dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScanConfig:
    """
    All tuneable parameters.  Adjust for device capability.

    Examples::

        # Low-end Android phone (Termux):
        ScanConfig(concurrency=5, base_timeout=12)

        # Mid-range device with good signal:
        ScanConfig(concurrency=15)

        # Disable Gemini check for speed:
        ScanConfig(check_gemini=False)
    """
    concurrency: int = DEFAULT_CONCURRENCY
    xray_warmup: float = XRAY_WARMUP
    base_timeout: float = BASE_TIMEOUT
    resource_timeout: float = RESOURCE_TIMEOUT
    gemini_timeout: float = GEMINI_TIMEOUT
    check_gemini: bool = True
    resource_domains: List[str] = field(
        default_factory=lambda: [
            "youtube.com",
            "t.me",
            "discord.com",
            "instagram.com",
        ]
    )
    xray_bin: Optional[str] = None   # auto-detected when None
    temp_dir: Optional[str] = None   # system tmpdir when None


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class NodeResult:
    """Typed, serialisable result for a single proxy node."""
    link: str
    name: str
    protocol: str
    ping_ms: float
    host: str
    port: int
    accessible_count: int
    accessibility: str
    is_high_reliability: bool
    avg_resource_rtt: float
    total_resource_rtt: float
    resource_results: Dict[str, Tuple[bool, float]]
    gemini_ready: bool
    tags: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "link": self.link,
            "name": self.name,
            "type": self.protocol,
            "ping": self.ping_ms,
            "host": self.host,
            "port": self.port,
            "accessible_count": self.accessible_count,
            "accessibility": self.accessibility,
            "is_high_reliability": self.is_high_reliability,
            "avg_resource_rtt": self.avg_resource_rtt,
            "total_resource_rtt": self.total_resource_rtt,
            "resource_results": {
                k: {"ok": v[0], "rtt_ms": v[1]}
                for k, v in self.resource_results.items()
            },
            "gemini_ready": self.gemini_ready,
            "tags": self.tags,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_xray(hint: Optional[str] = None) -> str:
    """
    Locate xray binary.  Search order:
      1. Explicit hint path
      2. mobile/bin/  (sibling of this file's package)
      3. app/bin/     (PC version location, shared repo)
      4. System PATH  (Termux installs xray via pkg)
    """
    if hint and os.path.isfile(hint):
        return hint

    root = Path(__file__).resolve().parent.parent   # …/mobile/
    candidates: List[str] = []
    for name in ("xray", "xray.exe"):
        candidates.append(str(root / "bin" / name))
        candidates.append(str(root.parent / "app" / "bin" / name))

    for name in ("xray", "xray.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    for path in candidates:
        if os.path.isfile(path):
            return path

    raise FileNotFoundError(
        "xray binary not found.  "
        "Place it in mobile/bin/  or set ScanConfig.xray_bin."
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def _false() -> bool:
    return False


# ─────────────────────────────────────────────────────────────────────────────
# MobileScanner
# ─────────────────────────────────────────────────────────────────────────────

LogFn = Callable[[str], Any]


class MobileScanner:
    """
    Mobile-optimised async proxy scanner.

    Design goals
    ~~~~~~~~~~~~
    * No GUI, no threading bridge.
    * Fixed worker-pool so only ``concurrency`` coroutines are alive at once
      — memory-safe for lists of 500+ links.
    * One shared aiohttp session per node (resource + Gemini checks share it).
    * Cross-platform process management (Windows & POSIX / Android Termux).
    * Results streamed via async generator — caller decides what to do with them.

    Usage::

        cfg = ScanConfig(concurrency=10)
        scanner = MobileScanner(cfg, log_callback=print)

        async for node in scanner.scan(links):
            print(node.to_dict())
    """

    def __init__(
        self,
        config: Optional[ScanConfig] = None,
        log_callback: Optional[LogFn] = None,
    ) -> None:
        self.cfg = config or ScanConfig()
        self._log_fn = log_callback
        self._bin = _find_xray(self.cfg.xray_bin)
        self._tmpdir = self.cfg.temp_dir or tempfile.gettempdir()
        self._active_procs: List[asyncio.subprocess.Process] = []
        self._stop = asyncio.Event()

    # ── logging ───────────────────────────────────────────────────────────────

    async def _log(self, msg: str) -> None:
        if not self._log_fn:
            return
        try:
            result = self._log_fn(msg)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass

    # ── public API ────────────────────────────────────────────────────────────

    async def scan(self, links: List[str]) -> AsyncIterator[NodeResult]:
        """
        Async generator yielding NodeResult for each live node found.

        Uses a fixed-size worker pool so only ``concurrency`` coroutines
        run at once — safe for large lists without blowing memory.
        """
        self._stop.clear()

        if not links:
            return

        queue_in: asyncio.Queue[Optional[str]] = asyncio.Queue()
        queue_out: asyncio.Queue[Optional[NodeResult]] = asyncio.Queue()

        for link in links:
            await queue_in.put(link)

        n = min(self.cfg.concurrency, len(links))

        async def _worker() -> None:
            while True:
                link = await queue_in.get()
                if link is None:
                    break
                result = await self._check_one(link)
                await queue_out.put(result)

        worker_tasks = [asyncio.create_task(_worker()) for _ in range(n)]

        for _ in range(n):
            await queue_in.put(None)

        remaining = len(links)
        try:
            while remaining > 0:
                node = await queue_out.get()
                remaining -= 1
                if node is not None:
                    yield node
                await asyncio.sleep(0)
        finally:
            for t in worker_tasks:
                if not t.done():
                    t.cancel()

    def stop(self) -> None:
        """Signal all checks to abort and kill active xray processes."""
        self._stop.set()
        self.kill_all()

    def kill_all(self) -> int:
        """Kill all tracked xray processes.  Returns number killed."""
        killed = 0
        for proc in self._active_procs[:]:
            try:
                if proc.returncode is None:
                    proc.kill()
                    killed += 1
            except Exception:
                pass
        self._active_procs.clear()
        return killed

    # ── config builder ────────────────────────────────────────────────────────

    def build_config(self, link: str, port: int) -> Tuple[Optional[Dict], str]:
        """Parse a proxy URI into an xray JSON config dict + display name."""
        try:
            link = link.strip()
            if not link:
                return None, "empty link"
            parsed = urlparse(link)
            scheme = parsed.scheme.lower()
            if scheme in ("vless", "trojan"):
                return self._vless_trojan(parsed, scheme, port)
            if scheme == "vmess":
                return self._vmess(link, port)
            if scheme == "ss":
                return self._ss(parsed, port)
            return None, f"unsupported scheme: {scheme}"
        except Exception as exc:
            return None, f"parse error: {exc}"

    # ── stream settings builder ───────────────────────────────────────────────

    @staticmethod
    def _stream(qs: Dict[str, str], host: str) -> Dict[str, Any]:
        net = qs.get("type") or qs.get("network") or "tcp"
        sec = qs.get("security") or "none"
        s: Dict[str, Any] = {"network": net, "security": sec}

        if sec == "tls":
            sni = qs.get("sni") or qs.get("host") or host
            s["tlsSettings"] = {"serverName": sni, "allowInsecure": False}
            alpn_raw = qs.get("alpn") or ""
            if alpn_raw:
                s["tlsSettings"]["alpn"] = [a for a in alpn_raw.split(",") if a]
            fp = qs.get("fp") or ""
            if fp:
                s["tlsSettings"]["fingerprint"] = fp

        elif sec == "reality":
            sni = qs.get("sni") or qs.get("host") or host
            s["realitySettings"] = {
                "serverName": sni,
                "fingerprint": qs.get("fp") or "chrome",
                "publicKey": qs.get("pbk") or "",
                "shortId": qs.get("sid") or "",
                "spiderX": qs.get("spx") or "/",
            }

        if net == "ws":
            path = unquote(qs.get("path") or "/")
            ws_host = qs.get("host") or qs.get("sni") or host
            s["wsSettings"] = {"path": path, "headers": {"Host": ws_host}}

        elif net == "grpc":
            s["grpcSettings"] = {"serviceName": qs.get("serviceName") or ""}

        elif net == "h2":
            h2_host = qs.get("host") or host
            s["httpSettings"] = {
                "path": qs.get("path") or "/",
                "host": [h2_host],
            }

        return s

    # ── protocol builders ─────────────────────────────────────────────────────

    def _vless_trojan(
        self, p: Any, scheme: str, port: int
    ) -> Tuple[Optional[Dict], str]:
        qs = dict(parse_qsl(p.query))
        host = p.hostname or ""
        h_port = _int(p.port, 443)
        name = unquote(p.fragment) if p.fragment else f"{host}:{h_port}"
        stream = self._stream(qs, host)

        if scheme == "vless":
            user: Dict[str, Any] = {
                "id": p.username or "",
                "encryption": qs.get("encryption") or "none",
            }
            flow = qs.get("flow") or ""
            if flow:
                user["flow"] = flow
            outbound = {
                "protocol": "vless",
                "settings": {
                    "vnext": [{"address": host, "port": h_port, "users": [user]}]
                },
                "streamSettings": stream,
            }
        else:
            outbound = {
                "protocol": "trojan",
                "settings": {
                    "servers": [
                        {
                            "address": host,
                            "port": h_port,
                            "password": p.username or "",
                        }
                    ]
                },
                "streamSettings": stream,
            }

        return self._wrap(outbound, port), name

    def _vmess(self, link: str, port: int) -> Tuple[Optional[Dict], str]:
        raw = link[len("vmess://"):]
        if "#" in raw:
            raw = raw[: raw.index("#")]
        try:
            padding = (4 - len(raw) % 4) % 4
            vm = json.loads(base64.b64decode(raw + "=" * padding).decode())
        except Exception:
            return None, "vmess: decode error"

        host = vm.get("add", "")
        h_port = _int(vm.get("port", 443), 443)
        name = vm.get("ps") or f"{host}:{h_port}"
        net = vm.get("net", "tcp")
        tls_val = str(vm.get("tls", "")).lower()
        security = "tls" if tls_val in ("tls", "true", "1") else "none"

        stream: Dict[str, Any] = {"network": net, "security": security}

        if security == "tls":
            sni = vm.get("sni") or vm.get("host") or host
            stream["tlsSettings"] = {"serverName": sni, "allowInsecure": True}

        if net == "ws":
            ws_host = vm.get("host") or host
            stream["wsSettings"] = {
                "path": vm.get("path") or "/",
                "headers": {"Host": ws_host},
            }
        elif net == "h2":
            stream["httpSettings"] = {"path": vm.get("path") or "/"}

        outbound = {
            "protocol": "vmess",
            "settings": {
                "vnext": [
                    {
                        "address": host,
                        "port": h_port,
                        "users": [
                            {
                                "id": vm.get("id") or "",
                                "alterId": _int(vm.get("aid", 0)),
                                "security": vm.get("scy") or "auto",
                            }
                        ],
                    }
                ]
            },
            "streamSettings": stream,
        }
        return self._wrap(outbound, port), name

    def _ss(self, p: Any, port: int) -> Tuple[Optional[Dict], str]:
        name = unquote(p.fragment) if p.fragment else ""

        netloc = p.netloc
        if "@" not in netloc:
            return None, "ss: missing auth@host"

        auth, addr = netloc.split("@", 1)

        if addr.startswith("["):
            if "]:" in addr:
                host_part, h_port_s = addr.rsplit(":", 1)
                host = host_part[1:-1]
            else:
                host = addr[1:-1]
                h_port_s = "8388"
        elif ":" in addr:
            host, h_port_s = addr.rsplit(":", 1)
        else:
            host, h_port_s = addr, "8388"

        h_port = _int(h_port_s, 8388)
        if not name:
            name = f"{host}:{h_port}"

        method, password = "aes-256-gcm", ""
        try:
            padding = (4 - len(auth) % 4) % 4
            decoded = base64.b64decode(auth + "=" * padding).decode("utf-8")
            method, _, password = decoded.partition(":")
        except Exception:
            if ":" in auth:
                method, _, password = auth.partition(":")
            else:
                method, password = "aes-256-gcm", auth

        outbound = {
            "protocol": "shadowsocks",
            "settings": {
                "servers": [
                    {
                        "address": host,
                        "port": h_port,
                        "method": method,
                        "password": password,
                    }
                ]
            },
        }
        return self._wrap(outbound, port), name

    @staticmethod
    def _wrap(outbound: Dict, port: int) -> Dict:
        return {
            "log": {"loglevel": "error"},
            "inbounds": [
                {"port": port, "protocol": "socks", "settings": {"udp": False}}
            ],
            "outbounds": [outbound, {"protocol": "freedom", "tag": "direct"}],
        }

    # ── connectivity checks ───────────────────────────────────────────────────

    async def _basic_check(self, port: int) -> bool:
        connector = aiohttp_socks.ProxyConnector.from_url(
            f"socks5://127.0.0.1:{port}"
        )
        timeout = aiohttp.ClientTimeout(total=self.cfg.base_timeout)
        try:
            async with aiohttp.ClientSession(
                connector=connector, timeout=timeout
            ) as sess:
                async with sess.head(
                    "http://cp.cloudflare.com/generate_204",
                    allow_redirects=False,
                ) as r:
                    return r.status in (200, 204)
        except Exception:
            return False
        finally:
            connector.close()

    async def _check_domain(
        self, domain: str, session: aiohttp.ClientSession
    ) -> Tuple[str, bool, float]:
        timeout = aiohttp.ClientTimeout(total=self.cfg.resource_timeout)
        t0 = time.monotonic()
        try:
            async with session.head(
                f"https://{domain}",
                allow_redirects=False,
                ssl=False,
                timeout=timeout,
            ) as r:
                ok = r.status in (200, 204, 301, 302, 307, 308, 403, 404)
                elapsed = (time.monotonic() - t0) * 1000
                return domain, ok, elapsed if ok else 0.0
        except Exception:
            return domain, False, 0.0

    async def _check_resources(
        self, port: int, session: aiohttp.ClientSession
    ) -> Dict[str, Any]:
        tasks = [
            asyncio.create_task(self._check_domain(d, session))
            for d in self.cfg.resource_domains
        ]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        results: Dict[str, Tuple[bool, float]] = {}
        ok_count = 0
        total_rtt = 0.0

        for item in completed:
            if isinstance(item, Exception):
                continue
            domain, ok, rtt = item
            results[domain] = (ok, rtt)
            if ok:
                ok_count += 1
                total_rtt += rtt

        n = len(self.cfg.resource_domains)
        avg = total_rtt / ok_count if ok_count else 0.0
        return {
            "results": results,
            "accessible_count": ok_count,
            "total_rtt": round(total_rtt, 1),
            "avg_rtt": round(avg, 1),
            "is_high_reliability": ok_count == n,
            "accessibility": f"{ok_count}/{n}",
        }

    async def _check_gemini(
        self, port: int, session: aiohttp.ClientSession
    ) -> bool:
        _ALLOWED_SUFFIXES = (
            "google.com",
            "googleapis.com",
            "google.dev",
            "gstatic.com",
            "googleusercontent.com",
        )
        _POISON = (
            "captcha",
            "recaptcha",
            "unusual traffic",
            "/sorry/",
            "provider",
            "blocked",
            "failed_precondition",
        )
        urls = [
            "https://generativelanguage.googleapis.com/$discovery/rest?version=v1beta",
            "https://generativelanguage.googleapis.com/v1beta/models",
            "https://gemini.google.com/",
        ]
        timeout = aiohttp.ClientTimeout(total=self.cfg.gemini_timeout)

        for url in urls:
            try:
                async with session.get(
                    url, allow_redirects=False, ssl=False, timeout=timeout
                ) as r:
                    if 300 <= r.status < 400:
                        loc = r.headers.get("Location") or ""
                        loc_low = loc.lower()
                        redirect_host = urlparse(loc).netloc.lower()
                        if redirect_host and not redirect_host.endswith(_ALLOWED_SUFFIXES):
                            return False
                        if any(p in loc_low for p in ("captcha", "recaptcha", "/sorry/")):
                            return False
                        continue

                    if r.status not in (200, 403):
                        continue

                    body = (
                        await r.content.read(READ_LIMIT)
                    ).decode(errors="ignore").lower()

                    if "failed_precondition" in body:
                        continue

                    if r.status == 403 and not any(
                        k in body
                        for k in (
                            "api key",
                            "api_key",
                            "permission_denied",
                            "unauthenticated",
                        )
                    ):
                        continue

                    if r.status == 200 and "$discovery/rest" in url:
                        if (
                            "discovery#restdescription" not in body
                            and "gemini api" not in body
                        ):
                            continue

                    if any(p in body for p in _POISON):
                        continue

                    return True

            except Exception:
                continue

        return False

    # ── xray process management (cross-platform) ──────────────────────────────

    @asynccontextmanager
    async def _xray(self, cfg_path: str, port: int):
        proc = None
        try:
            kwargs: Dict[str, Any] = {
                "stdout": asyncio.subprocess.DEVNULL,
                "stderr": asyncio.subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                import subprocess as _sp
                kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP

            proc = await asyncio.create_subprocess_exec(
                self._bin, "-c", cfg_path, **kwargs
            )
            self._active_procs.append(proc)
            yield proc
        finally:
            if proc is not None:
                if proc in self._active_procs:
                    self._active_procs.remove(proc)
                await self._kill_proc(proc)

    async def _kill_proc(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        try:
            if sys.platform == "win32":
                try:
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                except Exception:
                    proc.kill()
            else:
                proc.terminate()

            try:
                await asyncio.wait_for(proc.wait(), timeout=1.5)
                return
            except asyncio.TimeoutError:
                pass

            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                await self._log(f"[KILL] PID {proc.pid} unresponsive")
        except ProcessLookupError:
            pass
        except Exception as exc:
            await self._log(f"[KILL] {exc}")

    # ── host/port extraction from config ─────────────────────────────────────

    @staticmethod
    def _addr_from_config(config: Dict) -> Tuple[str, int]:
        try:
            ob = config["outbounds"][0]
            proto = ob.get("protocol", "")
            s = ob.get("settings", {})
            if proto in ("vless", "vmess"):
                v = s.get("vnext", [{}])[0]
                return v.get("address", ""), _int(v.get("port", 0))
            srv = s.get("servers", [{}])[0]
            return srv.get("address", ""), _int(srv.get("port", 0))
        except Exception:
            return "", 0

    # ── single node check ─────────────────────────────────────────────────────

    async def _check_one(self, link: str) -> Optional[NodeResult]:
        if self._stop.is_set():
            return None

        port = _free_port()
        config, name = self.build_config(link, port)

        if config is None:
            await self._log(f"[SKIP] {name} | {link[:50]}")
            return None

        proto = config["outbounds"][0].get("protocol", "unknown")

        fd, cfg_path = tempfile.mkstemp(
            suffix=".json", prefix=f"xray_{port}_", dir=self._tmpdir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(config, fh)

            async with self._xray(cfg_path, port):
                await asyncio.sleep(self.cfg.xray_warmup)

                if self._stop.is_set():
                    return None

                t0 = time.monotonic()
                alive = await self._basic_check(port)
                ping = (time.monotonic() - t0) * 1000

                if not alive:
                    await self._log(f"[DEAD] {name[:35]}")
                    return None

                await self._log(f"[LIVE] {name[:35]} | {ping:.0f}ms")

                sess_timeout = aiohttp.ClientTimeout(
                    total=max(self.cfg.resource_timeout, self.cfg.gemini_timeout) + 3
                )
                connector = aiohttp_socks.ProxyConnector.from_url(
                    f"socks5://127.0.0.1:{port}"
                )
                try:
                    async with aiohttp.ClientSession(
                        connector=connector, timeout=sess_timeout
                    ) as session:
                        res_coro = self._check_resources(port, session)
                        gem_coro = (
                            self._check_gemini(port, session)
                            if self.cfg.check_gemini
                            else _false()
                        )
                        res, gemini_ok = await asyncio.gather(
                            asyncio.create_task(res_coro),
                            asyncio.create_task(gem_coro),
                        )
                finally:
                    connector.close()

                host, h_port = self._addr_from_config(config)
                tags = ["Gemini_Ready"] if gemini_ok else []

                await self._log(
                    f"[DONE] {name[:35]} | {res['accessibility']} | "
                    f"Avg:{res['avg_rtt']:.0f}ms"
                    + (" | Gemini_Ready" if gemini_ok else "")
                )

                return NodeResult(
                    link=link,
                    name=name,
                    protocol=proto.upper(),
                    ping_ms=round(ping, 1),
                    host=host,
                    port=h_port,
                    accessible_count=res["accessible_count"],
                    accessibility=res["accessibility"],
                    is_high_reliability=res["is_high_reliability"],
                    avg_resource_rtt=res["avg_rtt"],
                    total_resource_rtt=res["total_rtt"],
                    resource_results=res["results"],
                    gemini_ready=gemini_ok,
                    tags=tags,
                )

        except asyncio.CancelledError:
            await self._log(f"[CANCELLED] {name[:35]}")
            return None
        except Exception as exc:
            await self._log(f"[ERROR] {name[:35]} | {exc}")
            return None
        finally:
            try:
                os.unlink(cfg_path)
            except OSError:
                pass

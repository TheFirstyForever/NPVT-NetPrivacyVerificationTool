# Made by @TheFirSStYfOreVer
import asyncio
import base64
import ctypes
import json
import os
import platform
import random
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from ctypes import wintypes
from typing import Callable, Optional
from urllib.parse import parse_qsl, unquote, urlparse

import aiohttp
import aiohttp_socks


class LogicVerifier:
    def __init__(self, tui=None, log_callback: Optional[Callable[[str], None]] = None):
        self.tui = tui  # Legacy: ссылка на TUI/GUI для логирования и обновлений
        self._log_callback = log_callback  # Новый callback для логов

        def _emit(msg: str) -> None:
            try:
                if self._log_callback:
                    self._log_callback(msg)
            except Exception:
                pass

        roots = []
        try:
            roots.append(os.getcwd())
        except Exception:
            pass
        try:
            roots.append(os.path.dirname(sys.executable))
        except Exception:
            pass
        try:
            base = getattr(sys, "_MEIPASS", None)
            if base and os.path.isdir(base):
                roots.append(os.path.abspath(base))
        except Exception:
            pass
        try:
            roots.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)))
        except Exception:
            pass
        try:
            roots.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
        except Exception:
            pass

        seen = set()
        roots = [r for r in roots if r and (not (r in seen or seen.add(r)))]

        candidates = []
        for r in roots:
            candidates.append(os.path.join(r, "core", "nv_backend_core.exe"))
            candidates.append(os.path.join(r, "core", "npvt_core.exe"))
            candidates.append(os.path.join(r, "core", "xray.exe"))
            candidates.append(os.path.join(r, "core", "bin", "nv_backend_core.exe"))
            candidates.append(os.path.join(r, "core", "bin", "npvt_core.exe"))
            candidates.append(os.path.join(r, "app", "bin", "npvt_core.exe"))
            candidates.append(os.path.join(r, "core", "bin", "xray.exe"))
            candidates.append(os.path.join(r, "app", "bin", "xray.exe"))

        self.bin_path = ""
        for p in candidates:
            try:
                if os.path.isfile(p) and p.lower().endswith("npvt_core.exe"):
                    self.bin_path = p
                    break
            except Exception:
                continue

        if not self.bin_path:
            for p in candidates:
                try:
                    if os.path.isfile(p) and p.lower().endswith("nv_backend_core.exe"):
                        self.bin_path = p
                        break
                except Exception:
                    continue

        if not self.bin_path:
            for p in candidates:
                try:
                    if os.path.isfile(p) and p.lower().endswith("xray.exe"):
                        self.bin_path = p
                        break
                except Exception:
                    continue

        if not self.bin_path:
            _emit("[ERROR] Engine binary not found (nv_backend_core.exe/npvt_core.exe/xray.exe). Check installation folder.")
        self.process_timeout = 15
        self._current_config = None  # Текущий конфиг для отображения
        self._active_processes: list = []  # Список активных процессов для принудительной остановки
        self.deep_checks = True

        self._engine_path = self.bin_path
        self._job_handle = None
        if sys.platform == "win32":
            try:
                class IO_COUNTERS(ctypes.Structure):
                    _fields_ = [
                        ("ReadOperationCount", ctypes.c_uint64),
                        ("WriteOperationCount", ctypes.c_uint64),
                        ("OtherOperationCount", ctypes.c_uint64),
                        ("ReadTransferCount", ctypes.c_uint64),
                        ("WriteTransferCount", ctypes.c_uint64),
                        ("OtherTransferCount", ctypes.c_uint64),
                    ]

                class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                    _fields_ = [
                        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD),
                    ]

                class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                    _fields_ = [
                        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                        ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t),
                    ]

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                hjob = kernel32.CreateJobObjectW(None, None)
                if hjob:
                    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
                    info.BasicLimitInformation.LimitFlags = 0x00002000
                    ok = kernel32.SetInformationJobObject(
                        hjob,
                        9,
                        ctypes.byref(info),
                        ctypes.sizeof(info),
                    )
                    if ok:
                        self._job_handle = hjob
            except Exception:
                self._job_handle = None
        self._cfg_dir = os.path.join(tempfile.gettempdir(), "npvt_configs")
        try:
            os.makedirs(self._cfg_dir, exist_ok=True)
        except Exception:
            pass

        self._port_lock = threading.Lock()
        self._ports_in_use = set()
        self._port_min = 20000
        self._port_max = 65000
        self._port_cursor = random.randint(self._port_min, self._port_max)

    def get_free_port(self):
        rng = (self._port_max - self._port_min) + 1
        with self._port_lock:
            for _ in range(rng):
                port = self._port_cursor
                self._port_cursor += 1
                if self._port_cursor > self._port_max:
                    self._port_cursor = self._port_min
                if port in self._ports_in_use:
                    continue
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                        s.bind(("127.0.0.1", port))
                except OSError:
                    continue
                self._ports_in_use.add(port)
                return port

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]
        with self._port_lock:
            self._ports_in_use.add(port)
        return port

    def _release_port(self, port: int) -> None:
        try:
            if not port:
                return
            with self._port_lock:
                self._ports_in_use.discard(int(port))
        except Exception:
            pass

    def _assign_pid_to_job(self, pid: int) -> None:
        if sys.platform != "win32" or not self._job_handle or not pid:
            return
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            PROCESS_TERMINATE = 0x0001
            PROCESS_SET_QUOTA = 0x0100
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            hproc = kernel32.OpenProcess(
                PROCESS_TERMINATE | PROCESS_SET_QUOTA | PROCESS_QUERY_LIMITED_INFORMATION,
                False,
                int(pid),
            )
            if not hproc:
                return
            try:
                kernel32.AssignProcessToJobObject(self._job_handle, hproc)
            finally:
                kernel32.CloseHandle(hproc)
        except Exception:
            return

    def _taskkill_tree(self, pid: int) -> bool:
        if sys.platform != "win32" or not pid:
            return False
        try:
            cf = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=cf,
                timeout=2,
            )
            return True
        except Exception:
            return False

    async def _wait_local_tcp_open(self, port: int, timeout_s: float = 1.2) -> bool:
        if not port:
            return False

        deadline = time.monotonic() + float(timeout_s)
        while time.monotonic() < deadline:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", int(port)),
                    timeout=0.25,
                )
                try:
                    writer.close()
                    if hasattr(writer, "wait_closed"):
                        await writer.wait_closed()
                except Exception:
                    pass
                return True
            except Exception:
                await asyncio.sleep(0.05)
        return False

    def _decode_vmess(self, raw_data):
        """Decode VMess base64 with proper padding calculation."""
        # Fix: Calculate exact padding needed instead of adding '==='
        padding_needed = (4 - len(raw_data) % 4) % 4
        padded = raw_data + ("=" * padding_needed)
        return base64.b64decode(padded).decode("utf-8")

    def _safe_parse_int(self, value, default=0):
        """Safely parse integer values that might be strings."""
        try:
            return int(value) if value is not None else default
        except (ValueError, TypeError):
            return default

    def _write_config_file(self, config_path: str, config: dict) -> None:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    async def _log(self, message: str):
        """Логирование через callback, TUI или stdout."""
        if self._log_callback:
            try:
                self._log_callback(message)
            except Exception:
                pass
        elif self.tui:
            try:
                await self.tui.log(message)
            except Exception:
                pass
    
    def _extract_host_port(self, config: dict) -> tuple:
        """Извлекает хост и порт из конфига для отображения."""
        try:
            outbound = config.get("outbounds", [{}])[0]
            protocol = outbound.get("protocol", "")
            
            if protocol in ["vless", "trojan", "vmess"]:
                vnext = outbound.get("settings", {}).get("vnext", [{}])[0]
                return vnext.get("address", ""), vnext.get("port", 0)
            elif protocol in ("ss", "shadowsocks"):
                servers = outbound.get("settings", {}).get("servers", [{}])[0]
                return servers.get("address", ""), servers.get("port", 0)
        except:
            pass
        return "", 0

    def build_config(self, link, port):
        """Parse proxy link and generate Xray config."""
        try:
            # Handle leading/trailing whitespace
            link = link.strip()
            if not link:
                return None, "Empty link"

            parsed = urlparse(link)
            ptype = parsed.scheme.lower()

            # Validate protocol type
            if ptype not in ["vless", "vmess", "trojan", "ss"]:
                return None, f"Invalid protocol: '{ptype}'"

            # Extract name from fragment (URL decoded)
            name = unquote(parsed.fragment) if parsed.fragment else "Unknown Node"

            qs = dict(parse_qsl(parsed.query))
            # Xray uses "shadowsocks" as protocol name; "ss" is only the URL scheme
            xray_protocol = "shadowsocks" if ptype == "ss" else ptype
            outbound = {"protocol": xray_protocol, "settings": {}, "streamSettings": {}}

            # === VLESS / Trojan Parsing ===
            if ptype in ["vless", "trojan"]:
                if "@" not in parsed.netloc:
                    return None, "Missing auth@host in URL"

                auth, addr = parsed.netloc.split("@", 1)

                # Handle IPv6 addresses and ports
                if addr.startswith("["):
                    # IPv6 format: [::1]:443 or [::1]
                    if "]:" in addr:
                        host, h_port = addr.rsplit(":", 1)
                        host = host[1:-1]  # Remove brackets
                        h_port = h_port
                    else:
                        host = addr[1:-1]
                        h_port = "443"
                elif ":" in addr:
                    host, h_port = addr.rsplit(":", 1)
                else:
                    host = addr
                    h_port = "443"

                user_key = "id" if ptype == "vless" else "password"
                outbound["settings"] = {
                    "vnext": [
                        {
                            "address": host,
                            "port": self._safe_parse_int(h_port, 443),
                            "users": [{user_key: auth}],
                        }
                    ]
                }

                if ptype == "vless":
                    outbound["settings"]["vnext"][0]["users"][0]["encryption"] = qs.get(
                        "encryption", "none"
                    )
                    # Add flow if present (for XTLS)
                    if "flow" in qs:
                        outbound["settings"]["vnext"][0]["users"][0]["flow"] = qs["flow"]

                # Network settings
                net_type = qs.get("type", "tcp")
                security = qs.get("security", "none")
                outbound["streamSettings"] = {"network": net_type, "security": security}

                # WebSocket settings with proper path/host/SNI handling
                if net_type == "ws":
                    path = unquote(qs.get("path", "/"))
                    # Host priority: host param > sni param > server address
                    ws_host = qs.get("host") or qs.get("sni") or host
                    outbound["streamSettings"]["wsSettings"] = {
                        "path": path,
                        "headers": {"Host": ws_host},
                    }

                # gRPC settings
                if net_type == "grpc":
                    service_name = qs.get("serviceName", "")
                    outbound["streamSettings"]["grpcSettings"] = {
                        "serviceName": service_name,
                    }

                # Reality settings with full parameter support
                if security == "reality":
                    reality_host = qs.get("sni") or qs.get("host") or host
                    outbound["streamSettings"]["realitySettings"] = {
                        "serverName": reality_host,
                        "fingerprint": qs.get("fp", "chrome"),
                        "publicKey": qs.get("pbk", ""),
                        "shortId": qs.get("sid", ""),
                        "spiderX": qs.get("spx", "/"),
                    }
                    # XTLS Reality flow
                    if "flow" in qs:
                        outbound["settings"]["vnext"][0]["users"][0]["flow"] = qs["flow"]

                elif security == "tls":
                    tls_host = qs.get("sni") or qs.get("host") or host
                    outbound["streamSettings"]["tlsSettings"] = {
                        "serverName": tls_host,
                        "allowInsecure": False,
                    }
                    # ALPN settings if provided
                    if "alpn" in qs:
                        alpn_list = qs["alpn"].split(",")
                        outbound["streamSettings"]["tlsSettings"]["alpn"] = alpn_list

            # === VMess Parsing ===
            elif ptype == "vmess":
                raw_data = link.replace("vmess://", "")
                if not raw_data:
                    return None, "Empty VMess payload"

                try:
                    decoded = self._decode_vmess(raw_data)
                    data = json.loads(decoded)
                except Exception as e:
                    return None, f"VMess decode error: {e}"

                name = data.get("ps", name)
                vmess_host = data.get("add", "")
                vmess_port = self._safe_parse_int(data.get("port"), 443)

                outbound["settings"] = {
                    "vnext": [
                        {
                            "address": vmess_host,
                            "port": vmess_port,
                            "users": [
                                {
                                    "id": data.get("id", ""),
                                    "alterId": self._safe_parse_int(data.get("aid", 0)),
                                    "security": data.get("scy", "auto"),
                                }
                            ],
                        }
                    ]
                }

                net = data.get("net", "tcp")
                security = "tls" if data.get("tls") in ["tls", "true", "1"] else "none"
                outbound["streamSettings"] = {
                    "network": net,
                    "security": security,
                }

                # VMess WebSocket settings
                if net == "ws":
                    ws_host = data.get("host") or vmess_host
                    outbound["streamSettings"]["wsSettings"] = {
                        "path": data.get("path", "/"),
                        "headers": {"Host": ws_host},
                    }

                # VMess TLS settings
                if security == "tls":
                    sni = data.get("sni") or data.get("host") or vmess_host
                    outbound["streamSettings"]["tlsSettings"] = {
                        "serverName": sni,
                    }

            # === Shadowsocks (SS) Parsing ===
            elif ptype == "ss":
                # Three possible formats:
                # (A) SIP002 plain:   ss://method:password@host:port[#name]
                # (B) SIP002 b64auth: ss://BASE64(method:password)@host:port[#name]
                # (C) Legacy full:    ss://BASE64(method:password@host:port)[#name]
                if "@" in parsed.netloc:
                    # Formats A and B: split on last @
                    auth, addr = parsed.netloc.split("@", 1)

                    # addr → host + port
                    if addr.startswith("["):
                        if "]:" in addr:
                            host, h_port = addr.rsplit(":", 1)
                            host = host[1:-1]
                        else:
                            host = addr[1:-1]
                            h_port = "8388"
                    elif ":" in addr:
                        host, h_port = addr.rsplit(":", 1)
                    else:
                        host = addr
                        h_port = "8388"

                    # auth → method + password (base64 or plain)
                    method, password = "aes-256-gcm", auth
                    try:
                        padding = (4 - len(auth) % 4) % 4
                        decoded_auth = base64.b64decode(auth + "=" * padding).decode("utf-8")
                        if ":" in decoded_auth:
                            method, password = decoded_auth.split(":", 1)
                    except Exception:
                        if ":" in auth:
                            method, password = auth.split(":", 1)

                else:
                    # Format C: legacy — the entire payload after ss:// is base64
                    # reassemble in case urlparse split on a "/" inside base64
                    raw = parsed.netloc
                    if parsed.path and parsed.path not in ("/", ""):
                        raw += parsed.path
                    raw = raw.rstrip("=")  # strip existing padding before re-adding
                    try:
                        padding = (4 - len(raw) % 4) % 4
                        full_decoded = base64.b64decode(raw + "=" * padding).decode("utf-8")
                    except Exception as e:
                        return None, f"SS base64 decode error: {e}"

                    if "@" not in full_decoded:
                        return None, "Invalid SS URL: no auth@host after decoding"

                    auth_part, addr = full_decoded.split("@", 1)
                    if ":" not in auth_part:
                        return None, "Invalid SS URL: missing method:password"

                    method, password = auth_part.split(":", 1)

                    if addr.startswith("["):
                        if "]:" in addr:
                            host, h_port = addr.rsplit(":", 1)
                            host = host[1:-1]
                        else:
                            host = addr[1:-1]
                            h_port = "8388"
                    elif ":" in addr:
                        host, h_port = addr.rsplit(":", 1)
                    else:
                        host = addr
                        h_port = "8388"

                outbound["settings"] = {
                    "servers": [
                        {
                            "address": host,
                            "port": self._safe_parse_int(h_port, 8388),
                            "method": method,
                            "password": password,
                        }
                    ]
                }

            return {
                "log": {"loglevel": "error"},
                "inbounds": [
                    {"listen": "127.0.0.1", "port": port, "protocol": "socks", "settings": {"udp": True}}
                ],
                "outbounds": [outbound, {"protocol": "freedom", "tag": "direct"}],
            }, name

        except Exception as e:
            return None, f"Parse error: {str(e)}"

    async def _check_single_resource(self, domain: str, port: int, session) -> tuple:
        """
        Проверяет доступность одного endpoint через SOCKS5 прокси.
        
        Args:
            domain: Домен для проверки (например, "youtube.com")
            port: Порт локального SOCKS5 прокси
            session: aiohttp сессия с SOCKS коннектором
            
        Returns:
            tuple: (domain, success: bool, rtt_ms: float)
        """
        url = f"https://{domain}"
        start_time = time.time()
        
        try:
            req_timeout = aiohttp.ClientTimeout(total=6)
            # HEAD запрос без следования редиректам (быстрее)
            async with session.head(url, allow_redirects=False, ssl=False, timeout=req_timeout) as resp:
                elapsed = (time.time() - start_time) * 1000
                
                # Считаем успешными 200, 301, 302, 403 (доступ есть, даже если блок)
                success = resp.status in [200, 204, 301, 302, 307, 308, 403, 404, 405]
                
                return domain, success, elapsed if success else 0
                
        except Exception as e:
            return domain, False, 0

    async def _check_resources_with_session(self, port: int, session: aiohttp.ClientSession) -> dict:
        domains = ["youtube.com", "t.me", "discord.com", "instagram.com"]

        results = {}
        accessible_count = 0
        total_rtt = 0

        tasks = [
            self._check_single_resource(domain, port, session)
            for domain in domains
        ]

        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for result in completed:
            if isinstance(result, Exception):
                continue

            domain, success, rtt = result
            results[domain] = (success, rtt)

            if success:
                accessible_count += 1
                total_rtt += rtt

        avg_rtt = total_rtt / accessible_count if accessible_count > 0 else 0

        return {
            "results": results,
            "accessible_count": accessible_count,
            "total_rtt": round(total_rtt, 1),
            "avg_rtt": round(avg_rtt, 1),
            "is_high_reliability": accessible_count == 4,
            "accessibility": f"{accessible_count}/4"
        }

    async def check_resources(self, port: int, session: Optional[aiohttp.ClientSession] = None) -> dict:
        """
        Проверяет доступность 4 endpoint через прокси.
        
        Использует параллельную проверку (asyncio.gather) для скорости:
        все 4 домена проверяются одновременно, а не последовательно.
        
        Args:
            port: Порт локального SOCKS5 прокси
            
        Returns:
            dict: {
                "results": {"youtube.com": (True, 120ms), ...},
                "accessible_count": 4,  # 0-4
                "total_rtt": 450ms,    # сумма всех успешных RTT
                "avg_rtt": 112.5ms,    # среднее успешных
                "is_high_reliability": True  # 4/4
            }
        """
        if session is not None:
            try:
                return await self._check_resources_with_session(port, session)
            except Exception as e:
                await self._log(f"[ERROR] Resource check failed: {e}")
                return {
                    "results": {},
                    "accessible_count": 0,
                    "total_rtt": 0,
                    "avg_rtt": 0,
                    "is_high_reliability": False,
                    "accessibility": "0/4"
                }

        connector = aiohttp_socks.ProxyConnector.from_url(
            f"socks5://127.0.0.1:{port}"
        )
        timeout = aiohttp.ClientTimeout(total=15)

        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as owned_session:
                return await self._check_resources_with_session(port, owned_session)
        except Exception as e:
            await self._log(f"[ERROR] Resource check failed: {e}")
            return {
                "results": {},
                "accessible_count": 0,
                "total_rtt": 0,
                "avg_rtt": 0,
                "is_high_reliability": False,
                "accessibility": "0/4"
            }
        finally:
            connector.close()

    async def _kill_process_failsafe(self, proc, port: int = 0, timeout=5):
        """Foolproof process termination - guarantees process death."""
        if proc is None or proc.returncode is not None:
            return

        pid = proc.pid
        try:
            # Stage 1: Graceful termination
            if sys.platform == "win32":
                try:
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                except OSError as e:
                    if getattr(e, "winerror", None) not in (6,):
                        await self._log(f"[KILL] Ошибка при сигнале PID {pid}: {e}")
            else:
                try:
                    proc.terminate()
                except OSError as e:
                    if getattr(e, "winerror", None) not in (6,):
                        await self._log(f"[KILL] Ошибка при terminate PID {pid}: {e}")

            # Wait with timeout
            try:
                await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=0.5)
                await self._log(f"[KILL] PID {pid} завершен gracefully")
                return
            except asyncio.TimeoutError:
                await self._log(f"[KILL] PID {pid} не отвечает, принудительное убийство...")
                pass

            # Stage 2: Force kill
            try:
                proc.kill()
            except ProcessLookupError:
                return
            except OSError as e:
                if getattr(e, "winerror", None) in (6,):
                    return
                raise
            try:
                await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=1.0)
                await self._log(f"[KILL] PID {pid} убит forcefully")
            except asyncio.TimeoutError:
                ok = self._taskkill_tree(pid)
                if ok:
                    await self._log(f"[KILL] PID {pid} убит taskkill")
                else:
                    await self._log(f"[KILL] ⚠ PID {pid} не удается убить!")
                pass

        except ProcessLookupError:
            return
        except OSError as e:
            if getattr(e, "winerror", None) in (6,):
                return
            await self._log(f"[KILL] Ошибка при убийстве PID {pid}: {e}")
        except Exception as e:
            await self._log(f"[KILL] Ошибка при убийстве PID {pid}: {e}")

    def _cleanup_temp_artifacts(self, max_age_seconds: int = 24 * 60 * 60) -> None:
        try:
            now = time.time()
            temp_dir = tempfile.gettempdir()

            cfg_dir = os.path.join(temp_dir, "npvt_configs")
            if os.path.isdir(cfg_dir):
                for fn in os.listdir(cfg_dir):
                    if not (fn.startswith("temp_") and fn.endswith(".json")):
                        continue
                    p = os.path.join(cfg_dir, fn)
                    try:
                        if now - os.path.getmtime(p) > max_age_seconds:
                            os.remove(p)
                    except Exception:
                        pass

            for fn in os.listdir(temp_dir):
                if not (fn.startswith("npvt_run_") and fn.lower().endswith(".exe")):
                    continue
                p = os.path.join(temp_dir, fn)
                try:
                    if now - os.path.getmtime(p) > max_age_seconds:
                        os.remove(p)
                except Exception:
                    pass
        except Exception:
            pass

    def cleanup_temp_now(self) -> None:
        self._cleanup_temp_artifacts(max_age_seconds=0)

    def kill_shadow_processes(self, prefix: str = "npvt_run_") -> int:
        if sys.platform != "win32":
            return 0

        try:
            ps = (
                f"$p=Get-CimInstance Win32_Process | Where-Object {{$_.Name -like '{prefix}*.exe'}};"
                "$ids=@($p | Select-Object -ExpandProperty ProcessId);"
                "foreach($id in $ids){try{Stop-Process -Id $id -Force -ErrorAction SilentlyContinue}catch{}};"
                "$ids.Count"
            )
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", ps],
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,
                timeout=2,
            ).decode(errors="ignore").strip()
            return int(out) if out else 0
        except subprocess.TimeoutExpired:
            return 0
        except Exception:
            return 0

    def kill_all_processes(self) -> int:
        """Принудительно убивает все активные процессы xray."""
        import subprocess as sp
        killed = 0
        for proc in self._active_processes[:]:
            try:
                if proc and proc.returncode is None:
                    pid = proc.pid
                    try:
                        if sys.platform == "win32":
                            if self._taskkill_tree(pid):
                                killed += 1
                            else:
                                proc.kill()
                                killed += 1
                        else:
                            proc.kill()
                            killed += 1
                    except ProcessLookupError:
                        pass
                    except OSError as e:
                        if getattr(e, "winerror", None) not in (6,):
                            pass
                    if self._log_callback:
                        try:
                            self._log_callback(f"[KILL ALL] Process {pid} killed")
                        except:
                            pass
            except Exception:
                pass
        self._active_processes.clear()
        return killed

    @asynccontextmanager
    async def _managed_xray_process(self, config_path, port: int = 0):
        """Context manager for Xray process with guaranteed cleanup."""
        proc = None
        try:
            # Windows: hide console window to avoid cluttering desktop
            _creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            if sys.platform == "win32":
                _creationflags |= subprocess.CREATE_NO_WINDOW

            engine_path = self._engine_path
            proc = await asyncio.create_subprocess_exec(
                engine_path,
                "-c",
                config_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=_creationflags,
            )
            try:
                self._assign_pid_to_job(proc.pid)
            except Exception:
                pass
            # Добавляем в список активных процессов
            self._active_processes.append(proc)
            await self._log(f"[XRAY] PID {proc.pid} запущен на порту {port}")
            yield proc
        finally:
            if proc:
                # Удаляем из списка активных
                if proc in self._active_processes:
                    self._active_processes.remove(proc)
                if proc.returncode is None:
                    await self._log(f"[XRAY] Завершение PID {proc.pid} (порт {port})")
                try:
                    await asyncio.shield(self._kill_process_failsafe(proc, port))
                except Exception:
                    pass
            self._release_port(port)

    async def check_connection(self, link, semaphore=None):
        """Test a single proxy connection with full async processing."""
        if semaphore is None:
            return await self._check_connection_inner(link)
        async with semaphore:
            return await self._check_connection_inner(link)

    async def _check_connection_inner(self, link):
            try:
                if self.tui is not None and getattr(self.tui, "_stop_requested", False):
                    return None
                if self.tui is not None and hasattr(self.tui, "is_running") and (not getattr(self.tui, "is_running")):
                    return None
            except Exception:
                pass
            # Сокращаем ссылку для логирования (первые 60 символов)
            link_preview = link[:60] + "..." if len(link) > 60 else link
            node_name = "Unknown Node"
            last_error = None

            for attempt in range(2):
                try:
                    if self.tui is not None and getattr(self.tui, "_stop_requested", False):
                        return None
                    if self.tui is not None and hasattr(self.tui, "is_running") and (not getattr(self.tui, "is_running")):
                        return None
                except Exception:
                    pass

                port = self.get_free_port()
                config, node_name = self.build_config(link, port)

                if not config:
                    self._release_port(port)
                    await self._log(f"[SKIP] {node_name} | {link_preview}")
                    return None

                await self._log(f"[CHECK] {node_name[:30]} | {link_preview}")

                if self.tui:
                    self.tui.set_current_config(config, node_name)

                protocol = config["outbounds"][0].get("protocol", "")
                if not protocol:
                    self._release_port(port)
                    await self._log(f"[SKIP] Empty protocol | {link_preview}")
                    return None

                config_path = os.path.join(self._cfg_dir, f"temp_{port}.json")
                try:
                    try:
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(None, self._write_config_file, config_path, config)
                    except Exception:
                        self._write_config_file(config_path, config)

                    await self._log(f"[XRAY] Запуск процесса на порту {port}")

                    try:
                        if self.tui is not None and getattr(self.tui, "_stop_requested", False):
                            return None
                        if self.tui is not None and hasattr(self.tui, "is_running") and (not getattr(self.tui, "is_running")):
                            return None
                    except Exception:
                        pass

                    async with self._managed_xray_process(config_path, port):
                        ready = await self._wait_local_tcp_open(port, timeout_s=1.2)
                        if not ready:
                            last_error = f"port {port} not listening"
                            continue

                        connector = aiohttp_socks.ProxyConnector.from_url(
                            f"socks5://127.0.0.1:{port}"
                        )
                        timeout = aiohttp.ClientTimeout(total=15)
                        base_ping_ms = 0.0
                        try:
                            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                                resource_task = asyncio.create_task(self.check_resources(port, session=session))
                                resource_results = await resource_task

                                ok_rtts = []
                                try:
                                    for _domain, (ok, rtt) in (resource_results.get("results") or {}).items():
                                        if ok and rtt and rtt > 0:
                                            ok_rtts.append(float(rtt))
                                except Exception:
                                    ok_rtts = []

                                if ok_rtts:
                                    base_ping_ms = min(ok_rtts)
                                else:
                                    base_ping_ms = 0.0

                                if resource_results.get("accessible_count", 0) <= 0:
                                    last_error = "resources 0/4"
                                    continue

                                host, host_port = self._extract_host_port(config)

                                await self._log(f"[ACTIVE] {node_name[:30]} | Базовая задержка: {base_ping_ms:.0f}ms")
                        finally:
                            connector.close()

                        reliability_status = "[HIGH RELIABILITY]" if resource_results["is_high_reliability"] else f"✓ {resource_results['accessibility']}"
                        await self._log(f"[RESOURCES] {node_name[:30]} | {reliability_status} | Avg: {resource_results['avg_rtt']:.0f}ms")

                        try:
                            await self._log(
                                f"[RESULT] {node_name[:30]} | {base_ping_ms:.0f}ms | {resource_results['accessibility']} | Avg: {resource_results['avg_rtt']:.0f}ms"
                            )
                        except Exception:
                            pass

                        return {
                            "link": link,
                            "name": node_name,
                            "type": protocol.upper(),
                            "ping": round(base_ping_ms, 1),
                            "host": host,
                            "port": host_port,
                            "accessible_count": resource_results["accessible_count"],
                            "accessibility": resource_results["accessibility"],
                            "is_high_reliability": resource_results["is_high_reliability"],
                            "avg_resource_rtt": resource_results["avg_rtt"],
                            "total_resource_rtt": resource_results["total_rtt"],
                            "resource_results": resource_results["results"],
                            "tags": [],
                        }
                except asyncio.CancelledError:
                    await self._log(f"[CANCELLED] {node_name[:30]} | проверка отменена")
                    raise
                except Exception as e:
                    last_error = str(e)
                    await self._log(f"[ERROR] {node_name[:30]} | {str(e)[:50]}")
                finally:
                    try:
                        if os.path.exists(config_path):
                            os.remove(config_path)
                    except Exception:
                        pass
                    self._release_port(port)

            if last_error:
                await self._log(f"[INACTIVE] {node_name[:30]} | {last_error}")
            else:
                await self._log(f"[INACTIVE] {node_name[:30]} | timeout/failed")
            return None

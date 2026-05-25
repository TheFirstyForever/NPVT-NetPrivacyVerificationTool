# Made by @TheFirSStYfOreVer
import asyncio
import base64
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from typing import Callable, Optional
from urllib.parse import parse_qsl, unquote, urlparse

import aiohttp
import aiohttp_socks


class LogicVerifier:
    def __init__(self, tui=None, log_callback: Optional[Callable[[str], None]] = None):
        self.bin_path = os.path.join(os.getcwd(), "app", "bin", "xray.exe")
        self.test_target = "http://cp.cloudflare.com/generate_204"
        self.process_timeout = 15
        self.tui = tui  # Legacy: ссылка на TUI/GUI для логирования и обновлений
        self._log_callback = log_callback  # Новый callback для логов
        self._current_config = None  # Текущий конфиг для отображения
        self._active_processes: list = []  # Список активных процессов для принудительной остановки

    def get_free_port(self):
        """Safely find a free port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

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
            elif protocol == "ss":
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
            outbound = {"protocol": ptype, "settings": {}, "streamSettings": {}}

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
                # SS формат: ss://method:password@host:port#name
                # или ss://YmFzZTY0ZW5jb2RlZA==@host:port#name
                if "@" not in parsed.netloc:
                    return None, "Missing auth@host in SS URL"
                
                auth, addr = parsed.netloc.split("@", 1)
                
                # Handle IPv6 and ports
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
                
                # Auth может быть в base64 или plain text
                try:
                    # Пытаемся декодировать base64
                    padding = (4 - len(auth) % 4) % 4
                    decoded = base64.b64decode(auth + "=" * padding).decode("utf-8")
                    method, password = decoded.split(":", 1)
                except:
                    # Если не base64, пробуем plain text method:password
                    if ":" in auth:
                        method, password = auth.split(":", 1)
                    else:
                        method, password = "aes-256-gcm", auth
                
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
                    {"port": port, "protocol": "socks", "settings": {"udp": True}}
                ],
                "outbounds": [outbound, {"protocol": "freedom", "tag": "direct"}],
            }, name

        except Exception as e:
            return None, f"Parse error: {str(e)}"

    async def _async_head_check(self, port):
        """Fully async connection check using aiohttp with SOCKS proxy."""
        connector = aiohttp_socks.ProxyConnector.from_url(
            f"socks5://127.0.0.1:{port}"
        )
        timeout = aiohttp.ClientTimeout(total=10)

        try:
            async with aiohttp.ClientSession(
                connector=connector, timeout=timeout
            ) as session:
                async with session.head(self.test_target, allow_redirects=False) as resp:
                    return resp.status in [200, 204]
        except Exception:
            return False
        finally:
            connector.close()

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
            # HEAD запрос без следования редиректам (быстрее)
            async with session.head(url, allow_redirects=False, ssl=False) as resp:
                elapsed = (time.time() - start_time) * 1000
                
                # Считаем успешными 200, 301, 302, 403 (доступ есть, даже если блок)
                success = resp.status in [200, 204, 301, 302, 307, 308, 403, 404]
                
                if success:
                    await self._log(f"[DEBUG] Testing {domain} via SOCKS5:{port}... Success ({elapsed:.0f}ms)")
                else:
                    await self._log(f"[DEBUG] Testing {domain} via SOCKS5:{port}... HTTP {resp.status}")
                
                return domain, success, elapsed if success else 0
                
        except Exception as e:
            await self._log(f"[DEBUG] Testing {domain} via SOCKS5:{port}... Failed ({str(e)[:30]})")
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

    async def check_gemini_availability(self, port: int, session: Optional[aiohttp.ClientSession] = None) -> bool:
        req_timeout = aiohttp.ClientTimeout(total=5)

        allowed_suffixes = (
            "google.com",
            "googleapis.com",
            "google.dev",
            "gstatic.com",
            "googleusercontent.com",
        )

        urls = [
            "https://generativelanguage.googleapis.com/$discovery/rest?version=v1beta",
            "https://generativelanguage.googleapis.com/v1beta/models",
            "https://gemini.google.com/",
        ]

        async def run_probe(sess: aiohttp.ClientSession) -> bool:
            for url in urls:
                try:
                    async with sess.get(url, allow_redirects=False, ssl=False, timeout=req_timeout) as resp:
                        if 300 <= resp.status < 400:
                            location = resp.headers.get("Location") or ""
                            location_low = location.lower()
                            host = urlparse(location).netloc.lower()
                            if host and not host.endswith(allowed_suffixes):
                                return False
                            if "captcha" in location_low or "recaptcha" in location_low or "/sorry/" in location_low:
                                return False
                            continue

                        if resp.status not in (200, 403):
                            continue

                        raw = await resp.content.read(4096)
                        text = raw.decode(errors="ignore")
                        low = text.lower()

                        if "failed_precondition" in low:
                            continue

                        if resp.status == 403:
                            if not (
                                "api key" in low
                                or "api_key" in low
                                or "permission_denied" in low
                                or "unauthenticated" in low
                            ):
                                continue

                        if resp.status == 200 and "$discovery/rest" in url:
                            if "discovery#restdescription" not in low and "gemini api" not in low:
                                continue

                        if (
                            "captcha" in low
                            or "recaptcha" in low
                            or "unusual traffic" in low
                            or "/sorry/" in low
                            or "provider" in low
                            or "blocked" in low
                        ):
                            continue

                        return True
                except Exception:
                    continue
            return False

        if session is not None:
            try:
                return await run_probe(session)
            except Exception:
                return False

        connector = aiohttp_socks.ProxyConnector.from_url(
            f"socks5://127.0.0.1:{port}"
        )
        timeout = aiohttp.ClientTimeout(total=5)

        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as owned_session:
                return await run_probe(owned_session)
        except Exception:
            return False
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
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()

            # Wait with timeout
            try:
                await asyncio.wait_for(proc.wait(), timeout=0.5)
                await self._log(f"[KILL] PID {pid} завершен gracefully")
                return
            except asyncio.TimeoutError:
                await self._log(f"[KILL] PID {pid} не отвечает, принудительное убийство...")
                pass

            # Stage 2: Force kill
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.0)
                await self._log(f"[KILL] PID {pid} убит forcefully")
            except asyncio.TimeoutError:
                await self._log(f"[KILL] ⚠ PID {pid} не удается убить!")
                pass

        except ProcessLookupError:
            await self._log(f"[KILL] PID {pid} уже не существует")
        except Exception as e:
            await self._log(f"[KILL] Ошибка при убийстве PID {pid}: {e}")

    def kill_all_processes(self) -> int:
        """Принудительно убивает все активные процессы xray."""
        import subprocess as sp
        killed = 0
        for proc in self._active_processes[:]:
            try:
                if proc and proc.returncode is None:
                    pid = proc.pid
                    proc.kill()
                    killed += 1
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
            proc = await asyncio.create_subprocess_exec(
                self.bin_path,
                "-c",
                config_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
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
                await self._kill_process_failsafe(proc, port)

    async def check_connection(self, link, semaphore):
        """Test a single proxy connection with full async processing."""
        async with semaphore:
            port = self.get_free_port()
            config, node_name = self.build_config(link, port)

            # Сокращаем ссылку для логирования (первые 60 символов)
            link_preview = link[:60] + "..." if len(link) > 60 else link

            if not config:
                await self._log(f"[SKIP] {node_name} | {link_preview}")
                return None

            # Обновляем текущий конфиг в TUI для отображения
            if self.tui:
                self.tui.set_current_config(config, node_name)

            protocol = config["outbounds"][0].get("protocol", "")
            if not protocol:
                await self._log(f"[SKIP] Empty protocol | {link_preview}")
                return None

            temp_dir = os.path.join("app", "temp_configs")
            os.makedirs(temp_dir, exist_ok=True)
            config_path = os.path.join(temp_dir, f"temp_{port}.json")
            try:
                # Сохраняем временный конфиг
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2)
                
                await self._log(f"[XRAY] Запуск процесса на порту {port}")

                async with self._managed_xray_process(config_path, port) as proc:
                    # Wait for Xray to initialize
                    await asyncio.sleep(0.5)

                    # Measure connection time
                    start_time = time.time()
                    success = await self._async_head_check(port)
                    elapsed = (time.time() - start_time) * 1000

                    host, host_port = self._extract_host_port(config)

                    if success:
                        await self._log(f"[ACTIVE] {node_name[:30]} | Базовая задержка: {elapsed:.0f}ms")

                        await self._log(f"[*] Начинаю проверку доступности endpoint для {node_name[:30]}...")

                        connector = aiohttp_socks.ProxyConnector.from_url(
                            f"socks5://127.0.0.1:{port}"
                        )
                        timeout = aiohttp.ClientTimeout(total=15)
                        try:
                            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                                resource_task = asyncio.create_task(self.check_resources(port, session=session))
                                gemini_task = asyncio.create_task(self.check_gemini_availability(port, session=session))
                                resource_results, gemini_ready = await asyncio.gather(resource_task, gemini_task)
                        finally:
                            connector.close()

                        reliability_status = "[HIGH RELIABILITY]" if resource_results["is_high_reliability"] else f"✓ {resource_results['accessibility']}"
                        await self._log(f"[RESOURCES] {node_name[:30]} | {reliability_status} | Avg: {resource_results['avg_rtt']:.0f}ms")
                        if gemini_ready:
                            await self._log(f"[GEMINI] {node_name[:30]} | Gemini_Ready")
                        else:
                            await self._log(f"[GEMINI] {node_name[:30]} | NOT READY")
                        
                        return {
                            "link": link,
                            "name": node_name,
                            "type": protocol.upper(),
                            "ping": round(elapsed, 1),
                            "host": host,
                            "port": host_port,
                            # Новые поля для ресурсов
                            "accessible_count": resource_results["accessible_count"],
                            "accessibility": resource_results["accessibility"],
                            "is_high_reliability": resource_results["is_high_reliability"],
                            "avg_resource_rtt": resource_results["avg_rtt"],
                            "total_resource_rtt": resource_results["total_rtt"],
                            "resource_results": resource_results["results"],
                            "gemini_ready": gemini_ready,
                            "tags": ["Gemini_Ready"] if gemini_ready else [],
                        }
                    else:
                        await self._log(f"[INACTIVE] {node_name[:30]} | timeout/failed")
                        return None
            except asyncio.CancelledError:
                await self._log(f"[CANCELLED] {node_name[:30]} | проверка отменена")
                raise  # Перебрасываем для обработки выше
            except Exception as e:
                await self._log(f"[ERROR] {node_name[:30]} | {str(e)[:50]}")
                return None
            finally:
                # Cleanup temp config
                try:
                    if os.path.exists(config_path):
                        os.remove(config_path)
                        await self._log(f"[CLEANUP] Удален temp конфиг порта {port}")
                except Exception as e:
                    await self._log(f"[CLEANUP ERROR] Порт {port}: {e}")

import asyncio
import base64
import ipaddress
import json
from typing import Callable, List, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

from aiohttp import web


class LocalSubscriptionServer:
    """
    Lightweight local subscription server.
    - Serves GET /sub on 127.0.0.1:<port>
    - Response: text/plain, each proxy link on a new line (\n)
    - Data source is provided via a callable returning a List[Dict] of results.
    """

    def __init__(
        self,
        data_provider: Callable[[], List[Dict]],
        host: str = "127.0.0.1",
        port: int = 54321,
    ) -> None:
        self._provider = data_provider
        self._host = host
        self._port = port
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._started = asyncio.Event()

    async def _handle_sub(self, request: web.Request) -> web.Response:
        # Get a snapshot from provider
        try:
            results = self._provider() or []
        except Exception:
            results = []

        # Filter working nodes (at least 1 accessible) and sort by base ping ascending
        candidates = [
            r for r in results
            if (
                r
                and isinstance(r, dict)
                and r.get("link")
                and r.get("ping") is not None
                and (r.get("accessible_count", 0) or r.get("is_high_reliability", False))
            )
        ]
        # Top-10 by base RTT (robust to non-numeric values)
        def _ping_key(item: Dict) -> float:
            v = item.get("ping", 1e9)
            try:
                return float(v)
            except Exception:
                try:
                    # Remove non-digits like 'ms'
                    s = str(v)
                    num = "".join(ch for ch in s if (ch.isdigit() or ch in ".-"))
                    return float(num) if num else 1e9
                except Exception:
                    return 1e9
        candidates.sort(key=_ping_key)
        top10 = candidates[:10]

        # Rename nodes as "Топ-1 | <orig> | <flag>", "Топ-2 | <orig> | <flag>", ...
        lines: List[str] = []
        for idx, item in enumerate(top10, start=1):
            link = str(item.get("link", ""))
            if not link:
                continue
            orig_name = str(item.get("name", "")).strip()
            host = str(item.get("host", "")).strip()
            flag = self._flag_from_host(host)
            parts = [f"Топ-{idx}"]
            if orig_name:
                parts.append(orig_name)
            if flag:
                parts.append(flag)
            display = " | ".join(parts)

            renamed = self._rename_link_with_top_name(link, display)
            lines.append(renamed)
        body = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")

        # Try to hint subscription name via headers used by some clients
        headers = {
            "Profile-Title": "Топ-10 рабочих",
            "Content-Disposition": "inline; filename=top10.txt",
        }

        return web.Response(body=body, content_type="text/plain", charset="utf-8", status=200, headers=headers)

    # Helpers
    def _rename_link_with_top_name(self, link: str, top_text: str) -> str:
        """Return a link with display name set to the provided top_text.

        - vless/trojan/ss: use URL fragment '#<top_text>' (replace existing)
        - vmess: decode JSON, set 'ps' to '<top_text>', re-encode (no padding)
        """
        try:
            if link.startswith("vmess://"):
                payload = link[len("vmess://") :]
                padding = (4 - len(payload) % 4) % 4
                try:
                    data = json.loads(base64.b64decode(payload + ("=" * padding)).decode("utf-8"))
                except Exception:
                    return link
                data["ps"] = top_text
                encoded = base64.b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("utf-8")
                return "vmess://" + encoded

            # For other URL-based protocols, replace fragment (URL-encode for compatibility)
            parts = urlsplit(link)
            safe_fragment = base64.b64decode(base64.b64encode(top_text.encode("utf-8"))).decode("utf-8") if isinstance(top_text, str) else str(top_text)
            from urllib.parse import quote
            encoded_fragment = quote(safe_fragment, safe="")
            new_parts = parts._replace(fragment=encoded_fragment)
            return urlunsplit(new_parts)
        except Exception:
            return link

    # Country flag helpers (heuristic by ccTLD)
    def _flag_from_host(self, host: str) -> str:
        """Heuristic: if host is a real IP -> no flag (no GeoIP).
        If host is a domain, try ccTLD mapping to emoji.
        """
        try:
            if not host:
                return ""
            h = host.strip("[]")  # IPv6 may come with brackets
            # Detect real IP (v4/v6). Domains with digits should NOT be treated as IPs.
            try:
                ipaddress.ip_address(h)
                return ""  # no GeoIP lookup to keep server lightweight
            except ValueError:
                pass

            # Domain: extract ccTLD and convert to flag
            tld = h.rsplit(".", 1)[-1].lower()
            if len(tld) == 2 and tld.isalpha():
                return self._cc_to_flag(tld)
            return ""
        except Exception:
            return ""

    def _cc_to_flag(self, cc: str) -> str:
        if not cc or len(cc) != 2:
            return ""
        base = ord('🇦') - ord('A')
        try:
            return chr(base + ord(cc[0].upper())) + chr(base + ord(cc[1].upper()))
        except Exception:
            return ""

    async def start(self) -> None:
        if self._runner is not None:
            # Already started
            self._started.set()
            return

        self._app = web.Application()
        self._app.router.add_get("/sub", self._handle_sub)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, host=self._host, port=self._port)
        await self._site.start()
        self._started.set()

    async def stop(self) -> None:
        self._started.clear()
        try:
            if self._site is not None:
                await self._site.stop()
        finally:
            self._site = None
            try:
                if self._runner is not None:
                    await self._runner.cleanup()
            finally:
                self._runner = None
                self._app = None

    async def wait_until_started(self, timeout: float = 2.0) -> bool:
        try:
            await asyncio.wait_for(self._started.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

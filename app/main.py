"""
NetPrivacy Verification Tool - Modern GUI Edition
Powered by CustomTkinter
Made by @TheFirSStYfOreVer
"""

import asyncio
import os
import re
import sys
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional

import customtkinter as ctk
from PIL import Image

import aiohttp
import aiohttp_socks

# Core imports
from core.scanner import LogicVerifier

# Pyperclip для копирования
try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False

# Настройка темы CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# Константы
CONCURRENT_LIMIT = 50
PROXY_REGEX = re.compile(r'(vless|vmess|trojan|ss)://[^\s<>"\']+', re.IGNORECASE)


def is_proxy_link(text):
    """Проверяет, является ли строка прокси-ссылкой."""
    return text.startswith(("vless://", "vmess://", "trojan://", "ss://"))


class AsyncTkinterBridge:
    """Мост для интеграции asyncio с tkinter mainloop."""
    def __init__(self, root):
        self.root = root
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.pending_callbacks = []
        self.current_task = None
        self._stop_event = asyncio.Event()
        self._check_callbacks()
    
    def _run_loop(self):
        """Запускает event loop в отдельном потоке."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
    
    def _check_callbacks(self):
        """Проверяет и выполняет отложенные callback'и в main thread."""
        while self.pending_callbacks:
            callback = self.pending_callbacks.pop(0)
            try:
                callback()
            except Exception as e:
                print(f"Callback error: {e}")
        self.root.after(50, self._check_callbacks)
    
    def run_async(self, coro, callback=None):
        """Запускает корутину в отдельном потоке с опциональным callback."""
        async def wrapper():
            try:
                result = await coro
                if callback:
                    self.pending_callbacks.append(lambda: callback(result))
                return result
            except asyncio.CancelledError:
                print("Async task was cancelled")
                if callback:
                    self.pending_callbacks.append(lambda: callback(None))
            except Exception as e:
                print(f"Async error: {e}")
                if callback:
                    self.pending_callbacks.append(lambda: callback(None))
        
        # Сбрасываем stop event
        self._stop_event.clear()
        # Создаем Task внутри event loop потокобезопасно
        def create_task():
            self.current_task = self.loop.create_task(wrapper())
        self.loop.call_soon_threadsafe(create_task)
        return True
    
    def cancel_current(self):
        """Отменяет все запущенные задачи."""
        cancelled_count = 0
        
        def do_cancel():
            nonlocal cancelled_count
            # Отменяем все задачи в loop кроме самой loop задачи
            for task in asyncio.all_tasks(self.loop):
                if not task.done() and not task.cancelled():
                    task.cancel()
                    cancelled_count += 1
        
        # Отменяем задачи внутри event loop
        self.loop.call_soon_threadsafe(do_cancel)
        # Устанавливаем stop event
        self.loop.call_soon_threadsafe(self._stop_event.set)
        
        return cancelled_count > 0
    
    def stop(self):
        """Останавливает event loop."""
        self.loop.call_soon_threadsafe(self.loop.stop)
    
    def is_stopped(self):
        """Проверяет, был ли запрошен останов."""
        return self._stop_event.is_set()


class LogPanel(ctk.CTkFrame):
    """Панель логов с авто-прокруткой."""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        
        # Заголовок
        self.header = ctk.CTkLabel(
            self, 
            text="📋 SYSTEM LOGS", 
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("#3B8ED0", "#3B8ED0")
        )
        self.header.pack(pady=(10, 5), padx=10, anchor="w")
        
        # Область логов
        self.log_text = ctk.CTkTextbox(
            self,
            wrap="word",
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=("#1A1A2E", "#1A1A2E"),
            border_color=("#3B8ED0", "#3B8ED0"),
            border_width=1
        )
        self.log_text.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_text.configure(state="disabled")
        
        self.max_lines = 200
    
    def add_log(self, message: str, tag: str = "info"):
        """Добавляет сообщение в лог."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        colors = {
            "info": "#00BFFF",
            "success": "#00FF7F", 
            "warning": "#FFD700",
            "error": "#FF6B6B",
            "debug": "#888888"
        }
        
        color = colors.get(tag, "#FFFFFF")
        
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        
        lines = self.log_text.get("1.0", "end").split("\n")
        if len(lines) > self.max_lines:
            self.log_text.delete("1.0", f"{len(lines) - self.max_lines}.0")
        
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
    
    def clear(self):
        """Очищает лог."""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


class ResultsPanel(ctk.CTkFrame):
    """Панель результатов проверки."""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        
        # Заголовок
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=10, pady=(10, 5))
        
        self.header = ctk.CTkLabel(
            self.header_frame,
            text="🔍 VERIFICATION RESULTS",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=("#3B8ED0", "#3B8ED0")
        )
        self.header.pack(side="left")
        
        self.count_label = ctk.CTkLabel(
            self.header_frame,
            text="Nodes: 0 | Active: 0 | High Reliability: 0",
            font=ctk.CTkFont(size=11)
        )
        self.count_label.pack(side="right")
        
        # Таблица результатов
        self.table_frame = ctk.CTkFrame(self, fg_color=("#1A1A2E", "#1A1A2E"))
        self.table_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Заголовки таблицы
        headers = ["#", "Status", "Node", "Protocol", "Base RTT", "Resources", "Avg RTT", "YT|TG|DC|IG"]
        header_frame = ctk.CTkFrame(self.table_frame, fg_color=("#2D2D44", "#2D2D44"), height=30)
        header_frame.pack(fill="x", padx=1, pady=1)
        header_frame.pack_propagate(False)
        
        col_widths = [4, 12, 20, 8, 10, 10, 10, 20]
        for i, (header, width) in enumerate(zip(headers, col_widths)):
            lbl = ctk.CTkLabel(
                header_frame,
                text=header,
                font=ctk.CTkFont(size=11, weight="bold"),
                width=width * 8,
                text_color=("#3B8ED0", "#3B8ED0")
            )
            lbl.pack(side="left", padx=2)
        
        # Область для строк таблицы с прокруткой
        self.rows_canvas = ctk.CTkCanvas(self.table_frame, bg="#1A1A2E", highlightthickness=0, width=750)
        self.rows_canvas.pack(fill="both", expand=True, padx=1, pady=1)
        
        # Горизонтальная прокрутка
        self.h_scrollbar = ctk.CTkScrollbar(self.table_frame, orientation="horizontal", command=self.rows_canvas.xview)
        self.h_scrollbar.pack(fill="x", padx=1)
        
        self.rows_canvas.configure(xscrollcommand=self.h_scrollbar.set)
        
        self.rows_frame = ctk.CTkFrame(self.rows_canvas, fg_color="transparent", width=750)
        self.rows_canvas.create_window((0, 0), window=self.rows_frame, anchor="nw", width=750)
        
        self.results_data = []
        self.row_widgets = []
    
    def update_counts(self, total: int, active: int, high_rel: int):
        """Обновляет счетчики."""
        self.count_label.configure(
            text=f"Nodes: {total} | Active: {active} | High Reliability: {high_rel}"
        )
    
    def add_result(self, result: dict):
        """Добавляет результат в таблицу."""
        self.results_data.append(result)
        self._refresh_table()
    
    def _refresh_table(self):
        """Обновляет отображение таблицы."""
        for widget in self.row_widgets:
            widget.destroy()
        self.row_widgets = []
        
        sorted_results = sorted(
            self.results_data,
            key=lambda x: (-x.get("accessible_count", 0), x.get("avg_resource_rtt", 99999))
        )
        
        for idx, result in enumerate(sorted_results[:15], 1):
            row_frame = self._create_row(result, idx)
            row_frame.pack(fill="x", padx=2, pady=1)
            self.row_widgets.append(row_frame)
        
        self.rows_frame.update_idletasks()
        self.rows_canvas.configure(scrollregion=self.rows_canvas.bbox("all"))
        self.rows_canvas.configure(width=750)
        
        active_count = sum(1 for r in self.results_data if r.get("accessible_count", 0) >= 1)
        high_count = sum(1 for r in self.results_data if r.get("is_high_reliability", False))
        self.update_counts(len(self.results_data), active_count, high_count)
    
    def _create_row(self, result: dict, idx: int) -> ctk.CTkFrame:
        """Создает строку таблицы."""
        accessible = result.get("accessible_count", 0)
        
        if accessible == 4:
            bg_color = ("#2D5016", "#2D5016")
            status_text = "★ HIGH"
            status_color = "#FFD700"
        elif accessible == 3:
            bg_color = ("#1E3A2F", "#1E3A2F")
            status_text = "✓ GOOD"
            status_color = "#00FF7F"
        elif accessible == 2:
            bg_color = ("#1A2F1A", "#1A2F1A")
            status_text = "✓ OK"
            status_color = "#90EE90"
        elif accessible == 1:
            bg_color = ("#3A3010", "#3A3010")
            status_text = "~ WEAK"
            status_color = "#FFD700"
        else:
            bg_color = ("#3A1A1A", "#3A1A1A")
            status_text = "✗ DEAD"
            status_color = "#FF6B6B"

        if result.get("gemini_ready"):
            status_text = f"{status_text} G"
        
        row = ctk.CTkFrame(self.rows_frame, fg_color=bg_color, height=28, width=750)
        row.pack_propagate(False)
        
        node_name = result.get("name", "Unknown")[:18]
        protocol = result.get("type", "?").upper()[:4]
        ping = f"{result.get('ping', 0):.0f}"
        accessibility = result.get("accessibility", "0/4")
        avg_rtt = f"{result.get('avg_resource_rtt', 0):.0f}" if result.get("avg_resource_rtt", 0) > 0 else "-"
        
        details = result.get("resource_results", {})
        domains_map = {"youtube.com": "YT", "t.me": "TG", "discord.com": "DC", "instagram.com": "IG"}
        resource_strs = []
        for domain, short in domains_map.items():
            if domain in details:
                success, rtt = details[domain]
                if success:
                    resource_strs.append(f"{short}:{rtt:.0f}")
                else:
                    resource_strs.append(f"{short}:T")
            else:
                resource_strs.append(f"{short}:-")
        resource_text = "|".join(resource_strs)
        
        cols_data = [
            (str(idx), 4),
            (status_text, 12),
            (node_name, 20),
            (protocol, 8),
            (ping, 10),
            (accessibility, 10),
            (avg_rtt, 10),
            (resource_text, 20)
        ]
        
        for text, width in cols_data:
            text_color = status_color if width == 12 else ("#E0E0E0", "#E0E0E0")
            lbl = ctk.CTkLabel(
                row, 
                text=text, 
                width=width * 8,
                font=ctk.CTkFont(size=10),
                text_color=text_color
            )
            lbl.pack(side="left", padx=2)
        
        return row
    
    def clear(self):
        """Очищает таблицу."""
        self.results_data = []
        for widget in self.row_widgets:
            widget.destroy()
        self.row_widgets = []
        self.update_counts(0, 0, 0)


class CurrentNodePanel(ctk.CTkFrame):
    """Панель текущего проверяемого узла."""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        
        self.header = ctk.CTkLabel(
            self,
            text="⚡ CURRENT NODE",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("#3B8ED0", "#3B8ED0")
        )
        self.header.pack(pady=(10, 5), padx=10, anchor="w")
        
        # Информационные поля
        self.info_frame = ctk.CTkFrame(self, fg_color=("#1A1A2E", "#1A1A2E"))
        self.info_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.fields = {}
        field_names = ["Name:", "Host:", "Port:", "Protocol:", "Network:", "Security:"]
        
        for name in field_names:
            frame = ctk.CTkFrame(self.info_frame, fg_color="transparent")
            frame.pack(fill="x", padx=10, pady=2)
            
            lbl = ctk.CTkLabel(
                frame,
                text=name,
                font=ctk.CTkFont(size=11, weight="bold"),
                width=80,
                anchor="w"
            )
            lbl.pack(side="left")
            
            val = ctk.CTkLabel(
                frame,
                text="-",
                font=ctk.CTkFont(size=11),
                anchor="w"
            )
            val.pack(side="left", fill="x", expand=True)
            
            self.fields[name] = val
        
        # Индикатор прогресса
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_frame.pack(fill="x", padx=10, pady=5)
        
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, height=8)
        self.progress_bar.pack(fill="x", padx=5, pady=5)
        self.progress_bar.set(0)
        
        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="Ready to scan",
            font=ctk.CTkFont(size=10)
        )
        self.progress_label.pack()
    
    def update_node(self, config: dict, name: str = ""):
        """Обновляет информацию о текущем узле."""
        if not config:
            for val in self.fields.values():
                val.configure(text="-")
            return
        
        outbound = config.get("outbounds", [{}])[0]
        protocol = outbound.get("protocol", "unknown")
        
        settings = outbound.get("settings", {})
        stream = outbound.get("streamSettings", {})
        
        host = "N/A"
        port = "N/A"
        
        if protocol in ["vless", "vmess", "trojan"]:
            vnext = settings.get("vnext", [{}])[0] if protocol in ["vless", "vmess"] else {}
            if protocol == "trojan":
                servers = settings.get("servers", [{}])
                if servers:
                    host = servers[0].get("address", "N/A")
                    port = str(servers[0].get("port", "N/A"))
            else:
                host = vnext.get("address", "N/A")
                port = str(vnext.get("port", "N/A"))
        elif protocol == "ss":
            servers = settings.get("servers", [{}])
            if servers:
                host = servers[0].get("address", "N/A")
                port = str(servers[0].get("port", "N/A"))
        
        network = stream.get("network", "tcp")
        security = stream.get("security", "none")
        
        self.fields["Name:"].configure(text=name[:30] if name else "Unknown")
        self.fields["Host:"].configure(text=host)
        self.fields["Port:"].configure(text=port)
        self.fields["Protocol:"].configure(text=protocol.upper())
        self.fields["Network:"].configure(text=network)
        self.fields["Security:"].configure(text=security)
    
    def update_progress(self, current: int, total: int):
        """Обновляет прогресс-бар."""
        if total > 0:
            progress = current / total
            self.progress_bar.set(progress)
            self.progress_label.configure(text=f"Progress: {current}/{total} ({int(progress*100)}%)")
        else:
            self.progress_bar.set(0)
            self.progress_label.configure(text="Ready to scan")
    
    def reset(self):
        """Сбрасывает панель."""
        for val in self.fields.values():
            val.configure(text="-")
        self.progress_bar.set(0)
        self.progress_label.configure(text="Ready to scan")


class BestConfigPanel(ctk.CTkFrame):
    """Панель лучшей конфигурации."""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        
        self.best_config = None
        
        self.header = ctk.CTkLabel(
            self,
            text="🏆 OPTIMAL CONFIG",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("#FFD700", "#FFD700")
        )
        self.header.pack(pady=(10, 5), padx=10, anchor="w")
        
        # Информация о лучшей конфигурации
        self.info_frame = ctk.CTkFrame(self, fg_color=("#1A1A2E", "#1A1A2E"))
        self.info_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.status_label = ctk.CTkLabel(
            self.info_frame,
            text="Waiting for high reliability node...",
            font=ctk.CTkFont(size=11),
            text_color=("#888888", "#888888")
        )
        self.status_label.pack(pady=20)
        
        # Кнопки
        self.button_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.button_frame.pack(fill="x", padx=10, pady=5)
        
        self.copy_btn = ctk.CTkButton(
            self.button_frame,
            text="📋 Copy to Clipboard",
            command=self._copy_to_clipboard,
            fg_color=("#2D5016", "#2D5016"),
            hover_color=("#3D7020", "#3D7020"),
            state="disabled"
        )
        self.copy_btn.pack(fill="x", pady=2)
        
        self.save_btn = ctk.CTkButton(
            self.button_frame,
            text="💾 Save to File",
            command=self._save_to_file,
            fg_color=("#1E3A5F", "#1E3A5F"),
            hover_color=("#2E4A6F", "#2E4A6F"),
            state="disabled"
        )
        self.save_btn.pack(fill="x", pady=2)
    
    def update_config(self, result: dict):
        """Обновляет лучшую конфигурацию."""
        if not result or not result.get("is_high_reliability"):
            return
        
        if self.best_config:
            current_avg = self.best_config.get("avg_resource_rtt", 99999)
            new_avg = result.get("avg_resource_rtt", 99999)
            if new_avg >= current_avg:
                return
        
        self.best_config = result
        self._update_display()
    
    def _update_display(self):
        """Обновляет отображение."""
        if not self.best_config:
            return
        
        for widget in self.info_frame.winfo_children():
            widget.destroy()
        
        name = self.best_config.get("name", "Unknown")[:25]
        avg_rtt = self.best_config.get("avg_resource_rtt", 0)
        accessibility = self.best_config.get("accessibility", "0/4")
        
        ctk.CTkLabel(
            self.info_frame,
            text=f"{name}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#FFD700", "#FFD700")
        ).pack(pady=(10, 5))
        
        ctk.CTkLabel(
            self.info_frame,
            text=f"Protocol: {self.best_config.get('type', '?').upper()}",
            font=ctk.CTkFont(size=11)
        ).pack()
        
        ctk.CTkLabel(
            self.info_frame,
            text=f"Average RTT: {avg_rtt:.1f}ms",
            font=ctk.CTkFont(size=11),
            text_color=("#00FF7F", "#00FF7F")
        ).pack()
        
        ctk.CTkLabel(
            self.info_frame,
            text=f"Accessibility: {accessibility}",
            font=ctk.CTkFont(size=11),
            text_color=("#00FF7F", "#00FF7F")
        ).pack()
        
        # Детали по ресурсам
        details = self.best_config.get("resource_results", {})
        domains_map = {"youtube.com": "YT", "t.me": "TG", "discord.com": "DC", "instagram.com": "IG"}
        
        detail_frame = ctk.CTkFrame(self.info_frame, fg_color="transparent")
        detail_frame.pack(pady=5)
        
        for domain, short in domains_map.items():
            if domain in details:
                success, rtt = details[domain]
                color = "#00FF7F" if success else "#FF6B6B"
                text = f"{short}: {rtt:.0f}ms" if success else f"{short}: TIMEOUT"
            else:
                color = "#888888"
                text = f"{short}: -"
            
            ctk.CTkLabel(
                detail_frame,
                text=text,
                font=ctk.CTkFont(size=10, family="Consolas"),
                text_color=color
            ).pack(side="left", padx=5)
        
        self.copy_btn.configure(state="normal")
        self.save_btn.configure(state="normal")
    
    def _copy_to_clipboard(self):
        """Копирует ссылку в буфер обмена."""
        if not self.best_config:
            return
        
        link = self.best_config.get("link", "")
        if not link:
            return
        
        try:
            copied = False
            
            # Пробуем pyperclip
            if HAS_PYPERCLIP:
                try:
                    pyperclip.copy(link)
                    copied = True
                except Exception as pe:
                    print(f"pyperclip failed: {pe}, trying fallback...")
            
            # Fallback для Windows через ctypes
            if not copied:
                import ctypes
                
                CF_UNICODETEXT = 13
                
                # Open clipboard
                if not ctypes.windll.user32.OpenClipboard(0):
                    raise Exception("Failed to open clipboard")
                try:
                    ctypes.windll.user32.EmptyClipboard()
                    
                    # Allocate memory
                    size = (len(link) + 1) * 2
                    handle = ctypes.windll.kernel32.GlobalAlloc(0x0002 | 0x0040, size)
                    if not handle:
                        raise Exception("Failed to allocate memory")
                    
                    # Lock and copy
                    ptr = ctypes.windll.kernel32.GlobalLock(handle)
                    if ptr:
                        ctypes.memmove(ptr, link.encode('utf-16-le'), len(link) * 2)
                        ctypes.windll.kernel32.GlobalUnlock(handle)
                    
                    # Set clipboard data
                    if not ctypes.windll.user32.SetClipboardData(CF_UNICODETEXT, handle):
                        raise Exception("Failed to set clipboard data")
                finally:
                    ctypes.windll.user32.CloseClipboard()
            
            self.copy_btn.configure(text="✅ Copied!", fg_color=("#00FF7F", "#00FF7F"))
            self.after(2000, lambda: self.copy_btn.configure(
                text="📋 Copy to Clipboard",
                fg_color=("#2D5016", "#2D5016")
            ))
        except Exception as e:
            print(f"Clipboard error: {e}")
            self.log_panel.add_log(f"Copy failed: {e}", "error")
            self.copy_btn.configure(text="❌ Failed", fg_color=("#7B2D2D", "#7B2D2D"))
            self.after(2000, lambda: self.copy_btn.configure(
                text="📋 Copy to Clipboard",
                fg_color=("#2D5016", "#2D5016")
            ))
    
    def _save_to_file(self):
        """Сохраняет конфигурацию в файл."""
        if not self.best_config:
            return
        
        try:
            result_dir = os.path.join("app", "result")
            os.makedirs(result_dir, exist_ok=True)
            
            file_path = os.path.join(result_dir, "optimal_config.txt")
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"# NetPrivacy Verification Tool - Optimal Configuration\n")
                f.write(f"# Made by @TheFirSStYfOreVer\n")
                f.write(f"# Node: {self.best_config.get('name', 'Unknown')}\n")
                f.write(f"# Protocol: {self.best_config.get('type', 'Unknown').upper()}\n")
                f.write(f"# Avg Latency: {self.best_config.get('avg_resource_rtt', 0):.1f}ms\n")
                f.write(f"# Endpoint Availability: {self.best_config.get('accessibility', '0/4')}\n")
                f.write(f"# Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"#{'='*60}\n")
                f.write(f"{self.best_config.get('link', '')}\n")
            
            self.save_btn.configure(text="✅ Saved!", fg_color=("#00FF7F", "#00FF7F"))
            self.after(2000, lambda: self.save_btn.configure(
                text="💾 Save to File",
                fg_color=("#1E3A5F", "#1E3A5F")
            ))
        except Exception as e:
            print(f"Save error: {e}")
    
    def reset(self):
        """Сбрасывает панель."""
        self.best_config = None
        for widget in self.info_frame.winfo_children():
            widget.destroy()
        
        self.status_label = ctk.CTkLabel(
            self.info_frame,
            text="Waiting for high reliability node...",
            font=ctk.CTkFont(size=11),
            text_color=("#888888", "#888888")
        )
        self.status_label.pack(pady=20)
        
        self.copy_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")


class ControlPanel(ctk.CTkFrame):
    """Панель управления."""
    def __init__(self, parent, on_start=None, on_stop=None, **kwargs):
        super().__init__(parent, **kwargs)
        
        self.on_start = on_start
        self.on_stop = on_stop
        
        self.header = ctk.CTkLabel(
            self,
            text="🎮 CONTROL CENTER",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("#3B8ED0", "#3B8ED0")
        )
        self.header.pack(pady=(10, 15), padx=10, anchor="w")
        
        # Кнопки управления
        self.start_btn = ctk.CTkButton(
            self,
            text="▶ START VERIFICATION",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=45,
            fg_color=("#1E592E", "#1E592E"),
            hover_color=("#2E7940", "#2E7940"),
            command=self._on_start_click
        )
        self.start_btn.pack(fill="x", padx=10, pady=5)
        
        self.stop_btn = ctk.CTkButton(
            self,
            text="⏹ STOP",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=40,
            fg_color=("#7B2D2D", "#7B2D2D"),
            hover_color=("#9B3D3D", "#9B3D3D"),
            command=self._on_stop_click,
            state="disabled"
        )
        self.stop_btn.pack(fill="x", padx=10, pady=5)
        
        # Разделитель
        ctk.CTkFrame(self, height=2, fg_color=("#3B8ED0", "#3B8ED0")).pack(
            fill="x", padx=10, pady=15
        )
        
        # Настройки
        ctk.CTkLabel(
            self,
            text="⚙ SETTINGS",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(padx=10, anchor="w")
        
        # Параллелизм
        self.concurrency_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.concurrency_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(
            self.concurrency_frame,
            text="Concurrency:",
            font=ctk.CTkFont(size=11)
        ).pack(side="left")
        
        self.concurrency_var = ctk.StringVar(value="50")
        self.concurrency_combo = ctk.CTkComboBox(
            self.concurrency_frame,
            values=["10", "25", "50", "75", "100"],
            variable=self.concurrency_var,
            width=70
        )
        self.concurrency_combo.pack(side="right")
    
    def _on_start_click(self):
        """Обработчик нажатия Start."""
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        if self.on_start:
            self.on_start(int(self.concurrency_var.get()))
    
    def _on_stop_click(self):
        """Обработчик нажатия Stop."""
        self.stop_btn.configure(state="disabled")
        if self.on_stop:
            self.on_stop()
    
    def reset_buttons(self):
        """Сбрасывает состояние кнопок."""
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")


class NetPrivacyApp(ctk.CTk):
    """Главное окно приложения."""
    def __init__(self):
        super().__init__()
        
        self.title("NetPrivacy Verification Tool | made by @TheFirSStYfOreVer")
        self.geometry("1400x900")
        self.minsize(1200, 700)
        
        # Цветовая схема
        self.configure(fg_color=("#0F0F1A", "#0F0F1A"))
        
        # Инициализация async bridge
        self.async_bridge = AsyncTkinterBridge(self)
        
        # Состояние
        self.scanner = None
        self.is_running = False
        self.current_results = []
        self.semaphore_limit = CONCURRENT_LIMIT
        self._stop_requested = False
        self._active_tasks = []  # Храним задачи для отмены при STOP
        
        self._build_ui()
        
        # Проверка pyperclip
        import sys
        python_exe = sys.executable
        if not HAS_PYPERCLIP:
            self.after(1000, lambda: self.log_panel.add_log(
                f"pyperclip not found in {python_exe}. Clipboard will use Windows API fallback.",
                "warning"
            ))
        else:
            self.after(1000, lambda: self.log_panel.add_log(
                f"pyperclip loaded OK from {python_exe}",
                "success"
            ))
    
    def _build_ui(self):
        """Строит пользовательский интерфейс."""
        # Главный контейнер
        self.main_frame = ctk.CTkFrame(self, fg_color=("#0F0F1A", "#0F0F1A"))
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Верхняя панель с заголовком
        self.title_frame = ctk.CTkFrame(self.main_frame, fg_color=("#1A1A2E", "#1A1A2E"), height=60)
        self.title_frame.pack(fill="x", padx=5, pady=5)
        self.title_frame.pack_propagate(False)
        
        self.title_label = ctk.CTkLabel(
            self.title_frame,
            text="🔒 NetPrivacy Verification Tool | @TheFirSStYfOreVer",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=("#3B8ED0", "#3B8ED0")
        )
        self.title_label.pack(side="left", padx=20, pady=10)
        
        self.subtitle_label = ctk.CTkLabel(
            self.title_frame,
            text="Research utility for encrypted node availability & security",
            font=ctk.CTkFont(size=12),
            text_color=("#888888", "#888888")
        )
        self.subtitle_label.pack(side="left", padx=10, pady=10)
        
        # Центральная область
        self.center_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.center_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Левая панель (контролы + логи)
        self.left_panel = ctk.CTkFrame(self.center_frame, fg_color=("#161622", "#161622"), width=320)
        self.left_panel.pack(side="left", fill="y", padx=5, pady=5)
        self.left_panel.pack_propagate(False)
        
        # Панель управления
        self.control_panel = ControlPanel(
            self.left_panel,
            on_start=self._start_verification,
            on_stop=self._stop_verification,
            fg_color="transparent"
        )
        self.control_panel.pack(fill="x", padx=5, pady=5)
        
        # Панель логов
        self.log_panel = LogPanel(self.left_panel, fg_color="transparent")
        self.log_panel.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Правая область (результаты + инфо)
        self.right_panel = ctk.CTkFrame(self.center_frame, fg_color=("#161622", "#161622"))
        self.right_panel.pack(side="right", fill="both", expand=True, padx=5, pady=5)
        
        # Верхняя часть - результаты
        self.results_panel = ResultsPanel(self.right_panel, fg_color="transparent")
        self.results_panel.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Нижняя часть - инфо панели
        self.info_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent", height=280)
        self.info_frame.pack(fill="both", padx=5, pady=5)
        self.info_frame.pack_propagate(False)
        
        # Текущий узел
        self.current_node_panel = CurrentNodePanel(
            self.info_frame,
            fg_color=("#1A1A2E", "#1A1A2E"),
            width=400
        )
        self.current_node_panel.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        
        # Лучшая конфигурация
        self.best_config_panel = BestConfigPanel(
            self.info_frame,
            fg_color=("#1A1A2E", "#1A1A2E"),
            width=350
        )
        self.best_config_panel.pack(side="right", fill="both", expand=True, padx=5, pady=5)
    
    def _start_verification(self, concurrency: int):
        """Запускает процесс верификации."""
        if self.is_running:
            return
        
        self.is_running = True
        self._stop_requested = False
        self.semaphore_limit = concurrency
        
        # Очистка предыдущих результатов
        self.results_panel.clear()
        self.current_node_panel.reset()
        self.best_config_panel.reset()
        self.log_panel.clear()
        
        self.log_panel.add_log(f"Starting verification with concurrency: {concurrency}", "info")
        
        # Запускаем async задачу
        self._current_verification = self.async_bridge.run_async(self._run_verification(), self._on_verification_complete)
    
    def _stop_verification(self):
        """Останавливает процесс верификации полностью."""
        if not self.is_running:
            return
        
        self._stop_requested = True
        self.log_panel.add_log("🛑 STOPPING: Cancelling all operations...", "warning")
        
        # 1. Отменяем все активные задачи проверки
        cancelled_tasks = 0
        for task in self._active_tasks:
            if not task.done():
                task.cancel()
                cancelled_tasks += 1
        if cancelled_tasks > 0:
            self.log_panel.add_log(f"Cancelled {cancelled_tasks} check tasks", "info")
        
        # 2. Отменяем future в async bridge
        cancelled = self.async_bridge.cancel_current()
        if cancelled:
            self.log_panel.add_log("Async tasks cancelled", "info")
        
        # 3. Убиваем все процессы xray через scanner
        if self.scanner:
            killed = self.scanner.kill_all_processes()
            self.log_panel.add_log(f"Killed {killed} active processes", "info")
        
        # 4. Принудительно останавливаем сессии aiohttp
        self.log_panel.add_log("Closing all connections...", "info")
        
        self.is_running = False
        self.control_panel.reset_buttons()
        self.log_panel.add_log("✓ Verification stopped", "success")
    
    def _on_verification_complete(self, results):
        """Обработчик завершения верификации."""
        self.is_running = False
        self.control_panel.reset_buttons()
        
        if results:
            self.log_panel.add_log(f"Verification complete. Total nodes: {len(results)}", "success")
            self._save_results_to_file(results)
        else:
            self.log_panel.add_log("Verification finished with no results", "warning")
    
    async def _run_verification(self):
        """Основная логика верификации."""
        try:
            return await self._do_verification()
        except asyncio.CancelledError:
            self.log_panel.add_log("Verification cancelled by user", "warning")
            return []
    
    async def _do_verification(self):
        """Внутренняя логика верификации."""
        src_path = os.path.join("app", "data", "sources.txt")
        
        if not os.path.exists(src_path):
            self.log_panel.add_log("ERROR: app/data/sources.txt not found!", "error")
            return []
        
        self.scanner = LogicVerifier(tui=self)
        all_links = []
        
        # Читаем источники
        self.log_panel.add_log("Collecting proxy configurations...", "info")
        
        with open(src_path, "r", encoding="utf-8") as f:
            sources = [line.strip() for line in f if line.strip()]
        
        self.log_panel.add_log(f"Loaded {len(sources)} sources", "info")
        
        async with aiohttp.ClientSession() as session:
            for source in sources:
                if self._stop_requested:
                    break
                
                # Проверяем отмену задачи
                try:
                    asyncio.current_task().cancelled()
                except asyncio.CancelledError:
                    break
                
                if is_proxy_link(source):
                    all_links.append(source)
                    self.log_panel.add_log(f"Direct link added: {source[:50]}...", "debug")
                    continue
                
                if source.startswith(("http://", "https://")):
                    try:
                        self.log_panel.add_log(f"Loading: {source[:60]}...", "info")
                        async with session.get(source, timeout=15) as resp:
                            if resp.status != 200:
                                self.log_panel.add_log(f"HTTP {resp.status}: {source[:50]}", "error")
                                continue
                            
                            text = await resp.text()
                            full_links = []
                            for match in PROXY_REGEX.finditer(text):
                                full_links.append(match.group(0))
                            
                            unique_links = list(set(full_links))
                            all_links.extend(unique_links)
                            self.log_panel.add_log(f"Found {len(unique_links)} links from {source[:50]}...", "success")
                    except asyncio.CancelledError:
                        break
                    except Exception as e:
                        self.log_panel.add_log(f"Error loading {source[:50]}: {e}", "error")
        
        # Дедупликация
        all_links = list(dict.fromkeys(all_links))
        
        if not all_links:
            self.log_panel.add_log("No configurations found!", "error")
            return []
        
        self.log_panel.add_log(f"Total unique links: {len(all_links)}", "info")
        
        # Проверка
        sem = asyncio.BoundedSemaphore(self.semaphore_limit)
        # Создаем Task явно чтобы можно было отменить
        self._active_tasks = [asyncio.create_task(self.scanner.check_connection(link, sem)) for link in all_links]
        
        results = []
        completed = 0
        total = len(self._active_tasks)
        
        self.log_panel.add_log(f"Starting check of {total} nodes...", "info")
        
        try:
            for task in asyncio.as_completed(self._active_tasks):
                if self._stop_requested:
                    break
                
                try:
                    res = await task
                    completed += 1
                    
                    # Обновляем прогресс
                    self.after(0, lambda c=completed, t=total: self.current_node_panel.update_progress(c, t))
                    
                    if res is not None:
                        results.append(res)
                        
                        # Обновляем UI
                        self.after(0, lambda r=res: self._add_result_to_ui(r))
                        
                        accessible_count = res.get("accessible_count", 0)
                        reliability_mark = "[HIGH RELIABILITY]" if res.get("is_high_reliability") else f"✓ {res.get('accessibility', '0/4')}"
                        gemini_mark = " | Gemini_Ready" if res.get("gemini_ready") else ""
                        
                        self.log_panel.add_log(
                            f"{res['name'][:40]} | {res['ping']}ms | {reliability_mark}{gemini_mark}",
                            "success" if accessible_count >= 2 else "warning"
                        )
                    
                    if completed % 5 == 0 or completed == total:
                        self.log_panel.add_log(f"Progress: {completed}/{total} ({completed*100//total}%)", "info")
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.log_panel.add_log(f"Check error: {e}", "error")
        finally:
            # Отменяем все оставшиеся задачи
            for task in self._active_tasks:
                if not task.done():
                    task.cancel()
            self._active_tasks = []
        
        return results
    
    def _add_result_to_ui(self, result: dict):
        """Добавляет результат в UI (вызывается в main thread)."""
        self.results_panel.add_result(result)
        
        if result.get("is_high_reliability"):
            self.best_config_panel.update_config(result)
    
    def _save_results_to_file(self, results: list):
        """Сохраняет результаты в файл."""
        try:
            # Сортируем
            results.sort(key=lambda x: (
                -x.get("accessible_count", 0),
                x.get("avg_resource_rtt", 99999)
            ))
            
            # Сохраняем
            with open(os.path.join("app", "data", "verified_nodes.txt"), "w", encoding="utf-8") as f:
                for r in results:
                    if r.get("is_high_reliability"):
                        gemini_tag = " | Gemini_Ready" if r.get("gemini_ready") else ""
                        f.write(f"# HIGH RELIABILITY {r.get('accessibility')} | Avg: {r.get('avg_resource_rtt')}ms | {r['name']}{gemini_tag}\n")
                        f.write(f"{r['link']}\n\n")
                
                for r in results:
                    if not r.get("is_high_reliability"):
                        gemini_tag = " | Gemini_Ready" if r.get("gemini_ready") else ""
                        f.write(f"# {r.get('accessibility')} | Avg: {r.get('avg_resource_rtt')}ms | {r['name']}{gemini_tag}\n")
                        f.write(f"{r['link']}\n\n")
            
            self.log_panel.add_log(f"Results saved to data/verified_nodes.txt", "success")
        except Exception as e:
            self.log_panel.add_log(f"Save error: {e}", "error")
    
    # Методы для совместимости с scanner.py
    async def log(self, message: str):
        """Логирование для совместимости с scanner."""
        tag = "info"
        if "[ERROR]" in message or "[!]" in message:
            tag = "error"
        elif "[ACTIVE]" in message or "[+]" in message:
            tag = "success"
        elif "[WARN]" in message:
            tag = "warning"
        elif "[DEBUG]" in message or "[*]" in message:
            tag = "debug"
        
        self.after(0, lambda m=message, t=tag: self.log_panel.add_log(m, t))
    
    def set_current_config(self, config: dict, name: str = ""):
        """Устанавливает текущую конфигурацию для отображения."""
        self.after(0, lambda c=config, n=name: self.current_node_panel.update_node(c, n))
    
    def on_closing(self):
        """Обработчик закрытия окна."""
        self._stop_requested = True
        self.async_bridge.stop()
        self.destroy()


def main():
    """Точка входа."""
    app = NetPrivacyApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    
    print("""
╔══════════════════════════════════════════════════════════════╗
║     NetPrivacy Verification Tool - GUI Edition               ║
║     Powered by CustomTkinter                                 ║
║     Made by @TheFirSStYfOreVer                               ║
║                                                              ║
║     Supported protocols: VLESS, VMESS, Trojan, Shadowsocks   ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    app.mainloop()


if __name__ == "__main__":
    main()

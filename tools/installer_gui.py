"""
NetPrivacy Verification Tool — Legacy GUI Installer (DEPRECATED)

This project has migrated to a Flet-based application and an Inno Setup installer.
Use:
- NetPrivacyTool_Setup.exe (Inno Setup)

This file is kept only for historical reference and now exits immediately.
Made by @TheFirSStYfOreVer
"""

import sys

print("[DEPRECATED] installer_gui.py is no longer supported. Use the Inno Setup installer.")
raise SystemExit(1)

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import tempfile
import random
import winreg
import stat
import ctypes
from ctypes import wintypes
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────
APP_NAME        = "NetPrivacyTool"
APP_DISPLAY     = "NetPrivacy Verification Tool"
APP_VERSION     = "2.0"
APP_PUBLISHER   = "@TheFirSStYfOreVer"
APP_EXE_NAME    = "NetPrivacyTool.exe"
ENGINE_ORIGINAL = "xray.exe"
ENGINE_RENAMED  = "npvt_core.exe"
CONFLICT_NAMES  = {"xray.exe", "np_engine.exe", "npvt_core.exe", APP_EXE_NAME.lower()}
PORT_RANGE      = (20000, 30000)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _bundle_base() -> str:
    """Root of bundled resources (sys._MEIPASS when frozen, project root otherwise)."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_free_port() -> int:
    for _ in range(300):
        port = random.randint(*PORT_RANGE)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return 25432


def _running_conflicts(install_dir: str) -> list[dict]:
    """Return list of running processes that would block overwriting install_dir."""
    install_dir = os.path.abspath(install_dir)
    found: list[dict] = []
    try:
        ps = (
            "$names=@('xray','np_engine','npvt_core','NetPrivacyTool');"
            "$p=Get-CimInstance Win32_Process | Where-Object { $names -contains ($_.Name -replace '\\.[^.]+$','') };"
            "$p | Select-Object Name,ProcessId,ExecutablePath | ConvertTo-Json -Compress"
        )
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        ).decode(errors="ignore").strip()

        if out:
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            for p in data:
                exe_path = (p.get("ExecutablePath") or "").strip()
                name = (p.get("Name") or "").strip()
                pid = str(p.get("ProcessId") or "?")
                if exe_path and os.path.abspath(exe_path).startswith(install_dir):
                    found.append({"name": name, "pid": pid, "path": exe_path})
        return found
    except Exception:
        pass

    return []


def _create_shortcut(target: str, shortcut_path: str, icon: str = "", description: str = "") -> None:
    icon_line = f'$s.IconLocation="{icon}";' if icon and os.path.isfile(icon) else ""
    ps = (
        f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{shortcut_path}");'
        f'$s.TargetPath="{target}";'
        f'$s.WorkingDirectory="{os.path.dirname(target)}";'
        f'$s.Description="{description}";'
        f'{icon_line}'
        f'$s.Save()'
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        creationflags=0x08000000,
    )


def _get_desktop_dir() -> str:
    try:
        # FOLDERID_Desktop = {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
        fid = (ctypes.c_ubyte * 16).from_buffer_copy(
            bytes.fromhex("3ACCBFB42CDB4C42B0297FE99A87C641")
        )
        ppath = ctypes.c_wchar_p()
        SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
        SHGetKnownFolderPath.argtypes = [ctypes.POINTER(ctypes.c_ubyte), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
        SHGetKnownFolderPath.restype = wintypes.HRESULT
        hr = SHGetKnownFolderPath(fid, 0, 0, ctypes.byref(ppath))
        if hr == 0 and ppath.value:
            return ppath.value
    except Exception:
        pass

    userprofile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(userprofile, "Desktop")


def _register_uninstall(install_dir: str, exe_path: str, icon_path: str) -> None:
    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\NetPrivacyTool"
    uninstall_cmd = f'"{exe_path}" /uninstall'
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, "DisplayName",     0, winreg.REG_SZ,    APP_DISPLAY)
            winreg.SetValueEx(k, "DisplayVersion",  0, winreg.REG_SZ,    APP_VERSION)
            winreg.SetValueEx(k, "Publisher",       0, winreg.REG_SZ,    APP_PUBLISHER)
            winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ,    install_dir)
            winreg.SetValueEx(k, "DisplayIcon",     0, winreg.REG_SZ,    icon_path)
            winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ,    uninstall_cmd)
            winreg.SetValueEx(k, "NoModify",        0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair",        0, winreg.REG_DWORD, 1)
    except Exception:
        pass


def _read_install_location() -> str | None:
    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\NetPrivacyTool"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            v, _t = winreg.QueryValueEx(k, "InstallLocation")
            v = (v or "").strip()
            return v if v else None
    except Exception:
        return None


def _unregister_uninstall() -> None:
    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\NetPrivacyTool"
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
    except Exception:
        pass


def _schedule_delete_install_dir(install_dir: str) -> None:
    install_dir = os.path.abspath(install_dir)
    if sys.platform != "win32":
        return

    t = install_dir.replace("'", "''")
    ps = (
        f"$t='{t}';"
        "Start-Sleep -Milliseconds 800;"
        "for($i=0;$i -lt 240;$i++){"
        "  try{Remove-Item -LiteralPath $t -Recurse -Force -ErrorAction Stop; break}catch{Start-Sleep -Milliseconds 500}"
        "}" 
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
        creationflags=0x08000000,
    )


def _remove_tree(path: str) -> None:
    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    shutil.rmtree(path, onerror=_onerror)


def _delete_install_contents(install_dir: str) -> None:
    install_dir = os.path.abspath(install_dir)
    for name in os.listdir(install_dir):
        if name.lower() == "uninstall.exe":
            continue
        p = os.path.join(install_dir, name)
        try:
            if os.path.isdir(p):
                _remove_tree(p)
            else:
                try:
                    os.chmod(p, stat.S_IWRITE)
                except Exception:
                    pass
                try:
                    os.remove(p)
                except FileNotFoundError:
                    pass
        except Exception:
            pass


def _run_uninstall() -> int:
    try:
        root = ctk.CTk()
        root.withdraw()
    except Exception:
        root = None

    install_dir = _read_install_location()
    if not install_dir:
        guess = os.path.dirname(os.path.abspath(sys.argv[0]))
        install_dir = guess if os.path.isdir(guess) else ""

    if not install_dir or not os.path.isdir(install_dir):
        try:
            mb.showerror(APP_DISPLAY, "Не найдена папка установки для удаления.")
        except Exception:
            pass
        return 1

    if not mb.askyesno(APP_DISPLAY, f"Удалить {APP_DISPLAY}?\n\nПапка: {install_dir}"):
        return 0

    conflicts = _running_conflicts(install_dir)
    if conflicts:
        names = "\n".join(f"{c['name']}  PID {c['pid']}" for c in conflicts)
        mb.showerror(APP_DISPLAY, f"Закройте запущенные процессы из папки установки и повторите удаление:\n\n{names}")
        return 1

    try:
        desktop_dir = _get_desktop_dir()
        shortcut = os.path.join(desktop_dir, f"{APP_DISPLAY}.lnk")
        if os.path.isfile(shortcut):
            os.remove(shortcut)
    except Exception:
        pass

    _unregister_uninstall()
    try:
        _delete_install_contents(install_dir)
    except Exception:
        pass

    _schedule_delete_install_dir(install_dir)

    try:
        mb.showinfo(APP_DISPLAY, "Удаление запущено. Папка будет удалена через несколько секунд.")
    except Exception:
        pass
    return 0


# ── GUI ───────────────────────────────────────────────────────────────────────

class InstallerApp(ctk.CTk):
    BG       = ("#0D0D1A", "#0D0D1A")
    CARD     = ("#141428", "#141428")
    HEADER   = ("#0A0A1F", "#0A0A1F")
    ACCENT   = "#00BFFF"
    SUCCESS  = "#00E676"
    WARN     = "#FF9800"
    MUTED    = "#666680"

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title(f"{APP_DISPLAY} — Installer")
        self.geometry("600x650")
        self.resizable(False, False)
        self.configure(fg_color=self.BG)

        self._bundle      = _bundle_base()
        self._install_var = ctk.StringVar(value=os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP_NAME
        ))
        self._installing  = False

        self._build_ui()
        self.after(200, self._refresh_conflicts)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=self.HEADER, corner_radius=0, height=88)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(
            hdr, text="🛡  NetPrivacy Verification Tool",
            font=ctk.CTkFont(size=22, weight="bold"), text_color=self.ACCENT
        ).pack(pady=(16, 2))
        ctk.CTkLabel(
            hdr, text=f"Installer  v{APP_VERSION}  ·  {APP_PUBLISHER}",
            font=ctk.CTkFont(size=11), text_color=self.MUTED
        ).pack()

        # Body
        body = ctk.CTkScrollableFrame(self, fg_color=self.BG, scrollbar_button_color=self.CARD)
        body.pack(fill="both", expand=True, padx=12, pady=8)

        # — Install path —
        self._section(body, "📁  Папка установки")
        path_row = ctk.CTkFrame(body, fg_color="transparent")
        path_row.pack(fill="x", padx=4, pady=(0, 8))
        ctk.CTkEntry(
            path_row, textvariable=self._install_var,
            font=ctk.CTkFont(size=11), height=32
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(
            path_row, text="…", width=36, height=32,
            fg_color=self.CARD, hover_color="#22223A",
            command=self._browse
        ).pack(side="left")

        # — Conflict check —
        self._section(body, "🔍  Проверка конфликтующих процессов")
        self.conflict_card = ctk.CTkFrame(body, fg_color=self.CARD, corner_radius=8)
        self.conflict_card.pack(fill="x", padx=4, pady=(0, 10))
        self._conflict_status_lbl = ctk.CTkLabel(
            self.conflict_card, text="⟳  Проверяю...",
            font=ctk.CTkFont(size=11), text_color=self.MUTED
        )
        self._conflict_status_lbl.pack(pady=12)

        # — Install features —
        self._section(body, "✨  Что будет сделано")
        feat_card = ctk.CTkFrame(body, fg_color=self.CARD, corner_radius=8)
        feat_card.pack(fill="x", padx=4, pady=(0, 10))
        features = [
            ("🔀", f"xray.exe → {ENGINE_RENAMED}  (не конфликтует с V2RayN / Nekobox)"),
            ("🔒", f"Порты {PORT_RANGE[0]}–{PORT_RANGE[1]}  (не трогает 1080 / 10808)"),
            ("🚫", "Не изменяет системный прокси Windows"),
            ("🖥", "Ярлык на Рабочем столе"),
            ("📋", "Запись в реестр  (удаление через Панель управления)"),
        ]
        for icon, text in features:
            row = ctk.CTkFrame(feat_card, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(row, text=icon, width=22, font=ctk.CTkFont(size=13)).pack(side="left")
            ctk.CTkLabel(
                row, text=text, font=ctk.CTkFont(size=11), text_color="#BBBBD0"
            ).pack(side="left", padx=6)

        # — Progress —
        self._section(body, "📊  Прогресс")
        prog_card = ctk.CTkFrame(body, fg_color=self.CARD, corner_radius=8)
        prog_card.pack(fill="x", padx=4, pady=(0, 6))
        self.progress = ctk.CTkProgressBar(prog_card, mode="determinate", height=14)
        self.progress.pack(fill="x", padx=12, pady=(10, 4))
        self.progress.set(0)
        self._status_lbl = ctk.CTkLabel(
            prog_card, text="Ожидание...",
            font=ctk.CTkFont(size=10), text_color=self.MUTED
        )
        self._status_lbl.pack(pady=(0, 10))

        self._open_folder_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            prog_card,
            text="Открыть папку после установки",
            variable=self._open_folder_var,
            font=ctk.CTkFont(size=11),
            text_color="#BBBBD0",
            fg_color=self.ACCENT,
            hover_color="#2A2A40",
        ).pack(anchor="w", padx=12, pady=(0, 10))

        # Footer buttons
        foot = ctk.CTkFrame(self, fg_color=self.HEADER, corner_radius=0, height=56)
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)
        ctk.CTkButton(
            foot, text="Отмена", width=90, height=34,
            fg_color="#2A2A40", hover_color="#3A3A55",
            command=self.destroy
        ).pack(side="right", padx=(6, 12), pady=10)
        self.install_btn = ctk.CTkButton(
            foot, text="🚀  Установить", width=170, height=34,
            fg_color="#1A3A7A", hover_color="#2453B4",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._start_install
        )
        self.install_btn.pack(side="right", padx=6, pady=10)

    def _section(self, parent, title: str):
        ctk.CTkLabel(
            parent, text=title,
            font=ctk.CTkFont(size=12, weight="bold"), text_color=self.ACCENT,
            anchor="w"
        ).pack(fill="x", padx=4, pady=(10, 4))

    # ── Conflict check ────────────────────────────────────────────────────────

    def _refresh_conflicts(self):
        for w in self.conflict_card.winfo_children():
            w.destroy()
        conflicts = _running_conflicts(self._install_var.get())
        if not conflicts:
            ctk.CTkLabel(
                self.conflict_card,
                text="✅  Конфликтов не обнаружено — можно устанавливать",
                font=ctk.CTkFont(size=11), text_color=self.SUCCESS
            ).pack(pady=10)
            self.install_btn.configure(state="normal")
        else:
            names = "  |  ".join(f"{c['name']}  PID {c['pid']}" for c in conflicts)
            ctk.CTkLabel(
                self.conflict_card,
                text=f"⚠  Найдены процессы: {names}",
                font=ctk.CTkFont(size=11), text_color=self.WARN
            ).pack(padx=12, pady=(10, 2))
            ctk.CTkLabel(
                self.conflict_card,
                text=(
                    "Обнаружены запущенные процессы из папки установки.\n"
                    "Закройте их вручную, затем нажмите «Проверить снова».\n"
                    "Установщик НЕ завершает процессы автоматически."
                ),
                font=ctk.CTkFont(size=10), text_color=self.MUTED, justify="left"
            ).pack(padx=12, pady=(0, 6))
            ctk.CTkButton(
                self.conflict_card,
                text="🔄  Проверить снова", width=150, height=28,
                fg_color="#2A2A40", hover_color="#3A3A55",
                command=self._refresh_conflicts
            ).pack(pady=(0, 10))
            self.install_btn.configure(state="disabled")

    # ── Install logic ─────────────────────────────────────────────────────────

    def _browse(self):
        path = fd.askdirectory(title="Выберите папку установки", initialdir=self._install_var.get())
        if path:
            self._install_var.set(path)

    def _set_status(self, text: str, progress: float | None = None):
        self._status_lbl.configure(text=text)
        if progress is not None:
            self.progress.set(max(0.0, min(1.0, progress)))
        self.update_idletasks()

    def _start_install(self):
        if self._installing:
            return
        self._installing = True
        self.install_btn.configure(state="disabled", text="⏳  Установка...")
        threading.Thread(target=self._do_install, daemon=True).start()

    def _do_install(self):
        try:
            install_dir = self._install_var.get().strip()
            bundle      = self._bundle

            # 1 · Create install dir
            self.after(0, self._set_status, "Создание папки установки...", 0.05)
            os.makedirs(install_dir, exist_ok=True)

            # 2 · Copy main EXE
            self.after(0, self._set_status, "Копирование основного EXE...", 0.15)
            for src_rel in ("main_dist/main.exe", "dist/main.exe", "main.exe"):
                src_exe = os.path.join(bundle, src_rel)
                if os.path.isfile(src_exe):
                    shutil.copy2(src_exe, os.path.join(install_dir, APP_EXE_NAME))
                    break

            # 3 · Copy resource directories
            dir_map = [
                ("app/bin",    "core/bin"),
                ("app/data",   "data"),
                ("app/assets", "assets"),
            ]
            for i, (src_rel, dst_rel) in enumerate(dir_map):
                src = os.path.join(bundle, src_rel)
                dst = os.path.join(install_dir, dst_rel)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                progress = 0.20 + (i + 1) / len(dir_map) * 0.35
                self.after(0, self._set_status, f"Копирование {dst_rel}/...", progress)

            # 4 · Ensure renamed core exists
            self.after(0, self._set_status, f"Переименование {ENGINE_ORIGINAL} → {ENGINE_RENAMED}...", 0.60)
            xray_path   = os.path.join(install_dir, "core", "bin", ENGINE_ORIGINAL)
            engine_path = os.path.join(install_dir, "core", "bin", ENGINE_RENAMED)
            if os.path.isfile(xray_path):
                if not os.path.isfile(engine_path):
                    shutil.copy2(xray_path, engine_path)

            # 5 · Write port config (avoids 1080/10808)
            self.after(0, self._set_status, "Выбор свободного порта...", 0.68)
            free_port  = _find_free_port()
            config_dir = os.path.join(install_dir, "data")
            os.makedirs(config_dir, exist_ok=True)
            with open(os.path.join(config_dir, "npvt_config.txt"), "w", encoding="utf-8") as f:
                f.write(f"preferred_port={free_port}\n")
                f.write(f"engine_name={ENGINE_RENAMED}\n")

            # 6 · Desktop shortcut
            self.after(0, self._set_status, "Создание ярлыка на рабочем столе...", 0.78)
            target_exe  = os.path.join(install_dir, APP_EXE_NAME)
            icon_path   = os.path.join(install_dir, "assets", "icon.ico")
            desktop_dir = _get_desktop_dir()
            shortcut    = os.path.join(desktop_dir, f"{APP_DISPLAY}.lnk")
            _create_shortcut(target_exe, shortcut, icon_path, APP_DISPLAY)

            # 7 · Copy uninstaller
            self.after(0, self._set_status, "Создание деинсталлятора...", 0.88)
            uninstall_exe = os.path.join(install_dir, "uninstall.exe")
            try:
                self_exe = os.path.abspath(sys.executable if getattr(sys, "frozen", False) else sys.argv[0])
                if os.path.isfile(self_exe) and self_exe.lower().endswith(".exe"):
                    shutil.copy2(self_exe, uninstall_exe)
            except Exception:
                pass

            # 8 · Registry uninstall entry
            self.after(0, self._set_status, "Запись в реестр...", 0.92)
            _register_uninstall(install_dir, uninstall_exe, icon_path)

            self.after(0, self._set_status, "✅  Установка завершена!", 1.0)
            self.after(0, self._on_complete, install_dir, target_exe)

        except Exception as exc:
            self.after(0, self._on_error, str(exc))

    def _on_complete(self, install_dir: str, exe_path: str):
        try:
            if getattr(self, "_open_folder_var", None) and self._open_folder_var.get():
                subprocess.Popen(["explorer", install_dir], creationflags=0x08000000)
        except Exception:
            pass
        self.install_btn.configure(
            state="normal",
            text="🚀  Запустить программу",
            fg_color="#006830",
            hover_color="#00A040",
            command=lambda: [subprocess.Popen([exe_path]), self.destroy()],
        )

    def _on_error(self, error: str):
        self._installing = False
        self._set_status(f"❌  Ошибка: {error}")
        self.install_btn.configure(
            state="normal",
            text="🔁  Повторить",
            fg_color="#6B1A1A",
            hover_color="#9B2A2A",
            command=self._start_install,
        )


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    args = [a.lower() for a in sys.argv[1:]]
    wants_uninstall = any(a in {"/uninstall", "--uninstall", "-uninstall"} for a in args)
    wants_install = any(a in {"/install", "--install", "-install"} for a in args)

    exe_name = os.path.basename(sys.argv[0]).lower()
    is_uninstaller_exe = exe_name == "uninstall.exe"

    if wants_uninstall or (is_uninstaller_exe and not wants_install):
        raise SystemExit(_run_uninstall())
    app = InstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()

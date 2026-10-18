#!/usr/bin/env python3
"""Apple Music ALAC Downloader - GUI

Requires: Python 3.7+, customtkinter and WSL2 (wrapper + downloader)
"""

import os
import re
import sys
import json
import time
import queue
import atexit
import tempfile
import threading
import subprocess
import ctypes
import webbrowser
from datetime import datetime
import customtkinter as ctk
from PIL import Image, ImageDraw


# ---- font cache -----------------------------------------------------------
# Every widget used to build its own CTkFont, and each one allocates a Tk font.
# The UI asks for the same handful of size/weight pairs ~69 times, so cache
# them by constructor arguments: startup drops from ~1.8s to ~0.4s. Fonts are
# shared resources in Tk and nothing here mutates one after creation.
_CTkFont_orig = ctk.CTkFont
_ctkfont_cache = {}


def _cached_ctkfont(*args, **kwargs):
    key = (args, tuple(sorted(kwargs.items())))
    font = _ctkfont_cache.get(key)
    if font is None:
        font = _CTkFont_orig(*args, **kwargs)
        _ctkfont_cache[key] = font
    return font


ctk.CTkFont = _cached_ctkfont

from common import (
    SCRIPT_DIR, DATA_DIR, DOWNLOAD_DIR, CONFIG_FILE,
    APP_DATA_DIR, WRAPPER_HOST, DECRYPT_PORT, M3U8_PORT, ACCOUNT_PORT, WSL_DISTRO,
    get_config_path, load_config_content, get_download_folder, get_save_folder,
    find_tool, get_downloader_exe, downloader_env,
    prepare_run_config, cleanup_run_config, build_downloader_command,
    find_media_user_token, validate_media_user_token, save_media_user_token,
    wrapper_running, wrapper_status, wrapper_service_state, wsl_diagnose,
    wrapper_health_after_run, port_open, kill_downloader,
    start_wrapper_service, restart_wrapper_service, stop_wrapper,
    shutdown_wsl, shutdown_wsl_detached, shutdown_wsl_on_exit_enabled,
    login_cached,
    wrapper_login as _common_wrapper_login,
    _SI, _CF,
)

WRAPPER_ENDPOINT = f"{WRAPPER_HOST}:{DECRYPT_PORT}/{M3U8_PORT}/{ACCOUNT_PORT}"


FONT_FAMILY = "Microsoft YaHei"
MONO_FAMILY = "Consolas"
APP_ICON = os.path.join(DATA_DIR, "assets", "app_icon.ico")

if os.name == "nt":
    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                    ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]

LOG_DIR = os.path.join(APP_DATA_DIR, "log")


class SessionLogger:
    _MAX_HISTORY = 5000

    def __init__(self):
        self._history = []
        os.makedirs(LOG_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._path = os.path.join(LOG_DIR, f"{stamp}.log")
        self._file = open(self._path, "w", encoding="utf-8", buffering=1)
        atexit.register(self.close)

    def write(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self._history.append(line)
        if len(self._history) > self._MAX_HISTORY:
            self._history = self._history[-self._MAX_HISTORY:]
        try:
            self._file.write(line + "\n")
            self._file.flush()
        except Exception:
            pass

    def replay(self, widget):
        for line in self._history:
            widget.insert("end", line + "\n")

    def close(self):
        try:
            if self._file:
                self._file.close()
                self._file = None
        except Exception:
            pass


session_log = SessionLogger()

APPLE_LIGHT = {
    "primary": "#007AFF",
    "primary_hover": "#0062CC",
    "surface": "#F2F2F7",
    "card": "#FFFFFF",
    "background": "#F5F5F7",
    "border": "#E5E5EA",
    "text": "#1D1D1F",
    "text_secondary": "#86868B",
    "error": "#FF3B30",
    "success": "#34C759",
    "warning": "#FF9500",
    "divider": "#E5E5EA",
    "input_bg": "#F2F2F7",
}

I18N = {
    "zh": {
        "app_title": "Apple Music Downloader",
        "brand": "Apple Music",
        "product": "ALAC Downloader",
        "checking": "正在检测环境...",
        "retry": "重试",
        "start_service": "启动服务",
        "wrapper_not_ready": "wrapper 未就绪",
        "wrapper_hint": "wrapper 运行在 WSL2 发行版 {distro} 中，地址 {url}。\\n可点击「重试」或到「状态」页签重启服务。",
        "downloader_missing": "未找到 WSL 内的下载器 /opt/amdl-legacy/amdl",
        "sign_in": "登录",
        "tips_login": "登录一次即可缓存凭据，无需重复输入",
        "apple_id": "Apple ID",
        "password": "密码",
        "placeholder_email": "example@icloud.com",
        "placeholder_password": "输入密码",
        "placeholder_url": "粘贴 Apple Music 链接...",
        "download": "下载",
        "running_btn": "运行中...",
        "clear": "清除",
        "output": "输出",
        "wrapper": "Wrapper",
        "running_status": "运行中 | {ports}",
        "stopped": "已停止",
        "ready": "就绪",
        "output_to": "输出: {path}",
        "tab_download": "下载",
        "tab_status": "状态",
        "tab_config": "配置",
        "lang_switch": "English",
        "config_title": "配置文件",
        "reload": "重新加载",
        "save": "保存",
        "config_source": "来源: {path}",
        "config_not_found": "未找到配置文件",
        "config_saved": "已保存到: {path}",
        "config_save_failed": "保存失败: {error}",
        "get_token": "获取 Token",
        "token_searching": "正在查找 media-user-token…",
        "token_found": "已自动获取并保存（来源: {source}，{detail}）",
        "token_not_found": "未能自动获取，请按提示手动复制",
        "token_dialog_title": "获取 media-user-token",
        "token_howto": "这个 token 只能从浏览器读取：\n1. 浏览器登录 https://music.apple.com\n2. 按 F12 打开开发者工具\n3. Application（应用）→ Storage → Cookies → https://music.apple.com\n4. 找到名为 media-user-token 的条目，复制它的 Value（整串）\n5. 粘贴到下面输入框，点击「校验并保存」\n\n（下面的文字可以选中复制）",
        "token_open_browser": "打开 music.apple.com",
        "token_copy_url": "复制网址",
        "token_copied": "网址已复制到剪贴板",
        "token_placeholder": "在此粘贴 media-user-token 的值…",
        "token_empty": "请先粘贴 token",
        "token_checking": "正在向 Apple 校验…",
        "token_verify_save": "校验并保存",
        "token_cancel": "取消",
        "token_saved": "已校验通过并保存（{detail}）",
        "status_title": "系统状态",
        "status_refresh": "刷新",
        "s_wrapper": "Wrapper 服务",
        "wrapper_endpoint": "接口地址",
        "wrapper_service": "WSL 服务状态",
        "wrapper_storefront": "账号区域",
        "s_login": "登录",
        "s_paths": "路径",
        "wrapper_container": "运行状态",
        "wrapper_ports": "监听端口",
        "login_cached": "凭据缓存",
        "config_path_label": "配置文件",
        "log_path_label": "日志目录",
        "downloader_path_label": "下载器",
        "not_installed": "未安装",
        "running": "运行中",
        "not_running": "未运行",
        "not_built": "未构建",
        "logged_in": "已登录",
        "not_logged_in": "未登录",
        "checking_status": "检测中...",
        "format_label": "格式:",
        "mode_album": "专辑",
        "mode_song": "单曲",
        "mode_playlist": "播放列表",
        "mode_atmos": "杜比全景声",
        "mode_aac": "AAC",
        "mode_select": "交互选择",
        "mode_debug": "调试 / 查看质量",
        "mode_search": "搜索",
        "mode_artist": "歌手全部专辑",
        "search_type": "搜索类型:",
        "wrapper_restart": "重启 Wrapper",
        "wrapper_restarting": "重启中...",
        "tab_convert": "转换",
        "convert_title": "FLAC 转换",
        "convert_btn": "开始转换",
        "convert_select_dir": "选择目录",
        "convert_source_dir": "源目录: {path}",
        "convert_scanning": "正在扫描文件...",
        "convert_found": "找到 {count} 个 .m4a 文件",
        "convert_converting": "正在转换: {file}",
        "convert_done": "转换完成: {count} 个文件",
        "convert_failed": "失败: {file}",
        "convert_nothing": "未找到可转换的文件",
        "convert_complete": "转换完毕，共处理 {total} 个文件",
        "convert_skip_exists": "已存在，跳过: {file}",
        "convert_running": "转换中...",
        "tab_rename": "重命名",
        "rename_title": "音频重命名",
        "rename_btn": "执行重命名",
        "rename_select_dir": "选择目录",
        "rename_format_label": "格式:",
        "rename_source_dir": "源目录: {path}",
        "rename_scanning": "正在扫描文件...",
        "rename_found": "找到 {count} 个可重命名文件",
        "rename_nothing": "未找到 .flac / .wav 文件",
        "rename_renaming": "重命名: {old} -> {new}",
        "rename_done": "重命名完成: {count} 个文件",
        "rename_failed": "失败: {file}",
        "rename_complete": "重命名完毕，共处理 {total} 个文件",
        "rename_no_tag": "跳过(缺少标签): {file}",
        "rename_no_tool": "未找到 ffprobe，无法读取标签（请将 ffprobe.exe 放入 assets 目录或加入 PATH）",
        "rename_tpl_track": "编号. 音乐名",
        "rename_tpl_artist": "歌手 - 音乐名",
    },
    "en": {
        "app_title": "Apple Music Downloader",
        "brand": "Apple Music",
        "product": "ALAC Downloader",
        "checking": "Checking environment...",
        "retry": "Retry",
        "start_service": "Start Service",
        "wrapper_not_ready": "wrapper is not ready",
        "wrapper_hint": "wrapper runs inside the WSL2 distro {distro} at {url}.\\nClick Retry, or restart the service from the Status tab.",
        "downloader_missing": "Downloader not found at /opt/amdl-legacy/amdl inside WSL",
        "sign_in": "Sign In",
        "tips_login": "Login once to cache credentials, no need to re-enter",
        "apple_id": "Apple ID",
        "password": "Password",
        "placeholder_email": "example@icloud.com",
        "placeholder_password": "Enter password",
        "placeholder_url": "Paste Apple Music link...",
        "download": "Download",
        "running_btn": "Running...",
        "clear": "Clear",
        "output": "Output",
        "wrapper": "Wrapper",
        "running_status": "Running | {ports}",
        "stopped": "Stopped",
        "ready": "Ready",
        "output_to": "Output: {path}",
        "tab_download": "Download",
        "tab_status": "Status",
        "tab_config": "Config",
        "lang_switch": "中文",
        "config_title": "Configuration",
        "reload": "Reload",
        "save": "Save",
        "config_source": "Source: {path}",
        "config_not_found": "Config file not found",
        "config_saved": "Saved to: {path}",
        "config_save_failed": "Save failed: {error}",
        "get_token": "Get Token",
        "token_searching": "Looking for media-user-token…",
        "token_found": "Auto-detected and saved (source: {source}, {detail})",
        "token_not_found": "Could not auto-detect - copy it manually",
        "token_dialog_title": "Get media-user-token",
        "token_howto": "This token can only be read from a browser:\n1. Sign in to https://music.apple.com\n2. Press F12 to open developer tools\n3. Application -> Storage -> Cookies -> https://music.apple.com\n4. Find the entry named media-user-token and copy its Value\n5. Paste it below and click Verify & Save\n\n(the text below is selectable)",
        "token_open_browser": "Open music.apple.com",
        "token_copy_url": "Copy URL",
        "token_copied": "URL copied to clipboard",
        "token_placeholder": "Paste the media-user-token value here…",
        "token_empty": "Paste a token first",
        "token_checking": "Verifying with Apple…",
        "token_verify_save": "Verify & Save",
        "token_cancel": "Cancel",
        "token_saved": "Verified and saved ({detail})",
        "status_title": "System Status",
        "status_refresh": "Refresh",
        "s_wrapper": "Wrapper Service",
        "wrapper_endpoint": "Endpoint",
        "wrapper_service": "WSL Service",
        "wrapper_storefront": "Storefront",
        "s_login": "Login",
        "s_paths": "Paths",
        "wrapper_container": "Status",
        "wrapper_ports": "Listening Ports",
        "login_cached": "Cached Credentials",
        "config_path_label": "Config File",
        "log_path_label": "Log Directory",
        "downloader_path_label": "Downloader",
        "not_installed": "Not Installed",
        "running": "Running",
        "not_running": "Not Running",
        "not_built": "Not Built",
        "logged_in": "Logged In",
        "not_logged_in": "Not Logged In",
        "checking_status": "Checking...",
        "format_label": "Format:",
        "mode_album": "Album",
        "mode_song": "Song",
        "mode_playlist": "Playlist",
        "mode_atmos": "Dolby Atmos",
        "mode_aac": "AAC",
        "mode_select": "Interactive Select",
        "mode_debug": "Debug / View Quality",
        "mode_search": "Search",
        "mode_artist": "All Artist Albums",
        "search_type": "Search type:",
        "wrapper_restart": "Restart Wrapper",
        "wrapper_restarting": "Restarting...",
        "tab_convert": "Convert",
        "convert_title": "FLAC Convert",
        "convert_btn": "Start Convert",
        "convert_select_dir": "Select Folder",
        "convert_source_dir": "Source: {path}",
        "convert_scanning": "Scanning files...",
        "convert_found": "Found {count} .m4a files",
        "convert_converting": "Converting: {file}",
        "convert_done": "Converted: {count} files",
        "convert_failed": "Failed: {file}",
        "convert_nothing": "No convertible files found",
        "convert_complete": "Conversion complete, total {total} files",
        "convert_skip_exists": "Already exists, skip: {file}",
        "convert_running": "Converting...",
        "tab_rename": "Rename",
        "rename_title": "Rename Audio",
        "rename_btn": "Rename",
        "rename_select_dir": "Select Dir",
        "rename_format_label": "Format:",
        "rename_source_dir": "Source: {path}",
        "rename_scanning": "Scanning files...",
        "rename_found": "Found {count} renamable files",
        "rename_nothing": "No .flac / .wav files found",
        "rename_renaming": "Rename: {old} -> {new}",
        "rename_done": "Renamed: {count} files",
        "rename_failed": "Failed: {file}",
        "rename_complete": "Rename complete, total {total} files",
        "rename_no_tag": "Skip (missing tag): {file}",
        "rename_no_tool": "ffprobe not found, cannot read tags (put ffprobe.exe in assets/ or add it to PATH)",
        "rename_tpl_track": "TrackNumber. SongName",
        "rename_tpl_artist": "Artist - SongName",
    },
}

DEFAULT_LANG = "zh"


def wrapper_login(username, password, log_callback=None, twofa_callback=None):
    return _common_wrapper_login(username, password, log_callback=log_callback, twofa_callback=twofa_callback)


def do_start_wrapper(log_callback=None):
    if wrapper_running():
        return True, f"wrapper already running ({WRAPPER_ENDPOINT})"
    return start_wrapper_service(log_callback=log_callback)


def _make_close(size=16, color="#86868B"):
    """Draw an X mark icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m = 4
    draw.line([(m, m), (size - m, size - m)], fill=color, width=2, joint="curve")
    draw.line([(size - m, m), (m, size - m)], fill=color, width=2, joint="curve")
    return ctk.CTkImage(img, size=(size, size))


def _make_folder(size=16, color="#86868B"):
    """Draw a folder icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    tab_w, tab_h = size // 3, size // 5
    draw.rectangle([2, tab_h, 2 + tab_w, tab_h + 2], fill=color)
    draw.rectangle([2, tab_h + 2, size - 2, size - 2], fill=color)
    return ctk.CTkImage(img, size=(size, size))


_ILLEGAL_FS_CHARS = '<>:"/\\|?*'


def _sanitize_filename(base):
    """Strip characters Windows rejects in filenames; keep the name non-empty."""
    cleaned = "".join("_" if ch in _ILLEGAL_FS_CHARS or ord(ch) < 32 else ch
                      for ch in base)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(". ")
    return cleaned or "untitled"


# =====================================================================
# GUI APPLICATION
# =====================================================================

class AppleMusicApp(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.colors = APPLE_LIGHT
        self.configure(fg_color=self.colors["background"])
        self.title("Apple Music Downloader")
        self.geometry("880x660")
        self.minsize(640, 480)

        if getattr(sys, 'frozen', False):
            try:
                self.iconbitmap(sys.executable)
            except Exception:
                pass
        elif os.path.isfile(APP_ICON):
            try:
                self.iconbitmap(APP_ICON)
            except Exception:
                pass

        self.lang = DEFAULT_LANG

        self.wrapper_ready = False
        self.setup_done = False

        self.container = ctk.CTkFrame(self, fg_color=self.colors["background"])
        self.container.pack(fill="both", expand=True)

        self.frames = {}
        self._frame_classes = {
            "SetupPage": SetupPage,
            "LoginPage": LoginPage,
            "TabbedContainer": TabbedContainer,
        }
        self.show_frame("SetupPage")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        get_config_path()

        self._make_layered_window()
        self._center_window()

    def _center_window(self):
        if os.name != "nt":
            self.update_idletasks()
            w = self.winfo_width()
            h = self.winfo_height()
            x = max(0, (self.winfo_screenwidth() - w) // 2)
            y = max(0, (self.winfo_screenheight() - h) // 2)
            self.geometry(f"+{x}+{y}")
            return
        try:
            self.update_idletasks()
            user32 = ctypes.windll.user32
            hwnd = user32.GetAncestor(self.winfo_id(), 2)  # GA_ROOT
            rect = _RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            user32.GetMonitorInfoW(monitor, ctypes.byref(mi))
            wk = mi.rcWork
            x = wk.left + max(0, (wk.right - wk.left - w) // 2)
            y = wk.top + max(0, (wk.bottom - wk.top - h) // 2)
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            user32.SetWindowPos(hwnd, 0, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER)
        except Exception:
            pass

    def _make_layered_window(self):
        """Make window WS_EX_LAYERED so DWM composites it, skipping GDI WM_ERASEBKGND."""
        if os.name != 'nt':
            return
        try:
            hwnd = self.winfo_id()
            if not hwnd:
                return
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            LWA_ALPHA = 0x00000002
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
            user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
        except Exception:
            pass

    def t(self, key, **fmt):
        value = I18N.get(self.lang, {}).get(key, key)
        if fmt:
            value = value.format(**fmt)
        return value

    def set_language(self, lang):
        if lang not in I18N:
            return
        self.lang = lang
        self.title(self.t("app_title"))
        for frame in self.frames.values():
            if hasattr(frame, "refresh_language"):
                frame.refresh_language()

    def _on_close(self):
        # Destroy the window first so closing feels instant, then hand the WSL
        # shutdown to a detached process. Doing it inline used to block the exit
        # for several seconds (systemctl stop + wsl --shutdown).
        session_log.close()
        self.destroy()
        try:
            if shutdown_wsl_on_exit_enabled():
                if not shutdown_wsl_detached():
                    threading.Thread(target=shutdown_wsl, daemon=True).start()
            else:
                threading.Thread(target=stop_wrapper, daemon=True).start()
        except Exception:
            pass

    def show_frame(self, name):
        # Pages are built on first use: constructing every page up front (the
        # download/config/status/convert/rename tree is several hundred CTk
        # widgets) made the window take seconds to appear.
        frame = self.frames.get(name)
        if frame is None:
            frame = self._frame_classes[name](self.container, self)
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.frames[name] = frame
        frame.tkraise()
        if hasattr(frame, "on_show"):
            frame.on_show()



class AppPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=app.colors["background"])
        self.app = app
        self._i18n_refs = []

    def c(self, key):
        return self.app.colors.get(key, "#000000")

    def t(self, key, **fmt):
        return self.app.t(key, **fmt)

    def _reg(self, widget, key, attr="text"):
        self._i18n_refs.append((widget, key, attr))

    def refresh_language(self):
        for widget, key, attr in self._i18n_refs:
            try:
                value = self.t(key)
                if attr == "text":
                    widget.configure(text=value)
                elif attr == "placeholder":
                    widget.configure(placeholder_text=value)
            except Exception:
                pass

    def _app_bind(self, callback):
        """Bind a global click handler on the root window, returns bind id."""
        return self.winfo_toplevel().bind("<Button-1>", callback, add="+")

    def _app_unbind(self, bind_id):
        """Remove a global click handler previously added via _app_bind."""
        if bind_id:
            try:
                self.winfo_toplevel().unbind("<Button-1>", bind_id)
            except Exception:
                pass


class SetupPage(AppPage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.log_text = None
        self.progress = None
        self.status_label = None
        self._mirror_profile = "cn"
        self.build_ui()

    def build_ui(self):
        c = self.app.colors
        f = FONT_FAMILY
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(expand=True, fill="both", padx=40, pady=40)

        lbl = ctk.CTkLabel(container, text=self.t("brand"),
                           font=ctk.CTkFont(family=f, size=32, weight="bold"),
                           text_color=c["text"]); lbl.pack(pady=(40, 0)); self._reg(lbl, "brand")
        lbl = ctk.CTkLabel(container, text=self.t("product"),
                           font=ctk.CTkFont(family=f, size=20),
                           text_color=c["primary"]); lbl.pack(); self._reg(lbl, "product")
        self._checking_label = ctk.CTkLabel(container, text=self.t("checking"),
                                            font=ctk.CTkFont(family=f, size=14),
                                            text_color=c["text_secondary"])
        self._checking_label.pack(pady=(16, 8)); self._reg(self._checking_label, "checking")

        self.progress = ctk.CTkProgressBar(container, width=400, height=6,
                                           progress_color=c["primary"],
                                           fg_color=c["divider"])
        self.progress.pack(pady=8)
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(container, text="",
                                         font=ctk.CTkFont(family=f, size=12),
                                         text_color=c["text_secondary"])
        self.status_label.pack()

        self.log_text = ctk.CTkTextbox(container, width=500, height=200,
                                       fg_color=c["input_bg"],
                                       text_color=c["text"],
                                       border_color=c["border"],
                                       border_width=1,
                                       corner_radius=10,
                                       font=ctk.CTkFont(family=MONO_FAMILY, size=12))
        self.log_text.pack(pady=16, fill="both", expand=True)

        self.retry_btn = ctk.CTkButton(container, text=self.t("retry"),
                                         fg_color=c["primary"],
                                         hover_color=c["primary_hover"],
                                         corner_radius=10,
                                         font=ctk.CTkFont(family=f, size=13),
                                         command=self.start_setup)
        self.retry_btn.pack(pady=8)
        self.retry_btn.pack_forget()
        self._reg(self.retry_btn, "retry")

    def on_show(self):
        if not self.app.setup_done:
            self.start_setup()

    def _ui(self, fn, *args):
        """Run a widget update on the Tk main thread.

        The setup steps run on a worker thread, and Tk is not thread-safe:
        touching widgets from there raised "main thread is not in main loop"
        and made the window stutter.
        """
        try:
            if threading.current_thread() is threading.main_thread():
                fn(*args)
            else:
                self.after(0, lambda: fn(*args))
        except Exception:
            pass

    def log(self, msg):
        session_log.write(msg)
        self._ui(self._append_log, msg)

    def _append_log(self, msg):
        try:
            if self.log_text and self.log_text.winfo_exists():
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
        except Exception:
            pass

    def set_status(self, msg):
        self._ui(self._apply_status, msg)

    def _apply_status(self, msg):
        try:
            if self.status_label and self.status_label.winfo_exists():
                self.status_label.configure(text=msg)
        except Exception:
            pass

    def set_progress(self, val):
        self._ui(self._apply_progress, val)

    def _apply_progress(self, val):
        try:
            if self.progress and self.progress.winfo_exists():
                self.progress.set(val)
        except Exception:
            pass

    def start_setup(self):
        self.log_text.delete("1.0", "end")
        self.set_progress(0)
        self.retry_btn.pack_forget()

        exe = get_downloader_exe()
        if not exe:
            msg = self.t("downloader_missing")
            self.log(f"[ERROR] {msg}")
            self.set_status(msg)
            self.retry_btn.pack(pady=8)
            return

        self.log(f"[OK] Downloader: {exe}")
        self.set_progress(0.25)
        threading.Thread(target=self._run_setup_steps, daemon=True).start()

    def _run_setup_steps(self):
        steps = [
            ("Check downloader", self._check_downloader),
            ("Check WSL distro", self._check_wsl),
            ("Start wrapper", self._start_wrapper),
        ]
        total = len(steps)
        for i, (name, fn) in enumerate(steps):
            self.set_status(f"[{i+1}/{total}] {name}...")
            self.log(f"--- {name} ---")
            try:
                ok, msg = fn()
                self.log(msg)
                if not ok:
                    self.set_status(f"FAILED: {name}")
                    self.after(0, lambda: self.retry_btn.pack(pady=8))
                    return
            except Exception as e:
                self.log(f"Error: {e}")
                self.set_status(f"ERROR: {name}")
                self.after(0, lambda: self.retry_btn.pack(pady=8))
                return
            self.set_progress(0.25 + 0.25 * (i + 1))

        self.app.setup_done = True
        self.set_status("All checks passed")
        self.log("Environment ready. Launching...")
        self.set_progress(1.0)
        self.after(600, self.go_next)

    def _check_downloader(self):
        exe = get_downloader_exe()
        if not exe:
            return False, self.t("downloader_missing")
        return True, f"Downloader ready: {exe}"

    def _check_wsl(self):
        problem = wsl_diagnose()
        if problem:
            return False, f"WSL unavailable: {problem}"
        state = wrapper_service_state()
        if state == "unknown":
            return False, f"WSL distro '{WSL_DISTRO}' exists but systemd did not answer"
        return True, f"WSL distro '{WSL_DISTRO}' reachable (service: {state})"

    def _start_wrapper(self):
        ok, _data, _err = wrapper_status(timeout=2)
        if ok:
            self.app.wrapper_ready = True
            return True, f"wrapper already running ({WRAPPER_ENDPOINT})"
        if not login_cached():
            # Not a failure: the wrapper cannot open its ports before an Apple
            # Music sign-in. Treating this as an error used to abort setup
            # before the login page was ever shown - a deadlock, since signing
            # in is the only way to make the wrapper start.
            return True, "Apple Music sign-in required - continuing to the login page"
        ok, msg = start_wrapper_service(log_callback=self.log)
        if not ok:
            return False, msg
        self.app.wrapper_ready = True
        return True, msg

    def go_next(self):
        session_log._history.clear()
        if not login_cached():
            self.app.show_frame("LoginPage")
        else:
            self.app.show_frame("TabbedContainer")


class LoginPage(AppPage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.log_text = None
        self._log_queue = queue.Queue()
        self._flush_timer = None
        self.build_ui()

    def build_ui(self):
        c = self.app.colors
        f = FONT_FAMILY
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(expand=True, fill="both", padx=80, pady=30)

        lang_row = ctk.CTkFrame(container, fg_color="transparent")
        lang_row.pack(fill="x", pady=(0, 6))
        lang_label_text = "中文" if self.app.lang == "zh" else "English"
        self._login_lang_btn = ctk.CTkButton(lang_row, text=lang_label_text, anchor="center",
                                             fg_color=c["input_bg"], hover_color=c["divider"],
                                             text_color=c["text"],
                                             font=ctk.CTkFont(family=f, size=11),
                                             corner_radius=6, height=28, width=60,
                                             command=self._toggle_lang)
        self._login_lang_btn.pack(side="right")

        lbl = ctk.CTkLabel(container, text=self.t("sign_in"),
                           font=ctk.CTkFont(family=f, size=26, weight="bold"),
                            text_color=c["text"]); lbl.pack(pady=(20, 4)); self._reg(lbl, "sign_in")
        lbl = ctk.CTkLabel(container, text=self.t("tips_login"),
                            font=ctk.CTkFont(family=f, size=13),
                            text_color=c["text_secondary"]); lbl.pack(pady=(0, 12)); self._reg(lbl, "tips_login")

        field_frame1 = ctk.CTkFrame(container, fg_color="transparent")
        field_frame1.pack(fill="x", pady=(0, 14))
        lbl = ctk.CTkLabel(field_frame1, text=self.t("apple_id"),
                           font=ctk.CTkFont(family=f, size=14),
                           text_color=c["text_secondary"]); lbl.pack(anchor="w", pady=(0, 2)); self._reg(lbl, "apple_id")
        self.username_entry = ctk.CTkEntry(field_frame1, height=46,
                                           corner_radius=10,
                                           fg_color=c["input_bg"],
                                           text_color=c["text"],
                                           border_color=c["border"],
                                           font=ctk.CTkFont(family=f, size=14),
                                           placeholder_text=self.t("placeholder_email"))
        self.username_entry.pack(fill="x")
        self.username_entry.bind("<Return>", lambda e: self.do_login())
        self._reg(self.username_entry, "placeholder_email", "placeholder")

        field_frame2 = ctk.CTkFrame(container, fg_color="transparent")
        field_frame2.pack(fill="x", pady=(0, 10))
        lbl = ctk.CTkLabel(field_frame2, text=self.t("password"),
                           font=ctk.CTkFont(family=f, size=14),
                           text_color=c["text_secondary"]); lbl.pack(anchor="w", pady=(0, 2)); self._reg(lbl, "password")
        self.password_entry = ctk.CTkEntry(field_frame2, height=46,
                                           corner_radius=10,
                                           fg_color=c["input_bg"],
                                           text_color=c["text"],
                                           border_color=c["border"],
                                           show="\u2022",
                                           font=ctk.CTkFont(family=f, size=14),
                                           placeholder_text=self.t("placeholder_password"))
        self.password_entry.pack(fill="x")
        self.password_entry.bind("<Return>", lambda e: self.do_login())
        self._reg(self.password_entry, "placeholder_password", "placeholder")

        self.login_btn = ctk.CTkButton(container, text=self.t("sign_in"),
                                       width=340, height=42,
                                       fg_color=c["primary"],
                                       hover_color=c["primary_hover"],
                                       corner_radius=10,
                                       font=ctk.CTkFont(family=f, size=16, weight="bold"),
                                       command=self.do_login)
        self.login_btn.pack(pady=4)
        self._reg(self.login_btn, "sign_in")

        self.status_label = ctk.CTkLabel(container, text="",
                                          font=ctk.CTkFont(family=f, size=12),
                                          text_color=c["text_secondary"])
        self.status_label.pack(pady=4)

        self.progress = ctk.CTkProgressBar(container, width=340, height=4,
                                           progress_color=c["primary"],
                                           fg_color=c["divider"])
        self.progress.pack()
        self.progress.set(0)

        self.log_text = ctk.CTkTextbox(container, width=500, height=120,
                                       fg_color=c["input_bg"],
                                       text_color=c["text"],
                                       border_color=c["border"],
                                       border_width=1,
                                       corner_radius=10,
                                       font=ctk.CTkFont(family=MONO_FAMILY, size=11))
        self.log_text.pack(fill="both", expand=True, pady=(10, 0))

    def log(self, msg):
        session_log.write(msg)
        self._log_queue.put(msg)

    def _flush_log(self):
        messages = []
        while not self._log_queue.empty():
            try:
                messages.append(self._log_queue.get_nowait())
            except queue.Empty:
                break
        if messages and self.log_text and self.log_text.winfo_exists():
            self.log_text.configure(state="normal")
            for m in messages:
                self.log_text.insert("end", m + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self._flush_timer = self.after(100, self._flush_log)

    def on_show(self):
        self.status_label.configure(text="")
        self.progress.set(0)
        self.login_btn.configure(state="normal")
        if self.log_text:
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.configure(state="normal")
        if self._flush_timer:
            self.after_cancel(self._flush_timer)
        self._flush_timer = self.after(100, self._flush_log)

    def _toggle_lang(self):
        new_lang = "en" if self.app.lang == "zh" else "zh"
        self.app.set_language(new_lang)
        if hasattr(self, '_login_lang_btn') and self._login_lang_btn.winfo_exists():
            self._login_lang_btn.configure(text="中文" if new_lang == "zh" else "English")

    def do_login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        if not username or not password:
            self.status_label.configure(text="Enter Apple ID and password",
                                        text_color=self.c("error"))
            return
        self.login_btn.configure(state="disabled")
        self.status_label.configure(text="Starting login...", text_color=self.c("text_secondary"))
        self.progress.set(0.1)
        threading.Thread(target=self._login_thread, args=(username, password), daemon=True).start()

    def _login_thread(self, username, password):
        self.after(0, lambda: self.status_label.configure(text="Launching login container..."))
        self.after(0, lambda: self.progress.set(0.3))

        twofa_event = threading.Event()
        twofa_result = [None]

        def _twofa_callback():
            self.after(0, lambda: self._show_2fa_dialog(twofa_event, twofa_result))
            twofa_event.wait(timeout=300)
            return twofa_result[0]

        ok, msg = wrapper_login(username, password, log_callback=self.log, twofa_callback=_twofa_callback)
        self.after(0, lambda: self._login_done(ok, msg))

    def _show_2fa_dialog(self, event, result):
        from tkinter import simpledialog
        self.log("[.] 2FA required - check your Apple device")
        code = simpledialog.askstring(
            "Two-Factor Authentication",
            "Enter the verification code sent to your Apple device:",
            parent=self
        )
        if code:
            result[0] = code.strip()
        event.set()

    def _login_done(self, ok, msg):
        if ok:
            self.progress.set(0.7)
            self.status_label.configure(text="Starting wrapper...", text_color=self.c("text_secondary"))
            self.log("[OK] Login done, starting wrapper...")
            threading.Thread(target=self._post_login_start_wrapper, daemon=True).start()
        else:
            self.progress.set(1.0)
            self.status_label.configure(text=msg, text_color=self.c("error"))
            self.login_btn.configure(state="normal")

    def _post_login_start_wrapper(self):
        self.after(0, lambda: self.status_label.configure(text="Initializing wrapper container..."))
        ok2, msg2 = do_start_wrapper(log_callback=self.log)
        self.after(0, lambda: self._post_login_done(ok2))

    def _post_login_done(self, ok2):
        self.app.wrapper_ready = ok2
        self.progress.set(1.0)
        if self._flush_timer:
            self.after_cancel(self._flush_timer)
            self._flush_timer = None
        self.status_label.configure(
            text="Wrapper running" if ok2 else "Wrapper start failed",
            text_color=self.c("success") if ok2 else self.c("error")
        )
        session_log._history.clear()
        self.after(300, lambda: self.app.show_frame("TabbedContainer"))


MODE_SPECS = [
    ("album",    "mode_album",   ""),
    ("song",     "mode_song",    "--song {url}"),
    ("playlist", "mode_playlist",""),
    ("atmos",    "mode_atmos",   "--atmos {url}"),
    ("aac",      "mode_aac",     "--aac --aac-type {aac_type} {url}"),
    ("select",   "mode_select",  "--select {url}"),
    ("debug",    "mode_debug",   "--debug {url}"),
    ("search",   "mode_search",  "--search {search_type} {query}"),
    ("artist",   "mode_artist",  "--all-album {url}"),
]


class TabbedContainer(AppPage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.current_tab = "download"
        c = app.colors
        f = FONT_FAMILY

        self.sidebar = ctk.CTkFrame(self, fg_color=c["card"], width=140, corner_radius=0,
                                    border_color=c["divider"], border_width=1)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.tab_btns = {}
        sep = ctk.CTkFrame(self.sidebar, height=12, fg_color="transparent")
        sep.pack(fill="x")
        self._tab_keys = [("download", "tab_download"), ("status", "tab_status"), ("config", "tab_config"), ("convert", "tab_convert"), ("rename", "tab_rename")]
        for key, i18n_key in self._tab_keys:
            btn = ctk.CTkButton(self.sidebar, text=self.t(i18n_key), anchor="w",
                                fg_color="transparent", hover_color=c["input_bg"],
                                text_color=c["text"],
                                font=ctk.CTkFont(family=f, size=13),
                                corner_radius=6, height=34,
                                command=lambda k=key: self.show_tab(k))
            btn.pack(fill="x", padx=8, pady=(0, 2))
            self.tab_btns[key] = btn
            self._reg(btn, i18n_key)

        space = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        space.pack(side="bottom", fill="x", padx=8, pady=6)

        lang_label = "中文" if self.app.lang == "zh" else "English"
        self._lang_btn = ctk.CTkButton(space, text=lang_label, anchor="center",
                                       fg_color=c["input_bg"], hover_color=c["divider"],
                                       text_color=c["text"],
                                       font=ctk.CTkFont(family=f, size=11),
                                       corner_radius=6, height=28,
                                       command=self._toggle_lang)
        self._lang_btn.pack(fill="x")

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.pack(side="left", fill="both", expand=True)

        self.pages = {}
        self.main_page = MainPage(self.content, app)
        self.pages["download"] = self.main_page
        self.main_page.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.config_page = ConfigPage(self.content, app)
        self.pages["config"] = self.config_page
        self.config_page.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.status_page = StatusPage(self.content, app)
        self.pages["status"] = self.status_page
        self.status_page.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.convert_page = ConvertPage(self.content, app)
        self.pages["convert"] = self.convert_page
        self.convert_page.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.rename_page = RenamePage(self.content, app)
        self.pages["rename"] = self.rename_page
        self.rename_page.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.show_tab("download")

    def show_tab(self, key):
        self.current_tab = key
        c = self.app.colors
        for k, btn in self.tab_btns.items():
            if k == key:
                btn.configure(fg_color=c["primary"], text_color="white",
                              hover_color=c["primary_hover"])
            else:
                btn.configure(fg_color="transparent", text_color=c["text"],
                              hover_color=c["input_bg"])
        page = self.pages[key]
        page.tkraise()
        if hasattr(page, "on_show"):
            page.on_show()

    def on_show(self):
        if self.current_tab in self.pages:
            page = self.pages[self.current_tab]
            if hasattr(page, "on_show"):
                page.on_show()

    def _toggle_lang(self):
        new_lang = "en" if self.app.lang == "zh" else "zh"
        self.app.set_language(new_lang)
        self._lang_btn.configure(text="中文" if new_lang == "zh" else "English")

    def refresh_language(self):
        super().refresh_language()
        for key, i18n_key in self._tab_keys:
            if key in self.tab_btns:
                self.tab_btns[key].configure(text=self.t(i18n_key))
        for page in self.pages.values():
            if hasattr(page, "refresh_language"):
                page.refresh_language()


class MainPage(AppPage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._status_timer = None
        self._mode_var = None
        self._url_var = None
        self._extra_widgets = []
        self._last_progress = False
        self._log_queue = queue.Queue()
        self._flush_timer = None
        self._popup = None
        self._reposition_timer = None
        self._dl_proc = None
        self._downloading = False
        self._status_timer = None
        self._polling = False
        self.build_ui()

    def build_ui(self):
        c = self.app.colors
        f = FONT_FAMILY

        topbar = ctk.CTkFrame(self, fg_color=c["card"], height=44, corner_radius=0,
                              border_color=c["divider"], border_width=1)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        self._title_label = ctk.CTkLabel(topbar, text=self.t("app_title"),
                                         font=ctk.CTkFont(family=f, size=16, weight="bold"),
                                         text_color=c["text"])
        self._title_label.pack(side="left", padx=16, pady=11); self._reg(self._title_label, "app_title")

        right_frame = ctk.CTkFrame(topbar, fg_color="transparent")
        right_frame.pack(side="right", padx=6)

        self.wrapper_dot = ctk.CTkFrame(right_frame, width=10, height=10,
                                        corner_radius=5, fg_color=c["error"])
        self.wrapper_dot.pack(side="left", padx=(0, 4))
        self._wrapper_label = ctk.CTkLabel(right_frame, text=self.t("wrapper"),
                                           font=ctk.CTkFont(family=f, size=12),
                                           text_color=c["text_secondary"])
        self._wrapper_label.pack(side="left", padx=(0, 8)); self._reg(self._wrapper_label, "wrapper")

        body = ctk.CTkFrame(self, fg_color=c["background"], corner_radius=0)
        body.pack(fill="both", expand=True, padx=12, pady=(8, 0))

        card = ctk.CTkFrame(body, fg_color=c["card"], corner_radius=10,
                            border_color=c["border"], border_width=1)
        card.pack(fill="x", pady=(0, 0))

        card_inner = ctk.CTkFrame(card, fg_color="transparent")
        card_inner.pack(fill="x", padx=10, pady=10)

        ctrl_row = ctk.CTkFrame(card_inner, fg_color="transparent")
        ctrl_row.pack(fill="x")

        self._mode_var = ctk.StringVar(value="album")
        self._mode_entry = ctk.CTkEntry(ctrl_row, height=36, corner_radius=8,
                                        fg_color=c["input_bg"], text_color=c["text"],
                                        border_color=c["border"],
                                        font=ctk.CTkFont(family=f, size=13),
                                        width=150, justify="center")
        self._mode_entry.pack(side="left", padx=(0, 8))
        self._mode_entry.insert(0, self._mode_name("album"))
        self._mode_entry.configure(state="readonly")
        self._mode_entry.bind("<Button-1>", lambda e: self._show_mode_popup())

        self._url_var = ctk.StringVar()
        self._url_entry = ctk.CTkEntry(ctrl_row, height=36, corner_radius=8,
                                       fg_color=c["input_bg"], text_color=c["text"],
                                       border_color=c["border"],
                                       font=ctk.CTkFont(family=f, size=13),
                                       placeholder_text=self.t("placeholder_url"),
                                       textvariable=self._url_var)
        self._url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._url_entry.bind("<Return>", lambda e: self._start_download())
        self._url_entry.bind("<Button-3>", self._paste_url)
        self._reg(self._url_entry, "placeholder_url", "placeholder")

        self._close_img = _make_close(color=c["text_secondary"])
        self._clear_btn = ctk.CTkButton(ctrl_row, text="", width=32, height=36,
                                        corner_radius=8, image=self._close_img,
                                        fg_color=c["input_bg"], hover_color=c["divider"],
                                        command=self._clear_url)
        self._clear_btn.pack(side="left", padx=(0, 8))

        self._go_btn = ctk.CTkButton(ctrl_row, text=self.t("download"), width=96, height=36,
                                     corner_radius=8,
                                     fg_color=c["primary"], hover_color=c["primary_hover"],
                                     text_color="white",
                                     font=ctk.CTkFont(family=f, size=14, weight="bold"),
                                     command=self._start_download)
        self._go_btn.pack(side="right")
        self._reg(self._go_btn, "download")

        self._extra_row = ctk.CTkFrame(card_inner, fg_color="transparent")
        self._extra_row.pack(fill="x", pady=(6, 0))
        self._extra_row.pack_forget()

        self.console = ctk.CTkTextbox(body,
                                       fg_color=c["card"], text_color=c["text"],
                                       border_color=c["border"], border_width=1,
                                       corner_radius=10,
                                       font=ctk.CTkFont(family=MONO_FAMILY, size=12),
                                       state="disabled",
                                       wrap="none")
        self.console.pack(fill="both", expand=True, pady=(8, 0))

        footer = ctk.CTkFrame(body, fg_color="transparent")
        footer.pack(fill="x", pady=(2, 0))
        lbl = ctk.CTkLabel(footer, text=self.t("output"),
                           font=ctk.CTkFont(family=f, size=12, weight="bold"),
                           text_color=c["text"]); lbl.pack(side="left"); self._reg(lbl, "output")
        clear_footer_btn = ctk.CTkButton(footer, text=self.t("clear"), width=48, height=22,
                                          fg_color=c["card"], hover_color=c["divider"],
                                          text_color=c["text_secondary"], corner_radius=4,
                                          font=ctk.CTkFont(family=f, size=10),
                                          command=self._clear_console)
        clear_footer_btn.pack(side="right")
        self._reg(clear_footer_btn, "clear")

        self._scroll_btn = ctk.CTkButton(footer, text="▼", width=28, height=22,
                                          fg_color=c["card"], hover_color=c["divider"],
                                          text_color=c["text_secondary"], corner_radius=4,
                                          font=ctk.CTkFont(family=f, size=10),
                                          command=self._toggle_scroll)
        self._scroll_btn.pack(side="right", padx=(0, 4))

        self.status_bar = ctk.CTkFrame(self, fg_color=c["card"], height=26, corner_radius=0,
                                       border_color=c["divider"], border_width=1)
        self.status_bar.pack(fill="x", side="bottom")
        self.status_bar.pack_propagate(False)

        self._status_text = ctk.CTkLabel(self.status_bar, text=self.t("ready"),
                                         font=ctk.CTkFont(family=f, size=11),
                                         text_color=c["text_secondary"])
        self._status_text.pack(side="left", padx=10, pady=2); self._reg(self._status_text, "ready")

        self._output_path_label = ctk.CTkLabel(self.status_bar,
                                               text=self.t("output_to", path=get_download_folder()),
                                               font=ctk.CTkFont(family=f, size=10),
                                               text_color=c["text_secondary"])
        self._output_path_label.pack(side="right", padx=(0, 10), pady=2)

        self._open_folder_img = _make_folder(size=14, color=c["text_secondary"])
        self._open_folder_btn = ctk.CTkButton(self.status_bar, text="",
                                              width=24, height=22,
                                              corner_radius=4,
                                              image=self._open_folder_img,
                                              fg_color="transparent",
                                              hover_color=c["divider"],
                                              command=self._open_output_dir)
        self._open_folder_btn.pack(side="right", padx=(0, 8), pady=2)

    def _clear_url(self):
        self._url_var.set("")

    def _open_output_dir(self):
        os.startfile(get_download_folder())

    def _on_download_done(self):
        self._reset_download_state()
        self._clear_url()

    def _paste_url(self, event=None):
        try:
            text = self.clipboard_get()
            self._url_var.set(text)
        except Exception:
            pass

    def _clear_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        self._last_progress = False

    def _toggle_scroll(self):
        if self.console.yview()[1] >= 0.99:
            self.console.see("1.0")
            self._scroll_btn.configure(text="▲")
        else:
            self.console.see("end")
            self._scroll_btn.configure(text="▼")
        self._update_scroll_icon()

    def _update_scroll_icon(self):
        try:
            if self.console.yview()[1] >= 0.99:
                self._scroll_btn.configure(text="▲")
            else:
                self._scroll_btn.configure(text="▼")
        except Exception:
            pass

    def log(self, msg):
        self._log_queue.put(("log", msg))

    def log_replace(self, msg):
        self._log_queue.put(("replace", msg))

    _MAX_CONSOLE_LINES = 3000

    def _log_locked(self, msg):
        session_log.write(msg)
        if self._last_progress:
            self.console.insert("end", "\n")
            self._last_progress = False
        self.console.insert("end", msg + "\n")

    def _trim_console(self):
        try:
            end = int(float(self.console.index("end-1c")))
            if end > self._MAX_CONSOLE_LINES:
                self.console.delete("1.0", f"{end - self._MAX_CONSOLE_LINES}.0")
        except Exception:
            pass

    def _log_replace_locked(self, msg):
        prefix = msg.split()[0] if msg else ""
        if self._last_progress:
            last_pos = self.console.index("end-2c linestart")
            last_line = self.console.get(last_pos, "end-1c").strip()
            last_prefix = last_line.split()[0] if last_line else ""
            if last_prefix != prefix:
                self.console.insert("end", "\n")
            else:
                self.console.delete(last_pos, "end-1c")
        else:
            self._last_progress = True
        self.console.insert("end", msg)

    def _flush_log(self):
        """Drain log queue in batch every 100ms."""
        messages = []
        while not self._log_queue.empty():
            try:
                messages.append(self._log_queue.get_nowait())
            except queue.Empty:
                break
        if messages:
            at_bottom = self.console.yview()[1] >= 0.99
            self.console.configure(state="normal")
            for kind, msg in messages:
                if kind == "replace":
                    self._log_replace_locked(msg)
                else:
                    self._log_locked(msg)
            self._trim_console()
            self.console.configure(state="disabled")
            if at_bottom:
                self.console.see("end")
            self._update_scroll_icon()
        self._flush_timer = self.after(100, self._flush_log)

    def on_show(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        session_log.replay(self.console)
        self.console.configure(state="disabled")
        # Probe off the UI thread so switching tabs never stalls.
        if not self._polling:
            self._polling = True
            threading.Thread(target=self._probe_status, daemon=True).start()
        if self._status_timer:
            self.after_cancel(self._status_timer)
        self._status_timer = self.after(3000, self._poll_status)
        if self._flush_timer:
            self.after_cancel(self._flush_timer)
        self._flush_timer = self.after(100, self._flush_log)
        try:
            self.after(100, self._url_entry.focus)
        except Exception:
            pass

    def refresh_language(self):
        super().refresh_language()
        self._output_path_label.configure(text=self.t("output_to", path=get_download_folder()))
        current_key = self._mode_var.get()
        name = self._mode_name(current_key)
        self._mode_entry.configure(state="normal")
        self._mode_entry.delete(0, "end")
        self._mode_entry.insert(0, name)
        self._mode_entry.configure(state="readonly")

    def _poll_status(self):
        # Probe on a worker thread: wrapper_running() opens TCP connections with
        # retries, and running that on the UI thread froze the window for
        # seconds at a time - very noticeable while typing.
        if not self._polling:
            self._polling = True
            threading.Thread(target=self._probe_status, daemon=True).start()
        self._status_timer = self.after(3000, self._poll_status)

    def _probe_status(self):
        running = False
        try:
            running = port_open(port=ACCOUNT_PORT, timeout=0.4, attempts=1)
            if not running:
                # WSL's localhost relay drops the occasional SYN, so a failed
                # TCP probe alone is not proof. The HTTP endpoint is the more
                # truthful check and this runs off the UI thread anyway.
                running = wrapper_status(timeout=1.2)[0]
        except Exception:
            running = False
        finally:
            self._polling = False
        try:
            self.after(0, lambda: self._update_status(running))
        except Exception:
            pass

    def _update_status(self, running=None):
        try:
            if running is None:
                running = port_open(port=ACCOUNT_PORT, timeout=0.4, attempts=1)
            c = self.app.colors
            if hasattr(self, 'wrapper_dot') and self.wrapper_dot.winfo_exists():
                dot_color = c["success"] if running else c["error"]
                self.wrapper_dot.configure(fg_color=dot_color)
                ports = WRAPPER_ENDPOINT
                status_text = self.t("running_status", ports=ports) if running else self.t("stopped")
                self._status_text.configure(text=status_text)
        except Exception:
            pass

    def _mode_name(self, key):
        for spec in MODE_SPECS:
            if spec[0] == key:
                return self.t(spec[1])
        return key

    def _show_mode_popup(self):
        if self._popup and self._popup.winfo_exists():
            self._popup.destroy()
        self._popup = None
        self._app_unbind(getattr(self, '_popup_bind_id', None))
        self._popup_bind_id = None
        if self._reposition_timer is not None:
            self.after_cancel(self._reposition_timer)
            self._reposition_timer = None

        c = self.app.colors
        f = FONT_FAMILY

        popup = ctk.CTkFrame(self, fg_color=c["surface"],
                             border_color=c["border"], border_width=1,
                             corner_radius=6)
        self._popup = popup
        self._popup_bind_id = None

        def select(key, name):
            self._mode_var.set(key)
            self._mode_entry.configure(state="normal")
            self._mode_entry.delete(0, "end")
            self._mode_entry.insert(0, name)
            self._mode_entry.configure(state="readonly")
            self._on_mode_change(key)
            dismiss()

        def dismiss():
            if self._reposition_timer is not None:
                self.after_cancel(self._reposition_timer)
                self._reposition_timer = None
            self._app_unbind(self._popup_bind_id)
            self._popup_bind_id = None
            if self._popup:
                try:
                    self._popup.destroy()
                except Exception:
                    pass
                self._popup = None

        for i, (key, _name, _) in enumerate(MODE_SPECS):
            name = self._mode_name(key)
            btn = ctk.CTkButton(popup, text=name, anchor="w",
                                fg_color="transparent", hover_color=c["input_bg"],
                                text_color=c["text"],
                                font=ctk.CTkFont(family=f, size=13),
                                corner_radius=6, height=32, width=190,
                                command=lambda k=key, n=name: select(k, n))
            btn.pack(fill="x", pady=1, padx=4)

        popup.update_idletasks()
        popup.place(in_=self._mode_entry, x=0, rely=1.0, y=2, anchor="nw")
        popup.lift()
        self._popup_bind_id = self._app_bind(
            lambda e: dismiss() if not self._is_inside_popup(e.widget) else None
        )

    def _is_inside_popup(self, w):
        while w:
            if w == self._popup:
                return True
            w = w.master
        return False

    def _on_mode_change(self, key):
        for w in self._extra_widgets:
            try:
                w.destroy()
            except AttributeError:
                pass
        self._extra_widgets.clear()

        if key == "aac":
            self._add_extra_dropdown(self.t("format_label"), ["aac-lc", "aac", "aac-binaural", "aac-downmix"], "aac-lc")
            self._extra_row.pack(fill="x", pady=(6, 0))
        elif key == "search":
            self._add_extra_dropdown(self.t("search_type"), ["song", "album", "artist"], "song")
            self._extra_row.pack(fill="x", pady=(6, 0))
        else:
            self._extra_row.pack_forget()

    def _add_extra_dropdown(self, label, values, default):
        c = self.app.colors
        f = FONT_FAMILY
        row = ctk.CTkFrame(self._extra_row, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text=label, font=ctk.CTkFont(family=f, size=11),
                     text_color=c["text_secondary"], width=55, anchor="w").pack(side="left")
        var = ctk.StringVar(value=default)
        menu = ctk.CTkOptionMenu(row, values=values, variable=var,
                                 width=160, height=30, corner_radius=6,
                                 fg_color=c["input_bg"], text_color=c["text"],
                                 button_color=c["primary"],
                                 button_hover_color=c["primary_hover"],
                                 font=ctk.CTkFont(family=f, size=11))
        menu.pack(side="left")
        self._extra_widgets.extend([row, var])

    def _ensure_prereqs(self):
        if not wrapper_running():
            ok, msg = do_start_wrapper(self.log)
            if not ok:
                self.log(f"[ERROR] {msg}")
                return False
            self.app.wrapper_ready = True
        if not get_downloader_exe():
            self.log(f"[ERROR] {self.t('downloader_missing')}")
            return False
        return True

    def _start_download(self):
        if self._downloading:
            self._cancel_download()
            return

        key = self._mode_var.get()
        spec = next(m for m in MODE_SPECS if m[0] == key)
        tmpl = spec[2]

        url = self._url_var.get().strip()
        if not url:
            return

        title = self._mode_name(key)
        if key == "aac":
            aac_type = self._extra_widgets[1].get() if len(self._extra_widgets) >= 2 else "aac-lc"
            args = tmpl.format(aac_type=aac_type, url=url)
            title = f"{title} ({aac_type})"
        elif key == "search":
            search_type = self._extra_widgets[1].get() if len(self._extra_widgets) >= 2 else "song"
            args = tmpl.format(search_type=search_type, query=url)
            title = f"{title} ({search_type})"
        else:
            args = tmpl.format(url=url) if tmpl else url

        self.log(f">>> {title}")
        self._downloading = True
        self._go_btn.configure(fg_color=self.c("error"), hover_color="#CC2F26",
                               text=self.t("running_btn"))
        threading.Thread(target=self._dl_thread, args=(args,), daemon=True).start()

    def _cancel_download(self):
        if self._dl_proc and self._dl_proc.poll() is None:
            self._dl_proc.kill()
            self.log("[CANCEL] Download cancelled")
        # Killing wsl.exe leaves the downloader running inside the distro.
        try:
            kill_downloader(log_callback=self.log)
        except Exception:
            pass
        self._reset_download_state()

    def _reset_download_state(self):
        self._downloading = False
        self._dl_proc = None
        try:
            self._go_btn.configure(fg_color=self.c("primary"), hover_color=self.c("primary_hover"),
                                   text=self.t("download"))
        except Exception:
            pass

    def _dl_thread(self, arguments):
        # Prerequisite checks spawn wsl.exe and open sockets, so they belong on
        # this worker thread - not on the button handler, where they froze the
        # window for seconds before the download even started.
        if not self._ensure_prereqs():
            self.after(0, self._on_download_done)
            return

        exe = get_downloader_exe()
        if not exe:
            self.log(f"[ERROR] {self.t('downloader_missing')}")
            self.after(0, self._on_download_done)
            return

        if not get_config_path():
            self.log("[WARN] No config.yaml found, using defaults")

        dl_args = arguments.split()
        dl_folder = get_save_folder("alac")

        # The legacy downloader reads config.yaml from its working directory,
        # so it runs inside a temp dir whose config points at the real output.
        workdir, _cfg = prepare_run_config()
        argv = build_downloader_command(dl_args, workdir)
        if not argv:
            cleanup_run_config(workdir)
            self.log("[ERROR] Downloader binary not found in WSL")
            self.after(0, self._on_download_done)
            return

        for attempt in range(1, 4):
            if attempt > 1:
                self.log(f"[RETRY] Attempt {attempt}/3...")
                time.sleep(2)

            try:
                proc = subprocess.Popen(
                    argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    env=downloader_env(),
                    startupinfo=_SI, creationflags=_CF)
            except Exception as e:
                self.log(f"[ERROR] Failed to launch downloader: {e}")
                break

            self._dl_proc = proc
            buf = ""
            try:
                for ch in iter(lambda: proc.stdout.read(1), ""):
                    if ch in ("\r", "\n"):
                        if buf.strip():
                            if "%" in buf:
                                self.log_replace(buf.strip())
                            else:
                                self.log(buf.strip())
                        buf = ""
                    else:
                        buf += ch
                if buf.strip():
                    self.log(buf.strip())
                proc.wait()
                if proc.returncode == 0:
                    break
                self.log(f"Exit code: {proc.returncode}")
            except Exception:
                pass

        cleanup_run_config(workdir)
        self.log(f"Done - output: {dl_folder}")
        if not wrapper_running():
            wrapper_health_after_run(log_callback=self.log)
        self.after(0, self._on_download_done)


class ConfigPage(AppPage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.build_ui()

    def build_ui(self):
        c = self.app.colors
        f = FONT_FAMILY

        topbar = ctk.CTkFrame(self, fg_color=c["card"], height=44, corner_radius=0,
                              border_color=c["divider"], border_width=1)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        self._config_title = ctk.CTkLabel(topbar, text=self.t("config_title"),
                                          font=ctk.CTkFont(family=f, size=16, weight="bold"),
                                          text_color=c["text"])
        self._config_title.pack(side="left", padx=16, pady=11); self._reg(self._config_title, "config_title")

        btn_frame = ctk.CTkFrame(topbar, fg_color="transparent")
        btn_frame.pack(side="right", padx=6)

        self.token_btn = ctk.CTkButton(btn_frame, text=self.t("get_token"), width=96, height=30,
                                       corner_radius=6,
                                       fg_color=c["input_bg"], hover_color=c["divider"],
                                       text_color=c["text"],
                                       font=ctk.CTkFont(family=f, size=12),
                                       command=self._get_media_token)
        self.token_btn.pack(side="left", padx=(0, 6)); self._reg(self.token_btn, "get_token")

        self.reload_btn = ctk.CTkButton(btn_frame, text=self.t("reload"), width=72, height=30,
                                        corner_radius=6,
                                        fg_color=c["input_bg"], hover_color=c["divider"],
                                        text_color=c["text"],
                                        font=ctk.CTkFont(family=f, size=12),
                                        command=self._reload_config)
        self.reload_btn.pack(side="left", padx=(0, 6)); self._reg(self.reload_btn, "reload")

        self.save_btn = ctk.CTkButton(btn_frame, text=self.t("save"), width=60, height=30,
                                      corner_radius=6,
                                      fg_color=c["primary"], hover_color=c["primary_hover"],
                                      text_color="white",
                                      font=ctk.CTkFont(family=f, size=12, weight="bold"),
                                      command=self._save_config)
        self.save_btn.pack(side="left"); self._reg(self.save_btn, "save")

        self.status_label = ctk.CTkLabel(self, text="",
                                         font=ctk.CTkFont(family=f, size=11),
                                         text_color=c["text_secondary"])
        self.status_label.pack(fill="x", padx=12, pady=(4, 0))

        self.config_editor = ctk.CTkTextbox(self,
                                            fg_color=c["card"], text_color=c["text"],
                                            border_color=c["border"], border_width=1,
                                            corner_radius=10,
                                            font=ctk.CTkFont(family=MONO_FAMILY, size=12),
                                            wrap="none")
        self.config_editor.pack(fill="both", expand=True, padx=8, pady=8)

    def on_show(self):
        self._reload_config()

    def _reload_config(self):
        content = load_config_content()
        self.config_editor.configure(state="normal")
        self.config_editor.delete("1.0", "end")
        self.config_editor.insert("1.0", content)
        self.config_editor.configure(state="normal")
        path = get_config_path()
        if path:
            self.status_label.configure(text=self.t("config_source", path=path), text_color=self.c("text_secondary"))
        else:
            self.status_label.configure(text=self.t("config_not_found"), text_color=self.c("error"))

    def _save_config(self):
        content = self.config_editor.get("1.0", "end-1c")
        try:
            os.makedirs(APP_DATA_DIR, exist_ok=True)
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                f.write(content)
            self.status_label.configure(
                text=self.t("config_saved", path=CONFIG_FILE),
                text_color=self.c("success")
            )
        except Exception as e:
            self.status_label.configure(text=self.t("config_save_failed", error=e), text_color=self.c("error"))

    # ---- media-user-token helper -------------------------------------
    def _get_media_token(self):
        """Auto-detect a media-user-token, or guide the user to paste one."""
        self.token_btn.configure(state="disabled", text="...")
        self.status_label.configure(text=self.t("token_searching"),
                                    text_color=self.c("text_secondary"))
        threading.Thread(target=self._media_token_worker, daemon=True).start()

    def _media_token_worker(self):
        token, source, notes = find_media_user_token()
        if token:
            ok, detail = validate_media_user_token(token)
            if ok:
                save_media_user_token(token)
                self.after(0, lambda: self._media_token_done(
                    True, self.t("token_found", source=source, detail=detail)))
                return
            notes.append(f"{source}: {detail}")
        self.after(0, lambda: self._media_token_prompt(notes))

    def _media_token_done(self, ok, message):
        self.token_btn.configure(state="normal", text=self.t("get_token"))
        self.status_label.configure(
            text=message, text_color=self.c("success") if ok else self.c("error"))
        if ok:
            self._reload_config()

    def _copy_to_clipboard(self, text):
        """Copy text to the clipboard and confirm on the status label."""
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
            self.status_label.configure(text=self.t("token_copied"),
                                        text_color=self.c("success"))
        except Exception as e:
            self.status_label.configure(text=str(e), text_color=self.c("error"))

    def _media_token_prompt(self, notes):
        """Fallback: explain how to get the token and accept a pasted value."""
        self.token_btn.configure(state="normal", text=self.t("get_token"))
        self.status_label.configure(text=self.t("token_not_found"),
                                    text_color=self.c("text_secondary"))
        c = self.app.colors
        f = FONT_FAMILY

        dlg = ctk.CTkToplevel(self)
        dlg.title(self.t("token_dialog_title"))
        dlg.geometry("640x500")
        dlg.transient(self)
        dlg.grab_set()

        # A read-only textbox instead of a label so the URL and the steps can be
        # selected and copied (labels are not selectable).
        howto = self.t("token_howto")
        if notes:
            howto += "\n\n" + "\n".join("• " + n for n in notes)
        howto_box = ctk.CTkTextbox(dlg, height=150,
                                   fg_color=c["input_bg"], text_color=c["text"],
                                   border_color=c["border"], border_width=1,
                                   corner_radius=8, wrap="word",
                                   font=ctk.CTkFont(family=f, size=12))
        howto_box.pack(fill="x", padx=16, pady=(14, 8))
        howto_box.insert("1.0", howto)
        howto_box.configure(state="disabled")

        open_row = ctk.CTkFrame(dlg, fg_color="transparent")
        open_row.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkButton(open_row, text=self.t("token_open_browser"), width=170, height=30,
                      corner_radius=6, fg_color=c["primary"],
                      hover_color=c["primary_hover"], text_color="white",
                      font=ctk.CTkFont(family=f, size=12),
                      command=lambda: webbrowser.open("https://music.apple.com")
                      ).pack(side="left")
        ctk.CTkButton(open_row, text=self.t("token_copy_url"), width=120, height=30,
                      corner_radius=6, fg_color=c["input_bg"],
                      hover_color=c["divider"], text_color=c["text"],
                      font=ctk.CTkFont(family=f, size=12),
                      command=lambda: self._copy_to_clipboard(
                          "https://music.apple.com")
                      ).pack(side="left", padx=(8, 0))

        entry = ctk.CTkEntry(dlg, height=38, corner_radius=8,
                             fg_color=c["input_bg"], text_color=c["text"],
                             border_color=c["border"],
                             font=ctk.CTkFont(family=MONO_FAMILY, size=11),
                             placeholder_text=self.t("token_placeholder"))
        entry.pack(fill="x", padx=16, pady=(4, 6))

        result = ctk.CTkLabel(dlg, text="", font=ctk.CTkFont(family=f, size=11),
                              text_color=c["text_secondary"], anchor="w")
        result.pack(fill="x", padx=16)

        def clear_placeholder(event=None):
            try:
                if entry.get().endswith("\u2026"):
                    entry.delete(0, "end")
            except Exception:
                pass
        entry.bind("<FocusIn>", clear_placeholder)

        def submit():
            value = entry.get().strip()
            if not value:
                result.configure(text=self.t("token_empty"), text_color=c["error"])
                return
            verify.configure(state="disabled", text="...")
            result.configure(text=self.t("token_checking"),
                             text_color=c["text_secondary"])

            def work():
                ok, detail = validate_media_user_token(value)
                def finish():
                    verify.configure(state="normal", text=self.t("token_verify_save"))
                    if ok:
                        save_media_user_token(value)
                        dlg.destroy()
                        self._media_token_done(
                            True, self.t("token_saved", detail=detail))
                    else:
                        result.configure(text=detail, text_color=c["error"])
                self.after(0, finish)
            threading.Thread(target=work, daemon=True).start()

        row = ctk.CTkFrame(dlg, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=12)
        verify = ctk.CTkButton(row, text=self.t("token_verify_save"), width=150, height=34,
                               corner_radius=8, fg_color=c["primary"],
                               hover_color=c["primary_hover"], text_color="white",
                               font=ctk.CTkFont(family=f, size=12, weight="bold"),
                               command=submit)
        verify.pack(side="right")
        ctk.CTkButton(row, text=self.t("token_cancel"), width=80, height=34,
                      corner_radius=8, fg_color=c["input_bg"],
                      hover_color=c["divider"], text_color=c["text"],
                      font=ctk.CTkFont(family=f, size=12),
                      command=dlg.destroy).pack(side="right", padx=(0, 8))

        entry.focus_set()
        entry.bind("<Return>", lambda e: submit())


class StatusPage(AppPage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._items = {}
        self._section_headers = []
        self._item_labels = {}
        self._path_labels = {}
        self.build_ui()

    def build_ui(self):
        c = self.app.colors
        f = FONT_FAMILY
        folder_img = _make_folder(size=14, color=c["text_secondary"])

        topbar = ctk.CTkFrame(self, fg_color=c["card"], height=44, corner_radius=0,
                              border_color=c["divider"], border_width=1)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        lbl = ctk.CTkLabel(topbar, text=self.t("status_title"),
                           font=ctk.CTkFont(family=f, size=16, weight="bold"),
                           text_color=c["text"]); lbl.pack(side="left", padx=16, pady=11); self._reg(lbl, "status_title")

        self.refresh_btn = ctk.CTkButton(topbar, text=self.t("status_refresh"), width=60, height=30,
                                         corner_radius=6,
                                         fg_color=c["primary"], hover_color=c["primary_hover"],
                                         text_color="white",
                                         font=ctk.CTkFont(family=f, size=12, weight="bold"),
                                         command=self._refresh)
        self.refresh_btn.pack(side="right", padx=6, pady=7); self._reg(self.refresh_btn, "status_refresh")

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=12, pady=8)

        sections = [
            ("s_wrapper", [
                ("wrapper-endpoint", "wrapper_endpoint"),
                ("wrapper-service", "wrapper_service"),
                ("wrapper-container", "wrapper_container"),
                ("wrapper-ports", "wrapper_ports"),
                ("wrapper-storefront", "wrapper_storefront"),
            ]),
            ("s_login", [
                ("login-cached", "login_cached"),
            ]),
        ]

        for section_key, items in sections:
            header = ctk.CTkLabel(scroll, text=self.t(section_key),
                                  font=ctk.CTkFont(family=f, size=13, weight="bold"),
                                  text_color=c["text_secondary"])
            header.pack(anchor="w", pady=(12, 4))
            self._section_headers.append((header, section_key))

            card = ctk.CTkFrame(scroll, fg_color=c["card"], corner_radius=10,
                                border_color=c["border"], border_width=1)
            card.pack(fill="x", pady=(0, 4))

            for key, i18n_key in items:
                row = ctk.CTkFrame(card, fg_color="transparent", height=32)
                row.pack(fill="x", padx=10, pady=3)
                row.pack_propagate(False)

                dot = ctk.CTkFrame(row, width=8, height=8, corner_radius=4,
                                   fg_color=c["error"])
                dot.pack(side="left", padx=(4, 8))

                item_lbl = ctk.CTkLabel(row, text=self.t(i18n_key),
                                        font=ctk.CTkFont(family=f, size=13),
                                        text_color=c["text"])
                item_lbl.pack(side="left")
                self._item_labels[key] = (item_lbl, i18n_key)

                value = ctk.CTkLabel(row, text=self.t("checking_status"),
                                     font=ctk.CTkFont(family=f, size=12),
                                     text_color=c["text_secondary"])
                value.pack(side="right", padx=4)

                self._items[key] = (dot, value)

            if section_key == "s_wrapper":
                restart_row = ctk.CTkFrame(card, fg_color="transparent", height=32)
                restart_row.pack(fill="x", padx=10, pady=3)
                restart_row.pack_propagate(False)
                self._restart_btn = ctk.CTkButton(restart_row, text=self.t("wrapper_restart"),
                                                  fg_color=c["warning"], hover_color="#E68600",
                                                  text_color="white",
                                                  font=ctk.CTkFont(family=f, size=12),
                                                  corner_radius=6, height=26,
                                                  command=self._restart_wrapper)
                self._restart_btn.pack(side="left")
                self._reg(self._restart_btn, "wrapper_restart")

            # Add export button inside the images card
            # (removed: image export is no longer applicable)

        path_header = ctk.CTkLabel(scroll, text=self.t("s_paths"),
                                   font=ctk.CTkFont(family=f, size=13, weight="bold"),
                                   text_color=c["text_secondary"])
        path_header.pack(anchor="w", pady=(12, 4))
        self._section_headers.append((path_header, "s_paths"))

        path_card = ctk.CTkFrame(scroll, fg_color=c["card"], corner_radius=10,
                                 border_color=c["border"], border_width=1)
        path_card.pack(fill="x", pady=(0, 4))

        paths = [
            ("config-path", "config_path_label", CONFIG_FILE),
            ("log-path", "log_path_label", LOG_DIR),
            ("downloader-path", "downloader_path_label", get_downloader_exe() or "—"),
        ]

        for key, i18n_key, path in paths:
            row = ctk.CTkFrame(path_card, fg_color="transparent", height=32)
            row.pack(fill="x", padx=10, pady=3)
            row.pack_propagate(False)

            plbl = ctk.CTkLabel(row, text=self.t(i18n_key),
                                font=ctk.CTkFont(family=f, size=13),
                                text_color=c["text"])
            plbl.pack(side="left", padx=4)
            self._item_labels[key] = (plbl, i18n_key)

            path_label = ctk.CTkLabel(row, text=path,
                                      font=ctk.CTkFont(family=f, size=11),
                                      text_color=c["text_secondary"])
            path_label.pack(side="left", padx=(6, 4))

            btn = ctk.CTkButton(row, text="", width=24, height=22,
                                corner_radius=4, image=folder_img,
                                fg_color="transparent", hover_color=c["input_bg"],
                                command=lambda p=path: os.startfile(p))
            btn.pack(side="right", padx=2)

            self._path_labels[key] = path_label

    def on_show(self):
        self._refresh()

    def _refresh(self):
        threading.Thread(target=self._run_checks, daemon=True).start()

    def _run_checks(self):
        c = self.app.colors
        results = {}

        results["wrapper-endpoint"] = (True, WRAPPER_ENDPOINT)

        state = wrapper_service_state()
        results["wrapper-service"] = (state == "active", state)

        ok, data, err = wrapper_status(timeout=5)
        results["wrapper-container"] = (ok, self.t("running") if ok else self.t("not_running"))

        results["wrapper-ports"] = (ok, f"{DECRYPT_PORT} / {M3U8_PORT} / {ACCOUNT_PORT}" if ok else "—")

        storefront = (data or {}).get("storefront_id") or ""
        results["wrapper-storefront"] = (bool(storefront), storefront or "—")

        has_login = login_cached()
        results["login-cached"] = (has_login,
                                   self.t("logged_in") if has_login else self.t("not_logged_in"))

        def update():
            for key, (ok2, text) in results.items():
                if key in self._items:
                    dot, label = self._items[key]
                    dot.configure(fg_color=c["success"] if ok2 else c["error"])
                    label.configure(text=text)
            for key, lbl in self._path_labels.items():
                path_map = {
                    "config-path": CONFIG_FILE,
                    "log-path": LOG_DIR,
                    "downloader-path": get_downloader_exe() or "—",
                }
                if key in path_map:
                    lbl.configure(text=path_map[key])
        self.after(0, update)

    def _restart_wrapper(self):
        self._restart_btn.configure(state="disabled", text=self.t("wrapper_restarting"))
        threading.Thread(target=self._do_restart_wrapper, daemon=True).start()

    def _do_restart_wrapper(self):
        ok, msg = restart_wrapper_service(log_callback=None)
        self.after(0, lambda: self._restart_btn.configure(
            state="normal", text=self.t("wrapper_restart")
        ))
        self.after(0, self._refresh)

    def refresh_language(self):
        super().refresh_language()
        for header, key in self._section_headers:
            header.configure(text=self.t(key))
        for (_lbl, i18n_key) in self._item_labels.values():
            _lbl.configure(text=self.t(i18n_key))


class ConvertPage(AppPage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._source_dir = get_download_folder()
        self._converting = False
        self._format_var = None
        self._popup = None
        self._reposition_timer = None
        self.build_ui()

    def build_ui(self):
        c = self.app.colors
        f = FONT_FAMILY

        topbar = ctk.CTkFrame(self, fg_color=c["card"], height=44, corner_radius=0,
                              border_color=c["divider"], border_width=1)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        self._convert_title = ctk.CTkLabel(topbar, text=self.t("convert_title"),
                                           font=ctk.CTkFont(family=f, size=16, weight="bold"),
                                           text_color=c["text"])
        self._convert_title.pack(side="left", padx=16, pady=11)
        self._reg(self._convert_title, "convert_title")

        btn_frame = ctk.CTkFrame(topbar, fg_color="transparent")
        btn_frame.pack(side="right", padx=6)

        self._select_dir_btn = ctk.CTkButton(btn_frame, text=self.t("convert_select_dir"),
                                              width=80, height=30, corner_radius=6,
                                              fg_color=c["input_bg"], hover_color=c["divider"],
                                              text_color=c["text"],
                                              font=ctk.CTkFont(family=f, size=12),
                                              command=self._select_dir)
        self._select_dir_btn.pack(side="left", padx=(0, 6))
        self._reg(self._select_dir_btn, "convert_select_dir")

        self._format_var = ctk.StringVar(value="FLAC")
        self._format_entry = ctk.CTkEntry(btn_frame, height=30, corner_radius=6,
                                          fg_color=c["input_bg"], text_color=c["text"],
                                          border_color=c["border"],
                                          font=ctk.CTkFont(family=f, size=12),
                                          width=70, justify="center")
        self._format_entry.pack(side="left", padx=(0, 6))
        self._format_entry.insert(0, "FLAC")
        self._format_entry.configure(state="readonly")
        self._format_entry.bind("<Button-1>", lambda e: self._show_format_popup())

        self._convert_btn = ctk.CTkButton(btn_frame, text=self.t("convert_btn"),
                                           width=90, height=30, corner_radius=6,
                                           fg_color=c["primary"], hover_color=c["primary_hover"],
                                           text_color="white",
                                           font=ctk.CTkFont(family=f, size=12, weight="bold"),
                                           command=self._start_convert)
        self._convert_btn.pack(side="left")
        self._reg(self._convert_btn, "convert_btn")

        body = ctk.CTkFrame(self, fg_color=c["background"], corner_radius=0)
        body.pack(fill="both", expand=True, padx=12, pady=8)

        self._status_label = ctk.CTkLabel(body, text=self.t("convert_source_dir", path=self._source_dir),
                                          font=ctk.CTkFont(family=f, size=12),
                                          text_color=c["text_secondary"])
        self._status_label.pack(anchor="w", pady=(0, 4))

        self._progress = ctk.CTkProgressBar(body, width=400, height=4,
                                            progress_color=c["primary"],
                                            fg_color=c["divider"])
        self._progress.pack(fill="x", pady=(0, 8))
        self._progress.set(0)

        self._log = ctk.CTkTextbox(body,
                                    fg_color=c["card"], text_color=c["text"],
                                    border_color=c["border"], border_width=1,
                                    corner_radius=10,
                                    font=ctk.CTkFont(family=MONO_FAMILY, size=12),
                                    state="disabled",
                                    wrap="none")
        self._log.pack(fill="both", expand=True)

    def log(self, msg):
        if self._log:
            self._log.configure(state="normal")
            self._log.insert("end", msg + "\n")
            self._log.see("end")
            self._log.configure(state="disabled")

    def on_show(self):
        self._update_dir_label()

    def _update_dir_label(self):
        self._status_label.configure(text=self.t("convert_source_dir", path=self._source_dir))

    def _select_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title=self.t("convert_select_dir"), initialdir=self._source_dir)
        if d:
            self._source_dir = d
            self._update_dir_label()

    def _show_format_popup(self):
        if self._popup and self._popup.winfo_exists():
            self._popup.destroy()
        self._popup = None
        self._app_unbind(getattr(self, '_popup_bind_id', None))
        self._popup_bind_id = None
        if self._reposition_timer is not None:
            self.after_cancel(self._reposition_timer)
            self._reposition_timer = None

        c = self.app.colors
        f = FONT_FAMILY
        popup = ctk.CTkFrame(self, fg_color=c["surface"],
                             border_color=c["border"], border_width=1,
                             corner_radius=6)
        self._popup = popup
        self._popup_bind_id = None

        def select(fmt):
            self._format_var.set(fmt)
            self._format_entry.configure(state="normal")
            self._format_entry.delete(0, "end")
            self._format_entry.insert(0, fmt)
            self._format_entry.configure(state="readonly")
            dismiss()

        def dismiss():
            if self._reposition_timer is not None:
                self.after_cancel(self._reposition_timer)
                self._reposition_timer = None
            self._app_unbind(self._popup_bind_id)
            self._popup_bind_id = None
            if self._popup:
                try:
                    self._popup.destroy()
                except Exception:
                    pass
                self._popup = None

        for fmt in ["FLAC", "WAV"]:
            btn = ctk.CTkButton(popup, text=fmt, anchor="w",
                                fg_color="transparent", hover_color=c["input_bg"],
                                text_color=c["text"],
                                font=ctk.CTkFont(family=f, size=12),
                                corner_radius=4, height=28, width=70,
                                command=lambda f=fmt: select(f))
            btn.pack(fill="x", pady=1, padx=2)

        popup.update_idletasks()
        popup.place(in_=self._format_entry, x=0, rely=1.0, y=2, anchor="nw")
        popup.lift()
        self._popup_bind_id = self._app_bind(
            lambda e: dismiss() if not self._is_inside_popup(e.widget) else None
        )

    def _is_inside_popup(self, w):
        while w:
            if w == self._popup:
                return True
            w = w.master
        return False

    def _start_convert(self):
        if self._converting:
            return
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

        ffmpeg = find_tool("ffmpeg")
        if not ffmpeg:
            self.log("[WARN] ffmpeg not found in assets or PATH")
            self.log("[INFO] Place ffmpeg.exe in the assets folder, or install via winget...")
            self._converting = True
            self._convert_btn.configure(state="disabled", text=self.t("convert_running"))
            threading.Thread(target=self._try_install_ffmpeg, daemon=True).start()
            return

        self._converting = True
        self._convert_btn.configure(state="disabled", text=self.t("convert_running"))
        threading.Thread(target=self._do_convert, daemon=True).start()

    def _try_install_ffmpeg(self):
        self.after(0, lambda: self.log("[INFO] Running winget install (this may take a few minutes)..."))
        try:
            result = subprocess.run(
                ["winget", "install", "--id", "Gyan.FFmpeg", "-e",
                 "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity"],
                capture_output=True, text=True,
                startupinfo=_SI, creationflags=_CF,
                timeout=600
            )
            if result.returncode == 0:
                self.after(0, lambda: self.log("[OK] ffmpeg installed"))
                ffmpeg = find_tool("ffmpeg")
                if ffmpeg:
                    self.after(0, lambda: self.log(f"[OK] Found: {ffmpeg}"))
                    self.after(0, self._start_convert)
                    return
                self.after(0, lambda: self.log("[INFO] Restart the app, then convert again"))
            else:
                err = (result.stderr or result.stdout or "").strip()[:200]
                self.after(0, lambda: self.log(f"[ERROR] winget install failed: {err}"))
                self.after(0, lambda: self.log("[INFO] Place ffmpeg.exe in assets/ manually"))
        except FileNotFoundError:
            self.after(0, lambda: self.log("[ERROR] winget not found"))
            self.after(0, lambda: self.log("[INFO] Place ffmpeg.exe in assets/ manually"))
        except subprocess.TimeoutExpired:
            self.after(0, lambda: self.log("[ERROR] winget install timed out"))
            self.after(0, lambda: self.log("[INFO] Place ffmpeg.exe in assets/ manually"))
        except Exception as e:
            self.after(0, lambda: self.log(f"[ERROR] {e}"))
        self.after(0, self._reset_btn)

    def _do_convert(self):
        self.after(0, lambda: self.log(self.t("convert_scanning")))

        # Recursive scan for m4a files only
        files = []
        try:
            for root, dirs, filenames in os.walk(self._source_dir):
                for f in sorted(filenames):
                    if os.path.splitext(f)[1].lower() == '.m4a':
                        files.append(os.path.join(root, f))
        except Exception as e:
            self.after(0, lambda: self.log(f"[ERROR] {e}"))
            self.after(0, self._reset_btn)
            return

        if not files:
            self.after(0, lambda: self.log(self.t("convert_nothing")))
            self.after(0, self._reset_btn)
            return

        self.after(0, lambda: self.log(self.t("convert_found", count=len(files))))
        total = len(files)
        ok_count = 0
        fmt = self._format_var.get().lower()
        ffmpeg = find_tool("ffmpeg") or "ffmpeg"

        for i, src in enumerate(files):
            base = os.path.splitext(src)[0]
            base = base.replace(". ", ".", 1)
            out = base + "." + fmt
            name = os.path.basename(src)
            name_noext = os.path.splitext(name)[0]

            # Skip if output file already exists
            if os.path.isfile(out):
                self.after(0, lambda n=name_noext: self.log(self.t("convert_skip_exists", file=n)))
                continue

            self.after(0, lambda n=name_noext: self.log(self.t("convert_converting", file=n)))
            self.after(0, lambda v=(i+1)/total: self._progress.set(v))

            try:
                if fmt == "wav":
                    result = subprocess.run(
                        [ffmpeg, "-y", "-i", src, "-loglevel", "error", out],
                        capture_output=True, text=True,
                        startupinfo=_SI, creationflags=_CF
                    )
                else:
                    result = subprocess.run(
                        [ffmpeg, "-y", "-i", src, "-c:a", "flac", "-compression_level", "6", "-loglevel", "error", out],
                        capture_output=True, text=True,
                        startupinfo=_SI, creationflags=_CF
                    )
                if result.returncode == 0:
                    ok_count += 1
                else:
                    self.after(0, lambda n=name_noext: self.log(self.t("convert_failed", file=n)))
                    if result.stderr.strip():
                        self.after(0, lambda e=result.stderr.strip()[:200]: self.log(f"  [ERROR] {e}"))
            except FileNotFoundError as fe:
                self.after(0, lambda: self.log(f"[ERROR] {fe.filename} not found"))
                self.after(0, lambda: self.log("[INFO] Place ffmpeg.exe in the assets folder"))
                break
            except Exception as e:
                self.after(0, lambda n=name_noext, err=str(e): self.log(f"[ERROR] {n}: {err}"))

        self.after(0, lambda: self._progress.set(1.0))
        self.after(0, lambda: self.log(self.t("convert_complete", total=ok_count)))
        self.after(0, self._reset_btn)

    def _reset_btn(self):
        self._converting = False
        self._convert_btn.configure(state="normal", text=self.t("convert_btn"))

    def refresh_language(self):
        super().refresh_language()
        self._update_dir_label()


class RenamePage(AppPage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._source_dir = get_download_folder()
        self._renaming = False
        self._popup = None
        self._reposition_timer = None
        self.build_ui()

    def build_ui(self):
        c = self.app.colors
        f = FONT_FAMILY

        topbar = ctk.CTkFrame(self, fg_color=c["card"], height=44, corner_radius=0,
                              border_color=c["divider"], border_width=1)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        self._title = ctk.CTkLabel(topbar, text=self.t("rename_title"),
                                   font=ctk.CTkFont(family=f, size=16, weight="bold"),
                                   text_color=c["text"])
        self._title.pack(side="left", padx=16, pady=11)
        self._reg(self._title, "rename_title")

        btn_frame = ctk.CTkFrame(topbar, fg_color="transparent")
        btn_frame.pack(side="right", padx=6)

        self._select_dir_btn = ctk.CTkButton(btn_frame, text=self.t("rename_select_dir"),
                                              width=80, height=30, corner_radius=6,
                                              fg_color=c["input_bg"], hover_color=c["divider"],
                                              text_color=c["text"],
                                              font=ctk.CTkFont(family=f, size=12),
                                              command=self._select_dir)
        self._select_dir_btn.pack(side="left", padx=(0, 6))
        self._reg(self._select_dir_btn, "rename_select_dir")

        lbl = ctk.CTkLabel(btn_frame, text=self.t("rename_format_label"),
                           font=ctk.CTkFont(family=f, size=12),
                           text_color=c["text_secondary"])
        lbl.pack(side="left", padx=(0, 4))
        self._reg(lbl, "rename_format_label")

        self._format_var = ctk.StringVar(value=self.t("rename_tpl_track"))
        self._format_entry = ctk.CTkEntry(btn_frame, height=30, corner_radius=6,
                                          fg_color=c["input_bg"], text_color=c["text"],
                                          border_color=c["border"],
                                          font=ctk.CTkFont(family=f, size=12),
                                          width=90, justify="center")
        self._format_entry.pack(side="left", padx=(0, 6))
        self._format_entry.insert(0, self.t("rename_tpl_track"))
        self._format_entry.configure(state="readonly")
        self._format_entry.bind("<Button-1>", lambda e: self._show_format_popup())

        self._rename_btn = ctk.CTkButton(btn_frame, text=self.t("rename_btn"),
                                          width=90, height=30, corner_radius=6,
                                          fg_color=c["primary"], hover_color=c["primary_hover"],
                                          text_color="white",
                                          font=ctk.CTkFont(family=f, size=12, weight="bold"),
                                          command=self._start_rename)
        self._rename_btn.pack(side="left")
        self._reg(self._rename_btn, "rename_btn")

        body = ctk.CTkFrame(self, fg_color=c["background"], corner_radius=0)
        body.pack(fill="both", expand=True, padx=12, pady=8)

        self._status_label = ctk.CTkLabel(body, text=self.t("rename_source_dir", path=self._source_dir),
                                          font=ctk.CTkFont(family=f, size=12),
                                          text_color=c["text_secondary"])
        self._status_label.pack(anchor="w", pady=(0, 4))

        self._progress = ctk.CTkProgressBar(body, width=400, height=4,
                                            progress_color=c["primary"],
                                            fg_color=c["divider"])
        self._progress.pack(fill="x", pady=(0, 8))
        self._progress.set(0)

        self._log = ctk.CTkTextbox(body,
                                    fg_color=c["card"], text_color=c["text"],
                                    border_color=c["border"], border_width=1,
                                    corner_radius=10,
                                    font=ctk.CTkFont(family=MONO_FAMILY, size=12),
                                    state="disabled",
                                    wrap="none")
        self._log.pack(fill="both", expand=True)

    def log(self, msg):
        if self._log:
            self._log.configure(state="normal")
            self._log.insert("end", msg + "\n")
            self._log.see("end")
            self._log.configure(state="disabled")

    def on_show(self):
        self._update_dir_label()

    def _update_dir_label(self):
        self._status_label.configure(text=self.t("rename_source_dir", path=self._source_dir))

    def _select_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title=self.t("rename_select_dir"), initialdir=self._source_dir)
        if d:
            self._source_dir = d
            self._update_dir_label()

    def _show_format_popup(self):
        if self._popup and self._popup.winfo_exists():
            self._popup.destroy()
        self._popup = None
        self._app_unbind(getattr(self, '_popup_bind_id', None))
        self._popup_bind_id = None
        if self._reposition_timer is not None:
            self.after_cancel(self._reposition_timer)
            self._reposition_timer = None

        c = self.app.colors
        f = FONT_FAMILY
        popup = ctk.CTkFrame(self, fg_color=c["surface"],
                             border_color=c["border"], border_width=1,
                             corner_radius=6)
        self._popup = popup
        self._popup_bind_id = None

        tpl_track = self.t("rename_tpl_track")
        tpl_artist = self.t("rename_tpl_artist")

        def select(fmt):
            self._format_var.set(fmt)
            self._format_entry.configure(state="normal")
            self._format_entry.delete(0, "end")
            self._format_entry.insert(0, fmt)
            self._format_entry.configure(state="readonly")
            dismiss()

        def dismiss():
            if self._reposition_timer is not None:
                self.after_cancel(self._reposition_timer)
                self._reposition_timer = None
            self._app_unbind(self._popup_bind_id)
            self._popup_bind_id = None
            if self._popup:
                try:
                    self._popup.destroy()
                except Exception:
                    pass
                self._popup = None

        for fmt in [tpl_track, tpl_artist]:
            btn = ctk.CTkButton(popup, text=fmt, anchor="w",
                                fg_color="transparent", hover_color=c["input_bg"],
                                text_color=c["text"],
                                font=ctk.CTkFont(family=f, size=12),
                                corner_radius=4, height=28, width=160,
                                command=lambda f=fmt: select(f))
            btn.pack(fill="x", pady=1, padx=2)

        popup.update_idletasks()
        popup.place(in_=self._format_entry, x=0, rely=1.0, y=2, anchor="nw")
        popup.lift()
        self._popup_bind_id = self._app_bind(
            lambda e: dismiss() if not self._is_inside_popup(e.widget) else None
        )

    def _is_inside_popup(self, w):
        while w:
            if w == self._popup:
                return True
            w = w.master
        return False

    def _start_rename(self):
        if self._renaming:
            return
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
        self._renaming = True
        self._rename_btn.configure(state="disabled", text=self.t("convert_running"))
        threading.Thread(target=self._do_rename, daemon=True).start()

    def _do_rename(self):
        ffprobe = find_tool("ffprobe")
        selected_fmt = self._format_var.get()
        is_track = selected_fmt == self.t("rename_tpl_track")
        self.after(0, lambda: self.log(self.t("rename_scanning")))

        if not ffprobe:
            self.after(0, lambda: self.log(self.t("rename_no_tool")))
            self.after(0, self._reset_btn)
            return

        files = []
        try:
            for root, dirs, filenames in os.walk(self._source_dir):
                for f in sorted(filenames):
                    ext = os.path.splitext(f)[1].lower()
                    if ext in ('.flac', '.wav', '.m4a', '.aif', '.aiff', '.ape', '.wv'):
                        files.append(os.path.join(root, f))
        except Exception as e:
            self.after(0, lambda: self.log(f"[ERROR] {e}"))
            self.after(0, self._reset_btn)
            return

        if not files:
            self.after(0, lambda: self.log(self.t("rename_nothing")))
            self.after(0, self._reset_btn)
            return

        self.after(0, lambda: self.log(self.t("rename_found", count=len(files))))
        total = len(files)
        ok_count = 0

        for i, src in enumerate(files):
            name = os.path.basename(src)
            ext = os.path.splitext(src)[1]
            self.after(0, lambda v=(i+1)/total: self._progress.set(v))

            # Extract tags (ffprobe reports tag keys lower-cased in JSON output)
            tags = {}
            try:
                p = subprocess.run(
                    [ffprobe, "-v", "error",
                     "-show_entries", "format_tags",
                     "-of", "json", src],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace",
                    startupinfo=_SI, creationflags=_CF
                )
                if p.returncode == 0 and p.stdout.strip():
                    raw = json.loads(p.stdout).get("format", {}).get("tags", {})
                    tags = {str(k).lower(): str(v).strip()
                            for k, v in raw.items() if v is not None}
            except Exception:
                pass

            title = tags.get("title", "")
            artist = tags.get("artist", "") or tags.get("album_artist", "")
            if artist.lower() in ("", "unknown", "unknown artist"):
                artist = tags.get("album_artist", "")

            if is_track:
                if not title:
                    self.after(0, lambda n=name: self.log(self.t("rename_no_tag", file=n)))
                    continue
                # Prefer the leading number in the filename so existing
                # zero-padding is preserved; fall back to the TRACK tag.
                m = re.match(r'^\s*(\d+)', os.path.splitext(name)[0])
                track_num = m.group(1) if m else tags.get("track", "").split("/")[0].strip()
                if not track_num.isdigit():
                    track_num = ""
                new_base = f"{track_num}. {title}" if track_num else title
            else:
                if not artist or not title:
                    self.after(0, lambda n=name: self.log(self.t("rename_no_tag", file=n)))
                    continue
                new_base = artist + " - " + title

            new_name = _sanitize_filename(new_base) + ext
            new_path = os.path.join(os.path.dirname(src), new_name)

            if os.path.normpath(src) == os.path.normpath(new_path):
                continue

            self.after(0, lambda o=name, n=new_name: self.log(self.t("rename_renaming", old=o, new=n)))

            try:
                os.rename(src, new_path)
                ok_count += 1
            except Exception as e:
                self.after(0, lambda n=name, err=str(e): self.log(self.t("rename_failed", file=n) + f": {err}"))

        self.after(0, lambda: self._progress.set(1.0))
        self.after(0, lambda: self.log(self.t("rename_complete", total=ok_count)))
        self.after(0, self._reset_btn)

    def _reset_btn(self):
        self._renaming = False
        self._rename_btn.configure(state="normal", text=self.t("rename_btn"))

    def refresh_language(self):
        super().refresh_language()
        self._update_dir_label()
        new_val = self.t("rename_tpl_track")
        self._format_var.set(new_val)
        self._format_entry.configure(state="normal")
        self._format_entry.delete(0, "end")
        self._format_entry.insert(0, new_val)
        self._format_entry.configure(state="readonly")


_INSTANCE_MUTEX = None


def _acquire_single_instance():
    """Take a per-user named mutex. Returns False when one is already held.

    Two instances fight over the same distro, ports and config: the second one
    would try to start a service that is already up and its status panel would
    flip between the two. A mutex is released automatically when the process
    dies, unlike a lock file.
    """
    global _INSTANCE_MUTEX
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, "Local\\AppleMusicDownloader")
        if not handle:
            return True  # cannot tell; better to run than to block the user
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            return False
        _INSTANCE_MUTEX = handle
        return True
    except Exception:
        return True


def _warn_already_running():
    """Tell the user another instance owns the wrapper.

    A plain messagebox blocks forever when nobody can click it (scripts, tests),
    so this window closes itself after a few seconds. AMDL_NO_DIALOG=1 skips the
    UI entirely - useful for automation.
    """
    if (os.environ.get("AMDL_NO_DIALOG") or "").strip().lower() in ("1", "true", "yes"):
        print("Apple Music Downloader is already running.")
        return
    try:
        win = ctk.CTk()
        win.title("Apple Music Downloader")
        win.geometry("440x170")
        win.resizable(False, False)
        ctk.CTkLabel(
            win,
            text=("The app is already running.\n"
                  "Only one instance can use the WSL wrapper at a time."),
            font=ctk.CTkFont(size=13), justify="center",
        ).pack(expand=True, padx=24, pady=(24, 8))
        ctk.CTkButton(win, text="OK", width=110, command=win.destroy).pack(pady=(0, 18))
        win.after(8000, win.destroy)
        win.mainloop()
    except Exception:
        print("Apple Music Downloader is already running.")


def main():
    if not _acquire_single_instance():
        _warn_already_running()
        return 1
    app = AppleMusicApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

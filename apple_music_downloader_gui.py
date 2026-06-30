#!/usr/bin/env python3
"""Apple Music ALAC Downloader - GUI
Requires: Python 3.7+, Docker, customtkinter
"""

import os
import re
import sys
import time
import shutil
import queue
import atexit
import tempfile
import threading
import subprocess
import ctypes
from datetime import datetime
import customtkinter as ctk
from PIL import Image, ImageDraw

if getattr(sys, 'frozen', False):
    SCRIPT_DIR = os.path.dirname(sys.executable)
    DATA_DIR = sys._MEIPASS
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = SCRIPT_DIR
DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
CONFIG_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AppleMusicDownloader", "config.yaml")
CONFIG_EXAMPLE = os.path.join(DATA_DIR, "config.yaml.example")
CONFIG_EXAMPLE_ALT = os.path.join(DATA_DIR, "assets", "apple-music-downloader", "config.yaml.example")

APP_DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AppleMusicDownloader")

WRAPPER_SRC = os.environ.get("WRAPPER_SRC", os.path.join(DATA_DIR, "assets", "Wrapper"))
WRAPPER_IMAGE = "wrapper:local"
WRAPPER_NAME = "am-wrapper"
WRAPPER_DATA_DIR = os.path.join(APP_DATA_DIR, "wrapper-data")

DECRYPT_PORT = 10020
M3U8_PORT = 20020
ACCOUNT_PORT = 30020

REGISTRY_MIRROR = os.environ.get("REGISTRY_MIRROR", "docker.m.daocloud.io")

# ---- Downloader settings ----
DL_SRC = os.environ.get("DL_SRC", os.path.join(DATA_DIR, "assets", "apple-music-downloader"))
DL_IMAGE = "apple-music-downloader:local"

FLAC_EXE = os.environ.get("FLAC_EXE", os.path.join(DATA_DIR, "assets", "flac.exe"))


def get_config_path():
    """返回配置文件路径：若不存在则从示例复制"""
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    if not os.path.isfile(CONFIG_FILE):
        example = None
        if os.path.isfile(CONFIG_EXAMPLE):
            example = CONFIG_EXAMPLE
        elif os.path.isfile(CONFIG_EXAMPLE_ALT):
            example = CONFIG_EXAMPLE_ALT
        if example:
            shutil.copy(example, CONFIG_FILE)
            session_log.write(f"[INFO] 默认配置已复制到: {CONFIG_FILE}")
        else:
            session_log.write(f"[WARN] 未找到示例: {CONFIG_EXAMPLE}")
    if not os.path.isfile(CONFIG_FILE):
        session_log.write(f"[WARN] 配置文件不存在: {CONFIG_FILE}")
        return None
    return CONFIG_FILE


def load_config_content():
    """加载配置文件内容"""
    path = get_config_path()
    if path:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return ""


def get_download_folder():
    """根据 config.yaml 的 alac-save-folder 拼接实际下载目录"""
    try:
        content = load_config_content()
        m = re.search(r'^alac-save-folder:\s*"?([^"\n\r]+)"?\s*$', content, re.MULTILINE)
        if m:
            folder = m.group(1).strip()
            if folder:
                return os.path.join(os.path.expanduser("~"), "Downloads", folder)
    except Exception:
        pass
    return DOWNLOAD_DIR


FONT_FAMILY = "Microsoft YaHei"
MONO_FAMILY = "Consolas"
APP_ICON = os.path.join(DATA_DIR, "assets", "app_icon.ico")

LOG_DIR = os.path.join(APP_DATA_DIR, "log")


class SessionLogger:
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
        "start_docker": "启动 Docker",
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
        "status_title": "系统状态",
        "status_refresh": "刷新",
        "s_docker": "Docker",
        "s_images": "镜像",
        "s_wrapper": "Wrapper 容器",
        "s_login": "登录",
        "s_paths": "路径",
        "docker_installed": "Docker 已安装",
        "docker_running": "Docker 守护进程",
        "wrapper_image": "Wrapper 镜像",
        "dl_image": "下载器镜像",
        "wrapper_container": "容器运行状态",
        "wrapper_ports": "端口映射",
        "login_cached": "凭据缓存",
        "config_path_label": "配置文件",
        "log_path_label": "日志目录",
        "wrapper_data_path_label": "Wrapper 数据",
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
        "use_local_image_title": "本地镜像",
        "use_local_image_msg": "检测到需要构建 Docker 镜像。\n\n是否使用本地 .tar 镜像文件导入？\n\n选择「是」将打开目录选择器，\n选择「否」将从源码构建镜像。",
        "select_image_dir_title": "选择镜像目录",
        "export_images": "导出镜像",
        "export_done": "导出完成",
        "export_failed": "导出失败",
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
        "rename_tpl_track": "编号. 音乐名",
        "rename_tpl_artist": "歌手 - 音乐名",
    },
    "en": {
        "app_title": "Apple Music Downloader",
        "brand": "Apple Music",
        "product": "ALAC Downloader",
        "checking": "Checking environment...",
        "retry": "Retry",
        "start_docker": "Start Docker",
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
        "status_title": "System Status",
        "status_refresh": "Refresh",
        "s_docker": "Docker",
        "s_images": "Images",
        "s_wrapper": "Wrapper Container",
        "s_login": "Login",
        "s_paths": "Paths",
        "docker_installed": "Docker Installed",
        "docker_running": "Docker Daemon",
        "wrapper_image": "Wrapper Image",
        "dl_image": "Downloader Image",
        "wrapper_container": "Container Status",
        "wrapper_ports": "Port Mapping",
        "login_cached": "Cached Credentials",
        "config_path_label": "Config File",
        "log_path_label": "Log Directory",
        "wrapper_data_path_label": "Wrapper Data",
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
        "use_local_image_title": "Local Image",
        "use_local_image_msg": "Docker images need to be built.\n\nUse local .tar image files instead?\n\nClick 'Yes' to select a directory,\nclick 'No' to build from source.",
        "select_image_dir_title": "Select Image Directory",
        "export_images": "Export Images",
        "export_done": "Export Done",
        "export_failed": "Export Failed",
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
        "rename_tpl_track": "TrackNumber. SongName",
        "rename_tpl_artist": "Artist - SongName",
    },
}

DEFAULT_LANG = "zh"

# Prevent subprocess console windows on Windows
_SI = subprocess.STARTUPINFO()
_SI.dwFlags |= subprocess.STARTF_USESHOWWINDOW
_SI.wShowWindow = subprocess.SW_HIDE
_CF = subprocess.CREATE_NO_WINDOW


def _run(*args, capture=True, silent=True, check=False):
    try:
        r = subprocess.run(list(args), capture_output=capture, text=True,
                           encoding="utf-8", errors="replace", check=check,
                           startupinfo=_SI, creationflags=_CF)
        return r.stdout.strip()
    except Exception:
        return ""


def _live(*args):
    return subprocess.run(list(args), check=False,
                          startupinfo=_SI, creationflags=_CF).returncode


def wrapper_running():
    out = _run("docker", "ps", "-q", "-f", f"name={WRAPPER_NAME}", silent=True)
    return len(out) > 0


def load_docker_image(tar_path, log_callback=None):
    """Load a Docker image from a local .tar file."""
    if not os.path.isfile(tar_path):
        msg = f"File not found: {tar_path}"
        if log_callback:
            log_callback(f"[ERROR] {msg}")
        return False, msg
    if log_callback:
        log_callback(f"Loading image from: {tar_path}")
    try:
        result = subprocess.run(
            ["docker", "load", "-i", tar_path],
            capture_output=True, text=True,
            startupinfo=_SI, creationflags=_CF
        )
        if result.returncode == 0:
            msg = result.stdout.strip()
            if log_callback:
                log_callback(f"[OK] {msg}")
            return True, msg
        else:
            err = result.stderr.strip() or result.stdout.strip()
            if log_callback:
                log_callback(f"[ERROR] docker load failed: {err[:500]}")
            return False, err[:500]
    except Exception as e:
        msg = str(e)
        if log_callback:
            log_callback(f"[ERROR] {msg}")
        return False, msg


def load_images_from_dir(image_dir, log_callback=None):
    """Load all .tar files from a directory as Docker images."""
    if not os.path.isdir(image_dir):
        if log_callback:
            log_callback(f"[ERROR] Directory not found: {image_dir}")
        return
    tar_files = sorted([f for f in os.listdir(image_dir) if f.endswith('.tar')])
    if not tar_files:
        if log_callback:
            log_callback(f"[WARN] No .tar files found in: {image_dir}")
        return
    if log_callback:
        log_callback(f"Found {len(tar_files)} .tar file(s) in: {image_dir}")
    for tf in tar_files:
        load_docker_image(os.path.join(image_dir, tf), log_callback)
    _auto_tag_images(log_callback)


def _get_all_image_repos():
    try:
        out = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True, text=True,
            startupinfo=_SI, creationflags=_CF
        )
        return set(line.strip() for line in out.stdout.strip().split('\n') if line.strip())
    except Exception:
        return set()


def _auto_tag_images(log_callback=None):
    tag_map = [
        (WRAPPER_IMAGE, ["wrapper"]),
        (DL_IMAGE, ["apple-music-downloader", "am-downloader", "downloader"]),
    ]
    for target, hints in tag_map:
        if _run("docker", "images", "-q", target, silent=True):
            continue
        for repo_tag in _get_all_image_repos():
            if repo_tag == target:
                continue
            if any(h in repo_tag.lower() for h in hints):
                if log_callback:
                    log_callback(f"Auto-tagging {repo_tag} -> {target}")
                _live("docker", "tag", repo_tag, target)
                break


def export_images(output_dir=None, log_callback=None):
    if output_dir is None:
        output_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(output_dir, exist_ok=True)
    wrapper_tar = os.path.join(output_dir, "wrapper_local.tar")
    dl_tar = os.path.join(output_dir, "apple-music-downloader_local.tar")
    all_ok = True
    for image, tar_path, label in [
        (WRAPPER_IMAGE, wrapper_tar, "Wrapper"),
        (DL_IMAGE, dl_tar, "Downloader"),
    ]:
        if not _run("docker", "images", "-q", image, silent=True):
            if log_callback:
                log_callback(f"[WARN] Image '{image}' not found, skipping")
            all_ok = False
            continue
        if log_callback:
            log_callback(f"Exporting {label}: {image} -> {tar_path}")
        code = _live("docker", "save", "-o", tar_path, image)
        if code == 0:
            if log_callback:
                log_callback(f"[OK] Exported: {tar_path}")
        else:
            if log_callback:
                log_callback(f"[ERROR] Failed to export {image}")
            all_ok = False
    if all_ok and log_callback:
        log_callback(f"[OK] All images exported to: {output_dir}")
    return all_ok


def build_wrapper_image(log_callback=None):
    src = WRAPPER_SRC
    if not os.path.isdir(src):
        return False, f"Wrapper source not found: {src}"
    dockerfile = os.path.join(src, "Dockerfile")
    if not os.path.isfile(dockerfile):
        return False, f"{src} must contain Dockerfile"
    if log_callback:
        log_callback(f"Building wrapper image from: {src}")
        log_callback(f"  REGISTRY_MIRROR={REGISTRY_MIRROR}")
    err_lines = []
    proc = subprocess.Popen(["docker", "build",
        "--build-arg", f"REGISTRY_MIRROR={REGISTRY_MIRROR}",
        "--tag", WRAPPER_IMAGE, src],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        startupinfo=_SI, creationflags=_CF)
    for line in proc.stdout:
        line = line.strip()
        if line:
            if log_callback:
                log_callback(line)
            err_lines.append(line)
    proc.wait()
    if proc.returncode != 0:
        err = "\n".join(err_lines[-10:]) or "Unknown error"
        return False, f"Build failed: {err[:500]}"
    return True, f"Wrapper image built: {WRAPPER_IMAGE}"


def wrapper_login(username, password, log_callback=None):
    if log_callback:
        log_callback("Starting login container...")
    os.makedirs(WRAPPER_DATA_DIR, exist_ok=True)
    _run("docker", "rm", "-f", f"{WRAPPER_NAME}-login", silent=True)
    db_file = os.path.join(
        os.path.abspath(WRAPPER_DATA_DIR),
        "data", "com.apple.android.music", "files", "mpl_db", "kvs.sqlitedb"
    )
    if os.path.isfile(db_file):
        os.remove(db_file)
    if log_callback:
        log_callback("Launching wrapper login container...")
    code = _live(
        "docker", "run", "-dit",
        "--name", f"{WRAPPER_NAME}-login",
        "--privileged",
        "-v", f"{os.path.abspath(WRAPPER_DATA_DIR)}:/app/rootfs/data",
        "-e", f"USERNAME={username}",
        "-e", f"PASSWORD={password}",
        "--entrypoint", "/bin/sh",
        WRAPPER_IMAGE,
        "-c", "mkdir -p /app/rootfs/system/usr/share/zoneinfo /app/rootfs/etc; cp /usr/share/zoneinfo/tzdata.zi /app/rootfs/system/usr/share/zoneinfo/tzdata; cp /etc/hosts /app/rootfs/etc/hosts; cp /etc/resolv.conf /app/rootfs/etc/resolv.conf; export ANDROID_ROOT=/app/rootfs/system; export ANDROID_DATA=/app/rootfs/data; mkdir -p /app/rootfs/data/data/com.apple.android.music/files/mpl_db; exec /app/wrapper -L ${USERNAME}:${PASSWORD} -F -H 0.0.0.0",
    )
    if code != 0:
        return False, "Failed to start login container"
    if log_callback:
        log_callback("Waiting for credential database...")
    waited = 0
    last_lines = 0
    while not os.path.isfile(db_file) and waited < 120:
        time.sleep(2)
        waited += 2
        if log_callback:
            out = _run("docker", "logs", f"{WRAPPER_NAME}-login", silent=True)
            if out:
                lines = out.split('\n')
                if len(lines) > last_lines:
                    for line in lines[last_lines:]:
                        s = line.strip()
                        if s:
                            log_callback(s)
                    last_lines = len(lines)
    if not os.path.isfile(db_file):
        exit_code = _run("docker", "inspect", "-f", "{{.State.ExitCode}}", f"{WRAPPER_NAME}-login", silent=True)
        logs = _run("docker", "logs", f"{WRAPPER_NAME}-login")
        if log_callback:
            log_callback(f"[ERROR] Login failed (exit={exit_code})")
            if logs:
                lines = logs.split('\n')
                unseen = lines[last_lines:] if len(lines) > last_lines else lines
                for line in unseen:
                    s = line.strip()
                    if s:
                        log_callback(s)
        _run("docker", "rm", "-f", f"{WRAPPER_NAME}-login", silent=True)
        return False, f"Login failed (exit={exit_code}). {logs}"
    if log_callback:
        log_callback("[OK] Credential database created")
    fsi_file = os.path.join(
        os.path.abspath(WRAPPER_DATA_DIR),
        "data", "com.apple.android.music", "files", "fsi.pdat"
    )
    if log_callback:
        log_callback("Waiting for FairPlay registration...")
    waited = 0
    last_lines = 0
    while not os.path.isfile(fsi_file) and waited < 120:
        time.sleep(2)
        waited += 2
        if log_callback:
            out = _run("docker", "logs", f"{WRAPPER_NAME}-login", silent=True)
            if out:
                lines = out.split('\n')
                if len(lines) > last_lines:
                    for line in lines[last_lines:]:
                        s = line.strip()
                        if s:
                            log_callback(s)
                    last_lines = len(lines)
    _run("docker", "rm", "-f", f"{WRAPPER_NAME}-login", silent=True)
    if os.path.isfile(fsi_file):
        if log_callback:
            log_callback("[OK] FairPlay registered")
        return True, "Login successful. Credentials cached."
    if log_callback:
        log_callback("[WARN] FairPlay not registered, may retry on first download")
    return False, "Login may have failed."


def do_start_wrapper(log_callback=None):
    if wrapper_running():
        return True, "Wrapper is already running"
    os.makedirs(WRAPPER_DATA_DIR, exist_ok=True)
    data_dir = os.path.abspath(WRAPPER_DATA_DIR)
    if not _run("docker", "images", "-q", WRAPPER_IMAGE, silent=True):
        return False, f"Wrapper image '{WRAPPER_IMAGE}' not found"
    db_file = os.path.join(data_dir, "data", "com.apple.android.music", "files", "mpl_db", "kvs.sqlitedb")
    if not os.path.isfile(db_file):
        return False, "NEED_LOGIN"
    _run("docker", "rm", "-f", WRAPPER_NAME, silent=True)
    if log_callback:
        log_callback("Launching wrapper container...")
    code = _live(
        "docker", "run", "-dit",
        "--name", WRAPPER_NAME,
        "--privileged",
        "-v", f"{data_dir}:/app/rootfs/data",
        "-p", f"{DECRYPT_PORT}:{DECRYPT_PORT}",
        "-p", f"{M3U8_PORT}:{M3U8_PORT}",
        "-p", f"{ACCOUNT_PORT}:{ACCOUNT_PORT}",
        "--entrypoint", "/bin/sh",
        WRAPPER_IMAGE,
        "-c", "mkdir -p /app/rootfs/system/usr/share/zoneinfo /app/rootfs/etc; cp /usr/share/zoneinfo/tzdata.zi /app/rootfs/system/usr/share/zoneinfo/tzdata; cp /etc/hosts /app/rootfs/etc/hosts; cp /etc/resolv.conf /app/rootfs/etc/resolv.conf; export ANDROID_ROOT=/app/rootfs/system; export ANDROID_DATA=/app/rootfs/data; exec /app/wrapper -H 0.0.0.0",
    )
    if code != 0:
        return False, "Failed to start wrapper"
    if log_callback:
        log_callback("Waiting for wrapper to initialize...")
    last_lines = 0
    for _ in range(8):
        time.sleep(2)
        if wrapper_running():
            # stream any remaining logs
            if log_callback:
                out = _run("docker", "logs", WRAPPER_NAME, silent=True)
                if out:
                    lines = out.split('\n')
                    if len(lines) > last_lines:
                        for line in lines[last_lines:]:
                            s = line.strip()
                            if s:
                                log_callback(s)
        if log_callback:
            out = _run("docker", "logs", WRAPPER_NAME, silent=True)
            if out:
                lines = out.split('\n')
                if len(lines) > last_lines:
                    for line in lines[last_lines:]:
                        s = line.strip()
                        if s:
                            log_callback(s)
                    last_lines = len(lines)
    if wrapper_running():
        return True, f"Wrapper running (ports: {DECRYPT_PORT}/{M3U8_PORT}/{ACCOUNT_PORT})"
    else:
        logs = _run("docker", "logs", WRAPPER_NAME)
        if log_callback and logs:
            for line in logs.split('\n'):
                s = line.strip()
                if s:
                    log_callback(s)
        if os.path.isfile(db_file):
            os.remove(db_file)
        return False, f"NEED_LOGIN\n{logs}"


def stop_wrapper():
    _run("docker", "rm", "-f", f"{WRAPPER_NAME}-login", silent=True)
    if wrapper_running():
        _run("docker", "rm", "-f", WRAPPER_NAME, silent=True)


def build_downloader_image(log_callback=None):
    src = DL_SRC
    if not os.path.isdir(src):
        return False, f"Downloader source not found: {src}"
    dockerfile = os.path.join(src, "Dockerfile")
    if not os.path.isfile(dockerfile):
        return False, f"{src} must contain Dockerfile"
    if log_callback:
        log_callback(f"Building downloader image from: {src}")
        log_callback(f"  REGISTRY_MIRROR={REGISTRY_MIRROR}")
    err_lines = []
    proc = subprocess.Popen(["docker", "build",
        "--build-arg", f"REGISTRY_MIRROR={REGISTRY_MIRROR}",
        "--tag", DL_IMAGE, src],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        startupinfo=_SI, creationflags=_CF)
    for line in proc.stdout:
        line = line.strip()
        if line:
            if log_callback:
                log_callback(line)
            err_lines.append(line)
    proc.wait()
    if proc.returncode != 0:
        err = "\n".join(err_lines[-10:]) or "Unknown error"
        return False, f"Build failed: {err[:500]}"
    return True, f"Downloader image built: {DL_IMAGE}"


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
        for F in (SetupPage, LoginPage, TabbedContainer):
            frame = F(self.container, self)
            self.frames[F.__name__] = frame
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.show_frame("SetupPage")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        get_config_path()

        self._make_layered_window()

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
        stop_wrapper()
        session_log.close()
        self.destroy()

    def show_frame(self, name):
        frame = self.frames[name]
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

        self.start_docker_btn = ctk.CTkButton(container, text=self.t("start_docker"),
                                               fg_color=c["primary"],
                                               hover_color=c["primary_hover"],
                                               corner_radius=10,
                                               font=ctk.CTkFont(family=f, size=13),
                                               command=self._start_docker)
        self.start_docker_btn.pack(pady=8)
        self.start_docker_btn.pack_forget()
        self._reg(self.start_docker_btn, "start_docker")

    def on_show(self):
        if not self.app.setup_done:
            self.start_setup()

    def log(self, msg):
        session_log.write(msg)
        if self.log_text:
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")

    def set_status(self, msg):
        if self.status_label:
            self.status_label.configure(text=msg)

    def set_progress(self, val):
        if self.progress:
            self.progress.set(val)

    def _start_docker(self):
        self.start_docker_btn.pack_forget()
        self._try_launch_docker()
        threading.Thread(target=self._wait_docker_and_continue, daemon=True).start()

    def start_setup(self):
        self.log_text.delete("1.0", "end")
        self.set_progress(0)
        self.retry_btn.pack_forget()
        self.start_docker_btn.pack_forget()

        # Check Docker daemon, auto-start if needed
        if subprocess.call(["docker", "info"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           startupinfo=_SI, creationflags=_CF) != 0:
            self.log("Docker daemon not running, attempting to start...")
            self.set_status("Starting Docker Desktop...")
            self._try_launch_docker()
            threading.Thread(target=self._wait_docker_and_continue, daemon=True).start()
            return

        self.log("Docker OK")
        self._continue_setup()

    def _try_launch_docker(self):
        docker_exe = os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"),
                                  "Docker", "Docker", "Docker Desktop.exe")
        if not os.path.isfile(docker_exe):
            docker_exe = os.path.join(os.environ.get("LocalAppData", ""),
                                      "Docker", "Docker Desktop.exe")
        if os.path.isfile(docker_exe):
            subprocess.Popen([docker_exe], startupinfo=_SI, creationflags=_CF)
        else:
            self.log("Docker Desktop not found at known paths")

    def _wait_docker_and_continue(self):
        for i in range(60):
            time.sleep(2)
            if subprocess.call(["docker", "info"],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,
                               startupinfo=_SI, creationflags=_CF) == 0:
                self.after(0, lambda: self.log("Docker is ready"))
                self.after(0, self._continue_setup)
                return
        self.after(0, lambda: self.log("Docker did not start in time"))
        self.after(0, lambda: self.set_status("Docker failed to start"))
        self.after(0, lambda: self.start_docker_btn.pack(pady=8))

    def _continue_setup(self):
        need_wrapper = not _run("docker", "images", "-q", WRAPPER_IMAGE, silent=True)
        need_downloader = not _run("docker", "images", "-q", DL_IMAGE, silent=True)

        if not (need_wrapper or need_downloader):
            threading.Thread(target=self._run_setup, daemon=True).start()
            return

        self.after(200, self._prompt_local_image)

    def _prompt_local_image(self):
        from tkinter import messagebox
        answer = messagebox.askyesno(
            self.t("use_local_image_title"),
            self.t("use_local_image_msg")
        )
        if answer:
            from tkinter import filedialog
            image_dir = filedialog.askdirectory(
                title=self.t("select_image_dir_title")
            )
            if image_dir:
                self.log(f"Loading images from: {image_dir}")
                self.set_status("Loading local Docker images...")
                threading.Thread(target=self._load_images_and_setup, args=(image_dir,), daemon=True).start()
                return

        # User said no or cancelled - proceed with normal setup
        threading.Thread(target=self._run_setup, daemon=True).start()

    def _load_images_and_setup(self, image_dir):
        load_images_from_dir(image_dir, self.log)
        self.after(0, lambda: self.set_status("Image loading done, starting checks..."))
        self._run_setup()

    def _run_setup(self):
        steps = [
            ("Build Wrapper Image", self._check_wrapper),
            ("Build Downloader Image", self._check_downloader),
            ("Start Wrapper", self._start_wrapper),
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
                    if "daemon" in msg:
                        self.after(0, lambda: self.start_docker_btn.pack(pady=8))
                    else:
                        self.after(0, lambda: self.retry_btn.pack(pady=8))
                    return
            except Exception as e:
                self.log(f"Error: {e}")
                self.set_status(f"ERROR: {name}")
                self.after(0, lambda: self.retry_btn.pack(pady=8))
                return
            self.set_progress((i + 1) / total)

        self.app.setup_done = True
        self.set_status("All checks passed")
        self.log("Environment ready. Launching...")
        self.set_progress(1.0)
        self.after(600, self.go_next)

    def _check_docker(self):
        if subprocess.call(["docker", "--version"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           startupinfo=_SI, creationflags=_CF) != 0:
            return False, "Docker not installed or not in PATH"
        if subprocess.call(["docker", "info"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           startupinfo=_SI, creationflags=_CF) != 0:
            return False, "Docker daemon not running - start Docker Desktop first"
        return True, "Docker OK"

    def _check_wrapper(self):
        if not _run("docker", "images", "-q", WRAPPER_IMAGE, silent=True):
            ok, msg = build_wrapper_image(self.log)
            if not ok:
                return False, msg
        return True, "Wrapper image ready"

    def _check_downloader(self):
        if not _run("docker", "images", "-q", DL_IMAGE, silent=True):
            ok, msg = build_downloader_image(self.log)
            if not ok:
                return False, msg
        return True, "Downloader image ready"

    def _start_wrapper(self):
        ok, msg = do_start_wrapper(self.log)
        if "NEED_LOGIN" in msg:
            return True, "Login required"
        if not ok:
            return False, msg
        self.app.wrapper_ready = True
        return True, msg

    def go_next(self):
        session_log._history.clear()
        db_file = os.path.join(
            os.path.abspath(WRAPPER_DATA_DIR),
            "data", "com.apple.android.music", "files", "mpl_db", "kvs.sqlitedb"
        )
        if not os.path.isfile(db_file):
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
            self.log_text.configure(state="normal")
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
        ok, msg = wrapper_login(username, password, log_callback=self.log)
        self.after(0, lambda: self._login_done(ok, msg))

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
    ("album",       "专辑",            ""),
    ("song",        "单曲",            "--song {url}"),
    ("playlist",    "播放列表",        ""),
    ("atmos",       "杜比全景声",      "--atmos {url}"),
    ("aac",         "AAC",             "--aac --aac-type {aac_type} {url}"),
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
            self._scroll_btn.configure(text="▼")
        else:
            self.console.see("end")
            self._scroll_btn.configure(text="▲")
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
        self._update_status()
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
        try:
            self._update_status()
        except Exception:
            pass
        self._status_timer = self.after(3000, self._poll_status)

    def _update_status(self):
        try:
            running = wrapper_running()
            c = self.app.colors
            if hasattr(self, 'wrapper_dot') and self.wrapper_dot.winfo_exists():
                dot_color = c["success"] if running else c["error"]
                self.wrapper_dot.configure(fg_color=dot_color)
                ports = f"{DECRYPT_PORT}:{M3U8_PORT}:{ACCOUNT_PORT}"
                status_text = self.t("running_status", ports=ports) if running else self.t("stopped")
                self._status_text.configure(text=status_text)
        except Exception:
            pass

    def _mode_name(self, key):
        i18n_map = {"album": "mode_album", "song": "mode_song", "playlist": "mode_playlist",
                    "atmos": "mode_atmos", "aac": "mode_aac"}
        return self.t(i18n_map.get(key, key))

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
            if not self.app.wrapper_ready:
                ok, msg = do_start_wrapper()
                if not ok:
                    if "NEED_LOGIN" in msg:
                        self.app.show_frame("LoginPage")
                        return False
                    self.log(f"[ERROR] {msg}")
                    return False
                self.app.wrapper_ready = True
            else:
                ok, msg = do_start_wrapper()
                if not ok:
                    if "NEED_LOGIN" in msg:
                        self.app.show_frame("LoginPage")
                    else:
                        self.log(f"[ERROR] {msg}")
                    return False
        if not _run("docker", "images", "-q", DL_IMAGE, silent=True):
            self.log("[ERROR] Downloader image not found")
            return False
        return True

    def _start_download(self):
        if self._downloading:
            self._cancel_download()
            return

        key = self._mode_var.get()
        spec = next(m for m in MODE_SPECS if m[0] == key)
        tmpl = spec[2]

        title = None
        if key == "aac":
            url = self._url_var.get().strip()
            if not url:
                return
            aac_type = self._extra_widgets[1].get() if len(self._extra_widgets) >= 2 else "aac-lc"
            args = tmpl.format(aac_type=aac_type, url=url)
            title = f"AAC ({aac_type})"
        elif key == "song":
            url = self._url_var.get().strip()
            if not url:
                return
            args = f"--song {url}"
            title = "单曲"
        else:
            url = self._url_var.get().strip()
            if not url:
                return
            args = tmpl.format(url=url) if tmpl else url
            title = spec[1]

        if not self._ensure_prereqs():
            return
        self.log(f">>> {title}")
        self._downloading = True
        self._go_btn.configure(fg_color=self.c("error"), hover_color="#CC2F26",
                               text=self.t("running_btn"))
        threading.Thread(target=self._dl_thread, args=(args,), daemon=True).start()

    def _cancel_download(self):
        if self._dl_proc and self._dl_proc.poll() is None:
            self._dl_proc.kill()
            self.log("[CANCEL] Download cancelled")
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
        config_path = get_config_path()
        if config_path:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_content = f.read()
        else:
            self.log("[WARN] No config.yaml found, using defaults")
            config_content = ""

        for folder_key in ['alac-save-folder', 'atmos-save-folder', 'aac-save-folder', 'mv-save-folder']:
            config_content = re.sub(
                rf'^({folder_key}:\s*)"?([^"\n]+)"?',
                rf'\1"/downloads/\2"',
                config_content,
                flags=re.MULTILINE,
            )
        config_content = config_content.replace("127.0.0.1:10020", "host.docker.internal:10020")
        config_content = config_content.replace("127.0.0.1:20020", "host.docker.internal:20020")

        dl_args = arguments.split()

        for attempt in range(1, 4):
            if attempt > 1:
                self.log(f"[RETRY] Attempt {attempt}/3...")
                time.sleep(2)

            fd, tmp_config = tempfile.mkstemp(suffix='.yaml', prefix='am_config_')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(config_content)

            try:
                proc = subprocess.Popen(
                    ["docker", "run", "--rm",
                     "-v", f"{DOWNLOAD_DIR}:/downloads",
                     "-v", f"{tmp_config}:/app/config.yaml",
                     DL_IMAGE] + dl_args,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace",
                                        startupinfo=_SI, creationflags=_CF)
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
            finally:
                try:
                    os.remove(tmp_config)
                except Exception:
                    pass

        self.log(f"Done - output: {get_download_folder()}")
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
            ("s_docker", [
                ("docker-installed", "docker_installed"),
                ("docker-running", "docker_running"),
            ]),
            ("s_images", [
                ("wrapper-image", "wrapper_image"),
                ("downloader-image", "dl_image"),
            ]),
            ("s_wrapper", [
                ("wrapper-container", "wrapper_container"),
                ("wrapper-ports", "wrapper_ports"),
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
            if section_key == "s_images":
                export_row = ctk.CTkFrame(card, fg_color="transparent", height=32)
                export_row.pack(fill="x", padx=10, pady=3)
                export_row.pack_propagate(False)
                self._export_btn = ctk.CTkButton(export_row, text=self.t("export_images"),
                                                 fg_color=c["primary"], hover_color=c["primary_hover"],
                                                 text_color="white",
                                                 font=ctk.CTkFont(family=f, size=12),
                                                 corner_radius=6, height=26,
                                                 command=self._export_images)
                self._export_btn.pack(side="left")
                self._reg(self._export_btn, "export_images")

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
            ("wrapper-data-path", "wrapper_data_path_label", WRAPPER_DATA_DIR),
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

        docker_ver = _run("docker", "--version", silent=True)
        results["docker-installed"] = (docker_ver != "", docker_ver.replace("Docker version ", "") if docker_ver else self.t("not_installed"))

        docker_info = _run("docker", "info", silent=True)
        results["docker-running"] = (docker_info != "", self.t("running") if docker_info else self.t("not_running"))

        wrapper_img = _run("docker", "images", "-q", WRAPPER_IMAGE, silent=True)
        results["wrapper-image"] = (wrapper_img != "", wrapper_img[:12] if wrapper_img else self.t("not_built"))

        dl_img = _run("docker", "images", "-q", DL_IMAGE, silent=True)
        results["downloader-image"] = (dl_img != "", dl_img[:12] if dl_img else self.t("not_built"))

        wrapper_ok = wrapper_running()
        results["wrapper-container"] = (wrapper_ok, self.t("running") if wrapper_ok else self.t("stopped"))

        ports_text = f"{DECRYPT_PORT} / {M3U8_PORT} / {ACCOUNT_PORT}" if wrapper_ok else "—"
        results["wrapper-ports"] = (wrapper_ok, ports_text)

        db_file = os.path.join(os.path.abspath(WRAPPER_DATA_DIR),
                               "data", "com.apple.android.music", "files", "mpl_db", "kvs.sqlitedb")
        has_login = os.path.isfile(db_file)
        results["login-cached"] = (has_login, self.t("logged_in") if has_login else self.t("not_logged_in"))

        def update():
            for key, (ok, text) in results.items():
                if key in self._items:
                    dot, label = self._items[key]
                    dot.configure(fg_color=c["success"] if ok else c["error"])
                    label.configure(text=text)
            for key, lbl in self._path_labels.items():
                path_map = {
                    "config-path": CONFIG_FILE,
                    "log-path": LOG_DIR,
                    "wrapper-data-path": WRAPPER_DATA_DIR,
                }
                if key in path_map:
                    lbl.configure(text=path_map[key])
        self.after(0, update)

    def _restart_wrapper(self):
        self._restart_btn.configure(state="disabled", text=self.t("wrapper_restarting"))
        stop_wrapper()
        threading.Thread(target=self._do_restart_wrapper, daemon=True).start()

    def _do_restart_wrapper(self):
        ok, msg = do_start_wrapper()
        self.after(0, lambda: self._restart_btn.configure(
            state="normal", text=self.t("wrapper_restart")
        ))
        self.after(0, self._refresh)

    def _export_images(self):
        from tkinter import filedialog
        image_dir = filedialog.askdirectory(title=self.t("select_image_dir_title"))
        if not image_dir:
            return
        self._export_btn.configure(state="disabled", text="...")
        threading.Thread(target=lambda: self._do_export(image_dir), daemon=True).start()

    def _do_export(self, output_dir):
        ok = export_images(output_dir, log_callback=None)
        self.after(0, lambda: self._export_btn.configure(
            state="normal", text=self.t("export_done") if ok else self.t("export_failed")
        ))
        if ok:
            self.after(3000, lambda: self._export_btn.configure(
                state="normal", text=self.t("export_images")
            ))

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

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.log("[WARN] ffmpeg/ffprobe not found, attempting winget install...")
            self._converting = True
            self._convert_btn.configure(state="disabled", text=self.t("convert_running"))
            threading.Thread(target=self._try_install_ffmpeg, daemon=True).start()
            return

        self._converting = True
        self._convert_btn.configure(state="disabled", text=self.t("convert_running"))
        threading.Thread(target=self._do_convert, daemon=True).start()

    def _try_install_ffmpeg(self):
        try:
            result = subprocess.run(
                ["winget", "install", "--id", "Gyan.FFmpeg", "--accept-source-agreements", "--accept-package-agreements", "--silent"],
                capture_output=True, text=True,
                startupinfo=_SI, creationflags=_CF,
                timeout=120
            )
            if result.returncode == 0:
                self.after(0, lambda: self.log("[OK] ffmpeg installed, please restart convert"))
            else:
                self.after(0, lambda: self.log("[ERROR] winget install failed"))
                self.after(0, lambda: self.log("[INFO] Install ffmpeg manually: https://ffmpeg.org/download.html"))
        except FileNotFoundError:
            self.after(0, lambda: self.log("[ERROR] winget not found"))
            self.after(0, lambda: self.log("[INFO] Install ffmpeg manually: https://ffmpeg.org/download.html"))
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
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"

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
                self.after(0, lambda: self.log("[INFO] Install ffmpeg or place flac.exe in assets/"))
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
        ffprobe = shutil.which("ffprobe") or "ffprobe"
        selected_fmt = self._format_var.get()
        is_track = selected_fmt == self.t("rename_tpl_track")
        self.after(0, lambda: self.log(self.t("rename_scanning")))

        files = []
        try:
            for root, dirs, filenames in os.walk(self._source_dir):
                for f in sorted(filenames):
                    ext = os.path.splitext(f)[1].lower()
                    if ext in ('.flac', '.wav'):
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

            # Extract tags
            tags = {}
            try:
                p = subprocess.run(
                    [ffprobe, "-v", "error",
                     "-show_entries", "format_tags=ARTIST,TITLE",
                     "-of", "default=noprint_wrappers=1", src],
                    capture_output=True, text=True,
                    startupinfo=_SI, creationflags=_CF
                )
                if p.returncode == 0 and p.stdout.strip():
                    for line in p.stdout.strip().split('\n'):
                        upper = line.upper()
                        if upper.startswith("TAG:ARTIST="):
                            tags["ARTIST"] = line.split("=", 1)[1].strip()
                        elif upper.startswith("TAG:TITLE="):
                            tags["TITLE"] = line.split("=", 1)[1].strip()
            except Exception:
                pass

            artist = tags.get("ARTIST", "")
            title = tags.get("TITLE", "")

            if is_track:
                if not title:
                    self.after(0, lambda n=name: self.log(self.t("rename_no_tag", file=n)))
                    continue
                track_num = os.path.splitext(name)[0].split('.')[0]
                new_base = track_num + ". " + title
            else:
                if not artist or not title:
                    self.after(0, lambda n=name: self.log(self.t("rename_no_tag", file=n)))
                    continue
                new_base = artist + " - " + title

            new_name = new_base + ext
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


def main():
    app = AppleMusicApp()
    app.mainloop()


if __name__ == "__main__":
    main()

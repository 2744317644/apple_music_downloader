#!/usr/bin/env python3
"""Apple Music ALAC Downloader - GUI
Requires: Python 3.7+, Docker, customtkinter
"""

import os
import re
import sys
import time
import queue
import atexit
import tempfile
import threading
import subprocess
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
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.yaml")

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

FONT_FAMILY = None
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
    os.makedirs(WRAPPER_DATA_DIR, exist_ok=True)
    _run("docker", "rm", "-f", f"{WRAPPER_NAME}-login", silent=True)
    db_file = os.path.join(
        os.path.abspath(WRAPPER_DATA_DIR),
        "data", "com.apple.android.music", "files", "mpl_db", "kvs.sqlitedb"
    )
    if os.path.isfile(db_file):
        os.remove(db_file)
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
    waited = 0
    while not os.path.isfile(db_file) and waited < 120:
        time.sleep(2)
        waited += 2
    if not os.path.isfile(db_file):
        exit_code = _run("docker", "inspect", "-f", "{{.State.ExitCode}}", f"{WRAPPER_NAME}-login", silent=True)
        logs = _run("docker", "logs", f"{WRAPPER_NAME}-login")
        _run("docker", "rm", "-f", f"{WRAPPER_NAME}-login", silent=True)
        return False, f"Login failed (exit={exit_code}). {logs}"
    fsi_file = os.path.join(
        os.path.abspath(WRAPPER_DATA_DIR),
        "data", "com.apple.android.music", "files", "fsi.pdat"
    )
    waited = 0
    while not os.path.isfile(fsi_file) and waited < 120:
        time.sleep(2)
        waited += 2
    _run("docker", "rm", "-f", f"{WRAPPER_NAME}-login", silent=True)
    if os.path.isfile(fsi_file):
        return True, "Login successful. Credentials cached."
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
    time.sleep(15)
    if wrapper_running():
        return True, f"Wrapper running (ports: {DECRYPT_PORT}/{M3U8_PORT}/{ACCOUNT_PORT})"
    else:
        logs = _run("docker", "logs", WRAPPER_NAME)
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
        super().__init__()
        self.title("Apple Music Downloader")
        self.geometry("800x600")
        self.minsize(600, 450)

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

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.colors = APPLE_LIGHT
        self._setup_theme()

        self.wrapper_ready = False
        self.setup_done = False

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True)

        self.frames = {}
        for F in (SetupPage, LoginPage, MainPage):
            frame = F(self.container, self)
            self.frames[F.__name__] = frame
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.show_frame("SetupPage")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        stop_wrapper()
        session_log.close()
        self.destroy()

    def _setup_theme(self):
        self.configure(fg_color=self.colors["background"])

    def show_frame(self, name):
        frame = self.frames[name]
        frame.tkraise()
        if hasattr(frame, "on_show"):
            frame.on_show()



class AppPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app

    def c(self, key):
        return self.app.colors.get(key, "#000000")


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

        ctk.CTkLabel(container, text="Apple Music",
                     font=ctk.CTkFont(family=f, size=32, weight="bold"),
                     text_color=c["text"]).pack(pady=(40, 0))
        ctk.CTkLabel(container, text="ALAC Downloader",
                     font=ctk.CTkFont(family=f, size=20),
                     text_color=c["primary"]).pack()
        ctk.CTkLabel(container, text="Checking environment...",
                     font=ctk.CTkFont(family=f, size=14),
                     text_color=c["text_secondary"]).pack(pady=(16, 8))

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

        self.retry_btn = ctk.CTkButton(container, text="Retry",
                                       fg_color=c["primary"],
                                       hover_color=c["primary_hover"],
                                       corner_radius=10,
                                       font=ctk.CTkFont(family=f, size=13),
                                       command=self.start_setup)
        self.retry_btn.pack(pady=8)
        self.retry_btn.pack_forget()

        self.start_docker_btn = ctk.CTkButton(container, text="Start Docker",
                                              fg_color=c["primary"],
                                              hover_color=c["primary_hover"],
                                              corner_radius=10,
                                              font=ctk.CTkFont(family=f, size=13),
                                              command=self._start_docker)
        self.start_docker_btn.pack(pady=8)
        self.start_docker_btn.pack_forget()

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
        self.log("Starting Docker Desktop...")
        self.set_status("Waiting for Docker to start...")
        docker_exe = os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"),
                                  "Docker", "Docker", "Docker Desktop.exe")
        if not os.path.isfile(docker_exe):
            docker_exe = os.path.join(os.environ.get("LocalAppData", ""),
                                      "Docker", "Docker Desktop.exe")
        if os.path.isfile(docker_exe):
            subprocess.Popen([docker_exe], startupinfo=_SI, creationflags=_CF)
        else:
            self.log("Docker Desktop not found. Please start Docker manually.")
        threading.Thread(target=self._wait_docker, daemon=True).start()

    def _wait_docker(self):
        for _ in range(60):
            time.sleep(2)
            if subprocess.call(["docker", "info"],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,
                               startupinfo=_SI, creationflags=_CF) == 0:
                self.log("Docker is ready")
                self.after(0, self.start_setup)
                return
        self.log("Docker did not start in time")
        self.after(0, lambda: self.start_docker_btn.pack(pady=8))

    def start_setup(self):
        self.log_text.delete("1.0", "end")
        self.set_progress(0)
        self.retry_btn.pack_forget()
        self.start_docker_btn.pack_forget()
        threading.Thread(target=self._run_setup, daemon=True).start()

    def _run_setup(self):
        steps = [
            ("Docker", self._check_docker),
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
        db_file = os.path.join(
            os.path.abspath(WRAPPER_DATA_DIR),
            "data", "com.apple.android.music", "files", "mpl_db", "kvs.sqlitedb"
        )
        if not os.path.isfile(db_file):
            self.app.show_frame("LoginPage")
        else:
            self.app.show_frame("MainPage")


class LoginPage(AppPage):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.build_ui()

    def build_ui(self):
        c = self.app.colors
        f = FONT_FAMILY
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(expand=True, fill="both", padx=80, pady=60)

        ctk.CTkLabel(container, text="Sign In",
                     font=ctk.CTkFont(family=f, size=26, weight="bold"),
                     text_color=c["text"]).pack(pady=(40, 8))
        ctk.CTkLabel(container, text="Tips: 登录一次即可缓存凭据，无需重复输入",
                     font=ctk.CTkFont(family=f, size=13),
                     text_color=c["text_secondary"]).pack(pady=(0, 24))

        field_frame1 = ctk.CTkFrame(container, fg_color="transparent")
        field_frame1.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(field_frame1, text="Apple ID",
                     font=ctk.CTkFont(family=f, size=14),
                     text_color=c["text_secondary"]).pack(anchor="w", pady=(0, 2))
        self.username_entry = ctk.CTkEntry(field_frame1, height=46,
                                           corner_radius=10,
                                           fg_color=c["input_bg"],
                                           text_color=c["text"],
                                           border_color=c["border"],
                                           font=ctk.CTkFont(family=f, size=14),
                                           placeholder_text="example@icloud.com")
        self.username_entry.pack(fill="x")
        self.username_entry.bind("<Return>", lambda e: self.do_login())

        field_frame2 = ctk.CTkFrame(container, fg_color="transparent")
        field_frame2.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(field_frame2, text="Password",
                     font=ctk.CTkFont(family=f, size=14),
                     text_color=c["text_secondary"]).pack(anchor="w", pady=(0, 2))
        self.password_entry = ctk.CTkEntry(field_frame2, height=46,
                                           corner_radius=10,
                                           fg_color=c["input_bg"],
                                           text_color=c["text"],
                                           border_color=c["border"],
                                           show="\u2022",
                                           font=ctk.CTkFont(family=f, size=14),
                                           placeholder_text="Enter password")
        self.password_entry.pack(fill="x")
        self.password_entry.bind("<Return>", lambda e: self.do_login())

        self.login_btn = ctk.CTkButton(container, text="Sign In",
                                       width=340, height=42,
                                       fg_color=c["primary"],
                                       hover_color=c["primary_hover"],
                                       corner_radius=10,
                                       font=ctk.CTkFont(family=f, size=16, weight="bold"),
                                       command=self.do_login)
        self.login_btn.pack(pady=6)

        self.status_label = ctk.CTkLabel(container, text="",
                                          font=ctk.CTkFont(family=f, size=12),
                                          text_color=c["text_secondary"])
        self.status_label.pack(pady=8)

        self.progress = ctk.CTkProgressBar(container, width=340, height=4,
                                           progress_color=c["primary"],
                                           fg_color=c["divider"])
        self.progress.pack()
        self.progress.set(0)

    def on_show(self):
        self.status_label.configure(text="")
        self.progress.set(0)
        self.login_btn.configure(state="normal")

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
        ok, msg = wrapper_login(username, password, log_callback=None)
        self.after(0, lambda: self._login_done(ok, msg))

    def _login_done(self, ok, msg):
        self.progress.set(1.0)
        if ok:
            self.status_label.configure(text="Login successful", text_color=self.c("success"))
            ok2, _ = do_start_wrapper()
            self.app.wrapper_ready = ok2
            self.after(1000, lambda: self.app.show_frame("MainPage"))
        else:
            self.status_label.configure(text=msg, text_color=self.c("error"))
            self.login_btn.configure(state="normal")


MODE_SPECS = [
    ("album",       "专辑",            ""),
    ("song",        "单曲",            "--song {url}"),
    ("playlist",    "播放列表",        ""),
    ("atmos",       "杜比全景声",      "--atmos {url}"),
    ("aac",         "AAC",             "--aac --aac-type {aac_type} {url}"),
]


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
        self._popup_dismiss_id = None
        self._reposition_timer = None
        self.build_ui()

    def build_ui(self):
        c = self.app.colors
        f = FONT_FAMILY

        topbar = ctk.CTkFrame(self, fg_color=c["card"], height=44, corner_radius=0,
                              border_color=c["divider"], border_width=1)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        ctk.CTkLabel(topbar, text="Apple Music Downloader",
                     font=ctk.CTkFont(family=f, size=16, weight="bold"),
                     text_color=c["text"]).pack(side="left", padx=16, pady=11)

        right_frame = ctk.CTkFrame(topbar, fg_color="transparent")
        right_frame.pack(side="right", padx=6)

        self.wrapper_dot = ctk.CTkFrame(right_frame, width=10, height=10,
                                        corner_radius=5, fg_color=c["error"])
        self.wrapper_dot.pack(side="left", padx=(0, 4))
        ctk.CTkLabel(right_frame, text="Wrapper",
                     font=ctk.CTkFont(family=f, size=12),
                     text_color=c["text_secondary"]).pack(side="left", padx=(0, 8))

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
                                        width=150)
        self._mode_entry.pack(side="left", padx=(0, 8))
        self._mode_entry.insert(0, "专辑")
        self._mode_entry.configure(state="readonly")
        self._mode_entry.bind("<Button-1>", lambda e: self._show_mode_popup())

        self._url_var = ctk.StringVar()
        self._url_entry = ctk.CTkEntry(ctrl_row, height=36, corner_radius=8,
                                       fg_color=c["input_bg"], text_color=c["text"],
                                       border_color=c["border"],
                                       font=ctk.CTkFont(family=f, size=13),
                                       placeholder_text="粘贴 Apple Music 链接...",
                                       textvariable=self._url_var)
        self._url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._url_entry.bind("<Return>", lambda e: self._start_download())
        self._url_entry.bind("<Button-3>", self._paste_url)

        self._close_img = _make_close(color=c["text_secondary"])
        self._clear_btn = ctk.CTkButton(ctrl_row, text="", width=32, height=36,
                                        corner_radius=8, image=self._close_img,
                                        fg_color=c["input_bg"], hover_color=c["divider"],
                                        command=self._clear_url)
        self._clear_btn.pack(side="left", padx=(0, 8))

        self._go_btn = ctk.CTkButton(ctrl_row, text="Download", width=96, height=36,
                                     corner_radius=8,
                                     fg_color=c["primary"], hover_color=c["primary_hover"],
                                     text_color="white",
                                     font=ctk.CTkFont(family=f, size=14, weight="bold"),
                                     command=self._start_download)
        self._go_btn.pack(side="right")

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
        ctk.CTkLabel(footer, text="Output",
                     font=ctk.CTkFont(family=f, size=12, weight="bold"),
                     text_color=c["text"]).pack(side="left")
        ctk.CTkButton(footer, text="Clear", width=48, height=22,
                      fg_color=c["card"], hover_color=c["divider"],
                      text_color=c["text_secondary"], corner_radius=4,
                      font=ctk.CTkFont(family=f, size=10),
                      command=self._clear_console).pack(side="right")

        self.status_bar = ctk.CTkFrame(self, fg_color=c["card"], height=26, corner_radius=0,
                                       border_color=c["divider"], border_width=1)
        self.status_bar.pack(fill="x", side="bottom")
        self.status_bar.pack_propagate(False)

        self.status_text = ctk.CTkLabel(self.status_bar, text="Ready",
                                        font=ctk.CTkFont(family=f, size=11),
                                        text_color=c["text_secondary"])
        self.status_text.pack(side="left", padx=10, pady=2)

        self.output_path_label = ctk.CTkLabel(self.status_bar, text=f"Output: {DOWNLOAD_DIR}",
                                              font=ctk.CTkFont(family=f, size=10),
                                              text_color=c["text_secondary"])
        self.output_path_label.pack(side="right", padx=(0, 10), pady=2)

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
        os.startfile(DOWNLOAD_DIR)

    def _on_download_done(self):
        try:
            self._go_btn.configure(state="normal", text="Download")
        except Exception:
            pass
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
                status_text = f"Running | {DECRYPT_PORT}:{M3U8_PORT}:{ACCOUNT_PORT}" if running else "Stopped"
                self.status_text.configure(text=status_text)
        except Exception:
            pass

    def _show_mode_popup(self):
        if self._popup and self._popup.winfo_exists():
            self._popup.destroy()
            self._popup = None
        if self._popup_dismiss_id is not None:
            try:
                self.winfo_toplevel().unbind("<Button-1>", self._popup_dismiss_id)
            except Exception:
                pass
            self._popup_dismiss_id = None
        if self._reposition_timer is not None:
            self.after_cancel(self._reposition_timer)
            self._reposition_timer = None

        c = self.app.colors
        f = FONT_FAMILY

        popup = ctk.CTkToplevel(self)
        popup.overrideredirect(True)
        popup.transient(self.winfo_toplevel())
        popup.configure(fg_color=c["surface"])
        popup.configure(border_color=c["border"], border_width=1)

        self._popup = popup

        frame = ctk.CTkFrame(popup, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=6, pady=6)

        def select(key, name):
            self._mode_var.set(key)
            self._mode_entry.configure(state="normal")
            self._mode_entry.delete(0, "end")
            self._mode_entry.insert(0, name)
            self._mode_entry.configure(state="readonly")
            self._on_mode_change(name)
            dismiss()

        def dismiss(*args):
            if self._reposition_timer is not None:
                self.after_cancel(self._reposition_timer)
                self._reposition_timer = None
            if self._popup_dismiss_id is not None:
                try:
                    self.winfo_toplevel().unbind("<Button-1>", self._popup_dismiss_id)
                except Exception:
                    pass
                self._popup_dismiss_id = None
            if self._popup:
                try:
                    self._popup.destroy()
                except Exception:
                    pass
                self._popup = None

        for i, (key, name, _) in enumerate(MODE_SPECS):
            btn = ctk.CTkButton(frame, text=name, anchor="w",
                                fg_color="transparent", hover_color=c["input_bg"],
                                text_color=c["text"],
                                font=ctk.CTkFont(family=f, size=13),
                                corner_radius=6, height=32, width=190,
                                command=lambda k=key, n=name: select(k, n))
            btn.pack(fill="x", pady=1)

        _last_pos = (0, 0)

        def _poll_reposition():
            nonlocal _last_pos
            if self._popup and self._popup.winfo_exists():
                x = self._mode_entry.winfo_rootx()
                y = self._mode_entry.winfo_rooty() + self._mode_entry.winfo_height() + 4
                if (x, y) != _last_pos:
                    _last_pos = (x, y)
                    self._popup.geometry(f"+{x}+{y}")
            self._reposition_timer = self.after(200, _poll_reposition)

        popup.update_idletasks()
        _poll_reposition()

        def outside_popup(w):
            while w:
                if w == popup:
                    return False
                try:
                    w = w.master
                except Exception:
                    break
            return True

        root = self.winfo_toplevel()
        bind_id = root.bind("<Button-1>", lambda e: dismiss() if outside_popup(e.widget) else None, add="+")
        self._popup_dismiss_id = bind_id
        popup.bind("<Escape>", lambda e: dismiss())

    def _on_mode_change(self, choice):
        for w in self._extra_widgets:
            try:
                w.destroy()
            except AttributeError:
                pass
        self._extra_widgets.clear()

        key = [m for m in MODE_SPECS if m[1] == choice][0][0]

        if key == "aac":
            self._add_extra_dropdown("Format:", ["aac-lc", "aac", "aac-binaural", "aac-downmix"], "aac-lc")
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
        self._go_btn.configure(state="disabled", text="Running...")
        threading.Thread(target=self._dl_thread, args=(args,), daemon=True).start()

    def _dl_thread(self, arguments):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config_content = f.read()
        except FileNotFoundError:
            self.log("[WARN] config.yaml not found, using defaults")
            config_path = os.path.join(DATA_DIR, "assets", "apple-music-downloader", "config.yaml.example")
            if os.path.isfile(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_content = f.read()
            else:
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
        fd, tmp_config = tempfile.mkstemp(suffix='.yaml', prefix='am_config_')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(config_content)
        try:
            args = ["run", "--rm",
                    "-v", f"{DOWNLOAD_DIR}:/downloads",
                    "-v", f"{tmp_config}:/app/config.yaml",
                    DL_IMAGE]
            args.extend(arguments.split())
            proc = subprocess.Popen(["docker"] + args,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace",
                                    startupinfo=_SI, creationflags=_CF)
            buf = ""
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
            if proc.returncode != 0:
                self.log(f"Exit code: {proc.returncode}")
        finally:
            try:
                os.remove(tmp_config)
            except Exception:
                pass
        self.log(f"Done - output: {DOWNLOAD_DIR}")
        self.after(0, self._on_download_done)


def main():
    app = AppleMusicApp()
    app.mainloop()


if __name__ == "__main__":
    main()

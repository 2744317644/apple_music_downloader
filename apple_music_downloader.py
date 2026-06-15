#!/usr/bin/env python3
"""Apple Music ALAC Downloader - Interactive Terminal
Requires: Python 3.7+, Docker
"""

import os
import re
import sys
import shutil
import subprocess
import tempfile
import time

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
            print(f"{C}[INFO] 默认配置已复制到: {CONFIG_FILE}{R}")
        else:
            print(f"{Y}[WARN] 未找到示例: {CONFIG_EXAMPLE}{R}")
    if not os.path.isfile(CONFIG_FILE):
        print(f"{Y}[WARN] 配置文件不存在: {CONFIG_FILE}{R}")
        return None
    return CONFIG_FILE


# ---- ANSI colors ----
R = "\033[0m"
C = "\033[96m"
G = "\033[92m"
Y = "\033[93m"
E = "\033[91m"
M = "\033[95m"
W = "\033[97m"
D = "\033[90m"


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def banner():
    clear()
    print(f"{C}========================================")
    print(f"   Apple Music ALAC Downloader{W}")
    print(f"{C}========================================")
    print(f"  {D}Config: {CONFIG_FILE}{R}")
    print()


def _run(*args, capture=True, silent=False, check=False):
    """Run a subprocess command. Returns output string."""
    try:
        r = subprocess.run(list(args), capture_output=capture, text=True, check=check)
        if not silent and r.stdout:
            print(r.stdout.strip())
        if not silent and r.stderr and r.returncode != 0:
            print(f"{E}{r.stderr.strip()}{R}", file=sys.stderr)
        return r.stdout.strip()
    except FileNotFoundError:
        print(f"{E}[ERROR] '{args[0]}' not found in PATH{R}")
        sys.exit(1)


def _live(*args):
    """Run with stdout/stderr streaming (for interactive -it)."""
    return subprocess.run(list(args), check=False).returncode


# =====================================================================
# WRAPPER LIFECYCLE
# =====================================================================

def wrapper_running():
    out = _run("docker", "ps", "-q", "-f", f"name={WRAPPER_NAME}", silent=True)
    return len(out) > 0


def build_wrapper_image():
    """Build wrapper Docker image from local source directory."""
    src = WRAPPER_SRC
    if not os.path.isdir(src):
        print(f"{E}[ERROR] Wrapper source not found: {src}{R}")
        print(f"{Y}  Set the WRAPPER_SRC env var or ensure the folder exists:{R}")
        print(f"{Y}    {os.path.join(SCRIPT_DIR, 'assets', 'Wrapper')}{R}")
        print(f"{Y}  The folder must contain: Dockerfile, wrapper (binary), rootfs/, entrypoint.sh{R}")
        return False

    dockerfile = os.path.join(src, "Dockerfile")
    if not os.path.isfile(dockerfile):
        print(f"{E}[ERROR] {src} must contain Dockerfile.{R}")
        return False

    print(f"{C}Building wrapper image from: {src}{R}")
    code = _live("docker", "build",
        "--build-arg", f"REGISTRY_MIRROR={REGISTRY_MIRROR}",
        "--tag", WRAPPER_IMAGE, src)
    if code != 0:
        print(f"{E}[ERROR] Build failed.{R}")
        return False
    print(f"{G}[OK] Wrapper image built: {WRAPPER_IMAGE}{R}")
    return True


def wrapper_login():
    """First-time login: run wrapper in background, wait for login, then stop."""
    print(f"\n{Y}========================================")
    print(f"  First-time setup: Apple Music login")
    print(f"========================================{R}\n")
    username = input("Apple ID (email): ").strip()
    try:
        import msvcrt
        print("Password: ", end="", flush=True)
        password = ""
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                break
            if ch == "\x08":
                if password:
                    password = password[:-1]
                    print("\b \b", end="", flush=True)
            elif ch == "\x03":
                raise KeyboardInterrupt
            else:
                password += ch
                print("*", end="", flush=True)
        print()
    except ImportError:
        import getpass
        password = getpass.getpass("Password: ")

    print(f"\n{C}Logging in to Apple Music (this may take 30 seconds)...{R}")

    # Start login container in background
    _run("docker", "rm", "-f", f"{WRAPPER_NAME}-login", silent=True)
    os.makedirs(WRAPPER_DATA_DIR, exist_ok=True)
    code = _live(
        "docker", "run", "-d",
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
        print(f"{E}[ERROR] Failed to start login container.{R}")
        return False

    # Wait for login to complete (check for the DB file every 2 seconds)
    db_file = os.path.join(
        os.path.abspath(WRAPPER_DATA_DIR),
        "data", "com.apple.android.music", "files", "mpl_db", "kvs.sqlitedb"
    )
    fsi_file = os.path.join(
        os.path.abspath(WRAPPER_DATA_DIR),
        "data", "com.apple.android.music", "files", "fsi.pdat"
    )
    waited = 0
    while not os.path.isfile(db_file) and waited < 60:
        time.sleep(2)
        waited += 2

    # Show logs and exit status
    print()
    exit_code = _run("docker", "inspect", "-f", "{{.State.ExitCode}}", f"{WRAPPER_NAME}-login", silent=True)
    if exit_code:
        print(f"{Y}[INFO] Login container exited with code: {exit_code}{R}")
    _live("docker", "logs", f"{WRAPPER_NAME}-login")
    print()

    if os.path.isfile(db_file):
        print(f"{G}[OK] Login successful. Credentials cached.{R}")
        if not os.path.isfile(fsi_file):
            print(f"{Y}[INFO] Waiting for FairPlay registration (up to 120s)...{R}")
            waited = 0
            while not os.path.isfile(fsi_file) and waited < 120:
                time.sleep(2)
                waited += 2
            if os.path.isfile(fsi_file):
                print(f"{G}[OK] FairPlay registered.{R}")
            else:
                print(f"{Y}[WARN] FairPlay not yet registered (will retry on first download).{R}")
    else:
        print(f"{E}[ERROR] Login may have failed. No credential database created.{R}")

    # Stop login container
    _run("docker", "rm", "-f", f"{WRAPPER_NAME}-login", silent=True)

    if os.path.isfile(db_file):
        return True
    return False


def start_wrapper():
    if wrapper_running():
        print(f"{G}[OK] Wrapper container is already running.{R}")
        return True

    os.makedirs(WRAPPER_DATA_DIR, exist_ok=True)
    data_dir = os.path.abspath(WRAPPER_DATA_DIR)

    if not _run("docker", "images", "-q", WRAPPER_IMAGE, silent=True):
        print(f"{E}[ERROR] Wrapper image '{WRAPPER_IMAGE}' not found.{R}")
        return False

    # Step 2: login if needed
    db_file = os.path.join(data_dir, "data", "com.apple.android.music", "files", "mpl_db", "kvs.sqlitedb")
    if not os.path.isfile(db_file):
        print(f"{Y}[INFO] No cached login found. Starting first-time login...{R}")
        if not wrapper_login():
            return False

    # Step 3: start wrapper
    print(f"{C}Starting wrapper container (background)...{R}")
    _run("docker", "rm", "-f", WRAPPER_NAME, silent=True)

    code = _live(
        "docker", "run", "-d", "--rm",
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
        print(f"{E}[ERROR] Failed to start wrapper.{R}")
        return False

    time.sleep(3)
    if wrapper_running():
        print(f"{G}[OK] Wrapper running (ports: {DECRYPT_PORT}/{M3U8_PORT}/{ACCOUNT_PORT}){R}")
        return True
    else:
        print(f"{E}[ERROR] Wrapper exited immediately. Logs:{R}")
        _live("docker", "logs", WRAPPER_NAME)
        return False


def stop_wrapper():
    if wrapper_running():
        _run("docker", "rm", "-f", WRAPPER_NAME, silent=True)
        print(f"{G}[OK] Wrapper stopped.{R}")


# =====================================================================
# PREREQUISITES
# =====================================================================

def build_downloader_image():
    """Build downloader Docker image from local source directory."""
    src = DL_SRC
    if not os.path.isdir(src):
        print(f"{E}[ERROR] Downloader source not found: {src}{R}")
        print(f"{Y}  Set the DL_SRC env var or ensure the folder exists:{R}")
        print(f"{Y}    {os.path.join(SCRIPT_DIR, 'assets', 'apple-music-downloader')}{R}")
        return False

    dockerfile = os.path.join(src, "Dockerfile")
    if not os.path.isfile(dockerfile):
        print(f"{E}[ERROR] {src} must contain Dockerfile.{R}")
        return False

    print(f"{C}Building downloader image from: {src}{R}")
    code = _live("docker", "build",
        "--build-arg", f"REGISTRY_MIRROR={REGISTRY_MIRROR}",
        "--tag", DL_IMAGE, src)
    if code != 0:
        print(f"{E}[ERROR] Build failed.{R}")
        return False
    print(f"{G}[OK] Downloader image built: {DL_IMAGE}{R}")
    return True


def check_prerequisites():
    if subprocess.call(["docker", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        print(f"{E}[ERROR] Docker is not installed or not in PATH.{R}")
        sys.exit(1)

    os.makedirs(APP_DATA_DIR, exist_ok=True)
    config_path = get_config_path()
    if not config_path:
        print(f"{Y}[WARN] 未找到配置文件示例 (config.yaml.example)，请手动创建 {CONFIG_FILE}{R}")

    if not _run("docker", "images", "-q", DL_IMAGE, silent=True):
        if not build_downloader_image():
            print(f"{E}[ERROR] Downloader image not available.{R}")
            sys.exit(1)

    if not _run("docker", "images", "-q", WRAPPER_IMAGE, silent=True):
        if not build_wrapper_image():
            print(f"{E}[ERROR] Wrapper image not available.{R}")
            sys.exit(1)

    if not start_wrapper():
        print(f"{E}[ERROR] Wrapper is not running. Cannot continue.{R}")
        sys.exit(1)


# =====================================================================
# DOWNLOAD
# =====================================================================

def invoke_downloader(arguments, description):
    print()
    print(f"{M}>>> {description}{R}")
    print()

    config_path = get_config_path()
    if config_path:
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
        args = ["run", "--rm", "-it",
                "-v", f"{DOWNLOAD_DIR}:/downloads",
                "-v", f"{tmp_config}:/app/config.yaml",
                DL_IMAGE]
        args.extend(arguments.split())
        code = _live("docker", *args)
        if code != 0:
            print(f"\n{Y}[WARN] Docker exited with code {code}{R}")
    finally:
        os.remove(tmp_config)
        print(f"\n{G}Output: {SCRIPT_DIR}{R}")
    print()
    input("Press Enter to return to menu")


# =====================================================================
# MENU HANDLERS
# =====================================================================

def menu_download_album():
    banner()
    url = input("Enter Apple Music album URL: ").strip()
    if url:
        invoke_downloader(url, "Download album")


def menu_download_song():
    banner()
    url = input("Enter Apple Music song URL: ").strip()
    if url:
        invoke_downloader(f"--song {url}", "Download single song")


def menu_interactive_select():
    banner()
    url = input("Enter Apple Music URL (album/playlist): ").strip()
    if url:
        invoke_downloader(f"--select {url}", "Interactive track select")


def menu_download_playlist():
    banner()
    url = input("Enter Apple Music playlist URL: ").strip()
    if url:
        invoke_downloader(url, "Download playlist")


def menu_download_atmos():
    banner()
    url = input("Enter Apple Music album URL: ").strip()
    if url:
        invoke_downloader(f"--atmos {url}", "Dolby Atmos")


def menu_download_aac():
    banner()
    url = input("Enter Apple Music album URL: ").strip()
    if not url:
        return
    t = input("AAC type (aac-lc/aac/aac-binaural/aac-downmix) [aac-lc]: ").strip() or "aac-lc"
    invoke_downloader(f"--aac --aac-type {t} {url}", "Download AAC")


def menu_debug():
    banner()
    url = input("Enter Apple Music album URL: ").strip()
    if url:
        invoke_downloader(f"--debug {url}", "Debug / view quality")


def menu_artist_albums():
    banner()
    url = input("Enter Apple Music artist URL: ").strip()
    if url:
        invoke_downloader(f"--all-album {url}", "All artist albums")


def menu_search():
    banner()
    print(f"{Y}Search type:{R}")
    print("  1. song")
    print("  2. album")
    print("  3. artist\n")
    m = {"1": "song", "2": "album", "3": "artist"}
    t = m.get(input("Select (1-3): ").strip())
    if not t:
        return
    q = input("Enter search query: ").strip()
    if q:
        invoke_downloader(f"--search {t} {q}", f"Search {t}: '{q}'")


def menu_custom():
    banner()
    a = input("Enter full args (e.g. --atmos --select https://...): ").strip()
    if a:
        invoke_downloader(a, "Custom command")


def menu_wrapper_status():
    banner()
    print(f"{C}WRAPPER STATUS{R}")
    print(f"  Source: {WRAPPER_SRC}")
    print(f"  Image : {WRAPPER_IMAGE}")
    print(f"  Data  : {WRAPPER_DATA_DIR}")
    if wrapper_running():
        print(f"  Status: {G}RUNNING{R}")
        print(f"  Ports : {DECRYPT_PORT}, {M3U8_PORT}, {ACCOUNT_PORT}")
    else:
        print(f"  Status: {E}STOPPED{R}")
    print()
    input("Press Enter to return")


def menu_help():
    banner()
    print(f"{C}ABOUT{R}")
    print(f"  Apple Music ALAC / Dolby Atmos / AAC downloader.\n")
    print(f"{C}QUICK START{R}")
    print(f"  1. Put wrapper release in: {WRAPPER_SRC}")
    print(f"  2. Edit config.yaml (media-user-token + storefront)")
    print(f"  3. Run: python am-dl.py\n")
    print(f"{C}CONFIG (set via env vars or edit script header){R}")
    print(f"  REGISTRY_MIRROR   = {REGISTRY_MIRROR}")
    print(f"  WRAPPER_SRC       = {WRAPPER_SRC}")
    print(f"  WRAPPER_IMAGE     = {WRAPPER_IMAGE}")
    print(f"  DL_SRC            = {DL_SRC}")
    print(f"  DL_IMAGE          = {DL_IMAGE}")
    print(f"  WRAPPER_DATA_DIR  = {WRAPPER_DATA_DIR}")
    print(f"  DOWNLOAD_DIR      = {DOWNLOAD_DIR}")
    print()
    input("Press Enter to return")


MENU = {
    "1": ("Download Album", menu_download_album),
    "2": ("Download Single Song", menu_download_song),
    "3": ("Interactive Select (pick tracks)", menu_interactive_select),
    "4": ("Download Playlist", menu_download_playlist),
    "5": ("Dolby Atmos Mode", menu_download_atmos),
    "6": ("AAC Mode", menu_download_aac),
    "7": ("Debug / View Audio Quality", menu_debug),
    "8": ("Search (song/album/artist)", menu_search),
    "9": ("Download All Artist Albums", menu_artist_albums),
    "0": ("Custom Command", menu_custom),
    "s": ("Wrapper Status", menu_wrapper_status),
    "h": ("Help / Info", menu_help),
}


def status_line():
    if wrapper_running():
        print(f"  {G}Wrapper: RUNNING | Ports: {DECRYPT_PORT}/{M3U8_PORT}/{ACCOUNT_PORT}{R}")
    else:
        print(f"  {E}Wrapper: STOPPED{R}")
    print()


def main_menu():
    banner()
    status_line()
    for k, (label, _) in MENU.items():
        if k in ("s", "h"):
            continue
        print(f"  [{k}] {label}")
    print()
    print(f"  {D}[S] Wrapper Status")
    print(f"  [H] Help / Info")
    print(f"  [Q] Quit{R}")
    print()
    return input("Select: ").strip().lower()


def main():
    check_prerequisites()
    while True:
        c = main_menu()
        if c == "q":
            stop_wrapper()
            clear()
            sys.exit(0)
        if c in MENU:
            MENU[c][1]()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{E}Interrupted.{R}")
        stop_wrapper()
        sys.exit(0)

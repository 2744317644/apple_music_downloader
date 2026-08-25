#!/usr/bin/env python3
"""Apple Music ALAC Downloader - Interactive Terminal
Requires: Python 3.7+, Docker
"""

import argparse
import os
import sys
import subprocess
import tempfile
import time

from common import (
    SCRIPT_DIR, DOWNLOAD_DIR, CONFIG_FILE,
    WRAPPER_SRC, WRAPPER_IMAGE, WRAPPER_NAME, WRAPPER_DATA_DIR,
    DECRYPT_PORT, M3U8_PORT, ACCOUNT_PORT,
    DL_IMAGE, APP_DATA_DIR, MIRROR_PROFILES,
    get_config_path, load_images_from_dir, export_images,
    build_wrapper_image, build_downloader_image,
    wrapper_running, do_start_wrapper, stop_wrapper,
    prepare_config_for_docker, _SI, _CF,
)

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
    try:
        r = subprocess.run(list(args), capture_output=capture, text=True, check=check,
                           encoding="utf-8", errors="replace",
                           startupinfo=_SI, creationflags=_CF)
        if not silent and r.stdout:
            print(r.stdout.strip())
        if not silent and r.stderr and r.returncode != 0:
            print(f"{E}{r.stderr.strip()}{R}", file=sys.stderr)
        return r.stdout.strip()
    except FileNotFoundError:
        print(f"{E}[ERROR] '{args[0]}' not found in PATH{R}")
        sys.exit(1)


def _live(*args):
    return subprocess.run(list(args), check=False,
                          startupinfo=_SI, creationflags=_CF).returncode


def _check_docker():
    if subprocess.call(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       startupinfo=_SI, creationflags=_CF) == 0:
        return True
    return False


def _log_print(msg):
    """Log callback that prints with ANSI colors."""
    if msg.startswith("[ERROR]"):
        print(f"{E}{msg}{R}")
    elif msg.startswith("[WARN]"):
        print(f"{Y}{msg}{R}")
    elif msg.startswith("[OK]"):
        print(f"{G}{msg}{R}")
    elif msg.startswith("[INFO]"):
        print(f"{C}{msg}{R}")
    else:
        print(msg)


def wrapper_login():
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

    def _twofa_input():
        print(f"\n{Y}========================================")
        print(f"  Two-Factor Authentication Required")
        print(f"  Check your Apple device for the code")
        print(f"========================================{R}")
        return input("Enter 2FA code: ").strip()

    from common import wrapper_login as _wl
    ok, msg = _wl(username, password, log_callback=_log_print, twofa_callback=_twofa_input)

    if ok:
        print(f"{G}[OK] {msg}{R}")
    else:
        print(f"{E}[ERROR] {msg}{R}")
    return ok


def _ask_mirror_profile():
    print(f"\n{C}选择镜像源 / Select mirror source:{R}")
    print(f"  [1] 国内镜像 (DaoCloud + 清华 apt)")
    print(f"  [2] 国际源 (Docker Hub + 默认 apt)")
    while True:
        choice = input(f"  选择 (1/2) [1]: ").strip()
        if choice in ("", "1"):
            return "cn"
        if choice == "2":
            return "intl"
        print(f"  {Y}请输入 1 或 2{R}")


def check_prerequisites(image_dir=None):
    if subprocess.call(["docker", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       startupinfo=_SI, creationflags=_CF) != 0:
        print(f"{E}[ERROR] Docker is not installed or not in PATH. Please install Docker Desktop.{R}")
        sys.exit(1)

    while not _check_docker():
        print(f"{Y}[WARN] Docker daemon is not running.{R}")
        print(f"{C}  Please start Docker Desktop, then press Enter to retry (or Q to quit).{R}")
        choice = input("  > ").strip().lower()
        if choice == "q":
            sys.exit(0)

    print(f"{G}[OK] Docker is running{R}")

    os.makedirs(APP_DATA_DIR, exist_ok=True)
    config_path = get_config_path()
    if not config_path:
        print(f"{Y}[WARN] 未找到配置文件示例 (config.yaml.example)，请手动创建 {CONFIG_FILE}{R}")

    if image_dir:
        print(f"{C}[INFO] 尝试从本地目录加载镜像: {image_dir}{R}")
        load_images_from_dir(image_dir, log_callback=_log_print)

    profile = _ask_mirror_profile()

    try:
        r = subprocess.run(["docker", "images", "-q", DL_IMAGE], capture_output=True, text=True,
                           startupinfo=_SI, creationflags=_CF)
        if not r.stdout.strip():
            if not build_downloader_image(profile=profile, log_callback=_log_print)[0]:
                print(f"{E}[ERROR] Downloader image not available.{R}")
                sys.exit(1)
    except Exception:
        pass

    try:
        r = subprocess.run(["docker", "images", "-q", WRAPPER_IMAGE], capture_output=True, text=True,
                           startupinfo=_SI, creationflags=_CF)
        if not r.stdout.strip():
            if not build_wrapper_image(profile=profile, log_callback=_log_print)[0]:
                print(f"{E}[ERROR] Wrapper image not available.{R}")
                sys.exit(1)
    except Exception:
        pass

    if not start_wrapper():
        print(f"{E}[ERROR] Wrapper is not running. Cannot continue.{R}")
        sys.exit(1)


def start_wrapper():
    if wrapper_running():
        print(f"{G}[OK] Wrapper container is already running.{R}")
        return True

    os.makedirs(WRAPPER_DATA_DIR, exist_ok=True)
    data_dir = os.path.abspath(WRAPPER_DATA_DIR)

    try:
        r = subprocess.run(["docker", "images", "-q", WRAPPER_IMAGE], capture_output=True, text=True,
                           startupinfo=_SI, creationflags=_CF)
        if not r.stdout.strip():
            print(f"{E}[ERROR] Wrapper image '{WRAPPER_IMAGE}' not found.{R}")
            return False
    except Exception:
        print(f"{E}[ERROR] Docker not available.{R}")
        return False

    db_file = os.path.join(data_dir, "data", "com.apple.android.music", "files", "mpl_db", "kvs.sqlitedb")
    fsi_file = os.path.join(data_dir, "data", "com.apple.android.music", "files", "fsi.pdat")
    if not os.path.isfile(db_file) or not os.path.isfile(fsi_file):
        print(f"{Y}[INFO] No cached login found. Starting first-time login...{R}")
        if not wrapper_login():
            return False

    print(f"{C}Starting wrapper container (background)...{R}")
    _run("docker", "rm", "-f", WRAPPER_NAME, silent=True)

    from common import _build_wrapper_docker_run_args
    args = _build_wrapper_docker_run_args(detach=True, with_ports=True)
    code = _live(*args)
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
    config_content = prepare_config_for_docker(config_content)

    fd, tmp_config = tempfile.mkstemp(suffix='.yaml', prefix='am_config_')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(config_content)

    try:
        args = ["run", "--rm", "-it",
                "-v", f"{DOWNLOAD_DIR}:/downloads",
                "-v", f"{tmp_config}:/app/config.yaml",
                DL_IMAGE]
        args.extend(arguments.split())
        for attempt in range(1, 4):
            if attempt > 1:
                print(f"\n{Y}[RETRY] Attempt {attempt}/3...{R}")
            code = _live("docker", *args)
            if code == 0:
                break
            print(f"\n{Y}[WARN] Docker exited with code {code}{R}")
            if attempt < 3:
                time.sleep(2)
    finally:
        os.remove(tmp_config)
        print(f"\n{G}Output: {DOWNLOAD_DIR}{R}")
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
    print(f"  国内源: {MIRROR_PROFILES['cn']['registry']} / apt: {MIRROR_PROFILES['cn']['apt']}")
    print(f"  国际源: {MIRROR_PROFILES['intl']['registry']} / apt: default")
    print(f"  WRAPPER_SRC       = {WRAPPER_SRC}")
    print(f"  WRAPPER_IMAGE     = {WRAPPER_IMAGE}")
    print(f"  WRAPPER_DATA_DIR  = {WRAPPER_DATA_DIR}")
    print(f"  DOWNLOAD_DIR      = {DOWNLOAD_DIR}")
    print()
    input("Press Enter to return")


def menu_export_images():
    banner()
    print(f"{C}EXPORT DOCKER IMAGES{R}")
    print(f"  This will save {WRAPPER_IMAGE} and {DL_IMAGE} as .tar files.")
    print()
    out = input(f"Output directory [{os.path.join(os.path.expanduser('~'), 'Downloads')}]: ").strip()
    if not out:
        out = None
    print()
    export_images(out, log_callback=_log_print)
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
    "e": ("Export Images", menu_export_images),
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
        if k in ("s", "h", "e"):
            continue
        print(f"  [{k}] {label}")
    print()
    print(f"  {D}[S] Wrapper Status")
    print(f"  [E] Export Images")
    print(f"  [H] Help / Info")
    print(f"  [Q] Quit{R}")
    print()
    return input("Select: ").strip().lower()


def main():
    parser = argparse.ArgumentParser(description="Apple Music ALAC Downloader")
    parser.add_argument("--image-dir", dest="image_dir", metavar="DIR",
                        help="Directory containing local Docker image .tar files")
    args = parser.parse_args()

    check_prerequisites(image_dir=args.image_dir)
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

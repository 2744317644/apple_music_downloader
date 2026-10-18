#!/usr/bin/env python3
"""Apple Music ALAC Downloader - Interactive Terminal

Requirements: Python 3.7+
  - the legacy `wrapper` running in the WSL2 distro `Debian13-wrapper`
  - the downloader binary /opt/amdl-legacy/amdl (Linux, inside WSL)
"""

import argparse
import os
import sys
import subprocess
import time

from common import (
    SCRIPT_DIR, DOWNLOAD_DIR, CONFIG_FILE, APP_DATA_DIR,
    WRAPPER_HOST, DECRYPT_PORT, M3U8_PORT, ACCOUNT_PORT, WSL_DISTRO, DOWNLOADER_WSL,
    get_config_path, get_download_folder, get_save_folder, get_downloader_exe,
    prepare_run_config, cleanup_run_config, build_downloader_command,
    find_media_user_token, validate_media_user_token, save_media_user_token,
    wrapper_running, wrapper_status, wrapper_service_state, wsl_diagnose,
    wrapper_health_after_run, login_cached, kill_downloader,
    start_wrapper_service, restart_wrapper_service, stop_wrapper,
    shutdown_wsl, shutdown_wsl_on_exit_enabled,
    wrapper_login as _common_wrapper_login, _SI, _CF,
)

WRAPPER_ENDPOINT = f"{WRAPPER_HOST}:{DECRYPT_PORT}/{M3U8_PORT}/{ACCOUNT_PORT}"

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
    # Not os.system: that spawns a shell and inherits its parsing rules.
    try:
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "cls"], check=False,
                           startupinfo=_SI, creationflags=_CF)
        else:
            subprocess.run(["clear"], check=False)
    except Exception:
        print("\033[2J\033[H", end="")


def banner():
    clear()
    print(f"{C}========================================")
    print(f"   Apple Music ALAC Downloader{W}")
    print(f"{C}========================================")
    print(f"  {D}Config: {CONFIG_FILE}{R}")
    print()


def _live(*args, cwd=None):
    """Run a command and stream its output line by line.

    Letting the child inherit our stdout loses wsl.exe's output entirely when
    stdout is a pipe (as in any scripted run), so capture it explicitly and
    echo it here.
    """
    proc = subprocess.Popen(list(args), cwd=cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            startupinfo=_SI, creationflags=_CF)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
    except KeyboardInterrupt:
        try:
            proc.kill()
        except Exception:
            pass
        # Killing wsl.exe does not stop the downloader inside the distro.
        try:
            kill_downloader(log_callback=_log_print)
        except Exception:
            pass
        raise
    finally:
        try:
            proc.wait()
        except Exception:
            pass
    return proc.returncode


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

    ok, msg = _common_wrapper_login(username, password,
                                    log_callback=_log_print,
                                    twofa_callback=_twofa_input)
    if ok:
        print(f"{G}[OK] {msg}{R}")
    else:
        print(f"{E}[ERROR] {msg}{R}")
    return ok


def check_prerequisites():
    """Verify the wrapper and the downloader binary are usable."""
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    config_path = get_config_path()
    if not config_path:
        print(f"{Y}[WARN] 未找到配置文件示例 (config.yaml.example)，请手动创建 {CONFIG_FILE}{R}")

    exe = get_downloader_exe()
    if not exe:
        print(f"{E}[ERROR] Downloader binary not found.{R}")
        print(f"{C}  Expected at: {DOWNLOADER_WSL} inside WSL distro '{WSL_DISTRO}'{R}")
        print(f"{C}  Download it from the upstream releases page.{R}")
        sys.exit(1)
    print(f"{G}[OK] Downloader: {exe}{R}")

    if wrapper_running():
        print(f"{G}[OK] wrapper ready ({WRAPPER_ENDPOINT}){R}")
        return

    print(f"{Y}[WARN] wrapper is not responding on {WRAPPER_ENDPOINT}{R}")
    state = wrapper_service_state()
    if state == "unknown":
        problem = wsl_diagnose()
        print(f"{E}[ERROR] Cannot use the WSL distro '{WSL_DISTRO}'.{R}")
        if problem:
            print(f"{C}  Reason: {problem}{R}")
        print(f"{C}  Make sure WSL2 is installed and the distro exists.{R}")
        sys.exit(1)

    # A fresh install has no cached credentials; the wrapper legitimately
    # cannot open its ports yet, so go straight to the login flow.
    if not login_cached():
        print(f"{Y}[WARN] Not signed in yet.{R}")
        print(f"{C}  The wrapper cannot start until an Apple Music login exists.{R}")
        if wrapper_login():
            ok, msg = start_wrapper_service(log_callback=_log_print)
            if ok:
                print(f"{G}[OK] {msg}{R}")
                return
            print(f"{E}[ERROR] {msg}{R}")
        sys.exit(1)

    print(f"{C}  Service state: {state}. Trying to start it...{R}")
    ok, msg = start_wrapper_service(log_callback=_log_print)
    if ok:
        print(f"{G}[OK] {msg}{R}")
        return

    print(f"{E}[ERROR] {msg}{R}")
    print(f"{C}  If this is the first run you need to sign in.{R}")
    if wrapper_login():
        return
    sys.exit(1)


def start_wrapper():
    if wrapper_running():
        print(f"{G}[OK] wrapper is already running ({WRAPPER_ENDPOINT}){R}")
        return True
    ok, msg = start_wrapper_service(log_callback=_log_print)
    if ok:
        print(f"{G}[OK] {msg}{R}")
        return True
    print(f"{E}[ERROR] {msg}{R}")
    return False


def _pause_if_interactive(prompt="Press Enter to return to menu"):
    """Only wait for input when a human is actually watching.

    In a script or piped run stdin is closed, and input() throws EOFError -
    which used to abort the CLI after a download had already finished.
    """
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return
    except Exception:
        return
    try:
        input(prompt)
    except (EOFError, KeyboardInterrupt):
        pass


def invoke_downloader(arguments, description):
    print()
    print(f"{M}>>> {description}{R}")
    print()

    exe = get_downloader_exe()
    if not exe:
        print(f"{E}[ERROR] Downloader binary not found.{R}")
        _pause_if_interactive("Press Enter to return to menu")
        return

    # The legacy downloader reads config.yaml from its working directory, so it
    # runs inside a temp dir whose config points at the real output folders.
    workdir, _cfg = prepare_run_config()
    argv = build_downloader_command(arguments.split(), workdir)
    if not argv:
        cleanup_run_config(workdir)
        print(f"{E}[ERROR] Downloader binary not found in WSL.{R}")
        _pause_if_interactive("Press Enter to return to menu")
        return

    try:
        for attempt in range(1, 4):
            if attempt > 1:
                print(f"\n{Y}[RETRY] Attempt {attempt}/3...{R}")
                time.sleep(2)
            try:
                code = _live(*argv, cwd=workdir)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"{E}[ERROR] {e}{R}")
                code = 1
            if code == 0:
                break
            print(f"\n{Y}[WARN] Downloader exited with code {code}{R}")
    finally:
        cleanup_run_config(workdir)

    if not wrapper_running():
        wrapper_health_after_run(log_callback=_log_print)

    print(f"\n{G}Output: {get_save_folder('alac')}{R}")
    print()
    _pause_if_interactive("Press Enter to return to menu")


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
    print(f"  Endpoint : {WRAPPER_ENDPOINT}")
    print(f"  WSL distro: {WSL_DISTRO}")
    state = wrapper_service_state()
    print(f"  Service  : {state}")
    ok, data, err = wrapper_status(timeout=5)
    if ok:
        storefront = (data or {}).get("storefront_id") or "n/a"
        print(f"  Status   : {G}RUNNING{R}")
        print(f"  Storefront: {storefront}")
    else:
        print(f"  Status   : {E}NOT RESPONDING{R}")
        if err:
            print(f"  Detail   : {err}")
    exe = get_downloader_exe()
    print(f"  Downloader: {exe or f'{E}not found{R}'}")
    print(f"  Save dirs : {get_save_folder('alac')}")
    print()
    _pause_if_interactive("Press Enter to return")


def menu_restart_wrapper():
    banner()
    print(f"{C}Restarting wrapper...{R}")
    ok, msg = restart_wrapper_service(log_callback=_log_print)
    if ok:
        print(f"{G}[OK] {msg}{R}")
    else:
        print(f"{E}[ERROR] {msg}{R}")
    print()
    _pause_if_interactive("Press Enter to return")


def menu_login():
    banner()
    wrapper_login()
    print()
    _pause_if_interactive("Press Enter to return")


def menu_get_token():
    banner()
    print(f"{C}media-user-token{R}")
    print(f"{D}  Needed for AAC downloads, stations and lyrics. ALAC works without it.{R}")
    print()

    print(f"{C}Looking for an existing token...{R}")
    token, source, notes = find_media_user_token()
    if token:
        print(f"{G}[OK] found in {source}, verifying...{R}")
        ok, detail = validate_media_user_token(token)
        if ok:
            save_media_user_token(token)
            print(f"{G}[OK] verified and saved ({detail}){R}")
            print()
            _pause_if_interactive("Press Enter to return")
            return
        print(f"{E}[WARN] that token was rejected: {detail}{R}")
    else:
        print(f"{Y}[INFO] not found automatically.{R}")
        for n in notes:
            print(f"{D}   - {n}{R}")

    print()
    print(f"{C}Get it manually:{R}")
    print("  1. Sign in at https://music.apple.com in a browser")
    print("  2. Press F12 -> Application -> Storage -> Cookies -> music.apple.com")
    print("  3. Find 'media-user-token' and copy its Value (the whole string)")
    print()
    value = input("Paste the token (or leave empty to cancel): ").strip()
    if not value:
        print(f"{Y}[INFO] cancelled{R}")
    else:
        print(f"{C}Verifying with Apple...{R}")
        ok, detail = validate_media_user_token(value)
        if ok:
            save_media_user_token(value)
            print(f"{G}[OK] verified and saved ({detail}){R}")
        else:
            print(f"{E}[ERROR] {detail}{R}")
    print()
    _pause_if_interactive("Press Enter to return")


def menu_help():
    banner()
    print(f"{C}ABOUT{R}")
    print(f"  Apple Music ALAC / Dolby Atmos / AAC downloader.\n")
    print(f"{C}ARCHITECTURE{R}")
    print(f"  wrapper      : {WRAPPER_ENDPOINT} (systemd in WSL distro '{WSL_DISTRO}')")
    print(f"  downloader   : {get_downloader_exe() or '(not found)'}")
    print(f"  config       : {CONFIG_FILE}")
    print(f"  output       : {get_save_folder('alac')}")
    print()
    print(f"{C}QUICK START{R}")
    print(f"  1. the wrapper must be running (menu S / R)")
    print(f"  2. Edit config.yaml if you need a different storefront")
    print(f"  3. Pick a menu entry and paste an Apple Music URL\n")
    _pause_if_interactive("Press Enter to return")


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
    "r": ("Restart Wrapper", menu_restart_wrapper),
    "l": ("Apple Music Login", menu_login),
    "t": ("Get media-user-token", menu_get_token),
    "h": ("Help / Info", menu_help),
}


def status_line():
    ok, _data, _err = wrapper_status(timeout=3)
    if ok:
        print(f"  {G}wrapper: RUNNING ({WRAPPER_ENDPOINT}){R}")
    else:
        print(f"  {E}wrapper: NOT RESPONDING ({WRAPPER_ENDPOINT}){R}")
    print()


def main_menu():
    banner()
    status_line()
    for k, (label, _) in MENU.items():
        if k in ("s", "r", "l", "t", "h"):
            continue
        print(f"  [{k}] {label}")
    print()
    print(f"  {D}[S] Wrapper Status")
    print(f"  [R] Restart Wrapper")
    print(f"  [L] Apple Music Login")
    print(f"  [T] Get media-user-token")
    print(f"  [H] Help / Info")
    print(f"  [Q] Quit{R}")
    print()
    return input("Select: ").strip().lower()


def main():
    parser = argparse.ArgumentParser(description="Apple Music ALAC Downloader")
    parser.add_argument("--url", metavar="URL",
                        help="Download this URL directly, then exit")
    parser.add_argument("--args", dest="extra_args", metavar="ARGS",
                        help="Extra downloader arguments used with --url")
    parser.add_argument("--status", action="store_true",
                        help="Print wrapper status and exit")
    args = parser.parse_args()

    if args.status:
        ok, data, err = wrapper_status(timeout=5)
        print(f"endpoint  : {WRAPPER_ENDPOINT}")
        print(f"service   : {wrapper_service_state()}")
        if ok:
            print(f"status    : RUNNING")
            print(f"storefront: {(data or {}).get('storefront_id') or 'n/a'}")
            return 0
        print(f"status   : NOT RESPONDING ({err})")
        return 1

    check_prerequisites()

    if args.url:
        argv_desc = ((args.extra_args or "") + " " + args.url).strip()
        invoke_downloader(argv_desc, "Download")
        return 0

    while True:
        c = main_menu()
        if c == "q":
            clear()
            return 0
        if c in MENU:
            MENU[c][1]()


def _cleanup_on_exit():
    """Stop the wrapper and (by default) release the WSL VM."""
    try:
        if shutdown_wsl_on_exit_enabled():
            ok, msg = shutdown_wsl(log_callback=log)
            if not ok and msg:
                log(msg)
        else:
            stop_wrapper()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        rc = main()
    except KeyboardInterrupt:
        print(f"\n{E}Interrupted.{R}")
        rc = 0
    finally:
        _cleanup_on_exit()
    sys.exit(rc)

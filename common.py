#!/usr/bin/env python3
"""Apple Music ALAC Downloader - Shared utilities for CLI and GUI.

Architecture:
  - The legacy `wrapper` runs natively inside the WSL2 distro `Debian13-wrapper`
    as the systemd unit `apple-music-wrapper`, exposing four TCP services:
      10020 decrypt / 20020 m3u8 / 30020 account / 40020 key
  - The downloader is the Linux binary /opt/amdl-legacy/amdl, built from
    assets/apple-music-downloader (legacy source). It runs inside WSL too:
    the Windows build stalls on non-ASCII paths such as the user profile.
"""

import os
import re
import sys
import json
import time
import atexit
import shutil
import socket
import subprocess
import tempfile
import threading
import urllib.request
import urllib.error

# ---- Windows subprocess flags (hide console windows) ----
if os.name == 'nt':
    _SI = subprocess.STARTUPINFO()
    _SI.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _SI.wShowWindow = subprocess.SW_HIDE
    _CF = subprocess.CREATE_NO_WINDOW
else:
    _SI = None
    _CF = 0

# ---- Path constants ----
if getattr(sys, 'frozen', False):
    SCRIPT_DIR = os.path.dirname(sys.executable)
    DATA_DIR = sys._MEIPASS
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = SCRIPT_DIR

DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
CONFIG_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                           "AppleMusicDownloader", "config.yaml")
CONFIG_EXAMPLE = os.path.join(DATA_DIR, "config.yaml.example")
CONFIG_EXAMPLE_ALT = os.path.join(DATA_DIR, "assets", "apple-music-downloader",
                                  "config.yaml.example")
APP_DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                            "AppleMusicDownloader")

# ---- Legacy wrapper services ----
# The bundled wrapper build only opens the first three; it has no key-port
# option (-K), so 40020 is intentionally absent here.
WRAPPER_HOST = "127.0.0.1"
DECRYPT_PORT = 10020
M3U8_PORT = 20020
ACCOUNT_PORT = 30020

# WSL2 distro + systemd unit that hosts the wrapper
WSL_DISTRO = "Debian13-wrapper"
# Accepted distro names, in order of preference. `wsl --install -d Debian`
# produces a distro simply called "Debian", and this WSL build has no --rename,
# so the actual name is discovered at runtime.
WSL_DISTRO_CANDIDATES = ("Debian13-wrapper", "Debian", "Debian-13", "Debian12")
WSL_SERVICE = "apple-music-wrapper"

_resolved_distro = None


def resolve_wsl_distro():
    """Name of the WSL distro that hosts the wrapper (discovered once)."""
    global _resolved_distro
    if _resolved_distro:
        return _resolved_distro
    names = _wsl_list_distros()
    for cand in WSL_DISTRO_CANDIDATES:
        if cand in names:
            _resolved_distro = cand
            return cand
    for name in names:
        if name.lower().startswith("debian"):
            _resolved_distro = name
            return name
    # Not found: return the preferred name so error messages stay meaningful.
    return WSL_DISTRO

# Inside the distro: wrapper home and its data dir (chroot-relative base dir
# `data/data/com.apple.android.music/files` resolved on the host).
WRAPPER_HOME = "/opt/wrapper"
WRAPPER_BASE_DIR_REL = "data/data/com.apple.android.music/files"
WRAPPER_BASE_DIR_ABS = f"{WRAPPER_HOME}/rootfs/{WRAPPER_BASE_DIR_REL}"

# ---- Downloader ----
# The legacy downloader runs *inside* WSL: its Windows build stalls on paths
# containing non-ASCII characters (the user profile is `柠墨白`), while the Linux
# build handles them fine. Running it next to the wrapper also mirrors the
# original container topology (both processes on the Linux side).
DOWNLOADER_WSL = "/opt/amdl-legacy/amdl"
DOWNLOADER_EXE = os.environ.get("AMDL_EXE", DOWNLOADER_WSL)
DEFAULT_SAVE_FOLDERS = {
    "alac": "AM-DL downloads",
    "atmos": "AM-DL-Atmos downloads",
    "aac": "AM-DL-AAC downloads",
    "mv": "AM-DL-MV downloads",
}

_downloader_present = None


def _log(msg, log_callback=None):
    if log_callback:
        log_callback(msg)


# =====================================================================
# Config (legacy flat schema)
# =====================================================================

def get_config_path():
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    if not os.path.isfile(CONFIG_FILE):
        example = None
        if os.path.isfile(CONFIG_EXAMPLE):
            example = CONFIG_EXAMPLE
        elif os.path.isfile(CONFIG_EXAMPLE_ALT):
            example = CONFIG_EXAMPLE_ALT
        if example:
            shutil.copy(example, CONFIG_FILE)
    if not os.path.isfile(CONFIG_FILE):
        return None
    return CONFIG_FILE


def load_config_content():
    path = get_config_path()
    if path:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return ""


def save_config_content(content):
    path = get_config_path() or CONFIG_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


def _config_get(content, key, default=""):
    """Read a flat scalar, stripping inline comments and template placeholders."""
    value = default
    pattern = re.compile(
        r'^[ \t]*(?:-\s*)?' + re.escape(key) + r'\s*:\s*(.*)$',
        re.MULTILINE,
    )
    for m in pattern.finditer(content or ""):
        raw = m.group(1).strip()
        if not raw:
            value = ""
            continue
        qm = re.match(r'''^(['"])(.*?)\1''', raw)
        if qm:
            value = qm.group(2).strip()
        else:
            value = raw.split("#", 1)[0].strip()
        if re.match(r'(?i)^(your-|enter your|<)', value):
            value = ""
    return value


# Map the v0.1.x nested schema back onto the legacy flat one.
_NESTED_TO_FLAT = {
    "alac": "alac-save-folder",
    "atmos": "atmos-save-folder",
    "aac": "aac-save-folder",
    "mv": "mv-save-folder",
    "album-folder": "album-folder-format",
    "playlist-folder": "playlist-folder-format",
    "song-file": "song-file-format",
}


def ensure_config_schema(log_callback=None):
    """Make sure config.yaml uses the legacy flat schema the downloader expects."""
    path = get_config_path()
    if not path:
        return False, "config.yaml not found"
    content = load_config_content()
    if not content.strip():
        return False, "config.yaml is empty"

    is_nested = re.search(r'^\s*lite-server\s*:', content, re.MULTILINE) is not None
    is_flat = re.search(r'^\s*alac-save-folder\s*:', content, re.MULTILINE) is not None
    if is_flat and not is_nested:
        return False, "config already uses the legacy schema"

    backup = path + ".bak"
    try:
        shutil.copy2(path, backup)
    except Exception:
        pass

    def pick(*keys):
        for k in keys:
            v = _config_get(content, k)
            if v:
                return v
        return ""

    folders = {}
    for kind in DEFAULT_SAVE_FOLDERS:
        folders[kind] = (pick(_NESTED_TO_FLAT[kind], kind)
                         or DEFAULT_SAVE_FOLDERS[kind])

    migrated = _build_config(
        storefront=pick("storefront") or "us",
        language=pick("language"),
        media_user_token=pick("media-user-token"),
        authorization_token=pick("authorization-token"),
        alac_max=pick("alac-max") or "192000",
        atmos_max=pick("atmos-max") or "2768",
        aac_type=pick("aac-type") or "aac-lc",
        get_m3u8_mode=pick("get-m3u8-mode") or "hires",
        folders=folders,
        album_folder=pick("album-folder-format", "album-folder") or "{AlbumName}",
        playlist_folder=pick("playlist-folder-format", "playlist-folder") or "{PlaylistName}",
        song_file=pick("song-file-format", "song-file") or "{SongNumer}. {SongName}",
        lrc_type=pick("lrc-type") or "lyrics",
        lrc_format=pick("lrc-format") or "lrc",
        lrc_embed=pick("embed-lrc") or "true",
        lrc_save=pick("save-lrc-file") or "false",
        cover_embed=pick("embed-cover") or "true",
        cover_size=pick("cover-size") or "5000x5000",
        cover_format=pick("cover-format") or "jpg",
        convert_after=pick("convert-after-download") or "false",
        convert_format=pick("convert-format") or "flac",
        exit_on_error=pick("exit-on-error") or "false",
        log_callback=log_callback,
    )
    save_config_content(migrated)
    _log(f"[OK] Migrated config to the legacy schema (backup: {backup})", log_callback)
    return True, migrated


def _build_config(*, storefront="us", language="", media_user_token="",
                  authorization_token="", alac_max="192000", atmos_max="2768",
                  aac_type="aac-lc", get_m3u8_mode="hires", folders=None,
                  album_folder="{AlbumName}", playlist_folder="{PlaylistName}",
                  song_file="{SongNumer}. {SongName}", lrc_type="lyrics",
                  lrc_format="lrc", lrc_embed="true", lrc_save="false",
                  cover_embed="true", cover_size="5000x5000", cover_format="jpg",
                  convert_after="false", convert_format="flac",
                  exit_on_error="false", log_callback=None):
    """Render a flat config.yaml for the legacy downloader."""
    folders = folders or dict(DEFAULT_SAVE_FOLDERS)
    ffmpeg = find_tool("ffmpeg") or "ffmpeg"

    def q(v):
        v = "" if v is None else str(v)
        return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'

    def b(v):
        return "true" if str(v).strip().lower() in ("true", "1", "yes", "on") else "false"

    def num(v, fallback):
        try:
            return str(int(str(v).strip()))
        except Exception:
            return str(fallback)

    return f"""media-user-token: {q(media_user_token)}
authorization-token: {q(authorization_token)}
language: {q(language)}
lrc-type: {q(lrc_type)}
lrc-format: {q(lrc_format)}
embed-lrc: {b(lrc_embed)}
save-lrc-file: {b(lrc_save)}
save-artist-cover: false
save-animated-artwork: false
embed-cover: {b(cover_embed)}
cover-size: {q(cover_size)}
cover-format: {q(cover_format)}
tag-sort-order: true
tag-itunes-id: true
alac-save-folder: {q(folders.get("alac", DEFAULT_SAVE_FOLDERS["alac"]))}
atmos-save-folder: {q(folders.get("atmos", DEFAULT_SAVE_FOLDERS["atmos"]))}
aac-save-folder: {q(folders.get("aac", DEFAULT_SAVE_FOLDERS["aac"]))}
mv-save-folder: {q(folders.get("mv", DEFAULT_SAVE_FOLDERS["mv"]))}
max-memory-limit: 256
decrypt-m3u8-port: "{WRAPPER_HOST}:{DECRYPT_PORT}"
get-m3u8-port: "{WRAPPER_HOST}:{M3U8_PORT}"
get-m3u8-from-device: true
exit-on-error: {b(exit_on_error)}
get-m3u8-mode: {q(get_m3u8_mode)}
aac-type: {q(aac_type)}
alac-max: {num(alac_max, 192000)}
atmos-max: {num(atmos_max, 2768)}
limit-max: 200
album-folder-format: {q(album_folder)}
playlist-folder-format: {q(playlist_folder)}
artist-folder-format: "{{UrlArtistName}}"
song-file-format: {q(song_file)}
explicit-choice: "[E]"
clean-choice: "[C]"
apple-master-choice: "[M]"
use-songinfo-for-playlist: false
dl-albumcover-for-playlist: false
mv-audio-type: "atmos"
mv-max: 2160
storefront: {q(storefront or "us")}
alac-fix: false
convert-after-download: {b(convert_after)}
convert-format: {q(convert_format)}
convert-keep-original: false
convert-skip-if-source-matches: true
ffmpeg-path: {q(ffmpeg)}
convert-extra-args: ""
convert-with-metadata: true
convert-warn-lossy-to-lossless: true
convert-skip-lossy-to-lossless: true
convert-check-bad-alac: false
"""


def get_save_folder(kind="alac"):
    content = load_config_content()
    folder = _config_get(content, f"{kind}-save-folder")
    folder = folder.strip().strip('"')
    if not folder:
        folder = DEFAULT_SAVE_FOLDERS.get(kind, "AM-DL downloads")
    if os.path.isabs(folder):
        return os.path.normpath(folder)
    return os.path.join(DOWNLOAD_DIR, folder)


def get_download_folder():
    return get_save_folder("alac")


# =====================================================================
# Tools
# =====================================================================

def find_tool(name):
    """Find a bundled tool in assets/, then PATH, then WinGet links."""
    exe = name if name.lower().endswith(".exe") else name + (".exe" if os.name == "nt" else "")
    bundled = os.path.join(DATA_DIR, "assets", exe)
    if os.path.isfile(bundled):
        return bundled
    found = shutil.which(name)
    if found:
        return found
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        for sub in ("Microsoft\\WinGet\\Links", "Microsoft\\WinGet\\Packages"):
            base = os.path.join(local, sub)
            if sub.endswith("Links"):
                cand = os.path.join(base, exe)
                if os.path.isfile(cand):
                    return cand
            elif os.path.isdir(base):
                for root, _dirs, files in os.walk(base):
                    if exe in files:
                        return os.path.join(root, exe)
    return None


def get_downloader_exe():
    """WSL path of the downloader binary, or None when it is not installed."""
    global _downloader_present
    if _downloader_present is None:
        _downloader_present = False
        if wsl_distro_present():
            try:
                r = _wsl("sh", "-c",
                         f"test -x {DOWNLOADER_WSL} && echo YES || echo NO", timeout=30)
                _downloader_present = "YES" in (r.stdout or "")
            except Exception:
                _downloader_present = False
    return DOWNLOADER_WSL if _downloader_present else None


def to_wsl_path(win_path):
    """Translate a Windows path to its WSL /mnt/<drive>/... form."""
    p = os.path.abspath(win_path)
    drive, rest = os.path.splitdrive(p)
    letter = (drive[:1] or "C").lower()
    rest = rest.replace("\\", "/").lstrip("/")
    return f"/mnt/{letter}/{rest}"


# =====================================================================
# WSL / wrapper helpers
# =====================================================================

def port_open(host=WRAPPER_HOST, port=DECRYPT_PORT, timeout=0.5, attempts=1):
    """True when host:port accepts a TCP connection.

    Keep this cheap. A closed port in WSL does not refuse the connection - the
    SYN is blackholed - so every attempt costs the full timeout. Three attempts
    on two ports once made a single status check take 5.3s. Retrying is left to
    the caller, which knows whether the extra latency is acceptable.
    """
    for i in range(max(1, attempts)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            if i + 1 < attempts:
                time.sleep(0.3)
    return False


def wrapper_running():
    """True when the wrapper is serving.

    One probe is enough: all four ports belong to the same process, so the
    account port is representative. Probing two ports doubled the worst-case
    latency for no extra information.
    """
    return port_open(port=ACCOUNT_PORT, timeout=0.5, attempts=1)


def wrapper_status(timeout=5):
    """Query the account-info service. Returns (ok, data, error).

    No port pre-check: an HTTP call answers the same question and costs one
    timeout instead of two. Previously the pre-check alone could take 5s.
    """
    try:
        url = f"http://{WRAPPER_HOST}:{ACCOUNT_PORT}/"
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
        if not body.strip():
            return True, {}, None
        return True, json.loads(body), None
    except Exception as e:
        return False, None, str(e)


def wsl_available():
    return os.name == "nt" and _wsl_bin() is not None


def _wsl_bin():
    found = shutil.which("wsl")
    if found:
        return found
    if os.name == "nt":
        root = os.environ.get("SystemRoot", r"C:\Windows")
        for sub in ("System32", "Sysnative"):
            cand = os.path.join(root, sub, "wsl.exe")
            if os.path.isfile(cand):
                return cand
    return None


def _wsl_env():
    env = os.environ.copy()
    env["WSL_UTF8"] = "1"
    return env


def _clean(s):
    if not s:
        return ""
    return s.replace("\x00", "").replace("\r", "")


def _wsl(*args, timeout=60):
    cmd = [_wsl_bin() or "wsl", "-d", resolve_wsl_distro(), "--"] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       timeout=timeout, env=_wsl_env(),
                       startupinfo=_SI, creationflags=_CF)
    r.stdout = _clean(r.stdout)
    r.stderr = _clean(r.stderr)
    return r


def _wsl_list_distros():
    if not wsl_available():
        return []
    try:
        r = subprocess.run([_wsl_bin(), "-l", "-q"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30,
                           env=_wsl_env(), startupinfo=_SI, creationflags=_CF)
        return [ln.strip() for ln in _clean(r.stdout).splitlines() if ln.strip()]
    except Exception:
        return []


def _wsl_running_distros():
    """Names of the distros that are running right now."""
    if not wsl_available():
        return []
    try:
        r = subprocess.run([_wsl_bin(), "--list", "--running", "--quiet"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30,
                           env=_wsl_env(), startupinfo=_SI, creationflags=_CF)
        return [ln.strip() for ln in _clean(r.stdout).splitlines() if ln.strip()]
    except Exception:
        return []


def _wsl_raw(*args, timeout=120):
    """Run wsl.exe with no distro/-d prefix (for --shutdown, --terminate, ...)."""
    cmd = [_wsl_bin() or "wsl"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          env=_wsl_env(), startupinfo=_SI, creationflags=_CF)


def shutdown_wsl_on_exit_enabled():
    """Should closing the app release the WSL VM?

    Default: yes. Override with the environment variable
    AMDL_SHUTDOWN_WSL_ON_EXIT=0 (keeps WSL running, so the next start is fast).

    Deliberately an env var and not a config.yaml key: that file is consumed by
    the legacy downloader, which should not receive keys it does not know.
    """
    val = (os.environ.get("AMDL_SHUTDOWN_WSL_ON_EXIT", "1") or "1").strip().lower()
    return val not in ("0", "false", "no", "off")


def shutdown_wsl(log_callback=None, force_all=False):
    """Stop the wrapper and release the WSL VM.

    `wsl --shutdown` terminates *every* distro, including Docker Desktop's.
    So when another distro is running, only ours is terminated and the VM is
    left alone - freeing memory must not break someone else's container.
    """
    if not wsl_available() or not wsl_distro_present():
        return False, "WSL or the distro is not available"

    ours = resolve_wsl_distro()
    stop_wrapper_service()
    _log("Shutting down WSL...", log_callback)

    running = _wsl_running_distros()
    others = [d for d in running if d != ours]
    if others and not force_all:
        try:
            _wsl_raw("--terminate", ours)
        except Exception as e:
            return False, f"Failed to terminate the distro: {e}"
        _log(f"Other distros are running ({', '.join(others)}); "
             f"terminated '{ours}' only and kept the VM alive.", log_callback)
        return False, "terminated our distro only (other distros are running)"

    try:
        _wsl_raw("--shutdown")
    except Exception as e:
        return False, f"wsl --shutdown failed: {e}"
    _log("WSL shut down.", log_callback)
    return True, "WSL shut down"


def wsl_distro_present():
    return resolve_wsl_distro() in _wsl_list_distros()


def wsl_diagnose():
    if os.name != "nt":
        return "not running on Windows"
    if _wsl_bin() is None:
        return "wsl.exe not found on PATH"
    try:
        r = subprocess.run([_wsl_bin(), "-l", "-q"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30,
                           env=_wsl_env(), startupinfo=_SI, creationflags=_CF)
    except Exception as e:
        return f"wsl -l failed: {e}"
    names = [ln.strip() for ln in _clean(r.stdout).splitlines() if ln.strip()]
    if WSL_DISTRO not in names:
        have = ", ".join(names) if names else "none"
        return f"distro '{WSL_DISTRO}' not found (installed: {have})"
    return ""


def wrapper_service_state():
    if not wsl_distro_present():
        return "unknown"
    try:
        r = _wsl("systemctl", "is-active", WSL_SERVICE, timeout=30)
        state = (r.stdout or "").strip()
        for known in ("active", "inactive", "failed", "activating", "deactivating"):
            if state.startswith(known):
                return known
        return state or "unknown"
    except Exception:
        return "unknown"


def start_wrapper_service(log_callback=None):
    if not wsl_available():
        return False, "WSL is not available on this system"
    if not wsl_distro_present():
        return False, f"WSL distro '{resolve_wsl_distro()}' not found"

    # Without cached Apple credentials the wrapper initialises, finds no token
    # and exits with status 0 - it never opens the ports. Saying so right away
    # beats waiting out the readiness timeout and reporting "not ready".
    if not login_cached():
        return False, ("Apple Music is not signed in yet, so the wrapper cannot "
                       "start. Sign in first (the login page in the GUI, or menu "
                       "'L' in the CLI), then try again.")

    _log(f"Starting {WSL_SERVICE} in WSL distro {resolve_wsl_distro()}...", log_callback)
    try:
        _wsl("systemctl", "start", WSL_SERVICE, timeout=120)
    except Exception as e:
        return False, f"Failed to start wrapper service: {e}"
    for _ in range(30):
        time.sleep(2)
        if wrapper_running():
            return True, f"wrapper running ({DECRYPT_PORT}/{M3U8_PORT}/{ACCOUNT_PORT})"
    # Ports still closed: surface the log tail instead of a bare timeout.
    tail = wrapper_log_tail(6).strip()
    if tail:
        _log(tail, log_callback)
    return False, "wrapper did not become ready (see the log above)"


def stop_wrapper_service():
    try:
        if wsl_distro_present():
            _wsl("systemctl", "stop", WSL_SERVICE, timeout=60)
    except Exception:
        pass


def restart_wrapper_service(log_callback=None):
    try:
        _wsl("systemctl", "restart", WSL_SERVICE, timeout=120)
    except Exception as e:
        return False, f"Restart failed: {e}"
    for _ in range(30):
        time.sleep(2)
        if wrapper_running():
            return True, "wrapper restarted"
    return False, "wrapper did not come back up"


def wrapper_log_tail(lines=40):
    if not wsl_distro_present():
        return ""
    try:
        r = _wsl("sh", "-c",
                 f"tail -n {int(lines)} /var/log/apple-music-wrapper.log 2>/dev/null",
                 timeout=30)
        return r.stdout or ""
    except Exception:
        return ""


def login_cached():
    """True when the wrapper has cached Apple Music credentials."""
    if not wsl_distro_present():
        return False
    try:
        r = _wsl("sh", "-c",
                 f"test -s {WRAPPER_BASE_DIR_ABS}/MUSIC_TOKEN && echo YES || echo NO",
                 timeout=30)
        return "YES" in (r.stdout or "")
    except Exception:
        return False


def stop_wrapper():
    stop_wrapper_service()


def shutdown_wsl_detached():
    """Release the WSL VM without blocking the caller.

    Used when the app closes: the GUI thread must not sit and wait for
    `systemctl stop` plus `wsl --shutdown`, so the real work is handed to a
    detached process that outlives this one.
    """
    if not wsl_available():
        return False
    try:
        ours = resolve_wsl_distro()
        others = []
        if wsl_distro_present():
            others = [d for d in _wsl_running_distros() if d != ours]

        if ours and not others:
            args = [_wsl_bin() or "wsl", "--shutdown"]
        elif ours:
            # Another distro (e.g. docker-desktop) is active - only drop ours.
            args = [_wsl_bin() or "wsl", "--terminate", ours]
        else:
            return False

        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(args, creationflags=flags, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, env=_wsl_env())
        return True
    except Exception:
        return False


def wrapper_health_after_run(log_callback=None, crashed_hint=False):
    """Make sure the wrapper is healthy after a download run."""
    if wrapper_running():
        return True
    _log("[WARN] wrapper is not responding; waiting for systemd to restart it...",
         log_callback)
    for _ in range(15):
        time.sleep(2)
        if wrapper_running():
            _log("[OK] wrapper is back up.", log_callback)
            return True
    ok, msg = restart_wrapper_service(log_callback)
    if ok:
        _log("[OK] wrapper restarted.", log_callback)
        return True
    _log(f"[ERROR] Could not restart wrapper: {msg}", log_callback)
    return False


# =====================================================================
# Login
# =====================================================================

def _tail_log(path="/var/log/wrapper-login.log", lines=60):
    try:
        r = _wsl("sh", "-c", f"tail -n {int(lines)} {path} 2>/dev/null", timeout=20)
        return r.stdout or ""
    except Exception:
        return ""


def _shquote(s):
    if s is None:
        return "''"
    return "'" + str(s).replace("'", "'\\''") + "'"


def _restart_service(log_callback=None):
    _log("Restarting the wrapper service...", log_callback)
    try:
        _wsl("systemctl", "start", WSL_SERVICE, timeout=120)
    except Exception:
        pass


def _wsl_input(text, *args, timeout=60):
    """Run a command in WSL, feeding `text` on stdin (no shell parsing).

    The payload is sent as raw bytes: in text mode Python rewrites "\\n" to
    "\\r\\n" on Windows, and a CRLF shell script makes bash fail with
    "ambiguous redirect".
    """
    cmd = [_wsl_bin() or "wsl", "-d", resolve_wsl_distro(), "--"] + list(args)
    payload = str(text).replace("\r\n", "\n").encode("utf-8")
    r = subprocess.run(cmd, input=payload, capture_output=True,
                       timeout=timeout, env=_wsl_env(),
                       startupinfo=_SI, creationflags=_CF)
    # Bytes in, bytes out: decode here instead of letting Popen pick text mode.
    r.stdout = (r.stdout or b"").decode("utf-8", "replace")
    r.stderr = (r.stderr or b"").decode("utf-8", "replace")
    return r


def _reset_login_state(log_callback=None):
    """Move leftover account databases aside before a fresh sign-in.

    A stale mpl_db/adi.pb left by an earlier attempt makes the wrapper exit
    silently right after credentialHandler instead of reporting an auth error,
    so signing in from that state looks like a no-op failure. The old state is
    kept under /tmp/wrapper-login-backup in case it is ever needed.
    """
    try:
        r = _wsl("sh", "-c",
                 "mkdir -p /tmp/wrapper-login-backup && "
                 f"if [ -d {WRAPPER_BASE_DIR_ABS} ]; then "
                 f"  mv {WRAPPER_BASE_DIR_ABS} /tmp/wrapper-login-backup/files-$(date +%Y%m%d-%H%M%S) "
                 f"  2>/dev/null || rm -rf {WRAPPER_BASE_DIR_ABS}/*; "
                 "fi; "
                 f"mkdir -p {WRAPPER_BASE_DIR_ABS} && "
                 f"ls -A {WRAPPER_BASE_DIR_ABS} | wc -l",
                 timeout=60)
        if r.returncode == 0:
            _log("Cleared the previous sign-in state (backup: /tmp/wrapper-login-backup).",
                 log_callback)
        else:
            _log("[WARN] Could not fully clear the previous sign-in state.", log_callback)
    except Exception as e:
        _log(f"[WARN] Could not clear the previous sign-in state: {e}", log_callback)


def wrapper_login(username, password, log_callback=None, twofa_callback=None,
                  timeout=300):
    """Sign in through the legacy wrapper inside WSL.

    Runs `wrapper -L user:pass -F`, which caches credentials into its data dir.
    The 2FA code is delivered via `<base>/2fa.txt`.
    """
    if not wsl_distro_present():
        return False, f"WSL distro '{WSL_DISTRO}' not found"

    _log("Stopping the wrapper service for a one-off login run...", log_callback)
    try:
        _wsl("systemctl", "stop", WSL_SERVICE, timeout=60)
    except Exception:
        pass

    _reset_login_state(log_callback)

    log_path = "/var/log/wrapper-login.log"
    runner = "/tmp/wrapper-login.sh"
    cred_file = "/tmp/wrapper-login.cred"

    # Two quirks are handled here, both found by testing against the real binary:
    #
    # 1. The wrapper must not be the direct child of the wsl.exe session. When
    #    it is, it prints up to credentialHandler and exits 0 without ever
    #    reporting an auth error - login looks like a silent no-op.
    # 2. Credentials travel as positional arguments to the inner `sh -c`, not
    #    through a shell string, so no password character can break the quoting.
    script = (
        "#!/bin/bash\n"
        f"U=$(sed -n 1p {cred_file} 2>/dev/null)\n"
        f"P=$(sed -n 2p {cred_file} 2>/dev/null)\n"
        f"rm -f {cred_file}\n"
        f"rm -f {log_path}\n"
        "sh -c 'cd /opt/wrapper && exec ./wrapper -L \"$1:$2\" -F -H 0.0.0.0' "
        f"_ \"$U\" \"$P\" > {log_path} 2>&1\n"
    )
    try:
        # Both files are written through stdin. Building them as shell strings
        # broke on quoting: the embedded single quotes ended the outer quoted
        # region, so "$1"/"$2" were expanded by the outer shell and the wrapper
        # received "-L ':'" - empty credentials, which it rejects by exiting
        # silently right after credentialHandler.
        _wsl_input(script, "sh", "-c", f"cat > {runner} && chmod +x {runner}", timeout=30)
        _wsl_input(f"{username}\n{password}\n", "sh", "-c",
                   f"cat > {cred_file} && chmod 600 {cred_file}", timeout=30)
    except Exception as e:
        _restart_service(log_callback)
        return False, f"Failed to prepare the login script: {e}"

    cmd = [
        _wsl_bin() or "wsl", "-d", WSL_DISTRO, "--",
        "bash", runner,
    ]

    _log("Launching wrapper login (this may take ~30s)...", log_callback)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, env=_wsl_env(),
                                startupinfo=_SI, creationflags=_CF)
    except Exception as e:
        _restart_service(log_callback)
        return False, f"Failed to start login: {e}"

    printed = 0
    twofa_sent = False
    success = False
    deadline = time.time() + timeout

    while proc.poll() is None and time.time() < deadline:
        time.sleep(2)
        log = _tail_log(log_path, 200)
        lines = [ln for ln in log.splitlines() if ln.strip()]
        for line in lines[printed:]:
            _log(line.strip(), log_callback)
        printed = len(lines)

        # After a successful sign-in the wrapper does NOT exit - it keeps
        # running and starts serving the decrypt/account ports. Waiting for the
        # process to end therefore always hit the timeout and reported a false
        # "Login timed out" even though the credentials were already cached.
        if ("account info cached successfully" in log) or ("Music-Token:" in log):
            success = True
            break

        if twofa_callback and not twofa_sent:
            if ("2FA: true" in log) or ("Enter your 2FA code" in log):
                _log("Two-factor authentication required.", log_callback)
                code = twofa_callback()
                if code and str(code).strip():
                    _log("Delivering 2FA code...", log_callback)
                    try:
                        _wsl("sh", "-c",
                             f"mkdir -p {WRAPPER_BASE_DIR_ABS} && "
                             f"printf '%s' {_shquote(str(code).strip())} > "
                             f"{WRAPPER_BASE_DIR_ABS}/2fa.txt",
                             timeout=30)
                        twofa_sent = True
                    except Exception as e:
                        _log(f"[ERROR] Failed to deliver 2FA code: {e}", log_callback)
                else:
                    _log("[WARN] No 2FA code provided", log_callback)

    if success:
        # This ad-hoc instance is already listening on the wrapper ports; stop
        # it and let the managed systemd unit take over.
        try:
            proc.kill()
            proc.wait(timeout=10)
        except Exception:
            pass
        _restart_service(log_callback)
        return True, "Login successful. Credentials cached."

    if proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
        _log("[ERROR] Login timed out", log_callback)
        _restart_service(log_callback)
        return False, "Login timed out"

    log = _tail_log(log_path, 2000)
    lines = [ln for ln in log.splitlines() if ln.strip()]
    for line in lines[printed:]:
        _log(line.strip(), log_callback)

    # Exit code is genuinely diagnostic here: a wrong password prints an auth
    # error, while a crash (>=128, e.g. 139 = SIGSEGV) prints nothing at all.
    rc = proc.returncode
    if rc is not None and rc >= 128:
        _log(f"[ERROR] The wrapper crashed during login (exit code {rc}, "
             f"signal {rc - 128}).", log_callback)
    elif rc not in (0, None):
        _log(f"[ERROR] The wrapper exited with code {rc}.", log_callback)
    else:
        _log(f"[*] wrapper exit code: {rc}", log_callback)

    tok_ok = False
    try:
        chk = _wsl("sh", "-c",
                   f"test -s {WRAPPER_BASE_DIR_ABS}/MUSIC_TOKEN && echo YES || echo NO",
                   timeout=30)
        tok_ok = "YES" in (chk.stdout or "")
    except Exception:
        pass

    if not tok_ok:
        try:
            state = _wsl("sh", "-c",
                         f"ls -la {WRAPPER_BASE_DIR_ABS}/ 2>/dev/null; "
                         f"echo '---mpl_db---'; "
                         f"ls -la {WRAPPER_BASE_DIR_ABS}/mpl_db/ 2>/dev/null | head -6",
                         timeout=30)
            if state.stdout:
                _log("[*] credential dir after login:", log_callback)
                for ln in state.stdout.splitlines():
                    if ln.strip():
                        _log("    " + ln.strip(), log_callback)
        except Exception:
            pass

    _restart_service(log_callback)

    if tok_ok:
        return True, "Login successful. Credentials cached."

    # Turn the log into an actionable reason instead of a generic failure.
    low = (log or "").lower()
    if "check the account information" in low:
        return False, "Apple rejected the sign-in: check the Apple ID and password."
    if "auth error" in low:
        return False, "Apple returned an authentication error - see the log above."
    if "2fa: true" in low or "verification code" in low:
        return False, "Apple asked for two-factor verification, but it did not complete."
    if rc is not None and rc >= 128:
        return False, (f"The wrapper crashed during sign-in (exit code {rc}). "
                       f"See the log above.")
    return False, "Login failed - check the log above for details."


# =====================================================================
# media-user-token
# =====================================================================

MEDIA_TOKEN_COOKIE = "media-user-token"

_CHROMIUM_PROFILES = ("Default", "Profile 1", "Profile 2", "Profile 3", "Profile 4")


def _chromium_bases():
    local = os.environ.get("LOCALAPPDATA", "")
    return [
        ("Edge", os.path.join(local, "Microsoft", "Edge", "User Data")),
        ("Chrome", os.path.join(local, "Google", "Chrome", "User Data")),
        ("Brave", os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data")),
    ]


def _firefox_cookie_dbs():
    base = os.path.join(os.environ.get("APPDATA", ""), "Mozilla", "Firefox", "Profiles")
    dbs = []
    try:
        if os.path.isdir(base):
            for name in os.listdir(base):
                p = os.path.join(base, name, "cookies.sqlite")
                if os.path.isfile(p):
                    dbs.append((name, p))
    except Exception:
        pass
    return dbs


def _copy_for_read(path):
    """Copy a possibly-locked SQLite file to a temp path for reading."""
    tmp = tempfile.mktemp(suffix=".sqlite")
    with open(path, "rb") as src, open(tmp, "wb") as dst:
        dst.write(src.read())
    return tmp


def read_firefox_media_user_token():
    """Firefox stores cookies in plain SQLite, so the value can be read out."""
    import sqlite3
    found = []
    for profile, db in _firefox_cookie_dbs():
        tmp = None
        try:
            tmp = _copy_for_read(db)
            con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
            try:
                rows = con.execute(
                    "SELECT value FROM moz_cookies "
                    "WHERE name = ? AND host LIKE '%music.apple.com%'",
                    (MEDIA_TOKEN_COOKIE,),
                ).fetchall()
            finally:
                con.close()
            for (value,) in rows:
                value = (value or "").strip()
                if len(value) > 50:
                    found.append((value, f"Firefox/{profile}"))
        except Exception:
            pass
        finally:
            if tmp and os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
    return found


def chromium_token_presence():
    """Which Chromium browsers hold a media-user-token cookie.

    Chromium encrypts cookie values with DPAPI + AES-GCM, so the value itself
    cannot be read here; this only tells the user where to copy it from.
    Returns (browser, profile, state) with state True/False/None (None = locked).
    """
    import sqlite3
    report = []
    for label, base in _chromium_bases():
        if not os.path.isdir(base):
            continue
        for prof in _CHROMIUM_PROFILES:
            db = os.path.join(base, prof, "Network", "Cookies")
            if not os.path.isfile(db):
                continue
            tmp = None
            state = None
            try:
                tmp = _copy_for_read(db)
                con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
                try:
                    n = con.execute(
                        "SELECT COUNT(*) FROM cookies "
                        "WHERE name = ? AND host_key LIKE '%music.apple.com%'",
                        (MEDIA_TOKEN_COOKIE,),
                    ).fetchone()[0]
                    state = n > 0
                finally:
                    con.close()
            except Exception:
                state = None
            finally:
                if tmp and os.path.isfile(tmp):
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
            report.append((label, prof, state))
    return report


def find_media_user_token():
    """Best-effort automatic discovery.

    Returns (token_or_None, source, notes); notes explains what was checked so
    the UI can guide the user when nothing could be read automatically.
    """
    notes = []
    found = read_firefox_media_user_token()
    if found:
        return found[0][0], found[0][1], notes

    if not _firefox_cookie_dbs():
        notes.append("Firefox: not installed / no profile")
    else:
        notes.append("Firefox: no music.apple.com media-user-token cookie")

    for browser, prof, state in chromium_token_presence():
        if state is True:
            notes.append(f"{browser}/{prof}: cookie present, but its value is "
                         f"encrypted by the browser - copy it manually")
        elif state is None:
            notes.append(f"{browser}/{prof}: cookie database is locked")

    return None, None, notes


def wrapper_dev_token(timeout=10):
    """Developer token reported by the wrapper's account service."""
    try:
        url = f"http://{WRAPPER_HOST}:{ACCOUNT_PORT}/"
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return (data or {}).get("dev_token") or ""
    except Exception:
        return ""


def validate_media_user_token(token, timeout=20):
    """Check a media-user-token against Apple. Returns (ok, detail)."""
    token = (token or "").strip()
    if not token:
        return False, "empty token"
    if len(token) < 50:
        return False, "token looks too short - copy the whole cookie value"
    dev = wrapper_dev_token()
    if not dev:
        return False, ("the wrapper account service is not answering - "
                       "make sure the wrapper is running")
    req = urllib.request.Request(
        "https://amp-api.music.apple.com/v1/me/storefront",
        headers={
            "Authorization": f"Bearer {dev}",
            "Music-User-Token": token,
            "Origin": "https://music.apple.com",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
        if r.status == 200:
            try:
                storefront = (json.loads(body).get("data") or [{}])[0].get("id")
            except Exception:
                storefront = None
            return True, (f"valid (storefront: {storefront})" if storefront else "valid")
        return False, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, f"Apple rejected this token (HTTP {e.code}) - wrong or expired"
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


def save_media_user_token(token):
    """Write the token into config.yaml, leaving the rest of the file untouched."""
    token = (token or "").strip()
    content = load_config_content()
    line = f'media-user-token: "{token}"'
    if re.search(r'^[ \t]*media-user-token\s*:', content, re.MULTILINE):
        content = re.sub(r'^[ \t]*media-user-token\s*:.*$', line, content,
                         count=1, flags=re.MULTILINE)
    else:
        content = content.rstrip("\n") + "\n" + line + "\n"
    return save_config_content(content)


# =====================================================================
# Downloader
# =====================================================================

def build_downloader_command(dl_args, workdir_win):
    """Build the subprocess argv used to run the downloader inside WSL.

    The legacy downloader reads config.yaml from its working directory, so the
    WSL side cd's into the (Windows) temp dir that holds the generated config.
    Returns None when the downloader is not installed.
    """
    import shlex
    exe = get_downloader_exe()
    if not exe:
        return None
    workdir_wsl = to_wsl_path(workdir_win)
    inner = (f"cd {shlex.quote(workdir_wsl)} && exec {exe} "
             + " ".join(shlex.quote(str(a)) for a in dl_args))
    return [_wsl_bin() or "wsl", "-d", WSL_DISTRO, "--", "sh", "-c", inner]


def downloader_env():
    env = os.environ.copy()
    env["WSL_UTF8"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


_RUN_DIRS = []


def _sweep_stale_run_dirs(max_age_seconds=7200):
    """Delete leftover am_run_* dirs from earlier runs.

    A run dir holds a config.yaml containing media-user-token, so stale copies
    must not linger in %TEMP% if a previous process died before cleaning up.
    """
    tmp = tempfile.gettempdir()
    now = time.time()
    try:
        for name in os.listdir(tmp):
            if not name.startswith("am_run_"):
                continue
            path = os.path.join(tmp, name)
            try:
                if os.path.isdir(path) and (now - os.path.getmtime(path)) > max_age_seconds:
                    shutil.rmtree(path, ignore_errors=True)
            except Exception:
                continue
    except Exception:
        pass


def _cleanup_all_run_dirs():
    for d in list(_RUN_DIRS):
        cleanup_run_config(d)


atexit.register(_cleanup_all_run_dirs)


def prepare_run_config():
    """Materialise a runnable config.yaml in a temp working directory.

    The legacy downloader reads config.yaml from its working directory and has
    no --config flag, so we hand it a temp dir whose config points the save
    folders at absolute **WSL** paths (the binary runs inside WSL).

    Returns (workdir_win, config_path_win).
    """
    _sweep_stale_run_dirs()
    content = load_config_content()
    workdir = tempfile.mkdtemp(prefix="am_run_")
    _RUN_DIRS.append(workdir)

    for kind in DEFAULT_SAVE_FOLDERS:
        wsl_dir = to_wsl_path(get_save_folder(kind))
        key = f"{kind}-save-folder"
        pattern = re.compile(rf'^([ \t]*{re.escape(key)}[ \t]*:[ \t]*).*$', re.MULTILINE)

        def repl(m, _v=wsl_dir):
            return f'{m.group(1)}"{_v}"'

        if pattern.search(content):
            content = pattern.sub(repl, content)
        else:
            content += f'\n{key}: "{wsl_dir}"\n'

    path = os.path.join(workdir, "config.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return workdir, path


def cleanup_run_config(workdir):
    """Remove the temp working directory, retrying briefly.

    A single shutil.rmtree often fails on Windows because the downloader
    subprocess still holds the directory as its CWD - the old code passed
    ignore_errors=True, so the config.yaml (containing media-user-token) could
    survive and empty am_run_* dirs piled up in %TEMP%.
    """
    if not workdir:
        return
    for attempt in range(6):
        try:
            shutil.rmtree(workdir)
            break
        except FileNotFoundError:
            break
        except Exception:
            if attempt == 5:
                # Last resort: at least destroy the credentials.
                try:
                    os.remove(os.path.join(workdir, "config.yaml"))
                except Exception:
                    pass
            else:
                time.sleep(0.25)
    try:
        _RUN_DIRS.remove(workdir)
    except ValueError:
        pass

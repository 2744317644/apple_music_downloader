#!/usr/bin/env python3
"""Apple Music ALAC Downloader - Shared utilities for CLI and GUI."""

import os
import re
import sys
import time
import shutil
import subprocess
import tempfile
import threading

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
CONFIG_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AppleMusicDownloader", "config.yaml")
CONFIG_EXAMPLE = os.path.join(DATA_DIR, "config.yaml.example")
CONFIG_EXAMPLE_ALT = os.path.join(DATA_DIR, "assets", "apple-music-downloader", "config.yaml.example")
APP_DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AppleMusicDownloader")

# ---- Docker image constants ----
WRAPPER_SRC = os.environ.get("WRAPPER_SRC", os.path.join(DATA_DIR, "assets", "Wrapper"))
WRAPPER_IMAGE = "wrapper:local"
WRAPPER_NAME = "am-wrapper"
WRAPPER_DATA_DIR = os.path.join(APP_DATA_DIR, "wrapper-data")

DECRYPT_PORT = 10020
M3U8_PORT = 20020
ACCOUNT_PORT = 30020

REGISTRY_MIRROR = os.environ.get("REGISTRY_MIRROR", "")

MIRROR_PROFILES = {
    "cn": {
        "label": "国内镜像",
        "registry": "docker.m.daocloud.io",
        "apt": "mirrors.tuna.tsinghua.edu.cn",
        "goproxy": "https://goproxy.cn,direct",
    },
    "intl": {
        "label": "国际源 (Docker Hub)",
        "registry": "docker.io",
        "apt": "",
        "goproxy": "https://proxy.golang.org,direct",
    },
}

DL_SRC = os.environ.get("DL_SRC", os.path.join(DATA_DIR, "assets", "apple-music-downloader"))
DL_IMAGE = "apple-music-downloader:local"


def _log(msg, log_callback=None):
    if log_callback:
        log_callback(msg)


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


def get_download_folder():
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


# ---- Docker helpers ----

def wrapper_running():
    try:
        r = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name={WRAPPER_NAME}"],
            capture_output=True, text=True,
            startupinfo=_SI, creationflags=_CF
        )
        return len(r.stdout.strip()) > 0
    except Exception:
        return False


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
        try:
            r = subprocess.run(["docker", "images", "-q", target], capture_output=True, text=True,
                               startupinfo=_SI, creationflags=_CF)
            if r.stdout.strip():
                continue
        except Exception:
            continue
        for repo_tag in _get_all_image_repos():
            if repo_tag == target:
                continue
            if any(h in repo_tag.lower() for h in hints):
                _log(f"Auto-tagging {repo_tag} -> {target}", log_callback)
                subprocess.run(["docker", "tag", repo_tag, target],
                               startupinfo=_SI, creationflags=_CF)
                break


def load_docker_image(tar_path, log_callback=None):
    if not os.path.isfile(tar_path):
        msg = f"File not found: {tar_path}"
        _log(f"[ERROR] {msg}", log_callback)
        return False, msg
    _log(f"Loading image from: {tar_path}", log_callback)
    try:
        result = subprocess.run(
            ["docker", "load", "-i", tar_path],
            capture_output=True, text=True,
            startupinfo=_SI, creationflags=_CF
        )
        if result.returncode == 0:
            msg = result.stdout.strip()
            _log(f"[OK] {msg}", log_callback)
            return True, msg
        else:
            err = result.stderr.strip() or result.stdout.strip()
            _log(f"[ERROR] docker load failed: {err[:500]}", log_callback)
            return False, err[:500]
    except Exception as e:
        msg = str(e)
        _log(f"[ERROR] {msg}", log_callback)
        return False, msg


def load_images_from_dir(image_dir, log_callback=None):
    if not os.path.isdir(image_dir):
        _log(f"[ERROR] Directory not found: {image_dir}", log_callback)
        return
    tar_files = sorted([f for f in os.listdir(image_dir) if f.endswith('.tar')])
    if not tar_files:
        _log(f"[WARN] No .tar files found in: {image_dir}", log_callback)
        return
    _log(f"Found {len(tar_files)} .tar file(s) in: {image_dir}", log_callback)
    for tf in tar_files:
        load_docker_image(os.path.join(image_dir, tf), log_callback)
    _auto_tag_images(log_callback)


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
        try:
            r = subprocess.run(["docker", "images", "-q", image], capture_output=True, text=True,
                               startupinfo=_SI, creationflags=_CF)
            if not r.stdout.strip():
                _log(f"[WARN] Image '{image}' not found, skipping", log_callback)
                all_ok = False
                continue
        except Exception:
            all_ok = False
            continue
        _log(f"Exporting {label}: {image} -> {tar_path}", log_callback)
        code = subprocess.run(["docker", "save", "-o", tar_path, image],
                              startupinfo=_SI, creationflags=_CF).returncode
        if code == 0:
            _log(f"[OK] Exported: {tar_path}", log_callback)
        else:
            _log(f"[ERROR] Failed to export {image}", log_callback)
            all_ok = False
    if all_ok:
        _log(f"[OK] All images exported to: {output_dir}", log_callback)
    return all_ok


def build_wrapper_image(profile="cn", log_callback=None):
    src = WRAPPER_SRC
    if not os.path.isdir(src):
        return False, f"Wrapper source not found: {src}"
    dockerfile = os.path.join(src, "Dockerfile")
    if not os.path.isfile(dockerfile):
        return False, f"{src} must contain Dockerfile"
    p = MIRROR_PROFILES.get(profile, MIRROR_PROFILES["cn"])
    _log(f"Building wrapper image from: {src}", log_callback)
    _log(f"  Registry: {p['registry']}", log_callback)
    err_lines = []
    proc = subprocess.Popen(
        ["docker", "build",
         "--build-arg", f"REGISTRY_MIRROR={p['registry']}",
         "--tag", WRAPPER_IMAGE, src],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        startupinfo=_SI, creationflags=_CF
    )
    for line in proc.stdout:
        line = line.strip()
        if line:
            _log(line, log_callback)
            err_lines.append(line)
    proc.wait()
    if proc.returncode != 0:
        err = "\n".join(err_lines[-10:]) or "Unknown error"
        return False, f"Build failed: {err[:500]}"
    return True, f"Wrapper image built: {WRAPPER_IMAGE}"


def build_downloader_image(profile="cn", log_callback=None):
    src = DL_SRC
    if not os.path.isdir(src):
        return False, f"Downloader source not found: {src}"
    dockerfile = os.path.join(src, "Dockerfile")
    if not os.path.isfile(dockerfile):
        return False, f"{src} must contain Dockerfile"
    p = MIRROR_PROFILES.get(profile, MIRROR_PROFILES["cn"])
    _log(f"Building downloader image from: {src}", log_callback)
    _log(f"  Registry: {p['registry']}, APT: {p['apt'] or 'default'}, GoProxy: {p['goproxy']}", log_callback)
    err_lines = []
    proc = subprocess.Popen(
        ["docker", "build",
         "--build-arg", f"REGISTRY_MIRROR={p['registry']}",
         "--build-arg", f"APT_MIRROR={p['apt']}",
         "--build-arg", f"GOPROXY={p['goproxy']}",
         "--tag", DL_IMAGE, src],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        startupinfo=_SI, creationflags=_CF
    )
    for line in proc.stdout:
        line = line.strip()
        if line:
            _log(line, log_callback)
            err_lines.append(line)
    proc.wait()
    if proc.returncode != 0:
        err = "\n".join(err_lines[-10:]) or "Unknown error"
        return False, f"Build failed: {err[:500]}"
    return True, f"Downloader image built: {DL_IMAGE}"


def wrapper_login(username, password, log_callback=None, twofa_callback=None):
    os.makedirs(WRAPPER_DATA_DIR, exist_ok=True)
    subprocess.run(["docker", "rm", "-f", f"{WRAPPER_NAME}-login"], capture_output=True,
                   startupinfo=_SI, creationflags=_CF)

    db_file = os.path.join(
        os.path.abspath(WRAPPER_DATA_DIR),
        "data", "com.apple.android.music", "files", "mpl_db", "kvs.sqlitedb"
    )

    _log("Launching wrapper login container...", log_callback)
    data_dir = os.path.abspath(WRAPPER_DATA_DIR)
    cmd = [
        "docker", "run", "-i", "--rm",
        "--name", f"{WRAPPER_NAME}-login",
        "--privileged",
        "-v", f"{data_dir}:/app/rootfs/data",
        "-e", f"USERNAME={username}",
        "-e", f"PASSWORD={password}",
        "--entrypoint", "/bin/sh",
        WRAPPER_IMAGE,
        "-c",
        "mkdir -p /app/rootfs/system/usr/share/zoneinfo /app/rootfs/etc; "
        "cp /usr/share/zoneinfo/tzdata.zi /app/rootfs/system/usr/share/zoneinfo/tzdata; "
        "cp /etc/hosts /app/rootfs/etc/hosts; "
        "cp /etc/resolv.conf /app/rootfs/etc/resolv.conf; "
        "export ANDROID_ROOT=/app/rootfs/system; "
        "export ANDROID_DATA=/app/rootfs/data; "
        "mkdir -p /app/rootfs/data/data/com.apple.android.music/files/mpl_db; "
        "exec /app/wrapper -L ${USERNAME}:${PASSWORD} -F -H 0.0.0.0",
    ]

    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            startupinfo=_SI, creationflags=_CF
        )
    except Exception as e:
        return False, f"Failed to start login container: {e}"

    twofa_sent = False

    def _read_output():
        nonlocal twofa_sent
        buf = ""
        try:
            for ch in iter(lambda: proc.stdout.read(1), ""):
                if ch in ("\r", "\n"):
                    line = buf.strip()
                    if line:
                        _log(line, log_callback)
                        if "2FA: true" in line and not twofa_sent:
                            twofa_sent = True
                            code = None
                            if twofa_callback:
                                code = twofa_callback()
                            if code:
                                _log("Sending 2FA code...", log_callback)
                                try:
                                    twofa_file = os.path.join(
                                        os.path.abspath(WRAPPER_DATA_DIR),
                                        "data", "com.apple.android.music", "files", "2fa.txt"
                                    )
                                    with open(twofa_file, "w", encoding="utf-8") as f:
                                        f.write(code)
                                except Exception:
                                    _log("[ERROR] Failed to write 2FA code file", log_callback)
                            else:
                                _log("[WARN] No 2FA code provided", log_callback)
                    buf = ""
                else:
                    buf += ch
        except Exception:
            pass

    reader = threading.Thread(target=_read_output, daemon=True)
    reader.start()

    _log("Waiting for credential database...", log_callback)
    waited = 0
    while not os.path.isfile(db_file) and waited < 180:
        time.sleep(2)
        waited += 2
        if proc.poll() is not None:
            break

    if not os.path.isfile(db_file):
        try:
            proc.kill()
        except Exception:
            pass
        reader.join(timeout=3)
        _log("[ERROR] Login failed", log_callback)
        subprocess.run(["docker", "rm", "-f", f"{WRAPPER_NAME}-login"], capture_output=True,
                       startupinfo=_SI, creationflags=_CF)
        return False, "Login failed."

    _log("[OK] Credential database created", log_callback)

    fsi_file = os.path.join(
        os.path.abspath(WRAPPER_DATA_DIR),
        "data", "com.apple.android.music", "files", "fsi.pdat"
    )

    _log("Waiting for FairPlay registration...", log_callback)
    waited = 0
    while not os.path.isfile(fsi_file) and waited < 120:
        time.sleep(2)
        waited += 2
        if proc.poll() is not None:
            break

    try:
        proc.kill()
    except Exception:
        pass
    reader.join(timeout=3)
    subprocess.run(["docker", "rm", "-f", f"{WRAPPER_NAME}-login"], capture_output=True,
                   startupinfo=_SI, creationflags=_CF)

    if os.path.isfile(fsi_file):
        _log("[OK] FairPlay registered", log_callback)
        return True, "Login successful. Credentials cached."

    _log("[WARN] FairPlay not registered, may retry on first download", log_callback)
    return False, "Login may have failed."


def _build_wrapper_docker_run_args(detach=True, with_ports=True):
    data_dir = os.path.abspath(WRAPPER_DATA_DIR)
    args = ["docker", "run"]
    args.append("-dit" if detach else "--rm")
    args.extend(["--name", WRAPPER_NAME])
    args.append("--privileged")
    args.extend(["-v", f"{data_dir}:/app/rootfs/data"])
    if with_ports:
        args.extend([
            "-p", f"{DECRYPT_PORT}:{DECRYPT_PORT}",
            "-p", f"{M3U8_PORT}:{M3U8_PORT}",
            "-p", f"{ACCOUNT_PORT}:{ACCOUNT_PORT}",
        ])
    args.extend(["--entrypoint", "/bin/sh", WRAPPER_IMAGE])
    args.extend(["-c",
        "mkdir -p /app/rootfs/system/usr/share/zoneinfo /app/rootfs/etc; "
        "cp /usr/share/zoneinfo/tzdata.zi /app/rootfs/system/usr/share/zoneinfo/tzdata; "
        "cp /etc/hosts /app/rootfs/etc/hosts; "
        "cp /etc/resolv.conf /app/rootfs/etc/resolv.conf; "
        "export ANDROID_ROOT=/app/rootfs/system; "
        "export ANDROID_DATA=/app/rootfs/data; "
        "exec /app/wrapper -H 0.0.0.0"
    ])
    return args


def do_start_wrapper(log_callback=None):
    if wrapper_running():
        return True, "Wrapper is already running"
    os.makedirs(WRAPPER_DATA_DIR, exist_ok=True)
    data_dir = os.path.abspath(WRAPPER_DATA_DIR)

    try:
        r = subprocess.run(["docker", "images", "-q", WRAPPER_IMAGE], capture_output=True, text=True,
                           startupinfo=_SI, creationflags=_CF)
        if not r.stdout.strip():
            return False, f"Wrapper image '{WRAPPER_IMAGE}' not found"
    except Exception:
        return False, "Docker not available"

    db_file = os.path.join(data_dir, "data", "com.apple.android.music", "files", "mpl_db", "kvs.sqlitedb")
    fsi_file = os.path.join(data_dir, "data", "com.apple.android.music", "files", "fsi.pdat")
    if os.path.isfile(db_file) and not os.path.isfile(fsi_file):
        _log("[WARN] Incomplete login detected, clearing credentials...", log_callback)
        try:
            os.remove(db_file)
        except Exception:
            pass
    if not os.path.isfile(db_file) or not os.path.isfile(fsi_file):
        return False, "NEED_LOGIN"

    subprocess.run(["docker", "rm", "-f", WRAPPER_NAME], capture_output=True,
                   startupinfo=_SI, creationflags=_CF)
    _log("Launching wrapper container...", log_callback)
    args = _build_wrapper_docker_run_args(detach=True, with_ports=True)
    code = subprocess.run(args, startupinfo=_SI, creationflags=_CF).returncode
    if code != 0:
        return False, "Failed to start wrapper"

    _log("Waiting for wrapper to initialize...", log_callback)
    for _ in range(8):
        time.sleep(2)
        if wrapper_running():
            break
    if wrapper_running():
        return True, f"Wrapper running (ports: {DECRYPT_PORT}/{M3U8_PORT}/{ACCOUNT_PORT})"
    else:
        try:
            logs = subprocess.run(["docker", "logs", WRAPPER_NAME], capture_output=True, text=True,
                                  startupinfo=_SI, creationflags=_CF).stdout.strip()
        except Exception:
            logs = ""
        if os.path.isfile(db_file):
            os.remove(db_file)
        return False, "NEED_LOGIN"


def stop_wrapper():
    subprocess.run(["docker", "rm", "-f", f"{WRAPPER_NAME}-login"], capture_output=True,
                   startupinfo=_SI, creationflags=_CF)
    subprocess.run(["docker", "rm", "-f", WRAPPER_NAME], capture_output=True,
                   startupinfo=_SI, creationflags=_CF)


def prepare_config_for_docker(config_content):
    for folder_key in ['alac-save-folder', 'atmos-save-folder', 'aac-save-folder', 'mv-save-folder']:
        config_content = re.sub(
            rf'^({folder_key}:\s*)"?([^"\n]+)"?',
            rf'\1"/downloads/\2"',
            config_content,
            flags=re.MULTILINE,
        )
    config_content = config_content.replace("127.0.0.1:10020", "host.docker.internal:10020")
    config_content = config_content.replace("127.0.0.1:20020", "host.docker.internal:20020")
    return config_content

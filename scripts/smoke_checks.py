"""Checks used by scripts/smoke-test.ps1.

Kept in a file rather than passed with `python -c` because PowerShell strips
embedded double quotes when invoking native commands, which silently corrupted
the snippets.

Usage: python smoke_checks.py <check>
Exit code 0 = pass, non-zero = fail (message on stdout).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_parse():
    import ast
    bad = []
    for name in ("common.py", "apple_music_downloader.py", "apple_music_downloader_gui.py"):
        try:
            with open(name, encoding="utf-8") as f:
                ast.parse(f.read())
        except SyntaxError as e:
            bad.append("%s:%s: %s" % (name, e.lineno, e.msg))
        except Exception as e:
            # Wrong encoding, unreadable file, ... - still a hard failure,
            # but report it instead of dumping a traceback.
            bad.append("%s: %s" % (name, e))
    if bad:
        print("; ".join(bad))
        return 1
    return 0


def check_imports():
    import common
    need = ["resolve_wsl_distro", "load_config_content", "prepare_run_config",
            "cleanup_run_config", "wrapper_running", "wrapper_status",
            "start_wrapper_service", "wrapper_login", "login_cached",
            "shutdown_wsl", "shutdown_wsl_detached", "port_open"]
    missing = [n for n in need if not hasattr(common, n)]
    if missing:
        print("missing: " + ", ".join(missing))
        return 1
    return 0


def check_config():
    import common
    content = common.load_config_content()
    if not content.strip():
        print("config.yaml is empty")
        return 1
    if "storefront" not in content:
        print("config.yaml has no storefront key")
        return 1
    return 0


def check_tempdir():
    import common
    w, cfg = common.prepare_run_config()
    try:
        if not os.path.isfile(cfg):
            print("config.yaml was not created")
            return 1
        if "am_run_" not in w:
            print("unexpected workdir: " + w)
            return 1
    finally:
        common.cleanup_run_config(w)
    if os.path.isdir(w):
        print("workdir still present after cleanup: " + w)
        return 1
    return 0


def check_distro():
    import common
    names = common._wsl_list_distros()
    if common.resolve_wsl_distro() not in names:
        print("distro not registered; present: " + (", ".join(names) or "(none)"))
        return 1
    print(common.resolve_wsl_distro())
    return 0


def check_downloader():
    import common
    r = common._wsl("test", "-x", common.DOWNLOADER_WSL, timeout=60)
    if r.returncode != 0:
        print("missing " + common.DOWNLOADER_WSL)
        return 1
    print(common.DOWNLOADER_WSL)
    return 0


def check_mp4box():
    import common
    r = common._wsl("sh", "-c", "command -v MP4Box && MP4Box -version 2>&1 | head -1", timeout=60)
    out = (r.stdout or "").strip()
    if r.returncode != 0 or "MP4Box" not in out:
        print("MP4Box not runnable - downloads would be saved without tags")
        return 1
    print(out.splitlines()[0])
    return 0


def check_credentials():
    import common
    if not common.login_cached():
        print("not signed in yet (start the app and log in)")
        return 1
    print("MUSIC_TOKEN cached")
    return 0


def check_status():
    import common
    ok, data, err = common.wrapper_status(timeout=8)
    if not ok:
        # Not running yet is normal: the app starts it on launch. Do the same
        # here so the check answers "will it work?" rather than "is it running
        # this very second?".
        print("starting the wrapper service...")
        started, msg = common.start_wrapper_service()
        if not started:
            print("could not start it: " + str(msg))
            return 1
        ok, data, err = common.wrapper_status(timeout=8)
    if not ok:
        print("not reachable: %s" % err)
        return 1
    print("storefront=" + str((data or {}).get("storefront_id")))
    return 0


CHECKS = {
    "parse": check_parse,
    "imports": check_imports,
    "config": check_config,
    "tempdir": check_tempdir,
    "distro": check_distro,
    "downloader": check_downloader,
    "mp4box": check_mp4box,
    "credentials": check_credentials,
    "status": check_status,
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in CHECKS:
        print("usage: smoke_checks.py <" + "|".join(sorted(CHECKS)) + ">")
        return 2
    return CHECKS[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())

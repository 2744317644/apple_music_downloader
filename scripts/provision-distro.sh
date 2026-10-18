#!/usr/bin/env bash
# Provision the wrapper + legacy downloader inside the WSL distro.
#
# Run from Windows:
#   wsl -d Debian13-wrapper -- bash /mnt/<drive>/<path>/scripts/provision-distro.sh
#
# It is idempotent: re-running upgrades/reinstalls in place and keeps the
# cached login credentials in /opt/wrapper/rootfs/data.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

WRAPPER_HOME=/opt/wrapper
AMDL_HOME=/opt/amdl-legacy
UNIT=apple-music-wrapper
SERVICE_FILE=/etc/systemd/system/${UNIT}.service
GOPROXY_CN="${GOPROXY:-https://goproxy.cn,direct}"

step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '[OK] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "run as root inside WSL"; exit 1; }
[ -d "$REPO/assets/Wrapper" ] || { echo "missing $REPO/assets/Wrapper"; exit 1; }
[ -d "$REPO/assets/apple-music-downloader" ] || { echo "missing $REPO/assets/apple-music-downloader"; exit 1; }

# ---------------------------------------------------------------------------
step "apt sources (http mirror first: a bare rootfs has no ca-certificates)"
if ! dpkg -s ca-certificates >/dev/null 2>&1; then
  cat > /etc/apt/sources.list.d/debian.sources <<'EOF'
Types: deb
URIs: http://mirrors.tuna.tsinghua.edu.cn/debian
Suites: trixie trixie-updates
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp

Types: deb
URIs: http://mirrors.tuna.tsinghua.edu.cn/debian-security
Suites: trixie-security
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp
EOF
fi
apt-get update -qq
ok "sources ready"

# ---------------------------------------------------------------------------
step "installing packages"
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  ca-certificates systemd systemd-sysv procps \
  build-essential golang-go \
  curl unzip zip sqlite3 >/dev/null
ok "go $(go version | awk '{print $3}')"

# ---------------------------------------------------------------------------
# MP4Box is what makes tag writing work. The downloader calls
# `MP4Box -itags ... file` to create the udta/ilst boxes first; without it the
# follow-up Go tag writer fails with "moov.udta box not present" and the file
# ends up with no title/artist/cover at all.
#
# gpac is not packaged in trixie, so the binary is built once from source and
# shipped in assets/ (static build, ~12 MB).
step "installing MP4Box"
if [ -f "$REPO/assets/MP4Box" ]; then
  install -m 0755 "$REPO/assets/MP4Box" /usr/local/bin/MP4Box
  if MP4Box -version >/dev/null 2>&1; then
    ok "MP4Box $(MP4Box -version 2>&1 | head -1 | sed 's/.*GPAC version //')"
  else
    warn "MP4Box installed but does not run (missing libs?)"
  fi
elif command -v MP4Box >/dev/null 2>&1; then
  ok "MP4Box already present"
else
  warn "assets/MP4Box missing - downloads will save audio without tags"
fi

# ---------------------------------------------------------------------------
step "installing the wrapper into $WRAPPER_HOME"
if [ ! -x "$WRAPPER_HOME/wrapper" ]; then
  mkdir -p "$WRAPPER_HOME"
  cp -a "$REPO/assets/Wrapper/wrapper" "$WRAPPER_HOME/"
  cp -a "$REPO/assets/Wrapper/rootfs" "$WRAPPER_HOME/"
fi
chmod +x "$WRAPPER_HOME/wrapper"
ok "$(du -sh "$WRAPPER_HOME" | cut -f1) in place (credentials are kept)"

cat > "$WRAPPER_HOME/start-wrapper.sh" <<'EOF'
#!/bin/sh
# Legacy wrapper: decrypt + m3u8 + account services.
# Must run from /opt/wrapper because `rootfs` is a relative path.
#
# Only -H is passed: the bundled binary's built-in defaults are already
# 10020 / 20020 / 30020. Do NOT add -K here - the wrapper shipped in
# assets/Wrapper is an older build that has no such option and exits with
# "invalid option -- 'K'".
cd /opt/wrapper || exit 1
exec ./wrapper -H 0.0.0.0
EOF
chmod +x "$WRAPPER_HOME/start-wrapper.sh"

# ---------------------------------------------------------------------------
step "building the legacy downloader into $AMDL_HOME/amdl"
mkdir -p "$AMDL_HOME"
cp -a "$REPO/assets/apple-music-downloader/main.go" \
      "$REPO/assets/apple-music-downloader/go.mod" \
      "$REPO/assets/apple-music-downloader/go.sum" "$AMDL_HOME/"
# Sub-packages (present in the upstream tree); copy when available.
for sub in utils cmd; do
  if [ -d "$REPO/assets/apple-music-downloader/$sub" ]; then
    cp -a "$REPO/assets/apple-music-downloader/$sub" "$AMDL_HOME/"
  fi
done

(
  cd "$AMDL_HOME"
  export GOPROXY="$GOPROXY_CN" GOTOOLCHAIN=local CGO_ENABLED=0 GOOS=linux GOARCH=amd64
  go build -mod=mod -o amdl . 
)
ok "built $AMDL_HOME/amdl ($(du -h "$AMDL_HOME/amdl" | cut -f1))"

# ---------------------------------------------------------------------------
step "installing the systemd unit"
cat > "$SERVICE_FILE" <<'EOF'
[Unit]
Description=Apple Music legacy wrapper (native WSL2 service)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/wrapper
ExecStart=/opt/wrapper/start-wrapper.sh
# on-failure, not always: without cached Apple credentials the wrapper exits
# with status 0 (it cannot do anything until a login happens). Restart=always
# would turn that into an endless restart loop that spams the log and never
# settles; on-failure leaves the unit inactive until the app starts it again.
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/apple-music-wrapper.log
StandardError=append:/var/log/apple-music-wrapper.log

[Install]
WantedBy=multi-user.target
EOF

# The legacy wrapper ignores SIGTERM, so a plain stop would take 90s.
mkdir -p "/etc/systemd/system/${UNIT}.service.d"
cat > "/etc/systemd/system/${UNIT}.service.d/stop.conf" <<'EOF'
[Service]
KillSignal=SIGKILL
TimeoutStopSec=5
RestartSec=3
EOF

systemctl daemon-reload
systemctl enable "$UNIT" >/dev/null 2>&1 || true
systemctl restart "$UNIT"
ok "service restarted"

# ---------------------------------------------------------------------------
step "waiting for the wrapper to come up (FairPlay init takes ~20-40s)"
for i in $(seq 1 30); do
  sleep 3
  if curl -sf --max-time 3 http://127.0.0.1:30020/ >/dev/null 2>&1; then
    break
  fi
done

if curl -sf --max-time 5 http://127.0.0.1:30020/ >/dev/null 2>&1; then
  ok "account service answering on 30020"
else
  warn "30020 not answering yet - check: journalctl -u $UNIT -n 40"
fi

echo
echo "state: $(systemctl is-active "$UNIT" 2>/dev/null || true)"
echo
echo "Next:"
echo "  - Windows: wsl --shutdown ; then start the app (it auto-starts the service)"
echo "  - first run needs an Apple Music login (GUI login page, or menu L in the CLI)"

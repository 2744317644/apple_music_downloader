# Apple Music ALAC Downloader

English | [中文](README.md)

> Apple Music lossless ALAC / Dolby Atmos / AAC downloader

## Acknowledgments

Built on these excellent open-source projects:

- **[apple-music-downloader](https://github.com/zhaarey/apple-music-downloader)** — the Apple Music ALAC / Atmos / AAC download engine
- **[wrapper](https://github.com/WorldObservationLog/wrapper)** — Apple Music Android DRM decryption service (this project uses its `lite` branch)

Thanks to their authors and contributors.

## Architecture

This project does **not** require Docker. It consists of two natively running parts:

```
Windows                                          WSL2 (Debian13-wrapper)
┌──────────────────────────┐                    ┌──────────────────────────────────┐
│ GUI / CLI  (Python)      │                    │ systemd                          │
│   └─ calls wsl.exe       │  127.0.0.1         │  └─ apple-music-wrapper.service  │
│                          │ ────────────────>  │      ├─ wrapper  (legacy)        │
│                          │ 10020/20020/       │      │    four TCP services      │
│                          │ 30020/40020        │      └─ (launched per run)       │
│                          │                    │          /opt/amdl-legacy/amdl   │
└──────────────────────────┘                    └──────────────────────────────────┘
                            └─ output written to /mnt/c/Users/<user>/Downloads/
```

- **wrapper** (legacy) is a systemd service exposing four TCP services (decrypt / m3u8 / account / key)
- **amdl** is the legacy downloader, built as a Linux binary and invoked from Python through `wsl.exe`
- The downloader **must** run on the Linux side: the Windows build stalls on paths containing
  non-ASCII characters (such as the user profile)

> Why must the decryptor live in WSL2? wrapper needs Linux kernel features
> (`unshare` / `mount` / `chroot`) that Windows does not provide; WSL2 supplies a real Linux kernel.
> See [WSL2-WRAPPER.md](WSL2-WRAPPER.md).

## Features

- ALAC lossless downloads (up to 192 kHz)
- Dolby Atmos downloads
- AAC-LC / AAC / AAC-Binaural / AAC-Downmix
- Albums, single tracks, playlists, all albums by an artist
- Lyrics downloads (LRC / TTML)
- Cover art embedding and animated artwork
- Post-download conversion (FLAC / MP3 / Opus / WAV)
- Custom file and folder naming
- **GUI** with sidebar navigation
- **Chinese / English** UI switching
- **One-click login** with cached Apple ID credentials
- **Environment self-check** of the wrapper service
- **Built-in config editor**
- **Live download progress** with persistent logs
- **Built-in format conversion** (bundled ffmpeg, m4a → FLAC)
- **Built-in audio renamer** (batch rename from tags)
- **Single-file packaging** (PyInstaller)

## Requirements

- **Windows 10/11 with WSL2**
- **Python 3.7+** (only for GUI/CLI)

One command does everything:

```powershell
.\scripts\deploy.bat
```

Or call PowerShell directly (accepts parameters):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1
```

It creates the WSL2 base distro, enables systemd, writes the WSL network settings,
deploys the wrapper, builds the downloader, registers and starts the service, then verifies.

Debian is obtained **only from official Microsoft / Debian channels**, trying in order:

1. `wsl --install -d Debian --web-download` (WSL fetches the official image itself)
2. `wsl --install -d Debian` (Microsoft Store)
3. The `.AppxBundle` listed in the official distribution manifest (Microsoft-hosted),
   unpacked and imported with `wsl --import`

If Microsoft endpoints are slow or blocked on your network, pass a proxy:
`deploy.ps1 -Proxy http://127.0.0.1:7890`

Architecture, directories, ports and pitfalls: **[WSL2-WRAPPER.md](WSL2-WRAPPER.md)**.

### CLI extra dependencies

```bash
pip install -r requirements.txt
```

## Quick Start

### 1. Check the service

```bash
python apple_music_downloader.py --status
```

Expected output:

```
endpoint : http://127.0.0.1:12340
service  : active
status   : RUNNING
regions  : cn
```

### 2. Run

**Terminal version:**

```bash
python apple_music_downloader.py
```

**GUI version:**

```bash
python apple_music_downloader_gui.py
```

On first run it will:

- check whether the wrapper is online and start the systemd service if not
- guide you through Apple Music login (including 2FA) when no credentials are cached
- cache credentials for later runs

### 3. Where files land

Save paths come from the `paths` section of `config.yaml`; relative paths are
resolved against the **user's Downloads folder**:

| Type | Default location |
|------|------------------|
| ALAC | `Downloads\AM-Lossless\` |
| Dolby Atmos | `Downloads\AM-Atmos\` |
| AAC | `Downloads\AM-AAC\` |
| MV | `Downloads\AM-MV\` |

> Upgrading from an older version keeps your existing `AM-DL downloads` folder names.

### 4. Build an EXE

```bash
build.bat
```

Produces `AppleMusicDownloader.exe`.

## Configuration

The config file lives at `%LOCALAPPDATA%\AppleMusicDownloader\config.yaml` and uses a
**flat layout** (the legacy downloader's format). Common options:

| Key | Description |
|-----|-------------|
| `storefront` | account region code (`cn` / `us` / `jp` …) |
| `media-user-token` | needed for AAC / stations / lyrics (see below) |
| `authorization-token` | leave empty; the downloader fetches it automatically |
| `alac-max` | max ALAC sample rate: 192000 / 96000 / 48000 / 44100 |
| `atmos-max` | max Atmos bitrate: 2768 / 2448 |
| `aac-type` | `aac-lc` / `aac` / `aac-binaural` / `aac-downmix` |
| `alac-save-folder` etc. | save folders (relative paths resolve under Downloads) |
| `song-file-format` | song filename template |
| `lrc-type` / `lrc-format` / `embed-lrc` | lyric type, format, embedding |
| `cover-size` / `cover-format` / `embed-cover` | cover size, format, embedding |
| `convert-after-download` / `convert-format` | post-download conversion |
| `decrypt-m3u8-port` / `get-m3u8-port` | wrapper ports, default `127.0.0.1:10020` / `20020` |

> The program detects the config format on startup (including rolling back the v0.1.x nested
> layout) and backs up the previous file as `config.yaml.bak`.

### Getting media-user-token

`media-user-token` is only needed for **AAC downloads, stations and lyrics**;
**ALAC downloads do not need it**.

The flow is built in: **Config tab → "Get Token"**. It will:

1. scan the local browsers (Firefox stores cookies in plain SQLite, so its value can be read)
2. for Chrome / Edge / Brave the cookie is encrypted by the browser, so a dialog with
   instructions is shown instead
3. **validate the pasted token against Apple immediately** and only then write it to the config

Manual steps:

1. Sign in at https://music.apple.com in a browser
2. `F12` → `Application` → `Storage` → `Cookies` → `https://music.apple.com`
3. Find `media-user-token` and copy its whole `Value`
4. Paste it into the dialog and click "Verify & Save"

CLI equivalent: menu item `T`.

> The token rotates with the session. If AAC downloads report `Invalid media-user-token`,
> grab a fresh one.

### Filename template variables

- Album folder: `{AlbumId}` `{AlbumName}` `{ArtistName}` `{ReleaseDate}` `{ReleaseYear}` `{UPC}` `{Copyright}` `{Quality}` `{Codec}` `{Tag}` `{RecordLabel}`
- Song file: `{SongId}` `{SongNumer}` `{SongName}` `{DiscNumber}` `{TrackNumber}` `{Quality}` `{Codec}` `{Tag}`

## GUI

Five tabs: **Download** / **Status** / **Config** / **Convert** / **Rename**.

### Download

| Component | Purpose |
|-----------|---------|
| Mode selector | Album / Song / Playlist / Atmos / AAC / Select / Debug / Search / Artist |
| URL field | Paste an Apple Music link; right-click to paste |
| Download button | Starts the download; turns red to cancel |

### Status

Shows the wrapper endpoint, WSL service state, responsiveness, listening port and
available regions, plus login cache state and key paths.

### Config

Built-in YAML editor to edit and save the config file.

### Convert

Recursively scans a folder for `.m4a` and converts to FLAC using the bundled ffmpeg.

### Rename

Two templates:

- **TrackNumber. SongName** — leading number from the filename + title tag
- **Artist - SongName** — artist and title tags

## Terminal menu

| Key | Action |
|-----|--------|
| `1` | Download album |
| `2` | Download single song (URL with `?i=` track id) |
| `3` | Interactive track selection |
| `4` | Download playlist |
| `5` | Dolby Atmos mode |
| `6` | AAC mode |
| `7` | Debug / view audio quality |
| `8` | Search (song/album/artist) |
| `9` | Download all artist albums |
| `0` | Custom command |
| `S` | Wrapper status |
| `R` | Restart wrapper service |
| `L` | Apple Music login |
| `H` | Help |
| `Q` | Quit |

## Project layout

```
.
├── apple_music_downloader.py      # terminal entry point
├── apple_music_downloader_gui.py  # GUI entry point
├── common.py                      # shared logic (config / wrapper / login)
├── build.bat                      # packaging script
├── config.yaml.example            # default config template
├── requirements.txt               # Python dependencies
├── WSL2-WRAPPER.md                # WSL2 base install and operations
├── scripts/
│   ├── deploy.ps1                 # one-shot deploy (distro + components)
│   ├── deploy.bat                 # policy-bypass wrapper for deploy.ps1
│   ├── uninstall.ps1              # one-shot uninstall (removes only ours)
│   ├── uninstall.bat              # policy-bypass wrapper for uninstall.ps1
│   └── provision-distro.sh        # provision wrapper + downloader (inside the distro)
└── assets/
    ├── app_icon.ico
    ├── ffmpeg.exe                 # conversion / animated artwork
    ├── ffprobe.exe                # tag reading
    └── flac.exe                   # FLAC encoder
```

> `ffmpeg.exe` / `ffprobe.exe` are tracked with **Git LFS** (`git lfs install` before cloning).
> Alternatively download them from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) and drop them
> into `assets/`. Lookup order: `assets/` → PATH → WinGet install location.

### Runtime data

| Data | Path |
|------|------|
| Config | `%LOCALAPPDATA%\AppleMusicDownloader\config.yaml` |
| Logs | `%LOCALAPPDATA%\AppleMusicDownloader\log\` |
| Credentials | inside WSL: `/opt/wrapper/rootfs/data/.../files/` |
| Downloads | the user's Downloads folder |

## Troubleshooting

**wrapper not responding?**

```bash
python apple_music_downloader.py --status
wsl -d Debian13-wrapper -- systemctl status apple-music-wrapper
wsl -d Debian13-wrapper -- systemctl restart apple-music-wrapper
```

**Downloader not found?**

It lives at `/opt/amdl-legacy/amdl` inside WSL and is built by
`scripts/provision-distro.sh`. Re-run that script to rebuild it.

**GUI flashes or hangs?**

- Verify WSL2: `wsl -d Debian13-wrapper -- echo ok`
- Check logs in `%LOCALAPPDATA%\AppleMusicDownloader\log\`

**"Failed to get token"?**

- Make sure `music.apple.com` is reachable
- Sign in on the web, copy `authorization-token` manually into the config

**No files after downloading?**

- Check the `paths` section and write permissions
- Make sure `storefront` matches your account region
- The downloader runs inside `Downloads`, so relative paths resolve there

**Lyrics failing?**

Set `general.storefront` to your account's region code (e.g. `cn`).

**Config errors after upgrading?**

The program migrates old configs automatically and backs them up as `config.yaml.bak`.
If problems remain, align your config with `config.yaml.example`.

**EXE build failing?**

- Close any running `AppleMusicDownloader.exe`
- Install the dependencies from `requirements.txt`

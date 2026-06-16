# Apple Music ALAC Downloader

English | [中文](README.md)

> Apple Music lossless ALAC / Dolby Atmos / AAC downloader

## Acknowledgments

This project builds upon the following excellent open-source projects:

- **[apple-music-downloader](https://github.com/zhaarey/apple-music-downloader)** — Core download engine implemented in Go, supporting ALAC / Atmos / AAC
- **[wrapper](https://github.com/WorldObservationLog/wrapper)** — Apple Music Android DRM decryption service, providing FairPlay decryption and M3U8 retrieval

Thanks to the authors and contributors of the above projects.

## Features

- ALAC lossless downloads (up to 192kHz)
- Dolby Atmos spatial audio downloads
- AAC-LC / AAC / AAC-Binaural / AAC-Downmix downloads
- Full album, single song, and playlist downloads
- Lyrics download (LRC / TTML)
- Cover art embedding and animated artwork download
- Post-download format conversion (FLAC / MP3 / Opus / WAV)
- Custom file and folder naming
- **Graphical interface** with sidebar tab navigation
- **Bilingual UI** — switch between Chinese and English with one click
- **One-click login** — Apple ID credentials cached automatically
- **Environment self-check** — automatic detection of Docker, images, and service status
- **Built-in config editor** — edit and save configuration directly in the GUI
- **Real-time download progress** with persistent logging
- **Standalone EXE** — single-file packaging via PyInstaller

## Requirements

- **Python 3.7+**
- **Docker** (must be installed and running)

### Additional CLI dependencies

```bash
pip install -r requirements.txt
```

## Quick Start

### 1. First Launch

On first launch, the default configuration is automatically copied to `%LOCALAPPDATA%\AppleMusicDownloader\config.yaml`. No manual config creation is needed.

Edit the key settings in that file as needed:

- `media-user-token`: Your Apple Music media user token
- `storefront`: Your account region code (e.g., `us`, `jp`, `cn`)

### 2. Run

**CLI version**:
```bash
python apple_music_downloader.py
```

**GUI version**:
```bash
python apple_music_downloader_gui.py
```

On first run, the application will automatically:
- Build the Wrapper and Downloader Docker images
- Guide you through Apple Music login
- Cache login credentials for subsequent launches

### 3. Output Location

| Mode | Save Location |
|------|---------------|
| ALAC | `Downloads\AM-DL downloads\` |
| Dolby Atmos | `Downloads\AM-DL-Atmos downloads\` |
| AAC | `Downloads\AM-DL-AAC downloads\` |
| MV | `Downloads\AM-DL-MV downloads\` |

> Save paths can be customized via `alac-save-folder` and other fields in the config file. The GUI status bar also shows the output path — click the folder icon to open it.

### 4. Build EXE

```bash
build.bat
```

Generates `AppleMusicDownloader.exe`.

## Docker Images

| Component | Source | Notes |
|-----------|--------|-------|
| wrapper | `assets/Wrapper/` | Built locally, Dockerfile + wrapper binary bundled in EXE |
| downloader | `assets/apple-music-downloader/` | Built locally, Go source + Dockerfile bundled in EXE |

## GUI Usage

The interface uses sidebar tab navigation with three tabs:

### Download

| Component | Function |
|-----------|----------|
| Mode Selector | Click to open dropdown: Album / Song / Playlist / Dolby Atmos / AAC |
| URL Input | Paste Apple Music link; right-click to paste |
| Download Button | Click to start download; turns red while downloading; click again to cancel |
| Clear Button (×) | Clear the URL |
| Output Log | Real-time download progress; progress lines update in place |
| Clear Log Button | Clear the console |
| Status Bar | Left: Wrapper status; Right: output path (clickable to open) |

### Status

| Item | Description |
|------|-------------|
| Docker | Installation status, daemon running status |
| Images | Whether Wrapper and Downloader images are built |
| Wrapper Container | Running status, port mapping |
| Login | Credential cache status |
| Paths | Config file, log directory, and wrapper data paths (clickable to open) |

### Config

Built-in YAML editor — edit configuration directly and save. The Reload button re-reads the currently active config.

### Language

Language switch buttons are available at the bottom of the sidebar and in the top-right corner of the login page. Toggle between Chinese and English with one click.

## CLI Menu

| Key | Function |
|-----|----------|
| `1` | Download Album |
| `2` | Download Single Song |
| `3` | Interactive Track Select |
| `4` | Download Playlist |
| `5` | Dolby Atmos Mode |
| `6` | AAC Mode |
| `7` | Debug / View Audio Quality |
| `8` | Search (song/album/artist) |
| `9` | Download All Artist Albums |
| `0` | Custom Command |
| `H` | Help / Info |
| `Q` | Quit |

## Configuration

The config file is located at `%LOCALAPPDATA%\AppleMusicDownloader\config.yaml`. Key settings:

| Setting | Description |
|---------|-------------|
| `alac-max` | ALAC max sample rate: 192000 / 96000 / 48000 / 44100 |
| `atmos-max` | Atmos max bitrate: 2768 / 2448 |
| `aac-type` | AAC type: aac-lc / aac / aac-binaural / aac-downmix |
| `cover-size` | Cover art size, default 5000x5000 |
| `cover-format` | Cover format: jpg / png / original |
| `lrc-type` | Lyrics type: lyrics / syllable-lyrics |
| `lrc-format` | Lyrics format: lrc / ttml |
| `embed-lrc` | Embed lyrics in file |
| `embed-cover` | Embed cover art in file |
| `album-folder-format` | Album folder naming template |
| `song-file-format` | Song file naming template |
| `convert-after-download` | Enable post-download format conversion |
| `convert-format` | Target format: flac / mp3 / opus / wav / copy |

### Naming Template Variables

- Album folder: `{AlbumId}` `{AlbumName}` `{ArtistName}` `{ReleaseDate}` `{ReleaseYear}` `{UPC}` `{Copyright}` `{Quality}` `{Codec}` `{Tag}` `{RecordLabel}`
- Song file: `{SongId}` `{SongNumer}` `{SongName}` `{DiscNumber}` `{TrackNumber}` `{Quality}` `{Codec}` `{Tag}`

## Project Structure

```
.
├── apple_music_downloader.py      # CLI entry point
├── apple_music_downloader_gui.py  # GUI entry point
├── build.bat                      # Build script
├── config.yaml.example            # Default config template
├── requirements.txt               # Python dependencies
├── assets/
│   ├── app_icon.ico                       # Application icon
│   ├── Wrapper/                           # Wrapper source (Dockerfile + binary)
│   └── apple-music-downloader/            # Downloader source (Go + Dockerfile)
└── AppleMusicDownloader.exe       # Packaged output (optional)
```

### Runtime Data

Login credentials and logs are stored in the user directory:

| Data | Path |
|------|------|
| Config | `%LOCALAPPDATA%\AppleMusicDownloader\config.yaml` |
| Credentials | `%LOCALAPPDATA%\AppleMusicDownloader\wrapper-data\` |
| Logs | `%LOCALAPPDATA%\AppleMusicDownloader\log\` |
| Downloads | User Downloads folder |

## FAQ

**Q: Docker not installed?**
Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and ensure the `docker` command is available in the terminal.

**Q: GUI crashes or freezes on startup?**
- Ensure Docker Desktop is running
- First launch requires building images, which may take 1–3 minutes
- Check logs at: `%LOCALAPPDATA%\AppleMusicDownloader\log\`

**Q: "Failed to get token"?**
- Check if you can access `music.apple.com`
- Log into Apple Music in a browser, then manually copy the `authorization-token` into the config file

**Q: Login failed?**
- Verify your Apple ID and password (an app-specific password may be required)
- Check Wrapper container logs for details
- Delete `%LOCALAPPDATA%\AppleMusicDownloader\wrapper-data\` and retry

**Q: No files after download?**
- Verify the save path in the config is correct and writable
- Check that the download log shows "Completed" rather than "Warnings" or "Errors"

**Q: Lyrics not working?**
Ensure `storefront` matches your Apple Music account region (e.g., `us` for United States).

**Q: EXE build failed?**
- Close any running `AppleMusicDownloader.exe`
- Ensure dependencies are installed: `pip install -r requirements.txt`

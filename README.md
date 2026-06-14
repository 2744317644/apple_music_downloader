# Apple Music ALAC Downloader

> Apple Music 无损 ALAC / 杜比全景声 Dolby Atmos / AAC 下载工具

## 功能特性

- 支持 ALAC 无损下载（最高 192kHz）
- 支持 Dolby Atmos 杜比全景声下载
- 支持 AAC-LC / AAC / AAC-Binaural / AAC-Downmix 下载
- 支持整张专辑、单曲、播放列表下载
- 支持交互式选曲下载（终端版）
- 支持搜索歌曲/专辑/艺人（终端版）
- 支持下载艺人全部专辑（终端版）
- 支持歌词下载（LRC / TTML）
- 支持封面嵌入、动画封面下载
- 支持下载后格式转换（FLAC / MP3 / Opus / WAV）
- 自定义文件名和文件夹命名
- **GUI 图形界面**（Apple 风格设计）

## 环境要求

- **Python 3.7+**
- **Docker**（必须安装且可正常运行）

### GUI 版本额外依赖

```bash
pip install -r requirements.txt
```

## 快速开始

### 1. 配置

编辑 `config.yaml`，填写以下必要信息：

- `media-user-token`: 你的 Apple Music 媒体用户令牌
- `storefront`: 你的账号所属区域代码（如 `cn`、`us`、`jp`）
- `alac-max`: ALAC 最大采样率，默认 192000

### 2. 运行

**终端版本**：
```bash
python apple_music_downloader.py
```

**GUI 版本**：
```bash
python apple_music_downloader_gui.py
```

首次运行会自动：
- 导入或构建 Wrapper 镜像（优先从 `am-wrapper.tar` 导入，否则用 `assets/wrapper-release/` 构建）
- 拉取 Downloader 镜像（优先从 `am-downloader.tar` 导入，否则从 GitHub 拉取）
- 引导完成 Apple Music 登录

### 3. 打包为 EXE

```bash
build.bat
```

生成 `AppleMusicDownloader.exe`。

## 镜像说明

| 组件 | 来源 | 说明 |
|------|------|------|
| am-wrapper | `assets/wrapper-release/` | 本地构建，无需网络。Dockerfile + wrapper 二进制已打包进 exe |
| am-downloader | `ghcr.io/zhaarey/apple-music-downloader:latest` | 自动 `docker pull` 拉取 |

> 如已导出 `.tar` 镜像文件，将 `am-wrapper.tar` / `am-downloader.tar` 放在 exe 同级目录，程序会优先从 tar 导入，跳过构建/拉取。

## GUI 使用说明

GUI 支持浅色/深色主题切换。

| 组件 | 功能 |
|------|------|
| 模式选择 | 专辑 / 单曲 / 播放列表 / 杜比全景声 / AAC |
| URL 输入框 | 粘贴 Apple Music 链接，右键粘贴，下载后自动清除 |
| Download 按钮 | 开始下载 |
| 清除按钮 | 手动清空 URL |
| 输出日志 | 实时显示下载进度，进度行原地刷新 |
| Clear 按钮 | 清空日志 |

## 终端菜单说明

| 选项 | 功能 |
|------|------|
| `1` | 下载专辑 |
| `2` | 下载单曲 |
| `3` | 交互式选曲 |
| `4` | 下载播放列表 |
| `5` | Dolby Atmos 模式 |
| `6` | AAC 模式 |
| `7` | 调试 / 查看音质信息 |
| `8` | 搜索（歌曲/专辑/艺人） |
| `9` | 下载艺人全部专辑 |
| `0` | 自定义命令 |
| `H` | 帮助信息 |
| `Q` | 退出 |

## 配置说明

完整配置项请参考 `config.yaml`，常用配置：

| 配置项 | 说明 |
|--------|------|
| `alac-max` | ALAC 最高采样率：192000 / 96000 / 48000 / 44100 |
| `atmos-max` | Atmos 最高码率：2768 / 2448 |
| `aac-type` | AAC 类型：aac-lc / aac / aac-binaural / aac-downmix |
| `cover-size` | 封面尺寸，默认 5000x5000 |
| `cover-format` | 封面格式：jpg / png / original |
| `lrc-type` | 歌词类型：lyrics / syllable-lyrics |
| `lrc-format` | 歌词格式：lrc / ttml |
| `embed-lrc` | 是否嵌入歌词 |
| `embed-cover` | 是否嵌入封面 |
| `album-folder-format` | 专辑文件夹命名格式 |
| `song-file-format` | 单曲文件命名格式 |
| `convert-after-download` | 下载后是否转换格式 |
| `convert-format` | 转换目标格式：flac / mp3 / opus / wav / copy |

### 文件名模板变量

- 专辑文件夹：`{AlbumId}` `{AlbumName}` `{ArtistName}` `{ReleaseDate}` `{ReleaseYear}` `{UPC}` `{Copyright}` `{Quality}` `{Codec}` `{Tag}` `{RecordLabel}`
- 单曲文件：`{SongId}` `{SongNumer}` `{SongName}` `{DiscNumber}` `{TrackNumber}` `{Quality}` `{Codec}` `{Tag}`

## 项目结构

```
.
├── apple_music_downloader.py      # 终端版入口
├── apple_music_downloader_gui.py  # GUI 版入口
├── build.bat                      # 打包脚本
├── config.yaml                    # 配置文件
├── requirements.txt               # Python 依赖
├── assets/
│   ├── app_icon.ico               # 应用图标
│   └── wrapper-release/           # Wrapper 源码（Dockerfile + 二进制）
└── AppleMusicDownloader.exe       # 打包产物（可选）
```

> 可选：`am-wrapper.tar` / `am-downloader.tar` 可放在项目根目录作为离线镜像，程序优先从 tar 导入。

### 运行时数据

登录凭据和运行日志存放在用户目录下，exe 同级保持干净：

| 数据 | 路径 |
|------|------|
| 登录凭据 | `%LOCALAPPDATA%\AppleMusicDownloader\wrapper-data\` |
| 运行日志 | `%LOCALAPPDATA%\AppleMusicDownloader\log\` |
| 下载文件 | 用户 Downloads 文件夹 |
| 配置文件 | exe 同级 `config.yaml` |

## 常见问题

**Q: 提示 Docker 未安装？**
安装 Docker Desktop 并确保 `docker` 命令可在终端中使用。

**Q: 下载失败？**
- 检查 `config.yaml` 中 `media-user-token` 和 `storefront` 是否正确
- 检查网络连接

**Q: 歌词获取失败？**
确认 `storefront` 与你 Apple Music 账号的区域一致。

**Q: GUI 启动闪退？**
确保 Docker 已安装且正常运行。

## 致谢

本项目基于以下优秀的开源项目构建：

- **[apple-music-downloader](https://github.com/zhaarey/apple-music-downloader)** — Apple Music ALAC / Atmos / AAC 下载核心，提供 Go 语言实现的完整下载引擎
- **Apple Music Wrapper** — Apple Music Android DRM 解密服务，提供 FairPlay 解密与 M3U8 获取能力

感谢以上项目的作者和贡献者们。

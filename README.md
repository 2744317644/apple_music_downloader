# Apple Music ALAC Downloader

[English](README_EN.md) | 中文

> Apple Music 无损 ALAC / 杜比全景声 Dolby Atmos / AAC 下载工具

## 致谢

本项目基于以下优秀的开源项目构建：

- **[apple-music-downloader](https://github.com/zhaarey/apple-music-downloader)** — Apple Music ALAC / Atmos / AAC 下载核心，提供 Go 语言实现的完整下载引擎
- **[wrapper](https://github.com/WorldObservationLog/wrapper)** — Apple Music Android DRM 解密服务，提供 FairPlay 解密与 M3U8 获取能力

感谢以上项目的作者和贡献者们。

## 功能特性

- 支持 ALAC 无损下载（最高 192kHz）
- 支持 Dolby Atmos 杜比全景声下载
- 支持 AAC-LC / AAC / AAC-Binaural / AAC-Downmix 下载
- 支持整张专辑、单曲、播放列表下载
- 支持歌词下载（LRC / TTML）
- 支持封面嵌入、动画封面下载
- 支持下载后格式转换（FLAC / MP3 / Opus / WAV）
- 自定义文件名和文件夹命名
- **GUI 图形界面**（侧边栏页签导航）
- **中英文切换**（一键切换界面语言）
- **一键登录**（Apple ID 凭据自动缓存）
- **环境自检**（启动时自动检测 Docker、镜像、服务状态）
- **内置配置编辑**（GUI 内直接编辑保存配置文件）
- **下载进度实时显示**（日志持久化保存）
- **单文件打包**（PyInstaller 打包为独立 EXE）

## 环境要求

- **Python 3.7+**
- **Docker**（必须安装且可正常运行）

### GUI 版本额外依赖

```bash
pip install -r requirements.txt
```

## 快速开始

### 1. 首次启动

首次启动会自动将默认配置复制到 `%LOCALAPPDATA%\AppleMusicDownloader\config.yaml`，无需手动创建配置文件。

根据需要编辑该文件中的关键配置项：

- `media-user-token`: 你的 Apple Music 媒体用户令牌
- `storefront`: 你的账号所属区域代码（如 `cn`、`us`、`jp`）

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
- 构建 Wrapper 和 Downloader Docker 镜像
- 引导完成 Apple Music 登录
- 登录凭据自动缓存，后续无需重复

### 3. 下载文件在哪

| 下载模式 | 保存位置 |
|----------|----------|
| ALAC | `Downloads\AM-DL downloads\` |
| 杜比全景声 | `Downloads\AM-DL-Atmos downloads\` |
| AAC | `Downloads\AM-DL-AAC downloads\` |
| MV | `Downloads\AM-DL-MV downloads\` |

> 保存路径可通过配置文件中的 `alac-save-folder` 等字段自定义。GUI 底部状态栏也会显示输出路径，点击文件夹图标可直接打开。

### 4. 打包为 EXE

```bash
build.bat
```

生成 `AppleMusicDownloader.exe`。

## 镜像说明

| 组件 | 来源 | 说明 |
|------|------|------|
| wrapper | `assets/Wrapper/` | 本地构建，Dockerfile + wrapper 二进制已打包进 exe |
| downloader | `assets/apple-music-downloader/` | 本地构建，Go 源码 + Dockerfile 已打包进 exe |

## GUI 使用说明

界面采用侧边栏页签导航，包含三个页签：

### 下载

| 组件 | 功能 |
|------|------|
| 模式选择 | 点击左侧按钮弹出下拉菜单，选择：专辑 / 单曲 / 播放列表 / 杜比全景声 / AAC |
| URL 输入框 | 粘贴 Apple Music 链接，支持右键粘贴 |
| Download 按钮 | 点击开始下载，下载中变红，再次点击取消下载 |
| 清除按钮（×） | 清空 URL |
| 输出日志 | 实时显示下载进度，进度行原地刷新 |
| Clear 按钮 | 清空日志 |
| 状态栏 | 左侧显示 Wrapper 运行状态，右侧显示输出路径并支持点击打开 |

### 状态

| 显示项 | 说明 |
|--------|------|
| Docker | 安装状态、守护进程运行状态 |
| 镜像 | Wrapper 镜像、下载器镜像是否已构建 |
| Wrapper 容器 | 运行状态、端口映射 |
| 登录 | 凭据缓存状态 |
| 路径 | 配置文件、日志目录、Wrapper 数据目录路径，可点击打开 |

### 配置

内置 YAML 编辑器，可直接修改配置文件并保存。重新加载按钮可重读当前生效配置。

### 语言切换

侧边栏底部和登录页右上角均有语言切换按钮，支持中文 / English 一键切换。

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

配置文件位于 `%LOCALAPPDATA%\AppleMusicDownloader\config.yaml`，常用配置：

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
├── config.yaml.example            # 默认配置示例
├── requirements.txt               # Python 依赖
├── assets/
│   ├── app_icon.ico                       # 应用图标
│   ├── Wrapper/                           # Wrapper 源码（Dockerfile + 二进制）
│   └── apple-music-downloader/            # Downloader 源码（Go + Dockerfile）
└── AppleMusicDownloader.exe       # 打包产物（可选）
```

### 运行时数据

登录凭据和运行日志存放在用户目录下：

| 数据 | 路径 |
|------|------|
| 配置文件 | `%LOCALAPPDATA%\AppleMusicDownloader\config.yaml` |
| 登录凭据 | `%LOCALAPPDATA%\AppleMusicDownloader\wrapper-data\` |
| 运行日志 | `%LOCALAPPDATA%\AppleMusicDownloader\log\` |
| 下载文件 | 用户 Downloads 文件夹 |

## 常见问题

**Q: 提示 Docker 未安装？**
安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/) 并确保 `docker` 命令可在终端中使用。

**Q: GUI 启动闪退或无响应？**
- 确保 Docker Desktop 已启动且状态正常
- 首次启动需要构建镜像，可能耗时 1-3 分钟，请耐心等待
- 查看日志：`%LOCALAPPDATA%\AppleMusicDownloader\log\`

**Q: 提示 "Failed to get token"？**
- 检查网络是否能访问 `music.apple.com`
- 在浏览器登录 Apple Music 后，手动复制 `authorization-token` 填入配置文件

**Q: 登录失败？**
- 确认 Apple ID 和密码正确（可能需要使用 App 专用密码）
- 查看 Wrapper 容器日志排查具体原因
- 删除 `%LOCALAPPDATA%\AppleMusicDownloader\wrapper-data\` 重试

**Q: 下载后没有文件？**
- 检查配置中的保存路径是否正确，确保路径有写入权限
- 确认下载日志中显示 "Completed" 而非 "Warnings" 或 "Errors"

**Q: 歌词获取失败？**
确认 `storefront` 与你 Apple Music 账号的区域一致（如中国区填 `cn`）。

**Q: 打包 EXE 失败？**
- 确保已关闭正在运行的 `AppleMusicDownloader.exe`
- 确保 `requirements.txt` 中的依赖已安装：`pip install -r requirements.txt`

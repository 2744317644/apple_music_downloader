# Apple Music ALAC Downloader

> Apple Music 无损 ALAC / 杜比全景声 Dolby Atmos / AAC 下载工具

## 致谢

本项目基于以下优秀的开源项目构建：

- **[apple-music-downloader](https://github.com/zhaarey/apple-music-downloader)** — Apple Music ALAC / Atmos / AAC 下载核心，提供 Go 语言实现的完整下载引擎
- **[wrapper](https://github.com/WorldObservationLog/wrapper)** — Apple Music Android DRM 解密服务，提供 FairPlay 解密与 M3U8 获取能力

感谢以上项目的作者和贡献者们。

## 本版本新增

相比上游项目，本封装版本额外提供：

- **图形界面** — 无需命令行操作
- **免配置运行** — 无需 `config.yaml` 即可直接下载，内置完整默认配置
- **一键登录** — Apple ID 登录一次即可缓存凭据，后续启动无需重复输入
- **自动环境配置** — 自动检测 Docker、构建镜像、启动服务，开箱即用
- **单文件打包** — 支持 PyInstaller 打包为独立 EXE，无需安装 Python

## 功能特性

- 支持 ALAC 无损下载（最高 192kHz）
- 支持 Dolby Atmos 杜比全景声下载
- 支持 AAC-LC / AAC / AAC-Binaural / AAC-Downmix 下载
- 支持整张专辑、单曲、播放列表下载
- 支持歌词下载（LRC / TTML）
- 支持封面嵌入、动画封面下载
- 支持下载后格式转换（FLAC / MP3 / Opus / WAV）
- 自定义文件名和文件夹命名
- **GUI 图形界面**

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

> 保存路径可通过 `config.yaml` 中的 `alac-save-folder` 等字段自定义。GUI 底部状态栏也会显示输出路径，点击文件夹图标可直接打开。

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
│   ├── app_icon.ico                       # 应用图标
│   ├── Wrapper/                           # Wrapper 源码（Dockerfile + 二进制）
│   └── apple-music-downloader/            # Downloader 源码（Go + Dockerfile）
└── AppleMusicDownloader.exe       # 打包产物（可选）
```

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
安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/) 并确保 `docker` 命令可在终端中使用。

**Q: GUI 启动闪退或无响应？**
- 确保 Docker Desktop 已启动且状态正常
- 首次启动需要构建镜像，可能耗时 1-3 分钟，请耐心等待
- 查看日志：`%LOCALAPPDATA%\AppleMusicDownloader\log\`

**Q: 提示 "Failed to get token"？**
- 检查网络是否能访问 `music.apple.com`
- 在浏览器登录 Apple Music 后，手动复制 `authorization-token` 填入 `config.yaml`

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

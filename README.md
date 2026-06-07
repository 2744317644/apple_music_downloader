# Apple Music ALAC Downloader

> 本项目由 https://github.com/zhaarey/apple-music-downloader 开发而来

> Apple Music 无损 ALAC / 杜比全景声 Dolby Atmos / AAC 下载工具

## 功能特性

- 支持 ALAC 无损下载（最高 192kHz）
- 支持 Dolby Atmos 杜比全景声下载
- 支持 AAC-LC / AAC / AAC-Binaural / AAC-Downmix 下载
- 支持整张专辑、单曲、播放列表下载
- 支持交互式选曲下载
- 支持搜索（歌曲/专辑/艺人）
- 支持下载艺人全部专辑
- 支持歌词下载（LRC / TTML）
- 支持封面嵌入、动画封面下载
- 支持下载后格式转换（FLAC / MP3 / Opus / WAV）
- 自定义文件名和文件夹命名

## 环境要求

- **Python 3.7+**
- **Docker**（必须安装且可正常运行）

## 快速开始

### 1. 配置

```bash
copy config.yaml.example config.yaml
```

编辑 `config.yaml`，填写以下必要信息：

- `media-user-token`: 你的 Apple Music 媒体用户令牌
- `storefront`: 你的账号所属区域代码（如 `cn`、`us`、`jp`）
- `alac-max`: ALAC 最大采样率，默认 192000

### 2. 准备 Wrapper

将 wrapper 发行版文件夹放置为 `wrapper-release/`，该文件夹需包含：

- `Dockerfile`
- `wrapper`（二进制文件）
- `rootfs/`
- `entrypoint.sh`

也可通过环境变量指定路径：

```bash
$env:WRAPPER_SRC = "你的wrapper路径"
```

### 3. 运行

```bash
python apple_music_downloader.py
```

首次运行会自动：
- 从 `ghcr.io/zhaarey/apple-music-downloader:latest` 拉取下载器镜像
- 从 `wrapper-release/` 构建 Wrapper 镜像
- 引导完成 Apple Music 登录（凭据缓存到 `wrapper-data/`）

## 镜像说明

| 组件 | 来源 | 说明 |
|------|------|------|
| am-downloader | `ghcr.io/zhaarey/apple-music-downloader:latest` | 自动 `docker pull` 拉取 |
| am-wrapper | `wrapper-release/` 本地构建 | 自动 `docker build` 构建 |

> 如已导出 `.tar` 镜像文件，将 `am-downloader.tar` / `am-wrapper.tar` 放在项目根目录，程序会优先从 tar 导入。

### 镜像加速（国内用户）

构建 Wrapper 时，默认使用国内镜像加速：

| 环境变量 | 默认值 | 说明 |
|------|------|------|
| `REGISTRY_MIRROR` | `dockerproxy.com` | Docker Hub 镜像代理 |
| `APT_MIRROR` | `mirrors.tuna.tsinghua.edu.cn` | Debian APT 镜像（清华源） |

如需更换镜像源：

```bash
$env:REGISTRY_MIRROR = "docker.1ms.run"
$env:APT_MIRROR = "mirrors.ustc.edu.cn"
python apple_music_downloader.py
```

## 菜单说明

| 选项 | 功能 |
|------|------|
| `1` | 下载专辑 |
| `2` | 下载单曲 |
| `3` | 交互式选曲（可选择专辑/播放列表中的特定曲目） |
| `4` | 下载播放列表 |
| `5` | Dolby Atmos 模式 |
| `6` | AAC 模式 |
| `7` | 调试 / 查看音质信息 |
| `8` | 搜索（歌曲/专辑/艺人） |
| `9` | 下载艺人全部专辑 |
| `0` | 自定义命令 |
| `S` | 查看 Wrapper 运行状态 |
| `H` | 帮助信息 |
| `Q` | 退出 |

## 配置说明

完整配置项请参考 `config.yaml.example`，常用配置：

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

## 端口说明

Wrapper 服务默认占用以下端口：

| 端口 | 用途 |
|------|------|
| `10020` | 解密 M3U8 |
| `20020` | 获取 M3U8 |
| `30020` | 账号服务 |

## 项目结构

```
.
├── apple_music_downloader.py   # 主程序入口（终端交互菜单）
├── config.yaml                 # 配置文件
├── config.yaml.example         # 配置文件模板
├── wrapper-release/            # Wrapper 构建目录（需自行准备）
│   ├── Dockerfile
│   ├── compose.yaml
│   ├── entrypoint.sh
│   ├── wrapper
│   └── rootfs/
├── wrapper-data/               # Wrapper 数据目录（登录凭据缓存，自动创建）
└── downloads/                  # 下载输出目录（自动创建）
```

> 可选：`am-downloader.tar` / `am-wrapper.tar` 可放在根目录作为离线镜像。

## 常见问题

**Q: 提示 Docker 未安装？**
安装 Docker Desktop 并确保 `docker` 命令可在终端中使用。

**Q: 下载失败？**
- 检查 `config.yaml` 中 `media-user-token` 和 `storefront` 是否正确
- 确认 Wrapper 容器正常运行（按 `S` 查看状态）
- 检查网络连接

**Q: Wrapper 构建时拉取 Debian 镜像很慢？**
设置 `REGISTRY_MIRROR` 环境变量切换镜像代理，详见「镜像加速」章节。

**Q: 歌词获取失败？**
确认 `storefront` 与你 Apple Music 账号的区域一致。

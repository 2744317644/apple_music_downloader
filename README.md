# Apple Music ALAC Downloader

[English](README_EN.md) | 中文

> Apple Music 无损 ALAC / 杜比全景声 Dolby Atmos / AAC 下载工具

## 致谢

本项目基于以下优秀的开源项目构建：

- **[apple-music-downloader](https://github.com/zhaarey/apple-music-downloader)** — Apple Music ALAC / Atmos / AAC 下载核心
- **[wrapper](https://github.com/WorldObservationLog/wrapper)** — Apple Music Android DRM 解密服务（本项目使用其 **legacy 版预编译二进制**，连同 `rootfs/` 一起放在 `assets/Wrapper/`）

感谢以上项目的作者和贡献者们。

## 架构

本项目**不依赖 Docker**，全部组件原生运行：

```
Windows                                          WSL2 (Debian13-wrapper)
┌──────────────────────────┐                    ┌─────────────────────────────┐
│ GUI / CLI  (Python)      │                    │ apple-music-wrapper.service │
│   └─ 通过 wsl.exe 调用   │                    │   ├─ wrapper (legacy)       │
│                          │                    │   │    TCP 10020/20020/      │
│                          │  wsl 交互          │   │        30020/40020      │
│                          │ ─────────────────> │   └─ amdl (legacy, Linux)   │
└──────────────────────────┘                    └─────────────────────────────┘
```

- **wrapper**（legacy 版）：WSL2 内由 systemd 管理，提供四个 TCP 服务
- **amdl**：旧版下载器，从 `assets/apple-music-downloader` 源码编译为 Linux 二进制，同样跑在 WSL 内
- 输出目录通过 `/mnt/c/...` 直接写入 Windows 的 Downloads

> **为什么下载器也要在 WSL 里？** 旧版下载器在 Windows 上遇到含非 ASCII 字符的路径（你的用户目录是 `柠墨白`）会卡死，实测无法完成下载；Linux 构建则完全正常。这也与原先 Docker 的拓扑一致（两个进程都在 Linux 侧）。
>
> **为什么解密端必须放在 WSL2？** wrapper 需要 `unshare` / `mount` / `chroot` 等 Linux 内核能力，Windows 内核不提供。详见 [WSL2-WRAPPER.md](WSL2-WRAPPER.md)。

## 功能特性

- 支持 ALAC 无损下载（最高 192kHz）
- 支持 Dolby Atmos 杜比全景声下载
- 支持 AAC-LC / AAC / AAC-Binaural / AAC-Downmix 下载
- 支持整张专辑、单曲、播放列表、歌手全部专辑下载
- 支持歌词下载（LRC / TTML）
- 支持封面嵌入、动画封面下载
- 支持下载后格式转换（FLAC / MP3 / Opus / WAV）
- 自定义文件名和文件夹命名
- **GUI 图形界面**（侧边栏页签导航）
- **中英文切换**（一键切换界面语言）
- **一键登录**（Apple ID 凭据自动缓存）
- **环境自检**（启动时自动检测 wrapper 服务状态）
- **内置配置编辑**（GUI 内直接编辑保存配置文件）
- **下载进度实时显示**（日志持久化保存）
- **内置格式转换**（打包 ffmpeg，m4a → FLAC / WAV）
- **内置音频重命名**（按标签批量改名）
- **单文件打包**（PyInstaller 打包为独立 EXE）

## 环境要求

- **Windows 10/11 + WSL2**
- **Python 3.7+**（仅 GUI/CLI 需要）

一条命令完成部署：

```powershell
.\scripts\deploy.bat
```

或直接调用 PowerShell（可带参数）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1
```

脚本会依次：创建 WSL2 基座发行版 → 配置 systemd → 写入 WSL 网络设置 →
部署 wrapper → 编译下载器 → 注册并启动服务 → 自检。

Debian **只从微软/Debian 官方渠道获取**，按顺序尝试：

1. `wsl --install -d Debian --web-download`（WSL 自下载官方镜像）
2. `wsl --install -d Debian`（Microsoft Store）
3. 官方发行版清单里的 `.AppxBundle`（微软托管），解包 rootfs 后 `wsl --import`

若网络访问微软/微软云较慢或被阻断，用 `-Proxy` 指定代理：
`deploy.ps1 -Proxy http://127.0.0.1:7890`

原理、目录结构、端口与常见坑见 **[WSL2-WRAPPER.md](WSL2-WRAPPER.md)**。

### CLI 版本额外依赖

```bash
pip install -r requirements.txt
```

## 快速开始

### 1. 确认服务在跑

```bash
python apple_music_downloader.py --status
```

输出应类似：

```
endpoint : http://127.0.0.1:12340
service  : active
status   : RUNNING
regions  : cn
```

### 2. 运行

**终端版本**：

```bash
python apple_music_downloader.py
```

**GUI 版本**：

```bash
python apple_music_downloader_gui.py
```

首次运行会：

- 检测 wrapper 是否在线，不在线则尝试拉起 systemd 服务
- 若没有缓存凭据，引导完成 Apple Music 登录（含 2FA）
- 登录凭据自动缓存，后续无需重复

### 3. 下载文件在哪

保存路径由 `config.yaml` 的 `paths` 段决定，相对路径基于**用户 Downloads 目录**：

| 类型 | 默认位置 |
|------|----------|
| ALAC | `Downloads\AM-Lossless\` |
| 杜比全景声 | `Downloads\AM-Atmos\` |
| AAC | `Downloads\AM-AAC\` |
| MV | `Downloads\AM-MV\` |

> 若你从旧版升级，迁移时会保留原来的 `AM-DL downloads` 等文件夹名。

### 4. 打包为 EXE

```bash
build.bat
```

生成 `AppleMusicDownloader.exe`。

## 配置说明

配置文件位于 `%LOCALAPPDATA%\AppleMusicDownloader\config.yaml`，采用**平铺结构**（旧版下载器的格式）。常用项：

| 配置项 | 说明 |
|--------|------|
| `storefront` | 账号区域代码（`cn` / `us` / `jp` …） |
| `media-user-token` | AAC / 电台 / 歌词需要，见下方说明 |
| `authorization-token` | 留空即可，下载器会自动获取 |
| `alac-max` | ALAC 最高采样率：192000 / 96000 / 48000 / 44100 |
| `atmos-max` | Atmos 最高码率：2768 / 2448 |
| `aac-type` | `aac-lc` / `aac` / `aac-binaural` / `aac-downmix` |
| `alac-save-folder` 等 | 各类保存目录（相对路径基于 Downloads） |
| `song-file-format` | 单曲文件名模板 |
| `lrc-type` / `lrc-format` / `embed-lrc` | 歌词类型、格式、是否嵌入 |
| `cover-size` / `cover-format` / `embed-cover` | 封面尺寸、格式、是否嵌入 |
| `convert-after-download` / `convert-format` | 下载后是否转换及目标格式 |
| `decrypt-m3u8-port` / `get-m3u8-port` | wrapper 端口，默认 `127.0.0.1:10020` / `20020` |

> 程序启动时会自动检测配置格式（包括从 v0.1.x 的嵌套格式回退），原文件备份为 `config.yaml.bak`。

### 获取 media-user-token

`media-user-token` 只在 **AAC 下载 / 电台 / 歌词** 时需要，**下载 ALAC 无损不需要**。

程序已内置获取流程：**配置页签 → 「获取 Token」**。它会：

1. 自动扫描本机浏览器（Firefox 的 cookie 是明文，可直接读取）
2. Chrome / Edge / Brave 的 cookie 被浏览器加密，无法直接读取，此时弹窗给出操作指引
3. 粘贴后**立即向 Apple 校验**，通过才写入配置 —— 不会把无效值存进去

手动获取的步骤：

1. 浏览器登录 https://music.apple.com
2. `F12` → `Application`（应用）→ `Storage` → `Cookies` → `https://music.apple.com`
3. 找到 `media-user-token`，整串复制它的 `Value`
4. 粘进程序弹窗，点「校验并保存」

CLI 版本对应菜单项 `T`。

> 该 token 会随会话轮换失效。如果 AAC 下载报 `Invalid media-user-token`，重新获取一次即可。

### 文件名模板变量

- 专辑文件夹：`{AlbumId}` `{AlbumName}` `{ArtistName}` `{ReleaseDate}` `{ReleaseYear}` `{UPC}` `{Copyright}` `{Quality}` `{Codec}` `{Tag}` `{RecordLabel}`
- 单曲文件：`{SongId}` `{SongNumer}` `{SongName}` `{DiscNumber}` `{TrackNumber}` `{Quality}` `{Codec}` `{Tag}`

## GUI 使用说明

界面采用侧边栏页签导航，包含五个页签：**下载** / **状态** / **配置** / **转换** / **重命名**。

### 下载

| 组件 | 功能 |
|------|------|
| 模式选择 | 专辑 / 单曲 / 播放列表 / 杜比全景声 / AAC / 交互选择 / 调试 / 搜索 / 歌手全部专辑 |
| URL 输入框 | 粘贴 Apple Music 链接，支持右键粘贴 |
| Download 按钮 | 开始下载，下载中变红，再次点击取消 |
| 输出日志 | 实时显示下载进度，进度行原地刷新 |

### 状态

| 显示项 | 说明 |
|--------|------|
| Wrapper 服务 | 接口地址、WSL 服务状态、是否响应、监听端口、可用区域 |
| 登录 | 凭据缓存状态 |
| 路径 | 配置文件、日志目录、下载器路径，可点击打开 |

### 配置

内置 YAML 编辑器，可直接修改配置文件并保存。

### 格式转换

选择 `.m4a` 所在目录，递归扫描并转换为 FLAC，支持跳过已转换文件。使用内置 ffmpeg，无需额外管道。

### 音频重命名

选择 FLAC/WAV 所在目录，两种命名模板：

- **编号. 音乐名**：取文件名编号 + 标签中的歌曲名
- **歌手 - 音乐名**：取标签中的艺术家与歌曲名

## 终端菜单说明

| 选项 | 功能 |
|------|------|
| `1` | 下载专辑 |
| `2` | 下载单曲（URL 带 `?i=` 曲目 ID） |
| `3` | 交互式选曲 |
| `4` | 下载播放列表 |
| `5` | Dolby Atmos 模式 |
| `6` | AAC 模式 |
| `7` | 调试 / 查看音质信息 |
| `8` | 搜索（歌曲/专辑/艺人） |
| `9` | 下载艺人全部专辑 |
| `0` | 自定义命令 |
| `S` | Wrapper 状态 |
| `R` | 重启 Wrapper 服务 |
| `L` | Apple Music 登录 |
| `H` | 帮助信息 |
| `Q` | 退出 |

## 项目结构

```
.
├── apple_music_downloader.py      # 终端版入口
├── apple_music_downloader_gui.py  # GUI 版入口
├── common.py                      # 共享逻辑（配置 / wrapper / 登录）
├── build.bat                      # 打包脚本
├── config.yaml.example            # 默认配置示例
├── requirements.txt               # Python 依赖
├── WSL2-WRAPPER.md                # WSL2 基座安装与运维说明
├── scripts/
│   ├── deploy.ps1                 # 一键部署（创建基座 + 部署组件）
│   ├── deploy.bat                 # deploy.ps1 的免策略包装器
│   ├── uninstall.ps1              # 一键卸载（只删本项目的东西）
│   ├── uninstall.bat              # uninstall.ps1 的免策略包装器
│   └── provision-distro.sh        # 部署 wrapper + 下载器（发行版内）
└── assets/
    ├── app_icon.ico                     # 应用图标
    ├── ffmpeg.exe                       # 格式转换 / 动图封面
    ├── ffprobe.exe                      # 标签读取
    └── flac.exe                         # FLAC 编码器
```

> **ffmpeg 说明**：`ffmpeg.exe` / `ffprobe.exe` 通过 **Git LFS** 纳入版本管理（克隆前请先 `git lfs install`）。也可从 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 下载后放入 `assets/`。程序会依次在 `assets/` → 系统 PATH → WinGet 安装目录中查找。

### 运行时数据

| 数据 | 路径 |
|------|------|
| 配置文件 | `%LOCALAPPDATA%\AppleMusicDownloader\config.yaml` |
| 运行日志 | `%LOCALAPPDATA%\AppleMusicDownloader\log\` |
| 登录凭据 | WSL 内 `/opt/wrapper/rootfs/data/.../files/` |
| 下载文件 | 用户 Downloads 文件夹 |

## 已知问题

**1. WSL 空闲关闭会中断服务**

WSL 默认在空闲后关闭虚拟机，导致 wrapper 和下载器一起停止。本仓库已通过
`%USERPROFILE%\.wslconfig` 的 `vmIdleTimeout=-1` 关闭该行为。若发现服务莫名消失，
先检查这个文件，并执行 `wsl --shutdown` 让配置生效。

**2. 部分曲目在中国区没有无损**

某些单曲在当前区域只提供 AAC。此时下载器会回退到 AAC 并提示：

```
Unavailable, trying to dl aac-lc
MediaUserToken not set
```

若你在 `config.yaml` 里填好 `media-user-token`（从浏览器 Apple Music 的
`media-user-token` cookie 复制），AAC 回退也能正常工作。

**3. MP4Box 为可选项**

旧版下载器原本要求 MP4Box 才能完成标签写入，缺失时会把已下载的音频整首丢弃。
本仓库已把这一步改为可跳过（`assets/apple-music-downloader/main.go`），
没有 MP4Box 时音频照常保存，仅跳过 iTunes 标签嵌入。想获得完整标签可在 WSL 内
安装 gpac。

**4. `--song` 与 `?i=` 组合**

旧版下载器的 `--song` 参数期望的是 `/song/...` 形式的页面链接；
对 `/album/...?i=...` 这种链接请直接用专辑模式。

## 常见问题

**Q: 提示 wrapper 未响应？**

```bash
python apple_music_downloader.py --status        # 查看状态
wsl -d Debian13-wrapper -- systemctl status apple-music-wrapper
wsl -d Debian13-wrapper -- systemctl restart apple-music-wrapper
```

**Q: 提示找不到下载器？**

下载器在 WSL 内的 `/opt/amdl-legacy/amdl`，由 `scripts/provision-distro.sh` 编译生成。
重新执行该脚本即可重建。

**Q: GUI 启动闪退或无响应？**

- 确认 WSL2 可用：`wsl -d Debian13-wrapper -- echo ok`
- 查看日志：`%LOCALAPPDATA%\AppleMusicDownloader\log\`

**Q: 提示 "Failed to get token"？**

- 检查网络能否访问 `music.apple.com`
- 在浏览器登录 Apple Music 后，手动复制 `authorization-token` 填入配置文件

**Q: 下载后没有文件？**

- 检查 `paths` 段配置，确认目录有写入权限
- 确认 `storefront` 与账号区域一致
- 下载器在 `Downloads` 目录下运行，相对路径即基于该目录

**Q: 歌词获取失败？**

确认 `general.storefront` 与你 Apple Music 账号的区域一致（如中国区填 `cn`）。

**Q: 从旧版升级后配置报错？**

程序会自动迁移旧配置并把原文件备份为 `config.yaml.bak`。如迁移后仍有问题，可参考 `config.yaml.example` 手动调整。

**Q: 打包 EXE 失败？**

- 确保已关闭正在运行的 `AppleMusicDownloader.exe`
- 确保 `requirements.txt` 中的依赖已安装

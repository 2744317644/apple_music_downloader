# WSL2 基座与 wrapper 部署

本项目原先依赖 Docker 运行 `wrapper` 解密服务与下载器，现已改为**全部在 WSL2 里原生运行**。
Windows 侧不需要 Docker Desktop 或任何容器运行时。

## 架构

```
Windows                                          WSL2 发行版 Debian13-wrapper
┌──────────────────────────┐                    ┌──────────────────────────────────┐
│ GUI / CLI  (Python)      │                    │ systemd                          │
│   └─ wsl.exe 调用        │  127.0.0.1         │  └─ apple-music-wrapper.service  │
│                          │ ────────────────>  │      ├─ wrapper  (legacy)        │
│                          │ 10020/20020/       │      │    TCP 4 个端口            │
│                          │ 30020/40020        │      └─ (下载器按需启动)         │
│                          │                    │          /opt/amdl-legacy/amdl   │
└──────────────────────────┘                    └──────────────────────────────────┘
                            └─ 输出写 /mnt/c/Users/<用户>/Downloads/
```

- **wrapper**（legacy 版）：systemd 常驻服务，提供四个 TCP 服务（解密 / m3u8 / 账号 / key）
- **amdl**：旧版下载器，编译为 Linux 二进制，由 Python 侧通过 `wsl.exe` 调用
- 下载器**必须跑在 Linux 侧**：Windows 构建在含非 ASCII 字符的路径（如 `柠墨白`）上会卡死

## 目录

| 内容 | 位置 |
|------|------|
| WSL 发行版虚拟磁盘 | `%LOCALAPPDATA%\WSL\Debian13-wrapper` |
| wrapper 程序与 rootfs | WSL 内 `/opt/wrapper` |
| 登录凭据 | WSL 内 `/opt/wrapper/rootfs/data/data/com.apple.android.music/files` |
| 下载器 | WSL 内 `/opt/amdl-legacy/amdl` |
| 服务日志 | WSL 内 `/var/log/apple-music-wrapper.log` |
| systemd 服务 | `/etc/systemd/system/apple-music-wrapper.service` |
| 开机启动项 | `启动文件夹\AppleMusicWrapper.lnk` |

## 安装：标准流程

安装由**一条命令**完成。

### 一键部署

```powershell
.\scripts\deploy.bat
```

`deploy.bat` 只是把 PowerShell 的执行策略绕过一下（很多机器默认禁止运行 `.ps1`），
实际逻辑在 `deploy.ps1`。也可以直接调用：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1
```

它依次完成：创建基座发行版 → 写 `wsl.conf` 启用 systemd → 写 `.wslconfig` →
部署 wrapper → 编译下载器 → 注册并启动 systemd 服务 → 自检。

创建发行版之前会**询问把发行版磁盘放在哪个盘**：

```
  The distro disk only grows, so pick a drive with room to spare.
    [1] C:     43.0 GB free of  198.9 GB  (system drive)
    [2] D:    349.2 GB free of  752.5 GB  <- most free
    [3] E:    345.3 GB free of  953.9 GB

  Store WSL data on which drive? [1-3, Enter for 2, or type a full path]:
```

- 输入编号 → 存到 `<盘符>:\WSL\<发行版名>\`
- 直接回车 → 用空闲空间最大的那个盘
- 输入完整路径 → 用你指定的目录
- 同时把 `swapFile` 指到该盘，交换文件也不再占 C 盘

不想被询问时：

```powershell
.\scripts\deploy.ps1 -Location D:\WSL     # 直接指定，不询问
.\scripts\deploy.ps1 -NonInteractive      # 不询问，用默认 %LOCALAPPDATA%\WSL
```

### Debian 从哪里获取

**只从微软 / Debian 官方渠道获取，不使用 Docker 仓库。** 脚本先快速尝试 WSL 自带通道，
失败后**自动测速**两条官方直链，走最快的那条：

| 阶段 | 方式 | 说明 |
|------|------|------|
| 1 | `wsl --install -d Debian --no-launch --web-download` | WSL 自己下载官方镜像 |
| 2 | `wsl --install -d Debian --no-launch` | Microsoft Store 通道 |
| 3 | **Debian 官方 WSL 镜像**（salsa.debian.org） | 测速后择优 |
| 4 | 微软 blob 的 `.AppxBundle` | 测速后择优 |

第 3、4 步的地址来自微软维护的官方发行版清单
`https://raw.githubusercontent.com/microsoft/WSL/master/distributions/DistributionInfo.json`。

两个关键细节：

**salsa 的 PoW 绕过** —— 清单里给的是 `/-/jobs/9606244/artifacts/raw/...`，
这个地址受**工作量证明挑战**保护，返回的是 HTML 挑战页而不是镜像。
但同一 job 下的 `/-/jobs/9606244/artifacts/download` **没有挑战**，直接返回 ZIP 制品。
脚本自动把前者转成后者。

**清单域名会抽风** —— `raw.githubusercontent.com` 在这类网络下时通时断。
脚本会用 curl 重试 3 次；仍失败则回退到内置的已知官方 URL，
所以清单域名不可达**不会阻塞部署**。

> 下载后脚本会校验它是真归档（拒绝 HTML 挑战页/错误页）。
> 若清单提供了 SHA256 则一并核对。

### 网络要求与耗时

不需要代理也能完成，只是**下载镜像这段时间取决于线路**。实测（无代理）：

| 来源 | 实测速度 | 177 MB 预计耗时 |
|------|----------|-----------------|
| salsa 官方 WSL 镜像 | 0.06–0.42 MB/s | 约 10–48 分钟 |
| 微软 blob `.AppxBundle` | 0.02–0.04 MB/s | 1.5–2 小时 |

脚本会先测速再选，并在开始前打印预计耗时。

**salsa 支持断点续传**（返回 `206 Partial Content`），所以下载中断可以重跑接着下：

```
[OK] resuming from the 21 MB already downloaded
```

微软 blob **不支持字节范围**，那个源一旦中断只能从头开始 —— 这也是脚本优先选 salsa 的原因。

### 如果线路实在太慢

三个可选做法，都不需要代理：

1. **让脚本继续跑** —— 它可续传，中断后重跑即可
2. **用浏览器下载后本地导入**（浏览器能过 PoW，且可能走不同的路由）：
   在浏览器打开清单里 Debian 的 `.wsl` 地址，下载完成后：
   ```powershell
   .\scripts\deploy.ps1 -ImagePath 'C:\Users\你\Downloads\Debian_WSL_AMD64_v1.26.0.0.wsl'
   ```
3. **指定代理**（如果你的网络有这个条件）：
   ```powershell
   .\scripts\deploy.ps1 -Proxy http://127.0.0.1:7890
   ```

### 可用参数

| 参数 | 说明 |
|------|------|
| `-Name <name>` | 发行版名，默认 `Debian13-wrapper` |
| `-Location <dir>` | 磁盘存放位置，如 `D:\WSL`；不指定则运行时询问 |
| `-NonInteractive` | 不询问，直接用默认位置 `%LOCALAPPDATA%\WSL` |
| `-Method Auto\|WebDownload\|Store\|FromFile` | 限定获取方式，默认 `Auto` |
| `-Proxy <url>` | 下载镜像时使用的 HTTP(S) 代理 |
| `-ImagePath <file>` | 直接导入本地镜像（`.wsl` / `.appx` / rootfs tar） |
| `-ImageUrl` / `-ImageSha256` | 自定义镜像地址与校验值 |
| `-SkipProvision` | 只创建基座，不部署组件 |
| `-SkipWslConfig` | 不修改 `%USERPROFILE%\.wslconfig` |
| `-CreateStartupShortcut` | 在启动文件夹添加快捷方式，登录时自动拉起 WSL |
| `-KeepDownload` | 保留下载的镜像文件 |

> `wsl --install -d Debian` 得到的发行版可能就叫做 `Debian`（当前 WSL 版本不支持重命名）。
> 程序会自动发现可用的 Debian 发行版名，无需手动改名。

### MP4Box（标签写入必需）

`provision-distro.sh` 会把 `assets/MP4Box` 安装到 `/usr/local/bin/MP4Box`。

它**不是可选项**：下载器先调用 `MP4Box -itags` 创建 `udta/ilst` box，之后自己的
Go 标签写入才能成功。缺了它，音频能下载但**标题、歌手、专辑、封面、歌词全部丢失**，
日志里会出现：

```
[WARN] MP4Box not found - skipping tag embedding, audio is still saved
⚠ Failed to write tags in media: moov.udta box not present
```

`gpac` 在 Debian 13（trixie）里没有打包（专利原因），所以这里放的是从 GPAC 26.07
源码编译的静态二进制（MINI build，约 12 MB），一次编译、随仓库分发。

### 分步执行

只想重新部署组件、不重建发行版：

```powershell
wsl -d Debian13-wrapper -- bash /mnt/e/Code/apple_music_downloader/scripts/provision-distro.sh
```

脚本做的事（幂等，可重复执行）：

1. 配置 apt 源（裸 rootfs 没有 `ca-certificates`，先用 http 镜像）
2. 安装 `ca-certificates systemd systemd-sysv procps build-essential golang-go sqlite3 curl unzip zip`
3. 从 `assets/Wrapper` 部署 wrapper 到 `/opt/wrapper`（已存在则跳过，**保留登录凭据**）
4. 从 `assets/apple-music-downloader` 用 Go 编译下载器到 `/opt/amdl-legacy/amdl`
5. 写入 `start-wrapper.sh`、systemd unit 与快速停止 drop-in
6. 启用并启动服务，等待 30020 应答

### Windows 侧全局配置

`%USERPROFILE%\.wslconfig`：

```ini
[wsl2]
networkingMode=mirrored
vmIdleTimeout=-1
dnsTunneling=true
autoProxy=true
```

- `networkingMode=mirrored` —— 让 `127.0.0.1` 稳定可达。默认 NAT 模式下端口转发偶发失效，
  表现为「服务明明在跑，Windows 侧却连不上」
- `vmIdleTimeout=-1` —— 禁止 WSL 空闲关停虚拟机，否则下载会中途中断

改完需要 `wsl --shutdown` 生效。

## 运行期行为

| 时机 | 发生什么 |
|------|----------|
| 启动软件 | `wsl -d Debian13-wrapper -- systemctl start apple-music-wrapper` —— 这条命令本身会把发行版（即 WSL 虚拟机）拉起来，然后等端口就绪（最长 60 秒） |
| 关闭软件 | 停服务 → **`wsl --shutdown` 释放虚拟机**（默认行为） |
| 无凭据启动 | wrapper 正常工作需要缓存凭据；没有时它打印初始化信息后**以状态 0 退出**。systemd 的 `Restart=on-failure` 会让它停在 `inactive`，而不是无限重启 |

关闭时释放虚拟机的代价：下次启动要重新拉起 + wrapper 初始化，约 **60–90 秒**。

想保留虚拟机（下次启动只要几秒），设一个环境变量：

```powershell
$env:AMDL_SHUTDOWN_WSL_ON_EXIT = "0"
```

这样关闭软件只停服务、不关虚拟机。

> 为什么默认用 `wsl --shutdown` 而不是 `wsl --terminate <发行版>`：
> `vmIdleTimeout=-1` 会让虚拟机在空闲时也不自动回收，只有 `--shutdown` 能真正释放内存。
> 但如果检测到**别的发行版正在运行**（例如 Docker Desktop 的 `docker-desktop`），
> 程序会退一步只终止我们自己那个，避免打断你的容器。

## 卸载

```powershell
.\scripts\uninstall.bat
```

先看会删什么、不动任何东西：

```powershell
.\scripts\uninstall.bat -DryRun
```

默认会做这些：

1. 停掉 wrapper 服务、终止发行版
2. **备份登录凭据**到 `%LOCALAPPDATA%\AppleMusicDownloader\wrapper-backup-<时间戳>\`
3. 注销发行版、删除虚拟磁盘
4. 删除启动文件夹里的 `AppleMusicWrapper.lnk`
5. 删除 `%TEMP%` 里缓存的官方镜像

默认**不动**这些：

| 保留项 | 原因 |
|--------|------|
| 其他 WSL 发行版 | 只删带 `/opt/wrapper` 足迹的；`docker-desktop` 等在保护名单里 |
| `%LOCALAPPDATA%\AppleMusicDownloader\` | 你的 config.yaml、日志、凭据备份 |
| `%USERPROFILE%\.wslconfig` | 全局 WSL 设置，可能你还有别的用途 |

需要更彻底时：

| 参数 | 作用 |
|------|------|
| `-Force` | 不再要求输入 `YES` 确认 |
| `-PurgeAppData` | 同时删除 config.yaml、日志和凭据备份 |
| `-ResetWslConfig` | 移除本项目加的 `[wsl2]` 调优，有 `.wslconfig.bak` 则还原 |
| `-KeepBackup` | 不做凭据备份 |
| `-KeepImages` | 保留 `%TEMP%` 里的镜像缓存（便于快速重新部署） |
| `-Name <name>` | 指定要删的发行版名 |
| `-DryRun` | 只打印计划 |

> 自动识别规则：名字恰好是 `Debian13-wrapper`（本项目固定用的名字）就直接认定；
> 其他 `Debian*` 必须含 `/opt/wrapper` 足迹才处理，避免误删你自己装的 Debian。

## 常用命令

```powershell
# 应用层状态（推荐）
python apple_music_downloader.py --status

# systemd 状态
wsl -d Debian13-wrapper -- systemctl status apple-music-wrapper --no-pager

# 重启服务
wsl -d Debian13-wrapper -- systemctl restart apple-music-wrapper

# 看日志
wsl -d Debian13-wrapper -- tail -50 /var/log/apple-music-wrapper.log

# 接口自检
wsl -d Debian13-wrapper -- curl -s http://127.0.0.1:30020/
```

## 端口

| 端口 | 协议 | 用途 |
|------|------|------|
| 10020 | 裸 TCP | 样本解密 |
| 20020 | 裸 TCP | 获取 M3U8 |
| 30020 | HTTP | 账号信息 / `dev_token` |
| 40020 | HTTP | key service |

## 首登

GUI 登录页，或 CLI 菜单 `L`。底层等价于：

```bash
cd /opt/wrapper
./wrapper -L "APPLE_ID:PASSWORD" -F -H 0.0.0.0
```

需要 2FA 时，把 6 位码写进
`/opt/wrapper/rootfs/data/data/com.apple.android.music/files/2fa.txt`，
wrapper 会自动读取并删除。GUI 已把这个流程自动化。

## 踩过的坑

| 现象 | 原因 | 处理 |
|------|------|------|
| `wsl --install -d Debian` 连接被重置 | Store/CDN 被阻断 | 改用 `wsl --import` 导入官方 rootfs（脚本已自动回退） |
| 服务在跑但 Windows 连不上 | NAT 模式端口转发失效 | `.wslconfig` 开 `networkingMode=mirrored` |
| 服务莫名消失 | WSL 空闲关停虚拟机 | `vmIdleTimeout=-1` |
| `systemctl restart` 卡 90 秒 | legacy wrapper 不响应 SIGTERM | drop-in 里 `KillSignal=SIGKILL` + `TimeoutStopSec=5` |
| 下载卡在 0% | Windows 版下载器无法处理中文路径 | 下载器改为在 WSL 内运行 Linux 构建 |
| 每首曲子下完却报错丢弃 | MP4Box 缺失被判为致命错误 | 源码已改为可跳过（`assets/apple-music-downloader/main.go`） |

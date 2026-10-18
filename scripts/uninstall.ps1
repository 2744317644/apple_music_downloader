<#
.SYNOPSIS
    Remove the environment created by scripts/deploy.ps1.

.DESCRIPTION
    Uninstalls, in a safe order:

      1. stops the wrapper service and terminates the distro
      2. backs up the cached Apple Music credentials (kept by default)
      3. unregisters the WSL distro and deletes its virtual disk
      4. removes the logon shortcut
      5. removes the cached installer images in %TEMP%

    What it will NOT touch:
      * any distro that does not carry our footprint (/opt/wrapper). That is
        checked per distro, so an unrelated distro that happens to be called
        "Debian" survives.
      * Docker's own distros (docker-desktop / docker-desktop-data)
      * your config.yaml, logs and backups, unless -PurgeAppData is given
      * %USERPROFILE%\.wslconfig, unless -ResetWslConfig is given

.PARAMETER Name
    Distro name to remove. Default: auto-detect (Debian13-wrapper, Debian, Debian-*).

.PARAMETER Force
    Do not ask for confirmation.

.PARAMETER KeepBackup
    Do not back up the cached credentials before removing the distro.

.PARAMETER KeepImages
    Keep the cached installer images in %TEMP%.

.PARAMETER PurgeAppData
    Also delete %LOCALAPPDATA%\AppleMusicDownloader (config.yaml, logs,
    credential backups). Destructive - your Apple Music settings are lost.

.PARAMETER ResetWslConfig
    Remove the [wsl2] tuning this project added to %USERPROFILE%\.wslconfig
    (networkingMode, vmIdleTimeout, dnsTunneling, autoProxy) and restore the
    .wslconfig.bak left behind by the deploy script, if present.

.EXAMPLE
    .\scripts\uninstall.bat

.EXAMPLE
    .\scripts\uninstall.ps1 -Force -PurgeAppData
#>
[CmdletBinding()]
param(
    [string]$Name = '',

    [switch]$Force,
    [switch]$KeepBackup,
    [switch]$KeepImages,
    [switch]$PurgeAppData,
    [switch]$ResetWslConfig,

    # Print the plan and exit without changing anything.
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$env:WSL_UTF8 = '1'
try {
    if ([Console]::OutputEncoding.CodePage -ne 65001) {
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    }
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

function Write-Step { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn2{ param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Err2 { param($m) Write-Host "[ERROR] $m" -ForegroundColor Red }

$APP_DATA   = Join-Path $env:LOCALAPPDATA 'AppleMusicDownloader'
$WSL_ROOT   = Join-Path $env:LOCALAPPDATA 'WSL'
$WSLCONFIG  = Join-Path $env:USERPROFILE '.wslconfig'
$STARTUP    = [Environment]::GetFolderPath('Startup')

# Distros we are allowed to consider. Everything else is off limits.
$PROTECTED = @('docker-desktop', 'docker-desktop-data', 'Ubuntu', 'Ubuntu-22.04',
               'Ubuntu-24.04', 'kali-linux', 'AlmaLinux-8', 'AlmaLinux-9')

function Get-Distros {
    return @((wsl -l -q 2>$null) | ForEach-Object { ($_ -replace "`0", '').Trim() } |
             Where-Object { $_ })
}

function Test-OursFootprint {
    <# A distro is ours only if it has /opt/wrapper (installed by our deploy). #>
    param([string]$Distro)
    try {
        $r = & wsl -d $Distro -- test -d /opt/wrapper 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Get-DistroBasePath {
    <# Actual install path from the registry - the distro may live on any drive. #>
    param([string]$Distro)
    try {
        $key = Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' -ErrorAction SilentlyContinue |
               Where-Object {
                   (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DistributionName -eq $Distro
               } | Select-Object -First 1
        if ($key) {
            $bp = (Get-ItemProperty $key.PSPath -ErrorAction SilentlyContinue).BasePath
            if ($bp) { return $bp.TrimEnd('\') }
        }
    } catch { }
    return $null
}

function Get-DirSizeMB {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return 0 }
    try {
        $b = (Get-ChildItem $Path -Recurse -Force -ErrorAction SilentlyContinue |
              Measure-Object -Property Length -Sum).Sum
        if (-not $b) { return 0 }
        return [math]::Round($b / 1MB, 1)
    } catch { return 0 }
}

# ---------------------------------------------------------------------------
# 1. Decide what to remove
# ---------------------------------------------------------------------------
Write-Step 'Scanning'

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Write-Warn2 'wsl.exe not found - only cached files will be cleaned.'
    $distro = $null
} else {
    $all = Get-Distros
    Write-Host ("    installed distros: {0}" -f (($all -join ', ') -replace '^$', '(none)'))

    if ($Name) {
        if ($all -notcontains $Name) {
            Write-Err2 "distro '$Name' does not exist."
            $distro = $null
        } elseif ($PROTECTED -contains $Name) {
            Write-Err2 "'$Name' is on the protected list and will not be removed."
            $distro = $null
        } elseif (-not (Test-OursFootprint $Name) -and -not $Force) {
            Write-Err2 "'$Name' exists but has no /opt/wrapper - it does not look like ours."
            Write-Host '    Refusing to remove it. Use -Force only if you are certain.'
            $distro = $null
        } else {
            $distro = $Name
        }
    } else {
        # Exact name first: 'Debian13-wrapper' is a name this project chooses,
        # so it is ours even when provisioning never completed (no /opt/wrapper).
        # Other Debian-looking distros must prove it via the footprint.
        $all2 = Get-Distros
        if ($all2 -contains 'Debian13-wrapper') {
            $distro = 'Debian13-wrapper'
        } else {
            $candidates = @($all2 | Where-Object {
                $_ -in @('Debian', 'Debian-13') -or $_ -like 'Debian*'
            } | Where-Object { $PROTECTED -notcontains $_ })
            foreach ($c in $candidates) {
                if (Test-OursFootprint $c) { $distro = $c; break }
            }
            if (-not $distro -and $candidates.Count -gt 0) {
                Write-Warn2 ("found {0} but none has /opt/wrapper - leaving them alone" -f ($candidates -join ', '))
                Write-Host '    pass -Name and -Force if you are sure one of them is ours.'
            }
        }
    }
}

$distroDir = $null
if ($distro) {
    # Prefer the real path from the registry: the distro may have been created
    # on another drive with deploy.ps1 -Location.
    $distroDir = Get-DistroBasePath $distro
    if (-not $distroDir) { $distroDir = Join-Path $WSL_ROOT $distro }
}
$images = @(Get-ChildItem $env:TEMP -Filter 'debian-wsl-artifacts.zip' -ErrorAction SilentlyContinue) +
          @(Get-ChildItem $env:TEMP -Filter 'Debian_WSL_*.wsl' -ErrorAction SilentlyContinue)

# ---------------------------------------------------------------------------
# 2. Show the plan
# ---------------------------------------------------------------------------
Write-Step 'Plan'
$nothingToDo = $true

if ($distro) {
    $nothingToDo = $false
    Write-Host ("    remove WSL distro      : {0}" -f $distro)
    if ($distroDir -and (Test-Path $distroDir)) {
        Write-Host ("      virtual disk         : {0} ({1} MB)" -f $distroDir, (Get-DirSizeMB $distroDir))
    }
    if (-not $KeepBackup) { Write-Host '      credentials          : backed up first' }
}

$lnk = Join-Path $STARTUP 'AppleMusicWrapper.lnk'
if (Test-Path $lnk) {
    $nothingToDo = $false
    Write-Host ("    remove logon shortcut  : {0}" -f $lnk)
}

if (-not $KeepImages -and $images.Count -gt 0) {
    $nothingToDo = $false
    $sz = [math]::Round((($images | Measure-Object -Property Length -Sum).Sum) / 1MB, 1)
    Write-Host ("    remove cached images   : {0} file(s), {1} MB" -f $images.Count, $sz)
}

if ($PurgeAppData -and (Test-Path $APP_DATA)) {
    $nothingToDo = $false
    Write-Host ("    purge app data         : {0} ({1} MB)" -f $APP_DATA, (Get-DirSizeMB $APP_DATA))
} elseif (Test-Path $APP_DATA) {
    Write-Host ("    keep app data          : {0}  (use -PurgeAppData to remove)" -f $APP_DATA) -ForegroundColor DarkGray
}

if ($ResetWslConfig) {
    $nothingToDo = $false
    Write-Host '    reset .wslconfig       : remove the [wsl2] tuning added by deploy'
}

if ($nothingToDo) {
    Write-Ok 'nothing to remove.'
    exit 0
}

if ($DryRun) {
    Write-Host ''
    Write-Ok 'dry run - nothing was changed.'
    exit 0
}

if (-not $Force) {
    Write-Host ''
    Write-Host 'This is destructive. Type YES to continue: ' -NoNewline -ForegroundColor Yellow
    $answer = Read-Host
    if ($answer -ne 'YES') {
        Write-Warn2 'cancelled - nothing was changed.'
        exit 1
    }
}

# ---------------------------------------------------------------------------
# 3. Stop, back up, remove
# ---------------------------------------------------------------------------
if ($distro) {
    Write-Step "Removing distro '$distro'"

    Write-Host '    stopping the wrapper service...'
    try { & wsl -d $distro -- systemctl stop apple-music-wrapper 2>$null | Out-Null } catch { }
    try { & wsl --terminate $distro 2>$null | Out-Null } catch { }
    Start-Sleep -Seconds 2

    if (-not $KeepBackup) {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $backup = Join-Path $APP_DATA "wrapper-backup-$stamp"
        $backupWsl = '/mnt/' + ($backup.Substring(0, 1).ToLower()) + ($backup.Substring(2) -replace '\\', '/')
        try {
            New-Item -ItemType Directory -Force -Path $backup | Out-Null
            & wsl -d $distro -- sh -c "tar -czf '$backupWsl/wrapper-data.tar.gz' -C /opt/wrapper/rootfs/data/data/com.apple.android.music/files . 2>/dev/null" | Out-Null
            if (Test-Path (Join-Path $backup 'wrapper-data.tar.gz')) {
                Write-Ok ("credentials backed up to {0}" -f $backup)
            } else {
                Write-Warn2 'no cached credentials to back up (never logged in?)'
                Remove-Item $backup -Recurse -Force -ErrorAction SilentlyContinue
            }
        } catch {
            Write-Warn2 "credential backup failed: $($_.Exception.Message)"
        }
    }

    Write-Host '    unregistering...'
    $out = & wsl --unregister $distro 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Err2 ("wsl --unregister failed: {0}" -f ($out | Out-String).Trim())
        exit 1
    }
    Write-Ok "distro '$distro' unregistered"

    if ($distroDir -and (Test-Path $distroDir)) {
        Remove-Item $distroDir -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $distroDir) { Write-Warn2 "could not fully delete $distroDir (a file may be locked)" }
        else { Write-Ok 'virtual disk deleted' }
    }

    # Tidy an empty parent directory.
    if ((Test-Path $WSL_ROOT) -and -not (Get-ChildItem $WSL_ROOT -Force -ErrorAction SilentlyContinue)) {
        Remove-Item $WSL_ROOT -Force -ErrorAction SilentlyContinue
    }
}

if (Test-Path $lnk) {
    Write-Step 'Removing the logon shortcut'
    Remove-Item $lnk -Force -ErrorAction SilentlyContinue
    Write-Ok 'shortcut removed'
}

if (-not $KeepImages -and $images.Count -gt 0) {
    Write-Step 'Removing cached installer images'
    foreach ($f in $images) {
        Remove-Item $f.FullName -Force -ErrorAction SilentlyContinue
        Write-Ok ("deleted {0}" -f $f.Name)
    }
}

if ($PurgeAppData) {
    Write-Step 'Purging application data'
    if (Test-Path $APP_DATA) {
        Remove-Item $APP_DATA -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $APP_DATA) { Write-Warn2 "could not fully delete $APP_DATA" }
        else { Write-Ok 'application data removed (config.yaml, logs, backups)' }
    } else {
        Write-Ok 'nothing to purge'
    }
}

if ($ResetWslConfig) {
    Write-Step 'Resetting .wslconfig'
    if (Test-Path "$WSLCONFIG.bak") {
        Copy-Item "$WSLCONFIG.bak" $WSLCONFIG -Force
        Write-Ok 'restored .wslconfig from .wslconfig.bak'
    } elseif (Test-Path $WSLCONFIG) {
        $ours = @('networkingmode', 'vmidletimeout', 'dnstunneling', 'autoproxy')
        $kept = Get-Content $WSLCONFIG -Encoding utf8 | Where-Object {
            $line = $_
            if ($line -match '^\s*\[(.+)\]\s*$') { return $matches[1].ToLower() -ne 'wsl2' }
            if ($line -match '^\s*([A-Za-z0-9]+)\s*=') { return $ours -notcontains $matches[1].ToLower() }
            return $true
        }
        if ($kept) { Set-Content $WSLCONFIG -Value $kept -Encoding utf8 }
        else { Remove-Item $WSLCONFIG -Force -ErrorAction SilentlyContinue }
        Write-Ok 'removed the [wsl2] tuning this project added'
    } else {
        Write-Ok '.wslconfig does not exist'
    }
    Write-Host '    run "wsl --shutdown" for it to take effect'
}

# ---------------------------------------------------------------------------
# 4. Verify
# ---------------------------------------------------------------------------
Write-Step 'Verifying'
if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
    $left = Get-Distros
    Write-Host ("    remaining distros: {0}" -f (($left -join ', ') -replace '^$', '(none)'))
    if ($distro -and ($left -contains $distro)) {
        Write-Err2 "distro '$distro' is still registered"
        exit 1
    }
}
if ($distro -and $distroDir -and (Test-Path $distroDir)) {
    Write-Warn2 "virtual disk still present: $distroDir"
}

Write-Host ''
Write-Host '----------------------------------------------------------------' -ForegroundColor Green
Write-Host ' Uninstall finished.' -ForegroundColor Green
if (Test-Path $APP_DATA) {
    Write-Host " Kept: $APP_DATA"
    Write-Host '       (config.yaml, logs, credential backups)'
}
Write-Host ' Re-deploy with: .\scripts\deploy.bat'
Write-Host '----------------------------------------------------------------' -ForegroundColor Green

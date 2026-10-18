<#
.SYNOPSIS
    One-shot deployment: from a bare Windows machine to a working environment.

.DESCRIPTION
    Creates the WSL2 base distro, provisions the wrapper + downloader inside it,
    and verifies the result.

    Debian is obtained ONLY from official Microsoft / Debian channels - never
    from Docker. Three acquisition paths are tried in order:

      1. WebDownload  wsl --install -d Debian --no-launch --web-download
                      (WSL downloads the official image itself)
      2. Store        wsl --install -d Debian --no-launch
                      (Microsoft Store path)
      3. FromFile     read the official distribution manifest published at
                      microsoft/WSL, download Debian's .wsl image from the URL
                      it lists (salsa.debian.org), verify its SHA256, then
                      wsl --install --from-file <path> --name <Name>

    Path 3 also lets the distro be created with the exact name the app expects.

.PARAMETER Name
    Distro name to create. Default: Debian13-wrapper

.PARAMETER Method
    Auto (default) | WebDownload | Store | FromFile

.PARAMETER SkipProvision
    Only create the base distro; skip installing the app components.

.PARAMETER SkipWslConfig
    Do not touch %USERPROFILE%\.wslconfig.

.PARAMETER CreateStartupShortcut
    Add a Startup-folder shortcut that boots WSL at logon.

.PARAMETER KeepDownload
    Keep the downloaded .wsl image instead of deleting it.

.EXAMPLE
    .\scripts\deploy.ps1

.EXAMPLE
    .\scripts\deploy.ps1 -Method FromFile -CreateStartupShortcut

.NOTES
    Requires: Windows 10 2004+ / Windows 11, virtualization enabled.
    First run may require a reboot if WSL itself is not installed yet.
#>
[CmdletBinding()]
param(
    [string]$Name = 'Debian13-wrapper',

    [ValidateSet('Auto', 'WebDownload', 'Store', 'FromFile')]
    [string]$Method = 'Auto',

    [switch]$SkipProvision,
    [switch]$SkipWslConfig,
    [switch]$CreateStartupShortcut,
    [switch]$KeepDownload,

    # HTTP(S) proxy used for the image download, e.g. http://127.0.0.1:7890
    [string]$Proxy = '',

    # Where to keep the distro's virtual disk. Default: %LOCALAPPDATA%\WSL\<Name>.
    # Point this at a roomier drive, e.g. D:\WSL. Leave empty to be asked
    # interactively (or to get the default when -NonInteractive is used).
    [string]$Location = '',

    # Never prompt; take the defaults.
    [switch]$NonInteractive,

    # Override the image used by -Method FromFile (SHA256 is then skipped
    # unless -ImageSha256 is also given).
    [string]$ImageUrl = '',
    [string]$ImageSha256 = '',

    # Install from a local .wsl / .appx / rootfs tar instead of downloading.
    [string]$ImagePath = ''
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# wsl.exe emits UTF-16LE unless this is set; without it every captured string
# is interleaved with NUL bytes and every comparison fails.
$env:WSL_UTF8 = '1'
# ...and with WSL_UTF8=1 it speaks UTF-8, while a Chinese Windows console
# decodes child output with codepage 936 (GBK). That turns "无法从" into
# "鏃犳硶浠?". Force UTF-8 for decoding here; deploy.bat also runs chcp 65001 so
# the console renders it correctly.
try {
    if ([Console]::OutputEncoding.CodePage -ne 65001) {
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    }
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # Very old hosts: leave the defaults, the messages are cosmetic.
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$manifestUrl = 'https://raw.githubusercontent.com/microsoft/WSL/master/distributions/DistributionInfo.json'

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
function Write-Step { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn2{ param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "[ERROR] $m" -ForegroundColor Red }

function Get-Distros {
    param([string[]]$Raw)
    if (-not $Raw) { $Raw = (wsl -l -q 2>$null) }
    return @($Raw | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
}

$script:WslAvailable = $false

function Invoke-WslRaw {
    param([string[]]$Arguments)
    $out = & wsl.exe @Arguments 2>&1
    return @{ Code = $LASTEXITCODE; Output = ($out | Out-String).Trim() }
}

# ---------------------------------------------------------------------------
# 1. Preflight
# ---------------------------------------------------------------------------
Write-Step 'Preflight'
Write-Host ("    Windows {0} ({1})" -f [Environment]::OSVersion.Version,
            (Get-CimInstance Win32_OperatingSystem).Caption)

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Write-Warn2 'wsl.exe not found - WSL is not installed.'
    Write-Host '    Installing WSL (a reboot may be required)...'
    $r = Invoke-WslRaw @('--install', '--no-distribution')
    Write-Host "    $($r.Output)"
    if ($r.Code -ne 0) {
        Write-Err 'Could not install WSL automatically. Run this in an elevated shell:'
        Write-Host '    wsl --install'
        Write-Host '    ...then reboot and re-run this script.'
        exit 1
    }
    Write-Warn2 'WSL was installed. Reboot, then run this script again.'
    exit 0
}
$script:WslAvailable = $true

$ver = (Invoke-WslRaw @('--version')).Output -split "`n" | Select-Object -First 1
Write-Ok ("wsl.exe present - {0}" -f $ver.Trim())

$distros = Get-Distros
if ($distros -contains $Name) {
    Write-Ok "distro '$Name' already exists"
    $needAcquire = $false
} else {
    $needAcquire = $true
}

# ---------------------------------------------------------------------------
# 2. Acquire the distro from an official source
# ---------------------------------------------------------------------------
function New-Distro([string]$How) {
    switch ($How) {
        'WebDownload' {
            Write-Host '    wsl --install -d Debian --no-launch --web-download'
            $r = Invoke-WslRaw @('--install', '-d', 'Debian', '--no-launch', '--web-download')
            if ($r.Output) { Write-Host "    $($r.Output)" }
            return ($r.Code -eq 0)
        }
        'Store' {
            Write-Host '    wsl --install -d Debian --no-launch'
            $r = Invoke-WslRaw @('--install', '-d', 'Debian', '--no-launch')
            if ($r.Output) { Write-Host "    $($r.Output)" }
            return ($r.Code -eq 0)
        }
        'FromFile' {
            return (Install-FromOfficialImage)
        }
    }
    return $false
}

function Test-RangeSupport {
    param([string]$Url)
    try {
        $req = [System.Net.HttpWebRequest]::Create($Url)
        $req.AddRange(0, 1023)
        $req.Timeout = 15000
        $resp = $req.GetResponse()
        $ok = ($resp.StatusCode -eq [System.Net.HttpStatusCode]::PartialContent)
        $resp.Close()
        return $ok
    } catch {
        return $false
    }
}

function Measure-Rate {
    <#
        Quick throughput probe: pull bytes for a few seconds and report MB/s.
        Used to choose between official mirrors instead of blindly trying them.
    #>
    param([string]$Url, [int]$Seconds = 4)

    $tmp = Join-Path $env:TEMP ('probe_' + [guid]::NewGuid().ToString('N') + '.bin')
    try {
        $args = @('-L', '--max-time', $Seconds, '-sS', '-o', $tmp)
        if ($Proxy) { $args = @('--proxy', $Proxy) + $args }
        $args += $Url
        $p = Start-Process -FilePath 'curl.exe' -ArgumentList $args -NoNewWindow -PassThru `
                           -RedirectStandardError "$tmp.err" -RedirectStandardOutput "$tmp.out"
        $p.WaitForExit(($Seconds + 8) * 1000) | Out-Null
        if (-not $p.HasExited) { $p.Kill() }
        if (Test-Path $tmp) {
            $mb = (Get-Item $tmp).Length / 1MB
            return [math]::Round($mb / $Seconds, 3)
        }
        return 0
    } catch {
        return 0
    } finally {
        Remove-Item $tmp, "$tmp.err", "$tmp.out" -Force -ErrorAction SilentlyContinue
    }
}

function Format-Eta {
    param([double]$Megabytes, [double]$Rate)
    if ($Rate -le 0) { return 'unknown' }
    $minutes = $Megabytes / $Rate / 60
    if ($minutes -lt 1) { return '<1 min' }
    if ($minutes -lt 90) { return ('{0:N0} min' -f $minutes) }
    return ('{0:N1} h' -f ($minutes / 60))
}

function Invoke-Download {
    <#
        Download a large file with progress. Resumes when the server supports
        byte ranges (salsa does, Azure blob storage does not).
    #>
    param([string]$Url, [string]$OutFile, [switch]$Resume)

    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        if (-not $Resume -and (Test-Path $OutFile)) {
            Remove-Item $OutFile -Force -ErrorAction SilentlyContinue
        }
        $curlArgs = @('-L', '--fail', '--retry', '10', '--retry-delay', '3',
                      '--retry-all-errors', '--retry-connrefused', '-o', $OutFile)
        if ($Resume) { $curlArgs += @('--continue-at', '-') }
        if ($Proxy) { $curlArgs = @('--proxy', $Proxy) + $curlArgs }
        $curlArgs += $Url

        Write-Host ('    curl -L --retry 5{0} (progress below)' -f $(if ($Resume) { ' --continue-at -' } else { '' })) -ForegroundColor DarkGray
        & curl.exe @curlArgs
        return ($LASTEXITCODE -eq 0)
    }

    Write-Host '    curl.exe not available - falling back to Invoke-WebRequest' -ForegroundColor DarkGray
    $prevH = $env:HTTPS_PROXY; $prevX = $env:HTTP_PROXY
    if ($Proxy) { $env:HTTPS_PROXY = $Proxy; $env:HTTP_PROXY = $Proxy }
    try {
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -TimeoutSec 7200
        return $true
    } catch {
        Write-Err "download failed: $($_.Exception.Message)"
        return $false
    } finally {
        if ($Proxy) { $env:HTTPS_PROXY = $prevH; $env:HTTP_PROXY = $prevX }
    }
}

function Test-RealArchive {
    <# Rejects HTML challenge pages / error bodies served instead of an image. #>
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $false }
    $len = (Get-Item $Path).Length
    if ($len -lt 1MB) {
        $head = ''
        try {
            $bytes = [System.IO.File]::ReadAllBytes($Path)
            $head = [System.Text.Encoding]::UTF8.GetString($bytes[0..([Math]::Min(200, $bytes.Length - 1))])
        } catch { }
        if ($head -match '<!DOCTYPE|<html|I Challenge Thee') {
            Write-Err "the server returned an HTML page instead of the image ($len bytes)."
            Write-Host '    This URL is behind a proof-of-work challenge; the script cannot fetch it.'
            return $false
        }
    }
    return $true
}

function Expand-AppxRootfs {
    <# Extracts install.tar.gz from an .AppxBundle / .appx produced by Microsoft. #>
    param([string]$BundlePath, [string]$WorkDir)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $rootfsPattern = '^(install\.tar\.gz|install\.tar|rootfs\.tar(\.gz)?)$'

    function Find-In($zipPath, $depth) {
        if ($depth -gt 2) { return $null }
        $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
        try {
            $direct = $zip.Entries | Where-Object { $_.Name -match $rootfsPattern } |
                      Select-Object -First 1
            if ($direct) {
                $out = Join-Path $WorkDir $direct.Name
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($direct, $out, $true)
                return $out
            }
            # AppxBundle wraps per-architecture .appx packages - recurse into them.
            $inner = $zip.Entries |
                     Where-Object { $_.Name -match '\.(appx|msix)$' -and $_.Name -notmatch 'arm|arm64' } |
                     Select-Object -First 1
            if (-not $inner) {
                $inner = $zip.Entries | Where-Object { $_.Name -match '\.(appx|msix)$' } |
                         Select-Object -First 1
            }
            if ($inner) {
                $tmp = Join-Path $WorkDir $inner.Name
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($inner, $tmp, $true)
                return (Find-In $tmp ($depth + 1))
            }
            return $null
        } finally {
            $zip.Dispose()
        }
    }

    New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
    return (Find-In $BundlePath 0)
}

function Get-ManifestJson {
    <#
        Fetch the official distribution manifest, preferring curl (its TLS stack
        survives this kind of link far better than Invoke-RestMethod) and
        retrying - raw.githubusercontent.com is intermittently reachable.
    #>
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $tmp = Join-Path $env:TEMP "wsl-manifest-$attempt.json"
        try {
            if ($curl) {
                $args = @('-L', '--fail', '--max-time', '40', '-sS', '-o', $tmp)
                if ($Proxy) { $args = @('--proxy', $Proxy) + $args }
                & curl.exe @args $manifestUrl | Out-Null
                if ($LASTEXITCODE -eq 0 -and (Test-Path $tmp) -and (Get-Item $tmp).Length -gt 1000) {
                    $json = Get-Content $tmp -Raw | ConvertFrom-Json
                    return $json
                }
            } else {
                return (Invoke-RestMethod -Uri $manifestUrl -TimeoutSec 40)
            }
        } catch {
            # fall through to the retry
        } finally {
            Remove-Item $tmp -Force -ErrorAction SilentlyContinue
        }
        if ($attempt -lt 3) {
            Write-Host ("    manifest fetch failed (attempt {0}/3), retrying..." -f $attempt) -ForegroundColor DarkYellow
            Start-Sleep -Seconds 2
        }
    }
    return $null
}

function Get-AcquisitionSources {
    <#
        The two official, script-fetchable sources for the Debian image.

        Preferred: resolve them from the official Microsoft distribution
        manifest. If that host is unreachable, fall back to the URLs recorded
        from it, so a flaky raw.githubusercontent.com cannot block deployment.

          * the Debian WSL image, via salsa.debian.org's artifact endpoint
            (the manifest's /artifacts/raw/ URL sits behind a proof-of-work
            challenge; the sibling /artifacts/download endpoint does not)
          * the Microsoft-hosted .AppxBundle
    #>
    $sources = @()
    $manifest = Get-ManifestJson

    if ($manifest) {
        $modern = $manifest.ModernDistributions.Debian | Where-Object { $_.Name -eq 'Debian' } |
                  Select-Object -First 1
        if ($modern -and $modern.Amd64Url -and $modern.Amd64Url.Url -match '^(https://.+?/-/jobs/\d+)/artifacts/') {
            $sources += [pscustomobject]@{
                Name     = 'Debian official WSL image (salsa.debian.org)'
                Url      = "$($Matches[1])/artifacts/download"
                Kind     = 'zip'
                ApproxMB = 177
                Resume   = $true
            }
        }

        $legacy = $manifest.Distributions | Where-Object { $_.Name -eq 'Debian' } |
                  Select-Object -First 1
        if ($legacy -and $legacy.Amd64PackageUrl) {
            $sources += [pscustomobject]@{
                Name     = 'Debian package from Microsoft blob storage (.AppxBundle)'
                Url      = $legacy.Amd64PackageUrl
                Kind     = 'appx'
                ApproxMB = 175
                Resume   = $false
            }
        }
    }

    if (-not $sources) {
        Write-Warn2 'official manifest unreachable - using the URLs recorded from it'
        $sources += [pscustomobject]@{
            Name     = 'Debian official WSL image (salsa.debian.org) [cached URL]'
            Url      = 'https://salsa.debian.org/debian/WSL/-/jobs/9606244/artifacts/download'
            Kind     = 'zip'
            ApproxMB = 177
            Resume   = $true
        }
        $sources += [pscustomobject]@{
            Name     = 'Debian package from Microsoft blob storage (.AppxBundle) [cached URL]'
            Url      = 'https://publicwsldistros.blob.core.windows.net/wsldistrostorage/TheDebianProject.DebianGNULinux_1.12.2.0_neutral___76v4gfsz19hv4.AppxBundle'
            Kind     = 'appx'
            ApproxMB = 175
            Resume   = $false
        }
    }

    return $sources
}

function Test-IsZip {
    param([string]$Path)
    try {
        $fs = [System.IO.File]::OpenRead($Path)
        try {
            $b = New-Object byte[] 4
            $n = $fs.Read($b, 0, 4)
            return ($n -eq 4 -and $b[0] -eq 0x50 -and $b[1] -eq 0x4B -and $b[2] -eq 0x03 -and $b[3] -eq 0x04)
        } finally { $fs.Close() }
    } catch { return $false }
}

function Install-WslImageFromArchive {
    <# Extracts a .wsl (or rootfs tar) from a downloaded archive and installs it. #>
    param([string]$Archive, [string]$Kind)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $work = Join-Path $env:TEMP 'deploy-img'
    Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $work | Out-Null

    if ($Kind -eq 'appx') {
        $rootfs = Expand-AppxRootfs -BundlePath $Archive -WorkDir $work
        if (-not $rootfs) { Write-Err 'no rootfs found inside the bundle.'; return $false }
        Write-Ok ("rootfs extracted ({0:N0} MB)" -f ((Get-Item $rootfs).Length / 1MB))
        return (Import-Rootfs -Path $rootfs)
    }

    # Kind 'zip': the salsa artifact bundle, which ships BOTH the amd64 and the
    # arm64 image. Pick by name - the two differ by ~0.1 MB, so size alone is
    # not a safe discriminator.
    if (-not (Test-IsZip $Archive)) {
        # A bare .wsl (or tar) rather than a container archive.
        Write-Host "    wsl --install --from-file <image> --name $Name --no-launch"
        $ffArgs = @('--install', '--from-file', $Archive, '--name', $Name, '--no-launch')
        if ($Location) { $ffArgs += @('--location', (Join-Path $Location $Name)) }
        $r0 = Invoke-WslRaw $ffArgs
        if ($r0.Output) { Write-Host "    $($r0.Output)" }
        return ($r0.Code -eq 0)
    }

    $zip = [System.IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        $entries = $zip.Entries | Sort-Object Length -Descending
        $wslAll = @($entries | Where-Object { $_.Name -match '\.wsl$' })
        $wslEntry = $wslAll |
                    Where-Object { $_.Name -match '(?i)amd64|x64' -and $_.Name -notmatch '(?i)arm' } |
                    Select-Object -First 1
        if (-not $wslEntry -and $wslAll.Count -eq 1) { $wslEntry = $wslAll[0] }
        if ($wslEntry) {
            $target = Join-Path $work $wslEntry.Name
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($wslEntry, $target, $true)
            Write-Ok ("extracted {0} ({1:N0} MB)" -f $wslEntry.Name, ($wslEntry.Length / 1MB))
            # --no-launch is essential: without it WSL starts the distro and its
            # first-boot setup waits for a UNIX username/password on stdin,
            # which hangs forever in a script.
            Write-Host "    wsl --install --from-file <image> --name $Name --no-launch"
            $ffArgs = @('--install', '--from-file', $target, '--name', $Name, '--no-launch')
            if ($Location) { $ffArgs += @('--location', (Join-Path $Location $Name)) }
            $r = Invoke-WslRaw $ffArgs
            if ($r.Output) { Write-Host "    $($r.Output)" }
            return ($r.Code -eq 0)
        }
        $rootfsEntry = $entries |
            Where-Object { $_.Name -match '^(install\.tar(\.gz)?|rootfs\.tar(\.gz)?)$' } |
            Select-Object -First 1
        if ($rootfsEntry) {
            $target = Join-Path $work $rootfsEntry.Name
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($rootfsEntry, $target, $true)
            Write-Ok ("extracted {0} ({1:N0} MB)" -f $rootfsEntry.Name, ($rootfsEntry.Length / 1MB))
            return (Import-Rootfs -Path $target)
        }
        Write-Err 'the archive contains neither a .wsl image nor a rootfs tarball.'
        Write-Host '    contents:'
        $entries | Select-Object -First 10 | ForEach-Object { Write-Host "      $($_.FullName) ($([math]::Round($_.Length/1MB,1)) MB)" }
        return $false
    } finally {
        $zip.Dispose()
    }
}

function Get-InstallDir {
    <# Where the distro's ext4.vhdx will live. #>
    if ($Location) { return (Join-Path $Location $Name) }
    return (Join-Path $env:LOCALAPPDATA "WSL\$Name")
}

function Select-InstallLocation {
    <#
        Ask which drive should hold the distro's virtual disk.

        Worth asking: the vhdx only ever grows (deleting files inside the distro
        does not shrink it), and on a nearly full system drive that matters.
    #>
    $defaultBase = Join-Path $env:LOCALAPPDATA 'WSL'

    if ($NonInteractive -or -not [Environment]::UserInteractive) {
        return $defaultBase
    }

    $drives = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' -ErrorAction SilentlyContinue |
                Where-Object { $_.Size -gt 0 })
    if ($drives.Count -le 1) { return $defaultBase }
    $drives = @($drives | Sort-Object DeviceID)

    $best = $drives | Sort-Object -Property FreeSpace -Descending | Select-Object -First 1
    $bestIndex = 0
    for ($i = 0; $i -lt $drives.Count; $i++) {
        if ($drives[$i].DeviceID -eq $best.DeviceID) { $bestIndex = $i }
    }

    Write-Host ''
    Write-Host '  The distro disk only grows, so pick a drive with room to spare.' -ForegroundColor Cyan
    for ($i = 0; $i -lt $drives.Count; $i++) {
        $d = $drives[$i]
        $tag = ''
        if ($i -eq $bestIndex) { $tag = '  <- most free' }
        if ($d.DeviceID -eq 'C:') { $tag += '  (system drive)' }
        Write-Host ("    [{0}] {1}  {2,7:N1} GB free of {3,7:N1} GB{4}" -f `
                    ($i + 1), $d.DeviceID, ($d.FreeSpace / 1GB), ($d.Size / 1GB), $tag)
    }
    Write-Host ''
    Write-Host ("  Store WSL data on which drive? [1-{0}, Enter for {1}, or type a full path]: " -f `
                $drives.Count, ($bestIndex + 1)) -NoNewline -ForegroundColor Yellow
    $answer = Read-Host

    if (-not $answer) { $answer = [string]($bestIndex + 1) }

    $picked = 0
    if ([int]::TryParse($answer, [ref]$picked) -and $picked -ge 1 -and $picked -le $drives.Count) {
        $base = Join-Path ($drives[$picked - 1].DeviceID + '\') 'WSL'
    } else {
        $base = $answer.Trim().Trim('"')
    }

    try {
        $root = [System.IO.Path]::GetPathRoot($base)
        $info = New-Object System.IO.DriveInfo($root)
        if ($info.AvailableFreeSpace -lt 6GB) {
            Write-Warn2 ("only {0:N1} GB free on {1} - about 3-5 GB is needed" -f `
                         ($info.AvailableFreeSpace / 1GB), $root)
        }
    } catch {
        Write-Warn2 "could not check free space for '$base'"
    }

    New-Item -ItemType Directory -Force -Path $base | Out-Null
    Write-Ok "WSL data will be stored in $base"
    return $base
}

function Import-Rootfs {
    param([string]$Path)
    $installDir = Get-InstallDir
    New-Item -ItemType Directory -Force -Path $installDir | Out-Null
    Write-Host "    wsl --import $Name $installDir <rootfs> --version 2"
    $r = Invoke-WslRaw @('--import', $Name, $installDir, $Path, '--version', '2')
    if ($r.Output) { Write-Host "    $($r.Output)" }
    return ($r.Code -eq 0)
}

function Install-FromOfficialImage {
    <#
        Probe every official source, then download from the fastest one.

        Probing matters: on a congested international link the two sources differ
        by an order of magnitude, and which one is faster varies per network.
    #>
    if ($ImagePath) {
        if (-not (Test-Path $ImagePath)) {
            Write-Err "image not found: $ImagePath"
            return $false
        }
        $full = (Resolve-Path $ImagePath).Path
        Write-Host "    installing the image you supplied: $full"
        Write-Ok ("{0:N0} MB" -f ((Get-Item $full).Length / 1MB))
        if ($full -match '\.(tar|tar\.gz|tar\.xz)$') { return (Import-Rootfs -Path $full) }
        $kind = if ($full -match '\.(appx|appxbundle)$') { 'appx' } else { 'zip' }
        return (Install-WslImageFromArchive -Archive $full -Kind $kind)
    }

    if ($ImageUrl) {
        $target = Join-Path $env:TEMP (Split-Path ($ImageUrl -split '\?')[0] -Leaf)
        Write-Host "    using the image you supplied: $ImageUrl"
        if (-not (Invoke-Download -Url $ImageUrl -OutFile $target -Resume:(Test-RangeSupport $ImageUrl))) {
            Write-Err 'download failed.'
            return $false
        }
        $kind = if ($ImageUrl -match '\.(appx|appxbundle)$') { 'appx' } else { 'zip' }
        if ($ImageUrl -match '\.(tar|tar\.gz|tar\.xz)$') { return (Import-Rootfs -Path $target) }
        return (Install-WslImageFromArchive -Archive $target -Kind $kind)
    }

    Write-Host '    resolving official sources...'
    $sources = Get-AcquisitionSources
    if (-not $sources) {
        Write-Err 'no official source could be resolved.'
        return $false
    }

    Write-Host '    measuring throughput of each official source:'
    $best = $null
    foreach ($s in $sources) {
        $rate = Measure-Rate -Url $s.Url -Seconds 4
        $eta = Format-Eta -Megabytes $s.ApproxMB -Rate $rate
        $tag = if ($rate -gt 0) { '{0:N2} MB/s, ~{1}' -f $rate, $eta } else { 'unreachable' }
        Write-Host ("      {0,-55} {1}" -f $s.Name, $tag)
        $s | Add-Member -NotePropertyName Rate -NotePropertyValue $rate -Force
        if ($rate -gt 0 -and (-not $best -or $rate -gt $best.Rate)) { $best = $s }
    }

    if (-not $best) {
        Write-Err 'every official source is unreachable from this network.'
        return $false
    }

    Write-Host ''
    Write-Ok ("using {0}" -f $best.Name)
    Write-Host ("    size ~{0} MB at {1:N2} MB/s -> about {2}" -f `
                $best.ApproxMB, $best.Rate, (Format-Eta -Megabytes $best.ApproxMB -Rate $best.Rate))
    if ($best.Rate -lt 0.5) {
        Write-Warn2 'this is slow - the download will take a while. It is resumable, so you can Ctrl+C and re-run.'
    }

    $file = Join-Path $env:TEMP (Split-Path ($best.Url -split '\?')[0] -Leaf)
    if ($best.Kind -eq 'zip') { $file = Join-Path $env:TEMP 'debian-wsl-artifacts.zip' }
    if ($best.Kind -eq 'appx') { $file = Join-Path $env:TEMP 'debian-wsl.appxbundle' }

    $alreadyComplete = $false
    if ((Test-Path $file) -and (Get-Item $file).Length -gt 5MB) {
        $have = (Get-Item $file).Length

        # Trust the local file first: a complete archive can be verified without
        # any network round-trip. This matters because a HEAD request to these
        # mirrors often fails, and a "resume" past EOF errors out (curl 33).
        if ($best.Kind -ne 'appx' -and (Test-IsZip $file)) {
            try {
                Add-Type -AssemblyName System.IO.Compression.FileSystem
                $z = [System.IO.Compression.ZipFile]::OpenRead($file)
                $hasImage = @($z.Entries | Where-Object { $_.Name -match '\.wsl$' }).Count -gt 0
                $z.Dispose()
                if ($hasImage) {
                    Write-Ok ("already downloaded and verified locally ({0:N0} MB) - skipping the transfer" -f ($have / 1MB))
                    $alreadyComplete = $true
                }
            } catch {
                # corrupt/partial zip: fall through to a real download
            }
        }

        if (-not $alreadyComplete) {
            $expected = 0
            try {
                $head = [System.Net.HttpWebRequest]::Create($best.Url)
                $head.Method = 'HEAD'
                $head.Timeout = 20000
                $resp = $head.GetResponse()
                $expected = $resp.ContentLength
                $resp.Close()
            } catch { }
            if ($expected -gt 0 -and $have -ge $expected) {
                Write-Ok ("already downloaded ({0:N0} MB) - skipping the transfer" -f ($have / 1MB))
                $alreadyComplete = $true
            } else {
                Write-Ok ("resuming from the {0:N0} MB already downloaded" -f ($have / 1MB))
            }
        }
    }

    if (-not $alreadyComplete) {
        if (-not (Invoke-Download -Url $best.Url -OutFile $file -Resume:$best.Resume)) {
            Write-Err 'image download failed.'
            if (-not $Proxy) {
                Write-Host '    If Microsoft / Debian endpoints are slow or blocked here, either'
                Write-Host '    re-run with a proxy:'
                Write-Host '      deploy.ps1 -Proxy http://127.0.0.1:7890'
                Write-Host '    or download the image in a browser and import it locally:'
                Write-Host "      deploy.ps1 -ImagePath 'C:\path\to\Debian_WSL_AMD64.wsl'"
            }
            return $false
        }
        Write-Ok ("downloaded {0:N0} MB" -f ((Get-Item $file).Length / 1MB))
    }

    if (-not (Test-RealArchive $file)) {
        Remove-Item $file -Force -ErrorAction SilentlyContinue
        return $false
    }

    $ok = Install-WslImageFromArchive -Archive $file -Kind $best.Kind

    if ($ok -and -not $KeepDownload) {
        Remove-Item $file -Force -ErrorAction SilentlyContinue
        Write-Ok 'removed the downloaded image'
    }
    return $ok
}

if ($needAcquire) {
    Write-Step "Creating the base distro '$Name' from an official source"

    # Ask where to put it unless -Location was passed in.
    if (-not $Location) {
        Write-Step 'Choosing where to store the distro disk'
        $Location = Select-InstallLocation
    } else {
        New-Item -ItemType Directory -Force -Path $Location | Out-Null
        Write-Ok "WSL data will be stored in $Location"
    }

    $order = if ($Method -eq 'Auto') { @('WebDownload', 'Store', 'FromFile') } else { @($Method) }
    $created = $false

    foreach ($how in $order) {
        Write-Host "`n  -- trying $how --" -ForegroundColor Yellow
        Push-Location
        try { $ok = New-Distro $how } finally { Pop-Location }

        $distros = Get-Distros
        $match = $null
        if ($distros -contains $Name) { $match = $Name }
        elseif ($distros -contains 'Debian') { $match = 'Debian' }
        elseif ($distros | Where-Object { $_ -match '^Debian' }) {
            $match = $distros | Where-Object { $_ -match '^Debian' } | Select-Object -First 1
        }

        if ($ok -and $match) {
            Write-Ok "$how produced distro '$match'"
            if ($match -ne $Name) {
                Write-Warn2 "distro is named '$match' (this WSL build has no --rename)."
                Write-Host "    The app auto-discovers the distro name, so this is fine."
                $Name = $match
            }
            $created = $true
            break
        }
        Write-Warn2 "$how did not produce a usable distro"
    }

    if (-not $created) {
        Write-Err 'all acquisition methods failed.'
        Write-Host @'
    Things to check:
      - Network access to Microsoft / Debian (a proxy or firewall may block it)
      - Virtualization enabled in BIOS (Task Manager -> Performance -> Virtualization)
      - Run "wsl --update" and try again
    You can also build the distro by hand and re-run with -SkipProvision:
      wsl --install -d Debian --no-launch
'@
        exit 1
    }
} else {
    Write-Ok "reusing the existing distro '$Name'"
}

# ---------------------------------------------------------------------------
# 3. Base configuration inside the distro
# ---------------------------------------------------------------------------
Write-Step 'Configuring the distro (systemd, root user)'
$wslConf = "[boot]`nsystemd=true`n`n[user]`ndefault=root`n"
$tmpConf = Join-Path $env:TEMP 'deploy-wsl.conf'
[System.IO.File]::WriteAllText($tmpConf, $wslConf, (New-Object System.Text.UTF8Encoding($false)))
$tmpSlash = ($tmpConf -replace '\\', '/')
$tDrive = ($tmpSlash -split ':', 2)[0].ToLower()
$tRest = ($tmpSlash -split ':', 2)[1]
Invoke-WslRaw @('-d', $Name, '--', 'cp', "/mnt/$tDrive$tRest", '/etc/wsl.conf') | Out-Null
Remove-Item $tmpConf -Force -ErrorAction SilentlyContinue
Write-Ok 'wsl.conf written'

Write-Step 'Restarting the distro so systemd becomes PID 1'
Invoke-WslRaw @('--terminate', $Name) | Out-Null
Start-Sleep -Seconds 3
$pid1 = (Invoke-WslRaw @('-d', $Name, '--', 'ps', '-p', '1', '-o', 'comm=')).Output.Trim()
if ($pid1 -match 'systemd') { Write-Ok 'PID 1 is systemd' }
else { Write-Warn2 "PID 1 is '$pid1' - systemd may need another restart" }

# ---------------------------------------------------------------------------
# 4. Windows-side WSL settings
# ---------------------------------------------------------------------------
if (-not $SkipWslConfig) {
    Write-Step 'Windows WSL settings (%USERPROFILE%\.wslconfig)'
    $cfg = Join-Path $env:USERPROFILE '.wslconfig'
    $desired = [ordered]@{
        networkingMode = 'mirrored'
        vmIdleTimeout  = '-1'
        dnsTunneling   = 'true'
        autoProxy      = 'true'
    }
    # Keep the swap file off a nearly-full system drive when a location was given.
    if ($Location) {
        $desired['swapFile'] = (Join-Path $Location 'swap.vhdx')
    }

    if (Test-Path $cfg) {
        if (-not (Test-Path "$cfg.bak")) { Copy-Item $cfg "$cfg.bak" }
    }

    # Parse into sections so keys land under [wsl2] even when the user's file
    # already has other sections after it. A naive append put them in the wrong
    # section, and blindly prepending "[wsl2]" produced a duplicate header.
    $preamble = [System.Collections.Generic.List[string]]::new()
    $sections = [System.Collections.Generic.List[object]]::new()
    $current = $null
    if (Test-Path $cfg) {
        foreach ($raw in Get-Content $cfg) {
            if ($raw -match '^\s*\[(.+)\]\s*$') {
                $current = [pscustomobject]@{
                    Name  = $matches[1].Trim().ToLower()
                    Lines = [System.Collections.Generic.List[string]]::new()
                }
                $current.Lines.Add($raw)
                $sections.Add($current)
            } elseif ($null -eq $current) {
                $preamble.Add($raw)
            } else {
                $current.Lines.Add($raw)
            }
        }
    }

    # Merge duplicate [wsl2] sections into the first one.
    $wsl2Sections = @($sections | Where-Object { $_.Name -eq 'wsl2' })
    $wsl2 = if ($wsl2Sections.Count) { $wsl2Sections[0] } else { $null }
    if ($wsl2Sections.Count -gt 1) {
        foreach ($dup in ($wsl2Sections | Select-Object -Skip 1)) {
            foreach ($l in $dup.Lines) {
                if ($l -notmatch '^\s*\[.+\]\s*$') { $wsl2.Lines.Add($l) }
            }
            [void]$sections.Remove($dup)
        }
    }
    if (-not $wsl2) {
        $wsl2 = [pscustomobject]@{
            Name  = 'wsl2'
            Lines = [System.Collections.Generic.List[string]]::new()
        }
        $wsl2.Lines.Add('[wsl2]')
        $sections.Add($wsl2)
    }

    $have = @{}
    foreach ($l in $wsl2.Lines) {
        if ($l -match '^\s*([A-Za-z0-9]+)\s*=') { $have[$matches[1].ToLower()] = $true }
    }
    foreach ($k in $desired.Keys) {
        if (-not $have.ContainsKey($k.ToLower())) { $wsl2.Lines.Add("$k=$($desired[$k])") }
    }

    $out = @($preamble)
    foreach ($s in $sections) { $out += $s.Lines }
    [System.IO.File]::WriteAllLines($cfg, $out, (New-Object System.Text.UTF8Encoding($false)))
    Get-Content $cfg | ForEach-Object { Write-Host "    $_" }
    Write-Ok 'wslconfig updated (run "wsl --shutdown" later for it to take effect)'
}

# ---------------------------------------------------------------------------
# 5. Provision the app components
# ---------------------------------------------------------------------------
if ($SkipProvision) {
    Write-Warn2 'skipping provisioning (-SkipProvision)'
} else {
    Write-Step 'Installing the wrapper and downloader inside the distro'
    $repoSlash = ($repoRoot -replace '\\', '/')
    $rDrive = ($repoSlash -split ':', 2)[0].ToLower()
    $rRest = ($repoSlash -split ':', 2)[1]
    $provision = "/mnt/$rDrive$rRest/scripts/provision-distro.sh"

    $exists = (Invoke-WslRaw @('-d', $Name, '--', 'test', '-f', $provision)).Code -eq 0
    if (-not $exists) {
        Write-Err "provision script not reachable inside WSL: $provision"
        Write-Host "    Is the repository on a drive that WSL mounts? ($repoRoot)"
        exit 1
    }

    & wsl.exe -d $Name -- bash $provision
    if ($LASTEXITCODE -ne 0) {
        Write-Err "provisioning failed (exit $LASTEXITCODE)"
        exit 1
    }
    Write-Ok 'provisioning finished'
}

# ---------------------------------------------------------------------------
# 6. Optional logon shortcut
# ---------------------------------------------------------------------------
if ($CreateStartupShortcut) {
    Write-Step 'Adding a Startup shortcut (boots WSL at logon)'
    $startup = [Environment]::GetFolderPath('Startup')
    $lnk = Join-Path $startup 'AppleMusicWrapper.lnk'
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($lnk)
    $sc.TargetPath = "$env:SystemRoot\System32\wsl.exe"
    $sc.Arguments = "-d $Name --exec /bin/true"
    $sc.WorkingDirectory = "$env:SystemRoot\System32"
    $sc.WindowStyle = 7
    $sc.Description = 'Boot the WSL distro that hosts the Apple Music wrapper.'
    $sc.Save()
    Write-Ok "shortcut created: $lnk"
}

# ---------------------------------------------------------------------------
# 7. Verify
# ---------------------------------------------------------------------------
Write-Step 'Verifying'
$loggedIn = (Invoke-WslRaw @('-d', $Name, '--', 'test', '-s',
    '/opt/wrapper/rootfs/data/data/com.apple.android.music/files/MUSIC_TOKEN')).Code -eq 0

$state = (Invoke-WslRaw @('-d', $Name, '--', 'systemctl', 'is-active', 'apple-music-wrapper')).Output.Trim()
Write-Host "    service     : $state"

$reachable = $false
if (-not $loggedIn) {
    # A fresh distro has no cached Apple credentials, so the wrapper cannot
    # obtain a token and keeps restarting. That is the expected state until the
    # user signs in - do not present it as a failure.
    Write-Ok 'wrapper installed; it is waiting for an Apple Music login (expected on first run)'
} else {
    foreach ($i in 1..12) {
        $probe = (Invoke-WslRaw @('-d', $Name, '--', 'curl', '-sf', '--max-time', '3',
                                  'http://127.0.0.1:30020/')).Code -eq 0
        if ($probe) { $reachable = $true; break }
        Start-Sleep -Seconds 5
    }
    if ($reachable) { Write-Ok 'wrapper account service is answering on 30020' }
    else { Write-Warn2 'wrapper is not answering yet - it may still be initialising (FairPlay init takes 30-60s)' }
}

$downloader = (Invoke-WslRaw @('-d', $Name, '--', 'test', '-x', '/opt/amdl-legacy/amdl')).Code -eq 0
if ($downloader) { Write-Ok 'downloader present at /opt/amdl-legacy/amdl' }
else { Write-Warn2 'downloader missing - re-run scripts/provision-distro.sh' }

Write-Host ''
Write-Host '----------------------------------------------------------------' -ForegroundColor Green
Write-Host " Deployment finished. Distro: $Name" -ForegroundColor Green
Write-Host ''
Write-Host ' Next steps:'
if (-not $loggedIn) {
    Write-Host '   1. Start the app and sign in with your Apple ID (login page / CLI menu L)'
} else {
    Write-Host '   1. Credentials already cached - no login needed'
}
Write-Host '   2. Optional: python apple_music_downloader.py --status'
Write-Host '   3. Optional: config tab -> "Get Token" for AAC / lyrics'
if (-not $SkipWslConfig) {
    Write-Host ''
    Write-Host ' Note: .wslconfig changed. Run "wsl --shutdown" once, then start the app.'
}
Write-Host '----------------------------------------------------------------' -ForegroundColor Green

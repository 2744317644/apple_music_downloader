<#
.SYNOPSIS
    Smoke test for the Apple Music downloader environment.

.DESCRIPTION
    Read-only checks. Nothing is downloaded and no service is stopped. Every
    check maps to something that has actually broken before, so a regression
    shows up immediately.

    The individual checks live in scripts/smoke_checks.py - passing Python
    snippets with `python -c` from PowerShell silently strips their quotes.

.PARAMETER SkipWsl
    Skip the checks that need WSL (useful before the first deploy).

.PARAMETER SkipStart
    Skip the check that asks the wrapper for its status.

.EXAMPLE
    .\scripts\smoke-test.ps1

.EXAMPLE
    .\scripts\smoke-test.ps1 -SkipWsl
#>
[CmdletBinding()]
param(
    [switch]$SkipWsl,
    [switch]$SkipStart
)

$ErrorActionPreference = 'Continue'
$env:WSL_UTF8 = '1'
try {
    if ([Console]::OutputEncoding.CodePage -ne 65001) {
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    }
} catch { }

$root = Split-Path -Parent $PSScriptRoot
$helper = Join-Path $PSScriptRoot 'smoke_checks.py'

$script:pass = 0
$script:fail = 0
$script:skip = 0
$script:failures = @()

function Get-Python {
    $candidates = @(
        'python',
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe')
    )
    foreach ($c in $candidates) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
        if (Test-Path $c) { return $c }
    }
    return $null
}

function Check {
    param([string]$Name, [string]$Key)
    Push-Location $root
    try {
        $out = & $python $helper $Key 2>&1
        $code = $LASTEXITCODE
    } catch {
        $out = @($_.Exception.Message)
        $code = 1
    } finally {
        Pop-Location
    }

    $detail = (($out | Where-Object { $_ -ne $null }) -join ' ').Trim()
    if ($code -eq 0) {
        $script:pass++
        Write-Host "  [PASS] $Name" -ForegroundColor Green
        if ($detail -and $VerbosePreference -ne 'SilentlyContinue') {
            Write-Host "         $detail" -ForegroundColor DarkGray
        }
    } else {
        $script:fail++
        $script:failures += $Name
        Write-Host "  [FAIL] $Name" -ForegroundColor Red
        if ($detail) { Write-Host "         $detail" -ForegroundColor DarkYellow }
    }
}

function Skip {
    param([string]$Name, [string]$Why)
    $script:skip++
    Write-Host "  [SKIP] $Name" -ForegroundColor DarkGray
    if ($Why) { Write-Host "         $Why" -ForegroundColor DarkGray }
}

$python = Get-Python
if (-not $python) {
    Write-Host '[ERROR] Python not found.' -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $helper)) {
    Write-Host "[ERROR] helper missing: $helper" -ForegroundColor Red
    exit 1
}

Write-Host ''
Write-Host '=== Python sources ===' -ForegroundColor Cyan
Check 'sources parse' 'parse'
Check 'common.py imports' 'imports'
Check 'config.yaml readable' 'config'
Check 'temp run dir created and removed' 'tempdir'

if ($SkipWsl) {
    Write-Host ''
    Write-Host '=== WSL environment (skipped) ===' -ForegroundColor Cyan
    Skip 'WSL checks' '-SkipWsl'
} else {
    Write-Host ''
    Write-Host '=== WSL environment ===' -ForegroundColor Cyan
    if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
        $script:pass++
        Write-Host '  [PASS] wsl.exe present' -ForegroundColor Green
    } else {
        $script:fail++
        $script:failures += 'wsl.exe present'
        Write-Host '  [FAIL] wsl.exe present' -ForegroundColor Red
    }
    Check 'distro registered' 'distro'
    Check 'downloader present in distro' 'downloader'
    Check 'MP4Box present in distro' 'mp4box'
    Check 'credentials cached' 'credentials'
    if ($SkipStart) {
        Skip 'wrapper answers on 30020' '-SkipStart'
    } else {
        Check 'wrapper answers on 30020' 'status'
    }
}

Write-Host ''
Write-Host '----------------------------------------------------------------'
$total = $script:pass + $script:fail + $script:skip
Write-Host (" Result: {0} passed, {1} failed, {2} skipped (of {3})" -f `
            $script:pass, $script:fail, $script:skip, $total)
if ($script:fail -gt 0) {
    Write-Host ' Failed checks:' -ForegroundColor Red
    foreach ($f in $script:failures) { Write-Host "   - $f" -ForegroundColor Red }
}
Write-Host '----------------------------------------------------------------'

exit $(if ($script:fail -gt 0) { 1 } else { 0 })

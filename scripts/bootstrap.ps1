[CmdletBinding()]
param(
    [switch]$SkipWeb,
    [switch]$RequireCloudTools
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$UvVersion = '0.12.9'

function Get-Python311 {
    $Python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $Python) {
        throw 'Python 3.11 is required but python was not found on PATH.'
    }
    $Version = & $Python.Source -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
    if ($Version -ne '3.11') {
        throw "Python 3.11 is required; found $Version at $($Python.Source)."
    }
    return $Python.Source
}

function Invoke-Uv {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $Uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($Uv) {
        & $Uv.Source @Arguments
    }
    else {
        & $script:PythonPath -m uv @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "uv command failed with exit code $LASTEXITCODE."
    }
}

Push-Location $RepoRoot
try {
    $script:PythonPath = Get-Python311
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        & $script:PythonPath -m pip install --user --disable-pip-version-check "uv==$UvVersion"
        if ($LASTEXITCODE -ne 0) {
            throw 'Unable to install the pinned uv bootstrap tool.'
        }
    }

    Invoke-Uv sync --frozen --extra dev
    Invoke-Uv run python -m search_rank.cli --help

    if (-not $SkipWeb) {
        $Npm = Get-Command npm -ErrorAction SilentlyContinue
        if (-not $Npm) {
            throw 'npm is required for the web package; rerun with -SkipWeb only for backend work.'
        }
        & $Npm.Source --prefix web ci --ignore-scripts --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) {
            throw "npm ci failed with exit code $LASTEXITCODE."
        }
    }

    $MissingCloudTools = @('aws', 'terraform', 'docker') | Where-Object {
        -not (Get-Command $_ -ErrorAction SilentlyContinue)
    }
    if ($RequireCloudTools -and $MissingCloudTools.Count -gt 0) {
        throw "Missing required cloud/container tools: $($MissingCloudTools -join ', ')."
    }
    if ($MissingCloudTools.Count -gt 0) {
        Write-Warning "Optional cloud/container tools not found: $($MissingCloudTools -join ', ')."
    }

    Write-Host 'Bootstrap complete. No AWS API calls or cloud writes were performed.'
}
finally {
    Pop-Location
}

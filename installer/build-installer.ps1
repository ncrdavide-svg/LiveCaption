# Builds artifacts\installer\LiveCaption-Setup-<version>.exe and LiveCaption-Setup.exe
# Requires: Python 3 (64 bit), Inno Setup 6 (winget install JRSoftware.InnoSetup).
# Usage: powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1 [-SkipBuild]
param([switch]$SkipBuild)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

# The version lives in one place: APP_VERSION in LiveCaption.py.
$Version = (Select-String -Path "$root\LiveCaption.py" -Pattern '^APP_VERSION = "(.+)"').Matches[0].Groups[1].Value

$iscc = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source,
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 non trovato. Installalo con: winget install JRSoftware.InnoSetup" }

if (-not $SkipBuild) {
    & powershell -ExecutionPolicy Bypass -File "$root\build.ps1"
    if ($LASTEXITCODE -ne 0) { throw "build non riuscita" }
}

Write-Host "Creazione installer LiveCaption $Version..."
& $iscc "/DAppVersion=$Version" "/DPublishDir=$root\dist\LiveCaption" (Join-Path $PSScriptRoot "LiveCaption.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup non riuscito" }

$setup = Join-Path $root "artifacts\installer\LiveCaption-Setup-$Version.exe"
# Same file under a fixed name: LiveSuite and the README download releases/latest/download/LiveCaption-Setup.exe.
Copy-Item $setup (Join-Path $root "artifacts\installer\LiveCaption-Setup.exe") -Force
Get-Item $setup, (Join-Path $root "artifacts\installer\LiveCaption-Setup.exe")

# Compila LiveCaption in dist\LiveCaption\LiveCaption.exe (cartella con exe + librerie).
#   powershell -ExecutionPolicy Bypass -File build.ps1            solo compilazione
#   powershell -ExecutionPolicy Bypass -File build.ps1 -Install   compila e installa per l'utente
#                                                                 (menu Start + desktop)
param([switch]$Install)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
$py = ".venv\Scripts\python.exe"
& $py -m pip install -q -r requirements.txt pyinstaller pillow
if (-not (Test-Path "assets\LiveCaption.ico")) { & $py tools\make_icon.py }

& $py -m PyInstaller --noconfirm --clean --windowed `
    --name LiveCaption `
    --icon assets\LiveCaption.ico `
    --add-data "assets\LiveCaption.ico;assets" `
    --collect-all vosk `
    --collect-submodules transformers.models.marian `
    --collect-submodules transformers.models.xlm_roberta `
    --copy-metadata transformers --copy-metadata tokenizers --copy-metadata huggingface_hub `
    --copy-metadata safetensors --copy-metadata tqdm --copy-metadata regex `
    --copy-metadata packaging --copy-metadata filelock --copy-metadata numpy `
    --copy-metadata pyyaml --copy-metadata torch --copy-metadata sentencepiece `
    --exclude-module tensorflow --exclude-module jax --exclude-module matplotlib `
    LiveCaption.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller non riuscito" }
Write-Host "Creato dist\LiveCaption\LiveCaption.exe"

if ($Install) {
    $dest = Join-Path $env:LOCALAPPDATA "Programs\LiveCaption"
    Get-Process LiveCaption -ErrorAction SilentlyContinue | Stop-Process -Force
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    Copy-Item "dist\LiveCaption" $dest -Recurse
    $exe = Join-Path $dest "LiveCaption.exe"
    $shell = New-Object -ComObject WScript.Shell
    foreach ($dir in @([Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop"))) {
        $lnk = $shell.CreateShortcut((Join-Path $dir "LiveCaption.lnk"))
        $lnk.TargetPath = $exe
        $lnk.WorkingDirectory = $dest
        $lnk.IconLocation = "$exe,0"
        $lnk.Description = "Sottotitoli dal vivo con traduzione"
        $lnk.Save()
    }
    Write-Host "Installato in $dest (collegamenti nel menu Start e sul desktop)"
}

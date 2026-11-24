# BALE DOWNLOAD HUB - run from source (PowerShell). Usage: .\run.ps1 [-Console]
param([switch]$Console)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = $null
foreach ($v in @("3.13", "3.12", "3.11")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py "-$v" -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { $py = @("py", "-$v"); break }
    }
}
if (-not $py -and (Get-Command python -ErrorAction SilentlyContinue)) {
    & python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $py = @("python") }
}
if (-not $py) {
    Write-Host "Python 3.11 or newer was NOT found."
    if (Get-Command py -ErrorAction SilentlyContinue) { Write-Host "Installed versions:"; & py -0p }
    Write-Host "Install Python 3.12 from https://www.python.org/downloads/windows/ (tick 'Add python.exe to PATH') and run again."
    exit 1
}
Write-Host ("Using: " + ($py -join " "))
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "Creating virtual environment..."
    & $py[0] @($py[1..($py.Length - 1)]) -m venv .venv
}
$stamp = Join-Path $PSScriptRoot ".venv\.deps_installed"
$want = (Get-FileHash requirements.txt).Hash
if (-not (Test-Path $stamp) -or (Get-Content $stamp) -ne $want) {
    Write-Host "Installing dependencies..."
    & $venvPy -m pip install --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Write-Host "Dependency installation failed."; exit 1 }
    Set-Content $stamp $want
}
if ($Console) { & $venvPy -m app.main } else { Start-Process (Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe") -ArgumentList "-m", "app.main" }

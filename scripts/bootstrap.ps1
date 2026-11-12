param([switch]$SkipFrontend)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
Add-ProjectToolPaths
foreach ($command in @('python', 'node', 'npm', 'git', 'docker', 'kind', 'kubectl', 'helm')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Required command not found: $command" }
}
python --version
node --version
docker --version
kind version
kubectl version --client
helm version --short
$venv = Join-Path $Root '.venv'
if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) { python -m venv $venv }
& (Join-Path $venv 'Scripts\python.exe') -m pip install --upgrade pip
$requirementsLock = Join-Path $Root 'backend\requirements-lock.txt'
if (Test-Path $requirementsLock) {
    & (Join-Path $venv 'Scripts\python.exe') -m pip install -r $requirementsLock
} else {
    & (Join-Path $venv 'Scripts\python.exe') -m pip install -r (Join-Path $Root 'backend\requirements.txt')
}
if (-not $SkipFrontend) {
    Push-Location (Join-Path $Root 'frontend')
    try { npm install } finally { Pop-Location }
}
if (-not (Test-Path (Join-Path $Root '.env'))) {
    Copy-Item (Join-Path $Root '.env.example') (Join-Path $Root '.env')
    Write-Host 'Created .env from template. Add your own model/GitHub credentials there; do not commit it.'
}
New-Item -ItemType Directory -Force (Join-Path $Root 'data') | Out-Null
Write-Host 'Bootstrap complete. Next: .\scripts\lab-up.ps1'

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$Root = Split-Path -Parent $PSScriptRoot
$pidDir = Join-Path $Root '.local'
Get-ChildItem $pidDir -Filter '*.pid' -ErrorAction SilentlyContinue | ForEach-Object {
    $processId = [int](Get-Content $_.FullName -Raw)
    $candidate = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if ($candidate -and $candidate.CommandLine -match 'kubectl(?:\.exe)?.*port-forward') {
        & taskkill.exe /PID $processId /T /F *> $null
    }
    Remove-Item $_.FullName -Force
}
Write-Host 'Stopped recorded local port-forward processes.'

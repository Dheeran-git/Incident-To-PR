$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$Root = Split-Path -Parent $PSScriptRoot
$pidDir = Join-Path $Root '.local'
foreach ($name in @('api.pid','web.pid')) {
    $file = Join-Path $pidDir $name
    if (Test-Path $file) {
        $processId = [int](Get-Content $file -Raw)
        $candidate = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
        $expected = if ($name -eq 'api.pid') { $candidate.CommandLine -match 'app\.main:app' } else {
            $candidate.CommandLine -match 'npm run dev|next dev'
        }
        if ($candidate -and $expected) { & taskkill.exe /PID $processId /T /F *> $null }
        Remove-Item $file -Force
    }
}
Write-Host 'Stopped recorded app processes.'

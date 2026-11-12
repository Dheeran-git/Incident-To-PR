function Add-ProjectToolPaths {
    $candidates = @()
    if ($env:USERPROFILE) { $candidates += Join-Path $env:USERPROFILE 'bin' }
    if ($env:LOCALAPPDATA) { $candidates += Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin' }
    if ($env:ProgramFiles) { $candidates += Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin' }
    $available = @($candidates | Where-Object { Test-Path $_ })
    if ($available.Count -gt 0) { $env:Path += ';' + ($available -join ';') }
}

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
Add-ProjectToolPaths
$pidDir = Join-Path $Root '.local'
New-Item -ItemType Directory -Force $pidDir | Out-Null
$forwards = @(
    @{Name='prometheus'; Namespace='online-boutique'; Resource='svc/incident-to-pr-prometheus-server'; Local=9090; Remote=80},
    @{Name='loki'; Namespace='observability'; Resource='svc/incident-to-pr-loki'; Local=3100; Remote=3100},
    @{Name='grafana'; Namespace='observability'; Resource='svc/incident-to-pr-grafana'; Local=3001; Remote=80},
    @{Name='argocd'; Namespace='argocd'; Resource='svc/argocd-server'; Local=8081; Remote=443}
)
foreach ($forward in $forwards) {
    $cliArgs = @('--context','kind-incident-to-pr','-n',$forward.Namespace,'port-forward',$forward.Resource,"$($forward.Local):$($forward.Remote)",'--address','127.0.0.1')
    $kubectl = (Get-Command kubectl).Source
    $proc = Start-Process -FilePath $kubectl -ArgumentList $cliArgs -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $pidDir "$($forward.Name).out.log") `
        -RedirectStandardError (Join-Path $pidDir "$($forward.Name).err.log")
    Set-Content -Path (Join-Path $pidDir "$($forward.Name).pid") -Value $proc.Id
}
Write-Host 'Port forwards started on loopback: Prometheus :9090, Loki :3100, Grafana :3001, Argo CD :8081.'

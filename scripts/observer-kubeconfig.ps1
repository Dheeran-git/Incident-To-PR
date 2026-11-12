$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
Add-ProjectToolPaths
$contextName = 'kind-incident-to-pr'
$view = kubectl config view --raw --minify --context $contextName -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Could not read the demo cluster connection details.' }
$clusterName = $view.contexts[0].context.cluster
$sourceCluster = $view.clusters | Where-Object { $_.name -eq $clusterName } | Select-Object -First 1
if (-not $sourceCluster) { throw 'The selected kind cluster was not found in kubeconfig.' }
$token = kubectl --context $contextName -n online-boutique create token incident-to-pr-observer --duration=10h
if ($LASTEXITCODE -ne 0 -or -not $token) { throw 'Could not mint a short-lived read-only observer token.' }
$observerConfig = @{
    apiVersion = 'v1'; kind = 'Config'
    clusters = @(@{ name = $clusterName; cluster = @{
        server = $sourceCluster.cluster.server
        'certificate-authority-data' = $sourceCluster.cluster.'certificate-authority-data'
    } })
    contexts = @(@{ name = 'incident-to-pr-observer'; context = @{
        cluster = $clusterName; user = 'incident-to-pr-observer'; namespace = 'online-boutique'
    } })
    'current-context' = 'incident-to-pr-observer'
    users = @(@{ name = 'incident-to-pr-observer'; user = @{ token = $token.Trim() } })
}
$localDir = Join-Path $Root '.local'
New-Item -ItemType Directory -Force $localDir | Out-Null
$targetPath = Join-Path $localDir 'observer-kubeconfig.json'
$observerConfig | ConvertTo-Json -Depth 10 | Set-Content -Path $targetPath -Encoding ascii
Write-Host 'Created a 10-hour, namespace-scoped observer kubeconfig in .local.'

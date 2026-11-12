$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
Add-ProjectToolPaths
$Context = 'kind-incident-to-pr'
docker --context desktop-linux info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker engine is unavailable. Start Docker Desktop, then rerun this script.' }
if (-not (kind get clusters | Select-String '^incident-to-pr$')) {
    kind create cluster --config (Join-Path $Root 'lab\kind-config.yaml') --wait 5m
}
kubectl config use-context $Context | Out-Null
kubectl create namespace online-boutique --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace observability --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl delete -f (Join-Path $Root 'lab\vendor\online-boutique-v0.10.7\kubernetes-manifests.yaml') -n default --ignore-not-found
kubectl apply -n online-boutique -f (Join-Path $Root 'lab\vendor\online-boutique-v0.10.7\kubernetes-manifests.yaml')
if ($LASTEXITCODE -ne 0) { throw 'Could not apply the pinned Online Boutique manifest.' }
kubectl patch service frontend -n online-boutique --type=merge -p '{"spec":{"type":"NodePort","ports":[{"port":80,"targetPort":8080,"nodePort":30080}]}}'
if ($LASTEXITCODE -ne 0) { throw 'Could not expose the Online Boutique frontend on the local kind port.' }
kubectl apply -f (Join-Path $Root 'lab\rbac\observer.yaml')
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
helm repo add grafana https://grafana.github.io/helm-charts --force-update
helm repo update
helm upgrade --install incident-to-pr prometheus-community/prometheus --version 29.47.2 `
    --namespace online-boutique --values (Join-Path $Root 'lab\helm\prometheus-values.yaml') `
    --set kube-state-metrics.enabled=false --wait --timeout 10m
helm upgrade --install incident-to-pr-kube-state-metrics prometheus-community/kube-state-metrics --version 9.0.1 `
    --namespace online-boutique --wait --timeout 5m
helm upgrade --install incident-to-pr grafana/loki --version 7.6.0 `
    --namespace observability --values (Join-Path $Root 'lab\helm\loki-values.yaml') --wait --timeout 10m
helm upgrade --install incident-to-pr-alloy grafana/alloy --version 1.15.0 `
    --namespace observability --values (Join-Path $Root 'lab\helm\alloy-values.yaml') --wait --timeout 10m
helm upgrade --install incident-to-pr-grafana grafana/grafana --version 10.5.15 `
    --namespace observability --values (Join-Path $Root 'lab\helm\grafana-values.yaml') `
    --set-file "dashboards.default.incident-to-pr.json=$((Join-Path $Root 'lab\grafana\incident-to-pr-dashboard.json') -replace '\\','/')" `
    --wait --timeout 10m
kubectl apply --server-side --force-conflicts -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.6.1/manifests/install.yaml
if ($LASTEXITCODE -ne 0) { throw 'Argo CD manifest apply failed.' }
kubectl -n online-boutique rollout status deployment --timeout=10m
kubectl -n online-boutique rollout status deployment/incident-to-pr-kube-state-metrics --timeout=5m
kubectl -n observability rollout status statefulset --timeout=10m
kubectl -n argocd rollout status deployment/argocd-server --timeout=10m
$dotenv = @{}
if (Test-Path (Join-Path $Root '.env')) {
    foreach ($line in Get-Content (Join-Path $Root '.env')) {
        if ($line -match '^\s*([^#=\s]+)\s*=(.*)$') { $dotenv[$matches[1]] = $matches[2].Trim().Trim('"').Trim("'") }
    }
}
$gitopsRepository = $dotenv['GITHUB_GITOPS_REPOSITORY']
if (-not $gitopsRepository) {
    $python = Join-Path $Root '.venv\Scripts\python.exe'
    $database = Join-Path $Root 'data\incident-to-pr.sqlite3'
    if ((Test-Path $python) -and (Test-Path $database)) {
        $gitopsRepository = & $python (Join-Path $PSScriptRoot 'read-app-setting.py') $database 'gitops_repository'
        $gitopsRepository = $gitopsRepository.Trim()
    }
}
if ($gitopsRepository) {
    if ($gitopsRepository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'GITHUB_GITOPS_REPOSITORY must be owner/repository.' }
    $repoUrl = "https://github.com/$gitopsRepository.git"
    if ($dotenv['GITHUB_ARGOCD_READ_TOKEN']) {
        $repoSecret = @{
            apiVersion='v1'; kind='Secret'
            metadata=@{ name='incident-to-pr-gitops-repository'; namespace='argocd'; labels=@{'argocd.argoproj.io/secret-type'='repository'} }
            stringData=@{ type='git'; url=$repoUrl; username='x-access-token'; password=$dotenv['GITHUB_ARGOCD_READ_TOKEN'] }
        } | ConvertTo-Json -Depth 10 -Compress
        $repoSecret | kubectl --context $Context apply --server-side --force-conflicts -f -
        if ($LASTEXITCODE -ne 0) { throw 'Could not configure the read-only GitOps repository credential in Argo CD.' }
    }
    $revision = if ($dotenv['GITHUB_BASE_BRANCH']) { $dotenv['GITHUB_BASE_BRANCH'] } else { 'main' }
    $application = @{
        apiVersion='argoproj.io/v1alpha1'; kind='Application'
        metadata=@{ name='online-boutique'; namespace='argocd' }
        spec=@{
            project='default'
            source=@{ repoURL=$repoUrl; targetRevision=$revision; path='deploy/online-boutique' }
            destination=@{ server='https://kubernetes.default.svc'; namespace='online-boutique' }
            syncPolicy=@{ automated=@{ prune=$false; selfHeal=$true; allowEmpty=$false }; syncOptions=@('ApplyOutOfSyncOnly=true','FailOnSharedResource=true') }
        }
    } | ConvertTo-Json -Depth 15 -Compress
    $application | kubectl --context $Context apply --server-side --force-conflicts -f -
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Argo CD Online Boutique application.' }
} else {
    Write-Host 'Argo CD is installed; set GITHUB_GITOPS_REPOSITORY to activate GitOps reconciliation.'
}
Write-Host "Lab is installed on context $Context. Run .\scripts\port-forward.ps1, then start the app with .\scripts\dev.ps1."

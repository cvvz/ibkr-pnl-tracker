param(
    [string[]]$Targets = @("all")
)

$ErrorActionPreference = "Stop"

$Registry = "cvvz"
$BackendImage = "$Registry/ibkr-backend:latest"
$GatewayImage = "$Registry/ib-gateway:latest"
$FrontendImage = "$Registry/ibkr-frontend:latest"

$normalized = @()
foreach ($target in $Targets) {
    switch ($target.ToLower()) {
        "all" { $normalized += "all" }
        "backend" { $normalized += "backend" }
        "frontend" { $normalized += "frontend" }
        "gateway" { $normalized += "ib-gateway" }
        "ib-gateway" { $normalized += "ib-gateway" }
        default { throw "Unknown target: $target (use backend, frontend, ib-gateway, or all)" }
    }
}
if (-not $normalized) {
    $normalized = @("all")
}

function HasTarget([string]$name) {
    return ($normalized -contains "all") -or ($normalized -contains $name)
}

Write-Host "Targets: $($normalized -join ', ')"

if (HasTarget "backend") {
    Write-Host "Building backend image..."
    docker build -t $BackendImage backend
    Write-Host "Pushing backend image..."
    docker push $BackendImage
    Write-Host "Applying backend manifest..."
    kubectl apply -f k8s/backend.yaml
    Write-Host "Restarting backend..."
    kubectl rollout restart deploy/ibkr-backend -n ibkr
}

if (HasTarget "ib-gateway") {
    Write-Host "Building ib-gateway image..."
    docker build -t $GatewayImage ib-gateway
    Write-Host "Pushing ib-gateway image..."
    docker push $GatewayImage
    Write-Host "Applying ib-gateway manifest..."
    kubectl apply -f k8s/ib-gateway.yaml
    Write-Host "Restarting ib-gateway..."
    kubectl rollout restart deploy/ib-gateway -n ibkr
}

if (HasTarget "frontend") {
    Write-Host "Building frontend image..."
    docker build -t $FrontendImage frontend
    Write-Host "Pushing frontend image..."
    docker push $FrontendImage
    Write-Host "Applying frontend manifest..."
    kubectl apply -f k8s/frontend.yaml
    Write-Host "Restarting frontend..."
    kubectl rollout restart deploy/ibkr-frontend -n ibkr
}

Write-Host "Done."

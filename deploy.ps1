$ErrorActionPreference = "Stop"

$Registry = "cvvz"
$BackendImage = "$Registry/ibkr-backend:latest"
$GatewayImage = "$Registry/ib-gateway:latest"
$FrontendImage = "$Registry/ibkr-frontend:latest"

Write-Host "Building images..."
docker build -t $BackendImage backend
docker build -t $GatewayImage ib-gateway
docker build -t $FrontendImage frontend

Write-Host "Pushing images..."
docker push $BackendImage
docker push $GatewayImage
docker push $FrontendImage

Write-Host "Applying k8s manifests..."
kubectl apply -f k8s/backend-ib-gateway.yaml
kubectl apply -f k8s/frontend.yaml

Write-Host "Restarting ib-gateway (new images)..."
kubectl rollout restart deploy/ib-gateway -n ibkr

Write-Host "Restarting frontend (new images)..."
kubectl rollout restart deploy/ibkr-frontend -n ibkr

Write-Host "Done."

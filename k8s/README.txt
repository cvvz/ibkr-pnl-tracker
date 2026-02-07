# Apply all manifests
# kubectl apply -f k8s/namespace.yaml
# kubectl apply -f k8s/ib-gateway-pvc.yaml
# kubectl apply -f k8s/ib-gateway.yaml
# kubectl apply -f k8s/ib-gateway-service.yaml
# kubectl apply -f k8s/ib-gateway-novnc.yaml
# kubectl apply -f k8s/ib-gateway-novnc-service.yaml
# kubectl apply -f k8s/backend-sa.yaml
# kubectl apply -f k8s/backend-role.yaml
# kubectl apply -f k8s/backend-rb.yaml
# kubectl apply -f k8s/backend.yaml
# kubectl apply -f k8s/backend-service.yaml
# kubectl apply -f k8s/frontend.yaml
# kubectl apply -f k8s/frontend-service.yaml
#
# Notes:
# - Replace image names with your registry.
# - Build and push your IB Gateway image from `ib-gateway/Dockerfile`.
# - The container exposes API port 7496 and VNC port 5900.
# - Update IBKR_GATEWAY_VNC_URL to the external LB IP of ib-gateway-novnc service, e.g. http://<EXTERNAL_IP>:6080.
# - For Vite, set VITE_API_BASE at build time to your backend external IP.

# Apply all manifests
# kubectl apply -f k8s/ib-gateway.yaml
# kubectl apply -f k8s/backend.yaml
# kubectl apply -f k8s/frontend.yaml
#
# Notes:
# - Replace image names with your registry if needed.
# - Update IBKR_GATEWAY_VNC_URL to the external LB IP of ib-gateway-novnc service, e.g. http://<EXTERNAL_IP>:6080/vnc.html.
# - The IB Gateway API port is 4001 by default for live accounts.
# - Rebuild and push the ib-gateway image after updating start.sh to include noVNC.
# - The IB Gateway settings are stored under /root/Jts; PVC is mounted there to persist configuration.
# - For Vite, set VITE_API_BASE at build time to your backend external IP.

#!/usr/bin/env bash
set -euo pipefail

VNC_PORT="${VNC_PORT:-5900}"
VNC_PASSWORD="${VNC_PASSWORD:-}"

mkdir -p /tmp/.X11-unix

Xvfb :0 -screen 0 1280x800x24 -ac +extension GLX +render -noreset &
FLUXBOX_PID=""
for i in {1..10}; do
  if xdpyinfo -display :0 >/dev/null 2>&1; then
    fluxbox &
    FLUXBOX_PID=$!
    break
  fi
  sleep 0.5
done

if [ -n "$VNC_PASSWORD" ]; then
  x11vnc -storepasswd "$VNC_PASSWORD" /tmp/vncpass
  x11vnc -forever -shared -rfbport "$VNC_PORT" -rfbauth /tmp/vncpass -display :0 &
else
  x11vnc -forever -shared -rfbport "$VNC_PORT" -nopw -display :0 &
fi

if [ -f /opt/ibgateway/ibgatewaystart.sh ]; then
  exec /opt/ibgateway/ibgatewaystart.sh
fi

if [ -f /opt/ibgateway/ibgateway ]; then
  exec /opt/ibgateway/ibgateway
fi

echo "IB Gateway launch script not found in /opt/ibgateway" >&2
sleep 5
exit 1

#!/usr/bin/env bash
set -euo pipefail

VNC_PORT="${VNC_PORT:-5901}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
VNC_PASSWORD="${VNC_PASSWORD:-}"
export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:-} -Djava.net.preferIPv4Stack=true"

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

websockify --web /opt/novnc "$NOVNC_PORT" "localhost:$VNC_PORT" &

start_gateway() {
  if [ -f /opt/ibgateway/ibgatewaystart.sh ]; then
    /opt/ibgateway/ibgatewaystart.sh
    return
  fi
  if [ -f /opt/ibgateway/ibgateway ]; then
    /opt/ibgateway/ibgateway
    return
  fi
  echo "IB Gateway launch script not found in /opt/ibgateway" >&2
  exit 1
}

kill_gateway() {
  pkill -f "install4j.ibgateway.GWClient" >/dev/null 2>&1 || true
}

while true; do
  kill_gateway
  start_gateway &
  STARTER_PID=$!

  GW_PID=""
  for i in {1..30}; do
    GW_PID="$(pgrep -n -f "install4j.ibgateway.GWClient" || true)"
    if [ -n "$GW_PID" ]; then
      break
    fi
    sleep 1
  done

  while true; do
    if [ -n "$GW_PID" ] && ! kill -0 "$GW_PID" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done

  wait "$STARTER_PID" || true
  sleep 2
done

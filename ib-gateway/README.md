# IB Gateway Container (Self-Built)

This image runs IB Gateway with a headless X server, VNC, and noVNC so you can log in directly from a browser.

## Build

```bash
docker build -t ib-gateway:local --build-arg IB_GATEWAY_URL=<IB_GATEWAY_INSTALLER_URL> .
```

Example installer URL:
```
https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh
```

## Run

```bash
docker run --rm -p 4001:4001 -p 5900:5900 ib-gateway:local
```

Optional VNC password:

```bash
docker run --rm -e VNC_PASSWORD=yourpass -p 4001:4001 -p 5900:5900 -p 6080:6080 ib-gateway:local
```

## Notes
- You must complete login + 2FA in the GUI.
- Enable API access inside IB Gateway settings and confirm the API port (default 4001 for live).
- This image does not include IBC (auto-login). It is meant for manual login via VNC/noVNC.
 - noVNC is exposed on port 6080 (`http://localhost:6080/vnc.html`).

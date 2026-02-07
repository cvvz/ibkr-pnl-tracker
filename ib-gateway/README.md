# IB Gateway Container (Self-Built)

This image runs IB Gateway with a headless X server and VNC so you can log in from a browser (via noVNC) or a VNC client.

## Build

```bash
docker build -t ib-gateway:local --build-arg IB_GATEWAY_URL=<IB_GATEWAY_INSTALLER_URL> .
```

Example installer URL (update to the current version):
```
https://download2.interactivebrokers.com/installers/ibgateway/10.30.1o/ibgateway-10.30.1o-standalone-linux-x64.sh
```

## Run

```bash
docker run --rm -p 7496:7496 -p 5900:5900 ib-gateway:local
```

Optional VNC password:

```bash
docker run --rm -e VNC_PASSWORD=yourpass -p 7496:7496 -p 5900:5900 ib-gateway:local
```

## Notes
- You must complete login + 2FA in the GUI.
- Enable API access inside IB Gateway settings and confirm the API port (7496 for live).
- This image does not include IBC (auto-login). It is meant for manual login via VNC/noVNC.

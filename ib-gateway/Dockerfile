FROM ubuntu:22.04

ARG IB_GATEWAY_URL="https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh"

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:0 \
    VNC_PORT=5900

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    x11vnc \
    xvfb \
    fluxbox \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libxtst6 \
    libxi6 \
    libxfixes3 \
    libxrandr2 \
    libglib2.0-0 \
    libnss3 \
    libasound2 \
    libxcb1 \
    libxkbcommon0 \
    libdbus-1-3 \
    libgcc1 \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "$IB_GATEWAY_URL" -o /tmp/ibgateway.sh \
    && sh /tmp/ibgateway.sh -q -dir /opt/ibgateway \
    && rm /tmp/ibgateway.sh

COPY start.sh /usr/local/bin/start-ibgateway.sh
RUN chmod +x /usr/local/bin/start-ibgateway.sh

EXPOSE 7496 5900

CMD ["/usr/local/bin/start-ibgateway.sh"]

#!/bin/bash
# VPS initialization script for evo-server
# Run as root on 119.45.204.198
set -euo pipefail

echo "=== 1. System update ==="
yum update -y || apt-get update -y

echo "=== 2. Install Python 3.10+ ==="
if command -v python3 &>/dev/null; then
    echo "Python3 already installed: $(python3 --version)"
else
    yum install -y python3 python3-pip || apt-get install -y python3 python3-pip
fi

echo "=== 3. Install Nginx ==="
if command -v nginx &>/dev/null; then
    echo "Nginx already installed"
else
    yum install -y nginx || apt-get install -y nginx
fi

echo "=== 4. Install Litestream ==="
if command -v litestream &>/dev/null; then
    echo "Litestream already installed: $(litestream version)"
else
    LITESTREAM_VERSION="0.3.13"
    curl -sL "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-amd64.tar.gz" | tar xz -C /usr/local/bin/
    echo "Litestream installed"
fi

echo "=== 5. Create directories ==="
mkdir -p /opt/evo-server/data
mkdir -p /opt/evo-server/backups/litestream

echo "=== 6. Install Python dependencies ==="
pip3 install fastapi uvicorn httpx apscheduler || python3 -m pip install fastapi uvicorn httpx apscheduler

echo "=== 7. Setup complete ==="
echo "Next steps:"
echo "  1. Upload evo_server/ code to /opt/evo-server/"
echo "  2. Copy .env to /opt/evo-server/.env"
echo "  3. Copy evo-server.service to /etc/systemd/system/"
echo "  4. Copy nginx.conf to /etc/nginx/conf.d/evo-server.conf"
echo "  5. systemctl daemon-reload && systemctl enable --now evo-server"
echo "  6. systemctl restart nginx"

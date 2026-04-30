#!/usr/bin/env bash
# scripts/deploy.sh — Papyrus backend deploy helper.
#
# Usage:
#   ./scripts/deploy.sh --firsttime   # one-time VPS setup; prints sudo blocks
#   ./scripts/deploy.sh               # redeploy (pull, install, restart, health check)

set -euo pipefail

REPO_DIR="${PAPYRUS_REPO_DIR:-${HOME}/papyrus-intelligence}"
SERVICE_NAME="papyrus-api"
PORT="8001"
HOSTNAME="papyrus.5-78-200-61.nip.io"

if [[ "${1:-}" == "--firsttime" ]]; then
  echo "==> First-time setup in ${REPO_DIR}"
  cd "$REPO_DIR"

  if [[ ! -d venv ]]; then
    python3 -m venv venv
  fi
  ./venv/bin/pip install --upgrade pip --quiet
  ./venv/bin/pip install -r requirements-api.txt --quiet
  echo "    Python deps installed."

  if [[ ! -f .env ]]; then
    touch .env
    echo "    Created empty .env — fill it in before continuing."
  fi
  chmod 600 .env
  echo "    .env is mode 600."

  cat <<EOF

==> Python side complete. Now run these sudo commands:

1) Write systemd unit:
   sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<UNIT
   [Unit]
   Description=Papyrus FastAPI backend
   After=network.target

   [Service]
   Type=simple
   User=$(whoami)
   WorkingDirectory=${REPO_DIR}
   EnvironmentFile=${REPO_DIR}/.env
   ExecStart=${REPO_DIR}/venv/bin/uvicorn api.main:app --host 127.0.0.1 --port ${PORT} --workers 2
   Restart=on-failure
   RestartSec=3

   [Install]
   WantedBy=multi-user.target
   UNIT

2) Enable and start:
   sudo systemctl daemon-reload
   sudo systemctl enable --now ${SERVICE_NAME}

3) Add a Caddy block (do NOT remove the existing reed block):
   sudo tee -a /etc/caddy/Caddyfile > /dev/null <<CADDY

   ${HOSTNAME} {
       reverse_proxy localhost:${PORT}
   }
   CADDY

4) Reload Caddy:
   sudo systemctl reload caddy

5) (Optional) Allow passwordless service restart for $(whoami):
   echo "$(whoami) ALL=(ALL) NOPASSWD: /bin/systemctl restart ${SERVICE_NAME}" | sudo tee /etc/sudoers.d/${SERVICE_NAME}
   sudo chmod 440 /etc/sudoers.d/${SERVICE_NAME}

After running 1-4, verify:
  curl -I https://${HOSTNAME}/health

EOF
  exit 0
fi

# Redeploy mode
echo "==> Redeploying in ${REPO_DIR}"
cd "$REPO_DIR"

git pull --ff-only
./venv/bin/pip install -r requirements-api.txt --quiet

if sudo -n systemctl restart "$SERVICE_NAME" 2>/dev/null; then
  echo "    Restarted ${SERVICE_NAME}."
else
  echo "    Cannot restart without password. Run: sudo systemctl restart ${SERVICE_NAME}"
  exit 1
fi

# Wait a moment for the server to come up
for i in 1 2 3 4 5; do
  if curl -fsS "http://localhost:${PORT}/health" >/dev/null 2>&1; then
    echo "    ✓ Backend healthy on port ${PORT}"
    exit 0
  fi
  sleep 1
done

echo "    ✗ Health check failed after 5s. Check: journalctl -u ${SERVICE_NAME} -n 50"
exit 1

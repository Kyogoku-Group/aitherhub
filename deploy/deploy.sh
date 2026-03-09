#!/bin/bash
# =============================================================
# AitherHub Worker Deploy Script
# VM側で手動実行する場合に使用
# Usage: sudo bash deploy/deploy.sh
# =============================================================
set -e

REPO_DIR="/opt/aitherhub"
SERVICE_NAME="aither-worker"

echo "=== AitherHub Worker Deploy ==="
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# --- Pull latest code ---
cd "${REPO_DIR}"
git config --global --add safe.directory "${REPO_DIR}"
echo "Before: $(git rev-parse HEAD)"
git fetch origin master
git reset --hard origin/master
echo "After:  $(git rev-parse HEAD)"
echo ""

# --- Install dependencies ---
if [ -f requirements.txt ]; then
    echo "=== Installing dependencies ==="
    pip install -r requirements.txt --quiet
    echo ""
fi

# --- Restart worker ---
echo "=== Restarting worker ==="
systemctl restart "${SERVICE_NAME}"
sleep 5

# --- Verify ---
echo "=== Worker status ==="
systemctl is-active "${SERVICE_NAME}"
echo "Worker PID: $(systemctl show ${SERVICE_NAME} --property=MainPID --value)"
echo ""

# --- Health check ---
echo "=== Health check ==="
HEALTH=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/health 2>/dev/null || echo "no_endpoint")
if [ "${HEALTH}" = "200" ]; then
    echo "Health: OK"
else
    echo "Health: ${HEALTH} (health endpoint may not be running)"
fi
echo ""

echo "=== Deploy complete ==="
echo "Commit: $(git rev-parse HEAD)"
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

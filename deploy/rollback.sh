#!/bin/bash
# =============================================================
# AitherHub Worker Rollback Script
# Worker deploy 失敗時に前のcommitに戻す
# Usage: sudo bash deploy/rollback.sh
# Usage: sudo bash deploy/rollback.sh <commit_hash>
# =============================================================
set -e

REPO_DIR="/opt/aitherhub"
SERVICE_NAME="aither-worker"
TARGET_COMMIT="${1:-HEAD~1}"

echo "=== AitherHub Worker Rollback ==="
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

cd "${REPO_DIR}"
git config --global --add safe.directory "${REPO_DIR}"

echo "Current: $(git rev-parse HEAD)"
echo "Rolling back to: ${TARGET_COMMIT}"
echo ""

# --- Rollback ---
git reset --hard "${TARGET_COMMIT}"
echo "After rollback: $(git rev-parse HEAD)"
echo ""

# --- Install dependencies (previous version) ---
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

echo "=== Rollback complete ==="
echo "Commit: $(git rev-parse HEAD)"
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

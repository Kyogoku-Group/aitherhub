#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# Install Git hooks for the 4-Layer Defense System
# ─────────────────────────────────────────────────────────────────
# Usage: bash scripts/install-hooks.sh
#
# This script:
# 1. Copies the pre-push hook to .git/hooks/
# 2. Makes it executable
# 3. Verifies installation
# ─────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}[install-hooks]${NC} Installing git hooks..."

# Ensure hooks directory exists
mkdir -p "$HOOKS_DIR"

# Install pre-push hook
cp "$SCRIPT_DIR/pre-push" "$HOOKS_DIR/pre-push"
chmod +x "$HOOKS_DIR/pre-push"

echo -e "${GREEN}[install-hooks]${NC} Installed: pre-push hook"

# Verify
if [ -x "$HOOKS_DIR/pre-push" ]; then
    echo -e "${GREEN}[install-hooks]${NC} Verification: OK"
else
    echo "ERROR: Hook installation failed!"
    exit 1
fi

echo -e "${GREEN}[install-hooks]${NC} Done. All hooks installed."

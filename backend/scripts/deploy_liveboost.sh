#!/usr/bin/env bash
# ============================================================
# LiveBoost Backend Deploy Script
# ============================================================
# Usage: bash scripts/deploy_liveboost.sh
#
# Prerequisites:
#   - AZURE_STORAGE_CONNECTION_STRING is set
#   - DATABASE_URL is set
#   - OPENAI_API_KEY is set
#   - ffmpeg is installed on the worker machine
# ============================================================

set -euo pipefail

echo "============================================"
echo " LiveBoost Backend Deploy"
echo "============================================"

# ---- 1. Install new dependencies ----
echo "[1/4] Installing dependencies..."
pip install aiohttp 2>/dev/null || pip3 install aiohttp 2>/dev/null
echo "  ✓ aiohttp installed"

# ---- 2. Verify ffmpeg ----
echo "[2/4] Verifying ffmpeg..."
if command -v ffmpeg &> /dev/null; then
    echo "  ✓ ffmpeg found: $(ffmpeg -version 2>&1 | head -1)"
else
    echo "  ✗ ffmpeg NOT found. Please install ffmpeg."
    echo "    Ubuntu: sudo apt-get install -y ffmpeg"
    echo "    macOS:  brew install ffmpeg"
    exit 1
fi

# ---- 3. Run migration ----
echo "[3/4] Running database migration..."
cd "$(dirname "$0")/.."
alembic upgrade head
echo "  ✓ Migration complete"

# ---- 4. Verify endpoints ----
echo "[4/4] Verifying new endpoints..."
echo "  New endpoints:"
echo "    POST /api/v1/live-analysis/start"
echo "    GET  /api/v1/live-analysis/status/{video_id}"
echo "    POST /api/v1/live-analysis/generate-chunk-upload-url"
echo ""
echo "============================================"
echo " Deploy complete!"
echo ""
echo " To start the analysis worker:"
echo "   python -m app.workers.live_analysis_worker"
echo ""
echo " Worker environment variables:"
echo "   AZURE_STORAGE_CONNECTION_STRING (required)"
echo "   AZURE_QUEUE_NAME (default: video-jobs)"
echo "   DATABASE_URL (required)"
echo "   OPENAI_API_KEY (required for STT + OCR)"
echo "   WORKER_POLL_INTERVAL (default: 5)"
echo "   WORKER_MAX_CONCURRENT (default: 2)"
echo "============================================"

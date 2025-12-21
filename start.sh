#!/bin/bash
set -e

SERVER_PORT="${PORT:-8000}"

echo "=================================================="
echo "   EMAIL SCRAPER"
echo "   Port: $SERVER_PORT"
echo "=================================================="

echo "[*] Starting Web Dashboard..."
exec gunicorn app:app \
    --bind "0.0.0.0:$SERVER_PORT" \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
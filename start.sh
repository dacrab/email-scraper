#!/bin/bash
set -e

SERVER_PORT="${PORT:-8000}"

echo "=================================================="
echo "   EMAIL SCRAPER"
echo "   Port: $SERVER_PORT"
echo "=================================================="

echo "[*] Starting Web Dashboard..."
gunicorn app:app \
    --bind "0.0.0.0:$SERVER_PORT" \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - &

WEB_PID=$!

echo "[*] Launching Scraper..."
python3 /app/scraper.py > /proc/1/fd/1 2>&1 &

wait $WEB_PID

#!/bin/bash
set -e

# Default Railway port
PORT="${PORT:-8000}"

echo "--- Starting Scraper & Web Dashboard ---"

# 1. Start the Scraper in the BACKGROUND
# It will run, generate recipients.csv, and then exit.
# The web app monitors the CSV file.
echo "[*] Launching Scraper in background..."
python3 /app/scraper.py --config /app/config.json &

# 2. Start the Web Server (Gunicorn + Flask) in the FOREGROUND
# This ensures the container stays alive and listens on the correct PORT.
echo "[*] Starting Web Dashboard on port $PORT..."
exec gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120


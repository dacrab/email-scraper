#!/bin/bash
set -e

# Default Railway port is often determined by $PORT, defaulting to 8000 if not set
PORT="${PORT:-8000}"

echo "--- Starting Email Scraper Container ---"

# 1. Start the HTTP server in the background to allow file downloads
# We serve the current directory (/app)
echo "[*] Starting HTTP server on port $PORT..."
python3 -m http.server "$PORT" &
SERVER_PID=$!

# 2. Run the Scraper
# We run it in the foreground so we can see logs.
# When it finishes, the container would normally exit if we didn't have the server running.
echo "[*] Starting Scraper Job..."
python3 /app/scraper.py --config /app/config.json

echo "[*] Scraper finished. The CSV file should be available for download."
echo "[*] Web server is still running. Press Ctrl+C to stop."

# 3. Wait for the server process (keeps container alive)
wait $SERVER_PID

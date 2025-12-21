"""Flask web dashboard for the email scraper."""

import csv
import logging
import os
import signal
import subprocess
import time
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for

from config import ScraperConfig

app = Flask(__name__, 
            template_folder=str(ScraperConfig.TEMPLATE_DIR), 
            static_folder=str(ScraperConfig.STATIC_DIR))
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

class ScraperManager:
    """Handles the scraper process lifecycle."""
    
    @staticmethod
    def get_pid() -> int | None:
        if ScraperConfig.PID_FILE.exists():
            try:
                return int(ScraperConfig.PID_FILE.read_text().strip())
            except (ValueError, OSError):
                return None
        return None

    @classmethod
    def is_running(cls) -> bool:
        pid = cls.get_pid()
        if not pid: return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            if ScraperConfig.PID_FILE.exists():
                ScraperConfig.PID_FILE.unlink(missing_ok=True)
            return False

    @classmethod
    def start(cls) -> bool:
        if cls.is_running(): return False
        
        with open(ScraperConfig.LOG_FILE, "a") as log:
            process = subprocess.Popen(
                ["python3", str(ScraperConfig.BASE_DIR / "scraper.py")],
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=str(ScraperConfig.BASE_DIR),
            )
        ScraperConfig.PID_FILE.write_text(str(process.pid))
        return True

    @classmethod
    def stop(cls) -> bool:
        pid = cls.get_pid()
        if not pid: return False
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(10): # Graceful wait
                if not cls.is_running(): return True
                time.sleep(0.5)
            os.kill(pid, signal.SIGKILL)
            return True
        except OSError:
            return False

def load_csv_data() -> list[dict]:
    path = ScraperConfig().output_path
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        with path.open(encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        app.logger.error(f"Data load error: {e}")
        return []

@app.route("/")
@app.route("/dashboard")
def index():
    config = ScraperConfig()
    data = load_csv_data()
    return render_template(
        "index.html",
        data=data,
        count=len(data),
        running=ScraperManager.is_running(),
        config=config,
        error=request.args.get("error"),
        success=request.args.get("success")
    )

@app.route("/api/status")
def api_status():
    return jsonify({
        "running": ScraperManager.is_running(),
        "count": len(load_csv_data())
    })

@app.route("/api/data")
def api_data():
    data = load_csv_data()
    return jsonify({"data": data, "count": len(data)})

@app.route("/api/logs")
def api_logs():
    lines = int(request.args.get("lines", 100))
    if not ScraperConfig.LOG_FILE.exists():
        return jsonify({"logs": ""})
    try:
        with open(ScraperConfig.LOG_FILE) as f:
            content = f.readlines()
        return jsonify({"logs": "".join(content[-lines:])})
    except Exception as e:
        return jsonify({"logs": f"Error: {e}"})

@app.route("/scraper/<action>", methods=["POST"])
def scraper_control(action):
    if action == "start":
        if ScraperManager.start():
            return redirect(url_for("index", success="Scraper started"))
        return redirect(url_for("index", error="Already running"))
    elif action == "stop":
        if ScraperManager.stop():
            return redirect(url_for("index", success="Scraper stopped"))
        return redirect(url_for("index", error="Failed to stop"))
    elif action == "restart":
        ScraperManager.stop()
        time.sleep(1)
        ScraperManager.start()
        return redirect(url_for("index", success="Scraper restarted"))
    return redirect(url_for("index"))

@app.route("/config")
def config_view():
    return render_template("config.html", config=ScraperConfig())

@app.route("/download/<fmt>")
def download(fmt):
    path = ScraperConfig().output_path
    if not path.exists():
        return redirect(url_for("index", error="No data available"))
    if fmt == "csv":
        return send_file(path, as_attachment=True, download_name="contacts.csv")
    if fmt == "json":
        return jsonify(load_csv_data())
    return redirect(url_for("index", error="Invalid format"))

@app.route("/clear", methods=["POST"])
def clear_data():
    path = ScraperConfig().output_path
    if path.exists():
        path.unlink()
    return redirect(url_for("index", success="Data cleared"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", 
            port=int(os.environ.get("PORT", 8000)), 
            debug=os.environ.get("FLASK_DEBUG") == "1")

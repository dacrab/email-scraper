"""Flask web dashboard for email scraper."""

import csv
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for

from config import BASE_DIR, DEFAULT_CONFIG_FILE, STATIC_DIR, TEMPLATE_DIR, ScraperConfig

app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")


def get_output_path() -> Path:
    return ScraperConfig.load().output_path


def is_scraper_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "python.*scraper\\.py"],
            capture_output=True,
            text=True
        )
        pids = [p for p in result.stdout.strip().split('\n') if p]
        return len(pids) > 0
    except Exception:
        return False


LOG_FILE = BASE_DIR / "scraper.log"


def start_scraper() -> bool:
    if is_scraper_running():
        return False
    with open(LOG_FILE, "w") as log:
        subprocess.Popen(
            ["python3", str(BASE_DIR / "scraper.py")],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    return True


def stop_scraper() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "python.*scraper\\.py"],
            capture_output=True,
            text=True
        )
        pids = [p for p in result.stdout.strip().split('\n') if p]
        for pid in pids:
            os.kill(int(pid), signal.SIGTERM)
        return len(pids) > 0
    except Exception:
        return False


def restart_scraper() -> None:
    stop_scraper()
    time.sleep(1)
    start_scraper()


def load_data() -> tuple[list[dict], int]:
    output_path = get_output_path()
    if not output_path.exists() or output_path.stat().st_size == 0:
        return [], 0
    try:
        with output_path.open() as f:
            data = list(csv.DictReader(f))
        return data, len(data)
    except Exception:
        return [], 0


@app.route("/")
def index():
    config = ScraperConfig.load()
    data, count = load_data()
    error = request.args.get("error")
    success = request.args.get("success")

    return render_template(
        "index.html",
        data=data,
        count=count,
        running=is_scraper_running(),
        config=config,
        error=error,
        success=success,
    )


@app.route("/api/status")
def api_status():
    data, count = load_data()
    return jsonify({
        "running": is_scraper_running(),
        "count": count,
    })


@app.route("/api/data")
def api_data():
    data, count = load_data()
    return jsonify({
        "data": data,
        "count": count,
    })


@app.route("/config", methods=["GET", "POST"])
def config_page():
    if request.method == "POST":
        try:
            config = ScraperConfig(
                search_term=request.form.get("search_term", "").strip(),
                locations=[loc.strip() for loc in request.form.get("locations", "").split(",") if loc.strip()],
                max_results_per_query=int(request.form.get("max_results_per_query", 10)),
                max_concurrent_pages=int(request.form.get("max_concurrent_pages", 5)),
                headless=request.form.get("headless") == "on",
                scroll_pause_time=float(request.form.get("scroll_pause_time", 2.0)),
                max_scroll_attempts=int(request.form.get("max_scroll_attempts", 20)),
                delay_min=float(request.form.get("delay_min", 3.0)),
                delay_max=float(request.form.get("delay_max", 5.0)),
            )
            config.save()

            if request.form.get("restart_scraper"):
                restart_scraper()
                return redirect(url_for("index", success="Configuration saved and scraper restarted"))

            return redirect(url_for("index", success="Configuration saved"))
        except Exception as e:
            return redirect(url_for("index", error=str(e)))

    config = ScraperConfig.load()
    return render_template("config.html", config=config)


@app.route("/scraper/start", methods=["POST"])
def scraper_start():
    if start_scraper():
        return redirect(url_for("index", success="Scraper started"))
    return redirect(url_for("index", error="Scraper is already running"))


@app.route("/scraper/stop", methods=["POST"])
def scraper_stop():
    if stop_scraper():
        return redirect(url_for("index", success="Scraper stopped"))
    return redirect(url_for("index", error="Failed to stop scraper"))


@app.route("/scraper/restart", methods=["POST"])
def scraper_restart():
    restart_scraper()
    return redirect(url_for("index", success="Scraper restarted"))


@app.route("/download/<fmt>")
def download(fmt: str):
    output_path = get_output_path()
    if not output_path.exists():
        return redirect(url_for("index", error="No data to download"))

    if fmt == "csv":
        return send_file(output_path, as_attachment=True, download_name="contacts.csv")

    if fmt == "json":
        data, _ = load_data()
        json_path = BASE_DIR / "contacts.json"
        with json_path.open("w") as f:
            json.dump(data, f, indent=2)
        return send_file(json_path, as_attachment=True, download_name="contacts.json")

    return redirect(url_for("index", error="Unsupported format"))


@app.route("/clear", methods=["POST"])
def clear_data():
    output_path = get_output_path()
    if output_path.exists():
        output_path.unlink()
    return redirect(url_for("index", success="Data cleared"))


@app.route("/api/logs")
def api_logs():
    lines = int(request.args.get("lines", 100))
    if not LOG_FILE.exists():
        return jsonify({"logs": "No logs yet"})
    try:
        with open(LOG_FILE) as f:
            content = f.readlines()
        return jsonify({"logs": "".join(content[-lines:])})
    except Exception as e:
        return jsonify({"logs": f"Error reading logs: {e}"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)

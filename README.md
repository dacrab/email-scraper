# Google Maps Email Scraper (Python + Selenium)

Automates Google Maps with headless Chrome to collect business websites and extract emails/phones.
Fully configurable via `config.json` and ready for Docker/Railway deployment.

---

## 1) Prerequisites

- Python 3.12+
- Google Chrome or Chromium installed locally
  - If Chrome is not on PATH, set env var or config:
    - `export CHROME_BIN=/usr/bin/google-chrome` (or your path)
    - or set `"chrome_binary"` in `config.json`

Install Python deps:

```bash
pip install -r requirements.txt
```

---

## 2) Configuration (config.json)

Example:

```json
{
  "output_filename": "recipients.csv",
  "search_term": "Construction Company",
  "locations": ["Athens", "Thessaloniki"],
  "max_results_per_query": 10,
  "phone_min_digits": 10,
  "headless": true,
  "use_threading": false,
  "max_thread_workers": 3,
  "scroll_pause_time": 2,
  "max_scroll_attempts": 20,
  "delay_between_queries_seconds_min": 3.0,
  "delay_between_queries_seconds_max": 5.0,
  "chrome_binary": null
}
```

Notes:
- `max_results_per_query`: 0 = no cap.
- `chrome_binary`: optional absolute path to Chrome/Chromium. If omitted, the app tries `CHROME_BIN`/`GOOGLE_CHROME_BIN` or common paths.

---

## 3) Run locally

```bash
python scraper.py --config config.json
```

Output goes to `recipients.csv` (configurable).

---

## 4) Docker

Build:

```bash
docker build -t email-scraper .
```

Run (mount working dir to write CSV and read config):

```bash
docker run --rm \
  -v "$(pwd)":/app \
  email-scraper \
  --config=/app/config.json
```

---

## 5) Railway

`railway.json` is configured to run:

```bash
python /app/scraper.py --config=/app/config.json
```

Edit `config.json` in the project and redeploy to change behavior.

---

## 6) Rate limiting & best practices

- Built-in realistic UA, pacing between queries, and scroll limits.
- If you hit captchas/blocks: reduce locations, cap `max_results_per_query`, increase `delay_between_queries...`, or lower `max_scroll_attempts`.

---

## 7) Legal notice

Ensure your usage complies with Google’s ToS and local laws (e.g., GDPR). Use collected data responsibly and with consent.

# Email Scraper

A web-based email scraper that extracts contact information from Google Maps business listings and their websites.

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![Flask](https://img.shields.io/badge/flask-3.0+-green.svg)
![Playwright](https://img.shields.io/badge/playwright-1.47+-orange.svg)

## Features

- **Google Maps Integration** - Searches for businesses by type and location
- **Email Extraction** - Scrapes emails from Maps listings and company websites
- **Phone Detection** - Extracts phone numbers when available
- **Modern Web Dashboard** - Clean UI with dark mode support
- **Live Logs** - Real-time scraper activity monitoring
- **Export Options** - Download results as CSV or JSON
- **Flexible Configuration** - Configure via UI, JSON file, or environment variables

## Quick Start

### Prerequisites

- Python 3.10+
- pip

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/email-scraper.git
cd email-scraper

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
python -m playwright install chromium
```

### Running Locally

```bash
# Start the web dashboard
python app.py

# Open http://localhost:8000 in your browser
```

### Running with Docker

```bash
# Build the image
docker build -t email-scraper .

# Run the container
docker run -p 8000:8000 email-scraper
```

## Configuration

Settings can be configured in three ways (in order of priority):

### 1. Environment Variables

```bash
export SCRAPER_SEARCH_TERM="Restaurant"
export SCRAPER_LOCATIONS="New York,Los Angeles,Chicago"
export SCRAPER_MAX_RESULTS=20
export SCRAPER_CONCURRENCY=5
export SCRAPER_HEADLESS=true
```

### 2. Web UI

Navigate to **Settings** in the dashboard to configure all options through the interface.

### 3. Config File

Edit `config.json`:

```json
{
  "search_term": "Construction Company",
  "locations": ["Athens", "Thessaloniki"],
  "max_results_per_query": 10,
  "max_concurrent_pages": 5,
  "headless": true,
  "scroll_pause_time": 2.0,
  "max_scroll_attempts": 20,
  "delay_between_queries_seconds_min": 3.0,
  "delay_between_queries_seconds_max": 5.0
}
```

## Configuration Options

| Option | Env Variable | Default | Description |
|--------|--------------|---------|-------------|
| `search_term` | `SCRAPER_SEARCH_TERM` | `""` | Business type to search for |
| `locations` | `SCRAPER_LOCATIONS` | `[]` | Comma-separated list of cities/regions |
| `max_results_per_query` | `SCRAPER_MAX_RESULTS` | `10` | Max results per location (0 = unlimited) |
| `max_concurrent_pages` | `SCRAPER_CONCURRENCY` | `5` | Parallel page scraping limit |
| `headless` | `SCRAPER_HEADLESS` | `true` | Run browser without UI |
| `scroll_pause_time` | `SCRAPER_SCROLL_PAUSE` | `2.0` | Seconds to wait between scrolls |
| `max_scroll_attempts` | `SCRAPER_SCROLL_ATTEMPTS` | `20` | Max scroll iterations |

## Project Structure

```
email-scraper/
├── app.py              # Flask web application
├── scraper.py          # Email scraper logic
├── config.py           # Configuration management
├── config.json         # Default configuration
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container configuration
├── start.sh            # Container startup script
├── templates/          # HTML templates
│   ├── base.html       # Base template with navigation
│   ├── index.html      # Dashboard page
│   └── config.html     # Settings page
└── static/             # Static assets
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard |
| `/config` | GET/POST | Settings page |
| `/api/status` | GET | Scraper status (JSON) |
| `/api/data` | GET | Scraped contacts (JSON) |
| `/api/logs` | GET | Scraper logs (JSON) |
| `/scraper/start` | POST | Start scraper |
| `/scraper/stop` | POST | Stop scraper |
| `/scraper/restart` | POST | Restart scraper |
| `/download/csv` | GET | Download CSV |
| `/download/json` | GET | Download JSON |
| `/clear` | POST | Clear all data |

## Deployment

### Railway

The project includes `railway.json` for easy deployment:

```bash
railway up
```

### Docker Compose

```yaml
version: '3.8'
services:
  scraper:
    build: .
    ports:
      - "8000:8000"
    environment:
      - SCRAPER_SEARCH_TERM=Restaurant
      - SCRAPER_LOCATIONS=New York,Chicago
```

## Tech Stack

- **Backend**: Flask, Gunicorn
- **Scraping**: Playwright (Chromium)
- **Frontend**: Tailwind CSS, Alpine.js
- **Containerization**: Docker

## License

MIT License - feel free to use this project for any purpose.

## Disclaimer

This tool is for educational purposes. Ensure you comply with the terms of service of any websites you scrape and respect robots.txt files. Use responsibly.

# Google Maps Email Scraper (Go + chromedp)

This project is a modern Go 1.23 rewrite of the original "Email Scraper Prowebline" tool.

It automates **Google Maps** with **chromedp** (headless Chrome), scrolls the results panel to fetch
all businesses for a given search term and list of locations, then opens each `/maps/place/` page
and optionally the business website to extract:

- Business name
- Address
- Phone
- Website (with Google Maps fallbacks)
- First real email address (using strict regex + filters)
- Rating

All results are stored **immediately** into a local **SQLite** database file:

- File: `leads_greece_2025.sqlite`
- Table: `businesses`
- Columns:
  - `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
  - `name` (TEXT)
  - `address` (TEXT)
  - `phone` (TEXT)
  - `website` (TEXT)
  - `email` (TEXT)
  - `rating` (REAL)
  - `query` (TEXT)
  - `scraped_at` (TIMESTAMP, UTC)
- Indexes:
  - `idx_businesses_email_website` (UNIQUE on `email`, `website`)
  - `idx_businesses_website` on `website`
  - `idx_businesses_email` on `email`

Special “gold” leads (businesses **without a real website** or with **only g.page links**) are
highlighted in the console as:

```text
GOLD → no website: <Business Name> (<website>)
```

These are ideal targets for web design / website offers.

---

## 1. Prerequisites

### Go and SQLite

- Go **1.23+** (earlier 1.2x versions may work but are not guaranteed)
- SQLite3 client (optional, but useful for inspecting the DB)

### Chrome / Chromium

Locally you need a Chrome/Chromium-compatible browser that **chromedp** can launch.

- On most systems, the default Chrome install is enough.
- If Chrome is not in the default path, set `CHROME_PATH`:

```bash
export CHROME_PATH=/usr/bin/google-chrome    # or your local chrome/chromium path
```

Inside Docker/Railway, the provided image already includes a minimal Chrome build.

---

## 2. Configuring the scraper (`config.json`)

The Go version keeps the **exact same `config.json` format** as the original Python script.
Example (already provided in this repo):

```json
{
  "output_filename": "recipients.csv",
  "search_term": "Construction Company",
  "locations": [
    "Thessaloniki",
    "Athens",
    "Greece"
  ],
  "max_results_per_query": 0,
  "phone_min_digits": 10,
  "headless": true,
  "use_threading": false,
  "max_thread_workers": 3,
  "scroll_pause_time": 2,
  "max_scroll_attempts": 20
}
```

Important fields:

- `search_term` – What you’re looking for (e.g. `Restaurants`, `Hotels`, `Law Firm`).
- `locations` – Array of cities/regions to combine with `search_term`, building queries like
  `"Restaurants Athens"`, `"Hotels Crete"`, etc.
- `max_results_per_query` – Optional hard cap on the number of Google Maps results (0 = no cap).
- `phone_min_digits` – Minimum number of digits for a phone number to be considered valid.
- `headless` – `true` to run Chrome headlessly (recommended for servers / Docker).
- `scroll_pause_time` – Delay in seconds between scrolls of the Maps results panel.
- `max_scroll_attempts` – Maximum scroll attempts before assuming there are no more results.

`use_threading` and `max_thread_workers` are kept for compatibility with the old config but are
not used by the Go implementation.

---

## 3. Local development and usage

### 3.1 Install Go dependencies

From the project root:

```bash
go mod tidy
```

This will download and vendor the required modules:

- `github.com/chromedp/chromedp` – headless Chrome automation
- `github.com/mattn/go-sqlite3` – SQLite driver (CGO-based)

### 3.2 Build the scraper

```bash
go build -o scraper main.go
```

This produces a `scraper` binary in the current directory.

### 3.3 Run the scraper locally

Make sure `config.json` is configured as you like, then run:

```bash
./scraper --config=config.json
```

You’ll see logs similar to:

```text
======================================================================
   EMAIL SCRAPER PROWEBLINE (Go)
   Google Maps Scraping with Browser Automation
======================================================================
[*] Configuration:
   - Headless mode: true
   - Scroll pause: 2.0s
   - Max scroll attempts: 20
[*] Starting search for 3 querie(s)...
[!] This may take 10-30 minutes depending on results...
```

For each query, the scraper will:

1. Open Google Maps search.
2. Accept the cookie banner (using the same selectors as the Python version).
3. Scroll the results panel (`div[role="feed"]`) until no new results appear.
4. Open each `/maps/place/` result directly.
5. Extract name, address, phone, rating, website (with Google Maps fallback button).
6. Extract the first real email from the page HTML using the same regex + invalid-pattern filters.
7. Optionally scan the website (and contact page) for a better email/phone.
8. Insert each business into SQLite immediately via `INSERT OR IGNORE`.

When finished you’ll see:

```text
Done! Open leads_greece_2025.sqlite with DB Browser for SQLite or DuckDB
```

---

## 4. Inspecting the SQLite database

The scraper saves everything in `leads_greece_2025.sqlite`.

You can inspect it with:

- **DB Browser for SQLite** (GUI)
- **DuckDB**:

  ```bash
  duckdb
  CREATE VIEW businesses AS SELECT * FROM read_parquet('leads_greece_2025.sqlite');  -- or open via extension
  ```

- **sqlite3 CLI**:

  ```bash
  sqlite3 leads_greece_2025.sqlite
  .schema businesses
  SELECT name, email, website, query FROM businesses LIMIT 20;
  ```

The `GOLD → no website` leads are business rows where `website` is empty or only a `g.page`
link – ideal for website offers.

---

## 5. Running in Docker

A small multi-stage Dockerfile is provided.

### 5.1 Build the image

```bash
docker build -t email-scraper-go .
```

### 5.2 Run the scraper in Docker

Mount your local directory so that `config.json` and `leads_greece_2025.sqlite` are accessible:

```bash
docker run --rm \
  -v "$(pwd)":/app \
  email-scraper-go \
  --config=/app/config.json
```

The container uses a minimal Chrome image (`ghcr.io/chromebrew/chrome`) and runs in fully
headless mode. The resulting `leads_greece_2025.sqlite` file will be written to your host
project folder.

---

## 6. Deploying on Railway

A `railway.json` is included to make deployment straightforward.

- Build is done via the provided `Dockerfile`.
- The default start command is:

  ```bash
  /scraper --config=config.json
  ```

To customize behavior in Railway:

1. Add or edit `config.json` in the Railway project repo.
2. Adjust the `search_term`, `locations`, and limits to fit your use case.
3. Redeploy – the service will automatically start running the scraper with the
   new configuration.

Remember that Railway free tiers may have resource and time limits; keep
`max_results_per_query`, `max_scroll_attempts`, and your location list conservative.

---

## 7. Rate limiting and ban-avoidance

The scraper builds in:

- **Random delays (3–7 s)** between business lookups and between queries.
- **Reasonable timeouts** for page loads.
- Headless Chrome with realistic user-agent.

Despite these precautions, Google may still apply rate limits or captchas. If that happens:

- Reduce the number of locations.
- Set a non-zero `max_results_per_query`.
- Increase `scroll_pause_time` or decrease `max_scroll_attempts`.

---

## 8. Legal and ethical notice

Scraping and outreach can be legally and ethically sensitive. **Before using this tool**:

- Check each website’s and Google’s terms of service for scraping/crawling rules.
- Respect robots.txt and be considerate about request volume.
- Comply with local data protection and privacy laws (e.g. GDPR).
- Use the collected data responsibly and only for legitimate, opt-in communication.

This project is provided for educational and research purposes only; you are solely
responsible for how you use it.

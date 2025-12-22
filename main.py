import asyncio
import csv
import json
import logging
import re
import threading
from pathlib import Path
from flask import Flask, jsonify, request, render_template, send_file
from playwright.async_api import async_playwright

# --- CONFIG & CONSTANTS ---
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "contacts.csv"
CFG_FILE = BASE_DIR / "config.json"
LOG_FILE = BASE_DIR / "scraper.log"

DEFAULT_CFG = {
    "search_terms": "Construction", "locations": "Thessaloniki",
    "headless": True, "max_results": 10, "concurrency": 10
}

# Pre-compiled Regex for Performance
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
PHONE_REGEX = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")

# --- LOGGING ---
class MemoryHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.buffer = []

    def emit(self, record):
        self.buffer.append(self.format(record))
        if len(self.buffer) > 100:
            self.buffer.pop(0)

log_handler = MemoryHandler()
log = logging.getLogger("scraper")
log.setLevel(logging.INFO)
log.addHandler(log_handler)
log.addHandler(logging.FileHandler(LOG_FILE))
log.addHandler(logging.StreamHandler())
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# --- SCRAPER ENGINE ---
class Engine:
    def __init__(self):
        self.active = False
        self.data = []
        self._load_csv()

    def _load_csv(self):
        if DB_FILE.exists():
            with open(DB_FILE, "r", encoding="utf-8") as f:
                self.data = list(csv.DictReader(f))

    def save(self):
        fields = ["Company", "Email", "Phone", "Website", "Category", "Address", "Rating", "Reviews", "Maps URL"]
        tmp = f"{DB_FILE}.tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(self.data)
        Path(tmp).replace(DB_FILE)

    async def run(self, cfg):
        self.active = True
        log.info("Starting optimized scraper...")
        terms = [s.strip() for s in cfg["search_terms"].split(",") if s.strip()]
        locations = [loc.strip() for loc in cfg["locations"].split(",") if loc.strip()]
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=cfg["headless"])
            for q in [f"{t} {loc}" for t in terms for loc in locations]:
                if not self.active:
                    break
                await self.scrape_maps(browser, q, int(cfg.get("max_results", 10)))
            
            # High-Concurrency Enrichment
            sites = [r for r in self.data if r.get("Website") and not r.get("Email")]
            if sites and self.active:
                log.info(f"Enriching {len(sites)} websites...")
                sem = asyncio.Semaphore(cfg.get("concurrency", 10))
                await asyncio.gather(*[self.scrape_site(browser, r, sem) for r in sites])
            await browser.close()
        self.active = False
        log.info("Job finished.")

    async def scrape_maps(self, browser, q, limit):
        ctx = await browser.new_context(viewport={'width': 1200, 'height': 800})
        page = await ctx.new_page()
        try:
            log.info(f"Searching: {q}")
            await page.goto(f"https://www.google.com/maps/search/{q.replace(' ', '+')}", wait_until="domcontentloaded")
            
            # Consent Bypass
            try:
                for sel in ["button[aria-label*='Accept']", "button[aria-label*='agree']", "button[aria-label*='Αποδοχή']"]:
                    btn = await page.query_selector(sel)
                    if btn:
                        await btn.click()
                        break
            except Exception:
                pass

            await asyncio.sleep(2)
            if "/maps/place/" in page.url:
                urls = [page.url]
            else:
                # Optimized Scrolling
                last_count = 0
                for _ in range(20):
                    await page.mouse.wheel(0, 4000)
                    await asyncio.sleep(1.5)
                    found = await page.query_selector_all("a.hfpxzc")
                    if len(found) == last_count:
                        break
                    last_count = len(found)
                    if limit > 0 and len(found) >= limit:
                        break
                
                links = await page.query_selector_all("a.hfpxzc")
                urls = []
                for link in links:
                    href = await link.get_attribute("href")
                    if href:
                        urls.append(href)
                
                if limit > 0:
                    urls = urls[:limit]

            log.info(f"Processing {len(urls)} listings...")
            for url in urls:
                if not self.active:
                    break
                if any(r.get("Maps URL") == url for r in self.data):
                    continue
                
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_selector("h1.DUwDvf", timeout=5000)
                
                res = {
                    "Company": await self._text(page, "h1.DUwDvf"),
                    "Category": await self._text(page, "button.DkEaL"),
                    "Address": (await self._text(page, "button[data-item-id='address']")).replace("", "").strip(),
                    "Phone": (await self._text(page, "button[data-item-id*='phone:tel:']")).replace("", "").strip(),
                    "Website": "", "Email": "",
                    "Rating": await self._text(page, "div.F7nice span span[aria-hidden='true']"),
                    "Reviews": (await self._text(page, "div.F7nice span[aria-label*='reviews']")).strip("()"),
                    "Maps URL": url
                }
                
                wb_el = await page.query_selector("a[data-item-id='authority']")
                if wb_el:
                    href = await wb_el.get_attribute("href")
                    if href and not any(d in href.lower() for d in ["google.com", "facebook.com", "instagram.com"]):
                        res["Website"] = href.split("?")[0].rstrip("/")
                
                self.data.append(res)
                log.info(f"Captured: {res['Company']}")
                self.save()
        finally:
            await ctx.close()

    async def scrape_site(self, browser, res, sem):
        async with sem:
            if not self.active:
                return
            ctx = await browser.new_context()
            await ctx.route("**/*.{png,jpg,jpeg,gif,webp,svg,css,woff,woff2}", lambda r: r.abort())
            page = await ctx.new_page()
            try:
                await page.goto(res["Website"], timeout=15000)
                html = await page.content()
                res["Email"] = self._extract_email(html)
                if not res["Phone"]:
                    res["Phone"] = self._extract_phone(html)
                self.save()
            except Exception:
                pass
            finally:
                await ctx.close()

    def _extract_email(self, html):
        m = EMAIL_REGEX.search(html)
        return m.group(0).lower() if m else ""

    def _extract_phone(self, html):
        m = PHONE_REGEX.search(html)
        return m.group(0) if m else ""

    async def _text(self, page, sel):
        try:
            return await page.eval_on_selector(sel, "el => el.innerText")
        except Exception:
            return ""

engine = Engine()
app = Flask(__name__)

def load_cfg():
    if CFG_FILE.exists():
        return json.loads(CFG_FILE.read_text())
    return DEFAULT_CFG

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def status():
    return jsonify({
        "running": engine.active, 
        "leads": engine.data, 
        "logs": log_handler.buffer, 
        "config": load_cfg()
    })

@app.route("/control/<action>", methods=["POST"])
def control(action):
    if action == "start" and not engine.active:
        threading.Thread(target=lambda: asyncio.run(engine.run(load_cfg()))).start()
    elif action == "stop":
        engine.active = False
    elif action == "clear":
        engine.data = []
        if DB_FILE.exists():
            DB_FILE.unlink()
        log.info("Results cleared.")
    return jsonify({"success": True})

@app.route("/config", methods=["POST"])
def save_config():
    CFG_FILE.write_text(json.dumps(request.json))
    return jsonify({"success": True})

@app.route("/download")
def download():
    return send_file(DB_FILE, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
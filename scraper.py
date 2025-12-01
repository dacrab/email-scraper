"""Email scraper using Playwright for Google Maps and company websites."""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import random
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from config import (
    CONTACT_KEYWORDS,
    EMAIL_REGEX,
    INVALID_EMAIL_PATTERNS,
    MAPS_RESULT_SELECTORS,
    PHONE_PATTERNS,
    SKIP_DOMAINS,
    BASE_DIR,
    ScraperConfig,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-notifications",
    "--disable-popup-blocking",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class EmailScraper:
    """Scrapes emails from Google Maps results and company websites."""

    def __init__(self, config: ScraperConfig) -> None:
        self.config = config
        self.output_path = config.output_path
        self.emails: dict[str, str] = {}
        self.phones: dict[str, str] = {}
        self.visited: set[str] = set()
        self.pw: Playwright | None = None
        self.browser: Browser | None = None
        self._status = "idle"
        self._progress = 0
        self._total = 0
        self._load_existing()

    @property
    def status(self) -> dict:
        return {
            "state": self._status,
            "progress": self._progress,
            "total": self._total,
            "emails_found": len(self.emails),
        }

    def _load_existing(self) -> None:
        if not self.output_path.exists():
            return
        try:
            with self.output_path.open() as f:
                for row in csv.DictReader(f):
                    if email := row.get("Email"):
                        self.emails[email] = row.get("Website", "")
                    if (website := row.get("Website")) and (phone := row.get("Phone")):
                        self.phones[website] = phone
                        self.visited.add(website)
            log.info(f"Loaded {len(self.emails)} existing records")
        except Exception as e:
            log.warning(f"Failed to load existing data: {e}")

    async def start(self) -> None:
        self._status = "starting"
        self.pw = await async_playwright().start()
        try:
            self.browser = await self.pw.chromium.launch(headless=self.config.headless, args=BROWSER_ARGS)
        except Exception:
            import subprocess
            subprocess.run(["python", "-m", "playwright", "install", "--with-deps", "chromium"], check=True)
            self.browser = await self.pw.chromium.launch(headless=self.config.headless, args=BROWSER_ARGS)
        self._status = "running"

    async def stop(self) -> None:
        self._status = "stopping"
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()
        self._status = "idle"

    async def _new_context(self) -> BrowserContext:
        ctx = await self.browser.new_context(user_agent=USER_AGENT)
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,svg,css,woff,woff2,mp4,mp3}", lambda r: r.abort())
        return ctx

    def _extract_emails(self, text: str) -> list[str]:
        return [
            e for e in re.findall(EMAIL_REGEX, text, re.IGNORECASE)
            if not any(p in e.lower() for p in INVALID_EMAIL_PATTERNS)
        ]

    def _extract_phone(self, text: str) -> str | None:
        for pattern in PHONE_PATTERNS:
            for match in re.findall(pattern, text):
                digits = re.sub(r"\D", "", match)
                if self.config.phone_min_digits <= len(digits) <= 15 and len(set(digits)) > 1:
                    return match
        return None

    def _record(self, url: str, emails: list[str], phone: str | None = None) -> None:
        for email in emails:
            if email.lower() not in (e.lower() for e in self.emails):
                self.emails[email] = url
                log.info(f"Found: {email}")
        if phone and url not in self.phones:
            self.phones[url] = phone

    async def _accept_cookies(self, page: Page) -> None:
        for selector in ["button[aria-label='Accept all']", "button[jsname='b3VHJd']"]:
            try:
                if el := await page.query_selector(selector):
                    await el.click()
                    return
            except Exception:
                pass

    async def scrape_maps(self, query: str, max_results: int = 0) -> list[str]:
        log.info(f"Maps search: '{query}'")
        ctx = await self._new_context()
        page = await ctx.new_page()
        websites = []

        try:
            await page.goto(f"https://www.google.com/maps/search/{query.replace(' ', '+')}", wait_until="domcontentloaded")
            await self._accept_cookies(page)
            await asyncio.sleep(3)

            selector = None
            for s in MAPS_RESULT_SELECTORS:
                if await page.query_selector(s):
                    selector = s
                    break
            if not selector:
                log.warning("No results found")
                return websites

            urls: set[str] = set()
            stale_count = 0
            for _ in range(self.config.max_scroll_attempts):
                links = await page.query_selector_all(selector)
                new_urls = set()
                for el in links:
                    href = await el.get_attribute("href")
                    if href and "/maps/place/" in href:
                        new_urls.add(href)
                if new_urls - urls:
                    urls.update(new_urls)
                    stale_count = 0
                else:
                    stale_count += 1
                    if stale_count >= 3:
                        break
                if panel := await page.query_selector("div[role='feed']"):
                    await panel.evaluate("el => el.scrollTop = el.scrollHeight")
                await asyncio.sleep(self.config.scroll_pause_time)

            result_urls = list(urls)[:max_results] if max_results else list(urls)
            log.info(f"Found {len(result_urls)} business listings")

            for url in result_urls:
                try:
                    await page.goto(url, wait_until="domcontentloaded")
                    await asyncio.sleep(0.5)
                    content = await page.content()

                    if emails := self._extract_emails(content):
                        self._record(url, emails, self._extract_phone(content))

                    website = None
                    if wb := await page.query_selector("a[data-item-id='authority']"):
                        website = await wb.get_attribute("href")
                    if website and not any(d in website.lower() for d in SKIP_DOMAINS):
                        clean = website.split("?")[0].split("#")[0]
                        if clean not in websites:
                            websites.append(clean)
                except Exception:
                    continue

        except Exception as e:
            log.error(f"Maps error: {e}")
        finally:
            await ctx.close()

        return websites

    async def scrape_website(self, url: str, sem: asyncio.Semaphore) -> None:
        if url in self.visited:
            return
        self.visited.add(url)

        async with sem:
            ctx = await self._new_context()
            page = await ctx.new_page()
            try:
                log.debug(f"Scraping: {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1)

                content = await page.content()
                if emails := self._extract_emails(content):
                    self._record(url, emails, self._extract_phone(content))
                else:
                    for keyword in CONTACT_KEYWORDS:
                        try:
                            link = await page.query_selector(f"a:has-text('{keyword}')")
                            if link and (href := await link.get_attribute("href")) and href.startswith("http") and href not in self.visited:
                                self.visited.add(href)
                                await page.goto(href, wait_until="domcontentloaded", timeout=20000)
                                if emails := self._extract_emails(await page.content()):
                                    self._record(href, emails)
                                break
                        except Exception:
                            continue
            except Exception:
                pass
            finally:
                await ctx.close()
            self._progress += 1

    def save(self) -> None:
        rows = {}
        for email, url in self.emails.items():
            key = email.lower()
            if key not in rows:
                domain = urlparse(url).netloc.replace("www.", "").split(".")[0] if url else "unknown"
                company = " ".join(w.capitalize() for w in domain.replace("-", " ").replace("_", " ").split())
                rows[key] = [company, email, self.phones.get(url, ""), url]

        sorted_rows = sorted(rows.values(), key=lambda r: (r[0].lower(), r[1].lower()))
        tmp = f"{self.output_path}.tmp"
        with open(tmp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Company", "Email", "Phone", "Website"])
            w.writerows(sorted_rows)
        os.replace(tmp, self.output_path)

    async def run(self) -> None:
        queries = [f"{self.config.search_term} {loc}" for loc in self.config.locations]
        self._total = len(queries)
        log.info(f"Running {len(queries)} queries...")

        await self.start()
        if not self.browser:
            return

        websites: list[str] = []
        for i, query in enumerate(queries, 1):
            log.info(f"Query {i}/{len(queries)}: {query}")
            websites.extend(await self.scrape_maps(query, self.config.max_results_per_query))
            if i < len(queries):
                delay = random.uniform(*self.config.delay_range)
                await asyncio.sleep(delay)

        unique = list(set(websites))
        self._total = len(unique)
        self._progress = 0
        log.info(f"Scanning {len(unique)} websites...")

        sem = asyncio.Semaphore(self.config.max_concurrent_pages)
        for i in range(0, len(unique), 10):
            await asyncio.gather(*[self.scrape_website(u, sem) for u in unique[i:i+10]])
            self.save()
            log.info(f"Progress: {len(self.emails)} emails found")

        self.save()
        self._status = "completed"
        log.info(f"Done! {len(self.emails)} emails saved to {self.output_path}")
        await self.stop()


async def main() -> None:
    log.info("=" * 40)
    log.info("EMAIL SCRAPER")
    log.info("=" * 40)

    parser = argparse.ArgumentParser(description="Email scraper for Google Maps")
    parser.add_argument("--config", default=os.environ.get("SCRAPER_CONFIG"), help="Path to config file")
    args = parser.parse_args()

    config = ScraperConfig.load(args.config)
    if not config.search_term:
        log.error("search_term required in config or SCRAPER_SEARCH_TERM env var")
        return

    scraper = EmailScraper(config)
    try:
        await scraper.run()
    finally:
        await scraper.stop()


if __name__ == "__main__":
    asyncio.run(main())

"""Email scraper engine using Playwright."""

from __future__ import annotations

import asyncio
import csv
import logging
import os
import random
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from config import ScraperConfig
from constants import (
    CONTACT_KEYWORDS,
    EMAIL_REGEX,
    INVALID_EMAIL_PATTERNS,
    MAPS_RESULT_SELECTORS,
    PHONE_PATTERNS,
    SKIP_DOMAINS,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


class EmailScraper:
    """Scrapes emails and phones from Google Maps and company websites."""

    def __init__(self, config: ScraperConfig) -> None:
        self.config = config
        self.emails: dict[str, str] = {}
        self.phones: dict[str, str] = {}
        self.visited: set[str] = set()
        self.pw: Playwright | None = None
        self.browser: Browser | None = None
        
        self._load_existing()

    def _load_existing(self) -> None:
        """Loads existing data from the output file to avoid duplicates."""
        path = self.config.output_path
        if not path.exists():
            return
        try:
            with path.open(encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if email := row.get("Email"):
                        self.emails[email.lower()] = row.get("Website", "")
                    if (website := row.get("Website")) and (phone := row.get("Phone")):
                        self.phones[website] = phone
                        self.visited.add(website)
            log.info(f"Loaded {len(self.emails)} existing records")
        except Exception as e:
            log.warning(f"Failed to load existing data: {e}")

    async def _setup_browser(self) -> None:
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(
            headless=self.config.HEADLESS,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        )

    async def _cleanup(self) -> None:
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()
        
        # Cleanup PID file if we are the ones who created it
        if self.config.PID_FILE.exists():
            try:
                if self.config.PID_FILE.read_text().strip() == str(os.getpid()):
                    self.config.PID_FILE.unlink()
            except OSError:
                pass

    async def _new_context(self) -> BrowserContext:
        if not self.browser:
            raise RuntimeError("Browser not initialized")
            
        ctx = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        # Block media and CSS to speed up
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,svg,css,woff,woff2,mp4,mp3}", lambda r: r.abort())
        return ctx

    def _extract_data(self, url: str, content: str) -> None:
        """Extracts emails and phones from page content."""
        # Emails
        for email in re.findall(EMAIL_REGEX, content, re.IGNORECASE):
            email_lower = email.lower()
            if not any(p in email_lower for p in INVALID_EMAIL_PATTERNS):
                if email_lower not in self.emails:
                    self.emails[email_lower] = url
                    log.info(f"Found: {email} ({url})")

        # Phones
        for pattern in PHONE_PATTERNS:
            for match in re.findall(pattern, content):
                digits = re.sub(r"\D", "", match)
                if self.config.PHONE_MIN_DIGITS <= len(digits) <= 15 and len(set(digits)) > 1:
                    if url not in self.phones:
                        self.phones[url] = match
                    break

    async def scrape_maps(self, query: str) -> list[str]:
        """Scrapes website URLs from Google Maps search results."""
        log.info(f"Maps search: '{query}'")
        websites = []
        ctx = await self._new_context()
        page = await ctx.new_page()

        try:
            await page.goto(f"https://www.google.com/maps/search/{query.replace(' ', '+')}", wait_until="domcontentloaded")
            
            # Privacy consent
            try:
                if btn := await page.query_selector("button[aria-label='Accept all']"):
                    await btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            # Find valid results selector
            selector = next((s for s in MAPS_RESULT_SELECTORS if await page.query_selector(s)), None)
            if not selector:
                return websites

            # Infinite scroll
            seen_urls = set()
            for _ in range(self.config.MAX_SCROLL_ATTEMPTS):
                elements = await page.query_selector_all(selector)
                urls = {await e.get_attribute("href") for e in elements}
                urls = {u for u in urls if u and "/maps/place/" in u}
                
                if len(urls) <= len(seen_urls):
                    if _ > 2: break # No more results
                seen_urls = urls
                
                if panel := await page.query_selector("div[role='feed']"):
                    await panel.evaluate("el => el.scrollTop = el.scrollHeight")
                await asyncio.sleep(self.config.SCROLL_PAUSE_TIME)

            # Process listings
            listings = list(seen_urls)[:self.config.MAX_RESULTS_PER_QUERY] if self.config.MAX_RESULTS_PER_QUERY else list(seen_urls)
            for url in listings:
                try:
                    await page.goto(url, wait_until="domcontentloaded")
                    self._extract_data(url, await page.content())
                    
                    if wb_btn := await page.query_selector("a[data-item-id='authority']"):
                        if wb_url := await wb_btn.get_attribute("href"):
                            if not any(d in wb_url.lower() for d in SKIP_DOMAINS):
                                clean_url = wb_url.split("?")[0].split("#")[0].rstrip("/")
                                if clean_url not in websites:
                                    websites.append(clean_url)
                except Exception:
                    continue
        except Exception as e:
            log.error(f"Maps error: {e}")
        finally:
            await ctx.close()
        return websites

    async def scrape_website(self, url: str, sem: asyncio.Semaphore) -> None:
        """Visits a website and its contact page to find data."""
        if url in self.visited: return
        self.visited.add(url)

        async with sem:
            ctx = await self._new_context()
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                self._extract_data(url, await page.content())
                
                # Check for contact page
                for kw in CONTACT_KEYWORDS:
                    try:
                        link = await page.query_selector(f"a[href*='{kw}'], a:text-matches('{kw}', 'i')")
                        if link:
                            href = await link.get_attribute("href")
                            if href and href.startswith("http") and href not in self.visited:
                                self.visited.add(href)
                                await page.goto(href, wait_until="domcontentloaded", timeout=20000)
                                self._extract_data(href, await page.content())
                                break
                    except Exception:
                        continue
            except Exception:
                pass
            finally:
                await ctx.close()

    def save_results(self) -> None:
        """Atomic save of results to CSV."""
        if not self.emails: return

        rows = []
        for email, url in self.emails.items():
            domain = urlparse(url).netloc.replace("www.", "").split(".")[0] if url else "unknown"
            company = domain.replace("-", " ").replace("_", " ").title()
            rows.append([company, email, self.phones.get(url, ""), url])

        temp = f"{self.config.output_path}.tmp"
        try:
            with open(temp, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Company", "Email", "Phone", "Website"])
                writer.writerows(sorted(rows, key=lambda x: x[0]))
            os.replace(temp, self.config.output_path)
        except Exception as e:
            log.error(f"Save error: {e}")

    async def run(self) -> None:
        """Main execution flow."""
        queries = [f"{self.config.SEARCH_TERM} {loc}" for loc in self.config.LOCATIONS] or [self.config.SEARCH_TERM]
        if not any(queries):
            log.error("No search criteria provided.")
            return

        try:
            await self._setup_browser()
            
            all_sites = []
            for q in queries:
                sites = await self.scrape_maps(q)
                all_sites.extend(sites)
                self.save_results()
                await asyncio.sleep(random.uniform(*self.config.delay_range))

            unique_sites = list(set(all_sites))
            log.info(f"Scanning {len(unique_sites)} websites...")

            sem = asyncio.Semaphore(self.config.MAX_CONCURRENT_PAGES)
            for i in range(0, len(unique_sites), 10):
                chunk = unique_sites[i : i + 10]
                await asyncio.gather(*(self.scrape_website(s, sem) for s in chunk))
                self.save_results()
        finally:
            await self._cleanup()
            log.info("Job completed.")


async def main() -> None:
    config = ScraperConfig()
    config.PID_FILE.write_text(str(os.getpid()))
    try:
        await EmailScraper(config).run()
    except Exception as e:
        log.error(f"Main error: {e}")
    finally:
        if config.PID_FILE.exists():
            config.PID_FILE.unlink()

if __name__ == "__main__":
    asyncio.run(main())

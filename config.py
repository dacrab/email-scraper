"""Configuration management with environment variable and file support."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_FILE = BASE_DIR / "config.json"
DEFAULT_OUTPUT_FILE = BASE_DIR / "recipients.csv"
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key, "").lower()
    if val in ("1", "true", "yes"):
        return True
    if val in ("0", "false", "no"):
        return False
    return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def _env_list(key: str, default: list[str]) -> list[str]:
    val = os.environ.get(key)
    if val:
        return [x.strip() for x in val.split(",") if x.strip()]
    return default


@dataclass
class ScraperConfig:
    """Scraper configuration with env var and file support."""

    search_term: str = ""
    locations: list[str] = field(default_factory=list)
    output_filename: str = "recipients.csv"
    max_results_per_query: int = 10
    max_concurrent_pages: int = 5
    phone_min_digits: int = 10
    headless: bool = True
    scroll_pause_time: float = 2.0
    max_scroll_attempts: int = 20
    delay_min: float = 3.0
    delay_max: float = 5.0

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> ScraperConfig:
        """Load config with priority: env vars > file > defaults."""
        file_data: dict[str, Any] = {}
        path = Path(config_path) if config_path else DEFAULT_CONFIG_FILE

        if path.exists():
            try:
                with path.open() as f:
                    file_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        return cls(
            search_term=os.environ.get("SCRAPER_SEARCH_TERM", file_data.get("search_term", "")),
            locations=_env_list("SCRAPER_LOCATIONS", file_data.get("locations", [])),
            output_filename=os.environ.get("SCRAPER_OUTPUT", file_data.get("output_filename", "recipients.csv")),
            max_results_per_query=_env_int("SCRAPER_MAX_RESULTS", file_data.get("max_results_per_query", 10)),
            max_concurrent_pages=_env_int("SCRAPER_CONCURRENCY", file_data.get("max_concurrent_pages", 5)),
            phone_min_digits=_env_int("SCRAPER_PHONE_MIN_DIGITS", file_data.get("phone_min_digits", 10)),
            headless=_env_bool("SCRAPER_HEADLESS", file_data.get("headless", True)),
            scroll_pause_time=_env_float("SCRAPER_SCROLL_PAUSE", file_data.get("scroll_pause_time", 2.0)),
            max_scroll_attempts=_env_int("SCRAPER_SCROLL_ATTEMPTS", file_data.get("max_scroll_attempts", 20)),
            delay_min=_env_float("SCRAPER_DELAY_MIN", file_data.get("delay_between_queries_seconds_min", 3.0)),
            delay_max=_env_float("SCRAPER_DELAY_MAX", file_data.get("delay_between_queries_seconds_max", 5.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        d["delay_between_queries_seconds_min"] = d.pop("delay_min")
        d["delay_between_queries_seconds_max"] = d.pop("delay_max")
        return d

    def save(self, config_path: str | Path | None = None) -> None:
        """Save configuration to JSON file."""
        path = Path(config_path) if config_path else DEFAULT_CONFIG_FILE
        with path.open("w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @property
    def delay_range(self) -> tuple[float, float]:
        return (self.delay_min, self.delay_max)

    @property
    def output_path(self) -> Path:
        return BASE_DIR / self.output_filename


# Scraping patterns and constants
EMAIL_REGEX = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"

PHONE_PATTERNS = [
    r"\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}",
    r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
]

INVALID_EMAIL_PATTERNS = [
    "example.com", "@example", ".png", ".jpg", ".gif", ".webp", ".svg",
    "sampleemail", "youremail", "noreply", "wixpress", "sentry",
    "qodeinteractive", "placeholder", "test@", "email@",
]

SKIP_DOMAINS = [
    "google", "facebook", "instagram", "youtube", "linkedin",
    "twitter", "gstatic", "googleapis", "schema.org", "yelp",
    "tripadvisor", "booking.com",
]

CONTACT_KEYWORDS = ["contact", "kontakt", "contacto", "contatto", "contactez", "impressum", "about", "reach"]

MAPS_RESULT_SELECTORS = [
    "a[href*='/maps/place/']",
    "div.Nv2PK a",
    "a.hfpxzc",
    "div[role='article'] a",
]

"""Configuration management using Pydantic Settings."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class ScraperConfig(BaseSettings):
    """Scraper configuration with environment variable support."""

    # Core settings
    SEARCH_TERM: str = ""
    LOCATIONS: list[str] = []
    OUTPUT_FILENAME: str = "contacts.csv"

    # Scraping behavior
    MAX_RESULTS_PER_QUERY: int = 10
    MAX_CONCURRENT_PAGES: int = 5
    PHONE_MIN_DIGITS: int = 10
    HEADLESS: bool = True
    
    # Timing and Throttle
    SCROLL_PAUSE_TIME: float = 2.0
    MAX_SCROLL_ATTEMPTS: int = 20
    DELAY_MIN: float = 3.0
    DELAY_MAX: float = 5.0

    # Paths
    BASE_DIR: ClassVar[Path] = Path(__file__).resolve().parent
    TEMPLATE_DIR: ClassVar[Path] = BASE_DIR / "templates"
    STATIC_DIR: ClassVar[Path] = BASE_DIR / "static"
    LOG_FILE: ClassVar[Path] = BASE_DIR / "scraper.log"
    PID_FILE: ClassVar[Path] = BASE_DIR / "scraper.pid"

    model_config = SettingsConfigDict(
        env_prefix="SCRAPER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def output_path(self) -> Path:
        return self.BASE_DIR / self.OUTPUT_FILENAME

    @property
    def delay_range(self) -> tuple[float, float]:
        return (self.DELAY_MIN, self.DELAY_MAX)

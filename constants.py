"""Constants and regex patterns for the email scraper."""

# Regex Patterns
EMAIL_REGEX = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"

PHONE_PATTERNS = [
    r"\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}",
    r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
]

# Filtering Patterns
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

# Scraping Selectors
MAPS_RESULT_SELECTORS = [
    "a[href*='/maps/place/']",
    "div.Nv2PK a",
    "a.hfpxzc",
    "div[role='article'] a",
]

CONTACT_KEYWORDS = ["contact", "kontakt", "contacto", "contatto", "contactez", "impressum", "about", "reach"]

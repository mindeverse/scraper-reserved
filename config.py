"""Reserved scraper configuration."""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    BRAND_NAME: str = "Reserved"
    SOURCE: str = "scraper-reserved"
    BRAND_COLUMN: str = "Reserved"
    SECOND_HAND: bool = False
    LANDING_PAGE: str = "https://www.reserved.com/ie/en"
    BASE_URL: str = "https://www.reserved.com"
    CURRENCY: str = "EUR"
    PRODUCTS_JSON_LIMIT: int = 200

    SUPABASE_URL: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    SUPABASE_KEY: str = field(default_factory=lambda: os.getenv("SUPABASE_KEY", ""))

    EMBEDDING_MODEL: str = "google/siglip-base-patch16-384"
    EMBEDDING_DIM: int = 768
    EMBEDDING_VERSION: int = 2
    RATE_LIMIT_DELAY: float = 0.1
    BATCH_SIZE: int = 50
    STALE_MISS_THRESHOLD: int = 2
    REQUEST_TIMEOUT: int = 60
    SCRAPE_WORKERS: int = 1
    DOWNLOAD_WORKERS: int = 30
    TEXT_EMBED_BATCH_SIZE: int = 32
    USER_AGENT: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    GENDER_DEFAULT: str = "Unisex"


cfg = Config()

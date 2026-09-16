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

    CATEGORY_URLS: list[str] = field(default_factory=lambda: [
        "https://www.reserved.com/ie/en/men/shirts/view-all",
        "https://www.reserved.com/ie/en/men/t-shirts/view-all",
        "https://www.reserved.com/ie/en/men/premium-quality/view-all",
        "https://www.reserved.com/ie/en/men/trousers/view-all",
        "https://www.reserved.com/ie/en/men/shorts/view-all",
        "https://www.reserved.com/ie/en/men/jeans/view-all",
        "https://www.reserved.com/ie/en/men/coats-jackets/view-all",
        "https://www.reserved.com/ie/en/men/suits/view-all",
        "https://www.reserved.com/ie/en/men/jackets",
        "https://www.reserved.com/ie/en/men/polos",
        "https://www.reserved.com/ie/en/men/sweaters/view-all",
        "https://www.reserved.com/ie/en/men/sweatshirts/view-all",
        "https://www.reserved.com/ie/en/men/retravel/see-all",
        "https://www.reserved.com/ie/en/men/tracksuits",
        "https://www.reserved.com/ie/en/men/basic",
        "https://www.reserved.com/ie/en/men/shoes-and-accessories/shoes",
        "https://www.reserved.com/ie/en/men/underwear/beach-shorts",
        "https://www.reserved.com/ie/en/special-offer/men/t-shirts-polos",
        "https://www.reserved.com/ie/en/men/modern-classics",
        "https://www.reserved.com/ie/en/men/linen",
        "https://www.reserved.com/ie/en/men/beachwear-collection/view-all",
        "https://www.reserved.com/ie/en/men/shoes-and-accessories",
        "https://www.reserved.com/ie/en/men/active",
        "https://www.reserved.com/ie/en/men/back-to-city/view-all",
        "https://www.reserved.com/ie/en/women/back-to-city/view-all",
        "https://www.reserved.com/ie/en/women/most-popular",
        "https://www.reserved.com/ie/en/women/dresses/view-all",
        "https://www.reserved.com/ie/en/women/shirts-blouses/view-all",
        "https://www.reserved.com/ie/en/women/blazers-vests/view-all",
        "https://www.reserved.com/ie/en/women/outerwear/view-all",
        "https://www.reserved.com/ie/en/women/t-shirts-tops-body/view-all",
        "https://www.reserved.com/ie/en/women/jeans/view-all",
        "https://www.reserved.com/ie/en/women/trousers/view-all",
        "https://www.reserved.com/ie/en/women/sets/view-all",
        "https://www.reserved.com/ie/en/women/premium-quality/view-all",
        "https://www.reserved.com/ie/en/women/sweaters/view-all",
        "https://www.reserved.com/ie/en/women/sweatshirts/view-all",
        "https://www.reserved.com/ie/en/women/shorts/view-all",
        "https://www.reserved.com/ie/en/women/skirts/view-all",
        "https://www.reserved.com/ie/en/women/basic",
        "https://www.reserved.com/ie/en/women/for-mom",
        "https://www.reserved.com/ie/en/women/shoes/view-all",
        "https://www.reserved.com/ie/en/women/accessories/bags",
        "https://www.reserved.com/ie/en/women/underwear-beachwear/see-collection",
        "https://www.reserved.com/ie/en/special-offer/women/dresses-jumpsuits",
        "https://www.reserved.com/ie/en/women/trends/office-look",
        "https://www.reserved.com/ie/en/women/trends/polka-dots",
        "https://www.reserved.com/ie/en/women/modern-classics",
        "https://www.reserved.com/ie/en/women/linen",
        "https://www.reserved.com/ie/en/women/beachwear-collection/view-all",
    ])

    CATEGORY_DISPLAY: dict[str, str] = field(default_factory=lambda: {
        "shirts": "Shirts",
        "t-shirts": "T-Shirts",
        "premium-quality": "Premium Quality",
        "trousers": "Trousers",
        "shorts": "Shorts",
        "jeans": "Jeans",
        "coats-jackets": "Coats & Jackets",
        "suits": "Suits",
        "jackets": "Jackets",
        "polos": "Polos",
        "sweaters": "Sweaters",
        "sweatshirts": "Sweatshirts",
        "retravel": "ReTravel",
        "tracksuits": "Tracksuits",
        "basic": "Basic",
        "shoes": "Shoes",
        "beach-shorts": "Beach Shorts",
        "modern-classics": "Modern Classics",
        "linen": "Linen",
        "beachwear-collection": "Beachwear",
        "shoes-and-accessories": "Shoes & Accessories",
        "active": "Active",
        "back-to-city": "Back to City",
        "most-popular": "Most Popular",
        "dresses": "Dresses",
        "shirts-blouses": "Shirts & Blouses",
        "blazers-vests": "Blazers & Vests",
        "outerwear": "Outerwear",
        "t-shirts-tops-body": "T-Shirts, Tops & Body",
        "sets": "Sets",
        "skirts": "Skirts",
        "for-mom": "For Mom",
        "bags": "Bags",
        "underwear-beachwear": "Underwear & Beachwear",
        "dresses-jumpsuits": "Dresses & Jumpsuits",
        "office-look": "Office Look",
        "polka-dots": "Polka Dots",
        "view-all": "View All",
    })

    SUPABASE_URL: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    SUPABASE_KEY: str = field(default_factory=lambda: os.getenv("SUPABASE_KEY", ""))

    EMBEDDING_MODEL: str = "google/siglip-base-patch16-384"
    EMBEDDING_DIM: int = 768
    EMBEDDING_VERSION: int = 2
    RATE_LIMIT_DELAY: float = 0.2
    BATCH_SIZE: int = 50
    STALE_MISS_THRESHOLD: int = 2
    REQUEST_TIMEOUT: int = 30
    SCRAPE_WORKERS: int = 8
    DOWNLOAD_WORKERS: int = 30
    TEXT_EMBED_BATCH_SIZE: int = 32
    USER_AGENT: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    GENDER_DEFAULT: str = "Unisex"

    # Reserved arch API
    STORE_ID: int = 1065
    ARCH_API_BASE: str = "https://arch.reserved.com/api"


cfg = Config()

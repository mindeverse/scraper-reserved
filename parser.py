"""Reserved parser — scrape arch listing API, parse products."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import cfg

logger = logging.getLogger(__name__)

BACK_KEYWORDS = ("back", "rear", "_b.", "_back", "-back", "backview", "back_view")

# Shared session with connection pooling and retry strategy
_session: requests.Session | None = None
_session_lock = threading.Lock()


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                _session = requests.Session()
                retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
                adapter = HTTPAdapter(
                    max_retries=retry,
                    pool_connections=cfg.SCRAPE_WORKERS,
                    pool_maxsize=cfg.SCRAPE_WORKERS,
                )
                _session.mount("https://", adapter)
                _session.mount("http://", adapter)
                _session.headers.update(_headers())
    return _session


def _headers() -> dict[str, str]:
    return {
        "User-Agent": cfg.USER_AGENT,
        "Accept": "application/json,text/html,*/*",
        "Accept-Language": "en-IE,en;q=0.9",
    }


# Semaphore to control concurrent requests to a single domain
_request_semaphore = threading.Semaphore(cfg.SCRAPE_WORKERS)
_last_request_time = 0.0
_rate_lock = threading.Lock()


def _rate_limited_get(url: str, timeout: int = 30) -> requests.Response:
    """Get with per-domain rate limiting and connection pooling."""
    global _last_request_time
    with _request_semaphore:
        with _rate_lock:
            elapsed = time.monotonic() - _last_request_time
            if elapsed < cfg.RATE_LIMIT_DELAY:
                time.sleep(cfg.RATE_LIMIT_DELAY - elapsed)
            _last_request_time = time.monotonic()
        session = _get_session()
        return session.get(url, timeout=timeout)


def _stable_id(product_url: str) -> str:
    digest = hashlib.sha256(f"{cfg.SOURCE}:{product_url}".encode()).hexdigest()[:24]
    return f"reserved_{digest}"


def _money(amount: Optional[float | int | str], currency: str | None = None) -> Optional[str]:
    if amount is None:
        return None
    currency = currency or cfg.CURRENCY
    try:
        val = float(amount)
    except (TypeError, ValueError):
        return None
    return f"{val:.2f}{currency}"


def _parse_price_value(raw: Any) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        if isinstance(raw, str):
            return float(raw)
        raw_f = float(raw)
        if isinstance(raw, int) and raw_f >= 100:
            return raw_f / 100.0
        return raw_f
    except (TypeError, ValueError):
        return None


def _detect_back_image(images: dict[str, Any], front_src: str) -> Optional[str]:
    """Detect back image from the images dict."""
    for size_key in ["1200", "850"]:
        if size_key in images:
            back = images[size_key].get("back", "")
            if back and back != front_src:
                return back
    return None


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return urljoin(cfg.BASE_URL + "/", url)
    return url


def _category_from_url(url: str) -> str:
    """Extract category name from URL path."""
    parts = url.rstrip("/").split("/")
    for i, part in enumerate(parts):
        if part in ("men", "women") and i + 1 < len(parts):
            category = parts[i + 1]
            return cfg.CATEGORY_DISPLAY.get(category, category.replace("-", " ").title())
    return "Other"


def _infer_gender(url: str) -> Optional[str]:
    """Infer gender from URL path."""
    if "/men/" in url:
        return "Men"
    if "/women/" in url:
        return "Women"
    return cfg.GENDER_DEFAULT


def _extract_price_info(product: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Extract original price and sale price."""
    currency = product.get("currency", cfg.CURRENCY)

    regular_price = product.get("price", "")
    final_price = product.get("final_price", "")
    has_discount = product.get("has_discount", False)
    final_price_type = product.get("finalPriceType", "regular")

    color_options = product.get("colorOptions", [])
    if color_options:
        for opt in color_options:
            if opt.get("isActive", False) or opt == color_options[0]:
                prices = opt.get("prices", {})
                if prices:
                    regular_price = prices.get("price", regular_price)
                    final_price = prices.get("finalPrice", final_price)
                    currency = prices.get("currency", currency)
                    history_price = prices.get("historyPrice", 0)
                    if history_price > 0:
                        has_discount = True
                    final_price_type = prices.get("finalPriceType", final_price_type)
                break

    price_str = _money(regular_price, currency) if regular_price else None
    sale_str = None

    if has_discount and final_price_type == "special":
        sale_str = _money(final_price, currency) if final_price else None
        if not price_str and final_price:
            for opt in color_options:
                prices = opt.get("prices", {})
                history = prices.get("historyPrice", 0)
                if history > 0:
                    price_str = _money(history, currency)
                    break

    return price_str, sale_str


def _extract_sizes(product: dict[str, Any]) -> str:
    """Extract available sizes as a comma-separated string."""
    color_options = product.get("colorOptions", [])
    sizes = []

    for opt in color_options:
        if opt.get("isActive", False) or opt == color_options[0]:
            for size in opt.get("sizes", []):
                size_name = size.get("sizeName", "")
                if size_name and size.get("stock", False):
                    sizes.append(size_name)
            break

    if not sizes:
        for size in product.get("sizes", []):
            size_name = size.get("sizeName", "")
            if size_name and size.get("stock", False):
                sizes.append(size_name)

    return ", ".join(sizes) if sizes else None


def _extract_images(product: dict[str, Any]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract image URLs. Returns (image_url, back_image_url, additional_images)."""
    images_obj = product.get("images", {})
    image_url = None
    back_image_url = None

    for size_key in ["1200", "850"]:
        if size_key in images_obj:
            front = images_obj[size_key].get("front", "")
            back = images_obj[size_key].get("back", "")
            if front:
                image_url = front
            if back:
                back_image_url = back
            break

    if not image_url:
        img_arr = product.get("img", [])
        if img_arr:
            image_url = img_arr[0] if len(img_arr) > 0 else None
            if len(img_arr) > 1 and img_arr[1]:
                back_image_url = img_arr[1]

    if not image_url:
        first_photo = product.get("firstPhoto", {})
        sizes = first_photo.get("sizes", {})
        image_url = sizes.get("medium") or sizes.get("original")

    additional_images = []
    gallery = product.get("gallery", product.get("photos", []))
    front_url = image_url or ""
    back_url = back_image_url or ""

    for photo in gallery:
        sizes = photo.get("sizes", {})
        original = sizes.get("original", "")
        if original and original != front_url and original != back_url:
            additional_images.append(original)

    additional_images_str = " , ".join(additional_images) if additional_images else None

    return image_url, back_image_url, additional_images_str


def _extract_metadata(product: dict[str, Any]) -> dict[str, Any]:
    """Extract all useful metadata into a JSON-serializable dict."""
    metadata: dict[str, Any] = {}

    sku = product.get("sku", "")
    if sku:
        metadata["sku"] = sku

    color_options = product.get("colorOptions", [])
    for opt in color_options:
        if opt.get("isActive", False) or opt == color_options[0]:
            color = opt.get("color", {})
            if color:
                metadata["color_name"] = color.get("name", "")
                metadata["color_css"] = color.get("cssName", "")
            break

    stickers = product.get("stickers", {})
    if stickers:
        text_tags = stickers.get("textTag", [])
        if text_tags:
            metadata["badges"] = [t.get("text", "") for t in text_tags if t.get("text")]
        tertiary = stickers.get("tertiary", [])
        if tertiary:
            metadata["materials"] = [t.get("text", "") for t in tertiary if t.get("text")]

    for field in ["season", "line", "collectionName", "extendedName"]:
        val = product.get(field)
        if val:
            metadata[field] = val

    photos_qty = product.get("photosQty")
    if photos_qty:
        metadata["photos_qty"] = photos_qty

    type_id = product.get("typeId", "")
    if type_id:
        metadata["type_id"] = type_id

    merchant = product.get("merchant", {})
    if merchant:
        metadata["merchant"] = merchant.get("name", "")

    variant_skus = []
    for opt in color_options:
        for size in opt.get("sizes", []):
            variant_skus.append(size.get("sku", ""))
    if variant_skus:
        metadata["variant_skus"] = variant_skus

    stock_info = {}
    for opt in color_options:
        color_name = opt.get("color", {}).get("name", "")
        for size in opt.get("sizes", []):
            size_name = size.get("sizeName", "")
            qty = size.get("stockQuantity", 0)
            if color_name and size_name:
                stock_info[f"{color_name}/{size_name}"] = qty
    if stock_info:
        metadata["stock_quantities"] = stock_info

    return metadata


def _extract_tags(product: dict[str, Any]) -> list[str]:
    """Extract tags from stickers and badges."""
    tags = []

    stickers = product.get("stickers", {})
    if stickers:
        text_tags = stickers.get("textTag", [])
        for t in text_tags:
            text = t.get("text", "").strip()
            if text:
                tags.append(text)
        tertiary = stickers.get("tertiary", [])
        for t in tertiary:
            text = t.get("text", "").strip()
            if text:
                tags.append(text)

    return tags if tags else None


def parse_product(raw: dict[str, Any], category_url: str = "") -> Optional[dict[str, Any]]:
    """Parse a raw arch API product into the Supabase products schema."""
    product_url = raw.get("url", "")
    if not product_url:
        return None

    title = (raw.get("name") or "").strip() or raw.get("extendedName", "").strip()
    if not title:
        return None

    image_url, back_image_url, additional_images = _extract_images(raw)
    if not image_url:
        logger.warning("Skip %s: no image", product_url)
        return None

    price, sale = _extract_price_info(raw)
    size = _extract_sizes(raw)
    gender = _infer_gender(category_url) if category_url else raw.get("_gender", "")
    category = _category_from_url(category_url) if category_url else None
    categories = raw.get("_categories", [])
    if categories:
        category = ", ".join(categories)

    metadata = _extract_metadata(raw)
    tags = _extract_tags(raw)

    compressed_image_url = None
    if image_url and "cache/1200/" in image_url:
        compressed_image_url = image_url.replace("cache/1200/", "cache/850/")

    return {
        "id": _stable_id(product_url),
        "source": cfg.SOURCE,
        "product_url": product_url,
        "affiliate_url": None,
        "image_url": image_url,
        "compressed_image_url": compressed_image_url,
        "back_image_url": back_image_url,
        "brand": cfg.BRAND_COLUMN,
        "title": title,
        "description": None,
        "category": category,
        "gender": gender,
        "price": price,
        "sale": sale,
        "metadata": json.dumps(metadata, ensure_ascii=False) if metadata else None,
        "size": size,
        "second_hand": cfg.SECOND_HAND,
        "country": "IE",
        "tags": tags,
        "additional_images": additional_images,
        "other": None,
    }


def fetch_category_products(category_url: str) -> list[dict[str, Any]]:
    """Fetch products for a category using the arch API."""
    # Extract category ID from URL
    # Reserved URLs look like: /ie/en/men/shirts/view-all
    # We need to find the category ID from the arch API
    products: list[dict[str, Any]] = []
    seen: set[str] = set()

    # First, try to get category listing from arch API
    # The arch API endpoint pattern is: /api/v2/{store_id}/categories/{category_id}/products
    # We need to discover category IDs first

    # For now, scrape the webpage directly
    try:
        resp = _rate_limited_get(category_url, timeout=cfg.REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text

        # Extract product data from HTML/JSON
        # Reserved embeds product data in script tags
        product_pattern = r'window\.__PRODUCT_DATA__\s*=\s*({.*?});'
        match = re.search(product_pattern, html, re.DOTALL)

        if match:
            try:
                product_data = json.loads(match.group(1))
                if isinstance(product_data, list):
                    for raw_product in product_data:
                        parsed = parse_product(raw_product, category_url)
                        if parsed and parsed["product_url"] not in seen:
                            seen.add(parsed["product_url"])
                            products.append(parsed)
            except json.JSONDecodeError:
                pass

        # Also try to find product URLs in the HTML
        url_pattern = r'href="(/ie/en/[^"]+/p_[^"]+)"'
        product_urls = re.findall(url_pattern, html)

        for url_path in product_urls:
            full_url = f"https://www.reserved.com{url_path}"
            if full_url not in seen:
                # Create a minimal product entry
                product = {
                    "url": full_url,
                    "name": url_path.split("/")[-2].replace("-", " ").title(),
                }
                parsed = parse_product(product, category_url)
                if parsed:
                    seen.add(full_url)
                    products.append(parsed)

    except Exception as e:
        logger.warning("Failed to fetch category %s: %s", category_url, e)

    logger.info("Category %s: %d products", category_url.split("/")[-1], len(products))
    return products


def scrape_all_categories() -> list[dict[str, Any]]:
    """Scrape all categories in parallel."""
    all_products: list[dict[str, Any]] = []
    seen: set[str] = set()

    with ThreadPoolExecutor(max_workers=cfg.SCRAPE_WORKERS) as executor:
        future_to_url = {
            executor.submit(fetch_category_products, url): url
            for url in cfg.CATEGORY_URLS
        }

        for future in future_to_url:
            url = future_to_url[future]
            try:
                cat_products = future.result()
                for p in cat_products:
                    if p["product_url"] not in seen:
                        seen.add(p["product_url"])
                        all_products.append(p)
                    else:
                        # Merge categories
                        existing = next(
                            (x for x in all_products if x["product_url"] == p["product_url"]),
                            None,
                        )
                        if existing:
                            cats = {c.strip() for c in (existing.get("category") or "").split(",") if c.strip()}
                            if p.get("category"):
                                cats.add(p["category"])
                            existing["category"] = ", ".join(sorted(cats)) if cats else existing.get("category")
            except Exception as e:
                logger.error("Category %s crawl failed: %s", url, e)

    logger.info("Total unique products: %d", len(all_products))
    return all_products

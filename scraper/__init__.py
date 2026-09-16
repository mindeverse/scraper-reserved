"""Reserved arch API scraper — discover categories and fetch products."""
from __future__ import annotations

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
from parser import parse_product

logger = logging.getLogger(__name__)

# Shared session
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
                _session.headers.update({
                    "User-Agent": cfg.USER_AGENT,
                    "Accept": "application/json,text/html,*/*",
                    "Accept-Language": "en-IE,en;q=0.9",
                })
    return _session


def _rate_limited_get(url: str, timeout: int = 30) -> requests.Response:
    """Get with rate limiting."""
    time.sleep(cfg.RATE_LIMIT_DELAY)
    session = _get_session()
    return session.get(url, timeout=timeout)


def discover_all_category_ids() -> dict[str, int]:
    """Discover category IDs from Reserved arch API.
    
    Returns dict mapping category URL to category ID.
    """
    category_ids: dict[str, int] = {}
    
    for category_url in cfg.CATEGORY_URLS:
        try:
            # Try to get category ID from the arch API
            # The arch API has a categories endpoint
            resp = _rate_limited_get(
                f"{cfg.ARCH_API_BASE}/v2/{cfg.STORE_ID}/categories",
                timeout=cfg.REQUEST_TIMEOUT
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    for cat in data:
                        if "id" in cat and "url" in cat:
                            cat_url = cat.get("url", "")
                            cat_id = cat.get("id")
                            if cat_url and cat_id:
                                category_ids[cat_url] = cat_id
        except Exception as e:
            logger.warning("Failed to discover category ID for %s: %s", category_url, e)
    
    # If arch API discovery failed, try to extract from webpage
    if not category_ids:
        logger.info("Arch API discovery failed, trying webpage extraction...")
        for category_url in cfg.CATEGORY_URLS:
            try:
                resp = _rate_limited_get(category_url, timeout=cfg.REQUEST_TIMEOUT)
                resp.raise_for_status()
                html = resp.text
                
                # Look for category ID in script tags or data attributes
                patterns = [
                    r'"categoryId"\s*:\s*(\d+)',
                    r'data-category-id="(\d+)"',
                    r'category_id["\s:=]+(\d+)',
                ]
                for pattern in patterns:
                    match = re.search(pattern, html)
                    if match:
                        cat_id = int(match.group(1))
                        category_ids[category_url] = cat_id
                        break
            except Exception as e:
                logger.warning("Failed to extract category ID from %s: %s", category_url, e)
    
    logger.info("Discovered %d category IDs", len(category_ids))
    return category_ids


def fetch_category_products_from_arch(category_id: int, category_url: str) -> list[dict[str, Any]]:
    """Fetch products for a category using the arch API."""
    products: list[dict[str, Any]] = []
    seen: set[str] = set()
    page = 1
    page_size = cfg.PRODUCTS_JSON_LIMIT
    
    while True:
        try:
            url = f"{cfg.ARCH_API_BASE}/v2/{cfg.STORE_ID}/categories/{category_id}/products"
            params = {"page": page, "limit": page_size}
            resp = _rate_limited_get(url, timeout=cfg.REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            
            if not data:
                break
            
            batch = data if isinstance(data, list) else data.get("products", [])
            if not batch:
                break
            
            for raw_product in batch:
                # Add metadata from scraper
                raw_product["_gender"] = _infer_gender(category_url)
                raw_product["_categories"] = [_category_from_url(category_url)]
                parsed = parse_product(raw_product)
                if parsed and parsed["product_url"] not in seen:
                    seen.add(parsed["product_url"])
                    products.append(parsed)
            
            if len(batch) < page_size:
                break
            page += 1
            
        except Exception as e:
            logger.warning("Failed to fetch products for category %d page %d: %s", category_id, page, e)
            break
    
    return products


def _infer_gender(url: str) -> str:
    """Infer gender from URL path."""
    if "/men/" in url:
        return "Men"
    if "/women/" in url:
        return "Women"
    return cfg.GENDER_DEFAULT


def _category_from_url(url: str) -> str:
    """Extract category name from URL path."""
    parts = url.rstrip("/").split("/")
    for i, part in enumerate(parts):
        if part in ("men", "women") and i + 1 < len(parts):
            category = parts[i + 1]
            return cfg.CATEGORY_DISPLAY.get(category, category.replace("-", " ").title())
    return "Other"


def scrape_all_categories() -> list[dict[str, Any]]:
    """Scrape all categories using the arch API."""
    all_products: list[dict[str, Any]] = []
    seen: set[str] = set()
    
    # First, try to discover category IDs
    category_ids = discover_all_category_ids()
    
    if category_ids:
        # Use arch API with discovered category IDs
        with ThreadPoolExecutor(max_workers=cfg.SCRAPE_WORKERS) as executor:
            future_to_url = {}
            for category_url, category_id in category_ids.items():
                future = executor.submit(
                    fetch_category_products_from_arch,
                    category_id,
                    category_url
                )
                future_to_url[future] = category_url
            
            for future in future_to_url:
                url = future_to_url[future]
                try:
                    cat_products = future.result()
                    for product in cat_products:
                        product_url = product.get("url", "")
                        if product_url and product_url not in seen:
                            seen.add(product_url)
                            all_products.append(product)
                except Exception as e:
                    logger.error("Category %s crawl failed: %s", url, e)
    else:
        # Fallback: scrape webpages directly
        logger.info("No category IDs discovered, falling back to webpage scraping...")
        with ThreadPoolExecutor(max_workers=cfg.SCRAPE_WORKERS) as executor:
            future_to_url = {
                executor.submit(_scrape_webpage, url): url
                for url in cfg.CATEGORY_URLS
            }
            
            for future in future_to_url:
                url = future_to_url[future]
                try:
                    cat_products = future.result()
                    for product in cat_products:
                        product_url = product.get("url", "")
                        if product_url and product_url not in seen:
                            seen.add(product_url)
                            all_products.append(product)
                except Exception as e:
                    logger.error("Category %s crawl failed: %s", url, e)
    
    logger.info("Total unique products: %d", len(all_products))
    return all_products


def _scrape_webpage(category_url: str) -> list[dict[str, Any]]:
    """Fallback: scrape products from webpage HTML."""
    products: list[dict[str, Any]] = []
    seen: set[str] = set()
    
    try:
        resp = _rate_limited_get(category_url, timeout=cfg.REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
        
        # Extract product URLs from HTML
        # Reserved product URLs typically look like: /ie/en/.../p_XXXXX.html
        url_pattern = r'href="(/ie/en/[^"]+/p_[^"]+\.html)"'
        product_urls = re.findall(url_pattern, html)
        
        for url_path in product_urls:
            full_url = f"https://www.reserved.com{url_path}"
            if full_url not in seen:
                seen.add(full_url)
                # Create minimal product entry
                # Extract name from URL
                name_part = url_path.split("/")[-2] if "/" in url_path else url_path.split("/")[-1]
                name = name_part.replace("-", " ").replace("_", " ").title()
                # Remove p_ prefix if present
                if name.startswith("P "):
                    name = name[2:]
                
                product = {
                    "url": full_url,
                    "name": name,
                    "_gender": _infer_gender(category_url),
                    "_categories": [_category_from_url(category_url)],
                }
                parsed = parse_product(product)
                if parsed:
                    products.append(parsed)
        
        # Also try to extract product data from JSON-LD or script tags
        json_patterns = [
            r'window\.__PRODUCT_DATA__\s*=\s*({.*?});',
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        ]
        for pattern in json_patterns:
            matches = re.findall(pattern, html, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and "url" in item:
                                item["_gender"] = _infer_gender(category_url)
                                item["_categories"] = [_category_from_url(category_url)]
                                parsed = parse_product(item)
                                if parsed and parsed["product_url"] not in seen:
                                    seen.add(parsed["product_url"])
                                    products.append(parsed)
                    elif isinstance(data, dict) and "url" in data:
                        data["_gender"] = _infer_gender(category_url)
                        data["_categories"] = [_category_from_url(category_url)]
                        parsed = parse_product(data)
                        if parsed and parsed["product_url"] not in seen:
                            seen.add(parsed["product_url"])
                            products.append(parsed)
                except json.JSONDecodeError:
                    pass
        
    except Exception as e:
        logger.warning("Failed to scrape webpage %s: %s", category_url, e)
    
    return products

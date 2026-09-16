"""Reserved Algolia API scraper — fetch all products via Algolia search."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import cfg

logger = logging.getLogger(__name__)

ALGOLIA_APP_ID = "4DBLBFMEJV"
ALGOLIA_SEARCH_KEY = "e97ce435b768f0fa7048e25a7cf3752e"
ALGOLIA_INDEX = "PRODUCT_RES_IE_EN"
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"

ALGOLIA_ATTRIBUTES = [
    "id", "store_id", "sku", "name", "description", "final_price",
    "final_price_type", "currency", "url", "color_options",
    "categories_list", "color", "sizes", "season", "line",
    "collection_name", "merchant", "blocked", "rms_department_name",
    "rms_class_name", "rms_subclass_name",
]

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
                    pool_connections=4,
                    pool_maxsize=4,
                )
                _session.mount("https://", adapter)
                _session.mount("http://", adapter)
                _session.headers.update({
                    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
                    "X-Algolia-API-Key": ALGOLIA_SEARCH_KEY,
                    "Content-Type": "application/json",
                })
    return _session


def _algolia_query(body: dict) -> dict:
    session = _get_session()
    time.sleep(cfg.RATE_LIMIT_DELAY)
    resp = session.post(ALGOLIA_URL, json=body, timeout=cfg.REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _get_all_subcategories() -> dict[str, int]:
    data = _algolia_query({
        "query": "",
        "hitsPerPage": 0,
        "facets": ["categories.lvl1"],
        "maxValuesPerFacet": 200,
    })
    return data.get("facets", {}).get("categories.lvl1", {})


def _fetch_subcategory_products(subcat: str) -> list[dict[str, Any]]:
    all_hits = []
    last_id = 0

    while True:
        body = {
            "query": "",
            "hitsPerPage": 1000,
            "page": 0,
            "facetFilters": [[f"categories.lvl1:{subcat}"]],
            "numericFilters": [f"id > {last_id}"],
            "attributesToRetrieve": ALGOLIA_ATTRIBUTES,
        }
        data = _algolia_query(body)
        hits = data.get("hits", [])
        if not hits:
            break

        all_hits.extend(hits)
        last_id = max(h["id"] for h in hits)

        if len(hits) < 1000:
            break

    return all_hits


def _parse_algolia_hit(hit: dict[str, Any]) -> dict[str, Any] | None:
    product_url = hit.get("url", "")
    if not product_url:
        return None

    name = (hit.get("name") or "").strip()
    if not name:
        return None

    sku = hit.get("sku", "")
    final_price = hit.get("final_price")
    currency = hit.get("currency", cfg.CURRENCY)

    price_str = None
    if final_price:
        price_str = f"{float(final_price):.2f}{currency}"

    image_url = ""
    back_image_url = None
    compressed_image_url = None
    color_options = hit.get("color_options") or []

    if isinstance(color_options, list) and color_options:
        first_opt = color_options[0]
        if isinstance(first_opt, dict):
            color_obj = first_opt.get("color") or {}
            image_url = color_obj.get("photo", "")

    if image_url:
        hi_res = image_url.replace("/cache/40/", "/cache/1200/")
        if hi_res != image_url:
            compressed_image_url = image_url
            image_url = hi_res

    categories = hit.get("categories_list") or []
    category = ", ".join(categories) if categories else None

    gender = ""
    categories_lower = " ".join(categories).lower()
    if "women" in categories_lower or "ladies" in categories_lower:
        gender = "Women"
    elif "men" in categories_lower or "gentlemen" in categories_lower:
        gender = "Men"

    size_list = hit.get("sizes") or []
    available_sizes = []
    if isinstance(size_list, list):
        for s in size_list:
            if isinstance(s, dict) and s.get("stock") and s.get("sizeName"):
                available_sizes.append(s["sizeName"])
            elif isinstance(s, str) and s.strip():
                available_sizes.append(s.strip())
    size_str = ", ".join(available_sizes) if available_sizes else None

    metadata = {
        "sku": sku,
        "color": hit.get("color", ""),
        "season": hit.get("season", ""),
        "line": hit.get("line", ""),
        "collection_name": hit.get("collection_name", ""),
        "department": hit.get("rms_department_name", ""),
        "class_name": hit.get("rms_class_name", ""),
        "subclass_name": hit.get("rms_subclass_name", ""),
    }

    description = hit.get("description")
    if description:
        description = re.sub(r"<[^>]+>", " ", description)
        description = re.sub(r"\s+", " ", description).strip() or None

    prod_id = hashlib.sha256(f"{cfg.SOURCE}:{product_url}".encode()).hexdigest()[:24]

    return {
        "id": f"reserved_{prod_id}",
        "source": cfg.SOURCE,
        "product_url": product_url,
        "affiliate_url": None,
        "image_url": image_url or None,
        "compressed_image_url": compressed_image_url,
        "back_image_url": back_image_url,
        "brand": cfg.BRAND_COLUMN,
        "title": name,
        "description": description,
        "category": category,
        "gender": gender,
        "price": price_str,
        "sale": None,
        "metadata": json.dumps(metadata, ensure_ascii=False) if any(metadata.values()) else None,
        "size": size_str,
        "second_hand": cfg.SECOND_HAND,
        "country": "IE",
        "tags": None,
        "additional_images": None,
        "other": None,
    }


def scrape_all_categories() -> list[dict[str, Any]]:
    all_products: list[dict[str, Any]] = []
    seen: set[str] = set()

    logger.info("Fetching subcategory list from Algolia...")
    subcats = _get_all_subcategories()
    logger.info("Found %d subcategories", len(subcats))

    for subcat, count in sorted(subcats.items(), key=lambda x: -x[1]):
        logger.info("Fetching %s (%d products)...", subcat, count)
        hits = _fetch_subcategory_products(subcat)

        new_count = 0
        for hit in hits:
            parsed = _parse_algolia_hit(hit)
            if parsed and parsed["product_url"] not in seen:
                seen.add(parsed["product_url"])
                all_products.append(parsed)
                new_count += 1

        logger.info("  -> %d hits, %d new unique products", len(hits), new_count)

    logger.info("Total unique products scraped: %d", len(all_products))
    return all_products

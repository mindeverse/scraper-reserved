"""Reserved product parser — parse arch API product data into Supabase schema."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Optional

from config import cfg

logger = logging.getLogger(__name__)


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


def parse_product(raw: dict[str, Any]) -> Optional[dict[str, Any]]:
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
    gender = raw.get("_gender", "")
    categories = raw.get("_categories", [])
    category = ", ".join(categories) if categories else None

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

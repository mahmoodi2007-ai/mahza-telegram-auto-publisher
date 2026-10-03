```python

print("BOT.PY STARTED")


import json
import os
import time
from pathlib import Path

import requests


# ============================================================
# Configuration
# ============================================================

MIXIN_API_URL = "https://mahzacollection.ir/api/v4/products/"
SITE_URL = "https://mahzacollection.ir"

STATE_FILE = Path("published_products.json")

PAGE_SIZE = 50

MIXIN_API_KEY = os.getenv("MIXIN_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()

TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"

try:
    MAX_PRODUCTS_PER_RUN = int(
        os.getenv("MAX_PRODUCTS_PER_RUN", "0")
    )
except ValueError:
    MAX_PRODUCTS_PER_RUN = 0


# ============================================================
# Validation
# ============================================================

if not MIXIN_API_KEY:
    raise RuntimeError("MIXIN_API_KEY is missing.")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing.")

if not TELEGRAM_CHANNEL_ID:
    raise RuntimeError("TELEGRAM_CHANNEL_ID is missing.")


# ============================================================
# State management
# ============================================================

def load_published_ids():
    if not STATE_FILE.exists():
        print("WARNING: published_products.json not found.")
        return set()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        ids = data.get("published_ids", [])

        published_ids = {
            int(product_id)
            for product_id in ids
        }

        return published_ids

    except Exception as e:
        print(f"WARNING: Could not read state file: {e}")
        return set()


def save_published_ids(published_ids):
    data = {
        "published_ids": sorted(published_ids)
    }

    temp_file = STATE_FILE.with_suffix(".tmp")

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    temp_file.replace(STATE_FILE)


# ============================================================
# Get products from Mixin API
# ============================================================

def get_products():
    headers = {
        "Authorization": f"Api-Key {MIXIN_API_KEY}",
        "Accept": "application/json",
    }

    all_products = []
    page = 1

    while True:
        print(f"Getting products page {page}...")

        params = {
            "page": page,
            "page_size": PAGE_SIZE,
            "ordering": "-creation_date",
            "available": "true",
        }

        response = requests.get(
            MIXIN_API_URL,
            headers=headers,
            params=params,
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        products = data.get("data", [])

        print(
            f"Received {len(products)} products from page {page}."
        )

        all_products.extend(products)

        pagination = data.get("pagination", {})

        has_next = pagination.get("has_next", False)

        if not has_next or not products:
            break

        page += 1

    print(
        f"Total available products received: {len(all_products)}"
    )

    return all_products


# ============================================================
# Product URL
# ============================================================

def get_product_url(product):
    product_id = product.get("id")

    return f"{SITE_URL}/product/{product_id}/"


# ============================================================
# Images
# ============================================================

def normalize_image_url(image_url):
    if not image_url:
        return None

    if image_url.startswith("http://"):
        return image_url

    if image_url.startswith("https://"):
        return image_url

    if image_url.startswith("//"):
        return "https:" + image_url

    if image_url.startswith("/"):
        return SITE_URL + image_url

    return image_url


def get_product_images(product):
    images = []

    default_image = product.get("default_image")

    if default_image:
        images.append(default_image)

    product_images = product.get("images", [])

    for image in product_images:
        if isinstance(image, str):
            image_url = image

        elif isinstance(image, dict):
            image_url = (
                image.get("url")
                or image.get("image")
                or image.get("src")
            )

        else:
            image_url = None

        if image_url:
            images.append(image_url)

    result = []

    for image in images:
        image = normalize_image_url(image)

        if image and image not in result:
            result.append(image)

        if len(result) >= 3:
            break

    return result


# ============================================================
# Formatting
# ============================================================

def format_price(price):
    if price is None:
        return "تماس بگیرید"

    try:
        number = int(float(price))
        return f"{number:,} تومان"

    except Exception:
        return f"{price} تومان"


def get_discount_info(product):
    price = product.get("price")
    compare_at_price = product.get("compare_at_price")

    if not price or not compare_at_price:
        return None

    try:
        price = float(price)
        compare_at_price = float(compare_at_price)

        if compare_at_price <= price:
            return None

        discount_percent = round(
            ((compare_at_price - price) / compare_at_price) * 100
        )

        return {
            "percent": discount_percent,
            "old_price": format_price(compare_at_price),
        }

    except Exception:
        return None


# ============================================================
# Telegram caption
# ============================================================

def create_caption(product):
    name = product.get("name", "محصول")

    brand = product.get("brand")

    if isinstance(brand, dict):
        brand_name = (
            brand.get("name")
            or brand.get("title")
            or ""
        )
    else:
        brand_name = brand or ""

    price = format_price(product.get("price"))

    discount = get_discount_info(product)

    product_url = get_product_url(product)

    lines = []

    lines.append(f"🛍️ {name}")

    if brand_name:
        lines.append(f"🏷️ برند: {brand_name}")

    if discount:
        lines.append(
            f"💰 قیمت: {price}"
        )

        lines.append(
            f"🔥 تخفیف: {discount['percent']}٪"
        )

        lines.append(
            f"💵 قیمت قبل: {discount['old_price']}"
        )

    else:
        lines.append(
            f"💰 قیمت: {price}"
        )

    lines.append("")

    lines.append(
        f"🛒 خرید محصول:\n{product_url}"
    )

    lines.append("")

    lines.append(
        "✨ Mahza Collection"
    )

    lines.append(
        "🌐 www.mahzacollection.ir"
    )

    return "\n".join(lines)


# ============================================================
# Telegram API
# ============================================================

def telegram_api_url(method):
    return (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/{method}"
    )


def send_product_to_telegram(product):
    product_id = product.get("id")
    product_name = product.get("name", "محصول")

    images = get_product_images(product)

    caption = create_caption(product)

    print(
        f"Sending product {product_id}: {product_name}"
    )

    print(
        f"Images found: {len(images)}"
    )

    # --------------------------------------------------------
    # No image
    # --------------------------------------------------------

    if not images:
        response = requests.post(
            telegram_api_url("sendMessage"),
            data={
                "chat_id": TELEGRAM_CHANNEL_ID,
                "text": caption,
            },
            timeout=30,
        )

        response.raise_for_status()

        return True

    # --------------------------------------------------------
    # One image
    # --------------------------------------------------------

    if len(images) == 1:
        response = requests.post(
            telegram_api_url("sendPhoto"),
            data={
                "chat_id": TELEGRAM_CHANNEL_ID,
                "photo": images[0],
                "caption": caption,
            },
            timeout=60,
        )

        response.raise_for_status()

        return True

    # --------------------------------------------------------
    # Multiple images - maximum 3
    # --------------------------------------------------------

    media = []

    for index, image_url in enumerate(images[:3]):

        item = {
            "type": "photo",
            "media": image_url,
        }

        if index == 0:
            item["caption"] = caption
            item["parse_mode"] = "HTML"

        media.append(item)

    response = requests.post(
        telegram_api_url("sendMediaGroup"),
        data={
            "chat_id": TELEGRAM_CHANNEL_ID,
            "media": json.dumps(
                media,
                ensure_ascii=False
            ),
        },
        timeout=90,
    )

    response.raise_for_status()

    return True


# ============================================================
# Main
# ============================================================

def main():

    print("=" * 60)
    print("Mahza Collection Telegram Publisher")
    print("=" * 60)

    print(
        f"TEST_MODE = {TEST_MODE}"
    )

    print(
        f"MAX_PRODUCTS_PER_RUN = {MAX_PRODUCTS_PER_RUN}"
    )

    # --------------------------------------------------------
    # Load published IDs
    # --------------------------------------------------------

    published_ids = load_published_ids()

    # DEBUG:
    # Show exactly which product IDs were loaded
    # from published_products.json

    print(
        f"Published IDs loaded: {sorted(published_ids)}"
    )

    print(
        f"Previously published products: "
        f"{len(published_ids)}"
    )

    # --------------------------------------------------------
    # Get products
    #
```

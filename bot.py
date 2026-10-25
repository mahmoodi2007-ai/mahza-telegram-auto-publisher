
print("BOT.PY STARTED")

import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import requests


# ============================================================
# CONFIGURATION
# ============================================================

MIXIN_API_URL = "https://mahzacollection.ir/api/v4/products/"
SITE_URL = "https://mahzacollection.ir"

STATE_FILE = Path("published_products.json")
BALE_STATE_FILE = Path("published_bale_products.json")

PAGE_SIZE = 50
MAX_IMAGES = 3
REQUEST_TIMEOUT = 40
DELAY_BETWEEN_PRODUCTS = 2

MIXIN_API_KEY = os.getenv("MIXIN_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
BALE_BOT_TOKEN = os.getenv("BALE_BOT_TOKEN", "").strip()
BALE_CHANNEL_ID = os.getenv("BALE_CHANNEL_ID", "").strip()

TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"

try:
    MAX_PRODUCTS_PER_RUN = int(
        os.getenv("MAX_PRODUCTS_PER_RUN", "0")
    )
except ValueError:
    MAX_PRODUCTS_PER_RUN = 0


# ============================================================
# VALIDATION
# ============================================================

if not MIXIN_API_KEY:
    raise RuntimeError("MIXIN_API_KEY is missing.")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing.")

if not TELEGRAM_CHANNEL_ID:
    raise RuntimeError("TELEGRAM_CHANNEL_ID is missing.")

if not BALE_BOT_TOKEN:
    raise RuntimeError("BALE_BOT_TOKEN is missing.")

if not BALE_CHANNEL_ID:
    raise RuntimeError("BALE_CHANNEL_ID is missing.")


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "MahzaCollection-Telegram-Publisher/2.0"
})


# ============================================================
# STATE MANAGEMENT
# ============================================================

def load_published_ids():

    if not STATE_FILE.exists():
        print("WARNING: State file not found.")
        return set()

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        raw_ids = data.get("published_ids", [])

        published_ids = set()

        for item in raw_ids:

            try:
                published_ids.add(int(item))
            except (ValueError, TypeError):
                continue

        print(f"Previously published products: {len(published_ids)}")

        return published_ids

    except Exception as error:

        raise RuntimeError(
            f"Cannot read state file safely: {error}"
        )


def save_published_ids(published_ids):

    data = {
        "published_ids": sorted(published_ids)
    }

    temp_file = STATE_FILE.with_suffix(".tmp")

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )

    temp_file.replace(STATE_FILE)


# ============================================================
# AVAILABILITY CHECK
# ============================================================

def is_available(product):

    value = product.get("available")

    if value is True:
        return True

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 1

    if isinstance(value, str):
        return value.strip().lower() in (
            "true",
            "1",
            "yes"
        )

    return False


# ============================================================
# PRODUCT URL
# ============================================================

def get_product_url(product):

    product_id = product.get("id")

    if product_id is None:
        raise ValueError("Product ID is missing.")

    # First: use an existing full URL from API

    url_fields = [
        "product_url",
        "absolute_url",
        "web_url",
        "product_link",
        "url",
        "link"
    ]

    for key in url_fields:

        value = product.get(key)

        if isinstance(value, str):

            value = value.strip()

            if value.startswith("https://") or value.startswith("http://"):
                return value

    # Second: use product slug

    slug_fields = [
        "slug",
        "seo_slug",
        "permalink"
    ]

    for key in slug_fields:

        slug = product.get(key)

        if not isinstance(slug, str):
            continue

        slug = slug.strip()

        if not slug:
            continue

        if slug.startswith("https://") or slug.startswith("http://"):
            return slug

        if slug.startswith("/"):
            return SITE_URL + slug

        encoded_slug = quote(
            slug.strip("/"),
            safe="/-%._~"
        )

        return (
            f"{SITE_URL}/product/"
            f"{product_id}/{encoded_slug}/"
        )

    # Last fallback: product ID route

    print(
        f"WARNING: No product slug found for {product_id}. "
        "Using ID-only URL."
    )

    return f"{SITE_URL}/product/{product_id}/"


# ============================================================
# GET PRODUCTS
# ============================================================

def get_products():

    headers = {
        "Authorization": f"Api-Key {MIXIN_API_KEY}",
        "Accept": "application/json"
    }

    all_products = []
    page = 1

    while True:

        print(f"Getting products page {page}...")

        params = {
            "page": page,
            "page_size": PAGE_SIZE,
            "ordering": "-creation_date",
            "available": "true"
        }

        response = session.get(
            MIXIN_API_URL,
            headers=headers,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        result = response.json()

        products = result.get("data", [])

        if not isinstance(products, list):
            raise RuntimeError(
                "Invalid products API response."
            )

        print(
            f"Received {len(products)} products "
            f"from page {page}."
        )

        all_products.extend(products)

        pagination = result.get("pagination", {})

        has_next = pagination.get("has_next", False)

        if not has_next or not products:
            break

        page += 1

        if page > 100:
            raise RuntimeError(
                "Pagination safety limit reached."
            )

    print(
        f"Total products received: {len(all_products)}"
    )

    return all_products


# ============================================================
# IMAGE HELPERS
# ============================================================

def extract_image_url(image):

    if isinstance(image, str):
        return image.strip() or None

    if isinstance(image, dict):

        possible_keys = [
            "url",
            "image",
            "src",
            "file",
            "original",
            "original_url",
            "image_url"
        ]

        for key in possible_keys:

            value = image.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

            if isinstance(value, dict):

                nested = extract_image_url(value)

                if nested:
                    return nested

    return None


def normalize_image_url(url):

    if not url:
        return None

    if not isinstance(url, str):
        return None

    url = url.strip()

    if not url:
        return None

    if url.startswith("https://") or url.startswith("http://"):
        return url

    if url.startswith("//"):
        return "https:" + url

    if url.startswith("/"):
        return SITE_URL + url

    return None


def get_product_images(product):

    images = []

    default_image = extract_image_url(
        product.get("default_image")
    )

    if default_image:
        images.append(default_image)

    product_images = product.get("images", [])

    if isinstance(product_images, list):

        for image in product_images:

            image_url = extract_image_url(image)

            if image_url:
                images.append(image_url)

    result = []

    for image in images:

        image = normalize_image_url(image)

        if image and image not in result:
            result.append(image)

        if len(result) >= MAX_IMAGES:
            break

    return result


# ============================================================
# PRICE FORMATTING
# ============================================================

def format_price(price):

    if price is None:
        return "تماس بگیرید"

    try:

        number = int(float(price))

        return f"{number:,} تومان"

    except (ValueError, TypeError):

        return str(price)


def get_discount_info(product):

    price = product.get("price")

    old_price = product.get("compare_at_price")

    if price is None or old_price is None:
        return None

    try:

        price = float(price)
        old_price = float(old_price)

        if price <= 0 or old_price <= price:
            return None

        percent = round(
            ((old_price - price) / old_price) * 100
        )

        return {
            "percent": percent,
            "old_price": format_price(old_price)
        }

    except (ValueError, TypeError):

        return None


# ============================================================
# TELEGRAM CAPTION
# ============================================================

def create_caption(product):

    name = str(
        product.get("name") or "محصول"
    )

    brand = product.get("brand")

    if isinstance(brand, dict):

        brand_name = (
            brand.get("name")
            or brand.get("title")
            or ""
        )

    else:

        brand_name = str(brand or "")

    price = format_price(
        product.get("price")
    )

    discount = get_discount_info(product)

    product_url = get_product_url(product)

    lines = [
        f"🛍️ {name}"
    ]

    if brand_name:
        lines.append(f"🏷️ برند: {brand_name}")

    lines.append(f"💰 قیمت: {price}")

    if discount:

        lines.append(
            f"🔥 تخفیف: {discount['percent']}٪"
        )

        lines.append(
            f"💵 قیمت قبل: {discount['old_price']}"
        )

    lines.extend([
        "",
        "🛒 خرید محصول:",
        product_url,
        "",
        "✨ Mahza Collection",
        "🌐 www.mahzacollection.ir"
    ])

    caption = "\n".join(lines)

    # Telegram photo caption limit is 1024 characters.
    if len(caption) > 1024:

        suffix = (
            f"\n\n🛒 خرید محصول:\n{product_url}"
            f"\n\n✨ Mahza Collection"
        )

        available_length = 1024 - len(suffix)

        short_name = name[:max(20, available_length - 30)]

        caption = (
            f"🛍️ {short_name}"
            f"{suffix}"
        )

    return caption


# ============================================================
# TELEGRAM API
# ============================================================

def telegram_api_url(method):

    return (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/{method}"
    )


def telegram_request(method, data, timeout=60):

    response = session.post(
        telegram_api_url(method),
        data=data,
        timeout=timeout
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):

        raise RuntimeError(
            f"Telegram API error: {result}"
        )

    return result


# ============================================================
# SEND PRODUCT
# ============================================================

def send_product_to_telegram(product):

    product_id = product.get("id")

    product_name = product.get("name", "محصول")

    # Double-check availability

    if not is_available(product):

        print(
            f"SKIPPED: Product {product_id} is unavailable."
        )

        return False

    images = get_product_images(product)

    caption = create_caption(product)

    print(
        f"Sending product {product_id}: {product_name}"
    )

    print(
        f"Images found: {len(images)}"
    )

    # No image

    if not images:

        telegram_request(
            "sendMessage",
            {
                "chat_id": TELEGRAM_CHANNEL_ID,
                "text": caption
            }
        )

        return True

    # One image

    if len(images) == 1:

        telegram_request(
            "sendPhoto",
            {
                "chat_id": TELEGRAM_CHANNEL_ID,
                "photo": images[0],
                "caption": caption
            }
        )

        return True

    # Multiple images

    media = []

    for index, image_url in enumerate(images[:MAX_IMAGES]):

        item = {
            "type": "photo",
            "media": image_url
        }

        if index == 0:
            item["caption"] = caption

        media.append(item)

    telegram_request(
        "sendMediaGroup",
        {
            "chat_id": TELEGRAM_CHANNEL_ID,
            "media": json.dumps(
                media,
                ensure_ascii=False
            )
        },
        timeout=90
    )

    return True


# ============================================================
# BALE API
# ============================================================

def bale_api_url(method):
    return f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/{method}"


def bale_request(method, data, timeout=90):
    response = session.post(
        bale_api_url(method),
        data=data,
        timeout=timeout
    )
    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        # Do not print credentials; API response contains no token.
        raise RuntimeError(
            f"Bale API error ({method}): "
            f"{result.get('description', 'Unknown error')}"
        )

    return result


def load_bale_published_ids():
    if not BALE_STATE_FILE.exists():
        print("Bale state file not found; starting Bale publishing history.")
        save_bale_published_ids(set())
        return set()

    try:
        with open(BALE_STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        ids = set()
        for item in data.get("published_ids", []):
            try:
                ids.add(int(item))
            except (ValueError, TypeError):
                continue

        print(f"Previously published to Bale: {len(ids)}")
        return ids

    except Exception as error:
        raise RuntimeError(f"Cannot read Bale state file safely: {error}")


def save_bale_published_ids(published_ids):
    data = {"published_ids": sorted(published_ids)}
    temp_file = BALE_STATE_FILE.with_suffix(".tmp")

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    temp_file.replace(BALE_STATE_FILE)


def send_product_to_bale(product):
    product_id = product.get("id")
    product_name = product.get("name", "محصول")

    if not is_available(product):
        print(f"BALE SKIPPED: Product {product_id} is unavailable.")
        return False

    images = get_product_images(product)
    caption = create_caption(product)

    print(f"Sending product {product_id} to Bale: {product_name}")
    print(f"Bale images found: {len(images)}")

    if not images:
        bale_request(
            "sendMessage",
            {
                "chat_id": BALE_CHANNEL_ID,
                "text": caption
            }
        )
        return True

    if len(images) == 1:
        bale_request(
            "sendPhoto",
            {
                "chat_id": BALE_CHANNEL_ID,
                "photo": images[0],
                "caption": caption
            }
        )
        return True

    media = []
    for index, image_url in enumerate(images[:MAX_IMAGES]):
        item = {
            "type": "photo",
            "media": image_url
        }
        if index == 0:
            item["caption"] = caption
        media.append(item)

    bale_request(
        "sendMediaGroup",
        {
            "chat_id": BALE_CHANNEL_ID,
            "media": json.dumps(media, ensure_ascii=False)
        },
        timeout=120
    )
    return True



# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("Mahza Collection Telegram Publisher")
    print("=" * 60)

    print(f"TEST_MODE = {TEST_MODE}")

    print(
        f"MAX_PRODUCTS_PER_RUN = {MAX_PRODUCTS_PER_RUN}"
    )

    # Load state

    published_ids = load_published_ids()

    print(
        f"Published IDs loaded: {len(published_ids)}"
    )

    # Get products

    products = get_products()

    # Publish independently to Bale. This has its own state file so
    # the existing Telegram history does not block the initial Bale rollout.
    bale_published_ids = load_bale_published_ids()
    new_bale_products = []

    for product in products:
        if not isinstance(product, dict) or not is_available(product):
            continue

        product_id = product.get("id")
        if product_id is None:
            continue

        try:
            product_id = int(product_id)
        except (ValueError, TypeError):
            continue

        if product_id not in bale_published_ids:
            new_bale_products.append(product)

    def bale_sort_id(product):
        try:
            return int(product.get("id", 0))
        except (ValueError, TypeError):
            return 0

    new_bale_products.sort(key=bale_sort_id, reverse=True)

    if TEST_MODE:
        selected_bale_products = new_bale_products[:1]
    elif MAX_PRODUCTS_PER_RUN > 0:
        selected_bale_products = new_bale_products[:MAX_PRODUCTS_PER_RUN]
    else:
        selected_bale_products = new_bale_products

    print(f"New available products for Bale: {len(new_bale_products)}")
    print(f"Products selected for Bale: {len(selected_bale_products)}")

    bale_success_count = 0
    bale_error_count = 0

    for product in selected_bale_products:
        product_id = product.get("id")
        try:
            success = send_product_to_bale(product)
            if success:
                bale_published_ids.add(int(product_id))
                save_bale_published_ids(bale_published_ids)
                bale_success_count += 1
                print(f"BALE SUCCESS: Product {product_id} published.")
        except Exception as error:
            bale_error_count += 1
            print(f"BALE ERROR publishing product {product_id}: {error}")

        time.sleep(DELAY_BETWEEN_PRODUCTS)

    # Find new available products

    new_products = []

    for product in products:

        if not isinstance(product, dict):
            continue

        if not is_available(product):
            continue

        product_id = product.get("id")

        if product_id is None:
            continue

        try:
            product_id = int(product_id)
        except (ValueError, TypeError):
            continue

        if product_id not in published_ids:
            new_products.append(product)

    print(
        f"New available products found: {len(new_products)}"
    )

    # Newest first

    def sort_id(product):
        try:
            return int(product.get("id", 0))
        except (ValueError, TypeError):
            return 0

    new_products.sort(
        key=sort_id,
        reverse=True
    )

    # Select products

    if TEST_MODE:

        selected_products = new_products[:1]

    elif MAX_PRODUCTS_PER_RUN > 0:

        selected_products = new_products[
            :MAX_PRODUCTS_PER_RUN
        ]

    else:

        selected_products = new_products

    print(
        f"Products selected: {len(selected_products)}"
    )

    success_count = 0
    error_count = 0

    # Publish

    for product in selected_products:

        product_id = product.get("id")

        try:

            success = send_product_to_telegram(
                product
            )

            if success:

                # Save only after successful Telegram response

                published_ids.add(
                    int(product_id)
                )

                save_published_ids(
                    published_ids
                )

                success_count += 1

                print(
                    f"SUCCESS: Product {product_id} published."
                )

                print(
                    f"Saved published IDs: {len(published_ids)}"
                )

        except Exception as error:

            error_count += 1

            print(
                f"ERROR publishing product {product_id}: {error}"
            )

        time.sleep(DELAY_BETWEEN_PRODUCTS)

    # Summary

    print("=" * 60)

    print("PUBLISHING SUMMARY")

    print(f"New products found: {len(new_products)}")

    print(f"Products selected: {len(selected_products)}")

    print(f"Successfully published: {success_count}")

    print(f"Errors: {error_count}")

    print(f"Total saved Telegram IDs: {len(published_ids)}")
    print(f"Bale successfully published: {bale_success_count}")
    print(f"Bale errors: {bale_error_count}")
    print(f"Total saved Bale IDs: {len(bale_published_ids)}")

    print("Finished.")

    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()

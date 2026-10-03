import html
import json
import os
import time
from pathlib import Path
from urllib.parse import urljoin

import requests


# =========================================================
# SETTINGS
# =========================================================

MIXIN_API_URL = "https://mahzacollection.ir/api/v4/products/"
SITE_URL = "https://mahzacollection.ir"

STATE_FILE = Path("published_products.json")

PAGE_SIZE = 50

# ---------------------------------------------------------
# TEST MODE
#
# true  = فقط یک محصول جدید را برای تست ارسال می‌کند
# false = همه محصولات جدید را ارسال می‌کند
# ---------------------------------------------------------

TEST_MODE = os.getenv("TEST_MODE", "true").lower() == "true"

# حداکثر تعداد محصول در هر اجرای ربات
# اگر 0 باشد محدودیتی وجود ندارد.
MAX_PRODUCTS_PER_RUN = int(
    os.getenv("MAX_PRODUCTS_PER_RUN", "1" if TEST_MODE else "0")
)

# فاصله بین ارسال محصولات
SLEEP_BETWEEN_PRODUCTS = 2


# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

MIXIN_API_KEY = os.getenv("MIXIN_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")


# =========================================================
# VALIDATE SETTINGS
# =========================================================

def validate_settings():
    missing = []

    if not MIXIN_API_KEY:
        missing.append("MIXIN_API_KEY")

    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")

    if not TELEGRAM_CHANNEL_ID:
        missing.append("TELEGRAM_CHANNEL_ID")

    if missing:
        raise RuntimeError(
            "Missing environment variables: " + ", ".join(missing)
        )


# =========================================================
# STATE
# =========================================================

def load_state():
    if not STATE_FILE.exists():
        return {"published_ids": []}

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {"published_ids": []}

        published_ids = data.get("published_ids", [])

        if not isinstance(published_ids, list):
            published_ids = []

        return {
            "published_ids": published_ids
        }

    except Exception as exc:
        print(f"Warning: could not read state file: {exc}")
        return {"published_ids": []}


def save_state(state):
    temp_file = STATE_FILE.with_suffix(".tmp")

    with temp_file.open("w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )

    temp_file.replace(STATE_FILE)


# =========================================================
# MIXIN API
# =========================================================

def get_products():
    headers = {
        "Authorization": f"Api-Key {MIXIN_API_KEY}",
        "Accept": "application/json",
    }

    products = []
    page = 1

    while True:

        params = {
            "page": page,
            "page_size": PAGE_SIZE,
            "ordering": "-creation_date",
            "available": "true",
        }

        print(f"Getting products page {page}...")

        response = requests.get(
            MIXIN_API_URL,
            headers=headers,
            params=params,
            timeout=30,
        )

        response.raise_for_status()

        result = response.json()

        if result.get("status") != "success":
            raise RuntimeError(
                f"Mixin API error: {result}"
            )

        page_products = result.get("data", [])

        products.extend(page_products)

        pagination = result.get("pagination", {})

        has_next = pagination.get("has_next", False)

        print(
            f"Received {len(page_products)} products "
            f"from page {page}."
        )

        if not has_next:
            break

        page += 1

    print(f"Total products received: {len(products)}")

    return products


# =========================================================
# PRODUCT URL
# =========================================================

def get_product_url(product):
    """
    Mixin API response currently gives us the product ID
    but not the complete public URL.

    Mahza Collection public product URLs use:

    https://mahzacollection.ir/product/PRODUCT_ID/

    For example:

    https://mahzacollection.ir/product/126/
    """

    product_id = product.get("id")

    if not product_id:
        raise ValueError("Product has no ID.")

    return f"{SITE_URL}/product/{product_id}/"


# =========================================================
# IMAGES
# =========================================================

def get_product_images(product):
    images = []

    default_image = product.get("default_image")

    if isinstance(default_image, dict):
        image_url = default_image.get("image")

        if image_url:
            images.append(image_url)

    for image in product.get("images", []):

        if not isinstance(image, dict):
            continue

        image_url = image.get("image")

        if not image_url:
            continue

        if image_url not in images:
            images.append(image_url)

    # Maximum 3 images
    images = images[:3]

    normalized = []

    for image_url in images:
        image_url = urljoin(
            SITE_URL + "/",
            image_url
        )

        normalized.append(image_url)

    return normalized


# =========================================================
# PRICE
# =========================================================

def format_price(value):
    if value is None:
        return "تماس بگیرید"

    try:
        number = int(float(value))
        return f"{number:,} تومان"

    except (ValueError, TypeError):
        return str(value)


# =========================================================
# DISCOUNT
# =========================================================

def calculate_discount(product):

    price = product.get("price")
    compare_at_price = product.get("compare_at_price")

    try:
        price = float(price)
        compare_at_price = float(compare_at_price)

    except (ValueError, TypeError):
        return None

    if compare_at_price <= 0:
        return None

    if price >= compare_at_price:
        return None

    discount = (
        (compare_at_price - price)
        / compare_at_price
        * 100
    )

    return round(discount)


# =========================================================
# TELEGRAM CAPTION
# =========================================================

def create_caption(product):

    name = product.get("name") or "محصول جدید"

    brand_data = product.get("brand")

    if isinstance(brand_data, dict):
        brand = brand_data.get("name") or "بدون برند"
    else:
        brand = "بدون برند"

    price = format_price(
        product.get("price")
    )

    discount = calculate_discount(product)

    compare_at_price = product.get(
        "compare_at_price"
    )

    product_url = get_product_url(product)

    lines = [
        f"🛍 <b>{html.escape(str(name))}</b>",
        "",
        f"🏷 <b>برند:</b> {html.escape(str(brand))}",
        f"💰 <b>قیمت:</b> {html.escape(price)}",
    ]

    if discount is not None:
        lines.extend([
            f"🔥 <b>تخفیف:</b> {discount}٪",
            f"💵 <b>قیمت قبل:</b> "
            f"{html.escape(format_price(compare_at_price))}",
        ])

    lines.extend([
        "",
        f'🛒 <a href="{html.escape(product_url)}">'
        f"مشاهده و خرید محصول</a>",
        "",
        "✨ <b>Mahza Collection</b>",
        "🌐 mahzacollection.ir",
    ])

    return "\n".join(lines)


# =========================================================
# TELEGRAM API
# =========================================================

def telegram_url(method):
    return (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/{method}"
    )


def telegram_request(method, data):

    response = requests.post(
        telegram_url(method),
        data=data,
        timeout=60,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram API error: {result}"
        )

    return result


# =========================================================
# SEND PRODUCT
# =========================================================

def send_product(product):

    product_id = product.get("id")

    name = product.get("name") or "بدون نام"

    caption = create_caption(product)

    images = get_product_images(product)

    print(
        f"Sending product "
        f"{product_id}: {name}"
    )

    print(
        f"Images found: {len(images)}"
    )

    # -----------------------------------------------------
    # NO IMAGE
    # -----------------------------------------------------

    if not images:

        telegram_request(
            "sendMessage",
            {
                "chat_id": TELEGRAM_CHANNEL_ID,
                "text": caption,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
        )

        return

    # -----------------------------------------------------
    # ONE IMAGE
    # -----------------------------------------------------

    if len(images) == 1:

        telegram_request(
            "sendPhoto",
            {
                "chat_id": TELEGRAM_CHANNEL_ID,
                "photo": images[0],
                "caption": caption,
                "parse_mode": "HTML",
            },
        )

        return

    # -----------------------------------------------------
    # MULTIPLE IMAGES
    # -----------------------------------------------------

    media = []

    for index, image_url in enumerate(images):

        item = {
            "type": "photo",
            "media": image_url,
        }

        # Caption is placed on the first image only.
        if index == 0:
            item["caption"] = caption
            item["parse_mode"] = "HTML"

        media.append(item)

    telegram_request(
        "sendMediaGroup",
        {
            "chat_id": TELEGRAM_CHANNEL_ID,
            "media": json.dumps(
                media,
                ensure_ascii=False
            ),
        },
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print("=" * 60)
    print("Mahza Collection Telegram Publisher")
    print("=" * 60)

    print(
        f"TEST_MODE = {TEST_MODE}"
    )

    print(
        f"MAX_PRODUCTS_PER_RUN = "
        f"{MAX_PRODUCTS_PER_RUN}"
    )

    validate_settings()

    state = load_state()

    published_ids = set(
        str(product_id)
        for product_id in state.get(
            "published_ids",
            []
        )
    )

    products = get_products()

    new_products = []

    for product in products:

        product_id = product.get("id")

        if not product_id:
            continue

        product_id = str(product_id)

        if product_id in published_ids:
            continue

        new_products.append(product)

    print(
        f"New products found: "
        f"{len(new_products)}"
    )

    if not new_products:
        print(
            "No new products to publish."
        )
        return

    # -----------------------------------------------------
    # Initial/newest products come from API newest-first.
    #
    # Reverse them so that during a first bulk publish,
    # older products are published before newer ones.
    # -----------------------------------------------------

    new_products.reverse()

    if MAX_PRODUCTS_PER_RUN > 0:

        new_products = new_products[
            :MAX_PRODUCTS_PER_RUN
        ]

    print(
        f"Products selected for this run: "
        f"{len(new_products)}"
    )

    for product in new_products:

        product_id = product.get("id")

        try:

            send_product(product)

            # IMPORTANT:
            # Only mark as published AFTER successful
            # Telegram delivery.

            published_ids.add(
                str(product_id)
            )

            state["published_ids"] = sorted(
                published_ids,
                key=lambda x: int(x)
                if str(x).isdigit()
                else str(x)
            )

            save_state(state)

            print(
                f"SUCCESS: product "
                f"{product_id} published."
            )

        except Exception as exc:

            print(
                f"ERROR publishing product "
                f"{product_id}: {exc}"
            )

            # Do not mark failed products as published.
            continue

        time.sleep(
            SLEEP_BETWEEN_PRODUCTS
        )

    print("=" * 60)
    print("Finished.")
    print("=" * 60)


if __name__ == "__main__":
    main()

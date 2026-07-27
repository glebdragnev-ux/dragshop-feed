import json
import os
import urllib.request
import xml.etree.ElementTree as ET


# =========================
# Загрузка настроек
# =========================

with open("config.json", "r", encoding="utf-8") as file:
    config = json.load(file)


SOURCE_URL = config.get(
    "source_url",
    "https://b2b.yugtorg.com/upload/prom_yml.xml"
)

SOURCE_FILE = "source/source.xml"
TEMP_FILE = "source/source_temp.xml"
OUTPUT_FILE = "output/feed.xml"

PRICE_MARKUP = config.get("price_markup", [])
MIN_STOCK = config.get("min_stock", 1)
MAX_PRODUCTS = config.get("max_products", 10000)

EXCLUDE_CATEGORIES = {
    str(category).strip().lower()
    for category in config.get("exclude_categories", [])
}

EXCLUDE_BRANDS = {
    str(brand).strip().lower()
    for brand in config.get("exclude_brands", [])
}


# =========================
# Функция определения наценки
# =========================

def get_markup(price):
    selected_markup = 0

    sorted_rules = sorted(
        PRICE_MARKUP,
        key=lambda rule: float(rule.get("min", 0))
    )

    for rule in sorted_rules:
        min_price = float(rule.get("min", 0))
        max_value = rule.get("max")
        markup = float(rule.get("markup", 0))

        max_price = None

        if max_value is not None:
            max_price = float(max_value)

        if price >= min_price:
            selected_markup = markup

        if price >= min_price and (
            max_price is None or price < max_price
        ):
            return markup

    return selected_markup


# =========================
# Начало работы
# =========================

print("=" * 50)
print("DragShop Feed Builder")
print("=" * 50)

print(f"Диапазонов наценки: {len(PRICE_MARKUP)}")
print(f"Минимальный остаток: {MIN_STOCK}")
print(f"Максимум товаров: {MAX_PRODUCTS}")


# =========================
# Скачивание свежего XML
# =========================

os.makedirs("source", exist_ok=True)

print("\nСкачиваю свежий XML поставщика...")

try:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=180
    ) as response:

        with open(TEMP_FILE, "wb") as file:

            while True:
                chunk = response.read(1024 * 1024)

                if not chunk:
                    break

                file.write(chunk)

    # Проверяем, что скачанный файл является XML
    ET.parse(TEMP_FILE)

    os.replace(TEMP_FILE, SOURCE_FILE)

    print("Свежий XML успешно скачан.")

except Exception as error:

    if os.path.exists(TEMP_FILE):
        os.remove(TEMP_FILE)

    print(f"Не удалось скачать свежий XML: {error}")

    if not os.path.exists(SOURCE_FILE):
        raise Exception(
            "Нет сохранённого source/source.xml для продолжения работы."
        )

    print("Использую предыдущий сохранённый XML.")


# =========================
# Чтение XML
# =========================

print("\nЧитаю XML...")

tree = ET.parse(SOURCE_FILE)
root = tree.getroot()

offers_node = root.find(".//offers")

if offers_node is None:
    raise Exception("Не найден раздел <offers>")

offers = offers_node.findall("offer")

print(f"Всего товаров: {len(offers)}")


# =========================
# Чтение категорий
# =========================

categories = {}

for category in root.findall(".//category"):
    category_id = category.attrib.get("id")

    if category_id:
        categories[category_id] = (
            category.text or ""
        ).strip()

print(f"Категорий: {len(categories)}")


# =========================
# Счётчики
# =========================

new_offers = []

removed_stock = 0
removed_category = 0
removed_brand = 0
price_changed = 0
price_errors = 0


# =========================
# Фильтрация товаров
# =========================

print("\nФильтрую товары...")

for offer in offers:

    # -------------------------
    # Проверка остатка
    # -------------------------

    stock_value = 0
    stock_node = offer.find("quantity_in_stock")

    if stock_node is not None:

        try:
            stock_value = int(
                float(stock_node.text or "0")
            )

        except (ValueError, TypeError):
            stock_value = 0

    if stock_value < MIN_STOCK:
        removed_stock += 1
        continue


    # -------------------------
    # Проверка категории
    # -------------------------

    category_node = offer.find("categoryId")

    if category_node is not None:

        category_id = (
            category_node.text or ""
        ).strip()

        category_name = categories.get(
            category_id,
            ""
        ).strip().lower()

        if category_name in EXCLUDE_CATEGORIES:
            removed_category += 1
            continue


    # -------------------------
    # Проверка бренда
    # -------------------------

    vendor_node = offer.find("vendor")

    if vendor_node is not None:

        brand_name = (
            vendor_node.text or ""
        ).strip().lower()

        if brand_name in EXCLUDE_BRANDS:
            removed_brand += 1
            continue


    # -------------------------
    # Наценка по цене
    # -------------------------

    price_node = offer.find("price")

    if price_node is not None:

        try:
            old_price = float(
                (price_node.text or "0").replace(",", ".")
            )

            markup = get_markup(old_price)

            new_price = round(
                old_price * (1 + markup / 100),
                2
            )

            price_node.text = f"{new_price:.2f}"

            price_changed += 1

        except (ValueError, TypeError, AttributeError):
            price_errors += 1


    new_offers.append(offer)


print(f"После фильтрации: {len(new_offers)} товаров")


# =========================
# Ограничение до 10 000
# =========================

if len(new_offers) > MAX_PRODUCTS:

    print("\nСортирую товары...")

    def get_score(offer):
        stock = 0
        price = 0

        stock_node = offer.find("quantity_in_stock")

        if stock_node is not None:

            try:
                stock = int(
                    float(stock_node.text or "0")
                )

            except (ValueError, TypeError):
                stock = 0

        price_node = offer.find("price")

        if price_node is not None:

            try:
                price = float(
                    (price_node.text or "0").replace(",", ".")
                )

            except (ValueError, TypeError, AttributeError):
                price = 0

        return stock, price

    new_offers.sort(
        key=get_score,
        reverse=True
    )

    print(
        f"Оставляю лучшие {MAX_PRODUCTS} товаров..."
    )

    new_offers = new_offers[:MAX_PRODUCTS]


# =========================
# Замена списка товаров
# =========================

offers_node.clear()

for offer in new_offers:
    offers_node.append(offer)


# =========================
# Сохранение результата
# =========================

os.makedirs("output", exist_ok=True)

tree.write(
    OUTPUT_FILE,
    encoding="utf-8",
    xml_declaration=True
)


# =========================
# Итоговая статистика
# =========================

print("\n" + "=" * 50)
print("ГОТОВО")
print("=" * 50)

print(f"Исходных товаров: {len(offers)}")
print(f"Удалено без наличия: {removed_stock}")
print(f"Удалено по категориям: {removed_category}")
print(f"Удалено по брендам: {removed_brand}")
print(f"Изменено цен: {price_changed}")
print(f"Ошибок цены: {price_errors}")
print(f"Осталось товаров: {len(new_offers)}")

print("\nФайл сохранён:")
print(OUTPUT_FILE)

print("=" * 50)
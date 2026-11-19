"""
Google Merchant Center product feed (RSS 2.0 + g: namespace), built ONLY from
real Shopify products.

Rules:
- One <item> per variant (colour/size), linked by item_group_id — required by
  Google for apparel with variants.
- Only active, published products with a price > 0 and an image are included.
- Never invents products, prices, links or descriptions. If Shopify can't be
  reached, the caller must return an error instead of a feed (see main.py).
"""
import html
import os
import re
import xml.dom.minidom
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

G_NS = "http://base.google.com/ns/1.0"
ET.register_namespace("g", G_NS)

FEED_BRAND = os.getenv("FEED_BRAND", "Grozavu")
FEED_DOMAIN = os.getenv("FEED_DOMAIN", "maisongrozavu.com")

# Kept only so old imports don't break. Intentionally EMPTY: the feed never
# contains made-up products any more.
DEFAULT_LUXURY_PRODUCTS: List[Dict[str, Any]] = []

COLOR_OPTION_NAMES = {"color", "colour", "culoare", "farbe", "couleur", "colore"}
SIZE_OPTION_NAMES = {"size", "talla", "marime", "mărime", "größe", "grosse", "taille", "taglia", "tamaño", "tamano"}

ALLOWED_AVAILABILITY = {"in_stock", "out_of_stock", "preorder", "backorder"}
ALLOWED_CONDITION = {"new", "refurbished", "used"}
PRICE_RE = re.compile(r"^\d+(\.\d{1,2})? [A-Z]{3}$")
GTIN_RE = re.compile(r"^(\d{8}|\d{12}|\d{13}|\d{14})$")

# keyword -> Google product category (text form of the official taxonomy)
_CATEGORY_RULES: List[Tuple[Tuple[str, ...], str]] = [
    (("hoodie", "hoody", "sweatshirt", "crewneck", "sudadera", "hanorac", "jumper", "pullover"),
     "Apparel & Accessories > Clothing > Shirts & Tops"),
    (("t-shirt", "tshirt", "tee", "camiseta", "tricou", "top", "polo", "shirt", "long sleeve"),
     "Apparel & Accessories > Clothing > Shirts & Tops"),
    (("jacket", "windbreaker", "coat", "bomber", "chaqueta", "geacă", "geaca", "parka", "puffer"),
     "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets"),
    (("jogger", "pants", "trousers", "sweatpants", "pantal", "pantaloni", "shorts"),
     "Apparel & Accessories > Clothing > Pants"),
    (("cap", "hat", "beanie", "gorra", "șapcă", "sapca", "bucket"),
     "Apparel & Accessories > Clothing Accessories > Hats"),
    (("bag", "tote", "backpack", "sling", "bolso", "geantă", "geanta", "mochila"),
     "Apparel & Accessories > Handbags, Wallets & Cases"),
    (("sock", "calcet", "șosete", "sosete"),
     "Apparel & Accessories > Clothing > Underwear & Socks > Socks"),
]
DEFAULT_CATEGORY = "Apparel & Accessories > Clothing"


def _plain_text(val: Optional[str]) -> str:
    """HTML -> plain text. Returns UNESCAPED text (ElementTree escapes on output)."""
    if not val:
        return ""
    text = re.sub(r"<(br|/p|/li|/h\d)\s*/?>", " ", str(val), flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _category_for(product: Dict[str, Any]) -> str:
    hay = " ".join([
        str(product.get("product_type") or ""),
        str(product.get("title") or ""),
        str(product.get("tags") or ""),
    ]).lower()
    for keywords, category in _CATEGORY_RULES:
        if any(k in hay for k in keywords):
            return category
    return DEFAULT_CATEGORY


_FEMALE_RE = re.compile(r"\b(women|woman|womens|women's|female|mujer|femei|dama|damă|ladies)\b")
_MALE_RE = re.compile(r"\b(men|man|mens|men's|male|hombre|bărbați|barbati)\b")
_KIDS_RE = re.compile(r"\b(kids|kid|children|child|niños|ninos|niño|copii|copil|toddler|youth)\b")

# Garment colours we accept from a "Title — Colour" suffix (conservative: graphic colours like
# "Gold Hare" or "Deep Red Mark" are NOT taken as the garment colour).
_COLOUR_WORDS = {
    "black", "white", "off-white", "navy", "french navy", "grey", "gray", "heather grey", "charcoal",
    "beige", "cream", "ecru", "sand", "stone", "khaki", "olive", "green", "forest green", "sage",
    "blue", "sky blue", "red", "bordeaux", "burgundy", "maroon", "wine", "cocoa", "brown", "chocolate",
    "tan", "camel", "pink", "blush", "blush pink", "soft pink", "magenta", "purple", "lilac", "lavender",
    "yellow", "mustard", "orange", "rust", "natural", "bone", "vintage black", "washed black",
    "desert dust", "dust", "sandshell", "ivory",
}

_DESC_IN_COLOUR_RE = re.compile(
    r"\b(?:garment-dyed\s+|dyed\s+|knit\s+|woven\s+|cut\s+|finished\s+)?"
    r"in\s+(blush pink|soft pink|french navy|heather grey|vintage black|washed black|forest green|"
    r"desert dust|sandshell|off-white|bordeaux|burgundy|charcoal|black|white|ivory|cream|beige|ecru|"
    r"sand|dust|stone|khaki|olive|sage|navy|grey|gray|blue|red|brown|cocoa|tan|camel|blush|pink|bone)\b",
    re.I,
)
_DESC_ARTICLE_COLOUR_RE = re.compile(
    r"\b(?:a|an)\s+(?:[a-z-]+,\s*[a-z-]+\s+)?"
    r"(blush pink|soft pink|french navy|heather grey|vintage black|washed black|forest green|"
    r"desert dust|sandshell|off-white|bordeaux|burgundy|charcoal|black|white|ivory|cream|beige|ecru|"
    r"sand|dust|olive|navy|grey|gray|blue|red|brown|cocoa|tan|camel|blush|pink|bone)\s+"
    r"(?:bucket hat|hat|cap|beanie|tote|bag|crossbody|half-zip|quarter-zip|pullover|hoodie|crewneck|"
    r"sweatshirt|tee|t-shirt|shirt|tank|top|jacket|windbreaker|pants|trousers|joggers|shorts)\b",
    re.I,
)
_MATERIAL_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b100%\s+organic\s+cotton\s+twill\b", re.I), "100% Organic Cotton Twill"),
    (re.compile(r"\b100%\s+organic\s+(?:ring-spun\s+)?(?:combed\s+)?cotton\b", re.I), "100% Organic Cotton"),
    (re.compile(r"\b100%\s+(?:bio-washed\s+)?(?:chino\s+)?cotton\s+twill\b", re.I), "100% Cotton Twill"),
    (re.compile(r"\bcotton\s+twill\b", re.I), "Cotton Twill"),
    (re.compile(r"\bcotton[- ]elastane\b", re.I), "Cotton-Elastane"),
    (re.compile(r"\b100%\s+recycled\s+nylon\b", re.I), "100% Recycled Nylon"),
    (re.compile(r"\b100%\s+nylon\s+taslan\b", re.I), "100% Nylon Taslan"),
    (re.compile(r"\bsmooth\s+matte\s+nylon\b", re.I), "Nylon"),
    (re.compile(r"\brecycled\s+polyester\b", re.I), "Recycled Polyester"),
    (re.compile(r"\bwater-resistant\s+polyester\b", re.I), "Polyester"),
    (re.compile(r"\bpolyamide\b", re.I), "Polyamide"),
    (re.compile(r"\bairlume\s+combed\s+ring-spun\s+cotton\b", re.I), "Combed Ring-Spun Cotton"),
    (re.compile(r"\bcombed\s+ring-spun\s+cotton\b", re.I), "Combed Ring-Spun Cotton"),
    (re.compile(r"\bring-spun\s+(?:combed\s+)?cotton\b", re.I), "Ring-Spun Cotton"),
    (re.compile(r"\b(?:three-end|3-end)\s+fleece\b", re.I), "Three-End Cotton Fleece"),
    (re.compile(r"\bbrushed\s+fleece\b", re.I), "Brushed Fleece"),
    (re.compile(r"\b100%\s+(?:lightweight\s+)?cotton\b", re.I), "100% Cotton"),
]


def _category_attrs(product: Dict[str, Any]) -> Dict[str, List[str]]:
    """The owner's Shopify Category metafields attached by the feed loader (may be missing)."""
    attrs = product.get("_category_attrs")
    return attrs if isinstance(attrs, dict) else {}


def _colour_from_category(product: Dict[str, Any]) -> str:
    """Colour from the owner's Category metafield 'Color' (shopify.color-pattern), max 3 labels."""
    labels = [str(x).strip() for x in (_category_attrs(product).get("colors") or []) if str(x).strip()]
    return "/".join(labels[:3])


def _gender_for(product: Dict[str, Any]) -> str:
    """Google's gender attribute (machine value, not shown as store text).
    The owner's Category metafield 'Target gender' decides first; then the title
    ("Women's Wide-Leg Pants"); if type/tags mention both genders -> unisex."""
    meta = {str(g).strip().lower() for g in (_category_attrs(product).get("genders") or [])}
    if meta:
        is_f = bool(meta & {"female", "women", "woman"})
        is_m = bool(meta & {"male", "men", "man"})
        if is_f and is_m:
            return "unisex"
        if is_f:
            return "female"
        if is_m:
            return "male"
        if "unisex" in meta:
            return "unisex"
    title = str(product.get("title") or "").lower()
    if _FEMALE_RE.search(title) and not _MALE_RE.search(title):
        return "female"
    if _MALE_RE.search(title) and not _FEMALE_RE.search(title):
        return "male"
    rest = " ".join([str(product.get("product_type") or ""), str(product.get("tags") or "")]).lower()
    female, male = bool(_FEMALE_RE.search(rest)), bool(_MALE_RE.search(rest))
    if female and not male:
        return "female"
    if male and not female:
        return "male"
    return "unisex"


def _age_group_for(product: Dict[str, Any]) -> str:
    meta = {str(a).strip().lower() for a in (_category_attrs(product).get("age_groups") or [])}
    if meta & {"kids", "children", "toddlers", "infants", "babies"} and not meta & {"adults", "adult"}:
        return "kids"
    if meta & {"adults", "adult"}:
        return "adult"
    hay = " ".join([str(product.get("title") or ""), str(product.get("product_type") or ""),
                    str(product.get("tags") or "")]).lower()
    return "kids" if _KIDS_RE.search(hay) else "adult"


def _colour_from_title(product: Dict[str, Any]) -> str:
    """'Heritage Tartan Hoodie — Bordeaux' -> 'Bordeaux'. Only when the whole suffix is a known colour."""
    title = str(product.get("title") or "")
    for sep in (" — ", " – ", " - "):
        if sep in title:
            suffix = title.rsplit(sep, 1)[1].strip()
            if suffix.lower() in _COLOUR_WORDS:
                return suffix
    return ""


def _colour_from_description(product: Dict[str, Any]) -> str:
    """
    Extract explicit garment colour stated in body_html when the product has no colour option or suffix
    (e.g. '300 g/m² cotton-elastane in blush pink', 'A black bucket hat in 100% cotton twill',
    'split down the middle in black and soft pink', 'black on black').
    Never guesses from graphic print names.
    """
    raw_body = _plain_text(product.get("body_html"))
    if not raw_body:
        return ""
    if re.search(r"\bsplit down the middle in black and soft pink\b", raw_body, re.I):
        return "Black / Soft Pink"
    m_art = _DESC_ARTICLE_COLOUR_RE.search(raw_body)
    if m_art:
        return m_art.group(1).title()
    m_in = _DESC_IN_COLOUR_RE.search(raw_body)
    if m_in:
        return m_in.group(1).title()
    if re.search(r"\bblack on black\b", raw_body, re.I):
        return "Black"
    return ""


def _colour_from_images(image_urls: List[str]) -> str:
    """
    Infer garment colour from Shopify/Printful image filenames when title, options and description
    don't state it. Strips trailing studio-backdrop suffixes ('-grey.jpg' / '-gray.jpg') and
    ignores print-only graphic phrases (e.g. 'deep-red-mark').
    """
    token_order = [
        ("beige-black", "Beige / Black"),
        ("black-white", "Black / White"),
        ("blush-pink", "Blush Pink"),
        ("french-navy", "French Navy"),
        ("forest-green", "Forest Green"),
        ("desert-dust", "Desert Dust"),
        ("off-white", "Off-White"),
        ("bordeaux", "Bordeaux"),
        ("burgundy", "Burgundy"),
        ("charcoal", "Charcoal"),
        ("sandshell", "Sandshell"),
        ("black", "Black"),
        ("white", "White"),
        ("beige", "Beige"),
        ("ivory", "Ivory"),
        ("cream", "Cream"),
        ("navy", "Navy"),
        ("olive", "Olive"),
        ("khaki", "Khaki"),
        ("cocoa", "Cocoa"),
        ("blush", "Blush"),
        ("dust", "Dust"),
        ("sand", "Sand"),
        ("ecru", "Ecru"),
        ("bone", "Bone"),
    ]
    for url in image_urls or []:
        if not url or not isinstance(url, str):
            continue
        fname = url.rsplit("/", 1)[-1].split("?", 1)[0].lower()
        # Strip file extension and studio grey backdrop suffix (-grey.jpg / -gray.jpg / -grey-v2.jpg)
        stem = re.sub(r"\.(?:jpe?g|png|webp|gif)$", "", fname)
        stem = re.sub(r"[-_](?:grey|gray)(?:[-_]v\d+)?$", "", stem)
        # Ignore graphic print colour names
        stem = re.sub(r"\bdeep[-_]red[-_]mark\b", "", stem)
        stem = re.sub(r"\bgold[-_]hare\b", "", stem)
        stem = re.sub(r"\bmagenta[-_]smoke\b", "", stem)
        for tok, label in token_order:
            if re.search(rf"(?:^|[-_]){re.escape(tok)}(?:$|[-_])", stem):
                return label
    return ""


def _material_for(product: Dict[str, Any]) -> str:
    """Extract factual fabric/material from body_html or title for <g:material>."""
    hay = " ".join([_plain_text(product.get("body_html")), str(product.get("title") or "")])
    for pattern, label in _MATERIAL_PATTERNS:
        if pattern.search(hay):
            return label
    fabrics = [str(x).strip() for x in (_category_attrs(product).get("fabrics") or []) if str(x).strip()]
    return "/".join(fabrics[:3])


def _option_positions(product: Dict[str, Any]) -> Dict[str, int]:
    """Map 'color'/'size' -> option position (1..3) using the product's option names."""
    positions: Dict[str, int] = {}
    for idx, opt in enumerate(product.get("options") or [], start=1):
        if not isinstance(opt, dict):
            continue
        name = str(opt.get("name") or "").strip().lower()
        pos = int(opt.get("position") or idx)
        if name in COLOR_OPTION_NAMES and "color" not in positions:
            positions["color"] = pos
        elif name in SIZE_OPTION_NAMES and "size" not in positions:
            positions["size"] = pos
    return positions


def _price(val: Any) -> Optional[float]:
    try:
        p = float(val)
        return p if p > 0 else None
    except (TypeError, ValueError):
        return None


def _is_sellable_product(p: Dict[str, Any]) -> Tuple[bool, str]:
    status = str(p.get("status") or "active").lower()
    if status != "active":
        return False, f"status={status}"
    if "published_at" in p and not p.get("published_at"):
        return False, "not published on the Online Store"
    if not p.get("handle"):
        return False, "missing handle (no product page URL)"
    return True, ""


def build_feed_items(
    products: Optional[List[Dict[str, Any]]],
    shop_domain: str = FEED_DOMAIN,
    brand: str = FEED_BRAND,
    currency: str = "EUR",
    visual_colors: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Returns (items, skipped). Each item is a dict of g:attribute -> value."""
    items: List[Dict[str, str]] = []
    skipped: List[Dict[str, str]] = []
    vcolors = visual_colors or {}

    for p in products or []:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "").strip()
        title = (p.get("title") or "").strip()
        if not pid or not title:
            skipped.append({"product": title or pid or "?", "reason": "missing id/title"})
            continue
        ok, why = _is_sellable_product(p)
        if not ok:
            skipped.append({"product": title, "reason": why})
            continue

        images = [img for img in (p.get("images") or []) if isinstance(img, dict) and img.get("src")]
        image_by_id = {str(img.get("id")): img["src"] for img in images if img.get("id")}
        main_image = images[0]["src"] if images else ((p.get("image") or {}).get("src") if isinstance(p.get("image"), dict) else None)
        if not main_image:
            skipped.append({"product": title, "reason": "no product image"})
            continue
        extra_images = [img["src"] for img in images[1:11]]

        description = _plain_text(p.get("body_html")) or title
        category = _category_for(p)
        gender = _gender_for(p)
        age_group = _age_group_for(p)
        # The owner's own Category metafield "Color" wins over every guess (title, text, images).
        title_colour = (
            _colour_from_category(p)
            or _colour_from_title(p)
            or _colour_from_description(p)
            or _colour_from_images([main_image] + extra_images)
            or str(vcolors.get(pid) or "").strip()
        )
        material = _material_for(p)
        positions = _option_positions(p)
        is_one_size_category = ("Hats" in category) or ("Handbags" in category)
        handle = p["handle"]
        variants = [v for v in (p.get("variants") or []) if isinstance(v, dict)]
        if not variants:
            skipped.append({"product": title, "reason": "no variants/price"})
            continue
        multi = len(variants) > 1

        for v in variants:
            vid = str(v.get("id") or "").strip()
            price = _price(v.get("price"))
            if not vid or price is None:
                skipped.append({"product": title, "reason": f"variant {vid or '?'} has no valid price"})
                continue
            compare_at = _price(v.get("compare_at_price"))

            color = str(v.get(f"option{positions['color']}") or "").strip() if "color" in positions else title_colour
            size = str(v.get(f"option{positions['size']}") or "").strip() if "size" in positions else ""
            v_title = str(v.get("title") or "").strip()
            if not size and (is_one_size_category or (not multi and v_title.lower() in ("", "default title", "one size", "os"))):
                size = "One Size"
            variant_colour = color if "color" in positions else ""
            label = " / ".join(x for x in (variant_colour, size if "size" in positions else "") if x) or ("" if v_title.lower() == "default title" else v_title)
            item_title = f"{title} - {label}" if (multi and label) else title

            tracked = str(v.get("inventory_management") or "").lower() == "shopify"
            qty = v.get("inventory_quantity")
            availability = "in_stock"
            try:
                if tracked and qty is not None and int(qty) <= 0 and str(v.get("inventory_policy") or "deny") != "continue":
                    availability = "out_of_stock"
            except (TypeError, ValueError):
                pass

            image = image_by_id.get(str(v.get("image_id"))) or main_image
            item: Dict[str, str] = {
                "id": f"shopify_{pid}_{vid}" if multi else f"shopify_{pid}",
                "title": item_title[:150],
                "description": description[:5000],
                "link": f"https://{shop_domain}/products/{handle}" + (f"?variant={vid}" if multi else ""),
                "image_link": image,
                "availability": availability,
                "condition": "new",
                "brand": brand,
                "google_product_category": category,
                "product_type": str(p.get("product_type") or "").strip() or category.split(" > ")[-1],
                "gender": gender,
                "age_group": age_group,
            }
            if compare_at and compare_at > price:
                item["price"] = f"{compare_at:.2f} {currency}"
                item["sale_price"] = f"{price:.2f} {currency}"
            else:
                item["price"] = f"{price:.2f} {currency}"
            if multi:
                item["item_group_id"] = f"shopify_{pid}"
            if color:
                item["color"] = color[:100]
            if size:
                item["size"] = size[:100]
            if material:
                item["material"] = material[:200]
            barcode = str(v.get("barcode") or "").strip()
            if GTIN_RE.match(barcode):
                item["gtin"] = barcode
            else:
                item["identifier_exists"] = "no"
            if extra_images:
                item["additional_image_link"] = extra_images  # type: ignore[assignment]
            items.append(item)

    return items, skipped


def build_google_merchant_xml(
    products: Optional[List[Dict[str, Any]]] = None,
    shop_domain: str = FEED_DOMAIN,
    store_name: str = FEED_BRAND,
    currency: str = "EUR",
    visual_colors: Optional[Dict[str, str]] = None,
) -> str:
    """Generate the RSS 2.0 Merchant feed from real Shopify products only."""
    items, _ = build_feed_items(
        products, shop_domain=shop_domain, brand=store_name, currency=currency, visual_colors=visual_colors
    )

    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = f"{store_name} - Google Merchant feed"
    ET.SubElement(channel, "link").text = f"https://{shop_domain}"
    ET.SubElement(channel, "description").text = f"Product feed for {store_name} ({shop_domain}), generated from Shopify."

    order = ["id", "item_group_id", "title", "description", "link", "image_link", "additional_image_link",
             "availability", "price", "sale_price", "brand", "condition", "gtin", "identifier_exists",
             "google_product_category", "product_type", "gender", "age_group", "color", "size", "material"]
    for data in items:
        node = ET.SubElement(channel, "item")
        for key in order:
            if key not in data:
                continue
            values = data[key] if isinstance(data[key], list) else [data[key]]
            for value in values:
                ET.SubElement(node, f"{{{G_NS}}}{key}").text = str(value)

    rough = ET.tostring(root, "utf-8")
    if b"xmlns:g=" not in rough:  # ElementTree only declares namespaces that are used
        rough = rough.replace(b"<rss ", f'<rss xmlns:g="{G_NS}" '.encode(), 1)
    return xml.dom.minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def validate_google_merchant_feed(xml_content: str) -> Dict[str, Any]:
    """Validate the feed against the Google Merchant Center product data spec."""
    errors: List[str] = []
    warnings: List[str] = []
    items_count = 0

    try:
        root = ET.fromstring(xml_content.encode("utf-8") if isinstance(xml_content, str) else xml_content)
    except Exception as e:
        return {"valid": False, "items_count": 0, "errors": [f"XML parse error: {e}"], "warnings": []}

    if root.tag != "rss" or root.attrib.get("version") != "2.0":
        errors.append("Root element must be <rss version='2.0'>")

    channel = root.find("channel")
    if channel is None:
        errors.append("Missing <channel> element inside <rss>")
        return {"valid": False, "items_count": 0, "errors": errors, "warnings": warnings}

    for req in ("title", "link", "description"):
        if channel.find(req) is None:
            errors.append(f"Channel missing <{req}> tag")

    ns = {"g": G_NS}

    def text(it, tag) -> str:
        node = it.find(f"g:{tag}", ns)
        return (node.text or "").strip() if node is not None and node.text else ""

    items = channel.findall("item")
    items_count = len(items)
    if items_count == 0:
        errors.append("Feed contains 0 products")

    seen_ids = set()
    groups: Dict[str, int] = {}
    for idx, it in enumerate(items, start=1):
        label = text(it, "id") or f"#{idx}"
        for tag in ("id", "title", "description", "link", "image_link", "availability", "price", "brand", "condition"):
            if not text(it, tag):
                errors.append(f"{label}: missing required <g:{tag}>")
        gid = text(it, "id")
        if gid:
            if gid in seen_ids:
                errors.append(f"{label}: duplicate id")
            seen_ids.add(gid)
            if len(gid) > 50:
                errors.append(f"{label}: id longer than 50 characters")
        if text(it, "availability") and text(it, "availability") not in ALLOWED_AVAILABILITY:
            errors.append(f"{label}: invalid availability '{text(it, 'availability')}'")
        if text(it, "condition") and text(it, "condition") not in ALLOWED_CONDITION:
            errors.append(f"{label}: invalid condition '{text(it, 'condition')}'")
        for price_tag in ("price", "sale_price"):
            val = text(it, price_tag)
            if val and not PRICE_RE.match(val):
                errors.append(f"{label}: invalid {price_tag} '{val}' (expected e.g. '49.00 EUR')")
        for url_tag in ("link", "image_link"):
            val = text(it, url_tag)
            if val and not val.startswith("https://"):
                errors.append(f"{label}: {url_tag} must be an https:// URL")
        if len(text(it, "title")) > 150:
            errors.append(f"{label}: title longer than 150 characters")
        if len(text(it, "description")) > 5000:
            errors.append(f"{label}: description longer than 5000 characters")
        if not text(it, "gtin") and text(it, "identifier_exists") != "no" and not text(it, "mpn"):
            warnings.append(f"{label}: no gtin/mpn and identifier_exists is not 'no'")
        for tag in ("gender", "age_group", "color", "size"):
            if not text(it, tag):
                warnings.append(f"{label}: apparel attribute <g:{tag}> missing (required in some countries)")
        grp = text(it, "item_group_id")
        if grp:
            groups[grp] = groups.get(grp, 0) + 1

    return {
        "valid": len(errors) == 0,
        "items_count": items_count,
        "product_groups": len(groups),
        "errors": errors,
        "warnings": warnings[:50],
        "warnings_count": len(warnings),
        "spec": "Google Merchant Center product data specification (RSS 2.0)",
    }

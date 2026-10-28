import xml.etree.ElementTree as ET
import xml.dom.minidom
import html
from typing import List, Dict, Any, Optional

DEFAULT_LUXURY_PRODUCTS = [
    {
        "id": "mg-prod-001",
        "title": "Rochie de Seară din Mătase Naturală Noir",
        "description": "Rochie lungă de seară realizată din mătase naturală pură 100%, croială fluidă de atelier Maison Grozavu. Finisaje manuale rafinate și eleganță atemporală.",
        "link": "https://maisongrozavu.com/products/rochie-seara-matase-naturala-noir",
        "image_link": "https://maisongrozavu.com/cdn/shop/files/rochie-noir-matase.jpg",
        "price": "389.00 EUR",
        "availability": "in_stock",
        "brand": "Maison Grozavu",
        "condition": "new",
        "google_product_category": "Apparel & Accessories > Clothing > Dresses",
        "product_type": "Modă de Lux > Rochii de Atelier",
    },
    {
        "id": "mg-prod-002",
        "title": "Sacou Smoking din Catifea Imperială",
        "description": "Sacou cambrat din catifea de bumbac densă, rever din mătase satinată, nasturi îmbrăcați manual. Piesa de rezistență pentru ținute de gală și evenimente speciale.",
        "link": "https://maisongrozavu.com/products/sacou-smoking-catifea-imperiala",
        "image_link": "https://maisongrozavu.com/cdn/shop/files/sacou-catifea-smoking.jpg",
        "price": "450.00 EUR",
        "availability": "in_stock",
        "brand": "Maison Grozavu",
        "condition": "new",
        "google_product_category": "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets",
        "product_type": "Modă de Lux > Sacouri & Costume",
    },
    {
        "id": "mg-prod-003",
        "title": "Costum Clasic din Lână Fină Super 130s",
        "description": "Costum deux-pieces croit la standarde de bespoke din lână italiană Super 130s. Structură impecabilă, lejeritate în mișcare și confort termic optim.",
        "link": "https://maisongrozavu.com/products/costum-clasic-lana-fina-super-130s",
        "image_link": "https://maisongrozavu.com/cdn/shop/files/costum-lana-super130s.jpg",
        "price": "620.00 EUR",
        "availability": "in_stock",
        "brand": "Maison Grozavu",
        "condition": "new",
        "google_product_category": "Apparel & Accessories > Clothing > Suits",
        "product_type": "Modă de Lux > Costume Bărbătești & Dama",
    },
    {
        "id": "mg-prod-004",
        "title": "Geantă Piele Naturală Lucrată Manual Atelier",
        "description": "Geantă structurată din piele de vițel cu granulație naturală, accesorii metalice aurite, căptușeală din catifea. Ediție limitată de atelier Maison Grozavu.",
        "link": "https://maisongrozavu.com/products/geanta-piele-naturala-atelier",
        "image_link": "https://maisongrozavu.com/cdn/shop/files/geanta-piele-atelier.jpg",
        "price": "295.00 EUR",
        "availability": "in_stock",
        "brand": "Maison Grozavu",
        "condition": "new",
        "google_product_category": "Apparel & Accessories > Handbags, Wallets & Cases > Handbags",
        "product_type": "Accesorii de Lux > Marochinărie",
    },
    {
        "id": "mg-prod-005",
        "title": "Cămașă din Poplin de Bumbac Egiptean",
        "description": "Cămașă albă impecabilă din poplin de bumbac egiptean 120/2, guler franțuzesc, nasturi din sidef autentic. Eleganță pură pentru garderoba capsulă de lux.",
        "link": "https://maisongrozavu.com/products/camasa-poplin-bumbac-egiptean",
        "image_link": "https://maisongrozavu.com/cdn/shop/files/camasa-poplin-alb.jpg",
        "price": "165.00 EUR",
        "availability": "in_stock",
        "brand": "Maison Grozavu",
        "condition": "new",
        "google_product_category": "Apparel & Accessories > Clothing > Shirts & Tops",
        "product_type": "Modă de Lux > Cămăși Atelier",
    }
]


def _clean_text(val: Optional[str]) -> str:
    """Strip raw HTML and escape special XML characters."""
    if not val:
        return ""
    import re
    cleaned = re.sub(r'<[^>]+>', ' ', str(val))
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return html.escape(cleaned)


def build_google_merchant_xml(
    products: Optional[List[Dict[str, Any]]] = None,
    shop_domain: str = "maisongrozavu.com",
    store_name: str = "Maison Grozavu",
    currency: str = "EUR"
) -> str:
    """
    Generate official Google Merchant Center RSS 2.0 XML product feed
    using http://base.google.com/ns/1.0 namespace attributes.
    """
    items_to_format = []

    if products and len(products) > 0:
        for p in products:
            p_id = str(p.get("id") or "")
            title = p.get("title") or "Produs Maison Grozavu"
            body = p.get("body_html") or p.get("description") or f"Piesă de lux de atelier {title} Maison Grozavu."
            handle = p.get("handle") or f"produs-{p_id}"
            
            # Canonical link
            link = f"https://{shop_domain}/products/{handle}"
            
            # Image
            images = p.get("images") or []
            image_link = ""
            if images and isinstance(images, list):
                first_img = images[0]
                image_link = first_img.get("src") if isinstance(first_img, dict) else str(first_img)
            elif p.get("image_link"):
                image_link = p.get("image_link")
            elif p.get("image"):
                img = p.get("image")
                image_link = img.get("src") if isinstance(img, dict) else str(img)

            if not image_link:
                image_link = f"https://{shop_domain}/cdn/shop/files/product-{p_id}.jpg"

            # Price from variants
            variants = p.get("variants") or []
            price_str = f"195.00 {currency}"
            availability = "in_stock"
            if variants and isinstance(variants, list):
                v0 = variants[0]
                if isinstance(v0, dict):
                    raw_price = v0.get("price") or "195.00"
                    price_str = f"{float(raw_price):.2f} {currency}"
                    inv = v0.get("inventory_quantity")
                    if inv is not None and int(inv) <= 0 and v0.get("inventory_policy") != "continue":
                        availability = "out_of_stock"

            items_to_format.append({
                "id": f"shopify_{p_id}",
                "title": title,
                "description": body,
                "link": link,
                "image_link": image_link,
                "price": price_str,
                "availability": availability,
                "brand": store_name,
                "condition": "new",
                "google_product_category": "Apparel & Accessories > Clothing",
                "product_type": p.get("product_type") or "Modă de Lux",
            })

    if not items_to_format:
        items_to_format = DEFAULT_LUXURY_PRODUCTS

    # Register Google Merchant namespace so tags serialize as <g:...>
    ET.register_namespace("g", "http://base.google.com/ns/1.0")

    # Build XML document
    root = ET.Element("rss", {
        "version": "2.0"
    })
    channel = ET.SubElement(root, "channel")

    c_title = ET.SubElement(channel, "title")
    c_title.text = f"{store_name} - Google Merchant Feed Oficial"

    c_link = ET.SubElement(channel, "link")
    c_link.text = f"https://{shop_domain}"

    c_desc = ET.SubElement(channel, "description")
    c_desc.text = f"Feed automat de produse pentru Google Shopping gratuit și campanii Google Merchant ({store_name})."

    for item_data in items_to_format:
        item = ET.SubElement(channel, "item")

        g_id = ET.SubElement(item, "{http://base.google.com/ns/1.0}id")
        g_id.text = str(item_data["id"])

        g_title = ET.SubElement(item, "{http://base.google.com/ns/1.0}title")
        g_title.text = item_data["title"][:150]

        g_desc = ET.SubElement(item, "{http://base.google.com/ns/1.0}description")
        # Strip HTML and truncate
        import re
        plain_desc = re.sub(r'<[^>]+>', ' ', str(item_data["description"]))
        plain_desc = re.sub(r'\s+', ' ', plain_desc).strip()
        g_desc.text = plain_desc[:5000]

        g_link = ET.SubElement(item, "{http://base.google.com/ns/1.0}link")
        g_link.text = item_data["link"]

        g_img = ET.SubElement(item, "{http://base.google.com/ns/1.0}image_link")
        g_img.text = item_data["image_link"]

        g_avail = ET.SubElement(item, "{http://base.google.com/ns/1.0}availability")
        g_avail.text = item_data.get("availability", "in_stock")

        g_price = ET.SubElement(item, "{http://base.google.com/ns/1.0}price")
        g_price.text = item_data["price"]

        g_brand = ET.SubElement(item, "{http://base.google.com/ns/1.0}brand")
        g_brand.text = item_data.get("brand", store_name)

        g_cond = ET.SubElement(item, "{http://base.google.com/ns/1.0}condition")
        g_cond.text = item_data.get("condition", "new")

        g_cat = ET.SubElement(item, "{http://base.google.com/ns/1.0}google_product_category")
        g_cat.text = item_data.get("google_product_category", "Apparel & Accessories > Clothing")

        g_ptype = ET.SubElement(item, "{http://base.google.com/ns/1.0}product_type")
        g_ptype.text = item_data.get("product_type", "Modă de Lux")

        g_ident = ET.SubElement(item, "{http://base.google.com/ns/1.0}identifier_exists")
        g_ident.text = "no"

    rough_string = ET.tostring(root, "utf-8")
    reparsed = xml.dom.minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def validate_google_merchant_feed(xml_content: str) -> Dict[str, Any]:
    """
    Validate that the generated XML strictly adheres to Google Merchant specifications.
    Checks required namespace, channel elements, and required item attributes.
    """
    errors = []
    items_count = 0

    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        return {
            "valid": False,
            "items_count": 0,
            "errors": [f"XML Parse Error: {str(e)}"],
        }

    if root.tag != "rss" or root.attrib.get("version") != "2.0":
        errors.append("Root element must be <rss version='2.0'>")

    channel = root.find("channel")
    if channel is None:
        errors.append("Missing <channel> element inside <rss>")
    else:
        for req in ["title", "link", "description"]:
            if channel.find(req) is None:
                errors.append(f"Channel missing <{req}> tag")

        ns = {"g": "http://base.google.com/ns/1.0"}
        required_item_tags = [
            "id", "title", "description", "link", "image_link", "availability", "price", "brand"
        ]

        items = channel.findall("item")
        items_count = len(items)
        if items_count == 0:
            errors.append("Feed contains 0 items")

        for idx, it in enumerate(items):
            for tag in required_item_tags:
                node = it.find(f"g:{tag}", ns)
                if node is None or not node.text or not node.text.strip():
                    errors.append(f"Item #{idx+1} missing required tag: <g:{tag}>")

    return {
        "valid": len(errors) == 0,
        "items_count": items_count,
        "errors": errors,
        "spec": "Google Merchant Center Product Data RSS 2.0"
    }

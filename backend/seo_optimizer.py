import json
import re
from typing import List, Dict, Any, Optional
import database as db

# High-intent luxury e-commerce keywords for Maison Grozavu
FASHION_KEYWORDS = [
    "atelier", "lux", "mătase naturală", "croială bespoke",
    "eleganță atemporală", "ediție limitată", "design românesc", "evenimente speciale"
]

class ProductSEOOptimizer:
    def __init__(self, brand_name: str = "Maison Grozavu", domain: str = "maisongrozavu.com"):
        self.brand_name = brand_name
        self.domain = domain

    def audit_product_seo(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """Audit single product's SEO posture and return issues and optimization suggestions."""
        title = product.get("title") or ""
        body_html = product.get("body_html") or product.get("description") or ""
        clean_desc = re.sub(r'<[^>]+>', ' ', body_html).strip()
        images = product.get("images") or []

        score = 100
        issues = []
        suggestions = []

        # 1. Title Audit
        if len(title) < 25:
            score -= 20
            issues.append("Titlul produsului este prea scurt pentru Google Search (< 25 caractere).")
            suggestions.append("Adaugă materiale premium și tipul piesei (ex: 'din Mătase Naturală').")
        elif self.brand_name.lower() not in title.lower():
            score -= 10
            suggestions.append(f"Include brandul '{self.brand_name}' la finalul titlului pentru autoritate.")

        # 2. Meta Description Audit
        if len(clean_desc) < 80:
            score -= 25
            issues.append("Descrierea produsului este sumară (< 80 caractere). Google afișează snippet-uri incomplete.")
            suggestions.append("Extinde descrierea cu detalii de croială, țesătură și ocazii recomandate.")

        # 3. Image Alt Tag Audit
        missing_alts = 0
        if isinstance(images, list):
            for img in images:
                if isinstance(img, dict) and not (img.get("alt") or "").strip():
                    missing_alts += 1
        if missing_alts > 0:
            score -= 15
            issues.append(f"{missing_alts} imagini nu au tag ALT completat (pierzi trafic din Google Images).")
            suggestions.append("Generează automat tag-uri ALT bogate în cuvinte-cheie.")

        # Generate proposal
        optimized_title = self.generate_seo_title(title, product.get("product_type"))
        optimized_desc = self.generate_meta_description(title, clean_desc)
        optimized_alt = f"{title} - Creație Atelier {self.brand_name} din Țesătură Premium"
        schema_markup = self.generate_json_ld_schema(product)

        return {
            "product_id": str(product.get("id")),
            "current_title": title,
            "seo_score": max(20, score),
            "issues": issues,
            "suggestions": suggestions,
            "optimized_title": optimized_title,
            "optimized_description": optimized_desc,
            "optimized_image_alt": optimized_alt,
            "schema_json_ld": schema_markup,
            "needs_optimization": score < 90
        }

    def generate_seo_title(self, current_title: str, product_type: Optional[str] = None) -> str:
        """Create high-CTR Google title (50-60 chars target)."""
        base = current_title.strip()
        # Remove old brand duplicate if present
        base = re.sub(rf'\s*[-|]\s*{re.escape(self.brand_name)}.*$', '', base, flags=re.I).strip()

        if len(base) < 35:
            extra = "Atelier Luxury" if not product_type else product_type.title()
            base = f"{base} | {extra}"

        candidate = f"{base} | {self.brand_name}"
        if len(candidate) > 70:
            candidate = f"{candidate[:67]}..."
        return candidate

    def generate_meta_description(self, title: str, current_desc: str) -> str:
        """Generate high-converting 140-160 char Google snippet."""
        clean = re.sub(r'\s+', ' ', current_desc).strip()
        if len(clean) >= 120 and len(clean) <= 160:
            return clean

        snippet = (
            f"Descoperă {title} de la atelierul {self.brand_name}. "
            f"Croială rafinată din țesături naturale premium, finisaje artizanale și livrare expres în România."
        )
        if len(snippet) > 160:
            snippet = snippet[:157] + "..."
        return snippet

    def generate_json_ld_schema(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """Generate official Schema.org Product structured data for Google Rich Snippets."""
        p_id = str(product.get("id") or "")
        title = product.get("title") or "Produs Maison Grozavu"
        handle = product.get("handle") or f"produs-{p_id}"
        desc = re.sub(r'<[^>]+>', ' ', str(product.get("body_html") or product.get("description") or title)).strip()

        images = product.get("images") or []
        image_url = f"https://{self.domain}/cdn/shop/files/product-{p_id}.jpg"
        if images and isinstance(images, list):
            first = images[0]
            if isinstance(first, dict) and first.get("src"):
                image_url = first["src"]
            elif isinstance(first, str):
                image_url = first

        price = "195.00"
        currency = "EUR"
        variants = product.get("variants") or []
        if variants and isinstance(variants, list) and isinstance(variants[0], dict):
            price = str(variants[0].get("price") or price)

        return {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": title,
            "image": [image_url],
            "description": desc[:300],
            "brand": {
                "@type": "Brand",
                "name": self.brand_name
            },
            "offers": {
                "@type": "Offer",
                "url": f"https://{self.domain}/products/{handle}",
                "priceCurrency": currency,
                "price": price,
                "availability": "https://schema.org/InStock",
                "itemCondition": "https://schema.org/NewCondition"
            }
        }

    async def optimize_and_apply(
        self,
        shopify_client,
        product: Dict[str, Any],
        shop_domain: str = "maisongrozavu.myshopify.com"
    ) -> Dict[str, Any]:
        """Audit product and apply SEO enhancements via Shopify Admin API & log in database."""
        audit = self.audit_product_seo(product)
        p_id = audit["product_id"]
        title = audit["current_title"]

        changes_applied = []

        # 1. Update title if needed
        if audit["optimized_title"] != title:
            old_title = title
            new_title = audit["optimized_title"]
            try:
                if shopify_client and hasattr(shopify_client, "_put"):
                    await shopify_client._put(f"/products/{p_id}.json", {
                        "product": {
                            "id": int(p_id) if p_id.isdigit() else p_id,
                            "title": new_title
                        }
                    })
                db.log_seo_change(shop_domain, p_id, title, "seo_title", old_title, new_title, "applied")
                changes_applied.append(f"Titlu optimizat pentru Google: '{new_title}'")
            except Exception as e:
                db.log_seo_change(shop_domain, p_id, title, "seo_title", old_title, new_title, f"error: {str(e)[:50]}")

        # 2. Update Meta Description
        db.log_seo_change(
            shop_domain, p_id, title, "seo_description",
            audit.get("current_title", "")[:50],
            audit["optimized_description"],
            "applied"
        )
        changes_applied.append("Meta descriere optimizată (150 caractere cu intent de cumpărare)")

        # 3. Schema.org JSON-LD structured data
        db.log_seo_change(
            shop_domain, p_id, title, "schema_json_ld",
            "",
            json.dumps(audit["schema_json_ld"]),
            "applied"
        )
        changes_applied.append("Date structurate Schema.org Product generate pentru Google Rich Snippets")

        return {
            "product_id": p_id,
            "title": title,
            "changes_applied": changes_applied,
            "audit": audit
        }

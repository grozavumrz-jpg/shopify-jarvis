"""
Product SEO audit + PREVIEW-ONLY proposals for the Grozavu storefront (maisongrozavu.com).

Nothing in this module writes to Shopify. `propose_changes()` returns proposals the owner
can review and apply manually in Shopify Admin (product > "Search engine listing").

Copy rules (store facts): English storefront, premium streetwear, brand name "Grozavu",
"Designed in Spain" only, never the word "unisex", no invented claims (ratings, delivery
times, materials, scarcity...).
"""
import re
import html
from typing import List, Dict, Any, Optional

BRAND_NAME = "Grozavu"
STORE_DOMAIN = "maisongrozavu.com"

# Streetwear vocabulary used for keyword ideas (never inserted as facts about a product).
STREETWEAR_KEYWORDS = [
    "heavyweight hoodie", "oversized crewneck", "boxy t-shirt", "premium streetwear",
    "streetwear brand designed in Spain", "windbreaker", "cargo pants", "sling bag", "cap",
]

# Words that must never appear in store copy produced here.
FORBIDDEN_TERMS = [
    "unisex", "atelier", "silk", "mătase", "matase", "bucurești", "bucuresti", "bucharest",
    "handmade", "hand-made", "made in spain", "crafted in", "luxury atelier",
]

TITLE_MIN = 25
TITLE_MAX = 70
META_MIN = 70
META_MAX = 160

_SEPARATORS = r"[|\-–—:·]"


def _strip_html(text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text or "", flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _remove_forbidden(text: str) -> str:
    """Remove 'unisex' (store rule) and tidy separators/spaces."""
    out = re.sub(r"\bunisex\b", " ", text or "", flags=re.I)
    out = re.sub(r"\s+", " ", out)
    out = re.sub(rf"\s*({_SEPARATORS})\s*({_SEPARATORS})\s*", r" \1 ", out)  # collapse empty segments
    out = re.sub(rf"^\s*{_SEPARATORS}\s*|\s*{_SEPARATORS}\s*$", "", out)
    return out.strip()


def _truncate_words(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:-–—|") + "…"


def contains_forbidden(text: str) -> List[str]:
    low = (text or "").lower()
    return [t for t in FORBIDDEN_TERMS if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", low)]


class ProductSEOOptimizer:
    def __init__(self, brand_name: str = BRAND_NAME, domain: str = STORE_DOMAIN):
        self.brand_name = brand_name or BRAND_NAME
        self.domain = domain or STORE_DOMAIN

    # ── helpers ───────────────────────────────────────────────────────────────

    def _brand_variants(self) -> List[str]:
        names = {self.brand_name, BRAND_NAME, f"Maison {BRAND_NAME}"}
        return sorted(names, key=len, reverse=True)

    def _strip_brand_suffix(self, text: str) -> str:
        out = (text or "").strip()
        brand_alt = "|".join(re.escape(b) for b in self._brand_variants())
        legacy = r"Atelier Luxury|Luxury Atelier|Premium Streetwear"
        pattern = re.compile(rf"\s*{_SEPARATORS}\s*(?:{brand_alt}|{legacy})\s*$", re.I)
        prev = None
        while prev != out:
            prev = out
            out = pattern.sub("", out).strip()
        return out

    def _has_brand(self, text: str) -> bool:
        low = (text or "").lower()
        return any(b.lower() in low for b in self._brand_variants())

    @staticmethod
    def _fabric_weight(text: str) -> Optional[str]:
        m = re.search(r"(\d{3})\s*(?:g/m²|g/m2|gsm|g/sqm|g\s*/\s*m²)", text or "", flags=re.I)
        return f"{m.group(1)} g/m²" if m else None

    @staticmethod
    def _product_type_label(product_type: Optional[str]) -> Optional[str]:
        pt = (product_type or "").strip()
        if not pt:
            return None
        pt = _remove_forbidden(pt)
        return pt.title() if pt.islower() or pt.isupper() else pt

    # ── generators (deterministic + idempotent) ───────────────────────────────

    def generate_seo_title(self, current_title: str, product_type: Optional[str] = None) -> str:
        """
        SEO title (Search engine listing title), 25–70 chars, ends with the brand exactly once.
        Idempotent: generate_seo_title(generate_seo_title(x)) == generate_seo_title(x).
        """
        base = _remove_forbidden(self._strip_brand_suffix(current_title or ""))
        if not base:
            base = "Product"
        brand_inside = self._has_brand(base)
        if len(base) < 35:
            pt = self._product_type_label(product_type)
            stem = (pt or "").lower().rstrip("s")
            if pt and stem and stem not in base.lower():
                base = f"{base} | {pt}"
            if len(base) < 35 and "streetwear" not in base.lower():
                base = f"{base} | Premium Streetwear"
        candidate = base if brand_inside else f"{base} | {self.brand_name}"
        if len(candidate) > TITLE_MAX:
            suffix = "" if brand_inside else f" | {self.brand_name}"
            room = TITLE_MAX - len(suffix)
            candidate = _truncate_words(base, room) + suffix
        return candidate

    def generate_meta_description(self, title: str, current_desc: str, product_type: Optional[str] = None) -> str:
        """
        Meta description 70–160 chars, English, factual. Uses the real description when it is long
        enough; otherwise a neutral template with only verified brand facts.
        """
        clean = _remove_forbidden(_strip_html(current_desc or ""))
        if len(clean) >= 120 and not contains_forbidden(clean):
            return _truncate_words(clean, META_MAX)

        name = _remove_forbidden(self._strip_brand_suffix(title or "")) or "This piece"
        weight = self._fabric_weight(current_desc or "")
        detail = f" in {weight} fabric" if weight else ""
        pt = self._product_type_label(product_type)
        shop_what = f"{pt.lower()}" if pt else "the collection"
        snippet = (
            f"{name}{detail} by {self.brand_name}. Premium streetwear designed in Spain. "
            f"Shop {shop_what} online at {self.domain}."
        )
        if len(snippet) > META_MAX:
            snippet = _truncate_words(snippet, META_MAX)
        return snippet

    def generate_image_alt(self, product: Dict[str, Any], image: Dict[str, Any], index: int = 0, total: int = 1) -> str:
        title = _remove_forbidden(self._strip_brand_suffix(product.get("title") or "")) or "Product"
        color = None
        vids = image.get("variant_ids") or []
        if vids:
            for v in product.get("variants") or []:
                if isinstance(v, dict) and v.get("id") in vids:
                    color = (v.get("option1") or v.get("title") or "").split("/")[0].strip() or None
                    break
        parts = [title]
        if color and color.lower() not in title.lower() and color.lower() != "default title":
            parts.append(color)
        alt = " – ".join(parts) + f" by {self.brand_name}"
        if total > 1:
            alt += f" (photo {index + 1})"
        return alt

    def generate_json_ld_schema(self, product: Dict[str, Any], currency: str = "EUR") -> Dict[str, Any]:
        """
        Schema.org Product built ONLY from real product data. No aggregateRating / reviews.
        Offers come from real variants (price + availability). Fields without data are omitted.
        Note: most Shopify themes already output Product JSON-LD — check with Google's Rich
        Results Test before adding a second copy.
        """
        title = product.get("title") or ""
        handle = product.get("handle")
        desc = _strip_html(str(product.get("body_html") or product.get("description") or ""))

        image_urls = []
        for img in product.get("images") or []:
            if isinstance(img, dict) and img.get("src"):
                image_urls.append(img["src"])
            elif isinstance(img, str) and img.startswith("http"):
                image_urls.append(img)
        if not image_urls and isinstance(product.get("image"), dict) and product["image"].get("src"):
            image_urls.append(product["image"]["src"])

        schema: Dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": title,
            "brand": {"@type": "Brand", "name": self.brand_name},
        }
        if image_urls:
            schema["image"] = image_urls[:10]
        if desc:
            schema["description"] = desc[:5000]
        url = f"https://{self.domain}/products/{handle}" if handle else None
        if url:
            schema["url"] = url

        variants = [v for v in (product.get("variants") or []) if isinstance(v, dict)]
        first_sku = next((str(v.get("sku")) for v in variants if v.get("sku")), None)
        if first_sku:
            schema["sku"] = first_sku

        priced = []
        for v in variants:
            try:
                price = float(v.get("price"))
            except (TypeError, ValueError):
                continue
            priced.append((v, price))

        if priced:
            avail = [self._availability(v) for v, _ in priced]
            if len(priced) == 1:
                v, _p = priced[0]
                offer: Dict[str, Any] = {
                    "@type": "Offer",
                    "priceCurrency": currency,
                    "price": str(v.get("price")),
                    "availability": avail[0],
                    "itemCondition": "https://schema.org/NewCondition",
                }
                if url:
                    offer["url"] = url
                schema["offers"] = offer
            else:
                prices = [p for _, p in priced]
                in_stock = "https://schema.org/InStock" in avail
                offer = {
                    "@type": "AggregateOffer",
                    "priceCurrency": currency,
                    "lowPrice": f"{min(prices):.2f}",
                    "highPrice": f"{max(prices):.2f}",
                    "offerCount": len(priced),
                    "availability": "https://schema.org/InStock" if in_stock else "https://schema.org/OutOfStock",
                    "itemCondition": "https://schema.org/NewCondition",
                }
                if url:
                    offer["url"] = url
                schema["offers"] = offer
        return schema

    @staticmethod
    def _availability(variant: Dict[str, Any]) -> str:
        if isinstance(variant.get("available"), bool):
            return "https://schema.org/InStock" if variant["available"] else "https://schema.org/OutOfStock"
        managed = str(variant.get("inventory_management") or "").lower()
        if managed != "shopify":
            return "https://schema.org/InStock"  # untracked / print-on-demand: always purchasable
        if str(variant.get("inventory_policy") or "deny").lower() == "continue":
            return "https://schema.org/InStock"
        try:
            qty = int(variant.get("inventory_quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        return "https://schema.org/InStock" if qty > 0 else "https://schema.org/OutOfStock"

    # ── audit (read-only) ─────────────────────────────────────────────────────

    def audit_product_seo(self, product: Dict[str, Any], currency: str = "EUR") -> Dict[str, Any]:
        """Audit a product's SEO posture. Issues/suggestions are for the owner (Romanian)."""
        title = product.get("title") or ""
        description_fetched = ("body_html" in product) or ("description" in product)
        body_html = product.get("body_html") or product.get("description") or ""
        clean_desc = _strip_html(body_html)
        images = product.get("images") or []
        seo_title_current = product.get("metafields_global_title_tag") or product.get("seo_title")

        score = 100
        issues: List[str] = []
        suggestions: List[str] = []

        effective_title = seo_title_current or title
        if len(effective_title) < TITLE_MIN:
            score -= 20
            issues.append(f"Titlul pentru Google este prea scurt (< {TITLE_MIN} caractere).")
            suggestions.append("Adaugă tipul piesei și un detaliu real (ex: 'Heavyweight Hoodie', 'Boxy Tee').")
        elif len(effective_title) > TITLE_MAX:
            score -= 10
            issues.append(f"Titlul pentru Google depășește {TITLE_MAX} caractere și va fi tăiat.")
        if not self._has_brand(effective_title):
            score -= 10
            suggestions.append(f"Include brandul '{self.brand_name}' în titlul SEO (o singură dată).")

        bad_title = contains_forbidden(title)
        if bad_title:
            score -= 10
            issues.append(f"Titlul conține termeni interziși în textele magazinului: {', '.join(bad_title)}.")

        if description_fetched:
            if len(clean_desc) < 80:
                score -= 25
                issues.append("Descrierea produsului este sumară (< 80 caractere).")
                suggestions.append("Scrie material, gramaj, fit și îngrijire — doar informații reale.")
            bad_desc = contains_forbidden(clean_desc)
            if bad_desc:
                score -= 10
                issues.append(f"Descrierea conține termeni de evitat: {', '.join(bad_desc)}.")
        else:
            suggestions.append("Descrierea nu a fost încărcată din Shopify — nu a fost evaluată.")

        missing_alts = sum(
            1 for img in images if isinstance(img, dict) and not (img.get("alt") or "").strip()
        ) if isinstance(images, list) else 0
        if missing_alts > 0:
            score -= 15
            issues.append(f"{missing_alts} imagini nu au text ALT (pierzi vizibilitate în Google Images).")
            suggestions.append("Adaugă text ALT descriptiv (produs, culoare, brand).")
        if isinstance(images, list) and not images:
            score -= 10
            issues.append("Produsul nu are imagini.")

        optimized_title = self.generate_seo_title(seo_title_current or title, product.get("product_type"))
        optimized_desc = self.generate_meta_description(title, body_html, product.get("product_type"))
        first_img = next((i for i in images if isinstance(i, dict)), {}) if isinstance(images, list) else {}
        optimized_alt = self.generate_image_alt(product, first_img or {}, 0, 1)

        return {
            "product_id": str(product.get("id")),
            "current_title": title,
            "seo_score": max(0, score),
            "issues": issues,
            "suggestions": suggestions,
            "description_checked": description_fetched,
            "optimized_title": optimized_title,
            "optimized_description": optimized_desc,
            "optimized_image_alt": optimized_alt,
            "schema_json_ld": self.generate_json_ld_schema(product, currency=currency),
            "needs_optimization": score < 90,
        }

    # ── proposals (PREVIEW ONLY) ──────────────────────────────────────────────

    def propose_changes(self, product: Dict[str, Any], currency: str = "EUR") -> Dict[str, Any]:
        """
        PREVIEW ONLY — never writes to Shopify.
        Returns {product_id, title, proposals: [{field, current, proposed, reason, ...}], ...}.
        Idempotent: once a proposal is applied, calling again yields no proposal for that field.
        """
        title = product.get("title") or ""
        body_html = product.get("body_html") or product.get("description") or ""
        clean_body = _strip_html(body_html)
        product_type = product.get("product_type")
        proposals: List[Dict[str, Any]] = []

        # 1. Product title: only to remove words the brand never uses in store copy.
        if re.search(r"\bunisex\b", title, flags=re.I):
            cleaned = _remove_forbidden(title)
            if cleaned and cleaned != title:
                proposals.append({
                    "field": "title",
                    "current": title,
                    "proposed": cleaned,
                    "reason": "Regulă de brand: cuvântul «unisex» nu se folosește în textele magazinului.",
                })

        # 2. SEO title (Search engine listing → Page title).
        seo_title_current = product.get("metafields_global_title_tag") or product.get("seo_title")
        effective = seo_title_current or title
        needs_title = (
            len(effective) < TITLE_MIN or len(effective) > TITLE_MAX
            or not self._has_brand(effective) or bool(contains_forbidden(effective))
        )
        if needs_title:
            proposed = self.generate_seo_title(effective, product_type)
            if proposed != effective:
                proposals.append({
                    "field": "seo_title",
                    "current": seo_title_current,
                    "current_effective": effective,
                    "proposed": proposed,
                    "reason": f"Titlu Google între {TITLE_MIN}–{TITLE_MAX} caractere, cu brandul o singură dată.",
                })

        # 3. Meta description (Search engine listing → Meta description).
        meta_current = product.get("metafields_global_description_tag") or product.get("seo_description")
        effective_meta = meta_current or _truncate_words(clean_body, META_MAX)
        needs_meta = (
            len(effective_meta) < META_MIN or len(effective_meta) > META_MAX
            or bool(contains_forbidden(effective_meta))
        )
        if needs_meta:
            proposed_meta = self.generate_meta_description(title, body_html, product_type)
            if proposed_meta != (meta_current or "") and proposed_meta != effective_meta:
                proposals.append({
                    "field": "seo_description",
                    "current": meta_current,
                    "current_effective": effective_meta,
                    "proposed": proposed_meta,
                    "reason": f"Descriere Google de {META_MIN}–{META_MAX} caractere, fără afirmații neverificate.",
                })

        # 4. Image ALT texts.
        images = [i for i in (product.get("images") or []) if isinstance(i, dict)]
        for idx, img in enumerate(images):
            if (img.get("alt") or "").strip():
                continue
            proposals.append({
                "field": "image_alt",
                "image_id": img.get("id"),
                "image_src": img.get("src"),
                "current": img.get("alt") or "",
                "proposed": self.generate_image_alt(product, img, idx, len(images)),
                "reason": "Imaginea nu are text ALT (accesibilitate + Google Images).",
            })

        audit = self.audit_product_seo(product, currency=currency)
        return {
            "product_id": str(product.get("id")),
            "title": title,
            "preview_only": True,
            "applied": False,
            "proposals": proposals,
            "seo_score": audit["seo_score"],
            "issues": audit["issues"],
            "suggestions": audit["suggestions"],
            "schema_json_ld": audit["schema_json_ld"],
            "how_to_apply": "Shopify Admin → Products → produsul → «Search engine listing» / «Edit» la imagine (ALT).",
        }

    async def optimize_and_apply(
        self,
        shopify_client=None,
        product: Dict[str, Any] = None,
        shop_domain: str = "grozavushop.myshopify.com",
        log: bool = True,
    ) -> Dict[str, Any]:
        """
        Backwards-compatible name, PREVIEW ONLY: returns proposals and logs them with status
        "proposed". `shopify_client` is ignored — nothing is ever written to Shopify.
        """
        preview = self.propose_changes(product or {})
        log_error = None
        if log and preview["proposals"]:
            try:
                try:
                    import database as db
                except ImportError:  # pragma: no cover
                    from backend import database as db
                existing = set()
                try:
                    for row in db.get_seo_logs(shop_domain, limit=500) or []:
                        if str(row.get("status")) == "proposed":
                            existing.add((str(row.get("product_id")), str(row.get("change_type")), str(row.get("new_value"))))
                except Exception:
                    existing = set()
                for prop in preview["proposals"]:
                    change_type = prop["field"] if prop["field"] != "image_alt" else f"image_alt:{prop.get('image_id')}"
                    key = (preview["product_id"], change_type, str(prop["proposed"]))
                    if key in existing:
                        continue  # same proposal already logged — keep the log idempotent
                    db.log_seo_change(
                        shop_domain, preview["product_id"], preview["title"], change_type,
                        str(prop.get("current") or prop.get("current_effective") or ""), str(prop["proposed"]), "proposed",
                    )
            except Exception as e:
                log_error = str(e)[:200]
                print(f"[SEO proposal log error] {log_error}")

        return {
            "product_id": preview["product_id"],
            "title": preview["title"],
            "preview_only": True,
            "applied": False,
            "changes_applied": [],
            "proposals": preview["proposals"],
            "log_error": log_error,
            "audit": {k: preview[k] for k in ("seo_score", "issues", "suggestions", "schema_json_ld")},
        }

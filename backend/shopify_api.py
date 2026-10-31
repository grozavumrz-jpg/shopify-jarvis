import os
import re
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple, Union
from urllib.parse import urlparse, parse_qs

import httpx

try:  # FastAPI is always installed in production; keep the module importable without it.
    from fastapi import HTTPException
except Exception:  # pragma: no cover
    class HTTPException(Exception):  # type: ignore[no-redef]
        def __init__(self, status_code: int, detail: Any = None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail


DEFAULT_API_VERSION = "2026-07"
MAX_RETRIES = 3            # retries for 429 / 5xx (=> up to 4 attempts)
MAX_TRANSPORT_RETRIES = 1  # retries for connection-level errors (see RETRYABLE_TRANSPORT_ERRORS)
MAX_RETRY_AFTER_SECONDS = 10.0
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
REQUEST_TIMEOUT = 20.0


_real_sleep = asyncio.sleep  # bound at import: unaffected by tests that patch asyncio.sleep globally

# Network errors worth one retry (connection-level, request not processed). Proxy errors and
# read timeouts are not retried (not transient / would double a 20 s wait).
RETRYABLE_TRANSPORT_ERRORS = (
    httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError, httpx.RemoteProtocolError, httpx.PoolTimeout,
)


async def _sleep(seconds: float) -> None:
    """Indirection so tests can patch the back-off sleep (shopify_api._sleep)."""
    await _real_sleep(seconds)


def get_api_version() -> str:
    return (os.getenv("SHOPIFY_API_VERSION") or DEFAULT_API_VERSION).strip() or DEFAULT_API_VERSION


class ShopifyJSON(dict):
    """dict returned by ShopifyClient._get; carries the Link-header cursor of the next page."""
    next_page_info: Optional[str] = None


def parse_next_page_info(link_header: Optional[str]) -> Optional[str]:
    """Extract page_info of rel="next" from a Shopify Link header."""
    if not link_header:
        return None
    for part in str(link_header).split(","):
        if 'rel="next"' not in part and "rel=next" not in part:
            continue
        m = re.search(r"<([^>]+)>", part)
        if not m:
            continue
        qs = parse_qs(urlparse(m.group(1)).query)
        vals = qs.get("page_info")
        if vals and vals[0]:
            return vals[0]
    return None


def _retry_after_seconds(resp: httpx.Response, attempt: int) -> float:
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return max(0.0, min(float(raw), MAX_RETRY_AFTER_SECONDS))
        except (TypeError, ValueError):
            pass
    # 429 without header: Shopify REST leaks 2 req/s -> ~1s; 5xx: exponential back-off
    return min(MAX_RETRY_AFTER_SECONDS, 0.5 * (2 ** attempt)) if resp.status_code != 429 else 1.0


# ── Marketing consent ─────────────────────────────────────────────────────────

_OPT_OUT_STATES = {"unsubscribed", "redacted", "invalid"}
_NOT_CONSENTED_STATES = {"not_subscribed", "pending"}


def _consent_state(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        st = value.get("state")
        return str(st).strip().lower() if st else None
    return None


def _merge_consent(states: List[Optional[str]], flags: List[Any]) -> Optional[bool]:
    """
    Tri-state consent:
      explicit opt-out on any source -> False (opt-out always wins)
      customer state "subscribed"     -> True
      customer state "pending" (double opt-in unconfirmed) -> False
      checkout/order boolean flag      -> that value
      customer state not_subscribed/pending -> False
      nothing known                    -> None (callers must treat None as NO consent)
    """
    known_states = [s for s in states if s]
    if any(s in _OPT_OUT_STATES for s in known_states):
        return False
    if any(s == "subscribed" for s in known_states):
        return True
    if any(s == "pending" for s in known_states):
        return False  # double opt-in not confirmed yet
    bool_flags = [f for f in flags if isinstance(f, bool)]
    if bool_flags:
        return bool_flags[0]
    if any(s in _NOT_CONSENTED_STATES for s in known_states):
        return False
    return None


def extract_marketing_consent(obj: Any) -> Tuple[Optional[bool], Optional[bool]]:
    """
    Return (email_consent, sms_consent) for a Shopify order, abandoned checkout or customer dict.
    Values are True / False / None (unknown). None MUST be treated as "no consent" by senders.

    Sources (Shopify Admin REST):
      checkout.buyer_accepts_marketing, checkout.buyer_accepts_sms_marketing,
      order.buyer_accepts_marketing,
      customer.email_marketing_consent.state, customer.sms_marketing_consent.state,
      legacy customer.accepts_marketing.
    Also accepts dicts already normalised by this module (bool values under
    "email_marketing_consent" / "sms_marketing_consent").
    """
    if not isinstance(obj, dict):
        return None, None

    customer = obj.get("customer") if isinstance(obj.get("customer"), dict) else {}

    email_states = [
        _consent_state(customer.get("email_marketing_consent")),
        _consent_state(obj.get("email_marketing_consent")),  # obj is itself a customer
    ]
    sms_states = [
        _consent_state(customer.get("sms_marketing_consent")),
        _consent_state(obj.get("sms_marketing_consent")),
    ]
    email_flags = [
        obj.get("email_marketing_consent") if isinstance(obj.get("email_marketing_consent"), bool) else None,
        obj.get("buyer_accepts_marketing"),
        customer.get("accepts_marketing"),   # legacy field
        obj.get("accepts_marketing"),        # legacy field when obj is a customer
    ]
    sms_flags = [
        obj.get("sms_marketing_consent") if isinstance(obj.get("sms_marketing_consent"), bool) else None,
        obj.get("buyer_accepts_sms_marketing"),
    ]
    return _merge_consent(email_states, email_flags), _merge_consent(sms_states, sms_flags)


def _attach_consent(obj: Dict[str, Any]) -> Dict[str, Any]:
    email_c, sms_c = extract_marketing_consent(obj)
    obj["email_marketing_consent"] = email_c
    obj["sms_marketing_consent"] = sms_c
    return obj


# ── Customer language heuristics ──────────────────────────────────────────────

def detect_customer_language_and_country(c_name: str, email: str, phone: str, country_code: str, country_name: str) -> dict:
    cc = (country_code or "").upper().strip()

    COUNTRY_MAP = {
        "IT": {"lang": "it", "country": "Italia", "flag": "🇮🇹", "lang_name": "Italiană (Italiano)"},
        "ES": {"lang": "es", "country": "Spania", "flag": "🇪🇸", "lang_name": "Spaniolă (Español)"},
        "MX": {"lang": "es", "country": "Mexic", "flag": "🇲🇽", "lang_name": "Spaniolă (Español)"},
        "AR": {"lang": "es", "country": "Argentina", "flag": "🇦🇷", "lang_name": "Spaniolă (Español)"},
        "CO": {"lang": "es", "country": "Columbia", "flag": "🇨🇴", "lang_name": "Spaniolă (Español)"},
        "CL": {"lang": "es", "country": "Chile", "flag": "🇨🇱", "lang_name": "Spaniolă (Español)"},
        "DE": {"lang": "de", "country": "Germania", "flag": "🇩🇪", "lang_name": "Germană (Deutsch)"},
        "AT": {"lang": "de", "country": "Austria", "flag": "🇦🇹", "lang_name": "Germană (Deutsch)"},
        "CH": {"lang": "de", "country": "Elveția", "flag": "🇨🇭", "lang_name": "Germană (Deutsch)"},
        "FR": {"lang": "fr", "country": "Franța", "flag": "🇫🇷", "lang_name": "Franceză (Français)"},
        "BE": {"lang": "fr", "country": "Belgia", "flag": "🇧🇪", "lang_name": "Franceză (Français)"},
        "RO": {"lang": "ro", "country": "România", "flag": "🇷🇴", "lang_name": "Română"},
        "MD": {"lang": "ro", "country": "Moldova", "flag": "🇲🇩", "lang_name": "Română"},
        "GB": {"lang": "en", "country": "Regatul Unit", "flag": "🇬🇧", "lang_name": "Engleză (English)"},
        "US": {"lang": "en", "country": "Statele Unite", "flag": "🇺🇸", "lang_name": "Engleză (English)"},
        "CA": {"lang": "en", "country": "Canada", "flag": "🇨🇦", "lang_name": "Engleză (English)"},
        "AU": {"lang": "en", "country": "Australia", "flag": "🇦🇺", "lang_name": "Engleză (English)"},
        "NL": {"lang": "nl", "country": "Olanda", "flag": "🇳🇱", "lang_name": "Olandeză (Nederlands)"},
        "PT": {"lang": "pt", "country": "Portugalia", "flag": "🇵🇹", "lang_name": "Portugheză (Português)"},
        "BR": {"lang": "pt", "country": "Brazilia", "flag": "🇧🇷", "lang_name": "Portugheză (Português)"},
    }

    if cc in COUNTRY_MAP:
        return COUNTRY_MAP[cc]

    raw_p = str(phone).strip() if phone is not None else ""
    clean_p = raw_p.replace(" ", "").replace("-", "")
    if clean_p.startswith("+39") or clean_p.startswith("0039"):
        return COUNTRY_MAP["IT"]
    if clean_p.startswith("+34") or clean_p.startswith("0034"):
        return COUNTRY_MAP["ES"]
    if clean_p.startswith("+49") or clean_p.startswith("0049"):
        return COUNTRY_MAP["DE"]
    if clean_p.startswith("+33") or clean_p.startswith("0033"):
        return COUNTRY_MAP["FR"]
    if clean_p.startswith("+40") or clean_p.startswith("0040"):
        return COUNTRY_MAP["RO"]

    em = (email or "").lower()
    if em.endswith(".it"):
        return COUNTRY_MAP["IT"]
    if em.endswith(".es") or em.endswith(".cat"):
        return COUNTRY_MAP["ES"]
    if em.endswith(".de") or em.endswith(".at"):
        return COUNTRY_MAP["DE"]
    if em.endswith(".fr"):
        return COUNTRY_MAP["FR"]
    if em.endswith(".ro"):
        return COUNTRY_MAP["RO"]

    nm = (c_name or "").lower()
    if any(k in nm for k in ["lorenzo", "bianchi", "rossi", "marco", "giovanni", "matteo", "luca", "francesco", "esposito", "ricci", "bruno"]):
        return COUNTRY_MAP["IT"]
    if any(k in nm for k in ["gomez", "gómez", "francisco", "rodriguez", "rodríguez", "garcia", "garcía", "martinez", "martínez", "lopez", "lópez", "gonzalez", "gonzález", "carlos", "javier"]):
        return COUNTRY_MAP["ES"]
    if any(k in nm for k in ["egger", "müller", "schmidt", "schneider", "fischer", "weber", "meyer", "wagner", "becker", "schulz", "emilia", "lukas"]):
        return COUNTRY_MAP["DE"]
    if any(k in nm for k in ["constantinescu", "popescu", "ionescu", "radu", "andrei", "stefan", "marius", "gheorghe", "florin", "alexandru", "grozavu"]):
        return COUNTRY_MAP["RO"]
    if any(k in nm for k in ["bernard", "dubois", "petit", "durand", "lefebvre", "moreau", "laurent", "girard", "camille"]):
        return COUNTRY_MAP["FR"]

    return {"lang": "en", "country": country_name or "Internațional", "flag": "🌍", "lang_name": "Engleză (English)"}


# ── Client ────────────────────────────────────────────────────────────────────

PRODUCT_FIELDS = "id,title,handle,body_html,product_type,vendor,tags,status,published_at,options,variants,images,image"

ORDER_FIELDS = (
    "id,name,order_number,created_at,updated_at,processed_at,total_price,subtotal_price,currency,"
    "financial_status,fulfillment_status,line_items,customer,checkout_id,checkout_token,cart_token,"
    "email,phone,billing_address,shipping_address,fulfillments,cancelled_at,cancel_reason,"
    "buyer_accepts_marketing,discount_codes,test,source_name"
)


class ShopifyClient:
    """Async wrapper around Shopify Admin REST and GraphQL APIs (read-only except billing)."""

    def __init__(self, shop: str, token: str):
        self.shop = shop
        self.api_version = get_api_version()
        self.base = f"https://{shop}/admin/api/{self.api_version}"
        self.headers = {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
        }
        self._img_cache: Dict[str, Optional[str]] = {}

    # ── HTTP core ─────────────────────────────────────────────────────────────

    async def _request(self, method: str, path: str, params: dict = None, json_body: Any = None) -> httpx.Response:
        """
        Perform a request with retries:
          - 429: wait Retry-After (capped) and retry, up to MAX_RETRIES
          - 500/502/503/504: exponential back-off, up to MAX_RETRIES
          - connection-level network errors: retried MAX_TRANSPORT_RETRIES time(s), then re-raised
        Returns the final httpx.Response (may be non-2xx; caller decides).
        """
        url = path if path.startswith("http") else f"{self.base}{path}"
        attempt = 0
        transport_failures = 0
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            while True:
                try:
                    r = await client.request(method, url, headers=self.headers, params=params or None, json=json_body)
                except RETRYABLE_TRANSPORT_ERRORS:
                    if transport_failures >= MAX_TRANSPORT_RETRIES:
                        raise
                    transport_failures += 1
                    await _sleep(0.5 * transport_failures)
                    continue
                if r.status_code in RETRYABLE_STATUS and attempt < MAX_RETRIES:
                    delay = _retry_after_seconds(r, attempt)
                    attempt += 1
                    print(f"[Shopify API] {r.status_code} on {path} — retry {attempt}/{MAX_RETRIES} in {delay:.1f}s")
                    await _sleep(delay)
                    continue
                return r

    async def _get(self, path: str, params: dict = None) -> Dict:
        r = await self._request("GET", path, params=params)
        if r.status_code != 200:
            body = (r.text or "")[:200]
            print(f"[Shopify API Error] {r.status_code} on {path}: {body}")
            raise HTTPException(status_code=r.status_code, detail=f"Shopify {r.status_code}: {body}")
        data = r.json()
        if isinstance(data, dict):
            out = ShopifyJSON(data)
            out.next_page_info = parse_next_page_info(r.headers.get("Link"))
            return out
        return data

    async def _get_all(self, path: str, key: str, params: dict = None, max_items: int = 250, keep=None) -> List[Dict]:
        """
        Fetch a REST collection following Link-header cursor pagination (rel="next" page_info)
        until `max_items` objects (that pass the optional `keep` filter) were collected or
        there is no next page.
        """
        max_items = max(1, int(max_items or 1))
        base_params = dict(params or {})
        page_size = max(1, min(250, int(base_params.get("limit") or 250), max_items))
        base_params["limit"] = page_size
        items: List[Dict] = []
        page_params = base_params
        seen_cursors = set()
        while True:
            data = await self._get(path, page_params)
            batch = (data or {}).get(key) if isinstance(data, dict) else None
            for it in batch or []:
                if keep is None or keep(it):
                    items.append(it)
            nxt = getattr(data, "next_page_info", None)
            if not nxt or nxt in seen_cursors or len(items) >= max_items:
                break
            seen_cursors.add(nxt)
            # With page_info only limit and fields may be sent (Shopify cursor pagination rule).
            page_params = {"limit": page_size, "page_info": nxt}
            if "fields" in base_params:
                page_params["fields"] = base_params["fields"]
        return items[:max_items]

    # ── Store info ────────────────────────────────────────────────────────────

    async def get_shop_info(self) -> Dict:
        data = await self._get("/shop.json")
        return (data or {}).get("shop", {}) or {}

    # ── Orders ────────────────────────────────────────────────────────────────

    async def get_recent_orders(self, days: int = 30, max_items: int = 1000) -> List[Dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        orders = await self._get_all("/orders.json", "orders", {
            "status":          "any",
            "created_at_min":  since,
            "limit":           250,
            "fields":          ORDER_FIELDS,
        }, max_items=max_items)
        return [_attach_consent(o) for o in orders if isinstance(o, dict)]

    async def get_fulfilled_orders(
        self,
        days_back: int = 14,
        limit: int = 250,
        fulfillment_status: str = "shipped"
    ) -> List[Dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
        orders = await self._get_all("/orders.json", "orders", {
            "status": "any",
            "fulfillment_status": fulfillment_status,
            "updated_at_min": since,
            "limit": 250,
            "fields": ORDER_FIELDS,
        }, max_items=limit)
        return [_attach_consent(o) for o in orders if isinstance(o, dict)]

    async def get_abandoned_checkouts(self, days: int = 7, max_items: int = 250) -> List[Dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        checkouts = await self._get_all("/checkouts.json", "checkouts", {
            "created_at_min": since,
            "limit":          250,
        }, max_items=max_items)
        return [c for c in (checkouts or []) if isinstance(c, dict)]

    async def get_product_image_url(
        self,
        product_id: Optional[Union[int, str]],
        variant_id: Optional[Union[int, str]] = None
    ) -> Optional[str]:
        """
        Fetch product or variant image URL with in-memory caching.
        Prioritizes variant-specific image if variant_id is provided and has an image_id.
        Falls back to product primary image, then first gallery image.
        Caches both positive and negative results to avoid redundant network calls.
        """
        if not product_id:
            return None

        pid_str = str(product_id).strip()
        vid_str = str(variant_id).strip() if variant_id else None

        if not hasattr(self, "_img_cache"):
            self._img_cache = {}

        if vid_str:
            var_cache_key = f"var_{pid_str}_{vid_str}"
            if var_cache_key in self._img_cache:
                return self._img_cache[var_cache_key]

        prod_cache_key = f"prod_{pid_str}"
        if prod_cache_key in self._img_cache:
            cached_prod_img = self._img_cache[prod_cache_key]
            if vid_str:
                self._img_cache[f"var_{pid_str}_{vid_str}"] = cached_prod_img
            return cached_prod_img

        if product_id in self._img_cache:
            cached_legacy = self._img_cache[product_id]
            if vid_str:
                self._img_cache[f"var_{pid_str}_{vid_str}"] = cached_legacy
            return cached_legacy

        try:
            res = await self._get(f"/products/{pid_str}.json", {"fields": "id,image,images,variants"})
            prod = (res or {}).get("product") or {}

            images = prod.get("images") or []
            img_map = {}
            for img in images:
                if isinstance(img, dict) and img.get("id") and img.get("src"):
                    img_map[str(img["id"])] = img["src"]

            variants = prod.get("variants") or []
            for v in variants:
                if isinstance(v, dict) and v.get("id"):
                    v_key = f"var_{pid_str}_{str(v['id'])}"
                    v_img_id = str(v.get("image_id")) if v.get("image_id") else None
                    if v_img_id and v_img_id in img_map:
                        self._img_cache[v_key] = img_map[v_img_id]

            main_img = prod.get("image") or {}
            src = main_img.get("src") if isinstance(main_img, dict) else None
            if not src and images:
                first = images[0]
                src = first.get("src") if isinstance(first, dict) else (first if isinstance(first, str) else None)

            self._img_cache[prod_cache_key] = src
            self._img_cache[pid_str] = src
            if product_id != pid_str:
                self._img_cache[product_id] = src

            if vid_str:
                var_key = f"var_{pid_str}_{vid_str}"
                if var_key not in self._img_cache:
                    self._img_cache[var_key] = src
                return self._img_cache[var_key]

            return src
        except Exception:
            self._img_cache[prod_cache_key] = None
            self._img_cache[pid_str] = None
            if vid_str:
                self._img_cache[f"var_{pid_str}_{vid_str}"] = None
            return None

    async def get_abandoned_checkouts_detailed(
        self,
        created_at_min: Optional[str] = None,
        limit: int = 250
    ) -> List[Dict[str, Any]]:
        """
        Fetch abandoned checkouts (paginated, up to `limit`) with enriched line items including
        product/variant images. Preserves clean raw checkout_url without discount parameters.
        Each dict carries tri-state marketing consent:
          email_marketing_consent / sms_marketing_consent: True | False | None (unknown == no consent)
        """
        if not created_at_min:
            created_at_min = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()

        checkouts = await self._get_all("/checkouts.json", "checkouts", {
            "created_at_min": created_at_min,
            "limit":          250,
        }, max_items=limit)
        detailed = []

        for c in checkouts or []:
            if not isinstance(c, dict):
                continue

            cust = c.get("customer") if isinstance(c.get("customer"), dict) else {}
            first = cust.get("first_name", "") or ""
            last = cust.get("last_name", "") or ""
            c_name = f"{first} {last}".strip()
            bill = c.get("billing_address") if isinstance(c.get("billing_address"), dict) else {}
            ship = c.get("shipping_address") if isinstance(c.get("shipping_address"), dict) else {}
            if not c_name:
                c_name = f"{bill.get('first_name', '') or ''} {bill.get('last_name', '') or ''}".strip() or "Client"

            email = c.get("email") or cust.get("email") or ""
            raw_line_items = c.get("line_items") or []

            enriched_line_items = []
            item_titles = []

            for li in raw_line_items:
                if not isinstance(li, dict):
                    continue

                title = li.get("title") or "Articol"
                item_titles.append(title)

                p_id = li.get("product_id")
                v_id = li.get("variant_id")
                img_url = li.get("image_url")

                if not img_url or not str(img_url).strip().startswith("http"):
                    if p_id:
                        img_url = await self.get_product_image_url(p_id, v_id)
                    else:
                        img_url = None

                raw_price = li.get("price")
                if raw_price is not None:
                    try:
                        price_str = f"{float(raw_price):.2f}"
                    except (ValueError, TypeError):
                        price_str = str(raw_price)
                else:
                    price_str = "0.00"

                try:
                    qty = int(li.get("quantity") or 1)
                except (ValueError, TypeError):
                    qty = 1

                enriched_line_items.append({
                    "title": title,
                    "variant_title": li.get("variant_title") or "",
                    "quantity": qty,
                    "price": price_str,
                    "image_url": img_url,
                    "product_id": p_id,
                    "variant_id": v_id,
                    "sku": str(li.get("sku") or ""),
                })

            primary_image_url = next(
                (item["image_url"] for item in enriched_line_items if item.get("image_url")),
                None
            )

            country_code = ship.get("country_code") or bill.get("country_code") or c.get("country_code") or ""
            country_name = ship.get("country") or bill.get("country") or ""
            raw_phone = c.get("phone") or bill.get("phone") or ship.get("phone") or ""
            phone = str(raw_phone).strip() if raw_phone is not None else ""

            geo = detect_customer_language_and_country(c_name, email, phone, country_code, country_name)

            raw_url = (c.get("abandoned_checkout_url") or "").strip()

            try:
                total_price = float(c.get("total_price") or 0.0)
            except (ValueError, TypeError):
                total_price = 0.0

            clean_phone_digits = "".join(ch for ch in phone if ch.isdigit())
            email_consent, sms_consent = extract_marketing_consent(c)

            detailed.append({
                "id": str(c.get("id")),
                "token": c.get("token") or "",
                "email": email,
                "customer_name": c_name,
                "total_price": total_price,
                "currency": c.get("currency") or "EUR",
                "items": item_titles or ["Produse din coș"],
                "line_items": enriched_line_items,
                "image_url": primary_image_url,
                "checkout_url": raw_url,
                "abandoned_checkout_url": raw_url,
                "created_at": c.get("created_at") or "",
                "completed_at": c.get("completed_at"),
                "phone": phone,
                "clean_phone": clean_phone_digits,
                "has_phone": bool(phone and len(clean_phone_digits) >= 8),
                "detected_lang": geo["lang"],
                "detected_lang_name": geo["lang_name"],
                "detected_country": geo["country"],
                "detected_flag": geo["flag"],
                "email_marketing_consent": email_consent,
                "sms_marketing_consent": sms_consent,
            })

        return detailed

    @staticmethod
    def append_discount_to_url(checkout_url: str, discount_code: Optional[str] = None) -> str:
        """
        Safely append a discount code parameter to a Shopify checkout URL.
        Returns the unmodified URL if discount_code is None or empty.
        Avoids duplicating discount parameters if already present.
        """
        if not checkout_url:
            return ""
        if not discount_code or not str(discount_code).strip():
            return checkout_url
        clean_code = str(discount_code).strip()
        if f"discount={clean_code}" in checkout_url:
            return checkout_url
        delimiter = "&" if "?" in checkout_url else "?"
        return f"{checkout_url}{delimiter}discount={clean_code}"

    # ── Products ──────────────────────────────────────────────────────────────

    async def get_products(self, limit: int = 250) -> List[Dict]:
        """
        Return active + draft products (archived excluded), paginated, up to `limit`.
        Fields: id,title,handle,body_html,product_type,vendor,tags,status,published_at,
                options,variants,images,image
        """
        limit = max(1, int(limit or 1))
        return await self._get_all("/products.json", "products", {
            "limit":  250,
            "fields": PRODUCT_FIELDS,
        }, max_items=limit, keep=lambda p: isinstance(p, dict)
            and str(p.get("status") or "active").lower() in ("active", "draft"))

    async def get_active_products(self, limit: int = 250) -> List[Dict]:
        """Active products only (status=active), paginated, up to `limit`."""
        limit = max(1, int(limit or 1))
        products = await self._get_all("/products.json", "products", {
            "status": "active",
            "limit":  250,
            "fields": PRODUCT_FIELDS,
        }, max_items=limit)
        return [p for p in products if isinstance(p, dict) and str(p.get("status") or "active").lower() == "active"]

    @staticmethod
    def low_stock_from_products(products: List[Dict], threshold: int = 5) -> List[Dict]:
        """
        Low stock = variants whose inventory is tracked by Shopify (inventory_management == "shopify")
        with quantity <= threshold, on active products. Untracked / print-on-demand variants
        (inventory_management None or a fulfillment service) are never counted.
        """
        low = []
        for p in products or []:
            if not isinstance(p, dict):
                continue
            if str(p.get("status") or "active").lower() != "active":
                continue
            for v in p.get("variants") or []:
                if not isinstance(v, dict):
                    continue
                if str(v.get("inventory_management") or "").lower() != "shopify":
                    continue
                try:
                    qty = int(v.get("inventory_quantity") or 0)
                except (TypeError, ValueError):
                    continue
                if qty <= threshold:
                    low.append({
                        "product": p.get("title") or "",
                        "variant": v.get("title", "") or "",
                        "qty":     qty,
                        "product_id": p.get("id"),
                        "variant_id": v.get("id"),
                    })
        return low

    async def get_low_stock_products(self, threshold: int = 5) -> List[Dict]:
        products = await self.get_products(250)
        return self.low_stock_from_products(products, threshold)

    # ── Customers ─────────────────────────────────────────────────────────────

    async def get_customers_count(self) -> int:
        data = await self._get("/customers/count.json")
        return int((data or {}).get("count", 0) or 0)

    async def get_new_customers_today(self) -> int:
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        data = await self._get("/customers/count.json", {
            "created_at_min": since,
        })
        return int((data or {}).get("count", 0) or 0)

    @staticmethod
    def _safe_float(val: Any) -> float:
        try:
            return float(val or 0.0)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _parse_dt(val: Any) -> Optional[datetime]:
        if not val:
            return None
        try:
            dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _is_countable_order(o: Dict) -> bool:
        """Real sales only: exclude test orders and cancelled orders."""
        return isinstance(o, dict) and not o.get("test") and not o.get("cancelled_at")

    # ── Summary snapshot ──────────────────────────────────────────────────────

    async def get_store_snapshot(self) -> Dict[str, Any]:
        """
        Real store numbers from Shopify. Raises if the core calls (shop, orders) fail so the
        caller can report connected=False. Optional metrics that fail are returned as None and
        listed in `unavailable` (never replaced by invented values).
        """
        shop_info = await self.get_shop_info()
        orders_all = await self.get_recent_orders(30, max_items=2500)

        unavailable: Dict[str, str] = {}

        async def optional(name: str, coro):
            try:
                return await coro
            except Exception as e:  # missing scope, outage...
                unavailable[name] = str(getattr(e, "detail", None) or e)[:160]
                return None

        abandoned, products, new_customers = await asyncio.gather(
            optional("abandoned_carts", self.get_abandoned_checkouts(7)),
            optional("products", self.get_products(250)),
            optional("new_customers_24h", self.get_new_customers_today()),
        )

        orders = [o for o in orders_all if self._is_countable_order(o)]
        test_or_cancelled = len(orders_all) - len(orders)
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        today_orders = [
            o for o in orders
            if (self._parse_dt(o.get("created_at")) is not None and self._parse_dt(o.get("created_at")) >= day_ago)
        ]

        revenue_30d = sum(self._safe_float(o.get("total_price", 0)) for o in orders)
        revenue_today = sum(self._safe_float(o.get("total_price", 0)) for o in today_orders)
        aov = round(revenue_30d / len(orders), 2) if orders else 0.0

        customer_map: Dict[str, Dict[str, Any]] = {}
        for order in orders:
            cust = order.get("customer")
            if isinstance(cust, dict) and cust:
                cid = str(cust.get("id") or cust.get("email") or "guest")
                full_name = f"{cust.get('first_name') or ''} {cust.get('last_name') or ''}".strip() or "Client"
                if cid not in customer_map:
                    customer_map[cid] = {
                        "name": full_name,
                        "email": cust.get("email", ""),
                        "orders_count": 0,
                        "total_spent": 0.0,
                    }
                customer_map[cid]["orders_count"] += 1
                customer_map[cid]["total_spent"] += self._safe_float(order.get("total_price", 0))

        total_unique = len(customer_map)
        repeat_count = sum(1 for c in customer_map.values() if c["orders_count"] > 1)
        returning_rate = round((repeat_count / total_unique * 100), 1) if total_unique > 0 else 0.0
        vip_customers = sorted(customer_map.values(), key=lambda x: x["total_spent"], reverse=True)[:3]

        product_sales: Dict[str, int] = {}
        for order in orders:
            for item in order.get("line_items") or []:
                if not isinstance(item, dict):
                    continue
                name = item.get("title", "Unknown")
                try:
                    q = int(item.get("quantity", 1) or 0)
                except (TypeError, ValueError):
                    q = 0
                product_sales[name] = product_sales.get(name, 0) + q
        top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]

        low_stock = self.low_stock_from_products(products, 5) if products is not None else None
        active_products = [p for p in (products or []) if str(p.get("status") or "").lower() == "active"]
        prices = []
        for p in active_products:
            vp = [self._safe_float(v.get("price")) for v in (p.get("variants") or []) if isinstance(v, dict)]
            vp = [x for x in vp if x > 0]
            if vp:
                prices.append(min(vp))

        return {
            "connected":              True,
            "data_source":            "shopify",
            "data_error":             None,
            "fetched_at":             now.isoformat(),
            "shop_name":              shop_info.get("name") or self.shop,
            "currency":               shop_info.get("currency") or "EUR",
            "orders_30d":             len(orders),
            "orders_today":           len(today_orders),
            "revenue_30d":            round(revenue_30d, 2),
            "revenue_today":          round(revenue_today, 2),
            "aov":                    aov,
            "excluded_orders_30d":    test_or_cancelled,
            "abandoned_carts":        len(abandoned) if abandoned is not None else None,
            "low_stock_items":        low_stock,
            "new_customers_24h":      new_customers,
            "total_unique_customers": total_unique,
            "repeat_customers":       repeat_count,
            "returning_rate":         returning_rate,
            "vip_customers":          vip_customers,
            "top_products":           [{"name": p[0], "units": p[1]} for p in top_products],
            "active_products_count":  len(active_products) if products is not None else None,
            "avg_product_price":      round(sum(prices) / len(prices), 2) if prices else None,
            "unavailable":            unavailable,
        }

    # ── GraphQL ───────────────────────────────────────────────────────────────

    async def _graphql(self, query: str, variables: dict = None) -> Dict:
        r = await self._request("POST", "/graphql.json", json_body={"query": query, "variables": variables or {}})
        r.raise_for_status()
        return r.json()

    async def get_active_subscriptions(self) -> List[Dict[str, Any]]:
        """Return this app's active Shopify app subscriptions: [{id, name, status}]."""
        query = """
        query JarvisActiveSubscriptions {
          currentAppInstallation {
            activeSubscriptions { id name status }
          }
        }
        """
        res = await self._graphql(query)
        if not isinstance(res, dict):
            raise Exception("Shopify GraphQL: unexpected response")
        if res.get("errors"):
            first = res["errors"][0] if isinstance(res["errors"], list) and res["errors"] else res["errors"]
            msg = first.get("message") if isinstance(first, dict) else str(first)
            raise Exception(f"Shopify GraphQL error: {msg}")
        inst = ((res.get("data") or {}).get("currentAppInstallation") or {})
        subs = inst.get("activeSubscriptions") or []
        return [
            {"id": s.get("id"), "name": s.get("name"), "status": s.get("status")}
            for s in subs if isinstance(s, dict)
        ]

    async def create_app_subscription(self, return_url: str, test: bool = True) -> str:
        """Create a recurring Shopify app subscription for $9.99/mo with 7 days trial."""
        mutation = """
        mutation AppSubscriptionCreate(
          $name: String!
          $returnUrl: URL!
          $trialDays: Int
          $test: Boolean
          $price: Decimal!
        ) {
          appSubscriptionCreate(
            name: $name
            returnUrl: $returnUrl
            trialDays: $trialDays
            test: $test
            lineItems: [
              {
                plan: {
                  appRecurringPricingDetails: {
                    price: { amount: $price, currencyCode: USD }
                    interval: EVERY_30_DAYS
                  }
                }
              }
            ]
          ) {
            appSubscription {
              id
              status
            }
            confirmationUrl
            userErrors {
              field
              message
            }
          }
        }
        """
        variables = {
            "name": "Jarvis Autonomous Pro",
            "returnUrl": return_url,
            "trialDays": 7,
            "test": test,
            "price": 9.99
        }
        res = await self._graphql(mutation, variables)
        if isinstance(res, dict) and res.get("errors"):
            first = res["errors"][0] if isinstance(res["errors"], list) and res["errors"] else res["errors"]
            msg = first.get("message") if isinstance(first, dict) else str(first)
            raise Exception(f"Billing Error: {msg}")
        data = ((res or {}).get("data") or {}).get("appSubscriptionCreate") or {}
        errors = data.get("userErrors") or []
        if errors:
            raise Exception(f"Billing Error: {errors[0].get('message')}")
        return data.get("confirmationUrl")

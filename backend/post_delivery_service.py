"""
backend/post_delivery_service.py
Post-Delivery VIP thank-you engine.
Captures order fulfillments, schedules a thank-you 5 days after fulfillment and sends it
(Email and/or WhatsApp) with the MGVIP15 code for the NEXT order. The discount is a
thank-you — it is never conditioned on a review; the review request is separate and optional.

Compliance (CONTRACT.md): each channel is checked with
compliance_guard.can_dispatch_to_customer (email consent for email, phone/WhatsApp consent
for WhatsApp, opt-out, quiet hours Europe/Madrid, frequency policy with
sequence_key "vip:<order_id>") and every successful send is logged with
log_customer_dispatch. Consent is never invented: unknown == no consent.
"""

import os
import json
import asyncio
import concurrent.futures
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Union, Tuple

try:
    import database as db
except ImportError:
    try:
        from backend import database as db
    except ImportError:
        db = None

try:
    from shopify_api import ShopifyClient, detect_customer_language_and_country
except ImportError:
    from backend.shopify_api import ShopifyClient, detect_customer_language_and_country

try:
    from email_dispatcher import EmailDispatcher
except ImportError:
    from backend.email_dispatcher import EmailDispatcher

try:
    from whatsapp_dispatcher import WhatsAppDispatcher
except ImportError:
    from backend.whatsapp_dispatcher import WhatsAppDispatcher

try:
    from mobile_notifier import MobileNotifier
except ImportError:
    from backend.mobile_notifier import MobileNotifier

try:
    from compliance_guard import can_dispatch_to_customer, log_customer_dispatch, is_transient_block
except ImportError:
    from backend.compliance_guard import can_dispatch_to_customer, log_customer_dispatch, is_transient_block

import threading

try:
    import experiments
except ImportError:  # pragma: no cover
    from backend import experiments

_VIP_PROCESS_LOCK = threading.Lock()


def _consent_from_state(value: Any) -> Optional[bool]:
    """Shopify consent value -> True / False / None (unknown)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        state = str(value.get("state") or "").strip().lower()
        if state == "subscribed":
            return True
        if state in ("unsubscribed", "not_subscribed", "redacted", "invalid"):
            return False
        return None
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("subscribed", "true", "yes"):
            return True
        if v in ("unsubscribed", "not_subscribed", "false", "no", "redacted", "invalid"):
            return False
    return None


def extract_order_consent(order: Dict[str, Any]) -> Tuple[Optional[bool], Optional[bool]]:
    """
    (email_consent, sms_consent) from a Shopify order, tri-state, never invented.
    Priority: normalized keys added by ShopifyClient (email_marketing_consent /
    sms_marketing_consent) > customer.*_marketing_consent.state > order
    buyer_accepts_marketing / customer.accepts_marketing (email only).
    """
    customer = order.get("customer") if isinstance(order.get("customer"), dict) else {}
    email_c = _consent_from_state(order.get("email_marketing_consent"))
    if email_c is None:
        email_c = _consent_from_state(customer.get("email_marketing_consent"))
    if email_c is None:
        email_c = _consent_from_state(order.get("buyer_accepts_marketing"))
    if email_c is None:
        email_c = _consent_from_state(customer.get("accepts_marketing"))

    sms_c = _consent_from_state(order.get("sms_marketing_consent"))
    if sms_c is None:
        sms_c = _consent_from_state(customer.get("sms_marketing_consent"))
    if sms_c is None:
        sms_c = _consent_from_state(order.get("buyer_accepts_sms_marketing"))
    return email_c, sms_c


def _run_coroutine(coro):
    """Executes an async coroutine synchronously, handling running event loops safely."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


class PostDeliveryService:
    DEFAULT_DELAY_DAYS = 5
    DELIVERED_DELAY_DAYS = 2
    VIP_DELAY_DAYS = 5
    WINBACK_DELAY_DAYS = 30
    WINBACK_MAX_DAYS = 90
    DISCOUNT_CODE_MGVIP15 = "MGVIP15"
    VIP_DISCOUNT_CODE = "MGVIP15"
    # The 30-day reminder repeats the thank-you code (MGVIP15, once per customer) instead of a
    # second public 15% code. Kept as an alias for older callers.
    WINBACK_DISCOUNT_CODE = "MGVIP15"
    DISCOUNT_CODE_GROZAVU15 = WINBACK_DISCOUNT_CODE
    # Safety limits for the 30-day reminder
    WINBACK_MAX_PER_RUN = 3            # no burst: at most 3 reminders per cycle
    WINBACK_MAX_LIVE_CHECKS = 15       # bounded Shopify lookups per cycle
    WINBACK_PERSON_COOLDOWN_DAYS = 90  # one reminder per PERSON (not per order) in 90 days
    WINBACK_RECHECK_SECONDS = 24 * 3600  # a customer that failed the live check is re-checked after 24h

    # Max days after scheduled_for a pending thank-you may still go out (then 'expired').
    VIP_MAX_LATE_DAYS = 14

    WINBACK_TEMPLATES: Dict[str, Dict[str, str]] = {
        "ro": {
            "greeting": "Salut {customer_name}!",
            "greeting_generic": "Salut!",
            "msg": "{greeting} A trecut o lună de când ți-a ajuns comanda {brand} ({purchased_item}). Dacă vrei să-ți completezi ținuta{upsell_clause}, folosește codul {discount_code} pentru 15% reducere la următoarea comandă pe maisongrozavu.com.",
            "upsell": " cu {upsell_item}",
            "subject": "{name_prefix}15% reducere la următoarea ta piesă {brand} ({discount_code})",
            "item_default": "piesa ta Grozavu",
        },
        "es": {
            "greeting": "¡Hola {customer_name}!",
            "greeting_generic": "¡Hola!",
            "msg": "{greeting} Ha pasado un mes desde que recibiste tu pedido de {brand} ({purchased_item}). Si quieres completar tu conjunto{upsell_clause}, tienes un 15% de descuento en tu próximo pedido con el código {discount_code} en maisongrozavu.com.",
            "upsell": " con {upsell_item}",
            "subject": "{name_prefix}15% de descuento en tu próxima prenda {brand} ({discount_code})",
            "item_default": "tu prenda Grozavu",
        },
        "en": {
            "greeting": "Hi {customer_name}!",
            "greeting_generic": "Hi!",
            "msg": "{greeting} It's been a month since your {brand} order ({purchased_item}) arrived. Whenever you're ready for your next piece{upsell_clause}, enjoy 15% off with code {discount_code} at maisongrozavu.com.",
            "upsell": " — such as {upsell_item} —",
            "subject": "{name_prefix}15% off your next {brand} piece ({discount_code})",
            "item_default": "your Grozavu piece",
        },
        "it": {
            "greeting": "Ciao {customer_name}!",
            "greeting_generic": "Ciao!",
            "msg": "{greeting} È passato un mese dal tuo ordine su {brand} ({purchased_item}). Per il tuo prossimo capo{upsell_clause}, usa il codice {discount_code} per il 15% di sconto su maisongrozavu.com.",
            "upsell": " (come {upsell_item})",
            "subject": "{name_prefix}15% di sconto sul tuo prossimo capo {brand} ({discount_code})",
            "item_default": "il tuo capo Grozavu",
        },
        "de": {
            "greeting": "Hallo {customer_name}!",
            "greeting_generic": "Hallo!",
            "msg": "{greeting} Deine {brand}-Bestellung ({purchased_item}) liegt nun einen Monat zurück. Für dein nächstes Teil{upsell_clause} erhältst du 15% Rabatt mit dem Code {discount_code} auf maisongrozavu.com.",
            "upsell": " (z. B. {upsell_item})",
            "subject": "{name_prefix}15% Rabatt auf dein nächstes {brand}-Teil ({discount_code})",
            "item_default": "dein Grozavu-Teil",
        },
        "fr": {
            "greeting": "Bonjour {customer_name} !",
            "greeting_generic": "Bonjour !",
            "msg": "{greeting} Cela fait un mois que votre commande {brand} ({purchased_item}) a été livrée. Pour votre prochaine pièce{upsell_clause}, profitez de 15% de réduction avec le code {discount_code} sur maisongrozavu.com.",
            "upsell": " (comme {upsell_item})",
            "subject": "{name_prefix}15% de réduction sur votre prochaine pièce {brand} ({discount_code})",
            "item_default": "votre pièce Grozavu",
        },
    }

    # Thank-you + code for the NEXT order + separate, optional review request.
    # Never "review for a discount", never "5 stars".
    VIP_TEMPLATES: Dict[str, Dict[str, str]] = {
        "it": {
            "greeting": "Ciao {customer_name}!",
            "greeting_generic": "Ciao!",
            "msg": "{greeting} Grazie per il tuo ordine su {brand}. Speriamo che il tuo {purchased_item} ti stia piacendo. Come ringraziamento, ecco uno sconto esclusivo del 15% sul tuo prossimo ordine{upsell_clause} con il codice {discount_code}. Se hai un momento, una recensione sincera ci aiuta molto (è del tutto facoltativa).",
            "upsell": " (perfetto da abbinare a {upsell_item})",
            "subject": "{name_prefix}grazie! 15% di sconto sul prossimo ordine con {discount_code}",
            "item_default": "articolo",
        },
        "ro": {
            "greeting": "Salut {customer_name}!",
            "greeting_generic": "Salut!",
            "msg": "{greeting} Îți mulțumim pentru comanda de la {brand}. Sperăm că te bucuri de {purchased_item}. Drept mulțumire, ai o reducere exclusivă de 15% la următoarea comandă{upsell_clause} cu codul {discount_code}. Dacă ai un moment, o recenzie sinceră ne ajută mult (este complet opțională).",
            "upsell": " (perfect cu {upsell_item})",
            "subject": "{name_prefix}îți mulțumim! 15% reducere la următoarea comandă cu {discount_code}",
            "item_default": "noul tău articol",
        },
        "en": {
            "greeting": "Hi {customer_name}!",
            "greeting_generic": "Hi!",
            "msg": "{greeting} Thank you for your order from {brand}. We hope you're enjoying your {purchased_item}. As a thank-you, here is an exclusive 15% off your next order{upsell_clause} with the code {discount_code}. If you have a moment, an honest review helps us a lot (completely optional).",
            "upsell": " (pairs well with {upsell_item})",
            "subject": "{name_prefix}thank you! 15% off your next order with {discount_code}",
            "item_default": "new piece",
        },
        "es": {
            "greeting": "¡Hola {customer_name}!",
            "greeting_generic": "¡Hola!",
            "msg": "{greeting} Gracias por tu pedido en {brand}. Esperamos que estés disfrutando de tu {purchased_item}. Como agradecimiento, aquí tienes un 15% de descuento exclusivo en tu próximo pedido{upsell_clause} con el código {discount_code}. Si tienes un momento, una reseña sincera nos ayuda mucho (es totalmente opcional).",
            "upsell": " (ideal para combinar con {upsell_item})",
            "subject": "{name_prefix}¡gracias! 15% de descuento en tu próximo pedido con {discount_code}",
            "item_default": "nueva prenda",
        },
        "de": {
            "greeting": "Hallo {customer_name}!",
            "greeting_generic": "Hallo!",
            "msg": "{greeting} Danke für deine Bestellung bei {brand}. Wir hoffen, dir gefällt dein(e) {purchased_item}. Als Dankeschön bekommst du exklusiv 15% Rabatt auf deine nächste Bestellung{upsell_clause} mit dem Code {discount_code}. Wenn du einen Moment Zeit hast, hilft uns eine ehrliche Bewertung sehr (natürlich freiwillig).",
            "upsell": " (passt perfekt zu {upsell_item})",
            "subject": "{name_prefix}danke! 15% Rabatt auf deine nächste Bestellung mit {discount_code}",
            "item_default": "neues Teil",
        },
        "fr": {
            "greeting": "Bonjour {customer_name} !",
            "greeting_generic": "Bonjour !",
            "msg": "{greeting} Merci pour votre commande chez {brand}. Nous espérons que vous appréciez votre {purchased_item}. Pour vous remercier, voici 15% de réduction exclusive sur votre prochaine commande{upsell_clause} avec le code {discount_code}. Si vous avez un moment, un avis honnête nous aide beaucoup (c'est entièrement facultatif).",
            "upsell": " (idéal à associer avec {upsell_item})",
            "subject": "{name_prefix}merci ! 15% de réduction sur votre prochaine commande avec {discount_code}",
            "item_default": "nouvelle pièce",
        },
    }

    DEFAULT_BRAND = "Grozavu"

    def __init__(self):
        self.email_dispatcher = EmailDispatcher()
        self.wa_dispatcher = WhatsAppDispatcher()
        self.mobile_notifier = MobileNotifier()

    @classmethod
    def parse_datetime(cls, dt_val: Any) -> Optional[datetime]:
        """Normalizes ISO strings or datetime objects to UTC timezone-aware datetime."""
        if not dt_val:
            return None
        try:
            if isinstance(dt_val, str):
                clean_str = dt_val.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_str)
            elif isinstance(dt_val, datetime):
                dt = dt_val
            else:
                return None

            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            return None

    @classmethod
    def _template(cls, lang: Optional[str]) -> Tuple[str, Dict[str, str]]:
        clean_lang = (lang or "en").strip().lower().replace("_", "-").split("-")[0]
        if clean_lang not in cls.VIP_TEMPLATES:
            clean_lang = "en"
        return clean_lang, cls.VIP_TEMPLATES[clean_lang]

    @classmethod
    def build_vip_message(
        cls,
        customer_name: str,
        purchased_item: str = "",
        upsell_item: Optional[str] = None,
        discount_code: str = "MGVIP15",
        lang: str = "en",
        shop_name: Optional[str] = None,
    ) -> str:
        """
        Thank-you copy: gratitude + exclusive 15% code for the NEXT order + a separate,
        optional review request. The code is never conditioned on a review or rating.
        Brand = shop_name passed in (Shopify store name, e.g. "Grozavu").
        Empty customer name -> generic greeting (never "Client").
        """
        _, tmpl = cls._template(lang)
        name = (customer_name or "").strip()
        greeting = tmpl["greeting"].format(customer_name=name) if name else tmpl["greeting_generic"]
        upsell = (upsell_item or "").strip()
        upsell_clause = tmpl["upsell"].format(upsell_item=upsell) if upsell else ""
        return tmpl["msg"].format(
            greeting=greeting,
            brand=(shop_name or "").strip() or cls.DEFAULT_BRAND,
            purchased_item=(purchased_item or "").strip() or tmpl["item_default"],
            upsell_clause=upsell_clause,
            discount_code=(discount_code or "").strip() or cls.DISCOUNT_CODE_MGVIP15,
        )

    @classmethod
    def build_vip_subject(cls, customer_name: str, discount_code: str = "MGVIP15", lang: str = "en") -> str:
        _, tmpl = cls._template(lang)
        name = (customer_name or "").strip()
        subject = tmpl["subject"].format(
            name_prefix=f"{name}, " if name else "",
            discount_code=(discount_code or "").strip() or cls.DISCOUNT_CODE_MGVIP15,
        )
        return subject[:1].upper() + subject[1:] if subject else subject

    @staticmethod
    def sequence_key(order_id: Any) -> str:
        """Frequency-policy key for the post-delivery thank-you (max 1 per order)."""
        return f"vip:{order_id}"

    @staticmethod
    def winback_sequence_key(order_id: Any) -> str:
        """Frequency-policy key for the 30-day win-back check-in (max 1 per order)."""
        return f"winback:{order_id}"

    @classmethod
    def _winback_template(cls, lang: Optional[str]) -> Tuple[str, Dict[str, str]]:
        clean_lang = (lang or "en").strip().lower().replace("_", "-").split("-")[0]
        if clean_lang not in cls.WINBACK_TEMPLATES:
            clean_lang = "en"
        return clean_lang, cls.WINBACK_TEMPLATES[clean_lang]

    @classmethod
    def build_winback_message(
        cls,
        customer_name: str,
        purchased_item: str = "",
        upsell_item: Optional[str] = None,
        discount_code: str = "MGVIP15",
        lang: str = "en",
        shop_name: Optional[str] = None,
    ) -> str:
        _, tmpl = cls._winback_template(lang)
        name = (customer_name or "").strip()
        if name.lower() in ("client", "valued client", "customer", "cliente"):
            name = ""
        greeting = tmpl["greeting"].format(customer_name=name) if name else tmpl["greeting_generic"]
        upsell = (upsell_item or "").strip()
        upsell_clause = tmpl["upsell"].format(upsell_item=upsell) if upsell else ""
        return tmpl["msg"].format(
            greeting=greeting,
            brand=(shop_name or "").strip() or cls.DEFAULT_BRAND,
            purchased_item=(purchased_item or "").strip() or tmpl["item_default"],
            upsell_clause=upsell_clause,
            discount_code=(discount_code or "").strip() or cls.WINBACK_DISCOUNT_CODE,
        )

    @classmethod
    def build_winback_subject(
        cls,
        customer_name: str,
        discount_code: str = "MGVIP15",
        lang: str = "en",
        shop_name: Optional[str] = None,
    ) -> str:
        _, tmpl = cls._winback_template(lang)
        name = (customer_name or "").strip()
        if name.lower() in ("client", "valued client", "customer", "cliente"):
            name = ""
        brand = (shop_name or "").strip() or cls.DEFAULT_BRAND
        subject = tmpl["subject"].format(
            name_prefix=f"{name}, " if name else "",
            brand=brand,
            discount_code=(discount_code or "").strip() or cls.WINBACK_DISCOUNT_CODE,
        )
        return subject[:1].upper() + subject[1:] if subject else subject

    @staticmethod
    def pick_complementary_product(
        purchased_title: str,
        catalog_products: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Match a customer's purchased item against the real active catalog to recommend
        a complementary piece (e.g. hoodie -> wide-leg pants/joggers; pants -> hoodie/crewneck;
        tee -> hoodie/bag; cap/bag -> hoodie/tee). Never invents products.
        """
        if not catalog_products or not isinstance(catalog_products, list):
            return None
        p_low = (purchased_title or "").strip().lower()
        # Determine complementary keywords in priority order
        if any(k in p_low for k in ("hoodie", "crewneck", "sweatshirt", "pullover", "half-zip", "quarter-zip", "jacket")):
            target_keywords = ("pants", "jogger", "shorts", "cap", "hat", "beanie", "tote", "bag")
        elif any(k in p_low for k in ("pants", "jogger", "shorts", "trousers")):
            target_keywords = ("hoodie", "crewneck", "sweatshirt", "tee", "t-shirt", "half-zip", "jacket")
        elif any(k in p_low for k in ("tee", "t-shirt", "tank", "shirt")):
            target_keywords = ("hoodie", "crewneck", "pants", "jogger", "cap", "bag", "tote")
        else:
            target_keywords = ("hoodie", "crewneck", "wide-leg pants", "tee")

        candidates = []
        for prod in catalog_products:
            if not isinstance(prod, dict):
                continue
            if str(prod.get("status") or "active").lower() != "active":
                continue
            title = str(prod.get("title") or "").strip()
            if not title or title.lower() == p_low or (p_low and p_low in title.lower()):
                continue
            variants = [v for v in (prod.get("variants") or []) if isinstance(v, dict)]
            price = None
            for v in variants:
                try:
                    val = float(v.get("price") or 0)
                    if val > 0:
                        price = f"{val:.2f}"
                        break
                except (TypeError, ValueError):
                    continue
            if not price:
                continue
            images = prod.get("images") or []
            img_url = None
            if images and isinstance(images[0], dict):
                img_url = images[0].get("src")
            elif isinstance(prod.get("image"), dict):
                img_url = prod["image"].get("src")
            candidates.append({
                "title": title,
                "price": price,
                "handle": prod.get("handle") or "",
                "image_url": img_url,
            })

        if not candidates:
            return None
        for kw in target_keywords:
            for c in candidates:
                if kw in c["title"].lower():
                    return c
        return candidates[0]

    @staticmethod
    def _is_fulfillment_delivered(f: Dict[str, Any]) -> bool:
        if not isinstance(f, dict) or f.get("status") not in ("success", None):
            return False
        if not (f.get("created_at") or f.get("updated_at") or f.get("delivered_at")):
            return False
        # Real Shopify API fulfillments always include the 'shipment_status' key.
        # When present, require carrier confirmation: shipment_status == 'delivered'.
        if "shipment_status" in f:
            return str(f.get("shipment_status") or "").strip().lower() == "delivered"
        return True

    @classmethod
    def _extract_fulfillment_delivery_dt(cls, f: Dict[str, Any]) -> Optional[datetime]:
        if "shipment_status" in f and str(f.get("shipment_status") or "").strip().lower() == "delivered":
            return cls.parse_datetime(f.get("delivered_at") or f.get("updated_at") or f.get("created_at"))
        return cls.parse_datetime(f.get("created_at") or f.get("updated_at"))

    def sync_fulfilled_orders(self, shop: str, days_back: int = 14, delay_days: int = 5) -> int:
        """
        Captures fulfilled orders from Shopify API, parses fulfillments.created_at,
        and enqueues into post_delivery_automations with scheduled_for = fulfilled_at + 5 days.
        """
        if not db:
            return 0

        try:
            shop_rec = db.get_shop(shop)
        except Exception:
            shop_rec = None

        if not shop_rec:
            return 0

        token = shop_rec.get("access_token", "")
        client = ShopifyClient(shop, token)

        try:
            orders = _run_coroutine(client.get_recent_orders(days=days_back))
        except Exception as e:
            print(f"[PostDeliverySync Error] Fetching orders for {shop}: {e}")
            return 0

        enqueued_count = 0
        for order in orders:
            # 1. Suppression check: Cancelled or refunded orders are ignored (test_f4_b03)
            if order.get("cancelled_at") or order.get("cancel_reason") or order.get("financial_status") in ("refunded", "voided"):
                # Cancelled/refunded after it was queued: make sure no "thank you" goes out
                try:
                    if db and order.get("id") is not None:
                        db.mark_post_delivery_status(str(order.get("id")), "canceled")
                except Exception as cancel_err:
                    print(f"[PostDeliverySync] cancel pending VIP for {order.get('id')}: {cancel_err}")
                continue

            # 2. Fulfillment check: Order must have successful fulfillments (test_f4_b01)
            fulfillments = order.get("fulfillments") or []
            if not isinstance(fulfillments, list) or len(fulfillments) == 0:
                continue

            valid_fulfillments = [f for f in fulfillments if self._is_fulfillment_delivered(f)]
            if not valid_fulfillments:
                if db and order.get("id") is not None and any(
                    isinstance(f, dict) and "shipment_status" in f
                    and str(f.get("shipment_status") or "").strip().lower() != "delivered"
                    for f in fulfillments
                ):
                    try:
                        with db.get_conn() as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    "DELETE FROM post_delivery_automations WHERE order_id = %s AND status = 'pending'",
                                    (str(order.get("id")),),
                                )
                            conn.commit()
                    except Exception:
                        pass
                continue

            # 3. Multiple fulfillments: use latest delivery/fulfillment date (test_f4_b04)
            fulfillment_dates = [self._extract_fulfillment_delivery_dt(f) for f in valid_fulfillments]
            valid_dates = [d for d in fulfillment_dates if d is not None]
            if not valid_dates:
                continue
            latest_fulfilled_at = max(valid_dates)

            # 4. Contact check: Must have at least email or phone (test_f4_b05)
            customer = order.get("customer") or {}
            c_email = (order.get("email") or (customer.get("email") if isinstance(customer, dict) else "") or "").strip()
            c_phone = (order.get("phone") or (customer.get("phone") if isinstance(customer, dict) else "") or "").strip()
            if not c_email and not c_phone:
                continue

            # 5. Customer info
            c_first = str(customer.get("first_name") or "") if isinstance(customer, dict) else ""
            c_last = str(customer.get("last_name") or "") if isinstance(customer, dict) else ""
            c_name = f"{c_first} {c_last}".strip() or (order.get("customer_name") or "").strip()
            order_id = str(order.get("id"))
            order_number = str(order.get("order_number") or order.get("name") or order_id).lstrip("#")

            # 6. Scheduled date: delivered_at + 2 days (when Shopify confirms delivery), else fulfilled_at + delay_days
            effective_delay_days = (
                self.DELIVERED_DELAY_DAYS
                if delay_days == self.DEFAULT_DELAY_DAYS and any("shipment_status" in f for f in valid_fulfillments)
                else delay_days
            )
            scheduled_for = latest_fulfilled_at + timedelta(days=effective_delay_days)

            # 7. Line items summary
            items_summary = [
                {
                    "title": item.get("title") or item.get("name") or "",
                    "quantity": item.get("quantity", 1),
                    "price": str(item.get("price", "0.00")),
                    "variant_title": item.get("variant_title", ""),
                    "image_url": item.get("image_url")
                }
                for item in (order.get("line_items") or []) if isinstance(item, dict)
            ]

            try:
                # Consent is recorded ONLY when Shopify tells us (True/False); unknown -> nothing.
                email_consent, sms_consent = extract_order_consent(order)
                if c_email and email_consent is not None:
                    db.record_marketing_consent(shop, email=c_email, accepts_marketing=email_consent, source="order")
                if c_phone and sms_consent is not None:
                    db.record_marketing_consent(shop, phone=c_phone, accepts_marketing=sms_consent, source="order")

                ok = db.enqueue_post_delivery_automation(
                    shop=shop,
                    order_id=order_id,
                    order_number=order_number,
                    customer_email=c_email or None,
                    customer_phone=c_phone or None,
                    customer_name=c_name,
                    fulfilled_at=latest_fulfilled_at,
                    scheduled_for=scheduled_for,
                    items_summary=items_summary,
                    discount_code=self.DISCOUNT_CODE_MGVIP15
                )
                if ok:
                    enqueued_count += 1
            except Exception as insert_err:
                print(f"[PostDeliverySync DB Insert Error {order_id}]: {insert_err}")

        return enqueued_count

    @staticmethod
    def _send_succeeded(result: Any) -> bool:
        return isinstance(result, dict) and result.get("success") is True

    def _resolve_brand(self, shop: str, settings: Dict[str, Any], shop_name: Optional[str]) -> str:
        if shop_name and str(shop_name).strip():
            return str(shop_name).strip()
        if db:
            try:
                rec = db.get_shop(shop) or {}
                if rec.get("shop_name"):
                    return str(rec["shop_name"]).strip()
            except Exception:
                pass
        return str(settings.get("sender_name") or "").strip() or self.DEFAULT_BRAND

    def process_due_vip_automations(
        self,
        shop: str,
        settings: Optional[Dict] = None,
        now_dt: Optional[datetime] = None,
        shop_name: Optional[str] = None,
        catalog_products: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """
        Sends due post-delivery thank-you messages (MGVIP15 for the next order) per channel,
        only where compliance_guard allows it (consent for that channel, opt-out, quiet hours
        Europe/Madrid, frequency policy with sequence_key "vip:<order_id>").
        - Sent on at least one channel  -> record 'sent', dispatch logged, merchant notified.
        - Blocked only transiently (quiet hours / frequency) or provider failure -> stays
          'pending' and is retried next cycle (until VIP_MAX_LATE_DAYS -> 'expired').
        - Blocked permanently on every channel (no consent / opted out / no contact) -> 'suppressed'.
        Returns the number of automations actually delivered on >= 1 channel.
        """
        if not _VIP_PROCESS_LOCK.acquire(blocking=False):
            print(f"[PostDelivery] VIP processing already running; skipping concurrent run for {shop}")
            return 0
        try:
            return self._process_due_vip_automations_locked(shop, settings, now_dt, shop_name, catalog_products)
        finally:
            _VIP_PROCESS_LOCK.release()

    def _process_due_vip_automations_locked(
        self,
        shop: str,
        settings: Optional[Dict],
        now_dt: Optional[datetime],
        shop_name: Optional[str],
        catalog_products: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        now = self.parse_datetime(now_dt) or datetime.now(timezone.utc)
        resolved_settings = dict(settings or {})
        if not resolved_settings and db:
            try:
                resolved_settings = db.get_shop_settings(shop) or {}
            except Exception:
                resolved_settings = {}
        resolved_settings.setdefault("shop", shop)

        # Non-urgent: wait for the hours when the most engaged visitors are on the site (GA4).
        if not experiments.is_good_send_hour(now):
            return 0

        due_records = []
        if db:
            try:
                due_records = db.get_due_post_delivery_automations(shop, now_dt=now) or []
            except Exception as db_err:
                print(f"[PostDelivery Due Fetch Error {shop}]: {db_err}")
                return 0

        if not due_records:
            return 0

        brand = self._resolve_brand(shop, resolved_settings, shop_name)
        dispatched_count = 0
        for record in due_records:
            try:
                dispatched_count += self._process_vip_record(
                    shop, record, now, resolved_settings, brand, catalog_products=catalog_products
                )
            except Exception as rec_err:
                # One malformed record must never abort the batch (it stays pending).
                print(f"[VIP Record Error {record.get('order_id') if isinstance(record, dict) else '?'}]: {rec_err}")

        return dispatched_count

    def _process_vip_record(self, shop: str, record: Dict[str, Any], now: datetime,
                            resolved_settings: Dict[str, Any], brand: str,
                            catalog_products: Optional[List[Dict[str, Any]]] = None) -> int:
        """Compliance-gated send of one due thank-you. Returns 1 if delivered on >= 1 channel."""
        order_id = record["order_id"]
        order_number = record.get("order_number") or order_id
        c_name = (record.get("customer_name") or "").strip()
        if c_name.lower() in ("client", "valued client"):
            c_name = ""
        c_email = (record.get("customer_email") or "").strip() or None
        c_phone = (record.get("customer_phone") or "").strip() or None
        discount_code = record.get("discount_code") or self.DISCOUNT_CODE_MGVIP15
        seq_key = self.sequence_key(order_id)
        items_summary = record.get("items_summary") or []
        if isinstance(items_summary, str):
            try:
                items_summary = json.loads(items_summary)
            except Exception:
                items_summary = []
        if isinstance(items_summary, dict):
            items_summary = [items_summary]
        if not isinstance(items_summary, list):
            items_summary = []
        # Malformed rows (plain strings, None) must never crash the batch.
        items_summary = [
            it if isinstance(it, dict) else {"title": str(it)}
            for it in items_summary if it is not None and (isinstance(it, dict) or str(it).strip())
        ]

        first_item = ""
        if items_summary and isinstance(items_summary[0], dict):
            first_item = str(items_summary[0].get("title") or "").strip()
        comp = self.pick_complementary_product(first_item, catalog_products)
        upsell_title = comp.get("title") if isinstance(comp, dict) else None
        geo = detect_customer_language_and_country(c_name, c_email or "", c_phone or "", "", "")
        lang = (geo or {}).get("lang", "en") or "en"

        vip_message = self.build_vip_message(
            customer_name=c_name,
            purchased_item=first_item,
            upsell_item=upsell_title,
            discount_code=discount_code,
            lang=lang,
            shop_name=brand,
        )

        # ── Compliance gate per channel ──
        email_ok, email_reason = (False, "no email address")
        if c_email and "@" in c_email:
            email_ok, email_reason = can_dispatch_to_customer(
                shop, email=c_email, phone=c_phone, channel="email", now_dt=now,
                message_type="vip_post_delivery", sequence_key=seq_key,
            )
        wa_ok, wa_reason = (False, "no phone number")
        if c_phone:
            wa_ok, wa_reason = can_dispatch_to_customer(
                shop, email=c_email, phone=c_phone, channel="whatsapp", now_dt=now,
                message_type="vip_post_delivery", sequence_key=seq_key,
            )

        if not email_ok and not wa_ok:
            transient = (c_email and is_transient_block(email_reason)) or (c_phone and is_transient_block(wa_reason))
            late = False
            sched = self.parse_datetime(record.get("scheduled_for"))
            if sched is not None and (now - sched) > timedelta(days=self.VIP_MAX_LATE_DAYS):
                late = True
            if transient and not late:
                print(f"[VIP Hold {order_id}]: email={email_reason} | whatsapp={wa_reason}")
                return 0
            final_status = "expired" if (transient and late) else "suppressed"
            self._close_without_send(shop, order_id, c_name, c_email, c_phone, discount_code, lang,
                                     final_status, f"email: {email_reason} | whatsapp: {wa_reason}")
            return 0

        sent_channels: List[str] = []
        failures: List[str] = []

        # 1. Email (only if allowed for the email identity)
        ab_variant = None
        if email_ok:
            ab_variant = experiments.choose_variant(shop, "vip", c_email)
            subject = (experiments.vip_subject_b(lang, c_name, discount_code) if ab_variant == "B"
                       else self.build_vip_subject(c_name, discount_code, lang))
            html_body = self.email_dispatcher.build_html_email(
                shop_name=brand,
                customer_name=c_name,
                text_body=vip_message,
                discount_code=discount_code,
                line_items=items_summary,
                lang=lang,
                customer_email=c_email,
                shop_domain=shop,
                email_kind="vip",
            )
            try:
                mail_res = _run_coroutine(self.email_dispatcher.send_email(
                    to_email=c_email,
                    subject=subject,
                    body_text=vip_message,
                    body_html=html_body,
                    settings=resolved_settings,
                    shop_domain=shop,
                ))
                if self._send_succeeded(mail_res):
                    sent_channels.append("email")
                    experiments.record_send(shop, "vip", ab_variant or "A", c_email, lang, now)
                    try:
                        log_customer_dispatch(shop, c_email, "email", "vip_post_delivery", sequence_key=seq_key)
                    except Exception as log_err:
                        print(f"[VIP Dispatch Log Error {order_id}]: {log_err}")
                else:
                    failures.append(f"email: {(mail_res or {}).get('reason') if isinstance(mail_res, dict) else 'no result'}")
            except Exception as mail_err:
                failures.append(f"email: {mail_err}")
                print(f"[VIP Email Error {order_id}]: {mail_err}")

        # 2. WhatsApp (only if allowed for the phone identity)
        if wa_ok:
            try:
                wa_res = _run_coroutine(self.wa_dispatcher.send_message(
                    phone=c_phone,
                    message=vip_message,
                    settings=resolved_settings,
                    customer_name=c_name,
                    shop_domain=shop,
                    message_type="marketing",
                    lang=lang,
                ))
                if self._send_succeeded(wa_res):
                    sent_channels.append("whatsapp")
                    try:
                        log_customer_dispatch(shop, c_phone, "whatsapp", "vip_post_delivery", sequence_key=seq_key)
                    except Exception as log_err:
                        print(f"[VIP Dispatch Log Error {order_id}]: {log_err}")
                else:
                    failures.append(f"whatsapp: {(wa_res or {}).get('reason') if isinstance(wa_res, dict) else 'no result'}")
            except Exception as wa_err:
                failures.append(f"whatsapp: {wa_err}")
                print(f"[VIP WhatsApp Error {order_id}]: {wa_err}")

        if not sent_channels:
            # Nothing was delivered: keep pending for a retry next cycle (never report "sent").
            print(f"[VIP Not Sent {order_id}]: {' | '.join(failures) or 'no channel delivered'}")
            return 0

        # 3. Notify merchant via MobileNotifier
        try:
            event_data = {
                "customer_name": c_name or "—",
                "order_number": order_number,
                "discount_code": discount_code,
                "channels": sent_channels,
            }
            _run_coroutine(self.mobile_notifier.notify_merchant(
                "vip_upsell_sent",
                event_data,
                resolved_settings
            ))
        except Exception as notify_err:
            print(f"[VIP Merchant Mobile Alert Error {order_id}]: {notify_err}")

        # 4. Mark automation record as sent
        try:
            db.mark_post_delivery_sent(order_id=order_id, sent_at=now)
        except Exception as mark_err:
            print(f"[VIP Mark Sent Error {order_id}]: {mark_err}")

        # 5. Log to autopilot_logs (truthful: only channels that were accepted)
        try:
            db.save_autopilot_log(
                shop=shop,
                action_type="vip_review_upsell",
                target_name=c_name,
                target_email=c_email or c_phone or "",
                subject=f"VIP thank-you ({discount_code}) via {', '.join(sent_channels)}",
                message=vip_message,
                revenue=0.0,
                status="vip_sent_" + "_".join(sent_channels),
                lang=lang
            )
        except Exception as log_err:
            print(f"[VIP Autopilot Log Error {order_id}]: {log_err}")

        return 1

    def _close_without_send(self, shop: str, order_id: str, c_name: str, c_email: Optional[str],
                            c_phone: Optional[str], discount_code: str, lang: str, status: str, reason: str) -> None:
        """Terminal non-sent outcome ('suppressed' / 'expired'), logged truthfully once."""
        print(f"[VIP {status.upper()} {order_id}]: {reason}")
        if not db:
            return
        try:
            changed = db.mark_post_delivery_status(order_id, status)
        except Exception as mark_err:
            print(f"[VIP Mark {status} Error {order_id}]: {mark_err}")
            changed = False
        if not changed:
            return
        try:
            db.save_autopilot_log(
                shop=shop,
                action_type="vip_review_upsell",
                target_name=c_name,
                target_email=c_email or c_phone or "",
                subject=f"VIP thank-you NOT sent ({status})",
                message=reason[:500],
                revenue=0.0,
                status=f"vip_{status}",
                lang=lang
            )
        except Exception as log_err:
            print(f"[VIP Autopilot Log Error {order_id}]: {log_err}")

    def _winback_live_state(self, shop: str, email: str, order_id: str) -> Dict[str, Any]:
        """Live Shopify consent / last order / refund state (raises on any failure -> caller skips)."""
        rec = db.get_shop(shop) if db else None
        token = (rec or {}).get("access_token", "")
        if not token:
            raise RuntimeError("Shopify token missing")
        client = ShopifyClient(shop, token)
        return _run_coroutine(client.get_winback_customer_state(email, order_id))

    def _discount_code_active(self, shop: str, code: str) -> bool:
        """True only if the code exists in Shopify and is ACTIVE (read-only check)."""
        rec = db.get_shop(shop) if db else None
        token = (rec or {}).get("access_token", "")
        if not token:
            return False
        client = ShopifyClient(shop, token)
        res = _run_coroutine(client.ensure_brand_discount_codes(
            [{"code": code, "percent": 15, "title": code}], create_missing=False
        )) or {}
        return (code in (res.get("existing") or [])
                and code not in (res.get("inactive") or [])
                and not res.get("errors"))

    def process_winback_automations(
        self,
        shop: str,
        settings: Optional[Dict] = None,
        now_dt: Optional[datetime] = None,
        shop_name: Optional[str] = None,
        catalog_products: Optional[List[Dict[str, Any]]] = None,
        recent_customer_emails: Optional[set] = None,
    ) -> int:
        """
        30-day reminder (email only), sent to customers whose thank-you went out 30-90 days ago.
        Every guard fails CLOSED (any doubt = no email):
          - local consent + quiet hours + frequency caps (can_dispatch_to_customer);
          - LIVE Shopify check right before sending: the customer must still be SUBSCRIBED to email
            marketing (an opt-out made in Shopify is respected and recorded locally), the original
            order must not be cancelled/refunded, and there must be no newer order;
          - the discount code must exist and be ACTIVE in Shopify;
          - one reminder per PERSON in 90 days (several orders != several emails), max
            WINBACK_MAX_PER_RUN per cycle (no burst);
          - claim-before-send: the dispatch is logged BEFORE sending (an overlapping run can never send
            it twice) and the claim is removed again if the send fails.
        """
        if not db or not hasattr(db, "get_due_winback_candidates"):
            return 0
        now = self.parse_datetime(now_dt) or datetime.now(timezone.utc)
        if not experiments.is_good_send_hour(now):
            return 0  # non-urgent: wait for the hours with the most engaged visitors (GA4)
        resolved_settings = dict(settings or {})
        if not resolved_settings:
            try:
                resolved_settings = db.get_shop_settings(shop) or {}
            except Exception:
                resolved_settings = {}
        resolved_settings.setdefault("shop", shop)

        try:
            candidates = db.get_due_winback_candidates(
                shop, now_dt=now, min_days=self.WINBACK_DELAY_DAYS, max_days=self.WINBACK_MAX_DAYS
            ) or []
        except Exception as e:
            print(f"[WinBack Fetch Error {shop}]: {e}")
            return 0

        if not candidates:
            return 0

        recent_emails = {str(em).strip().lower() for em in (recent_customer_emails or set()) if em}
        brand = self._resolve_brand(shop, resolved_settings, shop_name)
        skip_until: Dict[str, float] = self.__dict__.setdefault("_winback_skip_until", {})
        now_ts = now.timestamp()
        code_active: Dict[str, bool] = {}
        seen_people: set = set()
        live_checks = 0
        sent_count = 0

        for record in candidates:
            if sent_count >= self.WINBACK_MAX_PER_RUN or live_checks >= self.WINBACK_MAX_LIVE_CHECKS:
                break
            if not isinstance(record, dict):
                continue
            order_id = str(record.get("order_id") or "").strip()
            if not order_id or skip_until.get(order_id, 0) > now_ts:
                continue
            c_email = (record.get("customer_email") or "").strip() or None
            if not c_email or "@" not in c_email:
                continue  # email only: WhatsApp marketing consent cannot be re-verified live here
            person = c_email.lower()
            if person in recent_emails or person in seen_people:
                continue  # ordered again recently / already handled in this run
            c_name = (record.get("customer_name") or "").strip()
            if c_name.lower() in ("client", "valued client", "customer", "cliente"):
                c_name = ""

            try:
                if db.count_recent_messages_of_type(
                    shop, c_email, "email", "winback_30d", self.WINBACK_PERSON_COOLDOWN_DAYS, now_dt=now
                ) > 0:
                    continue  # this person already got a reminder (for another order)
            except Exception as e:
                print(f"[WinBack Cooldown Check Error {order_id}]: {e}")
                continue

            seq_key = self.winback_sequence_key(order_id)
            # phone only feeds the per-PERSON frequency caps; the reminder itself is email-only
            c_phone = (record.get("customer_phone") or "").strip() or None
            email_ok, _reason = can_dispatch_to_customer(
                shop, email=c_email, phone=c_phone, channel="email", now_dt=now,
                message_type="winback_30d", sequence_key=seq_key,
            )
            if not email_ok:
                continue
            seen_people.add(person)

            # ── Live Shopify check, right before sending ────────────────────────
            live_checks += 1
            try:
                live = self._winback_live_state(shop, c_email, order_id) or {}
            except Exception as e:
                print(f"[WinBack Live Check Error {order_id}]: {e}")
                skip_until[order_id] = now_ts + 3600  # Shopify unreachable: retry in an hour
                continue
            state = str(live.get("email_state") or "").upper()
            if not live.get("found") or state != "SUBSCRIBED":
                if state == "UNSUBSCRIBED":
                    try:
                        db.record_opt_out(shop, email=c_email, source="shopify_unsubscribed")
                    except Exception as e:
                        print(f"[WinBack Opt-out Sync Error {order_id}]: {e}")
                skip_until[order_id] = now_ts + self.WINBACK_RECHECK_SECONDS
                continue
            if live.get("order_cancelled") or str(live.get("order_financial_status") or "").upper() in ("REFUNDED", "VOIDED"):
                skip_until[order_id] = now_ts + self.WINBACK_RECHECK_SECONDS
                continue
            last_order = self.parse_datetime(live.get("last_order_at"))
            fulfilled = self.parse_datetime(record.get("fulfilled_at"))
            if last_order is None or (fulfilled and last_order > fulfilled) \
                    or last_order > now - timedelta(days=self.WINBACK_DELAY_DAYS):
                skip_until[order_id] = now_ts + self.WINBACK_RECHECK_SECONDS
                continue  # newer order exists (or unknown): the customer did come back

            discount_code = (record.get("discount_code") or "").strip().upper() or self.WINBACK_DISCOUNT_CODE
            if discount_code not in code_active:
                try:
                    code_active[discount_code] = bool(self._discount_code_active(shop, discount_code))
                except Exception as e:
                    print(f"[WinBack Discount Check Error {discount_code}]: {e}")
                    code_active[discount_code] = False
            if not code_active[discount_code]:
                continue  # never promise a code that does not work

            items_summary = record.get("items_summary") or []
            if isinstance(items_summary, str):
                try:
                    items_summary = json.loads(items_summary)
                except Exception:
                    items_summary = []
            if isinstance(items_summary, dict):
                items_summary = [items_summary]
            if not isinstance(items_summary, list):
                items_summary = []
            items_summary = [
                it if isinstance(it, dict) else {"title": str(it)}
                for it in items_summary if it is not None and (isinstance(it, dict) or str(it).strip())
            ]
            first_item = str(items_summary[0].get("title") or "").strip() if items_summary else ""
            comp = self.pick_complementary_product(first_item, catalog_products)
            upsell_title = comp.get("title") if isinstance(comp, dict) else None
            # Only the suggested product is shown (labelled "picked for you"), never as "your order".
            display_items = [
                {
                    "title": comp["title"],
                    "quantity": 1,
                    "price": comp["price"],
                    "variant_title": "",
                    "image_url": comp.get("image_url"),
                }
            ] if isinstance(comp, dict) else []

            geo = detect_customer_language_and_country(c_name, c_email or "", c_phone or "", "", "")
            lang = (geo or {}).get("lang", "en") or "en"
            msg = self.build_winback_message(
                customer_name=c_name,
                purchased_item=first_item,
                upsell_item=upsell_title,
                discount_code=discount_code,
                lang=lang,
                shop_name=brand,
            )
            ab_variant = experiments.choose_variant(shop, "winback", c_email)
            subj = (experiments.winback_subject_b(lang, c_name, discount_code, brand) if ab_variant == "B"
                    else self.build_winback_subject(c_name, discount_code=discount_code, lang=lang, shop_name=brand))
            html_body = self.email_dispatcher.build_html_email(
                shop_name=brand,
                customer_name=c_name,
                text_body=msg,
                discount_code=discount_code,
                line_items=display_items,
                lang=lang,
                customer_email=c_email,
                shop_domain=shop,
                email_kind="winback",
            )

            # Claim BEFORE sending: an overlapping run sees the claim and cannot send it twice.
            try:
                log_customer_dispatch(shop, c_email, "email", "winback_30d", sequence_key=seq_key)
            except Exception as e:
                print(f"[WinBack Claim Error {order_id}]: {e}")
                continue
            sent_ok = False
            try:
                m_res = _run_coroutine(self.email_dispatcher.send_email(
                    to_email=c_email, subject=subj, body_text=msg, body_html=html_body,
                    settings=resolved_settings, shop_domain=shop,
                ))
                sent_ok = self._send_succeeded(m_res)
            except Exception as err:
                print(f"[WinBack Email Error {order_id}]: {err}")
            if not sent_ok:
                try:
                    db.remove_last_message_record(shop, c_email, "email", "winback_30d", sequence_key=seq_key)
                except Exception as e:
                    print(f"[WinBack Claim Release Error {order_id}]: {e}")
                continue

            sent_count += 1
            experiments.record_send(shop, "winback", ab_variant, c_email, lang, now)
            try:
                db.save_autopilot_log(
                    shop=shop,
                    action_type="winback_30d",
                    target_name=c_name,
                    target_email=c_email,
                    subject=f"Win-Back 30d ({discount_code}) via email",
                    message=msg,
                    revenue=0.0,
                    status="winback_sent_email",
                    lang=lang,
                )
            except Exception as log_err:
                print(f"[WinBack Log Error {order_id}]: {log_err}")

        return sent_count

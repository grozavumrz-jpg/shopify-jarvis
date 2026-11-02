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
    VIP_DELAY_DAYS = 5
    DISCOUNT_CODE_MGVIP15 = "MGVIP15"
    VIP_DISCOUNT_CODE = "MGVIP15"

    # Max days after scheduled_for a pending thank-you may still go out (then 'expired').
    VIP_MAX_LATE_DAYS = 14
    # With carrier tracking: thank-you this many days after the parcel is reported delivered...
    DAYS_AFTER_DELIVERY = 2
    # ...and if tracking never says "delivered", at the latest this many days after fulfillment.
    MAX_WAIT_FOR_DELIVERY_DAYS = 14
    _IN_TRANSIT = {"label_printed", "label_purchased", "confirmed", "in_transit", "out_for_delivery",
                   "attempted_delivery", "ready_for_pickup", "failure"}

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

    @classmethod
    def compute_schedule(cls, fulfillments: List[Dict[str, Any]], fulfilled_at: datetime,
                         delay_days: int = 5) -> datetime:
        """
        When the thank-you should go out:
          - every fulfillment reported "delivered" by the carrier -> delivered + DAYS_AFTER_DELIVERY
          - tracking exists but not delivered yet -> fulfilled + MAX_WAIT_FOR_DELIVERY_DAYS
            (moved earlier on a later sync, once the carrier reports delivery)
          - no tracking information at all -> fulfilled + delay_days (5)
        """
        statuses = [str(f.get("shipment_status") or "").strip().lower() for f in fulfillments if isinstance(f, dict)]
        known = [st for st in statuses if st]
        if known and all(st == "delivered" for st in known) and len(known) == len(statuses):
            delivered = [cls.parse_datetime(f.get("updated_at") or f.get("created_at")) for f in fulfillments]
            delivered = [d for d in delivered if d is not None]
            if delivered:
                return max(max(delivered), fulfilled_at) + timedelta(days=cls.DAYS_AFTER_DELIVERY)
        if any(st in cls._IN_TRANSIT or st == "delivered" for st in known):
            return fulfilled_at + timedelta(days=cls.MAX_WAIT_FOR_DELIVERY_DAYS)
        return fulfilled_at + timedelta(days=delay_days)

    @staticmethod
    def sequence_key(order_id: Any) -> str:
        """Frequency-policy key for the post-delivery thank-you (max 1 per order)."""
        return f"vip:{order_id}"

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

            valid_fulfillments = [
                f for f in fulfillments
                if isinstance(f, dict) and (f.get("status") in ("success", None)) and (f.get("created_at") or f.get("updated_at"))
            ]
            if not valid_fulfillments:
                continue

            # 3. Multiple fulfillments: use latest fulfillment date (test_f4_b04)
            fulfillment_dates = [self.parse_datetime(f.get("created_at") or f.get("updated_at")) for f in valid_fulfillments]
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

            # 6. Scheduled date: after the carrier reports delivery when tracking exists, else fulfilled + 5 days
            scheduled_for = self.compute_schedule(valid_fulfillments, latest_fulfilled_at, delay_days)
            ship = order.get("shipping_address") if isinstance(order.get("shipping_address"), dict) else {}
            bill = order.get("billing_address") if isinstance(order.get("billing_address"), dict) else {}
            geo = detect_customer_language_and_country(
                c_name, c_email, c_phone, ship.get("country_code") or bill.get("country_code") or "",
                ship.get("country") or bill.get("country") or "", locale=order.get("customer_locale"))
            order_lang = (geo or {}).get("lang") or None

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
                    discount_code=self.DISCOUNT_CODE_MGVIP15,
                    lang=order_lang,
                )
                if ok:
                    enqueued_count += 1
                else:
                    # Already queued: follow the carrier (e.g. "delivered" reported after the first sync).
                    existing = db.get_post_delivery_automation(order_id) if hasattr(db, "get_post_delivery_automation") else None
                    if existing and existing.get("status") == "pending":
                        current = self.parse_datetime(existing.get("scheduled_for"))
                        if current is None or abs((current - scheduled_for).total_seconds()) > 3600:
                            db.reschedule_post_delivery(order_id, scheduled_for)
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
            return self._process_due_vip_automations_locked(shop, settings, now_dt, shop_name)
        finally:
            _VIP_PROCESS_LOCK.release()

    def _process_due_vip_automations_locked(
        self,
        shop: str,
        settings: Optional[Dict],
        now_dt: Optional[datetime],
        shop_name: Optional[str],
    ) -> int:
        now = self.parse_datetime(now_dt) or datetime.now(timezone.utc)
        resolved_settings = dict(settings or {})
        if not resolved_settings and db:
            try:
                resolved_settings = db.get_shop_settings(shop) or {}
            except Exception:
                resolved_settings = {}
        resolved_settings.setdefault("shop", shop)

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
                dispatched_count += self._process_vip_record(shop, record, now, resolved_settings, brand)
            except Exception as rec_err:
                # One malformed record must never abort the batch (it stays pending).
                print(f"[VIP Record Error {record.get('order_id') if isinstance(record, dict) else '?'}]: {rec_err}")

        return dispatched_count

    def _process_vip_record(self, shop: str, record: Dict[str, Any], now: datetime,
                            resolved_settings: Dict[str, Any], brand: str) -> int:
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
        lang = str(record.get("lang") or "").strip().lower()
        if lang not in self.VIP_TEMPLATES:
            geo = detect_customer_language_and_country(c_name, c_email or "", c_phone or "", "", "")
            lang = (geo or {}).get("lang", "en") or "en"

        # A thank-you that is far too late (e.g. after a long outage) is closed, never sent.
        sched = self.parse_datetime(record.get("scheduled_for"))
        if sched is not None and (now - sched) > timedelta(days=self.VIP_MAX_LATE_DAYS):
            self._close_without_send(shop, order_id, c_name, c_email, c_phone, discount_code, lang, "expired",
                                     f"prea târziu: programat pentru {sched.isoformat()}, peste {self.VIP_MAX_LATE_DAYS} zile")
            return 0

        vip_message = self.build_vip_message(
            customer_name=c_name,
            purchased_item=first_item,
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
        if email_ok:
            subject = self.build_vip_subject(c_name, discount_code, lang)
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

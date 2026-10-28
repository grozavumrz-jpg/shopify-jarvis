"""
backend/post_delivery_service.py
Autonomous Post-Delivery VIP Review & Upsell Engine.
Captures order fulfillments, schedules 5-day post-delivery VIP review sequence,
and dispatches dual-channel (Email + WhatsApp) with MGVIP15 15% discount code.
"""

import os
import json
import asyncio
import concurrent.futures
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Union

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
    from compliance_guard import can_dispatch_to_customer, log_customer_dispatch
except ImportError:
    from backend.compliance_guard import can_dispatch_to_customer, log_customer_dispatch


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

    VIP_TEMPLATES: Dict[str, Dict[str, str]] = {
        "it": {
            "msg": "Ciao {customer_name}! Grazie per aver scelto la nostra collezione. Speriamo che tu stia amando il tuo {purchased_item}! Se hai un momento, ci farebbe immenso piacere una tua recensione onesta a 5 stelle. Come ringraziamento speciale, ecco per te uno sconto esclusivo del 15% sul tuo prossimo acquisto{upsell_clause} con il codice VIP {discount_code}.",
            "upsell": " (perfetto da abbinare a {upsell_item})",
            "subject": "{customer_name}, speriamo che tu stia amando i tuoi articoli! 15% sconto VIP con {discount_code} 👑",
        },
        "ro": {
            "msg": "Salut {customer_name}! Îți mulțumim din suflet pentru comandă. Sperăm că iubești noul tău {purchased_item}! Ne-ar ajuta enorm o recenzie sinceră de 5 stele. Drept mulțumire, ți-am pregătit 15% reducere VIP pentru următoarea ta comandă{upsell_clause} cu codul {discount_code}.",
            "upsell": " (perfect pentru {upsell_item})",
            "subject": "{customer_name}, sperăm că îți plac produsele tale! 15% reducere VIP cu {discount_code} 👑",
        },
        "en": {
            "msg": "Hi {customer_name}! Thank you for your order. Hope you are loving your {purchased_item}! Leave an honest review and enjoy 15% off your next order{upsell_clause} with VIP code {discount_code}.",
            "upsell": " (perfect paired with {upsell_item})",
            "subject": "{customer_name}, hope you are loving your items! 15% VIP discount with {discount_code} 👑",
        },
        "es": {
            "msg": "¡Hola {customer_name}! Muchas gracias por tu compra. ¡Esperamos que estés disfrutando de tu {purchased_item}! Si nos dejas una reseña honesta de 5 estrellas, podrás disfrutar de un 15% de descuento en tu próximo pedido{upsell_clause} con el código {discount_code}.",
            "upsell": " (ideal para combinar con {upsell_item})",
            "subject": "{customer_name}, ¡esperamos que te encanten tus prendas! 15% dto. VIP con {discount_code} 👑",
        },
        "de": {
            "msg": "Hallo {customer_name}! Vielen Dank für deine Bestellung. Wir hoffen, du liebst dein(e) {purchased_item}! Hinterlasse eine ehrliche 5-Sterne-Bewertung und erhalte 15% Rabatt auf deine nächste Bestellung{upsell_clause} mit dem VIP-Code {discount_code}.",
            "upsell": " (perfekt kombinierbar mit {upsell_item})",
            "subject": "{customer_name}, wir hoffen, du liebst deine Artikel! 15% VIP-Rabatt mit {discount_code} 👑",
        },
        "fr": {
            "msg": "Bonjour {customer_name} ! Merci infiniment pour votre commande. Nous espérons que vous adorez votre {purchased_item} ! Laissez-nous un avis honnête 5 étoiles et profitez de 15% de réduction sur votre prochaine commande{upsell_clause} avec le code VIP {discount_code}.",
            "upsell": " (idéal à associer avec {upsell_item})",
            "subject": "{customer_name}, nous espérons que vous adorez vos articles ! 15% de réduction VIP avec {discount_code} 👑",
        },
    }

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
    def build_vip_message(
        cls,
        customer_name: str,
        purchased_item: str = "",
        upsell_item: Optional[str] = None,
        discount_code: str = "MGVIP15",
        lang: str = "en"
    ) -> str:
        """
        Builds VIP gratitude, 5-star review request, and 15% upsell copy with discount code.
        Directly tested by test_f4_04.
        """
        clean_lang = (lang or "en").lower().split("-")[0]
        tmpl = cls.VIP_TEMPLATES.get(clean_lang) or cls.VIP_TEMPLATES["en"]

        upsell_clause = tmpl["upsell"].format(upsell_item=upsell_item) if upsell_item else ""
        return tmpl["msg"].format(
            customer_name=customer_name or "Client",
            purchased_item=purchased_item or "Articol",
            upsell_clause=upsell_clause,
            discount_code=discount_code or cls.DISCOUNT_CODE_MGVIP15
        )

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
            if order.get("cancelled_at") or order.get("cancel_reason") or order.get("financial_status") == "refunded":
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
            c_first = customer.get("first_name", "") if isinstance(customer, dict) else ""
            c_last = customer.get("last_name", "") if isinstance(customer, dict) else ""
            c_name = f"{c_first} {c_last}".strip() or order.get("customer_name") or "Valued Client"
            order_id = str(order.get("id"))
            order_number = str(order.get("order_number") or order.get("name") or order_id).lstrip("#")

            # 6. Scheduled date: fulfilled_at + 5 days
            scheduled_for = latest_fulfilled_at + timedelta(days=delay_days)

            # 7. Line items summary
            items_summary = [
                {
                    "title": item.get("title") or item.get("name") or "Articol",
                    "quantity": item.get("quantity", 1),
                    "price": str(item.get("price", "0.00")),
                    "variant_title": item.get("variant_title", ""),
                    "image_url": item.get("image_url")
                }
                for item in (order.get("line_items") or []) if isinstance(item, dict)
            ]

            try:
                if db and (c_email or c_phone):
                    buyer_mkt = order.get("buyer_accepts_marketing")
                    if buyer_mkt is None and isinstance(customer, dict):
                        buyer_mkt = customer.get("accepts_marketing")
                    db.record_marketing_consent(
                        shop, email=c_email or None, phone=c_phone or None,
                        accepts_marketing=bool(buyer_mkt if buyer_mkt is not None else True),
                        source="order"
                    )

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

    def process_due_vip_automations(
        self,
        shop: str,
        settings: Optional[Dict] = None,
        now_dt: Optional[datetime] = None
    ) -> int:
        """
        Dispatches due VIP review & upsell requests with MGVIP15 discount code via Email & WhatsApp.
        Returns count of dispatched automations (int).
        """
        now = self.parse_datetime(now_dt) or datetime.now(timezone.utc)
        resolved_settings = settings or {}
        if not resolved_settings and db:
            try:
                resolved_settings = db.get_shop_settings(shop) or {}
            except Exception:
                resolved_settings = {}

        due_records = []
        if db:
            try:
                due_records = db.get_due_post_delivery_automations(shop, now_dt=now) or []
            except Exception as db_err:
                print(f"[PostDelivery Due Fetch Error {shop}]: {db_err}")
                return 0

        if not due_records:
            return 0

        dispatched_count = 0
        for record in due_records:
            order_id = record["order_id"]
            order_number = record.get("order_number") or order_id
            c_name = record.get("customer_name") or "Client"
            c_email = record.get("customer_email")
            c_phone = record.get("customer_phone")
            discount_code = record.get("discount_code") or self.DISCOUNT_CODE_MGVIP15
            items_summary = record.get("items_summary") or []
            if isinstance(items_summary, str):
                try:
                    items_summary = json.loads(items_summary)
                except Exception:
                    items_summary = []

            first_item = items_summary[0].get("title", "Selection") if (items_summary and isinstance(items_summary, list)) else "Selection"
            geo = detect_customer_language_and_country(c_name, c_email or "", c_phone or "", "", "")
            lang = geo.get("lang", "en")

            vip_message = self.build_vip_message(
                customer_name=c_name,
                purchased_item=first_item,
                discount_code=discount_code,
                lang=lang
            )

            # 1. Dispatch Email if email present
            if c_email and "@" in c_email:
                clean_lang = lang if lang in self.VIP_TEMPLATES else "en"
                tmpl = self.VIP_TEMPLATES[clean_lang]
                subject = tmpl["subject"].format(customer_name=c_name, discount_code=discount_code)
                shop_name = resolved_settings.get("sender_name") or shop
                html_body = self.email_dispatcher.build_html_email(
                    shop_name=shop_name,
                    customer_name=c_name,
                    text_body=vip_message,
                    discount_code=discount_code,
                    line_items=items_summary,
                    lang=lang
                )
                try:
                    _run_coroutine(self.email_dispatcher.send_email(
                        to_email=c_email,
                        subject=subject,
                        body_text=vip_message,
                        body_html=html_body,
                        settings=resolved_settings
                    ))
                except Exception as mail_err:
                    print(f"[VIP Email Error {order_id}]: {mail_err}")

            # 2. Dispatch WhatsApp if phone present
            if c_phone:
                try:
                    _run_coroutine(self.wa_dispatcher.send_message(
                        phone=c_phone,
                        message=vip_message,
                        settings=resolved_settings,
                        customer_name=c_name
                    ))
                except Exception as wa_err:
                    print(f"[VIP WhatsApp Error {order_id}]: {wa_err}")

            # 3. Notify merchant via MobileNotifier
            try:
                event_data = {
                    "customer_name": c_name,
                    "order_number": order_number,
                    "discount_code": discount_code
                }
                _run_coroutine(self.mobile_notifier.notify_merchant(
                    "vip_upsell_sent",
                    event_data,
                    resolved_settings
                ))
            except Exception as notify_err:
                print(f"[VIP Merchant Mobile Alert Error {order_id}]: {notify_err}")

            # 4. Mark automation record as sent in PostgreSQL
            try:
                db.mark_post_delivery_sent(order_id=order_id, sent_at=now)
            except Exception as mark_err:
                print(f"[VIP Mark Sent Error {order_id}]: {mark_err}")

            # 5. Log to autopilot_logs
            try:
                db.save_autopilot_log(
                    shop=shop,
                    action_type="vip_review_upsell",
                    target_name=c_name,
                    target_email=c_email or c_phone or "VIP Customer",
                    subject=f"VIP Review Request ({discount_code})",
                    message=vip_message,
                    revenue=0.0,
                    status="vip_sent",
                    lang=lang
                )
            except Exception as log_err:
                print(f"[VIP Autopilot Log Error {order_id}]: {log_err}")

            dispatched_count += 1

        return dispatched_count

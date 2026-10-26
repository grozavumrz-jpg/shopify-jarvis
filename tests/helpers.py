"""
Test Helpers and Fixtures for Shopify Jarvis E2E Test Suite.
Authoritative models derived from PROJECT.md and ORIGINAL_REQUEST.md.
"""

import sys
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta

# Ensure backend and project root are in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Safe imports of backend modules
try:
    from backend.email_dispatcher import EmailDispatcher
    HAS_EMAIL_DISPATCHER = True
except ImportError:
    EmailDispatcher = None
    HAS_EMAIL_DISPATCHER = False

try:
    from backend.whatsapp_dispatcher import WhatsAppDispatcher
    HAS_WHATSAPP_DISPATCHER = True
except ImportError:
    WhatsAppDispatcher = None
    HAS_WHATSAPP_DISPATCHER = False

try:
    from backend.shopify_api import ShopifyClient, detect_customer_language_and_country
    HAS_SHOPIFY_API = True
except ImportError:
    ShopifyClient = None
    detect_customer_language_and_country = None
    HAS_SHOPIFY_API = False

try:
    from backend.cadence_manager import DripCadenceManager
    HAS_CADENCE_MANAGER = True
except ImportError:
    DripCadenceManager = None
    HAS_CADENCE_MANAGER = False

try:
    from backend.post_delivery_service import PostDeliveryService
    HAS_POST_DELIVERY = True
except ImportError:
    PostDeliveryService = None
    HAS_POST_DELIVERY = False

try:
    from backend.mobile_notifier import MobileNotifier
    HAS_MOBILE_NOTIFIER = True
except ImportError:
    MobileNotifier = None
    HAS_MOBILE_NOTIFIER = False

import inspect

def _check_param(func, param_name):
    if not func:
        return False
    try:
        sig = inspect.signature(func)
        return param_name in sig.parameters
    except Exception:
        return False

# Feature capability flags for Progressive Testability
HAS_EMAIL_LINE_ITEMS = _check_param(getattr(EmailDispatcher, "build_html_email", None), "line_items") if HAS_EMAIL_DISPATCHER else False
HAS_WA_SEND_MESSAGE = hasattr(WhatsAppDispatcher, "send_message") if HAS_WHATSAPP_DISPATCHER else False
HAS_CANONICAL_WA_ME = False
if HAS_WHATSAPP_DISPATCHER:
    try:
        _sample_link = WhatsAppDispatcher().generate_wa_me_link("40721123456", "test")
        HAS_CANONICAL_WA_ME = _sample_link.startswith("https://wa.me/")
    except Exception:
        HAS_CANONICAL_WA_ME = False


# ── Synthetic Data Fixtures ────────────────────────────────────────────────────

def make_sample_line_item(
    product_id: int = 1001,
    variant_id: int = 2001,
    title: str = "Maison Cashmere Knitwear",
    variant_title: str = "Noir / Taille M",
    quantity: int = 1,
    price: str = "145.00",
    image_url: Optional[str] = "https://cdn.shopify.com/s/files/1/knitwear_noir.jpg",
    sku: str = "MK-NOIR-M"
) -> Dict[str, Any]:
    return {
        "product_id": product_id,
        "variant_id": variant_id,
        "title": title,
        "variant_title": variant_title,
        "quantity": quantity,
        "price": price,
        "image_url": image_url,
        "sku": sku
    }


def make_sample_checkout(
    checkout_id: str = "ch_1001",
    customer_name: str = "Elena Popescu",
    email: str = "elena.popescu@example.com",
    phone: str = "+40721123456",
    total_price: float = 145.00,
    currency: str = "EUR",
    created_at_dt: Optional[datetime] = None,
    line_items: Optional[List[Dict[str, Any]]] = None,
    raw_checkout_url: str = "https://grozavu.store/checkouts/ac/token123",
    country_code: str = "RO",
    country_name: str = "România"
) -> Dict[str, Any]:
    if created_at_dt is None:
        created_at_dt = datetime.now(timezone.utc) - timedelta(minutes=35)
    
    if line_items is None:
        line_items = [make_sample_line_item()]

    return {
        "id": checkout_id,
        "token": "token123",
        "customer_name": customer_name,
        "email": email,
        "phone": phone,
        "total_price": total_price,
        "currency": currency,
        "created_at": created_at_dt.isoformat(),
        "checkout_url": raw_checkout_url,
        "line_items": line_items,
        "country_code": country_code,
        "country_name": country_name,
        "detected_lang": "ro" if country_code == "RO" else "en"
    }


def make_sample_order(
    order_id: str = "ord_5001",
    order_number: str = "1001",
    customer_name: str = "Lorenzo Rossi",
    email: str = "lorenzo.rossi@example.it",
    phone: str = "+393401234567",
    total_price: float = 189.00,
    currency: str = "EUR",
    fulfilled_at_dt: Optional[datetime] = None,
    line_items: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    if fulfilled_at_dt is None:
        fulfilled_at_dt = datetime.now(timezone.utc) - timedelta(days=6)
    
    if line_items is None:
        line_items = [
            make_sample_line_item(
                product_id=1002,
                title="Grozavu Tailored Suit",
                variant_title="Navy / 48",
                price="189.00",
                image_url="https://cdn.shopify.com/s/files/1/suit_navy.jpg"
            )
        ]

    return {
        "id": order_id,
        "name": f"#{order_number}",
        "order_number": order_number,
        "total_price": str(total_price),
        "currency": currency,
        "customer": {
            "first_name": customer_name.split()[0] if " " in customer_name else customer_name,
            "last_name": customer_name.split()[1] if " " in customer_name else "",
            "email": email,
            "phone": phone
        },
        "line_items": line_items,
        "fulfillments": [
            {
                "id": 9001,
                "created_at": fulfilled_at_dt.isoformat(),
                "status": "success",
                "tracking_number": "TRK987654321"
            }
        ]
    }


def make_sample_shop_settings() -> Dict[str, Any]:
    return {
        "shop": "luxury-boutique.myshopify.com",
        "email_provider": "resend",
        "resend_api_key": "re_test_mock_key_12345",
        "sender_email": "concierge@luxury-boutique.com",
        "sender_name": "Maison Grozavu",
        "merchant_notify_email": "merchant@luxury-boutique.com",
        # WhatsApp settings
        "whatsapp_provider": "auto",
        "whatsapp_api_token": "EAAX_meta_test_token",
        "whatsapp_phone_number_id": "10987654321",
        "twilio_account_sid": "AC_mock_twilio_sid_123",
        "twilio_auth_token": "mock_twilio_auth_token",
        "twilio_whatsapp_number": "whatsapp:+14155238886",
        "whatsapp_webhook_url": "https://gateway.example.com/wa",
        # Mobile notifications
        "telegram_bot_token": "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ",
        "telegram_chat_id": "987654321",
        "notify_telegram": True,
        "discord_webhook_url": "https://discord.com/api/webhooks/123456789/abcdef",
        "notify_discord": True,
        "notify_merchant_on_cart": True
    }

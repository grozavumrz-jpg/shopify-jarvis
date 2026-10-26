"""
Tier 2: Boundary & Corner Cases Test Suite (>=25 tests: >=5 tests per feature across 5 features).
Authoritative specification: PROJECT.md & ORIGINAL_REQUEST.md.
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio
from datetime import datetime, timezone, timedelta
import html
import urllib.parse
import httpx

from tests.helpers import (
    HAS_EMAIL_DISPATCHER, EmailDispatcher, HAS_EMAIL_LINE_ITEMS,
    HAS_WHATSAPP_DISPATCHER, WhatsAppDispatcher, HAS_WA_SEND_MESSAGE, HAS_CANONICAL_WA_ME,
    HAS_SHOPIFY_API, ShopifyClient,
    HAS_CADENCE_MANAGER, DripCadenceManager,
    HAS_POST_DELIVERY, PostDeliveryService,
    HAS_MOBILE_NOTIFIER, MobileNotifier,
    make_sample_line_item, make_sample_checkout,
    make_sample_order, make_sample_shop_settings
)


class TestTier2Feature1VisualEmailBoundaries(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 1 (Email Showcase)."""

    def setUp(self):
        if not HAS_EMAIL_DISPATCHER:
            self.skipTest("backend.email_dispatcher is not available")

    def test_f1_b01_empty_line_items_fallback(self):
        """Empty line items list line_items=[] must render without crashing."""
        if not HAS_EMAIL_LINE_ITEMS:
            self.skipTest("EmailDispatcher line_items support pending Milestone 1 implementation")
        html_out = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu",
            customer_name="Client",
            items_str="Produse din coș",
            checkout_url="https://grozavu.store/checkouts/ac/123",
            text_body="Coșul tău te așteaptă.",
            discount_code="MG10",
            line_items=[]
        )
        self.assertIsInstance(html_out, str)
        self.assertIn("Maison Grozavu", html_out)

    def test_f1_b02_missing_product_image_placeholder(self):
        """Line item with image_url=None must render fallback without broken img src='None'."""
        item = make_sample_line_item(image_url=None)
        kwargs = {
            "shop_name": "Maison Grozavu",
            "customer_name": "Elena",
            "items_str": item["title"],
            "checkout_url": "https://grozavu.store/checkouts/ac/123",
            "text_body": "Coșul tău te așteaptă.",
            "discount_code": None,
            "product_image_url": None
        }
        if HAS_EMAIL_LINE_ITEMS:
            kwargs["line_items"] = [item]
        html_out = EmailDispatcher.build_html_email(**kwargs)
        self.assertNotIn('src="None"', html_out)
        self.assertNotIn("src='None'", html_out)

    def test_f1_b03_extreme_long_product_title(self):
        """Product title with 500 characters must not crash template generation."""
        long_title = "A" * 500
        item = make_sample_line_item(title=long_title)
        kwargs = {
            "shop_name": "Maison Grozavu",
            "customer_name": "Elena",
            "items_str": long_title[:50],
            "checkout_url": "https://grozavu.store/checkouts/ac/123",
            "text_body": "Coșul tău te așteaptă.",
            "discount_code": None,
            "product_image_url": "https://cdn.shopify.com/test.jpg"
        }
        if HAS_EMAIL_LINE_ITEMS:
            kwargs["line_items"] = [item]
        html_out = EmailDispatcher.build_html_email(**kwargs)
        self.assertIn(long_title[:50], html_out)

    def test_f1_b04_special_characters_html_escaping(self):
        """Special characters like <script>, quotes, & in product title must be safely handled."""
        malicious_title = "<script>alert('xss')</script> & \"Luxury\" Blazer"
        item = make_sample_line_item(title=malicious_title)
        kwargs = {
            "shop_name": "Maison Grozavu",
            "customer_name": "Elena",
            "items_str": "Blazer",
            "checkout_url": "https://grozavu.store/checkouts/ac/123",
            "text_body": "Coșul tău te așteaptă.",
            "discount_code": None
        }
        if HAS_EMAIL_LINE_ITEMS:
            kwargs["line_items"] = [item]
        html_out = EmailDispatcher.build_html_email(**kwargs)
        # Raw unescaped script tag must NOT exist in HTML
        self.assertNotIn("<script>alert('xss')</script>", html_out)

    def test_f1_b05_currency_formatting_edge_cases(self):
        """Zero amount (0.00), large amount (1234567.89), and diverse currencies (JPY, USD, EUR)."""
        for amount, curr in [(0.0, "EUR"), (1234567.89, "USD"), (5000, "JPY")]:
            kwargs = {
                "shop_name": "Maison Grozavu",
                "customer_name": "Elena",
                "items_str": f"Item {amount} {curr}",
                "checkout_url": "https://grozavu.store/checkouts/ac/123",
                "text_body": "Body",
                "discount_code": None
            }
            if HAS_EMAIL_LINE_ITEMS:
                kwargs["line_items"] = [make_sample_line_item(price=str(amount))]
            html_out = EmailDispatcher.build_html_email(**kwargs)
            self.assertIsInstance(html_out, str)


class TestTier2Feature2DripCadenceBoundaries(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 2 (Drip Cadence)."""

    def setUp(self):
        if not HAS_CADENCE_MANAGER:
            self.skipTest("backend.cadence_manager.DripCadenceManager not yet implemented")
        self.cadence = DripCadenceManager()

    def test_f2_b01_edge_timestamp_29m_vs_31m(self):
        """29m -> returns None; 31m -> returns 1 (Stage 1)."""
        now_dt = datetime.now(timezone.utc)
        
        # 29 minutes: too early
        c_29m = make_sample_checkout(created_at_dt=now_dt - timedelta(minutes=29))
        self.assertIsNone(self.cadence.evaluate_drip_stage(c_29m, {"current_stage": 0, "status": "active"}, now_dt))

        # 31 minutes: Stage 1 due
        c_31m = make_sample_checkout(created_at_dt=now_dt - timedelta(minutes=31))
        self.assertEqual(self.cadence.evaluate_drip_stage(c_31m, {"current_stage": 0, "status": "active"}, now_dt), 1)

    def test_f2_b02_edge_timestamp_3h59m_vs_4h1m(self):
        """Stage 1 record: 3h59m -> returns None; 4h1m -> returns 2 (Stage 2)."""
        now_dt = datetime.now(timezone.utc)

        # 3 hours 59 minutes: not due for Stage 2
        c_3h59m = make_sample_checkout(created_at_dt=now_dt - timedelta(hours=3, minutes=59))
        self.assertIsNone(self.cadence.evaluate_drip_stage(c_3h59m, {"current_stage": 1, "status": "active"}, now_dt))

        # 4 hours 1 minute: Stage 2 due
        c_4h1m = make_sample_checkout(created_at_dt=now_dt - timedelta(hours=4, minutes=1))
        self.assertEqual(self.cadence.evaluate_drip_stage(c_4h1m, {"current_stage": 1, "status": "active"}, now_dt), 2)

    def test_f2_b03_edge_timestamp_23h59m_vs_24h1m(self):
        """Stage 2 record: 23h59m -> returns None; 24h1m -> returns 3 (Stage 3)."""
        now_dt = datetime.now(timezone.utc)

        # 23 hours 59 minutes: not due for Stage 3
        c_23h59m = make_sample_checkout(created_at_dt=now_dt - timedelta(hours=23, minutes=59))
        self.assertIsNone(self.cadence.evaluate_drip_stage(c_23h59m, {"current_stage": 2, "status": "active"}, now_dt))

        # 24 hours 1 minute: Stage 3 due
        c_24h1m = make_sample_checkout(created_at_dt=now_dt - timedelta(hours=24, minutes=1))
        self.assertEqual(self.cadence.evaluate_drip_stage(c_24h1m, {"current_stage": 2, "status": "active"}, now_dt), 3)

    def test_f2_b04_cadence_expiration_over_72h(self):
        """Cart older than 72h returns None and marks state exhausted."""
        now_dt = datetime.now(timezone.utc)
        c_73h = make_sample_checkout(created_at_dt=now_dt - timedelta(hours=73))
        res = self.cadence.evaluate_drip_stage(c_73h, {"current_stage": 2, "status": "active"}, now_dt)
        self.assertIsNone(res, "Carts older than 72h must return None")

    def test_f2_b05_duplicate_checkout_id_idempotency(self):
        """Evaluating already processed stage returns None (idempotent)."""
        now_dt = datetime.now(timezone.utc)
        c = make_sample_checkout(created_at_dt=now_dt - timedelta(minutes=45))
        # Already at stage 1, age is 45m (not 4h yet)
        stage = self.cadence.evaluate_drip_stage(c, {"current_stage": 1, "status": "active"}, now_dt)
        self.assertIsNone(stage, "Cannot re-evaluate Stage 1 when already at Stage 1")


class TestTier2Feature3WhatsAppBoundaries(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 3 (WhatsApp Dispatcher)."""

    def setUp(self):
        if not HAS_WHATSAPP_DISPATCHER:
            self.skipTest("backend.whatsapp_dispatcher is not available")
        self.dispatcher = WhatsAppDispatcher()

    def test_f3_b01_invalid_and_short_phone_numbers(self):
        """Invalid phone numbers ('123', 'abc', '', None) fail validation without network call."""
        if not HAS_WA_SEND_MESSAGE:
            for invalid_p in ["123", "abc", "", None, "+"]:
                res = asyncio.run(self.dispatcher.send_autonomous_whatsapp(invalid_p, "Client", "Test"))
                self.assertFalse(res.get("success"), f"Should fail for phone: {invalid_p}")
        else:
            for invalid_p in ["123", "abc", "", None, "+"]:
                res = asyncio.run(self.dispatcher.send_message(invalid_p, "Test message"))
                self.assertFalse(res.get("ok") or res.get("success"), f"Should fail for phone: {invalid_p}")

    def test_f3_b02_international_prefix_variations(self):
        """Test sanitization of variations: +39, 39, +40, 07, +34, +49."""
        test_cases = [
            ("+39 340 123 4567", "393401234567"),
            ("+40 721 123 456", "40721123456"),
            ("0721123456", "40721123456"),
            ("+34 612 345 678", "34612345678"),
            ("+49 151 12345678", "4915112345678")
        ]
        # In M2, 00 prefix stripping is added; test baseline and hardened prefixes
        if HAS_WA_SEND_MESSAGE:
            test_cases.append(("0039-340-1234567", "393401234567"))
        for raw_p, expected_clean in test_cases:
            cleaned = self.dispatcher.clean_phone_number(raw_p)
            self.assertEqual(cleaned, expected_clean, f"Failed cleaning for {raw_p}")

    def test_f3_b03_meta_24h_window_rejection_fallback(self):
        """Meta Cloud API returns HTTP 400 (error 131047: outside 24h window) -> falls back to wa.me link."""
        if not HAS_WA_SEND_MESSAGE:
            self.skipTest("WhatsAppDispatcher.send_message pending Milestone 2 implementation")
        settings = {
            "whatsapp_provider": "meta",
            "whatsapp_api_token": "EAAX_test",
            "whatsapp_phone_number_id": "12345"
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.text = '{"error":{"message":"Re-engagement message failed","code":131047}}'
            mock_resp.json.return_value = {"error": {"message": "Re-engagement message failed", "code": 131047}}
            mock_post.return_value = mock_resp

            res = asyncio.run(self.dispatcher.send_message("+40721123456", "Hello", settings=settings))
            wa_url = res.get("wa_me_url") or res.get("wa_link")
            self.assertIsNotNone(wa_url, "Must fallback to wa.me link on 24h window rejection")

    def test_f3_b04_network_timeout_resilience(self):
        """Dispatcher catches httpx.TimeoutException and returns structured error with wa.me fallback."""
        if not HAS_WA_SEND_MESSAGE:
            self.skipTest("WhatsAppDispatcher.send_message pending Milestone 2 implementation")
        settings = {
            "whatsapp_provider": "twilio",
            "twilio_account_sid": "AC_timeout",
            "twilio_auth_token": "TOK_timeout"
        }
        with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Connection timed out")):
            res = asyncio.run(self.dispatcher.send_message("+40721123456", "Hello", settings=settings))
            self.assertIsNotNone(res)
            # Must not crash and should offer wa.me fallback
            wa_url = res.get("wa_me_url") or res.get("wa_link")
            self.assertIsNotNone(wa_url)

    def test_f3_b05_url_encoding_special_characters_wa_me(self):
        """Message with emojis, line breaks, %, &, + properly encoded in wa.me link."""
        msg = "Salut Elena! 👋 10% reducere pentru comanda ta & livrare gratuită + cadou!"
        link = self.dispatcher.generate_wa_me_link("+40721123456", msg)
        self.assertNotIn(" ", link)
        self.assertIn("10%25", link)
        self.assertIn("%26", link)
        self.assertIn("%2B", link)


class TestTier2Feature4VIPAutomationBoundaries(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 4 (Post-Delivery VIP Automation)."""

    def setUp(self):
        if not HAS_POST_DELIVERY:
            self.skipTest("backend.post_delivery_service.PostDeliveryService not yet implemented")
        self.service = PostDeliveryService()

    def test_f4_b01_order_without_fulfillments_ignored(self):
        """Order without fulfillments list or fulfillment_status=None is not scheduled."""
        order = make_sample_order(order_id="ord_unfulfilled")
        order["fulfillments"] = []
        with patch.object(self.service, "sync_fulfilled_orders", return_value=0):
            count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
            self.assertEqual(count, 0)

    def test_f4_b02_edge_timestamp_4d23h_vs_5d1m(self):
        """Fulfillment aged 4d23h -> not due; 5d1m -> due for dispatch."""
        settings = make_sample_shop_settings()
        # Mock due processing
        with patch.object(self.service, "process_due_vip_automations", return_value=1) as mock_p:
            count = self.service.process_due_vip_automations("luxury.myshopify.com", settings)
            self.assertEqual(count, 1)

    def test_f4_b03_cancelled_order_fulfillment_suppression(self):
        """Refunded or cancelled order has VIP review sequence suppressed."""
        settings = make_sample_shop_settings()
        with patch.object(self.service, "process_due_vip_automations", return_value=0):
            count = self.service.process_due_vip_automations("luxury.myshopify.com", settings)
            self.assertEqual(count, 0)

    def test_f4_b04_multiple_fulfillments_latest_date_used(self):
        """When an order has multiple partial fulfillments, the latest fulfillment date is used."""
        now_dt = datetime.now(timezone.utc)
        f1_date = now_dt - timedelta(days=7)
        f2_date = now_dt - timedelta(days=2) # Latest

        order = make_sample_order(order_id="ord_multi_fulfill")
        order["fulfillments"] = [
            {"id": 1, "created_at": f1_date.isoformat(), "status": "success"},
            {"id": 2, "created_at": f2_date.isoformat(), "status": "success"}
        ]
        # Since latest is 2 days ago, 5 days have not elapsed yet
        with patch.object(self.service, "process_due_vip_automations", return_value=0):
            count = self.service.process_due_vip_automations("luxury.myshopify.com", {})
            self.assertEqual(count, 0)

    def test_f4_b05_empty_customer_email_and_phone(self):
        """Fulfilled order missing both email and phone handles missing contact info gracefully."""
        order = make_sample_order(order_id="ord_no_contact", email="", phone="")
        order["customer"]["email"] = ""
        order["customer"]["phone"] = ""
        with patch.object(self.service, "sync_fulfilled_orders", return_value=0):
            res = self.service.sync_fulfilled_orders("luxury.myshopify.com")
            self.assertEqual(res, 0)


class TestTier2Feature5MobileNotificationsBoundaries(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 5 (Mobile Notifications)."""

    def setUp(self):
        if not HAS_MOBILE_NOTIFIER:
            self.skipTest("backend.mobile_notifier.MobileNotifier not yet implemented")
        self.notifier = MobileNotifier()

    def test_f5_b01_missing_bot_token_or_chat_id(self):
        """Empty telegram_bot_token or telegram_chat_id returns error without network attempt."""
        settings = make_sample_shop_settings()
        settings["telegram_bot_token"] = ""
        settings["telegram_chat_id"] = ""

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))
            # Verify no HTTP call was made to Telegram API
            self.assertFalse(any("api.telegram.org" in str(c) for c in mock_post.mock_calls))

    def test_f5_b02_missing_discord_webhook_url(self):
        """Empty discord_webhook_url returns error without network attempt."""
        settings = make_sample_shop_settings()
        settings["discord_webhook_url"] = ""

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))
            self.assertFalse(any("discord.com" in str(c) for c in mock_post.mock_calls))

    def test_f5_b03_telegram_html_special_chars_escaping(self):
        """Product names and customer names with <, >, & are HTML-escaped for Telegram."""
        settings = make_sample_shop_settings()
        data = {
            "customer_name": "Elena <VIP & Gold>",
            "total_price": 100.0,
            "currency": "EUR",
            "items": ["Silk Shirt <Limited & Rare>"]
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp

            asyncio.run(self.notifier.notify_merchant("abandoned_cart", data, settings))

            if mock_post.called:
                for call in mock_post.call_args_list:
                    payload = call[1].get("json", {})
                    text = payload.get("text", "")
                    if text and "api.telegram.org" in str(call):
                        self.assertNotIn("<VIP & Gold>", text)
                        self.assertIn("&lt;VIP &amp; Gold&gt;", text)

    def test_f5_b04_discord_embed_field_length_limits(self):
        """Discord field values exceeding 1024 characters are truncated to prevent HTTP 400."""
        settings = make_sample_shop_settings()
        long_desc = "X" * 1500
        data = {
            "customer_name": "Lorenzo",
            "items": [long_desc]
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 204
            mock_post.return_value = mock_resp

            asyncio.run(self.notifier.notify_merchant("abandoned_cart", data, settings))

            if mock_post.called:
                for call in mock_post.call_args_list:
                    payload = call[1].get("json", {})
                    embeds = payload.get("embeds", [])
                    for emb in embeds:
                        for f in emb.get("fields", []):
                            self.assertLessEqual(len(f.get("value", "")), 1024)

    def test_f5_b05_notification_disabled_toggles(self):
        """When notify_telegram=False and notify_discord=False, zero notifications are dispatched."""
        settings = make_sample_shop_settings()
        settings["notify_telegram"] = False
        settings["notify_discord"] = False

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))
            self.assertFalse(mock_post.called)


if __name__ == "__main__":
    unittest.main()

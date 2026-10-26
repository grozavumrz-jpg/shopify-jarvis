"""
tests/test_mobile_notifier_adversarial.py
Adversarial Stress Test Suite for backend/mobile_notifier.py (Milestone 2 Challenger 2).

Probes:
1. Telegram HTML injection:
   - Dynamic inputs with <script>, <b>, unclosed <img src=x, &amp;, quotes, emojis, multiline text.
   - html.escape() verification preserving intentional layout tags.
   - Stage / discount / event_type parameter injection.
2. Discord Embed length limits:
   - Customer name with 2,000 characters.
   - Product list with 5,000 characters (single string and multi-item list).
   - URL / wa_link with 2,000+ characters.
   - All field values truncated <= 1024 characters.
   - Total embed character limit verification (< 6000 chars).
3. Event color validation:
   - Abandoned cart == 0xF59E0B (16096779).
   - Recovery converted == 0x10B981 (1096065).
   - VIP upsell == 0x6366F1 (6514417).
4. Failure isolation:
   - HTTP 429 Rate Limited, 500 Server Error, ConnectTimeout, ReadTimeout, ConnectError.
   - Partial failure isolation (one channel fails, other succeeds).
   - Calling service never crashes.
5. Channel toggle verification:
   - notify_telegram=False, notify_discord=False ensures zero HTTP requests.
   - Independent toggles and missing credentials pre-flight checks.
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio
import httpx
import re
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
from mobile_notifier import MobileNotifier


def make_test_settings(
    telegram_token: str = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
    telegram_chat_id: str = "987654321",
    notify_telegram: bool = True,
    discord_url: str = "https://discord.com/api/webhooks/123456789/abcdef",
    notify_discord: bool = True
):
    return {
        "telegram_bot_token": telegram_token,
        "telegram_chat_id": telegram_chat_id,
        "notify_telegram": notify_telegram,
        "discord_webhook_url": discord_url,
        "notify_discord": notify_discord
    }


class TestAdversarialTelegramHTMLInjection(unittest.TestCase):
    """Probe 1: Adversarial HTML Injection against Telegram Bot API formatting."""

    def setUp(self):
        self.notifier = MobileNotifier()

    def test_xss_script_tags_escaped_across_all_fields(self):
        """Dynamic input containing <script>alert(1)</script> must be escaped and never appear raw."""
        xss_payload = "<script>alert('xss_exploit')</script>"
        data = {
            "customer_name": f"Hacker {xss_payload}",
            "total_price": 250.00,
            "currency": f"USD{xss_payload}",
            "items": [f"Malicious Product {xss_payload}"],
            "checkout_url": f"https://shop.com/checkout?token={xss_payload}",
            "wa_recovery_link": f"https://wa.me/123456?text={xss_payload}",
            "discount_code": f"SAVE{xss_payload}"
        }

        tg_text = self.notifier.format_telegram_message("abandoned_cart", data)

        # Raw <script> tag must NOT exist in output
        self.assertNotIn("<script>", tg_text)
        self.assertNotIn("</script>", tg_text)

        # Escaped versions must exist
        self.assertIn("&lt;script&gt;alert(&#x27;xss_exploit&#x27;)&lt;/script&gt;", tg_text)

        # Intentional tags must remain valid
        self.assertIn("<b>Coș Abandonat Detectat!", tg_text)
        self.assertIn("👤 <b>Client:</b>", tg_text)
        self.assertIn("💰 <b>Valoare:</b>", tg_text)
        self.assertIn("🛍️ <b>Produse:</b>", tg_text)
        self.assertIn("<a href=", tg_text)

    def test_nested_and_unclosed_html_tags_escaped(self):
        """Unclosed tags like <img src=x onerror=alert(1), <b>bold</b>, <svg/onload=...> must be escaped."""
        evil_inputs = [
            "<img src=x onerror=alert('xss')>",
            "<b style='color:red'>Breakout Bold</b>",
            "<svg onload=alert(1)>",
            "<div><span>Unclosed nested",
            "</b extra>",
            "<!-- HTML comment -->",
            "<![CDATA[malicious]]>"
        ]

        for evil in evil_inputs:
            data = {
                "customer_name": f"Buyer {evil}",
                "items": [f"Item {evil}"],
                "total_price": 50.0
            }
            tg_text = self.notifier.format_telegram_message("abandoned_cart", data)

            # Ensure none of the evil raw tags appear
            self.assertNotIn(evil, tg_text)
            self.assertNotIn("<img", tg_text)
            self.assertNotIn("<svg", tg_text)
            self.assertNotIn("<div", tg_text)
            self.assertNotIn("<!--", tg_text)

    def test_ampersands_quotes_and_entities(self):
        """Verify &amp;, quotes, and entities are handled without double-escaping bugs or entity corruption."""
        data = {
            "customer_name": 'John "The VIP" O\'Connor & Sons',
            "items": ["Item & Brand <Special>", "Item &amp; Co"],
            "currency": "EUR & USD",
            "total_price": 100.0,
            "checkout_url": "https://store.com/cart?a=1&b=2&c=3"
        }
        tg_text = self.notifier.format_telegram_message("abandoned_cart", data)

        # Verify quotes are escaped
        self.assertIn("&quot;The VIP&quot;", tg_text)
        self.assertIn("O&#x27;Connor", tg_text)
        # Ampersands escaped
        self.assertIn("&amp; Sons", tg_text)
        self.assertIn("&amp; Brand &lt;Special&gt;", tg_text)

    def test_unicode_emojis_multiline_and_special_characters(self):
        """Complex unicode, RTL overrides, zero-width chars, emojis, and multiline text."""
        multiline_name = "Line 1\nLine 2\r\nLine 3"
        arabic_text = "مرحبا بالعالم"
        complex_emojis = "👑💎🔥👨‍👩‍👧‍👦🚀"
        zero_width = "Invisible\u200BName\u200DTest"

        data = {
            "customer_name": f"{multiline_name} {arabic_text} {complex_emojis} {zero_width}",
            "items": [f"Emoji Set {complex_emojis}\nSecond line"],
            "total_price": 99.99
        }
        tg_text = self.notifier.format_telegram_message("abandoned_cart", data)

        self.assertIn(arabic_text, tg_text)
        self.assertIn(complex_emojis, tg_text)
        self.assertIn(zero_width, tg_text)
        self.assertIn("Line 1\nLine 2\r\nLine 3", tg_text)

    def test_stage_parameter_handling_in_telegram_message(self):
        """Probe: Does stage parameter allow HTML injection into the message header?"""
        evil_stage = "1</b><script>alert('stage')</script>"
        data = {
            "customer_name": "Test",
            "total_price": 10.0,
            "items": ["Item"],
            "stage": evil_stage
        }
        tg_text = self.notifier.format_telegram_message("abandoned_cart", data)

        # Probe whether stage is sanitized or leaks unescaped tags
        # If unescaped, it would contain <script>
        has_raw_script = "<script>" in tg_text
        if has_raw_script:
            print("[VULNERABILITY DETECTED]: 'stage' parameter in format_telegram_message is not escaped!")
        # We record whether it's escaped
        self.assertNotIn("<script>", tg_text, "Stage parameter must not leak unescaped <script> tags!")

    def test_all_event_types_html_sanitized(self):
        """Verify HTML escaping across recovery_converted, vip_upsell_sent, and generic fallback."""
        bad_name = "Malicious <script>alert(1)</script>"
        bad_order = "ORD<script>999</script>"
        bad_discount = "DISC<script>15</script>"

        # 1. recovery_converted
        conv_text = self.notifier.format_telegram_message("recovery_converted", {
            "customer_name": bad_name,
            "order_number": bad_order,
            "recovered_revenue": 100.0,
            "discount_code": bad_discount
        })
        self.assertNotIn("<script>", conv_text)
        self.assertIn("&lt;script&gt;", conv_text)
        self.assertIn("🎉 <b>Venit Recuperat cu Succes!</b>", conv_text)

        # 2. vip_upsell_sent
        vip_text = self.notifier.format_telegram_message("vip_upsell_sent", {
            "customer_name": bad_name,
            "order_number": bad_order,
            "discount_code": bad_discount
        })
        self.assertNotIn("<script>", vip_text)
        self.assertIn("&lt;script&gt;", vip_text)
        self.assertIn("👑 <b>VIP Review &amp; Upsell Expediat!</b>", vip_text)

        # 3. fallback with evil event_type
        evil_event = "custom<script>alert(1)</script>"
        fallback_text = self.notifier.format_telegram_message(evil_event, {
            "customer_name": bad_name
        })
        self.assertNotIn("<script>", fallback_text)
        self.assertIn("&lt;script&gt;", fallback_text)


class TestAdversarialDiscordEmbedLimits(unittest.TestCase):
    """Probe 2: Discord Embed Length Limits (<= 1024 char field values, total limit < 6000)."""

    def setUp(self):
        self.notifier = MobileNotifier()

    def test_customer_name_2000_chars_truncated(self):
        """Customer name with 2,000 characters must be truncated to <= 1024."""
        giant_name = "C" * 2000
        data = {
            "customer_name": giant_name,
            "total_price": 50.0,
            "items": ["Item"]
        }
        embed = self.notifier.format_discord_embed("abandoned_cart", data)

        client_field = next(f for f in embed["fields"] if f["name"] == "Client")
        self.assertLessEqual(len(client_field["value"]), 1024)
        self.assertEqual(len(client_field["value"]), 1024)
        self.assertTrue(client_field["value"].endswith("..."))

    def test_product_list_5000_chars_truncated(self):
        """Product list with 5,000 characters must be truncated to <= 1024."""
        giant_items = "P" * 5000
        data = {
            "customer_name": "Test",
            "total_price": 50.0,
            "items": [giant_items]
        }
        embed = self.notifier.format_discord_embed("abandoned_cart", data)

        prod_field = next(f for f in embed["fields"] if f["name"] == "Produse")
        self.assertLessEqual(len(prod_field["value"]), 1024)
        self.assertEqual(len(prod_field["value"]), 1024)
        self.assertTrue(prod_field["value"].endswith("..."))

    def test_multi_item_list_exceeding_5000_chars(self):
        """A list of 200 item dictionaries resulting in > 5000 characters total."""
        items = [{"title": f"Luxurious Item #{i} with very long descriptive title", "quantity": i} for i in range(200)]
        data = {
            "customer_name": "Test",
            "items": items
        }
        embed = self.notifier.format_discord_embed("abandoned_cart", data)

        prod_field = next(f for f in embed["fields"] if f["name"] == "Produse")
        self.assertLessEqual(len(prod_field["value"]), 1024)
        self.assertTrue(prod_field["value"].endswith("..."))

    def test_total_embed_size_under_discord_6000_character_limit(self):
        """Under simultaneous adversarial stress on all fields, total characters must be < 6000."""
        data = {
            "customer_name": "A" * 2000,
            "currency": "EUR" * 100,
            "items": ["B" * 5000],
            "checkout_url": "https://store.com/checkout?" + ("x" * 2000),
            "wa_recovery_link": "https://wa.me/123456?text=" + ("y" * 2000),
            "stage": 2,
            "discount_code": "DISCOUNT" * 50
        }
        embed = self.notifier.format_discord_embed("abandoned_cart", data)

        total_chars = 0
        total_chars += len(embed.get("title", ""))
        total_chars += len(embed.get("description", ""))
        for f in embed.get("fields", []):
            total_chars += len(f.get("name", ""))
            total_chars += len(f.get("value", ""))
        total_chars += len(embed.get("footer", {}).get("text", ""))

        # Discord limit is 6000 total characters for an embed
        self.assertLess(total_chars, 6000, f"Total embed characters ({total_chars}) exceeds Discord 6000 limit!")

    def test_send_discord_notification_clamps_raw_fields_to_1024(self):
        """Direct call to send_discord_notification with oversized raw fields clamps them."""
        raw_embed = {
            "title": "Raw Embed",
            "fields": [
                {"name": "Field1", "value": "X" * 3000},
                {"name": "Field2", "value": "Y" * 1500}
            ]
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(status_code=204)
            asyncio.run(self.notifier.send_discord_notification("https://discord.com/webhook", raw_embed))

            mock_post.assert_called_once()
            sent_payload = mock_post.call_args[1].get("json", {})
            sent_fields = sent_payload["embeds"][0]["fields"]

            for f in sent_fields:
                self.assertLessEqual(len(f["value"]), 1024)
                self.assertTrue(f["value"].endswith("..."))


class TestAdversarialEventColorValidation(unittest.TestCase):
    """Probe 3: Event Color Integer Validation (Exact Hex & Decimal)."""

    def setUp(self):
        self.notifier = MobileNotifier()

    def test_exact_color_integers_on_class(self):
        """Verify class constant integer values match exact hex codes."""
        self.assertEqual(MobileNotifier.COLOR_AMBER, 0xF59E0B)
        self.assertEqual(MobileNotifier.COLOR_AMBER, 16096779)

        self.assertEqual(MobileNotifier.COLOR_EMERALD, 0x10B981)
        self.assertEqual(MobileNotifier.COLOR_EMERALD, 1096065)

        self.assertEqual(MobileNotifier.COLOR_PURPLE, 0x6366F1)
        self.assertEqual(MobileNotifier.COLOR_PURPLE, 6514417)

    def test_abandoned_cart_embed_color_exact(self):
        """Abandoned cart must produce color 0xF59E0B (16096779)."""
        embed = self.notifier.format_discord_embed("abandoned_cart", {"total_price": 100})
        self.assertEqual(embed["color"], 0xF59E0B)
        self.assertEqual(embed["color"], 16096779)

    def test_recovery_converted_embed_color_exact(self):
        """Recovery converted must produce color 0x10B981 (1096065)."""
        embed = self.notifier.format_discord_embed("recovery_converted", {"order_number": "101"})
        self.assertEqual(embed["color"], 0x10B981)
        self.assertEqual(embed["color"], 1096065)

    def test_vip_upsell_embed_color_exact(self):
        """VIP upsell must produce color 0x6366F1 (6514417)."""
        embed = self.notifier.format_discord_embed("vip_upsell_sent", {"order_number": "101"})
        self.assertEqual(embed["color"], 0x6366F1)
        self.assertEqual(embed["color"], 6514417)


class TestAdversarialFailureIsolation(unittest.TestCase):
    """Probe 4: Failure Isolation (HTTP 429, 500, Timeouts, Network Errors)."""

    def setUp(self):
        self.notifier = MobileNotifier()

    def test_telegram_http_429_rate_limited(self):
        """Telegram returns HTTP 429 Too Many Requests -> handled cleanly without throwing."""
        settings = make_test_settings(notify_discord=False)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(
                status_code=429,
                text='{"ok":false,"error_code":429,"description":"Too Many Requests: retry after 36"}'
            )

            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))

            self.assertFalse(res["ok"])
            self.assertEqual(res["telegram"]["status"], 429)
            self.assertIn("Too Many Requests", res["telegram"]["error"])

    def test_telegram_http_500_server_error(self):
        """Telegram returns HTTP 500 Internal Server Error -> handled cleanly without throwing."""
        settings = make_test_settings(notify_discord=False)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(status_code=500, text="Internal Server Error")

            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))

            self.assertFalse(res["ok"])
            self.assertEqual(res["telegram"]["status"], 500)

    def test_discord_http_429_rate_limited(self):
        """Discord returns HTTP 429 -> handled cleanly without throwing."""
        settings = make_test_settings(notify_telegram=False)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(
                status_code=429,
                text='{"message": "You are being rate limited.", "retry_after": 2.5, "global": false}'
            )

            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))

            self.assertFalse(res["ok"])
            self.assertEqual(res["discord"]["status"], 429)
            self.assertIn("rate limited", res["discord"]["error"])

    def test_discord_http_500_server_error(self):
        """Discord returns HTTP 500 -> handled cleanly without throwing."""
        settings = make_test_settings(notify_telegram=False)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(status_code=500, text="Discord 500 Internal Error")

            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))

            self.assertFalse(res["ok"])
            self.assertEqual(res["discord"]["status"], 500)

    def test_connection_timeout_and_network_exceptions(self):
        """ConnectTimeout, ReadTimeout, ConnectError, NetworkError caught safely."""
        network_errors = [
            httpx.ConnectTimeout("Connection timed out after 10.0s"),
            httpx.ReadTimeout("Read timed out"),
            httpx.ConnectError("Connection refused by peer"),
            httpx.NetworkError("Network unreachable"),
            RuntimeError("Unexpected client crash")
        ]

        for err in network_errors:
            # Test Telegram
            with patch("httpx.AsyncClient.post", side_effect=err):
                res_tg = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, make_test_settings(notify_discord=False)))
                self.assertFalse(res_tg["ok"])
                self.assertIn("error", res_tg["telegram"])

            # Test Discord
            with patch("httpx.AsyncClient.post", side_effect=err):
                res_dc = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, make_test_settings(notify_telegram=False)))
                self.assertFalse(res_dc["ok"])
                self.assertIn("error", res_dc["discord"])

    def test_partial_failure_isolation(self):
        """If Telegram fails with 500, Discord should still execute successfully and vice-versa."""
        settings = make_test_settings(notify_telegram=True, notify_discord=True)

        # Telegram fails (500), Discord succeeds (204)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [
                MagicMock(status_code=500, text="Telegram Down"),
                MagicMock(status_code=204)
            ]

            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))

            self.assertEqual(mock_post.call_count, 2)
            self.assertFalse(res["telegram"]["ok"])
            self.assertTrue(res["discord"]["ok"])
            self.assertFalse(res["ok"])  # Overall status is False due to partial failure

        # Discord fails (429), Telegram succeeds (200)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [
                MagicMock(status_code=200, json=lambda: {"ok": True}),
                MagicMock(status_code=429, text="Discord Rate Limited")
            ]

            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))

            self.assertEqual(mock_post.call_count, 2)
            self.assertTrue(res["telegram"]["ok"])
            self.assertFalse(res["discord"]["ok"])
            self.assertFalse(res["ok"])

    def test_numeric_variations_total_price_and_revenue(self):
        """Test valid numeric string, integer, float, None, zero, and empty string handling."""
        settings = make_test_settings(notify_telegram=True, notify_discord=True)
        valid_variations = ["145.00", 145, 99.99, None, 0, ""]

        for val in valid_variations:
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                mock_post.side_effect = [
                    MagicMock(status_code=200, json=lambda: {"ok": True}),
                    MagicMock(status_code=204)
                ]
                res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {
                    "customer_name": "Test",
                    "total_price": val,
                    "items": ["Item"]
                }, settings))
                self.assertTrue(res["ok"], f"Failed on valid price variation: {val}")

    def test_adversarial_non_numeric_price_behavior(self):
        """Probe: Document behavior when non-numeric total_price string is passed -> safe fallback to 0.0."""
        settings = make_test_settings(notify_telegram=True, notify_discord=False)
        bad_data = {
            "customer_name": "Test",
            "total_price": "145.00 EUR",  # non-numeric string with currency suffix
            "items": ["Item"]
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", bad_data, settings))

            # Must not crash, must succeed with 0.00 fallback
            self.assertTrue(res["ok"])
            mock_post.assert_called_once()
            call_text = mock_post.call_args[1].get("json", {}).get("text", "")
            self.assertIn("0.00 EUR", call_text)





class TestAdversarialChannelToggles(unittest.TestCase):
    """Probe 5: Channel Toggle Verification & Missing Credentials."""

    def setUp(self):
        self.notifier = MobileNotifier()

    def test_both_toggles_false_zero_http(self):
        """Both toggles False -> zero HTTP requests, return dispatched=False."""
        settings = make_test_settings(notify_telegram=False, notify_discord=False)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))
            self.assertFalse(mock_post.called)
            self.assertTrue(res["ok"])
            self.assertFalse(res["dispatched"])
            self.assertEqual(res["reason"], "both_channels_disabled")

    def test_telegram_only_toggle(self):
        """notify_telegram=True, notify_discord=False -> exactly 1 HTTP call to Telegram."""
        settings = make_test_settings(notify_telegram=True, notify_discord=False)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))

            self.assertEqual(mock_post.call_count, 1)
            self.assertIn("api.telegram.org", mock_post.call_args[0][0])
            self.assertTrue(res["ok"])
            self.assertTrue(res["telegram"]["ok"])
            self.assertTrue(res["discord"]["skipped"])

    def test_discord_only_toggle(self):
        """notify_telegram=False, notify_discord=True -> exactly 1 HTTP call to Discord."""
        settings = make_test_settings(notify_telegram=False, notify_discord=True)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(status_code=204)
            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))

            self.assertEqual(mock_post.call_count, 1)
            self.assertIn("discord.com", mock_post.call_args[0][0])
            self.assertTrue(res["ok"])
            self.assertTrue(res["telegram"]["skipped"])
            self.assertTrue(res["discord"]["ok"])

    def test_missing_credentials_zero_http(self):
        """Enabled toggles with empty or whitespace-only credentials make zero HTTP calls."""
        # Whitespace or empty Telegram credentials
        settings_bad_tg = make_test_settings(
            telegram_token="   ",
            telegram_chat_id="",
            notify_discord=False
        )
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings_bad_tg))
            self.assertFalse(mock_post.called)
            self.assertFalse(res["ok"])
            self.assertEqual(res["telegram"]["reason"], "missing_telegram_credentials")

        # Whitespace or empty Discord webhook URL
        settings_bad_dc = make_test_settings(
            discord_url="   ",
            notify_telegram=False
        )
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings_bad_dc))
            self.assertFalse(mock_post.called)
            self.assertFalse(res["ok"])
            self.assertEqual(res["discord"]["reason"], "missing_discord_webhook_url")


if __name__ == "__main__":
    unittest.main()

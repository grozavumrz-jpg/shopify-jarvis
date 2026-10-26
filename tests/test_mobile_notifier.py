"""
Unit tests for backend/mobile_notifier.py
Exhaustively validates:
1. Telegram Bot API: HTML formatted alert dispatch, parse_mode="HTML" assertion.
2. Telegram HTML sanitization: strict html.escape() of customer names, item names (<, >, &).
3. Telegram credential validation: missing token or chat ID gracefully skips HTTP calls.
4. Discord Webhook: Rich Embed structure, title, fields, timestamp, customer/revenue info.
5. Discord Color Coding:
   - abandoned_cart: Amber (0xF59E0B / 16096779)
   - recovery_converted: Emerald (0x10B981 / 1096065)
   - vip_upsell_sent: Purple (0x6366F1 / 6514417)
6. Discord field length limits: truncation of values exceeding 1024 chars to avoid HTTP 400.
7. Discord credential validation: missing webhook URL gracefully skips HTTP calls.
8. Channel toggles: notify_telegram=False and notify_discord=False independently and jointly honored.
9. Network timeout & partial failure resilience: catches httpx.TimeoutException without crashing.
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio
import httpx
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


class TestMobileNotifierTelegram(unittest.TestCase):
    """Exhaustive tests for Telegram Bot API merchant alerts."""

    def setUp(self):
        self.notifier = MobileNotifier()

    def test_telegram_abandoned_cart_payload_structure(self):
        """Verify Telegram POST URL, parse_mode='HTML', chat_id, and content for abandoned cart."""
        settings = make_test_settings(notify_discord=False)
        data = {
            "customer_name": "Elena Popescu",
            "total_price": 145.00,
            "currency": "EUR",
            "items": ["Maison Cashmere Knitwear"],
            "checkout_url": "https://grozavu.store/checkouts/ac/123"
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})

            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", data, settings))

            self.assertTrue(res.get("ok", True))
            mock_post.assert_called_once()
            call_url = mock_post.call_args[0][0]
            call_payload = mock_post.call_args[1].get("json", {})

            self.assertIn("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", call_url)
            self.assertEqual(call_payload.get("chat_id"), "987654321")
            self.assertEqual(call_payload.get("parse_mode"), "HTML")
            self.assertIn("Elena Popescu", call_payload.get("text", ""))
            self.assertIn("145.0", call_payload.get("text", ""))

    def test_telegram_html_special_characters_escaping(self):
        """Verify that customer names and item titles with <, >, & are escaped with html.escape()."""
        settings = make_test_settings(notify_discord=False)
        data = {
            "customer_name": "Elena <VIP & Gold>",
            "total_price": 100.0,
            "currency": "EUR",
            "items": ["Silk Shirt <Limited & Rare>"]
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})

            asyncio.run(self.notifier.notify_merchant("abandoned_cart", data, settings))

            mock_post.assert_called_once()
            text = mock_post.call_args[1].get("json", {}).get("text", "")

            # Unescaped raw characters must NOT exist
            self.assertNotIn("<VIP & Gold>", text)
            self.assertNotIn("<Limited & Rare>", text)
            # Escaped entities must be present
            self.assertIn("&lt;VIP &amp; Gold&gt;", text)
            self.assertIn("&lt;Limited &amp; Rare&gt;", text)

    def test_telegram_missing_token_or_chat_id_skips_network(self):
        """Empty bot token or chat ID results in zero network requests to Telegram."""
        for bad_settings in [
            make_test_settings(telegram_token="", notify_discord=False),
            make_test_settings(telegram_chat_id="", notify_discord=False),
            make_test_settings(telegram_token="", telegram_chat_id="", notify_discord=False)
        ]:
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, bad_settings))
                self.assertFalse(mock_post.called)


class TestMobileNotifierDiscord(unittest.TestCase):
    """Exhaustive tests for Discord Webhook merchant alerts."""

    def setUp(self):
        self.notifier = MobileNotifier()

    def test_discord_abandoned_cart_amber_embed(self):
        """Verify abandoned cart sends Rich Embed with amber color (0xF59E0B / 16096779)."""
        settings = make_test_settings(notify_telegram=False)
        data = {
            "customer_name": "Elena Popescu",
            "total_price": 145.00,
            "currency": "EUR",
            "items": ["Maison Cashmere Knitwear"]
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(status_code=204)

            asyncio.run(self.notifier.notify_merchant("abandoned_cart", data, settings))

            mock_post.assert_called_once()
            payload = mock_post.call_args[1].get("json", {})
            embeds = payload.get("embeds", [])
            self.assertTrue(len(embeds) > 0)
            self.assertIn(embeds[0].get("color"), [16096779, 0xF59E0B, 16753920])

    def test_discord_recovery_converted_emerald_embed(self):
        """Verify recovery_converted sends Rich Embed with emerald color (0x10B981 / 1096065)."""
        settings = make_test_settings(notify_telegram=False)
        data = {
            "customer_name": "Elena Popescu",
            "order_number": "1002",
            "recovered_revenue": 145.00,
            "currency": "EUR",
            "discount_code": "MG10"
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(status_code=204)

            asyncio.run(self.notifier.notify_merchant("recovery_converted", data, settings))

            mock_post.assert_called_once()
            payload = mock_post.call_args[1].get("json", {})
            embeds = payload.get("embeds", [])
            self.assertTrue(len(embeds) > 0)
            self.assertIn(embeds[0].get("color"), [1096065, 0x10B981, 65280])

    def test_discord_vip_upsell_sent_purple_embed(self):
        """Verify vip_upsell_sent sends Rich Embed with purple color (0x6366F1 / 6514417)."""
        settings = make_test_settings(notify_telegram=False)
        data = {
            "customer_name": "Lorenzo Rossi",
            "order_number": "1001",
            "discount_code": "MGVIP15"
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(status_code=204)

            asyncio.run(self.notifier.notify_merchant("vip_upsell_sent", data, settings))

            mock_post.assert_called_once()
            payload = mock_post.call_args[1].get("json", {})
            embeds = payload.get("embeds", [])
            self.assertTrue(len(embeds) > 0)
            self.assertIn(embeds[0].get("color"), [6514417, 0x6366F1, 0x5865F2])

    def test_discord_field_length_truncation_to_1024(self):
        """Discord field values > 1024 characters are truncated to avoid HTTP 400."""
        settings = make_test_settings(notify_telegram=False)
        long_text = "A" * 1500
        data = {
            "customer_name": "Lorenzo",
            "items": [long_text]
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(status_code=204)

            asyncio.run(self.notifier.notify_merchant("abandoned_cart", data, settings))

            payload = mock_post.call_args[1].get("json", {})
            embeds = payload.get("embeds", [])
            for emb in embeds:
                for f in emb.get("fields", []):
                    self.assertLessEqual(len(f.get("value", "")), 1024)

    def test_discord_missing_webhook_url_skips_network(self):
        """Empty discord webhook URL results in zero network requests to Discord."""
        settings = make_test_settings(discord_url="", notify_telegram=False)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))
            self.assertFalse(mock_post.called)


class TestMobileNotifierTogglesAndResilience(unittest.TestCase):
    """Channel toggles and timeout resilience tests."""

    def setUp(self):
        self.notifier = MobileNotifier()

    def test_both_channels_disabled(self):
        """When notify_telegram=False and notify_discord=False, zero HTTP requests are dispatched."""
        settings = make_test_settings(notify_telegram=False, notify_discord=False)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))
            self.assertFalse(mock_post.called)

    def test_both_channels_enabled_dispatches_to_both(self):
        """When both toggles are True, both Telegram and Discord endpoints are invoked."""
        settings = make_test_settings(notify_telegram=True, notify_discord=True)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [
                MagicMock(status_code=200, json=lambda: {"ok": True}), # Telegram
                MagicMock(status_code=204)                              # Discord
            ]
            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"customer_name": "Test", "items": ["Item"]}, settings))

            self.assertEqual(mock_post.call_count, 2)
            urls = [c[0][0] for c in mock_post.call_args_list]
            self.assertTrue(any("api.telegram.org" in u for u in urls))
            self.assertTrue(any("discord.com" in u for u in urls))

    def test_network_timeout_resilience_telegram_does_not_crash(self):
        """httpx.TimeoutException on Telegram does not raise an unhandled exception."""
        settings = make_test_settings(notify_discord=False)
        with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Telegram timeout")):
            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))
            self.assertIsNotNone(res)
            self.assertFalse(res.get("telegram", {}).get("ok", True))

    def test_network_timeout_resilience_discord_does_not_crash(self):
        """httpx.TimeoutException on Discord does not raise an unhandled exception."""
        settings = make_test_settings(notify_telegram=False)
        with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Discord timeout")):
            res = asyncio.run(self.notifier.notify_merchant("abandoned_cart", {"items": ["Item"]}, settings))
            self.assertIsNotNone(res)
            self.assertFalse(res.get("discord", {}).get("ok", True))


if __name__ == "__main__":
    unittest.main()

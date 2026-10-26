"""
Adversarial Stress Test Suite for backend/whatsapp_dispatcher.py.
Author: Challenger 1 (Milestone 2)

Probes:
1. Phone normalization stress test:
   - Weird formats: +39 (06) 1234-5678, 0040 722 123 456, +400722123456, 39 333 1234567,
     0722123456, +34 612 345 678, 0034612345678, short invalid numbers (12345),
     non-digit strings, None, and edge formats.
2. URL generation stress test:
   - generate_wa_me_link with special characters, quotes, ampersands, newlines,
     query strings inside messages, and emojis.
   - Verifies round-trip lossless decode via urllib.parse.parse_qs.
3. Multi-tenant store isolation:
   - Store A (Twilio) vs Store B (Meta) isolation.
   - Interleaved multi-tenant calls.
   - Store C (unconfigured) fallback without credential contamination.
4. Provider waterfall failover:
   - Primary provider HTTP 401, 500, TimeoutException, ConnectError.
   - Secondary provider cascade and terminal wa.me link generation.
   - Explicit provider failure handling and wa.me link preservation.
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio
import urllib.parse
import httpx
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
from whatsapp_dispatcher import WhatsAppDispatcher


class TestAdversarialPhoneNormalization(unittest.TestCase):
    """Adversarial stress testing for phone normalization."""

    def setUp(self):
        self.dispatcher = WhatsAppDispatcher()

    def test_adv_phone_italian_landline_with_brackets(self):
        """Probe: +39 (06) 1234-5678 -> Rome landline with trunk 0 preserved."""
        cleaned = self.dispatcher.clean_phone_number("+39 (06) 1234-5678")
        self.assertEqual(cleaned, "390612345678")

    def test_adv_phone_romanian_leading_double_zero_with_spaces(self):
        """Probe: 0040 722 123 456 -> strips 00, yields 40722123456."""
        cleaned = self.dispatcher.clean_phone_number("0040 722 123 456")
        self.assertEqual(cleaned, "40722123456")

    def test_adv_phone_romanian_accidental_double_prefix(self):
        """
        Probe: +400722123456 (common typo where user enters +40 followed by national 0722...).
        Checks actual behavior of clean_phone_number.
        """
        cleaned = self.dispatcher.clean_phone_number("+400722123456")
        # Currently clean_phone_number extracts digits: '400722123456' (12 digits)
        # We record the exact empirical behavior
        self.assertIn(cleaned, ["400722123456", "40722123456"])

    def test_adv_phone_italian_mobile_with_country_code_and_spaces(self):
        """Probe: 39 333 1234567 -> 393331234567."""
        cleaned = self.dispatcher.clean_phone_number("39 333 1234567")
        self.assertEqual(cleaned, "393331234567")

    def test_adv_phone_romanian_local_07(self):
        """Probe: 0722123456 -> 40722123456."""
        cleaned = self.dispatcher.clean_phone_number("0722123456")
        self.assertEqual(cleaned, "40722123456")

    def test_adv_phone_spanish_mobile_variations(self):
        """Probe: +34 612 345 678 and 0034612345678 -> 34612345678."""
        self.assertEqual(self.dispatcher.clean_phone_number("+34 612 345 678"), "34612345678")
        self.assertEqual(self.dispatcher.clean_phone_number("0034612345678"), "34612345678")

    def test_adv_phone_short_and_invalid_inputs(self):
        """Probe: '12345', 'non-digit strings', None in clean_phone_number and send_message."""
        # clean_phone_number returns raw digits or empty string
        self.assertEqual(self.dispatcher.clean_phone_number("12345"), "12345")
        self.assertEqual(self.dispatcher.clean_phone_number("non-digit strings"), "")
        self.assertEqual(self.dispatcher.clean_phone_number(None), "")
        self.assertEqual(self.dispatcher.clean_phone_number("   "), "")

        # send_message must reject all of these (< 8 digits)
        for invalid in ["12345", "non-digit strings", None, "   ", "+", ""]:
            res = asyncio.run(self.dispatcher.send_message(invalid, "Adversarial test"))
            self.assertFalse(res.get("ok"))
            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("provider"), "none")
            self.assertIsNone(res.get("wa_me_url"))


class TestAdversarialUrlGeneration(unittest.TestCase):
    """Adversarial stress testing for canonical wa.me link generation."""

    def setUp(self):
        self.dispatcher = WhatsAppDispatcher()

    def test_adv_url_complex_message_with_url_and_emojis(self):
        """
        Probe: 'Hey John 👋! Recover your cart: https://shop.com/c/1?a=b&c=d'
        Must produce a valid URL where urllib.parse.parse_qs recovers the exact message.
        """
        msg = "Hey John 👋! Recover your cart: https://shop.com/c/1?a=b&c=d"
        link = self.dispatcher.generate_wa_me_link("+40722123456", msg)

        # 1. Structural checks
        self.assertTrue(link.startswith("https://wa.me/40722123456?text="))
        self.assertNotIn(" ", link)
        self.assertNotIn("\n", link)

        # 2. Lossless recovery oracle
        parsed = urllib.parse.urlparse(link)
        qs = urllib.parse.parse_qs(parsed.query)
        self.assertIn("text", qs)
        self.assertEqual(qs["text"][0], msg)

    def test_adv_url_quotes_ampersands_newlines_and_symbols(self):
        """
        Probe: Quotes, ampersands, percent signs, plus signs, newlines, tabs, and multi-byte emojis.
        """
        msg = (
            "Hello \"VIP\" & 'Loyal' Customer! 👋\n"
            "Your discount: 15% OFF + FREE GIFT 🎁\n"
            "Link: https://luxury-shop.com/cart?discount=MGVIP15&ref=wa#checkout\n"
            "Questions? Reply 'YES' or \"HELP\"!"
        )
        link = self.dispatcher.generate_wa_me_link("+39 340 123 4567", msg)

        # Structural checks
        self.assertTrue(link.startswith("https://wa.me/393401234567?text="))
        self.assertNotIn(" ", link)
        self.assertNotIn("\n", link)
        self.assertNotIn("\r", link)
        self.assertNotIn("\t", link)

        # Lossless recovery oracle
        parsed = urllib.parse.urlparse(link)
        qs = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(qs["text"][0], msg)


class TestAdversarialMultiTenantIsolation(unittest.TestCase):
    """Adversarial stress testing for multi-tenant store isolation."""

    def setUp(self):
        self.dispatcher = WhatsAppDispatcher()

    def test_adv_store_a_twilio_store_b_meta_isolation(self):
        """
        Store A (Twilio only) and Store B (Meta only) dispatched consecutively.
        Store A must never invoke Meta Cloud API.
        Store B must never invoke Twilio API.
        """
        settings_store_a = {
            "shop": "store-a.myshopify.com",
            "whatsapp_provider": "twilio",
            "twilio_account_sid": "AC_STORE_A_12345",
            "twilio_auth_token": "AUTH_STORE_A_SECRET",
            "twilio_whatsapp_number": "whatsapp:+14150000001"
        }
        settings_store_b = {
            "shop": "store-b.myshopify.com",
            "whatsapp_provider": "meta",
            "whatsapp_api_token": "META_TOKEN_STORE_B_XYZ",
            "whatsapp_phone_number_id": "PHONE_ID_STORE_B_999"
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            resp_twilio = MagicMock(status_code=201, json=lambda: {"sid": "SM_STORE_A_SUCCESS"})
            resp_meta = MagicMock(status_code=200, json=lambda: {"messages": [{"id": "WAMID_STORE_B_SUCCESS"}]})
            mock_post.side_effect = [resp_twilio, resp_meta]

            res_a = asyncio.run(self.dispatcher.send_message("+393401234567", "Message for Store A", settings=settings_store_a))
            res_b = asyncio.run(self.dispatcher.send_message("+40721123456", "Message for Store B", settings=settings_store_b))

            # Verify Store A result
            self.assertTrue(res_a.get("ok"))
            self.assertEqual(res_a.get("provider"), "twilio")
            self.assertEqual(res_a.get("sid"), "SM_STORE_A_SUCCESS")

            # Verify Store B result
            self.assertTrue(res_b.get("ok"))
            self.assertEqual(res_b.get("provider"), "meta")
            self.assertEqual(res_b.get("id"), "WAMID_STORE_B_SUCCESS")

            # Verify HTTP post parameters for Store A (Call 0)
            call_a = mock_post.call_args_list[0]
            url_a = call_a[0][0]
            auth_a = call_a[1].get("auth")
            self.assertIn("AC_STORE_A_12345", url_a)
            self.assertEqual(auth_a, ("AC_STORE_A_12345", "AUTH_STORE_A_SECRET"))
            self.assertNotIn("META_TOKEN_STORE_B_XYZ", str(call_a))

            # Verify HTTP post parameters for Store B (Call 1)
            call_b = mock_post.call_args_list[1]
            url_b = call_b[0][0]
            headers_b = call_b[1].get("headers", {})
            self.assertIn("PHONE_ID_STORE_B_999", url_b)
            self.assertEqual(headers_b.get("Authorization"), "Bearer META_TOKEN_STORE_B_XYZ")
            self.assertNotIn("AC_STORE_A_12345", str(call_b))

    def test_adv_unconfigured_store_c_falls_back_without_leakage(self):
        """
        Store C has no credentials configured.
        Must fall back cleanly to wa.me link without picking up credentials from other stores.
        """
        settings_store_c = {
            "shop": "store-c.myshopify.com",
            "whatsapp_provider": "auto",
            "whatsapp_api_token": "",
            "twilio_account_sid": ""
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res_c = asyncio.run(self.dispatcher.send_message("+40721123456", "Message for Store C", settings=settings_store_c))

            # Must not have made any HTTP requests
            mock_post.assert_not_called()

            self.assertFalse(res_c.get("ok"))
            self.assertEqual(res_c.get("provider"), "wa_me")
            self.assertEqual(res_c.get("gateway"), "wa_me_link")
            self.assertTrue(res_c.get("wa_me_url").startswith("https://wa.me/40721123456"))


class TestAdversarialWaterfallFailover(unittest.TestCase):
    """Adversarial stress testing for provider waterfall failover."""

    def setUp(self):
        self.dispatcher = WhatsAppDispatcher()
        self.auto_settings = {
            "whatsapp_provider": "auto",
            "whatsapp_api_token": "EAAX_META_KEY",
            "whatsapp_phone_number_id": "META_PID_111",
            "twilio_account_sid": "AC_TWILIO_SID",
            "twilio_auth_token": "TWILIO_TOK",
            "twilio_whatsapp_number": "whatsapp:+14155238886"
        }

    def test_adv_failover_meta_http_401_to_twilio_success(self):
        """Probe: Meta returns HTTP 401 (Invalid/expired token) -> cascades to Twilio -> succeeds."""
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            resp_meta_401 = MagicMock(status_code=401, text='{"error":{"message":"Invalid OAuth access token."}}')
            resp_twilio_201 = MagicMock(status_code=201, json=lambda: {"sid": "SM_TWILIO_BACKUP"})
            mock_post.side_effect = [resp_meta_401, resp_twilio_201]

            res = asyncio.run(self.dispatcher.send_message("+40721123456", "Cart reminder", settings=self.auto_settings))

            self.assertTrue(res.get("ok"))
            self.assertEqual(res.get("provider"), "twilio")
            self.assertEqual(res.get("sid"), "SM_TWILIO_BACKUP")
            self.assertEqual(mock_post.call_count, 2)

    def test_adv_failover_meta_http_500_to_twilio_success(self):
        """Probe: Meta returns HTTP 500 (Graph API internal server error) -> cascades to Twilio -> succeeds."""
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            resp_meta_500 = MagicMock(status_code=500, text="Internal Server Error")
            resp_twilio_201 = MagicMock(status_code=201, json=lambda: {"sid": "SM_TWILIO_RECOVER"})
            mock_post.side_effect = [resp_meta_500, resp_twilio_201]

            res = asyncio.run(self.dispatcher.send_message("+40721123456", "Cart reminder", settings=self.auto_settings))

            self.assertTrue(res.get("ok"))
            self.assertEqual(res.get("provider"), "twilio")
            self.assertEqual(mock_post.call_count, 2)

    def test_adv_failover_meta_timeout_to_twilio_success(self):
        """Probe: Meta raises httpx.TimeoutException -> cascades to Twilio -> succeeds."""
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            resp_twilio_201 = MagicMock(status_code=201, json=lambda: {"sid": "SM_TWILIO_TIMEOUT_RESCUE"})
            mock_post.side_effect = [httpx.TimeoutException("Meta request timed out"), resp_twilio_201]

            res = asyncio.run(self.dispatcher.send_message("+40721123456", "Cart reminder", settings=self.auto_settings))

            self.assertTrue(res.get("ok"))
            self.assertEqual(res.get("provider"), "twilio")
            self.assertEqual(mock_post.call_count, 2)

    def test_adv_failover_meta_network_error_to_twilio_success(self):
        """Probe: Meta raises httpx.ConnectError -> cascades to Twilio -> succeeds."""
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            resp_twilio_201 = MagicMock(status_code=201, json=lambda: {"sid": "SM_TWILIO_NET_RESCUE"})
            mock_post.side_effect = [httpx.ConnectError("Connection refused by Meta proxy"), resp_twilio_201]

            res = asyncio.run(self.dispatcher.send_message("+40721123456", "Cart reminder", settings=self.auto_settings))

            self.assertTrue(res.get("ok"))
            self.assertEqual(res.get("provider"), "twilio")
            self.assertEqual(mock_post.call_count, 2)

    def test_adv_failover_all_providers_fail_terminal_wa_me_link(self):
        """
        Probe: Meta returns HTTP 500, Twilio returns HTTP 500, Webhook returns HTTP 500.
        Must gracefully cascade to canonical wa.me link with error details and ok=False.
        """
        full_settings = dict(self.auto_settings)
        full_settings["whatsapp_webhook_url"] = "https://my-webhook.com/send"

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            resp_meta_500 = MagicMock(status_code=500, text="Meta 500")
            resp_twilio_500 = MagicMock(status_code=500, text="Twilio 500")
            resp_webhook_500 = MagicMock(status_code=500, text="Webhook 500")
            mock_post.side_effect = [resp_meta_500, resp_twilio_500, resp_webhook_500]

            res = asyncio.run(self.dispatcher.send_message("+40721123456", "Emergency reminder", settings=full_settings))

            self.assertFalse(res.get("ok"))
            self.assertEqual(res.get("provider"), "wa_me")
            self.assertEqual(res.get("gateway"), "wa_me_link")
            self.assertIsNotNone(res.get("wa_me_url"))
            self.assertTrue(res.get("wa_me_url").startswith("https://wa.me/40721123456"))
            self.assertIn("Webhook HTTP 500", res.get("error", ""))
            self.assertEqual(mock_post.call_count, 3)

    def test_adv_explicit_provider_meta_error_preserves_wa_link(self):
        """Probe: Explicit provider=meta raising HTTP 401 returns ok=False but preserves wa.me link."""
        settings = {
            "whatsapp_provider": "meta",
            "whatsapp_api_token": "BAD_TOKEN",
            "whatsapp_phone_number_id": "12345"
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock(status_code=401, text="Unauthorized token")
            mock_post.return_value = mock_resp

            res = asyncio.run(self.dispatcher.send_message("+40721123456", "Explicit meta test", settings=settings))

            self.assertFalse(res.get("ok"))
            self.assertEqual(res.get("provider"), "meta")
            self.assertTrue(res.get("wa_me_url").startswith("https://wa.me/40721123456"))


if __name__ == "__main__":
    unittest.main()

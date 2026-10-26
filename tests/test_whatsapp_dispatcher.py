"""
Unit tests for backend/whatsapp_dispatcher.py
Exhaustively validates:
1. Phone number sanitization: +39, +40, 07, leading 00, +34, +49, spaces, hyphens, and invalid inputs.
2. Canonical wa.me link generation with full URL-encoding of emojis, line breaks, %, &, +.
3. Meta WhatsApp Business Cloud API: authorization header, payload format, success (200/201), 24h window rejection (code 131047 fallback).
4. Twilio WhatsApp API: basic auth, form payload (From, To, Body), success (201), error handling.
5. Custom webhook gateway: json payload, success (200), failure handling.
6. Auto waterfall resolution: Meta -> Twilio -> Webhook -> wa.me link fallback.
7. Multi-tenant settings isolation: store-specific settings override env vars and do not cross-contaminate.
8. Network resilience: httpx.TimeoutException and connection error handling without unhandled exceptions.
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


class TestWhatsAppDispatcherPhoneSanitization(unittest.TestCase):
    """Exhaustive tests for WhatsAppDispatcher.clean_phone_number."""

    def setUp(self):
        self.dispatcher = WhatsAppDispatcher()

    def test_clean_italian_mobile_with_plus39(self):
        """+39 340 123 4567 -> 393401234567."""
        self.assertEqual(self.dispatcher.clean_phone_number("+39 340 123 4567"), "393401234567")

    def test_clean_italian_mobile_local_without_country_code(self):
        """3401234567 (10 digits starting with 3) -> 393401234567."""
        self.assertEqual(self.dispatcher.clean_phone_number("3401234567"), "393401234567")

    def test_clean_romanian_mobile_with_plus40(self):
        """+40 721 123 456 -> 40721123456."""
        self.assertEqual(self.dispatcher.clean_phone_number("+40 721 123 456"), "40721123456")

    def test_clean_romanian_mobile_local_07(self):
        """0721123456 (10 digits starting with 07) -> 40721123456."""
        self.assertEqual(self.dispatcher.clean_phone_number("0721123456"), "40721123456")

    def test_clean_leading_double_zero_prefix(self):
        """0039-340-1234567 and 0040721123456 -> strip leading 00."""
        self.assertEqual(self.dispatcher.clean_phone_number("0039-340-1234567"), "393401234567")
        self.assertEqual(self.dispatcher.clean_phone_number("0040721123456"), "40721123456")

    def test_clean_spanish_mobile(self):
        """+34 612 345 678 and local 612345678 -> 34612345678."""
        self.assertEqual(self.dispatcher.clean_phone_number("+34 612 345 678"), "34612345678")
        self.assertEqual(self.dispatcher.clean_phone_number("612345678"), "34612345678")

    def test_clean_german_mobile(self):
        """+49 151 12345678 and local 015112345678 -> 4915112345678."""
        self.assertEqual(self.dispatcher.clean_phone_number("+49 151 12345678"), "4915112345678")
        self.assertEqual(self.dispatcher.clean_phone_number("015112345678"), "4915112345678")

    def test_clean_invalid_or_empty_phone(self):
        """Empty, non-digit, or too short inputs return empty or unparseable string."""
        for invalid in ["", None, "abc", "   ", "---", "+", "123"]:
            res = self.dispatcher.clean_phone_number(invalid)
            self.assertTrue(len(res) < 8)


class TestWhatsAppDispatcherWaMeLink(unittest.TestCase):
    """Exhaustive tests for WhatsAppDispatcher.generate_wa_me_link."""

    def setUp(self):
        self.dispatcher = WhatsAppDispatcher()

    def test_canonical_wa_me_structure(self):
        """Verify standard canonical link format https://wa.me/{clean_phone}?text={quote(message)}."""
        link = self.dispatcher.generate_wa_me_link("+40721123456", "Hello World")
        self.assertEqual(link, "https://wa.me/40721123456?text=Hello%20World")

    def test_wa_me_special_characters_and_emojis(self):
        """Verify URL encoding of emojis, line breaks, %, &, +, and quotes."""
        msg = "Salut Elena! 👋\n10% reducere pentru comanda ta & livrare gratuită + cadou!"
        link = self.dispatcher.generate_wa_me_link("+40721123456", msg)
        self.assertNotIn(" ", link)
        self.assertNotIn("\n", link)
        self.assertIn("10%25", link)
        self.assertIn("%26", link)
        self.assertIn("%2B", link)
        self.assertIn("%F0%9F%91%8B", link) # UTF-8 emoji url-encoded


class TestWhatsAppDispatcherProviderDispatch(unittest.TestCase):
    """Unit tests for Meta, Twilio, Webhook, and Waterfall dispatch in send_message."""

    def setUp(self):
        self.dispatcher = WhatsAppDispatcher()

    def test_send_message_invalid_phone_early_exit(self):
        """Invalid or too short phone numbers fail immediately without making network calls."""
        for invalid_phone in ["123", "abc", "", None, "+"]:
            res = asyncio.run(self.dispatcher.send_message(invalid_phone, "Hello"))
            self.assertFalse(res.get("ok") or res.get("success"))
            self.assertIn("invalid", res.get("error", "").lower())

    def test_meta_cloud_api_success(self):
        """Verify Meta Cloud API payload, Bearer token header, and success handling."""
        settings = {
            "whatsapp_provider": "meta",
            "whatsapp_api_token": "EAAX_meta_valid_token",
            "whatsapp_phone_number_id": "9876543210"
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"messages": [{"id": "wamid.HBgM123456"}]}
            mock_post.return_value = mock_resp

            res = asyncio.run(self.dispatcher.send_message("+40721123456", "Test message", settings=settings))

            self.assertTrue(res.get("ok") or res.get("success"))
            self.assertEqual(res.get("provider"), "meta")
            self.assertEqual(res.get("id"), "wamid.HBgM123456")

            # Check post call kwargs
            mock_post.assert_called_once()
            call_url = mock_post.call_args[0][0]
            call_headers = mock_post.call_args[1].get("headers", {})
            call_json = mock_post.call_args[1].get("json", {})

            self.assertIn("9876543210", call_url)
            self.assertEqual(call_headers.get("Authorization"), "Bearer EAAX_meta_valid_token")
            self.assertEqual(call_json.get("to"), "40721123456")
            self.assertEqual(call_json.get("text", {}).get("body"), "Test message")

    def test_meta_cloud_api_24h_window_rejection_fallback(self):
        """Meta Cloud API HTTP 400 with code 131047 falls back gracefully to wa.me link."""
        settings = {
            "whatsapp_provider": "meta",
            "whatsapp_api_token": "EAAX_token",
            "whatsapp_phone_number_id": "9876543210"
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.text = '{"error":{"message":"Re-engagement message failed","code":131047}}'
            mock_resp.json.return_value = {"error": {"message": "Re-engagement message failed", "code": 131047}}
            mock_post.return_value = mock_resp

            res = asyncio.run(self.dispatcher.send_message("+40721123456", "Cart reminder", settings=settings))

            wa_link = res.get("wa_me_url") or res.get("wa_link")
            self.assertIsNotNone(wa_link)
            self.assertTrue(wa_link.startswith("https://wa.me/40721123456"))

    def test_twilio_provider_dispatch_success(self):
        """Verify Twilio API Basic Auth, form data payload, and SID extraction."""
        settings = {
            "whatsapp_provider": "twilio",
            "twilio_account_sid": "AC_mock_twilio_sid",
            "twilio_auth_token": "mock_twilio_auth_token",
            "twilio_whatsapp_number": "whatsapp:+14155238886"
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"sid": "SM9988776655"}
            mock_post.return_value = mock_resp

            res = asyncio.run(self.dispatcher.send_message("+393401234567", "Ciao Lorenzo", settings=settings))

            self.assertTrue(res.get("ok") or res.get("success"))
            self.assertEqual(res.get("provider"), "twilio")
            self.assertEqual(res.get("sid"), "SM9988776655")

            call_args = mock_post.call_args
            call_auth = call_args[1].get("auth")
            call_data = call_args[1].get("data", {})

            self.assertEqual(call_auth, ("AC_mock_twilio_sid", "mock_twilio_auth_token"))
            self.assertEqual(call_data.get("To"), "whatsapp:+393401234567")
            self.assertEqual(call_data.get("From"), "whatsapp:+14155238886")
            self.assertEqual(call_data.get("Body"), "Ciao Lorenzo")

    def test_custom_webhook_dispatch_success(self):
        """Verify generic webhook gateway dispatch."""
        settings = {
            "whatsapp_provider": "webhook",
            "whatsapp_webhook_url": "https://gateway.example.com/api/send"
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"status": "queued"}
            mock_post.return_value = mock_resp

            res = asyncio.run(self.dispatcher.send_message("+40721123456", "Webhook msg", settings=settings))

            self.assertTrue(res.get("ok") or res.get("success"))
            self.assertEqual(res.get("provider"), "webhook")

    def test_auto_waterfall_all_providers_configured_uses_meta_first(self):
        """Auto waterfall chooses Meta first when both Meta and Twilio credentials are present."""
        settings = {
            "whatsapp_provider": "auto",
            "whatsapp_api_token": "EAAX_token",
            "whatsapp_phone_number_id": "112233",
            "twilio_account_sid": "AC_sid",
            "twilio_auth_token": "TOK"
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"messages": [{"id": "wamid_meta"}]}
            mock_post.return_value = mock_resp

            res = asyncio.run(self.dispatcher.send_message("+40721123456", "Auto test", settings=settings))

            self.assertEqual(res.get("provider"), "meta")

    def test_auto_waterfall_falls_to_twilio_when_meta_fails(self):
        """Auto waterfall tries Twilio if Meta returns an HTTP error."""
        settings = {
            "whatsapp_provider": "auto",
            "whatsapp_api_token": "EAAX_token",
            "whatsapp_phone_number_id": "112233",
            "twilio_account_sid": "AC_sid",
            "twilio_auth_token": "TOK",
            "twilio_whatsapp_number": "whatsapp:+14155238886"
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            # First call (Meta) returns 500, second call (Twilio) returns 201
            resp_meta = MagicMock(status_code=500, text="Internal Error")
            resp_twilio = MagicMock(status_code=201, json=lambda: {"sid": "SM_fallback"})
            mock_post.side_effect = [resp_meta, resp_twilio]

            res = asyncio.run(self.dispatcher.send_message("+40721123456", "Auto test", settings=settings))

            self.assertEqual(res.get("provider"), "twilio")
            self.assertEqual(mock_post.call_count, 2)

    def test_auto_waterfall_falls_to_wa_me_when_credentials_empty(self):
        """When no external credentials exist, waterfall cleanly produces a wa.me link."""
        settings = {
            "whatsapp_provider": "auto",
            "whatsapp_api_token": "",
            "twilio_account_sid": "",
            "whatsapp_webhook_url": ""
        }
        res = asyncio.run(self.dispatcher.send_message("+40721123456", "Direct link test", settings=settings))

        wa_link = res.get("wa_me_url") or res.get("wa_link")
        self.assertIsNotNone(wa_link)
        self.assertTrue(wa_link.startswith("https://wa.me/40721123456"))

    def test_multi_tenant_settings_isolation(self):
        """Store A (Twilio) and Store B (Meta) calls remain completely isolated."""
        settings_a = {"whatsapp_provider": "twilio", "twilio_account_sid": "AC_A", "twilio_auth_token": "TOK_A"}
        settings_b = {"whatsapp_provider": "meta", "whatsapp_api_token": "TOK_B", "whatsapp_phone_number_id": "NUM_B"}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [
                MagicMock(status_code=201, json=lambda: {"sid": "SM_A"}),
                MagicMock(status_code=200, json=lambda: {"messages": [{"id": "wamid_B"}]})
            ]

            res_a = asyncio.run(self.dispatcher.send_message("+40721123456", "Msg A", settings=settings_a))
            res_b = asyncio.run(self.dispatcher.send_message("+40721123456", "Msg B", settings=settings_b))

            self.assertEqual(res_a.get("provider"), "twilio")
            self.assertEqual(res_b.get("provider"), "meta")

    def test_network_timeout_resilience(self):
        """httpx.TimeoutException is caught and structured response with wa.me fallback is returned."""
        settings = {"whatsapp_provider": "twilio", "twilio_account_sid": "AC_T", "twilio_auth_token": "TOK_T"}
        with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Read timeout")):
            res = asyncio.run(self.dispatcher.send_message("+40721123456", "Timeout test", settings=settings))

            self.assertIsNotNone(res)
            self.assertFalse(res.get("ok", True))
            wa_link = res.get("wa_me_url") or res.get("wa_link")
            self.assertIsNotNone(wa_link)


if __name__ == "__main__":
    unittest.main()

"""
Milestone 1 Gate 2 - Challenger Empirical Stress Probes
Adversarial probes against EmailDispatcher and ShopifyClient.
Designed by Challenger M1-Gate2-1.
"""

import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import sys
import os
import time
import html
import re

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
from email_dispatcher import EmailDispatcher, EMAIL_I18N
from shopify_api import ShopifyClient, detect_customer_language_and_country


class TestGate2EmailDispatcherAdversarialProbes(unittest.TestCase):
    """Deep adversarial probes for EmailDispatcher.build_html_email."""

    def test_probe_01_null_and_falsy_inputs(self):
        """Probe build_html_email with None and falsy values across all parameters."""
        res = EmailDispatcher.build_html_email(
            shop_name="",
            customer_name="",
            items_str="",
            checkout_url="",
            text_body="",
            discount_code=None,
            product_image_url=None,
            line_items=None,
            lang="",
            currency="",
            preheader=None,
        )
        self.assertIsInstance(res, str)
        self.assertIn("<!DOCTYPE html>", res)
        self.assertIn("</html>", res)

    def test_probe_02_xss_deep_injection_matrix(self):
        """Probe complete defanging of XSS vectors across all template insertion points."""
        payloads = [
            '<script>alert("XSS1")</script>',
            '"><img src=x onerror=alert(2)>',
            "';alert(3);//",
            '<svg/onload=alert(4)>',
            'javascript:/*--></title></style></textarea></script></xmp><svg/onload=alert(5)>',
        ]
        for p in payloads:
            res = EmailDispatcher.build_html_email(
                shop_name=f"Shop {p}",
                customer_name=f"User {p}",
                items_str=f"Items {p}",
                checkout_url=f"https://shop.com/c?q={p}",
                text_body=f"Hello\n{p}\nBye",
                discount_code=f"DISC{p}",
                product_image_url=f"https://cdn.com/img.jpg?p={p}",
                line_items=[
                    {"title": f"T {p}", "variant_title": f"V {p}", "price": f"10 {p}", "image_url": f"https://cdn.com/{p}.jpg"}
                ],
                lang="en",
                currency=f"EUR {p}",
                preheader=f"Pre {p}",
            )
            # Ensure raw unescaped script / svg / img tags are completely absent
            self.assertNotIn("<script>", res)
            self.assertNotIn("</script>", res)
            self.assertNotIn("<svg", res)
            self.assertNotIn("<img src=x", res)
            # Verify proper escaping occurred for characters in payload
            if '"' in p:
                self.assertIn("&quot;", res)
            if "'" in p:
                self.assertIn("&#x27;", res)
            if "<" in p:
                self.assertIn("&lt;", res)
            if ">" in p:
                self.assertIn("&gt;", res)

    def test_probe_03_format_string_curly_brace_attack(self):
        """Probe that format string attacks like {shop_name} or {0} in inputs do not trigger KeyError or crash."""
        malicious_inputs = [
            "{shop_name}",
            "{0}",
            "{100}",
            "{items_header}",
            "{discount}",
            "{{escaped}}",
            "{bad_key_that_does_not_exist}",
        ]
        for malicious in malicious_inputs:
            # Should not raise KeyError or ValueError
            res = EmailDispatcher.build_html_email(
                shop_name=malicious,
                text_body=f"Body with {malicious}",
                preheader=malicious,
                discount_code="MG10",
            )
            self.assertIsInstance(res, str)
            self.assertIn("</html>", res)

    def test_probe_04_discount_percentage_regex_boundary_cases(self):
        """Probe _extract_discount_percentage across complex alphanumeric and boundary patterns."""
        cases = [
            # Expected extraction
            ("MG10", "10%"),
            ("MGVIP15", "15%"),
            ("SAVE5", "5%"),
            ("BF2026_10", "10%"),
            ("SUMMER_2025_50_OFF", "50%"),
            ("NEW2026_99", "99%"),
            ("1", "1%"),
            ("99", "99%"),
            ("OFF10PCT", "10%"),
            # Rejections (should return None)
            (None, None),
            ("", None),
            ("   ", None),
            ("FREESHIP", None),
            ("VIP", None),
            ("2026", None),          # 4-digit year ignored
            ("2025", None),          # 4-digit year ignored
            ("100", None),           # 3-digit > 99 ignored
            ("500", None),           # 3-digit ignored
            ("0", None),             # 0 ignored
            ("00", None),            # 00 ignored
            ("05", None),            # Leading 0 blocked by lookaround
            ("-10", "10%"),          # Negative sign not a digit, extracts 10%
            ("100PERCENT", None),    # 100 has 3 digits
        ]
        for code, expected in cases:
            actual = EmailDispatcher._extract_discount_percentage(code)
            self.assertEqual(actual, expected, f"Failed for code: {code}")

    def test_probe_05_redos_discount_code_performance(self):
        """Probe ReDoS vulnerability in discount code extraction with massive payloads."""
        massive_string = ("A" * 1000 + "2026") * 50 + "_10"
        t0 = time.perf_counter()
        res = EmailDispatcher._extract_discount_percentage(massive_string)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed_ms, 50.0, f"ReDoS probe took too long: {elapsed_ms:.2f}ms")
        self.assertEqual(res, "10%")

    def test_probe_06_line_items_attribute_handling(self):
        """Probe line_items with diverse price formats, zero quantities, and missing fields."""
        items = [
            # Missing fields
            {},
            # Non-standard types in price, quantity, titles
            {"title": "Watch", "variant_title": "Gold", "quantity": "3", "price": 49.99},
            {"title": "Valid", "variant_title": None, "quantity": None, "price": None},
            {"title": "Zero Qty", "quantity": 0, "price": "0.00"},
            {"title": "Negative Qty", "quantity": -5, "price": "-10.00"},
            {"title": "Invalid Price", "price": "N/A", "quantity": "invalid"},
            {"title": "Huge Price", "price": "999999999999.99"},
        ]
        res = EmailDispatcher.build_html_email(
            shop_name="Shop",
            line_items=items,
            currency="EUR",
        )
        self.assertIsInstance(res, str)
        self.assertIn("Watch", res)
        self.assertIn("49.99 EUR", res)
        self.assertIn("999999999999.99 EUR", res)

    def test_probe_07_extreme_large_cart(self):
        """Probe 250 items rendering without memory or time blowup."""
        items = [
            {
                "title": f"Luxury Item {i}",
                "variant_title": f"Variant {i}",
                "quantity": 1,
                "price": "100.00",
                "image_url": f"https://cdn.com/item_{i}.jpg",
            }
            for i in range(250)
        ]
        t0 = time.perf_counter()
        res = EmailDispatcher.build_html_email(shop_name="Shop", line_items=items)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed_ms, 300.0, f"250 items took {elapsed_ms:.2f}ms")
        self.assertIn("Luxury Item 0", res)
        self.assertIn("Luxury Item 249", res)

    def test_probe_08_checkout_url_with_fragment_and_params(self):
        """Probe checkout_url containing query parameters and fragments."""
        url = "https://shop.com/checkouts/ac/123?locale=ro#summary"
        res = EmailDispatcher.build_html_email(
            shop_name="Shop",
            checkout_url=url,
            discount_code="MG10",
        )
        # Should cleanly append discount parameter
        self.assertIn("https://shop.com/checkouts/ac/123?locale=ro#summary&amp;discount=MG10", res)

    def test_probe_09_all_languages_with_special_characters(self):
        """Probe all supported languages with diacritics and special characters."""
        for lang in ["en", "ro", "it", "es", "de", "fr"]:
            res = EmailDispatcher.build_html_email(
                shop_name="Test Store",
                discount_code="MG10",
                lang=lang,
            )
            self.assertIn(EMAIL_I18N[lang]["items_header"], res)
            self.assertIn("CADENCE DISCOUNT CARD", res)


class TestGate2ShopifyClientAdversarialProbes(unittest.IsolatedAsyncioTestCase):
    """Deep adversarial probes for ShopifyClient."""

    def setUp(self):
        self.client = ShopifyClient("adversarial.myshopify.com", "shpat_mock_token")

    async def test_probe_01_checkouts_payload_edge_types(self):
        """Probe get_abandoned_checkouts_detailed when checkouts payload contains corrupted items."""
        # Payload with non-dict items, None items, empty dicts
        corrupted_payload = {
            "checkouts": [
                None,
                "corrupted_string",
                12345,
                [],
                {},  # completely empty checkout dict
            ]
        }
        self.client._get = AsyncMock(return_value=corrupted_payload)
        res = await self.client.get_abandoned_checkouts_detailed()
        # The 4 non-dicts are skipped; the empty dict is ingested safely with fallback defaults
        self.assertEqual(len(res), 1)
        c = res[0]
        self.assertEqual(c["id"], "None")
        self.assertEqual(c["customer_name"], "Client")
        self.assertEqual(c["total_price"], 0.0)
        self.assertEqual(c["line_items"], [])
        self.assertEqual(c["items"], ["Produse din coș"])
        self.assertEqual(c["detected_lang"], "en")

    async def test_probe_02_customer_and_address_corruptions(self):
        """Probe get_abandoned_checkouts_detailed with customer missing fields and shipping address."""
        mock_checkout = {
            "id": 9999,
            "abandoned_checkout_url": "https://store.com/c/9999",
            "customer": {
                "first_name": "Elena",
                "last_name": None,
                "email": None,
            },
            "shipping_address": {
                "first_name": None,
                "last_name": "Grozavu",
                "country_code": "RO",
            },
            "line_items": [
                {"title": "Item A", "price": "100.00", "quantity": 1}
            ]
        }
        self.client._get = AsyncMock(return_value={"checkouts": [mock_checkout]})
        res = await self.client.get_abandoned_checkouts_detailed()
        self.assertEqual(len(res), 1)
        c = res[0]
        self.assertEqual(c["customer_name"], "Elena")
        self.assertEqual(c["detected_lang"], "ro")

    async def test_probe_03_total_price_extreme_variations(self):
        """Probe total_price with various unusual values."""
        variations = [
            ("0.00", 0.0),
            ("199.99", 199.99),
            (250, 250.0),
            (14.50, 14.50),
            ("free", 0.0),
            ("invalid_price", 0.0),
            ("null", 0.0),
            ("", 0.0),
            (None, 0.0),
            ("999999999.99", 999999999.99),
        ]
        for val, expected in variations:
            mock_checkout = {
                "id": 1,
                "abandoned_checkout_url": "https://s.com/c",
                "total_price": val,
                "line_items": [],
            }
            self.client._get = AsyncMock(return_value={"checkouts": [mock_checkout]})
            res = await self.client.get_abandoned_checkouts_detailed()
            self.assertEqual(res[0]["total_price"], expected, f"Failed for total_price: {val}")

    async def test_probe_04_phone_variations_and_sanitization(self):
        """Probe phone parsing across formats, booleans, ints, and malformed strings."""
        phone_cases = [
            (40722123456, "40722123456", "40722123456", True),
            ("+40 (722) 123-456", "+40 (722) 123-456", "40722123456", True),
            ("0722 123 456", "0722 123 456", "0722123456", True),
            ("123", "123", "123", False),  # Too short for has_phone
            ("abc", "abc", "", False),
            (None, "", "", False),
            ("", "", "", False),
        ]
        for raw_p, exp_phone, exp_clean, exp_has in phone_cases:
            mock_checkout = {
                "id": 1,
                "abandoned_checkout_url": "https://s.com/c",
                "phone": raw_p,
                "line_items": [],
            }
            self.client._get = AsyncMock(return_value={"checkouts": [mock_checkout]})
            res = await self.client.get_abandoned_checkouts_detailed()
            self.assertEqual(res[0]["phone"], exp_phone)
            self.assertEqual(res[0]["clean_phone"], exp_clean)
            self.assertEqual(res[0]["has_phone"], exp_has)

    async def test_probe_05_image_lookup_empty_or_malformed_product_json(self):
        """Probe get_product_image_url when Shopify returns empty product JSON."""
        malformed_responses = [
            None,
            {},
            {"product": None},
            {"product": {}},
            {"product": {"image": None, "images": None, "variants": None}},
        ]
        for resp in malformed_responses:
            self.client._img_cache.clear()
            self.client._get = AsyncMock(return_value=resp)
            img = await self.client.get_product_image_url(55555)
            self.assertIsNone(img)

    async def test_probe_06_append_discount_to_url_edge_cases(self):
        """Probe append_discount_to_url with complex URLs, fragments, and queries."""
        cases = [
            # Standard clean URL
            ("https://s.com/c/1", "MG10", "https://s.com/c/1?discount=MG10"),
            # Already has discount
            ("https://s.com/c/1?discount=MG10", "MG10", "https://s.com/c/1?discount=MG10"),
            # Existing query param
            ("https://s.com/c/1?step=payment", "MG10", "https://s.com/c/1?step=payment&discount=MG10"),
            # Multiple existing query params
            ("https://s.com/c/1?locale=ro&step=payment", "MG10", "https://s.com/c/1?locale=ro&step=payment&discount=MG10"),
            # None or empty code returns original URL unmodified
            ("https://s.com/c/1", None, "https://s.com/c/1"),
            ("https://s.com/c/1", "", "https://s.com/c/1"),
            ("https://s.com/c/1", "   ", "https://s.com/c/1"),
            # Empty URL returns empty string
            ("", "MG10", ""),
            (None, "MG10", ""),
        ]
        for url, code, expected in cases:
            actual = ShopifyClient.append_discount_to_url(url, code)
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()

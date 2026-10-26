"""
Empirical Stress Test Suite & Adversarial Challenge Harness
Milestone 1: Core Checkout Recovery & Visual Email Engine

Components Tested:
1. EmailDispatcher.build_html_email (backend/email_dispatcher.py)
2. ShopifyClient.get_abandoned_checkouts_detailed (backend/shopify_api.py)
3. ShopifyClient.get_product_image_url (backend/shopify_api.py)
4. ShopifyClient.append_discount_to_url (backend/shopify_api.py)
5. detect_customer_language_and_country (backend/shopify_api.py)

Evaluated Scenarios:
- Empty items, None inputs, missing attributes
- 100 items cart stress & rendering latency
- Broken, invalid, non-HTTP, relative, and javascript: image URLs
- Full Unicode, RTL (Arabic), CJK (Japanese/Chinese), Cyrillic, Greek, accented Latin, and Emojis
- XSS injection in titles, variants, discount codes, shop names, prices, and currencies
- All 6 supported languages (en, ro, it, es, de, fr) + regional tags + fallback
- Discount code permutations (None, empty, whitespace, MG10, MGVIP15, no digits, year prefix)
- Network errors, 500s, 404s, and caching deduplication
- Zero unhandled exceptions requirement
- Luxury responsive email template compliance
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


class TestEmailDispatcherStress(unittest.TestCase):
    """Adversarial stress testing for EmailDispatcher.build_html_email."""

    def test_empty_and_none_line_items(self):
        """Verify build_html_email succeeds when line_items is empty list or None."""
        html_empty = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu",
            line_items=[],
            checkout_url="https://maisongrozavu.com/checkout",
            discount_code=None,
            lang="en"
        )
        self.assertIsInstance(html_empty, str)
        self.assertIn("Complete Your Order →", html_empty)
        self.assertNotIn("CADENCE DISCOUNT CARD", html_empty)

        html_none = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu",
            line_items=None,
            checkout_url="https://maisongrozavu.com/checkout",
            discount_code=None,
            lang="ro"
        )
        self.assertIsInstance(html_none, str)
        self.assertIn("Finalizează Comanda Acum →", html_none)

    def test_100_items_stress_and_performance(self):
        """Stress test: 100 items render completely with latency under 150ms."""
        items = [
            {
                "title": f"Luxury Item {i+1:03d}",
                "variant_title": f"Variant {i+1}" if i % 2 == 0 else "Default Title",
                "quantity": (i % 4) + 1,
                "price": f"{(i+1)*12.50:.2f}",
                "image_url": f"https://cdn.shopify.com/item_{i+1}.jpg" if i % 3 != 0 else None
            }
            for i in range(100)
        ]

        t0 = time.perf_counter()
        res = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu",
            line_items=items,
            checkout_url="https://maisongrozavu.com/checkout",
            discount_code="MG10",
            lang="en",
            currency="EUR"
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        self.assertLess(elapsed_ms, 150.0, f"Rendering 100 items took {elapsed_ms:.2f}ms")
        self.assertIn("Luxury Item 001", res)
        self.assertIn("Luxury Item 100", res)
        self.assertNotIn("Default Title", res)
        self.assertIn("Variant 2", res)
        self.assertIn("🛍️", res)  # Fallback for missing images
        self.assertIn("</html>", res)

    def test_missing_and_corrupted_images(self):
        """Verify non-HTTP, javascript, ftp, relative, None, and empty image URLs fallback to 🛍️."""
        items = [
            {"title": "Item None", "image_url": None},
            {"title": "Item Empty", "image_url": ""},
            {"title": "Item Relative", "image_url": "/cdn/img.jpg"},
            {"title": "Item JS URI", "image_url": "javascript:alert(1)"},
            {"title": "Item FTP", "image_url": "ftp://cdn.com/file.jpg"},
            {"title": "Item Valid", "image_url": "https://cdn.shopify.com/valid.jpg"},
        ]
        res = EmailDispatcher.build_html_email(shop_name="Shop", line_items=items)
        self.assertEqual(res.count("🛍️"), 5)
        self.assertIn("https://cdn.shopify.com/valid.jpg", res)
        self.assertNotIn("javascript:alert(1)", res)

    def test_multilingual_unicode_rtl_and_emojis(self):
        """Verify unicode handling across Romanian, German, French, Italian, Spanish, Arabic RTL, CJK, and Emojis."""
        items = [
            {"title": "Mănuși din Piele 🧤", "variant_title": "Cărbune / L", "price": "120.00"},
            {"title": "Gürtel aus Kalbsleder 🐂", "variant_title": "Schwarz / 95cm", "price": "95.00"},
            {"title": "Veste en Soie Pure ✨", "variant_title": "Bleu Nuit / 48", "price": "340.00"},
            {"title": "Camicia di Lino Pregiato 👔", "variant_title": "Bianco / 42", "price": "180.00"},
            {"title": "Zapatos de Cuero Hechos a Mano 👞", "variant_title": "Marrón / 44", "price": "290.00"},
            {"title": "高級シルク着物 👘", "variant_title": "黒 / M", "price": "550.00"},
            {"title": "قميص قطني فاخر 💎", "variant_title": "أبيض / XL", "price": "160.00"},
        ]
        res = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu 👑",
            line_items=items,
            checkout_url="https://maisongrozavu.com/checkout?ref=șțîâ",
            discount_code="MG10",
            lang="ro",
            currency="EUR"
        )
        self.assertIn("Mănuși din Piele 🧤", res)
        self.assertIn("Gürtel aus Kalbsleder 🐂", res)
        self.assertIn("Veste en Soie Pure ✨", res)
        self.assertIn("高級シルク着物 👘", res)
        self.assertIn("قميص قطني فاخر 💎", res)
        self.assertIn("Maison Grozavu 👑", res)

    def test_xss_sanitization_in_product_titles_and_variants(self):
        """Verify that XSS in product title and variant title is properly HTML-escaped."""
        items = [
            {
                "title": "<script>alert('xss_title')</script>Silk Dress",
                "variant_title": "<img src=x onerror=alert('xss_var')>Red",
                "price": "200.00",
                "image_url": "https://cdn.shopify.com/img.jpg?a=\" onmouseover=\"alert('xss_img')"
            }
        ]
        res = EmailDispatcher.build_html_email(shop_name="Safe Shop", line_items=items)
        self.assertNotIn("<script>alert('xss_title')</script>", res)
        self.assertIn("&lt;script&gt;alert(&#x27;xss_title&#x27;)&lt;/script&gt;", res)
        self.assertNotIn("<img src=x onerror=alert('xss_var')>", res)
        self.assertIn("&lt;img src=x onerror=alert(&#x27;xss_var&#x27;)&gt;", res)
        self.assertNotIn('a=" onmouseover="', res)

    def test_xss_in_discount_code_check(self):
        """Empirical vulnerability test: check if discount_code escapes malicious HTML."""
        malicious_code = "<script>alert('xss_discount')</script>"
        res = EmailDispatcher.build_html_email(
            shop_name="Shop",
            checkout_url="https://shop.com/checkout",
            discount_code=malicious_code
        )
        self.assertNotIn(malicious_code, res)
        self.assertIn("&lt;script&gt;alert(&#x27;xss_discount&#x27;)&lt;/script&gt;", res)
        self.assertIsInstance(res, str)

    def test_xss_in_shop_name_check(self):
        """Empirical vulnerability test: check if shop_name escapes malicious HTML."""
        malicious_shop = "<script>alert('xss_shop')</script>"
        res = EmailDispatcher.build_html_email(
            shop_name=malicious_shop,
            checkout_url="https://shop.com/checkout"
        )
        self.assertNotIn(malicious_shop, res)
        self.assertIn("&lt;script&gt;alert(&#x27;xss_shop&#x27;)&lt;/script&gt;", res)
        self.assertIsInstance(res, str)

    def test_xss_in_non_numeric_price_check(self):
        """Empirical vulnerability test: check if non-numeric price string with XSS escapes malicious HTML."""
        malicious_price = "<script>alert('xss_price')</script>"
        items = [{"title": "Art", "price": malicious_price}]
        res = EmailDispatcher.build_html_email(shop_name="Shop", line_items=items)
        self.assertNotIn(malicious_price, res)
        self.assertIn("&lt;script&gt;alert(&#x27;xss_price&#x27;)&lt;/script&gt;", res)
        self.assertIsInstance(res, str)

    def test_all_six_supported_languages(self):
        """Verify complete localization across EN, RO, IT, ES, DE, FR for both neutral and discount stages."""
        locales = {
            "en": ("YOUR RESERVED SELECTION", "Complete Your Order →", "Complete Order with 10% Off →"),
            "ro": ("PRODUSELE TALE REZERVATE", "Finalizează Comanda Acum →", "Finalizează Comanda cu 10% Reducere →"),
            "it": ("I TUOI ARTICOLI RISERVATI", "Completa il Tuo Ordine →", "Completa l'Ordine con lo Sconto 10% →"),
            "es": ("TUS ARTÍCULOS RESERVADOS", "Finalizar Mi Pedido →", "Finalizar Pedido con 10% de Descuento →"),
            "de": ("DEINE RESERVIERTE AUSWAHL", "Bestellung jetzt abschließen →", "Bestellung mit 10% Rabatt abschließen →"),
            "fr": ("VOTRE SÉLECTION RÉSERVÉE", "Finaliser ma Commande →", "Finaliser ma Commande avec 10% de Réduction →"),
        }
        for lang, (hdr, neutral_cta, disc_cta) in locales.items():
            # Neutral stage (Stage 1)
            h_neutral = EmailDispatcher.build_html_email(shop_name="Shop", discount_code=None, lang=lang)
            self.assertIn(hdr, h_neutral, f"Failed header for {lang}")
            self.assertIn(neutral_cta, h_neutral, f"Failed neutral CTA for {lang}")
            self.assertNotIn("CADENCE DISCOUNT CARD", h_neutral)

            # Discount stage (Stage 2)
            h_disc = EmailDispatcher.build_html_email(shop_name="Shop", discount_code="MG10", lang=lang)
            self.assertIn("CADENCE DISCOUNT CARD", h_disc)
            self.assertIn(disc_cta, h_disc, f"Failed discount CTA for {lang}")

    def test_language_normalization_and_unsupported_locales(self):
        """Verify normalization of regional tags and safe fallback on unsupported languages."""
        # Regional normalization
        self.assertIn("PRODUSELE TALE REZERVATE", EmailDispatcher.build_html_email(shop_name="S", lang="RO_md"))
        self.assertIn("DEINE RESERVIERTE AUSWAHL", EmailDispatcher.build_html_email(shop_name="S", lang="de-CH"))
        self.assertIn("TUS ARTÍCULOS RESERVADOS", EmailDispatcher.build_html_email(shop_name="S", lang="es-AR"))
        self.assertIn("VOTRE SÉLECTION RÉSERVÉE", EmailDispatcher.build_html_email(shop_name="S", lang="fr-BE"))
        self.assertIn("I TUOI ARTICOLI RISERVATI", EmailDispatcher.build_html_email(shop_name="S", lang="it_IT"))
        # Fallback to English
        self.assertIn("YOUR RESERVED SELECTION", EmailDispatcher.build_html_email(shop_name="S", lang="ja"))
        self.assertIn("YOUR RESERVED SELECTION", EmailDispatcher.build_html_email(shop_name="S", lang="ar"))
        self.assertIn("YOUR RESERVED SELECTION", EmailDispatcher.build_html_email(shop_name="S", lang="unsupported_xyz"))

    def test_discount_code_permutations(self):
        """Verify discount permutations: None, empty, whitespace, MG10, MGVIP15, and non-numeric code."""
        # 1. None
        h1 = EmailDispatcher.build_html_email(shop_name="S", checkout_url="https://s.com/c1", discount_code=None)
        self.assertNotIn("CADENCE DISCOUNT CARD", h1)
        self.assertNotIn("discount=", h1)

        # 2. Empty string
        h2 = EmailDispatcher.build_html_email(shop_name="S", checkout_url="https://s.com/c1", discount_code="")
        self.assertNotIn("CADENCE DISCOUNT CARD", h2)
        self.assertNotIn("discount=", h2)

        # 3. Whitespace
        h3 = EmailDispatcher.build_html_email(shop_name="S", checkout_url="https://s.com/c1", discount_code="   ")
        self.assertNotIn("CADENCE DISCOUNT CARD", h3)
        self.assertNotIn("discount=", h3)

        # 4. Standard MG10
        h4 = EmailDispatcher.build_html_email(shop_name="S", checkout_url="https://s.com/c1", discount_code="MG10", lang="en")
        self.assertIn("CADENCE DISCOUNT CARD", h4)
        self.assertIn("MG10", h4)
        self.assertIn("10% OFF", h4)
        self.assertIn("https://s.com/c1?discount=MG10", h4)

        # 5. VIP MGVIP15
        h5 = EmailDispatcher.build_html_email(shop_name="S", checkout_url="https://s.com/c1", discount_code="MGVIP15", lang="en")
        self.assertIn("CADENCE DISCOUNT CARD", h5)
        self.assertIn("MGVIP15", h5)
        self.assertIn("15% OFF", h5)
        self.assertIn("https://s.com/c1?discount=MGVIP15", h5)

        # 6. Alphanumeric without digits: FREESHIP
        h6 = EmailDispatcher.build_html_email(shop_name="S", checkout_url="https://s.com/c1", discount_code="FREESHIP", lang="en")
        self.assertIn("CADENCE DISCOUNT CARD", h6)
        self.assertIn("FREESHIP", h6)
        self.assertIn("Complete Order with Discount →", h6)
        self.assertIn("https://s.com/c1?discount=FREESHIP", h6)

    def test_discount_percentage_extraction_year_edge_case(self):
        """Empirical edge case: discount codes with year prefixes like BF2026_10."""
        code = "BF2026_10"
        extracted = EmailDispatcher._extract_discount_percentage(code)
        self.assertEqual(extracted, "10%")

    def test_luxury_template_structural_compliance(self):
        """Verify strict adherence to luxury email structural markers."""
        res = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu",
            checkout_url="https://maisongrozavu.com/checkout",
            discount_code="MG10"
        )
        self.assertIn("<!DOCTYPE html>", res)
        self.assertIn('xmlns:v="urn:schemas-microsoft-com:vml"', res)
        self.assertIn('xmlns:o="urn:schemas-microsoft-com:office:office"', res)
        self.assertIn("<!--[if mso]>", res)
        self.assertIn("<o:OfficeDocumentSettings>", res)
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1"', res)
        self.assertIn("max-width: 600px;", res)
        self.assertIn("<v:roundrect", res)
        self.assertIn('class="btn"', res)
        self.assertIn("🔒", res)


class TestShopifyClientStress(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress testing for ShopifyClient.get_abandoned_checkouts_detailed."""

    def setUp(self):
        self.client = ShopifyClient("luxury-test.myshopify.com", "shpat_test_token_secret")

    async def test_empty_checkouts(self):
        """Verify empty checkouts array returns empty list."""
        self.client._get = AsyncMock(return_value={"checkouts": []})
        res = await self.client.get_abandoned_checkouts_detailed()
        self.assertEqual(res, [])

    async def test_checkouts_none_bug_probe(self):
        """Empirical test for {'checkouts': None} bug."""
        self.client._get = AsyncMock(return_value={"checkouts": None})
        res = await self.client.get_abandoned_checkouts_detailed()
        self.assertEqual(res, [])

    async def test_total_price_non_numeric_crash_probe(self):
        """Empirical test for non-numeric total_price string e.g. 'free' or 'N/A'."""
        mock_checkout = {
            "id": 1001,
            "abandoned_checkout_url": "https://store.com/c1",
            "total_price": "free",
            "line_items": []
        }
        self.client._get = AsyncMock(return_value={"checkouts": [mock_checkout]})
        res = await self.client.get_abandoned_checkouts_detailed()
        self.assertEqual(res[0]["total_price"], 0.0)

    async def test_phone_integer_type_crash_probe(self):
        """Empirical test for integer phone number e.g. phone: 40722123456."""
        mock_checkout = {
            "id": 1002,
            "abandoned_checkout_url": "https://store.com/c2",
            "phone": 40722123456,
            "line_items": []
        }
        self.client._get = AsyncMock(return_value={"checkouts": [mock_checkout]})
        res = await self.client.get_abandoned_checkouts_detailed()
        self.assertEqual(res[0]["phone"], "40722123456")
        self.assertEqual(res[0]["clean_phone"], "40722123456")
        self.assertTrue(res[0]["has_phone"])

    async def test_100_line_items_caching_and_enrichment(self):
        """Verify checkout with 100 items queries product API only for distinct products."""
        items = [
            {"title": f"Item {i}", "product_id": (i % 10) + 1, "variant_id": i + 1, "price": "100.00"}
            for i in range(100)
        ]
        mock_checkout = {
            "id": 1003,
            "abandoned_checkout_url": "https://store.com/c3",
            "line_items": items,
            "total_price": "10000.00"
        }

        async def fake_get(path, params=None):
            if path == "/checkouts.json":
                return {"checkouts": [mock_checkout]}
            if path.startswith("/products/"):
                pid = path.split("/")[2].split(".")[0]
                return {
                    "product": {
                        "id": int(pid),
                        "image": {"src": f"https://cdn.shopify.com/prod_{pid}.jpg"}
                    }
                }
            return {}

        self.client._get = AsyncMock(side_effect=fake_get)
        res = await self.client.get_abandoned_checkouts_detailed()
        self.assertEqual(len(res[0]["line_items"]), 100)
        # Verify deduplication: exactly 10 calls for 10 unique product IDs
        prod_calls = [c.args[0] for c in self.client._get.call_args_list if c.args[0].startswith("/products/")]
        self.assertEqual(len(prod_calls), 10)

    async def test_negative_caching_on_network_failure(self):
        """Verify that 404 / 500 errors negative-cache None and do not re-query."""
        self.client._get = AsyncMock(side_effect=Exception("500 API Outage"))
        u1 = await self.client.get_product_image_url(8888)
        u2 = await self.client.get_product_image_url(8888)
        self.assertIsNone(u1)
        self.assertIsNone(u2)
        self.assertEqual(self.client._get.call_count, 1)

    async def test_raw_checkout_url_never_altered(self):
        """Verify raw abandoned_checkout_url is preserved exactly without discount injection."""
        url = "https://store.myshopify.com/123/checkouts/ac?discount=EXISTING&locale=it"
        self.client._get = AsyncMock(return_value={"checkouts": [{"id": 1, "abandoned_checkout_url": url, "line_items": []}]})
        res = await self.client.get_abandoned_checkouts_detailed()
        self.assertEqual(res[0]["checkout_url"], url)
        self.assertEqual(res[0]["abandoned_checkout_url"], url)


class TestDetectCustomerLanguageAndCountry(unittest.TestCase):
    """Stress testing the multi-lingual / geographical customer detection heuristics."""

    def test_detection_by_country_code(self):
        self.assertEqual(detect_customer_language_and_country("", "", "", "IT", "")["lang"], "it")
        self.assertEqual(detect_customer_language_and_country("", "", "", "RO", "")["lang"], "ro")
        self.assertEqual(detect_customer_language_and_country("", "", "", "DE", "")["lang"], "de")
        self.assertEqual(detect_customer_language_and_country("", "", "", "FR", "")["lang"], "fr")
        self.assertEqual(detect_customer_language_and_country("", "", "", "ES", "")["lang"], "es")
        self.assertEqual(detect_customer_language_and_country("", "", "", "US", "")["lang"], "en")

    def test_detection_by_phone_prefix(self):
        self.assertEqual(detect_customer_language_and_country("", "", "+39 02 12345", "", "")["lang"], "it")
        self.assertEqual(detect_customer_language_and_country("", "", "+40 722 12345", "", "")["lang"], "ro")
        self.assertEqual(detect_customer_language_and_country("", "", "+49 30 12345", "", "")["lang"], "de")
        self.assertEqual(detect_customer_language_and_country("", "", "+33 1 12345", "", "")["lang"], "fr")
        self.assertEqual(detect_customer_language_and_country("", "", "+34 91 12345", "", "")["lang"], "es")

    def test_detection_by_tld(self):
        self.assertEqual(detect_customer_language_and_country("", "client@azienda.it", "", "", "")["lang"], "it")
        self.assertEqual(detect_customer_language_and_country("", "client@magazin.ro", "", "", "")["lang"], "ro")
        self.assertEqual(detect_customer_language_and_country("", "client@firma.de", "", "", "")["lang"], "de")
        self.assertEqual(detect_customer_language_and_country("", "client@boutique.fr", "", "", "")["lang"], "fr")
        self.assertEqual(detect_customer_language_and_country("", "client@tienda.es", "", "", "")["lang"], "es")

    def test_detection_fallback(self):
        self.assertEqual(detect_customer_language_and_country("", "client@gmail.com", "", "", "")["lang"], "en")


if __name__ == "__main__":
    unittest.main()

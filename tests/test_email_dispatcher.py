"""
Unit tests for backend/email_dispatcher.py
Validates:
1. Stage 1 cadence zero-discount coupon box suppression & neutral CTA.
2. Stage 2 cadence discount card rendering with MG10 & auto-applied discount in URL.
3. Stage 3 / VIP discount card with custom code (e.g. MGVIP15).
4. Itemized product showcase with 90x90 thumbnails, quantities, formatted prices, and variant handling.
5. Multi-language dictionary across all 6 locales (EN, RO, IT, ES, DE, FR).
6. Language normalization and fallback on unknown locales.
7. Backward compatibility with legacy parameters (items_str, product_image_url).
8. MSO Outlook conditionals, VML buttons, and responsive viewport meta tags.
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
from email_dispatcher import EmailDispatcher, EMAIL_I18N


class TestEmailDispatcher(unittest.TestCase):

    def test_stage_1_cadence_omits_discount_card(self):
        """Verify that Stage 1 (30m reminder) with discount_code=None suppresses the coupon box."""
        html = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu",
            customer_name="Elena",
            checkout_url="https://maisongrozavu.com/checkouts/c123",
            text_body="We noticed you left something behind.",
            discount_code=None,
            lang="en"
        )
        # Assert coupon card is NOT rendered
        self.assertNotIn("CADENCE DISCOUNT CARD", html)
        self.assertNotIn("RESERVED DISCOUNT CODE", html)
        self.assertNotIn("border: 2px dashed", html)
        # Assert neutral CTA is rendered
        self.assertIn("Complete Your Order →", html)
        # Assert checkout URL has no discount param
        self.assertNotIn("discount=", html)

    def test_stage_1_cadence_omits_discount_card_on_empty_string(self):
        """Verify that discount_code='' also suppresses coupon box."""
        html = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu",
            customer_name="Elena",
            checkout_url="https://maisongrozavu.com/checkouts/c123",
            text_body="Hello Elena",
            discount_code="",
            lang="ro"
        )
        self.assertNotIn("CADENCE DISCOUNT CARD", html)
        self.assertNotIn("COD DE REDUCERE REZERVAT", html)
        self.assertIn("Finalizează Comanda Acum →", html)
        self.assertNotIn("discount=", html)

    def test_stage_2_cadence_renders_discount_card_and_appends_url(self):
        """Verify that Stage 2 with discount_code='MG10' renders coupon card and updates CTA."""
        html = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu",
            customer_name="Matteo",
            checkout_url="https://maisongrozavu.com/checkouts/c456",
            text_body="Here is 10% off for you.",
            discount_code="MG10",
            lang="it"
        )
        # Coupon box present with code
        self.assertIn("CADENCE DISCOUNT CARD", html)
        self.assertIn("MG10", html)
        self.assertIn("CODICE SCONTO RISERVATO", html)
        # Localized Italian CTA with discount
        self.assertTrue("Completa l&#39;Ordine con lo Sconto 10% →" in html or "Completa l'Ordine con lo Sconto 10% →" in html)
        # URL has discount auto-applied
        self.assertIn("https://maisongrozavu.com/checkouts/c456?discount=MG10", html)

    def test_stage_3_vip_discount_code_mgvip15(self):
        """Verify post-delivery / VIP with discount_code='MGVIP15' parses 15% discount."""
        html = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu",
            customer_name="Sophie",
            checkout_url="https://maisongrozavu.com/checkouts/c789",
            text_body="Merci pour votre achat.",
            discount_code="MGVIP15",
            lang="fr"
        )
        self.assertIn("MGVIP15", html)
        self.assertIn("Finaliser ma Commande avec 15% de Réduction →", html)
        self.assertIn("discount=MGVIP15", html)

    def test_itemized_product_showcase_thumbnails_and_variants(self):
        """Verify itemized line items table with 90x90 thumbnails, titles, quantities, prices, and variant filtering."""
        line_items = [
            {
                "title": "Cashmere Overcoat",
                "variant_title": "Navy Blue / 50",
                "quantity": 1,
                "price": "390.00",
                "image_url": "https://cdn.shopify.com/products/overcoat.jpg"
            },
            {
                "title": "Silk Pocket Square",
                "variant_title": "Default Title",  # Should be suppressed
                "quantity": 2,
                "price": "45.00",
                "image_url": None  # Should render fallback 🛍️ thumbnail
            }
        ]
        html = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu",
            customer_name="Alex",
            checkout_url="https://maisongrozavu.com/checkouts/c999",
            line_items=line_items,
            lang="en",
            currency="EUR"
        )
        # Verify titles
        self.assertIn("Cashmere Overcoat", html)
        self.assertIn("Silk Pocket Square", html)
        # Verify variant: 'Navy Blue / 50' included, 'Default Title' suppressed
        self.assertIn("Navy Blue / 50", html)
        self.assertNotIn("Default Title", html)
        # Verify quantities
        self.assertIn("Qty:", html)
        self.assertIn(">1<", html)
        self.assertIn(">2<", html)
        # Verify prices
        self.assertIn("390.00 EUR", html)
        self.assertIn("45.00 EUR", html)
        # Verify 90x90 thumbnail image tag
        self.assertIn('width="90" height="90"', html)
        self.assertIn('https://cdn.shopify.com/products/overcoat.jpg', html)
        # Verify placeholder for missing image
        self.assertIn('🛍️', html)

    def test_multilanguage_dictionary_all_six_locales(self):
        """Verify correct strings for all 6 supported languages: EN, RO, IT, ES, DE, FR."""
        locales = {
            "en": ("YOUR RESERVED SELECTION", "Complete Your Order →"),
            "ro": ("PRODUSELE TALE REZERVATE", "Finalizează Comanda Acum →"),
            "it": ("I TUOI ARTICOLI RISERVATI", "Completa il Tuo Ordine →"),
            "es": ("TUS ARTÍCULOS RESERVADOS", "Finalizar Mi Pedido →"),
            "de": ("DEINE RESERVIERTE AUSWAHL", "Bestellung jetzt abschließen →"),
            "fr": ("VOTRE SÉLECTION RÉSERVÉE", "Finaliser ma Commande →"),
        }
        for lang, (expected_header, expected_cta) in locales.items():
            html = EmailDispatcher.build_html_email(
                shop_name="Test Store",
                customer_name="Client",
                items_str="Sample Item",
                checkout_url="https://store.com/checkout",
                lang=lang,
                discount_code=None
            )
            self.assertIn(expected_header, html, f"Failed header match for {lang}")
            self.assertIn(expected_cta, html, f"Failed CTA match for {lang}")

    def test_language_normalization_and_fallback(self):
        """Verify locale normalization (e.g. 'ro-RO', 'IT_it') and fallback on unknown locale."""
        html_ro = EmailDispatcher.build_html_email(shop_name="Shop", lang="ro-RO")
        self.assertIn("PRODUSELE TALE REZERVATE", html_ro)

        html_it = EmailDispatcher.build_html_email(shop_name="Shop", lang="IT_it")
        self.assertIn("I TUOI ARTICOLI RISERVATI", html_it)

        html_fallback = EmailDispatcher.build_html_email(shop_name="Shop", lang="unknown_lang")
        self.assertIn("YOUR RESERVED SELECTION", html_fallback)

    def test_backward_compatibility_legacy_parameters(self):
        """Verify calling build_html_email with legacy kwargs still works perfectly."""
        html = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu",
            customer_name="Comerciant Grozavu",
            items_str="Pachet Test Recuperare Coș",
            checkout_url="https://maisongrozavu.com",
            text_body="Test body line 1\nTest line 2"
        )
        self.assertIn("Maison Grozavu", html)
        self.assertIn("Pachet Test Recuperare Coș", html)
        self.assertIn("Test body line 1<br/>Test line 2", html)
        self.assertIn("https://maisongrozavu.com", html)

    def test_email_client_mso_and_responsive_markers(self):
        """Verify Outlook MSO conditionals and responsive viewport meta tags exist."""
        html = EmailDispatcher.build_html_email(shop_name="Maison Grozavu")
        self.assertIn("<!--[if (gte mso 9)|(IE)]>", html)
        self.assertIn("<!--[if mso]>", html)
        self.assertIn('xmlns:v="urn:schemas-microsoft-com:vml"', html)
        self.assertIn("viewport", html)
        self.assertTrue("preheader" in html or "display: none; font-size: 1px;" in html)

    def test_html_email_escapes_xss_content(self):
        """Verify that shop_name, text_body, discount_code, checkout_url, and line items escape HTML/XSS payloads."""
        xss_payload = "<script>alert('xss')</script>"
        xss_url_breakout = 'https://store.com/checkout?ref=" onmouseover="alert(1)'
        line_items = [
            {
                "title": f"Luxury Watch {xss_payload}",
                "variant_title": f"Gold Edition {xss_payload}",
                "quantity": 1,
                "price": f"99.00 {xss_payload}",
                "image_url": "https://cdn.shopify.com/watch.jpg"
            }
        ]

        html_out = EmailDispatcher.build_html_email(
            shop_name=f"Maison {xss_payload}",
            customer_name="Victim",
            checkout_url=xss_url_breakout,
            text_body=f"Your cart is waiting.\n{xss_payload}",
            discount_code=f"BF2026_10{xss_payload}",
            line_items=line_items,
            currency=f"EUR{xss_payload}",
            lang="en"
        )

        # 1. Verify zero raw unescaped script tags exist in rendered HTML
        self.assertNotIn("<script>", html_out)
        self.assertNotIn("</script>", html_out)

        # 2. Verify attribute breakout prevention in href and VML roundrect
        self.assertNotIn('onmouseover="alert', html_out)
        self.assertIn('&quot; onmouseover=&quot;alert(1)', html_out)

        # 3. Verify HTML escaping of payloads
        self.assertTrue(
            "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html_out
            or "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;" in html_out
        )

        # 4. Verify newline conversion while preserving escaped body
        self.assertIn("<br/>", html_out)

        # 5. Verify discount percentage extraction safely ignores the XSS payload and extracts valid 10%
        self.assertIn("10% OFF", html_out)


if __name__ == "__main__":
    unittest.main()


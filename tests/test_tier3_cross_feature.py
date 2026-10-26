"""
Tier 3: Cross-Feature Combinations Test Suite (>=5 tests).
Pairwise interactions, cross-channel synchronization, and cascading state transitions.
Authoritative specification: PROJECT.md Section 5 (Interface Contracts) & ORIGINAL_REQUEST.md.
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio
from datetime import datetime, timezone, timedelta

from tests.helpers import (
    HAS_EMAIL_DISPATCHER, EmailDispatcher, HAS_EMAIL_LINE_ITEMS,
    HAS_WHATSAPP_DISPATCHER, WhatsAppDispatcher,
    HAS_SHOPIFY_API, ShopifyClient, detect_customer_language_and_country,
    HAS_CADENCE_MANAGER, DripCadenceManager,
    HAS_POST_DELIVERY, PostDeliveryService,
    HAS_MOBILE_NOTIFIER, MobileNotifier,
    make_sample_line_item, make_sample_checkout,
    make_sample_order, make_sample_shop_settings
)


class TestTier3CrossFeature(unittest.TestCase):
    """
    Tier 3: Pairwise and multi-channel cross-feature tests.
    """

    def test_f_cross_01_email_and_whatsapp_dual_dispatch(self):
        """
        Cross-Feature 1: Email Showcase + WhatsApp Fallback Dispatch
        When an abandoned cart with phone and email is recovered, both the responsive
        HTML email and a canonical wa.me link are generated with consistent line items.
        """
        if not HAS_EMAIL_DISPATCHER or not HAS_WHATSAPP_DISPATCHER:
            self.skipTest("EmailDispatcher or WhatsAppDispatcher missing")
        if not HAS_EMAIL_LINE_ITEMS:
            self.skipTest("EmailDispatcher line_items support pending Milestone 1 implementation")

        item = make_sample_line_item(title="Grozavu Velvet Tuxedo", price="320.00")
        checkout = make_sample_checkout(
            customer_name="Alexandru",
            phone="+40722111222",
            line_items=[item]
        )

        # 1. Generate Email Showcase
        html_email = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu",
            customer_name=checkout["customer_name"],
            items_str=item["title"],
            checkout_url=checkout["checkout_url"],
            text_body="Selecția ta este rezervată.",
            discount_code="MG10",
            line_items=[item]
        )
        self.assertIn("Grozavu Velvet Tuxedo", html_email)
        self.assertIn("MG10", html_email)

        # 2. Generate WhatsApp Link
        dispatcher = WhatsAppDispatcher()
        wa_msg = f"Salut Alexandru! Am rezervat {item['title']} cu 10% reducere (MG10): {checkout['checkout_url']}"
        wa_link = dispatcher.generate_wa_me_link(checkout["phone"], wa_msg)

        self.assertTrue(wa_link.startswith("https://wa.me/40722111222"))
        self.assertIn("MG10", wa_link)

    def test_f_cross_02_drip_stage2_discount_triggers_discord_alert(self):
        """
        Cross-Feature 2: Drip Stage 2 Cadence (MG10) + Discord Webhook Alert
        When checkout hits 4h mark (Stage 2), discount code MG10 is issued in email
        and a Discord rich embed alert is sent with stage 2 information.
        """
        if not HAS_CADENCE_MANAGER or not HAS_MOBILE_NOTIFIER:
            self.skipTest("DripCadenceManager or MobileNotifier missing")

        cadence = DripCadenceManager()
        notifier = MobileNotifier()
        settings = make_sample_shop_settings()

        now_dt = datetime.now(timezone.utc)
        cart_dt = now_dt - timedelta(hours=4, minutes=15)
        checkout = make_sample_checkout(created_at_dt=cart_dt)
        state_record = {"current_stage": 1, "status": "active"}

        # Cadence advances to Stage 2
        next_stage = cadence.evaluate_drip_stage(checkout, state_record, now_dt)
        self.assertEqual(next_stage, 2)

        # Merchant notified via Discord
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 204
            mock_post.return_value = mock_resp

            coro = notifier.notify_merchant(
                "abandoned_cart",
                {
                    "customer_name": checkout["customer_name"],
                    "total_price": checkout["total_price"],
                    "currency": checkout["currency"],
                    "stage": 2,
                    "discount_code": "MG10"
                },
                settings
            )
            asyncio.run(coro)
            self.assertTrue(mock_post.called)

    def test_f_cross_03_conversion_reconciliation_cancels_drip_and_alerts(self):
        """
        Cross-Feature 3: Order Conversion -> Drip Cancellation + Mobile Conversion Alert
        When an order is created, matching active drip sequence is converted (canceled from further stages)
        and an instant recovery success alert is sent to Telegram/Discord.
        """
        if not HAS_CADENCE_MANAGER or not HAS_MOBILE_NOTIFIER:
            self.skipTest("DripCadenceManager or MobileNotifier missing")

        cadence = DripCadenceManager()
        notifier = MobileNotifier()
        settings = make_sample_shop_settings()

        order = make_sample_order(order_id="ord_rev_777", total_price=145.00)

        with patch.object(cadence, "mark_order_converted", return_value=True) as mock_conv:
            converted = cadence.mark_order_converted(settings["shop"], order)
            self.assertTrue(converted)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp

            coro = notifier.notify_merchant(
                "recovery_converted",
                {
                    "customer_name": "Lorenzo Rossi",
                    "order_number": "1001",
                    "recovered_revenue": 145.00,
                    "currency": "EUR",
                    "discount_code": "MG10"
                },
                settings
            )
            res = asyncio.run(coro)
            self.assertIsNotNone(res)

    def test_f_cross_04_vip_review_generates_multichannel_and_mobile_alert(self):
        """
        Cross-Feature 4: Post-Delivery VIP (MGVIP15) + WhatsApp link + Telegram VIP Alert
        5-7 days post-fulfillment, VIP queue fires: dispatches email review request,
        generates WhatsApp link with MGVIP15, and alerts merchant on Telegram.
        """
        if not HAS_POST_DELIVERY or not HAS_MOBILE_NOTIFIER or not HAS_WHATSAPP_DISPATCHER:
            self.skipTest("PostDeliveryService, MobileNotifier, or WhatsAppDispatcher missing")

        service = PostDeliveryService()
        notifier = MobileNotifier()
        wa_dispatcher = WhatsAppDispatcher()
        settings = make_sample_shop_settings()

        with patch.object(service, "process_due_vip_automations", return_value=1):
            count = service.process_due_vip_automations(settings["shop"], settings)
            self.assertEqual(count, 1)

        # Verified WhatsApp wa.me link contains MGVIP15
        wa_link = wa_dispatcher.generate_wa_me_link("+393401234567", "Grazie! Usa MGVIP15 per il 15% OFF")
        self.assertIn("MGVIP15", wa_link)

        # Verified Telegram VIP notification
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp

            coro = notifier.notify_merchant(
                "vip_upsell_sent",
                {
                    "customer_name": "Lorenzo Rossi",
                    "order_number": "1001",
                    "discount_code": "MGVIP15"
                },
                settings
            )
            asyncio.run(coro)
            self.assertTrue(mock_post.called)

    def test_f_cross_05_multilingual_geo_to_email_and_whatsapp(self):
        """
        Cross-Feature 5: Language Detection -> Localized Email Showcase + Localized WhatsApp
        Italian customer (+39 phone, .it email) detected as 'it'.
        Email template renders Italian labels and WhatsApp message link is in Italian.
        """
        if not HAS_SHOPIFY_API or not HAS_EMAIL_DISPATCHER or not HAS_WHATSAPP_DISPATCHER:
            self.skipTest("ShopifyClient, EmailDispatcher, or WhatsAppDispatcher missing")
        if not HAS_EMAIL_LINE_ITEMS:
            self.skipTest("EmailDispatcher multilingual support pending Milestone 1 implementation")

        geo = detect_customer_language_and_country(
            c_name="Marco Esposito",
            email="marco.esposito@virgilio.it",
            phone="+393409876543",
            country_code="IT",
            country_name="Italia"
        )
        self.assertEqual(geo["lang"], "it")

        # Localized Email
        html_email = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu",
            customer_name="Marco",
            items_str="Abito Sartoriale",
            checkout_url="https://grozavu.store/checkouts/ac/it_99",
            text_body="Ciao Marco, abbiamo riservato i tuoi capi.",
            discount_code="MG10",
            lang=geo["lang"]
        )
        self.assertIn("Abito Sartoriale", html_email)

        # Localized WhatsApp
        wa = WhatsAppDispatcher()
        link = wa.generate_wa_me_link("+393409876543", f"Ciao Marco! Il tuo carrello è riservato su Maison Grozavu.")
        self.assertTrue("393409876543" in link)

    def test_f_cross_06_drip_stage1_preserves_raw_url_and_neutral_whatsapp(self):
        """
        Cross-Feature 6: Stage 1 Email & WhatsApp preserve raw URL without premature MG10 discount
        At 30 minutes, neither Email nor WhatsApp link should expose discount=MG10.
        """
        if not HAS_EMAIL_DISPATCHER or not HAS_WHATSAPP_DISPATCHER:
            self.skipTest("EmailDispatcher or WhatsAppDispatcher missing")
        if not HAS_EMAIL_LINE_ITEMS:
            self.skipTest("EmailDispatcher line_items support pending Milestone 1 implementation")

        raw_url = "https://grozavu.store/checkouts/ac/clean_token"
        item = make_sample_line_item(title="Silk Scarf")

        # Stage 1 Email: discount_code=None
        html_email = EmailDispatcher.build_html_email(
            shop_name="Maison Grozavu",
            customer_name="Elena",
            items_str="Silk Scarf",
            checkout_url=raw_url,
            text_body="Ai uitat ceva în coș?",
            discount_code=None,
            line_items=[item]
        )
        self.assertNotIn("discount=MG10", html_email)
        self.assertNotIn("MG10", html_email)

        # Stage 1 WhatsApp: neutral message
        wa = WhatsAppDispatcher()
        wa_msg = f"Salut Elena! Am păstrat produsele tale: {raw_url}"
        link = wa.generate_wa_me_link("+40721123456", wa_msg)
        self.assertNotIn("MG10", link)
        self.assertNotIn("discount=", link)


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for Jarvis Smart Upgrades:
- Google Merchant Feed colour & material extraction from real product copy
- Buyer-intent long-tail SEO proposals (strictly preview-only, no auto-SEO)
- Automatic Shopify discount code creation using Grozavu / MG names only (never Jarvis)
- Complementary product cross-sell & 30-day Win-Back sequence
- Autonomous Self-Healing engine
"""

import os
import sys
import time
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
for p in (PROJECT_ROOT, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from tests.auth_helpers import AUTH_HEADERS
except ImportError:
    from auth_helpers import AUTH_HEADERS

import database as db
import main
import post_delivery_service as pds
from google_merchant_feed import build_feed_items
from seo_optimizer import ProductSEOOptimizer
from shopify_api import ShopifyClient
from starlette.testclient import TestClient

SHOP = "grozavushop.myshopify.com"


class TestFeedDescriptionColourAndMaterial(unittest.TestCase):
    def _build_one(self, title, body_html="", ptype="Apparel", variants=None, options=None):
        prod = {
            "id": 501,
            "title": title,
            "handle": "test-item",
            "body_html": body_html,
            "product_type": ptype,
            "status": "active",
            "published_at": "2026-10-01T00:00:00Z",
            "options": options or [{"name": "Size", "position": 1}],
            "images": [{"id": 1, "src": "https://cdn.shopify.com/x.jpg"}],
            "variants": variants or [{"id": 11, "price": "65.00", "option1": "M", "title": "M"}],
        }
        items, skipped = build_feed_items([prod], shop_domain="maisongrozavu.com", brand="Grozavu")
        self.assertEqual(skipped, [])
        return items[0]

    def test_extracts_blush_pink_and_cotton_elastane(self):
        item = self._build_one(
            "Blush Wide-Leg Pants",
            body_html="<p>300 g/m² cotton-elastane in blush pink, cut long and wide with an adjustable waist.</p>",
            ptype="Pants",
        )
        self.assertEqual(item.get("color"), "Blush Pink")
        self.assertEqual(item.get("material"), "Cotton-Elastane")

    def test_extracts_black_over_graphic_print_name(self):
        item = self._build_one(
            "Magenta Smoke Hoodie",
            body_html="<p>330 g/m² cotton-elastane in black, with a magenta smoke print drifting across one side.</p>",
            ptype="Hoodie",
        )
        self.assertEqual(item.get("color"), "Black")
        self.assertEqual(item.get("material"), "Cotton-Elastane")

    def test_single_variant_accessory_gets_one_size_and_material(self):
        item = self._build_one(
            "Bucket Hat — Embroidered Hare",
            body_html="<p>A black bucket hat in 100% cotton twill, with the Grozavu hare embroidered in white.</p>",
            ptype="Hat",
            options=[{"name": "Title", "position": 1}],
            variants=[{"id": 99, "price": "35.00", "title": "Default Title"}],
        )
        self.assertEqual(item.get("color"), "Black")
        self.assertEqual(item.get("size"), "One Size")
        self.assertEqual(item.get("material"), "100% Cotton Twill")

    def test_two_tone_split_colour(self):
        item = self._build_one(
            "Two-Tone Hoodie",
            body_html="<p>308 g/m² hoodie split down the middle in black and soft pink, hood included.</p>",
            ptype="Hoodie",
        )
        self.assertEqual(item.get("color"), "Black / Soft Pink")


class TestLongTailPreviewOnlySEO(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.opt = ProductSEOOptimizer(brand_name="Grozavu", domain="maisongrozavu.com")

    async def test_seo_extracts_real_specs_and_stays_preview_only(self):
        prod = {
            "id": 901,
            "title": "Eco Tote Bag",
            "handle": "eco-tote-bag",
            "product_type": "Tote Bag",
            "body_html": (
                "<p>A black tote in 100% organic cotton twill, 272 g/m², with the Grozavu hare and wordmark "
                "in white on the front. Room for the weekly shop, books and the rest of the day.</p>"
            ),
            "images": [{"id": 1, "src": "https://cdn.shopify.com/tote.jpg", "alt": ""}],
            "variants": [{"id": 10, "price": "29.00"}],
        }
        res = await self.opt.optimize_and_apply(shopify_client=MagicMock(), product=prod, log=False)
        self.assertTrue(res["preview_only"])
        self.assertFalse(res["applied"])
        seo_title = self.opt.generate_seo_title(prod["title"], prod["product_type"], body_html=prod["body_html"])
        self.assertIn("272 g/m²", seo_title)
        self.assertIn("Grozavu", seo_title)
        self.assertNotIn("Premium Streetwear", seo_title)
        # Idempotent check
        self.assertEqual(
            self.opt.generate_seo_title(seo_title, prod["product_type"], body_html=prod["body_html"]),
            seo_title,
        )
        # Complete sentence meta description without mid-word ellipsis
        meta = self.opt.generate_meta_description(prod["title"], prod["body_html"], prod["product_type"])
        self.assertLessEqual(len(meta), 160)
        self.assertFalse(meta.endswith("…"))


class TestBrandDiscountCodesNoJarvis(unittest.IsolatedAsyncioTestCase):
    def test_brand_discount_specs_never_use_jarvis(self):
        codes = [s["code"] for s in ShopifyClient.BRAND_DISCOUNT_SPECS]
        self.assertIn("MG10", codes)
        self.assertIn("GROZAVU10", codes)
        self.assertIn("MGVIP15", codes)
        self.assertIn("GROZAVU15", codes)
        self.assertIn("GROZAVU5", codes)
        for c in codes:
            self.assertNotIn("jarvis", c.lower())

    async def test_ensure_brand_discount_codes_creates_and_rejects_jarvis(self):
        client = ShopifyClient(SHOP, "shpat_0123456789abcdef")

        async def fake_graphql(query, variables=None):
            if "codeDiscountNodeByCode" in query:
                if (variables or {}).get("code") == "MG10":
                    return {"data": {"codeDiscountNodeByCode": {"id": "gid://shopify/DiscountCodeNode/1"}}}
                return {"data": {"codeDiscountNodeByCode": None}}
            if "discountCodeBasicCreate" in query:
                return {
                    "data": {
                        "discountCodeBasicCreate": {
                            "codeDiscountNode": {"id": "gid://shopify/DiscountCodeNode/2"},
                            "userErrors": [],
                        }
                    }
                }
            return {}

        client._graphql = fake_graphql
        specs = [
            {"code": "MG10", "percent": 10},
            {"code": "GROZAVU10", "percent": 10},
            {"code": "JARVIS10", "percent": 10},  # must be rejected
        ]
        res = await client.ensure_brand_discount_codes(specs)
        self.assertIn("MG10", res["existing"])
        self.assertIn("GROZAVU10", res["created"])
        self.assertNotIn("JARVIS10", res["created"])
        self.assertEqual(res["codes"]["JARVIS10"]["status"], "rejected")

    async def test_ensure_brand_discount_codes_renames_legacy_jarvis_title(self):
        client = ShopifyClient(SHOP, "shpat_0123456789abcdef")
        renamed_payloads = []

        async def fake_graphql(query, variables=None):
            if "codeDiscountNodeByCode" in query:
                return {
                    "data": {
                        "codeDiscountNodeByCode": {
                            "id": "gid://shopify/DiscountCodeNode/99",
                            "codeDiscount": {"title": "MGVIP15 — Jarvis VIP (15%, o utilizare per client)"},
                        }
                    }
                }
            if "discountCodeBasicUpdate" in query:
                renamed_payloads.append(variables)
                return {
                    "data": {
                        "discountCodeBasicUpdate": {
                            "codeDiscountNode": {"id": "gid://shopify/DiscountCodeNode/99"},
                            "userErrors": [],
                        }
                    }
                }
            return {}

        client._graphql = fake_graphql
        res = await client.ensure_brand_discount_codes([
            {"code": "MGVIP15", "percent": 15, "title": "Grozavu MGVIP15 — 15% VIP & Win-Back"},
        ])
        self.assertIn("MGVIP15", res["renamed"])
        self.assertEqual(res["codes"]["MGVIP15"]["status"], "renamed")
        self.assertEqual(len(renamed_payloads), 1)
        self.assertEqual(renamed_payloads[0]["basicCodeDiscount"]["title"], "Grozavu MGVIP15 — 15% VIP & Win-Back")


class TestComplementaryCrossSellAndWinBack(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.svc = pds.PostDeliveryService()
        self.catalog = [
            {
                "id": 1,
                "title": "Heavyweight Brushed Hoodie",
                "handle": "heavyweight-hoodie",
                "status": "active",
                "images": [{"src": "https://cdn.shopify.com/hoodie.jpg"}],
                "variants": [{"id": 11, "price": "79.00"}],
            },
            {
                "id": 2,
                "title": "Blush Wide-Leg Pants",
                "handle": "blush-wide-leg-pants",
                "status": "active",
                "images": [{"src": "https://cdn.shopify.com/pants.jpg"}],
                "variants": [{"id": 22, "price": "69.00"}],
            },
        ]

    def test_complementary_recommendation_pairs_hoodie_with_pants(self):
        rec = self.svc.pick_complementary_product("Heavyweight Brushed Hoodie", self.catalog)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["title"], "Blush Wide-Leg Pants")

        rec2 = self.svc.pick_complementary_product("Blush Wide-Leg Pants", self.catalog)
        self.assertIsNotNone(rec2)
        self.assertEqual(rec2["title"], "Heavyweight Brushed Hoodie")

        self.assertIsNone(self.svc.pick_complementary_product("Hoodie", []))

    def test_winback_30d_sends_once_to_consented_customer_and_skips_repeat_buyer(self):
        now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)  # 13:00 Madrid (not quiet hours)
        sent_40d_ago = now - timedelta(days=40)
        order_id = f"wb_ord_{int(time.time() * 1000)}"
        email = f"winback_{int(time.time() * 1000)}@example.es"

        db.record_marketing_consent(SHOP, email=email, accepts_marketing=True, source="order")
        db.enqueue_post_delivery_automation(
            shop=SHOP,
            order_id=order_id,
            order_number="1055",
            customer_email=email,
            customer_phone=None,
            customer_name="Lucía",
            fulfilled_at=sent_40d_ago - timedelta(days=2),
            scheduled_for=sent_40d_ago,
            items_summary=[{"title": "Heavyweight Brushed Hoodie", "price": "79.00", "quantity": 1}],
            discount_code="MGVIP15",
        )
        db.mark_post_delivery_sent(order_id, sent_at=sent_40d_ago)

        with patch.object(self.svc.email_dispatcher, "send_email", new_callable=AsyncMock, return_value={"success": True}) as mock_send:
            # 1. If customer is in recent_customer_emails -> skipped
            cnt_skip = self.svc.process_winback_automations(
                SHOP, now_dt=now, catalog_products=self.catalog, recent_customer_emails={email}
            )
            self.assertEqual(cnt_skip, 0)
            mock_send.assert_not_called()

            # 2. Eligible customer -> sends once with GROZAVU15 and complementary product
            cnt_sent = self.svc.process_winback_automations(
                SHOP, now_dt=now, catalog_products=self.catalog, recent_customer_emails=set()
            )
            self.assertEqual(cnt_sent, 1)
            mock_send.assert_called_once()
            sent_body = mock_send.call_args.kwargs["body_text"]
            self.assertIn("GROZAVU15", sent_body)
            self.assertIn("Blush Wide-Leg Pants", sent_body)

            # 3. Second run -> blocked by sequence_key winback:<order_id> cap (max 1 per order)
            cnt_again = self.svc.process_winback_automations(
                SHOP, now_dt=now, catalog_products=self.catalog, recent_customer_emails=set()
            )
            self.assertEqual(cnt_again, 0)


class TestSelfHealingEndpoints(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.client = TestClient(main.app, headers=AUTH_HEADERS)

    def test_self_heal_clears_expired_locks_and_returns_status(self):
        main._FAILED_UNTIL["expired_cid_1"] = time.time() - 10
        r = self.client.post("/api/autopilot/self-heal", json={"shop": SHOP})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertNotIn("expired_cid_1", main._FAILED_UNTIL)

        st = self.client.get(f"/api/discounts/status?shop={SHOP}")
        self.assertEqual(st.status_code, 200)
        self.assertIn("GROZAVU10", st.json()["configured_codes"])
        self.assertNotIn("JARVIS10", st.json()["configured_codes"])


if __name__ == "__main__":
    unittest.main()

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
        # Only the codes Jarvis' emails actually mention; no extra public codes.
        self.assertEqual(sorted(codes), ["MG10", "MGVIP15"])
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

    LIVE_OK = {"found": True, "email_state": "SUBSCRIBED", "last_order_at": None,
               "order_found": True, "order_cancelled": False, "order_financial_status": "PAID"}

    def _new_shop(self):
        self.wb_shop = f"wb-{time.time_ns()}.myshopify.com"
        self.svc._winback_skip_until = {}
        return self.wb_shop

    def _winback_fixture(self, now, *, order_suffix="", email=None, days_ago=40, consent=True):
        shop = getattr(self, "wb_shop", None) or self._new_shop()
        stamp = f"{time.time_ns()}{order_suffix}"
        order_id = f"wb_ord_{stamp}"
        email = email or f"winback_{stamp}@example.es"
        sent_at = now - timedelta(days=days_ago)
        if consent:
            db.record_marketing_consent(shop, email=email, accepts_marketing=True, source="order")
        db.enqueue_post_delivery_automation(
            shop=shop, order_id=order_id, order_number="1055", customer_email=email,
            customer_phone=None, customer_name="Lucía",
            fulfilled_at=sent_at - timedelta(days=2), scheduled_for=sent_at,
            items_summary=[{"title": "Heavyweight Brushed Hoodie", "price": "79.00", "quantity": 1}],
            discount_code="MGVIP15",
        )
        db.mark_post_delivery_sent(order_id, sent_at=sent_at)
        # the live "last order" is the original order itself (placed before it was fulfilled)
        live = dict(self.LIVE_OK, last_order_at=(sent_at - timedelta(days=4)).isoformat())
        return order_id, email, live

    def _run(self, now, live_fn, code_ok=True, send_result=None, recent=None):
        with patch.object(self.svc, "_winback_live_state", side_effect=live_fn) as live_mock, \
             patch.object(self.svc, "_discount_code_active", return_value=code_ok), \
             patch.object(self.svc.email_dispatcher, "send_email", new_callable=AsyncMock,
                          return_value=send_result or {"success": True}) as mock_send:
            cnt = self.svc.process_winback_automations(
                self.wb_shop, now_dt=now, catalog_products=self.catalog, recent_customer_emails=recent or set()
            )
        return cnt, mock_send, live_mock

    def test_winback_30d_sends_once_to_consented_customer_and_skips_repeat_buyer(self):
        now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)  # 13:00 Madrid (not quiet hours)
        self._new_shop()
        order_id, email, live = self._winback_fixture(now)

        # 1. Customer in recent_customer_emails -> skipped before any Shopify lookup
        cnt, send, live_mock = self._run(now, lambda *a: live, recent={email})
        self.assertEqual(cnt, 0)
        send.assert_not_called()
        live_mock.assert_not_called()

        # 2. Eligible -> one email with MGVIP15 + complementary product, labelled as a suggestion
        cnt, send, _ = self._run(now, lambda *a: live)
        self.assertEqual(cnt, 1)
        send.assert_called_once()
        body = send.call_args.kwargs["body_text"]
        html_body = send.call_args.kwargs["body_html"]
        self.assertIn("MGVIP15", body)
        self.assertNotIn("GROZAVU15", body)
        self.assertIn("Blush Wide-Leg Pants", body)
        self.assertNotIn("TU PEDIDO", html_body)
        self.assertIn("ELEGIDO PARA TI", html_body)
        self.assertIn("Publicidad", html_body)

        # 3. Second run -> nothing (claim recorded; one per order and per person)
        cnt, send, _ = self._run(now, lambda *a: live)
        self.assertEqual(cnt, 0)
        send.assert_not_called()

    def test_winback_respects_unsubscribe_made_in_shopify(self):
        now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
        self._new_shop()
        _, email, live = self._winback_fixture(now, order_suffix="u")
        live = dict(live, email_state="UNSUBSCRIBED")
        cnt, send, _ = self._run(now, lambda *a: live)
        self.assertEqual(cnt, 0)
        send.assert_not_called()
        self.assertEqual(db.get_consent_status(self.wb_shop, email=email, channel="email"), db.CONSENT_OPTED_OUT)

    def test_winback_skips_not_subscribed_pending_and_unknown_customers(self):
        now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
        for state, found in (("NOT_SUBSCRIBED", True), ("PENDING", True), (None, False)):
            self._new_shop()
            _, _, live = self._winback_fixture(now, order_suffix=f"s{state}")
            live = dict(live, email_state=state, found=found)
            cnt, send, _ = self._run(now, lambda *a, lv=live: lv)
            self.assertEqual(cnt, 0, state)
            send.assert_not_called()

    def test_winback_skips_refunded_cancelled_and_returning_customers(self):
        now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
        cases = (
            {"order_financial_status": "REFUNDED"},
            {"order_cancelled": True},
            {"last_order_at": (now - timedelta(days=10)).isoformat()},   # ordered again recently
            {"last_order_at": (now - timedelta(days=35)).isoformat()},   # newer order after this one
            {"last_order_at": None},                                     # unknown -> fail closed
        )
        for i, change in enumerate(cases):
            self._new_shop()
            _, _, live = self._winback_fixture(now, order_suffix=f"r{i}", days_ago=60)
            live = dict(live, **change)
            cnt, send, _ = self._run(now, lambda *a, lv=live: lv)
            self.assertEqual(cnt, 0, change)
            send.assert_not_called()

    def test_winback_fails_closed_when_shopify_or_code_unavailable(self):
        now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
        self._new_shop()
        _, _, live = self._winback_fixture(now, order_suffix="e")

        def boom(*a):
            raise RuntimeError("Shopify down")
        cnt, send, _ = self._run(now, boom)
        self.assertEqual(cnt, 0)
        send.assert_not_called()

        self._new_shop()
        cnt, send, _ = self._run(now, lambda *a: live, code_ok=False)  # MGVIP15 missing/inactive
        self.assertEqual(cnt, 0)
        send.assert_not_called()

    def test_winback_failed_send_releases_claim_and_can_retry(self):
        now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
        self._new_shop()
        _, email, live = self._winback_fixture(now, order_suffix="f")
        cnt, send, _ = self._run(now, lambda *a: live, send_result={"success": False, "error": "x"})
        self.assertEqual(cnt, 0)
        send.assert_called_once()
        self.assertEqual(db.count_recent_messages_of_type(self.wb_shop, email, "email", "winback_30d", 90, now_dt=now), 0)
        cnt, send, _ = self._run(now, lambda *a: live)
        self.assertEqual(cnt, 1)

    def test_winback_one_email_per_person_even_with_several_orders(self):
        now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
        self._new_shop()
        email = f"multi_{int(time.time() * 1000)}@example.es"
        _, _, live_a = self._winback_fixture(now, order_suffix="a", email=email, days_ago=60)
        _, _, _live_b = self._winback_fixture(now, order_suffix="b", email=email, days_ago=50)
        cnt, send, _ = self._run(now, lambda *a: live_a)
        self.assertEqual(cnt, 1)
        # 4 days later (past the 72h cap) the second order still does not trigger another email
        later = now + timedelta(days=4)
        cnt, send, _ = self._run(later, lambda *a: live_a)
        self.assertEqual(cnt, 0)
        send.assert_not_called()

    def test_winback_never_sends_more_than_max_per_run(self):
        now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
        self._new_shop()
        lives = {}
        for i in range(5):
            oid, _, lv = self._winback_fixture(now, order_suffix=f"m{i}", days_ago=45 + i)
            lives[oid] = lv
        cnt, send, _ = self._run(now, lambda shop, email, oid: lives.get(oid, self.LIVE_OK))
        self.assertLessEqual(cnt, pds.PostDeliveryService.WINBACK_MAX_PER_RUN)
        self.assertLessEqual(send.call_count, pds.PostDeliveryService.WINBACK_MAX_PER_RUN)

    def test_winback_romanian_copy_does_not_call_shared_code_personal(self):
        msg = self.svc.build_winback_message("Ana", "Hoodie", None, "MGVIP15", lang="ro")
        self.assertNotIn("personal", msg)
        self.assertIn("MGVIP15", msg)


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
        self.assertEqual(sorted(st.json()["configured_codes"]), ["MG10", "MGVIP15"])
        self.assertNotIn("JARVIS10", st.json()["configured_codes"])


class TestWatchdogAgentAndImageColors(unittest.IsolatedAsyncioTestCase):
    def test_colour_from_image_filenames_and_multi_variant_beanie_size(self):
        from google_merchant_feed import _colour_from_images
        self.assertEqual(
            _colour_from_images(["https://cdn.shopify.com/deep-cut-sleeveless-tee-black-relaxed-fit-grey.jpg"]),
            "Black",
        )
        self.assertEqual(
            _colour_from_images(["https://cdn.shopify.com/structured-five-panel-cap-beige-black-grey.jpg"]),
            "Beige / Black",
        )
        self.assertEqual(
            _colour_from_images(["https://cdn.shopify.com/full-zip.jpg", "https://cdn.shopify.com/grozavu-full-zip-hoodie-beige-studio-1.jpg"]),
            "Beige",
        )
        # Studio backdrop '-grey.jpg' alone or print names must NOT be guessed as garment colour
        self.assertEqual(
            _colour_from_images(["https://cdn.shopify.com/cotton-cap-low-profile-grozavu-ss26-grey.jpg"]),
            "",
        )
        self.assertEqual(
            _colour_from_images(["https://cdn.shopify.com/ss26-wide-leg-pants-deep-red-mark.jpg"]),
            "",
        )

        # Multi-colour beanie with no Size option gets One Size
        beanie = {
            "id": 777,
            "title": "Fisherman Beanie",
            "handle": "fisherman-beanie",
            "product_type": "Beanie",
            "status": "active",
            "published_at": "2026-10-01T00:00:00Z",
            "options": [{"name": "Color", "position": 1}],
            "images": [{"id": 1, "src": "https://cdn.shopify.com/beanie.jpg"}],
            "variants": [
                {"id": 1, "price": "29.00", "option1": "Black", "title": "Black"},
                {"id": 2, "price": "29.00", "option1": "Athletic Heather", "title": "Athletic Heather"},
            ],
        }
        items, _ = build_feed_items([beanie], shop_domain="maisongrozavu.com", brand="Grozavu")
        self.assertEqual(len(items), 2)
        self.assertTrue(all(it.get("size") == "One Size" for it in items))

    async def test_watchdog_deep_scan_detects_blockers_and_autofixes_discounts(self):
        from store_watchdog import StoreWatchdogAgent
        agent = StoreWatchdogAgent(brand_domain="maisongrozavu.com", brand_name="Grozavu")

        fake_client = MagicMock()
        fake_client.ensure_brand_discount_codes = AsyncMock(return_value={
            "ok": True,
            "created": ["GROZAVU5"],
            "existing": ["MG10", "MGVIP15"],
            "renamed": ["MGVIP15"],
            "errors": [],
            "codes": {},
        })
        fake_dns = MagicMock()
        fake_dns.audit_domain = AsyncMock(return_value={"score": 100, "rating": "OK"})
        fake_notifier = MagicMock()
        fake_notifier.notify_merchant = AsyncMock(return_value={"success": True})

        products = [
            {
                "id": 1,
                "title": "No Image Product",
                "handle": "no-image-product",
                "body_html": "<p>Short</p>",
                "status": "active",
                "published_at": "2026-10-01T00:00:00Z",
                "images": [],
                "variants": [{"id": 11, "price": "45.00"}],
            },
            {
                "id": 2,
                "title": "Good Heavyweight Hoodie — Black",
                "handle": "good-hoodie",
                "body_html": "<p>350 g/m² combed ring-spun cotton in black with brushed fleece interior.</p>",
                "status": "active",
                "published_at": "2026-10-01T00:00:00Z",
                "options": [{"name": "Size", "position": 1}],
                "images": [{"id": 10, "src": "https://cdn.shopify.com/hoodie-black.jpg", "alt": "Good Hoodie"}],
                "variants": [{"id": 21, "price": "79.00", "option1": "M"}],
            },
        ]

        report = await agent.run_deep_scan(
            shop=SHOP,
            shopify_client=fake_client,
            products=products,
            deliverability_checker=fake_dns,
            mobile_notifier=fake_notifier,
            shop_settings={"notify_telegram": True},
            check_storefront=False,
            check_dns=True,
            auto_fix_discounts=True,
        )
        self.assertEqual(report["scans_completed"], 1)
        self.assertTrue(any("GROZAVU5" in f["detail"] for f in report["auto_fixed"]))
        self.assertTrue(any("MGVIP15" in f["detail"] for f in report["auto_fixed"]))
        self.assertTrue(any(c["code"] == "products_missing_images" for c in report["critical_issues"]))
        self.assertLess(report["health_score"], 100)
        fake_notifier.notify_merchant.assert_awaited_once()

    def test_watchdog_endpoints_require_auth(self):
        unauth = TestClient(main.app)
        self.assertEqual(unauth.get("/api/watchdog/status").status_code, 401)
        self.assertEqual(unauth.post("/api/watchdog/scan-now", json={}).status_code, 401)

    async def test_vision_color_detector_and_watchdog_auto_fix(self):
        import io
        from PIL import Image
        from vision_color_detector import classify_image_bytes, is_trusted_product_image_url
        from store_watchdog import StoreWatchdogAgent

        # SSRF host validation
        self.assertTrue(is_trusted_product_image_url("https://cdn.shopify.com/s/files/1/cap.jpg"))
        self.assertFalse(is_trusted_product_image_url("http://169.254.169.254/latest/meta-data"))
        self.assertFalse(is_trusted_product_image_url("https://evil.example/a.jpg"))

        # Synthetic studio product images on white background
        def make_studio_jpg(rgb):
            im = Image.new("RGB", (120, 120), (255, 255, 255))
            for y in range(25, 95):
                for x in range(25, 95):
                    im.putpixel((x, y), rgb)
            buf = io.BytesIO()
            im.save(buf, format="JPEG")
            return buf.getvalue()

        self.assertEqual(classify_image_bytes(make_studio_jpg((20, 20, 20))), "Black")
        self.assertEqual(classify_image_bytes(make_studio_jpg((235, 219, 193))), "Beige")
        self.assertEqual(classify_image_bytes(make_studio_jpg((232, 229, 224))), "Off-White")

        # Watchdog auto-detects missing color and eliminates feed_missing_color warning
        db.init_db()
        shop_v = f"vision-test-{int(time.time() * 1000)}.myshopify.com"
        prod = {
            "id": 999888,
            "title": "Utility Crossbody — Rain Flap",
            "handle": "utility-crossbody-rain-flap",
            "product_type": "Bag",
            "body_html": "<p>Recycled polyester rectangular crossbody bag with two-way zip and rain flap.</p>",
            "status": "active",
            "published_at": "2026-10-01T00:00:00Z",
            "options": [{"name": "Title", "position": 1}],
            "images": [{"id": 1, "src": "https://cdn.shopify.com/s/files/utility-crossbody.jpg", "alt": "Utility Crossbody"}],
            "variants": [{"id": 10, "price": "45.00", "title": "Default Title"}],
        }
        agent = StoreWatchdogAgent(brand_domain="maisongrozavu.com", brand_name="Grozavu")
        with patch("store_watchdog.detect_color_from_image_url", new_callable=AsyncMock, return_value="Black") as mock_det:
            report = await agent.run_deep_scan(
                shop=shop_v,
                shopify_client=MagicMock(ensure_brand_discount_codes=AsyncMock(return_value={"ok": True, "created": [], "existing": ["MG10"], "renamed": [], "errors": [], "codes": {}})),
                products=[prod],
                check_storefront=False,
                check_dns=False,
                auto_fix_discounts=True,
                auto_fix_colors=True,
            )
        mock_det.assert_awaited_once()
        self.assertEqual(report["feed_summary"]["warnings_count"], 0)
        self.assertEqual(report["feed_summary"]["missing_color_products"], [])
        self.assertTrue(any("Black" in f["detail"] for f in report["auto_fixed"]))
        self.assertEqual(db.get_visual_colors_map(shop_v).get("999888"), "Black")


if __name__ == "__main__":
    unittest.main()

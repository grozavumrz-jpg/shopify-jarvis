"""
Nov 19 upgrades:
  1. Truthful Jarvis: feed colours from the owner's Category metafields, honest GEO score,
     no invented search phrases / competitor prices / material claims, web search that never
     pretends, bot filter worded as an estimate.
  2. Learning: subject A/B tests with real sales attribution, best sending hours from GA4.
  4. Weekly market report with sources: prices kept only from cited pages, verified on the page.
"""
import asyncio
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
for p in (PROJECT_ROOT, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from tests.auth_helpers import AUTH_HEADERS
except ImportError:
    from auth_helpers import AUTH_HEADERS

import ai_advisor
import database as db
import experiments
import main
import market_intel
import post_delivery_service as pds
import visibility_engine as vis
from google_analytics_service import GoogleTrafficService
from google_merchant_feed import build_feed_items
from growth_studio import _match_products_for_keyword, build_competitor_radar
from mobile_notifier import MobileNotifier
from starlette.testclient import TestClient


def _product(pid=1, title="Oversized Heavyweight Tee", attrs=None, images=None, **extra):
    p = {
        "id": pid, "title": title, "handle": f"p-{pid}", "status": "active",
        "published_at": "2026-10-01T00:00:00Z", "product_type": "T-Shirt",
        "body_html": "<p>A tee.</p>",
        "images": images if images is not None else [{"id": 9, "src": f"https://cdn.shopify.com/tee-{pid}-black.jpg"}],
        "variants": [{"id": pid * 10, "price": "45.00", "title": "M", "option1": "M"}],
        "options": [{"name": "Size", "position": 1}],
    }
    if attrs is not None:
        p["_category_attrs"] = attrs
    p.update(extra)
    return p


# ═════════════════════════════ 1. Truthful Jarvis ═══════════════════════════

class TestFeedUsesOwnerCategoryMetafields(unittest.IsolatedAsyncioTestCase):
    def test_color_gender_age_material_from_metafields(self):
        items, _ = build_feed_items([
            _product(1, attrs={"colors": ["Off-white", "White"], "fabrics": ["Cotton"], "genders": ["Male"],
                               "age_groups": ["Adults"]}),
            _product(2, title="Kids Tee", attrs={"colors": ["Black"], "genders": ["Female", "Male"],
                                                 "age_groups": ["Kids"]}),
        ], shop_domain="maisongrozavu.com", brand="Grozavu")
        a, b = items
        self.assertEqual(a["color"], "Off-white/White")      # metafield beats the "-black" image filename
        self.assertEqual(a["gender"], "male")
        self.assertEqual(a["age_group"], "adult")
        self.assertEqual(a["material"], "Cotton")
        self.assertEqual(b["gender"], "unisex")               # Male + Female in the metafield
        self.assertEqual(b["age_group"], "kids")

    def test_without_metafields_old_fallbacks_still_work(self):
        items, _ = build_feed_items([_product(3)], shop_domain="maisongrozavu.com", brand="Grozavu")
        self.assertEqual(items[0]["color"], "Black")         # from the image filename, as before

    async def test_watchdog_never_guesses_from_photo_when_metafield_exists(self):
        from store_watchdog import StoreWatchdogAgent
        agent = StoreWatchdogAgent(brand_domain="maisongrozavu.com", brand_name="Grozavu")
        prod = _product(4, images=[{"id": 1, "src": "https://cdn.shopify.com/s/files/plain.jpg"}],
                        attrs={"colors": ["Navy"]})
        with patch("store_watchdog.detect_color_from_image_url", new_callable=AsyncMock, return_value="Black") as det:
            report = await agent.run_deep_scan(shop=f"wd-{time.time_ns()}.myshopify.com", shopify_client=None,
                                               products=[prod], check_storefront=False, check_dns=False,
                                               auto_fix_discounts=False)
        det.assert_not_called()
        self.assertEqual(report["scans_completed"] >= 1, True)


class TestHonestGeoScore(unittest.IsolatedAsyncioTestCase):
    def test_prompts_never_contain_the_brand(self):
        prompts = vis.build_geo_prompts([_product(5, title="Heavyweight Hoodie")], None)
        self.assertTrue(prompts)
        for p in prompts:
            self.assertNotRegex(p.lower(), r"grozavu")

    async def test_brand_knowledge_answer_is_excluded_from_the_score(self):
        class FakeAI:
            def _get_api_key(self):
                return "AIzaTestKey1234567890"

            async def _call_gemini(self, prompt, **kw):
                if "grozavu" in prompt.lower():
                    return "Grozavu is a Spanish streetwear brand.\nBRANDS: Grozavu"
                return "Try Nude Project and Scuffers.\nBRANDS: Nude Project, Scuffers"

        shop = f"geo-{time.time_ns()}.myshopify.com"
        out = await vis.run_geo_test(shop, FakeAI(), [_product(6, title="Heavyweight Hoodie")], None, force=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["brand_mentioned_count"], 0)
        self.assertEqual(out["mention_rate_pct"], 0)          # before: the brand question counted as a hit
        self.assertTrue(out["brand_knowledge"]["excluded_from_score"])
        self.assertIn("Spanish streetwear", out["brand_knowledge"]["answer_excerpt"])

    def test_mentions_plan_without_gsc_uses_a_placeholder_not_a_fake_query(self):
        plan = vis.build_mentions_plan([_product(7)], None)
        self.assertEqual(plan["top_query_source"], "placeholder_no_gsc_data")
        blob = str(plan)
        self.assertNotIn("pernera ancha", blob)
        self.assertIn("Search Console", blob)


class TestCompetitorRadarOnlySourcedPrices(unittest.TestCase):
    def test_no_hard_coded_brand_prices(self):
        radar = build_competitor_radar([_product(8)], None)
        blob = str(radar)
        for brand in ("Zara", "Nude Project", "Represent", "Fear of God", "pernera ancha"):
            self.assertNotIn(brand, blob)
        tees = next(c for c in radar["categories"] if c["key"] == "tshirts")
        self.assertIsNone(tees["market_reference"])
        self.assertIn("Fără prețuri verificate", tees["positioning_label"])

    def test_only_verified_prices_count(self):
        report = {"generated_at": "2026-11-19T08:00:00Z", "categories": {"tshirts": {"observations": [
            {"brand": "A", "product": "Tee A", "price": 50.0, "url": "https://a.es/p", "verified": True},
            {"brand": "B", "product": "Tee B", "price": 60.0, "url": "https://b.es/p", "verified": True},
            {"brand": "C", "product": "Tee C", "price": 70.0, "url": "https://c.es/p", "verified": True},
            {"brand": "D", "product": "Tee D", "price": 999.0, "url": "https://d.es/p", "verified": False},
        ]}}}
        radar = build_competitor_radar([_product(9)], None, market_report=report)
        tees = next(c for c in radar["categories"] if c["key"] == "tshirts")
        ref = tees["market_reference"]
        self.assertEqual((ref["min"], ref["max"], ref["median"], ref["verified_prices"]), (50.0, 70.0, 60.0, 3))
        self.assertIn("Sub mediana", tees["positioning_label"])   # store avg 45 < 0.85 * 60
        self.assertEqual(radar["market_report_as_of"], "2026-11-19T08:00:00Z")

    def test_unrelated_products_are_never_used(self):
        self.assertEqual(_match_products_for_keyword("bucket hat", [_product(10, title="Boxy Tee")]), [])

    def test_catalog_ideas_are_labelled_as_ideas(self):
        radar = build_competitor_radar([_product(11, title="Bordeaux Tartan Hoodie")], None)
        kw = radar["campaign_keywords"][0]
        self.assertEqual(kw["source"], "catalog_title")
        self.assertEqual(kw["keyword"], "Bordeaux Tartan Hoodie")
        self.assertIn("nu e o căutare reală", kw["badge"])


class TestHonestAdvisor(unittest.IsolatedAsyncioTestCase):
    def test_web_search_only_for_outside_information(self):
        f = ai_advisor.AIAdvisor._should_use_web_search
        for msg in ("Cum merge magazinul online în 2026?", "Ce produse streetwear am vândut?",
                    "Scrie-mi o descriere pentru varianta neagră", "Fă-mi un plan SEO pentru vară"):
            self.assertFalse(f(msg), msg)
        for msg in ("Ce trenduri sunt acum?", "caută pe google prețuri hanorace", "/web hoodies",
                    "Cât costă la concurență un hanorac?", "Ce face Nude Project?"):
            self.assertTrue(f(msg), msg)

    async def test_reply_warns_when_search_did_not_happen(self):
        def handler(request):
            body = request.content.decode()
            if '"tools"' in body:
                return httpx.Response(400, json={"error": {"message": "tools not supported"}})
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Hanoracele costă între 90 și 160 EUR în Europa."}]}}]})

        transport = httpx.MockTransport(handler)
        real = httpx.AsyncClient
        advisor = ai_advisor.AIAdvisor()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaTestKey1234567890", "GEMINI_MODEL": "gemini-2.5-flash"}), \
             patch.object(ai_advisor.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw)):
            res = await advisor.chat_detailed(shop_name="Grozavu", snapshot={"connected": True}, history=[],
                                              message="/web prețuri concurență hanorace", lang="ro")
        self.assertFalse(res["web_grounded"])
        self.assertIn("Căutarea pe internet nu a funcționat", res["reply"])

    def test_offline_ad_copy_has_no_generalized_material_claim(self):
        blob = str(ai_advisor.__dict__.get("__file__"))
        with open(ai_advisor.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("Heavyweight combed cotton fleece", src)
        self.assertNotIn("Algodón peinado de alto gramaje", src)
        del blob


class TestBotFilterIsAnEstimate(unittest.TestCase):
    def test_wording(self):
        gsc = {"connected": False}
        ga4 = {"connected": True, "summary": {"sessions": 1000, "engagement_rate": 20.0},
               "channels": [{"channel": "Direct", "sessions": 800}, {"channel": "Organic Search", "sessions": 200}],
               "countries": []}
        tq = GoogleTrafficService.analyze_traffic_quality(gsc, ga4)
        self.assertTrue(tq["bot_alert"])
        self.assertIn("estimare", tq["bot_summary_ro"])
        self.assertIn("estimare", tq["alerts"][0]["title"])
        ctx = GoogleTrafficService.to_prompt_context({"traffic_quality": tq, "search_console": gsc, "analytics": ga4})
        self.assertNotIn("BOT INFLATION DETECTED", ctx)


# ═════════════════════════════ 2. Learning ══════════════════════════════════

class TestSubjectAbTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        experiments._STATS_CACHE.clear()
        self.shop = f"ab-{time.time_ns()}.myshopify.com"

    def tearDown(self):
        experiments._STATS_CACHE.clear()

    def test_split_is_stable_and_balanced(self):
        emails = [f"user{i}@example.es" for i in range(400)]
        first = [experiments.choose_variant(self.shop, "vip", e) for e in emails]
        again = [experiments.choose_variant(self.shop, "vip", e) for e in emails]
        self.assertEqual(first, again)
        share_b = first.count("B") / len(first)
        self.assertTrue(0.4 < share_b < 0.6, share_b)

    def test_no_winner_without_enough_data(self):
        ev = experiments.evaluate_kind([{"variant": "A", "sends": 10, "conversions": 0, "revenue": 0},
                                        {"variant": "B", "sends": 10, "conversions": 4, "revenue": 200}])
        self.assertIsNone(ev["winner"])
        self.assertIn("Se strâng date", ev["status_ro"])

    def test_winner_with_enough_data_then_90_10(self):
        ev = experiments.evaluate_kind([{"variant": "A", "sends": 200, "conversions": 2, "revenue": 90},
                                        {"variant": "B", "sends": 200, "conversions": 16, "revenue": 900}])
        self.assertEqual(ev["winner"], "B")
        with patch.object(experiments, "_stats", return_value={"vip": [
                {"variant": "A", "sends": 200, "conversions": 2, "revenue": 90},
                {"variant": "B", "sends": 200, "conversions": 16, "revenue": 900}]}):
            picks = [experiments.choose_variant(self.shop, "vip", f"u{i}@x.es") for i in range(500)]
        self.assertTrue(0.85 < picks.count("B") / 500 < 0.95)

    def test_sale_is_attributed_once_and_refunds_never_count(self):
        now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
        experiments.record_send(self.shop, "vip", "B", "Ana@Test.es", "es", now - timedelta(days=2))
        order = {"id": 501, "email": "ana@test.es", "created_at": now.isoformat(), "total_price": "79.00"}
        self.assertEqual(experiments.attribute_order(self.shop, order), {"kind": "vip", "variant": "B"})
        self.assertIsNone(experiments.attribute_order(self.shop, order))            # same order again
        refunded = {"id": 502, "email": "ana@test.es", "created_at": now.isoformat(),
                    "total_price": "79.00", "financial_status": "refunded"}
        self.assertIsNone(experiments.attribute_order(self.shop, refunded))
        late = {"id": 503, "email": "bob@test.es", "created_at": now.isoformat(), "total_price": "50"}
        experiments.record_send(self.shop, "vip", "A", "bob@test.es", "es", now - timedelta(days=10))
        self.assertIsNone(experiments.attribute_order(self.shop, late))            # outside the 7-day window
        rep = experiments.learning_report(self.shop)
        vip = next(t for t in rep["tests"] if t["kind"] == "vip")
        self.assertEqual(vip["variants"]["B"]["conversions"], 1)
        self.assertEqual(vip["variants"]["B"]["revenue"], 79.0)

    def test_gdpr_redact_deletes_test_rows(self):
        experiments.record_send(self.shop, "winback", "A", "gone@test.es", "es")
        res = db.redact_customer(self.shop, email="gone@test.es")
        self.assertEqual(res["deleted"].get("email_experiments"), 1)

    def test_b_subjects_exist_for_all_languages_and_keep_the_real_code(self):
        for lang in ("ro", "es", "en", "it", "de", "fr"):
            self.assertIn("MGVIP15", experiments.vip_subject_b(lang, "Ana", "MGVIP15"))
            self.assertIn("MGVIP15", experiments.winback_subject_b(lang, "", "MGVIP15", "Grozavu"))
            self.assertIn("Grozavu", experiments.cart_stage1_subject_b(lang, "Grozavu"))
            self.assertNotRegex(experiments.cart_stage1_subject_b(lang, "Grozavu"), r"\d+ ?%")


class TestBestSendingHours(unittest.TestCase):
    def tearDown(self):
        experiments.set_best_hours({"hours": [], "computed_at": None})

    def test_too_little_data_means_no_restriction(self):
        res = experiments.compute_best_hours({"days": 28, "hours": [{"hour": 19, "sessions": 20, "engaged_sessions": 10}]})
        self.assertEqual(res["hours"], [])
        experiments.set_best_hours(res)
        self.assertTrue(experiments.is_good_send_hour(datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)))

    def test_best_hours_only_inside_allowed_window(self):
        rows = [{"hour": h, "sessions": 100, "engaged_sessions": (300 if h in (22, 23) else 10 * h)} for h in range(24)]
        res = experiments.compute_best_hours({"days": 28, "hours": rows})
        self.assertEqual(res["hours"], [17, 18, 19, 20])     # 22-23 are quiet hours: never chosen
        experiments.set_best_hours(res)
        self.assertTrue(experiments.is_good_send_hour(datetime(2026, 11, 19, 17, 30, tzinfo=timezone.utc)))   # 18:30 Madrid
        self.assertFalse(experiments.is_good_send_hour(datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)))   # 11:00 Madrid

    def test_thank_you_and_reminder_wait_for_good_hours(self):
        experiments.set_best_hours({"hours": [19], "computed_at": time.time()})
        svc = pds.PostDeliveryService()
        noon = datetime(2026, 11, 19, 11, 0, tzinfo=timezone.utc)      # 12:00 Madrid
        with patch.object(db, "get_due_post_delivery_automations") as due, \
             patch.object(db, "get_due_winback_candidates") as wb:
            self.assertEqual(svc.process_due_vip_automations("x.myshopify.com", {"a": 1}, noon), 0)
            self.assertEqual(svc.process_winback_automations("x.myshopify.com", {"a": 1}, noon), 0)
        due.assert_not_called()
        wb.assert_not_called()


# ═════════════════════════════ 4. Market report with sources ════════════════

class TestMarketIntel(unittest.IsolatedAsyncioTestCase):
    def test_price_parsing_and_page_check(self):
        rows = market_intel.parse_price_lines(
            "PRICE | Nude Project | Boxy Tee | 59,95 | EUR | https://nudeproject.com/products/boxy-tee\n"
            "PRICE | Grozavu | Tee | 45 | EUR | https://maisongrozavu.com/products/tee\n"
            "PRICE | X | Y | about 50 | EUR | https://x.es/p\n"
            "random text")
        self.assertEqual(len(rows), 1)                    # own brand and non-numeric price dropped
        self.assertEqual(rows[0]["price"], 59.95)
        self.assertTrue(market_intel.price_on_page('<span class="price">59,95 €</span>', 59.95))
        self.assertTrue(market_intel.price_on_page('"price":"60.00"', 60.0))
        self.assertTrue(market_intel.price_on_page("€60", 60.0))
        self.assertFalse(market_intel.price_on_page("160,00 €", 60.0))
        self.assertFalse(market_intel.price_on_page("59.951", 59.95))

    async def test_only_cited_pages_and_verified_prices(self):
        class FakeAI:
            def _get_api_key(self):
                return "AIzaTestKey1234567890"

            async def _call_gemini(self, prompt, grounding_out=None, **kw):
                grounding_out.update({"web_grounded": True, "search_queries": ["boxy tee price"], "sources": [
                    {"title": "nudeproject.com", "url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/1"},
                    {"title": "scuffers.com", "url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/2"},
                ]})
                return ("PRICE | Nude Project | Boxy Tee | 59,95 | EUR | https://www.nudeproject.com/products/boxy-tee\n"
                        "PRICE | Scuffers | Tee | 65 | EUR | https://scuffers.com/en/tee\n"
                        "PRICE | Invented | Tee | 10 | EUR | https://not-in-search.example/tee\n")

        pages = {
            "https://www.nudeproject.com/products/boxy-tee": "<html>no price in html</html>",
            "https://www.nudeproject.com/products/boxy-tee.json": '{"variants":[{"price":"59.95"}]}',
            "https://scuffers.com/en/tee": "<html>Price 75,00 €</html>",
        }

        async def fake_fetch(url):
            return pages.get(url)

        res = await market_intel.collect_competitor_prices(FakeAI(), "tshirts", "T-Shirts & Tops", fetch=fake_fetch)
        self.assertEqual(res["dropped_uncited"], 1)                 # not among Google's results -> dropped
        by_brand = {o["brand"]: o for o in res["observations"]}
        self.assertTrue(by_brand["Nude Project"]["verified"])        # found via the Shopify product JSON
        self.assertFalse(by_brand["Scuffers"]["verified"])           # page shows another price
        self.assertTrue(all(o.get("checked_at") and o.get("url") for o in res["observations"]))

    async def test_trends_need_a_cited_source(self):
        class FakeAI:
            async def _call_gemini(self, prompt, grounding_out=None, **kw):
                grounding_out.update({"web_grounded": True, "sources": [{"title": "vogue.es", "url": "https://vertexaisearch.cloud.google.com/x"}]})
                return ("TREND | Gorpcore | Outdoor gear worn in the city. | https://www.vogue.es/moda/gorpcore\n"
                        "TREND | Fake | Nothing. | https://made-up.example/a\n")
        res = await market_intel.collect_trends(FakeAI(), now=datetime(2026, 11, 19, tzinfo=timezone.utc))
        self.assertEqual([t["trend"] for t in res["trends"]], ["Gorpcore"])

    async def test_no_gemini_key_no_report(self):
        class NoKey:
            def _get_api_key(self):
                return ""
        res = await market_intel.build_market_report(NoKey(), [], None)
        self.assertFalse(res["ok"])

    async def test_failed_research_explains_why(self):
        class SlowAI:
            def _get_api_key(self):
                return "AIzaTestKey1234567890"

            async def _call_gemini(self, prompt, **kw):
                assert kw.get("timeout") == market_intel.RESEARCH_TIMEOUT
                raise RuntimeError("Gemini unavailable (ReadTimeout)")
        res = await market_intel.build_market_report(SlowAI(), [_product(12)], None)
        self.assertFalse(res["ok"])
        self.assertIn("ReadTimeout", res["message"])

    def test_refresh_while_running_does_not_lock_the_button(self):
        shop = "grozavushop.myshopify.com"
        client = TestClient(main.app, headers=AUTH_HEADERS)
        main._MARKET_REPORT_LAST_MANUAL.pop(shop, None)
        main._MARKET_REPORT_RUNNING[shop] = True
        try:
            r = client.post("/api/market/report/refresh", json={"shop": shop}).json()
        finally:
            main._MARKET_REPORT_RUNNING.pop(shop, None)
        self.assertEqual(r["error"], "already_running")
        self.assertNotIn(shop, main._MARKET_REPORT_LAST_MANUAL)

    async def test_private_hosts_are_never_fetched(self):
        self.assertFalse(await market_intel._is_public_host("localhost"))
        self.assertFalse(await market_intel._is_public_host("127.0.0.1"))
        self.assertFalse(await market_intel._is_public_host("10.0.0.5"))
        self.assertIsNone(await market_intel.fetch_page_text("http://example.com/insecure"))

    def test_staleness_and_storage(self):
        db.init_db()
        shop = f"mr-{time.time_ns()}.myshopify.com"
        self.assertTrue(market_intel.report_is_stale(None))
        fresh = {"ok": True, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "categories": {}}
        self.assertFalse(market_intel.report_is_stale(fresh))
        old = dict(fresh, generated_at="2026-01-01T00:00:00Z")
        self.assertTrue(market_intel.report_is_stale(old, now=datetime(2026, 11, 19, tzinfo=timezone.utc)))
        db.save_market_report(shop, old)
        db.save_market_report(shop, fresh)
        self.assertEqual(db.get_latest_market_report(shop)["generated_at"], fresh["generated_at"])

    def test_telegram_message(self):
        data = market_intel.telegram_summary({"generated_at": "2026-11-19T08:00:00Z", "prices_found": 3,
                                              "prices_verified": 2, "categories": {"tshirts": {"label": "T-Shirts", "observations": [
                                                  {"price": 50.0, "verified": True}, {"price": 70.0, "verified": True}]}},
                                              "trends": [{"trend": "Gorpcore"}], "search_console": {"connected": False}})
        text = MobileNotifier().format_telegram_message("market_report", data)
        self.assertIn("2026-11-19", text)
        self.assertIn("T-Shirts: 50–70 EUR (2 prețuri verificate)", text)
        self.assertIn("Gorpcore", text)

    def test_endpoints_require_auth(self):
        unauth = TestClient(main.app)
        self.assertEqual(unauth.get("/api/market/report").status_code, 401)
        self.assertEqual(unauth.post("/api/market/report/refresh", json={}).status_code, 401)
        self.assertEqual(unauth.get("/api/learning/report").status_code, 401)
        authed = TestClient(main.app, headers=AUTH_HEADERS)
        lr = authed.get("/api/learning/report")
        self.assertEqual(lr.status_code, 200)
        self.assertEqual({t["kind"] for t in lr.json()["tests"]}, {"cart_stage_1", "vip", "winback"})


if __name__ == "__main__":
    unittest.main()

"""
W2 truth tests: shopify_api, ai_advisor, seo_optimizer, deliverability_checker.

Every HTTP call is served by httpx.MockTransport — no real network. The default handler for
each test raises ConnectError so an unexpected real request can never leave the machine.
"""
import os
import re
import sys
import json
import types
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

import httpx

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import shopify_api  # noqa: E402
import ai_advisor  # noqa: E402
import seo_optimizer  # noqa: E402
import deliverability_checker as dc  # noqa: E402
from shopify_api import ShopifyClient, extract_marketing_consent, parse_next_page_info  # noqa: E402
from ai_advisor import AIAdvisor, parse_goal_message, parse_amount, get_gemini_models  # noqa: E402
from seo_optimizer import ProductSEOOptimizer  # noqa: E402
from deliverability_checker import DeliverabilityChecker, DNSLookupError, parse_txt_data  # noqa: E402

_OrigAsyncClient = httpx.AsyncClient
SHOP = "grozavu-test.myshopify.com"


class Recorder:
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return self.handler(request)


def mock_http(handler):
    """Patch httpx.AsyncClient so every client uses MockTransport(handler)."""
    rec = Recorder(handler)

    class _Client(_OrigAsyncClient):
        def __init__(self, *a, **kw):
            kw.pop("transport", None)
            super().__init__(*a, transport=httpx.MockTransport(rec), **kw)

    return patch("httpx.AsyncClient", _Client), rec


def _no_network(request):
    raise httpx.ConnectError("network disabled in tests", request=request)


class NoNetworkMixin:
    def start_no_network(self):
        p, self.blocked = mock_http(_no_network)
        p.start()
        self.addCleanup(p.stop)


# ═════════════════════════════ shopify_api ═══════════════════════════════════

class TestShopifyHttpCore(NoNetworkMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.start_no_network()
        self.sleep = AsyncMock()
        p = patch.object(shopify_api, "_sleep", self.sleep)
        p.start()
        self.addCleanup(p.stop)

    def test_api_version_default_and_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHOPIFY_API_VERSION", None)
            self.assertIn("/admin/api/2026-07", ShopifyClient(SHOP, "t").base)
        with patch.dict(os.environ, {"SHOPIFY_API_VERSION": "2026-10"}):
            self.assertIn("/admin/api/2026-10", ShopifyClient(SHOP, "t").base)

    async def test_429_retry_after_then_success(self):
        state = {"n": 0}

        def h(req):
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "2.0"}, text="Exceeded 2 calls per second")
            return httpx.Response(200, json={"shop": {"name": "Grozavu"}})

        p, rec = mock_http(h)
        with p:
            info = await ShopifyClient(SHOP, "t").get_shop_info()
        self.assertEqual(info["name"], "Grozavu")
        self.assertEqual(len(rec.requests), 2)
        self.sleep.assert_awaited_once_with(2.0)

    async def test_5xx_retried_three_times_then_http_exception(self):
        from fastapi import HTTPException
        p, rec = mock_http(lambda req: httpx.Response(503, text="unavailable"))
        with p:
            with self.assertRaises(HTTPException) as cm:
                await ShopifyClient(SHOP, "t").get_shop_info()
        self.assertEqual(cm.exception.status_code, 503)
        self.assertEqual(len(rec.requests), 4)  # 1 + 3 retries
        self.assertEqual(self.sleep.await_count, 3)

    async def test_401_not_retried(self):
        from fastapi import HTTPException
        p, rec = mock_http(lambda req: httpx.Response(401, text="Invalid API key or access token"))
        with p:
            with self.assertRaises(HTTPException) as cm:
                await ShopifyClient(SHOP, "t").get_shop_info()
        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(len(rec.requests), 1)
        self.sleep.assert_not_awaited()

    def test_parse_next_page_info(self):
        link = ('<https://s.myshopify.com/admin/api/2026-07/products.json?limit=250&page_info=prev1>; rel="previous", '
                '<https://s.myshopify.com/admin/api/2026-07/products.json?limit=250&page_info=next2>; rel="next"')
        self.assertEqual(parse_next_page_info(link), "next2")
        self.assertIsNone(parse_next_page_info('<https://x/products.json?page_info=p>; rel="previous"'))
        self.assertIsNone(parse_next_page_info(None))

    async def test_products_pagination_fields_and_archived_excluded(self):
        page1 = {"products": [{"id": 1, "title": "Hoodie", "status": "active"},
                              {"id": 2, "title": "Old", "status": "archived"}]}
        page2 = {"products": [{"id": 3, "title": "Boxy Tee", "status": "draft"}]}

        def h(req):
            if req.url.params.get("page_info") == "abc":
                return httpx.Response(200, json=page2)
            return httpx.Response(200, json=page1, headers={
                "Link": f'<https://{SHOP}/admin/api/2026-07/products.json?limit=250&page_info=abc>; rel="next"'})

        p, rec = mock_http(h)
        with p:
            products = await ShopifyClient(SHOP, "t").get_products(limit=250)
        self.assertEqual([x["id"] for x in products], [1, 3])
        self.assertEqual(len(rec.requests), 2)
        first, second = rec.requests
        self.assertEqual(first.url.params.get("fields"),
                         "id,title,handle,body_html,product_type,vendor,tags,status,published_at,options,variants,images,image")
        self.assertEqual(second.url.params.get("page_info"), "abc")
        self.assertNotIn("status", second.url.params)  # only limit/fields allowed with page_info
        self.assertIn("/admin/api/2026-07/products.json", str(first.url))

    async def test_active_products_uses_status_filter(self):
        p, rec = mock_http(lambda req: httpx.Response(200, json={"products": [{"id": 1, "title": "A", "status": "active"}]}))
        with p:
            res = await ShopifyClient(SHOP, "t").get_active_products()
        self.assertEqual(len(res), 1)
        self.assertEqual(rec.requests[0].url.params.get("status"), "active")

    async def test_pagination_stops_on_repeated_cursor(self):
        def h(req):
            return httpx.Response(200, json={"checkouts": [{"id": 1}]}, headers={
                "Link": f'<https://{SHOP}/admin/api/2026-07/checkouts.json?page_info=same>; rel="next"'})
        p, rec = mock_http(h)
        with p:
            res = await ShopifyClient(SHOP, "t").get_abandoned_checkouts()
        self.assertLessEqual(len(rec.requests), 2)
        self.assertGreaterEqual(len(res), 1)

    async def test_recent_orders_request_consent_fields_and_attach_consent(self):
        orders = {"orders": [{"id": 1, "buyer_accepts_marketing": True, "customer": {
            "email_marketing_consent": {"state": "subscribed"}, "sms_marketing_consent": None}}]}
        p, rec = mock_http(lambda req: httpx.Response(200, json=orders))
        with p:
            res = await ShopifyClient(SHOP, "t").get_recent_orders(days=2)
        fields = rec.requests[0].url.params.get("fields").split(",")
        for f in ("buyer_accepts_marketing", "customer", "email", "phone", "discount_codes", "test", "cancelled_at"):
            self.assertIn(f, fields)
        self.assertIs(res[0]["email_marketing_consent"], True)
        self.assertIsNone(res[0]["sms_marketing_consent"])

    async def test_fulfilled_orders_carry_consent(self):
        orders = {"orders": [{"id": 9, "buyer_accepts_marketing": False}]}
        p, rec = mock_http(lambda req: httpx.Response(200, json=orders))
        with p:
            res = await ShopifyClient(SHOP, "t").get_fulfilled_orders()
        self.assertIn("buyer_accepts_marketing", rec.requests[0].url.params.get("fields"))
        self.assertIs(res[0]["email_marketing_consent"], False)

    async def test_active_subscriptions_graphql(self):
        def h(req):
            self.assertTrue(str(req.url).endswith("/admin/api/2026-07/graphql.json"))
            body = json.loads(req.content)
            self.assertIn("activeSubscriptions", body["query"])
            return httpx.Response(200, json={"data": {"currentAppInstallation": {"activeSubscriptions": [
                {"id": "gid://shopify/AppSubscription/1", "name": "Jarvis Autonomous Pro", "status": "ACTIVE"}]}}})
        p, _ = mock_http(h)
        with p, patch.dict(os.environ, {"SHOPIFY_API_VERSION": "2026-07"}):
            subs = await ShopifyClient(SHOP, "t").get_active_subscriptions()
        self.assertEqual(subs, [{"id": "gid://shopify/AppSubscription/1", "name": "Jarvis Autonomous Pro", "status": "ACTIVE"}])

    async def test_active_subscriptions_errors_raise(self):
        p, _ = mock_http(lambda req: httpx.Response(200, json={"errors": [{"message": "Access denied"}]}))
        with p:
            with self.assertRaises(Exception):
                await ShopifyClient(SHOP, "t").get_active_subscriptions()

    async def test_create_subscription_top_level_errors_raise(self):
        c = ShopifyClient(SHOP, "t")
        c._graphql = AsyncMock(return_value={"errors": [{"message": "Access denied for appSubscriptionCreate"}]})
        with self.assertRaises(Exception):
            await c.create_app_subscription("https://x/return")

    def test_send_recovery_email_removed(self):
        self.assertFalse(hasattr(ShopifyClient, "send_recovery_email"))


class TestShopifySnapshotAndStock(NoNetworkMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.start_no_network()
        p = patch.object(shopify_api, "_sleep", AsyncMock())
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def _store_handler(customers_status=200):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        products = {"products": [
            {"id": 1, "title": "Boxy Tee", "status": "active", "variants": [
                {"id": 11, "title": "M", "price": "45.00", "inventory_quantity": 0, "inventory_management": None},
                {"id": 12, "title": "L", "price": "45.00", "inventory_quantity": 0, "inventory_management": "printful"}]},
            {"id": 2, "title": "Cap", "status": "active", "variants": [
                {"id": 21, "title": "Black", "price": "35.00", "inventory_quantity": 2, "inventory_management": "shopify"},
                {"id": 22, "title": "White", "price": "35.00", "inventory_quantity": 40, "inventory_management": "shopify"}]},
        ]}
        orders = {"orders": [
            {"id": 100, "created_at": now, "total_price": "80.00", "line_items": [{"title": "Cap", "quantity": 1}],
             "customer": {"id": 5, "first_name": "Ana"}},
            {"id": 101, "created_at": now, "total_price": "999.00", "test": True, "line_items": []},
            {"id": 102, "created_at": now, "total_price": "500.00", "cancelled_at": now, "line_items": []},
        ]}

        def h(req):
            path = req.url.path
            if path.endswith("/shop.json"):
                return httpx.Response(200, json={"shop": {"name": "Grozavu", "currency": "EUR"}})
            if path.endswith("/orders.json"):
                return httpx.Response(200, json=orders)
            if path.endswith("/checkouts.json"):
                return httpx.Response(200, json={"checkouts": [{"id": 7}, {"id": 8}]})
            if path.endswith("/products.json"):
                return httpx.Response(200, json=products)
            if path.endswith("/customers/count.json"):
                if customers_status != 200:
                    return httpx.Response(customers_status, text="forbidden")
                return httpx.Response(200, json={"count": 1})
            return httpx.Response(404, text="not mocked")
        return h

    async def test_snapshot_real_numbers_and_flags(self):
        p, _ = mock_http(self._store_handler())
        with p:
            snap = await ShopifyClient(SHOP, "t").get_store_snapshot()
        self.assertIs(snap["connected"], True)
        self.assertEqual(snap["data_source"], "shopify")
        self.assertEqual(snap["orders_30d"], 1)            # test + cancelled orders excluded
        self.assertEqual(snap["revenue_30d"], 80.0)
        self.assertEqual(snap["excluded_orders_30d"], 2)
        self.assertEqual(snap["abandoned_carts"], 2)
        self.assertEqual(snap["new_customers_24h"], 1)
        self.assertEqual([i["variant"] for i in snap["low_stock_items"]], ["Black"])  # only tracked
        self.assertEqual(snap["active_products_count"], 2)
        self.assertEqual(snap["avg_product_price"], 40.0)
        self.assertEqual(snap["unavailable"], {})

    async def test_snapshot_optional_failure_is_none_not_invented(self):
        p, _ = mock_http(self._store_handler(customers_status=403))
        with p:
            snap = await ShopifyClient(SHOP, "t").get_store_snapshot()
        self.assertIsNone(snap["new_customers_24h"])
        self.assertIn("new_customers_24h", snap["unavailable"])

    async def test_snapshot_core_failure_raises(self):
        from fastapi import HTTPException
        p, _ = mock_http(lambda req: httpx.Response(401, text="Invalid API key or access token"))
        with p:
            with self.assertRaises(HTTPException):
                await ShopifyClient(SHOP, "t").get_store_snapshot()

    def test_low_stock_ignores_untracked_print_on_demand(self):
        products = [{"id": 1, "title": "Hoodie", "status": "active", "variants": [
            {"title": "M", "inventory_quantity": 0, "inventory_management": None},
            {"title": "L", "inventory_quantity": 0},
            {"title": "XL", "inventory_quantity": -3, "inventory_management": "shopify"}]},
            {"id": 2, "title": "Draft", "status": "draft", "variants": [
                {"title": "S", "inventory_quantity": 0, "inventory_management": "shopify"}]}]
        low = ShopifyClient.low_stock_from_products(products, 5)
        self.assertEqual([(x["product"], x["variant"]) for x in low], [("Hoodie", "XL")])


class TestConsentExtraction(unittest.TestCase):
    def test_checkout_flags(self):
        self.assertEqual(extract_marketing_consent({"buyer_accepts_marketing": True}), (True, None))
        self.assertEqual(extract_marketing_consent({"buyer_accepts_marketing": False,
                                                    "buyer_accepts_sms_marketing": True}), (False, True))

    def test_unknown_is_none(self):
        self.assertEqual(extract_marketing_consent({}), (None, None))
        self.assertEqual(extract_marketing_consent({"customer": {}}), (None, None))
        self.assertEqual(extract_marketing_consent(None), (None, None))

    def test_customer_states(self):
        obj = {"customer": {"email_marketing_consent": {"state": "subscribed"},
                            "sms_marketing_consent": {"state": "unsubscribed"}},
               "buyer_accepts_sms_marketing": True}
        self.assertEqual(extract_marketing_consent(obj), (True, False))  # opt-out wins

    def test_opt_out_beats_checkout_checkbox(self):
        obj = {"buyer_accepts_marketing": True, "customer": {"email_marketing_consent": {"state": "unsubscribed"}}}
        self.assertEqual(extract_marketing_consent(obj)[0], False)

    def test_pending_and_not_subscribed_are_false(self):
        self.assertIs(extract_marketing_consent({"customer": {"email_marketing_consent": {"state": "pending"}},
                                                 "buyer_accepts_marketing": True})[0], False)
        self.assertIs(extract_marketing_consent({"customer": {"email_marketing_consent": {"state": "not_subscribed"}}})[0], False)

    def test_customer_object_and_idempotent_on_normalized(self):
        cust = {"email_marketing_consent": {"state": "subscribed"}, "sms_marketing_consent": {"state": "not_subscribed"}}
        self.assertEqual(extract_marketing_consent(cust), (True, False))
        normalized = {"email_marketing_consent": True, "sms_marketing_consent": None}
        self.assertEqual(extract_marketing_consent(normalized), (True, None))


class TestCheckoutDictConsentAndLanguage(unittest.IsolatedAsyncioTestCase):
    async def test_detailed_checkout_has_consent_keys(self):
        c = ShopifyClient(SHOP, "t")
        c._get = AsyncMock(return_value={"checkouts": [
            {"id": 1, "email": "a@b.es", "buyer_accepts_marketing": True, "line_items": []},
            {"id": 2, "email": "c@d.ro", "line_items": [], "customer": {"email_marketing_consent": {"state": "unsubscribed"}}},
            {"id": 3, "line_items": []},
        ]})
        res = await c.get_abandoned_checkouts_detailed()
        self.assertEqual([r["email_marketing_consent"] for r in res], [True, False, None])
        self.assertTrue(all("sms_marketing_consent" in r for r in res))
        self.assertEqual(c._get.call_count, 1)

    def test_french_names_map_to_fr(self):
        det = shopify_api.detect_customer_language_and_country
        self.assertEqual(det("Camille Dubois", "camille@gmail.com", "", "", "")["lang"], "fr")
        self.assertEqual(det("Pierre Durand", "", "", "", "")["lang"], "fr")
        self.assertEqual(det("Jordi Puig", "jordi@x.cat", "", "", "")["lang"], "es")


# ═════════════════════════════ ai_advisor ════════════════════════════════════

FAKE_NUMBERS_SNAPSHOT = {
    "connected": False, "data_error": "token invalid",
    "orders_30d": 128, "orders_today": 8, "revenue_30d": 19450.0, "revenue_today": 1240.0,
    "aov": 151.95, "abandoned_carts": 7, "returning_rate": 27.4,
    "vip_customers": [{"name": "Elena Popescu", "total_spent": 1420.0}],
}

CONNECTED_EMPTY = {
    "connected": True, "data_source": "shopify", "shop_name": "Grozavu", "currency": "EUR",
    "orders_30d": 0, "orders_today": 0, "revenue_30d": 0.0, "revenue_today": 0.0, "aov": 0.0,
    "abandoned_carts": 0, "new_customers_24h": 0, "total_unique_customers": 0, "repeat_customers": 0,
    "low_stock_items": [], "active_products_count": 14, "avg_product_price": 50.0, "unavailable": {},
}

BANNED = ["atelier", "mătase", "matase", "silk", "bucurești", "bucuresti", "unisex", "garantat",
          "garantează", "guaranteed", "s-a conectat la serverele google", "vrei să activăm", "rezervat", "reserved for",
          "6 ore", "6 hours", "4.9", "aggregaterating", "ron"]


def _banned_hits(text):
    low = text.lower()
    hits = []
    for b in BANNED:
        if b == "ron":
            if re.search(r"\bron\b", low):
                hits.append(b)
        elif b in low:
            hits.append(b)
    return hits


class AdvisorBase(NoNetworkMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.start_no_network()
        env = patch.dict(os.environ, {"GEMINI_API_KEY": "", "GEMINI_MODEL": ""})
        env.start()
        self.addCleanup(env.stop)
        self.ai = AIAdvisor()
        self.ai.api_key = ""
        p = patch.object(ai_advisor, "_real_sleep", AsyncMock())
        p.start()
        self.addCleanup(p.stop)


class TestBriefingTruth(AdvisorBase):
    async def test_disconnected_briefing_has_no_numbers_and_no_gemini(self):
        self.ai._call_gemini = AsyncMock(side_effect=AssertionError("must not call Gemini"))
        b = await self.ai.generate_briefing(FAKE_NUMBERS_SNAPSHOT, lang="ro")
        self.assertIsNone(b["health_score"])
        self.assertIs(b["connected"], False)
        self.assertIsNone(b["metrics"])
        self.assertIn("nu este conectat", b["summary"])
        dump = json.dumps(b, ensure_ascii=False)
        for n in ("128", "19450", "19,450", "1240", "151.95", "27.4", "Elena", "89", "88"):
            self.assertNotIn(n, dump)
        self.assertNotRegex(dump, r"\b7\b")
        self.ai._call_gemini.assert_not_called()

    async def test_missing_connected_flag_is_treated_as_no_data(self):
        snap = dict(FAKE_NUMBERS_SNAPSHOT)
        snap.pop("connected")
        b = await self.ai.generate_briefing(snap, lang="en")
        self.assertIs(b["connected"], False)
        self.assertNotIn("128", json.dumps(b))

    async def test_disconnected_briefing_respects_lang(self):
        b_es = await self.ai.generate_briefing({"connected": False}, lang="es")
        self.assertIn("no está conectado", b_es["summary"])
        b_en = await self.ai.generate_briefing({"connected": False}, lang="en")
        self.assertIn("not connected", b_en["summary"])

    async def test_connected_fallback_uses_only_real_numbers(self):
        b = await self.ai.generate_briefing(CONNECTED_EMPTY, lang="ro")  # no key => fallback
        self.assertIsNone(b["health_score"])
        self.assertEqual(b["source"], "fallback")
        self.assertIn("0 comenzi", b["summary"])
        self.assertEqual(b["metrics"]["orders_30d"], 0)
        dump = json.dumps(b, ensure_ascii=False)
        self.assertNotIn("7 coșuri", dump)
        self.assertNotIn("Recuperează cele", dump)
        self.assertEqual(b["alerts"], [])  # 0 carts, no low stock -> no alerts
        self.assertEqual(len(b["top_tasks"]), 3)
        self.assertTrue(all(isinstance(t, dict) and t.get("task") for t in b["top_tasks"]))
        self.assertEqual(_banned_hits(dump), [])

    async def test_carts_alert_uses_real_count(self):
        snap = dict(CONNECTED_EMPTY, abandoned_carts=3)
        b = await self.ai.generate_briefing(snap, lang="en")
        self.assertIn("3 abandoned checkouts", b["alerts"][0]["message"])

    async def test_gemini_output_validated(self):
        self.ai._call_gemini = AsyncMock(return_value=json.dumps({
            "health_score": 95, "greeting": "Hi", "top_tasks": "do everything now", "summary": "Revenue 99999 EUR"}))
        b = await self.ai.generate_briefing(CONNECTED_EMPTY, lang="en")
        self.assertIsNone(b["health_score"])
        self.assertIsInstance(b["top_tasks"], list)
        self.assertEqual(b["top_tasks"][0]["task"], "do everything now")
        self.assertNotIn("99999", b["summary"])  # summary is deterministic from data
        self.assertEqual(b["source"], "gemini")

    async def test_gemini_garbage_falls_back(self):
        self.ai._call_gemini = AsyncMock(return_value="not json at all")
        b = await self.ai.generate_briefing(CONNECTED_EMPTY, lang="en")
        self.assertEqual(b["source"], "fallback")
        self.assertTrue(all(isinstance(t, dict) for t in b["top_tasks"]))


class TestGeminiTransport(AdvisorBase):
    def _ok(self, text="Salut! Acesta este un răspuns de test suficient de lung."):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    async def test_key_in_header_not_url_and_default_model(self):
        p, rec = mock_http(lambda req: self._ok())
        with p, patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaTestKey1234567890"}):
            out = await self.ai._call_gemini("hello")
        self.assertTrue(out.startswith("Salut"))
        req = rec.requests[0]
        self.assertNotIn("key=", str(req.url))
        self.assertNotIn("AIzaTestKey1234567890", str(req.url))
        self.assertEqual(req.headers.get("x-goog-api-key"), "AIzaTestKey1234567890")
        self.assertIn("/models/gemini-2.5-flash:generateContent", str(req.url))

    async def test_model_fallback_order(self):
        def h(req):
            if "gemini-2.5-flash:" in str(req.url):
                return httpx.Response(404, json={"error": {"message": "model not found"}})
            return self._ok()
        p, rec = mock_http(h)
        with p, patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaTestKey1234567890"}):
            await self.ai._call_gemini("hello")
        models = [re.search(r"models/([^:]+):", str(r.url)).group(1) for r in rec.requests]
        self.assertEqual(models, ["gemini-2.5-flash", "gemini-flash-latest"])

    def test_env_model_first_and_no_retired_models(self):
        with patch.dict(os.environ, {"GEMINI_MODEL": "gemini-3-flash"}):
            self.assertEqual(get_gemini_models(), ["gemini-3-flash", "gemini-2.5-flash", "gemini-flash-latest"])
        with patch.dict(os.environ, {"GEMINI_MODEL": ""}):
            models = get_gemini_models()
        self.assertEqual(models, ["gemini-2.5-flash", "gemini-flash-latest"])
        self.assertNotIn("gemini-1.5-flash", models)
        self.assertNotIn("gemini-2.0-flash", models)

    async def test_missing_key_no_request_and_honest_chat(self):
        reply = await self.ai.chat("Grozavu", CONNECTED_EMPTY, [], "Salut, ce faci?", lang="ro")
        self.assertEqual(self.blocked.requests, [])
        self.assertIn("0 comenzi", reply)
        self.assertEqual(_banned_hits(reply), [])

    async def test_bad_key_raises_unavailable(self):
        p, rec = mock_http(lambda req: httpx.Response(403, json={"error": {"message": "API key not valid"}}))
        with p, patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaTestKey1234567890"}):
            with self.assertRaises(ai_advisor.GeminiUnavailable):
                await self.ai._call_gemini("hello")
        self.assertEqual(len(rec.requests), 1)


class TestChatTruth(AdvisorBase):
    async def test_disconnected_prompt_says_no_data(self):
        captured = {}

        async def fake(prompt, **kw):
            captured["prompt"] = prompt
            return "Nu am date despre magazin pentru că Shopify nu este conectat."
        self.ai._call_gemini = fake
        await self.ai.chat("Maison Grozavu", FAKE_NUMBERS_SNAPSHOT, [], "Cât am vândut luna asta?", lang="ro")
        prompt = captured["prompt"]
        self.assertIn("NO STORE DATA", prompt)
        self.assertIn("Do not invent", prompt)
        for n in ("128", "19450", "151.95", "Elena"):
            self.assertNotIn(n, prompt)
        self.assertIn("cannot change the store", prompt)
        self.assertIn("Romanian", prompt)

    async def test_lang_param_respected_even_for_grozavu_shop(self):
        r_en = await self.ai.chat("Maison Grozavu", {"connected": False}, [], "hello there", lang="en")
        self.assertIn("Shopify is not connected", r_en)
        r_es = await self.ai.chat("Maison Grozavu", {"connected": False}, [], "hola", lang="es")
        self.assertIn("Shopify no está conectado", r_es)

    async def test_offline_replies_never_fabricate_or_claim_actions(self):
        messages = [
            "De ce nu am vânzări azi și ce pot schimba rapid?",
            "Scrie-mi un script de TikTok",
            "Scrie un email de recuperare a coșurilor abandonate",
            "Fă un audit rapid de conversie",
            "Scrie un email VIP de fidelizare",
            "Secvență post-livrare cu recenzie",
            "Cum aduc trafic?",
            "Ce ofertă sau bundle să fac?",
            "Strategie SEO google",
            "Scrie-mi o reclama pentru facebook ads",
            "altceva",
            "/boost",
            "/browser hanorac oversize",
        ]
        for snap in (FAKE_NUMBERS_SNAPSHOT, CONNECTED_EMPTY):
            for m in messages:
                reply = await self.ai.chat("Maison Grozavu", snap, [], m, lang="ro")
                self.assertEqual(_banned_hits(reply), [], f"{m!r} -> {reply[:200]}")
                if snap is FAKE_NUMBERS_SNAPSHOT:
                    for n in ("128", "19450", "19,450", "151.95", "Elena"):
                        self.assertNotIn(n, reply, m)
        self.assertTrue(all("suggestqueries" in str(r.url) for r in self.blocked.requests))

    async def test_carts_count_never_defaults_to_seven(self):
        reply = await self.ai._autonomous_brain_reply("Grozavu", {}, "de ce nu am vanzari", "ro")
        self.assertNotRegex(reply, r"\b7 coșuri|cele 7|\(7 ")
        self.assertIn("necunoscut", reply)


class TestGoalParsing(AdvisorBase):
    def test_parse_decimals(self):
        self.assertEqual(parse_goal_message("/goal 2500.50 EUR")[0], 2500.5)
        self.assertEqual(parse_goal_message("/goal 2.500,50")[0], 2500.5)
        self.assertEqual(parse_goal_message("/goal 2,500.50")[0], 2500.5)
        self.assertEqual(parse_goal_message("/goal 25000")[0], 25000.0)
        self.assertEqual(parse_goal_message("/goal 2.500")[0], 2500.0)
        self.assertEqual(parse_goal_message("/goal 10k")[0], 10000.0)
        self.assertEqual(parse_goal_message("/goal 3000 lei")[2], "RON")
        self.assertEqual(parse_goal_message("/goal 3000 $")[2], "USD")
        self.assertEqual(parse_goal_message("/goal 2500 aov 65,5"), (2500.0, 65.5, None))
        self.assertIsNone(parse_amount("/goal"))

    async def test_goal_chat_decimal_and_aov(self):
        reply = await self.ai.chat("Grozavu", {"connected": False}, [], "/goal 2500.50 EUR aov 50", lang="ro")
        self.assertIn("2,500.50", reply)
        self.assertNotIn("250,050", reply)
        self.assertIn("51 / lună", reply)  # ceil(2500.5 / 50)

    async def test_goal_without_aov_asks_instead_of_inventing(self):
        reply = await self.ai.chat("Grozavu", {"connected": False}, [], "/goal 2500", lang="ro")
        self.assertIn("aov", reply.lower())
        self.assertNotIn("150", reply)
        self.assertNotIn("750", reply)

    def test_calculate_goal_requires_aov(self):
        g = self.ai.calculate_revenue_goal(10000, "EUR", None)
        self.assertIsNone(g["needed_orders"])
        self.assertEqual(g["aov_source"], "unavailable")
        g = self.ai.calculate_revenue_goal(15000.0, "EUR", 150.0, 30)
        self.assertEqual(g["needed_orders"], 100)
        self.assertEqual(g["scenarios"]["cr_2_0"]["total_visitors"], 5000)


class TestGoogleSuggest(AdvisorBase):
    async def test_failure_returns_empty_and_unavailable(self):
        res = await self.ai.fetch_google_suggest("hanorac oversize", "ro")
        self.assertEqual(res["results"], [])
        self.assertEqual(res["source"], "unavailable")
        self.assertEqual(await self.ai.fetch_live_google_trends("hanorac oversize"), [])

    async def test_http_error_returns_empty(self):
        p, _ = mock_http(lambda req: httpx.Response(503, text="no"))
        with p:
            res = await self.ai.fetch_google_suggest("hoodie")
        self.assertEqual((res["results"], res["source"]), ([], "unavailable"))

    async def test_success_real_results(self):
        p, rec = mock_http(lambda req: httpx.Response(200, json=["hoodie", ["hoodie oversize", "hoodie heavyweight"]]))
        with p:
            res = await self.ai.fetch_google_suggest("hoodie", "es")
        self.assertEqual(res["results"], ["hoodie oversize", "hoodie heavyweight"])
        self.assertEqual(res["source"], "google_suggest")
        self.assertEqual(rec.requests[0].url.params.get("hl"), "es")

    async def test_radar_reply_on_failure_has_no_invented_terms(self):
        reply = await self.ai.chat("Grozavu", CONNECTED_EMPTY, [], "/browser sacou catifea", lang="ro")
        self.assertIn("nu afișez sugestii inventate", reply)
        self.assertNotIn("bucuresti atelier", reply)
        self.assertNotIn("Date Reale de pe Servere Google", reply)


class TestGrowthIdeas(AdvisorBase):
    def test_seo_strategy_has_no_invented_metrics(self):
        seo = self.ai.generate_seo_strategy("Maison Grozavu", "maisongrozavu.com")
        self.assertEqual(seo["kind"], "ideas")
        self.assertTrue(seo["keywords"])
        for k in seo["keywords"]:
            self.assertIsNone(k["volume"])
            self.assertIsNone(k["cpc"])
            self.assertIsNone(k["difficulty"])
        self.assertIsNone(seo["json_ld"])  # no real products passed
        self.assertEqual(_banned_hits(json.dumps(seo, ensure_ascii=False)), [])

    def test_seo_strategy_json_ld_from_real_product_without_rating(self):
        prod = {"id": 5, "title": "Heavyweight Crewneck", "handle": "heavyweight-crewneck", "status": "active",
                "variants": [{"id": 1, "price": "69.00", "inventory_management": None}],
                "images": [{"src": "https://cdn.shopify.com/crew.jpg"}]}
        seo = self.ai.generate_seo_strategy("Grozavu", "maisongrozavu.com", products=[prod])
        ld = seo["json_ld"]
        self.assertEqual(ld["name"], "Heavyweight Crewneck")
        self.assertEqual(ld["offers"]["price"], "69.00")
        self.assertNotIn("aggregateRating", ld)
        self.assertNotIn("review", ld)

    def test_radar_and_boost_are_labelled_ideas_without_numbers(self):
        radar = self.ai.generate_lead_radar("Maison Grozavu")
        boost = self.ai.generate_boost_plan(FAKE_NUMBERS_SNAPSHOT, "Maison Grozavu")
        self.assertEqual(radar["kind"], "ideas")
        self.assertEqual(boost["kind"], "ideas")
        self.assertIn("Grozavu", radar["outreach_dm"])
        self.assertIsNone(boost["cart_bump"]["bump_price"])
        self.assertIsNone(boost["bundle"]["discount_pct"])
        self.assertIsNone(boost["abandoned_carts"])  # disconnected -> no number
        for obj in (radar, boost):
            self.assertEqual(_banned_hits(json.dumps(obj, ensure_ascii=False)), [])


class TestRecoveryCopy(AdvisorBase):
    CHECKOUT = {"customer_name": "Lucía", "items": ["Boxy Tee"], "checkout_url": "https://s/c/1",
                "detected_lang": "es", "detected_country": "Spania"}

    async def test_template_never_claims_reservation_or_scarcity(self):
        for lang in ("es", "ro", "en", "it", "de", "fr"):
            for code in ("MG10", None):
                r = await self.ai.generate_autonomous_recovery("Maison Grozavu", self.CHECKOUT, lang=lang, discount_code=code)
                text = " ".join([r["subject"], r["body"], r["whatsapp_message"]]).lower()
                for bad in ("reserv", "rezerv", "riservat", "réserv", "6 h", "6 ore", "6 ore", "stock", "stoc"):
                    self.assertNotIn(bad, text, f"{lang}/{code}: {bad}")
                self.assertIn("https://s/c/1", r["body"])
                self.assertEqual(code is not None, "mg10" in text, f"{lang}/{code}")
                self.assertIn("grozavu", text)
                self.assertNotIn("maison grozavu", text)

    async def test_prompt_forbids_reservation_claims(self):
        captured = {}

        async def fake(prompt, **kw):
            captured["p"] = prompt
            raise ai_advisor.GeminiUnavailable("x")
        self.ai._call_gemini = fake
        await self.ai.generate_autonomous_recovery("Grozavu", self.CHECKOUT, lang="es")
        self.assertIn("Do NOT say the items are reserved", captured["p"])
        self.assertNotIn("6 hours", captured["p"])
        self.assertIn("Spanish", captured["p"])


# ═════════════════════════════ seo_optimizer ═════════════════════════════════

def _sample_product():
    return {
        "id": 8123, "title": "Logo Hoodie Unisex", "handle": "logo-hoodie", "product_type": "Hoodies",
        "body_html": "<p>Hoodie.</p>", "status": "active",
        "variants": [
            {"id": 1, "title": "Black / M", "option1": "Black", "price": "65.00", "inventory_management": "shopify",
             "inventory_quantity": 0, "inventory_policy": "deny"},
            {"id": 2, "title": "Black / L", "option1": "Black", "price": "65.00", "inventory_management": "shopify",
             "inventory_quantity": 0, "inventory_policy": "deny"},
        ],
        "images": [{"id": 10, "src": "https://cdn.shopify.com/a.jpg", "alt": "", "variant_ids": [1]},
                   {"id": 11, "src": "https://cdn.shopify.com/b.jpg", "alt": None}],
    }


def _apply(product, proposals):
    p = json.loads(json.dumps(product))
    for prop in proposals:
        if prop["field"] == "title":
            p["title"] = prop["proposed"]
        elif prop["field"] == "seo_title":
            p["metafields_global_title_tag"] = prop["proposed"]
        elif prop["field"] == "seo_description":
            p["metafields_global_description_tag"] = prop["proposed"]
        elif prop["field"] == "image_alt":
            for img in p["images"]:
                if img["id"] == prop["image_id"]:
                    img["alt"] = prop["proposed"]
    return p


class TestSEOPreviewOnly(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.o = ProductSEOOptimizer()
        self.logged = []
        fake_db = types.SimpleNamespace(
            log_seo_change=lambda *a, **k: self.logged.append(a) or True,
            get_seo_logs=lambda shop, limit=50: [
                {"product_id": a[1], "change_type": a[3], "new_value": a[5], "status": a[6]} for a in self.logged],
        )
        p = patch.dict(sys.modules, {"database": fake_db})
        p.start()
        self.addCleanup(p.stop)

    async def test_optimize_and_apply_never_writes(self):
        client = MagicMock()
        res = await self.o.optimize_and_apply(client, _sample_product(), shop_domain=SHOP)
        self.assertEqual(client.mock_calls, [])
        self.assertFalse(res["applied"])
        self.assertTrue(res["preview_only"])
        self.assertEqual(res["changes_applied"], [])
        self.assertTrue(res["proposals"])
        self.assertTrue(self.logged)
        self.assertTrue(all(a[6] == "proposed" for a in self.logged))
        n = len(self.logged)
        await self.o.optimize_and_apply(client, _sample_product(), shop_domain=SHOP)
        self.assertEqual(len(self.logged), n)  # same proposals are not logged twice

    def test_module_has_no_write_path(self):
        src = open(seo_optimizer.__file__, encoding="utf-8").read()
        self.assertNotIn("_put", src)
        self.assertNotIn(".put(", src)
        self.assertNotIn(".post(", src)

    def test_proposals_shape_english_no_unisex(self):
        prev = self.o.propose_changes(_sample_product())
        self.assertEqual(set(["product_id", "title", "proposals"]) - set(prev), set())
        fields = [p["field"] for p in prev["proposals"]]
        self.assertIn("title", fields)
        self.assertIn("seo_title", fields)
        self.assertIn("seo_description", fields)
        self.assertEqual(fields.count("image_alt"), 2)
        for p in prev["proposals"]:
            self.assertEqual({"field", "current", "proposed", "reason"} - set(p), set())
            proposed = str(p["proposed"])
            self.assertNotIn("unisex", proposed.lower())
            self.assertEqual(seo_optimizer.contains_forbidden(proposed), [])
            for ro_word in ("Descoperă", "livrare", "România", "Creație", "țesătur"):
                self.assertNotIn(ro_word, proposed)
        seo_title = next(p["proposed"] for p in prev["proposals"] if p["field"] == "seo_title")
        self.assertEqual(seo_title.count("Grozavu"), 1)
        self.assertTrue(25 <= len(seo_title) <= 70, seo_title)
        desc = next(p["proposed"] for p in prev["proposals"] if p["field"] == "seo_description")
        self.assertLessEqual(len(desc), 160)
        self.assertIn("Designed in Spain".lower(), desc.lower())

    def test_idempotent(self):
        prod = _sample_product()
        first = self.o.propose_changes(prod)
        applied = _apply(prod, first["proposals"])
        second = self.o.propose_changes(applied)
        self.assertEqual(second["proposals"], [], second["proposals"])
        t = "Hoodie Logo Black"
        outs = set()
        for _ in range(4):
            t = self.o.generate_seo_title(t, "Hoodies")
            outs.add(t)
        self.assertEqual(len(outs), 1)
        self.assertEqual(t.count("Grozavu"), 1)
        legacy = "Rochie | Atelier Luxury | Maison Grozavu | Atelier Luxury | Maison Grozavu"
        self.assertEqual(self.o.generate_seo_title(legacy).count("Grozavu"), 1)
        self.assertNotIn("Atelier", self.o.generate_seo_title(legacy))

    def test_json_ld_real_data_only(self):
        ld = self.o.generate_json_ld_schema(_sample_product(), currency="EUR")
        self.assertNotIn("aggregateRating", ld)
        self.assertNotIn("review", ld)
        self.assertEqual(ld["offers"]["@type"], "AggregateOffer")
        self.assertEqual(ld["offers"]["availability"], "https://schema.org/OutOfStock")  # tracked, qty 0, deny
        self.assertEqual(ld["brand"]["name"], "Grozavu")
        self.assertEqual(ld["url"], "https://maisongrozavu.com/products/logo-hoodie")
        pod = {"id": 1, "title": "Tee", "variants": [{"price": "40.00", "inventory_management": None}]}
        ld2 = self.o.generate_json_ld_schema(pod, currency="RON")
        self.assertEqual(ld2["offers"]["availability"], "https://schema.org/InStock")
        self.assertEqual(ld2["offers"]["priceCurrency"], "RON")
        self.assertNotIn("image", ld2)  # no invented CDN image
        self.assertNotIn("url", ld2)    # no handle -> no invented URL
        ld3 = self.o.generate_json_ld_schema({"id": 2, "title": "No price"})
        self.assertNotIn("offers", ld3)  # no invented price

    def test_audit_does_not_penalize_unfetched_description(self):
        base = {"id": 1, "title": "Heavyweight Crewneck Black | Grozavu", "images": [{"src": "x", "alt": "Crewneck"}]}
        a = self.o.audit_product_seo(base)
        self.assertFalse(a["description_checked"])
        self.assertFalse(any("Descrierea produsului este sumară" in i for i in a["issues"]))
        b = self.o.audit_product_seo(dict(base, body_html=""))
        self.assertTrue(any("Descrierea produsului este sumară" in i for i in b["issues"]))
        self.assertLess(b["seo_score"], a["seo_score"])


# ═════════════════════════════ deliverability_checker ════════════════════════

LONG_KEY = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQ" + "A" * 180 + "IDAQAB"


def dns_side_effect(table):
    async def _q(name, rtype="TXT"):
        val = table.get((name, rtype), [])
        if isinstance(val, Exception):
            raise val
        return list(val)
    return _q


GOOD = {
    ("maisongrozavu.com", "TXT"): ["v=spf1 include:shops.shopify.com ~all", "google-site-verification=abc"],
    ("send.maisongrozavu.com", "TXT"): ["v=spf1 include:amazonses.com ~all"],
    ("send.maisongrozavu.com", "MX"): ["10 feedback-smtp.eu-west-1.amazonses.com"],
    ("resend._domainkey.maisongrozavu.com", "TXT"): [f"p={LONG_KEY}"],
    ("_dmarc.maisongrozavu.com", "TXT"): ["v=DMARC1; p=none; rua=mailto:info@maisongrozavu.com"],
}


class TestDeliverability(NoNetworkMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.start_no_network()

    async def _audit(self, table, domain="maisongrozavu.com"):
        d = DeliverabilityChecker()
        with patch.object(DeliverabilityChecker, "_query_records", side_effect=dns_side_effect(table)):
            return await d.audit_domain(domain)

    async def test_correct_resend_setup_is_ok(self):
        r = await self._audit(GOOD)
        self.assertEqual(r["score"], 100)
        self.assertEqual(r["color"], "green")
        self.assertTrue(r["complete"])
        for k in ("spf", "mx", "dkim", "dmarc", "root_spf"):
            self.assertEqual(r["checks"][k]["status"], "ok", k)
        self.assertEqual(r["records_to_add"], [])
        self.assertNotIn("garant", json.dumps(r, ensure_ascii=False).lower())
        self.assertNotIn("guarantee", json.dumps(r, ensure_ascii=False).lower())

    async def test_resend_spf_checked_on_send_subdomain(self):
        table = dict(GOOD)
        table[("maisongrozavu.com", "TXT")] = ["v=spf1 include:resend.com ~all"]
        table.pop(("send.maisongrozavu.com", "TXT"))
        r = await self._audit(table)
        self.assertEqual(r["checks"]["spf"]["status"], "missing")
        self.assertEqual(r["checks"]["spf"]["host"], "send.maisongrozavu.com")
        add = next(x for x in r["records_to_add"] if x.get("check") == "spf")
        self.assertEqual((add["type"], add["host"], add["value"]), ("TXT", "send", "v=spf1 include:amazonses.com ~all"))
        self.assertNotIn("include:resend.com", json.dumps(r["records_to_add"]))

    async def test_duplicate_spf_and_revoked_dkim_are_invalid(self):
        table = dict(GOOD)
        table[("send.maisongrozavu.com", "TXT")] = ["v=spf1 include:amazonses.com ~all", "v=spf1 include:x.com -all"]
        table[("maisongrozavu.com", "TXT")] = ["v=spf1 include:a.com ~all", "v=spf1 include:b.com -all"]
        table[("resend._domainkey.maisongrozavu.com", "TXT")] = ["p="]
        r = await self._audit(table)
        self.assertEqual(r["checks"]["spf"]["status"], "invalid")
        self.assertEqual(r["checks"]["root_spf"]["status"], "invalid")
        self.assertEqual(r["checks"]["dkim"]["status"], "invalid")
        self.assertLess(r["score"], 100)
        self.assertNotEqual(r["color"], "green")

    async def test_mx_and_dmarc_missing(self):
        table = dict(GOOD)
        table.pop(("send.maisongrozavu.com", "MX"))
        table.pop(("_dmarc.maisongrozavu.com", "TXT"))
        r = await self._audit(table)
        self.assertEqual(r["checks"]["mx"]["status"], "missing")
        self.assertEqual(r["checks"]["dmarc"]["status"], "missing")
        dmarc = next(x for x in r["records_to_add"] if x.get("check") == "dmarc")
        self.assertEqual(dmarc["value"], "v=DMARC1; p=none; rua=mailto:info@maisongrozavu.com")
        self.assertNotIn("contact@", json.dumps(r))
        self.assertEqual(r["score"], 65)

    async def test_dns_unreachable_is_unknown_not_missing(self):
        boom = DNSLookupError("all resolvers failed")
        table = {k: boom for k in GOOD}
        r = await self._audit(table)
        for k in ("spf", "mx", "dkim", "dmarc", "root_spf"):
            self.assertEqual(r["checks"][k]["status"], "unknown", k)
        self.assertIsNone(r["score"])
        self.assertEqual(r["missing_records"], [])
        self.assertEqual(r["records_to_add"], [])
        self.assertEqual(r["color"], "gray")

    async def test_other_domain_dmarc_has_no_brand_rua(self):
        r = await self._audit({}, domain="example.org")
        self.assertEqual(r["checks"]["dmarc"]["recommended_value"], "v=DMARC1; p=none;")

    async def test_invalid_domain_makes_no_queries(self):
        d = DeliverabilityChecker()
        with patch.object(DeliverabilityChecker, "_query_records", side_effect=AssertionError("no query")):
            r = await d.audit_domain("bad domain;rm -rf")
        self.assertEqual(r["error"], "invalid_domain")

    def test_multistring_txt_join(self):
        self.assertEqual(parse_txt_data('"v=spf1 include:amazonses.com" " ~all"'), "v=spf1 include:amazonses.com ~all")
        self.assertEqual(parse_txt_data('"p=MIGf" "AAAA"'), "p=MIGfAAAA")
        self.assertEqual(parse_txt_data("v=DMARC1; p=none"), "v=DMARC1; p=none")

    async def test_doh_parsing_nxdomain_and_failure(self):
        def h(req):
            name = req.url.params.get("name")
            if name == "send.maisongrozavu.com":
                return httpx.Response(200, json={"Status": 0, "Answer": [
                    {"type": 16, "data": '"v=spf1 include:amazonses.com" " ~all"'},
                    {"type": 5, "data": "alias.example."}]})
            if name == "_dmarc.maisongrozavu.com":
                return httpx.Response(200, json={"Status": 3})
            return httpx.Response(200, json={"Status": 2})  # SERVFAIL everywhere else
        p, rec = mock_http(h)
        d = DeliverabilityChecker()
        with p:
            self.assertEqual(await d._query_records("send.maisongrozavu.com", "TXT"), ["v=spf1 include:amazonses.com ~all"])
            self.assertEqual(await d._query_records("_dmarc.maisongrozavu.com", "TXT"), [])
            with self.assertRaises(DNSLookupError):
                await d._query_records("resend._domainkey.maisongrozavu.com", "TXT")
        self.assertTrue(all(r.headers.get("accept") == "application/dns-json" for r in rec.requests))

    async def test_resolvers_down_raise_lookup_error(self):
        d = DeliverabilityChecker()
        with self.assertRaises(DNSLookupError):
            await d._query_records("maisongrozavu.com", "TXT")
        self.assertEqual(len(self.blocked.requests), 2)


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for the Autonomous Sales & Traffic Growth Engine (Jarvis Brain)
Validates:
1. Resilient e-commerce chat under zero-config / offline Gemini API conditions.
2. The exact question from user screenshot: 'De ce nu am vânzări azi și ce pot schimba rapid?'
3. Slash commands: /boost, /browser, /goal.
4. Google SEO & Schema.org JSON-LD generation for Maison Grozavu.
5. Customer Hunter & Lead Radar (viral hooks, micro-influencer outreach DM).
6. Math-based revenue goal simulator.
7. /api/chat, /api/growth/seo, /api/growth/radar, /api/growth/boost, /api/growth/goal API routes.
8. Auto-provisioning and resilient store snapshot fallback for Maison Grozavu.
"""

import unittest
import httpx
from unittest.mock import patch, AsyncMock
import asyncio
import os
import sys

# Ensure backend is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ai_advisor import AIAdvisor
try:
    from tests.auth_helpers import AUTH_HEADERS, webhook_headers, auth_headers  # noqa: E402
except ImportError:  # running with tests/ as top-level dir
    from auth_helpers import AUTH_HEADERS, webhook_headers, auth_headers  # noqa: E402
import database as db
from main import app
from starlette.testclient import TestClient


FAKE_MARKERS = ("Elena", "Rochie", "19,450", "19450", "6 ore", "rezervat", "mătase", "Mătase", "atelier",
                "București", "unisex", "Quiet Luxury", "Silk")


class TestAutonomousSalesBrain(unittest.IsolatedAsyncioTestCase):
    """Chat/briefing helpers must be useful AND honest: real numbers only, no invented claims."""

    def setUp(self):
        os.environ.pop("GEMINI_API_KEY", None)  # offline replies, no network
        self.ai = AIAdvisor()
        self.connected = {
            "connected": True, "data_source": "shopify", "shop_name": "Grozavu",
            "orders_today": 0, "orders_30d": 0, "revenue_today": 0, "revenue_30d": 0,
            "currency": "EUR", "abandoned_carts": 2, "aov": 0, "low_stock_items": [], "vip_customers": [],
            "active_products_count": 59, "avg_product_price": 62.5,
        }
        self.disconnected = {"connected": False, "data_source": "none", "currency": "EUR"}

    def assertHonest(self, reply):
        self.assertTrue(reply and len(reply) > 40)
        for marker in FAKE_MARKERS:
            self.assertNotIn(marker, reply, f"invented/false content {marker!r} in reply")

    async def test_zero_sales_diagnosis_uses_real_numbers_only(self):
        query = "De ce nu am vânzări azi și ce pot schimba rapid?"
        reply = await self.ai.chat("Grozavu", self.connected, [], query, lang="ro")
        self.assertIn("Diagnostic Imediat Vânzări", reply)
        self.assertIn("Date reale Shopify", reply)
        self.assertIn("2 coșuri", reply)
        self.assertHonest(reply)

        reply_d = await self.ai.chat("Grozavu", self.disconnected, [], query, lang="ro")
        self.assertIn("Shopify nu este conectat", reply_d)
        self.assertHonest(reply_d)

    async def test_snapshot_without_connected_flag_is_not_trusted(self):
        legacy_fake = {"orders_30d": 128, "revenue_30d": 19450.0, "abandoned_carts": 7, "aov": 150.0}
        reply = await self.ai.chat("Grozavu", legacy_fake, [], "De ce nu am vânzări azi?", lang="ro")
        self.assertNotIn("128", reply)
        self.assertNotIn("7 coșuri", reply)
        self.assertHonest(reply)

    async def test_slash_commands_are_labelled_ideas(self):
        for cmd in ("/boost", "/browser", "/browser hanorac negru"):
            with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("offline")):
                reply = await self.ai.chat("Grozavu", self.connected, [], cmd, lang="ro")
            self.assertHonest(reply)
        with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("offline")):
            reply = await self.ai.chat("Grozavu", self.connected, [], "/browser hanorac negru", lang="ro")
        self.assertIn("hanorac negru", reply)
        self.assertIn("nu afișez sugestii inventate", reply)

    async def test_goal_needs_a_real_or_stated_aov(self):
        reply = await self.ai.chat("Grozavu", self.connected, [], "/goal 25000", lang="ro")
        self.assertIn("25,000", reply)
        self.assertIn("Ecuația Profitului", reply)
        self.assertIn("nu un AOV real", reply)  # avg product price is labelled as such
        reply_d = await self.ai.chat("Grozavu", self.disconnected, [], "/goal 25000", lang="ro")
        self.assertIn("aov", reply_d.lower())
        self.assertNotIn("Comenzi necesare", reply_d)

    def test_seo_strategy_never_invents_metrics_or_ratings(self):
        seo = self.ai.generate_seo_strategy("Grozavu", "maisongrozavu.com")
        self.assertGreaterEqual(len(seo["keywords"]), 5)
        for kw in seo["keywords"]:
            self.assertIsNone(kw.get("volume"))
            self.assertIsNone(kw.get("cpc"))
        self.assertIsNone(seo["json_ld"])  # no real product passed -> no sample markup
        product = {"id": 1, "title": "Grozavu Boxy Tee", "handle": "boxy-tee", "status": "active",
                   "images": [{"src": "https://cdn.shopify.com/t.jpg"}], "variants": [{"id": 2, "price": "45.00"}]}
        seo2 = self.ai.generate_seo_strategy("Grozavu", "maisongrozavu.com", products=[product])
        self.assertEqual(seo2["json_ld"]["@type"], "Product")
        self.assertNotIn("aggregateRating", seo2["json_ld"])
        self.assertIn("merchant_feed_tips", seo2)

    def test_lead_radar_structure(self):
        radar = self.ai.generate_lead_radar("Grozavu")
        self.assertGreaterEqual(len(radar["hooks"]), 3)
        self.assertIn("Grozavu", radar["outreach_dm"])
        self.assertGreaterEqual(len(radar["personas"]), 2)
        self.assertEqual(radar["kind"], "ideas")

    def test_revenue_goal_math(self):
        goal = self.ai.calculate_revenue_goal(target_amount=15000.0, currency="EUR", current_aov=150.0, days=30)
        self.assertEqual(goal["needed_orders"], 100)
        self.assertAlmostEqual(goal["daily_orders"], 3.3, places=1)
        self.assertEqual(goal["scenarios"]["cr_2_0"]["total_visitors"], 5000)
        no_aov = self.ai.calculate_revenue_goal(target_amount=15000.0, currency="EUR", current_aov=None, days=30)
        self.assertIsNone(no_aov["needed_orders"])

    async def test_one_click_templates_are_honest(self):
        prompts = [
            "Scrie-mi un script complet de TikTok/Reels de 30 secunde pentru cel mai vândut produs",
            "Scrie un email irezistibil de recuperare a coșurilor abandonate.",
            "Fă un audit rapid de conversie pentru produsele mele.",
            "Scrie un email VIP exclusiv de fidelizare și mulțumire.",
            "Scrie o secvență automată de email post-cumpărare (trimisă la 3 zile după livrare).",
            "Scrie-mi o reclama pentru facebook ads",
        ]
        for p in prompts:
            for snap in (self.connected, self.disconnected):
                reply = await self.ai.chat("Grozavu", snap, [], p, lang="ro")
                self.assertHonest(reply)
        post = await self.ai.chat("Grozavu", self.connected, [], prompts[4], lang="ro")
        self.assertIn("separată de reducere", post)  # review request is not tied to the discount


class TestGrowthEndpointsAPI(unittest.TestCase):

    def setUp(self):
        os.environ.pop("GEMINI_API_KEY", None)
        self.client = TestClient(app, headers=AUTH_HEADERS)

    def test_chat_endpoint_resilient_without_gemini(self):
        res = self.client.post("/api/chat", json={
            "shop": "maisongrozavu.myshopify.com",
            "message": "De ce nu am vânzări azi și ce pot schimba rapid?",
            "lang": "ro"
        })
        self.assertEqual(res.status_code, 200)
        self.assertIn("Diagnostic Imediat Vânzări", res.json()["reply"])

    def test_chat_requires_auth(self):
        res = TestClient(app).post("/api/chat", json={"message": "hi"})
        self.assertEqual(res.status_code, 401)

    def test_growth_seo_endpoint(self):
        res = self.client.get("/api/growth/seo?shop=maisongrozavu.myshopify.com")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("keywords", data)
        self.assertIn("json_ld", data)
        self.assertEqual(data["kind"], "ideas")

    def test_growth_radar_endpoint(self):
        res = self.client.get("/api/growth/radar?shop=maisongrozavu.myshopify.com")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("hooks", data)
        self.assertIn("outreach_dm", data)

    def test_growth_boost_endpoint(self):
        res = self.client.get("/api/growth/boost?shop=maisongrozavu.myshopify.com")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("urgency_banner", data)
        self.assertIn("cart_bump", data)

    def test_growth_goal_endpoint(self):
        res = self.client.post("/api/growth/goal", json={"shop": "maisongrozavu.myshopify.com",
                                                         "target_amount": 10000.0, "currency": "EUR"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["target_amount"], 10000.0)
        self.assertIsNone(data["needed_orders"])  # no real AOV -> no invented order count

        res2 = self.client.post("/api/growth/goal", json={"shop": "maisongrozavu.myshopify.com",
                                                          "target_amount": 10000.0, "currency": "EUR", "aov": 80})
        data2 = res2.json()
        self.assertEqual(data2["needed_orders"], 125)
        self.assertEqual(data2["aov_source"], "owner_assumption")

        bad = self.client.post("/api/growth/goal", json={"target_amount": -5})
        self.assertEqual(bad.status_code, 400)

    def test_google_suggest_endpoint_is_honest_when_offline(self):
        with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("offline")):
            res = self.client.get("/api/growth/google-suggest?q=heavyweight+hoodie")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["query"], "heavyweight hoodie")
        self.assertEqual(data["results"], [])
        self.assertEqual(data["source"], "unavailable")

    def test_autopilot_status_offline_resilience(self):
        res = self.client.get("/api/autopilot/status?shop=maisongrozavu.myshopify.com")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("active", data)  # real daemon state (disabled in tests)
        self.assertIn("queue", data)

    def test_briefing_default_shop_without_query_params(self):
        res = self.client.get("/api/briefing")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("briefing", data)
        self.assertIsNone(data["briefing"].get("health_score"))

    def test_snapshot_default_shop_without_query_params(self):
        res = self.client.get("/api/snapshot")
        self.assertEqual(res.status_code, 200)
        self.assertIn("orders_today", res.json())


if __name__ == "__main__":
    unittest.main()

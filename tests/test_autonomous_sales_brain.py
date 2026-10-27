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
import database as db
from main import app
from starlette.testclient import TestClient


class TestAutonomousSalesBrain(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.ai = AIAdvisor()
        self.snap = {
            "shop_name": "Maison Grozavu",
            "orders_today": 0,
            "orders_30d": 128,
            "revenue_today": 0,
            "revenue_30d": 19450.00,
            "currency": "EUR",
            "abandoned_carts": 7,
            "aov": 150.0,
            "low_stock_items": [
                {"product": "Rochie Seară Noir Silk", "qty": 2}
            ],
            "vip_customers": [
                {"name": "Elena Popescu", "total_spent": 1420.00, "orders_count": 4}
            ]
        }

    async def test_zero_sales_immediate_diagnosis(self):
        """Validates that 'De ce nu am vânzări azi și ce pot schimba rapid?' delivers an in-depth 4-pillar diagnosis."""
        query = "De ce nu am vânzări azi și ce pot schimba rapid?"
        reply = await self.ai.chat("maisongrozavu.myshopify.com", self.snap, [], query, lang="ro")
        self.assertIn("Diagnostic Imediat Vânzări", reply)
        self.assertIn("Trafic", reply)
        self.assertIn("Coșurile Abandonate", reply)
        self.assertIn("Plan de Acțiune în 3 Pași", reply)
        self.assertIn("MG10", reply)

    async def test_boost_slash_command(self):
        """Validates /boost returns instant conversion and traffic multiplier proposals."""
        reply = await self.ai.chat("maisongrozavu.myshopify.com", self.snap, [], "/boost", lang="ro")
        self.assertIn("Multiplicator Instant de Vânzări", reply)
        self.assertIn("Urgency", reply)
        self.assertIn("Cart Bump", reply)
        self.assertIn("MG10", reply)

    async def test_browser_slash_command(self):
        """Validates /browser returns customer radar, Google search demand and outreach scripts."""
        reply = await self.ai.chat("maisongrozavu.myshopify.com", self.snap, [], "/browser", lang="ro")
        self.assertIn("Radar Autonom Clienți", reply)
        self.assertIn("Google High-Intent Search", reply)
        self.assertIn("TikTok", reply)
        self.assertIn("Outreach", reply)

    async def test_goal_slash_command(self):
        """Validates /goal calculates mathematical revenue requirements."""
        reply = await self.ai.chat("maisongrozavu.myshopify.com", self.snap, [], "/goal", lang="ro")
        self.assertIn("Simulator & Obiectiv de Profit", reply)
        self.assertIn("Ecuația Profitului", reply)
        self.assertIn("vizitatori", reply)

    def test_seo_strategy_structure(self):
        """Validates Google SEO keywords and valid Schema.org JSON-LD generation."""
        seo = self.ai.generate_seo_strategy("Maison Grozavu", "maisongrozavu.com")
        self.assertIn("keywords", seo)
        self.assertGreaterEqual(len(seo["keywords"]), 5)
        self.assertIn("json_ld", seo)
        json_ld = seo["json_ld"]
        self.assertEqual(json_ld["@context"], "https://schema.org/")
        self.assertEqual(json_ld["@type"], "Product")
        self.assertEqual(json_ld["brand"]["name"], "Maison Grozavu")
        self.assertIn("merchant_feed_tips", seo)

    def test_lead_radar_structure(self):
        """Validates customer hunter viral hooks and influencer outreach DM."""
        radar = self.ai.generate_lead_radar("Maison Grozavu")
        self.assertIn("hooks", radar)
        self.assertGreaterEqual(len(radar["hooks"]), 3)
        self.assertIn("outreach_dm", radar)
        self.assertIn("Maison Grozavu", radar["outreach_dm"])
        self.assertIn("personas", radar)
        self.assertGreaterEqual(len(radar["personas"]), 2)

    def test_revenue_goal_math(self):
        """Validates math-based calculations for traffic and orders."""
        goal = self.ai.calculate_revenue_goal(target_amount=15000.0, currency="EUR", current_aov=150.0, days=30)
        self.assertEqual(goal["needed_orders"], 100)
        self.assertAlmostEqual(goal["daily_orders"], 3.3, places=1)
        self.assertEqual(goal["scenarios"]["cr_2_0"]["total_visitors"], 5000)
        self.assertIn("google_search", goal["channel_split"])
        self.assertIn("tiktok_reels", goal["channel_split"])


class TestGrowthEndpointsAPI(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def test_chat_endpoint_resilient_without_auth_failure(self):
        """Validates /api/chat never returns 401 or 500, even for fresh unauthenticated stores."""
        res = self.client.post("/api/chat", json={
            "shop": "maisongrozavu.myshopify.com",
            "message": "De ce nu am vânzări azi și ce pot schimba rapid?",
            "lang": "ro"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("reply", data)
        self.assertIn("Diagnostic Imediat Vânzări", data["reply"])

    def test_growth_seo_endpoint(self):
        res = self.client.get("/api/growth/seo?shop=maisongrozavu.myshopify.com")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("keywords", data)
        self.assertIn("json_ld", data)

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
        res = self.client.post("/api/growth/goal", json={
            "shop": "maisongrozavu.myshopify.com",
            "target_amount": 10000.0,
            "currency": "EUR"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["target_amount"], 10000.0)
        self.assertGreater(data["needed_orders"], 0)


if __name__ == "__main__":
    unittest.main()

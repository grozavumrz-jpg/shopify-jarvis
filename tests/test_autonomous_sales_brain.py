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

    async def test_dynamic_goal_parsing(self):
        """Validates that /goal 25000 dynamically calculates for 25,000."""
        reply = await self.ai.chat("maisongrozavu.myshopify.com", self.snap, [], "/goal 25000", lang="ro")
        self.assertIn("25,000", reply)
        self.assertIn("Ecuația Profitului", reply)

    async def test_dynamic_browser_search(self):
        """Validates that /browser sacou catifea searches for the specified query."""
        reply = await self.ai.chat("maisongrozavu.myshopify.com", self.snap, [], "/browser sacou catifea", lang="ro")
        self.assertIn("sacou catifea", reply)
        self.assertIn("Live Search Demand", reply)

    async def test_1click_tiktok_generation(self):
        """Validates 1-Click viral TikTok generation generates full 30s script without protocol error."""
        prompt = "Scrie-mi un script complet de TikTok/Reels de 30 secunde pentru cel mai vândut produs din magazinul Maison Grozavu"
        reply = await self.ai.chat("maisongrozavu.myshopify.com", self.snap, [], prompt, lang="ro")
        self.assertIn("Script Viral TikTok", reply)
        self.assertIn("CÂRLIG VIZUAL", reply)
        self.assertIn("MG10", reply)

    async def test_1click_cart_recovery_generation(self):
        """Validates 1-Click abandoned cart email recovery generation."""
        prompt = "Scrie un email irezistibil de recuperare a coșurilor abandonate pentru clienții Maison Grozavu."
        reply = await self.ai.chat("maisongrozavu.myshopify.com", self.snap, [], prompt, lang="ro")
        self.assertIn("Email & WhatsApp de Recuperare", reply)
        self.assertIn("MG10", reply)
        self.assertIn("6 ore", reply)

    async def test_1click_cro_audit_generation(self):
        """Validates 1-Click CRO conversion audit generation."""
        prompt = "Fă un audit rapid de conversie pentru produsele mele Maison Grozavu."
        reply = await self.ai.chat("maisongrozavu.myshopify.com", self.snap, [], prompt, lang="ro")
        self.assertIn("Audit Rapid de Conversie", reply)
        self.assertIn("Trust Badges", reply)

    async def test_1click_vip_reward_generation(self):
        """Validates 1-Click VIP loyalty email generation."""
        prompt = "Scrie un email VIP exclusiv de fidelizare și mulțumire pentru Maison Grozavu."
        reply = await self.ai.chat("maisongrozavu.myshopify.com", self.snap, [], prompt, lang="ro")
        self.assertIn("Email Exclusiv de Fidelizare", reply)
        self.assertIn("MGVIP15", reply)

    async def test_1click_post_purchase_generation(self):
        """Validates 1-Click post-delivery sequence generation."""
        prompt = "Scrie o secvență automată de email post-cumpărare (trimisă la 3 zile după livrare)."
        reply = await self.ai.chat("maisongrozavu.myshopify.com", self.snap, [], prompt, lang="ro")
        self.assertIn("Secvență Automată Post-Livrare", reply)
        self.assertIn("Recenzie", reply)

    async def test_ad_copy_generation(self):
        """Validates ad copy generation for Meta/Facebook."""
        reply = await self.ai.chat("maisongrozavu.myshopify.com", self.snap, [], "Scrie-mi o reclama pentru facebook ads", lang="ro")
        self.assertIn("Scripturi Reclame Meta Ads", reply)
        self.assertIn("Quiet Luxury", reply)


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

    def test_google_suggest_endpoint(self):
        res = self.client.get("/api/growth/google-suggest?q=rochii+matase")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["query"], "rochii matase")
        self.assertIn("results", data)
        self.assertGreater(len(data["results"]), 0)

    def test_autopilot_status_offline_resilience(self):
        res = self.client.get("/api/autopilot/status?shop=maisongrozavu.myshopify.com")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["active"])
        self.assertIn("queue", data)

    def test_briefing_default_shop_without_query_params(self):
        res = self.client.get("/api/briefing")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("briefing", data)

    def test_snapshot_default_shop_without_query_params(self):
        res = self.client.get("/api/snapshot")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("orders_today", data)


if __name__ == "__main__":
    unittest.main()

"""
Tests for:
  1. Gemini Live Web Search Grounding (`google_search` tool, citation extraction,
     graceful 400 fallback without tools, `/web` trigger, and `chat_detailed` metadata).
  2. Official Google Search Console (GSC) & Google Analytics 4 (GA4) integration
     (truthful unconfigured state, RS256 Service Account JWT signing, mocked GSC/GA4
     REST responses, opportunity query extraction, prompt context injection, and auth guard).
"""

import base64
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import ai_advisor
import google_analytics_service as gas
import main


def _generate_test_service_account_json() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    return json.dumps({
        "type": "service_account",
        "client_email": "jarvis-test@grozavu-test.iam.gserviceaccount.com",
        "private_key": pem,
        "token_uri": "https://oauth2.googleapis.com/token",
    })


TEST_SA_JSON = _generate_test_service_account_json()


class TestGeminiWebSearchGrounding(unittest.IsolatedAsyncioTestCase):
    async def test_should_use_web_search_triggers_on_trends_competitors_and_slash_web(self):
        self.assertTrue(ai_advisor.AIAdvisor._should_use_web_search("/web streetwear trends 2026"))
        self.assertTrue(ai_advisor.AIAdvisor._should_use_web_search("Care sunt trendurile streetwear și prețurile concurenței?"))
        self.assertTrue(ai_advisor.AIAdvisor._should_use_web_search("Idei de campanii de Black Friday pe TikTok"))
        self.assertFalse(ai_advisor.AIAdvisor._should_use_web_search("Cât am vândut luna asta?"))
        self.assertFalse(ai_advisor.AIAdvisor._should_use_web_search("Salut, ce faci?"))

    async def test_call_gemini_passes_google_search_tool_and_extracts_sources(self):
        seen_payloads = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            seen_payloads.append(body)
            return httpx.Response(200, json={
                "candidates": [{
                    "content": {
                        "parts": [{"text": "Trendurile actuale streetwear 2026 includ hanorace boxy heavyweight 450-500 GSM."}]
                    },
                    "groundingMetadata": {
                        "webSearchQueries": ["streetwear trends Europe 2026"],
                        "groundingChunks": [
                            {"web": {"uri": "https://www.highsnobiety.com/streetwear-2026", "title": "Highsnobiety"}},
                            {"web": {"uri": "https://www.highsnobiety.com/streetwear-2026", "title": "Duplicate"}},
                            {"web": {"uri": "https://hypebeast.com/heavyweight-hoodie-pricing", "title": "Hypebeast"}},
                            {"web": {"uri": "javascript:alert(1)", "title": "BadScheme"}},
                        ],
                    },
                }]
            })

        transport = httpx.MockTransport(handler)
        real_client_cls = httpx.AsyncClient
        advisor = ai_advisor.AIAdvisor()
        grounding_out = {}

        with patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaTestKey1234567890", "GEMINI_MODEL": "gemini-2.5-flash"}), \
             patch.object(ai_advisor.httpx, "AsyncClient", lambda **kw: real_client_cls(transport=transport, **kw)):
            text = await advisor._call_gemini(
                "Ce trenduri streetwear sunt acum?",
                use_web_search=True,
                grounding_out=grounding_out,
            )

        self.assertIn("450-500 GSM", text)
        self.assertEqual(len(seen_payloads), 1)
        self.assertEqual(seen_payloads[0].get("tools"), [{"google_search": {}}])
        self.assertTrue(grounding_out["web_grounded"])
        self.assertEqual(grounding_out["search_queries"], ["streetwear trends Europe 2026"])
        self.assertEqual(len(grounding_out["sources"]), 2)
        self.assertEqual(grounding_out["sources"][0]["title"], "Highsnobiety")
        self.assertEqual(grounding_out["sources"][1]["url"], "https://hypebeast.com/heavyweight-hoodie-pricing")

    async def test_call_gemini_retries_without_tools_on_400(self):
        seen_payloads = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            seen_payloads.append(body)
            if "tools" in body:
                return httpx.Response(400, json={"error": {"message": "Tool google_search not supported"}})
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"text": "Răspuns fără tool după fallback automat."}]}}]
            })

        transport = httpx.MockTransport(handler)
        real_client_cls = httpx.AsyncClient
        advisor = ai_advisor.AIAdvisor()

        with patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaTestKey1234567890", "GEMINI_MODEL": "gemini-2.5-flash"}), \
             patch.object(ai_advisor.httpx, "AsyncClient", lambda **kw: real_client_cls(transport=transport, **kw)):
            text = await advisor._call_gemini("Trenduri streetwear", use_web_search=True)

        self.assertIn("fallback automat", text)
        self.assertEqual(len(seen_payloads), 2)
        self.assertIn("tools", seen_payloads[0])
        self.assertNotIn("tools", seen_payloads[1])

    async def test_chat_detailed_appends_live_sources_and_injects_google_traffic(self):
        captured_prompts = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            captured_prompts.append(body["contents"][0]["parts"][0]["text"])
            return httpx.Response(200, json={
                "candidates": [{
                    "content": {
                        "parts": [{"text": "Pe piața din Europa, hanoracele streetwear premium sunt între 90 și 160 EUR."}]
                    },
                    "groundingMetadata": {
                        "webSearchQueries": ["premium streetwear hoodie price Europe"],
                        "groundingChunks": [
                            {"web": {"uri": "https://example.com/streetwear-report", "title": "Streetwear Report"}}
                        ],
                    },
                }]
            })

        transport = httpx.MockTransport(handler)
        real_client_cls = httpx.AsyncClient
        advisor = ai_advisor.AIAdvisor()
        snap = {"connected": True, "shop_name": "Grozavu", "orders_30d": 4, "revenue_30d": 380.0, "currency": "EUR"}
        traffic_ctx = "GOOGLE TRAFFIC & SEARCH DATA (real verified Google APIs, last 28 days):\n- Google Search Console: 120 clicks"

        with patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaTestKey1234567890", "GEMINI_MODEL": "gemini-2.5-flash"}), \
             patch.object(ai_advisor.httpx, "AsyncClient", lambda **kw: real_client_cls(transport=transport, **kw)):
            res = await advisor.chat_detailed(
                shop_name="Grozavu",
                snapshot=snap,
                history=[],
                message="/web Prețuri hanorace streetwear concurență",
                lang="ro",
                google_traffic_context=traffic_ctx,
            )

        self.assertTrue(res["web_grounded"])
        self.assertEqual(len(res["sources"]), 1)
        self.assertIn("Surse web live", res["reply"])
        self.assertIn("https://example.com/streetwear-report", res["reply"])
        self.assertIn("GOOGLE TRAFFIC & SEARCH DATA", captured_prompts[0])
        self.assertIn("LIVE WEB SEARCH (Google Search Grounding ACTIVE)", captured_prompts[0])


class TestGoogleSearchConsoleAndGA4(unittest.IsolatedAsyncioTestCase):
    async def test_unconfigured_returns_honest_empty_state_and_setup_guide(self):
        svc = gas.GoogleTrafficService(brand_domain="maisongrozavu.com")
        with patch.dict(os.environ, {}, clear=True):
            report = await svc.get_combined_report(days=28, force_refresh=True)

        self.assertFalse(report["configured"])
        self.assertFalse(report["connected"])
        self.assertFalse(report["search_console"]["connected"])
        self.assertIsNone(report["search_console"]["summary"])
        self.assertFalse(report["ga4"]["connected"])
        self.assertIsNone(report["ga4"]["summary"])
        self.assertEqual(len(report["setup_guide_ro"]), 4)
        self.assertEqual(svc.to_prompt_context(report), "")

    async def test_connected_gsc_and_ga4_parse_real_metrics_and_prompt_context(self):
        svc = gas.GoogleTrafficService(brand_domain="maisongrozavu.com")
        seen_urls = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            seen_urls.append(url)
            if "oauth2.googleapis.com/token" in url:
                return httpx.Response(200, json={"access_token": "ya29.test_token_123", "expires_in": 3600})
            if "searchconsole.googleapis.com" in url:
                body = json.loads(request.content.decode("utf-8"))
                dims = body.get("dimensions") or []
                if not dims:
                    return httpx.Response(200, json={
                        "rows": [{"clicks": 145, "impressions": 4200, "ctr": 0.0345, "position": 11.4}]
                    })
                if dims == ["query"]:
                    return httpx.Response(200, json={
                        "rows": [
                            {"keys": ["maison grozavu"], "clicks": 80, "impressions": 220, "ctr": 0.3636, "position": 1.3},
                            {"keys": ["heavyweight boxy hoodie spain"], "clicks": 12, "impressions": 640, "ctr": 0.0187, "position": 9.8},
                            {"keys": ["streetwear hoodie europe"], "clicks": 3, "impressions": 410, "ctr": 0.0073, "position": 16.2},
                        ]
                    })
                if dims == ["page"]:
                    return httpx.Response(200, json={
                        "rows": [
                            {"keys": ["https://maisongrozavu.com/"], "clicks": 95, "impressions": 1800, "ctr": 0.0528, "position": 6.1},
                        ]
                    })
            if "analyticsdata.googleapis.com" in url:
                body = json.loads(request.content.decode("utf-8"))
                dims = [d.get("name") for d in (body.get("dimensions") or [])]
                if not dims:
                    return httpx.Response(200, json={
                        "rows": [{
                            "metricValues": [
                                {"value": "512"},
                                {"value": "390"},
                                {"value": "310"},
                                {"value": "1280"},
                                {"value": "0.625"},
                                {"value": "94.3"},
                                {"value": "7"},
                            ]
                        }]
                    })
                if dims == ["sessionDefaultChannelGroup"]:
                    return httpx.Response(200, json={
                        "rows": [
                            {"dimensionValues": [{"value": "Organic Search"}], "metricValues": [{"value": "210"}, {"value": "175"}]},
                            {"dimensionValues": [{"value": "Organic Social"}], "metricValues": [{"value": "195"}, {"value": "150"}]},
                        ]
                    })
                if dims == ["pagePath"]:
                    return httpx.Response(200, json={
                        "rows": [
                            {"dimensionValues": [{"value": "/products/heavyweight-hoodie"}], "metricValues": [{"value": "340"}, {"value": "180"}]},
                        ]
                    })
                if dims == ["country"]:
                    return httpx.Response(200, json={
                        "rows": [
                            {"dimensionValues": [{"value": "Spain"}], "metricValues": [{"value": "280"}, {"value": "210"}]},
                            {"dimensionValues": [{"value": "Romania"}], "metricValues": [{"value": "165"}, {"value": "120"}]},
                        ]
                    })
            return httpx.Response(404, json={"error": {"message": "unexpected url"}})

        transport = httpx.MockTransport(handler)
        real_client_cls = httpx.AsyncClient
        b64_sa = base64.b64encode(TEST_SA_JSON.encode("utf-8")).decode("ascii")

        with patch.dict(os.environ, {
            "GOOGLE_SERVICE_ACCOUNT_B64": b64_sa,
            "GSC_SITE_URL": "sc-domain:maisongrozavu.com",
            "GA4_PROPERTY_ID": "properties/412345678",
        }, clear=True), patch.object(gas.httpx, "AsyncClient", lambda **kw: real_client_cls(transport=transport, **kw)):
            report = await svc.get_combined_report(days=28, force_refresh=True)

        self.assertTrue(report["configured"])
        self.assertTrue(report["connected"])
        self.assertTrue(report["search_console"]["connected"])
        self.assertEqual(report["search_console"]["summary"]["clicks"], 145)
        self.assertEqual(report["search_console"]["summary"]["impressions"], 4200)
        self.assertEqual(report["search_console"]["summary"]["ctr"], 3.45)
        self.assertEqual(report["search_console"]["summary"]["avg_position"], 11.4)
        self.assertEqual(len(report["search_console"]["opportunity_queries"]), 2)
        self.assertEqual(report["search_console"]["opportunity_queries"][0]["query"], "heavyweight boxy hoodie spain")

        self.assertTrue(report["ga4"]["connected"])
        self.assertEqual(report["ga4"]["property_id"], "412345678")
        self.assertEqual(report["ga4"]["summary"]["sessions"], 512)
        self.assertEqual(report["ga4"]["summary"]["total_users"], 390)
        self.assertEqual(report["ga4"]["summary"]["engagement_rate"], 62.5)
        self.assertEqual(report["ga4"]["channels"][0]["channel"], "Organic Search")
        self.assertEqual(report["ga4"]["countries"][0]["country"], "Spain")

        ctx = svc.to_prompt_context(report)
        self.assertIn("145 clicks", ctx)
        self.assertIn("heavyweight boxy hoodie spain", ctx)
        self.assertIn("512 sessions", ctx)
        self.assertIn("Organic Search", ctx)
        self.assertIn("Spain", ctx)
        # Never leaks private key material
        self.assertNotIn("PRIVATE KEY", json.dumps(report))


class TestGoogleAnalyticsEndpointsAuth(unittest.TestCase):
    def test_google_analytics_endpoints_require_auth(self):
        client = TestClient(main.app)
        with patch.dict(os.environ, {"JARVIS_ADMIN_KEY": "secret-test-key-12345"}):
            r1 = client.get("/api/google/analytics")
            r2 = client.post("/api/google/analytics/refresh", json={})
            self.assertEqual(r1.status_code, 401)
            self.assertEqual(r2.status_code, 401)

            r_ok = client.get("/api/google/analytics", headers={"X-Jarvis-Key": "secret-test-key-12345"})
            self.assertEqual(r_ok.status_code, 200)
            body = r_ok.json()
            self.assertIn("search_console", body)
            self.assertIn("ga4", body)
            self.assertIn("setup_guide_ro", body)

            h = client.get("/health")
            self.assertEqual(h.status_code, 200)
            hb = h.json()
            self.assertTrue(hb.get("web_search_grounding_enabled"))
            self.assertIn("google_search_console_configured", hb)
            self.assertIn("google_analytics_configured", hb)


if __name__ == "__main__":
    unittest.main()

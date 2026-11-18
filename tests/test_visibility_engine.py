import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import visibility_engine as vis  # noqa: E402

PRODUCTS = [
    {"id": 1, "title": "Wide Leg Shorts", "handle": "wide-leg-shorts", "status": "active",
     "body_html": "<p>Short cu croială largă. " + "x" * 150 + " Ce mărime aleg?</p>",
     "variants": [{"price": "49.90"}]},
    {"id": 2, "title": "Heavyweight Hoodie", "handle": "hoodie", "status": "active",
     "body_html": "scurt", "variants": [{"price": "79.00"}]},
]
GSC = {"connected": True,
       "summary": {"clicks": 173, "impressions": 16823, "ctr": 1.03, "avg_position": 13.8},
       "top_queries": [{"query": "grozavu", "clicks": 20, "impressions": 100, "position": 2.3}],
       "opportunity_queries": [{"query": "short de pernera ancha para mujer", "clicks": 3,
                                 "impressions": 900, "position": 9.9}]}


class FakeAI:
    def __init__(self, text="Recomand Nude Project si Scuffers.\nBRANDS: Nude Project, Scuffers", json_out=None):
        self.text, self.json_out = text, json_out

    def _get_api_key(self):
        return "k" * 20

    async def _call_gemini(self, prompt, **kw):
        if isinstance(kw.get("grounding_out"), dict):
            kw["grounding_out"].update({"sources": [{"title": "t", "url": "https://example.com"}]})
        return self.text

    async def _call_advisor_model(self, prompt, **kw):
        return json.dumps(self.json_out or {})

    @staticmethod
    def _parse_json_object(t):
        return json.loads(t)


class ScoreTests(unittest.TestCase):
    def test_seo_score_from_real_gsc(self):
        s = vis.seo_score(GSC)
        self.assertIsNotNone(s["score"])
        self.assertEqual(s["details"]["avg_position"], 13.8)
        self.assertLess(s["score"], 50)

    def test_scores_none_without_data(self):
        self.assertIsNone(vis.seo_score(None)["score"])
        self.assertIsNone(vis.aeo_readiness([], None)["score"])
        vis._GEO_CACHE.clear()
        self.assertIsNone(vis.geo_score("x.myshopify.com")["score"])

    def test_aeo_readiness_counts(self):
        a = vis.aeo_readiness(PRODUCTS, GSC)
        self.assertEqual(a["details"]["products_with_real_description"], 1)
        self.assertEqual(len(a["weak_products"]), 1)
        self.assertEqual(a["score"], round(100 * (0.6 * 0.5 + 0.4 * 0.5)))

    def test_overall_ignores_missing(self):
        vis._GEO_CACHE.clear()
        out = vis.build_visibility_score("x.myshopify.com", PRODUCTS, GSC)
        self.assertIsNone(out["geo"]["score"])
        self.assertTrue(any("GEO" in a for a in out["next_actions"]))


class AeoTests(unittest.TestCase):
    def test_template_pack_and_jsonld(self):
        pack = asyncio.run(vis.generate_aeo_pack("short pernera ancha", PRODUCTS, GSC, ai_advisor=None))
        self.assertEqual(pack["source"], "template")
        ld = json.loads(pack["faq_jsonld"])
        self.assertEqual(ld["@type"], "FAQPage")
        self.assertTrue(pack["has_placeholders"])
        self.assertIn("Designed in Spain", pack["answer_first_paragraph"])

    def test_gemini_pack_is_brand_sanitized(self):
        fake = FakeAI(json_out={
            "answer_first_paragraph": "Grozavu unisex made in Spain atelier.",
            "faq": [{"question": f"q{i}", "answer": "silk? no"} for i in range(4)],
            "article_outline": ["a", "b", "c", "d"],
        })
        pack = asyncio.run(vis.generate_aeo_pack("hoodie", PRODUCTS, GSC, ai_advisor=fake))
        blob = json.dumps(pack, ensure_ascii=False).lower()
        self.assertEqual(pack["source"], "gemini_ai")
        self.assertNotIn("unisex", blob)
        self.assertNotIn("atelier", blob)
        self.assertIn("designed in spain", blob)


class GeoTests(unittest.TestCase):
    def setUp(self):
        vis._GEO_CACHE.clear()

    def test_not_mentioned(self):
        res = asyncio.run(vis.run_geo_test("s.myshopify.com", FakeAI(), PRODUCTS, GSC, force=True))
        self.assertTrue(res["ok"])
        self.assertEqual(res["mention_rate_pct"], 0)
        self.assertEqual(res["competitors_recommended_instead"][0]["brand"], "Nude Project")
        self.assertEqual(vis.geo_score("s.myshopify.com")["score"], 0)

    def test_mentioned(self):
        ai = FakeAI(text="Prueba Grozavu.\nBRANDS: Grozavu, Scuffers")
        res = asyncio.run(vis.run_geo_test("s.myshopify.com", ai, PRODUCTS, GSC, force=True))
        self.assertEqual(res["mention_rate_pct"], 100)
        self.assertTrue(all(c["brand"] != "Grozavu" for c in res["competitors_recommended_instead"]))

    def test_no_key(self):
        class NoKey(FakeAI):
            def _get_api_key(self):
                return ""
        res = asyncio.run(vis.run_geo_test("s.myshopify.com", NoKey(), PRODUCTS, GSC, force=True))
        self.assertFalse(res["ok"])

    def test_mentions_plan_rules(self):
        plan = vis.build_mentions_plan(PRODUCTS, GSC)
        blob = json.dumps(plan, ensure_ascii=False).lower()
        self.assertIn("fondatorul", blob)
        self.assertNotIn("unisex", blob)
        self.assertNotIn("jarvis10", blob)


if __name__ == "__main__":
    unittest.main()

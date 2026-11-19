"""
Jarvis agent: reads the store, PROPOSES changes, and writes to Shopify only after the owner
approves. These tests run against an in-memory fake of the Shopify Admin GraphQL API.
"""
import copy
import json
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
for p in (PROJECT_ROOT, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from tests.auth_helpers import AUTH_HEADERS
except ImportError:
    from auth_helpers import AUTH_HEADERS

import agent
import agent_tools
import ai_advisor
import database as db
import main
from agent_tools import AEO_END, AEO_START, AgentError, AgentToolbox
from starlette.testclient import TestClient

AEO = f"{AEO_START}<section><h3>Frequently Asked Questions</h3><p>FAQ</p></section>{AEO_END}"
P1, P2 = "gid://shopify/Product/1", "gid://shopify/Product/2"
V11, V12 = "gid://shopify/ProductVariant/11", "gid://shopify/ProductVariant/12"
C_MANUAL, C_AUTO = "gid://shopify/Collection/100", "gid://shopify/Collection/200"
PUB = "gid://shopify/Publication/77"
WRITE_OPS = ("productUpdate(", "metafieldsSet(", "metafieldsDelete(", "productVariantsBulkUpdate(",
             "discountCodeBasicCreate(", "discountCodeDeactivate(", "publishablePublish(", "publishableUnpublish(")


class FakeShopify:
    """Tiny stateful stand-in for the Shopify Admin GraphQL API (only what the agent uses)."""

    def __init__(self, context_supported=True):
        self.shop = "agent-test.myshopify.com"
        self.context_supported = context_supported
        self.writes = []
        self.products = {
            P1: {"id": P1, "legacyResourceId": "1", "title": "Oversized Organic Tee", "handle": "oversized-organic-tee",
                 "status": "ACTIVE", "productType": "T-Shirt", "vendor": "Grozavu", "tags": ["Men", "oversized tee"],
                 "descriptionHtml": "<p>200 g/m² combed cotton tee with an oversized fit.</p>\n\n" + AEO,
                 "seo": {"title": "Oversized Tee | Grozavu", "description": "Oversized tee."},
                 "category": {"fullName": "Apparel > T-Shirts"}, "onlineStoreUrl": "https://maisongrozavu.com/products/x",
                 "published": True, "mediaCount": {"count": 6}, "totalInventory": 20,
                 "variants": [{"id": V11, "title": "Black / S", "sku": "A", "price": "51.00", "compareAtPrice": None, "inventoryQuantity": 10},
                              {"id": V12, "title": "Black / M", "sku": "B", "price": "51.00", "compareAtPrice": None, "inventoryQuantity": 10}],
                 "collections": [C_MANUAL],
                 "mf": {"color-pattern": ["gid://shopify/Metaobject/1"], "fabric": [], "target-gender": ["gid://shopify/Metaobject/20"], "age-group": []}},
            P2: {"id": P2, "legacyResourceId": "2", "title": "Magenta Smoke Hoodie", "handle": "magenta-smoke-hoodie",
                 "status": "DRAFT", "productType": "Hoodie", "vendor": "Grozavu", "tags": [],
                 "descriptionHtml": "<p>Heavy hoodie.</p>", "seo": {"title": None, "description": None},
                 "category": None, "onlineStoreUrl": None, "published": False, "mediaCount": {"count": 0}, "totalInventory": 0,
                 "variants": [{"id": "gid://shopify/ProductVariant/21", "title": "M", "sku": "H", "price": "89.00", "compareAtPrice": None, "inventoryQuantity": 0}],
                 "collections": [], "mf": {"color-pattern": [], "fabric": [], "target-gender": [], "age-group": []}},
        }
        self.metaobjects = {
            "shopify--color-pattern": [{"id": "gid://shopify/Metaobject/1", "handle": "black", "displayName": "Black"},
                                       {"id": "gid://shopify/Metaobject/2", "handle": "navy", "displayName": "Navy"},
                                       {"id": "gid://shopify/Metaobject/3", "handle": "pink", "displayName": "Pink"}],
            "shopify--fabric": [{"id": "gid://shopify/Metaobject/10", "handle": "cotton", "displayName": "Cotton"},
                                {"id": "gid://shopify/Metaobject/11", "handle": "fleece", "displayName": "Fleece"}],
            "shopify--target-gender": [{"id": "gid://shopify/Metaobject/20", "handle": "male", "displayName": "Male"},
                                       {"id": "gid://shopify/Metaobject/21", "handle": "unisex", "displayName": "Unisex"}],
            "shopify--age-group": [{"id": "gid://shopify/Metaobject/30", "handle": "adults", "displayName": "Adults"}],
        }
        self.collections = {C_MANUAL: {"id": C_MANUAL, "title": "Men", "ruleSet": None},
                            C_AUTO: {"id": C_AUTO, "title": "Hoodies", "ruleSet": {"appliedDisjunctively": False}}}
        self.discounts = {"MGVIP15": {"id": "gid://shopify/DiscountCodeNode/9", "title": "VIP", "status": "ACTIVE"}}
        self.last_discount_input = None

    def _mo_label(self, gid):
        for vals in self.metaobjects.values():
            for v in vals:
                if v["id"] == gid:
                    return v["displayName"]
        return "?"

    def _product_view(self, p):
        return {
            **{k: copy.deepcopy(v) for k, v in p.items() if k not in ("published", "variants", "collections", "mf")},
            "publishedOnPublication": p["published"],
            "variants": {"nodes": copy.deepcopy(p["variants"])},
            "collections": {"nodes": [{"id": c, "title": self.collections[c]["title"]} for c in p["collections"]]},
            "metafields": {"nodes": [{"key": f"shopify.{k}", "value": json.dumps(v),
                                      "references": {"nodes": [{"id": g, "displayName": self._mo_label(g)} for g in v]}}
                                     for k, v in p["mf"].items() if v]},
        }

    async def _graphql(self, query, variables=None):
        v = variables or {}
        q = " ".join(query.split())
        for op in WRITE_OPS:
            if op in q:
                self.writes.append((op, copy.deepcopy(v)))
                return self._mutate(op, v)
        if "publications(" in q:
            return {"data": {"publications": {"nodes": [
                {"id": "gid://shopify/Publication/5", "channels": {"nodes": [{"handle": "facebook", "name": "Facebook"}]}},
                {"id": PUB, "channels": {"nodes": [{"handle": "online_store", "name": "Online Store"}]}}]}}}
        if "metaobjects(" in q:
            return {"data": {"metaobjects": {"nodes": copy.deepcopy(self.metaobjects.get(v["t"], []))}}}
        if "codeDiscountNodeByCode(" in q:
            d = self.discounts.get(str(v["c"]).upper())
            return {"data": {"codeDiscountNodeByCode": {"id": d["id"], "codeDiscount": {"title": d["title"], "status": d["status"]}} if d else None}}
        if "inCollection(" in q:
            p = self.products.get(v["p"])
            return {"data": {"product": {"id": p["id"], "title": p["title"], "inCollection": v["c"] in p["collections"]} if p else None}}
        if "collection(id:" in q:
            c = self.collections.get(v["id"])
            return {"data": {"collection": copy.deepcopy(c) if c else None}}
        if "product(id:" in q:
            p = self.products.get(v["id"])
            return {"data": {"product": self._product_view(p) if p else None}}
        if "products(first:" in q:
            query_s = str(v.get("q") or "")
            if query_s.startswith("handle:"):
                h = query_s.split(":", 1)[1].strip("'")
                nodes = [{"id": p["id"]} for p in self.products.values() if p["handle"] == h]
            else:
                nodes = [{"id": p["id"], "title": p["title"], "handle": p["handle"], "status": p["status"],
                          "productType": p["productType"], "totalInventory": p["totalInventory"],
                          "priceRangeV2": {"minVariantPrice": {"amount": p["variants"][0]["price"], "currencyCode": "EUR"},
                                           "maxVariantPrice": {"amount": p["variants"][-1]["price"]}}}
                         for p in self.products.values() if not query_s or query_s.lower() in p["title"].lower()]
            return {"data": {"products": {"nodes": nodes}}}
        if "collections(first:" in q:
            return {"data": {"collections": {"nodes": [dict(copy.deepcopy(c), handle=c["title"].lower(), productsCount={"count": 1})
                                                       for c in self.collections.values()]}}}
        if "discountNodes(" in q:
            return {"data": {"discountNodes": {"nodes": []}}}
        if "orders(" in q:
            return {"data": {"orders": {"nodes": [{"name": "#1186", "createdAt": "2026-11-10T15:40:44Z",
                                                   "displayFinancialStatus": "PAID", "displayFulfillmentStatus": "FULFILLED",
                                                   "totalPriceSet": {"shopMoney": {"amount": "83.6", "currencyCode": "EUR"}},
                                                   "lineItems": {"nodes": [{"title": "Magenta Smoke Hoodie", "quantity": 1}]}}]}}}
        raise AssertionError("unexpected query: " + q[:120])

    def _mutate(self, op, v):
        if op == "productUpdate(":
            inp = v["product"]
            p = self.products[inp["id"]]
            if "title" in inp:
                p["title"] = inp["title"]
            if "descriptionHtml" in inp:
                p["descriptionHtml"] = inp["descriptionHtml"].replace("<p>", "<p>\n")  # Shopify re-formats HTML
            if "productType" in inp:
                p["productType"] = inp["productType"]
            if "tags" in inp:
                p["tags"] = list(inp["tags"])
            if "seo" in inp:
                p["seo"] = dict(inp["seo"])
            if "status" in inp:
                p["status"] = inp["status"]
            for c in inp.get("collectionsToJoin") or []:
                if self.collections[c]["ruleSet"]:
                    return {"data": {"productUpdate": {"product": None, "userErrors": [{"field": ["collectionsToJoin"], "message": "Can't add to a smart collection"}]}}}
                if c not in p["collections"]:
                    p["collections"].append(c)
            for c in inp.get("collectionsToLeave") or []:
                if c in p["collections"]:
                    p["collections"].remove(c)
            return {"data": {"productUpdate": {"product": {"id": p["id"], "status": p["status"]}, "userErrors": []}}}
        if op == "metafieldsSet(":
            for m in v["m"]:
                self.products[m["ownerId"]]["mf"][m["key"]] = json.loads(m["value"])
            return {"data": {"metafieldsSet": {"metafields": [{"key": m["key"]} for m in v["m"]], "userErrors": []}}}
        if op == "metafieldsDelete(":
            for m in v["m"]:
                self.products[m["ownerId"]]["mf"][m["key"]] = []
            return {"data": {"metafieldsDelete": {"deletedMetafields": [{"key": m["key"]} for m in v["m"]], "userErrors": []}}}
        if op == "productVariantsBulkUpdate(":
            p = self.products[v["pid"]]
            for upd in v["v"]:
                for var in p["variants"]:
                    if var["id"] == upd["id"]:
                        var["price"] = upd["price"]
                        var["compareAtPrice"] = upd["compareAtPrice"]
            return {"data": {"productVariantsBulkUpdate": {"productVariants": [], "userErrors": []}}}
        if op == "discountCodeBasicCreate(":
            d = v["d"]
            if "context" in d and not self.context_supported:
                return {"errors": [{"message": "InputObject 'DiscountCodeBasicInput' doesn't accept argument 'context'"}]}
            self.last_discount_input = copy.deepcopy(d)
            gid = f"gid://shopify/DiscountCodeNode/{len(self.discounts) + 100}"
            self.discounts[d["code"]] = {"id": gid, "title": d["title"], "status": "ACTIVE"}
            return {"data": {"discountCodeBasicCreate": {"codeDiscountNode": {"id": gid}, "userErrors": []}}}
        if op == "discountCodeDeactivate(":
            for d in self.discounts.values():
                if d["id"] == v["id"]:
                    d["status"] = "EXPIRED"
            return {"data": {"discountCodeDeactivate": {"codeDiscountNode": {"id": v["id"]}, "userErrors": []}}}
        if op in ("publishablePublish(", "publishableUnpublish("):
            assert v["in"][0]["publicationId"] == PUB
            self.products[v["id"]]["published"] = op == "publishablePublish("
            key = op[:-1]
            return {"data": {key: {"userErrors": []}}}
        raise AssertionError(op)


def _new_shop():
    return f"agent-{time.time_ns()}.myshopify.com"


class AgentToolsTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def setUp(self):
        self.fake = FakeShopify()
        self.tb = AgentToolbox(self.fake, None, self.fake.shop)
        self.shop = _new_shop()

    async def _propose(self, action, args):
        prop = await self.tb.prepare(action, args)
        rec = {"id": f"a{time.time_ns()}", "shop": self.shop, "status": "proposed", "action": prop["action"],
               "args": prop["args"], "before": prop["before"], "after": prop["after"], "title": prop["title"],
               "rows": prop["rows"], "warnings": prop["warnings"], "target": prop["target"],
               "created_at": datetime.now(timezone.utc).isoformat()}
        db.save_agent_action(self.shop, rec)
        return rec

    # ── product update ──

    async def test_product_update_proposal_writes_nothing_until_approved_then_verifies_and_undoes(self):
        rec = await self._propose("update_product", {"product": P1, "title": "Oversized Organic Tee — Black",
                                                     "fabrics": ["Cotton"], "colors": ["black", "Navy"], "tags_add": ["organic"]})
        self.assertEqual(self.fake.writes, [], "a proposal must never write to Shopify")
        fields = {r["field"] for r in rec["rows"]}
        self.assertEqual(fields, {"Titlu", "Tag-uri", "Color", "Fabric"})
        self.assertTrue(any("Age group" in w for w in rec["warnings"]))  # still missing → owner is told

        res = await agent.approve_action(self.tb, self.shop, rec["id"])
        self.assertEqual(res["status"], "executed")
        self.assertIn("verificat", res["message"])
        p = self.fake.products[P1]
        self.assertEqual(p["title"], "Oversized Organic Tee — Black")
        self.assertEqual(p["mf"]["fabric"], ["gid://shopify/Metaobject/10"])
        self.assertEqual(p["mf"]["color-pattern"], ["gid://shopify/Metaobject/1", "gid://shopify/Metaobject/2"])
        self.assertIn("organic", p["tags"])
        self.assertTrue(res["can_undo"])

        undone = await agent.undo_action(self.tb, self.shop, rec["id"])
        self.assertEqual(undone["status"], "undone")
        self.assertIn("ca înainte", undone["message"])
        self.assertEqual(p["title"], "Oversized Organic Tee")
        self.assertEqual(p["mf"]["fabric"], [])  # was empty before → the value Jarvis added is removed
        self.assertNotIn("organic", p["tags"])

    async def test_new_description_keeps_the_faq_block(self):
        rec = await self._propose("update_product", {"product": P1, "description_html":
                                                     "Heavyweight 200 g/m² organic cotton tee.\n\nOversized fit, dropped shoulders."})
        self.assertIn(AEO_START, rec["after"]["description_html"])
        self.assertTrue(rec["after"]["description_html"].startswith("<p>Heavyweight"))
        res = await agent.approve_action(self.tb, self.shop, rec["id"])
        self.assertEqual(res["status"], "executed")
        self.assertIn("verificat", res["message"])  # Shopify's HTML re-formatting is not a mismatch
        self.assertIn(AEO_END, self.fake.products[P1]["descriptionHtml"])

    async def test_non_english_title_is_flagged_and_unknown_values_are_refused(self):
        rec = await self._propose("update_product", {"product": P1, "title": "Tricou supradimensionat negru"})
        rec2 = await self._propose("update_product", {"product": P1, "title": "Camiseta oversize algodón"})
        self.assertTrue(any("engleză" in w for w in rec2["warnings"]))
        del rec
        with self.assertRaises(AgentError) as ctx:
            await self.tb.prepare("update_product", {"product": P1, "colors": ["Turquoise Dream"]})
        self.assertIn("Valori posibile", str(ctx.exception))
        self.assertIn("Navy", str(ctx.exception))
        with self.assertRaises(AgentError):
            await self.tb.prepare("update_product", {"product": P1, "title": "Oversized Organic Tee"})  # no change
        with self.assertRaises(AgentError):
            await self.tb.prepare("update_product", {"product": "gid://shopify/Product/999", "title": "X"})

    async def test_stale_proposal_is_not_applied(self):
        rec = await self._propose("update_product", {"product": P1, "title": "New Title"})
        self.fake.products[P1]["title"] = "Changed by the owner meanwhile"
        res = await agent.approve_action(self.tb, self.shop, rec["id"])
        self.assertEqual(res["status"], "stale")
        self.assertEqual(self.fake.writes, [])
        self.assertEqual(self.fake.products[P1]["title"], "Changed by the owner meanwhile")

    async def test_double_click_runs_once_and_rejected_cannot_be_approved(self):
        rec = await self._propose("update_product", {"product": P1, "seo_title": "Organic Oversized Tee | Grozavu"})
        await agent.approve_action(self.tb, self.shop, rec["id"])
        n = len(self.fake.writes)
        again = await agent.approve_action(self.tb, self.shop, rec["id"])
        self.assertEqual(again["status"], "executed")
        self.assertEqual(len(self.fake.writes), n)

        rec2 = await self._propose("update_product", {"product": P1, "product_type": "Tee"})
        rej = await agent.reject_action(self.shop, rec2["id"])
        self.assertEqual(rej["status"], "rejected")
        after = await agent.approve_action(self.tb, self.shop, rec2["id"])
        self.assertEqual(after["status"], "rejected")
        self.assertEqual(self.fake.products[P1]["productType"], "T-Shirt")

    async def test_expired_proposal(self):
        rec = await self._propose("update_product", {"product": P1, "product_type": "Tee"})
        rec["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        db.save_agent_action(self.shop, rec)
        res = await agent.approve_action(self.tb, self.shop, rec["id"])
        self.assertEqual(res["status"], "expired")
        self.assertEqual(self.fake.writes, [])

    # ── prices ──

    async def test_price_change_rules_apply_and_undo(self):
        with self.assertRaises(AgentError):
            await self.tb.prepare("change_prices", {"product": P1, "price": 60, "compare_at_price": 55})
        with self.assertRaises(AgentError):
            await self.tb.prepare("change_prices", {"product": P1, "variant_ids": ["gid://shopify/ProductVariant/21"], "price": 40})
        with self.assertRaises(AgentError):
            await self.tb.prepare("change_prices", {"product": P1, "price": 51})  # nothing changes
        rec = await self._propose("change_prices", {"product": P1, "price": 45, "compare_at_price": 59})
        self.assertEqual(len(rec["rows"]), 2)
        self.assertTrue(any("24%" in w for w in rec["warnings"]))
        res = await agent.approve_action(self.tb, self.shop, rec["id"])
        self.assertEqual(res["status"], "executed")
        self.assertEqual([v["price"] for v in self.fake.products[P1]["variants"]], ["45.00", "45.00"])
        self.assertEqual(self.fake.products[P1]["variants"][0]["compareAtPrice"], "59.00")
        undone = await agent.undo_action(self.tb, self.shop, rec["id"])
        self.assertEqual(undone["status"], "undone")
        self.assertEqual([v["price"] for v in self.fake.products[P1]["variants"]], ["51.00", "51.00"])
        self.assertIsNone(self.fake.products[P1]["variants"][0]["compareAtPrice"])

    async def test_big_price_drop_warns(self):
        rec = await self._propose("change_prices", {"product": P1, "variant_ids": [V11], "price": 20})
        self.assertEqual(len(rec["rows"]), 1)
        self.assertTrue(any("Schimbare mare" in w for w in rec["warnings"]))

    # ── discounts ──

    async def test_discount_validation(self):
        for bad in ({"code": "MGVIP15", "percent": 10}, {"code": "x", "percent": 10}, {"code": "JARVIS10", "percent": 10},
                    {"code": "BF20", "percent": 20, "amount_eur": 5}, {"code": "BF20"}, {"code": "BF20", "percent": 95},
                    {"code": "BF20", "percent": 20, "starts_at": "2026-12-05", "ends_at": "2026-12-01"}):
            with self.assertRaises(AgentError, msg=str(bad)):
                await self.tb.prepare("create_discount", bad)
        self.assertEqual(self.fake.writes, [])

    async def test_discount_create_and_deactivate(self):
        rec = await self._propose("create_discount", {"code": "blackfriday20", "percent": 20, "ends_at": "2026-11-30",
                                                      "usage_limit": 100, "min_subtotal_eur": 60})
        self.assertEqual(rec["args"]["code"], "BLACKFRIDAY20")
        res = await agent.approve_action(self.tb, self.shop, rec["id"])
        self.assertEqual(res["status"], "executed", res)
        sent = self.fake.last_discount_input
        self.assertEqual(sent["context"], {"all": "ALL"})
        self.assertEqual(sent["customerGets"]["value"], {"percentage": 0.2})
        self.assertTrue(sent["appliesOncePerCustomer"])
        self.assertEqual(sent["usageLimit"], 100)
        self.assertEqual(sent["minimumRequirement"]["subtotal"]["greaterThanOrEqualToSubtotal"], "60.00")
        self.assertTrue(sent["endsAt"].startswith("2026-11-30T22:59:59"))  # 23:59:59 Madrid
        undone = await agent.undo_action(self.tb, self.shop, rec["id"])
        self.assertEqual(undone["status"], "undone")
        self.assertEqual(self.fake.discounts["BLACKFRIDAY20"]["status"], "EXPIRED")

    async def test_discount_falls_back_for_older_api(self):
        self.fake.context_supported = False
        rec = await self._propose("create_discount", {"code": "WINTER10", "amount_eur": 10})
        res = await agent.approve_action(self.tb, self.shop, rec["id"])
        self.assertEqual(res["status"], "executed", res)
        self.assertEqual(self.fake.last_discount_input["customerSelection"], {"all": True})
        self.assertEqual(self.fake.last_discount_input["customerGets"]["value"]["discountAmount"]["amount"], "10.00")

    # ── collections ──

    async def test_collections(self):
        with self.assertRaises(AgentError) as ctx:
            await self.tb.prepare("change_collection", {"collection": C_AUTO, "add_products": [P2]})
        self.assertIn("automată", str(ctx.exception))
        with self.assertRaises(AgentError):
            await self.tb.prepare("change_collection", {"collection": C_MANUAL, "add_products": [P1]})  # already in
        rec = await self._propose("change_collection", {"collection": C_MANUAL, "add_products": [P2, P1]})
        self.assertEqual(rec["args"]["add_products"], [P2])
        res = await agent.approve_action(self.tb, self.shop, rec["id"])
        self.assertEqual(res["status"], "executed", res)
        self.assertIn(C_MANUAL, self.fake.products[P2]["collections"])
        undone = await agent.undo_action(self.tb, self.shop, rec["id"])
        self.assertEqual(undone["status"], "undone")
        self.assertNotIn(C_MANUAL, self.fake.products[P2]["collections"])

    # ── status / publishing ──

    async def test_activate_and_publish_then_undo(self):
        with self.assertRaises(AgentError):
            await self.tb.prepare("set_product_status", {"product": P2, "status": "ARCHIVED"})
        rec = await self._propose("set_product_status", {"product": "magenta-smoke-hoodie", "status": "ACTIVE"})
        warn = " ".join(rec["warnings"])
        self.assertIn("nicio poză", warn)
        self.assertIn("Category metafields", warn)
        res = await agent.approve_action(self.tb, self.shop, rec["id"])
        self.assertEqual(res["status"], "executed", res)
        self.assertEqual(self.fake.products[P2]["status"], "ACTIVE")
        self.assertTrue(self.fake.products[P2]["published"])
        undone = await agent.undo_action(self.tb, self.shop, rec["id"])
        self.assertEqual(undone["status"], "undone")
        self.assertEqual(self.fake.products[P2]["status"], "DRAFT")
        self.assertFalse(self.fake.products[P2]["published"])

    async def test_undo_refused_if_changed_again_after_us(self):
        rec = await self._propose("update_product", {"product": P1, "product_type": "Tee"})
        await agent.approve_action(self.tb, self.shop, rec["id"])
        self.fake.products[P1]["productType"] = "Owner's own change"
        res = await agent.undo_action(self.tb, self.shop, rec["id"])
        self.assertEqual(res["status"], "executed")
        self.assertIn("nu anulez", res["error"])
        self.assertEqual(self.fake.products[P1]["productType"], "Owner's own change")

    async def test_reads(self):
        found = await self.tb.search_products("hoodie")
        self.assertEqual(found["products"][0]["id"], P2)
        detail = await self.tb.get_product("oversized-organic-tee")
        self.assertEqual(detail["category_metafields"]["colors"], ["Black"])
        self.assertTrue(detail["has_faq_block"])
        self.assertNotIn(AEO_START, detail["description_html"])
        cols = await self.tb.list_collections()
        self.assertEqual({c["type"] for c in cols["collections"]}, {"manual", "automatic (rules)"})
        orders = await self.tb.recent_orders(7)
        self.assertNotIn("email", json.dumps(orders))
        with self.assertRaises(AgentError):
            await self.tb.get_product("bad handle with spaces")


class FakeAI:
    """Scripted Gemini: returns the queued responses and records each request body."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.bodies = []
        self.models = []

    async def _gemini_request(self, body, models=None, timeout=None):
        self.bodies.append(json.loads(json.dumps(body)))
        self.models.append(models)
        return self.responses.pop(0), "gemini-3.5-flash-lite"

    async def _call_gemini(self, prompt, **kw):
        assert kw.get("use_web_search") is True
        kw["grounding_out"].update({"web_grounded": True, "sources": [{"title": "Shop X", "url": "https://shop-x.example/hoodie"}]})
        return "Shop X sells a heavyweight hoodie for 120 EUR."


def _call(name, args, cid=None, sig=None):
    part = {"functionCall": {"name": name, "args": args}}
    if cid:
        part["functionCall"]["id"] = cid
    if sig:
        part["thoughtSignature"] = sig
    return {"candidates": [{"content": {"role": "model", "parts": [part]}}]}


def _text(t):
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": t}]}}]}


class AgentLoopTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    async def test_loop_reads_proposes_and_never_writes(self):
        fake = FakeShopify()
        ai = FakeAI([
            _call("search_products", {"query": "tee"}, cid="c1", sig="SIG-1"),
            _call("propose_price_change", {"product": P1, "price": 49}, cid="c2"),
            _text("Am pregătit schimbarea de preț la 49 EUR. Aștept să apeși Aprobă."),
        ])
        tb = AgentToolbox(fake, ai, fake.shop)
        shop = _new_shop()
        res = await agent.run_agent(ai, tb, shop, "Grozavu", "Pune tricoul oversized la 49 EUR", [], "ro", "store ok")
        self.assertEqual(fake.writes, [])
        self.assertEqual(len(res["actions"]), 1)
        act = res["actions"][0]
        self.assertEqual(act["status"], "proposed")
        self.assertTrue(act["can_approve"])
        self.assertEqual(db.get_agent_action(shop, act["id"])["after"][V11]["price"], "49.00")
        # the model's own parts (with the thought signature) are sent back unchanged, ids echoed
        second = ai.bodies[1]["contents"]
        self.assertEqual(second[1]["parts"][0]["thoughtSignature"], "SIG-1")
        self.assertEqual(second[2]["parts"][0]["functionResponse"]["id"], "c1")
        self.assertEqual(ai.models[1], ["gemini-3.5-flash-lite"])  # stays on the same model
        self.assertIn("Aprobă", res["reply"])
        decls = ai.bodies[0]["tools"][0]["functionDeclarations"]
        for d in decls:  # Gemini rejects OBJECT parameters with empty properties
            if "parameters" in d:
                self.assertTrue(d["parameters"]["properties"], d["name"])
        decl = {t["name"] for t in decls}
        self.assertNotIn("delete_product", decl)
        self.assertTrue(all(not n.startswith(("delete", "refund", "archive")) for n in decl))

    async def test_tool_errors_go_back_to_the_model_and_web_search_sources_are_returned(self):
        fake = FakeShopify()
        ai = FakeAI([
            _call("propose_discount_code", {"code": "MGVIP15", "percent": 10}),
            _call("web_search", {"query": "heavyweight hoodie price"}),
            _text("Codul există deja. Concurența: 120 EUR (Shop X)."),
        ])
        tb = AgentToolbox(fake, ai, fake.shop)
        res = await agent.run_agent(ai, tb, _new_shop(), "Grozavu", "fă cod MGVIP15", [], "ro", "")
        err = ai.bodies[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]
        self.assertIn("există deja", err["error"])
        self.assertEqual(res["actions"], [])
        self.assertEqual(res["sources"][0]["url"], "https://shop-x.example/hoodie")
        self.assertTrue(res["web_grounded"])

    async def test_step_limit(self):
        fake = FakeShopify()
        ai = FakeAI([_call("list_discounts", {}) for _ in range(agent.MAX_STEPS)])
        tb = AgentToolbox(fake, ai, fake.shop)
        res = await agent.run_agent(ai, tb, _new_shop(), "Grozavu", "?", [], "ro", "")
        self.assertIn("mulți pași", res["reply"])

    def test_history_starts_with_user_and_alternates(self):
        h = [{"role": "assistant", "content": "hi"}, {"role": "user", "content": "a"}, {"role": "user", "content": "b"},
             {"role": "assistant", "content": "c"}]
        out = agent._history_contents(h)
        self.assertEqual([c["role"] for c in out], ["user", "model"])
        self.assertEqual(out[0]["parts"][0]["text"], "a\nb")


class AgentEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_endpoints_require_auth(self):
        c = TestClient(main.app)
        self.assertEqual(c.post("/api/agent/chat", json={"message": "hi"}).status_code, 401)
        self.assertEqual(c.post("/api/agent/actions/x/approve", json={}).status_code, 401)
        self.assertEqual(c.post("/api/agent/actions/x/reject", json={}).status_code, 401)
        self.assertEqual(c.post("/api/agent/actions/x/undo", json={}).status_code, 401)
        self.assertEqual(c.get("/api/agent/actions").status_code, 401)

    def test_chat_falls_back_to_normal_chat_when_gemini_is_down(self):
        shop = _new_shop()
        db.upsert_shop(shop, "shpat_test_token_123456", "Grozavu")
        client = TestClient(main.app, headers=AUTH_HEADERS)

        async def down(*a, **k):
            raise ai_advisor.GeminiUnavailable("Gemini unavailable (x (429))")

        async def snap(*a, **k):
            return {"connected": True, "shop_name": "Grozavu"}

        async def plain_chat(**k):
            return "Răspuns din chatul obișnuit."

        with patch.object(main.agent_mod, "run_agent", down), patch.object(main, "get_resilient_store_snapshot", snap), \
                patch.object(main.ai, "chat", plain_chat):
            r = client.post("/api/agent/chat", json={"shop": shop, "message": "salut"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertFalse(body["agent"])
        self.assertEqual(body["reply"], "Răspuns din chatul obișnuit.")
        self.assertEqual(body["actions"], [])

    def test_approve_reject_and_journal_over_http(self):
        shop = _new_shop()
        db.upsert_shop(shop, "shpat_test_token_123456", "Grozavu")
        fake = FakeShopify()
        rec = {"id": f"h{time.time_ns()}", "shop": shop, "status": "proposed", "action": "update_product",
               "args": {"product": P1}, "before": {}, "after": {}, "title": "t", "rows": [], "warnings": [],
               "target": {}, "created_at": datetime.now(timezone.utc).isoformat()}
        db.save_agent_action(shop, rec)
        client = TestClient(main.app, headers=AUTH_HEADERS)
        with patch.object(main, "_agent_toolbox", lambda s: AgentToolbox(fake, None, s)):
            r = client.post(f"/api/agent/actions/{rec['id']}/reject", json={"shop": shop})
            self.assertEqual(r.json()["action"]["status"], "rejected")
            missing = client.post("/api/agent/actions/nope/approve", json={"shop": shop})
            self.assertEqual(missing.status_code, 400)
            journal = client.get("/api/agent/actions", params={"shop": shop}).json()["actions"]
        self.assertEqual(journal[0]["id"], rec["id"])
        self.assertNotIn("before", journal[0])
        self.assertEqual(fake.writes, [])

    def test_agent_table_is_purged_with_the_shop(self):
        self.assertIn(("agent_actions", "shop_domain"), db.SHOP_TABLES)


if __name__ == "__main__":
    unittest.main()

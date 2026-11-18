"""
Safety fixes (Nov 19):
- background loops never create discount codes unless the owner opts in;
- the watchdog checks the codes read-only and warns when a code used in emails is missing/inactive;
- live Shopify state for the 30-day reminder is parsed strictly (exact email match);
- one background loop (autopilot cycle + watchdog pass) at 30 minutes on Neon;
- /health shows the interval and switches, never the raw Gemini error text.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
for p in (PROJECT_ROOT, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import main
from shopify_api import ShopifyClient
from starlette.testclient import TestClient

SHOP = "grozavushop.myshopify.com"


class TestReadOnlyDiscountCheck(unittest.IsolatedAsyncioTestCase):
    async def test_check_only_never_creates_or_renames(self):
        client = ShopifyClient(SHOP, "shpat_0123456789abcdef")
        calls = []

        async def fake_graphql(query, variables=None):
            calls.append(query)
            if "codeDiscountNodeByCode" in query:
                code = (variables or {}).get("code")
                if code == "MG10":
                    return {"data": {"codeDiscountNodeByCode": {
                        "id": "gid://shopify/DiscountCodeNode/1",
                        "codeDiscount": {"title": "Old Jarvis MG10", "status": "ACTIVE"}}}}
                if code == "MGVIP15":
                    return {"data": {"codeDiscountNodeByCode": {
                        "id": "gid://shopify/DiscountCodeNode/2",
                        "codeDiscount": {"title": "VIP", "status": "EXPIRED"}}}}
                return {"data": {"codeDiscountNodeByCode": None}}
            raise AssertionError("read-only check must not run mutations")

        client._graphql = fake_graphql
        client._request = AsyncMock(side_effect=AssertionError("read-only check must not call REST"))
        res = await client.ensure_brand_discount_codes(
            [{"code": "MG10", "percent": 10}, {"code": "MGVIP15", "percent": 15}, {"code": "NEWCODE", "percent": 5}],
            create_missing=False,
        )
        self.assertEqual(res["created"], [])
        self.assertEqual(res["renamed"], [])            # no rename either
        self.assertEqual(res["missing"], ["NEWCODE"])
        self.assertEqual(res["inactive"], ["MGVIP15"])
        self.assertFalse(res["ok"])
        self.assertTrue(all("Create" not in q and "Update" not in q for q in calls))

    async def test_check_only_api_error_is_reported_not_created(self):
        client = ShopifyClient(SHOP, "shpat_0123456789abcdef")

        async def failing(query, variables=None):
            if "codeDiscountNodeByCode" in query:
                raise RuntimeError("HTTP 503")
            raise AssertionError("no mutation after a failed check")

        client._graphql = failing
        client._request = AsyncMock(side_effect=AssertionError("no REST fallback in read-only mode"))
        res = await client.ensure_brand_discount_codes([{"code": "MG10", "percent": 10}], create_missing=False)
        self.assertEqual(res["created"], [])
        self.assertTrue(res["errors"])

    async def test_watchdog_default_is_read_only_and_warns_on_missing_code(self):
        from store_watchdog import StoreWatchdogAgent
        agent = StoreWatchdogAgent(brand_domain="maisongrozavu.com", brand_name="Grozavu")
        fake_client = MagicMock()
        fake_client.ensure_brand_discount_codes = AsyncMock(return_value={
            "ok": False, "created": [], "existing": ["MG10"], "renamed": [],
            "missing": ["MGVIP15"], "inactive": [], "errors": [], "codes": {},
        })
        report = await agent.run_deep_scan(
            shop=SHOP, shopify_client=fake_client, products=[], deliverability_checker=None,
            mobile_notifier=None, shop_settings={}, check_storefront=False, check_dns=False,
            auto_fix_discounts=False,
        )
        fake_client.ensure_brand_discount_codes.assert_awaited_once_with(create_missing=False)
        self.assertFalse(report["auto_fixed"] and any("Creat automat" in f["detail"] for f in report["auto_fixed"]))
        self.assertTrue(any(w["code"] == "discount_code_not_active" and "MGVIP15" in w["title"]
                            for w in report["warnings"]))


class TestWinbackLiveState(unittest.IsolatedAsyncioTestCase):
    async def test_parses_state_and_requires_exact_email_match(self):
        client = ShopifyClient(SHOP, "shpat_0123456789abcdef")
        seen = {}

        async def fake_graphql(query, variables=None):
            seen.update(variables or {})
            return {"data": {
                "customers": {"nodes": [
                    {"id": "gid://shopify/Customer/9",
                     "defaultEmailAddress": {"emailAddress": "Ana@Test.es", "marketingState": "SUBSCRIBED"},
                     "lastOrder": {"createdAt": "2026-09-01T10:00:00Z"}}]},
                "order": {"cancelledAt": None, "displayFinancialStatus": "PARTIALLY_REFUNDED"},
            }}

        client._graphql = fake_graphql
        st = await client.get_winback_customer_state("ana@test.es", "123")
        self.assertTrue(st["found"])
        self.assertEqual(st["email_state"], "SUBSCRIBED")
        self.assertEqual(st["last_order_at"], "2026-09-01T10:00:00Z")
        self.assertEqual(st["order_financial_status"], "PARTIALLY_REFUNDED")
        self.assertEqual(seen["orderId"], "gid://shopify/Order/123")
        self.assertEqual(seen["q"], 'email:"ana@test.es"')

        st2 = await client.get_winback_customer_state("other@test.es", "123")  # search hit, wrong person
        self.assertFalse(st2["found"])
        self.assertIsNone(st2["email_state"])

    async def test_graphql_errors_raise_so_caller_fails_closed(self):
        client = ShopifyClient(SHOP, "shpat_0123456789abcdef")
        client._graphql = AsyncMock(return_value={"errors": [{"message": "Access denied for customers"}]})
        with self.assertRaises(Exception):
            await client.get_winback_customer_state("ana@test.es", "123")


class TestOneLoopAndSwitches(unittest.IsolatedAsyncioTestCase):
    async def test_daemon_runs_cycle_then_watchdog_without_creating_discounts(self):
        order = []

        async def fake_cycle(*a, **k):
            order.append("cycle")
            return {"sent": 0, "items": [], "errors": []}

        async def fake_watchdog(*a, **k):
            order.append("watchdog")
            return {}

        async def stop_after_first(seconds):
            if seconds == main.AUTOPILOT_INTERVAL_SECONDS:
                raise asyncio.CancelledError()

        heal = AsyncMock(return_value={})
        with patch.dict(os.environ, {"JARVIS_AUTO_CREATE_DISCOUNTS": ""}), \
             patch.object(main, "run_autopilot_cycle", side_effect=fake_cycle), \
             patch.object(main, "run_watchdog_pass", side_effect=fake_watchdog), \
             patch.object(main, "run_self_heal", heal), \
             patch.object(main.asyncio, "sleep", side_effect=stop_after_first):
            with self.assertRaises(asyncio.CancelledError):
                await main.autopilot_daemon_loop()
        self.assertEqual(order, ["cycle", "watchdog"])
        for call in heal.await_args_list:
            self.assertFalse(call.kwargs.get("force_discounts"), "daemon must not force discount creation")

    def test_switches_default_safe(self):
        with patch.dict(os.environ, {"JARVIS_AUTO_CREATE_DISCOUNTS": "", "JARVIS_WINBACK_ENABLED": ""}):
            self.assertFalse(main.auto_create_discounts_enabled())
            self.assertTrue(main.winback_enabled())
        with patch.dict(os.environ, {"JARVIS_AUTO_CREATE_DISCOUNTS": "1", "JARVIS_WINBACK_ENABLED": "0"}):
            self.assertTrue(main.auto_create_discounts_enabled())
            self.assertFalse(main.winback_enabled())

    def test_health_shows_interval_and_hides_gemini_error_text(self):
        with patch.object(main.ai, "last_gemini_error", "API key xyz invalid: secret details"):
            body = TestClient(main.app).get("/health").json()
        self.assertIn("autopilot_interval_minutes", body)
        self.assertNotIn("gemini_last_error", body)
        self.assertTrue(body["gemini_last_call_failed"])
        self.assertNotIn("secret details", str(body))
        self.assertFalse(body["auto_create_discounts"])
        self.assertEqual(body["watchdog_running"], body["autopilot_running"])


if __name__ == "__main__":
    unittest.main()

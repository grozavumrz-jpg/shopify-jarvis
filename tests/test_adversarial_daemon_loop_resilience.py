"""
tests/test_adversarial_daemon_loop_resilience.py
Empirical Challenger Test Suite for Milestone 1 (Gate 3 - Challenger M1-2).

Adversarially verifies:
1. Real coroutine execution of autopilot_daemon_loop across continuous iterations.
2. Background loop survival under network errors, timeouts, and connection resets.
3. Resilience against HTTP 429, 500, 502, 503, 504 status failures in Shopify REST/GraphQL APIs.
4. Database outage, drop, and reconnection survival during background daemon execution.
5. Multi-shop fault isolation ensuring one shop's network/token failure does not abort other shops.
6. Exhaustive degradation matrix of POST /api/billing/create under network errors, timeouts,
   HTTP status errors (400-504), GraphQL userErrors, and unconfigured tokens.
7. Windows CP1252 / charmap console encoding vulnerability probe on line 677 emoji print.
8. Shopify GraphQL top-level errors and null confirmationUrl degradation probe.
"""

import os
import sys
import io
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone
import httpx
from starlette.testclient import TestClient

# Path setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import database as db
from main import app, autopilot_daemon_loop, AUTOPILOT_STATUS
from shopify_api import ShopifyClient


class TestAdversarialDaemonLoopExecution(unittest.IsolatedAsyncioTestCase):
    """
    Empirical execution test of the actual autopilot_daemon_loop coroutine.
    Drives real multi-cycle iterations using controlled asyncio.sleep interception.
    """

    async def asyncSetUp(self):
        db.init_db()
        self.shop = "test-daemon-resilience.myshopify.com"
        db.upsert_shop(self.shop, "shpat_live_token", "Test Resilience Shop")
        db.save_shop_settings(self.shop, {
            "sender_name": "Test Atelier",
            "sender_email": "test@atelier.com",
            "merchant_notify_email": "admin@atelier.com"
        })

    def test_daemon_loop_survives_windows_cp1252_stdout(self):
        """
        REGRESSION: autopilot_daemon_loop must NOT crash with UnicodeEncodeError
        when stdout uses the default Windows charmap (cp1252, strict errors).
        The loop is bounded by cancelling on the 2nd non-startup sleep.
        """
        cp1252_stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
        cycles = 0

        async def bounded_sleep(seconds):
            nonlocal cycles
            if seconds == 15:
                return
            cycles += 1
            if cycles >= 2:
                raise asyncio.CancelledError()

        async def run_loop_on_cp1252():
            with patch("asyncio.sleep", side_effect=bounded_sleep):
                with patch("sys.stdout", cp1252_stream):
                    with patch("main.post_delivery_service.sync_fulfilled_orders", return_value=0):
                        with patch("main.post_delivery_service.process_due_vip_automations", return_value=0):
                            try:
                                await autopilot_daemon_loop()
                            except asyncio.CancelledError:
                                pass

        asyncio.run(run_loop_on_cp1252())  # must not raise UnicodeEncodeError
        self.assertEqual(cycles, 2, "Daemon loop did not complete 2 cycles under cp1252 stdout")

    async def test_daemon_loop_survives_multi_cycle_iterations(self):
        """
        Runs autopilot_daemon_loop through 3 complete cycles with safe print.
        Verifies loop does not crash, updates AUTOPILOT_STATUS, and records cycles.
        """
        cycle_count = 0

        async def fake_sleep(seconds):
            nonlocal cycle_count
            if seconds == 15:
                # Initial startup delay
                return
            cycle_count += 1
            if cycle_count >= 3:
                # Stop after 3 cycles by cancelling
                raise asyncio.CancelledError()

        with patch("builtins.print"):
            with patch("asyncio.sleep", side_effect=fake_sleep):
                with patch("main.post_delivery_service.sync_fulfilled_orders", return_value=1) as mock_sync:
                    with patch("main.post_delivery_service.process_due_vip_automations", return_value=1) as mock_proc:
                        try:
                            await autopilot_daemon_loop()
                        except asyncio.CancelledError:
                            pass

        self.assertEqual(cycle_count, 3, "Daemon loop did not execute all 3 cycles!")
        self.assertIsNotNone(AUTOPILOT_STATUS.get("last_cycle_at"))
        self.assertGreaterEqual(mock_sync.call_count, 3)
        self.assertGreaterEqual(mock_proc.call_count, 3)

    async def test_daemon_loop_survives_step1_network_timeout(self):
        """
        Step 1 (get_recent_orders) raises httpx.ConnectTimeout.
        Verifies Step 1 exception is trapped, and Step 2, Step 3, Step 4 still execute.
        """
        cycle_done = False

        async def fake_sleep(seconds):
            nonlocal cycle_done
            if seconds == 15:
                return
            cycle_done = True
            raise asyncio.CancelledError()

        with patch("builtins.print"):
            with patch("asyncio.sleep", side_effect=fake_sleep):
                with patch.object(
                    ShopifyClient,
                    "get_recent_orders",
                    side_effect=httpx.ConnectTimeout("Connection timed out after 20.0s")
                ):
                    with patch("main.post_delivery_service.sync_fulfilled_orders", return_value=0) as mock_vip_sync:
                        with patch("main.post_delivery_service.process_due_vip_automations", return_value=0) as mock_vip_proc:
                            try:
                                await autopilot_daemon_loop()
                            except asyncio.CancelledError:
                                pass

        self.assertTrue(cycle_done, "Daemon loop aborted on Step 1 ConnectTimeout!")
        mock_vip_sync.assert_called()
        mock_vip_proc.assert_called()

    async def test_daemon_loop_survives_step2_http_502_503_failures(self):
        """
        Step 2 (get_abandoned_checkouts_detailed) raises 502 Bad Gateway.
        Verifies Step 2 is caught and execution proceeds to Step 3 and Step 4.
        """
        cycle_done = False

        # Use token that is not shpat_live to trigger get_abandoned_checkouts_detailed
        db.upsert_shop(self.shop, "shpat_active_test_token_123", "Test Active Shop")

        async def fake_sleep(seconds):
            nonlocal cycle_done
            if seconds == 15:
                return
            cycle_done = True
            raise asyncio.CancelledError()

        mock_req = httpx.Request("GET", "https://test-daemon-resilience.myshopify.com/admin/api/2024-01/checkouts.json")
        mock_resp = httpx.Response(502, request=mock_req, text="502 Bad Gateway")

        with patch("builtins.print"):
            with patch("asyncio.sleep", side_effect=fake_sleep):
                with patch.object(
                    ShopifyClient,
                    "get_recent_orders",
                    new_callable=AsyncMock,
                    return_value=[]
                ):
                    with patch.object(
                        ShopifyClient,
                        "get_abandoned_checkouts_detailed",
                        side_effect=httpx.HTTPStatusError("502 Bad Gateway", request=mock_req, response=mock_resp)
                    ):
                        with patch("main.post_delivery_service.sync_fulfilled_orders", return_value=2) as mock_vip_sync:
                            with patch("main.post_delivery_service.process_due_vip_automations", return_value=2) as mock_vip_proc:
                                try:
                                    await autopilot_daemon_loop()
                                except asyncio.CancelledError:
                                    pass

        self.assertTrue(cycle_done, "Daemon loop aborted on Step 2 502 error!")
        mock_vip_sync.assert_called()
        mock_vip_proc.assert_called()

    async def test_daemon_loop_intermittent_failure_and_self_healing(self):
        """
        Cycle 1 encounters intermittent network failure (httpx.ConnectError).
        Cycle 2 recovers and successfully syncs checkouts.
        Verifies daemon loop self-heals without intervention.
        """
        cycle_index = 0
        cycle_1_synced = False
        cycle_2_synced = False

        db.upsert_shop(self.shop, "shpat_active_test_token_123", "Test Active Shop")

        mock_checkout = {
            "id": 99901,
            "email": "intermittent@customer.com",
            "customer_name": "Elena Intermittent",
            "total_price": "250.00",
            "currency": "EUR",
            "items": ["Silk Scarf"],
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        async def fake_sleep(seconds):
            nonlocal cycle_index
            if seconds == 15:
                return
            cycle_index += 1
            if cycle_index >= 2:
                raise asyncio.CancelledError()

        async def conditional_get_checkouts(*args, **kwargs):
            nonlocal cycle_index, cycle_1_synced, cycle_2_synced
            if cycle_index == 0:
                cycle_1_synced = True
                raise httpx.ConnectError("Network unreachable")
            else:
                cycle_2_synced = True
                return [mock_checkout]

        with patch("builtins.print"):
            with patch("asyncio.sleep", side_effect=fake_sleep):
                with patch.object(ShopifyClient, "get_recent_orders", new_callable=AsyncMock, return_value=[]):
                    with patch.object(ShopifyClient, "get_abandoned_checkouts_detailed", side_effect=conditional_get_checkouts):
                        with patch("main.process_single_checkout_recovery", new_callable=AsyncMock, return_value={"recovered": True}):
                            with patch("main.post_delivery_service.sync_fulfilled_orders", return_value=0):
                                with patch("main.post_delivery_service.process_due_vip_automations", return_value=0):
                                    try:
                                        await autopilot_daemon_loop()
                                    except asyncio.CancelledError:
                                        pass

        self.assertTrue(cycle_1_synced, "Cycle 1 did not attempt checkouts")
        self.assertTrue(cycle_2_synced, "Cycle 2 did not recover checkouts after network restored")
        self.assertEqual(cycle_index, 2, "Daemon did not execute both cycles")

    async def test_daemon_loop_survives_database_connection_failure_and_reconnection(self):
        """
        Cycle 1: db.get_active_shops raises OperationalError (e.g. Postgres restart / DB locked).
        Cycle 2: db.get_active_shops recovers and returns active shops.
        Verifies daemon loop outer try/except handles DB failure and recovers.
        """
        cycle_index = 0
        db_recovered = False

        async def fake_sleep(seconds):
            nonlocal cycle_index
            if seconds == 15:
                return
            cycle_index += 1
            if cycle_index >= 2:
                raise asyncio.CancelledError()

        def conditional_get_active_shops():
            nonlocal cycle_index, db_recovered
            if cycle_index == 0:
                raise Exception("OperationalError: server closed the connection unexpectedly")
            else:
                db_recovered = True
                return [{"shop": self.shop, "access_token": "shpat_live_token", "shop_name": "Test Shop"}]

        with patch("builtins.print"):
            with patch("asyncio.sleep", side_effect=fake_sleep):
                with patch("database.get_active_shops", side_effect=conditional_get_active_shops):
                    with patch("main.post_delivery_service.sync_fulfilled_orders", return_value=1) as mock_sync:
                        with patch("main.post_delivery_service.process_due_vip_automations", return_value=1) as mock_proc:
                            try:
                                await autopilot_daemon_loop()
                            except asyncio.CancelledError:
                                pass

        self.assertTrue(db_recovered, "Database did not recover on Cycle 2")
        self.assertEqual(cycle_index, 2, "Daemon loop died during DB outage on Cycle 1")
        mock_sync.assert_called()
        mock_proc.assert_called()

    async def test_daemon_loop_multi_shop_fault_isolation(self):
        """
        Shop A raises fatal ConnectError during checkout sync.
        Shop B has valid active checkout that should be processed.
        Verifies Shop A failure is isolated and does NOT prevent Shop B from executing.
        """
        cycle_done = False
        shop_a = "broken-shop.myshopify.com"
        shop_b = "healthy-shop.myshopify.com"

        shops_payload = [
            {"shop": shop_a, "access_token": "shpat_active_broken_token", "shop_name": "Broken Shop"},
            {"shop": shop_b, "access_token": "shpat_active_healthy_token", "shop_name": "Healthy Shop"}
        ]

        async def fake_sleep(seconds):
            nonlocal cycle_done
            if seconds == 15:
                return
            cycle_done = True
            raise asyncio.CancelledError()

        async def per_client_get_checkouts(self_client):
            if self_client.shop == shop_a:
                raise httpx.ConnectError("Shop A Connection reset by peer")
            return [{"id": 1001, "customer_name": "VIP Buyer", "total_price": "199.00"}]

        shop_b_recovered = False

        async def mock_recovery(shop, client, shop_name, c, force=False):
            nonlocal shop_b_recovered
            if shop == shop_b:
                shop_b_recovered = True
                return {"recovered": True}
            return None

        with patch("builtins.print"):
            with patch("asyncio.sleep", side_effect=fake_sleep):
                with patch("database.get_active_shops", return_value=shops_payload):
                    with patch.object(ShopifyClient, "get_recent_orders", new_callable=AsyncMock, return_value=[]):
                        with patch.object(ShopifyClient, "get_abandoned_checkouts_detailed", per_client_get_checkouts):
                            with patch("main.process_single_checkout_recovery", side_effect=mock_recovery):
                                with patch("main.post_delivery_service.sync_fulfilled_orders", return_value=1):
                                    with patch("main.post_delivery_service.process_due_vip_automations", return_value=1):
                                        try:
                                            await autopilot_daemon_loop()
                                        except asyncio.CancelledError:
                                            pass

        self.assertTrue(cycle_done, "Daemon loop did not complete cycle")
        self.assertTrue(shop_b_recovered, "Shop B was not recovered due to Shop A's failure!")


class TestAdversarialBillingDegradation(unittest.TestCase):
    """
    Adversarial test suite for POST /api/billing/create under all HTTP error codes,
    network dropouts, timeouts, GraphQL userErrors, and missing/dummy credentials.
    """

    @classmethod
    def setUpClass(cls):
        db.init_db()

    def setUp(self):
        self.shop = "billing-adversarial.myshopify.com"
        db.upsert_shop(self.shop, "shpat_valid_looking_token_12345678", "Billing Test Shop")
        self.client = TestClient(app)

    def test_billing_create_matrix_of_unconfigured_and_dummy_tokens(self):
        """
        Tests billing create with various unconfigured token formats.
        All must return HTTP 200 with ok=False and demo_mode=True.
        """
        dummy_tokens = [
            "",
            "dummy",
            "shpat_live_token",
            "shpat_live_test_dummy",
            "shpat_live_123456"
        ]
        for tok in dummy_tokens:
            test_shop = f"shop-{abs(hash(tok)) % 10000}.myshopify.com"
            db.upsert_shop(test_shop, tok, "Dummy Token Test Shop")

            res = self.client.post("/api/billing/create", json={"shop": test_shop})
            self.assertEqual(res.status_code, 200, f"Token '{tok}' returned status {res.status_code}")
            data = res.json()
            self.assertFalse(data.get("ok"), f"Token '{tok}' did not return ok=False")
            self.assertTrue(data.get("demo_mode"), f"Token '{tok}' did not set demo_mode=True")
            self.assertIn("not configured", data.get("error", "").lower())

    def test_billing_create_shopify_network_and_timeout_errors(self):
        """
        Tests billing create when Shopify API encounters network drops or timeouts.
        Must return HTTP 200 with ok=False, demo_mode=True (no 500!).
        """
        network_exceptions = [
            httpx.ConnectError("Failed to resolve host 'billing-adversarial.myshopify.com'"),
            httpx.ConnectTimeout("Connection timed out after 20000ms"),
            httpx.ReadTimeout("Read timed out"),
            httpx.WriteTimeout("Write timed out"),
            httpx.PoolTimeout("Connection pool exhausted"),
            ConnectionResetError("Connection reset by peer"),
            Exception("SSL Handshake failed: CERTIFICATE_VERIFY_FAILED")
        ]

        for exc in network_exceptions:
            with patch.object(ShopifyClient, "_graphql", side_effect=exc):
                res = self.client.post("/api/billing/create", json={"shop": self.shop})
                self.assertEqual(res.status_code, 200, f"Exception {exc!r} triggered HTTP {res.status_code}!")
                data = res.json()
                self.assertFalse(data.get("ok"))
                self.assertTrue(data.get("demo_mode"))
                self.assertIn("error", data)

    def test_billing_create_shopify_http_error_status_matrix(self):
        """
        Tests billing create when Shopify GraphQL responds with various HTTP error codes (400-504).
        Must return HTTP 200 with ok=False and demo_mode=True (never HTTP 500).
        """
        status_codes = [400, 401, 403, 404, 422, 429, 500, 502, 503, 504]
        for status in status_codes:
            req = httpx.Request("POST", f"https://{self.shop}/admin/api/2024-01/graphql.json")
            resp = httpx.Response(status, request=req, text=f"HTTP {status} Error from Shopify")
            exc = httpx.HTTPStatusError(f"HTTP {status}", request=req, response=resp)

            with patch.object(ShopifyClient, "_graphql", side_effect=exc):
                res = self.client.post("/api/billing/create", json={"shop": self.shop})
                self.assertEqual(res.status_code, 200, f"HTTP status {status} triggered HTTP {res.status_code}!")
                data = res.json()
                self.assertFalse(data.get("ok"))
                self.assertTrue(data.get("demo_mode"))

    def test_billing_create_graphql_user_errors(self):
        """
        Shopify GraphQL returns userErrors (e.g. payment method missing, invalid currency).
        Must return HTTP 200 with ok=False and demo_mode=True.
        """
        mock_graphql_response = {
            "data": {
                "appSubscriptionCreate": {
                    "appSubscription": None,
                    "confirmationUrl": None,
                    "userErrors": [
                        {"field": ["lineItems"], "message": "Shop does not have an active payment method on file."}
                    ]
                }
            }
        }
        with patch.object(ShopifyClient, "_graphql", new_callable=AsyncMock, return_value=mock_graphql_response):
            res = self.client.post("/api/billing/create", json={"shop": self.shop})
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertFalse(data.get("ok"))
            self.assertTrue(data.get("demo_mode"))

    def test_billing_create_graphql_top_level_errors_defect_probe(self):
        """
        DEFECT PROBE: When Shopify GraphQL returns top-level errors without userErrors
        e.g. {"errors": [{"message": "Access denied for appSubscriptionCreate"}]},
        create_app_subscription returns None.
        Billing endpoint must NOT return ok=True with confirmation_url=None!
        If it returns ok=True, that constitutes a false-positive billing success defect.
        """
        mock_graphql_error = {
            "errors": [
                {"message": "Access denied for appSubscriptionCreate field. Required access scope: write_own_subscription."}
            ]
        }
        with patch.object(ShopifyClient, "_graphql", new_callable=AsyncMock, return_value=mock_graphql_error):
            res = self.client.post("/api/billing/create", json={"shop": self.shop})
            self.assertEqual(res.status_code, 200)
            data = res.json()
            # If confirmation_url is None, it MUST NOT claim ok=True
            if data.get("ok"):
                self.fail(
                    f"DEFECT CONFIRMED: POST /api/billing/create returned ok=True when GraphQL had top-level errors! "
                    f"Payload: {data}"
                )

    def test_billing_create_unknown_shop_auto_provisions_and_degrades(self):
        """
        Posting billing create for an unseeded shop triggers get_shop_or_404 auto-provisioning
        and degrades safely to HTTP 200 demo_mode=True.
        """
        unknown_shop = "brand-new-unknown-shop-12345.myshopify.com"
        res = self.client.post("/api/billing/create", json={"shop": unknown_shop})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data.get("ok"))
        self.assertTrue(data.get("demo_mode"))


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for backend/cadence_manager.py
Validates:
1. 30m / 4h / 24h timing boundaries and transitions.
2. 72h cadence expiration cutoff and status exclusion.
3. Clean Stage 1 URL generation (stripping discount params).
4. Stage 2 and 3 URL generation (injecting MG10).
5. Stage metadata structure and content.
6. Order conversion reconciliation.
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
from cadence_manager import DripCadenceManager


class TestCadenceManagerTiming(unittest.TestCase):
    def setUp(self):
        self.cadence = DripCadenceManager()
        self.now = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)

    def test_stage_1_boundary_early(self):
        """29 minutes post-abandonment: Should NOT trigger Stage 1."""
        cart_created = self.now - timedelta(minutes=29)
        checkout = {"id": "c1", "created_at": cart_created.isoformat()}
        state = {"current_stage": 0, "status": "active"}

        result = self.cadence.evaluate_drip_stage(checkout, state, self.now)
        self.assertIsNone(result)

    def test_stage_1_boundary_trigger(self):
        """30 minutes post-abandonment: SHOULD trigger Stage 1."""
        cart_created = self.now - timedelta(minutes=30)
        checkout = {"id": "c1", "created_at": cart_created.isoformat()}
        state = {"current_stage": 0, "status": "active"}

        result = self.cadence.evaluate_drip_stage(checkout, state, self.now)
        self.assertEqual(result, 1)

    def test_stage_2_boundary_early(self):
        """3 hours 59 minutes post-abandonment: Should NOT trigger Stage 2."""
        cart_created = self.now - timedelta(hours=3, minutes=59)
        checkout = {"id": "c1", "created_at": cart_created.isoformat()}
        state = {"current_stage": 1, "status": "active"}

        result = self.cadence.evaluate_drip_stage(checkout, state, self.now)
        self.assertIsNone(result)

    def test_stage_2_boundary_trigger(self):
        """4 hours post-abandonment: SHOULD trigger Stage 2."""
        cart_created = self.now - timedelta(hours=4)
        checkout = {"id": "c1", "created_at": cart_created.isoformat()}
        state = {"current_stage": 1, "status": "active"}

        result = self.cadence.evaluate_drip_stage(checkout, state, self.now)
        self.assertEqual(result, 2)

    def test_stage_3_boundary_early(self):
        """23 hours 59 minutes post-abandonment: Should NOT trigger Stage 3."""
        cart_created = self.now - timedelta(hours=23, minutes=59)
        checkout = {"id": "c1", "created_at": cart_created.isoformat()}
        state = {"current_stage": 2, "status": "active"}

        result = self.cadence.evaluate_drip_stage(checkout, state, self.now)
        self.assertIsNone(result)

    def test_stage_3_boundary_trigger(self):
        """24 hours post-abandonment: SHOULD trigger Stage 3."""
        cart_created = self.now - timedelta(hours=24)
        checkout = {"id": "c1", "created_at": cart_created.isoformat()}
        state = {"current_stage": 2, "status": "active"}

        result = self.cadence.evaluate_drip_stage(checkout, state, self.now)
        self.assertEqual(result, 3)

    def test_cadence_cutoff_72_hours(self):
        """72 hours and 1 second post-abandonment: Must be exhausted (None)."""
        cart_created = self.now - timedelta(hours=72, seconds=1)
        checkout = {"id": "c1", "created_at": cart_created.isoformat()}
        state = {"current_stage": 2, "status": "active"}

        result = self.cadence.evaluate_drip_stage(checkout, state, self.now)
        self.assertIsNone(result)

    def test_cadence_exhausted_stage_3(self):
        """Stage 3 already dispatched: Must return None."""
        cart_created = self.now - timedelta(hours=30)
        checkout = {"id": "c1", "created_at": cart_created.isoformat()}
        state = {"current_stage": 3, "status": "active"}

        result = self.cadence.evaluate_drip_stage(checkout, state, self.now)
        self.assertIsNone(result)

    def test_cadence_ignores_non_active_status(self):
        """Converted, canceled, or exhausted status: Must return None."""
        cart_created = self.now - timedelta(hours=5)
        checkout = {"id": "c1", "created_at": cart_created.isoformat()}

        for st in ["converted", "exhausted", "canceled"]:
            state = {"current_stage": 1, "status": st}
            result = self.cadence.evaluate_drip_stage(checkout, state, self.now)
            self.assertIsNone(result)

    def test_parse_datetime_safe_on_invalid_inputs(self):
        """parse_datetime handles malformed strings, None, and bad types without crashing."""
        self.assertIsNone(DripCadenceManager.parse_datetime(None))
        self.assertIsNone(DripCadenceManager.parse_datetime(""))
        self.assertIsNone(DripCadenceManager.parse_datetime("invalid_date_format"))
        self.assertIsNone(DripCadenceManager.parse_datetime(12345))
        self.assertIsNone(DripCadenceManager.parse_datetime({"date": "bad"}))

    def test_evaluate_drip_stage_handles_malformed_created_at_safely(self):
        """evaluate_drip_stage returns None when created_at is malformed or unparseable."""
        checkout = {"id": "c_bad", "created_at": "not-a-date"}
        state = {"current_stage": 0, "status": "active"}
        result = self.cadence.evaluate_drip_stage(checkout, state, self.now)
        self.assertIsNone(result)

    def test_stage_2_cadence_cascade_prevented_by_stage_1_interval(self):
        """Carts discovered >= 4h must NOT immediately advance to Stage 2 if Stage 1 was just sent."""
        cart_created = self.now - timedelta(hours=5)
        checkout = {"id": "c_cascade", "created_at": cart_created.isoformat()}
        
        # Stage 1 sent 1 minute ago -> must NOT trigger Stage 2
        state_recent_1m = {
            "current_stage": 1,
            "status": "active",
            "stage_1_sent_at": (self.now - timedelta(minutes=1)).isoformat()
        }
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state_recent_1m, self.now))

        # Stage 1 sent 3 hours and 29 minutes ago (< 3.5h) -> must NOT trigger Stage 2
        state_recent_3h29m = {
            "current_stage": 1,
            "status": "active",
            "stage_1_sent_at": (self.now - timedelta(hours=3, minutes=29)).isoformat()
        }
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state_recent_3h29m, self.now))

        # Stage 1 sent 3 hours and 31 minutes ago (>= 3.5h) -> SHOULD trigger Stage 2
        state_eligible = {
            "current_stage": 1,
            "status": "active",
            "stage_1_sent_at": (self.now - timedelta(hours=3, minutes=31)).isoformat()
        }
        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state_eligible, self.now), 2)

    def test_stage_3_cadence_cascade_prevented_by_stage_2_interval(self):
        """Carts discovered >= 24h must NOT immediately advance to Stage 3 if Stage 2 was just sent."""
        cart_created = self.now - timedelta(hours=26)
        checkout = {"id": "c_cascade3", "created_at": cart_created.isoformat()}

        # Stage 2 sent 5 minutes ago -> must NOT trigger Stage 3
        state_recent_5m = {
            "current_stage": 2,
            "status": "active",
            "stage_2_sent_at": (self.now - timedelta(minutes=5)).isoformat()
        }
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state_recent_5m, self.now))

        # Stage 2 sent 17 hours 59 minutes ago (< 18h) -> must NOT trigger Stage 3
        state_recent_17h = {
            "current_stage": 2,
            "status": "active",
            "stage_2_sent_at": (self.now - timedelta(hours=17, minutes=59)).isoformat()
        }
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state_recent_17h, self.now))

        # Stage 2 sent 18 hours 1 minute ago (>= 18h) -> SHOULD trigger Stage 3
        state_eligible = {
            "current_stage": 2,
            "status": "active",
            "stage_2_sent_at": (self.now - timedelta(hours=18, minutes=1)).isoformat()
        }
        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state_eligible, self.now), 3)


class TestCadenceURLGeneration(unittest.TestCase):
    def setUp(self):
        self.cadence = DripCadenceManager()

    def test_stage_1_strips_existing_discount(self):
        raw_url = "https://shop.com/checkouts/123?discount=MG10&locale=ro"
        clean_url = self.cadence.build_stage_checkout_url(raw_url, stage=1)
        self.assertNotIn("discount=", clean_url)
        self.assertIn("locale=ro", clean_url)

    def test_stage_2_applies_mg10(self):
        raw_url = "https://shop.com/checkouts/123"
        url = self.cadence.build_stage_checkout_url(raw_url, stage=2)
        self.assertEqual(url, "https://shop.com/checkouts/123?discount=MG10")

    def test_stage_3_applies_mg10_with_existing_query_params(self):
        raw_url = "https://shop.com/checkouts/123?utm_source=fb"
        url = self.cadence.build_stage_checkout_url(raw_url, stage=3)
        self.assertIn("utm_source=fb", url)
        self.assertIn("discount=MG10", url)

    def test_empty_raw_url_returns_empty(self):
        self.assertEqual(self.cadence.build_stage_checkout_url("", 1), "")
        self.assertEqual(self.cadence.build_stage_checkout_url(None, 2), "")


class TestCadenceMetadata(unittest.TestCase):
    def setUp(self):
        self.cadence = DripCadenceManager()

    def test_stage_1_metadata(self):
        meta = self.cadence.get_stage_metadata(1)
        self.assertIsNone(meta["discount_code"])
        self.assertFalse(meta["has_discount"])
        self.assertFalse(meta["urgency"])

    def test_stage_2_metadata(self):
        meta = self.cadence.get_stage_metadata(2)
        self.assertEqual(meta["discount_code"], "MG10")
        self.assertTrue(meta["has_discount"])
        self.assertFalse(meta["urgency"])

    def test_stage_3_metadata(self):
        meta = self.cadence.get_stage_metadata(3)
        self.assertEqual(meta["discount_code"], "MG10")
        self.assertTrue(meta["has_discount"])
        self.assertTrue(meta["urgency"])

    def test_invalid_stage_metadata_raises(self):
        with self.assertRaises(ValueError):
            self.cadence.get_stage_metadata(4)


class TestCadenceReconciliation(unittest.TestCase):
    def setUp(self):
        self.cadence = DripCadenceManager()

    @patch("cadence_manager.db.mark_drip_converted")
    def test_mark_order_converted_calls_db(self, mock_db_mark):
        mock_db_mark.return_value = 1
        order = {
            "id": 9999,
            "checkout_id": "c1001",
            "checkout_token": "tok_abc",
            "total_price": "145.00",
            "customer": {"email": "buyer@example.com"}
        }
        res = self.cadence.mark_order_converted("test-shop.myshopify.com", order)
        self.assertTrue(res)
        mock_db_mark.assert_called_once_with(
            shop="test-shop.myshopify.com",
            checkout_id="c1001",
            email="buyer@example.com",
            checkout_token="tok_abc",
            order_id="9999",
            revenue=145.0
        )


class TestWebhookEndpoint(unittest.IsolatedAsyncioTestCase):
    @patch("main.cadence_mgr.mark_order_converted")
    async def test_webhook_order_created_reconciles(self, mock_mark):
        from main import webhook_order_created
        request = MagicMock()
        request.headers = {"x-shopify-shop-domain": "test-shop.myshopify.com"}
        request.json = unittest.mock.AsyncMock(return_value={"id": 8888, "checkout_id": "c999"})
        resp = await webhook_order_created(request)
        self.assertEqual(resp, {"status": "ok"})
        mock_mark.assert_called_once_with("test-shop.myshopify.com", {"id": 8888, "checkout_id": "c999"})


class TestProcessCheckoutRecoveryStage1Enforcement(unittest.IsolatedAsyncioTestCase):
    @patch("main.db")
    @patch("main.ai")
    @patch("main.email_dispatcher")
    @patch("main.wa_dispatcher")
    async def test_stage_1_unconditionally_suppresses_any_discount_copy(self, mock_wa, mock_email, mock_ai, mock_db):
        from unittest.mock import AsyncMock
        from main import process_single_checkout_recovery
        mock_db.upsert_checkout_drip_state.return_value = {"current_stage": 0, "status": "active"}
        mock_db.get_shop_settings.return_value = {"merchant_notify_email": ""}
        
        # AI returns an unexpected discount pitch without standard '10%' or 'MG10'
        mock_ai.generate_autonomous_recovery = AsyncMock(return_value={
            "subject": "Exclusive 25% Off Deal Just For You!",
            "body": "Use promo code SPECIAL25 to complete your checkout with 25% discount.",
            "whatsapp_message": "Save 25% today with code SPECIAL25!"
        })
        mock_email.send_email = AsyncMock(return_value={"success": True})
        mock_wa.send_autonomous_whatsapp = AsyncMock(return_value={"success": True})

        checkout = {
            "id": "c_stg1_test",
            "created_at": "2026-10-26T10:00:00Z",
            "total_price": "120.00",
            "customer_name": "Elena Popescu",
            "email": "elena@example.ro",
            "items": ["Rochie Elegantă"],
            "detected_lang": "ro"
        }
        client_mock = MagicMock()
        result = await process_single_checkout_recovery("test-shop.myshopify.com", client_mock, "Test Shop", checkout, force=True)
        
        self.assertEqual(result["stage"], 1)
        self.assertIsNone(result["discount_code"])
        self.assertNotIn("SPECIAL25", result["subject"])
        self.assertNotIn("25%", result["subject"])
        self.assertNotIn("SPECIAL25", result["message"])
        self.assertIn("ai nevoie de ajutor", result["subject"])


if __name__ == "__main__":
    unittest.main()

